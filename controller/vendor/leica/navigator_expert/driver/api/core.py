"""
Core dispatch engine.
=====================
The command dispatch backbone: all commands (set, move, acquire,
select) route through ``confirm_and_fire``.

Two-layer architecture:

    **Fire block** (inner, ``_fire_block``) — steps 1-4:
        pre_check → setup → fire → error_check.
        Retries on transient errors internally, up to ``max_retries``.
        Returns success or failure.

    **Confirm wrapper** (outer, ``confirm_and_fire``) — calls the fire
        block, then runs ``confirm_fn`` to verify the result. If
        confirmation fails, the wrapper can run corrective actions
        (idle-check + re-fire) and re-attempt. This is a flat loop,
        not recursion.

Two ceilings, both explicit:
    - ``max_retries`` controls transient error retries inside the fire block.
    - ``max_confirm_attempts`` controls how many times the confirm wrapper
      can re-run the cycle.

The backbone is dumb — it owns pipeline order, retry ceilings, and
timing. It does not know about zoom, objectives, stages, or Z-drives.
It does not poll for hardware state. It calls zero-arg callables and
acts on their result dicts. The only sleeping it does is backoff delay
between transient error retries (configurable via ``retry_backoff``
and ``retry_escalate``).

``_fire_with_receipt`` is the transport helper for UpdateAwaitReceipt
delivery. ``_await_echo_result`` polls the echo model after transport
delivery, waiting for LAS X to finish processing before the error
check reads the echo fields.

Import restrictions: only ``errors``, ``utils``, and stdlib. Nothing from
``commands``, ``profiles``, ``prechecks``, or ``confirmations``.
"""

import logging
import time

from .errors import _default_error_check
from .utils import _make_timing, _make_log_entry, RECEIPT_TIMEOUT

log = logging.getLogger(__name__)


# =============================================================================
# Transport helper
# =============================================================================

def _fire_with_receipt(api_obj, receipt_timeout=None, max_attempts=3,
                       retry_delay=0.5):
    """Dispatch command via UpdateAwaitReceipt with transport retry.

    Args:
        api_obj: API object (e.g. client.PyApiSetZoomByJobName).
        receipt_timeout: Seconds for UpdateAwaitReceipt. None uses
            the module-level RECEIPT_TIMEOUT default.
        max_attempts: Total transport delivery attempts.
        retry_delay: Seconds between transport retries.

    Returns:
        True if delivered, False if transport failed after all attempts.
    """
    if receipt_timeout is None:
        receipt_timeout = RECEIPT_TIMEOUT
    for attempt in range(max_attempts):
        receipt = api_obj.UpdateAwaitReceipt(receipt_timeout)
        if receipt:
            return True
        log.warning("Transport failure (attempt %d/%d)", attempt + 1,
                    max_attempts)
        if attempt < max_attempts - 1:
            time.sleep(retry_delay)
    return False


# =============================================================================
# Echo settlement poll
# =============================================================================

def _await_echo_result(client, timeout=1.0, poll_interval=0.01):
    """Poll echo model until LAS X finishes processing.

    After UpdateAwaitReceipt confirms transport delivery, LAS X still
    needs time to process the command and populate the echo fields
    (HasError, Error, Result). This function polls until the echo
    indicates processing is complete, or timeout.

    Settlement condition: ``Result != 0 (NotDefined)`` OR
    ``HasError is True``. Both are checked because LAS X may set
    HasError without changing Result from NotDefined.

    Args:
        client: LAS X API client.
        timeout: Max seconds to wait for echo settlement.
        poll_interval: Seconds between polls.

    Returns:
        True if the echo settled (ready for error check),
        False if timeout expired (echo still in cleared state).
    """
    deadline = time.perf_counter() + timeout

    while True:
        try:
            result_code = int(client.PyApiCommandEcho.Model.Result)
        except Exception:
            result_code = 0  # Unreadable → treat as not settled

        try:
            has_error = bool(client.PyApiCommandEcho.Model.HasError)
        except Exception:
            has_error = False  # Unreadable → treat as not settled

        if result_code != 0 or has_error:
            return True

        if time.perf_counter() >= deadline:
            return False

        time.sleep(poll_interval)


# =============================================================================
# Fire block — steps 1-4 with transient retry
# =============================================================================

def _fire_block(client, api_obj, description, *,
                setup_fn=None,
                pre_check_fn=None,
                error_check_fn=None,
                max_retries=3,
                retry_backoff=None,
                retry_escalate=False,
                skip_echo=False,
                receipt_timeout=None,
                fire_async=False):
    """Execute the four-step fire pipeline with transient retry.

    Steps:
        1. Pre-check — call ``pre_check_fn()`` (zero-arg, returns result dict).
        2. Setup — call ``setup_fn(api_obj.Model)`` to write parameters.
        3. Fire — clear echo, ``_fire_with_receipt(api_obj)``.
        4. Error check — call ``error_check_fn()`` (zero-arg, returns result dict).

    Steps 1-4 repeat on transient API errors, up to ``max_retries`` + 1
    total attempts. Pre-check functions own their own polling internally.
    The fire block never knows what it is checking.

    Args:
        client: LAS X API client.
        api_obj: Resolved API object (e.g. client.PyApiSetZoomByJobName).
        description: Human-readable label for logging.
        setup_fn: Callable(model) that writes parameters to api_obj.Model.
            None to skip setup.
        pre_check_fn: Zero-arg callable → result dict with "success" and
            "logs". None to skip step 1.
        error_check_fn: Zero-arg callable → result dict with "success",
            "error", "transient", and "logs". None defaults to
            ``_default_error_check``.
        max_retries: Max retries after the first attempt. Total attempts =
            max_retries + 1.
        retry_backoff: Base delay in seconds between transient error retries.
            None for immediate retry. First retry is always immediate;
            subsequent retries use the backoff delay.
        retry_escalate: If True, double the delay after each retry
            (exponential backoff: 0s, base, 2×base, 4×base, ...).
            If False, use a fixed delay. Ignored when retry_backoff is None.

    Returns:
        {
            "success": bool,
            "message": str,
            "timing": {pre_check_s, setup_s, fire_s, check_s},
            "attempts": int,
            "logs": [...],
        }
    """
    t_pre_check = 0.0
    t_setup = 0.0
    t_fire = 0.0
    t_check = 0.0
    attempts = 0
    all_logs = []

    for attempt in range(max_retries + 1):
        attempts = attempt + 1

        # --- Step 1: Pre-check ---
        if pre_check_fn is not None:
            t0 = time.perf_counter()
            result = pre_check_fn()
            t_pre_check += time.perf_counter() - t0
            all_logs.extend(result.get("logs", []))

            if not result["success"]:
                return {
                    "success": False,
                    "message": f"{description} | Pre-check failed",
                    "timing": {"pre_check_s": t_pre_check, "setup_s": t_setup,
                               "fire_s": t_fire, "check_s": t_check},
                    "attempts": attempts,
                    "logs": all_logs,
                }

        # --- Step 2: Setup ---
        t0 = time.perf_counter()
        try:
            if setup_fn is not None:
                setup_fn(api_obj.Model)
        except Exception as e:
            t_setup += time.perf_counter() - t0
            msg = f"{description} | Setup exception: {e}"
            log.error(msg)
            all_logs.append(_make_log_entry("error", msg))
            return {
                "success": False,
                "message": msg,
                "timing": {"pre_check_s": t_pre_check, "setup_s": t_setup,
                           "fire_s": t_fire, "check_s": t_check},
                "attempts": attempts,
                "logs": all_logs,
            }
        t_setup += time.perf_counter() - t0

        # --- Step 3: Fire + await echo ---
        t0 = time.perf_counter()
        try:
            client.PyApiCommandEcho.Model.HasError = False
            client.PyApiCommandEcho.Model.Error = ""
            try:
                client.PyApiCommandEcho.Model.Result = 0  # NotDefined
            except Exception:
                pass  # Some API versions may not allow Result assignment
            if fire_async:
                api_obj.UpdateAsync()
                delivered = True
            else:
                delivered = _fire_with_receipt(api_obj, receipt_timeout=receipt_timeout)
            if delivered and not skip_echo and not fire_async:
                _await_echo_result(client)
        except Exception as e:
            t_fire += time.perf_counter() - t0
            msg = f"{description} | Fire exception: {e}"
            log.error(msg)
            all_logs.append(_make_log_entry("error", msg))
            return {
                "success": False,
                "message": msg,
                "timing": {"pre_check_s": t_pre_check, "setup_s": t_setup,
                           "fire_s": t_fire, "check_s": t_check},
                "attempts": attempts,
                "logs": all_logs,
            }
        t_fire += time.perf_counter() - t0

        if not delivered:
            msg = (f"{description} | Transport failure: "
                   f"UpdateAwaitReceipt returned False after retries")
            log.error(msg)
            all_logs.append(_make_log_entry("error", msg))
            return {
                "success": False,
                "message": msg,
                "timing": {"pre_check_s": t_pre_check, "setup_s": t_setup,
                           "fire_s": t_fire, "check_s": t_check},
                "attempts": attempts,
                "logs": all_logs,
            }

        # --- Step 4: Error check ---
        t0 = time.perf_counter()
        if error_check_fn is not None:
            err_result = error_check_fn()
        else:
            err_result = {"success": True, "logs": []}
        t_check += time.perf_counter() - t0
        all_logs.extend(err_result.get("logs", []))

        if err_result["success"]:
            # No API error — fire block succeeded
            break

        error_msg = err_result.get("error", "")
        transient = err_result.get("transient", False)

        if transient and attempt < max_retries:
            # Backoff: first retry is immediate, then base × 2^(attempt-1)
            if retry_backoff is not None and attempt > 0:
                delay = retry_backoff * (2 ** (attempt - 1)) if retry_escalate else retry_backoff
                log.warning("%s | Transient error (attempt %d/%d), "
                            "retrying in %.1fs: %s",
                            description, attempts, max_retries + 1,
                            delay, error_msg)
                time.sleep(delay)
            else:
                log.warning("%s | Transient error (attempt %d/%d): %s",
                            description, attempts, max_retries + 1,
                            error_msg)
            continue

        # Permanent error, or transient but out of retries
        if transient:
            log.error("%s | Transient error exhausted retries: %s",
                      description, error_msg)
        else:
            log.error("%s | Permanent error: %s", description, error_msg)

        return {
            "success": False,
            "message": f"{description} | API Error: {error_msg}",
            "timing": {"pre_check_s": t_pre_check, "setup_s": t_setup,
                       "fire_s": t_fire, "check_s": t_check},
            "attempts": attempts,
            "logs": all_logs,
        }

    # Fire block succeeded
    return {
        "success": True,
        "message": description,
        "timing": {"pre_check_s": t_pre_check, "setup_s": t_setup,
                   "fire_s": t_fire, "check_s": t_check},
        "attempts": attempts,
        "logs": all_logs,
    }


# =============================================================================
# Confirm wrapper — outer layer with correction loop
# =============================================================================

def confirm_and_fire(client, api_obj, description, *,
                     setup_fn=None,
                     pre_check_fn=None,
                     error_check_fn=None,
                     confirm_fn=None,
                     correct_fn=None,
                     max_retries=3,
                     max_confirm_attempts=3,
                     retry_backoff=None,
                     retry_escalate=False,
                     skip_echo=False,
                     receipt_timeout=None,
                     fire_async=False,
                     success_on_unconfirmed=False):
    """Fire a command and optionally confirm the result, with correction.

    This is the single entry point through which all commands are
    dispatched. It calls ``_fire_block`` to execute steps 1-4, then
    runs ``confirm_fn`` to verify the result. If confirmation fails,
    the wrapper can run corrective actions and re-attempt.

    Correction strategy (when confirm_fn returns failure):
        1. If ``correct_fn`` is provided, call it.
        2. Otherwise, run built-in idle correction (re-run pre_check_fn
           to wait for scanner idle, then re-fire).
        3. Re-confirm after correction.
        4. All correction attempts count against ``max_confirm_attempts``.

    Args:
        client: LAS X API client.
        api_obj: Resolved API object.
        description: Human-readable label for logging.
        setup_fn: Callable(model) that writes parameters to api_obj.Model.
        pre_check_fn: Zero-arg callable → result dict. None to skip.
        error_check_fn: Zero-arg callable → error result dict. None
            defaults to ``_default_error_check``.
        confirm_fn: Zero-arg callable → result dict. None to skip
            confirmation entirely.
        correct_fn: Zero-arg callable → result dict. None uses built-in
            idle correction. Stubbed for future custom correction.
        max_retries: Transient error retries inside the fire block.
        max_confirm_attempts: How many times the confirm wrapper can
            re-run the fire-then-confirm cycle.
        retry_backoff: Base delay in seconds between transient error
            retries. None for immediate retry. Passed to ``_fire_block``.
        retry_escalate: If True, use exponential backoff (delay doubles
            each retry). Passed to ``_fire_block``.
        success_on_unconfirmed: If True, return success=True when all
            confirmation attempts are exhausted. Default False.

    Returns:
        {
            "success": bool,
            "confirmed": bool | None,
            "message": str,
            "timing": dict,
            "logs": [...],
        }

        ``confirmed`` is True if confirm_fn succeeded, False if it
        failed, None if confirm_fn was not provided or the command
        failed before reaching confirmation.
    """
    t_wall_start = time.perf_counter()
    t_confirm_total = 0.0
    all_logs = []
    total_attempts = 0
    confirm_attempts = 0

    # --- Fire block (first attempt) ---
    fb = _fire_block(
        client, api_obj, description,
        setup_fn=setup_fn,
        pre_check_fn=pre_check_fn,
        error_check_fn=error_check_fn,
        max_retries=max_retries,
        retry_backoff=retry_backoff,
        retry_escalate=retry_escalate,
        skip_echo=skip_echo,
        receipt_timeout=receipt_timeout,
        fire_async=fire_async,
    )
    all_logs.extend(fb["logs"])
    total_attempts += fb["attempts"]
    fb_timing = fb["timing"]

    if not fb["success"]:
        return {
            "success": False,
            "confirmed": None,
            "message": fb["message"],
            "timing": _make_timing(
                pre_check_s=fb_timing["pre_check_s"],
                setup_s=fb_timing["setup_s"],
                fire_s=fb_timing["fire_s"],
                check_s=fb_timing["check_s"],
                total_s=time.perf_counter() - t_wall_start,
                attempts=total_attempts,
                confirm_attempts=0,
                method="async",
            ),
            "logs": all_logs,
        }

    # --- No confirm_fn: step 5 skipped ---
    if confirm_fn is None:
        log.info("%s | OK (%.3fs) attempts=%d",
                 description, time.perf_counter() - t_wall_start,
                 total_attempts)
        return {
            "success": True,
            "confirmed": None,
            "message": description,
            "timing": _make_timing(
                pre_check_s=fb_timing["pre_check_s"],
                setup_s=fb_timing["setup_s"],
                fire_s=fb_timing["fire_s"],
                check_s=fb_timing["check_s"],
                total_s=time.perf_counter() - t_wall_start,
                attempts=total_attempts,
                confirm_attempts=0,
                method="async",
            ),
            "logs": all_logs,
        }

    # --- Confirm wrapper loop ---
    # Accumulate timing from all fire block calls across confirm attempts
    acc_pre = fb_timing["pre_check_s"]
    acc_setup = fb_timing["setup_s"]
    acc_fire = fb_timing["fire_s"]
    acc_check = fb_timing["check_s"]

    for ca in range(max_confirm_attempts):
        confirm_attempts = ca + 1

        # Run confirm_fn
        t0 = time.perf_counter()
        try:
            conf_result = confirm_fn()
        except Exception as e:
            msg = f"{description} | Confirm exception: {e}"
            log.warning(msg)
            all_logs.append(_make_log_entry("warning", msg))
            conf_result = {"success": False, "logs": []}
        t_confirm_total += time.perf_counter() - t0
        all_logs.extend(conf_result.get("logs", []))

        if conf_result["success"]:
            log.info("%s | OK (%.3fs) attempts=%d confirm_attempts=%d",
                     description, time.perf_counter() - t_wall_start,
                     total_attempts, confirm_attempts)
            return {
                "success": True,
                "confirmed": True,
                "message": description,
                "timing": _make_timing(
                    pre_check_s=acc_pre,
                    setup_s=acc_setup,
                    fire_s=acc_fire,
                    check_s=acc_check,
                    confirm_s=t_confirm_total,
                    total_s=time.perf_counter() - t_wall_start,
                    attempts=total_attempts,
                    confirm_attempts=confirm_attempts,
                    method="async",
                ),
                "logs": all_logs,
            }

        # Confirmation failed — attempt correction if not last attempt
        if ca < max_confirm_attempts - 1:
            if correct_fn is not None:
                # Custom correction — result success is not checked because
                # the re-fire + re-confirm cycle determines the outcome.
                # Correction time is tracked in confirm_s (part of the
                # confirm attempt cycle).
                t0 = time.perf_counter()
                try:
                    corr_result = correct_fn()
                except Exception as e:
                    msg = f"{description} | Correct exception: {e}"
                    log.warning(msg)
                    all_logs.append(_make_log_entry("warning", msg))
                    corr_result = {"success": False, "logs": []}
                t_confirm_total += time.perf_counter() - t0
                all_logs.extend(corr_result.get("logs", []))
            else:
                # Built-in idle correction: wait for idle, then re-fire
                if pre_check_fn is not None:
                    t0 = time.perf_counter()
                    idle_result = pre_check_fn()
                    acc_pre += time.perf_counter() - t0
                    all_logs.extend(idle_result.get("logs", []))

            # Re-fire after correction
            log.info("%s | Confirm failed, re-firing (attempt %d/%d)",
                     description, confirm_attempts + 1, max_confirm_attempts)
            fb = _fire_block(
                client, api_obj, description,
                setup_fn=setup_fn,
                pre_check_fn=None,  # Already waited for idle above
                error_check_fn=error_check_fn,
                max_retries=max_retries,
                retry_backoff=retry_backoff,
                retry_escalate=retry_escalate,
                skip_echo=skip_echo,
                receipt_timeout=receipt_timeout,
                fire_async=fire_async,
            )
            all_logs.extend(fb["logs"])
            total_attempts += fb["attempts"]
            acc_setup += fb["timing"]["setup_s"]
            acc_fire += fb["timing"]["fire_s"]
            acc_check += fb["timing"]["check_s"]

            if not fb["success"]:
                # Re-fire failed — give up
                return {
                    "success": False,
                    "confirmed": False,
                    "message": fb["message"],
                    "timing": _make_timing(
                        pre_check_s=acc_pre,
                        setup_s=acc_setup,
                        fire_s=acc_fire,
                        check_s=acc_check,
                        confirm_s=t_confirm_total,
                        total_s=time.perf_counter() - t_wall_start,
                        attempts=total_attempts,
                        confirm_attempts=confirm_attempts,
                        method="async",
                    ),
                    "logs": all_logs,
                }

    # All confirm attempts exhausted
    log.warning("%s | UNCONFIRMED after %d confirm attempts (%.3fs)",
                description, confirm_attempts,
                time.perf_counter() - t_wall_start)
    return {
        "success": success_on_unconfirmed,
        "confirmed": False,
        "message": f"{description} (readback unconfirmed)",
        "timing": _make_timing(
            pre_check_s=acc_pre,
            setup_s=acc_setup,
            fire_s=acc_fire,
            check_s=acc_check,
            confirm_s=t_confirm_total,
            total_s=time.perf_counter() - t_wall_start,
            attempts=total_attempts,
            confirm_attempts=confirm_attempts,
            method="async",
        ),
        "logs": all_logs,
    }

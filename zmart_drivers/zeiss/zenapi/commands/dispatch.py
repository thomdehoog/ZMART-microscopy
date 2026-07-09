"""
Core dispatch engine (gRPC).
============================
All commands (move, objective, snap, run-experiment) route through
``confirm_and_fire``. This is the ZEN adaptation of the Leica dispatch backbone,
kept deliberately dumb: it owns pipeline order, retry ceilings, and timing, and
knows nothing about stages, focus, objectives, or acquisitions.

Two layers:

    **Fire block** (inner, ``_fire_block``): optional pre-check, then ``fire_fn``.
        Retries on transient errors up to ``max_retries``. Returns success/failure
        plus the RPC's return value.

    **Confirm wrapper** (outer, ``confirm_and_fire``): calls the fire block, then
        ``confirm_fn`` to verify. On unconfirmed it can re-fire (per profile) and
        re-confirm, a flat loop bounded by ``max_confirm_attempts``.

The single ZEN adaptation vs Leica: there is no ``setup_fn`` / ``api_obj`` /
echo-model / transport machinery. A command is one **``fire_fn``** -- a zero-arg
sync callable that bridges one coroutine (``client.submit(...)``) to completion
and returns the result shape ``{"success","error","transient","value","logs"}``.
Fire and error-check are the same event (the RPC returns, or raises a GRPCError
the fire_fn has already classified).

Import restrictions: only runtime utilities and stdlib. Nothing from command
wrappers, profiles, or confirmations.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import logging
import time

from ..utils import _make_log_entry, _make_timing

log = logging.getLogger(__name__)


def _confirmation_detail(result):
    """Compact non-log readback details from a confirmation result."""
    if not isinstance(result, dict):
        return ""
    details = {k: v for k, v in result.items() if k not in {"success", "logs"}}
    return f"; last_confirmation={details!r}" if details else ""


def _fire_block(
    client,
    description,
    *,
    fire_fn,
    pre_check_fn=None,
    max_retries=3,
    retry_backoff=None,
    retry_escalate=False,
):
    """Execute pre-check -> fire, with transient retry.

    ``fire_fn`` is a zero-arg callable returning
    ``{"success", "error", "transient", "value", "logs"}``. It owns the RPC and
    its error classification; the fire block only reads ``success``/``transient``.

    Returns ``{"success", "message", "value", "timing", "attempts", "logs"}``.
    """
    t_pre = 0.0
    t_fire = 0.0
    attempts = 0
    value = None
    all_logs = []

    for attempt in range(max_retries + 1):
        attempts = attempt + 1

        if pre_check_fn is not None:
            t0 = time.perf_counter()
            result = pre_check_fn()
            t_pre += time.perf_counter() - t0
            all_logs.extend(result.get("logs", []))
            if not result["success"]:
                return {
                    "success": False,
                    "message": f"{description} | Pre-check failed",
                    "value": None,
                    "timing": {"pre_check_s": t_pre, "fire_s": t_fire},
                    "attempts": attempts,
                    "logs": all_logs,
                }

        t0 = time.perf_counter()
        try:
            fr = fire_fn()
        except Exception as e:  # noqa: BLE001 - fire_fn should not raise; guard anyway
            t_fire += time.perf_counter() - t0
            msg = f"{description} | Fire exception: {e}"
            log.error(msg)
            all_logs.append(_make_log_entry("error", msg))
            return {
                "success": False,
                "message": msg,
                "value": None,
                "timing": {"pre_check_s": t_pre, "fire_s": t_fire},
                "attempts": attempts,
                "logs": all_logs,
            }
        t_fire += time.perf_counter() - t0
        all_logs.extend(fr.get("logs", []))

        if fr["success"]:
            value = fr.get("value")
            break

        error_msg = fr.get("error", "")
        transient = fr.get("transient", False)

        if transient and attempt < max_retries:
            if retry_backoff is not None and attempt > 0:
                delay = retry_backoff * (2 ** (attempt - 1)) if retry_escalate else retry_backoff
                log.warning(
                    "%s | Transient error (attempt %d/%d), retrying in %.1fs: %s",
                    description,
                    attempts,
                    max_retries + 1,
                    delay,
                    error_msg,
                )
                time.sleep(delay)
            else:
                log.warning(
                    "%s | Transient error (attempt %d/%d): %s",
                    description,
                    attempts,
                    max_retries + 1,
                    error_msg,
                )
            continue

        if transient:
            log.error("%s | Transient error exhausted retries: %s", description, error_msg)
        else:
            log.error("%s | Permanent error: %s", description, error_msg)
        return {
            "success": False,
            "message": f"{description} | RPC error: {error_msg}",
            "value": None,
            "timing": {"pre_check_s": t_pre, "fire_s": t_fire},
            "attempts": attempts,
            "logs": all_logs,
        }

    return {
        "success": True,
        "message": description,
        "value": value,
        "timing": {"pre_check_s": t_pre, "fire_s": t_fire},
        "attempts": attempts,
        "logs": all_logs,
    }


def confirm_and_fire(
    client,
    description,
    *,
    fire_fn,
    pre_check_fn=None,
    confirm_fn=None,
    max_retries=3,
    max_confirm_attempts=3,
    refire_on_unconfirmed=True,
    retry_backoff=None,
    retry_escalate=False,
    success_on_unconfirmed=True,
):
    """Fire a command and optionally confirm it, re-firing on unconfirmed.

    Returns ``{"success", "confirmed", "message", "value", "timing", "logs"}``.
    ``confirmed`` is True if ``confirm_fn`` succeeded, False if it failed, None if
    no ``confirm_fn`` was provided or the command failed before confirmation.
    ``value`` carries the RPC return value from the (last successful) fire.
    """
    t_wall = time.perf_counter()
    t_confirm = 0.0
    all_logs = []
    total_attempts = 0
    confirm_attempts = 0

    fb = _fire_block(
        client,
        description,
        fire_fn=fire_fn,
        pre_check_fn=pre_check_fn,
        max_retries=max_retries,
        retry_backoff=retry_backoff,
        retry_escalate=retry_escalate,
    )
    all_logs.extend(fb["logs"])
    total_attempts += fb["attempts"]
    acc_pre = fb["timing"]["pre_check_s"]
    acc_fire = fb["timing"]["fire_s"]
    value = fb["value"]

    if not fb["success"]:
        return {
            "success": False,
            "confirmed": None,
            "message": fb["message"],
            "value": None,
            "timing": _make_timing(
                pre_check_s=acc_pre,
                fire_s=acc_fire,
                total_s=time.perf_counter() - t_wall,
                attempts=total_attempts,
                confirm_attempts=0,
            ),
            "logs": all_logs,
        }

    if confirm_fn is None:
        log.info(
            "%s | OK (%.3fs) attempts=%d", description, time.perf_counter() - t_wall, total_attempts
        )
        return {
            "success": True,
            "confirmed": None,
            "message": description,
            "value": value,
            "timing": _make_timing(
                pre_check_s=acc_pre,
                fire_s=acc_fire,
                total_s=time.perf_counter() - t_wall,
                attempts=total_attempts,
                confirm_attempts=0,
            ),
            "logs": all_logs,
        }

    last_confirm = None
    for ca in range(max_confirm_attempts):
        confirm_attempts = ca + 1
        t0 = time.perf_counter()
        try:
            conf = confirm_fn()
        except Exception as e:  # noqa: BLE001
            msg = f"{description} | Confirm exception: {e}"
            log.warning(msg)
            all_logs.append(_make_log_entry("warning", msg))
            conf = {"success": False, "logs": []}
        last_confirm = conf
        t_confirm += time.perf_counter() - t0
        all_logs.extend(conf.get("logs", []))

        if conf["success"]:
            log.info(
                "%s | OK (%.3fs) attempts=%d confirm_attempts=%d",
                description,
                time.perf_counter() - t_wall,
                total_attempts,
                confirm_attempts,
            )
            return {
                "success": True,
                "confirmed": True,
                "message": description,
                "value": value,
                "timing": _make_timing(
                    pre_check_s=acc_pre,
                    fire_s=acc_fire,
                    confirm_s=t_confirm,
                    total_s=time.perf_counter() - t_wall,
                    attempts=total_attempts,
                    confirm_attempts=confirm_attempts,
                ),
                "logs": all_logs,
            }

        if ca < max_confirm_attempts - 1:
            if not refire_on_unconfirmed:
                msg = f"{description} | Readback unconfirmed; retrying readback only"
                log.info(msg)
                all_logs.append(_make_log_entry("info", msg))
                continue

            if pre_check_fn is not None:
                t0 = time.perf_counter()
                idle = pre_check_fn()
                acc_pre += time.perf_counter() - t0
                all_logs.extend(idle.get("logs", []))

            log.info(
                "%s | Confirm failed, re-firing (attempt %d/%d)",
                description,
                confirm_attempts + 1,
                max_confirm_attempts,
            )
            fb = _fire_block(
                client,
                description,
                fire_fn=fire_fn,
                pre_check_fn=None,
                max_retries=max_retries,
                retry_backoff=retry_backoff,
                retry_escalate=retry_escalate,
            )
            all_logs.extend(fb["logs"])
            total_attempts += fb["attempts"]
            acc_fire += fb["timing"]["fire_s"]
            if fb["success"]:
                value = fb["value"]
            else:
                return {
                    "success": False,
                    "confirmed": False,
                    "message": fb["message"],
                    "value": None,
                    "timing": _make_timing(
                        pre_check_s=acc_pre,
                        fire_s=acc_fire,
                        confirm_s=t_confirm,
                        total_s=time.perf_counter() - t_wall,
                        attempts=total_attempts,
                        confirm_attempts=confirm_attempts,
                    ),
                    "logs": all_logs,
                }

    msg = (
        f"{description} | UNCONFIRMED after {confirm_attempts} readback attempt(s); "
        f"command was sent successfully, but state readback did not confirm the "
        f"requested value{_confirmation_detail(last_confirm)}"
    )
    log.warning("%s (%.3fs)", msg, time.perf_counter() - t_wall)
    all_logs.append(_make_log_entry("warning", msg))
    return {
        "success": success_on_unconfirmed,
        "confirmed": False,
        "message": f"{description} (readback unconfirmed)",
        "value": value,
        "timing": _make_timing(
            pre_check_s=acc_pre,
            fire_s=acc_fire,
            confirm_s=t_confirm,
            total_s=time.perf_counter() - t_wall,
            attempts=total_attempts,
            confirm_attempts=confirm_attempts,
        ),
        "logs": all_logs,
    }

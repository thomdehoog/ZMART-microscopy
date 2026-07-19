"""
Readback confirmation functions.
================================
Each ``_confirm_*`` function reads back the current state and checks
whether a specific parameter matches the target value. Used by the
backbone (``confirm_and_fire``) to verify that set commands took effect.

All confirm functions follow the same contract::

    callable(client) → {"success": bool, "logs": [...]}

Extra parameters (job_name, target, tolerance, etc.) are pre-bound with
``functools.partial`` at profile definition time. The command function
binds ``client`` via lambda. The backbone sees only a zero-arg callable
returning a result dict.

**Polling ownership:** Every confirm function owns one bounded polling
window and returns only when the readback matches or the window expires.
Profiles decide how many confirmation windows are allowed and whether a
failed window causes a re-fire.

**No closure factories.** The old ``_make_acquire_confirm`` and
``_make_select_job_confirm`` factories are eliminated. Confirm functions
that need polling own their loop; all state is local.

**Table-driven confirms.** Every per-setting confirm that is just the same
poll loop differing only by readback path, comparator, and tolerance is a
thin wrapper over ``_confirm_readback`` bound to one row of
``confirm_specs.CONFIRM_SPECS``. Confirms with extra behaviour (z-stack
quantisation, the zoom last-actual report, the image-format string target,
objective/move/acquire) keep their own bespoke loops below.

Import restrictions: only ``readers``, command settings, runtime
utilities/profiles, and stdlib. Nothing from command wrappers.
"""

import logging
import math
import queue
import threading
import time

from .. import readers as _readers
from ..commands.errors import _check_api_error, _is_transient_error
from ..config import timing as _timing
from .confirm_specs import CONFIRM_SPECS
from .envelope import _make_log_entry
from .settings import make_changeable_copy

log = logging.getLogger(__name__)


# =============================================================================
# Confirmation race - the one mechanism every command confirms through
# =============================================================================


def race_confirmations(api_leg=None, log_leg=None, *, label="", budget_s=None):
    """Compose confirmation legs into one dispatch-compatible callable.

    Every command's confirmation routes through here. A single leg passes
    through UNCHANGED - the returned callable is the leg itself, so the
    dispatch contract (``() -> {"success": bool, "logs": [...]}``) and the
    behavior of every existing single-leg confirmation are bit-identical.

    With two legs, the race returns as soon as the first leg confirms.
    Legs must be target-gated and fail closed on their own; the race adds
    no judgement of its own - it only arbitrates *which admissible evidence
    arrived first* and reports the outcome:

    - the winning leg and elapsed time (result ``logs[]``),
    - a WARNING (driver log + ``logs[]``) when the other leg had already
      failed - source disagreement is surfaced, never hidden,
    - abandonment of a still-pending leg (the CAM read is non-cancellable,
      so abandonment, not cancellation, is the honest option),
    - fail-closed ``success=False`` when no leg confirms or ``budget_s``
      expires. ``budget_s`` is mandatory for a dual-leg race and must fit
      inside one dispatcher confirm attempt.

    The race itself never touches the CAM and takes NO in-flight claim:
    the api leg performs all its CAM access through the routed readers,
    whose per-read in-flight cap already provides the single-flight
    guarantee. (Wrapping the whole leg in the client's claim starved the
    leg's own routed reads - CF-01.) An abandoned api leg can therefore
    hold at most one raw CAM read in flight, and the cap keeps that read
    from being overlapped; select_job additionally sizes the api leg's
    poll window inside the budget so an abandoned leg drains promptly
    (CF-05).
    """
    if log_leg is None:
        return api_leg
    if api_leg is None:
        return log_leg
    if budget_s is None:
        raise ValueError("a dual-leg confirmation race requires budget_s")

    def _failed_outcome(level, msg):
        return {"success": False, "logs": [_make_log_entry(level, msg)]}

    def _run_leg(tag, leg, results):
        try:
            outcome = leg()
        except Exception as exc:
            outcome = _failed_outcome(
                "warning",
                f"{label} | {tag} confirmation leg raised: {type(exc).__name__}: {exc}",
            )
        else:
            if not isinstance(outcome, dict):
                outcome = _failed_outcome(
                    "warning",
                    f"{label} | {tag} confirmation leg returned "
                    f"{type(outcome).__name__}, expected dict",
                )
        results.put(outcome)

    def run_race():
        api_results = queue.Queue()
        log_results = queue.Queue()
        threading.Thread(
            target=_run_leg,
            args=("api", api_leg, api_results),
            name="lasx-confirm-api",
            daemon=True,
        ).start()
        threading.Thread(
            target=_run_leg,
            args=("log", log_leg, log_results),
            name="lasx-confirm-log",
            daemon=True,
        ).start()

        started = time.monotonic()
        deadline = started + budget_s
        outcomes = {}
        winner = None
        while len(outcomes) < 2:
            now = time.monotonic()
            if now >= deadline:
                break
            if "api" not in outcomes:
                try:
                    outcomes["api"] = api_results.get_nowait()
                except queue.Empty:
                    pass
                else:
                    if outcomes["api"].get("success"):
                        winner = "api"
                        break
            if "log" not in outcomes:
                try:
                    outcomes["log"] = log_results.get_nowait()
                except queue.Empty:
                    pass
                else:
                    if outcomes["log"].get("success"):
                        winner = "log"
                        break
            if len(outcomes) < 2:
                time.sleep(min(0.005, max(0.0, deadline - now)))

        if winner is not None:
            loser = "log" if winner == "api" else "api"
            if loser not in outcomes:
                # The loser may have finished in the instant between our last
                # poll and the win — one bounded drain so a completed leg is
                # reported as disagreement, not misreported as abandoned.
                pending_q = log_results if loser == "log" else api_results
                try:
                    outcomes[loser] = pending_q.get(timeout=0.05)
                except queue.Empty:
                    pass

        elapsed = time.monotonic() - started
        logs = []
        for tag in ("api", "log"):
            if tag in outcomes:
                logs.extend(outcomes[tag].get("logs", []))

        if winner is not None:
            loser = "log" if winner == "api" else "api"
            logs.append(
                _make_log_entry("info", f"{label} | confirmed by {winner} leg ({elapsed:.3f}s)")
            )
            if loser in outcomes:
                msg = f"{label} | {loser} leg had not confirmed when the {winner} leg confirmed"
                log.warning(msg)
                logs.append(_make_log_entry("warning", msg))
            else:
                logs.append(
                    _make_log_entry(
                        "info", f"{label} | {loser} leg still pending at win; abandoned"
                    )
                )
            return {"success": True, "logs": logs}

        if len(outcomes) < 2:
            pending = [t for t in ("api", "log") if t not in outcomes]
            msg = (
                f"{label} | confirmation race budget {budget_s:.1f}s "
                f"exhausted; still pending: {', '.join(pending)}"
            )
            log.warning(msg)
            logs.append(_make_log_entry("warning", msg))
        else:
            logs.append(
                _make_log_entry("info", f"{label} | no confirmation leg confirmed ({elapsed:.3f}s)")
            )
        return {"success": False, "logs": logs}

    return run_race


# =============================================================================
# Readback helper
# =============================================================================


def _readback(client, job_name, *, observed_after=None, mode=None):
    """Read job settings, using the configured mode when *mode* is None."""
    # Reader budget is its own profile knob, distinct from the confirm poll
    # window: this is a genuine "how long may one job-settings read block"
    # value. Deferred import — profiles imports this module.
    from ..config.profiles import STATE_READERS

    reading = _readers.get_job_settings(
        client,
        job_name,
        timeout=STATE_READERS.job_settings_timeout_s,
        mode=mode,
        diagnostics=True,
    )
    if reading is None:
        return None
    if hasattr(reading, "value"):
        if reading.value is None:
            return None
        if (
            observed_after is not None
            and reading.observed_at is not None
            and reading.observed_at <= observed_after
        ):
            return None
        raw = reading.value
    else:
        raw = reading
    return make_changeable_copy(raw)


def _reading_value_after(reading, observed_after):
    """Return a diagnostic reading's value only if it is post-start.

    Tests sometimes patch routed readers with their old plain return shape; those
    values are accepted here so the tests can stay focused on confirmation logic.
    Real routed readers return ``Reading`` and get the timestamp gate.
    """
    if reading is None:
        return None
    if not hasattr(reading, "value"):
        return reading
    if reading.value is None or reading.observed_at is None:
        return None
    if reading.observed_at <= observed_after:
        return None
    return reading.value


# =============================================================================
# Generic readback confirmation — the shared per-setting poll loop
# =============================================================================


def _confirm_readback(
    client,
    job_name,
    target,
    *,
    extract,
    label,
    compare,
    errors,
    tolerance=None,
    poll_window=None,
    poll_interval=0.01,
):
    """Poll a job-settings readback until one value matches ``target``.

    This is the shared skeleton behind every pure per-setting confirm: the
    timeout default, the ``t_start``/``deadline`` window, the ``_readback``
    poll, the nested extraction, the comparison, the per-poll DEBUG line, the
    swallowed extraction errors, the sleep, and the single timeout WARNING +
    ``success=False`` dict. The four things that vary between settings are
    passed in from ``confirm_specs.CONFIRM_SPECS``:

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        target: Expected value.
        extract: ``callable(ch) -> actual`` pulling the value from the
            readback dict (binds the setting's selectors, e.g. ``si``).
        label: Display name used verbatim in the DEBUG and timeout messages.
        compare: ``callable(actual, target, tolerance) -> bool`` — exact or
            absolute-tolerance.
        errors: Exception tuple to swallow during extraction/comparison.
        tolerance: Acceptable deviation (ignored by exact comparators).
        poll_window: Hard ceiling in seconds. None uses CONFIRM_POLL_S.
        poll_interval: Seconds between readback polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    if poll_window is None:
        poll_window = _timing.CONFIRM_POLL_S
    logs = []
    t_start = time.perf_counter()
    deadline = t_start + poll_window

    while time.perf_counter() < deadline:
        ch = _readback(client, job_name)
        if ch is not None:
            try:
                actual = extract(ch)
                if compare(actual, target, tolerance):
                    return {"success": True, "logs": logs}
                log.debug("%s confirm: target=%s actual=%s", label, target, actual)
            except errors:
                pass
        time.sleep(poll_interval)

    msg = f"{label} timeout after {time.perf_counter() - t_start:.1f}s — target={target}"
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}


def _run_spec(
    name,
    client,
    job_name,
    target,
    *,
    tolerance=None,
    poll_window=None,
    poll_interval=0.01,
    **params,
):
    """Run ``_confirm_readback`` against one ``CONFIRM_SPECS`` row.

    ``params`` carries the setting's runtime selectors (si / beam_route /
    line_index / fw_type) which the descriptor's extractor reads.
    """
    spec = CONFIRM_SPECS[name]
    return _confirm_readback(
        client,
        job_name,
        target,
        extract=lambda ch: spec.extract(ch, params),
        label=spec.label,
        compare=spec.compare,
        errors=spec.errors,
        tolerance=tolerance,
        poll_window=poll_window,
        poll_interval=poll_interval,
    )


# =============================================================================
# Confirm functions — approximate match (tolerance parameter)
# =============================================================================

ZMODE_KEY = {"galvo": "z-galvo", "zwide": "z-wide"}


def confirm_move_z(
    client,
    *,
    job_name,
    z_mode,
    target_um,
    tolerance=1.0,
    poll_window=None,
    poll_interval=0.01,
    observed_after=None,
):
    """Poll until Z drive position is within tolerance, or until timeout.

    Owns one bounded polling window; the command profile decides how
    many windows are attempted.

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        z_mode: Drive type — "galvo" or "zwide".
        target_um: Expected Z position in micrometers.
        tolerance: Acceptable deviation in micrometers.
        poll_window: Hard ceiling in seconds. None uses CONFIRM_POLL_S.
        poll_interval: Seconds between position polls.
        observed_after: Reject reader observations at or before this wall-clock
            timestamp. Move commands bind their pre-command timestamp here so
            a stale log entry cannot confirm the move.

    Returns:
        {"success": bool, "logs": [...]}
    """
    if poll_window is None:
        poll_window = _timing.CONFIRM_POLL_S
    logs = []
    key = ZMODE_KEY[z_mode]
    t_start = time.perf_counter()
    deadline = t_start + poll_window

    while time.perf_counter() < deadline:
        ch = _readback(
            client,
            job_name,
            observed_after=observed_after,
        )
        if ch is not None:
            try:
                actual = ch["zPosition"][key]
                log.debug(
                    "MoveZ confirm: target=%.2f actual=%.2f delta=%.3f um",
                    target_um,
                    actual,
                    abs(actual - target_um),
                )
                if abs(actual - target_um) < tolerance:
                    return {"success": True, "logs": logs}
            except (KeyError, TypeError):
                pass

        time.sleep(poll_interval)

    msg = (
        f"MoveZ timeout after {time.perf_counter() - t_start:.1f}s — "
        f"target={target_um:.1f} um ({z_mode})"
    )
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}


def _confirm_zoom(client, job_name, target, tolerance=0.1, poll_window=None, poll_interval=0.01):
    """Poll until zoom matches target within tolerance, or until timeout.

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        target: Expected zoom value.
        tolerance: Acceptable deviation.
        poll_window: Hard ceiling in seconds. None uses CONFIRM_POLL_S.
        poll_interval: Seconds between readback polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    if poll_window is None:
        poll_window = _timing.CONFIRM_POLL_S
    logs = []
    t_start = time.perf_counter()
    deadline = t_start + poll_window

    last_actual = None
    while time.perf_counter() < deadline:
        ch = _readback(client, job_name)
        if ch is not None:
            try:
                actual = ch["zoom"]["current"]
                last_actual = actual
                if abs(actual - target) < tolerance:
                    return {"success": True, "logs": logs}
                log.debug("Zoom confirm: target=%s actual=%s", target, actual)
            except (KeyError, TypeError):
                pass
        time.sleep(poll_interval)

    msg = (
        f"Zoom timeout after {time.perf_counter() - t_start:.1f}s "
        f"— target={target}, last_actual={last_actual}"
    )
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}


def _confirm_scan_field_rotation(
    client, job_name, target, tolerance=0.5, poll_window=None, poll_interval=0.01
):
    """Poll until scan field rotation matches target within tolerance (degrees)."""
    return _run_spec(
        "scan_field_rotation",
        client,
        job_name,
        target,
        tolerance=tolerance,
        poll_window=poll_window,
        poll_interval=poll_interval,
    )


def _quantised_candidates(centre, raw_size, step):
    """Return (begin, end) pairs for adjacent step-quantised stack sizes.

    When LAS X is in "Z-Step Size" mode it snaps the total stack size to
    an integer multiple of the step size while preserving the centre. We
    don't know its exact rounding rule, so we return both the floor and
    ceil multiples as candidates.
    """
    candidates = []
    n_lo = max(1, math.floor(abs(raw_size) / step))
    n_hi = max(1, math.ceil(abs(raw_size) / step))
    # Preserve the stack direction: for a descending stack (begin > end)
    # the quantised readback keeps begin above end; ascending-only
    # candidates would never match and burn every re-fire.
    direction = -1.0 if raw_size < 0 else 1.0
    for n in sorted({n_lo, n_hi}):  # set avoids duplicate when exact
        q_size = n * step * direction
        candidates.append((centre - q_size / 2.0, centre + q_size / 2.0))
    return candidates


def _confirm_z_stack_definition(
    client, job_name, begin_um, end_um, tolerance=1.0, poll_window=None, poll_interval=0.01
):
    """Poll until z-stack begin/end positions match within tolerance (micrometers).

    Only checks fields where a target was provided (not None).

    When LAS X is in "Z-Step Size" mode, total stack size is quantised
    to an integer multiple of the step size (centre preserved). Rather
    than blindly widening tolerance, we predict the quantised begin/end
    from the readback step size and accept a match against either the
    raw targets or the quantised predictions.

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        begin_um: Expected begin position (um), or None to skip.
        end_um: Expected end position (um), or None to skip.
        tolerance: Acceptable deviation in micrometers.
        poll_window: Hard ceiling in seconds. None uses CONFIRM_POLL_S.
        poll_interval: Seconds between readback polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    if poll_window is None:
        poll_window = _timing.CONFIRM_POLL_S
    logs = []
    t_start = time.perf_counter()
    deadline = t_start + poll_window

    while time.perf_counter() < deadline:
        ch = _readback(client, job_name)
        if ch is not None:
            try:
                actual_begin = ch["stack"]["begin"]
                actual_end = ch["stack"]["end"]
                step = ch["stack"].get("stepSize")
                log.debug(
                    "Z-stack def confirm: target=(%s, %s) actual=(%s, %s) step=%s",
                    begin_um,
                    end_um,
                    actual_begin,
                    actual_end,
                    step,
                )

                # Build candidate (begin, end) pairs to match against
                target_b = begin_um if begin_um is not None else actual_begin
                target_e = end_um if end_um is not None else actual_end
                candidates = [(target_b, target_e)]

                # Add quantised candidates when a meaningful step size exists
                if step and step > 0 and begin_um is not None and end_um is not None:
                    centre = (begin_um + end_um) / 2.0
                    raw_size = end_um - begin_um  # signed: keeps stack direction
                    candidates.extend(_quantised_candidates(centre, raw_size, step))

                # Accept if actual matches ANY candidate within base tolerance
                for exp_b, exp_e in candidates:
                    ok = True
                    if begin_um is not None:
                        ok = ok and abs(actual_begin - exp_b) < tolerance
                    if end_um is not None:
                        ok = ok and abs(actual_end - exp_e) < tolerance
                    if ok:
                        log.debug(
                            "Z-stack def confirm: matched candidate (%.2f, %.2f)", exp_b, exp_e
                        )
                        return {"success": True, "logs": logs}
                log.debug("Z-stack def confirm: no candidate matched")
            except (KeyError, TypeError) as e:
                log.debug("Z-stack def confirm: exception %s, stack=%s", e, ch.get("stack"))
        time.sleep(poll_interval)

    msg = (
        f"Z-stack def timeout after {time.perf_counter() - t_start:.1f}s — "
        f"target=({begin_um}, {end_um})"
    )
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}


def _confirm_z_stack_step_size(
    client, job_name, target, tolerance=0.5, poll_window=None, poll_interval=0.01
):
    """Poll until z-stack step size matches within tolerance (micrometers)."""
    return _run_spec(
        "z_stack_step_size",
        client,
        job_name,
        target,
        tolerance=tolerance,
        poll_window=poll_window,
        poll_interval=poll_interval,
    )


def _confirm_z_stack_size(
    client, job_name, target_um, tolerance=1.5, poll_window=None, poll_interval=0.01
):
    """Poll until z-stack total size matches within tolerance (micrometers).

    When LAS X is in "Z-Step Size" mode, actual size is quantised to
    an integer multiple of the step size. We accept the actual if it
    matches the target directly or matches the nearest quantised
    multiple(s), all within the base tolerance.

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        target_um: Expected total stack size in micrometers.
        tolerance: Acceptable deviation in micrometers.
        poll_window: Hard ceiling in seconds. None uses CONFIRM_POLL_S.
        poll_interval: Seconds between readback polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    if poll_window is None:
        poll_window = _timing.CONFIRM_POLL_S
    logs = []
    t_start = time.perf_counter()
    deadline = t_start + poll_window

    while time.perf_counter() < deadline:
        ch = _readback(client, job_name)
        if ch is not None:
            try:
                actual = ch["stack"]["size"]
                step = ch["stack"].get("stepSize")
                log.debug(
                    "Z-stack size confirm: target=%.4f actual=%.6g step=%s", target_um, actual, step
                )

                # Direct match (number-of-steps mode, or step divides evenly)
                if abs(actual - target_um) < tolerance:
                    return {"success": True, "logs": logs}

                # Quantised match: accept adjacent multiples of step size
                if step and step > 0:
                    n_lo = max(1, math.floor(target_um / step))
                    n_hi = max(1, math.ceil(target_um / step))
                    for n in sorted({n_lo, n_hi}):
                        if abs(actual - n * step) < tolerance:
                            log.debug(
                                "Z-stack size confirm: matched quantised size %.2f (n=%d)",
                                n * step,
                                n,
                            )
                            return {"success": True, "logs": logs}

                log.debug("Z-stack size confirm: no match")
            except (KeyError, TypeError) as e:
                log.debug("Z-stack size confirm: exception %s, stack=%s", e, ch.get("stack"))
        time.sleep(poll_interval)

    msg = f"Z-stack size timeout after {time.perf_counter() - t_start:.1f}s — target={target_um}"
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}


def _confirm_pinhole_airy(
    client, job_name, si, target, tolerance=0.05, poll_window=None, poll_interval=0.01
):
    """Poll until pinhole size matches within tolerance (Airy units)."""
    return _run_spec(
        "pinhole_airy",
        client,
        job_name,
        target,
        tolerance=tolerance,
        poll_window=poll_window,
        poll_interval=poll_interval,
        si=si,
    )


def _confirm_detector_gain(
    client, job_name, si, beam_route, target, tolerance=1.0, poll_window=None, poll_interval=0.01
):
    """Poll until detector gain matches within tolerance."""
    return _run_spec(
        "detector_gain",
        client,
        job_name,
        target,
        tolerance=tolerance,
        poll_window=poll_window,
        poll_interval=poll_interval,
        si=si,
        beam_route=beam_route,
    )


def _confirm_laser_intensity(
    client,
    job_name,
    si,
    beam_route,
    line_index,
    target,
    tolerance=0.005,
    poll_window=None,
    poll_interval=0.01,
):
    """Poll until laser intensity matches within tolerance (fraction)."""
    return _run_spec(
        "laser_intensity",
        client,
        job_name,
        target,
        tolerance=tolerance,
        poll_window=poll_window,
        poll_interval=poll_interval,
        si=si,
        beam_route=beam_route,
        line_index=line_index,
    )


def _confirm_filter_wheel_spectrum(
    client,
    job_name,
    si,
    beam_route,
    fw_type,
    target,
    tolerance=1,
    poll_window=None,
    poll_interval=0.01,
):
    """Poll until filter wheel spectrum position matches within tolerance (nm)."""
    return _run_spec(
        "filter_wheel_spectrum",
        client,
        job_name,
        target,
        tolerance=tolerance,
        poll_window=poll_window,
        poll_interval=poll_interval,
        si=si,
        beam_route=beam_route,
        fw_type=fw_type,
    )


# =============================================================================
# Confirm functions — exact match (no tolerance parameter)
# =============================================================================


def _confirm_scan_speed(client, job_name, target, poll_window=None, poll_interval=0.01):
    """Poll until scan speed matches exactly (discrete integer)."""
    return _run_spec(
        "scan_speed", client, job_name, target, poll_window=poll_window, poll_interval=poll_interval
    )


def _confirm_scan_resonant(client, job_name, target, poll_window=None, poll_interval=0.01):
    """Poll until resonant scanner state matches exactly."""
    return _run_spec(
        "scan_resonant",
        client,
        job_name,
        target,
        poll_window=poll_window,
        poll_interval=poll_interval,
    )


def _confirm_scan_mode(client, job_name, target, poll_window=None, poll_interval=0.01):
    """Poll until scan mode matches exactly (enum string)."""
    return _run_spec(
        "scan_mode", client, job_name, target, poll_window=poll_window, poll_interval=poll_interval
    )


def _confirm_sequential_mode(client, job_name, target, poll_window=None, poll_interval=0.01):
    """Poll until sequential mode matches exactly (enum string)."""
    return _run_spec(
        "sequential_mode",
        client,
        job_name,
        target,
        poll_window=poll_window,
        poll_interval=poll_interval,
    )


def _confirm_image_format(client, job_name, w, h, poll_window=None, poll_interval=0.01):
    """Poll until image format matches exactly (pixel dimensions).

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        w: Expected width in pixels.
        h: Expected height in pixels.
        poll_window: Hard ceiling in seconds. None uses CONFIRM_POLL_S.
        poll_interval: Seconds between readback polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    if poll_window is None:
        poll_window = _timing.CONFIRM_POLL_S
    logs = []
    t_start = time.perf_counter()
    deadline = t_start + poll_window

    while time.perf_counter() < deadline:
        ch = _readback(client, job_name)
        if ch is not None:
            try:
                actual = ch["format"]
                if actual == f"{w} x {h}":
                    return {"success": True, "logs": logs}
                log.debug("ImageFormat confirm: target='%s x %s' actual='%s'", w, h, actual)
            except (KeyError, TypeError):
                pass
        time.sleep(poll_interval)

    msg = f"ImageFormat timeout after {time.perf_counter() - t_start:.1f}s — target='{w} x {h}'"
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}


def confirm_objective(
    client, *, job_name, target_slot, target_name=None, poll_window=None, poll_interval=0.01
):
    """Poll until the active objective's slot matches *target_slot*.

    Owns one bounded polling window. Objective turret rotation is
    mechanical and can take several seconds, so the objective profile
    keeps this as a single confirmation window.

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        target_slot: Expected objective slot index.
        target_name: Objective name (for log messages only).
        poll_window: Hard ceiling in seconds. None uses CONFIRM_POLL_S.
        poll_interval: Seconds between readback polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    if poll_window is None:
        poll_window = _timing.CONFIRM_POLL_S
    logs = []
    t_start = time.perf_counter()
    deadline = t_start + poll_window
    label = target_name or f"slot {target_slot}"

    while time.perf_counter() < deadline:
        ch = _readback(client, job_name)
        if ch is not None:
            try:
                actual_slot = ch["objective"]["slotIndex"]
                log.debug(
                    "Objective confirm: target_slot=%s actual_slot=%s", target_slot, actual_slot
                )
                if actual_slot == target_slot:
                    return {"success": True, "logs": logs}
            except (KeyError, TypeError, AttributeError):
                pass

        time.sleep(poll_interval)

    msg = (
        f"Objective timeout after {time.perf_counter() - t_start:.1f}s — "
        f"target={label} (slot {target_slot})"
    )
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}


def _confirm_frame_accumulation(client, job_name, si, target, poll_window=None, poll_interval=0.01):
    """Poll until frame accumulation matches exactly."""
    return _run_spec(
        "frame_accumulation",
        client,
        job_name,
        target,
        poll_window=poll_window,
        poll_interval=poll_interval,
        si=si,
    )


def _confirm_frame_average(client, job_name, si, target, poll_window=None, poll_interval=0.01):
    """Poll until frame average matches exactly."""
    return _run_spec(
        "frame_average",
        client,
        job_name,
        target,
        poll_window=poll_window,
        poll_interval=poll_interval,
        si=si,
    )


def _confirm_line_accumulation(client, job_name, si, target, poll_window=None, poll_interval=0.01):
    """Poll until line accumulation matches exactly."""
    return _run_spec(
        "line_accumulation",
        client,
        job_name,
        target,
        poll_window=poll_window,
        poll_interval=poll_interval,
        si=si,
    )


def _confirm_line_average(client, job_name, si, target, poll_window=None, poll_interval=0.01):
    """Poll until line average matches exactly."""
    return _run_spec(
        "line_average",
        client,
        job_name,
        target,
        poll_window=poll_window,
        poll_interval=poll_interval,
        si=si,
    )


def _confirm_laser_shutter(
    client, job_name, si, beam_route, target, poll_window=None, poll_interval=0.01
):
    """Poll until laser shutter state matches exactly."""
    return _run_spec(
        "laser_shutter",
        client,
        job_name,
        target,
        poll_window=poll_window,
        poll_interval=poll_interval,
        si=si,
        beam_route=beam_route,
    )


def _confirm_filter_wheel_slot(
    client, job_name, si, beam_route, fw_type, target, poll_window=None, poll_interval=0.01
):
    """Poll until filter wheel slot matches exactly."""
    return _run_spec(
        "filter_wheel_slot",
        client,
        job_name,
        target,
        poll_window=poll_window,
        poll_interval=poll_interval,
        si=si,
        beam_route=beam_route,
        fw_type=fw_type,
    )


# =============================================================================
# XY position confirmation
# =============================================================================


def confirm_move_xy(
    client, *, target_x_um, target_y_um, tolerance=20.0, poll_window=None, poll_interval=0.1
):
    """Poll until XY stage position is within tolerance, or until timeout.

    Calls ``get_xy`` reader with 0.1s between calls to avoid
    overwhelming the API.

    Args:
        client: The connected LAS X API client.
        target_x_um: Expected X position in micrometers.
        target_y_um: Expected Y position in micrometers.
        tolerance: Acceptable deviation in micrometers per axis.
        poll_window: Hard ceiling in seconds. None uses CONFIRM_POLL_S.
        poll_interval: Seconds between get_xy calls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    if poll_window is None:
        poll_window = _timing.CONFIRM_POLL_S
    logs = []
    observed_after = time.time()
    t_start = time.perf_counter()
    deadline = t_start + poll_window
    last_position = None

    while time.perf_counter() < deadline:
        pos = _reading_value_after(
            _readers.get_xy(client, mode="api", diagnostics=True),
            observed_after,
        )
        if pos is not None:
            last_position = pos
            dx = abs(pos["x_um"] - target_x_um)
            dy = abs(pos["y_um"] - target_y_um)
            log.debug(
                "MoveXY confirm: target=(%.1f, %.1f) actual=(%.1f, %.1f) delta=(%.2f, %.2f) um",
                target_x_um,
                target_y_um,
                pos["x_um"],
                pos["y_um"],
                dx,
                dy,
            )

            if dx < tolerance and dy < tolerance:
                return {"success": True, "logs": logs, "last_position": last_position}

        time.sleep(poll_interval)

    msg = (
        f"MoveXY timeout after {time.perf_counter() - t_start:.1f}s — "
        f"target=({target_x_um:.1f}, {target_y_um:.1f})"
    )
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs, "last_position": last_position}


# =============================================================================
# Long-running confirm functions (own their polling loop)
# =============================================================================


def confirm_acquire(
    client, *, start_timeout=15.0, heartbeat_interval=30.0, timeout=None, poll_interval=0.1
):
    """Poll until acquisition completes, or return False if scan never starts.

    Pure status-polling function: reads only, never fires. When the scan
    has not started within *start_timeout*, returns ``{"success": False}``.
    Acquisition profiles fire the command once and treat that as a
    failed acquisition, not as permission to send another acquire command.

    Known limitation: detection is level-based polling at *poll_interval*
    (each poll also costs an API round trip), so an acquisition shorter
    than one polling gap can start and finish unobserved — reported here
    as a failure even though data was acquired. ``save()``'s freshness
    check is the backstop that recovers the data in that case.

    Phase 1 — wait up to *start_timeout* for scan to go non-idle.
              Returns False immediately on permanent error.
              Returns False if scan hasn't started.
    Phase 2 — wait for consecutive idle reads to confirm completion.

    Args:
        client: The connected LAS X API client.
        start_timeout: Seconds to wait for scan to start before
            returning acquisition failure.
        heartbeat_interval: Seconds between heartbeat log messages
            during long scans.
        timeout: Hard ceiling in seconds. None means wait indefinitely.
        poll_interval: Seconds between scan status polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    logs = []
    observed_after = time.time()
    t_start = time.perf_counter()
    last_heartbeat = t_start
    saw_scanning = False
    consecutive_idle = 0
    idle_streak_required = 2

    start_deadline = t_start + start_timeout
    deadline = t_start + (timeout if timeout is not None else 1e9)

    while time.perf_counter() < deadline:
        status = _reading_value_after(
            _readers.get_scan_status(client, mode="api", diagnostics=True),
            observed_after,
        )
        elapsed = time.perf_counter() - t_start

        if status is None or status == "Unknown":
            # Failed or stale status read (the API reader reports "Unknown"
            # on failure): evidence of neither scanning nor idle. It must
            # not set saw_scanning — that would arm phase 2 and skip both
            # the permanent-error check and the start timeout, confirming
            # an acquisition that may never have run. It also breaks the
            # idle streak, so completion needs consecutive observed reads.
            consecutive_idle = 0
        elif "Idle" not in status:
            saw_scanning = True
            consecutive_idle = 0
        else:
            consecutive_idle += 1

        # Phase 1: check for permanent errors before scan starts
        if not saw_scanning:
            err = _check_api_error(client)
            if err is not None:
                error_msg = err.get("error", "?")
                if not _is_transient_error(error_msg):
                    msg = f"Acquire error (permanent): {error_msg}"
                    log.error(msg)
                    logs.append(_make_log_entry("error", msg))
                    return {"success": False, "logs": logs}
                log.debug("Transient error during acquire start: %s", error_msg)

            # Start timeout: return acquisition failure. The acquire
            # profile does not re-fire acquisition commands.
            if time.perf_counter() > start_deadline:
                msg = (
                    f"Scan was never observed non-idle within {start_timeout:.0f}s "
                    f"({elapsed:.0f}s total) — either it did not start, or it "
                    f"finished between two status polls"
                )
                log.warning(msg)
                logs.append(_make_log_entry("warning", msg))
                return {"success": False, "logs": logs}

        # Heartbeat for long scans
        now = time.perf_counter()
        if now - last_heartbeat > heartbeat_interval:
            msg = f"Scanning: {status or 'Unknown'}, {elapsed:.0f}s elapsed"
            log.info(msg)
            logs.append(_make_log_entry("info", msg))
            last_heartbeat = now

        # Phase 2: completion — consecutive idle reads after saw scanning
        if consecutive_idle >= idle_streak_required and saw_scanning:
            return {"success": True, "logs": logs}

        time.sleep(poll_interval)

    msg = f"Acquisition timeout after {time.perf_counter() - t_start:.1f}s"
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}

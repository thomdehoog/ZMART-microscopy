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

Import restrictions: only ``readers``, ``settings``, ``prechecks``,
``utils``, and stdlib. Nothing from ``core``, ``commands``, or
``profiles``.
"""

import logging
import math
import time

from . import readers as _readers
from .errors import _check_api_error, _is_transient_error
from .settings import make_changeable_copy
from .utils import _make_log_entry, CONFIRM_TIMEOUT

log = logging.getLogger(__name__)


# =============================================================================
# Readback helper
# =============================================================================

def _readback(client, job_name):
    """Read job settings and return changeable copy, or None on failure."""
    raw = _readers.get_job_settings(client, job_name, timeout=CONFIRM_TIMEOUT)
    if raw is None:
        return None
    return make_changeable_copy(raw)


# =============================================================================
# Confirm functions — approximate match (tolerance parameter)
# =============================================================================

ZMODE_KEY = {"galvo": "z-galvo", "zwide": "z-wide"}


def confirm_move_z(client, *, job_name, z_mode, target_um, tolerance=1.0,
                   timeout=None, poll_interval=0.01):
    """Poll until Z drive position is within tolerance, or until timeout.

    Owns one bounded polling window; the command profile decides how
    many windows are attempted.

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        z_mode: Drive type — "galvo" or "zwide".
        target_um: Expected Z position in micrometers.
        tolerance: Acceptable deviation in micrometers.
        timeout: Hard ceiling in seconds. None uses CONFIRM_TIMEOUT.
        poll_interval: Seconds between position polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    if timeout is None:
        timeout = CONFIRM_TIMEOUT
    logs = []
    key = ZMODE_KEY[z_mode]
    t_start = time.perf_counter()
    deadline = t_start + timeout

    while time.perf_counter() < deadline:
        ch = _readback(client, job_name)
        if ch is not None:
            try:
                actual = ch["zPosition"][key]
                log.debug("MoveZ confirm: target=%.2f actual=%.2f delta=%.3f um",
                          target_um, actual, abs(actual - target_um))
                if abs(actual - target_um) < tolerance:
                    return {"success": True, "logs": logs}
            except (KeyError, TypeError):
                pass

        time.sleep(poll_interval)

    msg = (f"MoveZ timeout after {time.perf_counter() - t_start:.1f}s — "
           f"target={target_um:.1f} um ({z_mode})")
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}


def _confirm_zoom(client, job_name, target, tolerance=0.1,
                  timeout=None, poll_interval=0.01):
    """Poll until zoom matches target within tolerance, or until timeout.

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        target: Expected zoom value.
        tolerance: Acceptable deviation.
        timeout: Hard ceiling in seconds. None uses CONFIRM_TIMEOUT.
        poll_interval: Seconds between readback polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    if timeout is None:
        timeout = CONFIRM_TIMEOUT
    logs = []
    t_start = time.perf_counter()
    deadline = t_start + timeout

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

    msg = (f"Zoom timeout after {time.perf_counter() - t_start:.1f}s "
           f"— target={target}, last_actual={last_actual}")
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}


def _confirm_scan_field_rotation(client, job_name, target, tolerance=0.5,
                                 timeout=None, poll_interval=0.01):
    """Poll until scan field rotation matches target within tolerance (degrees).

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        target: Expected rotation angle in degrees.
        tolerance: Acceptable deviation in degrees.
        timeout: Hard ceiling in seconds. None uses CONFIRM_TIMEOUT.
        poll_interval: Seconds between readback polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    if timeout is None:
        timeout = CONFIRM_TIMEOUT
    logs = []
    t_start = time.perf_counter()
    deadline = t_start + timeout

    while time.perf_counter() < deadline:
        ch = _readback(client, job_name)
        if ch is not None:
            try:
                actual = ch["scanFieldRotation"]["value"]
                if abs(actual - target) < tolerance:
                    return {"success": True, "logs": logs}
                log.debug("ScanFieldRotation confirm: target=%s actual=%s", target, actual)
            except (KeyError, TypeError):
                pass
        time.sleep(poll_interval)

    msg = f"ScanFieldRotation timeout after {time.perf_counter() - t_start:.1f}s — target={target}"
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}


def _quantised_candidates(centre, raw_size, step):
    """Return (begin, end) pairs for adjacent step-quantised stack sizes.

    When LAS X is in "Z-Step Size" mode it snaps the total stack size to
    an integer multiple of the step size while preserving the centre. We
    don't know its exact rounding rule, so we return both the floor and
    ceil multiples as candidates.
    """
    candidates = []
    n_lo = max(1, math.floor(raw_size / step))
    n_hi = max(1, math.ceil(raw_size / step))
    for n in sorted({n_lo, n_hi}):          # set avoids duplicate when exact
        q_size = n * step
        candidates.append((centre - q_size / 2.0, centre + q_size / 2.0))
    return candidates


def _confirm_z_stack_definition(client, job_name, begin_um, end_um,
                                tolerance=1.0, timeout=None, poll_interval=0.01):
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
        timeout: Hard ceiling in seconds. None uses CONFIRM_TIMEOUT.
        poll_interval: Seconds between readback polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    if timeout is None:
        timeout = CONFIRM_TIMEOUT
    logs = []
    t_start = time.perf_counter()
    deadline = t_start + timeout

    while time.perf_counter() < deadline:
        ch = _readback(client, job_name)
        if ch is not None:
            try:
                actual_begin = ch["stack"]["begin"]
                actual_end = ch["stack"]["end"]
                step = ch["stack"].get("stepSize")
                log.debug("Z-stack def confirm: target=(%s, %s) actual=(%s, %s) step=%s",
                          begin_um, end_um, actual_begin, actual_end, step)

                # Build candidate (begin, end) pairs to match against
                target_b = begin_um if begin_um is not None else actual_begin
                target_e = end_um if end_um is not None else actual_end
                candidates = [(target_b, target_e)]

                # Add quantised candidates when a meaningful step size exists
                if (step and step > 0
                        and begin_um is not None and end_um is not None):
                    centre = (begin_um + end_um) / 2.0
                    raw_size = abs(end_um - begin_um)
                    candidates.extend(_quantised_candidates(centre, raw_size, step))

                # Accept if actual matches ANY candidate within base tolerance
                for (exp_b, exp_e) in candidates:
                    ok = True
                    if begin_um is not None:
                        ok = ok and abs(actual_begin - exp_b) < tolerance
                    if end_um is not None:
                        ok = ok and abs(actual_end - exp_e) < tolerance
                    if ok:
                        log.debug("Z-stack def confirm: matched candidate "
                                  "(%.2f, %.2f)", exp_b, exp_e)
                        return {"success": True, "logs": logs}
                log.debug("Z-stack def confirm: no candidate matched")
            except (KeyError, TypeError) as e:
                log.debug("Z-stack def confirm: exception %s, stack=%s", e,
                          ch.get("stack"))
        time.sleep(poll_interval)

    msg = (f"Z-stack def timeout after {time.perf_counter() - t_start:.1f}s — "
           f"target=({begin_um}, {end_um})")
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}


def _confirm_z_stack_step_size(client, job_name, target_um, tolerance=0.5,
                               timeout=None, poll_interval=0.01):
    """Poll until z-stack step size matches within tolerance (micrometers).

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        target_um: Expected step size in micrometers.
        tolerance: Acceptable deviation in micrometers.
        timeout: Hard ceiling in seconds. None uses CONFIRM_TIMEOUT.
        poll_interval: Seconds between readback polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    if timeout is None:
        timeout = CONFIRM_TIMEOUT
    logs = []
    t_start = time.perf_counter()
    deadline = t_start + timeout

    while time.perf_counter() < deadline:
        ch = _readback(client, job_name)
        if ch is not None:
            try:
                actual = ch["stack"]["stepSize"]
                log.debug("Z-stack step confirm: target=%.4f actual=%.6g", target_um, actual)
                if abs(actual - target_um) < tolerance:
                    return {"success": True, "logs": logs}
            except (KeyError, TypeError):
                pass
        time.sleep(poll_interval)

    msg = f"Z-stack step timeout after {time.perf_counter() - t_start:.1f}s — target={target_um}"
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}


def _confirm_z_stack_size(client, job_name, target_um, tolerance=1.5,
                          timeout=None, poll_interval=0.01):
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
        timeout: Hard ceiling in seconds. None uses CONFIRM_TIMEOUT.
        poll_interval: Seconds between readback polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    if timeout is None:
        timeout = CONFIRM_TIMEOUT
    logs = []
    t_start = time.perf_counter()
    deadline = t_start + timeout

    while time.perf_counter() < deadline:
        ch = _readback(client, job_name)
        if ch is not None:
            try:
                actual = ch["stack"]["size"]
                step = ch["stack"].get("stepSize")
                log.debug("Z-stack size confirm: target=%.4f actual=%.6g step=%s",
                          target_um, actual, step)

                # Direct match (number-of-steps mode, or step divides evenly)
                if abs(actual - target_um) < tolerance:
                    return {"success": True, "logs": logs}

                # Quantised match: accept adjacent multiples of step size
                if step and step > 0:
                    n_lo = max(1, math.floor(target_um / step))
                    n_hi = max(1, math.ceil(target_um / step))
                    for n in sorted({n_lo, n_hi}):
                        if abs(actual - n * step) < tolerance:
                            log.debug("Z-stack size confirm: matched quantised "
                                      "size %.2f (n=%d)", n * step, n)
                            return {"success": True, "logs": logs}

                log.debug("Z-stack size confirm: no match")
            except (KeyError, TypeError) as e:
                log.debug("Z-stack size confirm: exception %s, stack=%s", e,
                          ch.get("stack"))
        time.sleep(poll_interval)

    msg = f"Z-stack size timeout after {time.perf_counter() - t_start:.1f}s — target={target_um}"
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}


def _confirm_pinhole_airy(client, job_name, si, target, tolerance=0.05,
                          timeout=None, poll_interval=0.01):
    """Poll until pinhole size matches within tolerance (Airy units).

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        si: Setting index.
        target: Expected pinhole size in Airy units.
        tolerance: Acceptable deviation.
        timeout: Hard ceiling in seconds. None uses CONFIRM_TIMEOUT.
        poll_interval: Seconds between readback polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    if timeout is None:
        timeout = CONFIRM_TIMEOUT
    logs = []
    t_start = time.perf_counter()
    deadline = t_start + timeout

    while time.perf_counter() < deadline:
        ch = _readback(client, job_name)
        if ch is not None:
            try:
                actual = ch["activeSettings"][si]["pinholeAiry"]["value"]
                if abs(actual - target) < tolerance:
                    return {"success": True, "logs": logs}
                log.debug("PinholeAiry confirm: target=%s actual=%s", target, actual)
            except (KeyError, TypeError, IndexError):
                pass
        time.sleep(poll_interval)

    msg = f"PinholeAiry timeout after {time.perf_counter() - t_start:.1f}s — target={target}"
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}


def _confirm_detector_gain(client, job_name, si, beam_route, target,
                           tolerance=1.0, timeout=None, poll_interval=0.01):
    """Poll until detector gain matches within tolerance.

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        si: Setting index.
        beam_route: Beam route identifier for the detector.
        target: Expected gain value.
        tolerance: Acceptable deviation.
        timeout: Hard ceiling in seconds. None uses CONFIRM_TIMEOUT.
        poll_interval: Seconds between readback polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    if timeout is None:
        timeout = CONFIRM_TIMEOUT
    logs = []
    t_start = time.perf_counter()
    deadline = t_start + timeout

    while time.perf_counter() < deadline:
        ch = _readback(client, job_name)
        if ch is not None:
            try:
                det = next(d for d in ch["activeSettings"][si]["activeDetectors"]
                           if d["_beamRoute"] == beam_route)
                actual = det["gain"]["value"]
                if abs(actual - target) < tolerance:
                    return {"success": True, "logs": logs}
                log.debug("DetectorGain confirm: target=%s actual=%s", target, actual)
            except (KeyError, TypeError, IndexError, StopIteration):
                pass
        time.sleep(poll_interval)

    msg = f"DetectorGain timeout after {time.perf_counter() - t_start:.1f}s — target={target}"
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}


def _confirm_laser_intensity(client, job_name, si, beam_route, line_index,
                             target, tolerance=0.005,
                             timeout=None, poll_interval=0.01):
    """Poll until laser intensity matches within tolerance (fraction).

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        si: Setting index.
        beam_route: Beam route identifier.
        line_index: Laser line index.
        target: Expected intensity (0.0-1.0).
        tolerance: Acceptable deviation.
        timeout: Hard ceiling in seconds. None uses CONFIRM_TIMEOUT.
        poll_interval: Seconds between readback polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    if timeout is None:
        timeout = CONFIRM_TIMEOUT
    logs = []
    t_start = time.perf_counter()
    deadline = t_start + timeout

    while time.perf_counter() < deadline:
        ch = _readback(client, job_name)
        if ch is not None:
            try:
                las = next(l for l in ch["activeSettings"][si]["activeLaserLines"]
                           if l["_beamRoute"] == beam_route and l["_lineIndex"] == line_index)
                actual = las["intensity"]["value"]
                if abs(actual - target) < tolerance:
                    return {"success": True, "logs": logs}
                log.debug("LaserIntensity confirm: target=%s actual=%s", target, actual)
            except (KeyError, TypeError, IndexError, StopIteration):
                pass
        time.sleep(poll_interval)

    msg = (f"LaserIntensity timeout after {time.perf_counter() - t_start:.1f}s — "
           f"target={target}")
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}


def _confirm_filter_wheel_spectrum(client, job_name, si, beam_route, fw_type,
                                   target, tolerance=1,
                                   timeout=None, poll_interval=0.01):
    """Poll until filter wheel spectrum position matches within tolerance (nm).

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        si: Setting index.
        beam_route: Beam route identifier.
        fw_type: Filter wheel type string.
        target: Expected spectrum position in nm.
        tolerance: Acceptable deviation in nm.
        timeout: Hard ceiling in seconds. None uses CONFIRM_TIMEOUT.
        poll_interval: Seconds between readback polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    if timeout is None:
        timeout = CONFIRM_TIMEOUT
    logs = []
    t_start = time.perf_counter()
    deadline = t_start + timeout

    while time.perf_counter() < deadline:
        ch = _readback(client, job_name)
        if ch is not None:
            try:
                fw = next(f for f in ch["activeSettings"][si]["filterWheels"]
                          if f["_beamRoute"] == beam_route and f.get("type") == fw_type)
                actual = fw["spectrumPosition"]
                if abs(actual - target) < tolerance:
                    return {"success": True, "logs": logs}
                log.debug("FilterWheelSpectrum confirm: target=%s actual=%s", target, actual)
            except (KeyError, TypeError, IndexError, StopIteration):
                pass
        time.sleep(poll_interval)

    msg = (f"FilterWheelSpectrum timeout after {time.perf_counter() - t_start:.1f}s — "
           f"target={target}")
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}


# =============================================================================
# Confirm functions — exact match (no tolerance parameter)
# =============================================================================

def _confirm_scan_speed(client, job_name, target,
                        timeout=None, poll_interval=0.01):
    """Poll until scan speed matches exactly (discrete integer).

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        target: Expected scan speed value.
        timeout: Hard ceiling in seconds. None uses CONFIRM_TIMEOUT.
        poll_interval: Seconds between readback polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    if timeout is None:
        timeout = CONFIRM_TIMEOUT
    logs = []
    t_start = time.perf_counter()
    deadline = t_start + timeout

    while time.perf_counter() < deadline:
        ch = _readback(client, job_name)
        if ch is not None:
            try:
                actual = ch["scanSpeed"]["value"]
                if actual == target:
                    return {"success": True, "logs": logs}
                log.debug("ScanSpeed confirm: target=%s actual=%s", target, actual)
            except (KeyError, TypeError):
                pass
        time.sleep(poll_interval)

    msg = f"ScanSpeed timeout after {time.perf_counter() - t_start:.1f}s — target={target}"
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}


def _confirm_scan_resonant(client, job_name, target,
                           timeout=None, poll_interval=0.01):
    """Poll until resonant scanner state matches exactly.

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        target: Expected resonant state (bool).
        timeout: Hard ceiling in seconds. None uses CONFIRM_TIMEOUT.
        poll_interval: Seconds between readback polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    if timeout is None:
        timeout = CONFIRM_TIMEOUT
    logs = []
    t_start = time.perf_counter()
    deadline = t_start + timeout

    while time.perf_counter() < deadline:
        ch = _readback(client, job_name)
        if ch is not None:
            try:
                actual = ch["scanSpeed"]["isResonant"]
                if actual == target:
                    return {"success": True, "logs": logs}
                log.debug("ScanResonant confirm: target=%s actual=%s", target, actual)
            except (KeyError, TypeError):
                pass
        time.sleep(poll_interval)

    msg = f"ScanResonant timeout after {time.perf_counter() - t_start:.1f}s — target={target}"
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}


def _confirm_scan_mode(client, job_name, target,
                       timeout=None, poll_interval=0.01):
    """Poll until scan mode matches exactly (enum string).

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        target: Expected scan mode string (e.g. "xyz").
        timeout: Hard ceiling in seconds. None uses CONFIRM_TIMEOUT.
        poll_interval: Seconds between readback polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    if timeout is None:
        timeout = CONFIRM_TIMEOUT
    logs = []
    t_start = time.perf_counter()
    deadline = t_start + timeout

    while time.perf_counter() < deadline:
        ch = _readback(client, job_name)
        if ch is not None:
            try:
                actual = ch["scanMode"]
                if actual == target:
                    return {"success": True, "logs": logs}
                log.debug("ScanMode confirm: target=%s actual=%s", target, actual)
            except (KeyError, TypeError):
                pass
        time.sleep(poll_interval)

    msg = f"ScanMode timeout after {time.perf_counter() - t_start:.1f}s — target={target}"
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}


def _confirm_sequential_mode(client, job_name, target,
                             timeout=None, poll_interval=0.01):
    """Poll until sequential mode matches exactly (enum string).

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        target: Expected sequential mode string.
        timeout: Hard ceiling in seconds. None uses CONFIRM_TIMEOUT.
        poll_interval: Seconds between readback polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    if timeout is None:
        timeout = CONFIRM_TIMEOUT
    logs = []
    t_start = time.perf_counter()
    deadline = t_start + timeout

    while time.perf_counter() < deadline:
        ch = _readback(client, job_name)
        if ch is not None:
            try:
                actual = ch["sequentialMode"]
                if actual == target:
                    return {"success": True, "logs": logs}
                log.debug("SequentialMode confirm: target=%s actual=%s", target, actual)
            except (KeyError, TypeError):
                pass
        time.sleep(poll_interval)

    msg = f"SequentialMode timeout after {time.perf_counter() - t_start:.1f}s — target={target}"
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}


def _confirm_image_format(client, job_name, w, h,
                          timeout=None, poll_interval=0.01):
    """Poll until image format matches exactly (pixel dimensions).

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        w: Expected width in pixels.
        h: Expected height in pixels.
        timeout: Hard ceiling in seconds. None uses CONFIRM_TIMEOUT.
        poll_interval: Seconds between readback polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    if timeout is None:
        timeout = CONFIRM_TIMEOUT
    logs = []
    t_start = time.perf_counter()
    deadline = t_start + timeout

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

    msg = (f"ImageFormat timeout after {time.perf_counter() - t_start:.1f}s — "
           f"target='{w} x {h}'")
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}


def confirm_objective(client, *, job_name, target_slot, target_name=None,
                      timeout=None, poll_interval=0.01):
    """Poll until the active objective's slot matches *target_slot*.

    Owns one bounded polling window. Objective turret rotation is
    mechanical and can take several seconds, so the objective profile
    keeps this as a single confirmation window.

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        target_slot: Expected objective slot index.
        target_name: Objective name (for log messages only).
        timeout: Hard ceiling in seconds. None uses CONFIRM_TIMEOUT.
        poll_interval: Seconds between readback polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    if timeout is None:
        timeout = CONFIRM_TIMEOUT
    logs = []
    t_start = time.perf_counter()
    deadline = t_start + timeout
    label = target_name or f"slot {target_slot}"

    while time.perf_counter() < deadline:
        ch = _readback(client, job_name)
        if ch is not None:
            try:
                actual_slot = ch["objective"]["slotIndex"]
                log.debug("Objective confirm: target_slot=%s actual_slot=%s",
                          target_slot, actual_slot)
                if actual_slot == target_slot:
                    return {"success": True, "logs": logs}
            except (KeyError, TypeError, AttributeError):
                pass

        time.sleep(poll_interval)

    msg = (f"Objective timeout after {time.perf_counter() - t_start:.1f}s — "
           f"target={label} (slot {target_slot})")
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}


def _confirm_frame_accumulation(client, job_name, si, target,
                                timeout=None, poll_interval=0.01):
    """Poll until frame accumulation matches exactly.

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        si: Setting index.
        target: Expected accumulation count.
        timeout: Hard ceiling in seconds. None uses CONFIRM_TIMEOUT.
        poll_interval: Seconds between readback polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    if timeout is None:
        timeout = CONFIRM_TIMEOUT
    logs = []
    t_start = time.perf_counter()
    deadline = t_start + timeout

    while time.perf_counter() < deadline:
        ch = _readback(client, job_name)
        if ch is not None:
            try:
                actual = ch["activeSettings"][si]["frameAccumulation"]
                if actual == target:
                    return {"success": True, "logs": logs}
                log.debug("FrameAccumulation confirm: target=%s actual=%s", target, actual)
            except (KeyError, TypeError, IndexError):
                pass
        time.sleep(poll_interval)

    msg = f"FrameAccumulation timeout after {time.perf_counter() - t_start:.1f}s — target={target}"
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}


def _confirm_frame_average(client, job_name, si, target,
                           timeout=None, poll_interval=0.01):
    """Poll until frame average matches exactly.

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        si: Setting index.
        target: Expected average count.
        timeout: Hard ceiling in seconds. None uses CONFIRM_TIMEOUT.
        poll_interval: Seconds between readback polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    if timeout is None:
        timeout = CONFIRM_TIMEOUT
    logs = []
    t_start = time.perf_counter()
    deadline = t_start + timeout

    while time.perf_counter() < deadline:
        ch = _readback(client, job_name)
        if ch is not None:
            try:
                actual = ch["activeSettings"][si]["frameAverage"]
                if actual == target:
                    return {"success": True, "logs": logs}
                log.debug("FrameAverage confirm: target=%s actual=%s", target, actual)
            except (KeyError, TypeError, IndexError):
                pass
        time.sleep(poll_interval)

    msg = f"FrameAverage timeout after {time.perf_counter() - t_start:.1f}s — target={target}"
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}


def _confirm_line_accumulation(client, job_name, si, target,
                               timeout=None, poll_interval=0.01):
    """Poll until line accumulation matches exactly.

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        si: Setting index.
        target: Expected accumulation count.
        timeout: Hard ceiling in seconds. None uses CONFIRM_TIMEOUT.
        poll_interval: Seconds between readback polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    if timeout is None:
        timeout = CONFIRM_TIMEOUT
    logs = []
    t_start = time.perf_counter()
    deadline = t_start + timeout

    while time.perf_counter() < deadline:
        ch = _readback(client, job_name)
        if ch is not None:
            try:
                actual = ch["activeSettings"][si]["lineAccumulation"]
                if actual == target:
                    return {"success": True, "logs": logs}
                log.debug("LineAccumulation confirm: target=%s actual=%s", target, actual)
            except (KeyError, TypeError, IndexError):
                pass
        time.sleep(poll_interval)

    msg = f"LineAccumulation timeout after {time.perf_counter() - t_start:.1f}s — target={target}"
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}


def _confirm_line_average(client, job_name, si, target,
                          timeout=None, poll_interval=0.01):
    """Poll until line average matches exactly.

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        si: Setting index.
        target: Expected average count.
        timeout: Hard ceiling in seconds. None uses CONFIRM_TIMEOUT.
        poll_interval: Seconds between readback polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    if timeout is None:
        timeout = CONFIRM_TIMEOUT
    logs = []
    t_start = time.perf_counter()
    deadline = t_start + timeout

    while time.perf_counter() < deadline:
        ch = _readback(client, job_name)
        if ch is not None:
            try:
                actual = ch["activeSettings"][si]["lineAverage"]
                if actual == target:
                    return {"success": True, "logs": logs}
                log.debug("LineAverage confirm: target=%s actual=%s", target, actual)
            except (KeyError, TypeError, IndexError):
                pass
        time.sleep(poll_interval)

    msg = f"LineAverage timeout after {time.perf_counter() - t_start:.1f}s — target={target}"
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}


def _confirm_laser_shutter(client, job_name, si, beam_route, target,
                           timeout=None, poll_interval=0.01):
    """Poll until laser shutter state matches exactly.

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        si: Setting index.
        beam_route: Beam route identifier.
        target: Expected shutter state (bool).
        timeout: Hard ceiling in seconds. None uses CONFIRM_TIMEOUT.
        poll_interval: Seconds between readback polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    if timeout is None:
        timeout = CONFIRM_TIMEOUT
    logs = []
    t_start = time.perf_counter()
    deadline = t_start + timeout

    while time.perf_counter() < deadline:
        ch = _readback(client, job_name)
        if ch is not None:
            try:
                las = next(l for l in ch["activeSettings"][si]["activeLaserLines"]
                           if l["_beamRoute"] == beam_route)
                actual = las["shutterOpen"]
                if actual == target:
                    return {"success": True, "logs": logs}
                log.debug("LaserShutter confirm: target=%s actual=%s", target, actual)
            except (KeyError, TypeError, IndexError, StopIteration):
                pass
        time.sleep(poll_interval)

    msg = f"LaserShutter timeout after {time.perf_counter() - t_start:.1f}s — target={target}"
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}


def _confirm_filter_wheel_slot(client, job_name, si, beam_route, fw_type,
                               target, timeout=None, poll_interval=0.01):
    """Poll until filter wheel slot matches exactly.

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        si: Setting index.
        beam_route: Beam route identifier.
        fw_type: Filter wheel type string.
        target: Expected slot index.
        timeout: Hard ceiling in seconds. None uses CONFIRM_TIMEOUT.
        poll_interval: Seconds between readback polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    if timeout is None:
        timeout = CONFIRM_TIMEOUT
    logs = []
    t_start = time.perf_counter()
    deadline = t_start + timeout

    while time.perf_counter() < deadline:
        ch = _readback(client, job_name)
        if ch is not None:
            try:
                fw = next(f for f in ch["activeSettings"][si]["filterWheels"]
                          if f["_beamRoute"] == beam_route and f.get("type") == fw_type)
                actual = fw["filterIndex"]
                if actual == target:
                    return {"success": True, "logs": logs}
                log.debug("FilterWheelSlot confirm: target=%s actual=%s", target, actual)
            except (KeyError, TypeError, IndexError, StopIteration):
                pass
        time.sleep(poll_interval)

    msg = f"FilterWheelSlot timeout after {time.perf_counter() - t_start:.1f}s — target={target}"
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}


# =============================================================================
# XY position confirmation
# =============================================================================

def confirm_move_xy(client, *, target_x_um, target_y_um, tolerance=20.0,
                    timeout=None, poll_interval=0.1):
    """Poll until XY stage position is within tolerance, or until timeout.

    Calls ``get_xy`` reader with 0.1s between calls to avoid
    overwhelming the API.

    Args:
        client: The connected LAS X API client.
        target_x_um: Expected X position in micrometers.
        target_y_um: Expected Y position in micrometers.
        tolerance: Acceptable deviation in micrometers per axis.
        timeout: Hard ceiling in seconds. None uses CONFIRM_TIMEOUT.
        poll_interval: Seconds between get_xy calls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    if timeout is None:
        timeout = CONFIRM_TIMEOUT
    logs = []
    t_start = time.perf_counter()
    deadline = t_start + timeout
    last_position = None

    while time.perf_counter() < deadline:
        pos = _readers.get_xy(client)
        if pos is not None:
            last_position = pos
            dx = abs(pos["x_um"] - target_x_um)
            dy = abs(pos["y_um"] - target_y_um)
            log.debug("MoveXY confirm: target=(%.1f, %.1f) actual=(%.1f, %.1f) "
                      "delta=(%.2f, %.2f) um", target_x_um, target_y_um,
                      pos["x_um"], pos["y_um"], dx, dy)

            if dx < tolerance and dy < tolerance:
                return {"success": True, "logs": logs,
                        "last_position": last_position}

        time.sleep(poll_interval)

    msg = (f"MoveXY timeout after {time.perf_counter() - t_start:.1f}s — "
           f"target=({target_x_um:.1f}, {target_y_um:.1f})")
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs,
            "last_position": last_position}


# =============================================================================
# Long-running confirm functions (own their polling loop)
# =============================================================================

def confirm_acquire(client, *, start_timeout=15.0, heartbeat_interval=30.0,
                    timeout=None, poll_interval=0.1):
    """Poll until acquisition completes, or return False if scan never starts.

    Pure status-polling function: reads only, never fires. When the scan
    has not started within *start_timeout*, returns ``{"success": False}``.
    Acquisition profiles fire the command once and treat that as a
    failed acquisition, not as permission to send another acquire command.

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
    t_start = time.perf_counter()
    last_heartbeat = t_start
    saw_scanning = False
    consecutive_idle = 0
    idle_streak_required = 2

    start_deadline = t_start + start_timeout
    deadline = t_start + (timeout if timeout is not None else 1e9)

    while time.perf_counter() < deadline:
        status = _readers.get_scan_status(client)
        elapsed = time.perf_counter() - t_start

        if "Idle" not in status:
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
                msg = f"Scan not started after {start_timeout:.0f}s ({elapsed:.0f}s total)"
                log.warning(msg)
                logs.append(_make_log_entry("warning", msg))
                return {"success": False, "logs": logs}

        # Heartbeat for long scans
        now = time.perf_counter()
        if now - last_heartbeat > heartbeat_interval:
            msg = f"Scanning: {status}, {elapsed:.0f}s elapsed"
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


def confirm_select_job(client, *, job_name, timeout=None,
                       poll_interval=0.01):
    """Poll until the specified job is selected, or until timeout.

    Args:
        client: The connected LAS X API client.
        job_name: Name of the job expected to become selected.
        timeout: Hard ceiling in seconds. None uses CONFIRM_TIMEOUT.
        poll_interval: Seconds between get_jobs polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    if timeout is None:
        timeout = CONFIRM_TIMEOUT
    logs = []
    t_start = time.perf_counter()
    deadline = t_start + timeout

    while time.perf_counter() < deadline:
        jobs = _readers.get_jobs(client)
        if jobs:
            for j in jobs:
                if j.get("Name") == job_name and j.get("IsSelected"):
                    return {"success": True, "logs": logs}

        time.sleep(poll_interval)

    msg = f"Job selection timeout after {timeout:.1f}s for '{job_name}'"
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}

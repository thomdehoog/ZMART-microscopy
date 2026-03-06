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

**Polling ownership:** Simple readback confirms (``_confirm_zoom``,
``_confirm_scan_speed``, etc.) do a single readback check and return
immediately — the backbone's confirm wrapper handles retry/timeout.
Long-running confirms (``confirm_acquire``, ``confirm_select_job``)
own their polling loop internally and return only when done or timed out.

**No closure factories.** The old ``_make_acquire_confirm`` and
``_make_select_job_confirm`` factories are eliminated. Confirm functions
that need polling own their loop; all state is local.

Import restrictions: only ``readers``, ``settings``, ``checks``,
``util``, and stdlib. Nothing from ``core``, ``commands``, or
``profiles``.
"""

import logging
import math
import time

from . import readers as _readers
from .settings import make_changeable_copy
from .util import _make_log_entry

log = logging.getLogger(__name__)


# =============================================================================
# Readback helper
# =============================================================================

def _readback(client, job_name):
    """Read job settings and return changeable copy, or None on failure."""
    # Clear cached settings to force fresh dispatch from LAS X
    try:
        client.PyApiGetJobSettingsByName.Model.Settings = None
    except Exception:
        log.debug("Could not clear cached settings before readback")
    raw = _readers.get_job_settings(client, job_name, timeout=5)
    if raw is None:
        return None
    return make_changeable_copy(raw)


# =============================================================================
# Confirm functions — approximate match (tolerance parameter)
# =============================================================================

ZMODE_KEY = {"galvo": "z-galvo", "zwide": "z-wide"}


def confirm_move_z(client, *, job_name, z_mode, target_um, tolerance=1.0,
                   timeout=10.0, poll_interval=0.01):
    """Poll until Z drive position is within tolerance, or until timeout.

    Owns its polling loop — the backbone calls this once with
    ``max_confirm_attempts=1``.

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        z_mode: Drive type — "galvo" or "zwide".
        target_um: Expected Z position in micrometers.
        tolerance: Acceptable deviation in micrometers.
        timeout: Hard ceiling in seconds.
        poll_interval: Seconds between position polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
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


def _confirm_zoom(client, job_name, target, tolerance=0.1):
    """Confirm zoom matches target within tolerance.

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        target: Expected zoom value.
        tolerance: Acceptable deviation.

    Returns:
        {"success": bool, "logs": [...]}
    """
    ch = _readback(client, job_name)
    if ch is None:
        return {"success": False, "logs": [_make_log_entry("warning", "Readback returned None")]}
    try:
        actual = ch["zoom"]["current"]
        ok = abs(actual - target) < tolerance
        if not ok:
            log.debug("Zoom confirm: target=%s actual=%s", target, actual)
        return {"success": ok, "logs": []}
    except (KeyError, TypeError):
        return {"success": False, "logs": [_make_log_entry("debug", "Zoom key missing from readback")]}


def _confirm_scan_field_rotation(client, job_name, target, tolerance=0.5):
    """Confirm scan field rotation matches target within tolerance (degrees).

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        target: Expected rotation angle in degrees.
        tolerance: Acceptable deviation in degrees.

    Returns:
        {"success": bool, "logs": [...]}
    """
    ch = _readback(client, job_name)
    if ch is None:
        return {"success": False, "logs": [_make_log_entry("warning", "Readback returned None")]}
    try:
        actual = ch["scanFieldRotation"]["value"]
        ok = abs(actual - target) < tolerance
        if not ok:
            log.debug("ScanFieldRotation confirm: target=%s actual=%s", target, actual)
        return {"success": ok, "logs": []}
    except (KeyError, TypeError):
        return {"success": False, "logs": [_make_log_entry("debug", "ScanFieldRotation key missing from readback")]}


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
                                tolerance=1.0):
    """Confirm z-stack begin/end positions within tolerance (micrometers).

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

    Returns:
        {"success": bool, "logs": [...]}
    """
    logs = []
    ch = _readback(client, job_name)
    if ch is None:
        logs.append(_make_log_entry("warning", "Z-stack def confirm: readback returned None"))
        return {"success": False, "logs": logs}
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
        return {"success": False, "logs": logs}
    except (KeyError, TypeError) as e:
        log.debug("Z-stack def confirm: exception %s, stack=%s", e,
                  ch.get("stack"))
        logs.append(_make_log_entry("debug", f"Z-stack def readback key error: {e}"))
        return {"success": False, "logs": logs}


def _confirm_z_stack_step_size(client, job_name, target_um, tolerance=0.5):
    """Confirm z-stack step size within tolerance (micrometers).

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        target_um: Expected step size in micrometers.
        tolerance: Acceptable deviation in micrometers.

    Returns:
        {"success": bool, "logs": [...]}
    """
    ch = _readback(client, job_name)
    if ch is None:
        return {"success": False, "logs": [_make_log_entry("warning", "Readback returned None")]}
    try:
        actual = ch["stack"]["stepSize"]
        log.debug("Z-stack step confirm: target=%.4f actual=%.6g", target_um, actual)
        ok = abs(actual - target_um) < tolerance
        return {"success": ok, "logs": []}
    except (KeyError, TypeError):
        return {"success": False, "logs": [_make_log_entry("debug", "Z-stack stepSize key missing from readback")]}


def _confirm_z_stack_size(client, job_name, target_um, tolerance=1.5):
    """Confirm z-stack total size within tolerance (micrometers).

    When LAS X is in "Z-Step Size" mode, actual size is quantised to
    an integer multiple of the step size. We accept the actual if it
    matches the target directly or matches the nearest quantised
    multiple(s), all within the base tolerance.

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        target_um: Expected total stack size in micrometers.
        tolerance: Acceptable deviation in micrometers.

    Returns:
        {"success": bool, "logs": [...]}
    """
    ch = _readback(client, job_name)
    if ch is None:
        return {"success": False, "logs": [_make_log_entry("warning", "Z-stack size confirm: readback returned None")]}
    try:
        actual = ch["stack"]["size"]
        step = ch["stack"].get("stepSize")
        log.debug("Z-stack size confirm: target=%.4f actual=%.6g step=%s",
                  target_um, actual, step)

        # Direct match (number-of-steps mode, or step divides evenly)
        if abs(actual - target_um) < tolerance:
            return {"success": True, "logs": []}

        # Quantised match: accept adjacent multiples of step size
        if step and step > 0:
            n_lo = max(1, math.floor(target_um / step))
            n_hi = max(1, math.ceil(target_um / step))
            for n in sorted({n_lo, n_hi}):
                if abs(actual - n * step) < tolerance:
                    log.debug("Z-stack size confirm: matched quantised "
                              "size %.2f (n=%d)", n * step, n)
                    return {"success": True, "logs": []}

        log.debug("Z-stack size confirm: no match")
        return {"success": False, "logs": []}
    except (KeyError, TypeError) as e:
        log.debug("Z-stack size confirm: exception %s, stack=%s", e,
                  ch.get("stack"))
        return {"success": False, "logs": [_make_log_entry("debug", f"Z-stack size readback key error: {e}")]}


def _confirm_pinhole_airy(client, job_name, si, target, tolerance=0.05):
    """Confirm pinhole size within tolerance (Airy units).

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        si: Setting index.
        target: Expected pinhole size in Airy units.
        tolerance: Acceptable deviation.

    Returns:
        {"success": bool, "logs": [...]}
    """
    ch = _readback(client, job_name)
    if ch is None:
        return {"success": False, "logs": [_make_log_entry("warning", "Readback returned None")]}
    try:
        actual = ch["activeSettings"][si]["pinholeAiry"]["value"]
        ok = abs(actual - target) < tolerance
        if not ok:
            log.debug("PinholeAiry confirm: target=%s actual=%s", target, actual)
        return {"success": ok, "logs": []}
    except (KeyError, TypeError, IndexError):
        return {"success": False, "logs": [_make_log_entry("debug", "PinholeAiry key missing from readback")]}


def _confirm_detector_gain(client, job_name, si, beam_route, target,
                           tolerance=1.0):
    """Confirm detector gain within tolerance.

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        si: Setting index.
        beam_route: Beam route identifier for the detector.
        target: Expected gain value.
        tolerance: Acceptable deviation.

    Returns:
        {"success": bool, "logs": [...]}
    """
    ch = _readback(client, job_name)
    if ch is None:
        return {"success": False, "logs": [_make_log_entry("warning", "Readback returned None")]}
    try:
        det = next(d for d in ch["activeSettings"][si]["activeDetectors"]
                   if d["_beamRoute"] == beam_route)
        actual = det["gain"]["value"]
        ok = abs(actual - target) < tolerance
        if not ok:
            log.debug("DetectorGain confirm: target=%s actual=%s", target, actual)
        return {"success": ok, "logs": []}
    except (KeyError, TypeError, IndexError, StopIteration):
        return {"success": False, "logs": [_make_log_entry("debug", "DetectorGain key missing from readback")]}


def _confirm_laser_intensity(client, job_name, si, beam_route, line_index,
                             target, tolerance=0.005):
    """Confirm laser intensity within tolerance (fraction, e.g. 0.005 = 0.5%).

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        si: Setting index.
        beam_route: Beam route identifier.
        line_index: Laser line index.
        target: Expected intensity (0.0-1.0).
        tolerance: Acceptable deviation.

    Returns:
        {"success": bool, "logs": [...]}
    """
    ch = _readback(client, job_name)
    if ch is None:
        return {"success": False, "logs": [_make_log_entry("warning", "Readback returned None")]}
    try:
        las = next(l for l in ch["activeSettings"][si]["activeLaserLines"]
                   if l["_beamRoute"] == beam_route and l["_lineIndex"] == line_index)
        actual = las["intensity"]["value"]
        ok = abs(actual - target) < tolerance
        if not ok:
            log.debug("LaserIntensity confirm: target=%s actual=%s", target, actual)
        return {"success": ok, "logs": []}
    except (KeyError, TypeError, IndexError, StopIteration):
        return {"success": False, "logs": [_make_log_entry("debug", "LaserIntensity key missing from readback")]}


def _confirm_filter_wheel_spectrum(client, job_name, si, beam_route, fw_type,
                                   target, tolerance=1):
    """Confirm filter wheel spectrum position within tolerance (nm).

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        si: Setting index.
        beam_route: Beam route identifier.
        fw_type: Filter wheel type string.
        target: Expected spectrum position in nm.
        tolerance: Acceptable deviation in nm.

    Returns:
        {"success": bool, "logs": [...]}
    """
    ch = _readback(client, job_name)
    if ch is None:
        return {"success": False, "logs": [_make_log_entry("warning", "Readback returned None")]}
    try:
        fw = next(f for f in ch["activeSettings"][si]["filterWheels"]
                  if f["_beamRoute"] == beam_route and f.get("type") == fw_type)
        actual = fw["spectrumPosition"]
        ok = abs(actual - target) < tolerance
        if not ok:
            log.debug("FilterWheelSpectrum confirm: target=%s actual=%s", target, actual)
        return {"success": ok, "logs": []}
    except (KeyError, TypeError, IndexError, StopIteration):
        return {"success": False, "logs": [_make_log_entry("debug", "FilterWheelSpectrum key missing from readback")]}


# =============================================================================
# Confirm functions — exact match (no tolerance parameter)
# =============================================================================

def _confirm_scan_speed(client, job_name, target):
    """Confirm scan speed matches exactly (discrete integer).

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        target: Expected scan speed value.

    Returns:
        {"success": bool, "logs": [...]}
    """
    ch = _readback(client, job_name)
    if ch is None:
        return {"success": False, "logs": [_make_log_entry("warning", "Readback returned None")]}
    try:
        actual = ch["scanSpeed"]["value"]
        ok = actual == target
        if not ok:
            log.debug("ScanSpeed confirm: target=%s actual=%s", target, actual)
        return {"success": ok, "logs": []}
    except (KeyError, TypeError):
        return {"success": False, "logs": [_make_log_entry("debug", "ScanSpeed key missing from readback")]}


def _confirm_scan_resonant(client, job_name, target):
    """Confirm resonant scanner state matches exactly.

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        target: Expected resonant state (bool).

    Returns:
        {"success": bool, "logs": [...]}
    """
    ch = _readback(client, job_name)
    if ch is None:
        return {"success": False, "logs": [_make_log_entry("warning", "Readback returned None")]}
    try:
        actual = ch["scanSpeed"]["isResonant"]
        ok = actual == target
        if not ok:
            log.debug("ScanResonant confirm: target=%s actual=%s", target, actual)
        return {"success": ok, "logs": []}
    except (KeyError, TypeError):
        return {"success": False, "logs": [_make_log_entry("debug", "ScanResonant key missing from readback")]}


def _confirm_scan_mode(client, job_name, target):
    """Confirm scan mode matches exactly (enum string).

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        target: Expected scan mode string (e.g. "xyz").

    Returns:
        {"success": bool, "logs": [...]}
    """
    ch = _readback(client, job_name)
    if ch is None:
        return {"success": False, "logs": [_make_log_entry("warning", "Readback returned None")]}
    try:
        actual = ch["scanMode"]
        ok = actual == target
        if not ok:
            log.debug("ScanMode confirm: target=%s actual=%s", target, actual)
        return {"success": ok, "logs": []}
    except (KeyError, TypeError):
        return {"success": False, "logs": [_make_log_entry("debug", "ScanMode key missing from readback")]}


def _confirm_sequential_mode(client, job_name, target):
    """Confirm sequential mode matches exactly (enum string).

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        target: Expected sequential mode string.

    Returns:
        {"success": bool, "logs": [...]}
    """
    ch = _readback(client, job_name)
    if ch is None:
        return {"success": False, "logs": [_make_log_entry("warning", "Readback returned None")]}
    try:
        actual = ch["sequentialMode"]
        ok = actual == target
        if not ok:
            log.debug("SequentialMode confirm: target=%s actual=%s", target, actual)
        return {"success": ok, "logs": []}
    except (KeyError, TypeError):
        return {"success": False, "logs": [_make_log_entry("debug", "SequentialMode key missing from readback")]}


def _confirm_image_format(client, job_name, w, h):
    """Confirm image format matches exactly (pixel dimensions).

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        w: Expected width in pixels.
        h: Expected height in pixels.

    Returns:
        {"success": bool, "logs": [...]}
    """
    ch = _readback(client, job_name)
    if ch is None:
        return {"success": False, "logs": [_make_log_entry("warning", "Readback returned None")]}
    try:
        actual = ch["format"]
        ok = actual == f"{w} x {h}"
        if not ok:
            log.debug("ImageFormat confirm: target='%s x %s' actual='%s'", w, h, actual)
        return {"success": ok, "logs": []}
    except (KeyError, TypeError):
        return {"success": False, "logs": [_make_log_entry("debug", "ImageFormat key missing from readback")]}


def confirm_objective(client, *, job_name, target_name,
                      timeout=10.0, poll_interval=0.01):
    """Poll until objective matches target, or until timeout.

    Owns its polling loop — the backbone calls this once with
    ``max_confirm_attempts=1``. Objective turret rotation is mechanical
    and can take several seconds.

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        target_name: Expected objective name string.
        timeout: Hard ceiling in seconds.
        poll_interval: Seconds between readback polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    logs = []
    t_start = time.perf_counter()
    deadline = t_start + timeout

    while time.perf_counter() < deadline:
        ch = _readback(client, job_name)
        if ch is not None:
            try:
                actual = ch["objective"]["name"].strip()
                log.debug("Objective confirm: target='%s' actual='%s'",
                          target_name.strip(), actual)
                if actual == target_name.strip():
                    return {"success": True, "logs": logs}
            except (KeyError, TypeError, AttributeError):
                pass

        time.sleep(poll_interval)

    msg = (f"Objective timeout after {time.perf_counter() - t_start:.1f}s — "
           f"target='{target_name.strip()}'")
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}


def _confirm_frame_accumulation(client, job_name, si, target):
    """Confirm frame accumulation matches exactly.

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        si: Setting index.
        target: Expected accumulation count.

    Returns:
        {"success": bool, "logs": [...]}
    """
    ch = _readback(client, job_name)
    if ch is None:
        return {"success": False, "logs": [_make_log_entry("warning", "Readback returned None")]}
    try:
        actual = ch["activeSettings"][si]["frameAccumulation"]
        ok = actual == target
        if not ok:
            log.debug("FrameAccumulation confirm: target=%s actual=%s", target, actual)
        return {"success": ok, "logs": []}
    except (KeyError, TypeError, IndexError):
        return {"success": False, "logs": [_make_log_entry("debug", "FrameAccumulation key missing from readback")]}


def _confirm_frame_average(client, job_name, si, target):
    """Confirm frame average matches exactly.

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        si: Setting index.
        target: Expected average count.

    Returns:
        {"success": bool, "logs": [...]}
    """
    ch = _readback(client, job_name)
    if ch is None:
        return {"success": False, "logs": [_make_log_entry("warning", "Readback returned None")]}
    try:
        actual = ch["activeSettings"][si]["frameAverage"]
        ok = actual == target
        if not ok:
            log.debug("FrameAverage confirm: target=%s actual=%s", target, actual)
        return {"success": ok, "logs": []}
    except (KeyError, TypeError, IndexError):
        return {"success": False, "logs": [_make_log_entry("debug", "FrameAverage key missing from readback")]}


def _confirm_line_accumulation(client, job_name, si, target):
    """Confirm line accumulation matches exactly.

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        si: Setting index.
        target: Expected accumulation count.

    Returns:
        {"success": bool, "logs": [...]}
    """
    ch = _readback(client, job_name)
    if ch is None:
        return {"success": False, "logs": [_make_log_entry("warning", "Readback returned None")]}
    try:
        actual = ch["activeSettings"][si]["lineAccumulation"]
        ok = actual == target
        if not ok:
            log.debug("LineAccumulation confirm: target=%s actual=%s", target, actual)
        return {"success": ok, "logs": []}
    except (KeyError, TypeError, IndexError):
        return {"success": False, "logs": [_make_log_entry("debug", "LineAccumulation key missing from readback")]}


def _confirm_line_average(client, job_name, si, target):
    """Confirm line average matches exactly.

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        si: Setting index.
        target: Expected average count.

    Returns:
        {"success": bool, "logs": [...]}
    """
    ch = _readback(client, job_name)
    if ch is None:
        return {"success": False, "logs": [_make_log_entry("warning", "Readback returned None")]}
    try:
        actual = ch["activeSettings"][si]["lineAverage"]
        ok = actual == target
        if not ok:
            log.debug("LineAverage confirm: target=%s actual=%s", target, actual)
        return {"success": ok, "logs": []}
    except (KeyError, TypeError, IndexError):
        return {"success": False, "logs": [_make_log_entry("debug", "LineAverage key missing from readback")]}


def _confirm_laser_shutter(client, job_name, si, beam_route, target):
    """Confirm laser shutter state matches exactly.

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        si: Setting index.
        beam_route: Beam route identifier.
        target: Expected shutter state (bool).

    Returns:
        {"success": bool, "logs": [...]}
    """
    ch = _readback(client, job_name)
    if ch is None:
        return {"success": False, "logs": [_make_log_entry("warning", "Readback returned None")]}
    try:
        las = next(l for l in ch["activeSettings"][si]["activeLaserLines"]
                   if l["_beamRoute"] == beam_route)
        actual = las["shutterOpen"]
        ok = actual == target
        if not ok:
            log.debug("LaserShutter confirm: target=%s actual=%s", target, actual)
        return {"success": ok, "logs": []}
    except (KeyError, TypeError, IndexError, StopIteration):
        return {"success": False, "logs": [_make_log_entry("debug", "LaserShutter key missing from readback")]}


def _confirm_filter_wheel_slot(client, job_name, si, beam_route, fw_type,
                               target):
    """Confirm filter wheel slot matches exactly.

    Args:
        client: The connected LAS X API client.
        job_name: Target job name.
        si: Setting index.
        beam_route: Beam route identifier.
        fw_type: Filter wheel type string.
        target: Expected slot index.

    Returns:
        {"success": bool, "logs": [...]}
    """
    ch = _readback(client, job_name)
    if ch is None:
        return {"success": False, "logs": [_make_log_entry("warning", "Readback returned None")]}
    try:
        fw = next(f for f in ch["activeSettings"][si]["filterWheels"]
                  if f["_beamRoute"] == beam_route and f.get("type") == fw_type)
        actual = fw["filterIndex"]
        ok = actual == target
        if not ok:
            log.debug("FilterWheelSlot confirm: target=%s actual=%s", target, actual)
        return {"success": ok, "logs": []}
    except (KeyError, TypeError, IndexError, StopIteration):
        return {"success": False, "logs": [_make_log_entry("debug", "FilterWheelSlot key missing from readback")]}


# =============================================================================
# XY position confirmation
# =============================================================================

def confirm_move_xy(client, *, target_x_um, target_y_um, tolerance=20.0,
                    timeout=10.0, poll_interval=0.01):
    """Poll until XY stage position is within tolerance, or until timeout.

    Owns its polling loop — the backbone calls this once with
    ``max_confirm_attempts=1``.

    Args:
        client: The connected LAS X API client.
        target_x_um: Expected X position in micrometers.
        target_y_um: Expected Y position in micrometers.
        tolerance: Acceptable deviation in micrometers per axis.
        timeout: Hard ceiling in seconds.
        poll_interval: Seconds between position polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
    logs = []
    t_start = time.perf_counter()
    deadline = t_start + timeout

    while time.perf_counter() < deadline:
        pos = _readers.get_xy(client, timeout=5)
        if pos is not None:
            dx = abs(pos["x_um"] - target_x_um)
            dy = abs(pos["y_um"] - target_y_um)
            log.debug("MoveXY confirm: target=(%.1f, %.1f) actual=(%.1f, %.1f) "
                      "delta=(%.2f, %.2f) um", target_x_um, target_y_um,
                      pos["x_um"], pos["y_um"], dx, dy)

            if dx < tolerance and dy < tolerance:
                return {"success": True, "logs": logs}

        time.sleep(poll_interval)

    msg = (f"MoveXY timeout after {time.perf_counter() - t_start:.1f}s — "
           f"target=({target_x_um:.1f}, {target_y_um:.1f})")
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}


# =============================================================================
# Long-running confirm functions (own their polling loop)
# =============================================================================

def confirm_acquire(client, *, settle_time=0.5, start_timeout=15.0,
                    heartbeat_interval=30.0, timeout=None,
                    poll_interval=0.1):
    """Poll until acquisition completes, or until timeout is exceeded.

    Owns its polling loop internally — the backbone calls this once and
    gets back a result dict. All state (saw_scanning, timing) is local
    to this function call.

    Logic:
        - Idle is only accepted as "scan complete" if we either observed
          a non-idle status at least once (saw_scanning) or settle_time
          has elapsed. This prevents mistaking "was already idle" for
          "scan finished instantly."
        - If the scan never starts within start_timeout, a warning is
          logged once. The timeout parameter is the hard ceiling.
        - Heartbeat logs are emitted at heartbeat_interval during long
          scans so operators know the system is not hung.

    Args:
        client: The connected LAS X API client.
        settle_time: Minimum seconds after entry before accepting idle
            as completion. Prevents race when scan finishes faster than
            the first poll.
        start_timeout: Seconds to wait for scan to start before logging
            a diagnostic warning. Not a hard ceiling.
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
    start_warning_logged = False

    # Use a very large deadline if timeout is None (effectively infinite)
    deadline = t_start + (timeout if timeout is not None else 1e9)

    while time.perf_counter() < deadline:
        status = _readers.get_scan_status(client)
        elapsed = time.perf_counter() - t_start

        if "Idle" not in status:
            saw_scanning = True

        # Heartbeat for long scans
        now = time.perf_counter()
        if now - last_heartbeat > heartbeat_interval:
            msg = f"Scanning: {status}, {elapsed:.0f}s elapsed"
            log.info(msg)
            logs.append(_make_log_entry("info", msg))
            last_heartbeat = now

        # Start-timeout warning: log when the scan never starts
        if (not saw_scanning and elapsed > start_timeout
                and not start_warning_logged):
            msg = f"Scan never started after {elapsed:.0f}s — still waiting"
            log.warning(msg)
            logs.append(_make_log_entry("warning", msg))
            start_warning_logged = True

        # Completion: idle AND (saw scanning OR settle time elapsed)
        if "Idle" in status:
            if saw_scanning or elapsed > settle_time:
                return {"success": True, "logs": logs}

        time.sleep(poll_interval)

    # Timeout exceeded
    msg = f"Acquisition timeout after {time.perf_counter() - t_start:.1f}s"
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs}


def confirm_select_job(client, *, job_name, timeout=10.0,
                       poll_interval=0.01):
    """Poll until the specified job is selected, or until timeout.

    Args:
        client: The connected LAS X API client.
        job_name: Name of the job expected to become selected.
        timeout: Hard ceiling in seconds for the entire operation.
        poll_interval: Seconds between get_jobs polls.

    Returns:
        {"success": bool, "logs": [...]}
    """
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

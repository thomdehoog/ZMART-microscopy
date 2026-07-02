"""
Command wrappers.
=================
Public write commands: stage movement (absolute / relative / convenience
per-axis), motion control (stop / zero), and instrument-state settings (filter,
zoom, laser, intensity, shutter, ETL). Each follows the three-phase pattern:

    Phase A -- pre-checks: validate axes/values, convert units, check limits.
    Phase B -- backbone: build a ``fire_fn`` (sends one protocol request) and a
        target-bound ``confirm_fn`` (reads state back with the freshness gate),
        then call ``confirm_and_fire``.
    Phase C -- the standard result envelope is returned as-is.

Unit rule: linear axes are micrometers, ``theta`` is degrees, on the public API
and the wire. Limit checks happen HERE, before the fire.

Acquisition (snap / run list) lives in :mod:`mesospim.acquisition`, not here --
these wrappers cover control, not capture.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import logging
from functools import partial

from ..config.limits import LimitError, check_move
from ..config.profiles import MOVE, MOVE_ROTATION, SET_STATE
from ..readers.readers import _reading_value_after, get_positions, get_state
from ..utils import AXES, _make_log_entry, _make_timing, _safe_float
from .dispatch import confirm_and_fire

log = logging.getLogger(__name__)


# =============================================================================
# Confirmation helpers
# =============================================================================


def _confirm_positions(client, targets, tolerance, *, observed_after):
    """Confirm that every target axis reads back within ``tolerance``."""
    reading = get_positions(client, diagnostics=True)
    positions = _reading_value_after(reading, observed_after)
    if positions is None:
        return {"confirmed": False, "reason": "stale readback"}
    for axis, want in targets.items():
        got = _safe_float(positions.get(axis))
        if got is None or abs(got - float(want)) > tolerance:
            return {"confirmed": False, "position": positions}
    return {"confirmed": True, "position": positions}


def _confirm_state_keys(client, wanted, *, observed_after):
    """Confirm that every key in ``wanted`` reads back equal in the state dict."""
    reading = get_state(client, diagnostics=True)
    state = _reading_value_after(reading, observed_after)
    if state is None:
        return {"confirmed": False, "reason": "stale readback"}
    for key, want in wanted.items():
        got = state.get(key)
        # Numeric fields compare with a small tolerance; the rest exact.
        if isinstance(want, (int, float)) and isinstance(got, (int, float)):
            if abs(float(got) - float(want)) > 1e-6:
                return {"confirmed": False, "state": {k: state.get(k) for k in wanted}}
        elif got != want:
            return {"confirmed": False, "state": {k: state.get(k) for k in wanted}}
    return {"confirmed": True, "state": {k: state.get(k) for k in wanted}}


# =============================================================================
# Movement
# =============================================================================


def _validate_targets(targets: dict) -> dict:
    clean = {}
    for axis, value in targets.items():
        if axis not in AXES:
            raise ValueError(f"unknown axis {axis!r}; known axes: {AXES}")
        clean[axis] = float(value)
    if not clean:
        raise ValueError("no axes to move")
    return clean


def move_absolute(client, targets: dict, *, tolerance: float | None = None) -> dict:
    """Move one or more axes to absolute targets (um / deg), from the origin.

    ``targets`` is ``{axis: value}`` over any of ``x, y, z, f, theta``. Limits
    are checked before firing; a violation returns a failed envelope without
    touching the stage.
    """
    try:
        clean = _validate_targets(targets)
        check_move(clean)
    except (ValueError, LimitError) as exc:
        return _fail(f"move_absolute {targets}", str(exc))

    profile = MOVE_ROTATION if set(clean) <= {"theta"} else MOVE
    tol = tolerance if tolerance is not None else profile.confirm_tolerance
    label = "move_absolute " + ",".join(f"{a}={v}" for a, v in clean.items())
    return confirm_and_fire(
        client,
        label,
        profile,
        fire_fn=lambda: client.request("move_absolute", targets=clean),
        confirm_fn=partial(_confirm_positions, targets=clean, tolerance=tol),
    )


def move_relative(client, deltas: dict, *, tolerance: float | None = None) -> dict:
    """Move one or more axes by relative offsets (um / deg).

    The expected absolute target (current + delta) is limit-checked before
    firing and used for readback confirmation.
    """
    try:
        clean = _validate_targets(deltas)
    except ValueError as exc:
        return _fail(f"move_relative {deltas}", str(exc))

    baseline = get_positions(client)
    expected = {}
    for axis, delta in clean.items():
        base = _safe_float(baseline.get(axis))
        if base is None:
            return _fail(f"move_relative {deltas}", f"cannot read baseline for axis {axis!r}")
        expected[axis] = base + delta
    try:
        check_move(expected)
    except LimitError as exc:
        return _fail(f"move_relative {deltas}", str(exc))

    profile = MOVE_ROTATION if set(clean) <= {"theta"} else MOVE
    tol = tolerance if tolerance is not None else profile.confirm_tolerance
    label = "move_relative " + ",".join(f"{a}={v:+}" for a, v in clean.items())
    return confirm_and_fire(
        client,
        label,
        profile,
        fire_fn=lambda: client.request("move_relative", deltas=clean),
        confirm_fn=partial(_confirm_positions, targets=expected, tolerance=tol),
    )


def move_xy(client, x: float, y: float, *, tolerance: float | None = None) -> dict:
    """Move the linear stage in X and Y (um)."""
    return move_absolute(client, {"x": x, "y": y}, tolerance=tolerance)


def move_z(client, z: float, *, tolerance: float | None = None) -> dict:
    """Move the sample Z axis (um)."""
    return move_absolute(client, {"z": z}, tolerance=tolerance)


def move_focus(client, f: float, *, tolerance: float | None = None) -> dict:
    """Move the focus (detection) axis (um)."""
    return move_absolute(client, {"f": f}, tolerance=tolerance)


def move_rotation(client, theta: float, *, tolerance: float | None = None) -> dict:
    """Rotate the sample (degrees)."""
    return move_absolute(client, {"theta": theta}, tolerance=tolerance)


def stop(client) -> dict:
    """Halt all stage motion immediately (no confirmation)."""
    return confirm_and_fire(
        client, "stop", MOVE, fire_fn=lambda: client.request("stop"), confirm_fn=None
    )


def zero_axes(client, axes: list[str] | None = None) -> dict:
    """Define the current position of ``axes`` as zero (mesoSPIM ``zero_axes``).

    ``axes=None`` zeroes every axis. This sets the *instrument*-side zero; the
    ZMART controller frame origin is handled separately in the controller
    adapter.
    """
    axes = list(axes) if axes is not None else list(AXES)
    for axis in axes:
        if axis not in AXES:
            return _fail("zero_axes", f"unknown axis {axis!r}")
    return confirm_and_fire(
        client,
        f"zero_axes {axes}",
        MOVE,
        fire_fn=lambda: client.request("zero", axes=axes),
        confirm_fn=None,
    )


# =============================================================================
# Instrument-state settings (via sig_state_request on the server)
# =============================================================================


def set_state(client, settings: dict) -> dict:
    """Apply a batch of mesoSPIM state settings and confirm the readback.

    ``settings`` keys are mesoSPIM state keys (``filter``, ``zoom``, ``laser``,
    ``intensity``, ``shutterconfig``, ``etl_l_amplitude``, ...). The server
    applies them via ``sig_state_request_and_wait_until_done``; confirmation
    reads the same keys back.
    """
    if not settings:
        return _fail("set_state", "no settings given")
    label = "set_state " + ",".join(f"{k}={v}" for k, v in settings.items())
    return confirm_and_fire(
        client,
        label,
        SET_STATE,
        fire_fn=lambda: client.request("set_state", settings=dict(settings)),
        confirm_fn=partial(_confirm_state_keys, wanted=dict(settings)),
    )


def set_filter(client, name: str) -> dict:
    """Select an emission filter by name."""
    return set_state(client, {"filter": name})


def set_zoom(client, name: str) -> dict:
    """Select a zoom setting by name (e.g. ``"1x"``)."""
    return set_state(client, {"zoom": name})


def set_laser(client, laser: str) -> dict:
    """Select the active laser line by name (e.g. ``"488 nm"``)."""
    return set_state(client, {"laser": laser})


def set_intensity(client, intensity: float) -> dict:
    """Set the active laser intensity (0-100 %)."""
    if not 0 <= float(intensity) <= 100:
        return _fail("set_intensity", f"intensity {intensity} out of range [0, 100]")
    return set_state(client, {"intensity": float(intensity)})


def set_shutter(client, shutterconfig: str) -> dict:
    """Select the light-sheet shutter configuration (``Left`` / ``Right`` / ``Both``)."""
    return set_state(client, {"shutterconfig": shutterconfig})


def set_etl(
    client,
    side: str,
    *,
    amplitude: float | None = None,
    offset: float | None = None,
) -> dict:
    """Set the electrically tunable lens parameters for one sheet side.

    ``side`` is ``"left"`` or ``"right"``; either ``amplitude`` or ``offset``
    (or both) may be given.
    """
    side = side.lower()
    if side not in ("left", "right"):
        return _fail("set_etl", f"side must be 'left' or 'right', got {side!r}")
    prefix = "etl_l" if side == "left" else "etl_r"
    settings = {}
    if amplitude is not None:
        settings[f"{prefix}_amplitude"] = float(amplitude)
    if offset is not None:
        settings[f"{prefix}_offset"] = float(offset)
    if not settings:
        return _fail("set_etl", "give amplitude and/or offset")
    return set_state(client, settings)


# =============================================================================
# helpers
# =============================================================================


def _fail(label: str, message: str) -> dict:
    """A pre-fire failure envelope (validation / limits), no request sent."""
    return {
        "success": False,
        "confirmed": None,
        "message": f"{label}: {message}",
        "data": {},
        "timing": _make_timing(total_s=0.0, attempts=0),
        "logs": [_make_log_entry("error", f"{label}: {message}")],
    }


__all__ = [
    "move_absolute",
    "move_relative",
    "move_xy",
    "move_z",
    "move_focus",
    "move_rotation",
    "stop",
    "zero_axes",
    "set_state",
    "set_filter",
    "set_zoom",
    "set_laser",
    "set_intensity",
    "set_shutter",
    "set_etl",
]

"""
Stage movement.
===============
Public write commands that move the stage: absolute / relative moves, the
per-axis convenience wrappers (``move_xy`` / ``move_z`` / ``move_focus`` /
``move_rotation``), an immediate ``stop``, and instrument-side ``zero_axes``.
Each move follows the three-phase pattern shared across the driver:

    Phase A -- pre-checks: validate axes/values, check the stage limits
        (:mod:`mesospim.motion.limits`).
    Phase B -- backbone: build a ``fire_fn`` (one protocol request) and a
        target-bound ``confirm_fn`` (reads position back with the freshness
        gate), then call ``confirm_and_fire`` (the dispatch backbone).
    Phase C -- the standard result envelope is returned as-is.

Unit rule: linear axes are micrometers, ``theta`` is degrees, on the public API
and the wire. Limit checks happen HERE, before the fire.

Sibling: instrument-state settings (filter / zoom / laser / intensity / shutter
/ ETL) live in :mod:`mesospim.commands.commands`; acquisition lives in
:mod:`mesospim.acquisition`.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import logging
from functools import partial

from ..commands.dispatch import confirm_and_fire
from ..config.profiles import MOVE, MOVE_ROTATION
from ..readers.readers import _reading_value_after, get_positions
from ..utils import AXES, _fail, _safe_float
from .limits import LimitError, check_move

log = logging.getLogger(__name__)


# =============================================================================
# Confirmation
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

    # A pre-fire failure returns the standard envelope, like every sibling:
    # a dropped link here must not escape as a raw exception.
    try:
        baseline = get_positions(client)
    except (ConnectionError, OSError, RuntimeError) as exc:
        return _fail(f"move_relative {deltas}", f"could not read baseline positions: {exc}")
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


__all__ = [
    "move_absolute",
    "move_relative",
    "move_xy",
    "move_z",
    "move_focus",
    "move_rotation",
    "stop",
    "zero_axes",
]

"""
Stage safety limits.
====================
Hard safety limits for the five mesoSPIM axes (x, y, z, focus in micrometers;
theta in degrees). Like the Leica/ZEN drivers, a module-level dict holds the
active limits; :func:`set_stage_limits` must configure them before any move, and
:func:`check_move` raises immediately (Phase A of the command wrappers) when a
target is out of range.

The mutable module-level state is intentional: limits are set once at session
start and shared across all command calls on the process.

A move dict is validated per axis, so a partial move (e.g. only ``x``) only
checks the axes it touches.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..utils import AXES

# axis -> (min, max); None means "not configured".
_stage_limits: dict[str, tuple[float, float] | None] = {axis: None for axis in AXES}


class LimitError(RuntimeError):
    """A move target is outside the configured safety limits."""


def set_stage_limits(**axis_limits: tuple[float, float]) -> None:
    """Configure hard safety limits per axis, e.g. ``x=(0, 20000)``.

    Only the named axes are updated; unspecified axes keep their current value.
    Each value is a ``(min, max)`` pair. Raises ``ValueError`` for an unknown
    axis or a ``min > max`` pair.
    """
    for axis, bounds in axis_limits.items():
        if axis not in _stage_limits:
            raise ValueError(f"unknown axis {axis!r}; known axes: {AXES}")
        low, high = float(bounds[0]), float(bounds[1])
        if low > high:
            raise ValueError(f"axis {axis!r} limit has min > max: {bounds!r}")
        _stage_limits[axis] = (low, high)


def get_stage_limits() -> dict[str, tuple[float, float] | None]:
    """Return a copy of the current stage limits."""
    return dict(_stage_limits)


def clear_stage_limits() -> None:
    """Reset every axis to unconfigured (used by tests)."""
    for axis in _stage_limits:
        _stage_limits[axis] = None


def check_axis(axis: str, value: float) -> None:
    """Validate one absolute axis target. Raises :class:`LimitError`.

    Fails **closed**, like the Leica ``navigator_expert`` sibling: an axis with
    no configured limit is rejected rather than silently allowed, so a forgotten
    ``set_stage_limits`` / ``apply_stage_limits_from_config`` can never let an
    unbounded move reach a mounted sample. Configure limits at session start
    (the controller does this automatically in ``controller.connect``).
    """
    bounds = _stage_limits.get(axis)
    if bounds is None:
        raise LimitError(
            f"no stage limits configured for axis {axis!r}; call set_stage_limits() "
            f"or apply_stage_limits_from_config() before moving"
        )
    low, high = bounds
    if value < low or value > high:
        raise LimitError(f"{axis}={value} outside limits [{low}, {high}]")


def check_move(targets: dict[str, float]) -> None:
    """Validate an absolute move dict (``{axis: value}``) axis by axis."""
    for axis, value in targets.items():
        check_axis(axis, float(value))


def apply_stage_limits_from_config(stage_cfg: dict[str, Any]) -> None:
    """Configure limits from a ``{"axes": {axis: [min, max]}}`` dict.

    This is the shape produced by :func:`load_stage_config`; pass it once at
    session start so notebooks and workflows share one source of truth.
    """
    axes = stage_cfg["axes"]
    set_stage_limits(**{axis: (bounds[0], bounds[1]) for axis, bounds in axes.items()})


# -- persisted stage config ---------------------------------------------------

_SCHEMA_VERSION = 1


def defaults_path() -> Path:
    """Path to the bundled default stage envelope."""
    return Path(__file__).resolve().parent / "stage_limits.json"


def load_stage_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load a stage-limits config file into ``{"axes": {axis: [min, max]}}``.

    Validates the schema version and that every axis is a ``[min, max]`` pair
    with ``min <= max``. Defaults to the bundled envelope.
    """
    selected = Path(path) if path is not None else defaults_path()
    with selected.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if payload.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError(
            f"unsupported stage-limits schema_version "
            f"{payload.get('schema_version')!r} in {selected}"
        )
    axes = payload.get("axes")
    if not isinstance(axes, dict):
        raise ValueError(f"{selected} missing 'axes' object")
    out: dict[str, list[float]] = {}
    for axis, bounds in axes.items():
        if axis not in _stage_limits:
            raise ValueError(f"{selected} has unknown axis {axis!r}")
        if not isinstance(bounds, list) or len(bounds) != 2:
            raise ValueError(f"{selected} axis {axis!r} must be [min, max], got {bounds!r}")
        low, high = float(bounds[0]), float(bounds[1])
        if low > high:
            raise ValueError(f"{selected} axis {axis!r} has min > max: {bounds!r}")
        out[axis] = [low, high]
    return {"axes": out, "source": payload.get("source", "defaults")}

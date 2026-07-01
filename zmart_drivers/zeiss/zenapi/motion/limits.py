"""
Stage safety limits.
====================
Hard safety limits for XY and Z stage movement (micrometers).

Guards against out-of-range stage moves via a module-level dict
(``_stage_limits``) that must be configured via ``set_stage_limits()`` before
any ``move_xy`` / ``move_z``. The validation functions ``_check_xy_limits`` and
``_check_z_limits`` raise ``RuntimeError`` immediately -- they run in Phase A of
the command wrappers, in micrometers, BEFORE any meters conversion or RPC.

Unlike the Leica confocal (dual galvo/wide Z), ZEN light microscopy has a
single focus (Z) axis, so limits are a flat XY + Z envelope.

The mutable module-level state is intentional: limits are set once at session
start and shared across all command calls.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

_stage_limits = {
    "x_min": None,
    "x_max": None,
    "y_min": None,
    "y_max": None,
    "z_min": None,
    "z_max": None,
}


def set_stage_limits(*, x_min, x_max, y_min, y_max, z_min, z_max) -> None:
    """Configure hard safety limits for stage movement (micrometers)."""
    _stage_limits.update(
        x_min=x_min, x_max=x_max, y_min=y_min, y_max=y_max, z_min=z_min, z_max=z_max
    )


def get_stage_limits() -> dict:
    """Return current stage limits as a dict (copy)."""
    return dict(_stage_limits)


def apply_stage_limits_from_config(stage_cfg: dict) -> None:
    """Configure stage limits from a stage_config dict.

    The dict shape is the one produced by
    :func:`zenapi.motion.stage_config.load`; pass it through once at session
    start so notebooks and calibration share one source of truth.
    """
    lim = stage_cfg["stage_um"]
    set_stage_limits(
        x_min=lim["x"][0],
        x_max=lim["x"][1],
        y_min=lim["y"][0],
        y_max=lim["y"][1],
        z_min=lim["z"][0],
        z_max=lim["z"][1],
    )


def _check_xy_limits(x, y) -> None:
    """Validate XY position (µm) against configured limits. Raises RuntimeError."""
    if _stage_limits["x_min"] is None:
        raise RuntimeError("Stage limits not configured. Call set_stage_limits() first.")
    if x < _stage_limits["x_min"] or x > _stage_limits["x_max"]:
        raise RuntimeError(
            f"X={x} outside limits [{_stage_limits['x_min']}, {_stage_limits['x_max']}]"
        )
    if y < _stage_limits["y_min"] or y > _stage_limits["y_max"]:
        raise RuntimeError(
            f"Y={y} outside limits [{_stage_limits['y_min']}, {_stage_limits['y_max']}]"
        )


def _check_z_limits(z) -> None:
    """Validate Z position (µm) against configured limits. Raises RuntimeError."""
    if _stage_limits["z_min"] is None:
        raise RuntimeError("Stage limits not configured. Call set_stage_limits() first.")
    if z < _stage_limits["z_min"] or z > _stage_limits["z_max"]:
        raise RuntimeError(
            f"Z={z} outside limits [{_stage_limits['z_min']}, {_stage_limits['z_max']}]"
        )

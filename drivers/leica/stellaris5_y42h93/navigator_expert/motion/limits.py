"""
Stage safety limits.
====================
Hard safety limits for XY and Z stage movement (micrometers).

This module guards against out-of-range stage moves by maintaining a
module-level dict (``_stage_limits``) that must be configured via
``set_stage_limits()`` before any ``move_xy`` or ``move_z`` command.
The validation functions ``_check_xy_limits`` and ``_check_z_limits``
raise ``RuntimeError`` (or ``ValueError``) immediately â€” they are
called in Phase A of the command wrappers, before the backbone fires.

The mutable module-level state is intentional: limits are set once at
session start and shared across all command calls.

Dependency direction:
    - Imports: stdlib only (no driver imports).
    - Imported by: ``commands`` (for Phase A limit checks),
      ``__init__`` (re-export).
"""

# =============================================================================
# Stage limits
# =============================================================================

_stage_limits = {
    "x_min": None,
    "x_max": None,
    "y_min": None,
    "y_max": None,
    "z_galvo_min": None,
    "z_galvo_max": None,
    "z_wide_min": None,
    "z_wide_max": None,
}


def set_stage_limits(
    *, x_min, x_max, y_min, y_max, z_galvo_min, z_galvo_max, z_wide_min, z_wide_max
):
    """Configure hard safety limits for stage movement (micrometers)."""
    _stage_limits.update(
        x_min=x_min,
        x_max=x_max,
        y_min=y_min,
        y_max=y_max,
        z_galvo_min=z_galvo_min,
        z_galvo_max=z_galvo_max,
        z_wide_min=z_wide_min,
        z_wide_max=z_wide_max,
    )


def get_stage_limits():
    """Return current stage limits as a dict (copy)."""
    return dict(_stage_limits)


def apply_stage_limits_from_config(stage_cfg: dict) -> None:
    """Configure stage limits from a stage_config dict.

    The dict shape is the one produced by
    :func:`navigator_expert.motion.config.load`; pass it through
    once at session start so the cookbook and calibration share one
    source of truth.
    """
    lim = stage_cfg["stage_um"]
    set_stage_limits(
        x_min=lim["x"][0],
        x_max=lim["x"][1],
        y_min=lim["y"][0],
        y_max=lim["y"][1],
        z_galvo_min=lim["z_galvo"][0],
        z_galvo_max=lim["z_galvo"][1],
        z_wide_min=lim["z_wide"][0],
        z_wide_max=lim["z_wide"][1],
    )


def _check_xy_limits(x, y):
    """Validate XY position against configured limits. Raises RuntimeError."""
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


def _check_z_limits(z, z_mode):
    """Validate Z position against configured limits.

    Raises:
        RuntimeError: If limits are not configured or z is out of range.
        ValueError: If z_mode is not recognized.
    """
    if _stage_limits["z_galvo_min"] is None:
        raise RuntimeError("Stage limits not configured. Call set_stage_limits() first.")
    if z_mode == "galvo":
        if z < _stage_limits["z_galvo_min"] or z > _stage_limits["z_galvo_max"]:
            raise RuntimeError(
                f"Z={z} outside galvo limits [{_stage_limits['z_galvo_min']}, "
                f"{_stage_limits['z_galvo_max']}]"
            )
    elif z_mode == "zwide":
        if z < _stage_limits["z_wide_min"] or z > _stage_limits["z_wide_max"]:
            raise RuntimeError(
                f"Z={z} outside zwide limits [{_stage_limits['z_wide_min']}, "
                f"{_stage_limits['z_wide_max']}]"
            )
    else:
        raise ValueError(f"Unknown z_mode '{z_mode}'. Use: 'galvo' or 'zwide'")

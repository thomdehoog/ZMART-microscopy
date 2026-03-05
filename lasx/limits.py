"""
Stage safety limits.
====================
Hard safety limits for XY and Z stage movement (micrometers).
Must be configured via set_stage_limits() before any move commands.
"""

# =============================================================================
# Stage limits
# =============================================================================

_stage_limits = {
    "x_min": None, "x_max": None,
    "y_min": None, "y_max": None,
    "z_galvo_min": None, "z_galvo_max": None,
    "z_wide_min": None, "z_wide_max": None,
}


def set_stage_limits(*, x_min, x_max, y_min, y_max,
                     z_galvo_min, z_galvo_max, z_wide_min, z_wide_max):
    """Configure hard safety limits for stage movement (micrometers)."""
    _stage_limits.update(
        x_min=x_min, x_max=x_max,
        y_min=y_min, y_max=y_max,
        z_galvo_min=z_galvo_min, z_galvo_max=z_galvo_max,
        z_wide_min=z_wide_min, z_wide_max=z_wide_max,
    )


def get_stage_limits():
    """Return current stage limits as a dict (copy)."""
    return dict(_stage_limits)


def _check_xy_limits(x, y):
    """Validate XY position against configured limits. Raises RuntimeError."""
    if _stage_limits["x_min"] is None:
        raise RuntimeError("Stage limits not configured. Call set_stage_limits() first.")
    if x < _stage_limits["x_min"] or x > _stage_limits["x_max"]:
        raise RuntimeError(
            f"X={x} outside limits [{_stage_limits['x_min']}, {_stage_limits['x_max']}]")
    if y < _stage_limits["y_min"] or y > _stage_limits["y_max"]:
        raise RuntimeError(
            f"Y={y} outside limits [{_stage_limits['y_min']}, {_stage_limits['y_max']}]")


def _check_z_limits(z, z_mode):
    """Validate Z position against configured limits.

    Raises:
        RuntimeError: If limits are not configured or z is out of range.
        ValueError: If z_mode is not recognized.
    """
    if _stage_limits["z_galvo_min"] is None:
        raise RuntimeError(
            "Stage limits not configured. Call set_stage_limits() first.")
    if z_mode == "galvo":
        if z < _stage_limits["z_galvo_min"] or z > _stage_limits["z_galvo_max"]:
            raise RuntimeError(
                f"Z={z} outside galvo limits [{_stage_limits['z_galvo_min']}, "
                f"{_stage_limits['z_galvo_max']}]")
    elif z_mode == "zwide":
        if z < _stage_limits["z_wide_min"] or z > _stage_limits["z_wide_max"]:
            raise RuntimeError(
                f"Z={z} outside zwide limits [{_stage_limits['z_wide_min']}, "
                f"{_stage_limits['z_wide_max']}]")
    else:
        raise ValueError(
            f"Unknown z_mode '{z_mode}'. Use: 'galvo' or 'zwide'")

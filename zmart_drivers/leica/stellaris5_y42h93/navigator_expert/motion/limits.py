"""
Stage safety limits.
====================
Hard safety limits for XY and Z stage movement (micrometers).

This module guards against out-of-range stage moves with two independent
layers, both checked in Phase A of the command wrappers before the
backbone fires:

1. **Session envelope** — the machine-local limits file, applied via
   ``set_stage_limits()`` / ``apply_stage_limits_from_config()`` (the
   connect-time limits handshake does this from the machine snapshot).
   Moves refuse until it is configured (fail closed).
2. **Hardcoded physical backstop** (:data:`STAGE_BACKSTOP_UM`) — checked
   AFTER the envelope, independently of any file, so even a hand-widened
   limits file can never command a move outside the physical envelope.

The mutable module-level envelope is intentional: limits are set once at
session start and shared across all command calls. This assumes ONE
instrument per process (the same single-writer convention as command
dispatch, see ``commands/dispatch.py``); a second connect in the same
process rebinds the envelope for everyone.

Dependency direction:
    - Imports: stdlib only (no driver imports).
    - Imported by: ``commands`` (for Phase A limit checks),
      ``commands.gate`` (backstop containment at the connect handshake),
      ``__init__`` (re-export).
"""

import math

# =============================================================================
# Hardcoded physical backstop
# =============================================================================

# !! VERIFY ON RIG !! -------------------------------------------------------
# Absolute coordinate backstop for the motoric stage and both z drives
# (micrometers, [min, max] per axis). The bundled X/Y defaults deliberately
# start at 1000 um as a conservative safety margin; that margin is not the
# physical coordinate floor. Operator-measured limits may therefore extend
# below the default margin, down to coordinate zero. The upper bounds and Z
# bounds remain pinned to the historical ZMB STELLARIS 5 (serial y42h93)
# envelope until someone verifies different travel on the rig.
# NEVER widen these without measured rig data; narrowing is always safe.
# ---------------------------------------------------------------------------
STAGE_BACKSTOP_UM = {
    "x": (0.0, 130000.0),
    "y": (0.0, 100000.0),
    "z_galvo": (-250.0, 250.0),
    "z_wide": (0.0, 8000.0),
}


def check_envelope_within_backstop(stage_um):
    """Validate that a limits-file envelope sits WITHIN the physical backstop.

    ``stage_um`` is the ``{"x": [min, max], ...}`` mapping from a validated
    limits file. Raises ``RuntimeError`` when any axis reaches outside
    :data:`STAGE_BACKSTOP_UM` — a file wider than the physical travel is a
    hand-edited (or wrong-machine) file and must not be trusted. Called by
    the connect-time limits handshake; the per-move backstop check in
    ``_check_xy_limits`` / ``_check_z_limits`` stays independent of it.
    """
    for axis, (backstop_lo, backstop_hi) in STAGE_BACKSTOP_UM.items():
        lo, hi = float(stage_um[axis][0]), float(stage_um[axis][1])
        if lo < backstop_lo or hi > backstop_hi:
            raise RuntimeError(
                f"stage limits for axis {axis!r} = [{lo}, {hi}] reach outside the "
                f"physical backstop [{backstop_lo}, {backstop_hi}] "
                f"(motion/limits.py STAGE_BACKSTOP_UM); refusing the envelope — "
                f"a file wider than the machine's physical travel cannot be trusted"
            )


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
    """Configure hard safety limits for stage movement (micrometers).

    An explicit operator action; the hardcoded :data:`STAGE_BACKSTOP_UM`
    still bounds every move independently of what is set here.
    """
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
    """Configure stage limits from the loaded limits configuration.

    The dict shape is the one produced by
    :func:`navigator_expert.limits.config.load`; pass it through
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


def _require_finite(value, label):
    """A move target must be a finite int/float; NaN/inf/None/str all refuse.

    NaN compares False against every bound, so without this check a NaN
    target would pass straight through the range checks below. Numeric
    STRINGS are refused too (not coerced): ``float("50000")`` would satisfy
    the range check here while the raw string travels on into the native
    command model — the checked value must be the commanded value.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError(f"{label}={value!r} is not a number; refusing the move")
    number = float(value)
    if not math.isfinite(number):
        raise RuntimeError(f"{label}={value!r} is not finite; refusing the move")
    return number


def _check_xy_limits(x, y):
    """Validate XY position against the envelope, then the physical backstop.

    Raises RuntimeError on any violation (unconfigured envelope, non-finite
    target, outside the session envelope, or outside the hardcoded backstop).
    """
    if _stage_limits["x_min"] is None:
        raise RuntimeError("Stage limits not configured. Call set_stage_limits() first.")
    x = _require_finite(x, "X")
    y = _require_finite(y, "Y")
    if x < _stage_limits["x_min"] or x > _stage_limits["x_max"]:
        raise RuntimeError(
            f"X={x} outside limits [{_stage_limits['x_min']}, {_stage_limits['x_max']}]"
        )
    if y < _stage_limits["y_min"] or y > _stage_limits["y_max"]:
        raise RuntimeError(
            f"Y={y} outside limits [{_stage_limits['y_min']}, {_stage_limits['y_max']}]"
        )
    # Backstop AFTER the envelope: even a hand-widened envelope cannot
    # authorize a move outside the physical travel.
    for axis, value in (("x", x), ("y", y)):
        lo, hi = STAGE_BACKSTOP_UM[axis]
        if value < lo or value > hi:
            raise RuntimeError(
                f"{axis.upper()}={value} outside the physical backstop [{lo}, {hi}] "
                f"(motion/limits.py STAGE_BACKSTOP_UM) — refused regardless of the "
                f"configured envelope"
            )


def _check_z_limits(z, z_mode):
    """Validate Z position against the envelope, then the physical backstop.

    Raises:
        RuntimeError: If limits are not configured, z is non-finite, or z is
            out of range (envelope or backstop).
        ValueError: If z_mode is not recognized.
    """
    if _stage_limits["z_galvo_min"] is None:
        raise RuntimeError("Stage limits not configured. Call set_stage_limits() first.")
    if z_mode == "galvo":
        axis = "z_galvo"
    elif z_mode == "zwide":
        axis = "z_wide"
    else:
        raise ValueError(f"Unknown z_mode '{z_mode}'. Use: 'galvo' or 'zwide'")
    z = _require_finite(z, "Z")
    lo, hi = _stage_limits[f"{axis}_min"], _stage_limits[f"{axis}_max"]
    if z < lo or z > hi:
        label = "galvo" if axis == "z_galvo" else "zwide"
        raise RuntimeError(f"Z={z} outside {label} limits [{lo}, {hi}]")
    backstop_lo, backstop_hi = STAGE_BACKSTOP_UM[axis]
    if z < backstop_lo or z > backstop_hi:
        raise RuntimeError(
            f"Z={z} ({z_mode}) outside the physical backstop [{backstop_lo}, {backstop_hi}] "
            f"(motion/limits.py STAGE_BACKSTOP_UM) — refused regardless of the "
            f"configured envelope"
        )

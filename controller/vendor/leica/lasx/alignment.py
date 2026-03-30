"""
Objective alignment — coordinate translation between objectives.
================================================================
Each objective on the STELLARIS has its own coordinate system: the motor
stage reports a different absolute position for the same physical point
depending on which objective is active.  The offsets are deterministic
(firmware-applied parcentric corrections) and measured by the 3D
alignment calibration script.

The total offset between two objectives has two components:

    **motor_delta** — the stage position change reported by the firmware
        when switching objectives (coordinate-system shift).
    **image_shift** — the residual misalignment measured by cross-
        correlation after the firmware correction (optical error).

    total = motor_delta + image_shift

The microscope firmware already applies the **motor_delta** when
switching objectives, so ``move_xy`` / ``get_xy`` only need the
**image** offset correction — the residual optical misalignment
measured by cross-correlation.  Galvo pan coordinates also use the
**image** offset.

This module loads a calibration file (``alignment_results.json``) and
provides functions to translate stage positions, pan values, and z
positions between any two calibrated objectives, using the reference
objective (typically 10x) as the canonical coordinate system.

All positions are in micrometres unless noted otherwise.

Usage::

    from lasx.alignment import load_alignment, translate_xy, translate_pan

    al = load_alignment("path/to/alignment_results.json")

    # Stage coordinates: 10x -> 40x
    x40, y40 = translate_xy(1000.0, 2000.0, from_slot=1, to_slot=0, alignment=al)

    # Pan coordinates: 10x -> 40x
    px40, py40 = translate_pan(0.0, 0.0, from_slot=1, to_slot=0, alignment=al)
"""

import json
import logging

from .utils import PAN_SCALE

log = logging.getLogger(__name__)

_ZERO_OFFSET = {
    "motor_xy_um": [0.0, 0.0],
    "image_xy_um": [0.0, 0.0],
    "total_xy_um": [0.0, 0.0],
    "image_z_um": 0.0,
}


def load_alignment(path):
    """Load an alignment calibration JSON file.

    Returns a dict with structure::

        {
            "ref_slot": int,
            "offsets": {
                slot_int: {
                    "motor_xy_um": [dx, dy],   # firmware coordinate shift
                    "image_xy_um": [dx, dy],    # cross-correlation residual
                    "total_xy_um": [dx, dy],    # motor + image
                    "image_z_um": float,         # parfocal residual
                    ...
                },
                ...
            }
        }

    The reference objective has an implicit offset of (0, 0, 0).
    """
    with open(path) as f:
        raw = json.load(f)

    ref_slot = raw["ref_slot"]
    offsets = {}

    for label, target in raw.get("targets", {}).items():
        slot = target["slot"]
        mx, my = target["motor_delta_um"]
        sx, sy = target.get("shift_xy_um", [0.0, 0.0])
        sz = target.get("shift_z_um", 0.0)

        offsets[slot] = {
            "motor_xy_um": [mx, my],
            "image_xy_um": [sx, sy],
            "total_xy_um": [mx + sx, my + sy],
            "image_z_um": sz,
            "label": label,
            "full_name": target.get("full_name", ""),
        }

    return {
        "ref_slot": ref_slot,
        "ref_label": raw.get("ref_label", ""),
        "ref_objective": raw.get("ref_objective", ""),
        "offsets": offsets,
    }


def _get_offset(slot, alignment):
    """Return the offset entry for *slot*.  Reference returns zeros."""
    if slot == alignment["ref_slot"]:
        return _ZERO_OFFSET
    entry = alignment["offsets"].get(slot)
    if entry is None:
        raise KeyError(
            f"No alignment data for slot {slot}. "
            f"Calibrated slots: {[alignment['ref_slot']] + list(alignment['offsets'])}"
        )
    return entry


def _translate(val_x, val_y, from_slot, to_slot, alignment, key):
    """Translate a 2D value between objectives using a specific offset key."""
    if from_slot == to_slot:
        return val_x, val_y
    f = _get_offset(from_slot, alignment)
    t = _get_offset(to_slot, alignment)
    fx, fy = f[key]
    tx, ty = t[key]
    return val_x - fx + tx, val_y - fy + ty


def translate_xy(x_um, y_um, from_slot, to_slot, alignment):
    """Translate motor stage (x, y) from one objective's space to another.

    Uses only the **image** offset (cross-correlation residual).  The
    motor_delta component is already applied by the microscope firmware
    when switching objectives, so only the optical misalignment needs
    correcting.

    Use this with ``move_xy`` / ``get_xy`` positions.  For galvo pan
    coordinates, use :func:`translate_pan` instead.

    Args:
        x_um, y_um: Position in *from_slot*'s coordinate system (um).
        from_slot: Objective slot the position was recorded under.
        to_slot: Objective slot to translate to.
        alignment: Alignment dict from :func:`load_alignment`.

    Returns:
        (x_um, y_um) in *to_slot*'s coordinate system.
    """
    return _translate(x_um, y_um, from_slot, to_slot, alignment, "image_xy_um")


def translate_pan(pan_x, pan_y, from_slot, to_slot, alignment):
    """Translate galvo pan from one objective's space to another.

    Uses only the **image** offset — the optical center misalignment
    measured by cross-correlation.  Pan coordinates are in pan units
    (1 unit = 100,000 um).

    .. note::

       Whether galvo pan requires parcentric correction is still an
       open question.  The image offset is measured, but it is not yet
       confirmed that applying it as a pan correction produces the
       expected result on the microscope.

    Args:
        pan_x, pan_y: Pan values under *from_slot*.
        from_slot: Objective slot the pan was recorded under.
        to_slot: Objective slot to translate to.
        alignment: Alignment dict from :func:`load_alignment`.

    Returns:
        (pan_x, pan_y) in *to_slot*'s pan space.
    """
    if from_slot == to_slot:
        return pan_x, pan_y
    f = _get_offset(from_slot, alignment)
    t = _get_offset(to_slot, alignment)
    fx, fy = f["image_xy_um"]
    tx, ty = t["image_xy_um"]
    return (pan_x - fx / PAN_SCALE + tx / PAN_SCALE,
            pan_y - fy / PAN_SCALE + ty / PAN_SCALE)


def translate_z(z_um, from_slot, to_slot, alignment):
    """Translate a z-wide (motor Z) position from one objective's space to another.

    The parfocal correction is always applied by adjusting the z-wide
    motor.  The z-galvo operates relative to wherever z-wide places
    the focal plane, so galvo Z coordinates do not need translation.

    Use this with ``move_z(..., z_mode="zwide")`` positions only.

    Args:
        z_um: Z-wide position in *from_slot*'s coordinate system (um).
        from_slot: Objective slot the position was recorded under.
        to_slot: Objective slot to translate to.
        alignment: Alignment dict from :func:`load_alignment`.

    Returns:
        z_um in *to_slot*'s coordinate system.
    """
    if from_slot == to_slot:
        return z_um
    fz = _get_offset(from_slot, alignment)["image_z_um"]
    tz = _get_offset(to_slot, alignment)["image_z_um"]
    return z_um - fz + tz


def translate_xyz(x_um, y_um, z_um, from_slot, to_slot, alignment):
    """Translate (x, y, z) from one objective's space to another.

    Convenience wrapper combining :func:`translate_xy` and
    :func:`translate_z`.

    Returns:
        (x_um, y_um, z_um) in *to_slot*'s coordinate system.
    """
    x2, y2 = translate_xy(x_um, y_um, from_slot, to_slot, alignment)
    z2 = translate_z(z_um, from_slot, to_slot, alignment)
    return x2, y2, z2

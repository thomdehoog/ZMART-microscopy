"""Consumer accessors for objective calibration config.

The canonical calibration lives in
``navigator_expert/calibration/config/config.json`` (schema v6).

Two physical quantities are stored per target objective:

- ``parcentric_xy.shift_um``: stage-frame XY shift between the target
  objective's optical axis and the reference objective's optical axis,
  measured by registration with the stage parked at the same XY for
  both acquisitions. **This is what the cookbook applies.**

- ``parcentric_xy.offset_um``: stage-frame XY motion induced by the
  firmware on objective switch, measured via ``get_xy`` before/after.
  Diagnostic only — not part of the correction.

Same shift/offset pattern for ``parfocal_z`` (Z, scalar instead of
2-vector).

The schema-v5 ``motor_um`` / ``residual_um`` decomposition is gone.
That decomposition baked the firmware shift into the math twice and
its sum was noisier than measuring the shift directly.
"""

from .machine_config import load_machine_config


def load_calibration(path=None):
    """Load the canonical objective calibration config."""
    return load_machine_config(path)


def get_reference_slot(config):
    """Return the reference objective slot."""
    if "reference_objective_slot" in config:
        return int(config["reference_objective_slot"])
    raise ValueError("calibration config is missing 'reference_objective_slot'")


def get_image_to_stage(config):
    """Return the 2x2 image-to-stage matrix as floats."""
    matrix = config.get("image_to_stage")
    if matrix is None:
        raise ValueError("calibration config is missing 'image_to_stage' matrix")
    if len(matrix) != 2 or any(len(row) != 2 for row in matrix):
        raise ValueError(f"image_to_stage must be 2x2, got {matrix!r}")
    return [
        [float(matrix[0][0]), float(matrix[0][1])],
        [float(matrix[1][0]), float(matrix[1][1])],
    ]


def get_parcentric_shift_um(config, slot):
    """Return the stage-frame XY shift between *slot* and the reference.

    This is the registration-measured optical-center difference. The
    reference slot returns ``(0.0, 0.0)``.

    Raises ``ValueError`` if no entry exists for the slot, or if the
    entry exists but ``shift_um`` has not been measured yet.
    """
    slot = int(slot)
    if slot == get_reference_slot(config):
        return 0.0, 0.0
    entry = (config.get("objectives") or {}).get(str(slot))
    if entry is None:
        raise ValueError(
            f"No calibration entry for slot {slot}. "
            f"Available: {sorted(int(s) for s in config.get('objectives', {}))}"
        )
    parc = entry.get("parcentric_xy") or {}
    shift = parc.get("shift_um")
    if shift is None:
        raise ValueError(
            f"Slot {slot} has no parcentric_xy.shift_um. "
            f"Re-run calibrate_objectives.py with --measure-xy."
        )
    return float(shift[0]), float(shift[1])


def get_parcentric_offset_um(config, slot):
    """Return the firmware-induced ``get_xy`` delta for *slot*.

    Diagnostic — not used in cookbook math. Reference slot returns
    ``(0.0, 0.0)``. Returns ``(0.0, 0.0)`` if not measured.
    """
    slot = int(slot)
    if slot == get_reference_slot(config):
        return 0.0, 0.0
    entry = (config.get("objectives") or {}).get(str(slot))
    if entry is None:
        return 0.0, 0.0
    parc = entry.get("parcentric_xy") or {}
    offset = parc.get("offset_um")
    if offset is None:
        return 0.0, 0.0
    return float(offset[0]), float(offset[1])


def get_parfocal_shift_um(config, slot):
    """Return the Z shift (focal-plane delta) for *slot*."""
    slot = int(slot)
    if slot == get_reference_slot(config):
        return 0.0
    entry = (config.get("objectives") or {}).get(str(slot))
    if entry is None:
        return 0.0
    parf = entry.get("parfocal_z") or {}
    shift = parf.get("shift_um")
    return 0.0 if shift is None else float(shift)


def translate_stage_xy_between_objectives(x_um, y_um, config, *,
                                          from_slot, to_slot):
    """Translate a stage XY from *from_slot*'s frame to *to_slot*'s frame.

    Adds ``shift_um(to) - shift_um(from)``. The reference slot has zero
    shift by definition, so this works in either direction across any
    pair the config covers.
    """
    dx_from, dy_from = get_parcentric_shift_um(config, from_slot)
    dx_to, dy_to = get_parcentric_shift_um(config, to_slot)
    return float(x_um) + (dx_to - dx_from), float(y_um) + (dy_to - dy_from)


def reference_to_objective_command_xy(x_ref_um, y_ref_um, config, target_slot):
    """Translate a reference-frame XY to a stage command under *target_slot*."""
    return translate_stage_xy_between_objectives(
        x_ref_um, y_ref_um, config,
        from_slot=get_reference_slot(config),
        to_slot=target_slot,
    )


def pixel_to_stage_xy_um(px, py, stage_xy_um, pixel_size_um, image_size, config):
    """Convert image pixel coordinates to absolute stage XY in um."""
    matrix = get_image_to_stage(config)
    centre = image_size / 2.0
    dx_image_um = (px - centre) * pixel_size_um
    dy_image_um = (py - centre) * pixel_size_um

    stage_dx = matrix[0][0] * dx_image_um + matrix[0][1] * dy_image_um
    stage_dy = matrix[1][0] * dx_image_um + matrix[1][1] * dy_image_um

    return float(stage_xy_um[0]) + stage_dx, float(stage_xy_um[1]) + stage_dy

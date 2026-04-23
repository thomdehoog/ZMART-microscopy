"""
Objective-switch calibration: library layer.
============================================

Pure-Python building blocks for the two-phase objective-switch calibration.
No image-processing dependencies live here — registration and Cellpose are
confined to the hardware scripts in ``test/`` and ``examples/``.

What this module provides
    - :func:`measure_objective_switch_offsets` — measures the stage XY
      readback delta caused by switching objectives (one switch per target).
    - :func:`save_objective_offsets`, :func:`load_objective_offsets` —
      atomic read/write of the calibration config.
    - :func:`pixel_to_stage_xy_um` — pixel → stage µm conversion that
      applies the scope-specific image→stage 2×2 transform stored in the
      config's ``sign_convention`` block.
    - :func:`translate_stage_xy_between_objectives` — convert a stage XY
      between objective coordinate frames, in either direction.

Config schema (v2)::

    {
      "schema_version": 2,
      "timestamp": "YYYYMMDD_HHMMSS",
      "method": "objective_switch_stage_xy_readback",
      "coordinate_policy": "...",
      "job": "<LAS X job name>",
      "reference_slot": <int>,
      "reference_objective": {slot, name, magnification, ...},
      "sign_convention": {
          "image_to_stage_um_per_um": [[a, b], [c, d]],   # D4-snapped 2x2
          "label": "+Y -X",                               # human label
          "move_um": 30.0,                                # test-move size
          "fitted_matrix": [[...], [...]],                # pre-snap fit
          "residual_from_d4": <float>                     # fit quality
      },
      "settle_s": 3.0,
      "offsets": {
          "<target_slot>": {
              "target_slot": <int>,
              "target_objective": {...},
              "reference_xy_um": [x, y],
              "target_xy_um":    [x, y],
              "motor_delta_um":  [dx, dy]
          },
          ...
      }
    }

Coordinate policy
    - Detected targets are stored in the reference objective coordinate frame.
    - If the protocol moves to a target under the reference objective and
      then switches objectives, the motor delta must NOT be applied again —
      the objective switch already accounts for it.
    - The motor delta is applied only when issuing direct XY commands while
      already operating under a non-reference objective.

Validated on hardware (ZMB STELLARIS 8, 10x → 20x, 2026-04-23)
    - motor delta reproducible to bit-exact across repeats (LAS X readback
      is deterministic; repeats add no information).
    - sign convention: measured image→stage matrix snaps cleanly to
      ``[[0, 1], [-1, 0]]`` (label "+Y -X") — image and stage are rotated
      90° relative to each other on this scope.
    - end-to-end stage-only targeting: ~9 µm landing error, consistent with
      the motorized stage's settle accuracy. For sub-µm targeting the
      protocol needs galvo pan or image-based refinement (out of scope
      here).
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from time import sleep

from .commands import set_objective
from .prechecks import check_idle
from .readers import get_hardware_info, get_xy

log = logging.getLogger(__name__)

SCHEMA_VERSION = 2
COORDINATE_POLICY = (
    "targets_in_reference_frame; switch_at_target; motor_delta_is_readback_only"
)
MIN_SETTLE_S = 0.5
IDLE_TIMEOUT_S = 5.0


# ── Objective metadata ─────────────────────────────────────────────

def objective_by_slot(hw_info):
    """Map occupied objective slot index to its hardware-info entry."""
    by_slot = {}
    for obj in (hw_info or {}).get("Microscope", {}).get("objectives", []):
        if obj.get("objectiveNumber", 0) == 0:
            continue
        slot = obj.get("slotIndex")
        if slot is not None:
            by_slot[int(slot)] = obj
    return by_slot


def objective_summary(obj):
    """Return stable, JSON-safe metadata for one objective entry."""
    if obj is None:
        return None
    return {
        "slot": obj.get("slotIndex"),
        "name": str(obj.get("name", "")).strip(),
        "magnification": obj.get("magnification"),
        "numerical_aperture": obj.get("numericalAperture"),
        "immersion": str(obj.get("immersion", "")).strip(),
        "objective_number": obj.get("objectiveNumber"),
    }


def validate_slots(hw_info, reference_slot, target_slots):
    """Validate requested slots against the LAS X hardware info.

    Returns the slot-to-entry mapping on success; raises ValueError otherwise.
    """
    if target_slots is None:
        raise ValueError("target_slots is required")
    if not target_slots:
        raise ValueError("target_slots must contain at least one slot")

    target_slots = [int(s) for s in target_slots]
    reference_slot = int(reference_slot)
    by_slot = objective_by_slot(hw_info)

    missing = [s for s in [reference_slot] + target_slots if s not in by_slot]
    if missing:
        raise ValueError(
            f"Objective slot(s) not available: {missing}. "
            f"Available real objective slots: {sorted(by_slot)}"
        )

    duplicates = sorted({s for s in target_slots if target_slots.count(s) > 1})
    if duplicates:
        raise ValueError(f"Duplicate target slot(s): {duplicates}")

    if reference_slot in target_slots:
        raise ValueError("target_slots must not include the reference slot")

    return by_slot


# ── Measurement ────────────────────────────────────────────────────

def _xy_um(xy):
    if xy is None:
        raise RuntimeError("Could not read XY stage position")
    try:
        return float(xy["x_um"]), float(xy["y_um"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Invalid XY readback: {xy!r}") from exc


def _switch_slot(client, job_name, hw_info, slot, *, settle_s):
    result = set_objective(client, job_name, hw_info, slot_index=slot)
    if not result or not result.get("success"):
        raise RuntimeError(f"Objective switch to slot {slot} failed: {result}")
    sleep(settle_s)


def measure_objective_switch_offsets(
    client,
    reference_slot,
    target_slots,
    *,
    job_name,
    hw_info=None,
    settle_s=3.0,
    restore_reference=True,
    sign_convention=None,
):
    """Measure the stage XY readback delta from one objective switch per target.

    For each target slot, performs a single switch from the reference slot to
    the target and records the XY readback before and after. The LAS X
    readback is deterministic, so one measurement captures the full signal.

    Args:
        client: Connected LAS X API client.
        reference_slot: Slot used as the canonical coordinate frame.
        target_slots: Iterable of target slots to measure. Must not include
            the reference slot.
        job_name: LAS X job name. The operator must have this job selected
            in the LAS X UI — this function does not call select_job.
        hw_info: Hardware info dict. Read from LAS X when omitted.
        settle_s: Delay after each objective switch before XY readback.
            Must be >= MIN_SETTLE_S; values below that risk a stale readback
            because confirm_objective returns before LAS X applies the new
            coordinate offset.
        restore_reference: Switch back to the reference slot at the end.
        sign_convention: Optional image→stage transform dict, typically
            produced by the measurement script's Phase 1 before this call.
            Included in the returned config for `pixel_to_stage_xy_um`.

    Returns:
        JSON-serializable dict with objective metadata, per-target motor
        deltas, and the coordinate policy.
    """
    if settle_s < MIN_SETTLE_S:
        raise ValueError(f"settle_s must be >= {MIN_SETTLE_S}")

    reference_slot = int(reference_slot)
    target_slots = [int(s) for s in target_slots]

    if hw_info is None:
        hw_info = get_hardware_info(client)
        if not hw_info:
            raise RuntimeError("Could not read LAS X hardware info")

    by_slot = validate_slots(hw_info, reference_slot, target_slots)

    idle = check_idle(client, timeout=IDLE_TIMEOUT_S)
    if not idle or not idle.get("success"):
        raise RuntimeError(
            f"LAS X not idle — dismiss any modal dialog and stop any "
            f"running scan, then retry. check_idle returned: {idle}"
        )

    config = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": _now_timestamp(),
        "method": "objective_switch_stage_xy_readback",
        "coordinate_policy": COORDINATE_POLICY,
        "job": job_name,
        "reference_slot": reference_slot,
        "reference_objective": objective_summary(by_slot[reference_slot]),
        "sign_convention": sign_convention,
        "settle_s": settle_s,
        "offsets": {},
    }

    # Read the reference XY once — it is deterministic, so reuse it for every
    # target. Switching to the reference slot first guarantees a known state.
    _switch_slot(client, job_name, hw_info, reference_slot, settle_s=settle_s)
    ref_xy = _xy_um(get_xy(client))
    log.info("reference slot=%d XY_um=(%.3f, %.3f)",
             reference_slot, ref_xy[0], ref_xy[1])

    for idx, target_slot in enumerate(target_slots):
        _switch_slot(client, job_name, hw_info, target_slot, settle_s=settle_s)
        target_xy = _xy_um(get_xy(client))
        motor_delta = [target_xy[0] - ref_xy[0], target_xy[1] - ref_xy[1]]

        log.info(
            "target slot=%d XY_um=(%.3f, %.3f)  motor_delta_um=(%+.3f, %+.3f)",
            target_slot, target_xy[0], target_xy[1], *motor_delta,
        )

        config["offsets"][str(target_slot)] = {
            "target_slot": target_slot,
            "target_objective": objective_summary(by_slot[target_slot]),
            "reference_xy_um": list(ref_xy),
            "target_xy_um": list(target_xy),
            "motor_delta_um": motor_delta,
        }

        # Between targets, return to reference so the next measurement starts
        # from the same known state. The final restore is handled below.
        if idx != len(target_slots) - 1:
            _switch_slot(client, job_name, hw_info, reference_slot,
                         settle_s=settle_s)

    if restore_reference:
        _switch_slot(client, job_name, hw_info, reference_slot,
                     settle_s=settle_s)

    return config


# ── Persistence ────────────────────────────────────────────────────

def default_archive_dir():
    """Directory for timestamped archive files (gitignored)."""
    return Path(__file__).resolve().parent.parent / "config" / "objective_offsets"


def default_current_path():
    """Fixed path for the active offsets config that protocols load."""
    return Path(__file__).resolve().parent.parent / "config" / "objective_offsets.json"


def save_objective_offsets(config, archive_dir=None, current_path=None):
    """Write both the timestamped archive and the fixed current config.

    Returns a dict ``{"archive": Path, "current": Path}``.
    """
    archive_dir = Path(archive_dir) if archive_dir is not None else default_archive_dir()
    current_path = Path(current_path) if current_path is not None else default_current_path()

    timestamp = config.get("timestamp") or _now_timestamp()
    archive_path = archive_dir / f"objective_offsets_{timestamp}.json"

    _atomic_write_json(archive_path, config)
    _atomic_write_json(current_path, config)
    return {"archive": archive_path, "current": current_path}


def load_objective_offsets(path=None):
    """Load a saved objective-offsets config. Defaults to the current path."""
    path = Path(path) if path is not None else default_current_path()
    with open(path, "r", encoding="utf-8") as f:
        config = json.load(f)
    if config.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported objective-offsets schema version: "
            f"{config.get('schema_version')!r} in {path}. "
            f"Re-run measure_objective_offsets.py to regenerate."
        )
    return config


# ── Coordinate conversion ─────────────────────────────────────────

def pixel_to_stage_xy_um(px, py, stage_xy_um, pixel_size_um, image_size, config):
    """Convert image pixel coordinates to absolute stage XY (um).

    Uses the scope-specific image→stage 2×2 Jacobian stored in
    ``config["sign_convention"]["image_to_stage_um_per_um"]``. That matrix
    is the linear map "image-feature shift per unit stage move" measured
    empirically by the calibration script. It captures reflection, 90°
    rotation, or small skew between the camera and stage axes — no
    hardcoded sign assumptions.

    The physics: a feature at current image offset ``I`` reaches the image
    centre when the stage moves by ``Δ`` such that
    ``I + stage_to_image @ Δ = 0``, i.e. ``Δ = -image_to_stage @ I``. The
    feature's stage position is therefore ``stage - image_to_stage @ I``
    — the negation is why this function subtracts rather than adds the
    matrix product.

    Args:
        px, py: Pixel coordinates (column, row), float OK.
        stage_xy_um: ``(x_um, y_um)`` of the image centre in stage coords.
        pixel_size_um: Pixel size in um.
        image_size: Image dimension in pixels (assumed square).
        config: Calibration config from :func:`load_objective_offsets`.

    Returns:
        ``(x_um, y_um)`` — absolute stage coordinate of the given pixel.
    """
    sign = (config or {}).get("sign_convention")
    if not sign or "image_to_stage_um_per_um" not in sign:
        raise ValueError(
            "config is missing sign_convention; re-run the calibration "
            "script (measure_objective_offsets.py) to include Phase 1."
        )
    m = sign["image_to_stage_um_per_um"]

    # Image-frame offset from centre, in um.
    centre = image_size / 2.0
    dx_image_um = (px - centre) * pixel_size_um
    dy_image_um = (py - centre) * pixel_size_um

    # Apply -image_to_stage to the image offset to get the feature's stage
    # offset from the current stage position.
    stage_dx = -(m[0][0] * dx_image_um + m[0][1] * dy_image_um)
    stage_dy = -(m[1][0] * dx_image_um + m[1][1] * dy_image_um)

    return stage_xy_um[0] + stage_dx, stage_xy_um[1] + stage_dy


def translate_stage_xy_between_objectives(x_um, y_um, config, *, from_slot, to_slot):
    """Translate a motorized-stage XY from *from_slot*'s readback frame to a
    stage command under *to_slot*.

    Works in either direction (reference → non-reference or vice versa) and
    for any pair of slots the config covers. The caller does not need to
    know which slot is the reference.

    Do NOT apply this to a target you just reached via the switch-at-target
    workflow — the objective switch itself already accounts for the delta,
    and adding it again would double-apply.

    This function handles only the motorized-stage delta. Galvo/pan and ROI
    coordinates are not affected by objective switching in the same way and
    are handled elsewhere.

    Example:
        cell_source = drv.pixel_to_absolute_um(...)            # (x, y) in slot 1 frame
        cell_target = drv.translate_stage_xy_between_objectives(
            *cell_source, offsets, from_slot=1, to_slot=2,
        )                                                      # (x, y) as slot-2 stage command
        drv.move_xy_stage(client, *cell_target, unit="um")
    """
    reference_slot = int(config["reference_slot"])
    offsets = config.get("offsets") or {}

    def _delta(slot):
        slot = int(slot)
        if slot == reference_slot:
            return 0.0, 0.0
        key = str(slot)
        if key not in offsets:
            raise ValueError(
                f"No offset measured for slot {slot}. Available: "
                f"reference={reference_slot}, "
                f"offsets={sorted(int(k) for k in offsets)}"
            )
        dx, dy = offsets[key]["motor_delta_um"]
        return float(dx), float(dy)

    dxs, dys = _delta(from_slot)
    dxt, dyt = _delta(to_slot)
    return float(x_um) + (dxt - dxs), float(y_um) + (dyt - dys)


def reference_to_objective_command_xy(x_ref_um, y_ref_um, config, target_slot):
    """Translate a reference-frame XY to an XY command under *target_slot*.

    Thin wrapper around :func:`translate_stage_xy_between_objectives` for
    the common case where the source frame is the reference slot.
    """
    return translate_stage_xy_between_objectives(
        x_ref_um, y_ref_um, config,
        from_slot=config["reference_slot"],
        to_slot=target_slot,
    )


# ── Internal helpers ──────────────────────────────────────────────

def _now_timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _atomic_write_json(path, obj):
    """Write *obj* as pretty JSON to *path* via a temp-file + rename."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(str(tmp_path), str(path))

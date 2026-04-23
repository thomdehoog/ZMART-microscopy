"""
Objective switch motor-offset measurement.
==========================================

Measures the change in reported stage XY when LAS X switches from a reference
objective slot to one or more target objective slots. The LAS X XY readback
is deterministic for a given objective plus commanded stage position, so a
single switch per target captures the full information — no repeats.

This module does not do image registration and does not estimate optical
parcentric residuals.

Coordinate policy:
    - Store detected targets in the reference objective coordinate frame.
    - If you move to a target under the reference objective and then switch
      objectives, do not apply the measured motor delta again.
    - Use the measured motor delta only when issuing direct XY commands while
      already operating under a non-reference objective coordinate frame.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from time import sleep

from .commands import set_objective
from .prechecks import check_idle
from .readers import get_hardware_info, get_job_settings, get_selected_job, get_xy

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
COORDINATE_POLICY = (
    "targets_in_reference_frame; switch_at_target; motor_delta_is_readback_only"
)
MIN_SETTLE_S = 0.5


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


def _switch_slot(client, job_name, hw_info, slot, *, settle_s, pre_check_timeout):
    result = set_objective(
        client, job_name, hw_info,
        slot_index=slot, pre_check_timeout=pre_check_timeout,
    )
    if not result or not result.get("success"):
        raise RuntimeError(f"Objective switch to slot {slot} failed: {result}")
    sleep(settle_s)
    return result


def measure_objective_switch_offsets(
    client,
    reference_slot,
    target_slots,
    *,
    job_name,
    hw_info=None,
    settle_s=3.0,
    restore_reference=True,
    pre_check_timeout=None,
    idle_timeout=5.0,
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
        pre_check_timeout: Idle-wait timeout passed to each set_objective.
        idle_timeout: Seconds to wait for LAS X idle before starting. A
            pre-existing modal dialog or running scan will fail this check.

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

    idle = check_idle(client, timeout=idle_timeout)
    if not idle or not idle.get("success"):
        raise RuntimeError(
            f"LAS X not idle — dismiss any modal dialog and stop any "
            f"running scan, then retry. check_idle returned: {idle}"
        )

    start_settings = get_job_settings(client, job_name) or {}
    start_slot = start_settings.get("objective", {}).get("slotIndex")
    start_objective = (
        objective_summary(by_slot.get(int(start_slot)))
        if start_slot is not None else None
    )

    config = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": _now_timestamp(),
        "method": "objective_switch_stage_xy_readback",
        "coordinate_policy": COORDINATE_POLICY,
        "job": job_name,
        "reference_slot": reference_slot,
        "reference_objective": objective_summary(by_slot[reference_slot]),
        "start_objective": start_objective,
        "settle_s": settle_s,
        "residual_xy_correction": {
            "enabled": False,
            "reason": "optical parcentric residual intentionally not measured",
        },
        "offsets": {},
    }

    # Read the reference XY once — it is deterministic, so reuse it for every
    # target. Switching to the reference slot first guarantees a known state.
    _switch_slot(
        client, job_name, hw_info, reference_slot,
        settle_s=settle_s, pre_check_timeout=pre_check_timeout,
    )
    ref_xy = _xy_um(get_xy(client))
    log.info(
        "reference slot=%d XY_um=(%.3f, %.3f)",
        reference_slot, ref_xy[0], ref_xy[1],
    )

    for idx, target_slot in enumerate(target_slots):
        _switch_slot(
            client, job_name, hw_info, target_slot,
            settle_s=settle_s, pre_check_timeout=pre_check_timeout,
        )
        target_xy = _xy_um(get_xy(client))
        motor_delta = [target_xy[0] - ref_xy[0], target_xy[1] - ref_xy[1]]

        log.info(
            "target slot=%d XY_um=(%.3f, %.3f)  motor_delta_um=(%+.3f, %+.3f)",
            target_slot, target_xy[0], target_xy[1],
            motor_delta[0], motor_delta[1],
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
            _switch_slot(
                client, job_name, hw_info, reference_slot,
                settle_s=settle_s, pre_check_timeout=pre_check_timeout,
            )

    if restore_reference:
        _switch_slot(
            client, job_name, hw_info, reference_slot,
            settle_s=settle_s, pre_check_timeout=pre_check_timeout,
        )

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

def reference_to_objective_command_xy(x_ref_um, y_ref_um, config, target_slot):
    """Convert a reference-frame XY to an XY command under *target_slot*.

    Returns the value to pass to a direct XY move command while the target
    objective is already active. Do NOT apply this to a target you just
    reached via the switch-at-target workflow — the objective switch itself
    already accounts for the delta, and adding it again would double-apply.
    """
    slot_key = str(int(target_slot))
    offsets = config.get("offsets") or {}
    if slot_key not in offsets:
        raise ValueError(
            f"No offset measured for target slot {target_slot}. "
            f"Available target slots in config: {sorted(int(k) for k in offsets)}"
        )
    dx, dy = offsets[slot_key]["motor_delta_um"]
    return float(x_ref_um) + float(dx), float(y_ref_um) + float(dy)


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

"""Objective-slot helpers.

Pure-functional utilities over the hardware-info dict returned by
``readers.get_hardware_info``. No I/O, no state, no schema coupling —
keep it that way so calibration and cookbook scripts can share these
without any version concerns.
"""

from __future__ import annotations

from typing import Any, Iterable


def objective_by_slot(hw_info: dict | None) -> dict[int, dict[str, Any]]:
    """Return ``{slot_index: objective_entry}`` for every occupied slot.

    Empty / placeholder entries (``objectiveNumber == 0``) are skipped.
    """
    by_slot: dict[int, dict[str, Any]] = {}
    for obj in (hw_info or {}).get("Microscope", {}).get("objectives", []):
        if obj.get("objectiveNumber", 0) == 0:
            continue
        slot = obj.get("slotIndex")
        if slot is not None:
            by_slot[int(slot)] = obj
    return by_slot


def validate_slots(
    hw_info: dict | None,
    reference_slot: int,
    target_slots: Iterable[int],
) -> dict[int, dict[str, Any]]:
    """Validate requested slots against the LAS X hardware info.

    Returns the ``{slot: entry}`` mapping for further use.
    Raises ``ValueError`` if any slot is unknown, if target_slots is
    empty, has duplicates, or includes the reference slot.
    """
    target_slots_list = [int(s) for s in (target_slots or [])]
    if not target_slots_list:
        raise ValueError("target_slots must contain at least one slot")

    reference_slot = int(reference_slot)
    by_slot = objective_by_slot(hw_info)

    missing = [s for s in [reference_slot] + target_slots_list if s not in by_slot]
    if missing:
        raise ValueError(
            f"Objective slot(s) not available: {missing}. "
            f"Available real objective slots: {sorted(by_slot)}"
        )

    duplicates = sorted({s for s in target_slots_list
                         if target_slots_list.count(s) > 1})
    if duplicates:
        raise ValueError(f"Duplicate target slot(s): {duplicates}")

    if reference_slot in target_slots_list:
        raise ValueError("target_slots must not include the reference slot")

    return by_slot

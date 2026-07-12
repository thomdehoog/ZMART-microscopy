"""Objective-slot helpers.

Pure-functional utilities over the hardware-info dict returned by
``readers.get_hardware_info``. No I/O, no state, no schema coupling —
keep it that way so calibration and cookbook scripts can share these
without any version concerns.
"""

from __future__ import annotations

from typing import Any


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

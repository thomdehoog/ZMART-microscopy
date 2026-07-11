"""Build the live, workflow-facing setup information for the Leica adapter."""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

from shared.output_layout import build_layout

_EXPERIMENT = "target-acquisition"


def output_root(handle: Any, save_source_root: Callable[[], Path]) -> Path:
    """Return the session run root, creating it from native AutoSave when omitted."""
    root = handle.connection.get("output_root")
    if root:
        return Path(root)
    try:
        layout = build_layout(save_source_root().parent / "zmart", _EXPERIMENT)
    except Exception as exc:
        raise RuntimeError(
            "output_root is not set and could not be discovered from LAS X native AutoSave"
        ) from exc
    handle.connection["output_root"] = str(layout.run_dir)
    return layout.run_dir


def tile_positions(scan_field: dict | None) -> list[dict]:
    """Return the currently configured LAS X tiles in controller-frame micrometres."""
    if not scan_field:
        return []
    tiles = []
    for entry in scan_field.get("positions") or []:
        if entry.get("kind") != "grid":
            continue
        position = _frame_position(entry)
        size = entry.get("tile_size") or {}
        position["tile_size"] = {
            "x": _positive(size.get("x"), "tile_size.x"),
            "y": _positive(size.get("y"), "tile_size.y"),
        }
        if entry.get("group") is not None:
            position["group"] = dict(entry["group"])
        if entry.get("job") is not None:
            position["job"] = entry["job"]
        tiles.append(position)
    return tiles


def focus_positions(scan_field: dict | None) -> list[dict]:
    """Return the currently configured LAS X focus points in controller-frame micrometres."""
    if not scan_field:
        return []
    positions = []
    for entry in scan_field.get("positions") or []:
        if entry.get("kind") not in {"focus-point", "autofocus-point"}:
            continue
        position = _frame_position(entry)
        if entry.get("id") is not None:
            position["id"] = entry["id"]
        position["enabled"] = bool(entry.get("enabled", True))
        positions.append(position)
    return positions


def _frame_position(entry: dict) -> dict:
    frame = entry.get("frame") or {}
    position = {
        "x": _finite(frame.get("x_um"), "position.x"),
        "y": _finite(frame.get("y_um"), "position.y"),
    }
    if frame.get("z_um") is not None:
        position["z"] = _finite(frame["z_um"], "position.z")
    return position


def _finite(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"LAS X {label} is not numeric: {value!r}") from exc
    if not math.isfinite(number):
        raise RuntimeError(f"LAS X {label} is not finite: {value!r}")
    return number


def _positive(value: Any, label: str) -> float:
    number = _finite(value, label)
    if number <= 0:
        raise RuntimeError(f"LAS X {label} must be positive: {value!r}")
    return number

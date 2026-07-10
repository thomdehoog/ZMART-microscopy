"""Small read-only procedures for the ZMART controller adapter."""

from __future__ import annotations

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


def positions(scan_field: dict | None) -> list[dict]:
    """Return grid positions as controller frame coordinates."""
    return _positions(scan_field, kinds={"grid"}, label="grid positions")


def focus_points(scan_field: dict | None) -> list[dict]:
    """Return focus positions as controller frame coordinates."""
    if not scan_field:
        return []
    positions = scan_field.get("positions") or []
    if not any(entry.get("kind") in {"focus-point", "autofocus-point"} for entry in positions):
        return []
    return _positions(
        scan_field,
        kinds={"focus-point", "autofocus-point"},
        label="focus points",
    )


def _positions(scan_field: dict | None, *, kinds: set[str], label: str) -> list[dict]:
    if not scan_field:
        raise RuntimeError(f"no LAS X scan-field {label} are available")
    out = []
    for entry in scan_field.get("positions") or []:
        if entry.get("kind") not in kinds:
            continue
        frame = entry.get("frame") or {}
        pos = {"x": float(frame["x_um"]), "y": float(frame["y_um"])}
        if frame.get("z_um") is not None:
            pos["z"] = float(frame["z_um"])
        out.append(pos)
    if not out:
        raise RuntimeError(f"no {label} found in the LAS X scan field")
    return out

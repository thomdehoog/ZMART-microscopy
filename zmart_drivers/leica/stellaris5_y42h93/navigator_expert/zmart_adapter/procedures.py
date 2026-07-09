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
        layout = build_layout(save_source_root().parent / "smart", _EXPERIMENT)
    except Exception as exc:
        raise RuntimeError(
            "output_root is not set and could not be discovered from LAS X native AutoSave"
        ) from exc
    handle.connection["output_root"] = str(layout.run_dir)
    return layout.run_dir


def positions(scan_field: dict | None) -> list[dict]:
    """Return grid positions as controller frame coordinates."""
    if not scan_field:
        raise RuntimeError("no LAS X scan-field positions are available")
    out = []
    for entry in scan_field.get("positions") or []:
        if entry.get("kind") != "grid":
            continue
        frame = entry.get("frame") or {}
        pos = {"x": float(frame["x_um"]), "y": float(frame["y_um"])}
        if frame.get("z_um") is not None:
            pos["z"] = float(frame["z_um"])
        out.append(pos)
    if not out:
        raise RuntimeError("no grid positions found in the LAS X scan field")
    return out

"""Controller-only workflow steps: connect, load positions, overview, targets.

Thin orchestration over the ``zmart_controller`` session and the driver-free
helpers (``_capture_run``, ``_focus_surface``). No ``navigator_expert`` import --
the driver adapter is imported by the notebook only to register the instrument.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ._capture_run import capture_positions


def connect(vendor: str, *, output_root: Any = None, **extras: Any):
    """Open a controller session for a registered instrument, selected by vendor.

    The driver adapter must already be imported (importing it is what registers
    the instrument with ``get_instruments()``). ``output_root`` and any ``extras``
    are dropped into the connection dict before connecting.
    """
    import zmart_controller

    matches = [i for i in zmart_controller.get_instruments() if i.get("vendor") == vendor]
    if not matches:
        raise ValueError(
            f"no registered instrument for vendor {vendor!r} -- import its adapter first"
        )
    if len(matches) > 1:
        raise ValueError(f"multiple instruments for vendor {vendor!r}; disambiguate by microscope")
    instrument = matches[0]
    if output_root is not None:
        instrument["output_root"] = str(output_root)
    instrument.update(extras)
    return zmart_controller.set_instrument(instrument)


def load_positions(path: Any) -> list[dict]:
    """Load frame positions from a JSON list of ``{"x", "y"[, "z"]}`` (micrometres)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    positions = []
    for row in data:
        pos = {"x": float(row["x"]), "y": float(row["y"])}
        if "z" in row:
            pos["z"] = float(row["z"])
        positions.append(pos)
    return positions


def with_focus_z(positions: list[dict], focus: Any = None) -> list[dict]:
    """Attach z to each ``{x, y}`` position: from the focus surface, else its own z, else 0."""
    placed = []
    for pos in positions:
        if focus is not None:
            z = float(focus.z_at(pos["x"], pos["y"]))
        else:
            z = float(pos.get("z", 0.0))
        placed.append({"x": pos["x"], "y": pos["y"], "z": z})
    return placed


def run_overview(
    session: Any,
    positions: list[dict],
    *,
    state: dict | None = None,
    focus: Any = None,
    options: dict | None = None,
) -> list[dict]:
    """Step 5: acquire an overview at each frame position (z from the focus surface)."""
    placed = with_focus_z(positions, focus)
    return capture_positions(session, placed, "overview", state=state, options=options)


def acquire_targets(
    session: Any,
    targets: list[dict],
    *,
    state: dict | None = None,
    focus: Any = None,
    options: dict | None = None,
) -> list[dict]:
    """Step 7: acquire a target at each discovered frame position (z from the focus surface)."""
    placed = with_focus_z(targets, focus)
    return capture_positions(session, placed, "target", state=state, options=options)

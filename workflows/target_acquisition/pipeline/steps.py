"""Controller-only workflow steps: connect, root/positions, overview, targets.

Thin orchestration over the ``zmart_controller`` session and the driver-free
helpers (``_capture_run``, ``_focus_surface``). No ``navigator_expert`` import --
the workflow bootstrap imports the driver adapter only to register the instrument.
"""

from __future__ import annotations

import importlib
import json
import sys
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
    return _normalize_positions(data)


def get_root(session: Any) -> Path:
    """Ask the controller driver for the run root."""
    result = session.run_procedure({"name": "get_root"})
    root = result.get("output_root") or result.get("root")
    if not root:
        raise RuntimeError("get_root procedure did not return output_root")
    return Path(root)


def get_positions(session: Any) -> list[dict]:
    """Ask the controller driver for overview positions."""
    result = session.run_procedure({"name": "get_positions"})
    return _normalize_positions(result.get("positions") or [])


def _normalize_positions(data: Any) -> list[dict]:
    positions = []
    for row in data:
        pos = {"x": float(row["x"]), "y": float(row["y"])}
        if "z" in row:
            pos["z"] = float(row["z"])
        positions.append(pos)
    return positions


def load_analysis_engine(analysis_repo: Any):
    """Load the smart-analysis Engine from *analysis_repo* and instantiate it."""
    repo = Path(analysis_repo)
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    return importlib.import_module("engine").Engine()


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


def overview_inputs_from_records(
    positions: list[dict],
    records: list[dict],
    *,
    focus: Any = None,
    **geometry: Any,
) -> list[dict]:
    """Build target-discovery inputs from overview positions and acquire records."""
    from .discovery import build_overview_inputs

    placed = with_focus_z(positions, focus)
    return build_overview_inputs(
        placed,
        [_first_image(record, index) for index, record in enumerate(records)],
        **geometry,
    )


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


def hijack_if_simulating(
    records: list[dict],
    *,
    simulate: bool,
    image_source: str = "skimage_human_mitosis",
) -> int:
    """Overwrite saved simulator images with mock cells when simulation is enabled."""
    if not simulate:
        return 0
    from ._hijack import hijack_records
    from ._mock_provider import get_provider

    return hijack_records(records, get_provider(image_source))


def write_run_report(
    output_root: Any,
    *,
    positions: list[dict],
    focus: Any,
    overview_records: list[dict],
    targets: list[dict],
    show: bool = True,
) -> dict:
    """Write the summary JSON and frame-layout plot for the notebook run."""
    from .viz import plot_frame_layout, summarize_run, write_summary

    output_root = Path(output_root)
    overview_positions = with_focus_z(positions, focus)
    summary = summarize_run(
        focus=focus,
        overview_positions=overview_positions,
        overview_records=overview_records,
        targets=targets,
    )
    write_summary(summary, output_root / "summary.json")
    plot_frame_layout(
        overview_positions=overview_positions,
        targets=targets,
        focus=focus,
        save_path=output_root / "run_layout.png",
        show=show,
    )
    return summary


def _first_image(record: dict, index: int) -> Any:
    images = record.get("images") or ()
    if not images:
        raise ValueError(f"overview record {index} has no saved image path")
    return images[0]

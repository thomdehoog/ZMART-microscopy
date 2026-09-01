"""The run: its steps, in order -- connect, overview, targets.

Thin orchestration over the ``zmart_controller`` session and the driver-free
parts it reaches for (``parts.microscope.capture_run``, the focus step's own
surface fit). No ``navigator_expert`` import -- the workflow bootstrap imports
the driver adapter only to register the instrument.

Named for what it is rather than ``steps.py``, which could not stand beside the
``steps/`` folder holding one folder per step: the package would win every
import. Its JavaScript counterpart, ``the-run.js``, composes the same steps
into the same run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from application.parts.microscope.capture_run import capture_positions
from application.parts.storage.records import record_channel_paths

#: The analysis pipeline the run discovers targets with, and the queue name it
#: is registered under -- the engine keys a pipeline by the top-level name in
#: its own YAML, so these two must agree.
ANALYSIS_QUEUE = "object_analysis"
ANALYSIS_PIPELINE = (
    Path(__file__).resolve().parents[3]
    / "zmart_analysis" / "workflows" / "object_analysis"
    / "pipelines" / f"{ANALYSIS_QUEUE}.yaml"
)


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


def require_driver_ready(state: dict) -> dict | None:
    """Refuse when a driver reports its machine setup is not ready.

    Limits, calibration, and orientation meanings remain entirely driver-owned. This
    workflow consumes only the driver's opaque ``ready`` verdict and displays
    its actionable issues. Drivers without such a verdict remain compatible.
    """
    setup = (state.get("observed") or {}).get("setup")
    if setup is None:
        return None
    if not setup.get("ready"):
        issues = setup.get("issues") or ["driver reported an unknown setup problem"]
        raise RuntimeError("driver preflight failed: " + "; ".join(map(str, issues)))
    return setup


def load_positions(path: Any) -> list[dict]:
    """Load frame positions from a JSON list of ``{"x", "y"[, "z"]}`` (micrometres)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return _normalize_positions(data)


def _normalize_positions(data: Any) -> list[dict]:
    positions = []
    for row in data:
        pos = {"x": float(row["x"]), "y": float(row["y"])}
        if "z" in row:
            pos["z"] = float(row["z"])
        positions.append(pos)
    return positions


def load_analysis_engine():
    """Start ZMART Analysis and register the object_analysis pipeline.

    The analysis lives in this repository, at ``zmart_analysis``, so there is
    nothing to find and no checkout to point at. What is registered is
    ``object_analysis``: cellpose detection, then per-object features, then
    the public object table -- the features are the point, which is why this
    is not the detection-only pipeline beside it.
    """
    from zmart_analysis.engine import Engine

    engine = Engine()
    try:
        engine.register(ANALYSIS_QUEUE, str(ANALYSIS_PIPELINE))
    except Exception:
        engine.shutdown()
        raise
    return engine


def preflight_analysis_engine(engine: Any) -> None:
    """Run one tiny blank tile through the registered analysis worker.

    Registration alone does not start the smart analysis Cellpose conda
    environment. This warm-up therefore happens before the microscope connects:
    a missing environment/model/GPU fails before any hardware work, and a valid
    worker stays warm for the overview run.
    """
    import tempfile

    import numpy as np
    import tifffile

    from application.workflows.target_acquisition.steps.discover_targets.discovery import (
        discover_targets,
    )

    with tempfile.TemporaryDirectory(prefix="zmart-preflight-") as tmp:
        image_path = Path(tmp) / "blank.tiff"
        tifffile.imwrite(image_path, np.zeros((64, 64), dtype=np.uint16))
        discover_targets(
            engine,
            [
                {
                    "image_path": image_path,
                    "center_frame_um": (0.0, 0.0),
                    "pixel_size_um": 1.0,
                    "image_size_px": (64, 64),
                    "label": "preflight",
                }
            ],
            n_picks=1,
        )


def with_focus_z(positions: list[dict], focus: Any = None) -> list[dict]:
    """Attach z while preserving vendor location fields used in output labels."""
    placed = []
    for pos in positions:
        if focus is not None:
            z = float(focus.z_at(pos["x"], pos["y"]))
        else:
            z = float(pos.get("z", 0.0))
        placed.append({**pos, "x": pos["x"], "y": pos["y"], "z": z})
    return placed


def run_overview(
    session: Any,
    positions: list[dict],
    *,
    state: dict | None = None,
    focus: Any = None,
    options: dict | None = None,
    on_record: Any = None,
    cancel: Any = None,
    output_root: Any = None,
) -> list[dict]:
    """Step 5: acquire an overview at each frame position (z from the focus surface).

    ``on_record(index, position, record)`` fires after each tile is saved —
    pass a viewer's ``add_acquisition`` here and the overview map grows on
    screen while the microscope is still scanning. ``cancel`` (a function
    answering True to stop) ends the run cleanly between two tiles; see
    :func:`~._capture_run.capture_positions`.
    """
    placed = with_focus_z(positions, focus)
    return capture_positions(
        session,
        placed,
        "overview",
        state=state,
        options=options,
        on_record=on_record,
        cancel=cancel,
        output_root=output_root,
    )


def overview_inputs_from_records(
    positions: list[dict],
    records: list[dict],
    *,
    focus: Any = None,
    **geometry: Any,
) -> list[dict]:
    """Build target-discovery inputs from overview positions and acquire records."""
    from application.workflows.target_acquisition.steps.discover_targets.discovery import (
        build_overview_inputs,
    )

    if len(positions) != len(records):
        raise ValueError(
            f"overview positions/records length mismatch: {len(positions)} != {len(records)}"
        )
    placed = with_focus_z(positions, focus)
    channel_paths = [
        record_channel_paths(record, context=f"overview record {index}")
        for index, record in enumerate(records)
    ]
    inputs = build_overview_inputs(
        placed,
        [paths[0] for paths in channel_paths],
        **geometry,
    )
    for overview, paths in zip(inputs, channel_paths, strict=True):
        overview["channel_paths"] = paths
    return inputs


def acquire_targets(
    session: Any,
    targets: list[dict],
    *,
    state: dict | None = None,
    focus: Any = None,
    options: dict | None = None,
    on_record: Any = None,
    cancel: Any = None,
    output_root: Any = None,
) -> list[dict]:
    """Step 7: acquire a target at each discovered frame position (z from the focus surface).

    ``on_record(index, position, record)`` fires after each target is saved —
    the acquisition gallery uses it to show every pair the moment it exists.
    ``cancel`` (a function answering True to stop) ends the run cleanly
    between two targets; see :func:`~._capture_run.capture_positions`.
    """
    placed = with_focus_z(targets, focus)
    return capture_positions(
        session,
        placed,
        "target",
        state=state,
        options=options,
        on_record=on_record,
        cancel=cancel,
        output_root=output_root,
    )


def hijack_if_simulating(
    records: list[dict],
    *,
    simulate: bool,
    image_source: str = "skimage_human_mitosis",
) -> int:
    """Overwrite saved simulator images with mock cells when simulation is enabled."""
    if not simulate:
        return 0
    from application.parts.microscope.hijack import hijack_records
    from application.parts.microscope.mock_provider import get_provider

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
    from application.parts.plots.viz import plot_frame_layout, summarize_run, write_summary

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

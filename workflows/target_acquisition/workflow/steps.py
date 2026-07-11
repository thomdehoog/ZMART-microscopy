"""Controller-only workflow steps: connect, overview, targets.

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
from ._records import record_channel_paths


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


def load_analysis_engine(analysis_repo: Any):
    """Load smart-analysis v4 and register its target-acquisition pipeline."""
    repo = Path(analysis_repo).expanduser().resolve()
    if not repo.is_dir():
        raise FileNotFoundError(f"smart-analysis repository not found: {repo}")
    pipeline = repo / "workflows" / "target_acquisition" / "pipelines" / "overview.yaml"
    if not pipeline.is_file():
        raise FileNotFoundError(
            f"smart-analysis target-acquisition pipeline not found: {pipeline}; "
            "checkout the v4-engine branch"
        )
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    engine_module = importlib.import_module("engine")
    module_path = Path(engine_module.__file__).resolve()
    try:
        module_path.relative_to(repo)
    except ValueError as exc:
        raise ImportError(
            f"Python imported smart-analysis engine from {module_path}, not {repo}; "
            "restart the notebook kernel after changing ANALYSIS_REPO"
        ) from exc
    engine = engine_module.Engine()
    try:
        engine.register("overview", pipeline)
    except Exception:
        engine.shutdown()
        raise
    return engine


def preflight_analysis_engine(engine: Any) -> None:
    """Run one tiny blank tile through the registered analysis worker.

    Registration alone does not start smart-analysis' declared Cellpose conda
    environment. This warm-up therefore happens before the microscope connects:
    a missing environment/model/GPU fails before any hardware work, and a valid
    worker stays warm for the overview run.
    """
    import tempfile

    import numpy as np
    import tifffile

    from .discovery import discover_targets

    with tempfile.TemporaryDirectory(prefix="zmart-analysis-preflight-") as tmp:
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
    from .discovery import build_overview_inputs

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

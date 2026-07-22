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


def _find_analysis_repo() -> Path:
    """Find the adjacent smart analysis checkout without exposing its folder name."""
    zmart_repo = Path(__file__).resolve().parents[3]
    candidates = []
    for path in zmart_repo.parent.iterdir():
        pipeline = path / "workflows" / "target_acquisition" / "pipelines" / "overview.yaml"
        if path != zmart_repo and pipeline.is_file() and (path / "engine").is_dir():
            candidates.append(path.resolve())
    if not candidates:
        raise FileNotFoundError(
            f"smart analysis repository not found next to the ZMART repository: {zmart_repo.parent}"
        )
    if len(candidates) > 1:
        raise RuntimeError(
            "multiple smart analysis repositories found next to the ZMART repository: "
            + ", ".join(map(str, candidates))
        )
    return candidates[0]


def load_analysis_engine(analysis_repo: Any = None):
    """Load smart analysis v4 and register its target-acquisition pipeline."""
    repo = (
        _find_analysis_repo()
        if analysis_repo is None
        else Path(analysis_repo).expanduser().resolve()
    )
    if not repo.is_dir():
        raise FileNotFoundError(f"smart analysis repository not found: {repo}")
    pipeline = repo / "workflows" / "target_acquisition" / "pipelines" / "overview.yaml"
    if not pipeline.is_file():
        raise FileNotFoundError(
            f"smart analysis target-acquisition pipeline not found: {pipeline}; "
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
            f"Python imported the smart analysis engine from {module_path}, not {repo}; "
            "restart the notebook kernel after changing the repository location"
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

    Registration alone does not start the smart analysis Cellpose conda
    environment. This warm-up therefore happens before the microscope connects:
    a missing environment/model/GPU fails before any hardware work, and a valid
    worker stays warm for the overview run.
    """
    import tempfile

    import numpy as np
    import tifffile

    from .discovery import discover_targets

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
    """Attach a focus z to each position, preserving its other fields.

    Where the z comes from:

    - With a fitted ``focus`` surface, z is read from the surface at each
      position's (x, y) — the normal path, after the focus step.
    - With no surface, a position that already carries its own ``z`` keeps
      it (for example, positions loaded from a file that stored a z).
    - With neither, there is no safe focus height to move to. Rather than
      silently driving to frame z = 0 — which, depending on where the
      origin sits, can defocus the whole run or push the objective into
      the sample — this refuses and asks for a focus surface or an
      explicit z. (A deliberate z = 0 is still fine: just set it on the
      position.)
    """
    placed = []
    for pos in positions:
        if focus is not None:
            z = float(focus.z_at(pos["x"], pos["y"]))
        elif "z" in pos:
            z = float(pos["z"])
        else:
            raise ValueError(
                "no focus surface was measured and this position has no z of its "
                "own, so there is no safe focus height to move to. Measure a focus "
                "surface (the focus step) before acquiring, or give each position "
                "an explicit z (z=0 is allowed — set it deliberately)."
            )
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
    focus: Any = None,  # noqa: ARG001 -- accepted for call-site symmetry; see below
    **geometry: Any,
) -> list[dict]:
    """Build target-discovery inputs from overview positions and acquire records.

    ``focus`` is accepted so callers can pass it alongside the acquisition
    steps, but discovery inputs only need each tile's (x, y) centre — the
    focus z never travels into an overview input — so it is intentionally not
    applied here. (Applying it would also wrongly demand a focus surface just
    to pair images with positions.)
    """
    from .discovery import build_overview_inputs

    if len(positions) != len(records):
        raise ValueError(
            f"overview positions/records length mismatch: {len(positions)} != {len(records)}"
        )
    channel_paths = [
        record_channel_paths(record, context=f"overview record {index}")
        for index, record in enumerate(records)
    ]
    inputs = build_overview_inputs(
        positions,
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
    overviews: list[dict] | None = None,
    show: bool = True,
) -> dict:
    """Write the run's summary JSON and figures.

    Always writes ``summary.json`` and the schematic ``run_layout.png`` (frame
    coordinates). When ``overviews`` (the discovery inputs, carrying each tile's
    saved image) is given, it also writes ``overview_targets.png``: the real
    overview mosaic with the acquired targets drawn on top — the picture that
    shows, at a glance, that the run imaged the cells it meant to.
    """
    from .viz import plot_frame_layout, plot_overview_targets, summarize_run, write_summary

    output_root = Path(output_root)
    # The report only needs each tile's (x, y); it never moves the stage, so it
    # does not attach a focus z (and must not demand a focus surface to save).
    summary = summarize_run(
        focus=focus,
        overview_positions=positions,
        overview_records=overview_records,
        targets=targets,
    )
    write_summary(summary, output_root / "summary.json")
    plot_frame_layout(
        overview_positions=positions,
        targets=targets,
        focus=focus,
        save_path=output_root / "run_layout.png",
        show=show,
    )
    if overviews:
        plot_overview_targets(
            overviews,
            targets,
            save_path=output_root / "overview_targets.png",
            show=show,
        )
    return summary

"""Run BOTH operator notebooks end to end, offline, cell by cell.

The structural guard tests pin the notebooks' shape; this module actually
EXECUTES them: every code cell, in order, in one shared namespace — the
closest thing to an operator session that can run without a microscope.
Only the boundary is stubbed: a fake session renders every "acquisition"
from one synthetic sample (so images are consistent with where the stage
went), and a fake analysis engine segments those images
for real. The operator's button presses (select a job, press Measure,
press Acquire) are scripted between cells, exactly where a human would
act.

If a cell references a variable defined later, calls an API that was
renamed, or the widgets' wiring drifts, these tests fail — which is the
whole point: "do the notebooks actually work?" answered in CI.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import math  # noqa: E402
import re  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

nbformat = pytest.importorskip("nbformat")

import workflow  # noqa: E402
from workflow._simulation import (  # noqa: E402
    INJECTED_ERROR_UM,
    SimulatedEngine,
    SimulatedSession,
    SimulatedWorld,
    write_ome,
)

_NB_DIR = Path(__file__).resolve().parents[1]

# The simulated target job is deliberately mis-aimed by INJECTED_ERROR_UM
# (see workflow._simulation) — small enough not to disturb this run, and
# available for any flow that wants to measure it.
_INJECTED_ERROR_UM = INJECTED_ERROR_UM


# ---------------------------------------------------------------------------
# The simulated microscope lives in workflow._simulation so the web
# interface's demo mode drives EXACTLY the boundary these tests prove out.
# The local names below keep this harness readable.
# ---------------------------------------------------------------------------

_World = SimulatedWorld
_SimSession = SimulatedSession
_SimEngine = SimulatedEngine
_write_ome = write_ome


# ---------------------------------------------------------------------------
# The cell runner: execute every code cell in order, performing the
# operator's actions (job selection, button presses) between the right cells.
# ---------------------------------------------------------------------------


def _run_notebook(nb_path: Path, session: _SimSession, engine: _SimEngine, monkeypatch) -> dict:
    nb = nbformat.read(str(nb_path), as_version=4)

    # The only boundary that is faked: connecting and loading the engine.
    monkeypatch.setattr(workflow, "connect", lambda vendor, **kw: session)
    monkeypatch.setattr(workflow, "load_analysis_engine", lambda repo: engine)
    # (preflight_analysis_engine runs for real, against the fake engine.)

    namespace: dict = {"__name__": "__main__", "display": lambda *a, **k: None}
    for cell in nb.cells:
        if cell.cell_type != "code":
            continue
        source = cell.source
        # The operator selects each job in LAS X before capturing its state.
        if "overview_state = zmart_controller.get_state()" in source:
            session.select_job("Sim Overview 10x")
        if "target_state = zmart_controller.get_state()" in source:
            session.select_job("Sim Target 63x")
        try:
            exec(compile(source, f"{nb_path.name}::cell", "exec"), namespace)  # noqa: S102
        except Exception as exc:  # pragma: no cover - the failure message IS the test
            raise AssertionError(
                f"{nb_path.name}: this cell failed offline:\n---\n{source}\n---\n{exc!r}"
            ) from exc
        # The operator's button presses, right where a human would click.
        if "pick_focus_points(" in source:
            namespace["picker"].measure()
        if "acquire_gallery(" in source:
            namespace["gallery"].acquire(2)
    return namespace


def _assert_full_run(ns: dict, session: _SimSession, engine: _SimEngine, output_root: Path) -> None:
    # The overview really scanned, and discovery found the synthetic cells.
    assert len(ns["overview_records"]) == 4
    assert len(ns["targets"]) >= 4
    for target in ns["targets"]:
        assert math.hypot(target["x"], target["y"]) < 250.0  # inside the scanned area
    # The gallery committed an honest result and the summary was written.
    assert len(ns["gallery"].records) == 2 == len(ns["gallery"].picked)
    root = ns["ROOT"]
    assert root.parent == output_root
    assert root.name.startswith("target-acquisition_")
    assert (root / "summary.json").exists() and (root / "run_layout.png").exists()
    for acquisition_type, records in (
        ("overview", ns["overview_records"]),
        ("target", ns["gallery"].records),
    ):
        data = root / acquisition_type / "data"
        assert data.is_dir()
        assert all(
            Path(path).parent == data and Path(path).is_file()
            for record in records
            for path in record["images"]
        )
        assert all(
            re.fullmatch(
                rf"{acquisition_type}_[0-9a-z]{{6}}_"
                r"K\d{2}_M\d{6}_G\d{6}_P\d{6}_V\d{2}_"
                r"T\d{6}_C\d{2}_Z\d{5}\.ome\.tiff",
                Path(path).name,
            )
            for record in records
            for path in record["images"]
        )
    # The cleanup cell really tore the boundary down.
    assert session.disconnected and engine.shut_down and "engine" not in ns


@pytest.mark.parametrize(
    "notebook", ["zmart_microscopy_v4.ipynb", "zmart_microscopy_v4_react.ipynb"]
)
def test_notebook_runs_end_to_end_offline(notebook, tmp_path, monkeypatch):
    """Every code cell of the operator notebook executes, in order, offline."""
    if "react" in notebook:
        pytest.importorskip("anywidget")
    session = _SimSession(tmp_path / "run")
    engine = _SimEngine()
    ns = _run_notebook(_NB_DIR / notebook, session, engine, monkeypatch)
    _assert_full_run(ns, session, engine, tmp_path / "run")


def test_the_fake_engine_finds_the_fake_cells(tmp_path):
    """Sanity for the harness itself: the segmentation sees the world's cells."""
    world = _World()
    image = world.render(0.0, 0.0, 1.2, (128, 128))
    path = _write_ome(tmp_path / "tile.ome.tif", image, 1.2)
    engine = _SimEngine()
    engine.submit("overview", {"image_path": str(path), "naming_p": 0})
    picks = engine.results("overview")[0]["pick_targets"]["picks"]
    assert len(picks) >= 3

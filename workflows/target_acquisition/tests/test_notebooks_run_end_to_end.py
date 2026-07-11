"""Run BOTH operator notebooks end to end, offline, cell by cell.

The structural guard tests pin the notebooks' shape; this module actually
EXECUTES them: every code cell, in order, in one shared namespace — the
closest thing to an operator session that can run without a microscope.
Only the boundary is stubbed: a fake session renders every "acquisition"
from one synthetic sample (so images are consistent with where the stage
went, and the calibration check can recover a deliberately mis-set
objective translation), and a fake analysis engine segments those images
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
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import pytest  # noqa: E402
import tifffile  # noqa: E402

nbformat = pytest.importorskip("nbformat")

import workflow  # noqa: E402

_NB_DIR = Path(__file__).resolve().parents[1]

# The fake objective-pair calibration is deliberately mis-set by this much:
# the notebooks' calibration check (section 5b) must measure it back.
_INJECTED_ERROR_UM = (1.8, -1.2)


# ---------------------------------------------------------------------------
# The synthetic sample: gaussian "cells" scattered over the stage area.
# Every acquisition renders the commanded field of view from this one world,
# so overview tiles, target shots, and the calibration pairs all agree about
# where things are — like a real (if suspiciously tidy) piece of tissue.
# ---------------------------------------------------------------------------


class _World:
    def __init__(self, seed: int = 7, extent_um: float = 1200.0) -> None:
        rng = np.random.default_rng(seed)
        spacing = 25.0  # one cell per (spacing x spacing) um on average
        n = int((2 * extent_um / spacing) ** 2)
        self.cx = rng.uniform(-extent_um, extent_um, n)
        self.cy = rng.uniform(-extent_um, extent_um, n)
        self.sigma = rng.uniform(2.5, 5.0, n)
        self.amp = rng.uniform(0.4, 1.0, n)

    def render(self, center_x: float, center_y: float, pixel_um: float, shape: tuple) -> np.ndarray:
        h, w = shape
        # The same pixel convention the pipeline uses: index - size/2.
        xs = center_x + (np.arange(w) - w / 2.0) * pixel_um
        ys = center_y + (np.arange(h) - h / 2.0) * pixel_um
        margin = 4 * float(self.sigma.max())
        keep = (
            (self.cx > xs[0] - margin)
            & (self.cx < xs[-1] + margin)
            & (self.cy > ys[0] - margin)
            & (self.cy < ys[-1] + margin)
        )
        image = np.zeros((h, w), dtype=np.float32)
        for cx, cy, sigma, amp in zip(
            self.cx[keep], self.cy[keep], self.sigma[keep], self.amp[keep], strict=True
        ):
            gx = np.exp(-((xs - cx) ** 2) / (2 * sigma**2))
            gy = np.exp(-((ys - cy) ** 2) / (2 * sigma**2))
            image += amp * np.outer(gy, gx).astype(np.float32)
        return (np.clip(image, 0.0, 2.0) * 20000.0 + 800.0).astype(np.uint16)


def _write_ome(path: Path, array: np.ndarray, pixel_um: float) -> Path:
    h, w = array.shape
    description = (
        '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
        '<Image><Pixels DimensionOrder="XYCZT" Type="uint16" '
        f'SizeX="{w}" SizeY="{h}" SizeC="1" SizeZ="1" SizeT="1" '
        f'PhysicalSizeX="{pixel_um}" PhysicalSizeY="{pixel_um}"/>'
        "</Image></OME>"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tifffile.imwrite(path, array, description=description)
    return path


class _SimSession:
    """The controller surface, backed by the synthetic sample.

    Two jobs with different pixel sizes stand in for the two objectives;
    the "target" job lands off by ``_INJECTED_ERROR_UM`` — the mis-set
    calibration the notebooks' section 5b exists to measure.
    """

    _JOBS = {
        "Sim Overview 10x": {"pixel_um": 1.2, "shape": (128, 128), "error": (0.0, 0.0)},
        "Sim Target 63x": {"pixel_um": 0.35, "shape": (128, 128), "error": _INJECTED_ERROR_UM},
    }

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        # The real driver's run root exists the moment get_root answers.
        self.root.mkdir(parents=True, exist_ok=True)
        self.world = _World()
        self.job = "Sim Overview 10x"
        self.position = (0.0, 0.0, 0.0)
        self.count = 0
        self.disconnected = False

    # -- what the operator does in LAS X between cells 3a and 3b ----------
    def select_job(self, name: str) -> None:
        assert name in self._JOBS, name
        self.job = name

    # -- the Session ops the notebooks call --------------------------------
    def set_origin(self) -> dict:
        return {"origin": {"x": 0.0, "y": 0.0, "z": 0.0}}

    def get_state(self) -> dict:
        return {
            "changeable": {"job": self.job},
            "observed": {
                "limits": {
                    "schema_version": 1,
                    "source": "machine",
                    "path": "<simulated>",
                    "is_fallback": False,
                }
            },
        }

    def set_state(self, state: dict) -> dict:
        job = (state.get("changeable") or {}).get("job")
        if job:
            self.select_job(job)
        return {"applied": {"job": self.job}}

    def get_procedures(self) -> dict:
        return {
            "get_root": {},
            "get_positions": {},
            "get_focus_points": {},
            "autofocus": {},
        }

    def run_procedure(self, procedure: dict) -> dict:
        name = procedure.get("name")
        if name == "get_root":
            return {"root": str(self.root)}
        if name == "get_positions":
            step = 130.0  # a touch under the overview field of view
            return {
                "positions": [
                    {"x": sx, "y": sy, "z": 0.0}
                    for sy in (-step / 2, step / 2)
                    for sx in (-step / 2, step / 2)
                ]
            }
        if name == "get_focus_points":
            return {
                "positions": [
                    {"x": -100.0, "y": -100.0},
                    {"x": 100.0, "y": -100.0},
                    {"x": 0.0, "y": 100.0},
                ]
            }
        if name == "autofocus":
            return {"frame_z_um": 5.0}  # a flat, honest focal plane
        raise ValueError(f"unknown procedure {name!r}")

    def get_xyz(self) -> dict:
        x, y, z = self.position
        return {axis: {"value": value} for axis, value in (("x", x), ("y", y), ("z", z))}

    def set_xyz(self, x: float, y: float, z: float, **_kw: object) -> dict:
        self.position = (float(x), float(y), float(z))
        return {"position": {"x": x, "y": y, "z": z}}

    def acquire(self, *, acquisition_type: str, position_label: str, options=None) -> dict:
        job = self._JOBS[self.job]
        err_x, err_y = job["error"]
        x, y, _z = self.position
        self.count += 1
        image = self.world.render(x + err_x, y + err_y, job["pixel_um"], job["shape"])
        path = _write_ome(
            self.root / acquisition_type / f"{position_label}-{self.count}.ome.tif",
            image,
            job["pixel_um"],
        )
        return {
            "acquisition_type": acquisition_type,
            "position_label": position_label,
            "images": [str(path)],
        }

    def disconnect(self) -> None:
        self.disconnected = True


class _SimEngine:
    """The smart-analysis contract, answered by honest blob segmentation.

    ``submit``/``status``/``results`` match what ``discover_targets``
    drives; the picks come from thresholding the actual rendered images,
    so the targets the notebooks gate and acquire really are the bright
    cells in the overview tiles.
    """

    def __init__(self) -> None:
        self._pending: list[dict] = []
        self._done: list[dict] = []
        self.shut_down = False

    def register(self, _name: str, _pipeline: object) -> None:
        pass

    def shutdown(self) -> None:
        self.shut_down = True

    def submit(self, _queue: str, payload: dict) -> None:
        self._pending.append(dict(payload))

    def status(self, _queue: str) -> dict:
        return {"pending": len(self._pending), "running": 0, "failed": 0, "failures": []}

    def results(self, _queue: str) -> list[dict]:
        from skimage.measure import label, regionprops

        while self._pending:
            payload = self._pending.pop(0)
            image = tifffile.imread(payload["image_path"]).astype(np.float32)
            threshold = float(image.mean() + 2.0 * image.std())
            labels = label(image > threshold)
            picks = []
            for region in regionprops(labels, intensity_image=image):
                if region.area < 6:
                    continue  # noise specks are not cells
                row, col = region.centroid
                picks.append(
                    {
                        "centroid_col_row_px": (float(col), float(row)),
                        "area_px": float(region.area),
                        "eccentricity": float(region.eccentricity),
                        "mean_intensity": float(
                            getattr(region, "intensity_mean", 0.0)
                        ),
                    }
                )
            n_picks = payload.get("n_picks")
            if n_picks:
                picks.sort(key=lambda p: p["area_px"], reverse=True)
                picks = picks[: int(n_picks)]
            self._done.append({"input": payload, "pick_targets": {"picks": picks}})
        drained, self._done = self._done, []
        return drained


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


def _assert_full_run(ns: dict, session: _SimSession, engine: _SimEngine, root: Path) -> None:
    # The calibration check measured the deliberately mis-set translation.
    report = ns["calibration_report"]
    assert report["mean_dx_um"] == pytest.approx(_INJECTED_ERROR_UM[0], abs=0.5)
    assert report["mean_dy_um"] == pytest.approx(_INJECTED_ERROR_UM[1], abs=0.5)
    assert (root / "calibration_check.json").exists()
    # The overview really scanned, and discovery found the synthetic cells.
    assert len(ns["overview_records"]) == 4
    assert len(ns["targets"]) >= 4
    for target in ns["targets"]:
        assert math.hypot(target["x"], target["y"]) < 250.0  # inside the scanned area
    # The gallery committed an honest result and the summary was written.
    assert len(ns["gallery"].records) == 2 == len(ns["gallery"].picked)
    assert (root / "summary.json").exists() and (root / "run_layout.png").exists()
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

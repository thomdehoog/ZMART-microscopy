"""Execute the real calibration notebook, cell by cell, on a simulated scope.

The other integration tests call the workflow *functions*; this file runs the
actual ``calibrate_objective_pair.ipynb`` code cells in their notebook order,
the way an operator would, against a small physical simulator:

- A textured scene. Each objective views the stage through its own true
  translation (``lens views stage - T[lens]``, the same convention the
  ground-truth frame tests use), and the image blurs as z-wide moves away
  from that lens's focal plane.
- Acquisition renders real pixels from that scene, and the REAL algorithms
  run on them: the Brenner focus fit finds the focal plane and the voting
  registration measures the parcentricity shift. Nothing about the
  measurement math is mocked -- only the LAS X wire.
- Between cells, a simulated operator turns the turret (which jolts the
  stage a little, like real firmware) and refocuses, exactly as the
  notebook instructions ask.

The pass criterion is physical: the calibration the notebook publishes must
reconstruct the simulator's ground-truth translations, and the validation
cells must show the compensated move landing back on the same spot.

A second test drives the operator-mistake paths through the same cells:
running a cell with the wrong lens in must refuse without destroying
anything, and re-running after switching must simply work.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import tifffile

pytest.importorskip("cv2")
pytest.importorskip("scipy")

from navigator_expert.calibration.core import common as cm
from navigator_expert.calibration.core import objective_pair as wf_obj
from navigator_expert.config.machine import MachineProfile
from scipy.ndimage import gaussian_filter

NOTEBOOK_PATH = Path(wf_obj.__file__).parents[1] / "notebooks" / "calibrate_objective_pair.ipynb"

# Ground truth the notebook must reconstruct: slot 1 (10x) is the reference,
# slot 2 (20x) sits 12 um right, 8 um down, and 6 um deeper in focus.
TRUE_T = {1: (0.0, 0.0, 0.0), 2: (12.0, -8.0, 6.0)}
OBJECTIVE_NAMES = {1: "10x", 2: "20x"}
FOCUS0 = 100.0  # z-wide focal plane of the reference lens
HOME = (512.0, 512.0)  # stage position; also scene coordinates (1 um/pixel)
SWAP_DRIFT = (3.0, -2.0)  # stage jolt the simulated firmware adds per turret turn
IMAGE_SHAPE = (192, 192)
PIXEL_UM = 1.0
BLUR_PER_UM = 0.6  # defocus blur sigma per um away from the focal plane


class SimulatedScope:
    """A tiny physical model of the stage, turret, and camera."""

    def __init__(self):
        rng = np.random.RandomState(42)
        scene = gaussian_filter(rng.rand(1024, 1024), 2.0)
        self.scene = (scene - scene.min()) / (scene.max() - scene.min())
        self.x, self.y = HOME
        self.zwide = 99.0  # roughly focused, like an operator who just found the sample
        self.slot = 1
        self.job = "Overview"
        # The operator-configured LAS X z-stack (begin/end/sections).
        self.stack = {"begin": 95.0, "end": 105.0, "sections": 11, "zDrive": "z-wide"}

    # -- operator actions -------------------------------------------------
    def turret(self, slot: int) -> None:
        """Switch objectives; the firmware jolts the stage a little."""
        if slot != self.slot:
            self.slot = slot
            self.x += SWAP_DRIFT[0]
            self.y += SWAP_DRIFT[1]

    def configure_stack(self, begin: float, end: float, sections: int = 11) -> None:
        self.stack = {"begin": begin, "end": end, "sections": sections, "zDrive": "z-wide"}

    # -- physics -----------------------------------------------------------
    def focal_plane(self) -> float:
        return FOCUS0 + TRUE_T[self.slot][2]

    def render(self, zwide: float | None = None) -> np.ndarray:
        """What the camera sees right now: the lens views stage - T[lens]."""
        z = self.zwide if zwide is None else zwide
        tx, ty, _tz = TRUE_T[self.slot]
        cx, cy = self.x - tx, self.y - ty
        h, w = IMAGE_SHAPE
        r0 = int(round(cy)) - h // 2
        c0 = int(round(cx)) - w // 2
        img = self.scene[r0 : r0 + h, c0 : c0 + w]
        blur = BLUR_PER_UM * abs(z - self.focal_plane())
        if blur > 0.05:
            img = gaussian_filter(img, blur)
        return (img * 4000.0).astype(np.uint16)


def _install_simulator(monkeypatch, machine) -> SimulatedScope:
    """Wire the simulator into every LAS X seam the workflow talks to."""
    sim = SimulatedScope()
    drv = cm.drv  # objective_pair / calibration_check import the same module

    monkeypatch.setattr("navigator_expert.config.machine.MACHINE", machine)
    monkeypatch.setattr(drv, "connect_python_client", lambda *a, **k: object())
    monkeypatch.setattr(
        drv,
        "connect_limits_handshake",
        lambda client, **k: SimpleNamespace(ok=True, error=None),
    )
    monkeypatch.setattr(
        drv,
        "get_hardware_info",
        lambda client, **kw: {
            "Microscope": {
                "objectives": [
                    {"slotIndex": s, "objectiveNumber": s, "name": n}
                    for s, n in OBJECTIVE_NAMES.items()
                ]
            }
        },
    )
    monkeypatch.setattr(drv, "get_selected_job", lambda client, **kw: {"Name": sim.job})

    def _get_job_settings(client, job_name, **kw):
        return {
            "objective": {"slotIndex": sim.slot, "name": OBJECTIVE_NAMES[sim.slot]},
            "zoom": {"current": 1.0},
            "scanSpeed": {"value": 600.0, "isResonant": False},
            "activeSettings": [],
            "scanMode": "xyz",
            "stack": dict(sim.stack),
        }

    monkeypatch.setattr(drv, "get_job_settings", _get_job_settings)
    monkeypatch.setattr(
        drv,
        "make_changeable_copy",
        lambda settings: (
            None
            if settings is None
            else {"stack": dict(settings["stack"]) if settings.get("stack") else None}
        ),
    )
    monkeypatch.setattr(
        drv,
        "parse_tile_geometry",
        lambda settings: {
            "pixel_w_um": PIXEL_UM,
            "pixel_h_um": PIXEL_UM,
            "pixels_x": IMAGE_SHAPE[1],
            "pixels_y": IMAGE_SHAPE[0],
        },
    )
    monkeypatch.setattr(drv, "get_xy", lambda client, **kw: {"x_um": sim.x, "y_um": sim.y})

    def _move_xy(client, x, y, unit="um", **kw):
        sim.x, sim.y = float(x), float(y)
        return {"success": True}

    def _move_z(client, job_name, z, unit="um", z_mode="galvo", **kw):
        if z_mode == "zwide":
            sim.zwide = float(z)
        return {"success": True, "confirmed": True}

    monkeypatch.setattr(drv, "move_xy", _move_xy)
    monkeypatch.setattr(drv, "move_z", _move_z)
    monkeypatch.setattr(drv, "read_zwide_um", lambda client, job_name, **kw: float(sim.zwide))
    monkeypatch.setattr(cm._movement, "correct_backlash", lambda client, *, passes, **kw: None)

    # Acquisition: render real pixels from the scene, write real TIFFs, and
    # let the real load/fit/register code consume them.
    def _acquire(client, job, **kw):
        return SimpleNamespace(job=job, command_result={"success": True})

    def _save(client, acq, output_root, naming, **kw):
        output_root = Path(output_root)
        output_root.mkdir(parents=True, exist_ok=True)
        image_paths = {}
        if naming.acquisition_type == "calibration-stack":
            positions = np.linspace(
                float(sim.stack["begin"]),
                float(sim.stack["end"]),
                int(sim.stack["sections"]),
            )
            for i, z in enumerate(positions):
                path = output_root / f"plane_z{i:03d}.tif"
                tifffile.imwrite(path, sim.render(zwide=float(z)))
                image_paths[drv.PlaneIndex(t=0, z=i, c=0)] = path
        else:
            path = output_root / "plane_z000.tif"
            tifffile.imwrite(path, sim.render())
            image_paths[drv.PlaneIndex(t=0, z=0, c=0)] = path
        return SimpleNamespace(image_paths=image_paths, naming=naming)

    monkeypatch.setattr(drv, "acquire", _acquire)
    monkeypatch.setattr(drv, "save", _save)
    return sim


# ---------------------------------------------------------------------
# Notebook cell access
# ---------------------------------------------------------------------


def _notebook_cells() -> dict[str, str]:
    """Load the real notebook and key its code cells by workflow step."""
    notebook = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
    sources = ["".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code"]
    markers = {
        "configure": "objective_pair.start_session",
        "parfocality_ref": "measure_parfocality_reference",
        "parfocality_target": "measure_parfocality_target",
        "parcentricity_ref": "measure_parcentricity_reference",
        "parcentricity_target": "measure_parcentricity_target_and_save",
        "check_ref": "calibration_check.start_session",
        "check_target": "measure_target_and_report",
        "adopt": "save_and_adopt",
    }
    cells: dict[str, str] = {}
    for key, marker in markers.items():
        matches = [src for src in sources if marker in src]
        # check_target's marker also appears in the adopt cell's required_code
        # comment-free source; keep the first cell that is not already taken.
        for src in matches:
            if src not in cells.values():
                cells[key] = src
                break
        assert key in cells, f"no notebook cell found for {key!r} ({marker!r})"
    return cells


@pytest.fixture
def notebook_runtime(monkeypatch, tmp_path):
    """A simulated scope + a namespace that executes the real notebook cells."""
    machine = MachineProfile(programdata_root=tmp_path / "programdata")
    sim = _install_simulator(monkeypatch, machine)

    # The notebook's first cell does `import _bootstrap` for sys.path setup and
    # the browser-save checkpoint. Headless there is no browser, so the fake
    # checkpoint skips the save-verification step but still hands the REAL
    # notebook path to the adopt callback (archiving then copies the real file).
    fake_bootstrap = types.ModuleType("_bootstrap")
    fake_bootstrap.NOTEBOOK_PATH = NOTEBOOK_PATH
    fake_bootstrap.NOTEBOOK = SimpleNamespace(save_and_adopt=lambda fn: fn(str(NOTEBOOK_PATH)))
    monkeypatch.setitem(sys.modules, "_bootstrap", fake_bootstrap)

    cells = _notebook_cells()
    namespace: dict = {}

    def run(cell_key: str):
        exec(compile(cells[cell_key], f"<notebook:{cell_key}>", "exec"), namespace)
        return namespace

    return SimpleNamespace(sim=sim, machine=machine, run=run, ns=namespace)


# ---------------------------------------------------------------------
# The happy path: an operator runs the notebook top to bottom
# ---------------------------------------------------------------------


def test_notebook_cells_reconstruct_ground_truth_on_simulated_scope(notebook_runtime):
    sim, machine, run = notebook_runtime.sim, notebook_runtime.machine, notebook_runtime.run

    # Configure: reference objective in, roughly focused, stack around it.
    run("configure")

    # Measure 1: reference focus stack.
    sim.configure_stack(95.0, 105.0)
    run("parfocality_ref")
    session = notebook_runtime.ns["session"]
    assert abs(session.focus_z_ref_um - FOCUS0) < 0.5

    # Measure 2: switch to the target lens, refocus by eye, re-center the stack.
    sim.turret(2)
    sim.zwide = 104.0  # close but not exact, like a human
    sim.configure_stack(101.0, 111.0)
    run("parfocality_target")
    assert abs(session.translation_z_um - TRUE_T[2][2]) < 0.5

    # Measure 3: back to the reference lens for the X/Y image.
    sim.turret(1)
    run("parcentricity_ref")

    # Measure 4: target lens back in; the turret jolt is part of the physics.
    sim.turret(2)
    run("parcentricity_target")
    summary = notebook_runtime.ns["summary"]
    assert summary["config_written"] is True
    assert summary["registration"]["trusted"] is True
    tx, ty = summary["translation_xy_um"]
    assert abs(tx - TRUE_T[2][0]) < 0.51
    assert abs(ty - TRUE_T[2][1]) < 0.51

    # Validation: park on the spot with the reference lens, focused.
    sim.turret(1)
    sim.zwide = FOCUS0
    run("check_ref")
    sim.turret(2)
    run("check_target")
    check_session = notebook_runtime.ns["check_session"]
    report = check_session.report
    assert report["trusted"] is True
    # The compensated move must land back on the same spot: the leftover
    # offset is the physical proof the calibration works on this simulator.
    assert report["offset_um"] is not None and report["offset_um"] < 0.75

    # Save and Adopt: publishes the machine snapshot and archives the notebook.
    run("adopt")
    adopted = notebook_runtime.ns["adopted"]
    published = json.loads(machine.calibration_path().read_text(encoding="utf-8"))
    t2 = published["objectives"]["2"]["translation_um"]
    assert published["objectives"]["1"]["translation_um"] == [0.0, 0.0, 0.0]
    for measured, true in zip(t2, TRUE_T[2], strict=True):
        assert abs(measured - true) < 0.51
    archived = [Path(p) for p in adopted["notebook_paths"]]
    assert archived and all(p.exists() for p in archived)


# ---------------------------------------------------------------------
# The mistake paths: wrong lens in, rerun after switching
# ---------------------------------------------------------------------


def test_notebook_cells_survive_wrong_lens_and_rerun(notebook_runtime):
    sim, run = notebook_runtime.sim, notebook_runtime.run

    run("configure")
    sim.configure_stack(95.0, 105.0)
    run("parfocality_ref")
    session = notebook_runtime.ns["session"]
    focus_ref = session.focus_z_ref_um

    # Mistake 1: run the target-focus cell while the reference lens is
    # still in. It must refuse loudly and destroy nothing.
    with pytest.raises(RuntimeError, match="still the reference objective"):
        run("parfocality_target")
    assert session.focus_z_ref_um == focus_ref

    # Recovery is just: switch the lens, run the same cell again.
    sim.turret(2)
    sim.zwide = 104.0
    sim.configure_stack(101.0, 111.0)
    run("parfocality_target")
    assert abs(session.translation_z_um - TRUE_T[2][2]) < 0.5

    # Mistake 2: run the reference X/Y cell with the target lens still in.
    # It must refuse, and the target focus measurement must survive.
    with pytest.raises(RuntimeError, match="wrong objective for reference step"):
        run("parcentricity_ref")
    assert session.focus_z_target_um is not None
    assert session.translation_z_um is not None

    # Recovery: switch back and rerun; then finish the pair normally.
    sim.turret(1)
    run("parcentricity_ref")
    sim.turret(2)
    run("parcentricity_target")
    summary = notebook_runtime.ns["summary"]
    assert summary["config_written"] is True
    tx, ty = summary["translation_xy_um"]
    assert abs(tx - TRUE_T[2][0]) < 0.51
    assert abs(ty - TRUE_T[2][1]) < 0.51

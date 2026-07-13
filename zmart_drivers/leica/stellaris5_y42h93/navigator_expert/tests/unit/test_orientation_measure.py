"""Mock-driven tests for the ``set_orientation`` measurement.

Exercises the D4 measurement guards (weak-vote stop, residual guard, singular
fit), all eight rotation/mirror mappings, the staging ``orientation.json``, and
adoption into the microscope's ProgramData snapshot. The converter itself is
covered by ``test_orientation.py``.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import tifffile

pytest.importorskip("cv2")  # calibration.core.common (reused by measure) imports cv2

from navigator_expert.acquisition.naming import build_image_name
from navigator_expert.calibration.core import common as cm
from navigator_expert.orientation import Orientation
from navigator_expert.orientation import measure as wf


@pytest.fixture
def sessions_root(tmp_path):
    return tmp_path / "sessions"


def _saved_manifest(output_root, naming, image):
    image_path = Path(output_root) / build_image_name(naming)
    image_path.parent.mkdir(parents=True, exist_ok=True)
    tifffile.imwrite(image_path, np.asarray(image))
    return SimpleNamespace(
        image_paths={cm.drv.PlaneIndex(t=0, z=0, c=0): image_path},
        xml_paths={cm.drv.PositionIndex(t=0, v=0): Path(output_root) / "mock.ome.xml"},
        naming=naming,
    )


def _synthetic_blob_image(shape, rng):
    """Microscopy-like, non-periodic features with stable registration landmarks."""
    yy, xx = np.indices(shape, dtype=float)
    image = np.zeros(shape, dtype=float)
    margin = min(shape) * 0.18
    for _ in range(36):
        cx = rng.uniform(margin, shape[1] - margin)
        cy = rng.uniform(margin, shape[0] - margin)
        sigma_x = rng.uniform(1.8, 7.0)
        sigma_y = rng.uniform(1.8, 7.0)
        amplitude = rng.uniform(0.25, 1.0)
        image += amplitude * np.exp(
            -0.5 * (((xx - cx) / sigma_x) ** 2 + ((yy - cy) / sigma_y) ** 2)
        )
    image += rng.normal(0.0, 0.008, shape)
    image -= image.min()
    image /= image.max()
    return (image * np.iinfo(np.uint16).max).astype(np.uint16)


def _translate_without_wrap(image, dx_px, dy_px):
    """Translate features like a camera frame; do not wrap opposite edges."""
    output = np.full_like(image, int(np.median(image)))
    src_x = slice(max(0, -dx_px), min(image.shape[1], image.shape[1] - dx_px))
    src_y = slice(max(0, -dy_px), min(image.shape[0], image.shape[0] - dy_px))
    dst_x = slice(max(0, dx_px), min(image.shape[1], image.shape[1] + dx_px))
    dst_y = slice(max(0, dy_px), min(image.shape[0], image.shape[0] + dy_px))
    output[dst_y, dst_x] = image[src_y, src_x]
    return output


def _patch(
    monkeypatch,
    *,
    pixel_size_um=0.5,
    image_shape=(64, 64),
    home_xy=(1000.0, 2000.0),
    image_to_stage=None,
):
    monkeypatch.setattr(wf.drv, "connect_python_client", lambda *a, **k: object())
    monkeypatch.setattr(
        wf.drv,
        "connect_limits_handshake",
        lambda client, **k: SimpleNamespace(
            ok=True,
            error=None,
            stage_cfg={"stage_um": {"x": [1000.0, 130000.0], "y": [1000.0, 100000.0]}},
        ),
    )
    monkeypatch.setattr(wf.drv, "get_hardware_info", lambda client, **kw: {"ok": True})

    pos = {"x": home_xy[0], "y": home_xy[1]}

    def _get_xy(client, **kw):
        return {"x_um": pos["x"], "y_um": pos["y"]}

    def _move_xy(client, x, y, unit="um", **kw):
        pos["x"] = x
        pos["y"] = y
        return {"success": True}

    monkeypatch.setattr(wf.drv, "get_xy", _get_xy)
    monkeypatch.setattr(cm.drv, "get_xy", _get_xy)
    monkeypatch.setattr(cm.drv, "move_xy", _move_xy)
    monkeypatch.setattr(cm.drv, "get_job_settings", lambda *a, **k: {"some": "settings"})
    monkeypatch.setattr(
        cm.drv,
        "parse_tile_geometry",
        lambda settings: {
            "pixel_w_um": pixel_size_um,
            "pixel_h_um": pixel_size_um,
            "pixels_x": image_shape[1],
            "pixels_y": image_shape[0],
        },
    )

    rng = np.random.RandomState(42)
    if image_to_stage is None:
        template = (rng.rand(*image_shape) * 255).astype(np.uint16)
    else:
        template = _synthetic_blob_image(image_shape, rng)

    def _acquire(client, job, **kw):
        return SimpleNamespace(job=job, command_result={"success": True})

    def _save(client, acq, output_root, naming, **kw):
        image = template.copy()
        if image_to_stage is not None:
            stage_delta = np.array([pos["x"] - home_xy[0], pos["y"] - home_xy[1]])
            stage_to_image = -np.linalg.inv(np.asarray(image_to_stage, dtype=float))
            dx_um, dy_um = stage_to_image @ stage_delta
            dx_px = int(round(dx_um / pixel_size_um))
            dy_px = int(round(dy_um / pixel_size_um))
            image = _translate_without_wrap(image, dx_px, dy_px)
        return _saved_manifest(output_root, naming, image)

    monkeypatch.setattr(cm.drv, "acquire", _acquire)
    monkeypatch.setattr(cm.drv, "save", _save)
    return pos


def _install_votes(monkeypatch, votes):
    iterator = iter(votes)
    monkeypatch.setattr(wf, "register_voting", lambda ref, tgt, px, **kw: next(iterator))


def _trusted(dx, dy):
    return {
        "dx_um": dx,
        "dy_um": dy,
        "trusted": True,
        "confidence": 4,
        "agreeing": ["pcc", "masked_pcc", "ncc", "orb"],
    }


def _untrusted():
    return {"dx_um": float("nan"), "dy_um": float("nan"), "trusted": False, "confidence": 0}


def _start(sessions_root, **kw):
    return wf.start_session(
        session_id=kw.pop("session_id", "orient"),
        job_name="Overview",
        reference_objective="10x",
        stage_move_um=kw.pop("stage_move_um", 30.0),
        settle_s=0.0,
        sessions_root=sessions_root,
    )


def test_measure_success_writes_staging_orientation(monkeypatch, sessions_root):
    _patch(monkeypatch)
    # +X (30 um) -> image (0, +30) um; +Y (30 um) -> image (-30, 0) um: the
    # "-Y +X" canonical [[0,-1],[1,0]], a 90-degree clockwise reorientation.
    _install_votes(monkeypatch, [_trusted(0.0, 30.0), _trusted(-30.0, 0.0)])

    session = _start(sessions_root, session_id="ok")
    session = wf.measure(session)

    assert session.d4_accepted is True
    assert session.d4_label == "-Y +X"
    assert session.residual_from_d4 == pytest.approx(0.0, abs=1e-9)
    assert session.is_mirrored is False
    assert session.orientation == Orientation(rotate_deg=90)
    assert session.config_written is True

    staging = session.paths.configs_dir / wf.STAGING_NAME
    assert staging.is_file()
    payload = json.loads(staging.read_text(encoding="utf-8"))
    # "measured": True is the positive marker that separates a measured file
    # from the shipped placeholder (which carries "_notes" instead).
    assert payload == {
        "schema_version": 2,
        "measured": True,
        "rotate_deg": 90,
        "mirrored": False,
        "axis_signs": {"stage_x": -1, "stage_y": 1},
        "axis_mapping": {"stage_x_from_image": "-Y", "stage_y_from_image": "+X"},
        "image_to_stage": [[0, -1], [1, 0]],
    }
    diagnostic = session.paths.reports_dir / wf.DIAGNOSTIC_NAME
    assert diagnostic.is_file()
    assert diagnostic.stat().st_size > 10_000

    report = json.loads((session.paths.reports_dir / "orientation_report.json").read_text())
    assert report["image_to_stage"] == [[0, -1], [1, 0]]
    assert report["mirrored"] is False
    assert report["determinant"] == 1
    assert report["axis_signs"] == {"stage_x": -1, "stage_y": 1}
    assert report["axis_mapping"] == {
        "stage_x_from_image": "-Y",
        "stage_y_from_image": "+X",
    }
    assert report["accepted"] is True
    assert report["diagnostic"] == wf.DIAGNOSTIC_NAME


@pytest.mark.parametrize(
    "matrix,expected",
    [
        ([[1, 0], [0, 1]], Orientation(0, False)),
        ([[0, -1], [1, 0]], Orientation(90, False)),
        ([[-1, 0], [0, -1]], Orientation(180, False)),
        ([[0, 1], [-1, 0]], Orientation(270, False)),
        ([[-1, 0], [0, 1]], Orientation(0, True)),
        ([[0, -1], [-1, 0]], Orientation(90, True)),
        ([[1, 0], [0, -1]], Orientation(180, True)),
        ([[0, 1], [1, 0]], Orientation(270, True)),
    ],
)
def test_measure_recovers_all_d4_mappings_from_synthetic_images(
    monkeypatch,
    sessions_root,
    matrix,
    expected,
):
    _patch(
        monkeypatch,
        pixel_size_um=1.0,
        image_shape=(192, 192),
        image_to_stage=matrix,
    )

    session = wf.measure(
        _start(
            sessions_root,
            session_id=f"synthetic-{expected.rotate_deg}-{int(expected.mirrored)}",
            stage_move_um=20.0,
        )
    )

    assert session.d4_accepted is True
    assert session.orientation == expected
    assert session.is_mirrored is expected.mirrored
    payload = json.loads((session.paths.configs_dir / wf.STAGING_NAME).read_text())
    assert payload == wf.orientation_config(expected)


def test_measure_weak_vote_stops_without_config(monkeypatch, sessions_root):
    _patch(monkeypatch)
    _install_votes(monkeypatch, [_untrusted(), _trusted(-30.0, 0.0)])

    session = wf.measure(_start(sessions_root, session_id="weak"))

    assert session.d4_accepted is None
    assert session.orientation is None
    assert session.config_written is False
    assert session.failure_reason is not None and "not trusted" in session.failure_reason
    assert not (session.paths.configs_dir / wf.STAGING_NAME).exists()


def test_measure_accepts_and_records_mirror(monkeypatch, sessions_root):
    _patch(monkeypatch)
    # Votes that snap to the reflection "-X +Y" (det < 0) at zero residual.
    _install_votes(monkeypatch, [_trusted(40.0, 0.0), _trusted(0.0, -40.0)])

    session = wf.measure(_start(sessions_root, session_id="refl", stage_move_um=40.0))

    assert session.d4_label == "-X +Y"
    assert session.is_mirrored is True
    assert session.d4_accepted is True
    assert session.failure_reason is None
    assert session.orientation == Orientation(rotate_deg=0, mirrored=True)
    assert session.config_written is True
    payload = json.loads((session.paths.configs_dir / wf.STAGING_NAME).read_text())
    assert payload == {
        "schema_version": 2,
        "measured": True,
        "rotate_deg": 0,
        "mirrored": True,
        "axis_signs": {"stage_x": -1, "stage_y": 1},
        "axis_mapping": {"stage_x_from_image": "-X", "stage_y_from_image": "+Y"},
        "image_to_stage": [[-1, 0], [0, 1]],
    }
    diagnostic = session.paths.reports_dir / wf.DIAGNOSTIC_NAME
    assert diagnostic.is_file()
    report = json.loads((session.paths.reports_dir / "orientation_report.json").read_text())
    assert report["mirrored"] is True
    assert report["determinant"] == -1
    assert report["accepted"] is True
    assert report["rotate_deg"] == 0


def test_measure_rejects_high_residual(monkeypatch, sessions_root):
    _patch(monkeypatch)
    # Fitted matrix lands closest to a rotation but with residual ~0.59 > 0.3.
    _install_votes(monkeypatch, [_trusted(10.0, 25.0), _trusted(-25.0, 10.0)])

    session = wf.measure(_start(sessions_root, session_id="resid"))

    assert session.d4_accepted is False
    assert "D4 residual" in session.failure_reason
    assert session.orientation is None
    assert not (session.paths.configs_dir / wf.STAGING_NAME).exists()


def test_measure_singular_fit(monkeypatch, sessions_root):
    _patch(monkeypatch)
    # Both shifts along image-X: the stage->image matrix is rank-1 / singular.
    _install_votes(monkeypatch, [_trusted(30.0, 0.0), _trusted(60.0, 0.0)])

    session = wf.measure(_start(sessions_root, session_id="singular"))

    assert session.d4_accepted is None
    assert "singular" in session.failure_reason
    assert session.orientation is None


def test_measure_acquire_failure_returns_home(monkeypatch, sessions_root):
    home_xy = (1000.0, 2000.0)
    pos = _patch(monkeypatch, home_xy=home_xy)
    boom = RuntimeError("acquire failed")

    calls = {"n": 0}
    real_save = cm.drv.save

    def _save(client, acq, output_root, naming, **kw):
        calls["n"] += 1
        if calls["n"] == 2:  # second frame (plus_x) fails
            raise boom
        return real_save(client, acq, output_root, naming, **kw)

    monkeypatch.setattr(cm.drv, "save", _save)

    session = _start(sessions_root, session_id="recover")
    with pytest.raises(RuntimeError, match="acquire failed"):
        wf.measure(session)
    assert pos["x"] == home_xy[0]
    assert pos["y"] == home_xy[1]


def test_adopt_publishes_orientation_snapshot(monkeypatch, sessions_root, tmp_path):
    from datetime import datetime, timezone

    from navigator_expert.config.machine import MachineProfile

    _patch(monkeypatch)
    _install_votes(monkeypatch, [_trusted(0.0, 30.0), _trusted(-30.0, 0.0)])
    machine = MachineProfile(programdata_root=tmp_path / "programdata")

    session = wf.measure(_start(sessions_root, session_id="adopt"))
    working_session = session.paths.session_dir
    out = wf.adopt_orientation(
        session,
        machine=machine,
        moment=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
    )

    # The measured turn now lives in the microscope's newest snapshot, and the
    # machine profile reads it back as the active orientation.
    written = Path(out["orientation_path"])
    assert written == machine.latest_snapshot("orientation") / "orientation.json"
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert payload == {
        "schema_version": 2,
        "measured": True,
        "rotate_deg": 90,
        "mirrored": False,
        "axis_signs": {"stage_x": -1, "stage_y": 1},
        "axis_mapping": {"stage_x_from_image": "-Y", "stage_y_from_image": "+X"},
        "image_to_stage": [[0, -1], [1, 0]],
    }
    assert machine.orientation_path() == written
    archived_session = Path(out["measurement_session"])
    assert archived_session == written.parent / "adopt"
    assert (archived_session / "reports" / wf.DIAGNOSTIC_NAME).is_file()
    assert Path(out["source"]) == archived_session / "configs" / wf.STAGING_NAME
    assert not working_session.exists()


def test_adopt_missing_staging_raises(monkeypatch, sessions_root):
    _patch(monkeypatch)
    _install_votes(monkeypatch, [_untrusted(), _trusted(-30.0, 0.0)])
    session = wf.measure(_start(sessions_root, session_id="adopt_missing"))
    with pytest.raises(FileNotFoundError):
        wf.adopt_orientation(session)


def test_notebook_archive_waits_for_a_new_saved_file_version(tmp_path, monkeypatch):
    bootstrap_path = Path(wf.__file__).parent / "notebooks" / "_bootstrap.py"
    spec = importlib.util.spec_from_file_location("orientation_notebook_bootstrap", bootstrap_path)
    bootstrap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bootstrap)
    notebook = tmp_path / "set_orientation.ipynb"
    notebook.write_text("before", encoding="utf-8")
    previous_mtime_ns = notebook.stat().st_mtime_ns
    monkeypatch.setattr(bootstrap, "NOTEBOOK_PATH", notebook)

    os.utime(notebook, ns=(previous_mtime_ns + 1_000_000, previous_mtime_ns + 1_000_000))

    assert bootstrap.wait_for_notebook_save(previous_mtime_ns, timeout_s=0.1) == notebook


def test_orientation_notebook_displays_then_saves_before_adoption():
    notebook_path = Path(wf.__file__).parent / "notebooks" / "set_orientation.ipynb"
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    code = "\n".join(
        "".join(cell.get("source", [])) for cell in notebook["cells"] if cell["cell_type"] == "code"
    )

    assert 'sessions_root=MACHINE.work_root("orientation")' in code
    assert "display(Image(filename=str(diagnostic)))" in code
    assert code.index("request_notebook_save") < code.index("wait_for_notebook_save")
    assert code.index("wait_for_notebook_save") < code.index("adopt_orientation")

"""Mock-driven tests for the ``set_orientation`` measurement.

Ports the D4 measurement guards (weak-vote stop, reflection guard, residual
guard, singular fit) from the retired ``image_to_stage`` calibration workflow
to the new ``orientation.measure`` module, plus the success path (writes a
staging ``orientation.json`` and an :class:`Orientation`) and adoption -- which
publishes the measured turn into the microscope's ProgramData snapshot. The
converter itself is covered by ``test_orientation.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import tifffile

pytest.importorskip("cv2")  # calibration.core.common (reused by measure) imports cv2

from navigator_expert.calibration.core import common as cm
from navigator_expert.orientation import Orientation
from navigator_expert.orientation import measure as wf

from shared.output_layout import build_image_name


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


def _patch(monkeypatch, *, pixel_size_um=0.5, image_shape=(64, 64), home_xy=(1000.0, 2000.0)):
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
    template = (rng.rand(*image_shape) * 255).astype(np.uint16)

    def _acquire(client, job, **kw):
        return SimpleNamespace(job=job, command_result={"success": True})

    def _save(client, acq, output_root, naming, **kw):
        return _saved_manifest(output_root, naming, template.copy())

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
    assert session.orientation == Orientation(rotate_deg=90)
    assert session.config_written is True

    staging = session.paths.configs_dir / wf.STAGING_NAME
    assert staging.is_file()
    payload = json.loads(staging.read_text(encoding="utf-8"))
    assert payload == {"schema_version": 1, "rotate_deg": 90}


def test_measure_weak_vote_stops_without_config(monkeypatch, sessions_root):
    _patch(monkeypatch)
    _install_votes(monkeypatch, [_untrusted(), _trusted(-30.0, 0.0)])

    session = wf.measure(_start(sessions_root, session_id="weak"))

    assert session.d4_accepted is None
    assert session.orientation is None
    assert session.config_written is False
    assert session.failure_reason is not None and "not trusted" in session.failure_reason
    assert not (session.paths.configs_dir / wf.STAGING_NAME).exists()


def test_measure_rejects_reflection(monkeypatch, sessions_root):
    _patch(monkeypatch)
    # Votes that snap to the reflection "-X +Y" (det < 0) at zero residual.
    _install_votes(monkeypatch, [_trusted(40.0, 0.0), _trusted(0.0, -40.0)])

    session = wf.measure(_start(sessions_root, session_id="refl", stage_move_um=40.0))

    assert session.d4_label == "-X +Y"
    assert session.d4_accepted is False
    assert "reflection-free" in session.failure_reason
    assert session.orientation is None
    assert not (session.paths.configs_dir / wf.STAGING_NAME).exists()


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
    out = wf.adopt_orientation(
        session,
        machine=machine,
        moment=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
    )

    # The measured turn now lives in the microscope's newest snapshot, and the
    # machine profile reads it back as the active orientation.
    written = Path(out["orientation_path"])
    assert written == machine.latest_snapshot() / "orientation.json"
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert payload == {"schema_version": 1, "rotate_deg": 90}
    assert machine.orientation_path() == written


def test_adopt_missing_staging_raises(monkeypatch, sessions_root):
    _patch(monkeypatch)
    _install_votes(monkeypatch, [_untrusted(), _trusted(-30.0, 0.0)])
    session = wf.measure(_start(sessions_root, session_id="adopt_missing"))
    with pytest.raises(FileNotFoundError):
        wf.adopt_orientation(session)

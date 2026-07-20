"""Mock-driven tests for the ``set_orientation`` measurement.

Exercises the D4 measurement guards (weak-vote stop, residual guard, singular
fit), all eight rotation/reflection mappings, and the direct timestamped
ProgramData session lifecycle. The converter itself is covered by
``test_orientation.py``.
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
from navigator_expert.notebook_support import NotebookCheckpoint
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
    monkeypatch.setattr(wf.drv, "get_selected_job", lambda client, **kw: {"Name": "Overview"})

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
    monkeypatch.setattr(
        cm.drv,
        "get_job_settings",
        lambda *a, **k: {"objective": {"slotIndex": 1, "name": "10x"}},
    )
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
    from datetime import datetime, timezone

    from navigator_expert.config.machine import MachineProfile

    kw.pop("session_id", None)  # legacy test label; run names are automatic
    return wf.start_session(
        job_name="Overview",
        stage_move_um=kw.pop("stage_move_um", 30.0),
        settle_s=0.0,
        machine=MachineProfile(programdata_root=sessions_root),
        moment=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
    )


def test_gallery_covers_all_options_and_correct_candidate_has_best_overlap():
    candidates = wf._gallery_orientations()
    assert len(candidates) == 8
    assert {(item.rotate_deg, item.mirrored) for item in candidates} == {
        (degrees, mirrored) for mirrored in (False, True) for degrees in (0, 90, 180, 270)
    }

    expected = Orientation(rotate_deg=90, mirrored=True)
    stage_move_um = 20.0
    pixel_size_um = 1.0
    home = _synthetic_blob_image((192, 192), np.random.RandomState(7))
    stage_to_image = -np.linalg.inv(np.asarray(expected.image_to_stage, dtype=float))
    shift_x = np.rint(stage_to_image[:, 0] * stage_move_um / pixel_size_um).astype(int)
    shift_y = np.rint(stage_to_image[:, 1] * stage_move_um / pixel_size_um).astype(int)
    plus_x = _translate_without_wrap(home, int(shift_x[0]), int(shift_x[1]))
    plus_y = _translate_without_wrap(home, int(shift_y[0]), int(shift_y[1]))

    disagreement = {}
    for candidate in candidates:
        overlay = wf._candidate_alignment_overlay(
            home,
            plus_x,
            plus_y,
            stage_move_um=stage_move_um,
            pixel_size_um=pixel_size_um,
            orientation=candidate,
        )
        disagreement[candidate] = float(np.mean(np.abs(overlay[..., 0] - overlay[..., 1])))

    assert min(disagreement, key=disagreement.get) == expected


@pytest.mark.parametrize("rotate_deg", [0, 90, 180, 270])
def test_gallery_preview_applies_reflected_candidate_to_displayed_pixels(rotate_deg):
    home = np.zeros((7, 9), dtype=np.uint16)
    home[1:3, 1] = 1000
    home[1, 1:4] = 1000

    overlay = wf._candidate_alignment_overlay(
        home,
        home,
        home,
        stage_move_um=0.0,
        pixel_size_um=1.0,
        orientation=Orientation(rotate_deg=rotate_deg, mirrored=True),
    )

    expected_red = np.rot90(np.fliplr(wf._normalise_for_display(home)), k=-(rotate_deg // 90))
    assert np.array_equal(overlay[..., 0], expected_red)


def test_measure_success_keeps_orientation_as_candidate(monkeypatch, sessions_root):
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
    assert session.config_written is False

    orientation_path = session.paths.session_dir / wf.ORIENTATION_NAME
    assert not orientation_path.exists()
    assert wf.orientation_config(session.orientation) == {
        "schema_version": 3,
        "measured": True,
        "rotation_deg": 90,
        "reflection": False,
        "sign_convention": {
            "stage_x_from_image": "-Y",
            "stage_y_from_image": "+X",
        },
    }
    diagnostic = session.paths.reports_dir / wf.DIAGNOSTIC_NAME
    assert diagnostic.is_file()
    assert diagnostic.stat().st_size > 10_000

    report = json.loads((session.paths.reports_dir / "orientation_report.json").read_text())
    assert report["image_to_stage"] == [[0, -1], [1, 0]]
    assert report["mirrored"] is False
    assert report["reflection_axis"] is None
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
    assert not (session.paths.session_dir / wf.ORIENTATION_NAME).exists()
    assert wf.orientation_config(session.orientation) == wf.orientation_config(expected)


def test_measure_weak_vote_stops_without_config(monkeypatch, sessions_root):
    _patch(monkeypatch)
    _install_votes(monkeypatch, [_untrusted(), _trusted(-30.0, 0.0)])

    session = wf.measure(_start(sessions_root, session_id="weak"))

    assert session.d4_accepted is None
    assert session.orientation is None
    assert session.config_written is False
    assert session.failure_reason is not None and "not trusted" in session.failure_reason
    assert not (session.paths.session_dir / wf.ORIENTATION_NAME).exists()


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
    assert session.config_written is False
    assert not (session.paths.session_dir / wf.ORIENTATION_NAME).exists()
    assert wf.orientation_config(session.orientation) == {
        "schema_version": 3,
        "measured": True,
        "rotation_deg": 0,
        "reflection": True,
        "sign_convention": {
            "stage_x_from_image": "-X",
            "stage_y_from_image": "+Y",
        },
    }
    diagnostic = session.paths.reports_dir / wf.DIAGNOSTIC_NAME
    assert diagnostic.is_file()
    report = json.loads((session.paths.reports_dir / "orientation_report.json").read_text())
    assert report["mirrored"] is True
    assert report["reflection_axis"] == "vertical"
    assert report["determinant"] == -1
    assert report["accepted"] is True
    assert report["rotate_deg"] == 0


def test_measure_sign_anchor_aligned_rig_maps_to_identity(monkeypatch, sessions_root):
    # PHYSICAL SIGN ANCHOR -- the one fact the other synthetic tests otherwise
    # assume through the shared `-inv` forward-model. A perfectly axis-aligned rig
    # makes features move OPPOSITE the stage: a +X stage move shifts features
    # toward -column, a +Y move toward -row. Fed here as explicit signed votes
    # (NOT generated via -inv), that evidence must classify as the identity
    # orientation. If measure.py's `-np.linalg.inv(...)` sign were flipped, the
    # same evidence would come out as a 180-degree turn and this fails -- so it
    # guards the convention non-circularly. Bench check: on an aligned rig, move
    # the stage +X and confirm features move toward -column.
    _patch(monkeypatch)
    _install_votes(monkeypatch, [_trusted(-30.0, 0.0), _trusted(0.0, -30.0)])

    session = wf.measure(_start(sessions_root, session_id="sign-anchor"))

    assert session.d4_accepted is True
    assert session.orientation == Orientation()  # rotate_deg=0, mirrored=False
    assert session.is_mirrored is False
    assert session.d4_label == "+X +Y"
    assert session.residual_from_d4 == pytest.approx(0.0, abs=1e-9)


def test_measure_rejects_high_residual(monkeypatch, sessions_root):
    _patch(monkeypatch)
    # Fitted matrix lands closest to a rotation but with residual ~0.59 > 0.3.
    _install_votes(monkeypatch, [_trusted(10.0, 25.0), _trusted(-25.0, 10.0)])

    session = wf.measure(_start(sessions_root, session_id="resid"))

    assert session.d4_accepted is False
    assert "D4 residual" in session.failure_reason
    assert session.orientation is None
    assert not (session.paths.session_dir / wf.ORIENTATION_NAME).exists()


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


def test_measure_rerun_replaces_this_sessions_outputs(monkeypatch, sessions_root):
    _patch(monkeypatch)
    votes = [_trusted(0.0, 30.0), _trusted(-30.0, 0.0)]
    _install_votes(monkeypatch, votes + votes)
    session = wf.measure(_start(sessions_root))

    stale_paths = [
        session.paths.data_dir / "stale-data.txt",
        session.paths.reports_dir / "stale-report.txt",
        session.paths.session_dir / "validation" / "stale-validation.txt",
    ]
    for path in stale_paths:
        path.write_text("obsolete", encoding="utf-8")

    rerun = wf.measure(session)

    assert rerun is session
    assert rerun.orientation == Orientation(rotate_deg=90)
    assert all(not path.exists() for path in stale_paths)
    assert not any((session.paths.session_dir / "validation").iterdir())
    assert (session.paths.reports_dir / "orientation_report.json").is_file()
    assert not (session.paths.session_dir / wf.ORIENTATION_NAME).exists()


def test_start_session_creates_a_new_session_after_kernel_restart(monkeypatch, sessions_root):
    from datetime import datetime, timezone

    from navigator_expert.config.machine import MachineProfile

    _patch(monkeypatch)
    machine = MachineProfile(programdata_root=sessions_root)
    first = wf.start_session(
        job_name="Overview",
        settle_s=0.0,
        machine=machine,
        moment=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
    )
    restarted = wf.start_session(
        job_name="Overview",
        settle_s=0.0,
        machine=machine,
        moment=datetime(2026, 7, 1, 12, 1, tzinfo=timezone.utc),
    )

    assert restarted.paths.session_dir != first.paths.session_dir
    assert not restarted.paths.session_dir.name.startswith(".")
    assert sorted(path.name for path in restarted.paths.session_dir.parent.iterdir()) == [
        "2026-07-01T12-00-00-000000Z",
        "2026-07-01T12-01-00-000000Z",
    ]


def test_successful_run_becomes_active_only_after_validation_and_adoption(
    monkeypatch, sessions_root, tmp_path
):
    _patch(monkeypatch)
    _install_votes(monkeypatch, [_trusted(0.0, 30.0), _trusted(-30.0, 0.0)])
    session = wf.measure(_start(sessions_root))
    assert session.session_id == "2026-07-01T12-00-00-000000Z"
    assert session.machine.latest_snapshot("orientation") is None
    written = session.paths.session_dir / wf.ORIENTATION_NAME
    assert not written.exists()
    assert {path.name for path in session.paths.session_dir.iterdir()} == {
        "data",
        "reports",
        "validation",
    }
    assert not any(path.name.startswith(".") for path in session.paths.session_dir.iterdir())
    assert not (session.paths.session_dir / "configs").exists()

    validation = session.paths.session_dir / "validation" / "check.ome.tiff"
    tifffile.imwrite(validation, np.zeros((4, 4), dtype=np.uint16))
    notebook = tmp_path / "set_orientation.ipynb"
    notebook.write_text('{"cells": []}', encoding="utf-8")
    adopted = wf.adopt_orientation(session, notebook)

    assert Path(adopted["snapshot"]) == session.paths.session_dir
    assert written.is_file()
    assert json.loads(written.read_text(encoding="utf-8")) == wf.orientation_config(
        session.orientation
    )
    assert session.config_written is True
    assert session.machine.latest_snapshot("orientation") == session.paths.session_dir
    assert Path(adopted["notebook_path"]) == (
        session.paths.session_dir / "data" / "notebook" / "set_orientation.ipynb"
    )

    notebook.write_text('{"cells": [{"rerun": true}]}', encoding="utf-8")
    adopted_again = wf.adopt_orientation(session, notebook)
    assert adopted_again == adopted
    assert Path(adopted_again["notebook_path"]).read_text(encoding="utf-8") == (
        '{"cells": [{"rerun": true}]}'
    )


def test_archive_notebook_places_one_canonical_copy_in_run(tmp_path):
    source = tmp_path / "working-copy.ipynb"
    source.write_text('{"cells": []}', encoding="utf-8")
    run_dir = tmp_path / "orientation" / "2026-07-01T12-00-00-000000Z"
    run_dir.mkdir(parents=True)
    session = SimpleNamespace(paths=SimpleNamespace(session_dir=run_dir))

    archived = wf.archive_notebook(session, source)

    assert archived == run_dir / "data" / "notebook" / "working-copy.ipynb"
    assert archived.read_text(encoding="utf-8") == '{"cells": []}'
    assert not any(path.name.startswith(".") for path in archived.parent.iterdir())
    assert not (archived.parent / "working-copy.ipynb.saving").exists()


def test_failed_run_keeps_evidence_but_is_not_active(monkeypatch, sessions_root):
    _patch(monkeypatch)
    _install_votes(monkeypatch, [_untrusted(), _trusted(-30.0, 0.0)])
    session = wf.measure(_start(sessions_root))
    assert not (session.paths.session_dir / wf.ORIENTATION_NAME).exists()
    assert (session.paths.reports_dir / "orientation_report.json").is_file()

    from navigator_expert.config.machine import MachineProfile

    machine = MachineProfile(programdata_root=sessions_root)
    assert machine.latest_snapshot("orientation") is None


def test_notebook_archive_waits_for_a_new_saved_file_version(tmp_path, monkeypatch):
    bootstrap_path = Path(wf.__file__).parent / "notebooks" / "_bootstrap.py"
    spec = importlib.util.spec_from_file_location("orientation_notebook_bootstrap", bootstrap_path)
    bootstrap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bootstrap)
    notebook = tmp_path / "set_orientation.ipynb"
    notebook.write_text(
        json.dumps(
            {
                "cells": [
                    {
                        "cell_type": "code",
                        "source": ["session = wf.run_notebook_measurement()"],
                        "execution_count": 1,
                        "outputs": [{"output_type": "display_data"}],
                    },
                    {
                        "cell_type": "code",
                        "source": ["validation_path = wf.validate(session)"],
                        "execution_count": 2,
                        "outputs": [{"output_type": "display_data"}],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    previous_mtime_ns = notebook.stat().st_mtime_ns
    monkeypatch.setattr(
        bootstrap,
        "NOTEBOOK",
        NotebookCheckpoint(
            notebook,
            required_code=(
                "session = wf.run_notebook_measurement()",
                "validation_path = wf.validate(session)",
            ),
        ),
    )

    os.utime(notebook, ns=(previous_mtime_ns + 1_000_000, previous_mtime_ns + 1_000_000))

    assert bootstrap.NOTEBOOK.wait_for_save(previous_mtime_ns, timeout_s=0.1) == notebook


def test_orientation_notebook_uses_one_automatic_run_directory():
    notebook_path = Path(wf.__file__).parent / "notebooks" / "set_orientation.ipynb"
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    code = "\n".join(
        "".join(cell.get("source", [])) for cell in notebook["cells"] if cell["cell_type"] == "code"
    )

    assert "session_id=" not in code
    assert "machine=MACHINE" not in code
    assert "reference_objective=" not in code
    assert "job_name=" not in code
    assert "session = wf.run_notebook_measurement()" in code
    assert "wf.start_session(" not in code
    assert "session = wf.measure(" not in code
    assert "wf.show_measurement_result(session)" in code
    assert code.index("wf.validate(session)") < code.index("save_and_adopt")
    assert code.index("save_and_adopt") < code.index("adopt_orientation")
    assert "output_root=" not in code
    assert "plt." not in code
    assert "# Save and Adopt" in code


def test_validation_stays_in_run_and_reloads_saved_image(tmp_path, monkeypatch):
    expected_orientation = Orientation(rotate_deg=90, mirrored=True)
    (tmp_path / "validation").mkdir()
    stale = tmp_path / "validation" / "stale.txt"
    stale.write_text("old validation", encoding="utf-8")
    session = SimpleNamespace(
        orientation=expected_orientation,
        d4_accepted=True,
        client=object(),
        job_name="Overview",
        paths=SimpleNamespace(session_dir=tmp_path),
    )
    acquired = object()
    expected_image = np.arange(12, dtype=np.uint16).reshape(3, 4)

    monkeypatch.setattr(wf.drv, "acquire", lambda client, job: acquired)

    def _save(client, acquisition, output_root, naming, *, orientation):
        assert client is session.client
        assert acquisition is acquired
        assert orientation == expected_orientation
        image_path = Path(output_root) / build_image_name(naming)
        image_path.parent.mkdir(parents=True, exist_ok=True)
        tifffile.imwrite(image_path, expected_image)
        return SimpleNamespace(image_paths={object(): image_path})

    monkeypatch.setattr(wf.drv, "save", _save)

    image, image_path = wf.acquire_validation_image(session)

    assert np.array_equal(image, expected_image)
    assert image_path.is_file()
    assert tmp_path / "validation" in image_path.parents
    assert not stale.exists()
    assert not (tmp_path / wf.ORIENTATION_NAME).exists()

"""Tests for calibration/core/ (PR 1).

Covers:

- SessionPaths creation and folder layout
- geometry validation
- non-square pixel rejection
- adoption behavior (publishes a copy-forward snapshot, snapshot history,
  missing staging source, wrong kind, bundled-default fallback)
- objective-pair workflow (parfocality / parcentricity, rerun invalidation)
- overlay smoke test
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import tifffile

pytest.importorskip("cv2")  # calibration core imports cv2

from navigator_expert.acquisition.naming import build_image_name, parse_image_name
from navigator_expert.calibration.core import (
    adopt as wf_adopt,
)
from navigator_expert.calibration.core import common as cm
from navigator_expert.calibration.core import (
    objective_pair as wf_obj,
)
from navigator_expert.config.machine import MachineProfile
from navigator_expert.orientation import Orientation

# ---------------------------------------------------------------------
# Explicit runtime roots
# ---------------------------------------------------------------------


@pytest.fixture
def sessions_root(tmp_path):
    return tmp_path / "sessions"


@pytest.fixture
def machine(tmp_path):
    return MachineProfile(programdata_root=tmp_path / "programdata")


# Fixed, well-separated UTC moments for snapshot publishing. Seeds stamp
# early so every later adopt sorts strictly after them (monotonic guard).
_SEED_MOMENT = datetime(2026, 1, 1, 0, 0, 0, 0, tzinfo=timezone.utc)
_ADOPT_MOMENT = datetime(2026, 6, 1, 0, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------


def test_calibration_capture_explicitly_passes_active_orientation(monkeypatch, tmp_path):
    expected = Orientation(rotate_deg=90, mirrored=True)
    session = SimpleNamespace(
        client=object(),
        job_name="Overview",
        exported_files={},
        paths=SimpleNamespace(session_dir=tmp_path, data_dir=tmp_path / "data"),
    )
    acquisition = object()
    saved = object()
    received = {}

    monkeypatch.setattr(cm._orientation, "rig_orientation", lambda: expected)
    monkeypatch.setattr(cm.drv, "acquire", lambda client, job: acquisition)

    def _save(client, result, output_root, naming, *, orientation):
        received["orientation"] = orientation
        return saved

    monkeypatch.setattr(cm.drv, "save", _save)

    result = cm._capture_for_calibration(
        session,
        name="reference",
        acquisition_type="calibration-frame",
    )

    assert result is saved
    assert received["orientation"] == expected


def test_make_session_paths_creates_layout(sessions_root):
    paths = cm.make_session_paths(
        "sess1",
        sessions_root=sessions_root,
        acquisition_name="10x-20x",
    )
    for sub in (paths.reports_dir, paths.data_dir):
        assert sub.is_dir()
    assert not paths.configs_dir.exists()
    assert paths.data_dir.name == "data"
    assert paths.session_dir.name == "10x-20x"
    assert paths.session_root.name == "sess1"


def test_make_session_paths_uses_explicit_root(sessions_root):
    paths = cm.make_session_paths(
        "sess_explicit",
        sessions_root=sessions_root,
    )
    assert paths.session_dir.parent == sessions_root.absolute()


def test_make_session_paths_does_not_use_package_sessions_root(sessions_root):
    paths = cm.make_session_paths(
        "sess_pkg",
        sessions_root=sessions_root,
    )
    package_sessions = Path(cm.__file__).resolve().parents[1] / "sessions"
    # session_dir lives under the explicit root, NOT the package tree.
    assert package_sessions not in paths.session_dir.parents


def test_runtime_paths_preserve_drive_letter(sessions_root):
    paths = cm.make_session_paths(
        "probe",
        sessions_root=sessions_root,
    )
    # The constructed session_dir keeps the same drive letter / prefix
    # as the input root -- no UNC conversion, no symlink dereferencing.
    expected_drive = sessions_root.absolute().drive
    assert (
        str(paths.session_dir).startswith(str(sessions_root.absolute().drive))
        or paths.session_dir.drive == expected_drive
    )


def test_assert_geometry_matches_accepts_exact_match():
    g = cm.ImageGeometry(
        image_size_px=(1024, 1024),
        format_px=(1024, 1024),
        pixel_size_um=0.5,
        pixel_w_um=0.5,
        pixel_h_um=0.5,
    )
    cm.assert_geometry_matches(g, (1024, 1024), 0.5, context="x")


def test_assert_geometry_matches_rejects_image_size():
    g = cm.ImageGeometry(
        image_size_px=(1024, 512),
        format_px=(1024, 512),
        pixel_size_um=0.5,
        pixel_w_um=0.5,
        pixel_h_um=0.5,
    )
    with pytest.raises(ValueError, match="image size mismatch"):
        cm.assert_geometry_matches(g, (1024, 1024), 0.5, context="x")


def test_assert_geometry_matches_rejects_pixel_size():
    g = cm.ImageGeometry(
        image_size_px=(1024, 1024),
        format_px=(1024, 1024),
        pixel_size_um=0.6,
        pixel_w_um=0.6,
        pixel_h_um=0.6,
    )
    with pytest.raises(ValueError, match="pixel size mismatch"):
        cm.assert_geometry_matches(g, (1024, 1024), 0.5, context="x")


def test_read_job_geometry_rejects_non_square_pixels(monkeypatch):
    monkeypatch.setattr(
        cm.drv,
        "get_job_settings",
        lambda *a, **k: {"some": "settings"},
    )
    monkeypatch.setattr(
        cm.drv,
        "parse_tile_geometry",
        lambda settings: {
            "pixel_w_um": 0.5,
            "pixel_h_um": 0.6,
            "pixels_x": 512,
            "pixels_y": 512,
        },
    )
    with pytest.raises(ValueError, match="non-square pixels"):
        cm.read_job_geometry(client=object(), job_name="Overview")


def test_read_job_geometry_pins_api_mode(monkeypatch):
    calls = []

    def _get_job_settings(client, job_name, **kwargs):
        calls.append((job_name, kwargs))
        return {"some": "settings"}

    monkeypatch.setattr(cm.drv, "get_job_settings", _get_job_settings)
    monkeypatch.setattr(
        cm.drv,
        "parse_tile_geometry",
        lambda settings: {
            "pixel_w_um": 0.5,
            "pixel_h_um": 0.5,
            "pixels_x": 512,
            "pixels_y": 512,
        },
    )

    cm.read_job_geometry(client=object(), job_name="Overview")

    assert calls[0][1]["mode"] == "api"


def test_read_job_geometry_uses_image_shape_when_provided(monkeypatch):
    monkeypatch.setattr(
        cm.drv,
        "get_job_settings",
        lambda *a, **k: {"some": "settings"},
    )
    monkeypatch.setattr(
        cm.drv,
        "parse_tile_geometry",
        lambda settings: {
            "pixel_w_um": 0.5,
            "pixel_h_um": 0.5,
            "pixels_x": 512,
            "pixels_y": 512,
        },
    )
    img = np.zeros((256, 384), dtype=np.uint16)
    g = cm.read_job_geometry(client=object(), job_name="Overview", image=img)
    assert g.image_size_px == (256, 384)
    assert g.format_px == (512, 512)
    assert g.pixel_size_um == 0.5


def test_plot_overlay_smoke():
    ref = (np.random.RandomState(0).rand(32, 32) * 255).astype(np.uint8)
    tgt = (np.random.RandomState(1).rand(32, 32) * 255).astype(np.uint8)
    fig = cm.plot_overlay(
        ref,
        tgt,
        "smoke",
        subtitle="Measured XY shift: (+0.50, -0.30) µm",
    )
    assert fig is not None
    # Without an alignment shift the figure stays a single panel.
    assert len(fig.axes) == 1
    plt = pytest.importorskip("matplotlib.pyplot")

    plt.close(fig)


def test_plot_overlay_uses_the_separately_acquired_corrected_target():
    # The first target is shifted. The second target is a separate image that
    # already matches the reference, as a successful physical stage correction
    # should. The plotting helper must show it directly, not shift pixels.
    plt = pytest.importorskip("matplotlib.pyplot")
    ref = (np.random.RandomState(0).rand(64, 64) * 255).astype(np.uint8)
    tgt = np.roll(ref, shift=(5, 3), axis=(0, 1))
    fig = cm.plot_overlay(
        ref,
        tgt,
        "Acquisition without correction",
        corrected_target=ref.copy(),
    )
    assert len(fig.axes) == 2
    rgb = fig.axes[1].images[0].get_array()
    red = np.asarray(rgb)[..., 0]
    green = np.asarray(rgb)[..., 1]
    assert np.array_equal(red, green)
    plt.close(fig)


def test_plot_brenner_curve_shows_focus_image_when_given():
    plt = pytest.importorskip("matplotlib.pyplot")
    z = [0.0, 1.0, 2.0, 3.0, 4.0]
    scores = [1.0, 2.0, 5.0, 2.0, 1.0]
    fig = cm.plot_brenner_curve(z, scores, 2.0)
    assert len(fig.axes) == 1
    plt.close(fig)
    focus_img = (np.random.RandomState(2).rand(16, 16) * 255).astype(np.uint8)
    fig = cm.plot_brenner_curve(z, scores, 2.0, focus_image=focus_img)
    assert len(fig.axes) == 2
    assert fig.get_size_inches().tolist() == [16.0, 7.0]
    assert fig.axes[0].get_title() == "Software Autofocus"
    assert fig.axes[0].get_ylabel() == "Brenner Gradient Score"
    assert fig.axes[1].get_title() == "Focus positions (Z = 2.00 µm)"
    plt.close(fig)


# ---------------------------------------------------------------------
# image_to_stage workflow
# ---------------------------------------------------------------------


def _write_saved_image(output_root, naming, image):
    image_path = Path(output_root) / build_image_name(naming)
    image_path.parent.mkdir(parents=True, exist_ok=True)
    tifffile.imwrite(image_path, np.asarray(image))
    return image_path


def _saved_manifest(output_root, naming, image):
    arr = np.asarray(image)
    if arr.ndim == 3:
        image_paths = {}
        for z, plane in enumerate(arr):
            plane_naming = replace(naming, z=z)
            image_paths[cm.drv.PlaneIndex(t=0, z=z, c=0)] = _write_saved_image(
                output_root, plane_naming, plane
            )
    else:
        image_paths = {
            cm.drv.PlaneIndex(t=0, z=0, c=0): _write_saved_image(output_root, naming, arr)
        }
    return SimpleNamespace(
        image_paths=image_paths,
        xml_paths={cm.drv.PositionIndex(t=0, v=0): Path(output_root) / "mock.ome.xml"},
        naming=naming,
    )


# ---------------------------------------------------------------------
# Adoption
# ---------------------------------------------------------------------


def _make_report_session(
    sessions_root,
    kind_payload,
    _old_name=None,
    *,
    sess_id="adopt_sess",
):
    paths = cm.make_session_paths(
        sess_id,
        sessions_root=sessions_root,
        acquisition_name="test-pair",
    )
    report = dict(kind_payload)
    if report.get("kind") == "objective_translation":
        report["kind"] = "objective_translation_report"
    report.setdefault("from_slot", 1 if report.get("from_objective") == "10x" else 2)
    report.setdefault("to_slot", 1 if report.get("to_objective") == "10x" else 2)
    report["session_id"] = sess_id
    report["acquisition_name"] = "test-pair"
    report["config_written"] = True
    report_path = paths.reports_dir / "objective_pair_report.json"
    cm.write_json_atomic(report_path, report)

    class _Stub:
        pass

    s = _Stub()
    s.session_id = sess_id
    s.paths = paths
    s.calibration_name = None
    return s, report_path


def _current_calibration_payload():
    return {
        "schema_version": 12,
        "last_updated": "20260527_120000",
        "objectives": {
            "1": {
                "name": "10x",
                "translation_um": [0.0, 0.0, 0.0],
                "session_id": "ref",
            },
            "2": {
                "name": "20x",
                "translation_um": [100.0, 100.0, 10.0],
                "session_id": "target",
            },
        },
    }


def _valid_obj_payload():
    return {
        "schema_version": cm.STAGING_SCHEMA_VERSION,
        "kind": "objective_translation",
        "created_at": "2026-05-22T15:10:00+02:00",
        "from_objective": "10x",
        "to_objective": "20x",
        "from_slot": 1,
        "to_slot": 2,
        "translation_xy_um": [12.0, 17.0],
        "translation_z_um": 3.0,
    }


def _seed_snapshot(machine, *, moment=_SEED_MOMENT):
    """Publish an initial snapshot holding a full valid calibration.

    Later adopts stamp with a strictly later moment (see ``_ADOPT_MOMENT``)
    so the monotonic snapshot guard is satisfied.
    """
    return machine.publish_snapshot(
        moment,
        calibration=_current_calibration_payload(),
    )


def test_adoption_objective_translation_updates_canonical_calibration(
    sessions_root,
    machine,
):
    _seed_snapshot(machine)
    payload = {
        "schema_version": cm.STAGING_SCHEMA_VERSION,
        "kind": "objective_translation",
        "created_at": "2026-05-22T15:10:00+02:00",
        "from_objective": "10x",
        "to_objective": "20x",
        "translation_xy_um": [12.0, 17.0],
        "translation_z_um": 3.0,
    }
    session, _ = _make_report_session(
        sessions_root,
        payload,
    )

    wf_adopt.adopt_calibration(
        session,
        calibration_name="water_lens_set",
        machine=machine,
        moment=_ADOPT_MOMENT,
    )

    current = json.loads(machine.calibration_path("water_lens_set").read_text(encoding="utf-8"))
    assert current["objectives"]["2"]["translation_um"] == [12.0, 17.0, 3.0]
    assert set(current["objectives"]["2"]) == {"name", "translation_um"}
    assert (
        machine.latest_snapshot("calibration")
        / "calibrations"
        / "water_lens_set"
        / "calibration.json"
    ).exists()


def test_adoption_archives_notebook_beside_objective_pair(sessions_root, machine, tmp_path):
    _seed_snapshot(machine)
    session, _ = _make_report_session(sessions_root, _valid_obj_payload())
    notebook = tmp_path / "working.ipynb"
    notebook.write_text('{"cells": []}', encoding="utf-8")

    result = wf_adopt.adopt_calibration(
        session,
        machine=machine,
        moment=_ADOPT_MOMENT,
        notebook_paths=[notebook],
    )

    archived = session.paths.session_dir / "data" / "notebook" / notebook.name
    assert archived.is_file()
    assert archived.read_text(encoding="utf-8") == '{"cells": []}'
    snapshot_archived = Path(result["snapshot"]) / "data" / "notebook" / notebook.name
    assert snapshot_archived.read_text(encoding="utf-8") == '{"cells": []}'
    assert result["notebook_paths"] == [str(archived), str(snapshot_archived)]
    assert (session.paths.session_dir / "calibration.json").is_file()


def test_adoption_keeps_canonical_objectives_minimal(
    sessions_root,
    machine,
):
    """Measurement provenance stays in the report, not calibration.json."""
    _seed_snapshot(machine)
    session, _ = _make_report_session(
        sessions_root,
        _valid_obj_payload(),
    )

    wf_adopt.adopt_calibration(
        session,
        machine=machine,
        moment=_ADOPT_MOMENT,
    )

    current = json.loads(machine.calibration_path().read_text(encoding="utf-8"))
    assert set(current) == {"schema_version", "objectives"}
    assert all(set(entry) == {"name", "translation_um"} for entry in current["objectives"].values())


def test_session_calibration_compiles_all_acquisition_folders(sessions_root, machine):
    session_id = "multi-pair"
    reports = (
        ("10x-20x", 2, "20x", [12.0, 17.0], 3.0),
        ("10x-40x", 3, "40x", [-4.0, 8.0], -2.0),
    )
    paths = None
    for acquisition_name, to_slot, to_name, xy, z in reports:
        paths = cm.make_session_paths(
            session_id,
            sessions_root,
            acquisition_name=acquisition_name,
        )
        cm.write_json_atomic(
            paths.reports_dir / "objective_pair_report.json",
            {
                "schema_version": cm.STAGING_SCHEMA_VERSION,
                "kind": "objective_translation_report",
                "session_id": session_id,
                "acquisition_name": acquisition_name,
                "config_written": True,
                "from_slot": 1,
                "to_slot": to_slot,
                "from_objective": "10x",
                "to_objective": to_name,
                "translation_xy_um": xy,
                "translation_z_um": z,
            },
        )

    session = SimpleNamespace(
        session_id=session_id,
        paths=paths,
        calibration_path=machine.bundled_default_path("calibration.json"),
        hardware_objectives={1: "10x", 2: "20x", 3: "40x"},
    )
    compiled = wf_adopt.compile_session_calibration(session)
    assert json.loads(compiled.read_text(encoding="utf-8")) == {
        "schema_version": 13,
        "objectives": {
            "1": {"name": "10x", "translation_um": [0.0, 0.0, 0.0]},
            "2": {"name": "20x", "translation_um": [12.0, 17.0, 3.0]},
            "3": {"name": "40x", "translation_um": [-4.0, 8.0, -2.0]},
        },
    }


def test_adoption_refuses_to_overwrite_the_established_reference(sessions_root, machine):
    """Adopting a pair whose target is the zero-reference must fail with advice.

    Overwriting the reference would shift the origin every other objective is
    measured against; before this guard the merge only failed later, at
    publish, with a schema message the operator could not act on.
    """
    _seed_snapshot(machine)
    payload = _valid_obj_payload()
    payload["from_objective"] = "20x"
    payload["to_objective"] = "10x"  # slot 1 — the calibration's zero reference
    payload["from_slot"] = 2
    payload["to_slot"] = 1
    session, _ = _make_report_session(
        sessions_root,
        payload,
    )

    with pytest.raises(ValueError, match="established reference"):
        wf_adopt.adopt_calibration(
            session,
            machine=machine,
            moment=_ADOPT_MOMENT,
        )


def test_adoption_refuses_a_same_slot_pair_from_labels(sessions_root, machine):
    _seed_snapshot(machine)
    payload = _valid_obj_payload()
    payload["to_objective"] = "10x"  # same slot as from_objective
    payload["from_objective"] = "10x"
    payload["from_slot"] = 1
    payload["to_slot"] = 1
    session, _ = _make_report_session(
        sessions_root,
        payload,
    )

    with pytest.raises(ValueError, match="must differ"):
        wf_adopt.adopt_calibration(
            session,
            machine=machine,
            moment=_ADOPT_MOMENT,
        )


def test_adoption_refuses_a_reference_missing_from_the_calibration(sessions_root, machine):
    """A measurement from an objective the calibration does not cover cannot chain.

    Its target has no path back to the existing origin; silently starting a
    second [0, 0, 0] origin would corrupt the file (and used to surface only
    as a publish-time schema error).
    """
    _seed_snapshot(machine)
    payload = _valid_obj_payload()
    payload["from_slot"] = 5
    payload["to_slot"] = 6
    payload["from_objective"] = "63x glycerol"
    payload["to_objective"] = "93x oil"
    session, _ = _make_report_session(
        sessions_root,
        payload,
    )

    with pytest.raises(ValueError, match="not calibrated relative"):
        wf_adopt.adopt_calibration(
            session,
            machine=machine,
            moment=_ADOPT_MOMENT,
        )


def test_common_reference_adoptions_infer_every_objective_pair(sessions_root, machine):
    """10→20/40/60 measurements must imply every pair and reverse."""
    from navigator_expert.calibration.core import model as calibration_model

    calibration_name = "shared_lens_setup"
    reference = {
        "schema_version": 12,
        "last_updated": "20260101_000000",
        "objectives": {
            "1": {
                "name": "10x reference",
                "translation_um": [0.0, 0.0, 0.0],
                "session_id": "reference_setup",
            }
        },
    }
    machine.publish_snapshot(
        _SEED_MOMENT,
        calibration=reference,
        calibration_name=calibration_name,
    )
    translations = {
        1: (0.0, 0.0, 0.0),
        2: (10.0, 20.0, 1.0),
        3: (-4.0, 7.0, 3.0),
        4: (25.0, -8.0, -2.0),
    }
    names = {1: "10x reference", 2: "20x", 3: "40x", 4: "60x"}

    for ordinal, target_slot in enumerate((2, 3, 4), start=1):
        tx, ty, tz = translations[target_slot]
        session_id = f"measure_10x_to_{names[target_slot]}"
        payload = {
            "schema_version": cm.STAGING_SCHEMA_VERSION,
            "kind": "objective_translation",
            "created_at": f"2026-06-01T00:00:0{ordinal}+00:00",
            "session_id": session_id,
            "from_slot": 1,
            "to_slot": target_slot,
            "from_objective": names[1],
            "to_objective": names[target_slot],
            "translation_xy_um": [tx, ty],
            "translation_z_um": tz,
        }
        session, _ = _make_report_session(
            sessions_root,
            payload,
            sess_id=session_id,
        )
        session.hardware_objectives = dict(names)
        wf_adopt.adopt_calibration(
            session,
            calibration_name=calibration_name,
            machine=machine,
            moment=datetime(2026, 6, 1, 0, 0, ordinal, tzinfo=timezone.utc),
        )

    config = calibration_model.load_calibration(machine.calibration_path(calibration_name))
    assert calibration_model.get_reference_slot(config) == 1
    assert set(map(int, config["objectives"])) == {1, 2, 3, 4}
    for slot in (2, 3, 4):
        assert calibration_model.get_translation_um(config, slot) == translations[slot]

    base = (100.0, 200.0, 500.0)
    for from_slot in translations:
        for to_slot in translations:
            actual = calibration_model.translate_xyz_between_objectives(
                *base,
                config,
                from_slot=from_slot,
                to_slot=to_slot,
            )
            t_from = translations[from_slot]
            t_to = translations[to_slot]
            expected = tuple(base[axis] + t_to[axis] - t_from[axis] for axis in range(3))
            assert actual == expected


def test_adoption_refreshes_objective_names_from_the_live_system(
    sessions_root,
    machine,
):
    # The base config carries stale (DRY) names; the live microscope reports the
    # WATER objectives actually in the turret. Adoption annotates the touched
    # slots with the live names.
    _seed_snapshot(machine)
    payload = {
        "schema_version": cm.STAGING_SCHEMA_VERSION,
        "kind": "objective_translation",
        "created_at": "2026-05-22T15:10:00+02:00",
        "from_objective": "10x",
        "to_objective": "20x",
        "translation_xy_um": [12.0, 17.0],
        "translation_z_um": 3.0,
    }
    session, _ = _make_report_session(
        sessions_root,
        payload,
    )
    session.hardware_objectives = {
        1: "HC PL APO CS2 10x/0.40 WATER",
        2: "HC PL APO CS2 20x/0.75 WATER",
    }

    wf_adopt.adopt_calibration(
        session,
        calibration_name="water_lens_set",
        machine=machine,
        moment=_ADOPT_MOMENT,
    )

    current = json.loads(machine.calibration_path("water_lens_set").read_text(encoding="utf-8"))
    assert current["objectives"]["1"]["name"] == "HC PL APO CS2 10x/0.40 WATER"
    assert current["objectives"]["2"]["name"] == "HC PL APO CS2 20x/0.75 WATER"
    # the translation is still applied alongside the refreshed name
    assert current["objectives"]["2"]["translation_um"] == [12.0, 17.0, 3.0]


def test_orientation_unmeasured_warning_signals(tmp_path, caplog, monkeypatch):
    """The 'orientation not measured yet' warning keys on two markers.

    The shipped placeholder carries ``"measured": false`` (warned); a measured/adopted
    file carries ``"measured": true`` (never warned); and a file with neither
    — adopted before the marker existed — is trusted as measured, so a driver
    upgrade never starts warning on a rig that was already set up.
    """
    import logging

    from navigator_expert.calibration.core import objective_pair as op
    from navigator_expert.config import machine as machine_mod

    profile = MachineProfile(programdata_root=tmp_path / "programdata")
    snap = profile.ensure_snapshot("orientation")  # seeds the shipped placeholder
    monkeypatch.setattr(machine_mod, "MACHINE", profile)

    def warns() -> bool:
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            op._warn_if_orientation_unmeasured()
        return any("has not been measured" in r.message for r in caplog.records)

    # Freshly seeded ProgramData carries measured=false -> warn.
    assert warns() is True
    # A measured/adopted file (positive marker) -> quiet.
    (snap / "orientation.json").write_text(
        json.dumps({"schema_version": 1, "rotate_deg": 90, "measured": True}),
        encoding="utf-8",
    )
    assert warns() is False
    # A pre-marker measured file (no measured field) -> quiet.
    (snap / "orientation.json").write_text(
        json.dumps({"schema_version": 1, "rotate_deg": 90}), encoding="utf-8"
    )
    assert warns() is False


def test_adoption_ignores_empty_live_names(sessions_root, machine):
    # A hardware record whose name is empty (firmware quirk, simulator) must
    # never erase the config's human-set name — only a real live name refreshes.
    _seed_snapshot(machine)
    session, _ = _make_report_session(
        sessions_root,
        _valid_obj_payload(),
    )
    session.hardware_objectives = {1: "", 2: "HC PL APO CS2 20x/0.75 WATER"}

    wf_adopt.adopt_calibration(
        session,
        machine=machine,
        moment=_ADOPT_MOMENT,
    )

    current = json.loads(machine.calibration_path().read_text(encoding="utf-8"))
    assert current["objectives"]["1"]["name"] == "10x"  # kept, not erased
    assert current["objectives"]["2"]["name"] == "HC PL APO CS2 20x/0.75 WATER"
    assert current["objectives"]["2"]["translation_um"] == [12.0, 17.0, 3.0]


def test_adoption_missing_staging_raises(sessions_root, machine):
    sess_id = "missing_sess"
    paths = cm.make_session_paths(
        sess_id,
        sessions_root=sessions_root,
    )

    class _Stub:
        pass

    s = _Stub()
    s.session_id = sess_id
    s.paths = paths

    with pytest.raises(FileNotFoundError):
        wf_adopt.adopt_calibration(
            s,
            machine=machine,
        )


def test_adoption_wrong_kind_rejected(sessions_root, machine):
    bad = dict(_valid_obj_payload())
    bad["kind"] = "garbage"
    session, _ = _make_report_session(sessions_root, bad)
    with pytest.raises(ValueError, match="unexpected acquisition report kind"):
        wf_adopt.adopt_calibration(
            session,
            machine=machine,
        )


def test_adoption_seeds_from_bundled_default_when_no_snapshot(sessions_root, machine):
    # With a fresh machine (no snapshot) an objective-pair adopt reads the
    # bundled default, merges the delta, and publishes the first snapshot.
    assert machine.latest_snapshot("calibration") is None
    payload = _valid_obj_payload()
    session, _ = _make_report_session(
        sessions_root,
        payload,
    )
    out = wf_adopt.adopt_calibration(
        session,
        calibration_name="lens_config_A",
        machine=machine,
        moment=_ADOPT_MOMENT,
    )
    assert machine.latest_snapshot("calibration") is not None
    assert len(machine.snapshots("calibration")) == 1
    assert Path(out["snapshot"]) == machine.latest_snapshot("calibration")
    # The bundled default's slot 1 is the "10x" reference ([0,0,0]); the
    # merged snapshot records the "20x" (slot 2) translation delta.
    assert Path(out["calibration_path"]) == (
        machine.latest_snapshot("calibration")
        / "calibrations"
        / "lens_config_A"
        / "calibration.json"
    )
    merged = json.loads(machine.calibration_path("lens_config_A").read_text(encoding="utf-8"))
    assert merged["objectives"]["2"]["translation_um"] == [12.0, 17.0, 3.0]
    assert set(merged["objectives"]["2"]) == {"name", "translation_um"}


# ---------------------------------------------------------------------
# Post-review fixes (PR 1 polish)
# ---------------------------------------------------------------------


def _strict_json_parse(text: str):
    """Strict JSON parse that rejects NaN / Infinity tokens."""

    def _no_constants(c):
        raise ValueError(f"non-finite JSON constant: {c!r}")

    return json.loads(text, parse_constant=_no_constants)


# =====================================================================
# objective_pair workflow
# =====================================================================


def _patch_objective_driver(
    monkeypatch,
    *,
    pixel_size_um=0.5,
    image_shape=(64, 64),
    home_xy=(1000.0, 2000.0),
    home_z=100.0,
    z_post=94.0,
    xy_post=(1010.0, 2020.0),
    ref_focus_z=100.0,
    target_focus_z=103.0,
    brenner_sigma=5.0,
    ref_stack=None,
    target_stack=None,
    acquire_side_effects=None,
    stack_side_effects=None,
):
    """Patch driver + algorithm hooks used by objective_pair.

    Each test phase ("ref" then "target") drives a separate stack
    acquisition. The fixture exposes ``state["stack_phase"]`` so tests
    can flip from "ref" to "target" between Steps 2 and 3 to simulate
    the operator switching objective and reconfiguring the LAS X stack.

    ``ref_stack`` / ``target_stack`` are dicts with begin/end/sections
    (and optional stepSize/zDrive); the mocked LAS X reports them via
    ``get_job_settings`` + ``make_changeable_copy``.

    Brenner score is a Gaussian centered at the phase-specific focus
    (``ref_focus_z`` / ``target_focus_z``). Each slice of the mocked
    stack is filled with its absolute z value, so the mocked
    ``brenner(slice)`` reads ``slice.flat[0]`` to know the slice's z.
    """
    monkeypatch.setattr(
        wf_obj.drv,
        "connect_python_client",
        lambda *a, **k: object(),
    )
    monkeypatch.setattr(
        wf_obj.drv,
        "connect_limits_handshake",
        lambda client, **k: SimpleNamespace(
            ok=True,
            error=None,
            stage_cfg={"stage_um": {"x": [1000.0, 130000.0], "y": [1000.0, 100000.0]}},
        ),
    )
    monkeypatch.setattr(
        wf_obj.drv,
        "get_hardware_info",
        # A realistic occupied turret: start_session resolves the configured
        # reference slot's name from this, exactly like the live driver.
        lambda client, **kw: {
            "Microscope": {
                "objectives": [
                    {"slotIndex": 1, "objectiveNumber": 1, "name": "10x"},
                    {"slotIndex": 2, "objectiveNumber": 2, "name": "20x"},
                ]
            }
        },
    )

    default_ref = {
        "begin": 95.0,
        "end": 105.0,
        "sections": 11,
        "stepSize": 1.0,
        "zDrive": "z-wide",
    }
    default_target = {
        "begin": 98.0,
        "end": 108.0,
        "sections": 11,
        "stepSize": 1.0,
        "zDrive": "z-wide",
    }
    state = {
        "x": home_xy[0],
        "y": home_xy[1],
        "zwide": home_z,
        "z_move_modes": [],
        "acquire_jobs": [],
        "backlash_passes": [],
        "acquisition_events": [],
        "stack_phase": "ref",
        "ref_stack": dict(default_ref if ref_stack is None else ref_stack),
        "target_stack": dict(default_target if target_stack is None else target_stack),
        "xy_post": xy_post,
    }

    def _get_xy(client, **kw):
        return {"x_um": state["x"], "y_um": state["y"]}

    def _move_xy(client, x, y, unit="um", **kw):
        state["x"] = x
        state["y"] = y
        return {"success": True}

    def _move_z(client, job_name, z, unit="um", z_mode="galvo", **kw):
        state["z_move_modes"].append(z_mode)
        if z_mode == "zwide":
            state["zwide"] = float(z)
        return {"success": True, "confirmed": True}

    def _read_zwide_um(client, job_name, **kw):
        # Returns the most recently commanded z-wide. Tests set
        # state["zwide"] = z_post before measure_parfocality_target to
        # simulate the firmware's post-switch z-wide reading.
        return float(state["zwide"])

    monkeypatch.setattr(wf_obj.drv, "get_xy", _get_xy)
    monkeypatch.setattr(cm.drv, "get_xy", _get_xy)
    monkeypatch.setattr(cm.drv, "move_xy", _move_xy)
    monkeypatch.setattr(cm.drv, "move_z", _move_z)
    monkeypatch.setattr(cm.drv, "read_zwide_um", _read_zwide_um)
    monkeypatch.setattr(wf_obj.drv, "read_zwide_um", _read_zwide_um)

    def _get_job_settings(client, job_name, **kw):
        return {
            "zoom": {"current": 1.0},
            "scanSpeed": {"value": 600.0, "isResonant": False},
            "activeSettings": [],
            "scanMode": "xyz",
            "stack": dict(state[f"{state['stack_phase']}_stack"]),
        }

    monkeypatch.setattr(cm.drv, "get_job_settings", _get_job_settings)

    def _make_changeable_copy(settings):
        if settings is None:
            return None
        stack = settings.get("stack")
        return {
            "stack": dict(stack) if isinstance(stack, dict) else None,
        }

    monkeypatch.setattr(cm.drv, "make_changeable_copy", _make_changeable_copy)

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

    rng = np.random.RandomState(7)
    img_template = (rng.rand(*image_shape) * 255).astype(np.uint16)

    frame_side_effects = list(acquire_side_effects or [])
    frame_count = {"n": 0}

    def _acquire(client, job, **kw):
        state["acquisition_events"].append("acquire")
        state["acquire_jobs"].append(job)
        return SimpleNamespace(job=job, command_result={"success": True})

    def _save(client, acq, output_root, naming, **kw):
        if naming.acquisition_type == "calibration-stack":
            idx = stack_count["n"]
            stack_count["n"] += 1
            if idx < len(stack_effects) and stack_effects[idx] is not None:
                effect = stack_effects[idx]
                if isinstance(effect, Exception):
                    raise effect
                image = np.asarray(effect)
            else:
                meta = state[f"{state['stack_phase']}_stack"]
                n = int(meta["sections"])
                begin = float(meta["begin"])
                end = float(meta["end"])
                positions = np.linspace(begin, end, n)
                h, w = image_shape
                image = np.zeros((n, h, w), dtype=np.float32)
                for i, z in enumerate(positions):
                    image[i] = float(z)
        else:
            idx = frame_count["n"]
            frame_count["n"] += 1
            if idx < len(frame_side_effects) and frame_side_effects[idx] is not None:
                effect = frame_side_effects[idx]
                if isinstance(effect, Exception):
                    raise effect
                image = effect
            else:
                image = img_template.copy()
        return _saved_manifest(output_root, naming, image)

    monkeypatch.setattr(cm.drv, "acquire", _acquire)
    monkeypatch.setattr(cm.drv, "save", _save)

    def _correct_backlash(_client, *, passes, **_kwargs):
        state["backlash_passes"].append(passes)
        state["acquisition_events"].append("backlash")

    monkeypatch.setattr(cm._movement, "correct_backlash", _correct_backlash)

    def _acquire_frame(client, job, **kw):
        idx = frame_count["n"]
        frame_count["n"] += 1
        if idx < len(frame_side_effects) and frame_side_effects[idx] is not None:
            effect = frame_side_effects[idx]
            if isinstance(effect, Exception):
                raise effect
            return effect, Path("C:/fake/export.tif")
        return img_template.copy(), Path("C:/fake/export.tif")

    stack_effects = list(stack_side_effects or [])
    stack_count = {"n": 0}

    def _acquire_stack(client, job, **kw):
        idx = stack_count["n"]
        stack_count["n"] += 1
        if idx < len(stack_effects) and stack_effects[idx] is not None:
            effect = stack_effects[idx]
            if isinstance(effect, Exception):
                raise effect
            return np.asarray(effect)
        meta = state[f"{state['stack_phase']}_stack"]
        n = int(meta["sections"])
        begin = float(meta["begin"])
        end = float(meta["end"])
        positions = np.linspace(begin, end, n)
        h, w = image_shape
        arr = np.zeros((n, h, w), dtype=np.float32)
        for i, z in enumerate(positions):
            arr[i] = float(z)
        return arr

    def _brenner(img):
        # Slices are filled with the absolute z position by the
        # acquire_stack mock; read flat[0] to recover it.
        z = float(np.asarray(img).flat[0])
        peak = target_focus_z if state["stack_phase"] == "target" else ref_focus_z
        return float(np.exp(-((z - peak) ** 2) / (2.0 * brenner_sigma**2)))

    monkeypatch.setattr(wf_obj, "brenner", _brenner)

    # Most integration tests exercise measurement arithmetic rather than the
    # live objective reader. Give them a stable operator-driven 10x/20x pair;
    # dedicated tests below exercise the real read/record/verify helper.
    def _observe_objective_for_step(session, role, **_kwargs):
        if role == "reference":
            session.from_slot = 1
            session.from_objective = session.from_objective or "10x"
            slot, name = session.from_slot, session.from_objective
        else:
            session.to_slot = 2
            session.to_objective = session.to_objective or "20x"
            slot, name = session.to_slot, session.to_objective
        session.hardware_objectives[slot] = name
        return slot, name

    monkeypatch.setattr(wf_obj, "_observe_objective_for_step", _observe_objective_for_step)

    return state


def _install_obj_vote(monkeypatch, vote):
    def _rv(ref, tgt, pixel_um, **kw):
        return vote

    monkeypatch.setattr(wf_obj, "register_voting", _rv)


def test_objective_pair_defaults_to_machine_workspace_calibration_and_active_job(
    monkeypatch,
    machine,
):
    _seed_snapshot(machine)
    monkeypatch.setattr("navigator_expert.config.machine.MACHINE", machine)
    _patch_objective_driver(monkeypatch)
    monkeypatch.setattr(
        wf_obj.drv, "get_selected_job", lambda client, **kwargs: {"Name": "Overview"}
    )

    session = wf_obj.start_session(
        session_id="obj_defaults",
        reference_slot=1,
    )

    assert session.paths.session_root == machine.subsystem_root("calibration") / "obj_defaults"
    assert session.paths.session_dir == session.paths.session_root / "objective-pair"
    assert session.calibration_path == machine.calibration_path().absolute()
    assert session.calibration_name is None
    assert session.job_name == "Overview"
    assert session.backlash_rounds == 5


def test_objective_pair_measure_runs_the_next_unfinished_step(monkeypatch):
    session = SimpleNamespace(
        focus_z_ref_um=None,
        focus_z_target_um=None,
        ref_image=None,
    )
    calls = []

    monkeypatch.setattr(
        wf_obj,
        "measure_parfocality_reference",
        lambda current: calls.append("reference_focus") or current,
    )
    monkeypatch.setattr(
        wf_obj,
        "measure_parfocality_target",
        lambda current: calls.append("target_focus") or current,
    )
    monkeypatch.setattr(
        wf_obj,
        "measure_parcentricity_reference",
        lambda current: calls.append("reference_xy") or current,
    )
    monkeypatch.setattr(
        wf_obj,
        "measure_parcentricity_target_and_save",
        lambda current: calls.append("target_xy") or {"status": "done"},
    )

    assert wf_obj.measure(session) is None
    session.focus_z_ref_um = 100.0
    assert wf_obj.measure(session) is None
    session.focus_z_target_um = 103.0
    assert wf_obj.measure(session) is None
    session.ref_image = np.zeros((4, 4))
    assert wf_obj.measure(session) == {"status": "done"}
    assert calls == ["reference_focus", "target_focus", "reference_xy", "target_xy"]


def test_objective_pair_notebook_only_configures_session_and_reference_slot():
    notebook_path = (
        Path(wf_obj.__file__).parents[1] / "notebooks" / "calibrate_objective_pair.ipynb"
    )
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    code = "\n".join(
        "".join(cell.get("source", [])) for cell in notebook["cells"] if cell["cell_type"] == "code"
    )

    assert 'session_id="' in code
    assert 'acquisition_name="' in code
    assert "reference_slot=1" in code
    assert "backlash_rounds=5" in code
    assert "job_name=" not in code
    assert "sessions_root=" not in code
    assert "parent_session=session" not in code
    assert "calibration_check" not in code
    assert "calibration_name=session.calibration_name" not in code
    assert "MACHINE" not in code
    assert "objective_pair.measure_parfocality_reference(session)" in code
    assert "objective_pair.measure_parfocality_target(session)" in code
    assert "objective_pair.measure_parcentricity_reference(session)" in code
    assert "summary = objective_pair.measure_parcentricity_target_and_save(session)" in code
    assert "objective_pair.measure(session)" not in code
    assert code.index("measure_parcentricity_target_and_save(session)") < code.index(
        "save_and_adopt"
    )
    assert code.index("save_and_adopt") < code.index("adopt_calibration")
    assert "# Save and Adopt" in code
    stored_notebook = json.dumps(notebook)
    assert "ObjectivePairSession(" not in stored_notebook
    assert "CalibrationCheckSession(" not in stored_notebook


def test_objective_pair_rejects_conflicting_calibration_selectors(monkeypatch):
    # The source file and adoption target must not be ambiguous.
    with pytest.raises(ValueError, match="either calibration_name or calibration_path"):
        wf_obj.start_session(
            session_id="obj_conflict",
            job_name="Overview",
            reference_slot=1,
            sessions_root="ignored",
            calibration_path="calibration.json",
            calibration_name="lens_A",
        )


@pytest.mark.parametrize("invalid_rounds", [-1, 1.5, True, "2"])
def test_objective_pair_rejects_invalid_backlash_rounds(invalid_rounds):
    with pytest.raises(ValueError, match="backlash_rounds must be a whole number"):
        wf_obj.start_session(
            session_id="invalid_backlash",
            reference_slot=1,
            backlash_rounds=invalid_rounds,
        )


def test_objective_pair_can_select_named_machine_calibration(
    monkeypatch,
    sessions_root,
    machine,
):
    cal = _current_calibration_payload()
    snap = machine.publish_snapshot(
        _SEED_MOMENT,
        calibration=cal,
        calibration_name="lens_A",
    )
    monkeypatch.setattr("navigator_expert.config.machine.MACHINE", machine)
    _patch_objective_driver(monkeypatch)

    session = wf_obj.start_session(
        session_id="obj_named",
        job_name="Overview",
        reference_slot=1,
        sessions_root=sessions_root,
        calibration_name="lens_A",
    )

    assert session.calibration_name == "lens_A"
    assert (
        session.calibration_path
        == (snap / "calibrations" / "lens_A" / "calibration.json").absolute()
    )


def test_configured_reference_must_match_existing_calibration_reference(tmp_path, sessions_root):
    calibration_path = tmp_path / "calibration.json"
    calibration_path.write_text(json.dumps(_current_calibration_payload()), encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        wf_obj.start_session(
            session_id="wrong_reference",
            job_name="Overview",
            reference_slot=2,
            sessions_root=sessions_root,
            calibration_path=calibration_path,
        )

    message = str(exc_info.value)
    assert "already uses reference slot 1" in message
    assert "different calibration session" in message
    assert "change reference_slot in the first cell to 1" in message


def _placeholder_calibration_payload():
    """The shipped seed's shape: positions present, no measuring session."""
    return {
        "schema_version": 12,
        "last_updated": "20260527_120000",
        "objectives": {
            "0": {"name": "40x", "translation_um": [-19.7, 33.0, 2.7], "session_id": None},
            "1": {"name": "10x", "translation_um": [0.0, 0.0, 0.0], "session_id": None},
            "2": {"name": "20x", "translation_um": [-6.5, 21.5, -3.7], "session_id": None},
        },
    }


def test_configured_reference_may_differ_on_a_placeholder_only_calibration(
    monkeypatch,
    sessions_root,
    machine,
    tmp_path,
):
    """A placeholder-only calibration has no measured origin to protect.

    The stored zero-reference is just the shipped seed's choice, so the
    operator's configured reference slot is accepted; adoption re-anchors
    the set to it.
    """
    calibration_path = tmp_path / "calibration.json"
    calibration_path.write_text(json.dumps(_placeholder_calibration_payload()), encoding="utf-8")
    monkeypatch.setattr("navigator_expert.config.machine.MACHINE", machine)
    _patch_objective_driver(monkeypatch)

    session = wf_obj.start_session(
        session_id="placeholder_reference_override",
        job_name="Overview",
        reference_slot=2,
        sessions_root=sessions_root,
        calibration_path=calibration_path,
    )
    assert session.from_slot == 2


def test_adoption_reanchors_a_placeholder_only_calibration(sessions_root, machine):
    """The first real measurement re-anchors a never-measured calibration.

    The measured reference becomes the [0, 0, 0] origin, the untouched
    placeholder positions are dropped (they were relative to the shipped
    origin, which no longer exists), and the objective names survive.
    """
    from navigator_expert.calibration.core import model as calibration_model

    machine.publish_snapshot(_SEED_MOMENT, calibration=_placeholder_calibration_payload())
    payload = {
        **_valid_obj_payload(),
        "from_slot": 0,
        "to_slot": 2,
        "from_objective": "40x",
        "to_objective": "20x",
    }
    session, _ = _make_report_session(
        sessions_root,
        payload,
    )

    wf_adopt.adopt_calibration(
        session,
        machine=machine,
        moment=_ADOPT_MOMENT,
    )

    current = json.loads(machine.calibration_path().read_text(encoding="utf-8"))
    assert current["objectives"]["0"]["translation_um"] == [0.0, 0.0, 0.0]
    assert current["objectives"]["2"]["translation_um"] == [12.0, 17.0, 3.0]
    # The untouched placeholder lost its shipped position but kept its name.
    assert "translation_um" not in current["objectives"]["1"]
    assert current["objectives"]["1"]["name"] == "10x"
    assert calibration_model.get_reference_slot(current) == 0


def test_adoption_still_protects_a_measured_reference(sessions_root, machine):
    """One measured slot is enough to lock the origin: the re-anchor path
    must never fire on a calibration that carries real measurements."""
    cal = _placeholder_calibration_payload()
    cal["objectives"]["1"]["session_id"] = "2026-06-01_bench"  # measured
    machine.publish_snapshot(_SEED_MOMENT, calibration=cal)
    payload = {
        **_valid_obj_payload(),
        "from_slot": 0,
        "to_slot": 1,  # the established zero-reference
        "from_objective": "40x",
        "to_objective": "10x",
    }
    session, _ = _make_report_session(
        sessions_root,
        payload,
    )
    with pytest.raises(ValueError, match="established reference"):
        wf_adopt.adopt_calibration(
            session,
            machine=machine,
            moment=_ADOPT_MOMENT,
        )


def test_start_session_reports_configured_reference_slot_and_hardware_name(
    monkeypatch, tmp_path, sessions_root, capsys
):
    calibration_path = tmp_path / "calibration.json"
    calibration_path.write_text(json.dumps(_current_calibration_payload()), encoding="utf-8")
    monkeypatch.setattr(wf_obj.drv, "connect_python_client", lambda: object())
    monkeypatch.setattr(
        wf_obj.drv,
        "connect_limits_handshake",
        lambda _client: SimpleNamespace(ok=True, error=None),
    )
    monkeypatch.setattr(
        wf_obj.drv,
        "get_hardware_info",
        lambda _client, **_kwargs: {
            "Microscope": {
                "objectives": [
                    {
                        "slotIndex": 1,
                        "objectiveNumber": 1,
                        "name": "HC PL APO CS2 10x/0.40 DRY",
                    },
                    {
                        "slotIndex": 2,
                        "objectiveNumber": 2,
                        "name": "HC PL APO CS2 20x/0.75 DRY",
                    },
                ]
            }
        },
    )
    monkeypatch.setattr(wf_obj, "_warn_if_orientation_unmeasured", lambda: None)

    session = wf_obj.start_session(
        session_id="reported_reference",
        job_name="Overview",
        reference_slot=1,
        sessions_root=sessions_root,
        calibration_path=calibration_path,
    )

    assert session.session_id == "reported_reference"
    assert session.from_slot == 1
    assert session.from_objective == "HC PL APO CS2 10x/0.40 DRY"
    assert (
        "Configured reference objective: slot 1 — HC PL APO CS2 10x/0.40 DRY"
        in capsys.readouterr().out
    )


def _live_objective_session():
    return SimpleNamespace(
        client=object(),
        job_name="Overview",
        from_slot=1,
        from_objective="HC PL APO CS2 10x/0.40 DRY",
        to_slot=None,
        to_objective=None,
        hardware_objectives={
            1: "HC PL APO CS2 10x/0.40 DRY",
            2: "HC PL APO CS2 20x/0.75 DRY",
            3: "HC PL APO CS2 40x/1.10 WATER",
        },
    )


def test_objective_cells_record_and_report_target_then_verify_both_roles(monkeypatch, capsys):
    session = _live_objective_session()
    live = {"job": "Overview", "slot": 1, "name": session.from_objective}
    monkeypatch.setattr(
        wf_obj.drv,
        "get_selected_job",
        lambda _client, **_kwargs: {"Name": live["job"]},
    )
    monkeypatch.setattr(
        wf_obj.drv,
        "get_job_settings",
        lambda _client, _job, **_kwargs: {
            "objective": {"slotIndex": live["slot"], "name": live["name"]}
        },
    )

    wf_obj._observe_objective_for_step(session, "reference")
    live.update(slot=2, name="HC PL APO CS2 20x/0.75 DRY")
    # The target focus step is the one that DEFINES the target lens.
    wf_obj._observe_objective_for_step(session, "target", establish=True)
    assert session.to_slot == 2
    assert session.to_objective == "HC PL APO CS2 20x/0.75 DRY"

    live.update(slot=1, name=session.from_objective)
    wf_obj._observe_objective_for_step(session, "reference")
    live.update(slot=2, name=session.to_objective)
    wf_obj._observe_objective_for_step(session, "target")

    output = capsys.readouterr().out
    assert "Reference objective: slot 1" in output
    assert "Target objective: slot 2" in output


def test_objective_verification_refuses_wrong_slot_same_reference_as_target_and_job_change(
    monkeypatch,
):
    session = _live_objective_session()
    live = {"job": "Overview", "slot": 2, "name": "20x"}
    monkeypatch.setattr(
        wf_obj.drv,
        "get_selected_job",
        lambda _client, **_kwargs: {"Name": live["job"]},
    )
    monkeypatch.setattr(
        wf_obj.drv,
        "get_job_settings",
        lambda _client, _job, **_kwargs: {
            "objective": {"slotIndex": live["slot"], "name": live["name"]}
        },
    )

    with pytest.raises(RuntimeError, match="wrong objective for reference step"):
        wf_obj._observe_objective_for_step(session, "reference")

    live.update(slot=1, name=session.from_objective)
    with pytest.raises(RuntimeError, match="still the reference objective"):
        wf_obj._observe_objective_for_step(session, "target")

    live["job"] = "Another job"
    with pytest.raises(RuntimeError, match="Navigator Expert job changed"):
        wf_obj._observe_objective_for_step(session, "reference")


def test_target_focus_rerun_with_a_different_lens_redefines_the_target(monkeypatch, capsys):
    """Re-running the target focus step with another lens must not lock the session.

    An accidental first run with the wrong lens used to pin ``to_slot``
    forever; the only escape was rebuilding the whole session. With
    ``establish=True`` the step simply adopts the new lens and the caller
    discards the old target data.
    """
    session = _live_objective_session()
    session.to_slot = 2
    session.to_objective = "HC PL APO CS2 20x/0.75 DRY"
    live = {"job": "Overview", "slot": 3, "name": "HC PL APO CS2 40x/1.10 WATER"}
    monkeypatch.setattr(
        wf_obj.drv,
        "get_selected_job",
        lambda _client, **_kwargs: {"Name": live["job"]},
    )
    monkeypatch.setattr(
        wf_obj.drv,
        "get_job_settings",
        lambda _client, _job, **_kwargs: {
            "objective": {"slotIndex": live["slot"], "name": live["name"]}
        },
    )

    wf_obj._observe_objective_for_step(session, "target", establish=True)

    assert session.to_slot == 3
    assert session.to_objective == "HC PL APO CS2 40x/1.10 WATER"
    output = capsys.readouterr().out
    assert "Target objective changed" in output
    assert "Discarding the previous target measurements" in output

    # Establishing still refuses the reference lens itself.
    live.update(slot=1, name=session.from_objective)
    with pytest.raises(RuntimeError, match="still the reference objective"):
        wf_obj._observe_objective_for_step(session, "target", establish=True)
    assert session.to_slot == 3


def test_target_verify_refuses_changed_lens_without_adopting_it(monkeypatch):
    """The final target step verifies against the recorded lens; it never adopts."""
    session = _live_objective_session()
    session.to_slot = 2
    session.to_objective = "HC PL APO CS2 20x/0.75 DRY"
    live = {"job": "Overview", "slot": 3, "name": "HC PL APO CS2 40x/1.10 WATER"}
    monkeypatch.setattr(
        wf_obj.drv,
        "get_selected_job",
        lambda _client, **_kwargs: {"Name": live["job"]},
    )
    monkeypatch.setattr(
        wf_obj.drv,
        "get_job_settings",
        lambda _client, _job, **_kwargs: {
            "objective": {"slotIndex": live["slot"], "name": live["name"]}
        },
    )

    with pytest.raises(RuntimeError, match="wrong objective for target step"):
        wf_obj._observe_objective_for_step(session, "target")
    assert session.to_slot == 2

    # Without an established target (e.g. a hand-built session), verifying
    # refuses instead of silently adopting whatever lens is active.
    session.to_slot = None
    session.to_objective = None
    live.update(slot=2, name="HC PL APO CS2 20x/0.75 DRY")
    with pytest.raises(RuntimeError, match="measure the target focus"):
        wf_obj._observe_objective_for_step(session, "target")
    assert session.to_slot is None


def test_observe_reference_refuses_a_session_without_a_configured_reference(monkeypatch):
    """A session with no reference slot must refuse, never silently adopt one.

    Adopting whatever objective happens to be active would let a mis-set-up
    session record the wrong lens as the reference for the whole calibration.
    """
    session = _live_objective_session()
    session.from_slot = None
    monkeypatch.setattr(
        wf_obj.drv,
        "get_selected_job",
        lambda _client, **_kwargs: {"Name": "Overview"},
    )
    monkeypatch.setattr(
        wf_obj.drv,
        "get_job_settings",
        lambda _client, _job, **_kwargs: {"objective": {"slotIndex": 2, "name": "20x"}},
    )

    with pytest.raises(RuntimeError, match="no configured reference objective slot"):
        wf_obj._observe_objective_for_step(session, "reference")


def test_start_session_no_longer_accepts_objective_labels():
    """Objective identities come from the microscope, never from typed labels."""
    with pytest.raises(TypeError):
        wf_obj.start_session(
            session_id="typed_labels",
            job_name="Overview",
            from_objective="10x",
            to_objective="20x",
            sessions_root="ignored",
            calibration_path="ignored.json",
        )


def test_objective_pair_override_calibration_path_recorded(
    monkeypatch,
    sessions_root,
    tmp_path,
):
    # Stage the override file at an arbitrary operator-supplied path.
    override = tmp_path / "alt_configs" / "alt_calibration.json"
    override.parent.mkdir(parents=True, exist_ok=True)
    cm.write_json_atomic(
        override,
        _current_calibration_payload(),
    )

    state = _patch_objective_driver(monkeypatch)
    _install_obj_vote(
        monkeypatch,
        {
            "dx_um": 0.0,
            "dy_um": 0.0,
            "trusted": True,
            "confidence": 4,
            "agreeing": ["pcc"],
        },
    )

    session = wf_obj.start_session(
        session_id="obj_override",
        job_name="Overview",
        reference_slot=1,
        sessions_root=sessions_root,
        calibration_path=override,
    )
    assert session.calibration_path == override.absolute()

    session = wf_obj.measure_parfocality_reference(session)
    state["stack_phase"] = "target"
    state["zwide"] = 94.0
    session = wf_obj.measure_parfocality_target(session)
    session = wf_obj.measure_parcentricity_reference(session)
    summary = wf_obj.measure_parcentricity_target_and_save(session)

    report = json.loads(
        (session.paths.reports_dir / f"{session.kind}_report.json").read_text(encoding="utf-8")
    )
    # The report records the exact source we used.
    assert override.name in report["source_calibration_file"]
    assert summary["config_written"] is True


def test_objective_pair_z_translation_arithmetic_peak_to_peak(
    monkeypatch,
    sessions_root,
    machine,
    capsys,
):
    # Ref-stack peak-to-peak case: home_z is diagnostic (operator's
    # approximate focus), the Brenner peaks set focus_z_ref_um=100 and
    # focus_z_target_um=103; z_post=94 after the firmware switch.
    # translation_z_um must equal focus_z_target - focus_z_ref = 3.0,
    # and motor_shift_z + correction_z must equal translation_z.
    state = _patch_objective_driver(
        monkeypatch,
        home_z=99.8,  # diagnostic, not the focus anchor
        z_post=94.0,
        ref_focus_z=100.0,
        target_focus_z=103.0,
        brenner_sigma=5.0,
    )
    _install_obj_vote(
        monkeypatch,
        {
            "dx_um": 0.0,
            "dy_um": 0.0,
            "trusted": True,
            "confidence": 4,
            "agreeing": ["pcc"],
        },
    )
    _seed_snapshot(machine)

    session = wf_obj.start_session(
        session_id="obj_z",
        job_name="Overview",
        reference_slot=1,
        sessions_root=sessions_root,
        calibration_path=machine.calibration_path(),
    )
    session = wf_obj.measure_parfocality_reference(session)
    assert session.home_z == pytest.approx(99.8)
    assert session.focus_z_ref_um == pytest.approx(100.0, abs=1e-6)

    # Operator switches to target; firmware leaves z-wide at z_post.
    state["stack_phase"] = "target"
    state["zwide"] = 94.0
    session = wf_obj.measure_parfocality_target(session)

    assert session.z_post == pytest.approx(94.0)
    assert session.focus_z_target_um == pytest.approx(103.0, abs=1e-6)
    assert session.motor_shift_z_um == pytest.approx(-6.0, abs=1e-6)
    assert session.correction_z_um == pytest.approx(9.0, abs=1e-6)
    # Peak-to-peak translation:
    assert session.translation_z_um == pytest.approx(3.0, abs=1e-6)
    # Identity: motor_shift + correction == translation.
    assert (session.motor_shift_z_um + session.correction_z_um) == pytest.approx(
        session.translation_z_um, abs=1e-6
    )
    output = capsys.readouterr().out
    assert "Reference focus:" not in output
    assert "Target focus:" not in output
    assert "home xy =" not in output
    assert "motor shift:" not in output
    assert "correction:" not in output
    assert "Z-wide translation from 10x to 20x: +3.00 µm" in output


@pytest.mark.parametrize("backlash_rounds", [0, 1, 2])
def test_objective_pair_xy_translation_arithmetic_identity(
    monkeypatch,
    sessions_root,
    machine,
    backlash_rounds,
):
    # Frames are stage-aligned (reoriented at save time), so the registered
    # image shift is already the stage-frame correction: motor_shift = (10, 20),
    # image shift = (2, -3) -> correction = (2, -3); translation = (12, 17).
    home_xy = (1000.0, 2000.0)
    xy_post = (1010.0, 2020.0)
    state = _patch_objective_driver(
        monkeypatch,
        home_xy=home_xy,
        xy_post=xy_post,
        home_z=100.0,
        z_post=94.0,
        ref_focus_z=100.0,
        target_focus_z=103.0,
    )
    _install_obj_vote(
        monkeypatch,
        {
            "dx_um": 2.0,
            "dy_um": -3.0,
            "trusted": True,
            "confidence": 4,
            "agreeing": ["pcc"],
        },
    )
    _seed_snapshot(machine)

    session = wf_obj.start_session(
        session_id="obj_xy_id",
        job_name="Overview",
        reference_slot=1,
        sessions_root=sessions_root,
        calibration_path=machine.calibration_path(),
        backlash_rounds=backlash_rounds,
    )
    session = wf_obj.measure_parfocality_reference(session)
    state["stack_phase"] = "target"
    state["zwide"] = 94.0
    session = wf_obj.measure_parfocality_target(session)
    session = wf_obj.measure_parcentricity_reference(session)
    # Operator "switches" to target: simulate the firmware shifting XY.
    state["x"], state["y"] = xy_post
    summary = wf_obj.measure_parcentricity_target_and_save(session)

    assert summary["config_written"] is True
    assert session.motor_shift_xy_um == pytest.approx((10.0, 20.0))
    assert session.correction_xy_um == pytest.approx((2.0, -3.0))
    assert session.translation_xy_um == pytest.approx((12.0, 17.0))

    cfg_path = session.paths.session_dir / "calibration.json"
    assert cfg_path.is_file()
    payload = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert payload == {
        "schema_version": 13,
        "objectives": {
            "1": {"name": "10x", "translation_um": [0.0, 0.0, 0.0]},
            "2": {"name": "20x", "translation_um": [12.0, 17.0, 3.0]},
        },
    }
    report = json.loads(
        (session.paths.reports_dir / "objective_pair_report.json").read_text(encoding="utf-8")
    )
    assert report["from_slot"] == 1
    assert report["to_slot"] == 2
    assert report["translation_xy_um"] == [12.0, 17.0]
    assert report["translation_z_um"] == pytest.approx(3.0, abs=1e-6)
    # The corrected image is acquired after a real stage move.
    assert (state["x"], state["y"]) == pytest.approx((1012.0, 2017.0))
    # Objective calibration owns motoric XY + z-wide only. It must never
    # command z-galvo, and every capture stays on the one configured
    # Navigator Expert job while the operator changes objectives manually.
    assert state["z_move_modes"] == ["zwide", "zwide"]
    assert state["acquire_jobs"]
    assert set(state["acquire_jobs"]) == {"Overview"}
    expected_passes = [] if backlash_rounds == 0 else [backlash_rounds] * 5
    expected_events = (
        ["acquire"] * 5
        if backlash_rounds == 0
        else ["backlash", "acquire"] * 5
    )
    assert state["backlash_passes"] == expected_passes
    assert state["acquisition_events"] == expected_events
    assert "backlash" not in payload
    assert report["backlash_rounds"] == backlash_rounds


def test_objective_pair_weak_xy_vote_blocks_config(monkeypatch, sessions_root, machine):
    home_xy = (1000.0, 2000.0)
    xy_post = (1010.0, 2020.0)
    state = _patch_objective_driver(
        monkeypatch,
        home_xy=home_xy,
        xy_post=xy_post,
        home_z=100.0,
        z_post=94.0,
        ref_focus_z=100.0,
        target_focus_z=103.0,
    )
    _install_obj_vote(
        monkeypatch,
        {
            "dx_um": float("nan"),
            "dy_um": float("nan"),
            "trusted": False,
            "confidence": 0,
            "agreeing": [],
        },
    )
    _seed_snapshot(machine)

    session = wf_obj.start_session(
        session_id="obj_weak",
        job_name="Overview",
        reference_slot=1,
        sessions_root=sessions_root,
        calibration_path=machine.calibration_path(),
    )
    session = wf_obj.measure_parfocality_reference(session)
    state["stack_phase"] = "target"
    state["zwide"] = 94.0
    session = wf_obj.measure_parfocality_target(session)
    session = wf_obj.measure_parcentricity_reference(session)
    state["x"], state["y"] = xy_post
    summary = wf_obj.measure_parcentricity_target_and_save(session)

    assert summary["config_written"] is False
    assert "WEAK VOTE" in summary["status"]
    assert session.translation_xy_um is None
    assert not (session.paths.session_dir / "calibration.json").exists()

    report = json.loads(
        (session.paths.reports_dir / f"{session.kind}_report.json").read_text(encoding="utf-8")
    )
    assert report["config_written"] is False
    # NaN must be coerced to null on disk.
    assert "NaN" not in (session.paths.reports_dir / f"{session.kind}_report.json").read_text(
        encoding="utf-8"
    )
    assert report["registration"]["trusted"] is False
    assert report["registration"]["image_shift_um"] == [None, None]
    assert report["translation_xy_um"] is None
    # Z fields stay populated even when XY voting fails.
    assert report["translation_z_um"] is not None


def test_objective_pair_target_xy_acquire_at_post_switch_xy(
    monkeypatch,
    sessions_root,
    machine,
):
    # Confirm the workflow does NOT return to home_xy before acquiring
    # target_xy. We assert that at the time of the target acquire the
    # stage is still at xy_post.
    home_xy = (1000.0, 2000.0)
    xy_post = (1010.0, 2020.0)
    state = _patch_objective_driver(
        monkeypatch,
        home_xy=home_xy,
        xy_post=xy_post,
        home_z=100.0,
        z_post=94.0,
        ref_focus_z=100.0,
        target_focus_z=103.0,
    )
    _install_obj_vote(
        monkeypatch,
        {
            "dx_um": 0.0,
            "dy_um": 0.0,
            "trusted": True,
            "confidence": 4,
            "agreeing": ["pcc"],
        },
    )
    _seed_snapshot(machine)

    # Track the stage XY at the moment every frame save is requested
    # (only ref_xy and target_xy use calibration-frame; the z-stacks
    # use calibration-stack and are not relevant here).
    acquire_positions: list[tuple[float, float]] = []

    real_save = cm.drv.save

    def _tracking_save(client, acq, output_root, naming, **kw):
        if naming.acquisition_type == "calibration-frame":
            acquire_positions.append((state["x"], state["y"]))
        return real_save(client, acq, output_root, naming, **kw)

    monkeypatch.setattr(cm.drv, "save", _tracking_save)

    session = wf_obj.start_session(
        session_id="obj_postswitch",
        job_name="Overview",
        reference_slot=1,
        sessions_root=sessions_root,
        calibration_path=machine.calibration_path(),
    )
    session = wf_obj.measure_parfocality_reference(session)
    state["stack_phase"] = "target"
    state["zwide"] = 94.0
    session = wf_obj.measure_parfocality_target(session)
    session = wf_obj.measure_parcentricity_reference(session)
    # Operator switches to target: firmware shifts XY to xy_post.
    state["x"], state["y"] = xy_post
    wf_obj.measure_parcentricity_target_and_save(session)

    # The last acquire is the target_xy. It must have happened at the
    # post-switch XY, not at home_xy.
    target_xy_position = acquire_positions[-1]
    assert target_xy_position == pytest.approx(xy_post)
    assert target_xy_position != pytest.approx(home_xy)


def test_objective_pair_parcentricity_reference_moves_to_home(
    monkeypatch,
    sessions_root,
    machine,
):
    home_xy = (1000.0, 2000.0)
    state = _patch_objective_driver(
        monkeypatch,
        home_xy=home_xy,
        home_z=100.0,
        z_post=94.0,
        ref_focus_z=100.0,
        target_focus_z=103.0,
    )
    _install_obj_vote(
        monkeypatch,
        {
            "dx_um": 0.0,
            "dy_um": 0.0,
            "trusted": True,
            "confidence": 4,
            "agreeing": ["pcc"],
        },
    )
    _seed_snapshot(machine)

    session = wf_obj.start_session(
        session_id="obj_ref_home",
        job_name="Overview",
        reference_slot=1,
        sessions_root=sessions_root,
        calibration_path=machine.calibration_path(),
    )
    session = wf_obj.measure_parfocality_reference(session)
    state["stack_phase"] = "target"
    state["zwide"] = 94.0
    session = wf_obj.measure_parfocality_target(session)
    # Simulate the operator drifting XY and z-wide before running Step 4.
    state["x"], state["y"] = (9999.0, -9999.0)
    state["zwide"] = 88.0

    session = wf_obj.measure_parcentricity_reference(session)
    # The cell must return the stage to home_xy and z-wide to the
    # reference Brenner focus before acquiring the reference image.
    assert (state["x"], state["y"]) == pytest.approx(home_xy)
    assert state["zwide"] == pytest.approx(session.focus_z_ref_um)


def test_objective_pair_failed_rerun_removes_stale_config(monkeypatch, sessions_root, machine):
    # Run 1: trusted vote -> session calibration compiled.
    # Run 2 (same session): weak vote on the parcentricity step. The
    # stale compiled calibration must be removed and adoption must raise.
    home_xy = (1000.0, 2000.0)
    xy_post = (1010.0, 2020.0)
    state = _patch_objective_driver(
        monkeypatch,
        home_xy=home_xy,
        xy_post=xy_post,
        home_z=100.0,
        z_post=94.0,
        ref_focus_z=100.0,
        target_focus_z=103.0,
    )
    _seed_snapshot(machine)

    votes = [
        {"dx_um": 1.0, "dy_um": -2.0, "trusted": True, "confidence": 4, "agreeing": ["pcc"]},
        {
            "dx_um": float("nan"),
            "dy_um": float("nan"),
            "trusted": False,
            "confidence": 0,
            "agreeing": [],
        },
    ]
    vote_iter = iter(votes)

    def _rv(ref, tgt, pixel_um, **kw):
        return next(vote_iter)

    monkeypatch.setattr(wf_obj, "register_voting", _rv)

    session = wf_obj.start_session(
        session_id="obj_rerun",
        job_name="Overview",
        reference_slot=1,
        sessions_root=sessions_root,
        calibration_path=machine.calibration_path(),
    )
    session = wf_obj.measure_parfocality_reference(session)
    state["stack_phase"] = "target"
    state["zwide"] = 94.0
    session = wf_obj.measure_parfocality_target(session)
    session = wf_obj.measure_parcentricity_reference(session)
    state["x"], state["y"] = xy_post
    summary1 = wf_obj.measure_parcentricity_target_and_save(session)
    assert summary1["config_written"] is True
    cfg = session.paths.session_dir / "calibration.json"
    assert cfg.is_file()

    # Operator reruns just the parcentricity target cell with new data.
    state["x"], state["y"] = xy_post
    summary2 = wf_obj.measure_parcentricity_target_and_save(session)
    assert summary2["config_written"] is False
    assert not cfg.exists()
    assert session.config_written is False

    with pytest.raises(FileNotFoundError):
        wf_adopt.adopt_calibration(
            session,
            machine=machine,
        )


# ---------------------------------------------------------------------
# Upstream rerun invalidation (Section 15 invariant for the multi-step
# objective-pair pipeline)
# ---------------------------------------------------------------------


def _full_objective_run(
    monkeypatch,
    sessions_root,
    machine,
    *,
    session_id="obj_full",
):
    """Drive the four objective-pair cells end-to-end with a trusted vote.

    Returns (session, state). Caller can then mutate ``state`` and rerun
    individual cells.
    """
    home_xy = (1000.0, 2000.0)
    xy_post = (1010.0, 2020.0)
    state = _patch_objective_driver(
        monkeypatch,
        home_xy=home_xy,
        xy_post=xy_post,
        home_z=100.0,
        z_post=94.0,
        ref_focus_z=100.0,
        target_focus_z=103.0,
        brenner_sigma=5.0,
    )
    _install_obj_vote(
        monkeypatch,
        {
            "dx_um": 2.0,
            "dy_um": -3.0,
            "trusted": True,
            "confidence": 4,
            "agreeing": ["pcc"],
        },
    )
    _seed_snapshot(machine)

    session = wf_obj.start_session(
        session_id=session_id,
        job_name="Overview",
        reference_slot=1,
        sessions_root=sessions_root,
        calibration_path=machine.calibration_path(),
    )
    session = wf_obj.measure_parfocality_reference(session)
    state["stack_phase"] = "target"
    state["zwide"] = 94.0
    session = wf_obj.measure_parfocality_target(session)
    session = wf_obj.measure_parcentricity_reference(session)
    state["x"], state["y"] = xy_post
    summary = wf_obj.measure_parcentricity_target_and_save(session)
    assert summary["config_written"] is True
    cfg = session.paths.session_dir / "calibration.json"
    assert cfg.is_file()
    return session, state, cfg


def test_objective_pair_rerun_2a_invalidates_full_pipeline(
    monkeypatch,
    sessions_root,
    machine,
):
    session, state, cfg = _full_objective_run(
        monkeypatch,
        sessions_root,
        machine,
        session_id="obj_rerun_2a",
    )

    # Operator returns to the reference objective and reruns Step 2.
    state["stack_phase"] = "ref"
    session = wf_obj.measure_parfocality_reference(session)

    assert not cfg.exists()
    assert session.config_written is False
    # Downstream state cleared:
    assert session.focus_z_target_um is None
    assert session.translation_z_um is None
    assert session.ref_image is None
    assert session.translation_xy_um is None
    assert session.target_image is None
    assert session.registration is None
    # Upstream values are freshly populated (not None) -- the rerun
    # itself wrote them.
    assert session.home_xy is not None
    assert session.home_z is not None
    assert session.focus_z_ref_um is not None

    # Skipping ahead to 3b must fail because focus_z_target_um /
    # ref_image are gone.
    with pytest.raises(RuntimeError, match="must run before"):
        wf_obj.measure_parcentricity_target_and_save(session)

    with pytest.raises(FileNotFoundError):
        wf_adopt.adopt_calibration(
            session,
            machine=machine,
        )


def test_objective_pair_rerun_2b_invalidates_parcentricity_target(
    monkeypatch,
    sessions_root,
    machine,
):
    session, state, cfg = _full_objective_run(
        monkeypatch,
        sessions_root,
        machine,
        session_id="obj_rerun_2b",
    )

    # Operator reruns 2b. ref_image and focus_z_ref_um stay valid;
    # 3b outputs and the compiled calibration must clear.
    ref_image_before = session.ref_image
    focus_ref_before = session.focus_z_ref_um
    state["stack_phase"] = "target"
    state["zwide"] = 94.0
    session = wf_obj.measure_parfocality_target(session)

    assert not cfg.exists()
    assert session.config_written is False
    assert session.translation_xy_um is None
    assert session.target_image is None
    assert session.registration is None
    assert session.motor_shift_xy_um is None
    # 2b does not change the reference focus or the reference image.
    assert session.ref_image is ref_image_before
    assert session.focus_z_ref_um == focus_ref_before
    # 2b also re-populates its own outputs.
    assert session.translation_z_um is not None

    with pytest.raises(FileNotFoundError):
        wf_adopt.adopt_calibration(
            session,
            machine=machine,
        )


def test_objective_pair_rerun_3a_invalidates_parcentricity_target(
    monkeypatch,
    sessions_root,
    machine,
):
    session, state, cfg = _full_objective_run(
        monkeypatch,
        sessions_root,
        machine,
        session_id="obj_rerun_3a",
    )

    # Operator reruns 3a. translation_z_um stays valid; 3b outputs must
    # clear; ref_image must be replaced.
    translation_z_before = session.translation_z_um
    ref_image_before = session.ref_image
    session = wf_obj.measure_parcentricity_reference(session)

    assert not cfg.exists()
    assert session.config_written is False
    assert session.translation_xy_um is None
    assert session.target_image is None
    assert session.registration is None
    # 2b's outputs are NOT cleared.
    assert session.translation_z_um == translation_z_before
    # 3a re-populates ref_image (a new object).
    assert session.ref_image is not None
    assert session.ref_image is not ref_image_before

    with pytest.raises(FileNotFoundError):
        wf_adopt.adopt_calibration(
            session,
            machine=machine,
        )


def test_wrong_objective_rerun_refuses_before_discarding_anything(
    monkeypatch,
    sessions_root,
    machine,
):
    """A rerun with the wrong lens must refuse WITHOUT wiping earlier data.

    The frustrating failure mode this pins down: the operator finishes a
    measurement, accidentally runs a cell with the wrong objective in, and
    loses everything that cell would have re-measured — even though the run
    was refused. The objective check must come before any invalidation, so
    the refusal costs nothing: switch lenses and run the cell again.
    """
    session, state, cfg = _full_objective_run(
        monkeypatch,
        sessions_root,
        machine,
        session_id="obj_wrong_lens_refusal",
    )

    def _refuse(_session, _role, **_kwargs):
        raise RuntimeError("wrong objective for this step (simulated)")

    monkeypatch.setattr(wf_obj, "_observe_objective_for_step", _refuse)

    for step in (
        wf_obj.measure_parfocality_reference,
        wf_obj.measure_parfocality_target,
        wf_obj.measure_parcentricity_reference,
        wf_obj.measure_parcentricity_target_and_save,
    ):
        with pytest.raises(RuntimeError, match="wrong objective"):
            step(session)

    # Everything the completed run produced is still there.
    assert cfg.is_file()
    assert session.config_written is True
    assert session.focus_z_ref_um is not None
    assert session.focus_z_target_um is not None
    assert session.translation_z_um is not None
    assert session.ref_image is not None
    assert session.target_image is not None
    assert session.translation_xy_um is not None
    assert session.registration is not None
    assert (session.paths.reports_dir / "objective_pair_report.json").is_file()


def test_objective_pair_rerun_2b_wipes_target_z_stack_dir(
    monkeypatch,
    sessions_root,
    machine,
):
    home_xy = (1000.0, 2000.0)
    xy_post = (1010.0, 2020.0)
    state = _patch_objective_driver(
        monkeypatch,
        home_xy=home_xy,
        xy_post=xy_post,
        home_z=100.0,
        z_post=94.0,
        ref_focus_z=100.0,
        target_focus_z=103.0,
        # First-run target stack: 21 slices [93..113].
        target_stack={
            "begin": 93.0,
            "end": 113.0,
            "sections": 21,
            "stepSize": 1.0,
            "zDrive": "z-wide",
        },
    )
    _install_obj_vote(
        monkeypatch,
        {
            "dx_um": 0.0,
            "dy_um": 0.0,
            "trusted": True,
            "confidence": 4,
            "agreeing": ["pcc"],
        },
    )
    _seed_snapshot(machine)

    session = wf_obj.start_session(
        session_id="obj_zstack_wipe",
        job_name="Overview",
        reference_slot=1,
        sessions_root=sessions_root,
        calibration_path=machine.calibration_path(),
    )
    session = wf_obj.measure_parfocality_reference(session)

    state["stack_phase"] = "target"
    state["zwide"] = 94.0
    session = wf_obj.measure_parfocality_target(session)
    z_dir = session.paths.data_dir / "target_z_stack"
    first_run_z = sorted(parse_image_name(p.name).z for p in z_dir.rglob("*.ome.tiff"))
    assert first_run_z == list(range(21))

    # Operator reconfigures LAS X to a smaller stack (5 slices) and
    # reruns Step 3. The disk wipe must remove the stale z_005..z_020.
    state["target_stack"] = {
        "begin": 101.0,
        "end": 105.0,
        "sections": 5,
        "stepSize": 1.0,
        "zDrive": "z-wide",
    }
    state["zwide"] = 94.0
    session = wf_obj.measure_parfocality_target(session)
    second_run_z = sorted(parse_image_name(p.name).z for p in z_dir.rglob("*.ome.tiff"))
    assert second_run_z == list(range(5))


# ---------------------------------------------------------------------
# Exception-path stale-config invariants (Section 15 invariant on the
# partial-failure-during-rerun path)
# ---------------------------------------------------------------------


def test_objective_pair_rerun_3b_acquire_failure_removes_stale_config(
    monkeypatch,
    sessions_root,
    machine,
):
    """Full pipeline success writes the session calibration. A 3b
    rerun raises mid-acquire. The stale result must be gone BEFORE the
    exception propagates.
    """
    home_xy = (1000.0, 2000.0)
    xy_post = (1010.0, 2020.0)
    boom = RuntimeError("acquire_frame failed")
    # Full run uses acquire_stack for the z-stacks; ref_xy, target_xy,
    # and the stage-corrected target are frame indices 0..2. The rerun's
    # target_xy is index 3.
    state = _patch_objective_driver(
        monkeypatch,
        home_xy=home_xy,
        xy_post=xy_post,
        home_z=100.0,
        z_post=94.0,
        ref_focus_z=100.0,
        target_focus_z=103.0,
        acquire_side_effects=[None, None, None, boom],
    )
    _install_obj_vote(
        monkeypatch,
        {
            "dx_um": 1.0,
            "dy_um": -2.0,
            "trusted": True,
            "confidence": 4,
            "agreeing": ["pcc"],
        },
    )
    _seed_snapshot(machine)

    session = wf_obj.start_session(
        session_id="obj_3b_fail",
        job_name="Overview",
        reference_slot=1,
        sessions_root=sessions_root,
        calibration_path=machine.calibration_path(),
    )
    session = wf_obj.measure_parfocality_reference(session)
    state["stack_phase"] = "target"
    state["zwide"] = 94.0
    session = wf_obj.measure_parfocality_target(session)
    session = wf_obj.measure_parcentricity_reference(session)
    state["x"], state["y"] = xy_post
    summary1 = wf_obj.measure_parcentricity_target_and_save(session)
    assert summary1["config_written"] is True
    cfg = session.paths.session_dir / "calibration.json"
    assert cfg.is_file()

    # Rerun 3b. The next acquire (target_xy) raises.
    state["x"], state["y"] = xy_post
    with pytest.raises(RuntimeError, match="acquire_frame failed"):
        wf_obj.measure_parcentricity_target_and_save(session)

    assert not cfg.exists()
    assert session.config_written is False
    with pytest.raises(FileNotFoundError):
        wf_adopt.adopt_calibration(
            session,
            machine=machine,
        )


def test_objective_pair_rerun_2a_wipes_per_step_tiffs(
    monkeypatch,
    sessions_root,
    machine,
):
    """A 2a rerun must leave data_dir consistent with the freshly-reset
    session: no stale ref_xy.tif / target_xy.tif / target_z_stack from
    the previous run remain on disk. (Ref stack is also wiped at the
    top of 2a; that case is verified separately in
    test_objective_pair_rerun_2a_wipes_ref_z_stack_dir, but the new
    2a immediately re-acquires the ref stack, so the directory ends
    populated -- we don't assert its absence here.)
    """
    session, state, cfg = _full_objective_run(
        monkeypatch,
        sessions_root,
        machine,
        session_id="obj_2a_tiff_wipe",
    )

    data_dir = session.paths.data_dir
    assert any((data_dir / "ref_xy").rglob("*.ome.tiff"))
    assert any((data_dir / "target_xy").rglob("*.ome.tiff"))
    target_z_dir = data_dir / "target_z_stack"
    assert target_z_dir.is_dir()
    assert any(target_z_dir.rglob("*.ome.tiff"))

    state["stack_phase"] = "ref"
    session = wf_obj.measure_parfocality_reference(session)

    assert not (data_dir / "ref_xy").exists()
    assert not (data_dir / "target_xy").exists()
    assert not (data_dir / "target_xy_corrected").exists()
    assert not target_z_dir.exists()
    assert not cfg.exists()


# ---------------------------------------------------------------------
# Ref-stack workflow (CALIBRATION_REF_STACK_UPDATE_PLAN.md)
# ---------------------------------------------------------------------


def test_objective_pair_parfocality_reference_acquires_z_stack(
    monkeypatch,
    sessions_root,
    machine,
):
    _patch_objective_driver(
        monkeypatch,
        home_z=99.8,  # diagnostic, distinct from peak
        ref_focus_z=100.0,
    )
    _install_obj_vote(
        monkeypatch,
        {
            "dx_um": 0.0,
            "dy_um": 0.0,
            "trusted": True,
            "confidence": 4,
            "agreeing": ["pcc"],
        },
    )
    _seed_snapshot(machine)

    session = wf_obj.start_session(
        session_id="obj_ref_stack",
        job_name="Overview",
        reference_slot=1,
        sessions_root=sessions_root,
        calibration_path=machine.calibration_path(),
    )
    session = wf_obj.measure_parfocality_reference(session)

    # Ref stack landed on disk with one TIFF per slice.
    z_dir = session.paths.data_dir / "ref_z_stack"
    assert z_dir.is_dir()
    files = sorted(z_dir.rglob("*.ome.tiff"))
    assert len(files) == 11
    # Brenner peak roughly at the Gaussian center (100.0).
    assert session.focus_z_ref_um == pytest.approx(100.0, abs=1e-6)
    # Diagnostic vs anchor are distinct.
    assert session.home_z == pytest.approx(99.8)
    assert session.focus_z_ref_um != pytest.approx(session.home_z)
    # Brenner series captured.
    assert session.ref_z_brenner is not None
    assert len(session.ref_z_brenner) == 11
    assert session.ref_z_positions_um is not None
    assert len(session.ref_z_positions_um) == 11


def test_objective_pair_z_stack_zoom_independent_of_image_to_stage(
    monkeypatch,
    sessions_root,
    machine,
):
    # image_to_stage carries only the X/Y sign; the operator can run the
    # parfocality z-stack at any zoom they like. Brenner focus does not
    # depend on pixel size. This test runs Steps 2 and 3 with z-stack
    # pixel_size_um intentionally different from whatever image_to_stage
    # was acquired at, and asserts no geometry check fires.
    state = _patch_objective_driver(
        monkeypatch,
        pixel_size_um=1.0,
    )
    _install_obj_vote(
        monkeypatch,
        {
            "dx_um": 0.0,
            "dy_um": 0.0,
            "trusted": True,
            "confidence": 4,
            "agreeing": ["pcc"],
        },
    )
    _seed_snapshot(machine)

    session = wf_obj.start_session(
        session_id="obj_z_zoom",
        job_name="Overview",
        reference_slot=1,
        sessions_root=sessions_root,
        calibration_path=machine.calibration_path(),
    )
    # Both parfocality steps must run without raising despite the
    # zoom difference from image_to_stage.
    session = wf_obj.measure_parfocality_reference(session)
    state["stack_phase"] = "target"
    state["zwide"] = 94.0
    session = wf_obj.measure_parfocality_target(session)
    assert session.focus_z_ref_um is not None
    assert session.focus_z_target_um is not None


def test_objective_pair_parcentricity_xy_pixel_size_mismatch_raises(
    monkeypatch,
    sessions_root,
    machine,
):
    # The only real geometry constraint in objective-pair: the target XY
    # must match the reference XY's pixel size so voting registration
    # sees the same scale on both sides. Mismatch -> raise.
    state = _patch_objective_driver(
        monkeypatch,
        pixel_size_um=0.5,
    )
    _install_obj_vote(
        monkeypatch,
        {
            "dx_um": 0.0,
            "dy_um": 0.0,
            "trusted": True,
            "confidence": 4,
            "agreeing": ["pcc"],
        },
    )
    _seed_snapshot(machine)

    session = wf_obj.start_session(
        session_id="obj_xy_pix_mismatch",
        job_name="Overview",
        reference_slot=1,
        sessions_root=sessions_root,
        calibration_path=machine.calibration_path(),
    )
    session = wf_obj.measure_parfocality_reference(session)
    state["stack_phase"] = "target"
    state["zwide"] = 94.0
    session = wf_obj.measure_parfocality_target(session)
    session = wf_obj.measure_parcentricity_reference(session)

    # Before Step 5, change the reported pixel size so target XY does
    # not match the ref XY's recorded pixel size.
    monkeypatch.setattr(
        cm.drv,
        "parse_tile_geometry",
        lambda settings: {
            "pixel_w_um": 1.0,
            "pixel_h_um": 1.0,
            "pixels_x": 64,
            "pixels_y": 64,
        },
    )
    state["x"], state["y"] = (1010.0, 2020.0)

    with pytest.raises(ValueError, match="pixel size"):
        wf_obj.measure_parcentricity_target_and_save(session)


def test_objective_pair_report_has_ref_and_target_brenner_blocks(
    monkeypatch,
    sessions_root,
    machine,
):
    session, state, cfg = _full_objective_run(
        monkeypatch,
        sessions_root,
        machine,
        session_id="obj_report_brenner",
    )
    report = json.loads(
        (session.paths.reports_dir / f"{session.kind}_report.json").read_text(encoding="utf-8")
    )

    # Both Brenner blocks present, populated, with matching lengths.
    assert "brenner_ref" in report
    assert "brenner_target" in report
    for key in ("brenner_ref", "brenner_target"):
        block = report[key]
        assert block["peak_z_um"] is not None
        assert len(block["scores"]) >= 3
        assert len(block["scores"]) == len(block["z_positions_um"])

    # Both z-stack directories referenced under images.
    assert "ref_z_stack" in report["images"]
    assert "target_z_stack" in report["images"]
    assert report["images"]["ref_z_stack"].endswith("/")
    assert report["images"]["target_z_stack"].endswith("/")
    # focus_z_ref_um surfaces at the top level for quick inspection.
    assert report["focus_z_ref_um"] is not None
    assert report["focus_z_target_um"] is not None


def test_objective_pair_rerun_2a_wipes_ref_z_stack_dir(monkeypatch, sessions_root, machine):
    # First run with 11 ref slices; rerun 2a with 5 ref slices. The
    # wipe at the top of _clear_parfocality_reference must remove the
    # stale higher-index slices.
    state = _patch_objective_driver(
        monkeypatch,
        home_z=100.0,
        ref_focus_z=100.0,
        target_focus_z=103.0,
        ref_stack={
            "begin": 95.0,
            "end": 105.0,
            "sections": 11,
            "stepSize": 1.0,
            "zDrive": "z-wide",
        },
    )
    _install_obj_vote(
        monkeypatch,
        {
            "dx_um": 0.0,
            "dy_um": 0.0,
            "trusted": True,
            "confidence": 4,
            "agreeing": ["pcc"],
        },
    )
    _seed_snapshot(machine)

    session = wf_obj.start_session(
        session_id="obj_ref_wipe",
        job_name="Overview",
        reference_slot=1,
        sessions_root=sessions_root,
        calibration_path=machine.calibration_path(),
    )
    session = wf_obj.measure_parfocality_reference(session)
    ref_dir = session.paths.data_dir / "ref_z_stack"
    first_run_z = sorted(parse_image_name(p.name).z for p in ref_dir.rglob("*.ome.tiff"))
    assert first_run_z == list(range(11))

    # Operator reconfigures the LAS X ref stack to 5 sections and
    # reruns Step 2. begin/end must keep the focus peak interior even
    # after slice 0 is dropped by the analysis -- this test exercises
    # the wipe behavior, not the peak math.
    state["ref_stack"] = {
        "begin": 98.0,
        "end": 102.0,
        "sections": 5,
        "stepSize": 1.0,
        "zDrive": "z-wide",
    }
    state["stack_phase"] = "ref"
    session = wf_obj.measure_parfocality_reference(session)

    second_run_z = sorted(parse_image_name(p.name).z for p in ref_dir.rglob("*.ome.tiff"))
    assert second_run_z == list(range(5))


def test_objective_pair_missing_stack_positions_raises(monkeypatch, sessions_root, machine):
    # LAS X reports no stack metadata and the operator did not pass an
    # override. The workflow must raise a clear RuntimeError rather
    # than guess positions from slice count.
    _patch_objective_driver(monkeypatch)
    # Strip the stack block from get_job_settings.
    monkeypatch.setattr(
        cm.drv,
        "get_job_settings",
        lambda *a, **k: {
            "zoom": {"current": 1.0},
            "scanSpeed": {"value": 600.0},
            "activeSettings": [],
            "scanMode": "xyz",
        },
    )
    monkeypatch.setattr(
        cm.drv,
        "make_changeable_copy",
        lambda settings: {"stack": None} if settings else None,
    )
    _seed_snapshot(machine)

    session = wf_obj.start_session(
        session_id="obj_missing_pos",
        job_name="Overview",
        reference_slot=1,
        sessions_root=sessions_root,
        calibration_path=machine.calibration_path(),
    )
    with pytest.raises(RuntimeError, match="z-stack"):
        wf_obj.measure_parfocality_reference(session)


def test_objective_pair_z_stack_requires_at_least_five_slices(
    monkeypatch,
    sessions_root,
    machine,
):
    _patch_objective_driver(
        monkeypatch,
        ref_stack={
            "begin": 98.5,
            "end": 101.5,
            "sections": 4,
            "stepSize": 1.0,
            "zDrive": "z-wide",
        },
    )
    _seed_snapshot(machine)
    session_a = wf_obj.start_session(
        session_id="obj_min_slices_meta",
        job_name="Overview",
        reference_slot=1,
        sessions_root=sessions_root,
        calibration_path=machine.calibration_path(),
    )
    with pytest.raises(RuntimeError, match="at least 5"):
        wf_obj.measure_parfocality_reference(session_a)


def test_objective_pair_z_stack_override_requires_at_least_five(
    monkeypatch,
    sessions_root,
    machine,
):
    _patch_objective_driver(
        monkeypatch,
        ref_stack={
            "begin": 98.5,
            "end": 101.5,
            "sections": 4,
            "stepSize": 1.0,
            "zDrive": "z-wide",
        },
    )
    _seed_snapshot(machine)
    session = wf_obj.start_session(
        session_id="obj_min_slices_override",
        job_name="Overview",
        reference_slot=1,
        sessions_root=sessions_root,
        calibration_path=machine.calibration_path(),
    )
    with pytest.raises(ValueError, match="at least 5"):
        wf_obj.measure_parfocality_reference(
            session,
            z_positions_um=[98.5, 99.5, 100.5, 101.5],
        )


def test_objective_pair_descending_stack_fits_peak_correctly(
    monkeypatch,
    sessions_root,
    machine,
):
    # np.linspace(105, 95, 11) yields the slices in descending order
    # (z_arr[1] - z_arr[0] = -1.0). The parabolic refinement must use
    # the SIGNED spacing or the sub-slice correction moves in the
    # wrong direction (away from the true peak).
    _patch_objective_driver(
        monkeypatch,
        home_z=105.0,
        ref_focus_z=100.3,
        target_focus_z=103.0,
        brenner_sigma=5.0,
        ref_stack={
            "begin": 105.0,
            "end": 95.0,
            "sections": 11,
            "stepSize": 1.0,
            "zDrive": "z-wide",
        },
    )
    _install_obj_vote(
        monkeypatch,
        {
            "dx_um": 0.0,
            "dy_um": 0.0,
            "trusted": True,
            "confidence": 4,
            "agreeing": ["pcc"],
        },
    )
    _seed_snapshot(machine)

    session = wf_obj.start_session(
        session_id="obj_descending",
        job_name="Overview",
        reference_slot=1,
        sessions_root=sessions_root,
        calibration_path=machine.calibration_path(),
    )
    session = wf_obj.measure_parfocality_reference(session)

    # The true peak is at 100.3; the discrete max sits at slice index
    # 5 (z=100). With abs(step), parabolic refinement moves DOWN to
    # ~99.7. With signed step, it moves UP to ~100.3.
    assert session.focus_z_ref_um == pytest.approx(100.3, abs=0.05)
    assert session.focus_z_ref_um > 100.0


def test_read_stack_z_positions_falls_back_on_partial_normalized(monkeypatch):
    # make_changeable_copy returns a stack dict with only `begin`
    # populated; the raw settings carry full begin/end/sections. The
    # helper must fall back to the raw block rather than raise.
    _patch_objective_driver(monkeypatch)

    full_raw = {
        "zoom": {"current": 1.0},
        "scanSpeed": {"value": 600.0, "isResonant": False},
        "activeSettings": [],
        "scanMode": "xyz",
        "stack": {
            "begin": 95.0,
            "end": 105.0,
            "sections": 11,
            "stepSize": 1.0,
            "mode": "z-wide",
        },
    }
    monkeypatch.setattr(
        cm.drv,
        "get_job_settings",
        lambda *a, **k: full_raw,
    )
    # Normalized form has only `begin`; end/sections are None.
    monkeypatch.setattr(
        cm.drv,
        "make_changeable_copy",
        lambda settings: (
            {
                "stack": {
                    "begin": 95.0,
                    "end": None,
                    "sections": None,
                    "stepSize": None,
                    "zDrive": None,
                }
            }
            if settings
            else None
        ),
    )

    positions = cm.read_stack_z_positions(
        client=object(),
        job_name="Overview",
        expected_slices=11,
    )
    assert len(positions) == 11
    assert positions[0] == pytest.approx(95.0)
    assert positions[-1] == pytest.approx(105.0)


def test_read_stack_z_positions_pins_api_mode(monkeypatch):
    calls = []
    full_raw = {
        "stack": {
            "begin": 0.0,
            "end": 4.0,
            "sections": 5,
            "zDrive": "z-wide",
        },
    }

    def _get_job_settings(client, job_name, **kwargs):
        calls.append((job_name, kwargs))
        return full_raw

    monkeypatch.setattr(cm.drv, "get_job_settings", _get_job_settings)
    monkeypatch.setattr(
        cm.drv,
        "make_changeable_copy",
        lambda settings: {"stack": dict(settings["stack"])} if settings else None,
    )

    cm.read_stack_z_positions(
        client=object(),
        job_name="Overview",
        expected_slices=5,
    )

    assert calls[0][1]["mode"] == "api"


def test_read_stack_z_positions_ignores_rounded_step_size(monkeypatch):
    # Regression: LAS X reports stepSize with limited precision. On
    # the rig, stepSize=2.051 came back alongside begin=0.0,
    # end=79.98003, sections=40 -- a derived step of 2.05077 um. The
    # workflow previously raised on this 0.00023 um disagreement.
    # begin/end/sections are authoritative; stepSize is informational
    # only and must not gate calibration.
    full_raw = {
        "zoom": {"current": 1.0},
        "scanSpeed": {"value": 600.0, "isResonant": False},
        "activeSettings": [],
        "scanMode": "xyz",
        "stack": {
            "begin": 0.0,
            "end": 79.98003,
            "sections": 40,
            "stepSize": 2.051,
            "zDrive": "z-wide",
        },
    }
    monkeypatch.setattr(
        cm.drv,
        "get_job_settings",
        lambda *a, **k: full_raw,
    )
    monkeypatch.setattr(
        cm.drv,
        "make_changeable_copy",
        lambda settings: {"stack": dict(settings["stack"])} if settings else None,
    )

    positions = cm.read_stack_z_positions(
        client=object(),
        job_name="Overview",
        expected_slices=40,
    )
    assert len(positions) == 40
    assert all(isinstance(z, float) for z in positions)
    assert positions[0] == pytest.approx(0.0)
    assert positions[-1] == pytest.approx(79.98003)


def test_objective_pair_non_finite_brenner_raises(monkeypatch, sessions_root, machine):
    # If any slice's Brenner score comes back NaN or +/-inf, the
    # workflow must raise rather than feed it into argmax/parabolic
    # peak (where it would silently corrupt focus_z_ref_um).
    _patch_objective_driver(
        monkeypatch,
        ref_focus_z=100.0,
        target_focus_z=103.0,
    )
    _seed_snapshot(machine)

    call_count = {"n": 0}
    real_brenner = wf_obj.brenner

    def _brenner_with_nan(img):
        idx = call_count["n"]
        call_count["n"] += 1
        if idx == 3:
            return float("nan")
        return float(real_brenner(img))

    monkeypatch.setattr(wf_obj, "brenner", _brenner_with_nan)

    session = wf_obj.start_session(
        session_id="obj_nan_brenner",
        job_name="Overview",
        reference_slot=1,
        sessions_root=sessions_root,
        calibration_path=machine.calibration_path(),
    )
    with pytest.raises(RuntimeError, match="non-finite"):
        wf_obj.measure_parfocality_reference(session)


def test_objective_pair_first_slice_artifact_is_dropped(
    monkeypatch,
    sessions_root,
    machine,
):
    # The driver's stack readback returns slice 0 before its file is
    # fully written, producing a Brenner spike on slice 0 that would
    # otherwise hijack argmax. The workflow drops slice 0 before peak
    # fitting; a spike on slice 0 must NOT corrupt focus_z_ref_um. The
    # full Brenner array stays in the session for diagnostics.
    _patch_objective_driver(
        monkeypatch,
        ref_focus_z=100.0,
        target_focus_z=103.0,
    )
    _seed_snapshot(machine)

    real_brenner = wf_obj.brenner
    call_count = {"n": 0}

    def _brenner_with_slice0_spike(img):
        idx = call_count["n"]
        call_count["n"] += 1
        if idx == 0:
            return 100.0
        return float(real_brenner(img))

    monkeypatch.setattr(wf_obj, "brenner", _brenner_with_slice0_spike)

    session = wf_obj.start_session(
        session_id="obj_slice0_drop",
        job_name="Overview",
        reference_slot=1,
        sessions_root=sessions_root,
        calibration_path=machine.calibration_path(),
    )
    session = wf_obj.measure_parfocality_reference(session)

    # Recovered Brenner peak is the real Gaussian peak, not slice 0.
    assert session.focus_z_ref_um == pytest.approx(100.0, abs=0.5)
    # The full Brenner array stays on the session, including the slice-0
    # spike. Operator/report can see the artifact happened.
    assert session.ref_z_brenner[0] == pytest.approx(100.0)


def test_objective_pair_last_slice_artifact_is_dropped(
    monkeypatch,
    sessions_root,
    machine,
):
    # Symmetric counterpart: a spike on the last slice (file-commit timing
    # is in principle symmetric, even if only the leading slice has been
    # observed breaking in practice). The trailing slice is dropped before
    # peak fitting; the spike must NOT corrupt focus_z_ref_um.
    _patch_objective_driver(
        monkeypatch,
        ref_focus_z=100.0,
        target_focus_z=103.0,
    )
    _seed_snapshot(machine)

    real_brenner = wf_obj.brenner
    call_count = {"n": 0}

    def _brenner_with_last_spike(img):
        idx = call_count["n"]
        call_count["n"] += 1
        # Default ref stack has 11 slices; spike index 10 (the last one).
        if idx == 10:
            return 100.0
        return float(real_brenner(img))

    monkeypatch.setattr(wf_obj, "brenner", _brenner_with_last_spike)

    session = wf_obj.start_session(
        session_id="obj_lastslice_drop",
        job_name="Overview",
        reference_slot=1,
        sessions_root=sessions_root,
        calibration_path=machine.calibration_path(),
    )
    session = wf_obj.measure_parfocality_reference(session)

    assert session.focus_z_ref_um == pytest.approx(100.0, abs=0.5)
    assert session.ref_z_brenner[-1] == pytest.approx(100.0)


def test_objective_pair_brenner_peak_at_stack_edge_raises(
    monkeypatch,
    sessions_root,
    machine,
):
    # The operator configures the stack around the focal plane, so a
    # valid Brenner peak must be inside the fitted interior window.
    # After the workflow drops slice 0, slice 1 is the lower edge of
    # that window. A spike there still raises.
    _patch_objective_driver(
        monkeypatch,
        ref_focus_z=100.0,
        target_focus_z=103.0,
    )
    _seed_snapshot(machine)

    real_brenner = wf_obj.brenner
    call_count = {"n": 0}

    def _brenner_edge_spike(img):
        idx = call_count["n"]
        call_count["n"] += 1
        # Spike at slice 1 -- slice 0 is dropped, so slice 1 is the new
        # lower edge of the peak-fit window.
        if idx == 1:
            return 100.0
        return float(real_brenner(img))

    monkeypatch.setattr(wf_obj, "brenner", _brenner_edge_spike)

    session = wf_obj.start_session(
        session_id="obj_edge_peak",
        job_name="Overview",
        reference_slot=1,
        sessions_root=sessions_root,
        calibration_path=machine.calibration_path(),
    )
    with pytest.raises(RuntimeError, match="stack edge"):
        wf_obj.measure_parfocality_reference(session)


def test_remeasured_pair_newest_report_wins_regardless_of_folder_name(sessions_root, machine):
    """Re-measuring a pair under a NEW acquisition name must supersede the
    old measurement by its created_at timestamp — never by which folder
    name sorts last. The folder names here are adversarial: the older
    measurement's folder sorts alphabetically last, so path order would
    silently pick the wrong one."""
    session_id = "remeasure"
    reports = (
        # (folder, created_at, translation_xy, translation_z)
        ("a-second-try", "2026-07-19T12:00:00+00:00", [99.0, -88.0], 7.5),  # newest
        ("z-first-try", "2026-07-01T09:00:00+00:00", [12.0, 17.0], 3.0),  # older
    )
    paths = None
    for acquisition_name, created_at, xy, z in reports:
        paths = cm.make_session_paths(
            session_id,
            sessions_root,
            acquisition_name=acquisition_name,
        )
        cm.write_json_atomic(
            paths.reports_dir / "objective_pair_report.json",
            {
                "schema_version": cm.STAGING_SCHEMA_VERSION,
                "kind": "objective_translation_report",
                "session_id": session_id,
                "acquisition_name": acquisition_name,
                "created_at": created_at,
                "config_written": True,
                "from_slot": 1,
                "to_slot": 2,
                "from_objective": "10x",
                "to_objective": "20x",
                "translation_xy_um": xy,
                "translation_z_um": z,
            },
        )

    session = SimpleNamespace(
        session_id=session_id,
        paths=paths,
        calibration_path=machine.bundled_default_path("calibration.json"),
        hardware_objectives={1: "10x", 2: "20x"},
    )
    compiled = wf_adopt.compile_session_calibration(session)
    config = json.loads(compiled.read_text(encoding="utf-8"))
    assert config["objectives"]["2"]["translation_um"] == [99.0, -88.0, 7.5]

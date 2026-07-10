"""Tests for calibration/core/ (PR 1).

Covers:

- SessionPaths creation and folder layout
- slug + objective_config_name + geometry validation
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

from navigator_expert.calibration.core import (
    adopt as wf_adopt,
)
from navigator_expert.calibration.core import common as cm
from navigator_expert.calibration.core import (
    objective_pair as wf_obj,
)
from navigator_expert.config.machine import MachineProfile

from shared.output_layout import build_image_name

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


def test_make_session_paths_creates_layout(sessions_root):
    paths = cm.make_session_paths(
        "sess1",
        "image_to_stage",
        sessions_root=sessions_root,
    )
    for sub in (paths.configs_dir, paths.reports_dir, paths.notebooks_dir, paths.data_dir):
        assert sub.is_dir()
    assert paths.data_dir.name == "image_to_stage"
    assert paths.data_dir.parent.name == "data"
    assert paths.session_dir.name == "sess1"


def test_make_session_paths_uses_explicit_root(sessions_root):
    paths = cm.make_session_paths(
        "sess_explicit",
        "image_to_stage",
        sessions_root=sessions_root,
    )
    assert paths.session_dir.parent == sessions_root.absolute()


def test_make_session_paths_does_not_use_package_sessions_root(sessions_root):
    paths = cm.make_session_paths(
        "sess_pkg",
        "image_to_stage",
        sessions_root=sessions_root,
    )
    package_sessions = Path(cm.__file__).resolve().parents[1] / "sessions"
    # session_dir lives under the explicit root, NOT the package tree.
    assert package_sessions not in paths.session_dir.parents


def test_runtime_paths_preserve_drive_letter(sessions_root):
    paths = cm.make_session_paths(
        "probe",
        "image_to_stage",
        sessions_root=sessions_root,
    )
    # The constructed session_dir keeps the same drive letter / prefix
    # as the input root -- no UNC conversion, no symlink dereferencing.
    expected_drive = sessions_root.absolute().drive
    assert (
        str(paths.session_dir).startswith(str(sessions_root.absolute().drive))
        or paths.session_dir.drive == expected_drive
    )


def test_slug_and_objective_config_name():
    assert cm.slug("10x") == "10x"
    assert cm.slug("100x oil") == "100x_oil"
    assert cm.slug("0.5x") == "0p5x"
    assert cm.objective_config_name("10x", "20x") == "objective_10x_to_20x.json"
    assert cm.objective_config_name("10x", "100x oil") == "objective_10x_to_100x_oil.json"


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
        shift_um=(0.5, -0.3),
        pixel_size_um=1.0,
    )
    assert fig is not None
    plt = pytest.importorskip("matplotlib.pyplot")

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


def _make_staging_session(
    sessions_root,
    kind_payload,
    staging_name="image_to_stage.json",
):
    sess_id = "adopt_sess"
    paths = cm.make_session_paths(
        sess_id,
        "image_to_stage",
        sessions_root=sessions_root,
    )
    cfg = paths.configs_dir / staging_name
    cm.write_json_atomic(cfg, kind_payload)

    class _Stub:
        pass

    s = _Stub()
    s.session_id = sess_id
    s.paths = paths
    return s, cfg


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
    session, _ = _make_staging_session(
        sessions_root,
        payload,
        "objective_10x_to_20x.json",
    )

    wf_adopt.adopt_calibration(
        session,
        "objective_10x_to_20x.json",
        calibration_name="water_lens_set",
        machine=machine,
        moment=_ADOPT_MOMENT,
    )

    current = json.loads(machine.calibration_path("water_lens_set").read_text(encoding="utf-8"))
    assert current["objectives"]["2"]["translation_um"] == [12.0, 17.0, 3.0]
    assert current["objectives"]["2"]["session_id"] == session.session_id
    assert (
        machine.latest_snapshot() / "calibrations" / "water_lens_set" / "calibration.json"
    ).exists()


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
    session, _ = _make_staging_session(
        sessions_root,
        payload,
        "objective_10x_to_20x.json",
    )
    session.hardware_objectives = {
        1: "HC PL APO CS2 10x/0.40 WATER",
        2: "HC PL APO CS2 20x/0.75 WATER",
    }

    wf_adopt.adopt_calibration(
        session,
        "objective_10x_to_20x.json",
        calibration_name="water_lens_set",
        machine=machine,
        moment=_ADOPT_MOMENT,
    )

    current = json.loads(machine.calibration_path("water_lens_set").read_text(encoding="utf-8"))
    assert current["objectives"]["1"]["name"] == "HC PL APO CS2 10x/0.40 WATER"
    assert current["objectives"]["2"]["name"] == "HC PL APO CS2 20x/0.75 WATER"
    # the translation is still applied alongside the refreshed name
    assert current["objectives"]["2"]["translation_um"] == [12.0, 17.0, 3.0]


def test_adoption_missing_staging_raises(sessions_root, machine):
    sess_id = "missing_sess"
    paths = cm.make_session_paths(
        sess_id,
        "image_to_stage",
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
            "image_to_stage.json",
            machine=machine,
        )


def test_adoption_wrong_kind_rejected(sessions_root, machine):
    bad = dict(_valid_obj_payload())
    bad["kind"] = "garbage"
    session, _ = _make_staging_session(sessions_root, bad)
    with pytest.raises(ValueError, match="unsupported kind"):
        wf_adopt.adopt_calibration(
            session,
            "image_to_stage.json",
            machine=machine,
        )


def test_adoption_seeds_from_bundled_default_when_no_snapshot(sessions_root, machine):
    # With a fresh machine (no snapshot) an objective-pair adopt reads the
    # bundled default, merges the delta, and publishes the first snapshot.
    assert machine.latest_snapshot() is None
    payload = _valid_obj_payload()
    session, _ = _make_staging_session(
        sessions_root,
        payload,
        "objective_10x_to_20x.json",
    )
    out = wf_adopt.adopt_calibration(
        session,
        "objective_10x_to_20x.json",
        calibration_name="lens_config_A",
        machine=machine,
        moment=_ADOPT_MOMENT,
    )
    assert machine.latest_snapshot() is not None
    assert len(machine.snapshots()) == 1
    assert Path(out["snapshot"]) == machine.latest_snapshot()
    # The bundled default's slot 1 is the "10x" reference ([0,0,0]); the
    # merged snapshot records the "20x" (slot 2) translation delta.
    assert Path(out["calibration_path"]) == (
        machine.latest_snapshot() / "calibrations" / "lens_config_A" / "calibration.json"
    )
    merged = json.loads(machine.calibration_path("lens_config_A").read_text(encoding="utf-8"))
    assert merged["objectives"]["2"]["translation_um"] == [12.0, 17.0, 3.0]
    assert merged["objectives"]["2"]["session_id"] == session.session_id


# ---------------------------------------------------------------------
# Post-review fixes (PR 1 polish)
# ---------------------------------------------------------------------


def _strict_json_parse(text: str):
    """Strict JSON parse that rejects NaN / Infinity tokens."""

    def _no_constants(c):
        raise ValueError(f"non-finite JSON constant: {c!r}")

    return json.loads(text, parse_constant=_no_constants)


def test_adoption_staging_name_with_separator_rejected(sessions_root, machine):
    session, _ = _make_staging_session(sessions_root, _valid_obj_payload())
    with pytest.raises(ValueError, match="bare filename"):
        wf_adopt.adopt_calibration(
            session,
            "sub/image_to_stage.json",
            machine=machine,
        )
    with pytest.raises(ValueError, match="bare filename"):
        wf_adopt.adopt_calibration(
            session,
            "..\\evil.json",
            machine=machine,
        )


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
        lambda client, **kw: {"ok": True},
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
        if z_mode == "zwide":
            state["zwide"] = float(z)
        return {"success": True}

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

    return state


def _install_obj_vote(monkeypatch, vote):
    def _rv(ref, tgt, pixel_um, **kw):
        return vote

    monkeypatch.setattr(wf_obj, "register_voting", _rv)


def test_start_session_requires_sessions_root_objective_pair(monkeypatch):
    # No driver patches: start_session must raise BEFORE any driver
    # call. TypeError comes from the keyword-only signature.
    with pytest.raises(TypeError):
        wf_obj.start_session(
            session_id="obj_no_root",
            job_name="Overview",
            from_objective="10x",
            to_objective="20x",
            calibration_path="ignored.json",
        )


def test_objective_pair_requires_explicit_calibration_path(monkeypatch):
    # The previous API allowed calibration_path=None and inferred
    # the package current calibration path. The new API has no implicit
    # fallback; omitting it must raise TypeError.
    with pytest.raises(TypeError):
        wf_obj.start_session(
            session_id="obj_no_i2s",
            job_name="Overview",
            from_objective="10x",
            to_objective="20x",
            sessions_root="ignored",
        )


def test_objective_pair_rejects_conflicting_calibration_selectors(monkeypatch):
    # The source file and adoption target must not be ambiguous.
    with pytest.raises(ValueError, match="either calibration_name or calibration_path"):
        wf_obj.start_session(
            session_id="obj_conflict",
            job_name="Overview",
            from_objective="10x",
            to_objective="20x",
            sessions_root="ignored",
            calibration_path="calibration.json",
            calibration_name="lens_A",
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
        from_objective="10x",
        to_objective="20x",
        sessions_root=sessions_root,
        calibration_name="lens_A",
    )

    assert session.calibration_name == "lens_A"
    assert (
        session.calibration_path
        == (snap / "calibrations" / "lens_A" / "calibration.json").absolute()
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
        from_objective="10x",
        to_objective="20x",
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
        from_objective="10x",
        to_objective="20x",
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


def test_objective_pair_xy_translation_arithmetic_identity(
    monkeypatch,
    sessions_root,
    machine,
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
        from_objective="10x",
        to_objective="20x",
        sessions_root=sessions_root,
        calibration_path=machine.calibration_path(),
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

    cfg_path = session.paths.configs_dir / session.objective_config_name
    assert cfg_path.is_file()
    payload = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert payload["kind"] == "objective_translation"
    assert payload["translation_xy_um"] == [12.0, 17.0]
    assert payload["translation_z_um"] == pytest.approx(3.0, abs=1e-6)


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
        from_objective="10x",
        to_objective="20x",
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
    assert not (session.paths.configs_dir / session.objective_config_name).exists()

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
        from_objective="10x",
        to_objective="20x",
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
        from_objective="10x",
        to_objective="20x",
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
    # Run 1: trusted vote -> staging config written.
    # Run 2 (same session): weak vote on the parcentricity step. The
    # stale staging config must be removed and adoption must raise.
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
        from_objective="10x",
        to_objective="20x",
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
    cfg = session.paths.configs_dir / session.objective_config_name
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
            session.objective_config_name,
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
        from_objective="10x",
        to_objective="20x",
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
    cfg = session.paths.configs_dir / session.objective_config_name
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
            session.objective_config_name,
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
    # 3b outputs and the staging config must clear.
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
            session.objective_config_name,
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
            session.objective_config_name,
            machine=machine,
        )


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
        from_objective="10x",
        to_objective="20x",
        sessions_root=sessions_root,
        calibration_path=machine.calibration_path(),
    )
    session = wf_obj.measure_parfocality_reference(session)

    state["stack_phase"] = "target"
    state["zwide"] = 94.0
    session = wf_obj.measure_parfocality_target(session)
    z_dir = session.paths.data_dir / "target_z_stack"
    first_run_files = sorted(p.name for p in z_dir.glob("*.tif"))
    assert len(first_run_files) == 21
    assert "z_020.tif" in first_run_files

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
    second_run_files = sorted(p.name for p in z_dir.glob("*.tif"))
    assert len(second_run_files) == 5
    for stale in ("z_005.tif", "z_010.tif", "z_020.tif"):
        assert stale not in second_run_files
    assert second_run_files == [
        "z_000.tif",
        "z_001.tif",
        "z_002.tif",
        "z_003.tif",
        "z_004.tif",
    ]


# ---------------------------------------------------------------------
# Exception-path stale-config invariants (Section 15 invariant on the
# partial-failure-during-rerun path)
# ---------------------------------------------------------------------


def test_objective_pair_rerun_3b_acquire_failure_removes_stale_config(
    monkeypatch,
    sessions_root,
    machine,
):
    """Full pipeline success writes the objective staging config. A 3b
    rerun raises mid-acquire. The stale config must be gone BEFORE the
    exception propagates.
    """
    home_xy = (1000.0, 2000.0)
    xy_post = (1010.0, 2020.0)
    boom = RuntimeError("acquire_frame failed")
    # Full run uses acquire_stack for the z-stacks; only ref_xy and
    # target_xy go through acquire_frame (indices 0 and 1). The
    # rerun's target_xy is index 2.
    state = _patch_objective_driver(
        monkeypatch,
        home_xy=home_xy,
        xy_post=xy_post,
        home_z=100.0,
        z_post=94.0,
        ref_focus_z=100.0,
        target_focus_z=103.0,
        acquire_side_effects=[None, None, boom],
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
        from_objective="10x",
        to_objective="20x",
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
    cfg = session.paths.configs_dir / session.objective_config_name
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
            session.objective_config_name,
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
    assert (data_dir / "ref_xy.tif").is_file()
    assert (data_dir / "target_xy.tif").is_file()
    target_z_dir = data_dir / "target_z_stack"
    assert target_z_dir.is_dir()
    assert any(target_z_dir.glob("*.tif"))

    state["stack_phase"] = "ref"
    session = wf_obj.measure_parfocality_reference(session)

    assert not (data_dir / "ref_xy.tif").exists()
    assert not (data_dir / "target_xy.tif").exists()
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
        from_objective="10x",
        to_objective="20x",
        sessions_root=sessions_root,
        calibration_path=machine.calibration_path(),
    )
    session = wf_obj.measure_parfocality_reference(session)

    # Ref stack landed on disk with one TIFF per slice.
    z_dir = session.paths.data_dir / "ref_z_stack"
    assert z_dir.is_dir()
    files = sorted(p.name for p in z_dir.glob("*.tif"))
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
        from_objective="10x",
        to_objective="20x",
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
        from_objective="10x",
        to_objective="20x",
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
        from_objective="10x",
        to_objective="20x",
        sessions_root=sessions_root,
        calibration_path=machine.calibration_path(),
    )
    session = wf_obj.measure_parfocality_reference(session)
    ref_dir = session.paths.data_dir / "ref_z_stack"
    first_run_files = sorted(p.name for p in ref_dir.glob("*.tif"))
    assert len(first_run_files) == 11
    assert "z_010.tif" in first_run_files

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

    second_run_files = sorted(p.name for p in ref_dir.glob("*.tif"))
    assert len(second_run_files) == 5
    for stale in ("z_005.tif", "z_010.tif"):
        assert stale not in second_run_files
    assert second_run_files == [
        "z_000.tif",
        "z_001.tif",
        "z_002.tif",
        "z_003.tif",
        "z_004.tif",
    ]


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
        from_objective="10x",
        to_objective="20x",
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
        from_objective="10x",
        to_objective="20x",
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
        from_objective="10x",
        to_objective="20x",
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
        from_objective="10x",
        to_objective="20x",
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
        from_objective="10x",
        to_objective="20x",
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
        from_objective="10x",
        to_objective="20x",
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
        from_objective="10x",
        to_objective="20x",
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
        from_objective="10x",
        to_objective="20x",
        sessions_root=sessions_root,
        calibration_path=machine.calibration_path(),
    )
    with pytest.raises(RuntimeError, match="stack edge"):
        wf_obj.measure_parfocality_reference(session)

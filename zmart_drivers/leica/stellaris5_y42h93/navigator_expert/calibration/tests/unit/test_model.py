import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]  # zmart_drivers/leica/stellaris5_y42h93


def _load_calibration_module():
    sys.path.insert(0, str(_repo_root()))
    import navigator_expert.calibration.core.model as calibration

    return calibration


def _config():
    return {
        "schema_version": 12,
        "last_updated": "20260527_120000",
        "objectives": {
            "1": {
                "name": "ref",
                "translation_um": [0.0, 0.0, 0.0],
                "session_id": None,
            },
            "2": {
                "name": "tgt",
                "translation_um": [-6.0, 13.0, -123.0],
                "session_id": "sess_target",
            },
        },
    }


def _semantically_equal(a: dict, b: dict) -> bool:
    a = {k: v for k, v in a.items() if k != "last_updated"}
    b = {k: v for k, v in b.items() if k != "last_updated"}
    return a == b


def test_get_translation_returned_as_stored():
    cal = _load_calibration_module()
    assert cal.get_translation_um(_config(), 1) == (0.0, 0.0, 0.0)
    assert cal.get_translation_um(_config(), 2) == (-6.0, 13.0, -123.0)


def test_reference_slot_derived_from_zero_translation():
    cal = _load_calibration_module()
    assert cal.get_reference_slot(_config()) == 1


def test_reference_slot_ignores_stale_stored_field():
    # The reference is derived from the [0,0,0] entry, not stored. A stale
    # reference_objective_slot on an older file is ignored, not honored.
    cal = _load_calibration_module()
    cfg = _config()
    cfg["reference_objective_slot"] = 2  # stale; slot 1 is actually [0,0,0]
    assert cal.get_reference_slot(cfg) == 1


def test_translate_xy_uses_translation_xy():
    cal = _load_calibration_module()
    cfg = _config()

    target_xy = cal.translate_xy_between_objectives(
        100.0,
        200.0,
        cfg,
        from_slot=1,
        to_slot=2,
    )
    assert target_xy == (94.0, 213.0)

    source_xy = cal.translate_xy_between_objectives(
        *target_xy,
        cfg,
        from_slot=2,
        to_slot=1,
    )
    assert source_xy == (100.0, 200.0)


def test_translate_z_uses_translation_z():
    cal = _load_calibration_module()
    cfg = _config()

    z_target = cal.translate_z_between_objectives(
        500.0,
        cfg,
        from_slot=1,
        to_slot=2,
    )
    assert z_target == 377.0

    z_back = cal.translate_z_between_objectives(
        z_target,
        cfg,
        from_slot=2,
        to_slot=1,
    )
    assert z_back == 500.0


def test_translate_xyz_combines_xy_and_z():
    cal = _load_calibration_module()
    x, y, z = cal.translate_xyz_between_objectives(
        100.0,
        200.0,
        500.0,
        _config(),
        from_slot=1,
        to_slot=2,
    )
    assert (x, y, z) == (94.0, 213.0, 377.0)


def test_set_reference_reorigins_all_translations():
    cal = _load_calibration_module()
    cfg = _config()
    cal.set_reference(cfg, 2)
    assert cal.get_reference_slot(cfg) == 2  # derived: slot 2 is now the origin
    assert cfg["objectives"]["2"]["translation_um"] == [0.0, 0.0, 0.0]
    assert cfg["objectives"]["1"]["translation_um"] == [6.0, -13.0, 123.0]


def test_translate_between_two_non_reference_objectives():
    # Translations are relative: any pair's difference is derivable from
    # measurements against a common objective (here slot 1 is the origin).
    cal = _load_calibration_module()
    cfg = {
        "schema_version": 12,
        "last_updated": "20260527_120000",
        "objectives": {
            "1": {"name": "a", "translation_um": [0.0, 0.0, 0.0], "session_id": None},
            "2": {"name": "b", "translation_um": [10.0, 20.0, 1.0], "session_id": None},
            "3": {"name": "c", "translation_um": [30.0, 5.0, -2.0], "session_id": None},
        },
    }
    # 2 -> 3 uses (t3 - t2) even though neither is the reference.
    x, y = cal.translate_xy_between_objectives(100.0, 200.0, cfg, from_slot=2, to_slot=3)
    assert (x, y) == (100.0 + 20.0, 200.0 + -15.0)


def test_adopt_seeds_first_used_objective_at_origin():
    # Fresh config (FROM objective has no translation yet): the first objective
    # used becomes the [0,0,0] origin; the pair's translation lands on TO.
    sys.path.insert(0, str(_repo_root()))
    from navigator_expert.calibration.core import adopt

    config = {
        "schema_version": 12,
        "objectives": {
            "1": {"name": "first", "session_id": None},  # no translation_um yet
            "2": {"name": "second", "session_id": None},
        },
    }
    payload = {
        "from_objective": "first",
        "to_objective": "second",
        "translation_xy_um": [4.0, -3.0],
        "translation_z_um": 2.0,
    }
    adopt._apply_staging_payload(config, payload, session_id="s0")
    assert config["objectives"]["1"]["translation_um"] == [0.0, 0.0, 0.0]
    assert config["objectives"]["2"]["translation_um"] == [4.0, -3.0, 2.0]


def test_missing_translation_raises_clearly():
    cal = _load_calibration_module()
    cfg = _config()
    cfg["objectives"]["2"].pop("translation_um")
    with pytest.raises(ValueError, match="translation_um"):
        cal.get_translation_um(cfg, 2)


def test_missing_slot_raises_clearly():
    cal = _load_calibration_module()
    with pytest.raises(ValueError, match="No calibration entry"):
        cal.get_translation_um(_config(), 9)


def test_update_objective_writes_only_passed_fields():
    cal = _load_calibration_module()
    cfg = {"objectives": {}}
    cal.update_objective(
        cfg,
        2,
        name="tgt",
        translation_um=(9.5, -8.5, 1.25),
    )
    assert cfg["objectives"]["2"] == {
        "name": "tgt",
        "translation_um": [9.5, -8.5, 1.25],
    }
    cal.update_objective(cfg, 2, session_id="sess")
    assert cfg["objectives"]["2"]["session_id"] == "sess"
    assert cfg["objectives"]["2"]["name"] == "tgt"


def test_update_objective_requires_name_for_new_slot():
    cal = _load_calibration_module()
    with pytest.raises(ValueError, match="without a name"):
        cal.update_objective({"objectives": {}}, 2, session_id="sess")


def test_old_schema_raises_pointing_at_recalibration(tmp_path):
    cal = _load_calibration_module()
    path = tmp_path / "calibration.json"
    path.write_text(
        json.dumps({"schema_version": 9, "objectives": {}}),
        encoding="utf-8",
    )
    with pytest.raises(cal.OldSchemaError, match="Re-run the calibration notebooks"):
        cal.load_calibration(path)


def test_validate_calibration_does_not_mutate():
    cal = _load_calibration_module()
    cfg = _config()
    before = json.loads(json.dumps(cfg))
    cal.validate_calibration(cfg)
    assert cfg == before


def test_calibration_has_no_backlash_field(tmp_path):
    """§2b: backlash is a motion utility, not calibration state. The bundled
    default calibration.json carries no backlash block."""
    cal = _load_calibration_module()
    bundled = _repo_root() / "navigator_expert" / "calibration" / "defaults" / "calibration.json"
    assert "backlash" not in json.loads(bundled.read_text(encoding="utf-8"))
    cal.validate_calibration(_config())  # a config without backlash validates


def test_stray_backlash_block_is_tolerated(tmp_path):
    """Backward compat (§2b): an older machine-local calibration.json may still
    carry a backlash block. The model IGNORES it — it neither requires nor
    validates it — so the file keeps loading without a re-adopt."""
    cal = _load_calibration_module()
    cfg = _config()
    # A stray block, deliberately malformed — must NOT be validated.
    cfg["backlash"] = {"overshoot_um": "not-a-number", "junk": True}
    cal.validate_calibration(cfg)  # tolerated, no raise
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    loaded = cal.load_calibration(path)
    assert loaded["objectives"]["1"]["translation_um"] == [0.0, 0.0, 0.0]


def test_save_load_semantic_round_trip(tmp_path):
    cal = _load_calibration_module()
    path = tmp_path / "calibration.json"
    cfg = _config()
    cal.save_calibration(cfg, path=path)
    loaded = cal.load_calibration(path)
    cal.save_calibration(loaded, path=path)
    loaded_again = cal.load_calibration(path)
    assert _semantically_equal(loaded, loaded_again)


def test_save_without_path_seeds_programdata_not_bundled_defaults(tmp_path, monkeypatch):
    cal = _load_calibration_module()
    from navigator_expert.config import machine as machine_config

    profile = machine_config.MachineProfile(programdata_root=tmp_path / "programdata")
    monkeypatch.setattr(machine_config, "MACHINE", profile)
    bundled = profile.bundled_default_path("calibration.json")
    before = bundled.read_text(encoding="utf-8")

    path = cal.save_calibration(_config(), calibration_name="lens_A")

    assert path == (
        profile.latest_snapshot("calibration") / "calibrations" / "lens_A" / "calibration.json"
    )
    assert path.exists()
    assert bundled.read_text(encoding="utf-8") == before


def test_save_named_calibration_writes_existing_machine_local_path(tmp_path, monkeypatch):
    cal = _load_calibration_module()
    from navigator_expert.config import machine as machine_config

    profile = machine_config.MachineProfile(programdata_root=tmp_path / "programdata")
    monkeypatch.setattr(machine_config, "MACHINE", profile)
    snap = profile.publish_snapshot(
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        calibration=_config(),
        calibration_name="lens_A",
    )

    path = cal.save_calibration(_config(), calibration_name="lens_A")

    assert path == snap / "calibrations" / "lens_A" / "calibration.json"
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 12

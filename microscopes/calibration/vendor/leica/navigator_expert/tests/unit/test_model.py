import json
import sys
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[6]


def _load_calibration_module():
    sys.path.insert(0, str(_repo_root()))
    import calibration.vendor.leica.navigator_expert.core.model as calibration

    return calibration


def _config():
    return {
        "schema_version": 11,
        "last_updated": "20260527_120000",
        "reference_objective_slot": 1,
        "image_to_stage": {
            "matrix": [[0.0, -1.0], [1.0, 0.0]],
            "session_id": None,
        },
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
        "backlash": {
            "approach": "+X+Y",
            "overshoot_um": 50.0,
            "settle_ms": 100,
            "tolerance_um": 20.0,
            "session_id": None,
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


def test_reference_slot_mismatch_raises():
    cal = _load_calibration_module()
    cfg = _config()
    cfg["reference_objective_slot"] = 2
    with pytest.raises(ValueError, match="disagrees"):
        cal.get_reference_slot(cfg)


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
    assert cfg["reference_objective_slot"] == 2
    assert cfg["objectives"]["2"]["translation_um"] == [0.0, 0.0, 0.0]
    assert cfg["objectives"]["1"]["translation_um"] == [6.0, -13.0, 123.0]


def test_pixel_to_stage_uses_image_to_stage_matrix():
    cal = _load_calibration_module()
    xy = cal.pixel_to_stage_xy_um(
        60,
        40,
        stage_xy_um=(100.0, 200.0),
        pixel_size_um=1.0,
        image_size=100,
        config=_config(),
    )
    assert xy == (110.0, 210.0)


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


def test_set_image_to_stage_coerces_to_v11_block():
    cal = _load_calibration_module()
    cfg = {}
    cal.set_image_to_stage(cfg, [[0, -1], [1, 0]], session_id="sess_i2s")
    assert cfg["image_to_stage"] == {
        "matrix": [[0.0, -1.0], [1.0, 0.0]],
        "session_id": "sess_i2s",
    }


def test_old_schema_raises_with_migration_command(tmp_path):
    cal = _load_calibration_module()
    path = tmp_path / "calibration.json"
    path.write_text(
        json.dumps({"schema_version": 9, "objectives": {}}),
        encoding="utf-8",
    )
    with pytest.raises(cal.OldSchemaError, match="migrate_current_calibration"):
        cal.load_calibration(path)


def test_validate_calibration_does_not_mutate():
    cal = _load_calibration_module()
    cfg = _config()
    before = json.loads(json.dumps(cfg))
    cal.validate_calibration(cfg)
    assert cfg == before


def test_save_load_semantic_round_trip(tmp_path):
    cal = _load_calibration_module()
    path = tmp_path / "calibration.json"
    cfg = _config()
    cal.save_calibration(cfg, path=path)
    loaded = cal.load_calibration(path)
    cal.save_calibration(loaded, path=path)
    loaded_again = cal.load_calibration(path)
    assert _semantically_equal(loaded, loaded_again)

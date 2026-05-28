import json
import shutil
import sys
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[6]


def _load_migration_module():
    sys.path.insert(0, str(_repo_root()))
    import calibration.vendor.leica.navigator_expert.migrate_current_calibration as migration
    return migration


def _copy_current_v9(tmp_path: Path) -> Path:
    current = (
        _repo_root()
        / "calibration"
        / "vendor"
        / "leica"
        / "navigator_expert"
        / "current"
    )
    dst = tmp_path / "current"
    dst.mkdir()
    shutil.copy2(current / "calibration.json", dst / "calibration.json")
    stage = current / "stage.json"
    if stage.exists():
        shutil.copy2(stage, dst / "stage.json")
    else:
        # The repository may already be migrated. Reconstruct the old
        # stage fixture from limits/backlash so the migration test still
        # pins the conversion function.
        calibration = json.loads((current / "calibration.json").read_text())
        limits = json.loads(
            (
                _repo_root()
                / "limits"
                / "vendor"
                / "leica"
                / "navigator_expert"
                / "current.json"
            ).read_text()
        )
        (dst / "stage.json").write_text(
            json.dumps({
                "schema_version": 1,
                "limits_um": limits["stage_um"],
                "backlash": {
                    k: v for k, v in calibration["backlash"].items()
                    if k != "session_id"
                },
            }),
            encoding="utf-8",
        )
        # Convert repo v11 back to the v9 fixture values pinned below.
        # This path only runs after the migration has landed; the exact
        # v9 source is not recoverable from v11 for XY offset diagnostics.
        (dst / "calibration.json").write_text(
            json.dumps(_source_v9_fixture(), indent=2),
            encoding="utf-8",
        )
    return dst


def _limits_path(tmp_path: Path) -> Path:
    return tmp_path / "limits" / "vendor" / "leica" / "navigator_expert" / "current.json"


def _source_v9_fixture() -> dict:
    return {
        "schema_version": 9,
        "last_updated": "20260521_175949",
        "reference_objective_slot": 1,
        "image_to_stage": [[0.0, -1.0], [1.0, 0.0]],
        "objectives": {
            "0": {
                "name": "HC PL APO CS2    40x/1.10 WATER",
                "offset_xy_um": [-13.940429687503638, 11.4306640625],
                "offset_z_um": -7.430000000000291,
                "shift_xy_um": [-19.69708, 32.9913604275696],
                "shift_z_um": 10.175871798653134,
            },
            "1": {
                "name": "HC PL APO CS2    10x/0.40 DRY",
                "offset_xy_um": [0.0, 0.0],
                "offset_z_um": 0.0,
                "shift_xy_um": [0.0, 0.0],
                "shift_z_um": 0.0,
            },
            "2": {
                "name": "HC PL APO CS2    20x/0.75 DRY",
                "offset_xy_um": [-7.021484375, 21.07421875],
                "offset_z_um": -6.109999999999673,
                "shift_xy_um": [-6.458369500000001, 21.53989335],
                "shift_z_um": 2.401066210072713,
            },
        },
    }


def test_build_v11_calibration_pins_translation_triples():
    migration = _load_migration_module()
    stage = {
        "schema_version": 1,
        "limits_um": {
            "x": [1000, 130000],
            "y": [1000, 100000],
            "z_galvo": [-200, 200],
            "z_wide": [0, 25000],
        },
        "backlash": {
            "approach": "+X+Y",
            "overshoot_um": 50,
            "settle_ms": 100,
            "tolerance_um": 20,
        },
    }
    migrated = migration.build_v11_calibration(
        _source_v9_fixture(), stage, timestamp="20260527_120000",
    )

    assert migrated["schema_version"] == 11
    assert migrated["reference_objective_slot"] == 1
    assert migrated["objectives"]["0"]["translation_um"] == [
        -19.69708,
        32.9913604275696,
        2.7458717986528427,
    ]
    assert migrated["objectives"]["1"]["translation_um"] == [0.0, 0.0, 0.0]
    assert migrated["objectives"]["2"]["translation_um"] == [
        -6.458369500000001,
        21.53989335,
        -3.7089337899269594,
    ]
    assert migrated["image_to_stage"] == {
        "matrix": [[0.0, -1.0], [1.0, 0.0]],
        "session_id": None,
    }
    assert migrated["backlash"]["session_id"] is None


def test_migrate_writes_v11_limits_and_removes_stage_json(tmp_path):
    migration = _load_migration_module()
    root = _copy_current_v9(tmp_path)
    limits_path = _limits_path(tmp_path)

    result = migration.migrate(root, limits_path=limits_path)

    assert "Migrated to v11" in result["status"]
    assert not (root / "stage.json").exists()
    calibration = json.loads((root / "calibration.json").read_text())
    limits = json.loads(limits_path.read_text())
    assert calibration["schema_version"] == 11
    assert limits == {
        "schema_version": 1,
        "stage_um": {
            "x": [1000, 130000],
            "y": [1000, 100000],
            "z_galvo": [-200, 200],
            "z_wide": [0, 25000],
        },
    }

    second = migration.migrate(root, limits_path=limits_path)
    assert second["status"] == "already current"


def test_migrate_recovers_v11_calibration_missing_limits(tmp_path):
    migration = _load_migration_module()
    root = _copy_current_v9(tmp_path)
    limits_path = _limits_path(tmp_path)

    calibration = migration.build_v11_calibration(
        _source_v9_fixture(),
        json.loads((root / "stage.json").read_text()),
        timestamp="20260527_120000",
    )
    (root / "calibration.json").write_text(
        json.dumps(calibration, indent=2),
        encoding="utf-8",
    )

    result = migration.migrate(root, limits_path=limits_path)

    assert "Recovered v11 calibration" in result["status"]
    assert not (root / "stage.json").exists()
    limits = json.loads(limits_path.read_text())
    assert limits["schema_version"] == 1
    assert "stage_um" in limits


def test_migrate_v11_missing_limits_without_stage_is_clear(tmp_path):
    migration = _load_migration_module()
    root = _copy_current_v9(tmp_path)
    limits_path = _limits_path(tmp_path)

    calibration = migration.build_v11_calibration(
        _source_v9_fixture(),
        json.loads((root / "stage.json").read_text()),
        timestamp="20260527_120000",
    )
    (root / "calibration.json").write_text(
        json.dumps(calibration, indent=2),
        encoding="utf-8",
    )
    (root / "stage.json").unlink()

    with pytest.raises(FileNotFoundError, match="current limits are missing"):
        migration.migrate(root, limits_path=limits_path)

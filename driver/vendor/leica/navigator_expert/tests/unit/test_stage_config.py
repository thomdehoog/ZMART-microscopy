"""Unit tests for the split stage safety/backlash loader."""

import json
from pathlib import Path

import pytest

import navigator_expert.stage.config as stage_config


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_load_combines_limits_and_calibrated_backlash(tmp_path):
    limits = tmp_path / "limits.json"
    calibration = tmp_path / "calibration.json"
    _write_json(
        limits,
        {
            "schema_version": 1,
            "source": "defaults",
            "stage_um": {
                "x": [1, 2],
                "y": [3, 4],
                "z_galvo": [-5, 5],
                "z_wide": [0, 100],
            },
        },
    )
    _write_json(
        calibration,
        {
            "schema_version": 11,
            "backlash": {
                "approach": "+X+Y",
                "overshoot_um": 50,
                "settle_ms": 100,
                "tolerance_um": 20,
                "session_id": "session-1",
            },
        },
    )

    cfg = stage_config.load(limits_path=limits, calibration_path=calibration)

    assert cfg == {
        "stage_um": {
            "x": [1.0, 2.0],
            "y": [3.0, 4.0],
            "z_galvo": [-5.0, 5.0],
            "z_wide": [0.0, 100.0],
        },
        "backlash": {
            "approach": "+X+Y",
            "overshoot_um": 50.0,
            "settle_ms": 100,
            "tolerance_um": 20.0,
            "session_id": "session-1",
        },
    }


def test_limits_paths_are_separate_from_calibration_state():
    repo_root = Path(__file__).resolve().parents[6]
    current_limits = (
        repo_root
        / "limits"
        / "vendor"
        / "leica"
        / "navigator_expert"
        / "current.json"
    )
    default_limits = current_limits.with_name("defaults.json")
    calibration = (
        repo_root
        / "calibration"
        / "vendor"
        / "leica"
        / "navigator_expert"
        / "current"
        / "calibration.json"
    )

    assert stage_config.current_path() == current_limits
    assert stage_config.defaults_path() == default_limits
    assert stage_config.default_calibration_path() == calibration
    assert current_limits.exists()
    assert default_limits.exists()
    assert calibration.exists()
    assert json.loads(default_limits.read_text(encoding="utf-8"))[
        "schema_version"
    ] == 1
    assert json.loads(default_limits.read_text(encoding="utf-8"))[
        "source"
    ] == "defaults"


def test_load_defaults_to_defaults_path(tmp_path, monkeypatch):
    defaults = tmp_path / "defaults.json"
    current = tmp_path / "current.json"
    calibration = tmp_path / "calibration.json"
    _write_json(
        defaults,
        {
            "schema_version": 1,
            "source": "defaults",
            "stage_um": {
                "x": [1, 2],
                "y": [3, 4],
                "z_galvo": [-5, 5],
                "z_wide": [0, 100],
            },
        },
    )
    _write_json(
        current,
        {
            "schema_version": 1,
            "source": "boundary_markers",
            "stage_um": {
                "x": [10, 20],
                "y": [30, 40],
                "z_galvo": [-50, 50],
                "z_wide": [0, 200],
            },
        },
    )
    _write_json(
        calibration,
        {
            "schema_version": 11,
            "backlash": {
                "approach": "+X+Y",
                "overshoot_um": 50,
                "settle_ms": 100,
                "tolerance_um": 20,
                "session_id": "session-1",
            },
        },
    )
    monkeypatch.setattr(stage_config, "defaults_path", lambda: defaults)
    monkeypatch.setattr(stage_config, "current_path", lambda: current)
    monkeypatch.setattr(
        stage_config,
        "default_calibration_path",
        lambda: calibration,
    )

    cfg = stage_config.load()

    assert cfg["stage_um"]["x"] == [1.0, 2.0]
    assert cfg["stage_um"]["y"] == [3.0, 4.0]


def test_load_requires_limits_schema_name(tmp_path):
    legacy_shaped_limits = tmp_path / "limits.json"
    calibration = tmp_path / "calibration.json"
    _write_json(
        legacy_shaped_limits,
        {
            "schema_version": 1,
            "source": "defaults",
            "limits_um": {
                "x": [1000, 130000],
                "y": [1000, 100000],
                "z_galvo": [-200, 200],
                "z_wide": [0, 25000],
            },
        },
    )
    _write_json(
        calibration,
        {
            "schema_version": 11,
            "backlash": {
                "approach": "+X+Y",
                "overshoot_um": 50,
                "settle_ms": 100,
                "tolerance_um": 20,
                "session_id": "session-1",
            },
        },
    )

    with pytest.raises(ValueError, match="stage_um"):
        stage_config.load(
            limits_path=legacy_shaped_limits,
            calibration_path=calibration,
        )


def test_load_requires_limits_source(tmp_path):
    limits = tmp_path / "limits.json"
    calibration = tmp_path / "calibration.json"
    _write_json(
        limits,
        {
            "schema_version": 1,
            "stage_um": {
                "x": [1, 2],
                "y": [3, 4],
                "z_galvo": [-5, 5],
                "z_wide": [0, 100],
            },
        },
    )
    _write_json(
        calibration,
        {
            "schema_version": 11,
            "backlash": {
                "approach": "+X+Y",
                "overshoot_um": 50,
                "settle_ms": 100,
                "tolerance_um": 20,
                "session_id": "session-1",
            },
        },
    )

    with pytest.raises(ValueError, match="source"):
        stage_config.load(limits_path=limits, calibration_path=calibration)


def test_write_limits_validates_and_writes_current_shape(tmp_path):
    path = tmp_path / "current.json"

    written = stage_config.write_limits(
        {
            "x": [10, 20],
            "y": [30, 40],
            "z_galvo": [-2, 2],
            "z_wide": [0, 100],
        },
        source="cfg_fallback",
        path=path,
    )

    assert written == path
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "source": "cfg_fallback",
        "stage_um": {
            "x": [10.0, 20.0],
            "y": [30.0, 40.0],
            "z_galvo": [-2.0, 2.0],
            "z_wide": [0.0, 100.0],
        },
    }


def test_write_limits_requires_source(tmp_path):
    path = tmp_path / "current.json"

    with pytest.raises(ValueError, match="source"):
        stage_config.write_limits(
            {
                "x": [10, 20],
                "y": [30, 40],
                "z_galvo": [-2, 2],
                "z_wide": [0, 100],
            },
            source="",
            path=path,
        )


def test_load_requires_complete_backlash_block(tmp_path):
    limits = tmp_path / "limits.json"
    calibration = tmp_path / "calibration.json"
    _write_json(
        limits,
        {
            "schema_version": 1,
            "source": "defaults",
            "stage_um": {
                "x": [1, 2],
                "y": [3, 4],
                "z_galvo": [-5, 5],
                "z_wide": [0, 100],
            },
        },
    )
    _write_json(
        calibration,
        {
            "schema_version": 11,
            "backlash": {
                "overshoot_um": 50,
                "settle_ms": 100,
                "tolerance_um": 20,
            },
        },
    )

    with pytest.raises(ValueError, match="backlash missing field"):
        stage_config.load(limits_path=limits, calibration_path=calibration)

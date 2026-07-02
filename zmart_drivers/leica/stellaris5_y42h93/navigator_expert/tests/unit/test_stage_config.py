"""Unit tests for the split stage safety/backlash loader."""

import json
from datetime import datetime, timezone
from pathlib import Path

import navigator_expert.motion.stage_config as stage_config
import pytest
from navigator_expert.config.machine import MachineProfile


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


# --- adopt_limits: publish a physical-envelope snapshot ---

_ENV_A = {"x": [1, 100], "y": [1, 100], "z_galvo": [-5, 5], "z_wide": [0, 50]}
_ENV_B = {"x": [2, 200], "y": [2, 200], "z_galvo": [-10, 10], "z_wide": [0, 60]}
_SEED_MOMENT = datetime(2026, 1, 1, tzinfo=timezone.utc)
_ADOPT_MOMENT = datetime(2026, 2, 1, tzinfo=timezone.utc)


def test_adopt_limits_publishes_snapshot_carrying_calibration_forward(tmp_path):
    m = MachineProfile(programdata_root=tmp_path)
    m.publish_snapshot(
        _SEED_MOMENT,
        calibration={"marker": "cal-A"},
        limits={"schema_version": 1, "source": "defaults", "stage_um": _ENV_A},
    )
    out = stage_config.adopt_limits(_ENV_B, machine=m, moment=_ADOPT_MOMENT)
    snap = m.latest_snapshot()
    assert Path(out["snapshot"]) == snap
    lim = json.loads((snap / "limits.json").read_text(encoding="utf-8"))
    assert lim["schema_version"] == 1
    assert lim["stage_um"]["x"] == [2.0, 200.0]  # validated to floats
    # calibration carried forward untouched
    assert json.loads((snap / "calibration.json").read_text(encoding="utf-8")) == {
        "marker": "cal-A"
    }


def test_adopt_limits_first_time_carries_bundled_calibration(tmp_path):
    from navigator_expert.calibration.core import model

    m = MachineProfile(programdata_root=tmp_path)
    assert m.latest_snapshot() is None
    stage_config.adopt_limits(_ENV_B, machine=m, moment=_ADOPT_MOMENT)
    snap = m.latest_snapshot()
    cal = model.load_calibration(snap / "calibration.json")  # bundled default carried in
    assert model.get_reference_slot(cal) == 1
    lim = json.loads((snap / "limits.json").read_text(encoding="utf-8"))
    assert lim["stage_um"]["z_wide"] == [0.0, 60.0]


def test_adopt_limits_validates_envelope(tmp_path):
    m = MachineProfile(programdata_root=tmp_path)
    bad = {"x": [100, 1], "y": [1, 100], "z_galvo": [-5, 5], "z_wide": [0, 50]}  # min > max
    with pytest.raises(ValueError):
        stage_config.adopt_limits(bad, machine=m, moment=_ADOPT_MOMENT)


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
    # With no machine snapshot (hermetic root fixture), the physical limits and
    # the calibration resolve to the driver-bundled defaults, while the per-run
    # working envelope stays under the driver tree - three distinct files.
    driver_root = Path(__file__).resolve().parents[2]
    current_limits = driver_root / "limits" / "current.json"
    default_limits = driver_root / "defaults" / "limits.json"
    calibration = driver_root / "defaults" / "calibration.json"

    assert stage_config.current_path() == current_limits
    assert stage_config.defaults_path() == default_limits
    assert stage_config.default_calibration_path() == calibration
    assert current_limits.exists()
    assert default_limits.exists()
    assert calibration.exists()
    assert json.loads(default_limits.read_text(encoding="utf-8"))["schema_version"] == 1
    assert json.loads(default_limits.read_text(encoding="utf-8"))["source"] == "defaults"


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

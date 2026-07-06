"""Unit tests for the single limits.json loader (§7b).

The one ``limits.json`` holds ``constraints`` (the stage envelope) +
``functions`` (the gate policy). ``stage_config`` reads the envelope from
``constraints.stage.*``. There is no ``backlash`` block: backlash is a plain
motion utility with baked-in defaults (decision §2b), not config; a stray
``backlash`` key left in an older file is ignored, not rejected.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import navigator_expert.motion.stage_config as stage_config
import pytest
from limits_fixtures import merged_limits_payload
from navigator_expert.config.machine import MachineProfile


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


# --- adopt_limits: publish a merged-limits snapshot ---

# Envelopes must sit WITHIN the hardcoded physical backstop
# (motion.limits.STAGE_BACKSTOP_UM) or adopt_limits refuses them.
_ENV_A = {"x": [1100, 100000], "y": [1100, 90000], "z_galvo": [-5, 5], "z_wide": [0, 50]}
_ENV_B = {"x": [1200, 120000], "y": [1200, 95000], "z_galvo": [-10, 10], "z_wide": [0, 60]}
_SEED_MOMENT = datetime(2026, 1, 1, tzinfo=timezone.utc)
_ADOPT_MOMENT = datetime(2026, 2, 1, tzinfo=timezone.utc)


def test_adopt_limits_publishes_single_file_carrying_calibration(tmp_path):
    m = MachineProfile(programdata_root=tmp_path)
    m.publish_snapshot(
        _SEED_MOMENT,
        calibration={"marker": "cal-A"},
        limits=merged_limits_payload(_ENV_A),
    )
    out = stage_config.adopt_limits(_ENV_B, machine=m, moment=_ADOPT_MOMENT)
    snap = m.latest_snapshot()
    assert Path(out["snapshot"]) == snap
    assert "function_limits_path" not in out  # single file only

    lim = json.loads((snap / "limits.json").read_text(encoding="utf-8"))
    assert lim["schema_version"] == 1
    # §2b: the published limits.json has NO backlash block. Its top-level keys
    # are exactly the envelope + gate.
    assert set(lim) == {"schema_version", "source", "constraints", "functions"}
    # envelope stated by name under constraints (validated to floats)
    assert lim["constraints"]["stage.x"] == {"min": 1200.0, "max": 120000.0}
    assert lim["functions"]["set_xyz"]["x_um"] == "@stage.x"
    # a REAL prior calibration carried forward untouched
    assert json.loads((snap / "calibration.json").read_text(encoding="utf-8")) == {
        "marker": "cal-A"
    }
    # no function_limits.json anywhere
    assert not (snap / "function_limits.json").exists()


def test_adopt_limits_first_time_writes_only_limits_no_seeded_calibration(tmp_path):
    m = MachineProfile(programdata_root=tmp_path)
    assert m.latest_snapshot() is None
    stage_config.adopt_limits(_ENV_B, machine=m, moment=_ADOPT_MOMENT)
    snap = m.latest_snapshot()
    files = sorted(p.name for p in snap.iterdir())
    assert files == ["limits.json"]  # §7b: no bundled calibration minted
    lim = json.loads((snap / "limits.json").read_text(encoding="utf-8"))
    assert lim["constraints"]["stage.z_wide"] == {"min": 0.0, "max": 60.0}
    # §2b: no backlash block is ever written
    assert "backlash" not in lim


def test_adopt_limits_validates_envelope(tmp_path):
    m = MachineProfile(programdata_root=tmp_path)
    bad = dict(_ENV_A, x=[100000, 1100])  # min > max
    with pytest.raises(ValueError):
        stage_config.adopt_limits(bad, machine=m, moment=_ADOPT_MOMENT)


def test_adopt_limits_refuses_an_envelope_outside_the_backstop(tmp_path):
    m = MachineProfile(programdata_root=tmp_path)
    wide = dict(_ENV_A, x=[500, 200000])  # wider than the physical travel
    with pytest.raises(RuntimeError, match="backstop"):
        stage_config.adopt_limits(wide, machine=m, moment=_ADOPT_MOMENT)
    assert m.latest_snapshot() is None  # nothing published


# --- load: envelope from constraints (no backlash) ---


def test_load_reads_envelope_from_constraints(tmp_path):
    limits = tmp_path / "limits.json"
    payload = merged_limits_payload(
        {"x": [1, 2], "y": [3, 4], "z_galvo": [-5, 5], "z_wide": [0, 100]}
    )
    _write_json(limits, payload)

    cfg = stage_config.load(limits_path=limits)

    assert cfg == {
        "stage_um": {
            "x": [1.0, 2.0],
            "y": [3.0, 4.0],
            "z_galvo": [-5.0, 5.0],
            "z_wide": [0.0, 100.0],
        },
    }


def test_load_ignores_a_stray_backlash_block(tmp_path):
    # Backward compat (§2b): an older machine-local limits.json may still carry
    # a backlash block. It is tolerated (ignored), never validated or returned.
    limits = tmp_path / "limits.json"
    payload = merged_limits_payload(
        {"x": [1, 2], "y": [3, 4], "z_galvo": [-5, 5], "z_wide": [0, 100]}
    )
    payload["backlash"] = {"anything": "not validated", "overshoot_um": "not-a-number"}
    _write_json(limits, payload)

    cfg = stage_config.load(limits_path=limits)

    assert set(cfg) == {"stage_um"}
    assert cfg["stage_um"]["x"] == [1.0, 2.0]


def test_limits_paths_are_separate_from_calibration_state():
    # With no machine snapshot (hermetic root fixture): the physical limits
    # REFUSE the bundled template (no-fallback rule), and the per-run working
    # envelope path stays under the driver tree (its file is untracked/per-run,
    # so only the path is asserted here).
    driver_root = Path(__file__).resolve().parents[2]
    current_limits = driver_root / "limits" / "current.json"
    template_limits = driver_root / "limits" / "defaults" / "limits.json"

    assert stage_config.current_path() == current_limits
    with pytest.raises(RuntimeError, match="set_stage_limits.ipynb"):
        stage_config.defaults_path()
    # The bundled template stays shipped (it seeds the notebook), but is
    # never returned as the enforceable envelope.
    assert template_limits.exists()
    template = json.loads(template_limits.read_text(encoding="utf-8"))
    assert template["schema_version"] == 1
    assert template["source"] == "defaults"
    # §2b: the template has no backlash block — envelope + gate only.
    assert set(template) == {"schema_version", "source", "constraints", "functions"}


def test_defaults_path_returns_the_machine_local_snapshot_copy(tmp_path, monkeypatch):
    import navigator_expert.config.machine as machine_mod

    monkeypatch.setenv("ZMART_MICROSCOPY_ROOT", str(tmp_path))
    m = machine_mod.MachineProfile()
    m.publish_snapshot(_SEED_MOMENT, limits=merged_limits_payload(_ENV_A))
    assert stage_config.defaults_path() == m.latest_snapshot() / "limits.json"


def test_load_defaults_to_defaults_path(tmp_path, monkeypatch):
    defaults = tmp_path / "defaults.json"
    _write_json(
        defaults,
        merged_limits_payload({"x": [1, 2], "y": [3, 4], "z_galvo": [-5, 5], "z_wide": [0, 100]}),
    )
    monkeypatch.setattr(stage_config, "defaults_path", lambda: defaults)

    cfg = stage_config.load()

    assert cfg["stage_um"]["x"] == [1.0, 2.0]
    assert cfg["stage_um"]["y"] == [3.0, 4.0]


def test_load_requires_constraints_section(tmp_path):
    limits = tmp_path / "limits.json"
    _write_json(limits, {"schema_version": 1, "source": "defaults", "functions": {}})
    with pytest.raises(ValueError, match="constraints"):
        stage_config.load(limits_path=limits)


def test_load_requires_source(tmp_path):
    limits = tmp_path / "limits.json"
    payload = merged_limits_payload(
        {"x": [1, 2], "y": [3, 4], "z_galvo": [-5, 5], "z_wide": [0, 100]}
    )
    del payload["source"]
    _write_json(limits, payload)
    with pytest.raises(ValueError, match="source"):
        stage_config.load(limits_path=limits)


# --- write_limits: the legacy per-run working envelope (flat stage_um) ---


def test_write_limits_validates_and_writes_current_shape(tmp_path):
    path = tmp_path / "current.json"

    written = stage_config.write_limits(
        {"x": [10, 20], "y": [30, 40], "z_galvo": [-2, 2], "z_wide": [0, 100]},
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
            {"x": [10, 20], "y": [30, 40], "z_galvo": [-2, 2], "z_wide": [0, 100]},
            source="",
            path=path,
        )

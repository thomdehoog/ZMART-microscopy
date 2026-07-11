"""Unit tests for the flat, operator-readable limits.json loader."""

import ast
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
    assert set(lim) == set(stage_config._REQUIRED_FILE_KEYS)
    assert lim["x_um"] == {"range": [1200.0, 120000.0]}
    assert lim["objective_slot"] == {"allowed": [1, 2, 3, 4, 5, 6]}
    assert all(lim[name] == [] for name in stage_config.SETTER_LIMIT_KEYS)
    # a REAL prior calibration carried forward untouched
    assert json.loads((snap / "calibration.json").read_text(encoding="utf-8")) == {
        "marker": "cal-A"
    }
    # no function_limits.json anywhere
    assert not (snap / "function_limits.json").exists()


def test_adopt_limits_first_time_writes_complete_snapshot(tmp_path):
    m = MachineProfile(programdata_root=tmp_path)
    assert m.latest_snapshot() is None
    stage_config.adopt_limits(_ENV_B, machine=m, moment=_ADOPT_MOMENT)
    snap = m.latest_snapshot()
    files = sorted(p.name for p in snap.iterdir())
    assert files == [".limits-machine", "calibration.json", "limits.json", "orientation.json"]
    lim = json.loads((snap / "limits.json").read_text(encoding="utf-8"))
    assert lim["z_wide_um"] == {"range": [0.0, 60.0]}
    # §2b: no backlash block is ever written
    assert "backlash" not in lim


def test_limits_machine_marker_survives_later_snapshot_adoptions(tmp_path):
    m = MachineProfile(programdata_root=tmp_path)
    stage_config.adopt_limits(_ENV_B, machine=m, moment=_SEED_MOMENT)
    first = m.latest_snapshot()
    assert (first / ".limits-machine").exists()

    later = m.publish_snapshot(_ADOPT_MOMENT, calibration={"marker": "new calibration"})
    assert (later / ".limits-machine").exists()
    assert json.loads((later / "limits.json").read_text(encoding="utf-8"))["x_um"] == {
        "range": [1200.0, 120000.0]
    }


def test_adopt_limits_validates_envelope(tmp_path):
    m = MachineProfile(programdata_root=tmp_path)
    bad = dict(_ENV_A, x=[100000, 1100])  # min > max
    with pytest.raises(ValueError):
        stage_config.adopt_limits(bad, machine=m, moment=_ADOPT_MOMENT)


@pytest.mark.parametrize("bad_bounds", [[False, True], ["1100", "100000"]])
def test_adopt_limits_rejects_coerced_legacy_bounds(tmp_path, bad_bounds):
    m = MachineProfile(programdata_root=tmp_path)
    with pytest.raises(ValueError, match="must contain numbers"):
        stage_config.adopt_limits(dict(_ENV_A, x=bad_bounds), machine=m, moment=_ADOPT_MOMENT)
    assert m.latest_snapshot() is None


@pytest.mark.parametrize("bad_value", [None, (1, 2)])
def test_typed_allowed_rejects_non_json_or_null_values(bad_value):
    payload = merged_limits_payload(_ENV_A)
    payload["set_zoom"] = {"allowed": [bad_value]}
    with pytest.raises(ValueError, match="JSON booleans, numbers, or strings"):
        stage_config.validate_payload(payload)


def test_adopt_limits_refuses_an_envelope_outside_the_backstop(tmp_path):
    m = MachineProfile(programdata_root=tmp_path)
    wide = dict(_ENV_A, x=[500, 200000])  # wider than the physical travel
    with pytest.raises(RuntimeError, match="backstop"):
        stage_config.adopt_limits(wide, machine=m, moment=_ADOPT_MOMENT)
    assert m.latest_snapshot() is None  # nothing published


# --- load: flat envelope and policy ---


def test_load_reads_envelope_from_constraints(tmp_path):
    limits = tmp_path / "limits.json"
    payload = merged_limits_payload(
        {"x": [1, 2], "y": [3, 4], "z_galvo": [-5, 5], "z_wide": [0, 100]}
    )
    _write_json(limits, payload)

    cfg = stage_config.load(limits_path=limits)

    assert cfg["stage_um"] == {
        "x": [1.0, 2.0],
        "y": [3.0, 4.0],
        "z_galvo": [-5.0, 5.0],
        "z_wide": [0.0, 100.0],
    }
    assert cfg["policy"]["objective_slot"] == {"allowed": [1, 2, 3, 4, 5, 6]}
    assert all(cfg["policy"][name] == [] for name in stage_config.SETTER_LIMIT_KEYS)


def test_load_rejects_a_stray_backlash_block(tmp_path):
    limits = tmp_path / "limits.json"
    payload = merged_limits_payload(
        {"x": [1, 2], "y": [3, 4], "z_galvo": [-5, 5], "z_wide": [0, 100]}
    )
    payload["backlash"] = {"anything": "not validated", "overshoot_um": "not-a-number"}
    _write_json(limits, payload)

    with pytest.raises(ValueError, match="unknown limits entries"):
        stage_config.load(limits_path=limits)


def test_limits_paths_are_separate_from_calibration_state(tmp_path, monkeypatch):
    # With no machine snapshot (hermetic root fixture): the physical limits
    # seed into ProgramData from the bundled template shipped in the driver tree.
    driver_root = Path(__file__).resolve().parents[2]
    template_limits = driver_root / "limits" / "defaults" / "limits.json"
    monkeypatch.setenv("ZMART_MICROSCOPY_ROOT", str(tmp_path / "programdata"))

    defaults = stage_config.defaults_path()
    assert defaults.name == "limits.json"
    assert defaults != template_limits
    assert defaults.exists()
    # The bundled template stays shipped; ProgramData gets the runtime copy.
    assert template_limits.exists()
    template = json.loads(template_limits.read_text(encoding="utf-8"))
    assert set(template) == set(stage_config._REQUIRED_FILE_KEYS)
    assert template["x_um"] == {"range": [1000, 130000]}


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


def test_load_requires_all_flat_entries(tmp_path):
    limits = tmp_path / "limits.json"
    _write_json(limits, {"x_um": [1, 2]})
    with pytest.raises(ValueError, match="missing limits entries"):
        stage_config.load(limits_path=limits)


def test_load_rejects_legacy_metadata(tmp_path):
    limits = tmp_path / "limits.json"
    payload = merged_limits_payload(
        {"x": [1, 2], "y": [3, 4], "z_galvo": [-5, 5], "z_wide": [0, 100]}
    )
    payload["source"] = "defaults"
    _write_json(limits, payload)
    with pytest.raises(ValueError, match="unknown limits entries"):
        stage_config.load(limits_path=limits)


def test_limits_notebook_publishes_the_exact_flat_template():
    driver_root = Path(__file__).resolve().parents[2]
    notebook = json.loads(
        (driver_root / "limits" / "notebooks" / "set_limits.ipynb").read_text(encoding="utf-8")
    )
    source = "\n".join(
        "".join(cell.get("source", []))
        for cell in notebook["cells"]
        if cell.get("cell_type") == "code"
    )
    tree = ast.parse(source)
    assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "LIMITS" for target in node.targets)
    )
    notebook_limits = ast.literal_eval(assignment.value)
    bundled = json.loads(
        (driver_root / "limits" / "defaults" / "limits.json").read_text(encoding="utf-8")
    )
    assert notebook_limits == bundled
    assert "stage_config.adopt_limits(LIMITS" in source

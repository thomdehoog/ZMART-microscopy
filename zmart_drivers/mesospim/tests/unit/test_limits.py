"""Stage limits: set/get/check + config loading."""

from __future__ import annotations

import json

import pytest
from mesospim.config import limits


@pytest.fixture(autouse=True)
def _isolate_limits():
    limits.clear_stage_limits()
    yield
    limits.clear_stage_limits()


def test_unconfigured_axis_fails_closed():
    # No limit set -> reject (fail closed, like the Leica sibling): an
    # unconfigured axis must never let an unbounded move through.
    with pytest.raises(limits.LimitError):
        limits.check_axis("x", 1e9)


def test_check_move_fails_closed_on_unconfigured_axis():
    limits.set_stage_limits(x=(0, 100))
    with pytest.raises(limits.LimitError):
        limits.check_move({"x": 10, "y": 20})  # y never configured


def test_set_and_check_axis():
    limits.set_stage_limits(x=(0, 100))
    limits.check_axis("x", 50)
    with pytest.raises(limits.LimitError):
        limits.check_axis("x", 200)
    with pytest.raises(limits.LimitError):
        limits.check_axis("x", -1)


def test_check_move_partial():
    limits.set_stage_limits(x=(0, 100), y=(0, 100))
    limits.check_move({"x": 10})  # only x checked
    with pytest.raises(limits.LimitError):
        limits.check_move({"x": 10, "y": 500})


def test_set_rejects_unknown_axis():
    with pytest.raises(ValueError):
        limits.set_stage_limits(w=(0, 1))


def test_set_rejects_min_gt_max():
    with pytest.raises(ValueError):
        limits.set_stage_limits(x=(100, 0))


def test_get_returns_copy():
    limits.set_stage_limits(z=(0, 10))
    snapshot = limits.get_stage_limits()
    snapshot["z"] = (0, 999)
    assert limits.get_stage_limits()["z"] == (0.0, 10.0)


def test_load_default_stage_config():
    cfg = limits.load_stage_config()
    assert set(cfg["axes"]) == {"x", "y", "z", "f", "theta"}


def test_apply_from_config():
    cfg = limits.load_stage_config()
    limits.apply_stage_limits_from_config(cfg)
    active = limits.get_stage_limits()
    assert active["x"] is not None


def test_load_rejects_bad_schema(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": 99, "axes": {}}))
    with pytest.raises(ValueError):
        limits.load_stage_config(bad)


def test_load_rejects_unknown_axis(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": 1, "axes": {"w": [0, 1]}}))
    with pytest.raises(ValueError):
        limits.load_stage_config(bad)

"""Tests for the MachineProfile calibration/limits resolver."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from navigator_expert.config import machine
from navigator_expert.config.machine import (
    MachineProfile,
    format_snapshot_name,
    is_snapshot_name,
)


def _mk_snapshot(root: Path, name: str, *, calibration=True, limits=True) -> Path:
    d = root / "leica" / "stellaris5_y42h93" / name
    d.mkdir(parents=True)
    if calibration:
        (d / "calibration.json").write_text("{}", encoding="utf-8")
    if limits:
        (d / "limits.json").write_text("{}", encoding="utf-8")
    return d


def _profile(tmp_path: Path) -> MachineProfile:
    return MachineProfile(programdata_root=tmp_path)


# --- datetime format ---


def test_format_snapshot_name_is_utc_windows_safe_sortable():
    m = datetime(2026, 7, 1, 14, 30, 0, 123456, tzinfo=timezone.utc)
    name = format_snapshot_name(m)
    assert name == "2026-07-01T14-30-00-123456Z"
    assert ":" not in name  # legal Windows path segment
    assert is_snapshot_name(name)


def test_format_converts_to_utc():
    tz = timezone(timedelta(hours=2))  # 16:30 +02:00 == 14:30 UTC
    m = datetime(2026, 7, 1, 16, 30, 0, 123456, tzinfo=tz)
    assert format_snapshot_name(m) == "2026-07-01T14-30-00-123456Z"


def test_lexical_order_is_chronological():
    a = format_snapshot_name(datetime(2026, 6, 15, 9, 12, 0, 0, tzinfo=timezone.utc))
    b = format_snapshot_name(datetime(2026, 7, 1, 14, 30, 0, 123456, tzinfo=timezone.utc))
    assert a < b


def test_is_snapshot_name_rejects_malformed():
    assert not is_snapshot_name("current")
    assert not is_snapshot_name("2026-07-01")
    assert not is_snapshot_name("2026-07-01T14-30-00Z")  # no microseconds


# --- latest_snapshot selection ---


def test_latest_snapshot_none_when_root_absent(tmp_path):
    assert _profile(tmp_path).latest_snapshot() is None


def test_latest_snapshot_none_when_empty(tmp_path):
    (tmp_path / "leica" / "stellaris5_y42h93").mkdir(parents=True)
    assert _profile(tmp_path).latest_snapshot() is None


def test_latest_snapshot_picks_newest(tmp_path):
    _mk_snapshot(tmp_path, "2026-06-15T09-12-00-000000Z")
    newest = _mk_snapshot(tmp_path, "2026-07-01T14-30-00-123456Z")
    _mk_snapshot(tmp_path, "2026-06-30T23-59-59-999999Z")
    assert _profile(tmp_path).latest_snapshot() == newest


def test_latest_snapshot_ignores_malformed_dirs_and_files(tmp_path):
    valid = _mk_snapshot(tmp_path, "2026-07-01T14-30-00-123456Z")
    (tmp_path / "leica" / "stellaris5_y42h93" / "current").mkdir()  # not a snapshot
    (tmp_path / "leica" / "stellaris5_y42h93" / "notes.txt").write_text("x")
    assert _profile(tmp_path).latest_snapshot() == valid


# --- resolve / fallback ---


def test_resolve_uses_latest_snapshot(tmp_path):
    _mk_snapshot(tmp_path, "2026-07-01T14-30-00-123456Z")
    p = _profile(tmp_path)
    cal, fb = p.resolve("calibration.json")
    assert fb is False
    assert cal == p.latest_snapshot() / "calibration.json"


def test_resolve_falls_back_to_bundled_default_when_no_snapshot(tmp_path):
    p = _profile(tmp_path)
    cal, fb = p.resolve("calibration.json")
    assert fb is True
    assert cal == p.bundled_default_root() / "calibration.json"
    assert cal.exists()  # the bundled default really ships


def test_resolve_falls_back_per_file_when_snapshot_incomplete(tmp_path):
    _mk_snapshot(tmp_path, "2026-07-01T14-30-00-123456Z", limits=False)
    p = _profile(tmp_path)
    _, cal_fb = p.resolve("calibration.json")
    lim, lim_fb = p.resolve("limits.json")
    assert cal_fb is False  # calibration present in the snapshot
    assert lim_fb is True  # limits missing -> bundled default
    assert lim == p.bundled_default_root() / "limits.json"


def test_bundled_defaults_are_real_last_known_good(tmp_path):
    """The shipped defaults must be valid config, never identity/zero."""
    from navigator_expert.calibration.core import model

    p = _profile(tmp_path)
    cal = model.load_calibration(p.bundled_default_root() / "calibration.json")
    assert model.get_reference_slot(cal) == 1
    assert model.get_translation_um(cal, 0) != (0.0, 0.0, 0.0)


# --- monotonic new snapshot ---


def test_new_snapshot_dir_first_is_allowed(tmp_path):
    p = _profile(tmp_path)
    m = datetime(2026, 7, 1, 14, 30, 0, 123456, tzinfo=timezone.utc)
    assert p.new_snapshot_dir(m).name == "2026-07-01T14-30-00-123456Z"


def test_new_snapshot_dir_rejects_backward_clock(tmp_path):
    _mk_snapshot(tmp_path, "2026-07-01T14-30-00-123456Z")
    p = _profile(tmp_path)
    earlier = datetime(2026, 7, 1, 14, 29, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        p.new_snapshot_dir(earlier)


def test_new_snapshot_dir_rejects_same_stamp(tmp_path):
    _mk_snapshot(tmp_path, "2026-07-01T14-30-00-123456Z")
    p = _profile(tmp_path)
    same = datetime(2026, 7, 1, 14, 30, 0, 123456, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        p.new_snapshot_dir(same)


def test_new_snapshot_dir_accepts_later(tmp_path):
    _mk_snapshot(tmp_path, "2026-07-01T14-30-00-123456Z")
    p = _profile(tmp_path)
    later = datetime(2026, 7, 1, 14, 30, 0, 123457, tzinfo=timezone.utc)
    d = p.new_snapshot_dir(later)
    assert d.name == "2026-07-01T14-30-00-123457Z"
    assert d.parent == p.snapshot_root()


# --- root resolution ---


def test_env_var_override(tmp_path, monkeypatch):
    monkeypatch.setenv(machine.PROGRAMDATA_ROOT_ENV, str(tmp_path))
    p = MachineProfile()  # no explicit root
    assert p.root() == tmp_path
    assert p.snapshot_root() == tmp_path / "leica" / "stellaris5_y42h93"


def test_explicit_root_beats_env(tmp_path, monkeypatch):
    monkeypatch.setenv(machine.PROGRAMDATA_ROOT_ENV, str(tmp_path / "env"))
    p = MachineProfile(programdata_root=tmp_path / "explicit")
    assert p.root() == tmp_path / "explicit"


# --- publish_snapshot (copy-forward writer) ---

_AT_1430 = datetime(2026, 7, 1, 14, 30, 0, 0, tzinfo=timezone.utc)
_AT_1500 = datetime(2026, 7, 1, 15, 0, 0, 0, tzinfo=timezone.utc)


def _write(path: Path, obj) -> None:
    path.write_text(json.dumps(obj), encoding="utf-8")


def test_publish_first_snapshot_carries_bundled_default_forward(tmp_path):
    p = _profile(tmp_path)
    new_limits = {"schema_version": 1, "source": "defaults", "stage_um": {"x": [0, 1]}}
    snap = p.publish_snapshot(_AT_1430, limits=new_limits)
    # No prior snapshot -> calibration.json comes from the bundled default.
    bundled = json.loads((p.bundled_default_root() / "calibration.json").read_text())
    assert json.loads((snap / "calibration.json").read_text()) == bundled
    assert json.loads((snap / "limits.json").read_text()) == new_limits
    assert p.latest_snapshot() == snap


def test_publish_carries_untouched_file_forward(tmp_path):
    p = _profile(tmp_path)
    first = _mk_snapshot(tmp_path, "2026-07-01T14-30-00-000000Z")
    _write(first / "calibration.json", {"marker": "cal-A"})
    _write(first / "limits.json", {"marker": "lim-A"})
    snap = p.publish_snapshot(_AT_1500, limits={"marker": "lim-B"})
    # limits overridden, calibration carried forward unchanged
    assert json.loads((snap / "calibration.json").read_text()) == {"marker": "cal-A"}
    assert json.loads((snap / "limits.json").read_text()) == {"marker": "lim-B"}


def test_publish_overrides_calibration_carries_limits(tmp_path):
    p = _profile(tmp_path)
    first = _mk_snapshot(tmp_path, "2026-07-01T14-30-00-000000Z")
    _write(first / "calibration.json", {"marker": "cal-A"})
    _write(first / "limits.json", {"marker": "lim-A"})
    snap = p.publish_snapshot(_AT_1500, calibration={"marker": "cal-B"})
    assert json.loads((snap / "calibration.json").read_text()) == {"marker": "cal-B"}
    assert json.loads((snap / "limits.json").read_text()) == {"marker": "lim-A"}


def test_publish_archives_notebook(tmp_path):
    p = _profile(tmp_path)
    nb = tmp_path / "calibrate_objective_pair.ipynb"
    nb.write_text('{"cells": []}', encoding="utf-8")
    snap = p.publish_snapshot(_AT_1430, calibration={"marker": "x"}, notebook_paths=[nb])
    assert (snap / "calibrate_objective_pair.ipynb").read_text() == '{"cells": []}'


def test_publish_makes_new_snapshot_the_latest(tmp_path):
    p = _profile(tmp_path)
    _mk_snapshot(tmp_path, "2026-07-01T14-30-00-000000Z")
    snap = p.publish_snapshot(_AT_1500, calibration={"marker": "x"})
    assert p.latest_snapshot() == snap
    assert snap.name == "2026-07-01T15-00-00-000000Z"


def test_publish_rejects_non_monotonic_and_leaves_no_partial(tmp_path):
    p = _profile(tmp_path)
    valid = _mk_snapshot(tmp_path, "2026-07-01T14-30-00-123456Z")
    earlier = datetime(2026, 7, 1, 14, 0, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        p.publish_snapshot(earlier, calibration={"marker": "x"})
    children = sorted(x.name for x in p.snapshot_root().iterdir())
    assert children == [valid.name]  # no ".partial" leftover, no bad snapshot


def test_publish_leaves_no_partial_after_success(tmp_path):
    p = _profile(tmp_path)
    p.publish_snapshot(_AT_1430, calibration={"marker": "x"})
    assert [x.name for x in p.snapshot_root().iterdir() if ".partial" in x.name] == []


def test_published_calibration_is_loadable(tmp_path):
    from navigator_expert.calibration.core import model

    p = _profile(tmp_path)
    cal = model.load_calibration(p.bundled_default_root() / "calibration.json")
    snap = p.publish_snapshot(_AT_1430, calibration=cal)
    reloaded = model.load_calibration(snap / "calibration.json")
    assert model.get_reference_slot(reloaded) == 1
    assert model.get_translation_um(reloaded, 0) == model.get_translation_um(cal, 0)

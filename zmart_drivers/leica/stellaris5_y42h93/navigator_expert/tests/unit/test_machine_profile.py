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


def _mk_snapshot(root: Path, name: str, *, calibration=True, limits=True, orientation=True) -> Path:
    d = root / "leica" / "stellaris5_y42h93" / "navigator_expert" / name
    d.mkdir(parents=True)
    if calibration:
        (d / "calibration.json").write_text("{}", encoding="utf-8")
    if limits:
        (d / "limits.json").write_text("{}", encoding="utf-8")
    if orientation:
        (d / "orientation.json").write_text(
            '{"schema_version": 1, "rotate_deg": 0}', encoding="utf-8"
        )
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
    (tmp_path / "leica" / "stellaris5_y42h93" / "navigator_expert").mkdir(parents=True)
    assert _profile(tmp_path).latest_snapshot() is None


def test_latest_snapshot_picks_newest(tmp_path):
    _mk_snapshot(tmp_path, "2026-06-15T09-12-00-000000Z")
    newest = _mk_snapshot(tmp_path, "2026-07-01T14-30-00-123456Z")
    _mk_snapshot(tmp_path, "2026-06-30T23-59-59-999999Z")
    assert _profile(tmp_path).latest_snapshot() == newest


def test_latest_snapshot_ignores_malformed_dirs_and_files(tmp_path):
    valid = _mk_snapshot(tmp_path, "2026-07-01T14-30-00-123456Z")
    api_root = tmp_path / "leica" / "stellaris5_y42h93" / "navigator_expert"
    (api_root / "current").mkdir()  # not a snapshot
    (api_root / "notes.txt").write_text("x")
    assert _profile(tmp_path).latest_snapshot() == valid


# --- resolve / ProgramData seeding ---


def test_resolve_uses_latest_snapshot(tmp_path):
    _mk_snapshot(tmp_path, "2026-07-01T14-30-00-123456Z")
    p = _profile(tmp_path)
    cal, fb = p.resolve("calibration.json")
    assert fb is False
    assert cal == p.latest_snapshot() / "calibration.json"


def test_resolve_seeds_programdata_from_defaults_when_no_snapshot(tmp_path):
    p = _profile(tmp_path)
    cal, fb = p.resolve("calibration.json")
    assert fb is False
    assert cal == p.latest_snapshot() / "calibration.json"
    assert cal.exists()
    assert (p.latest_snapshot() / "limits.json").exists()
    assert (p.latest_snapshot() / "orientation.json").exists()
    assert p.bundled_default_path("calibration.json").exists()


def test_resolve_repairs_incomplete_snapshot_by_publishing_complete_one(tmp_path):
    incomplete = _mk_snapshot(tmp_path, "2026-07-01T14-30-00-123456Z", limits=False)
    p = _profile(tmp_path)
    _, cal_fb = p.resolve("calibration.json")
    lim, lim_fb = p.resolve("limits.json")
    assert cal_fb is False
    assert lim_fb is False
    assert p.latest_snapshot() != incomplete
    assert lim == p.latest_snapshot() / "limits.json"
    assert lim.exists()
    assert json.loads((p.latest_snapshot() / "calibration.json").read_text()) == {}


def test_bundled_defaults_are_real_last_known_good(tmp_path):
    """The shipped defaults must be valid config, never identity/zero."""
    from navigator_expert.calibration.core import model

    p = _profile(tmp_path)
    cal = model.load_calibration(p.bundled_default_path("calibration.json"))
    assert model.get_reference_slot(cal) == 1
    assert model.get_translation_um(cal, 0) != (0.0, 0.0, 0.0)


# --- api level + legacy migration ---


def test_snapshot_root_includes_api_level(tmp_path):
    p = _profile(tmp_path)
    assert p.snapshot_root() == tmp_path / "leica" / "stellaris5_y42h93" / "navigator_expert"
    assert p.legacy_snapshot_root() == tmp_path / "leica" / "stellaris5_y42h93"


def test_migrate_legacy_snapshots_moves_pre_api_snapshots(tmp_path):
    # Snapshots at the old vendor/microscope level move under the api level.
    legacy = tmp_path / "leica" / "stellaris5_y42h93" / "2026-06-15T09-12-00-000000Z"
    legacy.mkdir(parents=True)
    (legacy / "calibration.json").write_text("{}", encoding="utf-8")
    p = _profile(tmp_path)
    assert p.latest_snapshot() is None  # not visible pre-migration

    moved = p.migrate_legacy_snapshots()

    assert moved == [p.snapshot_root() / "2026-06-15T09-12-00-000000Z"]
    assert not legacy.exists()
    assert p.latest_snapshot() == moved[0]
    assert (moved[0] / "calibration.json").exists()
    assert p.migrate_legacy_snapshots() == []  # idempotent


# --- origin: machine-local frame zero point ---


def test_origin_round_trips_in_its_own_folder(tmp_path):
    # The origin lives in its own origin/ folder, next to the snapshots and
    # independent of them.
    _mk_snapshot(tmp_path, "2026-07-01T14-30-00-123456Z")
    p = _profile(tmp_path)
    payload = {"origin": {"x_um": 1.0, "y_um": 2.0}, "captured_at": 123.0}

    path = p.write_origin(payload)

    assert path == p.origin_dir() / "origin.json"
    assert path.parent.name == "origin"
    assert p.read_origin() == payload

    # A second set_origin overwrites in place.
    p.write_origin({"origin": {"x_um": 9.0}, "captured_at": 456.0})
    assert p.read_origin()["origin"] == {"x_um": 9.0}


def test_origin_persists_without_any_snapshot(tmp_path):
    # set_origin works even before a calibration snapshot exists: the origin
    # folder is independent of the dated snapshots.
    p = _profile(tmp_path)
    path = p.write_origin({"origin": {}})
    assert path == p.origin_dir() / "origin.json"
    assert p.latest_snapshot() is None
    assert p.read_origin() == {"origin": {}}


def test_publish_snapshot_never_writes_origin(tmp_path):
    # The origin is not snapshot state: an adopt neither reads nor writes it.
    _mk_snapshot(tmp_path, "2026-07-01T14-30-00-123456Z")
    p = _profile(tmp_path)
    p.write_origin({"origin": {"x_um": 5.0}})

    snap = p.publish_snapshot(datetime(2026, 7, 2, 10, 0, 0, 0, tzinfo=timezone.utc))

    assert not (snap / "origin.json").exists()
    # The origin folder is untouched by the adopt.
    assert p.read_origin()["origin"] == {"x_um": 5.0}


def test_read_origin_is_none_when_never_set(tmp_path):
    _mk_snapshot(tmp_path, "2026-07-01T14-30-00-123456Z")
    p = _profile(tmp_path)
    snap = p.publish_snapshot(datetime(2026, 7, 2, 10, 0, 0, 0, tzinfo=timezone.utc))
    assert not (snap / "origin.json").exists()
    assert p.read_origin() is None


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
    assert p.snapshot_root() == tmp_path / "leica" / "stellaris5_y42h93" / "navigator_expert"


def test_explicit_root_beats_env(tmp_path, monkeypatch):
    monkeypatch.setenv(machine.PROGRAMDATA_ROOT_ENV, str(tmp_path / "env"))
    p = MachineProfile(programdata_root=tmp_path / "explicit")
    assert p.root() == tmp_path / "explicit"


# --- publish_snapshot (copy-forward writer) ---

_AT_1430 = datetime(2026, 7, 1, 14, 30, 0, 0, tzinfo=timezone.utc)
_AT_1500 = datetime(2026, 7, 1, 15, 0, 0, 0, tzinfo=timezone.utc)


def _write(path: Path, obj) -> None:
    path.write_text(json.dumps(obj), encoding="utf-8")


def test_publish_first_snapshot_seeds_complete_baseline(tmp_path):
    p = _profile(tmp_path)
    new_limits = {"schema_version": 1, "source": "defaults", "constraints": {}}
    snap = p.publish_snapshot(_AT_1430, limits=new_limits)
    assert (snap / "calibration.json").exists()
    assert (snap / "orientation.json").exists()
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


# --- orientation: a machine-specific file, alongside calibration and limits ---


def test_orientation_path_seeds_programdata_no_turn_default(tmp_path):
    p = _profile(tmp_path)
    resolved = p.orientation_path()
    assert resolved == p.latest_snapshot() / "orientation.json"
    assert json.loads(resolved.read_text())["rotate_deg"] == 0


def test_publish_overrides_orientation_carries_calibration_and_limits(tmp_path):
    p = _profile(tmp_path)
    first = _mk_snapshot(tmp_path, "2026-07-01T14-30-00-000000Z")
    _write(first / "calibration.json", {"marker": "cal-A"})
    _write(first / "limits.json", {"marker": "lim-A"})
    snap = p.publish_snapshot(_AT_1500, orientation={"schema_version": 1, "rotate_deg": 90})
    # orientation adopted; the other two machine-specific files ride forward.
    assert json.loads((snap / "orientation.json").read_text())["rotate_deg"] == 90
    assert json.loads((snap / "calibration.json").read_text()) == {"marker": "cal-A"}
    assert json.loads((snap / "limits.json").read_text()) == {"marker": "lim-A"}
    assert p.orientation_path() == snap / "orientation.json"


def test_publish_carries_measured_orientation_forward(tmp_path):
    # A later limits adopt (orientation not re-measured) must not lose the turn.
    p = _profile(tmp_path)
    first = _mk_snapshot(tmp_path, "2026-07-01T14-30-00-000000Z")
    _write(first / "orientation.json", {"schema_version": 1, "rotate_deg": 270})
    snap = p.publish_snapshot(_AT_1500, limits={"marker": "lim-B"})
    assert json.loads((snap / "orientation.json").read_text())["rotate_deg"] == 270


def test_publish_first_snapshot_seeds_bundled_orientation(tmp_path):
    p = _profile(tmp_path)
    snap = p.publish_snapshot(_AT_1430, limits={"schema_version": 1, "constraints": {}})
    assert (snap / "orientation.json").exists()


def test_publish_setup_sequence_ends_with_all_three(tmp_path):
    # The documented promise, and the real path a biologist walks bringing a new
    # microscope online: set up limits, then orientation, then calibration --
    # each step measures only one, yet the final snapshot holds all three,
    # because every adopt carries the others forward.
    p = _profile(tmp_path)
    p.publish_snapshot(_AT_1430, limits={"marker": "lim"})
    p.publish_snapshot(_AT_1500, orientation={"schema_version": 1, "rotate_deg": 90})
    snap = p.publish_snapshot(
        datetime(2026, 7, 1, 15, 30, 0, 0, tzinfo=timezone.utc),
        calibration={"marker": "cal"},
    )
    assert json.loads((snap / "limits.json").read_text()) == {"marker": "lim"}
    assert json.loads((snap / "orientation.json").read_text())["rotate_deg"] == 90
    assert json.loads((snap / "calibration.json").read_text()) == {"marker": "cal"}


def test_named_calibration_publishes_under_named_programdata_path(tmp_path):
    p = _profile(tmp_path)

    snap = p.publish_snapshot(
        _AT_1430,
        calibration={"marker": "lens-A"},
        calibration_name="10x_20x_water",
    )

    path = snap / "calibrations" / "10x_20x_water" / "calibration.json"
    assert json.loads(path.read_text()) == {"marker": "lens-A"}
    assert p.calibration_path("10x_20x_water") == path
    assert (snap / "calibration.json").exists()


def test_named_calibration_empty_root_seeds_one_complete_snapshot(tmp_path):
    p = _profile(tmp_path)

    path = p.calibration_path("lens_A")

    assert len(p.snapshots()) == 1
    snap = p.latest_snapshot()
    assert path == snap / "calibrations" / "lens_A" / "calibration.json"
    assert (snap / "calibration.json").exists()
    assert (snap / "limits.json").exists()
    assert (snap / "orientation.json").exists()


def test_named_calibration_sets_are_carried_forward(tmp_path):
    p = _profile(tmp_path)
    first = p.publish_snapshot(
        _AT_1430,
        calibration={"marker": "lens-A"},
        calibration_name="lens_A",
    )
    snap = p.publish_snapshot(_AT_1500, limits={"marker": "lim-B"})

    path = snap / "calibrations" / "lens_A" / "calibration.json"
    assert json.loads(path.read_text()) == {"marker": "lens-A"}
    assert p.calibration_path("lens_A") == path
    assert (first / "calibrations" / "lens_A" / "calibration.json").exists()


def test_named_calibration_can_be_selected_by_env(tmp_path, monkeypatch):
    p = _profile(tmp_path)
    snap = p.publish_snapshot(
        _AT_1430,
        calibration={"marker": "lens-A"},
        calibration_name="lens_A",
    )
    monkeypatch.setenv(machine.CALIBRATION_NAME_ENV, "lens_A")

    assert p.calibration_path() == snap / "calibrations" / "lens_A" / "calibration.json"


def test_named_calibration_rejects_path_segments(tmp_path):
    p = _profile(tmp_path)
    with pytest.raises(ValueError, match="calibration_name"):
        p.calibration_path("../escape")


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
    cal = model.load_calibration(p.bundled_default_path("calibration.json"))
    snap = p.publish_snapshot(_AT_1430, calibration=cal)
    reloaded = model.load_calibration(snap / "calibration.json")
    assert model.get_reference_slot(reloaded) == 1
    assert model.get_translation_um(reloaded, 0) == model.get_translation_um(cal, 0)

"""Tests for the subsystem-owned ProgramData resolver."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from navigator_expert.config import machine
from navigator_expert.config.machine import MachineProfile, format_snapshot_name, is_snapshot_name

_AT_1400 = datetime(2026, 7, 1, 14, 0, tzinfo=timezone.utc)
_AT_1430 = datetime(2026, 7, 1, 14, 30, tzinfo=timezone.utc)
_AT_1500 = datetime(2026, 7, 1, 15, 0, tzinfo=timezone.utc)
# A configuration seeded today is named by now, so a new one has to be later.
_TOMORROW = (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0)
_FILENAMES = {
    "limits": "limits.json",
    "calibration": "calibration.json",
    "orientation": "orientation.json",
    "origin": "origin.json",
}


def _profile(tmp_path: Path) -> MachineProfile:
    return MachineProfile(programdata_root=tmp_path)


def _mk_snapshot(
    profile: MachineProfile,
    subsystem: str,
    name: str,
    payload: dict | None = None,
) -> Path:
    snapshot = profile.subsystem_root(subsystem) / name
    snapshot.mkdir(parents=True)
    (snapshot / _FILENAMES[subsystem]).write_text(json.dumps(payload or {}), encoding="utf-8")
    return snapshot


def _mk_flat_snapshot(profile: MachineProfile, name: str) -> Path:
    snapshot = profile.api_root() / name
    snapshot.mkdir(parents=True)
    (snapshot / "limits.json").write_text('{"limits": "old"}', encoding="utf-8")
    (snapshot / ".limits-machine").touch()
    (snapshot / "calibration.json").write_text('{"calibration": "old"}', encoding="utf-8")
    (snapshot / "orientation.json").write_text('{"rotate_deg": 90}', encoding="utf-8")
    named = snapshot / "calibrations" / "water"
    named.mkdir(parents=True)
    (named / "calibration.json").write_text('{"calibration": "water"}', encoding="utf-8")
    (snapshot / "set_limits.ipynb").write_text("limits", encoding="utf-8")
    (snapshot / "set_orientation.ipynb").write_text("orientation", encoding="utf-8")
    (snapshot / "calibrate_objective_pair.ipynb").write_text("calibration", encoding="utf-8")
    return snapshot


def test_snapshot_name_is_utc_windows_safe_and_sortable():
    local = timezone(timedelta(hours=2))
    moment = datetime(2026, 7, 1, 16, 30, 0, 123456, tzinfo=local)
    name = format_snapshot_name(moment)
    assert name == "2026-07-01T14-30-00-123456Z"
    assert ":" not in name
    assert is_snapshot_name(name)
    assert not is_snapshot_name("2026-07-01T14-30-00Z")


def test_subsystem_roots_are_directly_below_the_configuration(tmp_path):
    profile = _profile(tmp_path)
    api_root = tmp_path / "leica" / "stellaris5_y42h93" / "navigator_expert"
    assert profile.api_root() == api_root
    # With no configuration yet, one is seeded: the driver has to stand somewhere.
    root = profile.snapshot_root()
    assert root.parent == api_root
    assert machine.is_configuration_name(root.name)
    for subsystem in _FILENAMES:
        assert profile.subsystem_root(subsystem) == root / subsystem
    # And it is the same one on every ask.
    assert profile.snapshot_root() == root
    assert [p.name for p in profile.configurations()] == [root.name]


def test_a_named_configuration_is_stood_on_and_a_missing_one_refused(tmp_path):
    profile = _profile(tmp_path)
    first = profile.snapshot_root()
    second = profile.new_configuration(_TOMORROW)
    assert second.name == machine.format_configuration_name(_TOMORROW)
    assert profile.snapshot_root() == second          # the newest, by default
    bound = MachineProfile(programdata_root=tmp_path, configuration=first.name)
    assert bound.snapshot_root() == first
    with pytest.raises(FileNotFoundError):
        MachineProfile(programdata_root=tmp_path, configuration="configuration_2000-01-01T00-00-00-000000Z").snapshot_root()


def test_a_new_configuration_copies_the_newest_snapshot_of_each_subsystem(tmp_path):
    profile = _profile(tmp_path)
    _mk_snapshot(profile, "limits", "2026-07-01T14-00-00-000000Z", {"x_um": {"range": [0, 1]}})
    _mk_snapshot(profile, "limits", "2026-07-01T14-30-00-000000Z", {"x_um": {"range": [0, 2]}})
    _mk_snapshot(profile, "origin", "2026-07-01T14-00-00-000000Z", {"x_um": 5})
    older = profile.snapshot_root()
    fresh = profile.new_configuration(_TOMORROW)
    assert sorted(p.name for p in fresh.iterdir()) == ["calibration", "limits", "orientation", "origin"]
    copied = sorted(p.name for p in (fresh / "limits").iterdir())
    assert copied == ["2026-07-01T14-30-00-000000Z"]        # the newest only
    assert json.loads((fresh / "limits" / copied[0] / "limits.json").read_text()) == {"x_um": {"range": [0, 2]}}
    assert (fresh / "origin" / "2026-07-01T14-00-00-000000Z" / "origin.json").is_file()
    assert list((fresh / "calibration").iterdir()) == []
    # The older configuration is untouched, and adopting in the new one leaves it so.
    assert sorted(p.name for p in (older / "limits").iterdir()) == [
        "2026-07-01T14-00-00-000000Z", "2026-07-01T14-30-00-000000Z"]
    said = profile.describe_configuration(fresh)
    assert said["id"] == fresh.name
    assert said["has"] == {"limits": True, "calibration": False, "orientation": False, "origin": True}


def test_subsystem_trees_under_the_api_root_are_copied_into_a_first_configuration(tmp_path):
    api_root = tmp_path / "leica" / "stellaris5_y42h93" / "navigator_expert"
    old = api_root / "limits" / "2026-07-01T14-30-00-000000Z"
    old.mkdir(parents=True)
    (old / "limits.json").write_text('{"x_um": {"range": [0, 1]}}', encoding="utf-8")
    (api_root / "origin").mkdir()
    profile = _profile(tmp_path)
    found = profile.configurations()
    assert [p.name for p in found] == ["configuration_2026-07-01T14-30-00-000000Z"]
    assert (old / "limits.json").is_file()                 # the old tree stays as it was
    assert profile.configurations() == found              # and is not copied twice
    assert (found[0] / "limits" / "2026-07-01T14-30-00-000000Z" / "limits.json").is_file()
    assert profile.latest_snapshot("limits") == found[0] / "limits" / "2026-07-01T14-30-00-000000Z"


def test_ensure_layout_creates_every_subsystem_directory(tmp_path):
    profile = _profile(tmp_path / "new-root")

    assert profile.ensure_layout() == profile.snapshot_root()
    assert profile.ensure_layout() == profile.snapshot_root()
    assert all(profile.subsystem_root(name).is_dir() for name in machine.SUBSYSTEMS)


def test_unknown_subsystem_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="unknown machine-config subsystem"):
        _profile(tmp_path).subsystem_root("mixed")


def test_latest_snapshot_is_independent_per_subsystem(tmp_path):
    profile = _profile(tmp_path)
    older = _mk_snapshot(profile, "limits", "2026-07-01T14-00-00-000000Z")
    newest = _mk_snapshot(profile, "limits", "2026-07-01T15-00-00-000000Z")
    orientation = _mk_snapshot(profile, "orientation", "2026-07-01T14-30-00-000000Z")
    assert profile.snapshots("limits") == [older, newest]
    assert profile.latest_snapshot("limits") == newest
    assert profile.latest_snapshot("orientation") == orientation
    assert profile.latest_snapshot("calibration") is None


def test_snapshot_listing_ignores_malformed_entries(tmp_path):
    profile = _profile(tmp_path)
    valid = _mk_snapshot(profile, "limits", "2026-07-01T14-30-00-000000Z")
    (profile.subsystem_root("limits") / "current").mkdir()
    (profile.subsystem_root("limits") / "notes.txt").write_text("x", encoding="utf-8")
    assert profile.snapshots("limits") == [valid]


def test_limits_do_not_seed_while_other_resolvers_seed_their_own_tree(tmp_path):
    profile = _profile(tmp_path)
    calibration = profile.calibration_path()
    assert calibration.parent.parent == profile.subsystem_root("calibration")
    assert profile.latest_snapshot("limits") is None
    assert profile.latest_snapshot("orientation") is None

    with pytest.raises(FileNotFoundError, match="operator-published"):
        profile.limits_path()
    orientation = profile.orientation_path()
    assert profile.latest_snapshot("limits") is None
    assert orientation.parent.parent == profile.subsystem_root("orientation")
    assert not (orientation.parent / "limits.json").exists()


def test_incomplete_limits_snapshot_does_not_seed_or_masquerade_as_machine_limits(tmp_path):
    profile = _profile(tmp_path)
    incomplete = profile.subsystem_root("limits") / "2026-07-01T14-30-00-000000Z"
    incomplete.mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="operator-published"):
        profile.limits_path()
    assert profile.latest_snapshot("limits") == incomplete


def test_flat_layout_migrates_copy_only_into_all_subsystems(tmp_path):
    profile = _profile(tmp_path)
    flat = _mk_flat_snapshot(profile, "2026-07-01T14-30-00-000000Z")
    old_origin = profile.origin_dir() / "origin.json"
    old_origin.parent.mkdir(parents=True, exist_ok=True)
    old_origin.write_text('{"origin": {"x_um": 5}}', encoding="utf-8")

    migrated = profile.migrate_flat_snapshots()

    assert set(migrated) == {"limits", "calibration", "orientation", "origin"}
    assert flat.exists()
    assert old_origin.exists()
    assert (migrated["limits"] / "limits.json").exists()
    assert not (migrated["limits"] / ".limits-machine").exists()
    assert (migrated["limits"] / "notebook" / "set_limits.ipynb").exists()
    assert not (migrated["limits"] / "data" / "notebook" / "set_orientation.ipynb").exists()
    assert (migrated["calibration"] / "calibrations" / "water" / "calibration.json").exists()
    assert (
        migrated["calibration"] / "data" / "notebook" / "calibrate_objective_pair.ipynb"
    ).exists()
    assert (migrated["orientation"] / "data" / "notebook" / "set_orientation.ipynb").exists()
    assert profile.read_origin()["origin"] == {"x_um": 5}
    assert profile.migrate_flat_snapshots() == {}


def test_pre_api_flat_snapshot_copies_then_migrates(tmp_path):
    profile = _profile(tmp_path)
    legacy = profile.legacy_snapshot_root() / "2026-06-15T09-12-00-000000Z"
    legacy.mkdir(parents=True)
    for filename in ("limits.json", "calibration.json", "orientation.json"):
        (legacy / filename).write_text("{}", encoding="utf-8")
    (legacy / ".limits-machine").touch()  # legacy proof that limits were operator-published

    migrated = profile.migrate_flat_snapshots()

    moved = profile.api_root() / legacy.name
    assert legacy.exists()
    assert moved.exists()
    assert set(migrated) == {"limits", "calibration", "orientation"}


def test_newer_flat_snapshot_is_migrated_during_a_rolling_upgrade(tmp_path):
    profile = _profile(tmp_path)
    _mk_flat_snapshot(profile, "2026-07-01T14-30-00-000000Z")
    profile.migrate_flat_snapshots()
    newer = _mk_flat_snapshot(profile, "2026-07-01T15-00-00-000000Z")
    (newer / "limits.json").write_text('{"limits": "new"}', encoding="utf-8")

    migrated = profile.migrate_flat_snapshots()

    assert migrated["limits"].name == newer.name
    assert json.loads((profile.limits_path()).read_text()) == {"limits": "new"}


def test_origin_writes_append_timestamp_history(tmp_path):
    profile = _profile(tmp_path)
    first = profile.write_origin({"origin": {"x_um": 1}}, moment=_AT_1430)
    second = profile.write_origin({"origin": {"x_um": 9}}, moment=_AT_1500)
    assert first == profile.origin_dir() / format_snapshot_name(_AT_1430) / "origin.json"
    assert second == profile.origin_dir() / format_snapshot_name(_AT_1500) / "origin.json"
    assert first.exists() and second.exists()
    assert profile.origin_path() == second
    assert profile.read_origin()["origin"] == {"x_um": 9}


def test_origin_has_no_seed_default(tmp_path):
    profile = _profile(tmp_path)
    assert profile.read_origin() is None
    assert profile.latest_snapshot("origin") is None


def test_new_snapshot_monotonicity_is_per_subsystem(tmp_path):
    profile = _profile(tmp_path)
    _mk_snapshot(profile, "limits", format_snapshot_name(_AT_1430))
    with pytest.raises(ValueError, match="new limits snapshot"):
        profile.new_snapshot_dir(_AT_1400, "limits")
    assert profile.new_snapshot_dir(_AT_1400, "calibration").parent == profile.subsystem_root(
        "calibration"
    )
    assert profile.new_snapshot_dir(_AT_1500, "limits").name == format_snapshot_name(_AT_1500)


def test_publish_requires_exactly_one_subsystem(tmp_path):
    profile = _profile(tmp_path)
    with pytest.raises(ValueError, match="exactly one"):
        profile.publish_snapshot(_AT_1430)
    with pytest.raises(ValueError, match="exactly one"):
        profile.publish_snapshot(_AT_1430, limits={}, calibration={})


def test_publish_does_not_duplicate_other_subsystems(tmp_path):
    profile = _profile(tmp_path)
    snapshot = profile.publish_snapshot(_AT_1430, limits={"marker": "limits"})
    assert snapshot.parent == profile.subsystem_root("limits")
    assert json.loads((snapshot / "limits.json").read_text()) == {"marker": "limits"}
    assert not (snapshot / ".limits-machine").exists()
    assert list(snapshot.glob("calibration*")) == []
    assert profile.latest_snapshot("calibration") is None
    assert profile.latest_snapshot("orientation") is None


def test_publish_carries_forward_only_within_subsystem(tmp_path):
    profile = _profile(tmp_path)
    first = profile.publish_snapshot(_AT_1430, limits={"marker": "A"})
    second = profile.publish_snapshot(_AT_1500, limits={"marker": "B"})
    assert json.loads((first / "limits.json").read_text()) == {"marker": "A"}
    assert json.loads((second / "limits.json").read_text()) == {"marker": "B"}
    assert sorted(path.name for path in second.iterdir()) == ["limits.json"]


def test_publish_archives_notebook_with_owning_subsystem(tmp_path):
    profile = _profile(tmp_path)
    notebook = tmp_path / "set_limits.ipynb"
    notebook.write_text('{"cells": []}', encoding="utf-8")
    snapshot = profile.publish_snapshot(
        _AT_1430,
        limits={"marker": "limits"},
        notebook_paths=[notebook],
    )
    assert (snapshot / "notebook" / notebook.name).read_text() == '{"cells": []}'


def test_publish_archives_evidence_directory_inside_atomic_snapshot(tmp_path):
    profile = _profile(tmp_path / "programdata")
    evidence = tmp_path / "scope_orientation"
    (evidence / "reports").mkdir(parents=True)
    (evidence / "reports" / "orientation_report.json").write_text(
        '{"rotate_deg": 90}', encoding="utf-8"
    )

    snapshot = profile.publish_snapshot(
        _AT_1430,
        orientation={"rotate_deg": 90},
        archive_paths=[evidence],
    )

    archived = snapshot / evidence.name / "reports" / "orientation_report.json"
    assert archived.read_text(encoding="utf-8") == '{"rotate_deg": 90}'
    assert evidence.is_dir()


def test_fresh_named_calibration_set_seeds_with_no_objectives(tmp_path):
    """A brand-new named set must start empty, not with the bundled seed.

    An operator creates a named set to establish their own reference
    objective; seeding it with the shipped placeholder numbers would lock
    the reference to the placeholder's arbitrary choice. The first measured
    pair anchors the origin instead.
    """
    profile = _profile(tmp_path)
    path = profile.calibration_path("fresh_lens_setup")
    cfg = json.loads(path.read_text(encoding="utf-8"))
    assert cfg["objectives"] == {}
    assert "schema_version" in cfg
    # The default set is equally safe: bundled defaults never pretend to be
    # measurements from this microscope.
    default_cfg = json.loads(profile.calibration_path().read_text(encoding="utf-8"))
    assert default_cfg["objectives"] == {}


def test_named_calibration_sets_copy_forward_inside_calibration_only(tmp_path):
    profile = _profile(tmp_path)
    first = profile.publish_snapshot(
        _AT_1430,
        calibration={"marker": "lens-A"},
        calibration_name="lens_A",
    )
    second = profile.publish_snapshot(_AT_1500, calibration={"marker": "default-B"})
    named = second / "calibrations" / "lens_A" / "calibration.json"
    assert json.loads(named.read_text()) == {"marker": "lens-A"}
    assert profile.calibration_path("lens_A") == named
    assert (first / "calibrations" / "lens_A" / "calibration.json").exists()
    assert profile.latest_snapshot("limits") is None


def test_named_calibration_cannot_be_selected_by_ambient_environment(tmp_path, monkeypatch):
    profile = _profile(tmp_path)
    profile.publish_snapshot(
        _AT_1430,
        calibration={"marker": "lens-A"},
        calibration_name="lens_A",
    )
    snapshot = profile.publish_snapshot(_AT_1500, calibration={"marker": "default"})
    monkeypatch.setenv("ZMART_CALIBRATION_NAME", "lens_A")
    assert profile.calibration_path() == snapshot / "calibration.json"


def test_named_calibration_rejects_path_segments(tmp_path):
    with pytest.raises(ValueError, match="calibration_name"):
        _profile(tmp_path).calibration_path("../escape")


def test_publish_rejects_non_monotonic_time_without_partial(tmp_path):
    profile = _profile(tmp_path)
    profile.publish_snapshot(_AT_1430, calibration={"marker": "A"})
    with pytest.raises(ValueError):
        profile.publish_snapshot(_AT_1400, calibration={"marker": "B"})
    assert not list(profile.subsystem_root("calibration").glob(".*.partial"))


def test_bundled_and_published_calibration_are_loadable(tmp_path):
    from navigator_expert.calibration.core import model

    profile = _profile(tmp_path)
    calibration = model.load_calibration(profile.bundled_default_path("calibration.json"))
    snapshot = profile.publish_snapshot(_AT_1430, calibration=calibration)
    reloaded = model.load_calibration(snapshot / "calibration.json")
    assert reloaded == {"schema_version": 13, "objectives": {}}


def test_programdata_root_precedence(tmp_path, monkeypatch):
    monkeypatch.setenv(machine.PROGRAMDATA_ROOT_ENV, str(tmp_path / "environment"))
    assert MachineProfile().root() == tmp_path / "environment"
    assert MachineProfile(programdata_root=tmp_path / "explicit").root() == tmp_path / "explicit"

"""The bounded frontend state follows publication, never files or array shape."""

from __future__ import annotations

import json

from zmart_live.live_state import LiveStateTracker
from zmart_live.model import ZmartLiveError

from .test_coordinator import some_specimen
from .test_gateway import a_live_run, prepare_without_publishing


def _ranges(tracker: LiveStateTracker) -> set[tuple[tuple[int, int], ...]]:
    return {
        source.committed_time_ranges
        for source in tracker.state.sources
    }


def test_only_the_atomic_marker_advances_bounded_aggregate_sources(tmp_path):
    run = a_live_run(tmp_path)
    tracker = LiveStateTracker(tmp_path)

    assert tracker.state.revision == 0
    assert tracker.state.sources == ()

    prepare_without_publishing(run, "posA", 1700)
    assert tracker.observe() is False
    assert tracker.state.revision == 0

    run.publish("posA")
    assert tracker.observe() is True
    assert tracker.state.revision == 1
    assert {source.role for source in tracker.state.sources} == {
        "non_seamless",
        "seamless",
    }
    assert len(tracker.state.sources) == 2
    assert _ranges(tracker) == {((0, 1),)}


def test_time_availability_comes_from_events_and_preserves_gaps(tmp_path):
    run = a_live_run(tmp_path, timepoints=3)
    run.write_and_publish("posA", some_specimen(700))
    tracker = LiveStateTracker(tmp_path)
    stable_urls = {source.source_id: source.url for source in tracker.state.sources}

    prepare_without_publishing(run, "posA", 2200, moment=2)
    assert tracker.observe() is False
    assert _ranges(tracker) == {((0, 1),)}

    run.publish("posA", timepoint=2)
    assert tracker.observe() is True
    assert _ranges(tracker) == {((0, 1), (2, 3))}
    assert {source.source_id: source.url for source in tracker.state.sources} == stable_urls
    assert {source.revision for source in tracker.state.sources} == {2}


def test_damage_regression_and_foreign_truth_retain_the_last_good_scene(tmp_path):
    run = a_live_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    tracker = LiveStateTracker(tmp_path)
    accepted = tracker.to_json()
    truth = run.manifest.truth
    revision_one = truth.read_text(encoding="utf-8")

    truth.write_text("not json", encoding="utf-8")
    assert tracker.observe() is False
    assert tracker.state.revision == 1
    assert tracker.freshness == "degraded"

    truth.write_text(revision_one, encoding="utf-8")
    assert tracker.observe() is False
    assert tracker.freshness == "current"
    assert tracker.to_json() == accepted

    truth.unlink()
    assert tracker.observe() is False
    assert tracker.state.revision == 1
    assert tracker.freshness == "degraded"
    truth.write_text(revision_one, encoding="utf-8")
    assert tracker.observe() is False
    assert tracker.freshness == "current"

    run.write_and_publish("posB", some_specimen(900))
    assert tracker.observe() is True
    assert tracker.state.revision == 2

    truth.write_text(revision_one, encoding="utf-8")
    assert tracker.observe() is False
    assert tracker.state.revision == 2
    assert tracker.freshness == "degraded"

    foreign = json.loads(revision_one)
    foreign["revision"] = 3
    foreign["run_id"] = "foreign-run"
    truth.write_text(json.dumps(foreign), encoding="utf-8")
    assert tracker.observe() is False
    assert tracker.state.run_id == "gateway-run"
    assert tracker.state.revision == 2


def test_payload_size_depends_on_views_not_position_count(tmp_path):
    run = a_live_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    tracker = LiveStateTracker(tmp_path)
    one = len(json.dumps(tracker.to_json()))

    run.write_and_publish("posB", some_specimen(900))
    assert tracker.observe() is True
    two = len(json.dumps(tracker.to_json()))

    assert len(tracker.state.sources) == 2
    assert two - one < 25


def test_idle_observation_stats_only_the_marker_and_reads_no_history(tmp_path, monkeypatch):
    run = a_live_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    tracker = LiveStateTracker(tmp_path)
    history_read = tracker.history_events_read

    def should_not_read_truth():
        raise AssertionError("unchanged observation parsed committed truth")

    monkeypatch.setattr(tracker.manifest, "committed_strict", should_not_read_truth)
    for _ in range(50):
        assert tracker.observe() is False

    assert tracker.history_events_read == history_read
    assert tracker.fingerprint_checks >= 51


def test_a_transient_failed_read_retries_without_another_marker_change(
    tmp_path, monkeypatch
):
    run = a_live_run(tmp_path)
    run.write_and_publish("posA", some_specimen(700))
    tracker = LiveStateTracker(tmp_path)
    run.write_and_publish("posB", some_specimen(900))

    strict = tracker.manifest.committed_strict
    monkeypatch.setattr(
        tracker.manifest,
        "committed_strict",
        lambda: (_ for _ in ()).throw(ZmartLiveError("temporary share failure")),
    )
    assert tracker.observe() is False
    assert tracker.state.revision == 1
    assert tracker.freshness == "degraded"

    monkeypatch.setattr(tracker.manifest, "committed_strict", strict)
    assert tracker.observe() is True
    assert tracker.state.revision == 2
    assert tracker.freshness == "current"


def test_replacement_generation_advances_both_stable_views_together(tmp_path):
    run = a_live_run(tmp_path, timepoints=2)
    run.write_and_publish("posA", some_specimen(700))
    run.write_and_publish("posA", some_specimen(900), timepoint=1)
    tracker = LiveStateTracker(tmp_path)
    before = {source.source_id: source.url for source in tracker.state.sources}

    replacement = run.replace_a_position("posA", some_specimen(1900), timepoint=1)
    assert replacement.position_generation == 1
    assert tracker.observe() is True

    assert {source.revision for source in tracker.state.sources} == {3}
    assert {source.source_id: source.url for source in tracker.state.sources} == before
    assert _ranges(tracker) == {((0, 2),)}

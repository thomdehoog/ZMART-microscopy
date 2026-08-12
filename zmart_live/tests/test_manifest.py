"""Checking that nothing half-written can ever be seen.

A note on how these tests are written, because it matters more here than usual.

Most of what this record does is *prevent* something, and a test that only checks
an absence is a poor test: "the unfinished position was not visible" passes just
as happily when nothing works at all. Two habits guard against that.

**Every absence is checked beside a presence.** A test that says the unfinished
position is invisible also says, in the same breath, that the finished one is
visible. If the whole mechanism were broken so that nothing ever appeared, the
second half would notice.

**The refusals are sabotaged on purpose.** The separate
``check_the_tests_can_fail`` campaign switches each rule off and requires this
file to go red. That proves the rule is doing the work rather than some accident
of the arrangement. Without it a check can quietly rot into one that cannot
fail, and this project has been caught by that before.

Everything here is small files and no images, so the whole file runs in well
under a second. That is deliberate: a check nobody wants to wait for is a check
that stops being run.
"""

from __future__ import annotations

import json

import pytest

from zmart_live.manifest import (
    CommittedState,
    PublicationRefused,
    RunManifest,
    now_in_words,
)
from zmart_live.model import CommitEvent, ZmartLiveError


def a_finished_position(revision: int, position_id: str = "pos000", **changes):
    """A publication with every prerequisite genuinely checked."""
    settings = {
        "revision": revision,
        "event_type": "position_committed",
        "position_id": position_id,
        "run_id": "run-1",
        "acquisition_type": "overview",
        "acquisition_profile_id": "overview-2304-256",
        "scene_layout_revision": 1,
        "link_revision": 1,
        "channels": ("green",),
        "levels": (0, 1, 2, 3),
        "pyramids_ready": True,
        "links_ready": True,
        "view_ready": True,
        "validated": True,
        "timestamp": now_in_words(),
    }
    settings.update(changes)
    return CommitEvent(**settings)


def a_finished_moment(revision: int, timepoint: int, position_id: str = "pos000"):
    """A moment added to a position that is already in place."""
    return a_finished_position(
        revision,
        position_id,
        event_type="timepoint_committed",
        timepoint=timepoint,
    )


@pytest.fixture
def run(tmp_path):
    return RunManifest.start(tmp_path, run_id="run-1")


class TestNothingIsVisibleUntilItIsPublished:
    """The one promise the whole design rests on."""

    def test_a_fresh_run_shows_nothing(self, run):
        assert run.revision() == 0
        assert run.events() == []

    def test_the_position_generation_survives_json(self):
        event = a_finished_position(
            2,
            event_type="position_replaced",
            position_generation=1,
        )
        assert CommitEvent.from_json(event.to_json()).position_generation == 1

    def test_a_half_written_position_is_refused_while_a_finished_one_is_published(self, run):
        """The load-bearing test, with both arms in it.

        The absence on its own would pass over a completely broken record, so the
        finished position is published in the same test to show the machinery is
        alive.
        """
        unfinished = a_finished_position(1, "pos001", pyramids_ready=False)
        with pytest.raises(PublicationRefused):
            run.publish(unfinished)

        # Nothing moved.
        assert run.revision() == 0
        assert run.revision_of("pos001") == 0

        # And the same call with everything ready does move it.
        run.publish(a_finished_position(1, "pos000"))
        assert run.revision() == 1
        assert run.revision_of("pos000") == 1
        assert run.revision_of("pos001") == 0

    @pytest.mark.parametrize(
        "missing",
        ["pyramids_ready", "links_ready", "view_ready", "validated"],
    )
    def test_every_single_prerequisite_is_load_bearing(self, run, missing):
        """Each of the four gates refuses on its own.

        Testing them only together would let three of them be dead code without
        anybody noticing.
        """
        with pytest.raises(PublicationRefused) as refused:
            run.publish(a_finished_position(1, **{missing: False}))
        assert run.revision() == 0
        # The message has to tell an operator what is actually missing.
        assert str(refused.value).strip() != ""


class TestTheCounterOnlyGoesUp:
    """A viewer that missed a message works out it is behind by comparing numbers."""

    def test_each_publication_advances_it(self, run):
        for revision in (1, 2, 3):
            run.publish(a_finished_position(revision, f"pos{revision:03d}"))
            assert run.revision() == revision

    def test_going_backwards_is_refused(self, run):
        run.publish(a_finished_position(1))
        run.publish(a_finished_position(2, "pos001"))
        with pytest.raises(PublicationRefused):
            run.publish(a_finished_position(2, "pos002"))
        with pytest.raises(PublicationRefused):
            run.publish(a_finished_position(1, "pos003"))
        assert run.revision() == 2

    def test_it_offers_the_right_next_number(self, run):
        assert run.next_revision() == 1
        run.publish(a_finished_position(run.next_revision()))
        assert run.next_revision() == 2


class TestAMomentAddedToAPositionAlreadyInPlace:
    """The failure the whole record was written for.

    Appending a moment changes neither the number of positions nor the length of
    any list, so the older way of noticing — watching a file get longer — cannot
    see it at all.
    """

    def test_a_new_moment_is_noticed_even_though_nothing_else_changed(self, run):
        run.publish(a_finished_position(1, "pos000"))
        before = run.revision()
        listed_before = len(run.committed().by_store)

        run.publish(a_finished_moment(2, timepoint=1, position_id="pos000"))

        assert len(run.committed().by_store) == listed_before  # nothing was added
        assert run.revision() > before  # yet it was noticed
        assert run.revision_of("pos000") == 2

    def test_a_moment_reuses_the_layout_rather_than_making_a_new_one(self, run):
        """Nothing about the arrangement changed, so nothing about it is rewritten."""
        run.publish(a_finished_position(1, "pos000"))
        run.publish(a_finished_moment(2, timepoint=1))
        assert run.committed().layout_revision == 1

    def test_a_moment_must_say_which_moment_it_is(self):
        with pytest.raises(ZmartLiveError):
            a_finished_position(1, event_type="timepoint_committed", timepoint=None)

    def test_a_moment_cannot_be_published_before_its_position(self, run):
        with pytest.raises(PublicationRefused):
            run.publish(a_finished_moment(1, timepoint=0, position_id="pos404"))
        assert run.revision() == 0

    def test_the_same_moment_cannot_be_committed_twice(self, run):
        run.publish(a_finished_position(1, "pos000"))
        run.publish(a_finished_moment(2, timepoint=1, position_id="pos000"))
        with pytest.raises(PublicationRefused):
            run.publish(a_finished_moment(3, timepoint=1, position_id="pos000"))
        assert run.revision() == 2

    def test_the_moment_the_position_arrived_with_cannot_be_committed_again(self, run):
        """Publishing a position without naming a moment publishes its moment zero.

        A later ``timepoint_committed`` naming 0 is therefore the same moment
        again, and letting it through would give that one moment two histories —
        the exact thing the refusal above exists for, hidden behind a spelling
        difference.
        """
        run.publish(a_finished_position(1, "pos000"))
        with pytest.raises(PublicationRefused):
            run.publish(a_finished_moment(2, timepoint=0, position_id="pos000"))
        assert run.revision() == 1
        # The refusal is about that one moment; the next one is welcome.
        run.publish(a_finished_moment(2, timepoint=1, position_id="pos000"))
        assert run.revision() == 2

    def test_a_replaced_moment_still_counts_as_committed(self, run):
        """Superseding a moment does not reopen it for an ordinary commit."""
        run.publish(a_finished_position(1, "pos000"))
        run.publish(
            a_finished_position(
                2,
                "pos000",
                event_type="position_replaced",
                timepoint=0,
                position_generation=1,
            )
        )
        with pytest.raises(PublicationRefused):
            run.publish(a_finished_moment(3, timepoint=0, position_id="pos000"))
        assert run.revision() == 2


class TestACommitCannotChangeWhichRunTheFolderMeans:
    """A plausible event from another microscope run must fail closed."""

    def test_an_event_from_another_run_is_refused(self, run):
        with pytest.raises(PublicationRefused):
            run.publish(a_finished_position(1, run_id="some-other-run"))
        assert run.revision() == 0
        assert run.events() == []

    def test_starting_an_existing_folder_under_another_name_is_refused(self, run, tmp_path):
        run.publish(a_finished_position(1))
        with pytest.raises(PublicationRefused):
            RunManifest.start(tmp_path, run_id="some-other-run")
        assert RunManifest.open(tmp_path).revision() == 1

    def test_a_position_needs_an_explicit_replacement_event(self, run):
        run.publish(a_finished_position(1, "pos000"))
        with pytest.raises(PublicationRefused):
            run.publish(a_finished_position(2, "pos000"))
        run.publish(a_finished_position(2, "pos000", event_type="position_replaced"))
        assert run.revision_of("pos000") == 2


class TestALostMessageDelaysButDoesNotStrand:
    """The counter is the truth; telling the viewer is only a hurry-up."""

    def test_a_viewer_that_heard_nothing_still_finds_out_by_asking(self, run):
        run.publish(a_finished_position(1))
        seen_by_a_viewer = run.revision()

        # Three things are published and every announcement is imagined lost.
        for revision in (2, 3, 4):
            run.publish(a_finished_position(revision, f"pos{revision:03d}"))

        # The viewer simply asks again, as it does anyway, and catches up.
        assert run.revision() > seen_by_a_viewer
        missed = run.events(after=seen_by_a_viewer)
        assert [e.revision for e in missed] == [2, 3, 4]

    def test_the_cheap_glance_moves_only_when_something_is_published(self, run):
        """Asked several times a second, so it must not read the history."""
        before = run.fingerprint()
        assert run.fingerprint() == before  # asking changes nothing
        run.publish(a_finished_position(1))
        assert run.fingerprint() != before


class TestOnlyTheChangedPictureNeedsRefreshing:
    """Refreshing everything has been measured here as thousands of requests."""

    def test_each_position_carries_its_own_number(self, run):
        run.publish(a_finished_position(1, "pos000"))
        run.publish(a_finished_position(2, "pos001"))
        run.publish(a_finished_moment(3, timepoint=1, position_id="pos000"))

        assert run.revision_of("pos000") == 3
        assert run.revision_of("pos001") == 2  # untouched, so unchanged
        assert run.revision_of("pos999") == 0  # never heard of

    def test_a_position_that_did_not_change_keeps_its_number(self, run):
        run.publish(a_finished_position(1, "pos000"))
        settled = run.revision_of("pos000")
        for revision in (2, 3, 4):
            run.publish(a_finished_position(revision, f"other{revision}"))
        assert run.revision_of("pos000") == settled


class TestTheHistoryIsReadSafely:
    """A writer may be partway through a line at the very moment we look."""

    def test_a_line_still_being_written_is_ignored_rather_than_fatal(self, run):
        run.publish(a_finished_position(1))
        with run.history.open("a", encoding="utf-8") as writing:
            writing.write('{"revision": 2, "event_type": "position_com')

        events = run.events()  # must not raise
        assert [e.revision for e in events] == [1]

    def test_damage_anywhere_earlier_is_reported_as_the_fault_it_is(self, run):
        """Lines before the end were finished long ago, so they cannot be mid-write."""
        run.publish(a_finished_position(1))
        run.publish(a_finished_position(2, "pos001"))
        lines = run.history.read_text().splitlines()
        lines[0] = "{ this was never valid"
        run.history.write_text("\n".join(lines) + "\n")

        with pytest.raises(ZmartLiveError) as raised:
            run.events()
        assert "line 1" in str(raised.value)

    def test_a_complete_but_invalid_last_line_is_corruption(self, run):
        """Only a line without its ending can honestly be called mid-write."""
        run.publish(a_finished_position(1))
        with run.history.open("a", encoding="utf-8") as writing:
            writing.write("{ this is invalid but it has finished its line }\n")
        with pytest.raises(ZmartLiveError) as raised:
            run.events()
        assert "line 2" in str(raised.value)

    def test_complete_revisions_have_to_appear_once_and_in_order(self, run):
        run.publish(a_finished_position(1, "pos000"))
        with run.history.open("a", encoding="utf-8") as writing:
            writing.write(json.dumps(a_finished_position(3, "pos002").to_json()) + "\n")

        with pytest.raises(ZmartLiveError, match="jumps from revision 1 to 3"):
            run.events(published_only=False)

    def test_a_failed_tail_parse_does_not_partly_change_the_reader_cache(self, run):
        run.publish(a_finished_position(1, "pos000"))
        first_line = run.history.read_text(encoding="utf-8")
        with run.history.open("a", encoding="utf-8") as writing:
            writing.write(json.dumps(a_finished_position(3, "pos002").to_json()) + "\n")

        reopened = RunManifest.open(run.folder)
        with pytest.raises(ZmartLiveError):
            reopened.events(published_only=False)
        reopened.history.write_text(first_line, encoding="utf-8")

        assert [event.revision for event in reopened.events()] == [1]

    def test_a_history_line_from_another_run_is_corruption(self, run):
        foreign = a_finished_position(1, "pos000", run_id="run-elsewhere")
        run.history.write_text(json.dumps(foreign.to_json()) + "\n", encoding="utf-8")

        with pytest.raises(ZmartLiveError, match="run-elsewhere"):
            RunManifest.open(run.folder).events(published_only=False)

    def test_a_complete_line_is_not_visible_before_the_atomic_commit(self, run):
        run.publish(a_finished_position(1, "pos000"))
        never_published = a_finished_position(2, "pos001")
        with run.history.open("a", encoding="utf-8") as writing:
            writing.write(json.dumps(never_published.to_json()) + "\n")

        assert [event.revision for event in run.events()] == [1]
        with pytest.raises(PublicationRefused):
            run.next_revision()

        run.recover()
        assert [event.revision for event in run.events()] == [1]
        assert run.next_revision() == 2
        run.publish(a_finished_position(2, "pos001"))
        assert [event.revision for event in run.events()] == [1, 2]

    def test_only_the_new_part_matters_when_following_a_long_run(self, run):
        for revision in range(1, 21):
            run.publish(a_finished_position(revision, f"pos{revision:03d}"))
        assert len(run.events(after=17)) == 3
        assert len(run.events()) == 20


class TestPickingUpAfterTheWriterStopped:
    """A run interrupted mid-position must not become a wrong picture."""

    def test_a_line_written_but_never_announced_is_treated_as_unfinished(self, run):
        run.publish(a_finished_position(1, "pos000"))

        # Exactly what a crash between the two steps leaves behind: the history
        # has the line, the small file was never replaced.
        interrupted = a_finished_position(2, "pos001")
        with run.history.open("a", encoding="utf-8") as writing:
            writing.write(json.dumps(interrupted.to_json()) + "\n")

        state = run.recover()
        assert state.revision == 1
        assert run.revision_of("pos001") == 0
        assert (run.bookkeeping / "interrupted.json").exists()
        note = json.loads((run.bookkeeping / "interrupted.json").read_text())
        preserved = note["written_but_never_published"][0]
        assert preserved == interrupted.to_json()

    def test_what_was_already_published_survives_the_interruption(self, run):
        """The safe direction: everything announced stays announced."""
        run.publish(a_finished_position(1, "pos000"))
        run.publish(a_finished_position(2, "pos001"))
        reopened = RunManifest.open(run.folder)
        assert reopened.revision() == 2
        assert reopened.revision_of("pos001") == 2

    def test_starting_again_does_not_wipe_what_was_published(self, run, tmp_path):
        """An interrupted writer coming back must continue, not begin afresh."""
        run.publish(a_finished_position(1, "pos000"))
        again = RunManifest.start(tmp_path, run_id="run-1")
        assert again.revision() == 1
        assert again.revision_of("pos000") == 1

    def test_a_truth_file_ahead_of_its_missing_history_is_not_extended(self, run):
        run.publish(a_finished_position(1, "pos000"))
        run.history.unlink()

        with pytest.raises(PublicationRefused, match="history reaches only 0"):
            run.publish(a_finished_position(2, "pos001"))
        with pytest.raises(PublicationRefused, match="history reaches only 0"):
            run.next_revision()
        with pytest.raises(PublicationRefused, match="history reaches only 0"):
            run.recover()
        assert run.revision() == 1

    def test_a_folder_with_no_record_refuses_to_pretend(self, tmp_path):
        with pytest.raises(ZmartLiveError):
            RunManifest.open(tmp_path / "never-a-run")

    def test_recovery_preserves_then_removes_an_incomplete_history_fragment(self, run):
        run.publish(a_finished_position(1, "pos000"))
        with run.history.open("ab") as writing:
            writing.write(b'{"revision": 2, "event_type": "position_com')

        run.recover()

        note = json.loads((run.bookkeeping / "interrupted.json").read_text())
        assert note["unfinished_history_fragment"].startswith('{"revision": 2')
        assert run.history.read_bytes().endswith(b"\n")
        run.publish(a_finished_position(2, "pos001"))
        assert run.revision() == 2


class TestTheSmallFileIsNeverSeenHalfWritten:
    """Publication is one rename, which the operating system does indivisibly."""

    def test_a_reader_sees_either_the_old_answer_or_the_new_one(self, run):
        run.publish(a_finished_position(1))
        first = json.loads(run.truth.read_text())
        run.publish(a_finished_position(2, "pos001"))
        second = json.loads(run.truth.read_text())
        assert first["revision"] == 1
        assert second["revision"] == 2

    def test_nonsense_in_the_small_file_shows_nothing_rather_than_something_wrong(self, run):
        """Failing towards an empty screen is the safe direction.

        An empty screen is a disappointment somebody will investigate. A picture
        built from unfinished data is a result nobody can spot.
        """
        run.publish(a_finished_position(1))
        run.truth.write_text("this is not json at all")
        assert run.revision() == 0

    def test_both_files_are_pushed_to_the_disk_before_anything_is_announced(self, run, monkeypatch):
        """The one claim here that a test cannot prove outright.

        Pushing to the disk matters only when the power fails: without it the
        operating system may still be holding the contents in memory after the
        rename has happened, so a machine that dies at the wrong moment comes
        back with a record confidently pointing at data that never arrived.

        Cutting the power to a test machine is not something a test suite can do,
        so this checks the next best thing — that the step is actually taken,
        twice, once for the history and once for the small file. Introducing that
        fault on purpose was not caught by anything else in this file, which is
        exactly why the check is written down here.
        """
        from zmart_live import manifest as under_test

        pushes = []
        really_push = under_test.os.fsync

        def watching(handle):
            pushes.append(handle)
            return really_push(handle)

        monkeypatch.setattr(under_test.os, "fsync", watching)
        run.publish(a_finished_position(1))
        assert len(pushes) >= 2

    def test_the_replacement_contents_are_pushed_before_the_rename(self, tmp_path, monkeypatch):
        """Counting flushes is not enough: the relevant one must precede rename."""
        from zmart_live import manifest as under_test

        actions = []
        really_push = under_test.os.fsync
        really_replace = under_test.os.replace

        def watching_push(handle):
            actions.append("push")
            return really_push(handle)

        def watching_replace(source, destination):
            actions.append("replace")
            return really_replace(source, destination)

        monkeypatch.setattr(under_test.os, "fsync", watching_push)
        monkeypatch.setattr(under_test.os, "replace", watching_replace)
        under_test._write_and_replace(tmp_path / "truth.json", "{}")

        replaced_at = actions.index("replace")
        assert "push" in actions[:replaced_at]

    def test_no_leftover_temporary_files_are_abandoned(self, run):
        for revision in (1, 2, 3):
            run.publish(a_finished_position(revision, f"pos{revision}"))
        leftovers = [p.name for p in run.bookkeeping.iterdir() if ".tmp" in p.name]
        assert leftovers == []

    def test_a_writer_refuses_to_overwrite_a_damaged_truth_file(self, run):
        run.publish(a_finished_position(1, "pos000"))
        run.truth.write_text("not json", encoding="utf-8")

        # Readers fail towards an empty screen; writers must not turn that
        # fallback into permission to erase what was published before damage.
        assert run.revision() == 0
        with pytest.raises(PublicationRefused):
            run.publish(a_finished_position(2, "pos001"))
        assert run.truth.read_text(encoding="utf-8") == "not json"

    def test_a_second_writer_cannot_overwrite_the_first_one_mid_commit(self, run):
        from zmart_live.manifest import _one_writer_at_a_time

        other = RunManifest.open(run.folder)
        with _one_writer_at_a_time(run.writer_lock):
            with pytest.raises(PublicationRefused):
                other.publish(a_finished_position(1, "pos001"))
        assert run.revision() == 0


class TestTheRecordSurvivesBeingStored:
    def test_what_is_committed_reads_back_exactly(self):
        state = CommittedState(
            revision=7,
            run_id="run-1",
            by_store={"pos000": 7, "pos001": 4},
            layout_revision=2,
            updated_at=now_in_words(),
        )
        assert CommittedState.from_json(state.to_json()) == state

    def test_a_callers_dictionary_cannot_edit_frozen_committed_state(self):
        counters = {"pos000": 1}
        state = CommittedState(revision=1, run_id="run-1", by_store=counters)
        counters["pos000"] = 99
        assert state.by_store["pos000"] == 1

    def test_every_published_event_reads_back_exactly(self, run):
        original = a_finished_position(1)
        run.publish(original)
        (recovered,) = run.events()
        assert recovered.to_json() == original.to_json()

    def test_a_published_event_names_everything_it_relied_on(self, run):
        """A reader has to be able to pin the exact plan and layout that were used."""
        run.publish(a_finished_position(1))
        (event,) = run.events()
        assert event.acquisition_profile_id
        assert event.scene_layout_revision
        assert event.link_revision
        assert event.ready

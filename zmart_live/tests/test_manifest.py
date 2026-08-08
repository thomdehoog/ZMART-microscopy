"""Checking that nothing half-written can ever be seen.

A note on how these tests are written, because it matters more here than usual.

Most of what this record does is *prevent* something, and a test that only checks
an absence is a poor test: "the unfinished position was not visible" passes just
as happily when nothing works at all. Two habits guard against that.

**Every absence is checked beside a presence.** A test that says the unfinished
position is invisible also says, in the same breath, that the finished one is
visible. If the whole mechanism were broken so that nothing ever appeared, the
second half would notice.

**The refusals are sabotaged on purpose.** For each rule, there is a test that
switches the rule off and confirms the very same situation then goes through.
That is what proves the rule is doing the work, rather than some accident of the
arrangement. Without it a check can quietly rot into one that cannot fail, and
this project has been caught by that before.

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
        "coarse_chunks_ready": True,
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

    def test_a_half_written_position_is_refused_while_a_finished_one_is_published(
        self, run
    ):
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
        ["pyramids_ready", "links_ready", "coarse_chunks_ready", "validated"],
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

    @pytest.mark.parametrize(
        "missing",
        ["pyramids_ready", "links_ready", "coarse_chunks_ready", "validated"],
    )
    def test_sabotage_the_refusal_and_the_very_same_event_goes_through(
        self, run, missing
    ):
        """Proof that the refusal above is what stopped it.

        If this did not publish, the earlier test would be passing for some other
        reason entirely and would tell us nothing.
        """
        run.publish(
            a_finished_position(1, **{missing: False}), allow_incomplete=True
        )
        assert run.revision() == 1


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

        assert len(run.committed().by_store) == listed_before   # nothing was added
        assert run.revision() > before                          # yet it was noticed
        assert run.revision_of("pos000") == 2

    def test_a_moment_reuses_the_layout_rather_than_making_a_new_one(self, run):
        """Nothing about the arrangement changed, so nothing about it is rewritten."""
        run.publish(a_finished_position(1, "pos000"))
        run.publish(a_finished_moment(2, timepoint=1))
        assert run.committed().layout_revision == 1

    def test_a_moment_must_say_which_moment_it_is(self):
        with pytest.raises(ZmartLiveError):
            a_finished_position(1, event_type="timepoint_committed", timepoint=None)


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
        assert run.fingerprint() == before          # asking changes nothing
        run.publish(a_finished_position(1))
        assert run.fingerprint() != before


class TestOnlyTheChangedPictureNeedsRefreshing:
    """Refreshing everything has been measured here as thousands of requests."""

    def test_each_position_carries_its_own_number(self, run):
        run.publish(a_finished_position(1, "pos000"))
        run.publish(a_finished_position(2, "pos001"))
        run.publish(a_finished_moment(3, timepoint=1, position_id="pos000"))

        assert run.revision_of("pos000") == 3
        assert run.revision_of("pos001") == 2     # untouched, so unchanged
        assert run.revision_of("pos999") == 0     # never heard of

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

        events = run.events()                     # must not raise
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
        with run.history.open("a", encoding="utf-8") as writing:
            writing.write(json.dumps(a_finished_position(2, "pos001").to_json()) + "\n")

        state = run.recover()
        assert state.revision == 1
        assert run.revision_of("pos001") == 0
        assert (run.bookkeeping / "interrupted.json").exists()

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

    def test_a_folder_with_no_record_refuses_to_pretend(self, tmp_path):
        with pytest.raises(ZmartLiveError):
            RunManifest.open(tmp_path / "never-a-run")


class TestTheSmallFileIsNeverSeenHalfWritten:
    """Publication is one rename, which the operating system does indivisibly."""

    def test_a_reader_sees_either_the_old_answer_or_the_new_one(self, run):
        run.publish(a_finished_position(1))
        first = json.loads(run.truth.read_text())
        run.publish(a_finished_position(2, "pos001"))
        second = json.loads(run.truth.read_text())
        assert first["revision"] == 1
        assert second["revision"] == 2

    def test_nonsense_in_the_small_file_shows_nothing_rather_than_something_wrong(
        self, run
    ):
        """Failing towards an empty screen is the safe direction.

        An empty screen is a disappointment somebody will investigate. A picture
        built from unfinished data is a result nobody can spot.
        """
        run.publish(a_finished_position(1))
        run.truth.write_text("this is not json at all")
        assert run.revision() == 0

    def test_both_files_are_pushed_to_the_disk_before_anything_is_announced(
        self, run, monkeypatch
    ):
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

    def test_no_leftover_temporary_files_are_abandoned(self, run):
        for revision in (1, 2, 3):
            run.publish(a_finished_position(revision, f"pos{revision}"))
        leftovers = [p.name for p in run.bookkeeping.iterdir() if ".tmp" in p.name]
        assert leftovers == []


class TestTheRecordSurvivesBeingStored:
    def test_what_is_committed_reads_back_exactly(self):
        state = CommittedState(
            revision=7, run_id="run-1", by_store={"pos000": 7, "pos001": 4},
            layout_revision=2, updated_at=now_in_words(),
        )
        assert CommittedState.from_json(state.to_json()) == state

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

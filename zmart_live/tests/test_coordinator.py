"""Checking that readiness is earned by looking, not granted by asking.

The publication record already refuses an event that does not claim readiness.
This file is about the harder question underneath that: whether the claim means
anything. Before the coordinator existed, a caller could set every flag to true
and the record would believe it, so the promise "nothing half-written is ever
visible" rested on the caller's honesty — which is not a property anybody can
test.

So the tests here mostly damage things on purpose. Each one takes a position that
*was* about to be publishable, breaks one thing about it in a way that leaves the
files looking perfectly normal, and checks that publication is refused. Every one
of those is paired with the undamaged case in the same test, because a refusal
that happens for every position regardless would pass a damage test while being
useless.

The damage chosen is deliberately the quiet kind. A missing zoomed-out level and
a chunk cut short do not announce themselves; they are drawn, as an empty region
or as plausible noise, and they look like results.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from zmart_live.coordinator import Inspection, LivePublisher, NotReadyToPublish
from zmart_live.model import GridCell, ZmartLiveError
from zmart_live.profiles import plan_the_writing

# Nine 128-pixel chunks across: the convention, at the smallest size that is
# still the real arrangement rather than a toy.
FRAME = 1152


@pytest.fixture(scope="module")
def profile():
    made, _ = plan_the_writing("overview", frame=FRAME, z_planes=1)
    return made


@pytest.fixture
def run(tmp_path, profile):
    return LivePublisher(
        tmp_path,
        profile,
        run_id="run-1",
        cells={GridCell(0, 0): "posA", GridCell(0, 1): "posB"},
    )


def some_specimen(value: int = 1000) -> np.ndarray:
    return np.full((1, FRAME, FRAME), value, "uint16")


def everything_but_the_commit(run, position_id, pixels=None):
    """Do every step of a publication except the commit at the end.

    Several tests below want a run that is complete on disk and has not been
    made visible, so that they can damage exactly one thing about it and watch
    the refusal. Writing those steps out in each test invited them to drift
    apart, and a test that quietly skips a step is a test that stops measuring
    what it says it measures.
    """
    run.write_a_position(position_id, some_specimen() if pixels is None else pixels)
    so_far = frozenset({position_id})
    run.write_the_seamless_view(so_far)
    run.write_the_raw_overlap_view(so_far)
    run.write_the_link_map(so_far)
    run.write_the_layout()


class TestTheOrderedSequenceWorks:
    """The positive arm that every refusal below is measured against."""

    def test_a_complete_position_is_published(self, run):
        event = run.write_and_publish("posA", some_specimen())
        assert event.validated is True
        assert run.manifest.revision() == 1
        assert run.manifest.revision_of("posA") == 1

    def test_the_second_position_joins_the_first(self, run):
        run.write_and_publish("posA", some_specimen(1000))
        run.write_and_publish("posB", some_specimen(2000))
        assert run.manifest.revision() == 2
        assert run.manifest.revision_of("posA") == 1
        assert run.manifest.revision_of("posB") == 2

    def test_writing_alone_makes_nothing_visible(self, run):
        """Files landing is not publication, however finished they look."""
        run.write_a_position("posA", some_specimen())
        assert run.manifest.revision() == 0
        assert run.manifest.revision_of("posA") == 0


class TestDamageThatWouldNotAnnounceItself:
    """Each of these leaves the run looking entirely normal."""

    def test_a_missing_zoomed_out_level_is_caught(self, run):
        """The quiet failure: complete zoomed in, empty zoomed out."""
        everything_but_the_commit(run, "posA")

        # It would have gone through.
        assert run.inspect("posA").everything_checks_out

        # Now remove one zoomed-out copy and nothing else.
        deepest = max(level.level for level in run.profile.levels)
        import shutil

        shutil.rmtree(run.position_store("posA") / str(deepest))

        found = run.inspect("posA")
        assert not found.everything_checks_out
        assert any("zoomed-out" in note for note in found.complaints)
        with pytest.raises(NotReadyToPublish):
            run.publish("posA")
        assert run.manifest.revision() == 0

    def test_a_chunk_cut_short_is_caught(self, run):
        """A file can exist and hold half a piece, and half a piece decodes."""
        everything_but_the_commit(run, "posA")
        assert run.inspect("posA").everything_checks_out

        level_zero = run.position_store("posA") / "0"
        pieces = [
            p for p in level_zero.rglob("*") if p.is_file() and p.name != "zarr.json"
        ]
        assert pieces, "expected some stored pieces to damage"
        whole = pieces[0].read_bytes()
        pieces[0].write_bytes(whole[: len(whole) // 3])

        found = run.inspect("posA")
        assert not found.everything_checks_out
        with pytest.raises(NotReadyToPublish):
            run.publish("posA")
        assert run.manifest.revision() == 0

    def test_nothing_written_at_all_is_caught(self, run):
        found = run.inspect("posA")
        assert not found.everything_checks_out
        assert any("Nothing has been written" in note for note in found.complaints)

    def test_a_missing_zoomed_out_picture_is_caught(self, run):
        """Complete zoomed in and missing zoomed out is still not complete."""
        run.write_a_position("posA", some_specimen())
        run.write_the_layout()
        found = run.inspect("posA")
        assert not found.everything_checks_out
        assert any("zoomed-out picture" in note for note in found.complaints)

    def test_a_missing_arrangement_is_caught(self, run):
        """A published measurement has to have something to point back at."""
        run.write_a_position("posA", some_specimen())
        run.write_the_seamless_view(frozenset({"posA"}))
        run.write_the_raw_overlap_view(frozenset({"posA"}))
        run.write_the_link_map(frozenset({"posA"}))
        found = run.inspect("posA")
        assert not found.everything_checks_out
        assert not found.layout_ready

    def test_an_unreadable_arrangement_is_caught(self, run):
        everything_but_the_commit(run, "posA")
        (run.folder / "zmart-live" / "layout.json").write_text("not json")
        found = run.inspect("posA")
        assert not found.layout_ready
        with pytest.raises(NotReadyToPublish):
            run.publish("posA")


class TestReadinessCannotBeAsserted:
    """The point of the whole module."""

    def test_there_is_no_way_to_hand_in_a_readiness_flag(self):
        """If this ever fails, somebody has added the hole back."""
        import inspect as looking

        for name in ("publish", "write_and_publish", "inspect"):
            parameters = looking.signature(getattr(LivePublisher, name)).parameters
            for suspicious in (
                "pyramids_ready", "links_ready", "coarse_chunks_ready",
                "validated", "ready", "force", "allow_incomplete",
            ):
                assert suspicious not in parameters, (
                    f"{name}() accepts '{suspicious}', which lets a caller assert "
                    f"readiness instead of earning it"
                )

    def test_the_published_event_carries_what_was_actually_found(self, run):
        event = run.write_and_publish("posA", some_specimen())
        found = run.inspect("posA")
        assert event.pyramids_ready == found.pyramids_ready
        assert event.links_ready == found.links_ready
        assert event.coarse_chunks_ready == found.coarse_chunks_ready

    def test_looking_actually_reads_bytes_rather_than_listing_files(self, run):
        """A count of nothing would mean the check is decorative."""
        run.write_and_publish("posA", some_specimen())
        found = run.inspect("posA")
        assert found.pieces_read > 0
        assert found.ranges_checked > 0
        assert found.coarse_pieces_rebuilt > 0
        assert found.raw_pixels_compared > 0

    def test_an_inspection_that_found_nothing_is_not_ready(self):
        """The record's default has to be the safe one."""
        assert Inspection(position_id="x", timepoint=None).everything_checks_out is False


class TestTheZoomedOutPictureOnlyShowsPublishedWork:
    """The rule that made this slice worth building around."""

    def test_ground_belonging_to_an_unpublished_position_stays_empty(self, run):
        import zarr

        run.write_and_publish("posA", some_specimen(1000))
        # posB's pixels are on disk but it has not been published.
        run.write_a_position("posB", some_specimen(2000))

        view = zarr.open_array(str(run.seamless_store), mode="r")
        placement = run.layout.placement("posB")
        y0 = placement.origin["y"]
        x0 = placement.origin["x"] + placement.visual_source_roi["x"].length - 4
        beyond = view[0, 0, 0, y0:y0 + 4, x0:x0 + 4]
        assert int(beyond.max()) != 2000, (
            "the unpublished position's pixels have reached the zoomed-out picture"
        )

        # And once it is published they do appear, so this cannot pass by the
        # picture being empty everywhere.
        run.write_and_publish("posB", some_specimen(2000))
        view = zarr.open_array(str(run.seamless_store), mode="r")
        after = view[0, 0, 0, y0:y0 + 4, x0:x0 + 4]
        assert int(after.max()) == 2000


def where_the_two_tiles_meet(run) -> tuple[int, int]:
    """The strip of specimen that both posA and posB photographed.

    They sit side by side, so the strip runs from where posB's frame begins to
    where posA's frame ends, measured in the run's own pixels. Inside it, two
    tiles hold two genuinely different measurements of the same place.
    """
    left = run.layout.placement("posA")
    right = run.layout.placement("posB")
    begins = right.origin["x"]
    ends = left.origin["x"] + run.profile.frame_shape["x"]
    assert ends > begins, "these two tiles were expected to share an overlap"
    return begins, ends


class TestTheRawViewKeepsBothMeasurementsOfAnOverlap:
    """The claim this view exists to make.

    Where two tiles meet, the microscope recorded the same piece of specimen
    twice, and the two records need not agree — that disagreement is the whole
    reason somebody opens this view. So the test that matters is not that the
    picture appears, but that *both* measurements can still be read back out of
    it afterwards.
    """

    def test_both_measurements_in_the_overlap_are_recoverable(self, run):
        import zarr

        run.write_and_publish("posA", some_specimen(1000))
        run.write_and_publish("posB", some_specimen(2000))

        begins, ends = where_the_two_tiles_meet(run)
        view = zarr.open_array(str(run.raw_overlap_store), mode="r")
        from_the_left = view[
            run.tile_stop_of("posA"), 0, 0, 0, :, begins:ends
        ]
        from_the_right = view[
            run.tile_stop_of("posB"), 0, 0, 0, :, begins:ends
        ]

        assert sorted(np.unique(from_the_left)) == [1000], (
            "posA's own measurement of the shared strip is not in the raw view"
        )
        assert sorted(np.unique(from_the_right)) == [2000], (
            "posB's own measurement of the shared strip is not in the raw view"
        )

        # And the comparison that makes this second view worth building at all:
        # the seamless view holds one value per place, so over the same strip it
        # can only be showing one of the two tiles. The rows are limited to the
        # ground the seamless view covers — the strip along the mosaic's far edge
        # is handed over by no tile, and this narrow path does not write it.
        seamless = zarr.open_array(str(run.seamless_store), mode="r")
        covered = run.profile.grid_step("y")
        chosen = np.unique(seamless[0, 0, 0, :covered, begins:ends])
        assert len(chosen) == 1 and chosen[0] in (1000, 2000), (
            "in the overlap the seamless view shows one tile's measurement and "
            "not the other's"
        )

    def test_two_tiles_that_meet_are_never_written_to_one_stop(self, run):
        """The property the whole arrangement rests on."""
        import zarr

        run.write_and_publish("posA", some_specimen(1000))
        assert run.tile_stop_of("posA") != run.tile_stop_of("posB")

        view = zarr.open_array(str(run.raw_overlap_store), mode="r")
        assert view.shape[0] == run.tile_stop_count
        assert run.tile_stop_count == 4, (
            "an ordinary mosaic needs two stops along each of y and x, so four "
            "in total, however many positions the run holds"
        )

    def test_a_wider_overlap_asks_for_more_stops(self, tmp_path):
        """The rule is not the chessboard; the chessboard is what it gives here.

        An acquisition whose tiles overlap by more than half a frame has three
        tiles sharing specimen at once, and the number of stops grows to match
        rather than the third measurement being lost.
        """
        from zmart_live.model import AcquisitionProfile, FrozenMap

        crowded = AcquisitionProfile(
            profile_id="crowded",
            acquisition_type="overview",
            axes=("t", "c", "z", "y", "x"),
            frame_shape=FrozenMap({"z": 1, "y": 64, "x": 64}),
            dtype="uint16",
            overlap_pixels=FrozenMap({"y": 48, "x": 48}),
            topology="grid",
        )
        run = LivePublisher(
            tmp_path,
            crowded,
            run_id="run-crowded",
            cells={
                GridCell(0, 0): "posA",
                GridCell(0, 1): "posB",
                GridCell(0, 2): "posC",
            },
        )
        # The stage moves 16 pixels between tiles and a frame is 64 wide, so four
        # tiles in a row can share specimen and four stops are needed on x.
        assert run.tile_stops_per_axis == {"y": 4, "x": 4}
        assert len({run.tile_stop_of(name) for name in ("posA", "posB", "posC")}) == 3

    def test_an_unpublished_position_never_reaches_the_raw_view(self, run):
        """The same rule as the seamless view, for the same reason."""
        import zarr

        run.write_and_publish("posA", some_specimen(1000))
        # posB's pixels are on disk, but nobody has said they are finished.
        run.write_a_position("posB", some_specimen(2000))
        run.write_the_raw_overlap_view(frozenset({"posA"}))

        view = zarr.open_array(str(run.raw_overlap_store), mode="r")
        stop = run.tile_stop_of("posB")
        placement = run.layout.placement("posB")
        y0, x0 = placement.origin["y"], placement.origin["x"]
        theirs = view[stop, 0, 0, 0, y0:y0 + 8, x0:x0 + 8]
        assert int(theirs.max()) != 2000, (
            "an unpublished position's pixels have reached the raw view"
        )

        # And they do arrive once it is published, so this cannot be passing
        # merely because the raw view is empty everywhere.
        run.write_and_publish("posB", some_specimen(2000))
        view = zarr.open_array(str(run.raw_overlap_store), mode="r")
        after = view[stop, 0, 0, 0, y0:y0 + 8, x0:x0 + 8]
        assert int(after.max()) == 2000

    def test_publication_is_refused_while_the_raw_view_is_missing(self, run):
        """Complete everywhere else is still not complete."""
        run.write_a_position("posA", some_specimen())
        run.write_the_seamless_view(frozenset({"posA"}))
        run.write_the_link_map(frozenset({"posA"}))
        run.write_the_layout()

        found = run.inspect("posA")
        assert found.raw_overlap_ready is False
        assert not found.everything_checks_out
        assert any("has not been built yet" in note for note in found.complaints), (
            "an operator should be told the view is missing, which is a different "
            "situation from one that is there and will not read"
        )
        with pytest.raises(NotReadyToPublish):
            run.publish("posA")
        assert run.manifest.revision() == 0

    def test_a_raw_view_that_will_not_read_is_caught(self, run):
        everything_but_the_commit(run, "posA")
        assert run.inspect("posA").everything_checks_out

        pieces = [
            p
            for p in run.raw_overlap_store.rglob("*")
            if p.is_file() and p.name != "zarr.json"
        ]
        assert pieces, "expected the raw view to have stored some pieces"
        whole = pieces[0].read_bytes()
        pieces[0].write_bytes(whole[: len(whole) // 3])

        found = run.inspect("posA")
        assert found.raw_overlap_ready is False
        with pytest.raises(NotReadyToPublish):
            run.publish("posA")
        assert run.manifest.revision() == 0

    def test_a_raw_view_holding_somebody_elses_pixels_is_caught(self, run):
        """The quiet failure: a strip of specimen replaced by another tile's.

        Nothing is damaged and nothing fails to decode. The picture still looks
        like specimen; it is simply no longer this position's record of it. Only
        comparing the view against the position's own store notices.
        """
        import zarr

        everything_but_the_commit(run, "posA", some_specimen(1000))
        assert run.inspect("posA").everything_checks_out

        view = zarr.open_array(str(run.raw_overlap_store), mode="r+")
        view[run.tile_stop_of("posA"), 0, 0, 0, :64, :64] = 2000

        found = run.inspect("posA")
        assert found.raw_overlap_ready is False
        assert found.pyramids_ready is True, (
            "the position's own pixels are untouched, so they must not be blamed"
        )
        with pytest.raises(NotReadyToPublish):
            run.publish("posA")
        assert run.manifest.revision() == 0

    def test_writing_is_refused_rather_than_losing_a_measurement(
        self, run, monkeypatch
    ):
        """The fail-closed guard, exercised by breaking the rule it protects.

        If the way stops are chosen were ever changed so that two overlapping
        tiles landed on the same one, the damage would be silent: one tile's
        measurements simply replaced by its neighbour's. So the writer checks
        instead of assuming, and refuses.
        """
        monkeypatch.setattr(LivePublisher, "tile_stop_of", lambda self, name: 0)
        run.write_a_position("posA", some_specimen(1000))
        with pytest.raises(ZmartLiveError) as refused:
            run.write_the_raw_overlap_view(frozenset({"posA"}))
        assert "erase" in str(refused.value)

    def test_the_viewer_is_told_where_this_store_actually_is(self, run):
        """The scene hands the viewer an address; it has to be this one.

        A scene naming a store that nothing writes produces an empty layer with
        no error anywhere, which is the sort of thing that is noticed weeks
        later.
        """
        from zmart_live.scene import build_the_scene

        scene = build_the_scene(run.profile, run.layout, channels=run.channels)
        raw = next(image for image in scene.images if image.role == "non_seamless")
        assert run.folder / raw.path == run.raw_overlap_store
        assert raw.selector_axis == "tile", (
            "the scene's tile selector is the dimension this store is written with"
        )


class TestTheRunIsDescribedHonestly:
    def test_the_stored_arrangement_matches_the_one_in_memory(self, run):
        run.write_and_publish("posA", some_specimen())
        stored = json.loads(
            (run.folder / "zmart-live" / "layout.json").read_text()
        )
        assert stored == run.layout.to_json()

    def test_a_position_the_run_does_not_have_is_refused(self, run):
        """Naming a position the mosaic does not contain is a caller mistake,
        and it is refused rather than quietly writing an orphan image."""
        with pytest.raises(ZmartLiveError) as refused:
            run.write_a_position("posZ", some_specimen())
        assert "posZ" in str(refused.value)


class TestEachCheckStandsOnItsOwn:
    """Written after the fault check found three claims nobody was making.

    Every flag on the inspection is read separately by whatever builds the
    publication event, so a flag that is wrong while the overall answer is right
    is a real fault. Testing only ``everything_checks_out`` hid that: a single
    flag could be hard-coded true and nothing noticed.
    """

    def test_damaged_pixels_are_blamed_on_the_pixels(self, run):
        """And specifically not on the pointers or the arrangement.

        The damage is done to a zoomed-out level that is stored as loose pieces
        rather than bundled, because damage to a bundle breaks its little table
        as well and would be caught by the pointer check instead. That is what
        makes this test isolate the reading of pixels.
        """
        everything_but_the_commit(run, "posA")
        assert run.inspect("posA").pyramids_ready

        unbundled = next(
            level for level in run.profile.levels if level.shard is None
        )
        pieces = [
            p
            for p in (run.position_store("posA") / str(unbundled.level)).rglob("*")
            if p.is_file() and p.name != "zarr.json"
        ]
        assert pieces, "expected loose pieces at an unbundled level"
        pieces[0].write_bytes(b"\x00\x01\x02")

        found = run.inspect("posA")
        assert found.pyramids_ready is False
        assert found.layout_ready is True, (
            "damaged pixels must not be reported as a damaged arrangement"
        )
        assert found.raw_overlap_ready is True, (
            "a damaged zoomed-out copy must not be reported as a damaged raw "
            "overlap view; the raw view is built from level zero and is untouched"
        )

    def test_the_pieces_read_count_comes_from_actually_reading(self, run):
        """If it came from the description, the read could be deleted unnoticed."""
        run.write_and_publish("posA", some_specimen())
        found = run.inspect("posA")
        level_zero = run.profile.level(0)
        # At least one full plane of values, which no amount of metadata
        # inspection would produce on its own.
        assert found.pieces_read >= level_zero.inner_chunk["y"] * level_zero.inner_chunk["x"]
        # The same argument for the raw overlap view: the comparison covers this
        # position's whole frame, overlap included, so anything smaller means
        # part of it was never looked at.
        whole_frame = (
            run.profile.frame_shape["y"] * run.profile.frame_shape["x"]
        )
        assert found.raw_pixels_compared >= whole_frame

    def test_a_pointer_to_the_wrong_bytes_is_caught(self, run, monkeypatch):
        """The failure that produces a picture rather than an error.

        The resolver is made to hand back the byte range of a *different* piece.
        Everything still decodes, no length is wrong and no file is damaged; the
        image simply shows a different part of the specimen. Nothing else in this
        module would notice, which is why the coordinator decodes what it is
        given and compares it rather than trusting the range it was handed.
        """
        from zmart_live import coordinator as under_test
        from zmart_live.shardlink import where_one_chunk_lives as really_find

        everything_but_the_commit(run, "posA", some_specimen(1000))
        assert run.inspect("posA").links_ready, "should be sound before meddling"

        # Give one corner genuinely different pixels, so that pointing at the
        # wrong piece is a difference somebody could see.
        import zarr

        array = zarr.open_array(str(run.position_store("posA") / "0"), mode="r+")
        array[0, 0, 0, : array.chunks[3], : array.chunks[4]] = 4242

        def hands_back_a_neighbour(path, coordinate):
            """Answer every request with the first piece's bytes."""
            return really_find(path, tuple(0 for _ in coordinate))

        monkeypatch.setattr(under_test, "where_one_chunk_lives", hands_back_a_neighbour)

        found = run.inspect("posA")
        assert found.links_ready is False, (
            "a pointer resolving to another piece decodes perfectly well, so "
            "nothing but comparing the pixels can catch it"
        )
        with pytest.raises(NotReadyToPublish):
            run.publish("posA")


# ---------------------------------------------------------------------------
# What an adversarial reading of this module turned up
# ---------------------------------------------------------------------------
#
# Everything below was written by first reproducing a fault and watching the
# test fail, and only afterwards changing the coordinator. Each docstring says
# what the run actually did before the fix, because that is the part a reader
# cannot recover from the code once it has been put right.


class TestOneMomentAtATimeIsWhatGetsChecked:
    """A publication names a position *and* a moment, so both must be looked at.

    A timelapse writes the same position over and over, once per moment, and
    each of those moments is published on its own. The check in front of that
    publication therefore has to be about that moment and no other.
    """

    def test_a_moment_nobody_wrote_cannot_be_published(self, tmp_path, profile):
        """Reproduced before the fix: an entirely unwritten moment was published.

        ``inspect(position, timepoint=1)`` did not look at moment 1 at all. It
        read the whole array back, and a store politely hands back its fill value
        for any piece it never held, so a moment for which not one byte had been
        written read as a perfectly good picture of empty specimen. The run's
        counter moved from 1 to 2 and the record said moment 1 was finished.
        """
        run = LivePublisher(
            tmp_path,
            profile,
            run_id="run-moments",
            cells={GridCell(0, 0): "posA", GridCell(0, 1): "posB"},
            timepoints=2,
        )
        run.write_and_publish("posA", some_specimen(1000))
        assert run.manifest.revision() == 1

        # Moment 0 is finished; moment 1 has never been written at all.
        assert run.inspect("posA", timepoint=0).everything_checks_out
        found = run.inspect("posA", timepoint=1)
        assert found.pyramids_ready is False, (
            "moment 1 holds no stored pieces at all, so nothing about it is ready"
        )
        assert not found.everything_checks_out
        with pytest.raises(NotReadyToPublish):
            run.publish("posA", timepoint=1)
        assert run.manifest.revision() == 1

    def test_a_moment_that_was_written_can_be_published(self, tmp_path, profile):
        """The positive arm: the refusal above must not refuse everything."""
        run = LivePublisher(
            tmp_path,
            profile,
            run_id="run-moments-2",
            cells={GridCell(0, 0): "posA", GridCell(0, 1): "posB"},
            timepoints=2,
        )
        run.write_and_publish("posA", some_specimen(1000))
        event = run.write_and_publish("posA", some_specimen(1500), timepoint=1)
        assert event.event_type == "timepoint_committed"
        assert event.timepoint == 1
        assert run.manifest.revision() == 2


class TestReadinessIsMeasuredAgainstTheRealPixels:
    """Four ways a run said it was ready when it was not."""

    def test_a_chunk_missing_from_the_middle_of_a_level_is_caught(self, run):
        """Reproduced before the fix: a deleted middle piece changed nothing.

        Reading a level back cannot tell an absent piece from a piece full of
        legitimate empty ground, because the store returns the same numbers for
        both. Deleting one whole valid piece out of the middle of the first
        zoomed-out level therefore left inspection completely satisfied, and a
        viewer would have drawn a black square in the middle of the specimen.
        """
        run.write_and_publish("posA", some_specimen(1000))
        assert run.inspect("posA").everything_checks_out

        level_one = run.position_store("posA") / "1"
        pieces = sorted(
            p for p in level_one.rglob("*") if p.is_file() and p.name != "zarr.json"
        )
        assert len(pieces) > 2, "expected the first zoomed-out level to be in pieces"
        pieces[len(pieces) // 2].unlink()

        found = run.inspect("posA")
        assert found.pyramids_ready is False, (
            "a piece that was never stored is not the same thing as a piece full "
            "of empty ground, and only asking the store which pieces it holds "
            "can tell them apart"
        )

    def test_a_seamless_picture_of_nothing_but_zeros_is_caught(self, run):
        """Reproduced before the fix: a black overview passed as ready.

        The check asked only whether a small corner of the picture had a non-zero
        *size* — that is, whether the array reached that far — and never looked at
        the pixels. Writing zeros over the entire seamless view left
        ``coarse_chunks_ready`` true, and the position published happily with a
        completely black overview.
        """
        import zarr

        run.write_and_publish("posA", some_specimen(1000))
        assert run.inspect("posA").everything_checks_out

        view = zarr.open_array(str(run.seamless_store), mode="r+")
        view[...] = 0

        found = run.inspect("posA")
        assert found.coarse_chunks_ready is False, (
            "the seamless picture has to be compared against this position's own "
            "pixels; its mere existence says nothing at all"
        )
        assert found.pyramids_ready is True, (
            "the position's own store is untouched, so it must not be blamed"
        )

    def test_a_stored_arrangement_from_another_run_is_caught(self, run):
        """Reproduced before the fix: any well-formed layout was accepted.

        The check parsed the file and stopped there, so an arrangement belonging
        to an entirely different run — different run identity, different storage
        plan, different revision number — was read back without complaint and
        treated as this run's. Every measurement published afterwards would have
        pointed at somebody else's account of who owns what.
        """
        run.write_and_publish("posA", some_specimen(1000))
        stored = run.folder / "zmart-live" / "layout.json"

        for changed, why in (
            ({"run_id": "somebody-elses-run"}, "run"),
            ({"profile_id": "a-different-storage-plan"}, "storage plan"),
            ({"revision": run.layout.revision + 7}, "revision"),
        ):
            stored.write_text(json.dumps(run.layout.to_json() | changed, indent=2))
            found = run.inspect("posA")
            assert found.layout_ready is False, (
                f"an arrangement whose {why} does not match this run must be refused"
            )

        # The untouched arrangement is accepted again, so this cannot be passing
        # by refusing everything put in front of it.
        run.write_the_layout()
        assert run.inspect("posA").layout_ready is True

    def test_the_pointers_are_written_down_and_then_followed(self, run):
        """Reproduced before the fix: readiness was claimed with no map at all.

        Nothing anywhere created or stored a map saying which position's bytes
        answer for which piece of the overview, and the check looked at two
        corner pieces of each level and no further. ``links_ready`` was published
        as true on the strength of that.
        """
        run.write_and_publish("posA", some_specimen(1000))
        written_down = run.link_map_file
        assert written_down.is_file(), (
            "a run claiming its pointers are ready has to have written the map "
            "those pointers live in"
        )

        found = run.inspect("posA")
        assert found.links_ready is True
        # Every piece this position supplies at full resolution, at the very
        # least. Two corner pieces of each level are not the pointers a viewer
        # would actually be served from.
        at_full_resolution = (
            run.profile.grid_step("y") // run.profile.level(0).inner_chunk["y"]
        ) * (run.profile.grid_step("x") // run.profile.level(0).inner_chunk["x"])
        assert found.ranges_checked > at_full_resolution, (
            f"only {found.ranges_checked} pointers were followed, and this "
            f"position supplies {at_full_resolution} pieces at full resolution "
            f"alone"
        )

        written_down.unlink()
        assert run.inspect("posA").links_ready is False, (
            "with no map on disk there is nothing for the claim to be about"
        )

    def test_a_map_of_pointers_from_another_run_is_caught(self, run):
        """A map that parses is not automatically this run's map."""
        run.write_and_publish("posA", some_specimen(1000))
        stored = json.loads(run.link_map_file.read_text())
        stored["run_id"] = "somebody-elses-run"
        run.link_map_file.write_text(json.dumps(stored, indent=2))
        assert run.inspect("posA").links_ready is False


class TestTheOuterEdgeOfTheMosaicSurvives:
    """Trimming every tile alike leaves strips that somebody has to write."""

    def test_a_lone_tile_reaches_the_seamless_picture_whole(self, tmp_path, profile):
        """Reproduced before the fix: a fifth of every edge tile was black.

        Every tile hands its far strip to the neighbour beyond it, and a tile
        with no neighbour beyond it has nobody to hand it to. Those strips were
        meant to be written instead, and the function that works out exactly
        which strips they are was never called by anything except its own tests.
        A single 1152 by 1152 tile therefore committed a seamless picture holding
        only 1024 by 1024 real pixels, the rest of it black, and inspection was
        perfectly satisfied.
        """
        import zarr

        run = LivePublisher(
            tmp_path, profile, run_id="run-lone", cells={GridCell(0, 0): "posA"}
        )
        run.write_and_publish("posA", some_specimen(1000))

        view = zarr.open_array(str(run.seamless_store), mode="r")
        whole = view[0, 0, 0]
        assert whole.shape == (FRAME, FRAME)
        assert int(whole.min()) == 1000, (
            "the strips along the mosaic's outer edge belong to this tile and to "
            "nobody else, so they have to be written rather than left empty"
        )

    def test_the_far_side_of_a_two_tile_mosaic_is_written(self, run):
        """The same claim where there is also a seam to get wrong."""
        import zarr

        run.write_and_publish("posA", some_specimen(1000))
        run.write_and_publish("posB", some_specimen(2000))

        view = zarr.open_array(str(run.seamless_store), mode="r")
        reach_y, reach_x = run._mosaic_extent()
        whole = view[0, 0, 0, :reach_y, :reach_x]
        assert int(whole.min()) > 0, (
            "these two tiles cover the whole of the mosaic's own extent, so no "
            "part of it should still be empty once both are published"
        )
        # And the seam is still where ownership put it: posA keeps its first step
        # and hands the rest to posB.
        step = run.profile.grid_step("x")
        assert int(view[0, 0, 0, 0, step - 1]) == 1000
        assert int(view[0, 0, 0, 0, step]) == 2000


class TestEveryPlaneAndEveryColourIsItsOwn:
    def test_a_whole_stack_reaches_the_seamless_picture(self, tmp_path):
        """Reproduced before the fix: only the first plane survived.

        The seamless store was created with its depth written in as ``1``, so a
        three-plane stack published its first plane and silently dropped the
        other two. The position's own store and the raw overlap view held all
        three, inspection passed, and the record committed the position.
        """
        import zarr

        stack, _ = plan_the_writing("overview", frame=FRAME, z_planes=3)
        run = LivePublisher(
            tmp_path, stack, run_id="run-stack", cells={GridCell(0, 0): "posA"}
        )
        pixels = np.stack(
            [np.full((FRAME, FRAME), value, "uint16") for value in (111, 222, 333)]
        )
        run.write_and_publish("posA", pixels)

        view = zarr.open_array(str(run.seamless_store), mode="r")
        assert view.shape[2] == 3, "the overview has to be as deep as the stack"
        for plane, value in enumerate((111, 222, 333)):
            assert set(np.unique(view[0, 0, plane])) == {value}

    def test_one_colours_pixels_are_not_copied_into_every_colour(
        self, tmp_path, profile
    ):
        """Reproduced before the fix: two colours held identical pixels.

        A run recording two colours was handed one stack of planes, and the
        writer put that same stack into both colours. Nothing complained, and the
        red channel of the published position was simply a copy of the green one.
        """
        run = LivePublisher(
            tmp_path,
            profile,
            run_id="run-colours",
            cells={GridCell(0, 0): "posA"},
            channels=("green", "red"),
        )
        with pytest.raises(ZmartLiveError) as refused:
            run.write_a_position("posA", some_specimen(1000))
        assert "colour" in str(refused.value)

    def test_each_colour_keeps_the_pixels_it_was_given(self, tmp_path, profile):
        import zarr

        run = LivePublisher(
            tmp_path,
            profile,
            run_id="run-colours-2",
            cells={GridCell(0, 0): "posA"},
            channels=("green", "red"),
        )
        run.write_and_publish(
            "posA", np.stack([some_specimen(1000), some_specimen(2000)])
        )
        source = zarr.open_array(str(run.position_store("posA") / "0"), mode="r")
        assert set(np.unique(source[0, 0])) == {1000}
        assert set(np.unique(source[0, 1])) == {2000}
        view = zarr.open_array(str(run.seamless_store), mode="r")
        assert set(np.unique(view[0, 0, 0, :FRAME, :FRAME])) == {1000}
        assert set(np.unique(view[0, 1, 0, :FRAME, :FRAME])) == {2000}


class TestPublishedPixelsStayAsTheyWerePublished:
    """What somebody has been shown cannot quietly become something else."""

    def test_a_committed_moment_cannot_be_written_over(self, run):
        """Reproduced before the fix: two readers, one revision, two answers.

        Publishing 'posA' with the value 1000 and then simply calling
        ``write_a_position`` again for the same moment with 2000 changed the
        position's own store to 2000 while the copied seamless view still held
        1000. Both belonged to the same published revision, so a viewer and an
        analysis reading that one revision saw different specimen, and nothing
        anywhere recorded that anything had changed.
        """
        import zarr

        run.write_and_publish("posA", some_specimen(1000))
        with pytest.raises(ZmartLiveError) as refused:
            run.write_a_position("posA", some_specimen(2000))
        assert "posA" in str(refused.value)

        source = zarr.open_array(str(run.position_store("posA") / "0"), mode="r")
        assert int(source[0, 0, 0].max()) == 1000
        view = zarr.open_array(str(run.seamless_store), mode="r")
        assert int(view[0, 0, 0, :8, :8].max()) == 1000

    def test_a_moment_nobody_has_seen_may_still_be_rewritten(self, run):
        """The refusal is about what has been shown, not about writing at all."""
        import zarr

        run.write_a_position("posA", some_specimen(1000))
        run.write_a_position("posA", some_specimen(2000))
        source = zarr.open_array(str(run.position_store("posA") / "0"), mode="r")
        assert int(source[0, 0, 0].max()) == 2000

    def test_replacing_a_position_is_explicit_and_keeps_what_came_before(self, run):
        """The one way published pixels may be superseded."""
        import zarr

        run.write_and_publish("posA", some_specimen(1000))
        event = run.replace_a_position("posA", some_specimen(2000))

        assert event.event_type == "position_replaced"
        assert run.manifest.revision() == 2

        kept = zarr.open_array(
            str(run.position_store("posA", generation=0) / "0"), mode="r"
        )
        assert int(kept[0, 0, 0].max()) == 1000, (
            "the pixels somebody was shown under revision 1 are still there"
        )
        now = zarr.open_array(str(run.position_store("posA") / "0"), mode="r")
        assert int(now[0, 0, 0].max()) == 2000
        view = zarr.open_array(str(run.seamless_store), mode="r")
        assert int(view[0, 0, 0, :8, :8].max()) == 2000, (
            "both pictures move together, under one new revision"
        )

    def test_there_is_nothing_to_replace_until_something_was_published(self, run):
        run.write_a_position("posA", some_specimen(1000))
        with pytest.raises(ZmartLiveError) as refused:
            run.replace_a_position("posA", some_specimen(2000))
        assert "never been published" in str(refused.value)

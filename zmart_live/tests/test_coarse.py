"""Checking the zoomed-out picture never shows an unfinished position.

This is the gap the browser test deliberately left open. That test wrote its run
with no zoomed-out copies at all, because a single zoomed-out piece covers both
positions and there was no honest answer to give for it while one of them was
still being written. The claim was clearer tested on its own, which is what this
file does.

The failure being guarded against is worth stating plainly. Zoom far enough out
and one stored piece of the picture covers several positions. If that piece is
built from everything on disk, then a position that is still being written
appears in it — quietly, at low magnification, where nobody is looking closely.
It does not look like an error. It looks like specimen.
"""

from __future__ import annotations

import pytest

from zmart_live.coarse import (
    CoarseChunk,
    chunks_touched_by,
    contributors_to,
    rebuild_after_committing,
    what_a_chunk_should_hold,
)
from zmart_live.model import (
    AcquisitionProfile,
    GridCell,
    Interval,
    LevelGeometry,
    ZmartLiveError,
)
from zmart_live.ownership import place_the_tiles


def a_plan(frame: int = 90, overlap: int = 10, chunk: int = 10, levels: int = 5):
    """A small mosaic plan shaped like a real one, with a few zoom levels.

    Five levels rather than four, and the reason is the whole subject of this
    file. A single 90-pixel tile is only worth keeping four zoomed-out copies of
    — halve it again and the copy is smaller than one stored piece. But the
    *mosaic* is much larger than any one tile, so the run-wide picture needs
    levels beyond what a tile keeps, and it is precisely at those levels that one
    stored piece starts covering several positions at once.

    With four levels the pieces come out exactly one grid step wide and nothing
    is ever shared, so a test built that way would quietly stop exercising the
    situation it was written for. That happened while writing this, which is why
    the class below opens by checking that a shared piece exists at all.
    """
    return AcquisitionProfile(
        profile_id="test",
        acquisition_type="overview",
        axes=("t", "c", "z", "y", "x"),
        frame_shape={"z": 1, "y": frame, "x": frame},
        dtype="uint16",
        overlap_pixels={"y": overlap, "x": overlap},
        topology="grid",
        levels=tuple(
            LevelGeometry(
                level=level,
                downsampling={"y": 2**level, "x": 2**level},
                inner_chunk={"y": chunk, "x": chunk},
                # This file tests physical coarse-piece ownership, not virtual
                # routing. Mark a level linkable only when the newer strict
                # frame/overlap/step rule genuinely holds.
                linkable=(
                    frame % (chunk * 2**level) == 0
                    and overlap % (chunk * 2**level) == 0
                    and (frame - overlap) % (chunk * 2**level) == 0
                ),
            )
            for level in range(levels)
        ),
    )


def a_square_of(rows: int, columns: int):
    return {
        GridCell(row, column): f"pos{row}{column}"
        for row in range(rows)
        for column in range(columns)
    }


@pytest.fixture
def mosaic():
    profile = a_plan()
    placements = place_the_tiles(profile, a_square_of(2, 2))
    return profile, placements


class TestAPieceReallyDoesCoverSeveralPositions:
    """The difficulty is real, so show it before guarding against it."""

    def test_zoomed_right_in_no_piece_is_shared(self, mosaic):
        """At full resolution the tidiness of the rest of the design still holds."""
        profile, placements = mosaic
        shared = [
            piece
            for piece in chunks_touched_by(profile, placements[0], level=0)
            if len(contributors_to(profile, piece, placements)) > 1
        ]
        assert shared == []

    def test_zoomed_far_enough_out_one_piece_covers_them_all(self, mosaic):
        """And here is the problem this module exists for."""
        profile, placements = mosaic
        deepest = max(level.level for level in profile.levels)
        crowded = [
            piece
            for piece in chunks_touched_by(profile, placements[0], level=deepest)
            if len(contributors_to(profile, piece, placements)) > 1
        ]
        assert crowded, (
            "if no piece is shared at the coarsest level, this test is no longer "
            "exercising the situation it was written for"
        )


class TestAnUnfinishedPositionNeverAppears:
    """The load-bearing claim, with both arms in every test."""

    def test_a_shared_piece_shows_the_committed_one_and_not_the_other(self, mosaic):
        profile, placements = mosaic
        deepest = max(level.level for level in profile.levels)
        piece = next(
            p
            for p in chunks_touched_by(profile, placements[0], level=deepest)
            if len(contributors_to(profile, p, placements)) > 1
        )

        allowed = what_a_chunk_should_hold(
            profile, piece, placements, committed=frozenset({"pos00"})
        )
        names = {p.position_id for p in allowed}

        assert "pos00" in names, "the finished position must be shown"
        assert "pos01" not in names, "the unfinished one must not"
        assert "pos11" not in names

    def test_when_the_second_one_commits_the_piece_shows_both(self, mosaic):
        """The other arm: the ground fills in rather than staying empty for ever."""
        profile, placements = mosaic
        deepest = max(level.level for level in profile.levels)
        piece = next(
            p
            for p in chunks_touched_by(profile, placements[0], level=deepest)
            if len(contributors_to(profile, p, placements)) > 1
        )

        before = what_a_chunk_should_hold(
            profile, piece, placements, committed=frozenset({"pos00"})
        )
        after = what_a_chunk_should_hold(
            profile, piece, placements, committed=frozenset({"pos00", "pos01"})
        )
        assert len(after) > len(before)
        assert {p.position_id for p in after} >= {"pos00", "pos01"}

    def test_with_nothing_committed_a_piece_shows_nothing(self, mosaic):
        """Empty ground is the truth: that specimen has not finished imaging."""
        profile, placements = mosaic
        deepest = max(level.level for level in profile.levels)
        piece = chunks_touched_by(profile, placements[0], level=deepest)[0]
        assert what_a_chunk_should_hold(profile, piece, placements, committed=frozenset()) == ()

    def test_a_position_written_but_not_committed_is_indistinguishable_from_absent(self, mosaic):
        """The whole point, stated as an equality.

        Whether the second position exists on disk or has not been started makes
        no difference to what the zoomed-out picture may show. If these two ever
        differ, unfinished data has become visible.
        """
        profile, placements = mosaic
        deepest = max(level.level for level in profile.levels)
        piece = chunks_touched_by(profile, placements[0], level=deepest)[0]

        written_but_not_committed = what_a_chunk_should_hold(
            profile, piece, placements, committed=frozenset({"pos00"})
        )
        never_written_at_all = what_a_chunk_should_hold(
            profile,
            piece,
            tuple(p for p in placements if p.position_id == "pos00"),
            committed=frozenset({"pos00"}),
        )
        assert [p.position_id for p in written_but_not_committed] == [
            p.position_id for p in never_written_at_all
        ]


class TestOnlyTheRightPiecesAreDisturbed:
    """Too many is wasted work on the microscope's critical path; too few leaves
    a gap that looks like specimen rather than like a fault."""

    def test_a_position_disturbs_the_pieces_covering_its_own_ground(self, mosaic):
        profile, placements = mosaic
        arriving = placements[0]
        touched = chunks_touched_by(profile, arriving, level=0)
        owned = arriving.visual_source_roi.shifted(arriving.origin)
        for piece in touched:
            assert piece.covers(profile, {"y": 10, "x": 10}).overlaps(owned)

    def test_a_position_disturbs_nothing_belonging_only_to_a_distant_neighbour(self):
        """At full resolution a far-off tile shares no piece at all."""
        profile = a_plan()
        placements = place_the_tiles(profile, a_square_of(1, 4))
        first = chunks_touched_by(profile, placements[0], level=0)
        last = chunks_touched_by(profile, placements[-1], level=0)
        assert set(first).isdisjoint(set(last))

    def test_the_piece_holding_the_last_pixel_is_named_and_no_further_one_is(self):
        """Half-open regions make an off-by-one here very easy, and it would show
        up as one stale strip of picture at every tile boundary."""
        profile = a_plan(frame=90, overlap=10, chunk=10)
        placements = place_the_tiles(profile, a_square_of(1, 1))
        touched = chunks_touched_by(profile, placements[0], level=0)
        # One tile keeps 80 pixels, which is exactly eight pieces of ten.
        across = sorted({piece.index[1] for piece in touched})
        assert across == list(range(8))

    def test_fewer_pieces_are_disturbed_the_further_out_you_zoom(self, mosaic):
        """Which is what keeps the work a commit brings with it bounded."""
        profile, placements = mosaic
        counts = [len(chunks_touched_by(profile, placements[0], level=level)) for level in range(5)]
        assert counts == sorted(counts, reverse=True)
        assert counts[0] > counts[-1]


class TestTheWorkOneCommitBringsWithIt:
    """A commit is not free, and the record of what it costs is what stops a
    neighbour being quietly erased."""

    def test_it_names_the_already_published_neighbours_that_share_a_piece(self, mosaic):
        """Rebuilding a shared piece without putting the neighbours back would
        erase them from the zoomed-out view, while leaving them perfectly visible
        zoomed in — a difference nobody would think to look for."""
        profile, placements = mosaic
        work = rebuild_after_committing(
            profile, placements, "pos01", committed=frozenset({"pos00"})
        )
        deepest = max(item.level for item in work)
        shared = next(item for item in work if item.level == deepest)
        assert "pos00" in shared.shared_with

    def test_the_first_position_of_a_run_shares_with_nobody(self, mosaic):
        """The other arm, so the test above cannot pass by naming everything."""
        profile, placements = mosaic
        work = rebuild_after_committing(profile, placements, "pos00", committed=frozenset())
        assert all(item.shared_with == () for item in work)

    def test_a_position_is_never_listed_as_its_own_neighbour(self, mosaic):
        """Even when the caller includes it in the committed set by mistake.

        ``shared_with`` answers "whose already-published pixels must I put back
        into these pieces". The position being committed is not one of those —
        its pixels are the thing being added. Listing it would have a caller do
        the same work twice, and worse, would make a run of one position look as
        though it had a neighbour to preserve.

        The mistaken call is the interesting one, because passing the full
        committed set including the new position is the obvious thing to do if
        you have not read the docstring closely.
        """
        profile, placements = mosaic
        careless = rebuild_after_committing(
            profile,
            placements,
            "pos01",
            committed=frozenset({"pos00", "pos01"}),  # pos01 wrongly included
        )
        for item in careless:
            assert "pos01" not in item.shared_with

        # And the neighbour that genuinely is published still appears, so this
        # cannot pass by returning nothing at all.
        deepest = max(item.level for item in careless)
        shared = next(item for item in careless if item.level == deepest)
        assert "pos00" in shared.shared_with

    def test_it_covers_every_level_the_plan_declares(self, mosaic):
        profile, placements = mosaic
        work = rebuild_after_committing(profile, placements, "pos00", committed=frozenset())
        assert [item.level for item in work] == [level.level for level in profile.levels]

    def test_the_work_is_reported_so_it_can_be_budgeted(self, mosaic):
        """The architecture record puts this on the acquisition's critical path,
        so somebody has to be able to see how much of it there is."""
        profile, placements = mosaic
        work = rebuild_after_committing(profile, placements, "pos00", committed=frozenset())
        assert sum(item.how_much_work for item in work) > 0
        assert work[0].how_much_work >= work[-1].how_much_work

    def test_a_position_that_is_not_in_the_layout_is_refused(self, mosaic):
        profile, placements = mosaic
        with pytest.raises(ZmartLiveError) as refused:
            rebuild_after_committing(profile, placements, "pos99", committed=frozenset())
        assert "pos99" in str(refused.value)

    def test_a_negative_level_is_refused_rather_than_wrapped_around(self, mosaic):
        profile, placements = mosaic
        with pytest.raises(ZmartLiveError):
            chunks_touched_by(profile, placements[0], level=-1)


class TestThePiecesDescribeThemselvesHonestly:
    def test_a_piece_covers_more_ground_the_further_out_it_is(self):
        profile = a_plan()
        close = CoarseChunk(level=0, index=(0, 0), axes=("y", "x"))
        far = CoarseChunk(level=3, index=(0, 0), axes=("y", "x"))
        chunk = {"y": 10, "x": 10}
        assert far.covers(profile, chunk)["x"].length == (
            close.covers(profile, chunk)["x"].length * 8
        )

    def test_neighbouring_pieces_meet_without_overlapping(self):
        """Half-open again: piece 0 stops exactly where piece 1 starts."""
        profile = a_plan()
        chunk = {"y": 10, "x": 10}
        first = CoarseChunk(level=1, index=(0, 0), axes=("y", "x")).covers(profile, chunk)
        second = CoarseChunk(level=1, index=(0, 1), axes=("y", "x")).covers(profile, chunk)
        assert first["x"].stop == second["x"].start
        assert not first.overlaps(second)

    def test_the_profile_scale_is_used_instead_of_guessing_from_level_number(self):
        """Confocal and volume pyramids may scale axes at different rates."""
        profile = AcquisitionProfile(
            profile_id="anisotropic",
            acquisition_type="confocal",
            axes=("z", "y", "x"),
            frame_shape={"z": 4, "y": 90, "x": 90},
            dtype="uint16",
            overlap_pixels={"y": 10, "x": 10},
            topology="grid",
            levels=(
                LevelGeometry(
                    level=0,
                    downsampling={"z": 1, "y": 1, "x": 1},
                    inner_chunk={"z": 1, "y": 10, "x": 10},
                ),
                LevelGeometry(
                    level=1,
                    downsampling={"z": 1, "y": 3, "x": 5},
                    inner_chunk={"z": 1, "y": 10, "x": 10},
                ),
            ),
        )
        piece = CoarseChunk(level=1, index=(1, 2), axes=("y", "x"))
        covered = piece.covers(profile, {"y": 10, "x": 10})

        assert covered["y"] == Interval(30, 60)
        assert covered["x"] == Interval(100, 150)

        placement = place_the_tiles(profile, a_square_of(1, 1))[0]
        touched = chunks_touched_by(profile, placement, level=1)
        assert {chunk.index[1] for chunk in touched} == {0, 1}

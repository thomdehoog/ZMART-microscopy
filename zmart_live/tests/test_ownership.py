"""Checking that every piece of specimen has exactly one owner.

The two failures this guards against are the ones nobody can spot afterwards. If
two tiles both own a piece of specimen, a nucleus sitting there is counted twice
and the number is simply too high. If neither owns it, a stripe of the specimen
quietly disappears and the number is too low. Neither raises anything; both look
like results.

So the central test here does not check a rule — it sweeps the mosaic and counts
owners. A rule can be right in principle and wrong at one corner; counting finds
that. It is done on small frames so the sweep stays quick, because the arithmetic
does not care how large the numbers are and a check nobody wants to wait for is a
check that stops being run.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from zmart_live.model import (
    AcquisitionProfile,
    GridCell,
    LevelGeometry,
    MosaicComponent,
    SceneLayoutRevision,
    ZmartLiveError,
)
from zmart_live.ownership import (
    TopologyRefused,
    check_the_grid_holds_together,
    place_the_tiles,
    plan_one_tile,
    the_far_edges,
)


def a_plan(frame: int = 90, overlap: int = 10, chunk: int = 10) -> AcquisitionProfile:
    """A small mosaic plan with the same shape as a real one.

    Ninety pixels with ten of overlap is nine chunks across with one chunk given
    up, which is the arrangement the real profiles choose — just small enough to
    sweep every pixel in a test.
    """
    return AcquisitionProfile(
        profile_id="test",
        acquisition_type="overview",
        axes=("t", "c", "z", "y", "x"),
        frame_shape={"z": 1, "y": frame, "x": frame},
        dtype="uint16",
        overlap_pixels={"y": overlap, "x": overlap},
        topology="grid",
        levels=(
            LevelGeometry(
                level=0,
                downsampling={"y": 1, "x": 1},
                inner_chunk={"y": chunk, "x": chunk},
                linkable=(frame - overlap) % chunk == 0,
            ),
        ),
    )


def one_tile(profile: AcquisitionProfile, cell: GridCell, **rest):
    """Plan one tile, giving it a plain name that is safe to put in a path.

    A position's name becomes a folder on disk, so the records now refuse
    anything that is not a plain word — no slashes, no colons, nothing that could
    climb out of the run folder. :func:`plan_one_tile` will invent a name when it
    is not given one, and the name it invents contains a colon, which Windows
    reads as a drive letter. Naming the tile here keeps these tests about
    ownership rather than about naming, which has its own tests elsewhere.
    """
    return plan_one_tile(profile, cell, position_id=f"pos{cell.row}{cell.column}", **rest)


def a_square_of(rows: int, columns: int) -> dict[GridCell, str]:
    return {
        GridCell(row, column): f"pos{row}{column}"
        for row in range(rows)
        for column in range(columns)
    }


class TestEveryPieceOfSpecimenHasExactlyOneOwner:
    """The invariant everything else exists to protect."""

    @pytest.mark.parametrize("rows,columns", [(1, 2), (2, 2), (3, 3), (2, 4)])
    def test_no_gaps_and_no_duplicates_anywhere_in_the_mosaic(self, rows, columns):
        """Swept pixel by pixel rather than argued about.

        Every place the mosaic covers is asked which tile owns it. Two owners is
        a nucleus counted twice; none is specimen that vanishes.
        """
        # The arithmetic is size-independent. A small nine-chunk frame lets this
        # inspect every pixel rather than sampling every third one.
        profile = a_plan(frame=18, overlap=2, chunk=2)
        placements = place_the_tiles(profile, a_square_of(rows, columns))
        step = profile.grid_step("x")
        frame = profile.frame_shape["x"]

        reach_y = (rows - 1) * step + frame
        reach_x = (columns - 1) * step + frame
        owners_seen = set()
        for y in range(reach_y):
            for x in range(reach_x):
                owning = [
                    p.position_id
                    for p in placements
                    if p.core_roi_in_run().contains_point({"y": y, "x": x, "z": 0})
                ]
                assert len(owning) <= 1, f"({y},{x}) is claimed by {owning}"
                owners_seen.update(owning)
                if y < reach_y and x < reach_x:
                    assert owning, f"({y},{x}) belongs to nobody"
        assert len(owners_seen) == rows * columns

    def test_the_four_tile_corner_has_one_owner_and_it_is_not_nobody(self):
        """Where four tiles meet is the hardest place for a rule to be right."""
        profile = a_plan()
        placements = place_the_tiles(profile, a_square_of(2, 2))
        step = profile.grid_step("x")
        overlap = profile.overlap_pixels["x"]

        for y in range(step - overlap, step + overlap):
            for x in range(step - overlap, step + overlap):
                owning = [
                    p.position_id
                    for p in placements
                    if p.core_roi_in_run().contains_point({"y": y, "x": x, "z": 0})
                ]
                assert len(owning) == 1, f"({y},{x}) is owned by {owning}"

    def test_an_odd_overlap_still_divides_cleanly(self):
        """An odd number cannot be halved, and the leftover pixel must not be
        given to both neighbours or to neither."""
        profile = a_plan(frame=90, overlap=7)
        placements = place_the_tiles(profile, a_square_of(2, 2))
        step = profile.grid_step("x")

        for y in range(0, step + 20):
            for x in range(0, step + 20):
                owning = [
                    p.position_id
                    for p in placements
                    if p.core_roi_in_run().contains_point({"y": y, "x": x, "z": 0})
                ]
                assert len(owning) == 1

    def test_the_order_tiles_arrived_in_changes_nothing(self):
        """A run interrupted and resumed must produce the same answer."""
        profile = a_plan()
        tidy = a_square_of(2, 3)
        jumbled = dict(reversed(list(tidy.items())))
        assert [p.to_json() for p in place_the_tiles(profile, tidy)] == [
            p.to_json() for p in place_the_tiles(profile, jumbled)
        ]


class TestTheLowerRightRule:
    """Every tile trimmed alike, which is what keeps the overview cheap."""

    def test_every_tile_is_taken_from_its_own_corner(self):
        """The whole point: no tile is taken from an offset, so the numbers line
        up as far down the zoom levels as possible."""
        profile = a_plan()
        placements = place_the_tiles(profile, a_square_of(3, 3))
        for placement in placements:
            for axis in ("y", "x"):
                assert placement.visual_source_roi[axis].start == 0

    def test_every_interior_tile_hands_over_exactly_one_step(self):
        profile = a_plan()
        step = profile.grid_step("x")
        placements = place_the_tiles(profile, a_square_of(3, 3))
        interior = [p for p in placements if p.cell == GridCell(0, 0)]
        for placement in interior:
            for axis in ("y", "x"):
                assert placement.visual_source_roi[axis].length == step

    def test_keeping_the_far_edge_is_available_and_visibly_different(self):
        """Both arms, so neither can pass by accident."""
        profile = a_plan()
        cells = a_square_of(2, 2)
        trimmed = place_the_tiles(profile, cells)
        kept = place_the_tiles(profile, cells, keep_the_far_edge=True)

        corner_trimmed = next(p for p in trimmed if p.cell == GridCell(1, 1))
        corner_kept = next(p for p in kept if p.cell == GridCell(1, 1))
        assert corner_trimmed.visual_source_roi["x"].stop == profile.grid_step("x")
        assert corner_kept.visual_source_roi["x"].stop == profile.frame_shape["x"]

    def test_the_uncovered_far_strips_are_named_rather_than_left_to_be_discovered(self):
        """Trimming alike leaves the mosaic's last row and column short, and
        somebody has to be told which pixels those are."""
        profile = a_plan()
        placements = place_the_tiles(profile, a_square_of(2, 2))
        edges = the_far_edges(profile, placements)

        assert edges, "the trim leaves strips uncovered, so they must be reported"
        for edge in edges:
            assert edge.width == profile.overlap_pixels[edge.axis]

        # And with the edge kept, there is nothing left over. Both arms again.
        kept = place_the_tiles(profile, a_square_of(2, 2), keep_the_far_edge=True)
        assert the_far_edges(profile, kept) == ()


class TestShowingAndCountingAreAllowedToDiffer:
    """Two questions, two answers, and forcing them together compromises both."""

    def test_the_seam_shown_and_the_seam_counted_are_not_the_same_line(self):
        profile = a_plan()
        placement = one_tile(profile, GridCell(0, 0), occupied=frozenset(a_square_of(2, 2)))
        shown = placement.visual_source_roi["x"]
        counted = placement.analysis_core_roi["x"]
        assert shown.stop != counted.stop

    def test_a_model_is_given_the_whole_tile_including_the_overlap(self):
        """The overlap is the context that lets a model judge an object at the edge."""
        profile = a_plan()
        placement = one_tile(profile, GridCell(1, 1), occupied=frozenset(a_square_of(3, 3)))
        for axis in ("y", "x"):
            assert placement.analysis_input_roi[axis].start == 0
            assert placement.analysis_input_roi[axis].stop == profile.frame_shape[axis]

    def test_what_counts_is_narrower_than_what_is_looked_at(self):
        profile = a_plan()
        placement = one_tile(profile, GridCell(1, 1), occupied=frozenset(a_square_of(3, 3)))
        for axis in ("y", "x"):
            looked = placement.analysis_input_roi[axis]
            counts = placement.analysis_core_roi[axis]
            assert counts.start > looked.start
            assert counts.stop < looked.stop

    def test_a_tile_at_the_mosaic_edge_counts_right_up_to_that_edge(self):
        """There is no neighbour out there to hand it to, so it keeps it."""
        profile = a_plan()
        placement = one_tile(profile, GridCell(0, 0), occupied=frozenset(a_square_of(2, 2)))
        assert placement.analysis_core_roi["y"].start == 0
        assert placement.analysis_core_roi["x"].start == 0
        assert placement.on_outer_boundary["y_low"] is True
        assert placement.on_outer_boundary["y_high"] is False


class TestAxesThatAreNotTiledAreNotDivided:
    """Colour, depth and time are not shared between neighbours, and saying so
    stops anybody inferring an ownership rule that does not exist."""

    def test_the_tiled_axes_are_only_the_overlapping_ones(self):
        assert a_plan().tiled_axes == ("y", "x")

    def test_depth_is_owned_whole(self):
        profile = a_plan()
        placement = one_tile(profile, GridCell(0, 0))
        assert placement.analysis_core_roi["z"].start == 0
        assert placement.analysis_core_roi["z"].stop == profile.frame_shape["z"]

    def test_a_plan_with_no_overlap_at_all_is_refused_rather_than_guessed_at(self):
        flat = AcquisitionProfile(
            profile_id="flat",
            acquisition_type="targets",
            axes=("y", "x"),
            frame_shape={"y": 90, "x": 90},
            dtype="uint16",
        )
        with pytest.raises(ZmartLiveError):
            one_tile(flat, GridCell(0, 0))


class TestTheGridHasToMeanWhatItSays:
    """Each refusal corresponds to a way a plausible picture comes out wrong."""

    def test_a_proper_mosaic_is_accepted_and_reported_complete(self):
        """The positive arm, so the refusals below cannot pass by accident."""
        component = check_the_grid_holds_together(a_square_of(2, 3))
        assert component.complete is True
        assert len(component.cells) == 6

    @pytest.mark.parametrize(
        "cell", [GridCell(-1, 0), GridCell(0, -1), GridCell(0.5, 0), GridCell(True, 0)]
    )
    def test_grid_coordinates_are_non_negative_whole_numbers(self, cell):
        with pytest.raises(TopologyRefused, match="non-negative whole-number"):
            check_the_grid_holds_together({cell: "posA"})

    def test_a_tile_cannot_be_planned_at_a_negative_array_origin(self):
        with pytest.raises(TopologyRefused, match="wrong place"):
            one_tile(a_plan(), GridCell(-1, 0))

    def test_the_same_position_in_two_squares_is_refused(self):
        cells = a_square_of(1, 2)
        cells[GridCell(0, 1)] = cells[GridCell(0, 0)]
        with pytest.raises(TopologyRefused) as refused:
            check_the_grid_holds_together(cells)
        assert "pos00" in str(refused.value)

    def test_position_names_that_collide_on_windows_are_refused(self):
        cells = {GridCell(0, 0): "posA", GridCell(0, 1): "POSA"}
        with pytest.raises(TopologyRefused, match="case-insensitive Windows"):
            check_the_grid_holds_together(cells)

    def test_a_tile_touching_only_at_a_corner_is_refused(self):
        """Two tiles meeting diagonally share no edge, so neither can trim
        against the other."""
        cells = {GridCell(0, 0): "a", GridCell(1, 1): "b"}
        with pytest.raises(TopologyRefused) as refused:
            check_the_grid_holds_together(cells)
        assert "corner" in str(refused.value).lower()

    def test_a_tile_with_nothing_beside_it_is_refused(self):
        cells = {GridCell(0, 0): "a", GridCell(0, 1): "b", GridCell(9, 9): "far"}
        with pytest.raises(TopologyRefused) as refused:
            check_the_grid_holds_together(cells)
        assert "separate patch" in str(refused.value)

    def test_a_single_tile_on_its_own_is_perfectly_fine(self):
        """An isolated target is its own component, not an error."""
        component = check_the_grid_holds_together({GridCell(0, 0): "only"})
        assert component.complete is True

    def test_a_hole_in_the_middle_leaves_the_mosaic_incomplete(self):
        """Not the same as an outer edge: an edge keeps its frame, a hole means
        the run has not finished."""
        cells = a_square_of(3, 3)
        del cells[GridCell(1, 1)]
        component = check_the_grid_holds_together(cells)
        assert component.complete is False
        assert len(component.cells) == 8

    def test_an_incomplete_footprint_cannot_publish_ownership_regions(self):
        """A hole must not be turned into four overlapping outer boundaries.

        Before this refusal, the four diagonal pairs around a missing centre
        each owned the same patch of specimen.  The production 1152/128 profile
        duplicated four 64 by 64 regions, large enough to double-count whole
        nuclei.  The planned footprint is settled before acquisition, so waiting
        for an explicit complete footprint does not make ownership depend on the
        order in which tiles arrive.
        """
        cells = a_square_of(3, 3)
        del cells[GridCell(1, 1)]

        with pytest.raises(TopologyRefused, match="incomplete"):
            place_the_tiles(a_plan(), cells)

    def test_an_empty_component_is_refused(self):
        with pytest.raises(TopologyRefused):
            check_the_grid_holds_together({})


class TestTheRecordsSurviveBeingStored:
    def test_a_placement_reads_back_exactly(self):
        from zmart_live.model import PositionPlacement

        placement = one_tile(a_plan(), GridCell(1, 2), occupied=frozenset(a_square_of(3, 3)))
        assert PositionPlacement.from_json(placement.to_json()).to_json() == (placement.to_json())

    def test_a_component_reads_back_exactly(self):
        from zmart_live.model import MosaicComponent

        component = check_the_grid_holds_together(a_square_of(2, 2))
        assert MosaicComponent.from_json(component.to_json()).to_json() == (component.to_json())

    def test_a_component_cannot_name_one_windows_folder_twice(self):
        with pytest.raises(ZmartLiveError, match="same folder"):
            MosaicComponent(
                component_id="component-0",
                profile_id="test",
                cells={GridCell(0, 0): "posA", GridCell(0, 1): "POSA"},
                complete=True,
            )


class TestAStoredLayoutNeverGuessesBetweenTwoOwners:
    def test_one_owner_is_returned(self):
        placement = one_tile(a_plan(), GridCell(0, 0))
        layout = SceneLayoutRevision(
            revision=1,
            schema_version="zmart-live-layout/1",
            run_id="run-1",
            acquisition_type="overview",
            profile_id="test",
            positions=(placement,),
        )
        assert layout.owner_of_point({"z": 0, "y": 1, "x": 1}) == placement.position_id

    def test_overlapping_ownership_is_refused_instead_of_returning_the_first(self):
        first = one_tile(a_plan(), GridCell(0, 0))
        second = replace(first, position_id="another-position")
        layout = SceneLayoutRevision(
            revision=1,
            schema_version="zmart-live-layout/1",
            run_id="run-1",
            acquisition_type="overview",
            profile_id="test",
            positions=(first, second),
        )

        with pytest.raises(ZmartLiveError, match="more than one position"):
            layout.owner_of_point({"z": 0, "y": 1, "x": 1})

    def test_position_names_that_share_one_windows_folder_are_refused(self):
        with pytest.raises(ZmartLiveError, match="same folder"):
            SceneLayoutRevision(
                revision=1,
                schema_version="zmart-live-layout/1",
                run_id="run-1",
                acquisition_type="overview",
                profile_id="test",
                positions=(
                    one_tile(a_plan(), GridCell(0, 0)),
                    plan_one_tile(
                        a_plan(), GridCell(0, 1), position_id="POS00"
                    ),
                ),
            )

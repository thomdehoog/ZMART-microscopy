"""Checking the geometry, and being explicit about what is not integrated yet.

The final tests hand the unsharded geometry to the existing linker, because the
only thing that settles whether placement arithmetic works is the code that has
to carry it out. They do **not** pretend that this proves the planned sharded
path: the current linker measures alignment in whole shards and rejects that
plan. The inner-chunk resolver is tested separately, but wiring it into the
viewer backend remains integration work and is recorded by a red-direction test
below.

That distinction has bitten this project before. A mismatch between what a
picture claims and what its bytes hold does not raise anything: the viewer draws
whatever those bytes happen to decode to, and a wrong answer looks exactly like a
right one. So a plan that is merely self-consistent is not yet known to be good.
"""

from __future__ import annotations

import pytest

from zmart_live.model import AcquisitionProfile, LevelGeometry, ZmartLiveError
from zmart_live.profiles import (
    DEFAULTS,
    a_kinder_frame,
    choose_the_geometry,
    plan_the_writing,
)

# The three frame sizes the convention is built around: nine chunks across, with
# one chunk of that given to the overlap.
KIND_FRAMES = (1152, 2304, 4608)

# Sizes an operator would reach for by habit, which turn out to behave worse.
ROUND_FRAMES = (1024, 2048, 4096)

# Frames that are not square, in both orientations and at two aspect ratios. Real
# instruments produce these: scientific cameras are often wider than they are
# tall, and a confocal's scan format is a software setting that can be asked for.
RECTANGLES = ((1152, 2304), (2304, 1152), (1152, 4608), (4608, 1152))


class TestTheNineChunkConvention:
    """The one arrangement that comes out best at every scale."""

    @pytest.mark.parametrize("frame", KIND_FRAMES)
    def test_a_kind_frame_gives_one_chunk_of_overlap(self, frame):
        """Nine chunks across, one chunk of overlap, stepping eight."""
        geometry = choose_the_geometry(frame, band=DEFAULTS["overview"].overlap_band)
        assert geometry.frame == 9 * geometry.chunk
        assert geometry.overlap == geometry.chunk
        assert geometry.step == 8 * geometry.chunk
        assert geometry.chunks_per_plane == 81

    @pytest.mark.parametrize("frame", KIND_FRAMES)
    def test_a_kind_frame_asks_the_microscope_for_little_overlap(self, frame):
        """Overlap is time on the microscope, so 11.1% is the point of all this."""
        geometry = choose_the_geometry(frame, band=DEFAULTS["overview"].overlap_band)
        assert geometry.overlap_fraction == pytest.approx(1 / 9, abs=0.001)

    @pytest.mark.parametrize("frame", KIND_FRAMES)
    def test_a_kind_frame_writes_none_of_the_tiles_own_zoom_levels(self, frame):
        """Every level a tile keeps can be pointed at, so none has to be built."""
        geometry = choose_the_geometry(frame, band=DEFAULTS["overview"].overlap_band)
        assert geometry.written_levels == 0
        assert geometry.pointed_levels >= 4

    @pytest.mark.parametrize("frame", ROUND_FRAMES)
    def test_a_round_frame_costs_more_and_a_better_one_is_offered(self, frame):
        """1024, 2048 and 4096 are the trap, and the code should say so.

        They are not refused — a fixed camera is a fixed camera — but each pays
        for it somewhere: more overlap, or shallower pointing, or many more
        chunks to a plane. Something should offer the better size where the
        format can actually be changed.
        """
        geometry = choose_the_geometry(frame, band=DEFAULTS["overview"].overlap_band)
        ideal = geometry.frame == 9 * geometry.chunk
        assert not ideal
        assert a_kinder_frame(frame) in KIND_FRAMES

    @pytest.mark.parametrize("frame", KIND_FRAMES)
    def test_a_kind_frame_is_not_told_to_change(self, frame):
        assert a_kinder_frame(frame) is None

    def test_nine_chunks_is_the_rule_rather_than_a_list_of_blessed_sizes(self):
        """1728 is nine 192-pixel chunks, and behaves exactly as well as 2304.

        Telling its owner to change would be wrong, so the check has to be worked
        out from the geometry rather than looked up in a table of sizes somebody
        remembered to write down.
        """
        geometry = choose_the_geometry(1728, band=DEFAULTS["overview"].overlap_band)
        assert geometry.frame == 9 * geometry.chunk
        assert geometry.overlap_fraction == pytest.approx(1 / 9, abs=0.001)
        assert geometry.written_levels == 0
        assert a_kinder_frame(1728) is None

    def test_overlap_is_never_traded_away_for_a_slightly_bigger_chunk(self):
        """Microscope time must outrank viewer convenience.

        A 4096 pixel frame can reach three levels of pointing either at 12.5%
        overlap with a small chunk, or at 25% with a larger one. The larger chunk
        would save the viewer some requests; the extra overlap would cost the
        experiment a further eighth of every tile, imaged twice. The cheaper
        chunk has to win, and getting this backwards is an easy mistake.
        """
        geometry = choose_the_geometry(4096, band=DEFAULTS["overview"].overlap_band)
        assert geometry.overlap_fraction <= 0.125


class TestTheOverlapStaysInsideTheBand:
    """Overlap is an intention with room to move, not one exact percentage."""

    @pytest.mark.parametrize(
        "frame", [1152, 1536, 1728, 2048, 2160, 2304, 2560, 3072, 4096, 4608, 5120]
    )
    def test_whatever_is_chosen_is_permitted(self, frame):
        band = DEFAULTS["overview"].overlap_band
        geometry = choose_the_geometry(frame, band=band)
        assert band.permits(geometry.overlap_fraction)

    def test_a_frame_that_cannot_be_helped_says_so_kindly(self):
        """An awkward frame gets a refusal that names a size which would work."""
        with pytest.raises(ZmartLiveError) as raised:
            choose_the_geometry(2000, band=DEFAULTS["overview"].overlap_band)
        message = str(raised.value)
        assert "2000" in message
        assert "overlap" in message.lower()

    @pytest.mark.parametrize("frame", [0, -1])
    def test_a_nonexistent_frame_is_refused_plainly(self, frame):
        with pytest.raises(ZmartLiveError):
            choose_the_geometry(frame, band=DEFAULTS["overview"].overlap_band)


class TestEachKindOfAcquisitionGetsItsOwn:
    """Different acquisitions genuinely want different things, and may have them."""

    def test_the_kinds_this_facility_runs_are_all_described(self):
        assert set(DEFAULTS) == {
            "overview",
            "targets",
            "timelapse",
            "mesospim",
            "confocal",
        }

    def test_scattered_targets_are_not_treated_as_one_mosaic(self):
        """Detailed scans sit apart from one another, so there is no seam to place."""
        profile, _ = plan_the_writing("targets", frame=1152)
        assert profile.topology == "independent"
        assert DEFAULTS["targets"].wants_seamless is False

    def test_an_overview_is_a_connected_mosaic(self):
        profile, _ = plan_the_writing("overview", frame=2304)
        assert profile.topology == "grid"
        assert profile.tiled_axes == ("y", "x")

    def test_a_timelapse_keeps_its_files_smaller(self):
        """A moment should become visible soon after it finishes.

        A large bundle has to be filled before it can be closed, so a run that
        publishes often wants smaller ones.
        """
        assert DEFAULTS["timelapse"].target_shard_bytes < DEFAULTS["mesospim"].target_shard_bytes

    def test_an_unknown_kind_is_refused_with_the_list_of_known_ones(self):
        with pytest.raises(ZmartLiveError) as raised:
            plan_the_writing("holotomography", frame=2304)
        assert "overview" in str(raised.value)

    def test_a_run_may_bring_its_own_defaults(self):
        """Nothing here is binding; an unusual run can say what it wants."""
        unusual = DEFAULTS["overview"].with_overlap(0.05, 0.30, 0.06)
        profile, geometry = plan_the_writing("overview", frame=2048, defaults=unusual)
        assert profile.overlap_band is unusual.overlap_band
        assert unusual.overlap_band.permits(geometry.overlap_fraction)

    def test_less_overlap_can_be_bought_by_accepting_shallower_pointing(self):
        """The two costs can be traded against one another, deliberately.

        A 2048 frame is awkward: the only overlap in the ordinary band that
        reaches three levels of pointing is a full quarter of the frame. A run
        that would rather spend less time on the microscope can say it will
        settle for shallower pointing, and pay in written zoom levels instead.

        This is the honest shape of the choice. It is not that one setting is
        better; it is that the microscope time and the writing have to come out
        of one budget, and the run gets to say which it would rather spend.
        """
        band = DEFAULTS["overview"].overlap_band
        careful = choose_the_geometry(2048, band=band, enough_depth=3)
        thrifty = choose_the_geometry(2048, band=band, enough_depth=1)

        assert thrifty.overlap_fraction < careful.overlap_fraction
        assert thrifty.pointed_levels < careful.pointed_levels
        assert thrifty.written_levels > careful.written_levels


class TestTheFileBundles:
    """Bundling is what makes half a terabyte movable between machines."""

    @pytest.mark.parametrize(
        "kind,frame,z,expected_mb",
        [
            ("confocal", 1152, 100, 256),
            ("mesospim", 4608, 300, 512),
            ("timelapse", 2304, 20, 128),
        ],
    )
    def test_a_bundle_lands_near_the_size_that_kind_asked_for(self, kind, frame, z, expected_mb):
        profile, _ = plan_the_writing(kind, frame=frame, z_planes=z)
        shard = profile.level(0).shard
        megabytes = shard["z"] * shard["y"] * shard["x"] * 2 / 1024**2
        assert megabytes == pytest.approx(expected_mb, rel=0.55)

    def test_a_bundle_covers_the_whole_frame(self):
        """Nine chunks by nine chunks is the entire tile, which is what makes
        the file size predictable from the plane size alone."""
        profile, geometry = plan_the_writing("mesospim", frame=4608, z_planes=300)
        shard = profile.level(0).shard
        assert shard["y"] == geometry.frame
        assert shard["x"] == geometry.frame

    def test_a_bundle_holds_a_whole_number_of_chunks(self):
        """Required by the format, and checked when the level is built."""
        profile, _ = plan_the_writing("confocal", frame=2304, z_planes=100)
        level = profile.level(0)
        for axis in ("z", "y", "x"):
            assert level.shard[axis] % level.inner_chunk[axis] == 0

    def test_a_bundle_never_spans_moments_or_colours(self):
        """The rule: a bundle may span anything inside one publication, and
        nothing across publications.

        A moment and a colour are inside one publication only in the sense that
        both must be finished before anything is visible — but a later moment is
        a *separate* publication, and a bundle holding two of them would have to
        be rewritten after the first was already on screen.
        """
        profile, _ = plan_the_writing("timelapse", frame=2304, z_planes=20)
        shard = profile.level(0).shard
        assert "t" not in shard
        assert "c" not in shard

    def test_bundling_cuts_the_file_count_enormously(self):
        """The number that decides whether a run can be moved at all."""
        profile, geometry = plan_the_writing("mesospim", frame=4608, z_planes=300)
        slab = profile.level(0).shard["z"]
        loose = 300 * geometry.chunks_per_plane
        bundled = -(-300 // slab)
        assert loose / bundled > 500


class TestWhatIsPromisedIsComputedRatherThanTrusted:
    """A level wrongly claimed as pointable draws a wrong picture, silently."""

    @pytest.mark.parametrize("frame", KIND_FRAMES + ROUND_FRAMES)
    def test_the_levels_marked_pointable_match_the_arithmetic(self, frame):
        profile, geometry = plan_the_writing("overview", frame=frame)
        assert profile.linkable_levels == tuple(range(geometry.pointed_levels))

    def test_no_level_is_marked_pointable_beyond_what_the_tile_keeps(self):
        profile, geometry = plan_the_writing("overview", frame=2304)
        assert len(profile.levels) == geometry.kept_levels
        assert max(profile.linkable_levels) < geometry.kept_levels


class TestARectangularFrameIsPlannedJustAsWell:
    """Observed before this was fixed: only one square frame value was accepted.

    ``choose_the_geometry`` and ``plan_the_writing`` took a single number and
    used it for both the height and the width, so a camera with a 2048 by 2048
    sensor was describable and a 1152 by 2304 scan format, or any of the many
    cameras whose sensor is wider than it is tall, simply was not. There was no
    refusal either: the number given was silently used for both sides, which
    would have written a profile describing a frame the microscope never
    produced.

    The nine-chunk convention still applies, but now once per axis. A frame of
    1152 by 2304 in 128-pixel chunks is nine chunks tall and eighteen across, and
    each axis gets whole chunks of overlap chosen to sit inside the same band.

    The shapes below are checked in both orientations and at two aspect ratios.
    Using only one shape hid a real fault while this was being written: a version
    that measured the width's overlap against the *height* still gave the right
    answer for a frame twice as wide as it was tall, and only came apart on a
    frame four times as wide.
    """

    def test_a_pair_gives_a_different_height_and_width(self):
        geometry = choose_the_geometry((1152, 2304), band=DEFAULTS["overview"].overlap_band)
        assert geometry.height == 1152
        assert geometry.width == 2304

    def test_one_number_still_means_a_square_frame(self):
        """Every existing caller passes a single number and must be unaffected."""
        square = choose_the_geometry(1152, band=DEFAULTS["overview"].overlap_band)
        spelled_out = choose_the_geometry((1152, 1152), band=DEFAULTS["overview"].overlap_band)
        assert square == spelled_out
        assert square.frame == 1152

    @pytest.mark.parametrize("shape", RECTANGLES)
    def test_the_chunk_divides_both_sides(self, shape):
        """A chunk that does not divide a side cannot tile it, so there is no plan."""
        geometry = choose_the_geometry(shape, band=DEFAULTS["overview"].overlap_band)
        assert geometry.height % geometry.chunk == 0
        assert geometry.width % geometry.chunk == 0

    @pytest.mark.parametrize("shape", RECTANGLES)
    def test_each_side_overlaps_by_whole_chunks_inside_the_band(self, shape):
        """Each side is judged against its own length, which is the easy thing to
        get wrong: a strip of 128 pixels is a comfortable overlap on a
        1152-pixel side and far too little on a 4608-pixel one."""
        band = DEFAULTS["overview"].overlap_band
        geometry = choose_the_geometry(shape, band=band)
        for overlap, side in zip(geometry.overlap_shape, geometry.frame_shape, strict=True):
            assert overlap % geometry.chunk == 0
            assert band.permits(overlap / side)

    @pytest.mark.parametrize("shape", RECTANGLES)
    def test_the_step_is_the_frame_minus_the_overlap_on_each_axis(self, shape):
        geometry = choose_the_geometry(shape, band=DEFAULTS["overview"].overlap_band)
        assert geometry.step_shape == (
            geometry.height - geometry.overlap_shape[0],
            geometry.width - geometry.overlap_shape[1],
        )

    @pytest.mark.parametrize("shape", RECTANGLES)
    def test_a_rectangular_frame_still_reaches_the_pointing_depth(self, shape):
        """The whole reason for the convention: nothing has to be written."""
        geometry = choose_the_geometry(shape, band=DEFAULTS["overview"].overlap_band)
        assert geometry.written_levels == 0
        assert geometry.pointed_levels >= 4

    @pytest.mark.parametrize("shape", RECTANGLES)
    def test_the_nine_chunk_convention_holds_on_both_axes(self, shape):
        """Eleven per cent either way, whatever the aspect ratio.

        This is the pleasing part of doing the arithmetic per axis: a frame four
        times as wide as it is tall simply gets four chunks of overlap across
        instead of one, and pays the same eleven per cent of microscope time on
        both sides as a square frame does.
        """
        geometry = choose_the_geometry(shape, band=DEFAULTS["overview"].overlap_band)
        for fraction in geometry.overlap_fractions:
            assert fraction == pytest.approx(1 / 9, abs=0.001)

    def test_the_square_shorthand_refuses_to_answer_for_a_rectangle(self):
        """``geometry.frame`` cannot mean anything when the sides differ.

        Returning one of the two would be the dangerous answer: the caller would
        get a plausible number and quietly plan for the wrong shape.
        """
        geometry = choose_the_geometry((1152, 2304), band=DEFAULTS["overview"].overlap_band)
        for shorthand in ("frame", "overlap", "step", "overlap_fraction"):
            with pytest.raises(ZmartLiveError):
                getattr(geometry, shorthand)

    def test_a_plan_records_the_rectangle_it_was_given(self):
        profile, geometry = plan_the_writing("confocal", frame=(1152, 2304), z_planes=8)
        assert profile.frame_shape["y"] == 1152
        assert profile.frame_shape["x"] == 2304
        assert profile.overlap_pixels["y"] == geometry.overlap_shape[0]
        assert profile.overlap_pixels["x"] == geometry.overlap_shape[1]

    def test_a_rectangular_bundle_still_covers_the_whole_frame(self):
        profile, _ = plan_the_writing("confocal", frame=(1152, 2304), z_planes=8)
        shard = profile.level(0).shard
        assert shard["y"] == 1152
        assert shard["x"] == 2304

    def test_the_levels_marked_pointable_match_the_arithmetic(self):
        profile, geometry = plan_the_writing("overview", frame=(1152, 2304))
        assert profile.linkable_levels == tuple(range(geometry.pointed_levels))

    def test_a_frame_given_the_wrong_shape_is_refused_plainly(self):
        for wrong in [(1152,), (1152, 1152, 1152), (0, 1152), (1152, -1), "1152"]:
            with pytest.raises(ZmartLiveError):
                choose_the_geometry(wrong, band=DEFAULTS["overview"].overlap_band)

    def test_a_rectangle_no_chunk_can_tile_says_so(self):
        """1152 and 2000 share no chunk that behaves, and the refusal names both."""
        with pytest.raises(ZmartLiveError) as raised:
            choose_the_geometry((1152, 2000), band=DEFAULTS["overview"].overlap_band)
        message = str(raised.value)
        assert "1152" in message and "2000" in message


class TestTheProfileSurvivesBeingStored:
    """A profile is stored with the run so that Tuesday's position still means
    the same thing on Friday."""

    @pytest.mark.parametrize("kind", sorted(DEFAULTS))
    def test_it_reads_back_exactly_as_written(self, kind):
        profile, _ = plan_the_writing(kind, frame=2304, z_planes=10)
        again = AcquisitionProfile.from_json(profile.to_json())
        assert again.to_json() == profile.to_json()

    def test_it_is_sealed(self):
        profile, _ = plan_the_writing("overview", frame=2304)
        assert profile.sealed is True

    def test_a_mutable_voxel_size_input_cannot_change_a_sealed_profile(self):
        profile, _ = plan_the_writing("overview", frame=2304)
        stored = profile.to_json()
        voxel_size = stored["voxel_size"]
        recovered = AcquisitionProfile.from_json(stored)

        voxel_size["x"] = 99.0
        assert recovered.voxel_size["x"] != 99.0


class TestMalformedProfilesFailBeforeTheyCanDrawPlausibleNoise:
    """The serialized profile is an input boundary, not trusted Python state."""

    @pytest.mark.parametrize(
        "level",
        [
            LevelGeometry(0, {"y": 1}, {"y": 1}, shard={"y": 1}),
        ],
    )
    def test_a_well_formed_control_level_is_accepted(self, level):
        assert level.level == 0

    @pytest.mark.parametrize(
        "field,value",
        [("downsampling", {"y": 0}), ("inner_chunk", {"y": 0}), ("shard", {"y": 0})],
    )
    def test_zero_sized_level_geometry_is_refused(self, field, value):
        settings = {
            "level": 0,
            "downsampling": {"y": 1},
            "inner_chunk": {"y": 1},
            "shard": None,
        }
        settings[field] = value
        with pytest.raises(ZmartLiveError):
            LevelGeometry(**settings)

    def test_a_linkable_flag_that_disagrees_with_the_grid_is_refused(self):
        with pytest.raises(ZmartLiveError):
            AcquisitionProfile(
                profile_id="bad-link",
                acquisition_type="overview",
                axes=("y", "x"),
                frame_shape={"y": 90, "x": 90},
                dtype="uint16",
                overlap_pixels={"y": 7, "x": 7},
                topology="grid",
                levels=(
                    LevelGeometry(
                        0,
                        {"y": 1, "x": 1},
                        {"y": 10, "x": 10},
                        linkable=True,
                    ),
                ),
            )

    def test_pyramid_levels_cannot_start_at_one_or_leave_a_gap(self):
        with pytest.raises(ZmartLiveError):
            AcquisitionProfile(
                profile_id="bad-levels",
                acquisition_type="overview",
                axes=("y", "x"),
                frame_shape={"y": 90, "x": 90},
                dtype="uint16",
                overlap_pixels={"y": 10, "x": 10},
                topology="grid",
                levels=(
                    LevelGeometry(
                        1,
                        {"y": 2, "x": 2},
                        {"y": 10, "x": 10},
                    ),
                ),
            )

    @pytest.mark.parametrize(
        "changes",
        [
            {"z_planes": 0},
            {"dtype": "not-a-real-pixel-type"},
            {"channels": ()},
            {"voxel_size": (1.0, 0.0, 1.0)},
            {"voxel_size": (1.0, float("nan"), 1.0)},
        ],
    )
    def test_an_unwritable_acquisition_input_is_refused(self, changes):
        with pytest.raises(ZmartLiveError):
            plan_the_writing("overview", frame=2304, **changes)


@pytest.mark.filterwarnings(
    "ignore:a tile of .* does not divide into whole pieces of image:UserWarning"
)
class TestTheGeometryAndTheCurrentLinker:
    """Hand the geometry to real code, without disguising the sharding gap.

    The first test builds an unsharded OME-Zarr mosaic and checks the placement
    arithmetic against the current linker. The second proves that simply turning
    on the profile's shards does not work: until the byte-range resolver is wired
    into the linked-view backend, claiming end-to-end sharded support would be a
    silently dangerous lie.
    """

    @pytest.mark.parametrize("frame", [1152, 2304])
    def test_the_chosen_geometry_really_links(self, frame, tmp_path):
        numpy = pytest.importorskip("numpy")
        from zmart_storage.canvas import Channel, TileCanvases
        from zmart_storage.linked import PlacedTile, link_the_tiles

        profile, geometry = plan_the_writing("overview", frame=frame)
        step, chunk = geometry.step, geometry.chunk
        rows = columns = 2

        stores = {}
        for row in range(rows):
            for column in range(columns):
                name = f"pos{row}{column}"
                canvases = TileCanvases.create(
                    tmp_path,
                    name=name,
                    canvas_shape=(1, frame, frame),
                    tile_shape=(1, frame, frame),
                    tile_step=(1, frame, frame),
                    voxel_size_um=(1.0, 0.5, 0.5),
                    channels=[Channel(name="green")],
                    chunk=chunk,
                    levels=geometry.kept_levels,
                    ome_zarr_version="0.5",
                    records_coverage=False,
                    origin_um=(0.0, row * step * 0.5, column * step * 0.5),
                )
                canvases.write(
                    numpy.full((1, frame, frame), row * columns + column + 1, "uint16"),
                    origin=(0, 0, 0),
                )
                canvases.close()
                stores[(row, column)] = tmp_path / f"{name}.ome.zarr"

        # Every tile treated alike: taken from its own corner, trimmed to one
        # step, landing at its place in the grid. This uniformity is exactly what
        # buys the pointing depth.
        tiles = [
            PlacedTile(
                store=store,
                lands_at=(0, row * step, column * step),
                taken_from=(0, 0, 0),
                size=(1, step, step),
            )
            for (row, column), store in stores.items()
        ]

        extent = (rows - 1) * step + frame
        link_the_tiles(
            tmp_path,
            tiles=tiles,
            name="seamless",
            view_shape=(1, extent, extent),
            levels=geometry.pointed_levels,
        )
        assert (tmp_path / "seamless.ome.zarr").exists()

    def test_pointing_one_level_deeper_than_promised_is_refused(self, tmp_path):
        """The promise is a ceiling, and the writer enforces it.

        If this ever stops raising, the plan has become more cautious than it
        needs to be and the depth calculation should be revisited.
        """
        numpy = pytest.importorskip("numpy")
        from zmart_storage.canvas import Channel, TileCanvases
        from zmart_storage.linked import PlacedTile, link_the_tiles

        frame = 2304
        profile, geometry = plan_the_writing("overview", frame=frame)
        step, chunk = geometry.step, geometry.chunk

        stores = []
        for index in range(2):
            name = f"pos{index}"
            canvases = TileCanvases.create(
                tmp_path,
                name=name,
                canvas_shape=(1, frame, frame),
                tile_shape=(1, frame, frame),
                tile_step=(1, frame, frame),
                voxel_size_um=(1.0, 0.5, 0.5),
                channels=[Channel(name="green")],
                chunk=chunk,
                levels=geometry.kept_levels,
                ome_zarr_version="0.5",
                records_coverage=False,
                origin_um=(0.0, 0.0, index * step * 0.5),
            )
            canvases.write(numpy.full((1, frame, frame), index + 1, "uint16"), origin=(0, 0, 0))
            canvases.close()
            stores.append(tmp_path / f"{name}.ome.zarr")

        # A trim that is deliberately not a whole number of chunks.
        tiles = [
            PlacedTile(store, (0, 0, index * step), (0, 0, 0), (1, frame, step + 1))
            for index, store in enumerate(stores)
        ]
        with pytest.raises(ValueError):
            link_the_tiles(
                tmp_path,
                tiles=tiles,
                name="wrong",
                view_shape=(1, frame, step + frame),
                levels=geometry.pointed_levels,
            )

    def test_the_current_whole_shard_linker_refuses_the_planned_sharded_path(self, tmp_path):
        """The resolver exists, but it is not yet connected to ``link_the_tiles``."""
        from zmart_storage.canvas import Channel, TileCanvases
        from zmart_storage.linked import PlacedTile, link_the_tiles

        frame = 1152
        profile, geometry = plan_the_writing("overview", frame=frame)
        shard = profile.level(0).shard["x"]
        canvases = TileCanvases.create(
            tmp_path,
            name="sharded-position",
            canvas_shape=(1, frame, frame),
            tile_shape=(1, frame, frame),
            tile_step=(1, frame, frame),
            voxel_size_um=(1.0, 0.5, 0.5),
            channels=[Channel(name="green")],
            chunk=geometry.chunk,
            shard=shard,
            levels=geometry.kept_levels,
            ome_zarr_version="0.5",
            records_coverage=False,
        )
        canvases.close()
        tile = PlacedTile(
            tmp_path / "sharded-position.ome.zarr",
            lands_at=(0, 0, 0),
            taken_from=(0, 0, 0),
            size=(1, geometry.step, geometry.step),
        )

        with pytest.raises(ValueError, match="bundle"):
            link_the_tiles(
                tmp_path,
                tiles=[tile],
                name="not-integrated-yet",
                view_shape=(1, frame, frame),
                levels=geometry.pointed_levels,
            )

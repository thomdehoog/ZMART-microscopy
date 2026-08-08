"""Checking that the storage plan a run is given actually holds up.

The important test in this file is the last one. Everything above it checks the
arithmetic against the rule as written down, which is worth doing but proves only
that two descriptions of the same idea agree. The last one takes the plan and
hands it to the real writer, because the only thing that settles whether a plan
works is the code that has to carry it out.

That distinction has bitten this project before. A mismatch between what a
picture claims and what its bytes hold does not raise anything: the viewer draws
whatever those bytes happen to decode to, and a wrong answer looks exactly like a
right one. So a plan that is merely self-consistent is not yet known to be good.
"""

from __future__ import annotations

import pytest

from zmart_live.model import AcquisitionProfile, ZmartLiveError
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
        assert (
            DEFAULTS["timelapse"].target_shard_bytes
            < DEFAULTS["mesospim"].target_shard_bytes
        )

    def test_an_unknown_kind_is_refused_with_the_list_of_known_ones(self):
        with pytest.raises(ZmartLiveError) as raised:
            plan_the_writing("holotomography", frame=2304)
        assert "overview" in str(raised.value)

    def test_a_run_may_bring_its_own_defaults(self):
        """Nothing here is binding; an unusual run can say what it wants."""
        unusual = DEFAULTS["overview"].with_overlap(0.05, 0.30, 0.06)
        profile, geometry = plan_the_writing(
            "overview", frame=2048, defaults=unusual
        )
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
    def test_a_bundle_lands_near_the_size_that_kind_asked_for(
        self, kind, frame, z, expected_mb
    ):
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


class TestThePlanSurvivesTheRealWriter:
    """The one that counts: hand the plan to the code that has to carry it out.

    Everything above checks the plan against the rule as this module states it.
    This builds a real mosaic of real OME-Zarr positions with the chosen geometry
    and asks the actual view-building code to point at them. If the stated rule
    and the enforced rule ever drift apart, this is what notices.
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
                tmp_path, name=name, canvas_shape=(1, frame, frame),
                tile_shape=(1, frame, frame), tile_step=(1, frame, frame),
                voxel_size_um=(1.0, 0.5, 0.5), channels=[Channel(name="green")],
                chunk=chunk, levels=geometry.kept_levels, ome_zarr_version="0.5",
                records_coverage=False,
                origin_um=(0.0, 0.0, index * step * 0.5),
            )
            canvases.write(
                numpy.full((1, frame, frame), index + 1, "uint16"), origin=(0, 0, 0)
            )
            canvases.close()
            stores.append(tmp_path / f"{name}.ome.zarr")

        # A trim that is deliberately not a whole number of chunks.
        tiles = [
            PlacedTile(store, (0, 0, index * step), (0, 0, 0), (1, frame, step + 1))
            for index, store in enumerate(stores)
        ]
        with pytest.raises(Exception):
            link_the_tiles(
                tmp_path, tiles=tiles, name="wrong",
                view_shape=(1, frame, step + frame), levels=geometry.pointed_levels,
            )

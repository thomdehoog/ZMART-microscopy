"""An overlapping run written twice: is anything lost, and is the canvas right?

:mod:`zmart_storage.cropped` makes two promises about an acquisition whose tiles
overlap, and both of them are the kind that can fail quietly. So both are checked
here against the voxels on disk rather than against anything the writer says about
itself.

**Nothing the camera recorded is lost.** Every tile is put away whole, overlap and
all, so a stitcher coming along afterwards has the strips it needs in order to work
out where the stage really went. The test for this counts every voxel that was
handed to the writer and reads every one of them back.

**The canvas holds exactly the right picture, in the right place.** Where two tiles
meet, half the shared strip comes off each of them, so what is left butts up and
touches nowhere. Where a tile has no neighbour, nothing comes off, so the picture
covers the whole ground the run covered rather than losing a border around the
outside. The tests for this rebuild the picture the canvas ought to hold and
compare it voxel for voxel.

There is a third thing checked here that is not about the pictures at all. The
whole arrangement rests on
:func:`zmart_storage.canvas._refuse_overlapping_tiles` being satisfied honestly
rather than argued around, so there is a test below that an overlapping run is
still refused by the plain writer. If somebody ever relaxes that refusal, this
file says so.
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pytest
import zarr

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from zmart_storage.canvas import Channel, TileCanvases
from zmart_storage.cropped import (
    TilesAndCanvas,
    Trimming,
    neighbours_of,
    the_piece_the_canvas_will_use,
)

# A tile 128 voxels across the specimen and two planes deep, with the stage
# stepping 96 across — so neighbouring tiles share a strip 32 voxels wide, which is
# a quarter of a tile and squarely in the range microscopists actually use. The
# stage steps a whole tile in depth, so this run overlaps across the specimen and
# not at all in depth, which is the usual arrangement.
#
# The canvas keeps its picture in pieces 96 voxels across, which is exactly what a
# trimmed tile comes to. That is the rule the arrangement rests on and it is being
# satisfied here deliberately rather than by luck; a test further down makes a run
# that breaks it and checks it is refused.
TILE = (2, 128, 128)
STEP = (2, 96, 96)
CHUNK = 96

# A raster three tiles across and three down, one tile deep.
GRID = (1, 3, 3)

VOXEL_UM = (2.0, 0.35, 0.35)


def _a_run(folder: Path, *, grid=GRID, channels: int = 1, frames: int = 1,
           tile=TILE, step=STEP, chunk: int = CHUNK, say_the_grid: bool = True,
           **kwargs) -> TilesAndCanvas:
    """A small overlapping acquisition, declared and ready for tiles."""
    return TilesAndCanvas.create(
        folder,
        name="overview",
        canvas_shape=_full_extent(grid, tile, step),
        tile_shape=tile,
        tile_step=step,
        tile_grid=grid if say_the_grid else None,
        voxel_size_um=VOXEL_UM,
        channels=[Channel(name) for name in ("488", "561")[:channels]],
        frames=frames,
        chunk=chunk,
        **kwargs,
    )


def _full_extent(grid, tile=TILE, step=STEP) -> tuple[int, int, int]:
    """How much ground a raster of this shape covers, in voxels, from edge to edge.

    This is the honest extent of the run: from the low corner of the first tile to
    the high corner of the last one, with nothing taken off either end. It is what
    the canvas has to hold if the outer edges of the perimeter tiles are really
    being kept.
    """
    return tuple(  # type: ignore[return-value]
        (grid[axis] - 1) * step[axis] + tile[axis] for axis in range(3)
    )


def _a_tile(seed: int, shape=TILE) -> np.ndarray:
    """A tile of pure noise, so that no two tiles can be confused for each other.

    Noise rather than a gradient or a flat value on purpose. If a tile were placed
    one voxel out, or a strip of it quietly replaced by its neighbour, a smooth
    picture would still look perfectly reasonable and the tests below would pass. A
    field of unrepeatable numbers makes every such mistake show up as an exact
    mismatch.
    """
    return np.random.default_rng(seed).integers(
        100, 4000, size=shape, dtype=np.uint16
    )


def _level0(store: Path) -> zarr.Array:
    """The full-resolution image inside an OME-Zarr store."""
    return zarr.open_group(str(store), mode="r")["0"]


def _where_it_says_it_sits(store: Path) -> list[float]:
    """Where an image says its full-size copy begins on the stage, in microns.

    OME-Zarr offers two places to say this: beside each copy of the picture, or
    once beside the block that lists them all. This writer says it beside each
    copy, because that is the place the format makes compulsory and therefore the
    place other people's readers actually look. An image that said it only in the
    optional place would open at the stage's zero in most of the Python world.

    The numbers come back exactly as they are written, one for each axis, so the
    first two are time and colour and the last three are depth, height and width.
    """
    described = json.loads((store / ".zattrs").read_text(encoding="utf-8"))
    full_size = described["multiscales"][0]["datasets"][0]
    placed = [step for step in full_size["coordinateTransformations"]
              if step["type"] == "translation"]
    assert placed, (
        f"{store.name} does not say where its full-size copy begins, so every "
        f"reader that looks in the compulsory place would draw it at the stage's "
        f"zero, on top of every other acquisition in the run"
    )
    return placed[0]["translation"]


def _corner_of(store: Path, origin_um=(0.0, 0.0, 0.0)) -> tuple[int, int, int]:
    """Where a whole-tile image says it sits, read back in voxels from the run's zero.

    Read from what was written rather than from the writer's own bookkeeping, so
    that the tests do not quietly depend on how positions happen to be numbered.
    """
    moved = _where_it_says_it_sits(store)
    return tuple(  # type: ignore[return-value]
        round((moved[2 + axis] - origin_um[axis]) / VOXEL_UM[axis])
        for axis in range(3)
    )


def _fill_a_raster(run: TilesAndCanvas, *, grid=GRID, channels: int = 1,
                   frames: int = 1, tile=TILE, step=STEP) -> dict:
    """Image a small overlapping raster, and remember every tile that was handed over.

    Returns what was written, keyed by ``(frame, channel, iz, iy, ix)``, so that the
    tests can afterwards ask of any voxel which tile it should have come from.
    """
    written = {}
    seed = 0
    for frame in range(frames):
        for channel in range(channels):
            for iz in range(grid[0]):
                for iy in range(grid[1]):
                    for ix in range(grid[2]):
                        seed += 1
                        picture = _a_tile(seed, tile)
                        run.write(
                            picture,
                            origin=(iz * step[0], iy * step[1], ix * step[2]),
                            channel=channel,
                            frame=frame,
                            tile_index=(iz, iy, ix),
                        )
                        written[(frame, channel, iz, iy, ix)] = picture
    return written


def _the_picture_the_canvas_should_hold(run: TilesAndCanvas, written: dict, *,
                                        grid=GRID, tile=TILE, step=STEP,
                                        frame: int = 0, channel: int = 0):
    """Rebuild, from the tiles that were handed over, what the canvas ought to hold.

    Built independently of the writer rather than asked of it, because a test that
    took the writer's own word for where a tile went could not catch the writer
    putting it in the wrong place.
    """
    extent = _full_extent(grid, tile, step)
    expected = np.zeros(extent, dtype="uint16")
    for (its_frame, its_channel, iz, iy, ix), picture in written.items():
        if (its_frame, its_channel) != (frame, channel):
            continue
        neighbours = neighbours_of((iz, iy, ix), grid)
        kept = run.trimming.cut(picture, neighbours)
        at = tuple(
            (iz, iy, ix)[axis] * step[axis]
            + (run.trimming.half[axis] if neighbours[axis][0] else 0)
            for axis in range(3)
        )
        expected[
            at[0]:at[0] + kept.shape[0],
            at[1]:at[1] + kept.shape[1],
            at[2]:at[2] + kept.shape[2],
        ] = kept
    return expected


def _what_the_canvas_holds(run: TilesAndCanvas, *, grid=GRID, tile=TILE, step=STEP,
                           frame: int = 0, channel: int = 0) -> np.ndarray:
    """The part of the canvas the run's own ground occupies, read back.

    The canvas begins a little before the stage's low corner — a blank margin, so
    that the untrimmed outer edges of the perimeter tiles have somewhere to sit —
    so the run's ground starts at ``run.shift`` rather than at nought.
    """
    extent = _full_extent(grid, tile, step)
    shift = run.shift
    return np.asarray(_level0(run.canvas_path)[
        frame, channel,
        shift[0]:shift[0] + extent[0],
        shift[1]:shift[1] + extent[1],
        shift[2]:shift[2] + extent[2],
    ])


# -- the archive: nothing the camera recorded is lost --------------------------


def test_every_voxel_the_camera_recorded_is_still_readable(tmp_path):
    """The whole point of keeping the overlap: not one reading is thrown away.

    This counts rather than samples. Every voxel handed to the writer is read back
    out of the archive and compared, and the number that disagree is reported —
    which has to be nought, because a stitcher given tiles with holes in them is
    worse off than one given no tiles at all.
    """
    run = _a_run(tmp_path / "run")
    written = _fill_a_raster(run)
    run.close()

    recorded = sum(picture.size for picture in written.values())
    by_corner = {
        _corner_of(store): store
        for store in sorted(run.tiles_folder.glob("*.ome.zarr"))
    }

    lost = 0
    for (frame, channel, iz, iy, ix), picture in written.items():
        store = by_corner[(iz * STEP[0], iy * STEP[1], ix * STEP[2])]
        back = np.asarray(_level0(store)[frame, channel])
        lost += int((back != picture).sum())

    assert lost == 0, (
        f"{lost} of the {recorded} voxels the camera recorded could not be read "
        "back from the archive. Keeping the overlap is the entire reason this "
        "writer exists, so any loss at all makes it pointless."
    )
    assert len(by_corner) == GRID[0] * GRID[1] * GRID[2], (
        "one whole-tile image per position was expected, and there are "
        f"{len(by_corner)}"
    )


def test_the_overlapping_strip_really_is_kept_twice(tmp_path):
    """The strip two tiles both photographed is present in both of their images.

    This is what a stitcher compares, and it is the one thing writing into a single
    image destroys. Checking it separately from the count above is worth doing
    because a writer that trimmed before archiving would still pass a count of its
    own trimmed voxels.
    """
    run = _a_run(tmp_path / "run", grid=(1, 2, 2))
    written = _fill_a_raster(run, grid=(1, 2, 2))
    run.close()

    corners = {
        _corner_of(store): store
        for store in sorted(run.tiles_folder.glob("*.ome.zarr"))
    }
    here = corners[(0, 0, 0)]
    to_the_right = corners[(0, 0, STEP[2])]
    overlap = TILE[2] - STEP[2]

    # The right-hand edge of one tile and the left-hand edge of the next cover the
    # same ground, and both should still hold their own recording of it.
    ours = np.asarray(_level0(here)[0, 0])[:, :, STEP[2]:]
    theirs = np.asarray(_level0(to_the_right)[0, 0])[:, :, :overlap]
    assert ours.shape[2] == overlap and theirs.shape[2] == overlap

    assert (ours == written[(0, 0, 0, 0, 0)][:, :, STEP[2]:]).all()
    assert (theirs == written[(0, 0, 0, 0, 1)][:, :, :overlap]).all()
    # And the two recordings genuinely differ, which is what makes the comparison
    # worth making. If they were identical there would be nothing for a stitcher to
    # measure, and this test would be passing on a fixture that could not fail.
    assert not (ours == theirs).all(), (
        "the two recordings of the shared strip are identical, so this fixture "
        "cannot tell a kept overlap from a discarded one"
    )


# -- the canvas: the right picture, in the right place -------------------------


def test_the_canvas_holds_exactly_the_right_picture(tmp_path):
    """Voxel for voxel, the canvas is the tiles trimmed where they meet.

    Two mistakes are being looked for and they fail in different ways. A tile
    trimmed by the wrong amount comes out shifted, and a tile written at the wrong
    corner comes out somewhere else entirely — both of which look like a perfectly
    ordinary picture and would be found weeks later, if at all.
    """
    run = _a_run(tmp_path / "run")
    written = _fill_a_raster(run)
    run.close()

    assert run.trimming.kept == STEP, (
        "a tile trimmed on both sides has to come to exactly the stage's step, or "
        f"trimmed tiles do not butt up: {run.trimming}"
    )

    expected = _the_picture_the_canvas_should_hold(run, written)
    got = _what_the_canvas_holds(run)
    disagreeing = int((got != expected).sum())
    assert disagreeing == 0, (
        f"{disagreeing} voxels of the canvas hold something other than the tile "
        "that belongs there, out of "
        f"{expected.size} — so tiles are landing in the wrong place, or on one "
        "another"
    )


def test_the_whole_extent_of_the_run_survives_on_the_canvas(tmp_path):
    """The outer edges of the perimeter tiles are kept, so no border is lost.

    Every tile around the outside of a raster has at least one edge with nothing
    beyond it. There is no neighbour there to replace what would be cut, so cutting
    it would throw away a strip of real specimen right around the run — sixteen
    voxels on every side here, which is a border a third of a tile wide in total and
    quite invisible once it has gone.

    So this measures the canvas from the outside in: the picture has to reach from
    the very first voxel of the first tile to the very last voxel of the last one.
    """
    run = _a_run(tmp_path / "run")
    written = _fill_a_raster(run)
    run.close()

    extent = _full_extent(GRID)
    got = _what_the_canvas_holds(run)
    assert got.shape == extent

    # Every one of the four outer edges holds picture, and holds the right picture.
    # The corner tiles are compared over the part of themselves they own — the whole
    # of their outer edge, up to where their neighbour takes over — because that is
    # exactly the strip that would go missing if outer edges were trimmed.
    first = written[(0, 0, 0, 0, 0)]
    last = written[(0, 0, 0, GRID[1] - 1, GRID[2] - 1)]
    owns = tuple(TILE[axis] - run.trimming.half[axis] for axis in range(3))
    assert (got[:, 0, :owns[2]] == first[:, 0, :owns[2]]).all(), (
        "the top edge of the run is missing from the canvas, so the first row the "
        "camera recorded was trimmed away with no neighbour to replace it"
    )
    assert (got[:, :owns[1], 0] == first[:, :owns[1], 0]).all(), (
        "the left edge of the run is missing from the canvas"
    )
    assert (got[:, -1, -owns[2]:] == last[:, -1, -owns[2]:]).all(), (
        "the bottom edge of the run is missing from the canvas"
    )
    assert (got[:, -owns[1]:, -1] == last[:, -owns[1]:, -1]).all(), (
        "the right edge of the run is missing from the canvas"
    )

    # And nothing is blank anywhere inside it, which is what says the trimmed tiles
    # really do meet rather than leaving gaps between them.
    assert (got > 0).all(), (
        f"{int((got == 0).sum())} voxels inside the run's own ground hold nothing, "
        "so the trimmed tiles are not butting up"
    )


def test_a_run_that_says_nothing_about_its_pattern_is_warned_and_loses_the_far_edge(
    tmp_path
):
    """What happens when the run does not say how many tiles it will take.

    Without that, the tiles at the far edge of the pattern cannot be told apart
    from the ones in the middle, so their outer edges are trimmed like any other
    and the canvas comes up short. Nothing is lost from the archive, and the
    warning says exactly that and what to pass instead — but the shortfall is real
    and is measured here rather than described.
    """
    with pytest.warns(UserWarning, match="nothing was said about how many tiles"):
        run = _a_run(tmp_path / "run", say_the_grid=False)
    written = _fill_a_raster(run)
    run.close()

    extent = _full_extent(GRID)
    got = _what_the_canvas_holds(run)
    # The low edges are still kept, because a tile at index nought is recognisable
    # without knowing where the pattern ends. The far edges are not.
    owns = TILE[2] - run.trimming.half[2]
    assert (got[:, 0, :owns] == written[(0, 0, 0, 0, 0)][:, 0, :owns]).all()
    short = run.trimming.half
    assert not got[:, extent[1] - short[1]:, :].any(), (
        "the far edge was expected to be missing when the pattern's size was not "
        "given, and something is there"
    )


def test_the_canvas_is_drawn_at_the_true_place_on_the_stage(tmp_path):
    """The picture has to sit where the specimen was, not a margin off.

    The canvas begins a little before the stage's low corner, so that the untrimmed
    outer edges of the perimeter tiles have somewhere to sit. If its declared corner
    did not carry that, the canvas and the whole tiles beside it would be drawn tens
    of microns apart — far enough to matter and near enough to look plausible.
    """
    origin_um = (10.0, 100.0, 200.0)
    run = _a_run(tmp_path / "run", origin_um=origin_um)
    _fill_a_raster(run)
    run.close()

    moved = _where_it_says_it_sits(run.canvas_path)
    with_the_margin = tuple(
        origin_um[axis] - run.shift[axis] * VOXEL_UM[axis] for axis in range(3)
    )
    assert tuple(moved[2:]) == pytest.approx(with_the_margin), (
        f"the canvas puts its corner at {tuple(moved[2:])}, where the blank "
        f"margin in front of the run's ground puts it at {with_the_margin} - so "
        f"the canvas would be drawn a margin away from the whole tiles beside it"
    )

    # Which is to say: the voxel where the run's own ground begins on the canvas
    # sits at exactly the stage position the run was declared with.
    for axis in range(3):
        began = moved[2 + axis] + run.shift[axis] * VOXEL_UM[axis]
        assert began == pytest.approx(origin_um[axis]), (
            f"on axis {axis} the run's own ground begins at {began} microns on "
            f"the canvas, where the stage was declared at {origin_um[axis]}"
        )

    # And a whole tile is recorded at the stage position it was acquired at, with
    # no shift at all, because nothing was taken off it.
    corners = {
        _corner_of(store, origin_um): store
        for store in run.tiles_folder.glob("*.ome.zarr")
    }
    whole = _where_it_says_it_sits(corners[(0, 0, 0)])
    assert tuple(whole[2:]) == pytest.approx(origin_um), (
        f"the first whole tile puts its corner at {tuple(whole[2:])}, where it "
        f"was acquired at {origin_um}. Nothing is trimmed off an archived tile, "
        f"so nothing should move it either"
    )


# -- a run that overlaps in depth as well --------------------------------------


def test_a_run_that_overlaps_in_depth_as_well_is_trimmed_in_depth(tmp_path):
    """Stacks that overlap each other, which is the case most easily missed.

    A run that steps the stage in depth by less than the depth it images overlaps
    in ``z`` exactly as it does across the specimen, and it is trimmed by the same
    arithmetic. Nothing about the writer treats depth as a special case, and this
    is what would notice if somebody made it one.
    """
    tile = (8, 128, 128)
    step = (6, 96, 96)     # two planes of overlap in depth, thirty-two across
    grid = (3, 2, 2)

    run = _a_run(tmp_path / "run", grid=grid, tile=tile, step=step)
    assert run.trimming.overlap == (2, 32, 32)
    assert run.trimming.half == (1, 16, 16)

    written = _fill_a_raster(run, grid=grid, tile=tile, step=step)
    run.close()

    expected = _the_picture_the_canvas_should_hold(
        run, written, grid=grid, tile=tile, step=step
    )
    got = _what_the_canvas_holds(run, grid=grid, tile=tile, step=step)
    assert (got == expected).all(), (
        f"{int((got != expected).sum())} voxels of a run overlapping in depth are "
        "not what they should be"
    )
    # The stacks meet plane by plane with nothing missing and nothing doubled: the
    # canvas is exactly as deep as the run reached.
    assert got.shape[0] == (grid[0] - 1) * step[0] + tile[0]
    assert (got > 0).all(), "there are blank planes between the stacks"

    # And every voxel of every stack is still in the archive, overlap included.
    by_corner = {
        _corner_of(store): store
        for store in sorted(run.tiles_folder.glob("*.ome.zarr"))
    }
    for (frame, channel, iz, iy, ix), picture in written.items():
        store = by_corner[(iz * step[0], iy * step[1], ix * step[2])]
        assert (np.asarray(_level0(store)[frame, channel]) == picture).all()


def test_a_run_that_does_not_overlap_in_depth_is_not_trimmed_in_depth(tmp_path):
    """The ordinary case: overlap across the specimen only, and depth left alone.

    Trimming is worked out axis by axis, so a run that overlaps in ``y`` and ``x``
    and steps a whole stack in ``z`` must keep every plane of every stack. Losing a
    plane off each end would be easy to do and hard to notice.
    """
    run = _a_run(tmp_path / "run")
    assert run.trimming.overlap[0] == 0
    assert run.trimming.half[0] == 0
    assert run.shift[0] == 0

    written = _fill_a_raster(run)
    run.close()
    got = _what_the_canvas_holds(run)
    assert got.shape[0] == TILE[0], "the canvas lost planes it should have kept"
    assert (got[0] > 0).all() and (got[-1] > 0).all()
    assert (got[:, :TILE[1], :TILE[2]][:, 0, 0] == written[(0, 0, 0, 0, 0)][:, 0, 0]).all()


# -- the rules --------------------------------------------------------------


def test_an_odd_overlap_is_refused(tmp_path):
    """Half of an odd number of voxels is not a voxel, so it is refused outright."""
    with pytest.raises(ValueError, match="odd number of voxels"):
        _a_run(tmp_path / "run", step=(2, 97, 96))


def test_the_refusal_of_an_odd_overlap_says_what_to_step_instead(tmp_path):
    """An operator meeting this needs a number to change, not a lecture."""
    with pytest.raises(ValueError) as complaint:
        _a_run(tmp_path / "run", step=(2, 97, 96))
    said = str(complaint.value)
    assert "could be stepped 96 or 98" in said


def test_a_trimmed_tile_that_is_not_a_whole_number_of_pieces_is_refused(tmp_path):
    """The rule the arrangement rests on, checked before anything is written."""
    with pytest.raises(ValueError, match="rather than a whole number of them"):
        _a_run(tmp_path / "run", step=(2, 100, 100))


def test_the_refusal_names_an_overlap_that_would_work(tmp_path):
    """An error that only says no leaves an operator with nowhere to go.

    The overlap is the number the experiment can freely change, so that is what the
    message has to talk about — not the piece size, which most people writing a run
    never think about at all.
    """
    with pytest.raises(ValueError) as complaint:
        _a_run(tmp_path / "run", step=(2, 100, 100))
    said = str(complaint.value)
    assert "Overlaps that would work here" in said
    # A tile of 128 with pieces of 96 leaves exactly one workable overlap.
    assert "32" in said


def test_a_run_that_lines_up_is_allowed_through_without_complaint(tmp_path):
    """The positive control: the arrangement this writer is for raises nothing.

    Without it the tests above would pass just as happily against a writer that
    refused every run, which is to say against one that was useless.
    """
    with warnings.catch_warnings(record=True) as complaints:
        warnings.simplefilter("always")
        run = _a_run(tmp_path / "run")
        _fill_a_raster(run)
        run.close()
    assert not [str(said.message) for said in complaints], (
        f"an ordinary overlapping run was warned about: "
        f"{[str(said.message) for said in complaints]}"
    )
    assert run.canvas_path.is_dir()


def test_the_trimming_arithmetic_is_stated_plainly():
    """What comes off a tile, worked out on its own so the numbers can be read."""
    across = Trimming.of((2, 128, 128), (2, 96, 96))
    assert across.overlap == (0, 32, 32)
    assert across.half == (0, 16, 16)
    assert across.kept == (2, 96, 96)
    assert across.anything_to_trim

    in_depth_too = Trimming.of((8, 128, 128), (6, 96, 96))
    assert in_depth_too.overlap == (2, 32, 32)
    assert in_depth_too.half == (1, 16, 16)
    assert in_depth_too.kept == (6, 96, 96)

    # A run that does not overlap at all is not an error. Nothing is trimmed and
    # the canvas holds whole tiles, which is exactly what TileCanvases would do —
    # the non-overlapping case is the same arithmetic with the overlap at nought,
    # not a case of its own.
    none = Trimming.of((2, 128, 128), (2, 128, 128))
    assert not none.anything_to_trim
    assert none.overlap == (0, 0, 0) and none.half == (0, 0, 0)
    assert none.kept == (2, 128, 128)


def test_a_run_whose_tiles_butt_up_is_trimmed_by_nothing_at_all(tmp_path):
    """The non-overlapping case must behave exactly as it does today.

    That is worth a test of its own rather than being left to the arithmetic. A run
    that does not overlap gets no trimming, no blank margin, and a canvas whose
    corner is the one it was given — which is to say, the picture such a run has
    always produced.
    """
    run = _a_run(tmp_path / "run", step=TILE, chunk=128, origin_um=(3.0, 4.0, 5.0))
    assert run.trimming.overlap == (0, 0, 0)
    assert run.shift == (0, 0, 0)

    written = _fill_a_raster(run, step=TILE)
    run.close()

    moved = _where_it_says_it_sits(run.canvas_path)
    assert tuple(moved[2:]) == pytest.approx((3.0, 4.0, 5.0)), (
        f"a run with no overlap has no blank margin to allow for, so its canvas "
        f"should begin at exactly the corner it was given, (3.0, 4.0, 5.0). It "
        f"begins at {tuple(moved[2:])} instead"
    )

    canvas = _level0(run.canvas_path)
    for (frame, channel, iz, iy, ix), picture in written.items():
        got = np.asarray(canvas[
            frame, channel,
            iz * TILE[0]:(iz + 1) * TILE[0],
            iy * TILE[1]:(iy + 1) * TILE[1],
            ix * TILE[2]:(ix + 1) * TILE[2],
        ])
        assert (got == picture).all(), (
            "a run whose tiles butt up had a tile trimmed or moved"
        )


def test_a_canvas_narrower_than_one_piece_uses_a_smaller_piece():
    """A piece of an image cannot be larger than the image it is a piece of.

    This matters because the rule about trimmed tiles landing on whole pieces has to
    be checked against the pieces the canvas will really be stored in. A run of one
    tile can easily be narrower than the few hundred voxels a piece is usually asked
    to be, and checking against the number that was asked for rather than the one in
    use would refuse a perfectly good run — or, worse, let a bad one through.
    """
    assert the_piece_the_canvas_will_use((2, 64, 64), 256) == 64
    assert the_piece_the_canvas_will_use((2, 4096, 4096), 256) == 256
    # The narrower of the two sides decides, because one piece size covers both.
    assert the_piece_the_canvas_will_use((2, 4096, 100), 256) == 100


def test_a_stage_that_never_moves_is_refused():
    """A step of nothing means every tile is the same field of view."""
    with pytest.raises(ValueError, match="step has to be at least one voxel"):
        Trimming.of((2, 128, 128), (2, 0, 96))


def test_which_sides_have_a_neighbour_is_read_from_the_pattern():
    """The one piece of reasoning that decides where trimming happens."""
    # A tile in the middle of a 3x3 raster meets a neighbour on every side.
    assert neighbours_of((0, 1, 1), (1, 3, 3)) == (
        (False, False), (True, True), (True, True)
    )
    # The corner tile has neighbours only on its high sides.
    assert neighbours_of((0, 0, 0), (1, 3, 3)) == (
        (False, False), (False, True), (False, True)
    )
    # And the far corner only on its low sides.
    assert neighbours_of((0, 2, 2), (1, 3, 3)) == (
        (False, False), (True, False), (True, False)
    )
    # A position the workflow chose for itself has no place in a pattern, so
    # nothing is going to butt up against it and nothing comes off.
    assert neighbours_of(None, (1, 3, 3)) == ((False, False),) * 3
    # Without the pattern's size the far edge cannot be recognised, so every high
    # side is treated as having a neighbour. The low sides are still read from the
    # tile's own index, which needs nothing else to be understood.
    assert neighbours_of((0, 2, 2), None) == (
        (False, True), (True, True), (True, True)
    )


# -- colours and moments -------------------------------------------------------


def test_two_colours_and_two_moments_do_not_collide(tmp_path):
    """Four recordings of one field of view, each still its own picture.

    This is the case a timelapse of a two-colour specimen produces on every
    revisit, and it is the one where a writer that keyed anything on position alone
    would quietly hand back the last thing written. Both artefacts are checked: the
    archive keeps all four in one image, and the canvas keeps them in four different
    slices of itself.
    """
    grid = (1, 2, 2)
    run = _a_run(tmp_path / "run", grid=grid, channels=2, frames=2)
    written = _fill_a_raster(run, grid=grid, channels=2, frames=2)
    run.close()

    # One image per position, not one per position and colour and moment. Four
    # recordings of one field belong together.
    assert len(run.tile_paths) == 4, (
        "two colours and two moments of a 2x2 raster should be four positions, "
        f"not {len(run.tile_paths)} images"
    )

    canvas = _level0(run.canvas_path)
    assert canvas.shape[0] == 2 and canvas.shape[1] == 2

    for frame in range(2):
        for channel in range(2):
            expected = _the_picture_the_canvas_should_hold(
                run, written, grid=grid, frame=frame, channel=channel
            )
            got = _what_the_canvas_holds(
                run, grid=grid, frame=frame, channel=channel
            )
            assert (got == expected).all(), (
                f"moment {frame}, colour {channel} does not hold what was written "
                "to it"
            )

    # The four are genuinely different pictures, so the comparison above could
    # have failed. Without this the test would pass on a writer that put the same
    # thing everywhere.
    seen = {
        _what_the_canvas_holds(run, grid=grid, frame=f, channel=c).tobytes()
        for f in range(2) for c in range(2)
    }
    assert len(seen) == 4, "the four moments and colours are not four pictures"

    # And in the archive, where all four live inside one image.
    by_corner = {
        _corner_of(store): store
        for store in sorted(run.tiles_folder.glob("*.ome.zarr"))
    }
    for (frame, channel, iz, iy, ix), picture in written.items():
        store = by_corner[(iz * STEP[0], iy * STEP[1], ix * STEP[2])]
        back = np.asarray(_level0(store)[frame, channel])
        assert (back == picture).all(), (
            f"the archive lost moment {frame}, colour {channel} of the tile at "
            f"({iy}, {ix})"
        )


def test_a_moment_nobody_imaged_stays_empty(tmp_path):
    """Declaring room for a timelapse must not put anything in it.

    A moment that reads back as picture when nothing was recorded in it would be
    the worst kind of mistake to make in a timelapse, because there is nothing on
    screen to say the frame is a copy of another one.
    """
    run = _a_run(tmp_path / "run", grid=(1, 2, 2), frames=3)
    run.write(_a_tile(1), origin=(0, 0, 0), frame=0, tile_index=(0, 0, 0))
    run.close()

    canvas = _level0(run.canvas_path)
    assert np.asarray(canvas[0, 0]).any(), "the moment that was imaged is empty"
    assert not np.asarray(canvas[1, 0]).any(), (
        "a moment nothing was written to holds picture"
    )


# -- the smallest run there is -------------------------------------------------


def test_one_tile_on_its_own_works(tmp_path):
    """A run of a single tile, which is the case most likely to be got wrong.

    It has no neighbours at all, so nothing is trimmed and the canvas holds the
    whole tile — which is right: there is no second recording of anything, so
    cutting a strip off would simply lose it.

    Nothing is warned about either, and that is worth insisting on. A run of one
    tile is a perfectly ordinary thing to do — a single target, a test exposure —
    and an operator who meets a warning for doing it learns to stop reading them.
    """
    with warnings.catch_warnings(record=True) as complaints:
        warnings.simplefilter("always")
        run = TilesAndCanvas.create(
            tmp_path / "run",
            name="targetscan",
            canvas_shape=TILE,
            tile_shape=TILE,
            tile_step=STEP,
            tile_grid=(1, 1, 1),
            voxel_size_um=VOXEL_UM,
            channels=[Channel("488")],
            chunk=CHUNK,
        )
    assert not [str(said.message) for said in complaints], (
        "a perfectly ordinary one-tile run was warned about: "
        f"{[str(said.message) for said in complaints]}"
    )

    picture = _a_tile(99)
    where = run.write(picture, origin=(0, 0, 0), tile_index=(0, 0, 0))
    run.close()

    assert (np.asarray(_level0(where)[0, 0]) == picture).all(), (
        "the one tile of a one-tile run was not archived whole"
    )
    got = _what_the_canvas_holds(run, grid=(1, 1, 1))
    assert (got == picture).all(), (
        "the canvas of a one-tile run does not hold the whole of that tile, and "
        "with no neighbour anywhere there was nothing to trim against"
    )


def test_a_target_with_no_place_in_a_pattern_is_kept_whole(tmp_path):
    """A position the workflow chose for itself, which has no row and column.

    Smart microscopy produces these constantly — the run looks at an overview,
    decides something is interesting, and goes there. Such a tile has no place in
    any raster and nothing is going to butt up against it, so it is kept whole and
    the canvas checks it against what it has already put down.
    """
    run = _a_run(tmp_path / "run")
    picture = _a_tile(5)
    run.write(picture, origin=(0, STEP[1], STEP[2]))
    run.close()

    at = (run.shift[0], STEP[1] + run.shift[1], STEP[2] + run.shift[2])
    got = np.asarray(_level0(run.canvas_path)[
        0, 0,
        at[0]:at[0] + TILE[0],
        at[1]:at[1] + TILE[1],
        at[2]:at[2] + TILE[2],
    ])
    assert (got == picture).all()


# -- the record of where the run went ------------------------------------------


def test_the_run_keeps_one_record_of_where_it_imaged(tmp_path):
    """Coverage is answered by the existing record rather than by a second one.

    Two records of the same thing would have to be kept in step, and the day they
    disagreed there would be no way of telling which was right. So this checks that
    what comes back is the ordinary :mod:`zmart_storage.coverage` record, measured
    in the canvas's own voxels.
    """
    grid = (1, 2, 2)
    run = _a_run(tmp_path / "run", grid=grid)
    _fill_a_raster(run, grid=grid)
    run.close()

    covered = run.coverage()
    assert covered.recorded, "no record of where the run imaged was kept at all"
    assert len(covered.tiles) == 4

    extent = _full_extent(grid)
    shift = run.shift
    assert covered.was_imaged(shift[0], shift[1], shift[2])
    assert covered.was_imaged(
        shift[0] + extent[0] - 1, shift[1] + extent[1] - 1, shift[2] + extent[2] - 1
    )
    assert not covered.was_imaged(shift[0], shift[1] + extent[1], shift[2]), (
        "the record claims ground beyond the tiles that were written"
    )
    # The tiles butt up, so the four of them are one rectangle rather than four.
    # That is the property that keeps the record small on a run of thousands.
    assert len(covered.regions) == 1, (
        f"tiles that butt up should join into one region: {covered.regions}"
    )
    covering = covered.regions[0]
    assert (covering.z1 - covering.z0, covering.y1 - covering.y0,
            covering.x1 - covering.x0) == extent, (
        "the record does not cover the full extent the run imaged"
    )


def test_a_tile_of_the_wrong_size_is_refused(tmp_path):
    """Trimming is worked out from the declared size, so the sizes have to agree."""
    run = _a_run(tmp_path / "run")
    with pytest.raises(ValueError, match="the run was declared with tiles of"):
        run.write(np.zeros((2, 64, 64), dtype="uint16"), origin=(0, 0, 0))


# -- the rule this whole arrangement leaves standing ---------------------------


def test_the_plain_writer_still_refuses_an_overlapping_run(tmp_path):
    """Trimming makes the refusal unnecessary; it does not make it go away.

    :class:`TileCanvases` writes everything into one image, one image holds a
    single value per voxel, and so a run whose tiles overlap must still be refused
    there — quietly losing a fifth of an acquisition is exactly what that refusal
    exists to prevent. This file's whole approach is to satisfy that rule by
    trimming rather than to argue with it, and this test is what would notice if
    somebody weakened it instead.
    """
    with pytest.raises(ValueError, match="these tiles overlap"):
        TileCanvases.create(
            tmp_path / "plain",
            name="overview",
            canvas_shape=(2, 288, 288),
            tile_shape=TILE,
            tile_step=STEP,
            voxel_size_um=VOXEL_UM,
            channels=[Channel("488")],
            chunk=CHUNK,
        )


def test_the_canvas_is_the_only_image_a_viewer_would_open(tmp_path):
    """The archive must not look like part of the picture.

    A viewer pointed at a run's folder opens the images it finds there. If the
    whole tiles sat beside the canvas as images in their own right, opening a run
    of ten thousand tiles would mean opening ten thousand images — which is the
    very cost the canvas exists to remove, paid anyway.
    """
    run = _a_run(tmp_path / "run", grid=(1, 2, 2))
    _fill_a_raster(run, grid=(1, 2, 2))
    run.close()

    folder = tmp_path / "run"
    images = sorted(
        child.name for child in folder.iterdir()
        if child.is_dir() and (child / ".zattrs").exists()
    )
    assert images == ["overview.ome.zarr"], (
        f"a viewer looking in the run's folder would find {images}, and it should "
        "find the canvas and nothing else"
    )
    assert run.paths == [run.canvas_path]

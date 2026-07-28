"""Does a tile actually land where it was put, and does the overlap survive?

These are the two questions the design rests on. The first is ordinary
correctness. The second is the whole reason there is more than one image: if
overlapping tiles are written into a single image, the second one to arrive
quietly erases the shared strip, and no error is raised to say so. The test
below writes exactly that situation both ways and looks at the pixels.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import zarr

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from zmart_storage.canvas import Channel, TileCanvases, slots_per_axis

# A small run: tiles 64 voxels across, stepped 48, so neighbours share 16 voxels.
# That is a third of a tile, which is more overlap than anyone acquires -- chosen
# so the shared strip is large enough to see plainly in a failure message.
TILE = (2, 64, 64)
STEP = (2, 48, 48)
GRID = 4  # tiles per side


def _canvases(folder: Path, **kwargs) -> TileCanvases:
    return TileCanvases.create(
        folder,
        canvas_shape=(2, 512, 512),
        tile_shape=TILE,
        tile_step=STEP,
        voxel_size_um=(2.0, 0.35, 0.35),
        channels=[Channel("488")],
        levels=2,
        chunk=64,
        **kwargs,
    )


def _write_a_grid(canvases: TileCanvases) -> dict[tuple[int, int], int]:
    """Fill a small raster of overlapping tiles, each a flat, distinct value.

    Giving every tile its own value is what makes the overlap question
    answerable: afterwards you can look at any voxel and say which tile it came
    from, so a tile that was overwritten is obvious rather than merely suspected.
    """
    expected = {}
    for row in range(GRID):
        for col in range(GRID):
            value = 1000 + row * GRID + col
            canvases.write(
                np.full(TILE, value, dtype="uint16"),
                origin=(0, row * STEP[1], col * STEP[2]),
                tile_index=(0, row, col),
            )
            expected[(row, col)] = value
    return expected


def _read_level0(store: Path) -> np.ndarray:
    return np.asarray(zarr.open_group(str(store), mode="r")["0"][0, 0])


# -- how many images a run needs ---------------------------------------------


@pytest.mark.parametrize(
    ("tile", "step", "wanted"),
    [
        (64, 64, 1),   # no overlap at all: one image is enough
        (64, 58, 2),   # a tenth of a tile shared -- the ordinary case
        (64, 48, 2),   # a third shared
        (64, 32, 2),   # exactly half: still two
        (64, 24, 3),   # more than half, which no tiled acquisition does
    ],
)
def test_how_many_images_one_axis_needs(tile, step, wanted):
    """Two images per axis is enough for any overlap up to half a tile."""
    assert slots_per_axis(tile, step) == wanted


# -- tiles landing where they were put ---------------------------------------


def test_a_tile_lands_where_it_was_put(tmp_path):
    canvases = _canvases(tmp_path)
    tile = np.arange(2 * 64 * 64, dtype="uint16").reshape(TILE)

    canvases.write(tile, origin=(0, 128, 192), tile_index=(0, 0, 0))

    written = _read_level0(canvases.paths[0])
    assert np.array_equal(written[:, 128:192, 192:256], tile)
    # And nothing was scribbled outside it: a tile that lands in the wrong place
    # would still read back correctly at the place it was asked about.
    assert written[:, 0:128, :].max() == 0


def test_the_smaller_copies_are_filled_in_as_tiles_arrive(tmp_path):
    """The zoomed-out view has to be right during a run, not only at the end."""
    canvases = _canvases(tmp_path)
    canvases.write(np.full(TILE, 4242, dtype="uint16"), origin=(0, 64, 64),
                   tile_index=(0, 0, 0))

    half = np.asarray(zarr.open_group(str(canvases.paths[0]), mode="r")["1"][0, 0])
    assert half[:, 32:64, 32:64].max() == 4242


def test_a_tile_beyond_the_declared_room_is_refused(tmp_path):
    """Better a clear complaint than a run that quietly loses its far edge."""
    canvases = _canvases(tmp_path)
    with pytest.raises(ValueError, match="past the declared room"):
        canvases.write(np.zeros(TILE, dtype="uint16"), origin=(0, 500, 0),
                       tile_index=(0, 0, 0))


# -- the overlap, which is the point -----------------------------------------


def test_every_tile_survives_when_the_run_is_spread_over_several_images(tmp_path):
    """No tile loses a single voxel, however much its neighbours overlap it."""
    canvases = _canvases(tmp_path)
    expected = _write_a_grid(canvases)

    # Four images, because tiles overlap in y and x but not in z.
    assert len(canvases.paths) == 4

    levels = [_read_level0(path) for path in canvases.paths]
    for (row, col), value in expected.items():
        y0, x0 = row * STEP[1], col * STEP[2]
        found = [
            level[:, y0:y0 + TILE[1], x0:x0 + TILE[2]]
            for level in levels
            if level[0, y0, x0] == value
        ]
        assert found, f"tile ({row}, {col}) is not in any image"
        assert (found[0] == value).all(), (
            f"tile ({row}, {col}) was partly overwritten: "
            f"{int((found[0] != value).sum())} of {found[0].size} voxels lost"
        )


def test_a_single_image_loses_the_overlap(tmp_path):
    """The same run written into one image, to show what it costs.

    This is not a fault being reported -- it is what a single image *means*, and
    it is here so the cost is a measured number rather than an argument.
    """
    canvases = _canvases(tmp_path, slots=(1, 1, 1))
    expected = _write_a_grid(canvases)

    assert len(canvases.paths) == 1
    written = _read_level0(canvases.paths[0])

    lost = 0
    for (row, col), value in expected.items():
        y0, x0 = row * STEP[1], col * STEP[2]
        patch = written[:, y0:y0 + TILE[1], x0:x0 + TILE[2]]
        lost += int((patch != value).sum())

    total = len(expected) * int(np.prod(TILE))
    # Every tile except those on the far edges is eaten into by its neighbours.
    assert lost > 0
    print(f"\none image: {lost} of {total} voxels overwritten "
          f"({100 * lost / total:.0f}% of what was acquired)")


def test_two_tiles_written_at_once_do_not_corrupt_each_other(tmp_path):
    """Concurrent writes that share a piece of image are held apart.

    Without this, both writers read the shared piece, each adds its own tile to
    its own copy, and whichever finishes second erases the other's contribution
    -- silently, with the picture merely coming out wrong.
    """
    import threading

    canvases = _canvases(tmp_path, slots=(1, 1, 1))
    # Deliberately overlapping, and deliberately not lined up with the pieces of
    # image, which is the arrangement that goes wrong.
    def write(value, x0):
        canvases.write(np.full(TILE, value, dtype="uint16"), origin=(0, 0, x0),
                       tile_index=(0, 0, 0))

    threads = [threading.Thread(target=write, args=(v, x))
               for v, x in ((111, 0), (222, 40), (333, 80), (444, 120))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    written = _read_level0(canvases.paths[0])
    # Each tile has a strip that belongs to it alone: past where the tile on its
    # left reaches, and before the one on its right begins. Whichever order the
    # four writes happened in, those strips must hold that tile's own value.
    # They also straddle the boundary between two pieces of image, which is
    # exactly where two writers would tread on each other without the guard.
    for value, x0 in ((222, 40), (333, 80), (444, 120)):
        mine_alone = written[:, :TILE[1], x0 + (TILE[2] - 40):x0 + 40]
        assert (mine_alone == value).all(), (
            f"the tile at x={x0} lost {int((mine_alone != value).sum())} of its "
            f"own {mine_alone.size} voxels to a concurrent write"
        )

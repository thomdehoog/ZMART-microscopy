"""Does a tile land where it was put, and is the rule about overlap enforced?

The arrangement this writer is for is **one image per acquisition type, with tiles
that do not overlap**. Most of what follows checks that ordinary path.

The rest checks the rule itself. A run whose tiles overlap must not be written
into one image as it goes, because the second tile to arrive replaces the strip
it shares with the first — and those two recordings of the shared strip are
exactly what a stitcher compares. Such a run keeps its tiles separate and is
stitched once it has finished. The writer refuses rather than letting it happen
quietly, and the tests below pin both the refusal and what it is protecting
against.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import zarr

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from zmart_storage.canvas import Channel, TileCanvases, slots_per_axis

# Tiles 128 voxels across. With 64-voxel pieces and two levels of shrunk-down
# copies, a whole piece is 128 voxels -- so a tile is exactly one piece and tiles
# never share one, which is the arrangement to aim for.
TILE = (2, 128, 128)
BUTTED_UP = (2, 128, 128)    # the rule: the stage steps by a whole tile
OVERLAPPING = (2, 112, 112)  # a run that must be stitched afterwards instead
GRID = 4


def _canvases(folder: Path, *, step=BUTTED_UP, **kwargs) -> TileCanvases:
    return TileCanvases.create(
        folder,
        name="overview",
        canvas_shape=(2, 640, 640),
        tile_shape=TILE,
        tile_step=step,
        voxel_size_um=(2.0, 0.35, 0.35),
        channels=[Channel("488")],
        levels=2,
        chunk=64,
        **kwargs,
    )


def _write_a_grid(canvases: TileCanvases, step=BUTTED_UP) -> dict[tuple[int, int], int]:
    """Fill a small raster, each tile a flat value of its own.

    Giving every tile its own value is what makes the overlap question
    answerable: afterwards you can look at any voxel and say which tile it came
    from, so a tile that was written over is obvious rather than merely suspected.
    """
    expected = {}
    for row in range(GRID):
        for col in range(GRID):
            value = 1000 + row * GRID + col
            canvases.write(
                np.full(TILE, value, dtype="uint16"),
                origin=(0, row * step[1], col * step[2]),
                tile_index=(0, row, col),
            )
            expected[(row, col)] = value
    return expected


def _read_level0(store: Path) -> np.ndarray:
    """The full-resolution image as (z, y, x), whatever leading axes it declares.

    A run of a single moment has no time axis, so the number of indexes to step
    past before reaching the planes is not fixed. Counting from the end keeps the
    tests honest about that instead of assuming a shape.
    """
    array = zarr.open_group(str(store), mode="r")["0"]
    return np.asarray(array[(0,) * (array.ndim - 3)])


# -- the rule ----------------------------------------------------------------


def test_a_run_with_overlapping_tiles_is_refused(tmp_path):
    """Overlap and one image do not go together, and saying so early is the point.

    Discovering it instead from a picture that looks subtly wrong, weeks later, is
    the outcome this prevents.
    """
    with pytest.raises(ValueError, match="these tiles overlap"):
        _canvases(tmp_path, step=OVERLAPPING)


def test_the_refusal_says_what_to_do_instead(tmp_path):
    """An error that only says no leaves the operator stuck."""
    with pytest.raises(ValueError) as complaint:
        _canvases(tmp_path, step=OVERLAPPING)
    said = str(complaint.value)
    assert "step the stage by the whole tile" in said
    assert "stitch" in said


def test_tiles_that_do_not_divide_into_pieces_are_only_a_warning(tmp_path):
    """Awkward sizes cost speed, not correctness, so they must not stop a run."""
    with pytest.warns(UserWarning, match="does not divide into whole pieces"):
        canvases = TileCanvases.create(
            tmp_path, name="overview",
            canvas_shape=(2, 640, 640),
            tile_shape=(2, 100, 100), tile_step=(2, 100, 100),
            voxel_size_um=(2.0, 0.35, 0.35),
            channels=[Channel("488")], levels=2, chunk=64,
        )
    canvases.write(np.full((2, 100, 100), 7, dtype="uint16"),
                   origin=(0, 0, 0), tile_index=(0, 0, 0))
    assert _read_level0(canvases.paths[0])[0, 50, 50] == 7


@pytest.mark.parametrize(
    ("tile", "step", "wanted"),
    [
        (64, 64, 1),   # butted up, which is the rule: one image is enough
        (64, 58, 2),   # a tenth of a tile shared
        (64, 32, 2),   # exactly half: still two
        (64, 24, 3),   # more than half, which no tiled acquisition does
    ],
)
def test_how_many_images_an_overlapping_run_would_need(tile, step, wanted):
    """Only relevant to a run being spread deliberately, but worth pinning."""
    assert slots_per_axis(tile, step) == wanted


# -- the ordinary path: one image, tiles butted up ---------------------------


def test_one_acquisition_type_is_one_image_named_after_it(tmp_path):
    """The viewer groups rows by this name, so it is what the operator sees."""
    canvases = _canvases(tmp_path)
    assert [p.name for p in canvases.paths] == ["overview.ome.zarr"]


def test_a_tile_lands_where_it_was_put(tmp_path):
    canvases = _canvases(tmp_path)
    tile = np.arange(2 * 128 * 128, dtype="uint16").reshape(TILE)

    canvases.write(tile, origin=(0, 128, 256), tile_index=(0, 1, 2))

    written = _read_level0(canvases.paths[0])
    assert np.array_equal(written[:, 128:256, 256:384], tile)
    # And nothing was scribbled outside it: a tile that landed in the wrong place
    # would still read back correctly at the place it was asked about.
    assert written[:, 0:128, :].max() == 0


def test_every_tile_survives_when_they_do_not_overlap(tmp_path):
    """The ordinary run: nothing is written over, because nothing is shared."""
    canvases = _canvases(tmp_path)
    expected = _write_a_grid(canvases)

    written = _read_level0(canvases.paths[0])
    for (row, col), value in expected.items():
        y0, x0 = row * BUTTED_UP[1], col * BUTTED_UP[2]
        patch = written[:, y0:y0 + TILE[1], x0:x0 + TILE[2]]
        assert (patch == value).all(), (
            f"tile ({row}, {col}) lost {int((patch != value).sum())} voxels"
        )


def test_the_smaller_copies_are_filled_in_as_tiles_arrive(tmp_path):
    """The zoomed-out view has to be right during a run, not only at the end."""
    canvases = _canvases(tmp_path)
    canvases.write(np.full(TILE, 4242, dtype="uint16"), origin=(0, 0, 128),
                   tile_index=(0, 0, 1))

    level1 = zarr.open_group(str(canvases.paths[0]), mode="r")["1"]
    half = np.asarray(level1[(0,) * (level1.ndim - 3)])
    assert half[:, 0:64, 64:128].max() == 4242


def test_a_tile_beyond_the_declared_room_is_refused(tmp_path):
    """Better a clear complaint than a run that quietly loses its far edge."""
    canvases = _canvases(tmp_path)
    with pytest.raises(ValueError, match="past the declared room"):
        canvases.write(np.zeros(TILE, dtype="uint16"), origin=(0, 600, 0),
                       tile_index=(0, 0, 0))


def test_tiles_written_at_once_do_not_corrupt_each_other(tmp_path):
    """Neighbouring tiles arriving together must both survive intact.

    With tiles butted up and sized to whole pieces of image they never share one,
    so this should hold with no waiting at all. It is checked rather than assumed
    because the failure it guards against is silent: two writers in one piece each
    write the whole piece back, and the second erases the first.
    """
    import threading

    canvases = _canvases(tmp_path)
    values = [(111, 0), (222, 128), (333, 256), (444, 384)]

    def write(value, x0):
        canvases.write(np.full(TILE, value, dtype="uint16"),
                       origin=(0, 0, x0), tile_index=(0, 0, x0 // 128))

    threads = [threading.Thread(target=write, args=pair) for pair in values]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    written = _read_level0(canvases.paths[0])
    for value, x0 in values:
        patch = written[:, :TILE[1], x0:x0 + TILE[2]]
        assert (patch == value).all(), (
            f"the tile at x={x0} lost {int((patch != value).sum())} of its "
            f"{patch.size} voxels to a concurrent write"
        )


# -- what the rule is protecting against -------------------------------------


def test_writing_an_overlapping_run_into_one_image_would_lose_a_fifth(tmp_path):
    """The cost the refusal exists to prevent, as a measured number.

    Reached deliberately here, by asking for a single image outright, which is the
    only way to get one for a run whose tiles overlap.
    """
    canvases = _canvases(tmp_path, step=OVERLAPPING, slots=(1, 1, 1))
    expected = _write_a_grid(canvases, step=OVERLAPPING)

    written = _read_level0(canvases.paths[0])
    lost = 0
    for (row, col), value in expected.items():
        y0, x0 = row * OVERLAPPING[1], col * OVERLAPPING[2]
        patch = written[:, y0:y0 + TILE[1], x0:x0 + TILE[2]]
        lost += int((patch != value).sum())

    total = len(expected) * int(np.prod(TILE))
    assert lost > 0
    print(f"\none image, tiles overlapping: {lost} of {total} voxels overwritten "
          f"({100 * lost / total:.0f}% of what was acquired)")


def test_spreading_an_overlapping_run_keeps_every_tile(tmp_path):
    """The other way to keep it: several images, so nothing is ever written over.

    Available deliberately, for a run that wants one artefact rather than tiles
    plus a stitching step afterwards. Not the default.
    """
    canvases = _canvases(tmp_path, step=OVERLAPPING, slots=(1, 2, 2))
    expected = _write_a_grid(canvases, step=OVERLAPPING)

    assert len(canvases.paths) == 4
    levels = [_read_level0(path) for path in canvases.paths]
    for (row, col), value in expected.items():
        y0, x0 = row * OVERLAPPING[1], col * OVERLAPPING[2]
        found = [
            level[:, y0:y0 + TILE[1], x0:x0 + TILE[2]]
            for level in levels
            if level[0, y0, x0] == value
        ]
        assert found, f"tile ({row}, {col}) is not in any image"
        assert (found[0] == value).all(), (
            f"tile ({row}, {col}) was partly overwritten: "
            f"{int((found[0] != value).sum())} voxels lost"
        )

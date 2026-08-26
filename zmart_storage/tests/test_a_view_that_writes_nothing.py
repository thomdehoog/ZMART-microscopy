"""A view over tiles that carry their own zoomed-out copies writes nothing at all.

A view has always pointed at the full-size picture rather than copying it. What it
still wrote were the zoomed-out copies — about a quarter of the picture, which on a
five-terabyte run is more than a terabyte written to look at data that already
exists.

It turns out it need not write those either, and the reason is one line in
``zmart_storage/canvas.py``::

    smaller = image[:, ::factor, ::factor]

Shrinking takes every second voxel and throws the rest away. Nothing is averaged, so
a voxel of a zoomed-out copy comes from exactly one voxel of the full-size picture,
and therefore from exactly one tile. A tile's own zoomed-out copy is therefore the
*view's* zoomed-out copy over the ground that tile covers, and can be pointed at
exactly like its full-size pieces.

There is a price, and it is a rule the acquisition has to follow. Shrinking counts
from the corner of whichever picture is being shrunk, so a tile that begins out of
step keeps a different set of voxels from the ones the view would have kept. A tile
must therefore begin on a multiple of the piece size **times the largest shrink**,
not merely of the piece size. That is checked, and refused loudly, because the
failure is a picture that is wrong rather than a picture that is missing.

These tests start small on purpose: four tiles, a picture whose every voxel says
where it came from, and comparisons against the arithmetic rather than against
another implementation of the same idea.
"""

from __future__ import annotations

import numpy as np
import pytest
import zarr

from zmart_storage.canvas import Channel, _declare_one
from zmart_storage.linked import PlacedTile, link_the_tiles

TILE = (1, 128, 128)
PIECE = 16
VOXEL_UM = (2.0, 0.35, 0.35)
ORIGIN_UM = (3.0, 1.5, 2.25)
ACROSS = 2


def a_run(folder, levels: int, nudge: int = 0):
    """Write four tiles of one picture, each keeping ``levels`` copies of itself.

    Every voxel holds a number worked out from where it sits in the *whole* picture,
    so that a picture assembled from the tiles can be checked against arithmetic
    rather than against another program that might be wrong in the same way.

    ``nudge`` shifts the tiles off the grid, for the tests that check a run which
    cannot be pointed at is refused rather than drawn wrongly.
    """
    y, x = np.indices((ACROSS * TILE[1] + nudge, ACROSS * TILE[2] + nudge),
                      dtype=np.int64)
    whole = (1000 + y * 7 + x).astype("uint16")
    tiles = []
    for index in range(ACROSS * ACROSS):
        lands_y = (index // ACROSS) * TILE[1] + (nudge if index else 0)
        lands_x = (index % ACROSS) * TILE[2] + (nudge if index else 0)
        store = folder / f"tile{index}.ome.zarr"
        arrays = _declare_one(
            store, canvas_shape=TILE, frames=1, channels=1, dtype="uint16",
            chunk=PIECE, levels=levels, voxel_size_um=VOXEL_UM,
            origin_um=(ORIGIN_UM[0],
                       ORIGIN_UM[1] + lands_y * VOXEL_UM[1],
                       ORIGIN_UM[2] + lands_x * VOXEL_UM[2]),
            channel_blocks=[Channel("488", window=(0, 65535)).described(65535)],
        )
        mine = whole[lands_y:lands_y + TILE[1], lands_x:lands_x + TILE[2]]
        arrays[0][0, 0] = np.broadcast_to(mine, TILE)
        # The tile keeps its own zoomed-out copies, shrunk the same way the canvas
        # writer shrinks: every second voxel, counted from the tile's own corner.
        for level in range(1, levels):
            factor = 2 ** level
            smaller = mine[::factor, ::factor]
            arrays[level][0, 0] = np.broadcast_to(smaller, (TILE[0], *smaller.shape))
        tiles.append(PlacedTile(store=store, lands_at=(0, lands_y, lands_x)))
    return tiles, whole


def picture_files_in(view, level: int) -> list:
    """The files of actual picture in one level, ignoring its description."""
    return [one for one in (view / str(level)).rglob("*")
            if one.is_file() and not one.name.startswith(".")]


def test_a_view_over_tiles_with_their_own_copies_writes_no_picture(tmp_path):
    """Not one byte of picture, at any zoom. This is the whole claim.

    The levels still exist as folders, because zarr needs a description saying what
    shape each copy is and how it is stored. What they hold is nothing.
    """
    levels = 4
    tiles, _ = a_run(tmp_path, levels=levels)
    built = link_the_tiles(tmp_path, name="v", tiles=tiles, levels=levels,
                           view_shape=(TILE[0], ACROSS * TILE[1], ACROSS * TILE[2]))

    for level in range(levels):
        written = picture_files_in(built.path, level)
        assert written == [], (
            f"level {level} of the view holds {len(written)} files of picture. "
            "A view over tiles that carry their own zoomed-out copies should point "
            "at all of them and write none."
        )


def test_every_zoom_is_the_picture_it_should_be(tmp_path):
    """Pointing at nothing is easy; pointing at the *right* thing is the test.

    Each level is rebuilt by following the pointers, then compared against the whole
    picture shrunk by the same amount. Not sampled — every voxel.
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "zmart-viewer" / "app" / "server"))
    import linking

    levels = 4
    tiles, whole = a_run(tmp_path, levels=levels)
    built = link_the_tiles(tmp_path, name="v", tiles=tiles, levels=levels,
                           view_shape=(TILE[0], ACROSS * TILE[1], ACROSS * TILE[2]))

    for level in range(levels):
        factor = 2 ** level
        wanted = whole[::factor, ::factor]
        rebuilt = np.zeros_like(wanted)
        for down in range(-(-wanted.shape[0] // PIECE)):
            for across in range(-(-wanted.shape[1] // PIECE)):
                held = linking.the_bytes_behind(
                    built.path, f"{level}/0/0/0/{down}/{across}")
                assert held is not None, (
                    f"no pointer for piece {down},{across} of level {level}"
                )
                named = held.path.split("/")
                block = np.asarray(
                    zarr.open_group(str(tmp_path / named[0]), mode="r")[named[1]]
                )[0, 0, 0]
                piece = block[int(named[-2]) * PIECE:(int(named[-2]) + 1) * PIECE,
                              int(named[-1]) * PIECE:(int(named[-1]) + 1) * PIECE]
                rebuilt[down * PIECE:down * PIECE + piece.shape[0],
                        across * PIECE:across * PIECE + piece.shape[1]] = piece
        assert np.array_equal(rebuilt, wanted), (
            f"level {level} followed through the pointers is not the picture "
            "shrinking the whole thing gives"
        )


def test_a_tile_off_the_coarse_grid_points_less_deep_and_writes_the_rest(tmp_path):
    """Landing on a whole piece is not enough once the copies are pointed at too.

    The nudge here is exactly one piece, so the full-size picture can be served
    from pointers perfectly well. The zoomed-out copies cannot: shrinking keeps
    every second voxel counted from the picture's own corner, and a tile one piece
    out keeps a different set of voxels entirely, so pointing at its own copies
    would draw a specimen that is not the specimen.

    What the builder does about it is not refuse — it points at the full-size
    picture, where the run does line up, and writes the zoomed-out copies from the
    tiles' pixels the way an ordinary canvas would. The view says how deep its
    pointers go, and every zoom of the picture still has to be right.
    """
    levels = 4
    tiles, whole = a_run(tmp_path, levels=levels, nudge=PIECE)
    built = link_the_tiles(
        tmp_path, name="v", tiles=tiles, levels=levels,
        view_shape=(TILE[0], ACROSS * TILE[1] + PIECE, ACROSS * TILE[2] + PIECE))

    assert built.pointed_levels == 1, (
        "a run one piece out of step with the coarse grid can point only at the "
        "full-size picture, and the view should say so"
    )
    assert picture_files_in(built.path, 0) == [], (
        "the full-size picture lines up and should still be pointers, not pixels"
    )
    assert picture_files_in(built.path, 1), (
        "the zoomed-out copies cannot be pointed at for this run, so they have "
        "to be written"
    )
    # And the picture is right at every zoom: the written copies were shrunk from
    # the view's own corner, so they hold the voxels the view would have chosen —
    # which is the whole reason pointing at the tiles' copies had to be given up.
    #
    # The nudged run does not cover its whole picture — shifting three of the four
    # tiles leaves L-shaped bands of ground nobody imaged — so the expectation is
    # assembled the same way the view is: each tile's part pasted where it lands,
    # unimaged ground left at the fill value, and the result shrunk from the
    # picture's own corner.
    covered = np.zeros((ACROSS * TILE[1] + PIECE, ACROSS * TILE[2] + PIECE),
                       dtype=whole.dtype)
    for index in range(ACROSS * ACROSS):
        lands_y = (index // ACROSS) * TILE[1] + (PIECE if index else 0)
        lands_x = (index % ACROSS) * TILE[2] + (PIECE if index else 0)
        covered[lands_y:lands_y + TILE[1], lands_x:lands_x + TILE[2]] = (
            whole[lands_y:lands_y + TILE[1], lands_x:lands_x + TILE[2]])
    for level in range(1, levels):
        factor = 2 ** level
        wanted = covered[::factor, ::factor]
        written = np.asarray(
            zarr.open_group(str(built.path), mode="r")[str(level)])[0, 0, 0]
        assert np.array_equal(written[:wanted.shape[0], :wanted.shape[1]], wanted), (
            f"level {level}, written rather than pointed, is not the picture "
            "shrinking what the tiles cover gives"
        )


def test_pointing_stops_where_a_tile_s_pieces_stop_being_full_size(tmp_path):
    """A copy smaller than one piece cannot be handed over, and must be written.

    A tile 128 voxels across shrunk four times is 8 voxels across — smaller than a
    16-voxel piece — so zarr stores that whole copy as one piece of 8. The view at
    that zoom is still larger than a piece, so its grid stays at 16, and a file of
    8-voxel pieces handed over there would be drawn wrongly or not at all, with
    nothing on screen to say so.

    Before the depth was worked out per level this went unchecked: only the
    full-size copy's storage was compared, and a view five levels deep would have
    pointed at those wrongly-sized files. Now the pointers stop one level above,
    the view says so, and the deepest copy is written instead.
    """
    levels = 5
    tiles, whole = a_run(tmp_path, levels=levels)
    built = link_the_tiles(tmp_path, name="v", tiles=tiles, levels=levels,
                           view_shape=(TILE[0], ACROSS * TILE[1], ACROSS * TILE[2]))

    assert built.pointed_levels == 4, (
        "the tiles' fourth shrink is smaller than one piece, so the pointers "
        "can go four levels deep and no further"
    )
    for level in range(4):
        assert picture_files_in(built.path, level) == [], (
            f"level {level} lines up and should be pointers, not pixels"
        )
    assert picture_files_in(built.path, 4), (
        "the copy below the pointers has to be written, or that zoom is blank"
    )
    wanted = whole[::16, ::16]
    written = np.asarray(
        zarr.open_group(str(built.path), mode="r")["4"])[0, 0, 0]
    assert np.array_equal(written[:wanted.shape[0], :wanted.shape[1]], wanted), (
        "the written deepest copy is not the picture shrinking the whole "
        "thing gives"
    )


def test_tiles_that_overlap_still_build_and_the_later_one_stands(tmp_path):
    """A run whose placements overlap is a run, not a fault.

    Fields of view meet whenever targets are chosen close together, and every
    recorded voxel is safe in the tiles themselves — a view copies nothing at
    full size. So overlap must not refuse the view. At full size the list of
    pointers decides which tile answers for a shared piece; in the *written*
    zoomed-out copies the later tile's pixels stand for the shared ground, which
    for a real specimen is the same specimen either way.

    The writer used to refuse this outright — the ordinary canvas's protection
    against silently overwriting an acquisition, doing its job in the wrong
    place — so this test is the record of why that guard does not apply here.
    """
    tiles = []
    for number, lands_x in enumerate((0, 64)):
        store = tmp_path / f"tile{number}.ome.zarr"
        arrays = _declare_one(
            store, canvas_shape=TILE, frames=1, channels=1, dtype="uint16",
            chunk=PIECE, levels=1, voxel_size_um=VOXEL_UM,
            origin_um=(ORIGIN_UM[0], ORIGIN_UM[1],
                       ORIGIN_UM[2] + lands_x * VOXEL_UM[2]),
            channel_blocks=[Channel("488", window=(0, 65535)).described(65535)],
        )
        arrays[0][0, 0] = np.full(TILE, 100 * (number + 1), dtype="uint16")
        tiles.append(PlacedTile(store=store, lands_at=(0, 0, lands_x)))

    built = link_the_tiles(tmp_path, name="v", tiles=tiles, levels=2,
                           view_shape=(TILE[0], TILE[1], TILE[2] + 64))

    assert built.tiles == 2
    written = np.asarray(
        zarr.open_group(str(built.path), mode="r")["1"])[0, 0, 0]
    # The first tile alone covers columns 0..64; from 64 on, the later tile
    # stands — both over the shared strip and over its own ground beyond.
    half = 64 // 2
    assert np.all(written[:, :half] == 100)
    assert np.all(written[:, half:(TILE[2] + 64) // 2] == 200)


def test_tiles_keeping_one_copy_still_work_and_the_view_writes_the_rest(tmp_path):
    """A run whose tiles keep only themselves has to be shown as before.

    This is what every tile written by this project looked like until now, so it
    must go on working: the view points at the full-size picture and writes the
    zoomed-out copies itself, because there is nothing to point them at.
    """
    tiles, _ = a_run(tmp_path, levels=1)
    built = link_the_tiles(tmp_path, name="v", tiles=tiles, levels=3,
                           view_shape=(TILE[0], ACROSS * TILE[1], ACROSS * TILE[2]))

    assert picture_files_in(built.path, 0) == [], (
        "the full-size picture should always be pointed at, never written"
    )
    assert picture_files_in(built.path, 1), (
        "with nothing to point at, the zoomed-out copies have to be written"
    )


def test_tiles_that_disagree_about_how_far_they_zoom_out_are_refused(tmp_path):
    """A run written two different ways is worth stopping rather than half-showing.

    The view can only point as far down as *every* tile goes. Tiles that disagree
    mean the run was written by two different arrangements, which is worth knowing
    about before it is drawn.
    """
    tiles, _ = a_run(tmp_path, levels=3)
    lonely = tmp_path / "odd"
    lonely.mkdir()
    odd, _ = a_run(lonely, levels=1)
    with pytest.raises(ValueError, match="copies of its picture"):
        link_the_tiles(tmp_path, name="v", tiles=[*tiles, odd[0]], levels=3,
                       view_shape=(TILE[0], ACROSS * TILE[1], ACROSS * TILE[2]))

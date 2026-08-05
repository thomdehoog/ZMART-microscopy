"""Keep every tile whole in one image, and put them in place when they are read.

This measures a way of having both things this project has so far had to choose
between: **one store**, which is what makes the viewer quick, and **overlap kept
intact**, which is what stitching needs and what one image normally destroys.

The idea, in one paragraph
--------------------------

Write one image in which every tile has a slot of its own, laid side by side, so
no tile is cropped and no two tiles share any ground. Nothing is lost and nothing
is written twice. What you get is a contact sheet rather than a specimen: a tile
sits at ``k x 256`` where it truly belongs at ``k x 224``, so the picture is
stretched by the overlap at every seam.

Then, when the picture is *read*, put each tile where it really goes. The address
of a tile in the store and its place on the stage are two different things, and
the second is worked out on the way out. Where two tiles genuinely cover the same
ground the later one wins, which is the same rule the viewer already uses when two
acquisitions are laid over each other.

That read-time step is the thing being timed here, because it is the thing that
decides whether this is usable.

Why it should be quick, and why the obvious alternative is not
--------------------------------------------------------------

A tile here is only *moved*, by a whole number of voxels. Producing a piece of the
true picture means working out which tiles touch it and copying rectangles. There
is no arithmetic on the pixels themselves.

The obvious alternative — asking a stitching library to fuse the tiles live,
each time a piece is asked for — was measured too, in
``measure_live_fusion_cost.py`` beside this file, and it is far slower for a
reason worth understanding: it resamples every tile through an arbitrary
transformation and builds smooth blending weights across the seams. That is the
right thing to do when tiles are rotated or shifted by fractions of a voxel, and
it costs hundreds of milliseconds a piece. This costs single-digit milliseconds
because it does none of it.

The trade is honest and should be stated: this gives a **hard seam** where two
tiles meet, not a smooth blend, and it is only correct while tiles are shifted by
whole voxels. A run that trusts its stage satisfies both.

What it reports
---------------

``virtual view over the montage``
    how long it takes to produce one piece of the true picture out of the
    slot-per-tile image.

``true image on disk``
    the control — the same piece, read from an ordinary image that was written in
    true geometry. This is the arrangement already known to draw well, so it is
    the bar to be judged against.

``largest disagreement``
    whether the two actually contain the same picture. A fast answer that is
    slightly wrong would be worse than a slow one.

``by level``
    the same work on each smaller copy, and the most tiles any one piece had to
    touch to be produced. This is the part that decides how much of the pyramid
    can be served this way and how much has to be written out — see below.

Run it with::

    python measure_tiles_in_one_store.py            # 8x8 tiles
    python measure_tiles_in_one_store.py 24         # 24x24, to check it holds

It needs nothing but numpy and zarr — no browser and no graphics card, because
none of what it measures involves drawing. It writes throwaway images under a
temporary folder and removes them afterwards.
"""

from __future__ import annotations

import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import zarr

# One tile, and how far the stage steps between them. The difference is the
# overlap -- the strip that neighbouring tiles both photographed, which is what a
# stitcher compares to work out where the stage really went.
TILE = 256
OVERLAP = 32
STEP = TILE - OVERLAP

DEPTH = 16
CHUNK = 256

# How many smaller copies to check. Each is half the width and height of the one
# before it.
#
# There is a rule hiding here and it is worth stating, because getting it wrong
# would be quiet rather than loud: placing a tile by whole voxels only works while
# the stage's step divides exactly by the shrinking factor. The step used here is
# 224 voxels, which is 32 x 7, so it divides exactly down to the fifth copy and no
# further. **Choose the overlap so that the step divides by two as many times as
# there are copies**, or the coarse copies will place tiles half a voxel out.
LEVELS = 5

# How many pieces to time. Enough to average over a slow moment, few enough that
# the whole thing stays under a minute.
HOW_MANY_PIECES = 40


def build_stores(work: Path, grid: int):
    """Write the slot-per-tile image, and the true-geometry image beside it.

    Both hold the same tiles. They differ only in where each tile was put, which
    is the whole point of the comparison.
    """
    montage_shape = (DEPTH, grid * TILE, grid * TILE)
    true_shape = (DEPTH, (grid - 1) * STEP + TILE, (grid - 1) * STEP + TILE)

    montage = zarr.open_array(
        str(work / "slot_per_tile.zarr"), mode="w", shape=montage_shape,
        chunks=(1, CHUNK, CHUNK), dtype="uint16")
    truth = zarr.open_array(
        str(work / "true_geometry.zarr"), mode="w", shape=true_shape,
        chunks=(1, CHUNK, CHUNK), dtype="uint16")

    for iy in range(grid):
        for ix in range(grid):
            # Noise rather than a flat value, so that a piece assembled out of the
            # wrong part of the store cannot accidentally match the right one.
            tile = np.random.default_rng(iy * 1000 + ix).integers(
                1000, 4000, size=(DEPTH, TILE, TILE), dtype=np.uint16)
            montage[:, iy * TILE:(iy + 1) * TILE, ix * TILE:(ix + 1) * TILE] = tile
            # Written in raster order, so where tiles overlap the later one wins.
            # The reader below has to reproduce exactly this.
            truth[:, iy * STEP:iy * STEP + TILE, ix * STEP:ix * STEP + TILE] = tile

    return montage, truth, true_shape


def read_true_piece(montage, grid, true_shape, z, y0, x0, size=CHUNK):
    """Produce one piece of the true picture out of the slot-per-tile image.

    Works out which tiles touch this piece of the specimen, then copies the part
    of each that lands inside it. Tiles are visited in the order they were
    acquired, so where two cover the same ground the later one is copied last and
    wins -- matching how the true-geometry image was written.

    Args:
        montage: the slot-per-tile image.
        grid: how many tiles across the raster is.
        true_shape: the shape of the true picture, as ``(z, y, x)``.
        z: which plane is wanted.
        y0, x0: the corner of the wanted piece, in true coordinates.
        size: how large a piece to produce.

    Returns:
        The piece, as a plain array. Pieces at the far edge come back smaller,
        which is ordinary for the last piece in a row.
    """
    y1 = min(y0 + size, true_shape[1])
    x1 = min(x0 + size, true_shape[2])
    piece = np.zeros((y1 - y0, x1 - x0), dtype=np.uint16)

    # Only the tiles whose footprint can touch this piece are considered. This is
    # what keeps the cost flat: a piece is touched by about four tiles whether the
    # run holds sixteen of them or ten thousand.
    first_iy = max(0, (y0 - TILE) // STEP + 1)
    first_ix = max(0, (x0 - TILE) // STEP + 1)
    last_iy = min(grid - 1, y1 // STEP)
    last_ix = min(grid - 1, x1 // STEP)

    for iy in range(first_iy, last_iy + 1):
        tile_y = iy * STEP
        for ix in range(first_ix, last_ix + 1):
            tile_x = ix * STEP
            # The part of this tile that lands inside the piece, in true coordinates.
            oy0, oy1 = max(y0, tile_y), min(y1, tile_y + TILE)
            ox0, ox1 = max(x0, tile_x), min(x1, tile_x + TILE)
            if oy0 >= oy1 or ox0 >= ox1:
                continue
            # The same rectangle, in this tile's own slot in the store.
            slot_y = iy * TILE + (oy0 - tile_y)
            slot_x = ix * TILE + (ox0 - tile_x)
            piece[oy0 - y0:oy1 - y0, ox0 - x0:ox1 - x0] = montage[
                z, slot_y:slot_y + (oy1 - oy0), slot_x:slot_x + (ox1 - ox0)]
    return piece


def smaller_copies(montage, grid: int, work: Path):
    """Shrink the whole store, once per copy, and write each one out.

    Shrinking the store as a whole is the same thing as shrinking each tile in its
    own slot, because the slots are a whole number of voxels wide at every copy.
    That is what keeps a tile's slot exactly where the arithmetic expects it.

    The copies are written to disk rather than kept in memory, and that matters
    for the measurement rather than for tidiness: reading a slice of an array
    already in memory is far quicker than reading one out of a store, so copies
    held in memory would report a speed the viewer could never see.
    """
    full = np.asarray(montage[:])
    copies = [montage]
    for level in range(1, LEVELS):
        factor = 2 ** level
        side = (grid * TILE) // factor
        shrunk = (full.reshape(DEPTH, side, factor, side, factor)
                      .mean(axis=(2, 4)).astype(np.uint16))
        array = zarr.open_array(
            str(work / f"slot_per_tile_copy{level}.zarr"), mode="w",
            shape=shrunk.shape, chunks=(1, CHUNK, CHUNK), dtype="uint16")
        array[:] = shrunk
        copies.append(array)
    return copies


def place_on_copy(copy, grid: int, level: int, z: int, y0: int, x0: int, shape):
    """One piece of the true picture, out of a smaller copy of the store.

    The same arithmetic as ``read_true_piece``, with the tile and the stage's step
    both shrunk by the copy's factor. Also reports how many tiles had to be
    touched, which is the number that decides whether this scales.
    """
    tile, step = TILE >> level, STEP >> level
    y1, x1 = min(y0 + CHUNK, shape[0]), min(x0 + CHUNK, shape[1])
    piece = np.zeros((y1 - y0, x1 - x0), dtype=np.uint16)
    touched = 0

    for iy in range(max(0, (y0 - tile) // step + 1), min(grid - 1, y1 // step) + 1):
        tile_y = iy * step
        for ix in range(max(0, (x0 - tile) // step + 1), min(grid - 1, x1 // step) + 1):
            tile_x = ix * step
            oy0, oy1 = max(y0, tile_y), min(y1, tile_y + tile)
            ox0, ox1 = max(x0, tile_x), min(x1, tile_x + tile)
            if oy0 >= oy1 or ox0 >= ox1:
                continue
            touched += 1
            slot_y = iy * tile + (oy0 - tile_y)
            slot_x = ix * tile + (ox0 - tile_x)
            piece[oy0 - y0:oy1 - y0, ox0 - x0:ox1 - x0] = copy[
                z, slot_y:slot_y + (oy1 - oy0), slot_x:slot_x + (ox1 - ox0)]
    return piece, touched


def _report(name: str, times: list[float]) -> float:
    ordered = sorted(times)
    middle = statistics.median(ordered)
    print(f"  {name:<34} n={len(ordered):<3} median={middle:7.2f} ms  "
          f"p90={ordered[int(len(ordered) * 0.9)]:7.2f} ms  "
          f"max={max(ordered):7.2f} ms")
    return middle


def main() -> None:
    grid = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    work = Path(tempfile.mkdtemp(prefix="tiles-in-one-store-"))
    try:
        print(f"\n{grid * grid} tiles of {TILE}x{TILE}, {OVERLAP} voxels of overlap, "
              f"{grid}x{grid} raster, {DEPTH} planes")

        started = time.perf_counter()
        montage, truth, true_shape = build_stores(work, grid)
        print(f"writing both images: {time.perf_counter() - started:.1f} s")
        print(f"the true picture is {true_shape}")

        wanted = []
        for z in range(min(DEPTH, 3)):
            for y0 in range(0, true_shape[1] - 1, CHUNK):
                for x0 in range(0, true_shape[2] - 1, CHUNK):
                    wanted.append((z, y0, x0))
        wanted = wanted[:HOW_MANY_PIECES]

        virtual, control = [], []
        for z, y0, x0 in wanted:
            started = time.perf_counter()
            read_true_piece(montage, grid, true_shape, z, y0, x0)
            virtual.append((time.perf_counter() - started) * 1000)

            started = time.perf_counter()
            np.asarray(truth[z, y0:y0 + CHUNK, x0:x0 + CHUNK])
            control.append((time.perf_counter() - started) * 1000)

        print()
        put_in_place = _report("virtual view over the montage", virtual)
        plain_read = _report("true image on disk (control)", control)
        print(f"\n  -> putting the tiles in place costs "
              f"{put_in_place / plain_read:.1f}x a plain read")

        worst = 0
        for z, y0, x0 in wanted[:12]:
            got = read_true_piece(montage, grid, true_shape, z, y0, x0)
            want = np.asarray(truth[z, y0:y0 + got.shape[0], x0:x0 + got.shape[1]])
            worst = max(worst, int(np.abs(got.astype(int) - want.astype(int)).max()))
        print(f"  -> largest disagreement with the true picture: {worst} grey levels")
        if worst:
            print("     (anything but zero means the two are not the same picture)")

        # -- the same work on each smaller copy --------------------------------
        #
        # A piece of a smaller copy covers more of the specimen, so more tiles
        # have to be touched to produce it. The question is whether that number is
        # set by *which copy* -- which is bounded, and therefore fine -- or by how
        # many tiles the run holds, which would not be.
        print("\n  on each smaller copy:")
        copies = smaller_copies(montage, grid, work)
        for level in range(LEVELS):
            tile, step = TILE >> level, STEP >> level
            side = (grid - 1) * step + tile
            spots = [(0, y, x)
                     for y in range(0, max(1, side - 1), CHUNK)
                     for x in range(0, max(1, side - 1), CHUNK)][:12]
            times, most = [], 0
            for z, y0, x0 in spots:
                started = time.perf_counter()
                _, touched = place_on_copy(copies[level], grid, level, z, y0, x0,
                                           (side, side))
                times.append((time.perf_counter() - started) * 1000)
                most = max(most, touched)
            print(f"    copy {level}  {statistics.median(times):8.2f} ms   "
                  f"touching at most {most:4d} tiles"
                  + ("   <- the whole run" if most >= grid * grid else ""))
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()

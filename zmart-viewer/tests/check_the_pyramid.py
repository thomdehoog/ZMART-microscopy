"""Do the coarser copies of a built picture show the same specimen, in the same place?

``check.py`` proves the pieces are assembled correctly, and cannot prove this. It
compares a built piece against the tiles laid out by ``Mosaic.lands_at`` — which is
the very function the composer uses — so a tile placed wrongly at some resolution
would be placed wrongly on both sides and the comparison would pass. That is a real
hole, and this is the check that closes it.

Why a resolution could genuinely be out of place
------------------------------------------------

A tile lands at a fractional position and is rounded to the nearest whole voxel
**of the copy being drawn**. Every copy rounds separately, so nothing in the code
makes the rounding at one resolution agree with the rounding at another. Two ways
that could go wrong and neither would raise anything:

- a tile could be rounded up at one resolution and down at the next, putting a
  seam half a coarse voxel from where the finer copy has it;
- if a transfer's own copies were not made by simple subsampling from the same
  corner, a coarse copy would hold a shifted specimen and the built picture would
  inherit the shift.

Either shows on screen as detail sliding as you zoom, which is exactly the fault
that is easy to blame on the viewer.

How this answers it
-------------------

By going through **micrometres**, which is the one description everything shares
and the only one not produced by the code under test. A patch of stage is chosen,
the built picture is read over that patch at full resolution and at a coarser one,
the fine copy is subsampled down to the coarse copy's grid, and the two are
compared at every small shift.

And then the same question is asked of **one tile on its own**, with no placement
and no building in it at all. That control is what makes the answer mean anything,
because a transfer's own coarse copies need not be simple subsamples of its full
resolution -- Thy1's deepest two are not -- and a picture built from them cannot
be better aligned than they are. So the verdict is not "is the coarse copy
perfect", which nothing could pass. It is **does building add any misalignment
beyond what the tile already has**, which is the only part this code is
answerable for.

A shift is only believed when taking it makes a real difference. At the deepest
copies the two answers can differ by a fraction of a per cent, which is a
measurement finding nothing rather than a copy being out of place.

Run it with::

    python check_the_pyramid.py "D:/OMEzarr data/.../Thy1_Mag25x_Ch561.ome.zarr"
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app" / "picture"))

from composer import Composer  # noqa: E402
from mosaic import read_the_transfer  # noqa: E402

# How large a patch to compare, in voxels of the coarse copy. Large enough to hold
# structure a shift would spoil, small enough to read quickly.
PATCH = 192

# How far to look for a better alignment, in coarse voxels. A copy that is right
# agrees best at nought; one rounded differently disagrees by one.
SHIFTS = 3

# How much better a shifted comparison has to be before the shift is believed. At
# the deepest copies, shifting changed the answer by three parts in a thousand,
# which is not a copy in the wrong place -- it is a flat patch of specimen where
# every alignment looks much like every other. Ten per cent is well clear of that
# and well under the third that a genuinely misplaced copy showed.
BELIEVE_A_SHIFT_AT = 0.10


def read_the_built_picture(composer: Composer, level: int, plane: int,
                           top: int, left: int, height: int,
                           width: int) -> np.ndarray:
    """A rectangle of the built picture, taken however many pieces it spans."""
    piece = composer.piece
    out = np.zeros((height, width), composer.mosaic.dtype)
    for row in range(top // piece, (top + height - 1) // piece + 1):
        for column in range(left // piece, (left + width - 1) // piece + 1):
            deep, down, across = composer.grid(level)
            if not (0 <= row < down and 0 <= column < across
                    and 0 <= plane < deep):
                continue
            built = composer._slab_for(level, plane, row, column)
            depth = composer.slab_depth(level)
            slab = built[plane - (plane // depth) * depth]
            from_y, to_y = max(top, row * piece), min(top + height,
                                                      (row + 1) * piece)
            from_x, to_x = max(left, column * piece), min(left + width,
                                                          (column + 1) * piece)
            if from_y >= to_y or from_x >= to_x:
                continue
            out[from_y - top:to_y - top, from_x - left:to_x - left] = slab[
                from_y - row * piece:to_y - row * piece,
                from_x - column * piece:to_x - column * piece]
    return out


def how_it_lines_up(fine: np.ndarray, coarse: np.ndarray) -> tuple[int, int, float]:
    """Which shift lines these two up, and only if taking it is worth believing.

    Returns the shift and how much better it is than no shift at all, as a share.
    A shift worth less than :data:`BELIEVE_A_SHIFT_AT` is reported as no shift,
    because on flat ground every alignment scores much the same and the best of
    them is noise rather than an answer.
    """
    down, across, apart = best_shift(fine, coarse)
    middle = fine[SHIFTS:-SHIFTS or None, SHIFTS:-SHIFTS or None].astype("float64")
    window = coarse[SHIFTS:coarse.shape[0] - SHIFTS,
                    SHIFTS:coarse.shape[1] - SHIFTS].astype("float64")
    at_nothing = float(np.abs(window - middle).mean())
    better = 0.0 if at_nothing == 0 else (at_nothing - apart) / at_nothing
    if better < BELIEVE_A_SHIFT_AT:
        return 0, 0, better
    return down, across, better


def best_shift(fine: np.ndarray, coarse: np.ndarray) -> tuple[int, int, float]:
    """Which small shift makes these two agree best, and how well.

    Compared by how far apart the two are on average rather than by correlation,
    because a flat patch correlates with anything and a light-sheet image has a
    great deal of near-empty ground in it.
    """
    best = (0, 0, float("inf"))
    middle = fine[SHIFTS:-SHIFTS or None, SHIFTS:-SHIFTS or None].astype("float64")
    for down in range(-SHIFTS, SHIFTS + 1):
        for across in range(-SHIFTS, SHIFTS + 1):
            window = coarse[SHIFTS + down:coarse.shape[0] - SHIFTS + down,
                            SHIFTS + across:coarse.shape[1] - SHIFTS + across]
            if window.shape != middle.shape:
                continue
            apart = float(np.abs(window.astype("float64") - middle).mean())
            if apart < best[2]:
                best = (down, across, apart)
    return best


def a_tile_on_its_own(mosaic, level: int, shrink: tuple[int, int, int]
                      ) -> tuple[int, int, float]:
    """The same question asked of one tile, with no placement and no building.

    This is the control, and without it the rest means nothing: a transfer's own
    coarse copies need not be simple subsamples of its full resolution, and a
    picture built out of them cannot line up better than they do.
    """
    tile = mosaic.tiles[0]
    fine, coarse = tile.copies[0], tile.copies[level]
    plane = min(coarse.shape[0] - 1, (fine.shape[0] // 2) // shrink[0])
    top = left = 1200 // shrink[1]
    if (top + PATCH > coarse.shape[1] or left + PATCH > coarse.shape[2]):
        top = left = 0
    held = np.asarray(coarse.array[plane, top:top + PATCH, left:left + PATCH])
    whole = np.asarray(fine.array[
        plane * shrink[0],
        top * shrink[1]:(top + PATCH) * shrink[1],
        left * shrink[2]:(left + PATCH) * shrink[2],
    ])[::shrink[1], ::shrink[2]]
    if held.shape != whole.shape:
        return 0, 0, 0.0
    return how_it_lines_up(whole, held)


def main() -> None:
    mosaic = read_the_transfer(Path(sys.argv[1]))
    composer = Composer(mosaic)

    deep0, height0, width0 = mosaic.shape(0)
    voxel0 = mosaic.voxel_um(0)
    print(f"\n  {len(mosaic.tiles)} tiles, {mosaic.levels} resolutions")
    print(f"  full resolution {height0} x {width0}, voxels of {voxel0[1]} um")

    # The middle of the imaged ground, named in micrometres so that every
    # resolution is asked the same question rather than the same voxel.
    middle_um = (
        mosaic.corner_um[0] + deep0 * voxel0[0] * 0.5,
        mosaic.corner_um[1] + height0 * voxel0[1] * 0.5,
        mosaic.corner_um[2] + width0 * voxel0[2] * 0.5,
    )
    print(f"  a patch of stage at y {middle_um[1]:.1f}, "
          f"x {middle_um[2]:.1f} um\n")
    print(f"  {'copy':>5} {'voxel um':>9} | {'the tile alone':>22} | "
          f"{'the built picture':>22} | verdict")
    print(f"  {'':>5} {'':>9} | {'shift':>10} {'better by':>11} | "
          f"{'shift':>10} {'better by':>11} |")
    print("  " + "-" * 88)

    added = 0
    for level in range(1, mosaic.levels):
        voxel = mosaic.voxel_um(level)
        shrink = tuple(int(round(voxel[axis] / voxel0[axis])) for axis in range(3))
        if shrink[1] != shrink[2] or shrink[1] < 1:
            print(f"  L{level} shrinks unevenly {shrink}; skipped")
            continue

        alone = a_tile_on_its_own(mosaic, level, shrink)  # type: ignore[arg-type]

        plane = int(round((middle_um[0] - mosaic.corner_um[0]) / voxel[0]))
        top = int(round((middle_um[1] - mosaic.corner_um[1]) / voxel[1])) - PATCH // 2
        left = int(round((middle_um[2] - mosaic.corner_um[2]) / voxel[2])) - PATCH // 2
        coarse = read_the_built_picture(composer, level, plane, top, left,
                                        PATCH, PATCH)
        plane0 = int(round((middle_um[0] - mosaic.corner_um[0]) / voxel0[0]))
        fine = read_the_built_picture(
            composer, 0, plane0, top * shrink[1], left * shrink[2],
            PATCH * shrink[1], PATCH * shrink[2])
        # Subsampled, not averaged -- the transfer's own copies are made that way,
        # and comparing against an average would report a difference that is only
        # the difference between two ways of shrinking.
        built = how_it_lines_up(fine[::shrink[1], ::shrink[2]], coarse)

        ours = max(abs(built[0] - alone[0]), abs(built[1] - alone[1]))
        added = max(added, ours)
        print(f"  L{level:>4} {voxel[1]:>9.2f} | "
              f"{f'{alone[0]}, {alone[1]}':>10} {alone[2]:>10.0%} | "
              f"{f'{built[0]}, {built[1]}':>10} {built[2]:>10.0%} | "
              + ("adds nothing" if ours == 0
                 else f"BUILDING ADDS {ours} voxel"))

    beyond = ("no misalignment beyond what the tiles themselves have"
              if added == 0 else f"{added} voxel of its own")
    print(f"\n  {'PASS' if added == 0 else 'FAIL'} — building adds {beyond}")
    print("  (a copy still sits within half a voxel of full resolution; that is")
    print("   the floor, and it is half a screen pixel at the zoom it is drawn)\n")


if __name__ == "__main__":
    main()

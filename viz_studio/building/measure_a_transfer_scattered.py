"""The real Thy1 tiles, scattered at random instead of laid on their grid.

`thy1_four_times.py` repeated the mosaic in a tidy two-by-two, where a piece of
the picture still met only one to four tiles. This puts the same twenty-four
tiles down at **random fractional positions**, which is the case a survey looks
like and the case a grid hides: scattered, some pieces meet far more tiles than
others, and the cost of a piece follows how many meet it.

It is a direct comparison with the four-times run -- the same tiles, the same
pixels, the same everything except where they are put.

Nothing is copied. Each tile folder is its own small ``zarr.json`` with a shifted
position, and its level folders are Windows directory junctions back to the
original tile's, which need no special privilege.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

# Beside the code it measures, so it finds it without being told where.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from composer import Composer  # noqa: E402
from mosaic import read_the_transfer  # noqa: E402

# The transfer to lay out again, and where to put the result. Both are given
# on the command line; these are only what this was developed against.
THY1 = Path(r"D:\OMEzarr data\Thy1-25x-3x2-1ch-OMEZARR\Thy1_Mag25x_Ch561.ome.zarr")
SCATTERED = Path(r"D:\zmart-thy1-scattered")

# How many tiles to put down, and how much of the ground to image more than once
# on average. Twenty-four so it compares with the four-times run tile for tile.
HOW_MANY = 24
COVERAGE = 2.0


def _junction(link: Path, target: Path) -> None:
    done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                          capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(f"could not link {link}: {done.stdout} {done.stderr}")


def scatter_them() -> Path:
    """Put the tiles down at random fractional places, sharing every pixel."""
    if SCATTERED.exists():
        shutil.rmtree(SCATTERED)
    SCATTERED.mkdir(parents=True)

    original = read_the_transfer(THY1)
    one = original.tiles[0].copies[0]
    voxel = original.voxel_um(0)
    tall_um = one.shape[1] * voxel[1]
    wide_um = one.shape[2] * voxel[2]

    # The area that gives the coverage asked for.
    side = float(np.sqrt(HOW_MANY * tall_um * wide_um / COVERAGE))
    seed = np.random.default_rng(19)
    corners = seed.uniform(0.0, side, size=(HOW_MANY, 2))
    print(f"  a tile is {tall_um:.0f} x {wide_um:.0f} um; "
          f"scattering {HOW_MANY} over {side:.0f} x {side:.0f} um")

    for number in range(HOW_MANY):
        source = original.tiles[number % len(original.tiles)]
        where = SCATTERED / f"Scattered{number:03d}.ome.zarr"
        where.mkdir()
        described = json.loads(
            (source.store / "zarr.json").read_text(encoding="utf-8"))
        multiscale = described["attributes"]["ome"]["multiscales"][0]
        # Where this tile's own corner is now, rather than where it was.
        was = source.copies[0].corner_um
        for dataset in multiscale["datasets"]:
            for transform in dataset["coordinateTransformations"]:
                if transform["type"] == "translation":
                    moved = list(transform["translation"])
                    moved[-2] += float(corners[number][0]) - (was[1] - original.corner_um[1])
                    moved[-1] += float(corners[number][1]) - (was[2] - original.corner_um[2])
                    transform["translation"] = moved
            _junction(where / str(dataset["path"]),
                      source.store / str(dataset["path"]))
        (where / "zarr.json").write_text(json.dumps(described), encoding="utf-8")
    print(f"  {HOW_MANY} tiles written, sharing every pixel with the original\n")
    return SCATTERED


def main() -> None:
    import argparse

    global THY1  # noqa: PLW0603 - the transfer to measure
    parsed = argparse.ArgumentParser(description=__doc__)
    parsed.add_argument("transfer", nargs="?", type=Path, default=THY1,
                        help="the folder holding one OME-Zarr per tile")
    given = parsed.parse_args()
    THY1 = given.transfer

    folder = scatter_them()

    began = time.perf_counter()
    mosaic = read_the_transfer(folder)
    opening = (time.perf_counter() - began) * 1000

    composer = Composer(mosaic)
    began = time.perf_counter()
    index = composer._tiles_in_each_piece(0)
    indexing = (time.perf_counter() - began) * 1000

    deep, down, across = composer.grid(0)
    _, height, width = mosaic.shape(0)
    voxel = mosaic.voxel_um(0)

    print(f"  {len(mosaic.tiles)} tiles, {mosaic.levels} resolutions")
    print(f"  picture    {height:,} x {width:,} voxels, {deep} planes "
          f"({height * voxel[1] / 1000:.1f} x {width * voxel[2] / 1000:.1f} mm)")
    print(f"  pieces     {down} x {across} = {down * across:,} a plane")
    print(f"  opening    {opening:.0f} ms   ({opening / len(mosaic.tiles):.2f} ms a tile)")
    print(f"  indexing   {indexing:.0f} ms")

    meeting = [len(index.get((r, c), ())) for r in range(down) for c in range(across)]
    covered = [one for one in meeting if one]
    print(f"  a piece meets {min(covered)}-{max(meeting)} tiles, "
          f"middling {int(np.median(covered))};  "
          f"{100 * (1 - len(covered) / len(meeting)):.0f}% of pieces are empty\n")

    # Pieces taken at random across the whole picture, so empty ground is met in
    # the proportion it really occurs.
    seed = np.random.default_rng(5)
    for level, label in ((0, "full resolution"), (2, "quarter size")):
        deep_here, down_here, across_here = composer.grid(level)
        plane = deep_here // 2
        full, empty = [], []
        for _ in range(24):
            row = int(seed.integers(0, down_here))
            column = int(seed.integers(0, across_here))
            fresh = Composer(mosaic)
            began = time.perf_counter()
            fresh._build_slab(level, plane, row, column)
            spent = (time.perf_counter() - began) * 1000
            (full if composer._tiles_in_each_piece(level).get((row, column))
             else empty).append(spent)
        middling = f"{np.median(full):.0f} ms" if full else "-"
        worst = f"{max(full):.0f} ms" if full else "-"
        print(f"  {label:<16} where tiles are: middling {middling:>8}, "
              f"worst {worst:>8}   ({len(full)} pieces)")
        if empty:
            print(f"  {'':<16} where none are:  middling "
                  f"{np.median(empty):.1f} ms   ({len(empty)} pieces)")
    print()


if __name__ == "__main__":
    main()

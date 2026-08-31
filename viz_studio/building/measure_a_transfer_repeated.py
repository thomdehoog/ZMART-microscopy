"""The Thy1 transfer laid out four times over, and what that costs to open.

Six tiles is a small mosaic. This makes a transfer of **twenty-four** by repeating
the same six in a two-by-two arrangement, so the picture is four times the area --
about 144 GB of specimen as far as anything reading it is concerned.

Nothing is copied. A tile folder is a small ``zarr.json`` saying where the tile
sits, and level folders holding the pixels; so each of the twenty-four gets its
own ``zarr.json`` with a shifted position, and its level folders are **junctions**
back to the original tile's. Junctions rather than symbolic links because Windows
grants those without special privilege, which this machine does not have.

The point is not the specimen -- it is the same specimen four times, and will look
it. The point is what a transfer four times the size costs to open and to draw,
measured on real blocks rather than on the synthetic tiles the scaling ladder
uses, which compress to almost nothing and so read unrealistically fast.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Beside the code it measures, so it finds it without being told where.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from composer import Composer  # noqa: E402
from mosaic import read_the_transfer  # noqa: E402

# The transfer to lay out again, and where to put the result. Both are given
# on the command line; these are only what this was developed against.
THY1 = Path(r"D:\OMEzarr data\Thy1-25x-3x2-1ch-OMEZARR\Thy1_Mag25x_Ch561.ome.zarr")
FOUR = Path(r"D:\zmart-thy1-x4")

# How many times across and down to repeat the mosaic.
ACROSS = 2
DOWN = 2


def _junction(link: Path, target: Path) -> None:
    """A directory junction, which Windows allows without any special privilege."""
    done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                          capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(f"could not link {link} -> {target}: "
                           f"{done.stdout} {done.stderr}")


def lay_it_out_four_times() -> Path:
    """Write the repeated transfer, sharing every pixel with the original."""
    if FOUR.exists():
        shutil.rmtree(FOUR)
    FOUR.mkdir(parents=True)

    original = read_the_transfer(THY1)
    _, height, width = original.shape(0)
    voxel = original.voxel_um(0)
    step_y, step_x = height * voxel[1], width * voxel[2]
    print(f"  one mosaic is {height} x {width} voxels "
          f"({step_y:.1f} x {step_x:.1f} um)")

    made = 0
    for down in range(DOWN):
        for across in range(ACROSS):
            for tile in original.tiles:
                where = FOUR / f"r{down}c{across}_{tile.name}"
                where.mkdir()
                described = json.loads(
                    (tile.store / "zarr.json").read_text(encoding="utf-8"))
                multiscale = described["attributes"]["ome"]["multiscales"][0]
                for dataset in multiscale["datasets"]:
                    for transform in dataset["coordinateTransformations"]:
                        if transform["type"] == "translation":
                            moved = list(transform["translation"])
                            moved[-2] += down * step_y
                            moved[-1] += across * step_x
                            transform["translation"] = moved
                    _junction(where / str(dataset["path"]),
                              tile.store / str(dataset["path"]))
                (where / "zarr.json").write_text(json.dumps(described),
                                                 encoding="utf-8")
                made += 1
    print(f"  {made} tiles written, sharing every pixel with the original\n")
    return FOUR


def main() -> None:
    import argparse

    global THY1  # noqa: PLW0603 - the transfer to measure
    parsed = argparse.ArgumentParser(description=__doc__)
    parsed.add_argument("transfer", nargs="?", type=Path, default=THY1,
                        help="the folder holding one OME-Zarr per tile")
    given = parsed.parse_args()
    THY1 = given.transfer

    folder = lay_it_out_four_times()

    began = time.perf_counter()
    mosaic = read_the_transfer(folder)
    opening = (time.perf_counter() - began) * 1000

    composer = Composer(mosaic)
    began = time.perf_counter()
    composer._tiles_in_each_piece(0)
    indexing = (time.perf_counter() - began) * 1000

    deep, down, across = composer.grid(0)
    _, height, width = mosaic.shape(0)
    voxel = mosaic.voxel_um(0)
    apparent = height * width * deep * 2 / 1e9

    print(f"  {len(mosaic.tiles)} tiles, {mosaic.levels} resolutions")
    print(f"  picture    {height:,} x {width:,} voxels, {deep} planes "
          f"({height * voxel[1] / 1000:.1f} x {width * voxel[2] / 1000:.1f} mm)")
    print(f"  that is    {apparent:.0f} GB of specimen, from 36 GB on disk")
    print(f"  pieces     {down} x {across} = {down * across:,} a plane")
    print(f"  opening    {opening:.0f} ms   ({opening / len(mosaic.tiles):.2f} ms a tile)")
    print(f"  indexing   {indexing:.0f} ms")

    index = composer._tiles_in_each_piece(0)
    meeting = [len(index.get((r, c), ())) for r in range(down) for c in range(across)]
    covered = [one for one in meeting if one]
    print(f"  a piece meets {min(covered)}-{max(meeting)} tiles "
          f"({100 * (1 - len(covered) / len(meeting)):.0f}% of pieces are empty)\n")

    # What a screenful costs, in the middle where four mosaics meet.
    for level, label in ((0, "full resolution"), (2, "quarter size"),
                         (4, "sixteenth size")):
        deep_here, down_here, across_here = composer.grid(level)
        plane = deep_here // 2
        fresh = Composer(mosaic)
        began = time.perf_counter()
        for row in range(down_here // 2, min(down_here, down_here // 2 + 4)):
            for column in range(across_here // 2,
                                min(across_here, across_here // 2 + 4)):
                fresh._build_slab(level, plane, row, column)
        print(f"  {label:<16} a screenful of up to 16 pieces: "
              f"{(time.perf_counter() - began) * 1000:>7.0f} ms")
    print()


if __name__ == "__main__":
    main()

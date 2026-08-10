"""Ten thousand tiles, scattered, shown as one picture.

Every measurement so far put tiles on a grid, where each of them meets its
neighbours in the same way and a piece of the picture always meets the same nine.
That is the easy case and it is also the honest one for a mosaic, but it hides two
things a survey would not:

**Some pieces meet far more tiles than the average.** Scattered at random, how many
tiles cover a piece follows a distribution rather than a number, and the slowest
piece is what an operator feels. The median is the wrong statistic to stop at.

**Most of the picture is ground nobody imaged.** A survey is sparse, so most
requests are for pieces no tile covers at all, and answering those quickly matters
more than answering the full ones quickly -- there are more of them.

So this scatters the tiles uniformly at fractional positions over an area chosen to
give roughly the coverage a real overlapping run has, and reports the spread rather
than a single number.

Run it with::

    python measure_ten_thousand.py                    # 10,000 tiles
    python measure_ten_thousand.py --tiles 2000       # fewer, to try it out
    python measure_ten_thousand.py --keep             # leave it on disk to look at

Roughly 3 GB and a few minutes of writing at ten thousand. Nothing outside the
folder it writes is touched.
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import zarr

sys.path.insert(0, str(Path(__file__).resolve().parent))

from composer import Composer  # noqa: E402
from mosaic import read_the_transfer  # noqa: E402

TILE = (2, 256, 256)
VOXEL_UM = (1.0, 0.5, 0.5)
LEVELS = 2

# How much of the ground is imaged more than once, on average. A real overlapping
# run sits near 2; scattering at random around that number gives pieces meeting
# one tile and pieces meeting a dozen, which is the spread being looked for.
COVERAGE = 2.0

# How many pieces to time. Taken at random across the whole picture rather than
# from one band, so empty ground is sampled in the proportion it really occurs.
SAMPLES = 200


def a_tile(number: int) -> np.ndarray:
    """One tile, made so a person can tell it from its neighbours on screen.

    Each carries its own brightness and a bright border, so where two of them
    overlap the join is visible rather than being lost in noise that looks the
    same either way.
    """
    level = 600 + (number % 23) * 140
    picture = np.full(TILE, level, "uint16")
    picture[:, :4, :] = 4000
    picture[:, -4:, :] = 4000
    picture[:, :, :4] = 4000
    picture[:, :, -4:] = 4000
    return picture


def write_a_scattered_transfer(folder: Path, tiles: int) -> tuple[Path, float]:
    """Write ``tiles`` positions at random fractional places, and say how wide."""
    folder.mkdir(parents=True, exist_ok=True)
    # The area that gives the coverage asked for, and the corner of each tile
    # inside it. Positions are in micrometres and are *not* whole voxels, which
    # is the condition that makes a picture like this impossible to point at.
    side = float(np.sqrt(tiles * TILE[1] * TILE[2] / COVERAGE))
    seed = np.random.default_rng(7)
    corners = seed.uniform(0.0, side, size=(tiles, 2)) * VOXEL_UM[1]

    def write_one(number: int) -> None:
        store = folder / f"Tile{number:05d}.ome.zarr"
        picture = a_tile(number)
        datasets = []
        for level in range(LEVELS):
            shrink = 2 ** level
            shape = (TILE[0], TILE[1] // shrink, TILE[2] // shrink)
            array = zarr.create_array(
                store=str(store / str(level)), shape=shape, chunks=shape,
                dtype="uint16", zarr_format=3, dimension_names=["z", "y", "x"],
                overwrite=True,
            )
            array[:] = picture[:, ::shrink, ::shrink]
            datasets.append({
                "path": str(level),
                "coordinateTransformations": [
                    {"type": "scale",
                     "scale": [VOXEL_UM[0], VOXEL_UM[1] * shrink,
                               VOXEL_UM[2] * shrink]},
                    {"type": "translation",
                     "translation": [0.0, float(corners[number][0]),
                                     float(corners[number][1])]},
                ],
            })
        (store / "zarr.json").write_text(json.dumps({
            "attributes": {"ome": {
                "version": "0.5",
                "multiscales": [{
                    "name": store.name, "type": "nearest",
                    "axes": [{"name": "z", "type": "space", "unit": "micrometer"},
                             {"name": "y", "type": "space", "unit": "micrometer"},
                             {"name": "x", "type": "space", "unit": "micrometer"}],
                    "datasets": datasets,
                }],
            }},
            "zarr_format": 3, "node_type": "group",
        }), encoding="utf-8")

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(write_one, range(tiles)))
    return folder, side


def truth_for(mosaic, composer, plane: int, row: int, column: int) -> np.ndarray:
    """The same piece, laid out straight from the tiles, the long way round."""
    _, height, width = mosaic.shape(0)
    piece = composer.piece
    top, left = row * piece, column * piece
    ground = np.zeros((piece, piece), mosaic.dtype)
    for tile in mosaic.tiles:
        at = mosaic.lands_at(tile, 0)
        held = tile.copies[0]
        if not (at[0] <= plane < at[0] + held.shape[0]):
            continue
        from_y, to_y = max(top, at[1]), min(min(top + piece, height),
                                            at[1] + held.shape[1])
        from_x, to_x = max(left, at[2]), min(min(left + piece, width),
                                             at[2] + held.shape[2])
        if from_y >= to_y or from_x >= to_x:
            continue
        ground[from_y - top:to_y - top, from_x - left:to_x - left] = np.asarray(
            held.array[plane - at[0], from_y - at[1]:to_y - at[1],
                       from_x - at[2]:to_x - at[2]])
    return ground


def main() -> None:
    parsed = argparse.ArgumentParser(description=__doc__)
    parsed.add_argument("--tiles", type=int, default=10_000)
    parsed.add_argument("--where", type=Path, default=Path(r"D:\zmart-ten-thousand"))
    parsed.add_argument("--keep", action="store_true",
                        help="leave the transfer on disk so it can be looked at")
    parsed.add_argument("--checks", type=int, default=12,
                        help="how many pieces to compare against the tiles")
    given = parsed.parse_args()

    folder = given.where / f"scattered{given.tiles:05d}"
    if folder.exists():
        shutil.rmtree(folder)

    print(f"\n  Writing {given.tiles:,} tiles at random fractional places ...")
    began = time.perf_counter()
    _, side = write_a_scattered_transfer(folder, given.tiles)
    writing = time.perf_counter() - began
    weighs = sum(one.stat().st_size for one in folder.rglob("*") if one.is_file())
    print(f"  written in {writing:.0f} s, {weighs / 1e9:.2f} GB on disk\n")

    began = time.perf_counter()
    mosaic = read_the_transfer(folder)
    opening = (time.perf_counter() - began) * 1000

    composer = Composer(mosaic)
    began = time.perf_counter()
    index = composer._tiles_in_each_piece(0)
    indexing = (time.perf_counter() - began) * 1000

    deep, down, across = composer.grid(0)
    _, height, width = mosaic.shape(0)
    print(f"  picture      {height:,} x {width:,} voxels, {deep} planes")
    print(f"  pieces       {down} x {across} = {down * across:,} a plane")
    print(f"  opening      {opening:.0f} ms   ({opening / given.tiles:.2f} ms a tile)")
    print(f"  indexing     {indexing:.0f} ms")

    meeting = [len(index.get((row, column), ()))
               for row in range(down) for column in range(across)]
    covered = [one for one in meeting if one]
    print(f"\n  tiles meeting a piece:  median {statistics.median(covered):.0f}, "
          f"most {max(meeting)}, "
          f"empty {100 * (1 - len(covered) / len(meeting)):.0f}% of pieces")

    # -- what a piece costs, across the whole picture ------------------------
    seed = np.random.default_rng(11)
    places = [(int(seed.integers(0, down)), int(seed.integers(0, across)))
              for _ in range(SAMPLES)]
    full, empty = [], []
    for row, column in places:
        began = time.perf_counter()
        Composer(mosaic)._build_slab(0, 0, row, column)
        spent = (time.perf_counter() - began) * 1000
        (full if index.get((row, column)) else empty).append(spent)

    def spread(name: str, times: list[float]) -> None:
        if not times:
            print(f"  {name:<22} none sampled")
            return
        ordered = sorted(times)
        print(f"  {name:<22} median {statistics.median(ordered):>7.1f} ms   "
              f"9 in 10 under {ordered[int(len(ordered) * 0.9)]:>7.1f} ms   "
              f"worst {ordered[-1]:>7.1f} ms   ({len(times)} pieces)")

    print(f"\n  building a piece, {SAMPLES} taken at random across the picture:")
    spread("where tiles are", full)
    spread("where none are", empty)

    # -- and is it right? ----------------------------------------------------
    print(f"\n  checking {given.checks} pieces against the tiles:")
    wrong = 0
    checked = 0
    for row, column in places:
        if not index.get((row, column)) or checked >= given.checks:
            continue
        built = Composer(mosaic)._build_slab(0, 0, row, column)[0]
        wrong += int((built != truth_for(mosaic, composer, 0, row, column)).sum())
        checked += 1
    print(f"  {'PASS' if wrong == 0 else 'FAIL'} — {wrong} wrong voxels "
          f"in {checked} pieces\n")

    if given.keep:
        print(f"  left on disk at {folder}\n")
    else:
        shutil.rmtree(folder)


if __name__ == "__main__":
    main()

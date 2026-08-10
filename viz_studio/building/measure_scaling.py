"""Does building a picture still work when the transfer holds thousands of tiles?

Building was measured on six tiles and shown correct and affordable there. Six is
not the question. The question is a survey — thousands of positions — and there is
a specific reason to think building answers it where handing the viewer one source
per tile does not: **a piece of the picture is covered by two to four tiles however
many the run holds**, so the work of building one should not grow with the run at
all.

Should, rather than does. Two things in the implementation grow with the tile
count whatever the geometry says, and this measures all three together:

``opening``
    every tile's description is read when the transfer is opened. Measured
    elsewhere in this repo at 86% of the time spent building a view, at sixteen
    hundred tiles, so it is the first thing expected to hurt.

``finding``
    which tiles reach a piece is answered by looking at every tile. That is right
    for six and wrong for ten thousand, and it is the known limit recorded in
    ``composer.py``. This says what it actually costs and at what size it starts
    to matter.

``building``
    laying the tiles that cover a piece into it and encoding the result. This is
    the part that should be flat, and the whole argument rests on it being flat.

Run it with::

    python measure_scaling.py                 # up to 1024 real tiles
    python measure_scaling.py --most 4096     # or further, if you have the disk

Tiles are written under a temporary folder and removed afterwards. They are small
-- a tile is 256 KB -- because what is being measured is how the cost moves with
the *number* of tiles, and a bigger tile would only make the ladder shorter.
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import zarr

sys.path.insert(0, str(Path(__file__).resolve().parent))

from composer import Composer  # noqa: E402
from mosaic import read_the_transfer  # noqa: E402

# One tile, shaped like a light-sheet transfer: a few planes, square across.
TILE = (2, 256, 256)

# How large a voxel is, and how far the stage moves between tiles. The step is
# given in micrometres and is deliberately **not** a whole number of voxels --
# 114.87 um at 0.5 um a voxel is 229.74 -- because that is what a real stage does
# and it is the exact condition that makes a picture impossible to point at.
VOXEL_UM = (1.0, 0.5, 0.5)
STEP_UM = 114.87

# How many copies of its picture each tile keeps, and how they are chunked. The
# chunk halves with the picture, which is what a mesoSPIM transfer does.
LEVELS = 2

# How many pieces to time at each rung. Enough to take a median rather than a
# reading.
SAMPLES = 9


def write_a_transfer(folder: Path, tiles: int) -> Path:
    """Write a synthetic transfer of ``tiles`` positions on a fractional grid."""
    folder.mkdir(parents=True, exist_ok=True)
    across = max(1, int(np.ceil(np.sqrt(tiles))))
    seed = np.random.default_rng(0)
    picture = seed.integers(200, 4000, TILE, dtype="uint16")

    for number in range(tiles):
        row, column = divmod(number, across)
        store = folder / f"Tile{number:05d}.ome.zarr"
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
                     "translation": [0.0, row * STEP_UM, column * STEP_UM]},
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
    return folder


def measure(folder: Path, tiles: int) -> dict:
    """Open a transfer of this size and time opening it, finding, and building."""
    began = time.perf_counter()
    mosaic = read_the_transfer(folder)
    opening = (time.perf_counter() - began) * 1000

    composer = Composer(mosaic)
    deep, down, across = composer.grid(0)
    _, height, width = mosaic.shape(0)

    # Pieces taken from across the middle of the picture, where tiles genuinely
    # overlap, rather than at a corner where one tile answers on its own.
    places = [(down // 2, column) for column in
              range(0, max(1, across), max(1, across // SAMPLES))][:SAMPLES]

    finding, building, rebuilding, covering = [], [], [], []
    for row, column in places:
        low = (0, row * composer.piece, column * composer.piece)
        high = (min(deep, 1), low[1] + composer.piece, low[2] + composer.piece)

        # Timed the way the composer actually does it -- a lookup in the index,
        # not a sweep of every tile. The index is built on first use, so it is
        # warmed here rather than being charged to the first piece measured.
        fresh = Composer(mosaic)
        fresh._tiles_in_each_piece(0)
        began = time.perf_counter()
        reached = fresh._tiles_in_each_piece(0).get((row, column), ())
        finding.append((time.perf_counter() - began) * 1000)
        covering.append(len(reached))

        began = time.perf_counter()
        fresh.bytes_for(0, 0, row, column)
        building.append((time.perf_counter() - began) * 1000)

        # The same piece again, with a composer that has no slab of it kept but
        # over the same tiles, which are now open. Opening a tile's picture waits
        # until something reads it, so the first piece to touch a tile pays for
        # it and every piece after that does not -- and the two are worth telling
        # apart, because a viewer pays the first once and the second for ever.
        again = Composer(mosaic)
        # Its index warmed too, for the same reason the first one's was: the
        # server keeps one composer per picture and builds the index once, so
        # charging it to a piece would be measuring the harness.
        again._tiles_in_each_piece(0)
        began = time.perf_counter()
        again.bytes_for(0, 0, row, column)
        rebuilding.append((time.perf_counter() - began) * 1000)

    return {
        "tiles": tiles,
        "picture": f"{height} x {width}",
        "opening_ms": opening,
        "finding_ms": statistics.median(finding),
        "building_ms": statistics.median(building),
        "rebuilding_ms": statistics.median(rebuilding),
        "covering": statistics.median(covering),
    }


def main() -> None:
    parsed = argparse.ArgumentParser(description=__doc__)
    parsed.add_argument("--most", type=int, default=1024,
                        help="the largest number of tiles to write")
    parsed.add_argument("--where", type=Path,
                        default=Path(r"D:\zmart-scaling-test"),
                        help="where to write the throwaway transfers")
    given = parsed.parse_args()

    rungs = [1, 4, 16, 64, 256, 1024, 4096, 16384]
    rungs = [one for one in rungs if one <= given.most]

    print(f"\n  Building a picture from a transfer, as the transfer grows.")
    print(f"  Tiles {TILE[1]}x{TILE[2]}, stepping {STEP_UM} um "
          f"({STEP_UM / VOXEL_UM[1]:.2f} voxels -- not a whole number),"
          f"\n  pieces of 512, one plane, nothing cached.\n")
    print(f"  {'tiles':>7} {'picture':>15} {'opening':>10} {'finding':>10} "
          f"{'1st build':>11} {'after':>9} {'tiles a piece':>14}")
    print("  " + "-" * 82)

    rows = []
    for tiles in rungs:
        folder = given.where / f"tiles{tiles:05d}"
        if folder.exists():
            shutil.rmtree(folder)
        write_a_transfer(folder, tiles)
        row = measure(folder, tiles)
        rows.append(row)
        print(f"  {row['tiles']:>7} {row['picture']:>15} "
              f"{row['opening_ms']:>7.0f} ms {row['finding_ms']:>7.2f} ms "
              f"{row['building_ms']:>8.1f} ms {row['rebuilding_ms']:>6.1f} ms "
              f"{row['covering']:>14.0f}")
        shutil.rmtree(folder)

    if len(rows) >= 2:
        first, last = rows[0], rows[-1]
        grew = last["tiles"] / first["tiles"]
        print(f"\n  From {first['tiles']} tiles to {last['tiles']} — {grew:.0f}x more:")
        print(f"    opening   {last['opening_ms'] / max(0.001, first['opening_ms']):>8.1f}x")
        print(f"    finding   {last['finding_ms'] / max(0.001, first['finding_ms']):>8.1f}x")
        print(f"    1st build {last['building_ms'] / max(0.001, first['building_ms']):>8.1f}x")
        print(f"    after     {last['rebuilding_ms'] / max(0.001, first['rebuilding_ms']):>8.1f}x")
        print("\n  Building is the number that decides this. If it held while the")
        print("  transfer grew a thousandfold, a piece really does cost what its")
        print("  own ground costs and nothing more.\n")


if __name__ == "__main__":
    main()

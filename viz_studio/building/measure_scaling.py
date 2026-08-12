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
from concurrent.futures import ThreadPoolExecutor
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

# How many requests arrive together when a browser draws a screenful. Twelve is
# what check.py fires in its parallel test, and it is the size of gesture the
# viewer actually produces -- pieces are never asked for one at a time.
ASKED_AT_ONCE = 12


def write_a_transfer(folder: Path, tiles: int, tile: tuple[int, int, int] = TILE,
                     step_um: float = STEP_UM) -> Path:
    """Write a synthetic transfer of ``tiles`` positions on a fractional grid."""
    folder.mkdir(parents=True, exist_ok=True)
    across = max(1, int(np.ceil(np.sqrt(tiles))))
    seed = np.random.default_rng(0)
    # Random pixels, so nothing compresses away and reads unrealistically fast.
    # Bright ones, spanning the upper half of what sixteen bits can hold: a
    # viewer that opens this without being told a display window shows it at
    # full-range brightness, and the check asking "was anything actually drawn"
    # can see the answer. Dim specimen-range noise, which this used to be,
    # reached the screen at a few per cent brightness and read as an empty
    # panel -- the exact trap measure_the_frame_rate_of_a_linked_view.py
    # documents at its MID and SWING constants.
    picture = seed.integers(24000, 56000, tile, dtype="uint16")

    for number in range(tiles):
        row, column = divmod(number, across)
        store = folder / f"Tile{number:05d}.ome.zarr"
        datasets = []
        for level in range(LEVELS):
            shrink = 2 ** level
            shape = (tile[0], tile[1] // shrink, tile[2] // shrink)
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
                     "translation": [0.0, row * step_um, column * step_um]},
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


def _asked_together(composer: Composer, level: int,
                    pieces: list[tuple[int, int]]) -> float:
    """Ask for these pieces at once, the way a browser does, and time the lot."""
    with ThreadPoolExecutor(max_workers=ASKED_AT_ONCE) as pool:
        began = time.perf_counter()
        list(pool.map(lambda rc: composer.bytes_for(level, 0, rc[0], rc[1]),
                      pieces))
        return (time.perf_counter() - began) * 1000


def gestures(folder: Path) -> dict:
    """Time the three movements an operator makes, rather than single pieces.

    Each cold gesture starts from a freshly read transfer, because what is being
    timed is the first one after opening the picture -- the one that pays for
    opening whichever tiles it touches. A tile's pixels open on first read and
    stay open on the mosaic, so reusing a mosaic would silently measure the warm
    case twice.
    """
    coarsest = LEVELS - 1

    # A screenful: the middle dozen pieces of full resolution, asked at once.
    mosaic = read_the_transfer(folder)
    composer = Composer(mosaic)
    _, down, across = composer.grid(0)
    middle = ((down - 1) / 2, (across - 1) / 2)
    screenful = sorted(
        ((row, column) for row in range(down) for column in range(across)),
        key=lambda rc: (rc[0] - middle[0]) ** 2 + (rc[1] - middle[1]) ** 2,
    )[:ASKED_AT_ONCE]
    composer._tiles_in_each_piece(0)
    cold = _asked_together(composer, 0, screenful)

    # The same screenful again, on the same composer: what a revisit costs.
    again = _asked_together(composer, 0, screenful)

    # Zooming out: every piece of the coarsest copy, from a transfer nothing has
    # opened yet. This is the gesture that meets the most tiles per piece and
    # collects the whole deferred opening bill at once.
    mosaic = read_the_transfer(folder)
    composer = Composer(mosaic)
    _, down, across = composer.grid(coarsest)
    whole = [(row, column) for row in range(down) for column in range(across)]
    composer._tiles_in_each_piece(coarsest)
    zoomout = _asked_together(composer, coarsest, whole)

    return {
        "screenful_ms": cold, "screenful_pieces": len(screenful),
        "again_ms": again,
        "zoomout_ms": zoomout, "zoomout_pieces": len(whole),
    }


def main() -> None:
    parsed = argparse.ArgumentParser(description=__doc__)
    parsed.add_argument("--most", type=int, default=1024,
                        help="the largest number of tiles to write")
    parsed.add_argument("--rungs",
                        help="tile counts to measure instead of the default "
                        "ladder, e.g. 1,5,10,50,100")
    parsed.add_argument("--where", type=Path,
                        default=Path(r"D:\zmart-scaling-test"),
                        help="where to write the throwaway transfers")
    given = parsed.parse_args()

    if given.rungs:
        rungs = [int(one) for one in given.rungs.split(",")]
    else:
        rungs = [1, 4, 16, 64, 256, 1024, 4096, 16384]
        rungs = [one for one in rungs if one <= given.most]

    print("\n  Building a picture from a transfer, as the transfer grows.")
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
        row.update(gestures(folder))
        rows.append(row)
        print(f"  {row['tiles']:>7} {row['picture']:>15} "
              f"{row['opening_ms']:>7.0f} ms {row['finding_ms']:>7.2f} ms "
              f"{row['building_ms']:>8.1f} ms {row['rebuilding_ms']:>6.1f} ms "
              f"{row['covering']:>14.0f}")
        shutil.rmtree(folder)

    print("\n  The same transfers, timed as gestures rather than pieces: a")
    print(f"  screenful is the middle {ASKED_AT_ONCE} full-resolution pieces "
          "asked at once, and")
    print("  zooming out asks for the whole coarsest copy of a picture nothing"
          "\n  has opened yet.\n")
    print(f"  {'tiles':>7} {'screenful':>12} {'revisited':>11} "
          f"{'zoom-out':>11} {'(pieces)':>9}")
    print("  " + "-" * 56)
    for row in rows:
        print(f"  {row['tiles']:>7} "
              f"{row['screenful_ms']:>9.1f} ms {row['again_ms']:>8.1f} ms "
              f"{row['zoomout_ms']:>8.1f} ms {row['zoomout_pieces']:>9}")

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

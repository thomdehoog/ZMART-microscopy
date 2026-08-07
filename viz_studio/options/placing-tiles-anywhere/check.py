"""Check the composed pieces against a canvas built plainly in numpy, voxel by voxel.

This is the half of the demonstration that does not depend on anybody looking at
a picture. Every piece the server would serve is composed, the bytes are written
out as an ordinary zarr store, that store is opened again with plain zarr — so
the encoding is checked as well as the arithmetic — and every voxel is compared
with what we meant to make.
"""

from __future__ import annotations

import shutil
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import zarr

sys.path.insert(0, str(Path(__file__).resolve().parent))

import geometry as g
from compose import Composer

HERE = Path(__file__).resolve().parent
POSITIONS = HERE / "run" / "anywhere.ome.zarr" / "positions"
READ_BACK = HERE / "read-back.zarr"


def main() -> None:
    composer = Composer(POSITIONS, g.PLACES)
    pieces = g.CANVAS // g.CHUNK

    if READ_BACK.exists():
        shutil.rmtree(READ_BACK)
    (READ_BACK / "0").mkdir(parents=True)
    (READ_BACK / "0" / "zarr.json").write_bytes(composer.array_json())

    straddling = 0
    times_ms: list[float] = []
    for cy in range(pieces):
        for cx in range(pieces):
            started = time.perf_counter()
            raw = composer.bytes_for(cy, cx)
            times_ms.append((time.perf_counter() - started) * 1000)
            if len(composer.touching(cy, cx)) > 1:
                straddling += 1
            where = READ_BACK / "0" / "c" / "0" / "0" / "0" / str(cy)
            where.mkdir(parents=True, exist_ok=True)
            (where / str(cx)).write_bytes(raw)

    # Opened with plain zarr, which knows nothing of this demonstration: if the
    # bytes were encoded even slightly wrongly this is where it shows.
    back = zarr.open_array(str(READ_BACK / "0"), mode="r")[0, 0, 0]
    meant = g.truth()

    same = back == meant
    print(f"tile {g.TILE}, piece {g.CHUNK}, step {g.STEP}, "
          f"overlap {g.OVERLAP} voxels, canvas {g.CANVAS} x {g.CANVAS}")
    print(f"positions                          : {len(g.PLACES)}")
    print(f"pieces of the picture              : {pieces * pieces}")
    print(f"pieces straddling more than one tile: {straddling} "
          f"({100 * straddling / (pieces * pieces):.0f}%)")
    print(f"pieces resting on exactly one tile  : "
          f"{sum(1 for cy in range(pieces) for cx in range(pieces) if len(composer.touching(cy, cx)) == 1)}")
    print(f"pieces touching no tile at all      : "
          f"{sum(1 for cy in range(pieces) for cx in range(pieces) if not composer.touching(cy, cx))}")
    print()
    print(f"voxels checked                     : {same.size}")
    print(f"voxels right                       : {int(same.sum())}")
    print(f"voxels wrong                       : {int((~same).sum())}")
    print()
    print(f"composing one piece, median        : {statistics.median(times_ms):.3f} ms")
    print(f"composing one piece, worst         : {max(times_ms):.3f} ms")
    print(f"the whole canvas, {pieces * pieces} pieces        : {sum(times_ms):.1f} ms")

    # What the same piece costs the way a view answers today: one position's own
    # file, read off disk and sent untouched. That is the price of insisting a
    # position lands on the grid of pieces, and it is what composing is being
    # compared with.
    one_file = next(one for one in
                    sorted((POSITIONS / "anywhere_pos00000.ome.zarr" / "0").rglob("*"))
                    if one.is_file() and one.name != "zarr.json")
    handing_over = []
    for _ in range(200):
        started = time.perf_counter()
        one_file.read_bytes()
        handing_over.append((time.perf_counter() - started) * 1000)
    print(f"handing a file over, median        : "
          f"{statistics.median(handing_over):.4f} ms")

    shutil.rmtree(READ_BACK)
    if int((~same).sum()):
        raise SystemExit("the composed picture is not the picture we meant to make")


if __name__ == "__main__":
    main()

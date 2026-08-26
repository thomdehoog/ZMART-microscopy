"""Ten thousand tiles in one store: does placing them on the way out still hold?

`measure_tiles_in_one_store.py` beside this file establishes the arrangement and
measures it up to a few hundred tiles. This carries it to the size the project is
actually aiming for, because a thing that holds at five hundred and fails at ten
thousand would be worse than useless -- it would look like an answer.

Two cases, because they are different problems.

Raster
    Tiles on a neat grid, as a mosaic scan produces. Working out which tiles touch
    a piece is closed-form arithmetic, so the only question is whether the store
    itself misbehaves at this size.

Scattered
    Tiles wherever the microscope decided to look, as smart microscopy produces.
    There is no arithmetic to do -- the tiles that touch a piece have to be looked
    up. That lookup is new work that the earlier measurements never exercised, and
    it is the thing most likely to spoil this at scale.

Run it with::

    python measure_ten_thousand_tiles.py            # 100x100 = 10,000 tiles
    python measure_ten_thousand_tiles.py 50         # smaller, if disk is short

It writes about 1.3 GB under a temporary folder and removes it afterwards, and it
needs no browser and no graphics card. Allow a minute or so for the writing.
"""
import shutil
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import zarr

TILE, OVERLAP, CHUNK, DEPTH = 256, 32, 256, 1
STEP = TILE - OVERLAP


def build_raster(work, grid):
    side = grid * TILE
    montage = zarr.open_array(str(work / "m.zarr"), mode="w",
                              shape=(DEPTH, side, side),
                              chunks=(1, CHUNK, CHUNK), dtype="uint16")
    rng = np.random.default_rng(0)
    for iy in range(grid):                      # a row at a time: far fewer writes
        montage[:, iy*TILE:(iy+1)*TILE, :] = rng.integers(
            1000, 4000, size=(DEPTH, TILE, side), dtype=np.uint16)
    return montage


def place_raster(montage, grid, z, y0, x0, shape):
    y1, x1 = min(y0+CHUNK, shape[0]), min(x0+CHUNK, shape[1])
    piece = np.zeros((y1-y0, x1-x0), dtype=np.uint16)
    n = 0
    for iy in range(max(0,(y0-TILE)//STEP+1), min(grid-1, y1//STEP)+1):
        ty = iy*STEP
        for ix in range(max(0,(x0-TILE)//STEP+1), min(grid-1, x1//STEP)+1):
            tx = ix*STEP
            oy0,oy1 = max(y0,ty), min(y1,ty+TILE)
            ox0,ox1 = max(x0,tx), min(x1,tx+TILE)
            if oy0 >= oy1 or ox0 >= ox1:
                continue
            n += 1
            piece[oy0-y0:oy1-y0, ox0-x0:ox1-x0] = montage[
                z, iy*TILE+(oy0-ty):iy*TILE+(oy0-ty)+(oy1-oy0),
                   ix*TILE+(ox0-tx):ix*TILE+(ox0-tx)+(ox1-ox0)]
    return piece, n


class Scattered:
    """Tiles at arbitrary places, with a coarse bucket index to find them.

    The index is the whole point: without one, finding the handful of tiles that
    touch a piece means looking at all ten thousand every time.
    """
    def __init__(self, positions, bucket=2048):
        self.positions, self.bucket = positions, bucket
        self.buckets = defaultdict(list)
        for slot, (ty, tx) in enumerate(positions):
            for by in range((ty)//bucket, (ty+TILE)//bucket + 1):
                for bx in range((tx)//bucket, (tx+TILE)//bucket + 1):
                    self.buckets[(by, bx)].append(slot)

    def touching(self, y0, y1, x0, x1):
        found = set()
        for by in range(y0//self.bucket, (y1-1)//self.bucket + 1):
            for bx in range(x0//self.bucket, (x1-1)//self.bucket + 1):
                for slot in self.buckets.get((by, bx), ()):
                    ty, tx = self.positions[slot]
                    if ty < y1 and ty+TILE > y0 and tx < x1 and tx+TILE > x0:
                        found.add(slot)
        return sorted(found)


def place_scattered(montage, index, grid, z, y0, x0, shape):
    y1, x1 = min(y0+CHUNK, shape[0]), min(x0+CHUNK, shape[1])
    piece = np.zeros((y1-y0, x1-x0), dtype=np.uint16)
    slots = index.touching(y0, y1, x0, x1)
    for slot in slots:
        ty, tx = index.positions[slot]
        oy0,oy1 = max(y0,ty), min(y1,ty+TILE)
        ox0,ox1 = max(x0,tx), min(x1,tx+TILE)
        sy, sx = (slot//grid)*TILE + (oy0-ty), (slot%grid)*TILE + (ox0-tx)
        piece[oy0-y0:oy1-y0, ox0-x0:ox1-x0] = montage[
            z, sy:sy+(oy1-oy0), sx:sx+(ox1-ox0)]
    return piece, len(slots)


def main():
    grid = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    work = Path(tempfile.mkdtemp(prefix="tenk-"))
    try:
        print(f"\n{grid*grid} tiles, {TILE}x{TILE}, store is "
              f"{grid*TILE}x{grid*TILE} voxels")
        t0 = time.perf_counter()
        montage = build_raster(work, grid)
        print(f"writing the store: {time.perf_counter()-t0:.1f} s")

        side = (grid-1)*STEP + TILE
        spots = [(0, y, x) for y in range(0, side-1, CHUNK*7)
                           for x in range(0, side-1, CHUNK*7)][:30]

        times, most = [], 0
        for z,y,x in spots:
            t0 = time.perf_counter()
            _, n = place_raster(montage, grid, z, y, x, (side, side))
            times.append((time.perf_counter() - t0) * 1000)
            most = max(most, n)
        print(f"  raster     median {statistics.median(times):6.2f} ms   "
              f"touching at most {most} tiles")

        # scattered: same tiles, jittered off the raster by up to half a tile
        rng = np.random.default_rng(1)
        positions = []
        for iy in range(grid):
            for ix in range(grid):
                positions.append((iy*STEP + int(rng.integers(0, TILE//2)),
                                  ix*STEP + int(rng.integers(0, TILE//2))))
        t0 = time.perf_counter()
        index = Scattered(positions)
        print(f"  building the index: {(time.perf_counter()-t0)*1000:.0f} ms "
              f"for {len(positions)} tiles")

        times, most = [], 0
        for z,y,x in spots:
            t0 = time.perf_counter()
            _, n = place_scattered(montage, index, grid, z, y, x, (side, side))
            times.append((time.perf_counter() - t0) * 1000)
            most = max(most, n)
        print(f"  scattered  median {statistics.median(times):6.2f} ms   "
              f"touching at most {most} tiles")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()

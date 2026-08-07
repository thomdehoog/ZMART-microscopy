"""What does compression cost when tiles are put in place as they are read?

`measure_tiles_in_one_store.py` beside this file times putting tiles in their true
places on the way out of the store, and every one of its numbers is from an
**uncompressed** store. Real acquisitions are compressed -- the 75 GB store this
project was last measured on uses zstd -- so those numbers could not be trusted
until this was run.

Run it with::

    python measure_compression_cost.py 8

Measured on this sandbox: zstd costs about **1.4x** an uncompressed store when a
tile's slot lines up with the pieces the file is stored in, and about **2.0x** when
it does not. Both are small enough that compression is not the obstacle it looked
like, and lining slots up is worth doing anyway, because `DATA_LAYOUT.md` already
asks the writer for it so that two tiles written at once cannot share a piece.

The original question this was written to answer:

Every measurement so far read uncompressed data. Real stores are compressed --
the 75 GB acquisition uses zstd. Assembling one piece means reading up to nine
rectangles, and if a rectangle straddles compressed chunks each one has to be
decompressed whole to get at the part wanted.

Two arrangements are compared, because the difference between them is the whole
question:

aligned    a tile occupies a whole number of chunks and starts on a chunk
           boundary, so reading a rectangle out of a slot touches only that
           tile's own chunks.
straddling a tile's slot is offset so that its rectangles cross chunk edges, which
           is what happens if the slot size and the chunk size are not chosen
           together.
"""
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import zarr
from zarr.codecs import ZstdCodec

TILE, OVERLAP, CHUNK, DEPTH = 256, 32, 256, 4
STEP = TILE - OVERLAP


def build(work, grid, chunk, compressor, name, realistic=True):
    side = grid * TILE
    arr = zarr.create_array(str(work / name), shape=(DEPTH, side, side),
                            chunks=(1, chunk, chunk), dtype="uint16",
                            compressors=compressor, overwrite=True)
    rng = np.random.default_rng(0)
    for iy in range(grid):
        if realistic:
            # Smooth-ish data, as a specimen is: pure noise is incompressible and
            # would make zstd look far cheaper than it is on real pictures.
            row = rng.integers(0, 400, size=(DEPTH, TILE, side), dtype=np.uint16)
            row = np.cumsum(row // 40, axis=2).astype(np.uint16) % 4000 + 200
        else:
            row = rng.integers(1000, 4000, size=(DEPTH, TILE, side), dtype=np.uint16)
        arr[:, iy*TILE:(iy+1)*TILE, :] = row
    return arr


def place(montage, grid, z, y0, x0, shape, slot_offset=0):
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
            sy = iy*TILE + (oy0-ty) + slot_offset
            sx = ix*TILE + (ox0-tx) + slot_offset
            piece[oy0-y0:oy1-y0, ox0-x0:ox1-x0] = montage[
                z, sy:sy+(oy1-oy0), sx:sx+(ox1-ox0)]
    return piece, n


def run(work, grid, label, chunk, compressor, slot_offset=0):
    arr = build(work, grid, chunk, compressor, f"m_{label}.zarr")
    side = (grid-1)*STEP + TILE
    spots = [(0, y, x) for y in range(0, side-1, CHUNK)
                       for x in range(0, side-1, CHUNK)][:20]
    times, most = [], 0
    for z,y,x in spots:
        t0 = time.perf_counter()
        _, n = place(arr, grid, z, y, x, (side, side), slot_offset)
        times.append((time.perf_counter() - t0) * 1000)
        most = max(most, n)
    size = sum(f.stat().st_size for f in (work / f"m_{label}.zarr").rglob("*")
               if f.is_file()) / 1e6
    print(f"  {label:<34} median {statistics.median(times):7.2f} ms   "
          f"max {max(times):7.2f} ms   store {size:6.1f} MB   <={most} tiles")
    return statistics.median(times)


def main():
    grid = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    work = Path(tempfile.mkdtemp(prefix="compressed-"))
    try:
        print(f"\n{grid*grid} tiles, chunk {CHUNK}, tile {TILE}, step {STEP}\n")
        plain = run(work, grid, "uncompressed, aligned", CHUNK, None)
        zstd = run(work, grid, "zstd, aligned", CHUNK, ZstdCodec(level=3))
        run(work, grid, "zstd, chunk 128 (tile spans 4)", 128, ZstdCodec(level=3))
        odd = run(work, grid, "zstd, chunk 192 (tile straddles)", 192, ZstdCodec(level=3))
        print(f"\n  zstd costs {zstd/plain:.1f}x uncompressed when slots are aligned")
        print(f"  and {odd/plain:.1f}x when a tile straddles chunk edges")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()

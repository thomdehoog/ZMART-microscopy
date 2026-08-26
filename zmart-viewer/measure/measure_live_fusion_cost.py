"""What does it cost to stitch the tiles afresh every time a picture is asked for?

There is an appealing idea that comes up whenever the cost of many stores is
discussed, and it deserves a measurement rather than an opinion, because the
argument for it is genuinely good.

The idea: leave the tiles exactly as they are on disk, overlap and all, and put a
program in front of them that *pretends* to be a single stitched image. When the
viewer asks for a piece of picture, the program stitches that piece on the spot
and hands it back. The viewer then holds one source instead of thousands — which
is the whole of the frame-rate problem — while nothing is copied and the overlap
survives for a stitcher to use later.

`multiview-stitcher` has this built, as `serve_virtual_ome_zarrs`, and it works.
The question is only whether it is quick enough to look at a specimen through.

**The measured answer is no, and by a wide margin.** The numbers are in
`docs/how_it_works/TILES_IN_ONE_STORE.md`; on this repository's sandbox one piece of picture took
between 110 and 645 times as long to stitch as to read from disk, and the cost of
a zoomed-out piece grew with the number of tiles, because a piece covering the
whole specimen has every tile overlapping it. Building the plan alone cost about
a tenth of a second per tile before any picture was produced at all.

That is not a criticism of the library. Stitching properly means resampling every
tile through its own transformation and building smooth blending weights across
the seams, which is exactly what you want when tiles are rotated or shifted by
fractions of a voxel, and it is why `multiview-stitcher` uses this to inspect a
few dozen tiles rather than to browse thousands.

**Doing several pieces at once helps, and does not rescue it.** That is the obvious
hope and it is measured here too, because it is worth answering with a number. On
four cores, stitching twelve pieces in a thread pool rather than one after another
raised the rate from 6.0 pieces a second to 13.2 -- a gain of 2.2 times -- while the
time for any *single* piece went the wrong way, from 184 ms to 316 ms. That is what
parallel work does: it lets more pieces arrive together, each having waited longer.
A viewer trying to draw is waiting on one piece.

At that rate a screenful, which is roughly thirty-five pieces, takes about two and a
half seconds, and again on every pan.

This script is kept so the finding can be re-checked rather than believed. If the
library gets faster, or if your tiles are much larger than the ones here and the
fixed costs amortise better, this is what will say so.

The alternative that *was* fast enough is `measure_tiles_in_one_store.py` beside
this file: keep every tile whole in one image and move it into place on the way
out, which needs no resampling and measured at about four times a plain read,
flat as the tile count grows.

Run it with::

    python measure_live_fusion_cost.py          # 16 tiles
    python measure_live_fusion_cost.py 6        # 6x6 = 36 tiles

`multiview-stitcher` is not a dependency of ZMART and this script simply says so
and stops if it is absent::

    python -m pip install multiview-stitcher
"""

from __future__ import annotations

import contextlib
import io
import itertools
import json
import os
import shutil
import statistics
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

try:
    import zarr
    from multiview_stitcher import fusion, msi_utils, ngff_utils
    from multiview_stitcher import spatial_image_utils as si_utils
except ImportError as missing:  # pragma: no cover - depends on the machine
    print(f"This measurement needs multiview-stitcher, which is not installed "
          f"({missing}).\n\n    python -m pip install multiview-stitcher\n")
    raise SystemExit(0) from missing

TILE = 256
OVERLAP = 32
DEPTH = 16
VOXEL = {"z": 2.0, "y": 0.35, "x": 0.35}


def make_tile(iy: int, ix: int):
    """One tile, carrying where it sits on the stage."""
    step = TILE - OVERLAP
    data = np.random.default_rng(iy * 100 + ix).integers(
        1000, 4000, size=(DEPTH, TILE, TILE), dtype=np.uint16)
    sim = si_utils.get_sim_from_array(
        data, dims=["z", "y", "x"], scale=VOXEL,
        translation={"z": 0.0,
                     "y": iy * step * VOXEL["y"],
                     "x": ix * step * VOXEL["x"]},
        transform_key="stage",
    )
    return msi_utils.get_msim_from_sim(sim, scale_factors=[2, 4])


def _report(name: str, times: list[float]) -> float:
    ordered = sorted(times)
    middle = statistics.median(ordered)
    print(f"  {name:<30} n={len(ordered):<3} median={middle:8.1f} ms  "
          f"p90={ordered[int(len(ordered) * 0.9)]:8.1f} ms  "
          f"max={max(ordered):8.1f} ms")
    return middle


def main() -> None:
    grid = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    work = Path(tempfile.mkdtemp(prefix="live-fusion-"))
    try:
        print(f"\n{grid * grid} overlapping tiles of {TILE}x{TILE}x{DEPTH}, "
              f"{OVERLAP} voxels of overlap")

        tiles = [make_tile(iy, ix) for iy in range(grid) for ix in range(grid)]

        started = time.perf_counter()
        stitched = fusion.fuse(images=tiles, transform_key="stage")
        planning = time.perf_counter() - started
        print(f"planning the stitch: {planning:.2f} s "
              f"({planning / (grid * grid) * 1000:.0f} ms a tile, and no picture yet)")

        pretend = ngff_utils.VirtualOMEZarr(stitched, name="stitched")

        # The same stitch, written out once, as the control. This is the
        # arrangement the viewer is already known to be quick on.
        on_disk = work / "written_out.ome.zarr"
        started = time.perf_counter()
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            fusion.fuse(images=tiles, transform_key="stage",
                        output_zarr_url=str(on_disk),
                        zarr_options={"ome_zarr": True})
        print(f"writing the same stitch out once: {time.perf_counter() - started:.2f} s")

        store = zarr.open_group(str(on_disk), mode="r")

        for level in pretend.paths:
            described = pretend.array_zarray(level)
            if isinstance(described, (str, bytes)):
                described = json.loads(described)
            shape, pieces = described["shape"], described["chunks"]
            across = [max(1, -(-s // c)) for s, c in zip(shape, pieces, strict=True)]

            wanted = []
            for zi in range(min(across[-3], 4)):
                for yi in range(min(across[-2], 3)):
                    for xi in range(min(across[-1], 3)):
                        wanted.append("/".join(
                            ["0"] * (len(across) - 3) + [str(zi), str(yi), str(xi)]))

            print(f"\nlevel {level}  shape={shape}  pieces={pieces}  "
                  f"({len(wanted)} timed)")

            live = []
            for key in wanted:
                started = time.perf_counter()
                pretend.read_chunk(level, key)
                live.append((time.perf_counter() - started) * 1000)
            stitched_ms = _report("stitched on the spot", live)

            try:
                array = store[level]
            except KeyError:
                continue
            plain = []
            for key in wanted:
                where = tuple(slice(int(i) * c, int(i) * c + c)
                              for i, c in zip(key.split("/"), pieces, strict=True))
                started = time.perf_counter()
                np.asarray(array[where])
                plain.append((time.perf_counter() - started) * 1000)
            read_ms = _report("read from disk (control)", plain)

            if read_ms:
                print(f"  -> stitching on the spot costs "
                      f"{stitched_ms / read_ms:.0f}x a plain read")

        _how_much_does_doing_several_at_once_help(pretend)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _how_much_does_doing_several_at_once_help(pretend) -> None:
    """Does stitching several pieces at once make this usable?

    The hope is that a piece taking hundreds of milliseconds does not matter,
    because a server can work on several at a time. What this shows is that the
    hope is half right: more pieces arrive per second, and each individual piece
    takes *longer*, because they are now competing for the same processors. A
    viewer waiting to draw is waiting on one piece, so the second number is the one
    it feels.
    """
    workers = min(8, os.cpu_count() or 1)
    level = pretend.paths[0]
    described = pretend.array_zarray(level)
    if isinstance(described, (str, bytes)):
        described = json.loads(described)
    across = [max(1, -(-size // piece))
              for size, piece in zip(described["shape"], described["chunks"],
                                     strict=True)]
    wanted = ["/".join(str(i) for i in where)
              for where in itertools.islice(
                  itertools.product(*[range(n) for n in across]), 12)]
    if len(wanted) < 2:
        return

    # One piece first, so neither arrangement pays a first-call cost the other
    # avoids.
    pretend.read_chunk(level, wanted[0])

    def one(key):
        started = time.perf_counter()
        pretend.read_chunk(level, key)
        return (time.perf_counter() - started) * 1000

    started = time.perf_counter()
    alone = [one(key) for key in wanted]
    serially = time.perf_counter() - started

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        together = list(pool.map(one, wanted))
    at_once = time.perf_counter() - started

    print(f"\nstitching {len(wanted)} pieces, on {os.cpu_count()} processors")
    print(f"  one after another   {serially:5.2f} s   "
          f"{statistics.median(alone):7.1f} ms a piece   "
          f"{len(wanted)/serially:5.2f} a second")
    print(f"  {workers} at a time         {at_once:5.2f} s   "
          f"{statistics.median(together):7.1f} ms a piece   "
          f"{len(wanted)/at_once:5.2f} a second")
    print(f"  -> {serially/at_once:.1f}x more pieces a second, and one piece went "
          f"from {statistics.median(alone):.0f} to "
          f"{statistics.median(together):.0f} ms")


if __name__ == "__main__":
    main()

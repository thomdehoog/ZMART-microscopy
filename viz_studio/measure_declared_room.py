"""What declaring more room than a run uses actually costs when the folder is opened.

A run declares its images before it has imaged anything, and it is told to be generous:
size the canvas to the ground the experiment means to cover, or to the stage's whole
travel range where the experiment does not say. The reason that advice is safe is that
a place nothing was written to takes no space on disk, so a canvas can be declared far
larger than the specimen and cost nothing to store.

That is true of the disk, and this script confirms it. But the disk is not the only
thing a generous canvas touches, and the other one is easy to miss.

**Why depth is the axis to watch.** The smaller copies of an image shrink it in y and x
only — depth is carried at full length on every level, which is right, because a stack
of a few hundred planes has nothing to spare. So the coarsest copy of a canvas declared
to the stage's travel in depth is a very tall, very thin thing: hundreds or thousands of
planes, most of which were never imaged.

**And the coarsest copy is what decides how bright the picture looks.** When the viewer
meets a store for the first time it reads that copy and takes percentiles from it, to
choose the window a plane is shown with, the window a volume is shown with, and the
histogram under the contrast slider. Reading the whole of it would be ruinous on a large
acquisition, so a bounded sample is taken instead: a few planes, spread evenly through
the depth, each cropped to a square about the middle.

Spreading the samples evenly through the depth is exactly right for an ordinary
acquisition, where every plane holds specimen. It is wrong for a canvas, where most of
the declared depth was never imaged — the samples land in empty space, the percentiles
are taken over voxels that are all zero, and the window that comes out describes nothing.

This script measures all three costs side by side, so the trade can be seen rather than
argued: the bytes on disk, the time the read takes, and the window that comes out of it.

Run it with::

    python measure_declared_room.py

It writes throwaway images under a temporary folder and deletes them afterwards, so
nothing here touches your data. It does write real pixels, because the cost being
measured is the cost of reading them, so allow a few gigabytes while it runs.

It prints three tables. The first two vary which axes are declared generously, with the
specimen first in the middle of the canvas — which is where a run puts it — and then in
the corner, because the sample is cropped about the middle and the corner is the case
that shows what that crop is doing. The third varies the declared depth alone, to find
where it stops being safe rather than to assert a number for it.

What to look for. The disk column should be identical down the whole table — that is
the claim that declaring generously is free, and it holds. The window column is the one
that does not: where it reads ``(0, 1)`` the measurement found nothing but empty space,
and the operator gets a volume view and a contrast slider with no usable range at all.
"""

from __future__ import annotations

import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

VIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(VIZ / "backend"))
sys.path.insert(0, str(VIZ.parent))

import numpy as np  # noqa: E402
import zarr  # noqa: E402

import contrast  # noqa: E402
from zmart_storage.canvas import Channel, TileCanvases  # noqa: E402

# One tile, sized so it begins and ends on whole pieces of image -- which is what
# DATA_LAYOUT.md asks for, and what lets tiles be written side by side safely.
TILE = (64, 1024, 1024)

# The imaged region is the same in every case below: four tiles in a square. Only the
# room declared around it changes, which is what makes the comparison honest.
MOSAIC = (1, 2, 2)
IMAGED = (TILE[0] * MOSAIC[0], TILE[1] * MOSAIC[1], TILE[2] * MOSAIC[2])

# Roughly what a stage can reach, in voxels: a couple of thousand planes of depth and a
# canvas some sixteen thousand voxels across.
TRAVEL = (2048, 16384, 16384)


def one_tile() -> np.ndarray:
    """A tile that behaves like a real acquisition rather than like noise.

    A few hundred counts of background everywhere, with brighter structure in the
    middle. The distinction matters here: the window being measured is a percentile,
    so a tile of one constant value would make every case in the table look the same
    and hide the very thing this script is for.
    """
    rng = np.random.default_rng(0)
    voxels = rng.normal(300, 30, size=TILE).astype(np.int32)
    voxels[:, 200:800, 200:800] += rng.normal(2500, 400, size=(TILE[0], 600, 600)).astype(np.int32)
    return np.clip(voxels, 0, 65535).astype(np.uint16)


def write_canvas(folder: Path, canvas_shape, tile, *, centred: bool) -> Path:
    """Declare a canvas of ``canvas_shape`` and image the same small mosaic inside it."""
    canvases = TileCanvases.create(
        folder=folder,
        name="targetscan",
        canvas_shape=canvas_shape,
        tile_shape=TILE,
        tile_step=TILE,
        voxel_size_um=(5.0, 0.5, 0.5),
        channels=[Channel(name="488", color="00FF00")],
        chunk=256,
        levels=3,
    )
    if centred:
        # Where a run actually puts the specimen: the canvas is the stage's travel and
        # the specimen sits somewhere in the middle of it.
        corner = tuple((canvas_shape[axis] - IMAGED[axis]) // 2 for axis in range(3))
        corner = (corner[0], corner[1] // TILE[1] * TILE[1], corner[2] // TILE[2] * TILE[2])
    else:
        corner = (0, 0, 0)
    for iz in range(MOSAIC[0]):
        for iy in range(MOSAIC[1]):
            for ix in range(MOSAIC[2]):
                canvases.write(
                    tile,
                    origin=(
                        corner[0] + iz * TILE[0],
                        corner[1] + iy * TILE[1],
                        corner[2] + ix * TILE[2],
                    ),
                    channel=0,
                )
    return canvases.paths[0]


def look_at(store: Path) -> dict:
    """Read the store the way the viewer does when it first meets it, and time it."""
    coarsest = zarr.open_group(str(store), mode="r")["2"]
    contrast.measure(store)  # once first, so the timing below is not paying for the disk
    runs = []
    for _ in range(5):
        started = time.perf_counter()
        result = contrast.measure(store)
        runs.append((time.perf_counter() - started) * 1000)
    # The same sample the window was taken from, asked for again so the table can say
    # how much of it had anything written to it. That share is what explains the window
    # rather than merely reporting it, and it is not something `measure` hands back --
    # hence reaching for the reading step directly.
    samples = contrast._samples(store)
    values = samples[1] if samples is not None else np.asarray([])
    return {
        "coarsest": tuple(int(n) for n in coarsest.shape)[2:],
        "milliseconds": statistics.median(runs),
        "megabytes": sum(p.stat().st_size for p in store.rglob("*") if p.is_file()) / 1024 / 1024,
        "volumeWindow": result["volumeWindow"],
        "imagedFraction": float((values > 0).mean()) if values.size else 0.0,
    }


CASES = (
    ("declared what was imaged", IMAGED),
    ("depth generous only", (TRAVEL[0], IMAGED[1], IMAGED[2])),
    ("width generous only", (IMAGED[0], TRAVEL[1], TRAVEL[2])),
    ("all three generous", TRAVEL),
)

# Where the depth stops being safe. The four sampled planes stand a third of the declared
# depth apart, so a band of specimen is certain to be caught only while it is thicker than
# that gap -- which puts the edge at about three times the imaged depth. These are the
# declared depths either side of it, so the table shows the edge rather than asserting it.
DEPTH_SWEEP = (64, 96, 128, 160, 192, 224, 256, 384, 512, 1024, 2048)


def sweep_depth(work: Path, tile: np.ndarray) -> None:
    """Vary only the declared depth, and watch the window fall over."""
    print("\n=== how much declared depth is too much ===")
    print(f"{'declared depth':>14s} {'times imaged':>13s} {'imaged':>7s}  volume window")
    for depth in DEPTH_SWEEP:
        folder = work / f"depth-{depth}"
        store = write_canvas(folder, (depth, IMAGED[1], IMAGED[2]), tile, centred=True)
        samples = contrast._samples(store)
        values = samples[1] if samples is not None else np.asarray([])
        low, high = contrast.measure(store)["volumeWindow"]
        share = 100 * float((values > 0).mean()) if values.size else 0.0
        print(
            f"{depth:14d} {depth / IMAGED[0]:12.1f}x {share:6.1f}%  ({low:.0f}, {high:.0f})"
            + ("   <-- nothing usable" if high - low <= 1.0 else "")
        )
        shutil.rmtree(folder, ignore_errors=True)


def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="zmart-declared-room-"))
    tile = one_tile()
    try:
        for centred in (True, False):
            where = (
                "the specimen in the middle of the canvas, where a run puts it"
                if centred
                else "the specimen in the corner of the canvas"
            )
            print(f"\n=== {where} ===")
            print(
                f"{'declared':26s} {'coarsest z, y, x':>22s} {'ms':>6s} {'disk MB':>8s} "
                f"{'imaged':>7s}  volume window"
            )
            for label, canvas_shape in CASES:
                name = f"{int(centred)}-{label.replace(' ', '-')}"
                store = write_canvas(work / name, canvas_shape, tile, centred=centred)
                seen = look_at(store)
                low, high = seen["volumeWindow"]
                print(
                    f"{label:26s} {str(seen['coarsest']):>22s} {seen['milliseconds']:6.0f} "
                    f"{seen['megabytes']:8.0f} {seen['imagedFraction'] * 100:6.1f}%  "
                    f"({low:.0f}, {high:.0f})"
                    + ("   <-- nothing usable" if high - low <= 1.0 else "")
                )
                shutil.rmtree(work / name, ignore_errors=True)
        sweep_depth(work, tile)
        print(
            "\nThe 'imaged' column is the share of what the measurement looked at that had\n"
            "anything written to it. Where that falls below one percent the window collapses,\n"
            "because the window is a percentile taken high in the distribution and the empty\n"
            "voxels fill everything below it.\n"
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()

"""What one more position costs a run that is already going.

A run hands positions to the writer as they come off the camera, so the number
that decides whether an acquisition can keep up is not how fast a thousand of them
can be written in a loop — it is what the *next* one costs when it arrives on its
own, with the run already however large it is.

Those are different questions and the difference has caught this project before.
An earlier arrangement measured 0.32 milliseconds a position when they were added
in a loop, and 89 milliseconds for one arriving after a quiet moment, because
every arrival rewrote the whole map. A loop hides that: the map was being rewritten
there too, but the cost was spread over positions that were all already in it.

So each measurement here is of **one** position, timed on its own, with the run
grown to the size being asked about first. What matters is whether the number is
flat as the run grows. If it climbs, something is being paid per position already
written, and a long acquisition will slow down as it goes.

Four kinds of arrival are measured, because a smart experiment produces all four:

- **a new place** — the ordinary case, a position the run has not visited
- **another colour** at a place already imaged
- **a later moment** at a place already imaged
- **another slab of z** above a place already imaged

Run it from the top of the repository::

    python zmart-viewer/measure_what_one_more_position_costs.py
    python zmart-viewer/measure_what_one_more_position_costs.py --steps 10,100,1000
"""

from __future__ import annotations

import argparse
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

_VIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_VIZ.parent))

from zmart_storage.canvas import Channel  # noqa: E402
from zmart_storage.positions import start_a_run  # noqa: E402

# Small on purpose. The pixel-writing part of the cost is the same whatever the run
# already holds, so it is the *bookkeeping* that this is watching for — and a
# smaller position lets the run be grown to two thousand without the measurement
# turning into an afternoon.
TILE = (2, 256, 256)
PIECE = 128
VOXEL_UM = (2.0, 0.325, 0.325)
COLOURS = 2
MOMENTS = 2

STEPS = (10, 100, 500, 1000, 2000)

# How many arrivals to time at each size. Each is timed on its own; the middle one
# is reported, because an occasional pause for the filesystem says nothing about
# what an arrival usually costs.
REPEATS = 5


def _a_picture(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (600 + rng.normal(0, 300, TILE)).clip(0, 4000).astype("uint16")


def _grow_to(run, count: int, already: int, across: int) -> int:
    """Bring the run up to ``count`` places, without timing any of it."""
    for index in range(already, count):
        run.write(_a_picture(index),
                  at=(0, (index // across) * TILE[1], (index % across) * TILE[2]))
    return count


def _timed(what) -> float:
    """How long one arrival took, in milliseconds."""
    began = time.perf_counter()
    what()
    return (time.perf_counter() - began) * 1000.0


def main() -> int:
    parsing = argparse.ArgumentParser(description=__doc__)
    parsing.add_argument(
        "--steps", type=str, default=None,
        help="run sizes to measure at, comma separated "
             f"(default {','.join(str(n) for n in STEPS)})",
    )
    asked = parsing.parse_args()
    steps = sorted(int(n) for n in (asked.steps.split(",") if asked.steps
                                    else [str(n) for n in STEPS]))

    work = Path(tempfile.mkdtemp(prefix="one-more-position-"))
    rows = []
    try:
        across = int(np.ceil(np.sqrt(steps[-1] + REPEATS)))
        run = start_a_run(
            work / "experiment", name="experiment",
            # Room for the whole climb, plus a second slab of z so that the
            # "another slab" measurement has somewhere to land.
            room=(2 * TILE[0], (across + 2) * TILE[1], (across + 2) * TILE[2]),
            tile_shape=TILE, voxel_size_um=VOXEL_UM,
            channels=[Channel("488", window=(400, 3800)),
                      Channel("561", window=(400, 3800))],
            frames=MOMENTS, piece=PIECE,
        )
        grown = 0
        for count in steps:
            grown = _grow_to(run, count, grown, across)

            fresh, colour, moment, slab = [], [], [], []
            for repeat in range(REPEATS):
                index = grown + repeat
                where = (0, (index // across) * TILE[1], (index % across) * TILE[2])
                # A new place: the ordinary arrival.
                fresh.append(_timed(
                    lambda index=index, where=where: run.write(_a_picture(index), at=where)))
                # The same place in the other colour, and at a later moment. The
                # view already knows this place, so these should cost less.
                colour.append(_timed(
                    lambda index=index, where=where: run.write(_a_picture(index), at=where, channel=1)))
                moment.append(_timed(
                    lambda index=index, where=where: run.write(_a_picture(index), at=where, frame=1)))
                # A slab of z above it, which is a new place and a new image.
                above = (TILE[0], where[1], where[2])
                slab.append(_timed(
                    lambda index=index, above=above: run.write(_a_picture(index), at=above)))
            grown += REPEATS

            rows.append({
                "run": count,
                "fresh": statistics.median(fresh),
                "colour": statistics.median(colour),
                "moment": statistics.median(moment),
                "slab": statistics.median(slab),
            })
            print(f"  run of {count:>5}: a new place {rows[-1]['fresh']:.2f} ms, "
                  f"another colour {rows[-1]['colour']:.2f} ms", flush=True)

        finishing = time.perf_counter()
        run.finish()
        closing = (time.perf_counter() - finishing) * 1000.0
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print()
    print("| run already holds | a new place | another colour | a later moment | "
          "a slab of z |")
    print("|---|---|---|---|---|")
    for row in rows:
        print(f"| {row['run']} positions | {row['fresh']:.2f} ms | "
              f"{row['colour']:.2f} ms | {row['moment']:.2f} ms | "
              f"{row['slab']:.2f} ms |")
    print()
    print(f"Closing the run at the end took {closing:.0f} ms — that is when the "
          "positions added a line at a time are folded into the picture's "
          "description, and it is paid once.")
    print()
    print("Flat is the answer being looked for. A number that climbs with the "
          "first column means something is being paid per position already "
          "written, and a long acquisition would slow down as it went.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

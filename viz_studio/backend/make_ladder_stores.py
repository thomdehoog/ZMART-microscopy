"""Write a ladder of survey rungs: grids of positions for the opening measurement.

`measure_the_ladder_in_the_view.py` asks how the viewer's opening behaves as a
survey grows — four positions, then sixteen, and so on up to a thousand and
twenty-four. Each of those sizes is one *rung* of the ladder, and this script
writes them: a square grid of small position stores, every position carrying
its own stage offset so that the viewer's composing door can lay them into one
picture, exactly the way `make_test_stores.py` writes its two-by-two grid.

Each position is deliberately tiny — three channels, four planes, sixty-four
pixels a side — because what the ladder measures is the *opening*: how many
descriptions and pieces the browser asks for as the survey grows, not how big
any one image is. A small frame keeps a thousand positions cheap to write and
cheap to hold, and measures the same round trips a full-size survey would.
(The 320-pixel frame in `make_test_stores.py` exists for the live replay
planner, which needs frames that halve cleanly; the composing door being
exercised here works at any size, so these frames stay small.)

Neighbouring positions step 56 of their 64 pixels, so they overlap by an
eighth the way a real survey's tiles do. The three channels are dressed white,
green and magenta with a display window from the background to the brightest
blob, so the opened picture shows colour rather than clipped white.

Rungs are written lazily: asking for a rung that is already complete on disk
costs a glance and nothing more. Run it on its own to write the whole ladder::

    python make_ladder_stores.py            # all five rungs
    python make_ladder_stores.py 4 64       # just these rung sizes

The rungs land in ``test_stores/ladder/rung_<N>/``, beside the other test
stores and one step away from the demo folder, for the reason given in
`make_test_stores.py`: the demo server live-watches its own folder and would
open every rung on its own the moment it appeared.
"""

from __future__ import annotations

import json
import math
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from make_test_stores import _SCALE, _tiny_volume  # noqa: E402

LADDER = _HERE / "test_stores" / "ladder"
RUNGS = (4, 16, 64, 256, 1024)

# One position's frame: channel, z, y, x. Three channels so mixing three
# colours can be seen working; four planes so the Z slider has somewhere to go.
FRAME = (3, 4, 64, 64)

# How far a neighbour steps, in pixels of the 64-pixel frame: an eighth of
# overlap on each side, the way a survey's tiles overlap so nothing is missed
# between them.
STEP_PX = 56

# The display dressing all three channels share: window from just under the
# 800-count background to the brightest blob, the same range the other test
# stores use, so nothing opens clipped white or pitch black.
_WINDOW = {"min": 0.0, "max": 65535.0, "start": 780.0, "end": 8800.0}
_CHANNELS = [
    {"label": "nuclei", "color": "FFFFFF", "active": True, "window": dict(_WINDOW)},
    {"label": "marker-a", "color": "00FF66", "active": True, "window": dict(_WINDOW)},
    {"label": "marker-b", "color": "FF33FF", "active": True, "window": dict(_WINDOW)},
]

# From how many positions writing fans out over worker processes. Below this
# the pool costs more to start than it saves; measured at about 0.1 s per
# store serially, so a 256-store rung is half a minute alone and worth sharing.
_POOL_FROM = 64


def _write_one_position(rung: Path, row: int, column: int, seed: int) -> None:
    """Write one position store, carrying its own place on the stage.

    The offset is written in micrometres, because that is what a real
    acquisition writes: the viewer learns where a tile belongs from the
    tile itself, never from its name.
    """
    import ngff_zarr

    image = ngff_zarr.to_ngff_image(
        _tiny_volume(seed, FRAME),
        dims=("c", "z", "y", "x"),
        scale=_SCALE,
        translation={
            "z": 0.0,
            "y": row * STEP_PX * _SCALE["y"],
            "x": column * STEP_PX * _SCALE["x"],
        },
    )
    multiscales = ngff_zarr.to_multiscales(image, scale_factors=[2])
    store = rung / f"pos_{row:03d}_{column:03d}.ome.zarr"
    ngff_zarr.to_ngff_zarr(str(store), multiscales, version="0.4", overwrite=True)

    # The dressing: names, colours and windows for all three channels.
    # `make_test_stores._dress_the_channels` writes two channels, so the
    # three-channel block is written here in the same shape.
    described = store / ".zattrs"
    attrs = json.loads(described.read_text(encoding="utf-8"))
    attrs["omero"] = {"channels": [dict(one) for one in _CHANNELS],
                      "rdefs": {"model": "color"}}
    described.write_text(json.dumps(attrs, indent=1), encoding="utf-8")


def a_rung_of(count: int) -> Path:
    """Write the ``count``-position rung if it is not already there, and say where.

    A rung that already holds exactly as many finished positions as its name
    promises is left alone. Anything else — half-written, or from an older
    shape of this script — is thrown away and written afresh, because a rung
    holding the wrong number of positions would put a wrong number in the
    table rather than a missing one.
    """
    across = math.isqrt(count)
    if across * across != count:
        raise ValueError(f"a rung is a square grid, and {count} is not square")
    rung = LADDER / f"rung_{count}"
    if rung.is_dir():
        finished = sum(1 for one in rung.glob("pos_*.ome.zarr")
                       if (one / ".zattrs").is_file())
        if finished == count:
            return rung
        shutil.rmtree(rung)
    rung.mkdir(parents=True)

    places = [(row, column) for row in range(across) for column in range(across)]
    began = time.perf_counter()
    if count >= _POOL_FROM:
        with ProcessPoolExecutor() as pool:
            # list() so that a worker's failure surfaces here rather than
            # passing silently and leaving a rung short of its promise.
            list(pool.map(_write_one_position,
                          (rung for _ in places),
                          (row for row, _ in places),
                          (column for _, column in places),
                          (row * across + column + 7
                           for row, column in places),
                          chunksize=8))
    else:
        for row, column in places:
            _write_one_position(rung, row, column, row * across + column + 7)
    took = time.perf_counter() - began
    held = sum(one.stat().st_size for one in rung.rglob("*") if one.is_file())
    print(f"rung {count:>4}: {count} positions written in {took:>5.1f}s, "
          f"{held / 1e6:.1f} MB on disk", flush=True)
    return rung


def main() -> None:
    asked = [int(one) for one in sys.argv[1:]] or list(RUNGS)
    for count in asked:
        a_rung_of(count)


if __name__ == "__main__":
    main()

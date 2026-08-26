"""Watch a run fill a single OME-Zarr, one position every few seconds.

This is the live-mode layout, running, with no microscope attached. A store is
declared once at its full size — the ground the experiment means to cover — and
then positions are written into it one at a time, exactly as a run would. The
viewer is open the whole time and each position appears as it lands.

Run it with::

    python run_live_run_demo.py

    python run_live_run_demo.py --positions 20 --every 5

It opens in a native window if pywebview is installed, and falls back to
printing an address for a browser if not. The built page must exist first
(``app/page/dist``).

**The two things this is here to show.**

The store never changes shape. Its canvas is declared before a single pixel
exists, so nothing is added to the folder and no description is rewritten — the
positions land in places that already existed and were empty. That is what keeps
the viewer's idea of the data stable while it fills.

And the run has to *say* so. The drawing engine remembers every piece of image it
has decoded, including the pieces it found empty, with no time limit and no way
for an HTTP header to reach it. A position written where the viewer has already
looked is otherwise not noticed — not slowly, never, and without a single request
being made. So each write here is followed by an announcement carrying
``wrote_image_in_place``, which is what makes the viewer let go of what it
decoded and look again. Comment out that announcement and the window stays blank
for the whole run while the data piles up on disk: that is worth doing once, on
purpose, because it is the failure an operator would otherwise meet by accident.

**Why each level has its own chunk size.** A position is one chunk at level 0. At
the level above it covers half as much ground, so if the chunk size stayed the
same it would be a *quarter* of a chunk — and four positions would share one
chunk file, each having to read it, add its own corner and write the whole thing
back. Two writers doing that at once lose a position silently. Halving the chunk
size with each level keeps every write a create rather than a read-modify-write,
which is the shape a real writer should copy.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "app" / "server"))

from launcher import open_window  # noqa: E402

# One position is one chunk of this many pixels at full resolution, and the run
# lays them out in a grid. Small enough to write in a moment, large enough to see.
TILE = 256
ACROSS, DOWN = 5, 4
PLANES = 8
LEVELS = 3
VOXEL_UM = (2.0, 0.35, 0.35)
STORE_NAME = "overview_whole.ome.zarr"


def declare_the_canvas(store: Path) -> None:
    """Create the store at its full size, with nothing in it.

    This is the whole of the difference from the ordinary layout. A run that
    writes one store per position adds a folder as each position finishes; this
    one makes the specimen's full extent up front and fills it in.
    """
    datasets = []
    for level in range(LEVELS):
        chunk = TILE >> level
        height, width = DOWN * chunk, ACROSS * chunk
        folder = store / str(level)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / ".zarray").write_text(
            json.dumps(
                {
                    "zarr_format": 2,
                    "shape": [1, PLANES, height, width],
                    # The chunk shrinks with the level so that one position stays
                    # exactly one chunk all the way up the pyramid.
                    "chunks": [1, 1, chunk, chunk],
                    "dtype": "<u2",
                    "compressor": None,
                    "fill_value": 0,
                    "order": "C",
                    "filters": None,
                    "dimension_separator": ".",
                }
            ),
            encoding="utf-8",
        )
        datasets.append(
            {
                "path": str(level),
                "coordinateTransformations": [
                    {
                        "type": "scale",
                        # Space is halved with each level; the channel axis is not.
                        "scale": [1.0, VOXEL_UM[0], *(unit * 2**level for unit in VOXEL_UM[1:])],
                    }
                ],
            }
        )
    (store / ".zgroup").write_text(json.dumps({"zarr_format": 2}), encoding="utf-8")
    (store / ".zattrs").write_text(
        json.dumps(
            {
                "multiscales": [
                    {
                        "version": "0.4",
                        "axes": [
                            {"name": "c", "type": "channel"},
                            {"name": "z", "type": "space", "unit": "micrometer"},
                            {"name": "y", "type": "space", "unit": "micrometer"},
                            {"name": "x", "type": "space", "unit": "micrometer"},
                        ],
                        "datasets": datasets,
                    }
                ],
                "omero": {"channels": [{"label": "specimen", "color": "00FF00"}]},
            }
        ),
        encoding="utf-8",
    )


def _one_position(chunk: int, brightness: int) -> bytes:
    """A plane of one position: a bright square inside a dimmer border.

    Something with structure in it, so that a position which has landed is
    obviously different from one that has not, and from its neighbours.
    """
    import numpy as np

    pixels = np.full((chunk, chunk), brightness // 3, dtype="<u2")
    inset = max(1, chunk // 6)
    pixels[inset:-inset, inset:-inset] = brightness
    return pixels.tobytes()


def write_position(store: Path, index: int) -> None:
    """Land one position, at every level of the pyramid.

    Every level, because the coarser ones are what the zoomed-out view reads. A
    level left unwritten is a specimen that vanishes the moment the operator
    zooms out to see the whole thing.
    """
    row, column = divmod(index, ACROSS)
    brightness = 1500 + (index % 7) * 1200
    for level in range(LEVELS):
        chunk = TILE >> level
        plane = _one_position(chunk, brightness)
        folder = store / str(level)
        for z in range(PLANES):
            (folder / f"0.{z}.{row}.{column}").write_bytes(plane)


def announce(port: int) -> None:
    """Tell the viewer a position landed inside a store it already has open.

    Without this nothing appears, however long you wait. See the note at the top.
    """
    body = json.dumps(
        {"reason": "a position finished", "wrote_image_in_place": True}
    ).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/announce",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as answer:
        answer.read()


def run_the_experiment(store: Path, port: int, positions: int, every: float) -> None:
    """The microscope's part: write a position, say so, wait, repeat."""
    # The window needs a moment to exist before there is anything to tell.
    time.sleep(every)
    for index in range(positions):
        write_position(store, index)
        try:
            announce(port)
        except OSError as closed:
            print(f"  the viewer is no longer listening ({closed}); stopping")
            return
        print(f"  position {index + 1} of {positions} landed", flush=True)
        if index + 1 < positions:
            time.sleep(every)
    print("  the run has finished; the window stays open")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--positions", type=int, default=ACROSS * DOWN)
    parser.add_argument("--every", type=float, default=5.0)
    parser.add_argument("--port", type=int, default=8851)
    parser.add_argument(
        "--folder",
        type=Path,
        default=HERE / "testdata" / "live_run_demo",
        help="where to write the store; it is recreated on every run",
    )
    args = parser.parse_args()

    if args.positions > ACROSS * DOWN:
        parser.error(f"the canvas declared here holds {ACROSS * DOWN} positions")

    import shutil

    folder = args.folder
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    store = folder / STORE_NAME
    declare_the_canvas(store)
    print(
        f"Declared one store for the whole specimen: {DOWN} x {ACROSS} positions, "
        f"{PLANES} planes deep, nothing written yet."
    )
    print(f"Landing {args.positions} of them, one every {args.every:g}s.")

    threading.Thread(
        target=run_the_experiment,
        args=(store, args.port, args.positions, args.every),
        daemon=True,
    ).start()

    open_window(
        port=args.port,
        data_dir=folder,
        store=STORE_NAME,
        live=True,
        allow_open=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

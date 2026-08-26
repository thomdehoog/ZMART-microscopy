"""What it costs to open a large finished folder, and where that cost goes.

This is the script behind the cold-open figures in `docs/open/NEXT_STEPS.md`. It answers one
question: when the viewer is pointed at a folder holding many positions that have
already been imaged, how long does the server take to describe what is there, and
how many stores does it have to read the pixels of to do so?

Why that second number matters. Deciding how a picture should first be shown --
how bright, and what the histogram under the contrast slider looks like -- means
reading image data, which is far more expensive than reading the small files that
describe a store. But several positions of one acquisition type are drawn as a
single row in the panel, and a row has one brightness setting for all of them. So
the number of stores that genuinely need reading is the number of rows, which is a
handful, however many positions the run holds. If this script reports a count that
follows the number of positions instead, that saving has been lost again.

Run it with::

    python measure_cold_open.py                 # 300 positions
    python measure_cold_open.py 1000            # or however many

It writes throwaway stores under a temporary folder and deletes them afterwards,
so nothing here touches your data. Be aware that it does write real pixels -- the
cost being measured is the cost of reading them -- so a few hundred positions is a
couple of gigabytes while it runs.

The stores are shaped the way `docs/how_it_works/DATA_LAYOUT.md` asks for at their coarsest level,
because that is what sets the price: judging brightness looks at the smallest copy
of the image, so a store's cost depends on how big that smallest copy is and not
at all on how large the acquisition really is. A store written here therefore costs
the same to judge as one from a 400 GB run would.

To see the difference the change made, run it once as the code stands and once
with the cold-open change undone (`git stash`); the times differ by about a
hundredfold at three hundred positions, and the description handed to the panel is
identical either way -- which is the point, since the measurements that were being
saved had never reached the screen.
"""

from __future__ import annotations

import http.client
import json
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import zarr

VIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(VIZ / "app" / "server"))

# One pyramid level of two channels, sixteen planes, 256 x 256. That is the
# coarsest level docs/how_it_works/DATA_LAYOUT.md asks for, and the coarsest level is what the
# brightness measurement actually reads. Only one level is written so that a few
# hundred positions still fit on an ordinary disk.
CHANNELS, DEPTH, SIDE, CHUNK = 2, 16, 256, 64

# Three acquisition types, so the folder merges into a realistic handful of rows
# rather than a single one -- otherwise "one measurement per row" and "one
# measurement in total" would look the same and a mistake could hide between them.
KINDS = ("overview", "targetscan", "detail")


def write_store(folder: Path, name: str, seed: int) -> None:
    """Write one position: a small OME-Zarr with real pixels in it."""
    store = folder / name
    store.mkdir(parents=True, exist_ok=True)
    group = zarr.open_group(str(store), mode="w", zarr_format=2)
    array = group.create_array(
        "0",
        shape=(1, CHANNELS, DEPTH, SIDE, SIDE),
        chunks=(1, 1, 1, CHUNK, CHUNK),
        dtype="uint16",
        chunk_key_encoding={"name": "v2", "separator": "/"},
    )
    # Real, varied values rather than a constant. A store full of one number is
    # far quicker to judge the brightness of than a real image, and would make
    # this whole measurement report a cost nobody actually pays.
    rng = np.random.default_rng(seed)
    array[:] = rng.integers(0, 4000, size=(1, CHANNELS, DEPTH, SIDE, SIDE), dtype=np.uint16)
    (store / ".zattrs").write_text(
        json.dumps(
            {
                "multiscales": [
                    {
                        "version": "0.4",
                        "axes": [
                            {"name": "t", "type": "time", "unit": "second"},
                            {"name": "c", "type": "channel"},
                            {"name": "z", "type": "space", "unit": "micrometer"},
                            {"name": "y", "type": "space", "unit": "micrometer"},
                            {"name": "x", "type": "space", "unit": "micrometer"},
                        ],
                        "datasets": [
                            {
                                "path": "0",
                                "coordinateTransformations": [
                                    {"type": "scale", "scale": [1.0, 1.0, 5.0, 0.5, 0.5]}
                                ],
                            }
                        ],
                    }
                ],
                "omero": {
                    "channels": [
                        {"label": "Ch488", "color": "00FF00"},
                        {"label": "Ch561", "color": "FF0000"},
                    ]
                },
            }
        ),
        encoding="utf-8",
    )


def measure(positions: int, folder: Path) -> dict:
    """Open a folder of ``positions`` stores and report what describing it cost."""
    for index in range(positions):
        write_store(folder, f"{KINDS[index % len(KINDS)]}_pos{index:05d}.ome.zarr", seed=index)

    # Count how many stores have their pixels read, by wrapping the function that
    # does it. This is the number that should stay small however large the folder.
    import contrast
    import server as server_module

    real, counted = contrast.measure, {"stores": 0}

    def counting(path, *args, **kwargs):
        counted["stores"] += 1
        return real(path, *args, **kwargs)

    contrast.measure = counting
    # server.py imported the function by name, so it holds its own reference and
    # has to be pointed at the counting version separately.
    if getattr(server_module, "measure", None) is real:
        server_module.measure = counting

    names = sorted(path.name for path in folder.iterdir() if path.is_dir())
    httpd = server_module.make_server(port=0, data_dir=folder, store=names, live=False)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        started = time.perf_counter()
        connection = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=3600)
        connection.request("GET", "/api/config")
        config = json.loads(connection.getresponse().read())
        took = time.perf_counter() - started
    finally:
        httpd.shutdown()
        httpd.server_close()
        contrast.measure = real
        server_module.measure = real

    return {
        "positions": positions,
        "seconds": took,
        "storesRead": counted["stores"],
        "rows": len(config["layers"]),
        "config": config,
    }


def main() -> None:
    positions = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    work = Path(tempfile.mkdtemp(prefix="zmart-cold-open-"))
    try:
        print(f"Writing {positions} positions -- this takes a few minutes.")
        result = measure(positions, work / "run")
        print(
            f"\n{result['positions']} positions became {result['rows']} rows.\n"
            f"Describing the folder took {result['seconds']:.2f} s "
            f"and read the pixels of {result['storesRead']} stores.\n"
        )
        if result["storesRead"] > result["rows"]:
            print(
                "More stores were read than there are rows, which means the saving "
                "described in docs/open/NEXT_STEPS.md has been lost. Look at build_config in "
                "app/server/server.py: the measurement belongs inside the branch that "
                "creates a row, not beside it."
            )
        else:
            print(
                "That is one read per row at most, and fewer where a store holds "
                "several channels and so decides more than one row at once. This is "
                "the property worth keeping: a run ten times the size costs the same "
                "to open."
            )
        # Written out so two runs can be compared field by field. The description
        # should be identical whether every store is read or only one per row.
        out = Path(f"cold_open_{positions}.json")
        out.write_text(json.dumps(result["config"], indent=2, sort_keys=True))
        print(f"\nThe description the panel receives is in {out}.")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()

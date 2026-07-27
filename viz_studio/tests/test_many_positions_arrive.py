"""Opening a folder with many positions, and getting all of them.

This is about a fault that was easy to miss and serious to have. A folder holding
more than roughly six hundred and eighty positions used to draw only some of the
specimen and say nothing at all about the rest — a folder of two thousand positions
showed six hundred and eighty-six of them, and looked complete. An operator would have
been judging their experiment from a small part of it without knowing.

The cause is the browser rather than the data or the disk. Reading one store means a
handful of small requests for the files describing it, and a browser will only hold six
conversations with one address at a time; beyond a few thousand requests waiting their
turn it refuses to start any more. Neuroglancer takes a refused request as "this store
cannot be read" and leaves that position out. So the viewer now hands the stores over in
groups and lets each group finish before offering the next, which keeps the queue short
enough that nothing is ever refused.

Proving that on a real folder would mean writing a thousand positions and waiting
several minutes, which is too slow to live in the suite. Instead the size of a group is
turned right down for these tests, so the same pacing can be watched happening over a
few dozen positions in a few seconds. The mechanism under test is identical; only the
number is smaller.

Two things are checked together, and neither is worth much without the other. That
**every position arrives** is the point of the exercise. That the positions arrived
**in groups rather than all at once** is the positive control: without it this file
would pass just as happily against the old viewer on a folder small enough not to
trip the browser's limit, which is to say it would be testing nothing.
"""

from __future__ import annotations

import json
import threading

import numpy as np
from pixels import assert_something_was_drawn
from server import make_server

# Enough positions to show pacing plainly at a small group size, and few enough that
# the folder is written and read in a couple of seconds. One channel, so the number of
# stores and the number of data sources the engine holds are the same number and the
# arithmetic below stays easy to follow.
POSITIONS = 40
GROUP = 5

SIDE = 128
VOXEL_UM = (2.0, 0.35, 0.35)
STEP_UM = SIDE * VOXEL_UM[2]


def write_position(store, index: int, across: int) -> None:
    """One position: the small files that describe it, and a single plane of image.

    Written by hand rather than through zarr because the cost being exercised is the
    number of separate stores, not their size — a position of one small plane costs the
    engine the same handful of requests as one holding a hundred gigabytes. Forty of
    these are written in well under a second, where forty real ones would not be.
    """
    level = store / "0"
    level.mkdir(parents=True, exist_ok=True)
    (store / ".zgroup").write_text('{"zarr_format": 2}', encoding="utf-8")
    (level / ".zarray").write_text(
        json.dumps(
            {
                "zarr_format": 2,
                "shape": [1, 1, SIDE, SIDE],
                "chunks": [1, 1, SIDE, SIDE],
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
    y, x = np.mgrid[0:SIDE, 0:SIDE]
    (level / "0.0.0.0").write_bytes((500 + (y + x) * 8).astype("<u2").tobytes())
    # Where this position sits on the stage. Stepped by exactly one image width, so the
    # positions tile edge to edge the way a real mosaic does.
    row, column = divmod(index, across)
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
                        "datasets": [
                            {
                                "path": "0",
                                "coordinateTransformations": [
                                    {"type": "scale", "scale": [1.0, *VOXEL_UM]},
                                    {
                                        "type": "translation",
                                        "translation": [
                                            0.0,
                                            0.0,
                                            row * STEP_UM,
                                            column * STEP_UM,
                                        ],
                                    },
                                ],
                            }
                        ],
                    }
                ],
                "omero": {
                    "channels": [
                        {
                            "label": "ch0",
                            "color": "FFFFFF",
                            "window": {"min": 0, "max": 65535, "start": 0, "end": 4000},
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )


def write_folder(root, count: int) -> None:
    across = max(1, int(count**0.5))
    for index in range(count):
        write_position(root / f"overview_pos{index:05d}.ome.zarr", index, across)


# Turn the group size right down, and start noting how many stores the engine is
# holding. This runs before any of the page's own code, so the very first group is seen
# as well as the later ones. Only changes are recorded, so the list that comes back is
# the sequence of sizes the engine passed through rather than thousands of repeats.
WATCH = """
window.zmartSourceBatch = %d;
window.zmartArrivals = [];
setInterval(() => {
  const viewer = window.zmartViewer;
  if (!viewer) return;
  const held = viewer.layerManager.managedLayers
    .filter((managed) => managed.layer && managed.layer.type === 'image')
    .reduce((total, managed) => total + managed.layer.dataSources.length, 0);
  const seen = window.zmartArrivals;
  if (seen[seen.length - 1] !== held) seen.push(held);
}, 5);
""" % GROUP

HELD = """() => window.zmartViewer.layerManager.managedLayers
           .filter((managed) => managed.layer && managed.layer.type === 'image')
           .reduce((total, managed) => total + managed.layer.dataSources.length, 0)"""


def test_every_position_reaches_the_engine_and_they_arrive_in_groups(
    browser, built_dist, tmp_path
):
    """A folder of many positions loads all of them, a group at a time."""
    write_folder(tmp_path, POSITIONS)
    # Opened the way a finished folder is opened: everything already on disk, nothing
    # being written, no watching. That is the case where every position used to be
    # handed to the engine in one burst.
    server = make_server(
        port=0,
        data_dir=tmp_path,
        site_dir=built_dist,
        store=sorted(p.name for p in tmp_path.glob("*.ome.zarr")),
        live=False,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1000, "height": 800})
    page.add_init_script(WATCH)
    try:
        page.goto(
            f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded"
        )
        page.wait_for_function("() => window.zmartViewer !== undefined", timeout=60_000)

        # Every position the panel knows about has been handed over, and the queue of
        # ones still to hand over is empty. The second half matters: a viewer that had
        # simply stopped feeding partway through would satisfy neither, but a viewer
        # that had lost the last few would satisfy the count on its own if the count
        # were read too early.
        page.wait_for_function(f"{HELD} === {POSITIONS}", timeout=120_000)
        page.wait_for_function("() => window.zmartSourcesWaiting() === 0", timeout=120_000)
        assert page.evaluate(HELD) == POSITIONS

        # And they went in as a series of groups rather than in one go. Without the
        # pacing the engine would step straight from holding none to holding all forty,
        # so every reading in between is the pacing being seen at work. Forty positions
        # in groups of five means seven such readings if none is missed; four are
        # required, which leaves room for the watcher happening to look at the wrong
        # moment without leaving room for no pacing at all.
        #
        # The size of the groups themselves is deliberately not asserted. The watcher
        # looks every five milliseconds and the engine could finish two groups between
        # two looks on a busy machine, so a check on the size of each step would fail
        # now and then for reasons that have nothing to do with the viewer. What matters
        # here is that the handing over is paced; how large a group is belongs to
        # AT_A_TIME in engine.js and is measured properly by check_scale.py.
        arrivals = page.evaluate("() => window.zmartArrivals")
        partway = [held for held in arrivals if 0 < held < POSITIONS]
        assert len(partway) >= 4, (
            "the positions were handed to the engine all at once rather than in "
            f"groups, which is what silently loses them on a large folder: {arrivals}"
        )

        # And there is genuinely a picture at the end of it. Counting data sources says
        # the engine was handed the stores; it does not say the specimen is on screen.
        # The two have come apart before — the viewer once held everything it needed and
        # drew the specimen a ten-thousandth of a pixel wide — so the panel is looked at
        # as well as counted.
        page.wait_for_timeout(2000)
        assert_something_was_drawn(page, "a folder of many positions")
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)

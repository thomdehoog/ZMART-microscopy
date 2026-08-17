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
from measure_the_frame_rate_of_a_linked_view import (  # noqa: E402
    EVERY_SOURCE_RESOLVED,
)
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
""" % GROUP  # noqa: UP031 -- the payload is JavaScript; its braces would fight str.format

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
        # Handed over is not read: that wait empties when the last URL reaches
        # the engine, with most of the positions still unresolved.
        page.wait_for_function(EVERY_SOURCE_RESOLVED, timeout=300_000)
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


# --------------------------------------------------------------------------
# The number the pacing turns on, and how to find it again
# --------------------------------------------------------------------------
#
# Everything above turns the group size right down so the pacing can be watched over
# forty positions in a few seconds. That is the right way to test the *mechanism*,
# but it leaves the number the viewer actually ships with untested: the production
# size could be raised to something unsafe and nothing in the suite would notice.
#
# Two things follow. The first is cheap and always runs: the shipped number is read
# out of the source and checked against the limit that was measured. The second is
# the measurement itself, which means opening folders of thousands of positions in a
# real browser and is far too slow to live in an ordinary run, so it is opt-in.

import os  # noqa: E402
import re  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

# How long to let one folder go on arriving before giving up on it, and how many
# quiet seconds count as "it has finished". Generous on purpose: pacing makes a
# large folder take longer by design, and a cap that cuts it off partway reports
# the pacing as losing positions when it is merely still working. That is not a
# hypothetical — measured with a three-minute cap, four thousand positions read as
# two thousand one hundred arrived, and the pacing looked worse than no pacing at
# all.
PATIENCE_S = 1800
QUIET_ROUNDS = 20

# Where the browser began refusing requests, measured by hand on a folder of two
# thousand positions: it held six hundred and eighty-six of them and looked complete.
# The exact figure depends on the machine and the browser, which is why the group
# size is chosen well below it rather than just under it.
THE_MEASURED_LIMIT = 680

# How much room the shipped group size must leave beneath that. A third is not a
# precise science; it is the margin that keeps the viewer safe on a machine slower
# or busier than the one the limit was measured on, where the browser gives up
# sooner. Raising the group size above this is not forbidden — it means the limit
# needs measuring again, which is what the opt-in test below is for.
SAFE_SHARE = 1 / 3

FIND_THE_LIMIT = "ZMART_FIND_THE_LIMIT"


def the_shipped_group_size() -> int:
    """The group size the viewer actually ships with, read from its source.

    Read from the source rather than from the running page because the page does
    not expose it — and deliberately not duplicated here as a number, because two
    copies of a constant drift apart and the copy in the test is the one that would
    quietly stop describing the viewer.
    """
    source = (
        Path(__file__).resolve().parent.parent / "frontend" / "src" / "engine.js"
    ).read_text(encoding="utf-8")
    found = re.search(r"const AT_A_TIME\s*=\s*(\d+)", source)
    assert found, (
        "AT_A_TIME could not be found in engine.js. It is the number of stores the "
        "viewer hands to the engine at a time, and it is what keeps a large folder "
        "from silently losing positions — so if it has been renamed, this test has "
        "to be taught the new name rather than deleted."
    )
    return int(found.group(1))


def test_the_shipped_group_size_leaves_room_beneath_the_measured_limit():
    """The one check that fails if somebody raises the real number.

    A folder of more than roughly six hundred and eighty positions used to draw
    only part of the specimen and say nothing about the rest. The pacing is what
    prevents that, and the pacing is only as good as the size of a group: set it
    above the browser's limit and the viewer is exactly as broken as it was before,
    while every other test in this file — which runs at a group size of five —
    carries on passing.
    """
    shipped = the_shipped_group_size()
    ceiling = int(THE_MEASURED_LIMIT * SAFE_SHARE)

    assert shipped > 0, "a group size of nothing would hand over no positions at all"
    assert shipped <= ceiling, (
        f"the viewer hands over {shipped} stores at a time, and the browser was "
        f"measured to start refusing requests at about {THE_MEASURED_LIMIT}. That "
        f"leaves too little room: at most {ceiling} keeps a margin for a machine "
        "slower or busier than the one the limit was measured on.\n\n"
        "If the limit is genuinely higher than it was, measure it again rather than "
        f"raising this ceiling from memory:\n\n    {FIND_THE_LIMIT}=1 python "
        "run_tests.py -s -k finds_the_limit\n"
    )


@pytest.mark.skipif(
    not os.environ.get(FIND_THE_LIMIT),
    reason=(
        f"set {FIND_THE_LIMIT}=1 to search for the browser's limit. It opens folders "
        "of thousands of positions in a real browser and takes many minutes, so it "
        "is not part of an ordinary run."
    ),
)
def test_finds_the_limit_where_positions_begin_to_be_lost(browser, built_dist, tmp_path):
    """Find where the browser starts refusing, and check the pacing carries past it.

    This is the measurement the number above came from, kept as something that can
    be run again rather than as a figure in a comment that nobody can check. Run it
    when the browser is updated, when the viewer moves to a different engine, or
    when somebody wants to raise the group size.

    It works in two halves. First it turns the pacing **off** and opens folders of
    increasing size until positions start going missing, narrowing down by halving
    until it has the boundary — that number is the browser's limit on this machine.
    Then it opens a folder comfortably past that limit with the pacing **on**, which
    must carry every position, because that is the whole point of the mechanism.

    It prints what it found. Run it with ``-s`` to see that.
    """
    # How far to look. Two thousand is the default because it is the largest
    # folder the pacing has actually been measured against, and because a folder
    # of it opens in minutes rather than tens of minutes on an ordinary machine.
    # Push it higher deliberately when you want to know where the ceiling really
    # is: ZMART_LIMIT_UPTO=8000.
    smallest = 100
    largest = int(os.environ.get("ZMART_LIMIT_UPTO", "2000"))
    write_folder(tmp_path / "probe", largest)
    every = sorted(p.name for p in (tmp_path / "probe").glob("*.ome.zarr"))

    def how_many_arrive(count: int, *, paced: bool) -> int:
        """Open the first ``count`` positions and see how many reach the engine.

        Waits for the number to **stop moving** rather than for a fixed length of
        time, and that distinction is the whole measurement. Pacing deliberately
        makes a large folder take longer — each group is allowed to finish before
        the next is offered — so a fixed cap reports "positions were lost" for a
        viewer that was simply still working. Measured that way, the pacing looked
        worse than no pacing at all, which is the opposite of the truth.
        """
        server = make_server(
            port=0, data_dir=tmp_path / "probe", site_dir=built_dist,
            store=every[:count], live=False,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        page = browser.new_page(viewport={"width": 1000, "height": 800})
        if not paced:
            # A group larger than the folder is the same as no pacing at all: every
            # position is offered in one breath, which is what the viewer used to do.
            page.add_init_script(f"window.zmartSourceBatch = {largest * 10};")
        try:
            page.goto(
                f"http://127.0.0.1:{server.server_address[1]}",
                wait_until="domcontentloaded",
            )
            page.wait_for_function("() => window.zmartViewer !== undefined", timeout=60_000)
            settled, held = 0, -1
            giving_up_at = time.monotonic() + PATIENCE_S
            while time.monotonic() < giving_up_at:
                now = page.evaluate(HELD)
                if now >= count:
                    return now
                if now == held:
                    # Nothing has moved for a while, and nothing is queued to be
                    # handed over. Whatever has not arrived is not going to.
                    settled += 1
                    if settled >= QUIET_ROUNDS and page.evaluate(
                        "() => window.zmartSourcesWaiting()"
                    ) == 0:
                        break
                else:
                    settled, held = 0, now
                page.wait_for_timeout(1000)
            return page.evaluate(HELD)
        finally:
            page.close()
            server.shutdown()
            thread.join(timeout=5)

    # Halve the gap between "all of them arrived" and "some went missing" until the
    # two meet. Each step opens one folder in a real browser, so a search rather than
    # a walk is what keeps this to minutes instead of hours.
    intact, lossy = smallest, largest
    assert how_many_arrive(intact, paced=False) == intact, (
        f"positions were already going missing at {intact}, which is below where "
        "this search was expecting to start. Lower `smallest` and run it again."
    )
    biggest = how_many_arrive(largest, paced=False)
    print(f"  unpaced, {largest} positions offered -> {biggest} arrived")
    if biggest == largest:
        # No loss anywhere in the range. That is a real answer and not a failure:
        # this machine's browser is more generous than the one the figure in the
        # register was measured on. What it means is that the range has to be
        # raised before a limit can be named at all.
        print(
            f"\n  no positions were lost anywhere up to {largest} on this machine, "
            f"so its limit is above {largest} and this search cannot name it.\n"
            f"  Raise `largest` and run it again if you need the number itself.\n"
            f"  The viewer ships a group size of {the_shipped_group_size()}, which is "
            "safe here by a wide margin."
        )
        intact = largest
    else:
        lossy = largest
        while lossy - intact > 50:
            middle = (intact + lossy) // 2
            arrived = how_many_arrive(middle, paced=False)
            print(f"  unpaced, {middle} positions offered -> {arrived} arrived")
            if arrived == middle:
                intact = middle
            else:
                lossy = middle
        print(
            f"\n  the browser carried {intact} positions unpaced and lost some by {lossy}"
        )
        print(f"  the viewer ships a group size of {the_shipped_group_size()}")
        assert the_shipped_group_size() <= intact, (
            f"the shipped group size ({the_shipped_group_size()}) is above what this "
            f"machine's browser carried unpaced ({intact})"
        )

    # And the pacing carries the whole folder, which is the point of it. Checked
    # whether or not a limit was found, because "the pacing delivers everything" is
    # worth knowing on any machine.
    arrived = how_many_arrive(largest, paced=True)
    print(f"  paced, {largest} positions offered -> {arrived} arrived")
    assert arrived == largest, (
        f"with the pacing on, {largest} positions were offered and only {arrived} "
        "arrived — the mechanism that exists to prevent exactly this is not working"
    )

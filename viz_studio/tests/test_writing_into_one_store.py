"""A run that writes into one OME-Zarr, rather than one per position.

There are two ways a smart-microscopy run can lay its data out, and they cost the viewer
very different amounts. One store per position is what the controller writes today. The
alternative is a single OME-Zarr, created empty at the start with the whole specimen's
extent declared, into which each tile is written straight to its place.

The second is much kinder to the viewer, and the reason is worth stating plainly: what
costs the viewer is the number of separate stores, not the amount of data behind them.
One store describing a hundred and thirty-seven gigabytes reaches the screen in about a
second and a half; three hundred tiny separate positions take longer, on thirty times the
requests, and then draw at a quarter of the rate. `measure_one_stitched_store.py` has the
figures.

But it only works if the viewer notices a tile written into a place it has already looked
at, and by default it does not. The drawing engine remembers every piece of image it has
decoded — including the pieces it found to be empty — and there is no time limit on that
memory. Left alone it goes on showing the emptiness it decided on earlier and never asks
the disk again. Not slowly: never, and without making a single request.

So the run has to say so, and it is the only one that can: nothing on disk changes when a
tile lands inside a store that is already open — same store, same name, same size — and
we measured that the viewer makes no request at all. An announcement may therefore carry
one piece of detail, `wrote_image_in_place`, and on hearing it the viewer asks the engine
to let go of the image it has decoded so that looking again really looks.

It is off by default, and that matters as much as the feature. These two tests are the
two halves, and neither is worth much without the other:

- a tile written into an open store **does** appear;
- a position arriving in the ordinary layout **does not** cost the view its image.

The second is the one that stops the first being bought too dearly. Letting go is cheap
only because it happens in the one case where nothing else can tell us anything; do it on
every announcement and a run would spend its life refetching what it already had. That is
not hypothetical — an earlier attempt worked it out from the scene instead of being told,
and this test caught it throwing the view away every time a neighbour arrived.
"""

from __future__ import annotations

import json
import threading

import numpy as np
import pytest
from pixels import assert_something_was_drawn, colour_spread, image_middle
from server import make_server

# A specimen a few tiles across, declared up front the way a run would declare a mosaic
# whose bounding box it knows before it starts. Small enough to write in a moment, and
# the number that matters -- how many separate stores there are -- is one either way.
SIDE, CHUNK, LEVELS = 1024, 256, 2
VOXEL_UM = (2.0, 0.35, 0.35)

# What a run says after writing a tile into the one store it is filling in. The flag is
# the whole point: it tells the viewer that the image landed somewhere it has already
# looked, which is the one thing reading the disk again cannot reveal.
ANNOUNCE_IN_PLACE = """async () => {
  const response = await fetch('/api/announce', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({reason: 'a tile was written', wrote_image_in_place: true}),
  });
  return (await response.json()).told;
}"""

# What a run says in the ordinary layout, where each position is a store of its own and
# the new store speaks for itself.
ANNOUNCE = """async () => {
  const response = await fetch('/api/announce', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({reason: 'a position finished'}),
  });
  return (await response.json()).told;
}"""


def one_tile() -> bytes:
    """A tile of image: a gradient, so it reads as a picture rather than a flat colour
    that an empty panel could not be told apart from."""
    y, x = np.mgrid[0:CHUNK, 0:CHUNK]
    return (600 + (y + x) * 4).astype("<u2").tobytes()


def declare_the_whole_specimen(store) -> None:
    """Create the store empty, with its full extent and pyramid declared but no image.

    This is what a run would do at the start: it knows how far the specimen reaches
    before it has visited any of it. A zarr reader treats a missing piece as empty, so a
    store in this state is perfectly valid and simply has nothing in it yet.
    """
    store.mkdir(parents=True, exist_ok=True)
    (store / ".zgroup").write_text('{"zarr_format": 2}', encoding="utf-8")
    datasets = []
    for level in range(LEVELS):
        side = SIDE >> level
        folder = store / str(level)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / ".zarray").write_text(
            json.dumps(
                {
                    "zarr_format": 2,
                    "shape": [1, side, side, side],
                    "chunks": [1, 1, CHUNK, CHUNK],
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
                        "scale": [1.0, *(unit * 2**level for unit in VOXEL_UM)],
                    }
                ],
            }
        )
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


def write_the_middle_tiles(store) -> None:
    """Write the tiles under the middle of the view, at every level of the pyramid.

    Every level, because a run writing into one store has to keep the coarser levels up
    to date as it goes — they are what makes zooming out affordable, and a level left
    unwritten is a specimen that vanishes when the operator zooms out.
    """
    for level in range(LEVELS):
        side = SIDE >> level
        folder = store / str(level)
        middle = side // 2
        across = max(1, side // CHUNK)
        centre = across // 2
        for row in range(max(0, centre - 1), min(across, centre + 2)):
            for column in range(max(0, centre - 1), min(across, centre + 2)):
                (folder / f"0.{middle}.{row}.{column}").write_bytes(one_tile())


def test_a_tile_written_into_an_open_store_appears(browser, built_dist, tmp_path):
    """The viewer is watching an empty store; a tile lands in it and is seen."""
    store = tmp_path / "overview_whole.ome.zarr"
    declare_the_whole_specimen(store)
    # Live, as during a run. That matters here: the browser is told to keep nothing, so
    # anything that failed to appear failed inside the drawing engine rather than in the
    # browser's own cache, which is the distinction this test exists to make.
    server = make_server(
        port=0, data_dir=tmp_path, site_dir=built_dist, store=store.name, live=True
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1000, "height": 800})
    try:
        page.goto(
            f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded"
        )
        page.wait_for_function("() => window.zmartViewer !== undefined", timeout=60_000)
        page.wait_for_timeout(3000)

        # The control. The panel really is empty to begin with, so the check below is
        # measuring an image arriving rather than one that was there all along.
        before = colour_spread(image_middle(page))
        assert before["distinct"] <= 2, (
            f"the store was meant to start empty, but something was drawn: {before}"
        )

        # The run's two steps: write the tile, then say so.
        write_the_middle_tiles(store)
        assert page.evaluate(ANNOUNCE_IN_PLACE) >= 1, (
            "the page was not listening when the run announced"
        )

        # And the tile appears. Without letting go of what the engine had decoded, this
        # never happens -- not slowly, but never, and without a single request being made.
        page.wait_for_function(
            """() => {
              const canvas = document.querySelector('canvas');
              return canvas !== null;
            }""",
            timeout=10_000,
        )
        appeared = False
        for _ in range(30):
            page.wait_for_timeout(500)
            spread = colour_spread(image_middle(page))
            if spread["distinct"] > 2 and spread["dominant_fraction"] < 0.99:
                appeared = True
                break
        assert appeared, (
            "a tile written into a store the viewer already had open never appeared; "
            "the engine is still answering from the emptiness it decided on earlier"
        )
        assert_something_was_drawn(page, "a tile written during the run")
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def write_position(folder, name, *, at):
    """One ordinary position, complete when it is written — the layout used today."""
    store = folder / f"{name}.ome.zarr"
    level = store / "0"
    level.mkdir(parents=True, exist_ok=True)
    (store / ".zgroup").write_text('{"zarr_format": 2}', encoding="utf-8")
    (level / ".zarray").write_text(
        json.dumps(
            {
                "zarr_format": 2,
                "shape": [1, 1, CHUNK, CHUNK],
                "chunks": [1, 1, CHUNK, CHUNK],
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
    (level / "0.0.0.0").write_bytes(one_tile())
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
                                            0.0,
                                            at * CHUNK * VOXEL_UM[2],
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
    return store


def test_a_position_arriving_still_keeps_the_image_already_fetched(
    browser, built_dist, tmp_path
):
    """The other half: letting go must stay confined to the case that needs it.

    In the layout used today a position arriving is a change the scene can see, so there
    is no need to throw anything away — and throwing it away would mean a run spending
    its life refetching image it already held, which gets worse the longer the run goes
    on. So this watches what is fetched while a neighbour arrives, and requires that
    nothing already in hand is asked for a second time.
    """
    write_position(tmp_path, "overview_pos001", at=0)
    server = make_server(
        port=0,
        data_dir=tmp_path,
        site_dir=built_dist,
        store="overview_pos001.ome.zarr",
        live=True,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1000, "height": 800})
    # Only pieces of image are counted, not the small files describing a store: a store
    # being read again is a different question, already settled elsewhere, and counting
    # both together would blur the two.
    pieces: list[str] = []
    page.on(
        "request",
        lambda request: pieces.append(request.url)
        if "/data/" in request.url
        and not request.url.endswith((".zarray", ".zattrs", ".zgroup"))
        else None,
    )
    try:
        page.goto(
            f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded"
        )
        page.wait_for_function("() => window.zmartViewer !== undefined", timeout=60_000)
        page.wait_for_timeout(3000)
        assert_something_was_drawn(page, "the first position")
        settled = len(pieces)
        assert settled, "no image was fetched at all, so this would prove nothing"

        write_position(tmp_path, "overview_pos002", at=1)
        assert page.evaluate(ANNOUNCE) >= 1
        page.wait_for_timeout(4000)

        repeats = [url for url in pieces[settled:] if url in pieces[:settled]]
        assert not repeats, (
            "a position arriving made the viewer throw away image it already had and "
            f"fetch it again: {repeats[:3]}"
        )
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)

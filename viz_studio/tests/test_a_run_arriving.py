"""A run arriving one position at a time, the way the control application drives it.

Every other browser test opens the viewer on data that is already there. This one
mimics an experiment in progress: the viewer is opened on a nearly empty folder, and
then positions are written and announced one by one, exactly as the application
running the microscope would do it — write the acquisition, then say so.

Two things are being checked, and the second matters more than the first.

The obvious one is that each position turns up. The important one is that the
positions already on screen are **not disturbed** when a new one arrives. A viewer
that redrew everything each time a tile landed would spend a long acquisition
throwing away image it had already fetched, and would lose whatever the operator had
marked. That failure is invisible in a screenshot and obvious in the numbers, so the
numbers are what this looks at.
"""

from __future__ import annotations

import json
import threading

import numpy as np
import pytest
import zarr
from server import make_server

CHANNELS, DEPTH, SIDE, CHUNK, LEVELS = 2, 4, 128, 64, 2


def write_position(folder, name, *, seed):
    """One position of an acquisition, complete and ready to be announced."""
    store = folder / f"{name}.ome.zarr"
    store.mkdir(parents=True, exist_ok=True)
    group = zarr.open_group(str(store), mode="w", zarr_format=2)
    datasets = []
    rng = np.random.default_rng(seed)
    for level in range(LEVELS):
        side = SIDE >> level
        array = group.create_array(
            str(level),
            shape=(CHANNELS, DEPTH, side, side),
            chunks=(1, 1, CHUNK, CHUNK),
            dtype="uint16",
            chunk_key_encoding={"name": "v2", "separator": "/"},
        )
        array[:] = (700 + rng.integers(0, 8000, size=(CHANNELS, DEPTH, side, side))).astype(
            np.uint16
        )
        datasets.append(
            {
                "path": str(level),
                "coordinateTransformations": [
                    {"type": "scale", "scale": [1.0, 2.0, 0.35 * 2**level, 0.35 * 2**level]}
                ],
            }
        )
    # Where this position sits on the stage: the same number the controller used to
    # move there. Positions are laid out in a row so each is somewhere of its own.
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
                        "coordinateTransformations": [
                            {"type": "translation",
                             "translation": [0.0, 0.0, 0.0, seed * SIDE * 0.35]}
                        ],
                    }
                ],
                "omero": {
                    "channels": [
                        {"label": f"ch{i}", "color": "FFFFFF",
                         "window": {"min": 0, "max": 65535, "start": 700, "end": 8700}}
                        for i in range(CHANNELS)
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    return store


ANNOUNCE = """async () => {
  const response = await fetch('/api/announce', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({reason: 'a position finished'}),
  });
  return (await response.json()).told;
}"""

ROWS = "() => (window.zmartConfig ? window.zmartConfig.layers.length : 0)"

# Put a private mark on every layer object currently on screen. If a layer is torn
# down and rebuilt, the replacement is a different object and carries no mark -- so
# counting the marks afterwards says exactly whether the layers survived. This is a
# stronger question than counting work done, and it needs nothing from the viewer.
MARK = """() => {
  const layers = window.zmartViewer.layerManager.managedLayers;
  layers.forEach((m) => { m.__survived = true; });
  return layers.length;
}"""
STILL_MARKED = """() => window.zmartViewer.layerManager.managedLayers
                     .filter((m) => m.__survived).length"""
SOURCES = """() => window.zmartViewer.layerManager.managedLayers
              .filter((m) => m.layer && m.layer.type === 'image')
              .reduce((n, m) => n + m.layer.dataSources.length, 0)"""


def test_a_run_arrives_one_position_at_a_time(browser, built_dist, tmp_path):
    """Three positions announced in turn, as an experiment would produce them."""
    write_position(tmp_path, "overview_pos001", seed=0)
    server = make_server(port=0, data_dir=tmp_path, site_dir=built_dist,
                         store="overview_pos001.ome.zarr")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1000, "height": 800})
    fetched: list[str] = []
    page.on(
        "request",
        lambda r: fetched.append(r.url)
        if "/data/" in r.url and "/.z" not in r.url
        else None,
    )
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined", timeout=60_000)
        page.wait_for_function(f"{ROWS} === {CHANNELS}", timeout=60_000)
        page.wait_for_timeout(1500)

        for position in (2, 3):
            already = page.evaluate(SOURCES)
            marked = page.evaluate(MARK)
            settled = len(fetched)

            # The controller's two steps: write the acquisition, then say so.
            write_position(tmp_path, f"overview_pos{position:03d}", seed=position)
            told = page.evaluate(ANNOUNCE)
            assert told >= 1, "the page was not listening when the run announced"

            # The row gains a source rather than the panel gaining a row: every
            # position of one acquisition type is one picture, so they share a layer.
            page.wait_for_function(
                f"{SOURCES} === {already + CHANNELS}", timeout=30_000
            )
            page.wait_for_timeout(1500)

            assert page.evaluate(ROWS) == CHANNELS, (
                "a new position must join the existing rows, not add rows of its own"
            )
            # Every layer that was on screen is still the same object. This is the
            # assertion worth having: a viewer that rebuilt on each arrival would
            # look right in a screenshot while quietly discarding everything it had
            # fetched and anything the operator had drawn.
            assert page.evaluate(STILL_MARKED) == marked, (
                "a position arriving destroyed layers that were already there"
            )
            # And nothing already fetched was fetched again.
            arriving = fetched[settled:]
            repeats = [url for url in arriving if url in fetched[:settled]]
            assert not repeats, f"pieces already in hand were fetched again: {repeats[:3]}"
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def grow_timelapse(store, frames):
    """Raise a store's length in time, the way a run does when a frame lands."""
    group = zarr.open_group(str(store), mode="a", zarr_format=2)
    for level in range(LEVELS):
        side = SIDE >> level
        array = group[str(level)]
        array.resize((frames, CHANNELS, DEPTH, side, side))
        array[frames - 1] = 5000
    return store


def write_timelapse(folder, name, *, frames):
    """A store with a time axis, holding as many frames as asked for."""
    store = folder / f"{name}.ome.zarr"
    store.mkdir(parents=True, exist_ok=True)
    group = zarr.open_group(str(store), mode="w", zarr_format=2)
    datasets = []
    for level in range(LEVELS):
        side = SIDE >> level
        group.create_array(
            str(level),
            shape=(frames, CHANNELS, DEPTH, side, side),
            chunks=(1, 1, 1, CHUNK, CHUNK),
            dtype="uint16",
            chunk_key_encoding={"name": "v2", "separator": "/"},
        )[:] = 3000
        datasets.append(
            {
                "path": str(level),
                "coordinateTransformations": [
                    {"type": "scale",
                     "scale": [30.0, 1.0, 2.0, 0.35 * 2**level, 0.35 * 2**level]}
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
                            {"name": "t", "type": "time", "unit": "second"},
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
                        {"label": f"ch{i}", "color": "FFFFFF",
                         "window": {"min": 0, "max": 65535, "start": 700, "end": 8700}}
                        for i in range(CHANNELS)
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    return store


TIME_REACH = """() => {
  const space = window.zmartViewer.navigationState.position.coordinateSpace.value;
  if (!space || !space.valid) return null;
  const at = space.names.indexOf('t');
  if (at < 0) return null;
  return Math.round(space.bounds.upperBounds[at]);
}"""


def test_a_timelapse_that_grows_is_noticed_without_being_added_twice(
    browser, built_dist, tmp_path
):
    """A frame lands, the run says so, and the viewer can reach the new frame.

    This is the one kind of change nothing about the scene reveals: the same store,
    the same channels, the same everything the panel can see — only the store's own
    account of how long it is has moved. So the engine has to be told to read that
    account again, and it must do so *without* treating the store as new. Adding it
    a second time would draw the specimen on top of itself; skipping it entirely
    would leave the slider unable to reach a frame that exists on disk.
    """
    store = write_timelapse(tmp_path, "overview_pos001", frames=2)
    server = make_server(port=0, data_dir=tmp_path, site_dir=built_dist,
                         store="overview_pos001.ome.zarr")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1000, "height": 800})
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined", timeout=60_000)
        page.wait_for_function(f"() => ({TIME_REACH})() === 2", timeout=60_000)
        page.wait_for_timeout(1000)
        sources_before = page.evaluate(SOURCES)
        marked = page.evaluate(MARK)

        grow_timelapse(store, 3)
        assert page.evaluate(ANNOUNCE) >= 1

        # The slider can now reach the frame that has just been written.
        page.wait_for_function(f"() => ({TIME_REACH})() === 3", timeout=30_000)
        # And the store was not opened a second time on top of itself.
        assert page.evaluate(SOURCES) == sources_before, (
            "a store that merely grew was added again instead of being re-read"
        )
        # The layers themselves were left alone, so nothing already fetched was lost.
        assert page.evaluate(STILL_MARKED) == marked, (
            "re-reading a store's description destroyed the layers"
        )
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def test_a_store_is_only_read_again_when_it_has_actually_grown(
    browser, built_dist, tmp_path
):
    """A neighbour arriving must not send us back to the stores already open.

    Re-reading a store is how a growing timelapse reaches the time slider, and it
    is worth doing — but an announcement only says that *something* on disk has
    changed, never what. A row can hold one store for every place the microscope
    visited, so treating every announcement as "everything may have grown" would
    mean four small requests per position per announcement, most of them asking a
    store whether it is still the length it was a second ago. That is the cost
    this guards against, and it is the same cost that makes opening a large folder
    slow. The frame count the server reports is what says whether the question is
    worth asking at all.

    The case is a second position arriving beside the first. Something has genuinely
    changed on disk, so the viewer does take the announcement seriously and does go
    and fetch the newcomer — but the position already open has not grown, and must
    be left alone. Only requests naming the first position are counted, so the
    newcomer's own perfectly proper fetches do not hide the fault.

    Then the first position really does grow, and two things are checked together:
    that it *is* read again, which is the positive control — without it this would
    pass just as happily against a viewer that had stopped re-reading anything at
    all — and that its neighbour, which did not grow, is still left alone. That
    second point is what keeps the cost of a frame landing the same whether the row
    holds two positions or two thousand.
    """
    store = write_timelapse(tmp_path, "overview_pos001", frames=2)
    server = make_server(port=0, data_dir=tmp_path, site_dir=built_dist,
                         store="overview_pos001.ome.zarr")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1000, "height": 800})
    # The small files a store keeps about itself -- how long it is, how big a voxel
    # is. These are what a re-read fetches, so counting the ones belonging to the
    # first position says whether it was read again, without having to ask the
    # viewer to confess to it.
    descriptions: list[str] = []
    # The same, for the position that arrives later and never grows. Counted apart
    # so the two questions -- "was the one that grew read again?" and "was its
    # neighbour left alone?" -- can be asked of the same moment.
    neighbour: list[str] = []

    def note(request):
        if not request.url.endswith((".zarray", ".zattrs")):
            return
        if "overview_pos001" in request.url:
            descriptions.append(request.url)
        elif "overview_pos002" in request.url:
            neighbour.append(request.url)

    page.on("request", note)
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined", timeout=60_000)
        page.wait_for_function(f"() => ({TIME_REACH})() === 2", timeout=60_000)
        page.wait_for_timeout(1500)

        # A second position lands. It has the same number of frames as the first, so
        # nothing about the first has grown -- but the scene has genuinely changed,
        # which is exactly when an over-eager re-read would happen.
        settled = len(descriptions)
        sources_before = page.evaluate(SOURCES)
        write_timelapse(tmp_path, "overview_pos002", frames=2)
        assert page.evaluate(ANNOUNCE) >= 1

        # Wait for the newcomer to actually be taken on, so the check below is made
        # after the pass that would have done the damage, not before it.
        page.wait_for_function(
            f"{SOURCES} === {sources_before + CHANNELS}", timeout=30_000
        )
        page.wait_for_timeout(2000)
        assert len(descriptions) == settled, (
            "a neighbour arriving sent us back to a position that had not changed: "
            f"{descriptions[settled:][:4]}"
        )

        # And now the first position really does grow, which must send us back to it
        # -- and to it alone.
        neighbour_settled = len(neighbour)
        grow_timelapse(store, 3)
        assert page.evaluate(ANNOUNCE) >= 1
        page.wait_for_function(f"() => ({TIME_REACH})() === 3", timeout=30_000)
        page.wait_for_timeout(2000)
        assert len(descriptions) > settled, (
            "a store that grew was never read again, so the guard is stuck shut"
        )
        # The neighbour shares the row and shares the row's frame count, so a viewer
        # deciding what to re-read from that count alone would go back to this store
        # too. It is the store that did not change, and it must not be touched: this
        # is what stops a frame landing costing more the more positions there are.
        assert len(neighbour) == neighbour_settled, (
            "one position growing sent us back to a neighbour that had not: "
            f"{neighbour[neighbour_settled:][:4]}"
        )
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)

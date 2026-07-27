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

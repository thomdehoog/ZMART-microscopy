"""Adding and removing images while the viewer is open, driven through the interface.

The library tests cover the rules; these cover the buttons — that pressing "open"
really adds an acquisition to the panel and puts its pixels on screen, that closing
takes it away again, and that a new acquisition appearing in the folder is noticed
on its own, which is what a smart-microscopy run does while you watch.
"""

from __future__ import annotations

import json
import threading

import numpy as np
import pytest
import zarr
from server import make_server


def _store(path, *, value=4000, channels=2):
    """A small multi-channel OME-Zarr, written quickly."""
    path.mkdir(parents=True)
    group = zarr.open_group(str(path), mode="w", zarr_format=2)
    data = np.full((channels, 4, 64, 64), value, dtype=np.uint16)
    group.create_array("0", shape=data.shape, chunks=(1, 1, 64, 64), dtype="uint16")[:] = data
    (path / ".zattrs").write_text(
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
                                    {"type": "scale", "scale": [1.0, 2.0, 0.35, 0.35]}
                                ],
                            }
                        ],
                    }
                ],
                "omero": {
                    "channels": [
                        {"label": f"ch{i}", "color": "00FF66",
                         "window": {"min": 0, "max": 65535, "start": 0, "end": 8000}}
                        for i in range(channels)
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def live(browser, built_dist, tmp_path):
    """A viewer open on one run, with a second run sitting on disk unopened."""
    first = tmp_path / "run_a"
    second = tmp_path / "run_b"
    first.mkdir()
    second.mkdir()
    _store(first / "overview_pos001.ome.zarr")
    _store(second / "targetscan_cell007.ome.zarr")

    server = make_server(
        port=0,
        data_dir=first,
        site_dir=built_dist,
        store="overview_pos001.ome.zarr",
        # Stand in for the desktop window's folder chooser, so the button can be
        # pressed here exactly as an operator would press it.
        browse=lambda: str(second),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1300, "height": 1000})
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartConfig !== undefined", timeout=30_000)
        yield page, first, second
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def _groups(page):
    return page.evaluate("() => window.zmartConfig.groups")


def test_the_viewer_starts_on_the_run_it_was_given(live):
    page, _, _ = live
    assert _groups(page) == ["overview"]


def test_opening_adds_an_acquisition_and_its_channels(live):
    page, _, _ = live
    page.get_by_label("open images").click()
    page.wait_for_function(
        "() => window.zmartConfig.groups.includes('targetscan')", timeout=20_000
    )
    assert _groups(page) == ["overview", "targetscan"]
    # Both channels of the newly opened store became rows.
    added = page.evaluate(
        "() => window.zmartConfig.layers.filter((l) => l.group === 'targetscan').length"
    )
    assert added == 2
    assert page.get_by_label("toggle group targetscan").is_visible()


def test_the_newly_opened_images_actually_render(live):
    """Opening has to grant permission to read the files, not just list them."""
    page, _, _ = live
    page.get_by_label("open images").click()
    page.wait_for_function(
        "() => window.zmartConfig.groups.includes('targetscan')", timeout=20_000
    )
    page.wait_for_function(
        """() => {
          const v = window.zmartViewer;
          const added = v.layerManager.managedLayers.filter((m) =>
            m.name.startsWith('targetscan'));
          if (!added.length) return false;
          let needed = 0, available = 0;
          for (const m of added) {
            for (const rl of (m.layer?.renderLayers) || []) {
              const p = rl.layerChunkProgressInfo;
              if (p) { needed += p.numVisibleChunksNeeded;
                       available += p.numVisibleChunksAvailable; }
            }
          }
          return available > 0 && available >= needed;
        }""",
        timeout=60_000,
    )


def test_closing_removes_it_again(live):
    page, _, _ = live
    page.get_by_label("open images").click()
    page.wait_for_function(
        "() => window.zmartConfig.groups.includes('targetscan')", timeout=20_000
    )
    page.get_by_label("close targetscan").click()
    page.wait_for_function(
        "() => !window.zmartConfig.groups.includes('targetscan')", timeout=20_000
    )
    assert _groups(page) == ["overview"]
    # And the engine is no longer drawing it.
    assert page.evaluate(
        """() => window.zmartViewer.layerManager.managedLayers
             .every((m) => !m.name.startsWith('targetscan'))"""
    )


def test_settings_on_what_stays_open_are_not_reset(live):
    """Opening a second run must not quietly undo the operator's own adjustments."""
    page, _, _ = live
    # Hide the first channel of the run already open.
    page.get_by_label("toggle ch0").first.click()
    page.wait_for_timeout(500)
    page.get_by_label("open images").click()
    page.wait_for_function(
        "() => window.zmartConfig.groups.includes('targetscan')", timeout=20_000
    )
    page.wait_for_timeout(800)
    hidden = page.evaluate(
        """() => window.zmartViewer.layerManager.managedLayers
             .filter((m) => m.name.startsWith('overview') && m.visible === false).length"""
    )
    assert hidden == 1, "the channel hidden before opening should still be hidden"


def test_an_acquisition_appearing_on_disk_is_noticed_on_its_own(live):
    """A run writes as it goes, so the viewer must look again without being asked."""
    page, first, _ = live
    _store(first / "prescan_pos001.ome.zarr", value=2500)
    page.wait_for_function(
        "() => window.zmartConfig.groups.includes('prescan')", timeout=30_000
    )
    assert "prescan" in _groups(page)


def test_the_load_data_box_can_be_switched_off(browser, built_dist, demo_store):
    """A workflow-driven viewer offers no way to add images by hand.

    During an experiment the workflow decides what is worth looking at, so a
    button inviting someone to add an image the experiment knows nothing about
    should not be on screen. Switching it off must hide it — and must *not* close
    the door on the workflow itself, which puts images on screen through the same
    server from outside the page.
    """
    import threading

    from server import make_server

    server = make_server(port=0, data_dir=demo_store, site_dir=built_dist, allow_open=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page()
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartConfig !== undefined", timeout=30_000)
        assert page.get_by_label("open images").count() == 0
        assert page.get_by_text("load data").count() == 0
        # The way in from outside the page is still there: this is what a
        # smart-microscopy workflow uses to say what should be shown.
        answer = page.evaluate(
            """async (folder) => {
                 const r = await fetch('/api/stores/open', {
                   method: 'POST',
                   headers: {'Content-Type': 'application/json'},
                   body: JSON.stringify({path: folder}),
                 });
                 return {ok: r.ok, layers: (await r.json()).layers?.length ?? 0};
               }""",
            str(demo_store),
        )
        assert answer["ok"], "a workflow must still be able to open images"
        assert answer["layers"] > 0
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def test_the_selection_list_is_absent_unless_asked_for(browser, built_dist, demo_store):
    """Marking places is not what most viewing is, so it is opt-in.

    Someone opening the viewer to look through yesterday's run wants the image and
    nothing else beside it. A workflow that cares about targets switches the
    selection list on when it starts the viewer.
    """
    import threading

    from server import make_server

    server = make_server(port=0, data_dir=demo_store, site_dir=built_dist)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page()
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartConfig !== undefined", timeout=30_000)
        assert page.get_by_label("selection panel").count() == 0
        assert page.get_by_role("button", name="Point", exact=True).count() == 0
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def test_the_bar_of_controls_can_be_put_on_the_left(browser, built_dist, demo_store):
    """Which edge the controls sit on is decided when the viewer is started.

    At a microscope the screen is often beside the instrument and one edge is
    easier to reach than the other, so this is worth being able to choose.
    """
    import threading

    from server import make_server

    server = make_server(
        port=0, data_dir=demo_store, site_dir=built_dist, panel_side="left"
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1200, "height": 900})
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartConfig !== undefined", timeout=30_000)
        page.wait_for_timeout(600)
        bar = page.get_by_label("controls", exact=True).bounding_box()
        image = page.locator("main").bounding_box()
        assert bar["x"] < image["x"], "the controls should be to the left of the image"
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def test_the_controls_fold_away(browser, built_dist, demo_store):
    """The bar folds to the edge, so the whole screen can show the specimen."""
    import threading

    from server import make_server

    server = make_server(port=0, data_dir=demo_store, site_dir=built_dist)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1200, "height": 900})
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartConfig !== undefined", timeout=30_000)
        assert page.get_by_label("controls", exact=True).count() == 1
        page.get_by_label("hide the controls").click()
        page.wait_for_timeout(400)
        assert page.get_by_label("controls", exact=True).count() == 0
        page.get_by_label("show the controls").click()
        page.wait_for_timeout(400)
        assert page.get_by_label("controls", exact=True).count() == 1
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def test_static_data_is_not_polled(browser, built_dist, demo_store):
    """A viewer on finished data stops asking whether anything has changed.

    Nothing about a run that has ended can change, so every question about it is
    wasted — and on a folder of several hundred acquisitions that asking is the
    largest thing the server does. The first question is still asked, because until
    something has been loaded there is a viewer with nothing in it.
    """
    import threading

    from server import make_server

    server = make_server(port=0, data_dir=demo_store, site_dir=built_dist, live=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page()
    asked = []
    page.on("request", lambda r: asked.append(r.url) if "/api/revision" in r.url else None)
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartConfig !== undefined", timeout=30_000)
        page.wait_for_timeout(3000)
        # Live mode would have asked four or five times over three seconds.
        assert len(asked) <= 1, f"a static viewer kept asking: {len(asked)} times"
        # And it is genuinely showing the data, not merely quiet.
        assert page.evaluate("() => window.zmartConfig.layers.length") == 3
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def test_live_data_is_polled(browser, built_dist, demo_store):
    """The counterpart: while a run is producing data, the viewer keeps looking."""
    import threading

    from server import make_server

    server = make_server(port=0, data_dir=demo_store, site_dir=built_dist)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page()
    asked = []
    page.on("request", lambda r: asked.append(r.url) if "/api/revision" in r.url else None)
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartConfig !== undefined", timeout=30_000)
        page.wait_for_timeout(3000)
        assert len(asked) >= 3, f"a live viewer stopped looking: {len(asked)} times"
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)

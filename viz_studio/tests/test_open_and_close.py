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
from pixels import fraction_lit
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
    # One load is one dataset, and it is named after what was loaded — so a folder
    # holds one acquisition and is called after it. That is what the panel shows.
    first = tmp_path / "overview"
    second = tmp_path / "targetscan"
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
    """Opening has to grant permission to read the files, not just list them.

    The name of this test promises a picture, so a picture is what it looks at.
    Asking the engine how many pieces of image it holds would not do, because that
    number can be perfectly healthy while the panel shows nothing — which is the
    fault this whole suite exists to catch. The engine is still asked, but only to
    know *when* to take the photograph; the photograph is what decides.

    There is one more thing to be careful about, and it is why the run that was
    already open gets hidden part-way through. The viewer is showing two
    acquisitions by then, both drawn in the same place, so a lit panel on its own
    would be satisfied by the overview alone and would say nothing whatever about
    what was just opened. With the overview hidden, any light left in the middle of
    the picture can only be coming from the newly opened images.
    """
    page, _, _ = live
    page.get_by_label("open images").click()
    page.wait_for_function(
        "() => window.zmartConfig.groups.includes('targetscan')", timeout=20_000
    )
    # The precondition: everything the newly opened images need has been fetched
    # and decoded, so there is nothing left to wait for and the panel can be
    # photographed. This says when to look, not what will be there.
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

    # Now put the run that was already open out of the picture, so that whatever
    # is left on screen was drawn from the files the "open" button just granted
    # access to.
    page.get_by_label("toggle group overview").click()
    page.wait_for_timeout(2000)
    lit = fraction_lit(page)
    assert lit > 0.01, (
        "the newly opened images reached the engine but nothing of them was drawn: "
        f"only {lit:.1%} of the middle of the picture is showing anything. Opening "
        "listed the files without really granting access to them, or they were "
        "drawn somewhere nobody can see"
    )

    # And the control, which is what stops the line above quietly becoming an
    # assertion that cannot fail. These stores are an even fill, so "is the panel
    # blank?" cannot be asked by looking for variety in it — a panel covered edge
    # to edge by an even tile is just as flat as an empty one. What is measured
    # instead is how much of the middle is brighter than the background, and this
    # is the proof that the measurement responds: with the new images hidden as
    # well, there is nothing left to draw and the panel goes dark.
    page.get_by_label("toggle group targetscan").click()
    page.wait_for_timeout(2000)
    empty = fraction_lit(page)
    assert empty < lit / 2, (
        "hiding both acquisitions left the picture as bright as before, so the "
        f"measurement is not reading the image at all: {lit:.1%} -> {empty:.1%}"
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
    # It joins the dataset whose folder it appeared in, so what is watched for is
    # the store reaching the page rather than a heading named after its filename.
    page.wait_for_function(
        """() => window.zmartConfig.layers.some(
             (row) => row.sources.some((s) => s.includes('prescan_pos001')))""",
        timeout=30_000,
    )
    assert _groups(page) == ["overview"]


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


def test_finished_data_opens_no_listening_connection(browser, built_dist, demo_store):
    """A viewer on finished data does not wait to be told about changes.

    Nothing about a run that has ended can change, so there is nothing to be told
    and no reason to hold a connection open waiting for it. The data is still
    fetched once, because until something has been loaded there is a viewer with
    nothing in it.

    This test used to collect every request to the listening address into a list
    and then never look at it. A viewer holding a connection open for ever on
    finished data passed, which is precisely the thing it is named after. The
    server is asked as well as the browser, because the two can disagree — a page
    that has gone away is only discovered when something is next written to it, so
    the count the server keeps is the one an announcement would actually reach.
    """
    import threading

    from server import make_server

    server = make_server(port=0, data_dir=demo_store, site_dir=built_dist, live=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page()
    started: list[str] = []
    settled: list[str] = []
    page.on("request", lambda r: started.append(r.url) if "/api/events" in r.url else None)
    page.on(
        "requestfinished", lambda r: settled.append(r.url) if "/api/events" in r.url else None
    )
    page.on(
        "requestfailed", lambda r: settled.append(r.url) if "/api/events" in r.url else None
    )
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartConfig !== undefined", timeout=30_000)
        page.wait_for_timeout(3000)
        # It may open one before the first answer says the data is finished; what
        # it must not do is keep one. A held connection is a request that never
        # comes back, so what says it was let go is that every one that started
        # has since finished.
        assert len(started) - len(settled) == 0, (
            f"{len(started) - len(settled)} listening connection(s) still open on "
            "finished data — the viewer is waiting to be told about changes that "
            "cannot happen"
        )
        # And the server comes to agree that nobody is listening.
        #
        # Asked more than once on purpose. A page that has gone away is only
        # discovered when something is next written to it — that is how the
        # connection breaks — so the first announcement after the page let go is
        # what clears the listener rather than what reports on it. A viewer that
        # really were holding the connection open would answer 1 every time and
        # this would still fail, which is the point.
        announce = """async () => {
             const r = await fetch('/api/announce', {method: 'POST'});
             return (await r.json()).told;
           }"""
        told = page.evaluate(announce)
        for _ in range(10):
            if told == 0:
                break
            page.wait_for_timeout(200)
            told = page.evaluate(announce)
        assert told == 0, (
            f"the server still thought {told} page(s) were listening after "
            "repeated announcements, so a connection is genuinely being held open "
            "on data that cannot change"
        )
        assert page.evaluate("() => window.zmartConfig.live") is False
        # And it is genuinely showing the data, not merely quiet.
        assert page.evaluate("() => window.zmartConfig.layers.length") == 3
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def test_a_live_viewer_waits_to_be_told(browser, built_dist, demo_store):
    """The counterpart: while a run is producing data, the viewer listens.

    One connection, opened once and then held. The old arrangement asked a
    question four or five times over these same three seconds; the point of this
    test is that there is now exactly one request and it never comes back.
    """
    import threading

    from server import make_server

    server = make_server(port=0, data_dir=demo_store, site_dir=built_dist)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page()
    asked = []
    page.on("request", lambda r: asked.append(r.url) if "/api/events" in r.url else None)
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartConfig !== undefined", timeout=30_000)
        page.wait_for_timeout(3000)
        assert len(asked) == 1, f"expected one held connection, saw {len(asked)}"
        # The server agrees that someone is listening -- which is what makes an
        # announcement reach anybody.
        told = page.evaluate(
            """async () => {
                 const r = await fetch('/api/announce', {method: 'POST'});
                 return (await r.json()).told;
               }"""
        )
        assert told == 1, f"the server thought {told} pages were listening"
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture
def no_chooser(browser, built_dist, tmp_path):
    """A viewer with no native folder chooser, as a plain web browser has.

    The desktop window can open the operating system's own chooser; a page
    served to an ordinary browser cannot, and used to fall back to a bare
    prompt asking for a path typed blind. The in-page load window replaces
    that: it lists the server's folders so the operator can walk to the run
    and open it by clicking.
    """
    first = tmp_path / "overview"
    second = tmp_path / "targetscan"
    first.mkdir()
    second.mkdir()
    _store(first / "overview_pos001.ome.zarr")
    _store(second / "targetscan_cell007.ome.zarr")
    server = make_server(
        port=0,
        data_dir=first,
        site_dir=built_dist,
        store="overview_pos001.ome.zarr",
        # No browse callable: exactly the situation in a plain browser.
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


class TestTheLoadWindow:
    """Without a native chooser, choosing a folder opens a window in the page."""

    def test_the_window_asks_what_kind_of_thing_first(self, no_chooser):
        """Step one is the choice: raw data, or a view constructed earlier.

        Only after the choice does the folder walk appear, offering Open on
        the kind of thing that was asked for -- raw mode on folders of
        positions, view mode on stores. The walk starts where the server is
        looking.
        """
        page, first, second = no_chooser
        page.get_by_label("open images").click()
        window = page.get_by_role("dialog", name="load data")
        window.wait_for(timeout=10_000)
        # No folders yet: the choice comes first.
        assert page.get_by_label("folder path").count() == 0
        page.get_by_label("build new view", exact=True).click()
        assert str(first) in page.get_by_label("folder path").input_value()
        # The starting folder holds a store; raw mode offers no Open on it.
        assert page.get_by_label(
            "open overview_pos001.ome.zarr", exact=True).count() == 0

    def test_raw_data_is_opened_by_constructing_a_viewer(self, no_chooser):
        """A folder of positions is raw data: a viewer is constructed over it.

        One composed picture draws far faster than many stores handed to the
        engine separately, so raw data always goes through construction. The
        operator says where the viewer's files live and whether the pieces
        are prebaked now or made on the fly when looked at; on the fly is
        the default, writes only the declaration, and serves immediately.
        """
        page, first, second = no_chooser
        page.get_by_label("open images").click()
        page.get_by_role("dialog", name="load data").wait_for(timeout=10_000)
        page.get_by_label("build new view", exact=True).click()
        page.get_by_label("parent folder").click()
        page.get_by_label("open targetscan", exact=True).wait_for(timeout=10_000)
        page.get_by_label("open targetscan", exact=True).click()
        # The construction pane, with the destination already suggested.
        destination = page.get_by_label("viewer files folder")
        destination.wait_for(timeout=10_000)
        assert destination.input_value().endswith("targetscan/views")
        page.get_by_label("start constructing").click()
        page.wait_for_function(
            "() => window.zmartConfig.groups.includes('targetscan')", timeout=30_000
        )
        assert page.get_by_role("dialog", name="load data").count() == 0, (
            "a successful open is finished; the window should close itself"
        )
        assert (second / "views" / "targetscan.ome.zarr" / "zarr.json").exists(), (
            "the viewer's files must be where the operator was told they go"
        )

    def test_prebaking_computes_the_pieces_and_reports_its_progress(
        self, browser, built_dist, tmp_path
    ):
        """The prebake choice computes every piece now, into real files.

        The window polls the construction's progress while it runs; when it
        is done the picture's baked ground sits on disk and the acquisition
        is open. Single-channel data here: the per-frame bake of grown
        pictures is its own ordered chapter, and a grown folder is refused
        with a plain answer instead (the refusal has its own words in
        declare._bake_the_coarse_ground).
        """
        first = tmp_path / "overview"
        run = tmp_path / "surveyrun"
        first.mkdir()
        run.mkdir()
        _store(first / "overview_pos001.ome.zarr", channels=1)
        _store(run / "surveyrun_pos001.ome.zarr", channels=1)
        server = make_server(port=0, data_dir=first, site_dir=built_dist,
                             store="overview_pos001.ome.zarr")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        page = browser.new_page(viewport={"width": 1300, "height": 1000})
        try:
            page.goto(f"http://127.0.0.1:{server.server_address[1]}",
                      wait_until="domcontentloaded")
            page.wait_for_function("() => window.zmartConfig !== undefined",
                                   timeout=30_000)
            page.get_by_label("open images").click()
            page.get_by_role("dialog", name="load data").wait_for(timeout=10_000)
            page.get_by_label("build new view", exact=True).click()
            page.get_by_label("parent folder").click()
            page.get_by_label("open surveyrun", exact=True).wait_for(timeout=10_000)
            page.get_by_label("open surveyrun", exact=True).click()
            page.get_by_label("viewer files folder").wait_for(timeout=10_000)
            page.get_by_label("prebake the pieces").check()
            page.get_by_label("start constructing").click()
            page.wait_for_function(
                "() => window.zmartConfig.groups.includes('surveyrun')",
                timeout=30_000,
            )
            store = run / "views" / "surveyrun.ome.zarr"
            assert (store / "zarr.json").exists()
            assert any(any((store / str(level)).glob("**/*"))
                       for level in range(4) if (store / str(level)).is_dir()), (
                "a prebaked picture keeps its pieces as real files"
            )
        finally:
            page.close()
            server.shutdown()
            thread.join(timeout=5)

    def test_a_typed_path_navigates(self, no_chooser):
        page, first, second = no_chooser
        page.get_by_label("open images").click()
        page.get_by_role("dialog", name="load data").wait_for(timeout=10_000)
        page.get_by_label("build new view", exact=True).click()
        box = page.get_by_label("folder path")
        box.fill(str(second.parent))
        box.press("Enter")
        # exact=True throughout: the starting folder already offers
        # "open overview_pos001.ome.zarr", which a substring match would
        # accept before the navigation has happened at all.
        page.get_by_label("open overview", exact=True).wait_for(timeout=10_000)
        assert page.get_by_label("open targetscan", exact=True).count() == 1

    def test_custom_opens_anything_directly(self, no_chooser):
        """The third door: no construction, no questions, just open it.

        Custom is for everything the two disciplined doors do not cover --
        demo data, the viewer's own test runs (the spiral among them),
        whatever the library accepts. It opens folders and stores directly,
        the way a workflow's API call does.
        """
        page, first, second = no_chooser
        page.get_by_label("open images").click()
        page.get_by_role("dialog", name="load data").wait_for(timeout=10_000)
        page.get_by_label("other", exact=True).click()
        page.get_by_label("parent folder").click()
        page.get_by_label("open targetscan", exact=True).wait_for(timeout=10_000)
        page.get_by_label("open targetscan", exact=True).click()
        page.wait_for_function(
            "() => window.zmartConfig.groups.includes('targetscan')", timeout=20_000
        )
        assert page.get_by_role("dialog", name="load data").count() == 0

    def test_cancel_closes_the_window_and_opens_nothing(self, no_chooser):
        page, first, second = no_chooser
        page.get_by_label("open images").click()
        page.get_by_role("dialog", name="load data").wait_for(timeout=10_000)
        page.get_by_label("cancel loading").click()
        page.wait_for_timeout(300)
        assert page.get_by_role("dialog", name="load data").count() == 0
        assert _groups(page) == ["overview"]

    def test_the_listing_is_not_served_when_opening_is_off(
        self, browser, built_dist, tmp_path
    ):
        """The window walks the server's folders, so it obeys the same gate.

        A run-mode server (allow_open off) offers no way to open data by hand;
        the listing endpoint has to be off with it, or the panel's missing
        button would be decoration over an API anyone could still call.
        """
        _store(tmp_path / "overview_pos001.ome.zarr")
        server = make_server(
            port=0, data_dir=tmp_path, site_dir=built_dist,
            store="overview_pos001.ome.zarr", allow_open=False,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        page = browser.new_page()
        try:
            page.goto(f"http://127.0.0.1:{server.server_address[1]}",
                      wait_until="domcontentloaded")
            page.wait_for_function("() => window.zmartConfig !== undefined", timeout=30_000)
            status = page.evaluate(
                """() => fetch('/api/stores/list', {
                  method: 'POST',
                  headers: {'Content-Type': 'application/json'},
                  body: JSON.stringify({}),
                }).then((r) => r.status)"""
            )
            assert status in (403, 404), (
                f"the folder listing answered {status} on a server that "
                "does not allow opening"
            )
        finally:
            page.close()
            server.shutdown()
            thread.join(timeout=5)


class TestRelinking:
    """A viewer whose raw data has moved asks to be pointed at it again."""

    def _a_viewer_with_moved_data(self, tmp_path):
        """Construct a viewer over a run, then move the run away."""
        import shutil

        run = tmp_path / "surveyrun"
        run.mkdir()
        _store(run / "surveyrun_pos001.ome.zarr", channels=1)
        import importlib
        declare = importlib.import_module("declare")
        store = declare.declare_a_built_picture(
            run / "views", run, name="surveyrun")
        shutil.move(str(run / "surveyrun_pos001.ome.zarr"),
                    str(tmp_path / "elsewhere.ome.zarr"))
        moved_to = tmp_path / "moved"
        moved_to.mkdir()
        shutil.move(str(tmp_path / "elsewhere.ome.zarr"),
                    str(moved_to / "surveyrun_pos001.ome.zarr"))
        return run, store, moved_to

    def test_opening_it_answers_with_a_relink_ask(
        self, browser, built_dist, tmp_path, demo_store
    ):
        """The miss is caught at open, with a plain answer naming the miss.

        Without this the open succeeds and every piece fails later, one
        request at a time, with nothing on screen saying why -- the picture
        simply stays black. Refusing at the door, with where the data WAS,
        is what lets the window prompt for where it is now.
        """
        run, store, moved_to = self._a_viewer_with_moved_data(tmp_path)
        server = make_server(port=0, data_dir=tmp_path, site_dir=built_dist,
                             store=[], loads=[{"path": str(demo_store)}])
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        page = browser.new_page()
        try:
            page.goto(f"http://127.0.0.1:{server.server_address[1]}",
                      wait_until="domcontentloaded")
            page.wait_for_function("() => window.zmartConfig !== undefined",
                                   timeout=30_000)
            answer = page.evaluate(
                """async (path) => {
                     const r = await fetch('/api/stores/open', {
                       method: 'POST',
                       headers: {'Content-Type': 'application/json'},
                       body: JSON.stringify({path}),
                     });
                     return {status: r.status, body: await r.json()};
                   }""",
                str(store),
            )
            assert answer["status"] == 409, answer
            assert answer["body"]["relink"]["was"].endswith("surveyrun"), (
                "the answer must say where the data was, so the window can "
                "ask where it is now"
            )
        finally:
            page.close()
            server.shutdown()
            thread.join(timeout=5)

    def test_the_window_prompts_for_the_data_and_relinks(
        self, browser, built_dist, tmp_path, demo_store
    ):
        run, store, moved_to = self._a_viewer_with_moved_data(tmp_path)
        server = make_server(port=0, data_dir=tmp_path, site_dir=built_dist,
                             store=[], loads=[{"path": str(demo_store)}])
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        page = browser.new_page(viewport={"width": 1300, "height": 1000})
        try:
            page.goto(f"http://127.0.0.1:{server.server_address[1]}",
                      wait_until="domcontentloaded")
            page.wait_for_function("() => window.zmartConfig !== undefined",
                                   timeout=30_000)
            page.get_by_label("open images").click()
            page.get_by_role("dialog", name="load data").wait_for(timeout=10_000)
            page.get_by_label("load existing view", exact=True).click()
            # Walk to the viewer's files and open them.
            box = page.get_by_label("folder path")
            box.fill(str(run / "views"))
            box.press("Enter")
            page.get_by_label("open surveyrun.ome.zarr", exact=True).wait_for(
                timeout=10_000)
            page.get_by_label("open surveyrun.ome.zarr", exact=True).click()
            # The window asks for the data instead of failing black.
            data_box = page.get_by_label("raw data folder")
            data_box.wait_for(timeout=10_000)
            data_box.fill(str(moved_to))
            page.get_by_label("start constructing").click()
            page.wait_for_function(
                "() => window.zmartConfig.groups.includes('surveyrun')",
                timeout=30_000,
            )
        finally:
            page.close()
            server.shutdown()
            thread.join(timeout=5)

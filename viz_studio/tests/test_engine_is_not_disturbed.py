"""Making sure the interface never makes the engine redo work it need not.

The engine underneath this viewer already handles enormous images: it fetches only
the pieces the current view needs and keeps what it has fetched. That is the whole
reason it was chosen. The danger is not the engine — it is **us**, above it.

Every control in the panel works by handing the engine a fresh description of what
to show. If the engine took that as "start again", then on a four-hundred-gigabyte
acquisition every nudge of a contrast slider would throw away everything loaded and
fetch it all back. The image would stutter, the disk would thrash, and the cause
would look like the engine rather than like us.

So these tests count the pieces of image actually asked for over the network, do
something in the interface, and count again. The number that matters is almost
always **zero**: changing how something is drawn must not change what is fetched.
Where a number is not zero it is stated why.

If one of these starts failing, the interface has begun fighting the engine, and
that is worth knowing long before anyone points it at real data.
"""

from __future__ import annotations

import json
import threading
import time

import numpy as np
import pytest
import zarr
from server import make_server

CHANNELS, DEPTH, SIDE, CHUNK, LEVELS = 2, 16, 1024, 256, 3


def _store(path, *, seed=0, channels=CHANNELS, side=SIDE):
    """A small but genuinely multi-resolution OME-Zarr, with pieces filed in folders.

    ``side`` is how wide the largest copy is. The default is big enough that the
    engine has to choose between resolution levels and fetch several pieces, which
    is what most of these tests are about. A test that is about *how many*
    acquisitions are open rather than how large they are should pass a small side:
    sixty full-size stores is two gigabytes of synthetic data and most of a minute
    spent writing it, for a question the size has no bearing on.
    """
    path.mkdir(parents=True, exist_ok=True)
    group = zarr.open_group(str(path), mode="w", zarr_format=2)
    datasets = []
    for level in range(LEVELS):
        wide = side >> level
        array = group.create_array(
            str(level),
            shape=(channels, DEPTH, wide, wide),
            chunks=(1, 1, CHUNK, CHUNK),
            dtype="uint16",
            chunk_key_encoding={"name": "v2", "separator": "/"},
        )
        rng = np.random.default_rng(seed + level)
        array[:] = (800 + rng.integers(0, 9000, size=(channels, DEPTH, wide, wide))).astype(
            np.uint16
        )
        datasets.append(
            {
                "path": str(level),
                "coordinateTransformations": [
                    {"type": "scale", "scale": [1.0, 2.0, 0.35 * (2**level), 0.35 * (2**level)]}
                ],
            }
        )
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
                        "datasets": datasets,
                    }
                ],
                "omero": {
                    "channels": [
                        {"label": f"ch{i}", "color": "FFFFFF",
                         "window": {"min": 0, "max": 65535, "start": 800, "end": 9800}}
                        for i in range(channels)
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    return path


class Watcher:
    """Counts the pieces of image asked for over the network."""

    def __init__(self, page):
        self.urls: list[str] = []
        page.on("request", self._note)

    def _note(self, request):
        url = request.url
        # Only pieces of image; the small files describing a store are not what
        # this is about, and the browser is told it may keep those anyway.
        if "/data/" in url and "/.z" not in url:
            self.urls.append(url)

    def since(self, mark: int) -> int:
        return len(self.urls) - mark

    def repeats(self) -> set[str]:
        """Pieces that were asked for more than once — that is, fetched again.

        Once a piece of image has been fetched the engine holds on to it, so
        asking for the same one twice means it was let go of and had to be
        collected again. On a large acquisition that is the difference between
        exploring comfortably and waiting on the disk at every move.
        """
        seen: set[str] = set()
        twice: set[str] = set()
        for url in self.urls:
            (twice if url in seen else seen).add(url)
        return twice

    @property
    def mark(self) -> int:
        return len(self.urls)


@pytest.fixture
def quiet_page(browser, built_dist, tmp_path):
    """The viewer, settled: everything the first view needs has been fetched."""
    _store(tmp_path / "overview_pos001.ome.zarr")
    server = make_server(
        port=0, data_dir=tmp_path, site_dir=built_dist, store="overview_pos001.ome.zarr"
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1100, "height": 800})
    watcher = Watcher(page)
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined", timeout=60_000)
        page.wait_for_function(_SETTLED, timeout=90_000)
        page.wait_for_timeout(2500)
        yield page, watcher, tmp_path
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


_SETTLED = """() => {
  let needed = 0, available = 0;
  for (const m of window.zmartViewer.layerManager.managedLayers)
    for (const rl of (m.layer?.renderLayers) || []) {
      const p = rl.layerChunkProgressInfo;
      if (p) { needed += p.numVisibleChunksNeeded; available += p.numVisibleChunksAvailable; }
    }
  return available > 0 && available >= needed;
}"""


def _set(page, label, value):
    """Move a slider the way a browser does, so the interface's handler runs."""
    page.evaluate(
        """([selector, value]) => {
          const el = document.querySelector(selector);
          const setter = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype, 'value').set;
          setter.call(el, String(value));
          el.dispatchEvent(new Event('input', { bubbles: true }));
          el.dispatchEvent(new Event('change', { bubbles: true }));
        }""",
        [f"[aria-label='{label}']", value],
    )


class TestChangingHowSomethingLooks:
    """Changing the *appearance* must never change what is fetched.

    All of this is decided on the graphics card from pixels already in memory, so
    the honest answer to every one of these is zero.
    """

    @pytest.mark.parametrize(
        ("what", "label", "value"),
        [
            ("the black point", "black ch0", 1500),
            ("the white point", "white ch0", 8000),
            ("a channel's opacity", "opacity ch0", 0.55),
            ("the whole acquisition's opacity", "opacity group overview", 0.7),
        ],
    )
    def test_moving_a_slider_fetches_nothing(self, quiet_page, what, label, value):
        page, watcher, _ = quiet_page
        mark = watcher.mark
        _set(page, label, value)
        page.wait_for_timeout(2500)
        assert watcher.since(mark) == 0, f"changing {what} refetched image data"

    def test_choosing_a_colour_map_fetches_nothing(self, quiet_page):
        """A colour map is a shader; the pixels behind it do not change."""
        page, watcher, _ = quiet_page
        mark = watcher.mark
        page.get_by_label("colour map ch0").select_option("viridis")
        page.wait_for_timeout(2500)
        assert watcher.since(mark) == 0

    def test_hiding_and_showing_a_channel_fetches_nothing(self, quiet_page):
        """Hiding must not discard what was loaded, or showing again would crawl."""
        page, watcher, _ = quiet_page
        mark = watcher.mark
        page.click("[aria-label='toggle ch1']")
        page.wait_for_timeout(1500)
        page.click("[aria-label='toggle ch1']")
        page.wait_for_timeout(2500)
        assert watcher.since(mark) == 0

    def test_hiding_a_whole_acquisition_fetches_nothing(self, quiet_page):
        page, watcher, _ = quiet_page
        mark = watcher.mark
        page.click("[aria-label='toggle group overview']")
        page.wait_for_timeout(1500)
        page.click("[aria-label='toggle group overview']")
        page.wait_for_timeout(2500)
        assert watcher.since(mark) == 0

    def test_collapsing_the_panel_fetches_nothing(self, quiet_page):
        """Tidying the list is not a statement about the image."""
        page, watcher, _ = quiet_page
        mark = watcher.mark
        page.get_by_label("collapse overview").click()
        page.wait_for_timeout(1500)
        page.get_by_label("expand overview").click()
        page.wait_for_timeout(2000)
        assert watcher.since(mark) == 0


class TestTheInterfaceMindingItsOwnBusiness:
    """Things the interface does on its own must not disturb the engine."""

    def test_sitting_still_fetches_nothing(self, quiet_page):
        """The viewer asks the server what has changed several times a second.

        That question is about which acquisitions exist, not about pixels, so a
        viewer nobody is touching must be completely quiet.
        """
        page, watcher, _ = quiet_page
        mark = watcher.mark
        page.wait_for_timeout(5000)
        assert watcher.since(mark) == 0, "the viewer fetched image data while idle"

    def test_drawing_a_target_fetches_nothing(self, quiet_page):
        """Marking a place is about the marks, not about the image."""
        page, watcher, _ = quiet_page
        mark = watcher.mark
        page.evaluate(
            """() => {
              const reference = window.zmartAnnotationSource.add({
                id: "t1", type: 2, description: "",
                pointA: new Float32Array([2, 3, 4]),
                pointB: new Float32Array([8, 9, 10]), properties: [] }, true);
              reference.dispose();
            }"""
        )
        page.wait_for_timeout(2500)
        assert watcher.since(mark) == 0

    def test_the_shader_is_left_alone_when_nothing_changed(self, quiet_page):
        """An unchanged shader must be handed over unchanged, character for character.

        The graphics card recompiles a shader whose text has altered. If the
        interface rebuilt that text slightly differently each time, every layer
        would be recompiled for no reason.
        """
        page, _, _ = quiet_page
        read = """() => window.zmartViewer.layerManager
                    .getLayerByName('overview · ch0').layer.fragmentMain.value"""
        before = page.evaluate(read)
        # Provoke a rebuild of the description without changing anything visible.
        page.get_by_label("collapse overview").click()
        page.wait_for_timeout(800)
        page.get_by_label("expand overview").click()
        page.wait_for_timeout(1500)
        assert page.evaluate(read) == before


class TestMovingAround:
    """Navigation should reuse what has been fetched already."""

    def test_returning_to_where_you_were_costs_nothing_already_held(self, quiet_page):
        """Scrolling away and back must not ask for any piece a second time.

        This is asked as "was anything fetched twice?" rather than "how much was
        fetched?", and the difference matters. Scrolling through a stack fetches a
        good deal quite properly: the engine reads ahead, so moving a few planes
        pulls in the planes around them as well, and coming back to where you
        started can quite legitimately finish off a plane that had not been reached
        yet. Counting those as waste would fail the engine for doing its job well.

        What would be genuinely wrong is a piece already in hand being asked for
        again — that would mean nothing is being kept, and exploring a large image
        would be miserable. So that, exactly, is what is measured.
        """
        page, watcher, _ = quiet_page
        home = page.evaluate(
            "() => Array.from(window.zmartViewer.navigationState.position.value)"
        )
        page.mouse.move(550, 400)
        for _ in range(3):
            page.mouse.wheel(0, -120)
        page.wait_for_timeout(2500)
        page.evaluate(
            "(p) => { window.zmartViewer.navigationState.position.value = Float32Array.from(p); }",
            home,
        )
        page.wait_for_timeout(2500)

        assert not watcher.repeats(), (
            "the engine fetched pieces it had already: "
            f"{sorted(watcher.repeats())[:5]} — it is not keeping what it fetched"
        )

    def test_going_to_three_d_and_back_keeps_the_slice(self, quiet_page):
        """The volume needs more data; returning to the slice needs none of it again."""
        page, watcher, _ = quiet_page
        page.click("text=3D")
        page.wait_for_timeout(6000)          # the volume legitimately fetches more
        mark = watcher.mark
        page.click("text=2D")
        page.wait_for_timeout(3000)
        assert watcher.since(mark) == 0, "returning to the slice refetched it"


class TestOpeningSomethingElse:
    """Adding an acquisition must not disturb the one already on screen."""

    def test_opening_a_second_acquisition_leaves_the_first_alone(
        self, browser, built_dist, tmp_path
    ):
        _store(tmp_path / "overview_pos001.ome.zarr")
        second = tmp_path / "later"
        second.mkdir()
        _store(second / "targetscan_cell007.ome.zarr", seed=40)

        server = make_server(
            port=0,
            data_dir=tmp_path,
            site_dir=built_dist,
            store="overview_pos001.ome.zarr",
            browse=lambda: str(second),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        page = browser.new_page(viewport={"width": 1100, "height": 800})
        watcher = Watcher(page)
        try:
            page.goto(f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded")
            page.wait_for_function("() => window.zmartViewer !== undefined", timeout=60_000)
            page.wait_for_function(_SETTLED, timeout=90_000)
            page.wait_for_timeout(2500)

            before = list(watcher.urls)
            page.get_by_label("open images").click()
            page.wait_for_function(
                "() => window.zmartConfig.groups.includes('targetscan')", timeout=20_000
            )
            page.wait_for_timeout(4000)

            # Whatever was fetched must belong to the newly opened acquisition.
            added = watcher.urls[len(before) :]
            first_again = [url for url in added if "overview_pos001" in url]
            assert not first_again, (
                "opening a second acquisition refetched the first: "
                f"{len(first_again)} pieces"
            )
        finally:
            page.close()
            server.shutdown()
            thread.join(timeout=5)


class TestDataArrivingWhileYouWatch:
    """A smart-microscopy run writes as it goes. That must stay cheap at any size.

    The store the viewer is looking at grows in two ways and only two: new
    acquisitions appear beside the ones open, and existing ones gain frames. Both
    have to stay affordable when there are already a great many, because a run does
    not slow down to let the viewer catch up.
    """

    def test_an_acquisition_arriving_among_many_does_not_disturb_the_rest(
        self, browser, built_dist, tmp_path
    ):
        """With sixty acquisitions open, a new one must not refetch the sixty."""
        existing = 60
        # Deliberately small. This test asks whether one new acquisition disturbs
        # sixty already open, and that question does not depend on how large they
        # are -- while writing sixty full-size ones costs two gigabytes and most of
        # a minute before the test has even begun.
        for i in range(existing):
            _store(tmp_path / f"overview_pos{i:03d}.ome.zarr", seed=i, channels=1, side=CHUNK)

        server = make_server(
            port=0,
            data_dir=tmp_path,
            site_dir=built_dist,
            store=sorted(p.name for p in tmp_path.glob("*.ome.zarr")),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        page = browser.new_page(viewport={"width": 1100, "height": 800})
        watcher = Watcher(page)
        try:
            page.goto(f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded")
            page.wait_for_function("() => window.zmartViewer !== undefined", timeout=90_000)
            page.wait_for_function(_SETTLED, timeout=120_000)
            page.wait_for_timeout(3000)

            settled = watcher.mark
            # The run writes another acquisition, as it would mid-experiment.
            _store(tmp_path / "targetscan_cell900.ome.zarr", seed=900, channels=1, side=CHUNK)
            started = time.monotonic()
            page.wait_for_function(
                # Generous, because this is the one test with sixty acquisitions
                # open, and when the suite is run several tests at a time the
                # browsers are competing for the same few cores. What is being
                # measured is below, and it is not a stopwatch.
                "() => window.zmartConfig.groups.includes('targetscan')", timeout=90_000
            )
            noticed = time.monotonic() - started
            page.wait_for_timeout(4000)

            fetched = watcher.urls[settled:]
            old_again = [url for url in fetched if "targetscan" not in url]
            assert not old_again, (
                f"a new acquisition refetched {len(old_again)} pieces of the "
                f"{existing} already open"
            )
            assert noticed < 60.0, f"took {noticed:.1f}s to notice new data"
        finally:
            page.close()
            server.shutdown()
            thread.join(timeout=5)

    def test_frames_arriving_do_not_disturb_what_is_shown(self, browser, built_dist, tmp_path):
        """A timelapse gains frames. Nothing already drawn should be fetched again.

        The length is declared up front, so a new frame is only new pieces of image
        on disk — no part of the store's description changes, and the engine has
        nothing to reconsider until you go and look at that frame.
        """
        store = tmp_path / "overview_pos001.ome.zarr"
        store.mkdir()
        group = zarr.open_group(str(store), mode="w", zarr_format=2)
        array = group.create_array(
            "0", shape=(8, 1, 8, 256, 256), chunks=(1, 1, 1, 256, 256), dtype="uint16",
            chunk_key_encoding={"name": "v2", "separator": "/"},
        )
        for t in range(2):
            array[t] = np.full((1, 8, 256, 256), 5000, dtype=np.uint16)
        (store / ".zattrs").write_text(
            json.dumps({
                "multiscales": [{
                    "version": "0.4",
                    "axes": [
                        {"name": "t", "type": "time", "unit": "second"},
                        {"name": "c", "type": "channel"},
                        {"name": "z", "type": "space", "unit": "micrometer"},
                        {"name": "y", "type": "space", "unit": "micrometer"},
                        {"name": "x", "type": "space", "unit": "micrometer"}],
                    "datasets": [{"path": "0", "coordinateTransformations": [
                        {"type": "scale", "scale": [30.0, 1.0, 2.0, 0.35, 0.35]}]}],
                }],
                "omero": {"channels": [{"label": "ch0", "color": "FFFFFF",
                    "window": {"min": 0, "max": 65535, "start": 0, "end": 9000}}]},
            }),
            encoding="utf-8",
        )

        server = make_server(
            port=0, data_dir=tmp_path, site_dir=built_dist, store=store.name
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        page = browser.new_page(viewport={"width": 1100, "height": 800})
        watcher = Watcher(page)
        try:
            page.goto(f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded")
            page.wait_for_function("() => window.zmartViewer !== undefined", timeout=60_000)
            page.wait_for_function(_SETTLED, timeout=90_000)
            page.wait_for_timeout(2500)
            assert page.evaluate("() => window.zmartConfig.layers[0].frames") == 2

            mark = watcher.mark
            for t in range(2, 5):
                array[t] = np.full((1, 8, 256, 256), 6000, dtype=np.uint16)
            # The slider must reach the new frames...
            page.wait_for_function(
                "() => window.zmartConfig.layers[0].frames === 5", timeout=20_000
            )
            page.wait_for_timeout(2500)
            # ...without anything already on screen being fetched again.
            assert watcher.since(mark) == 0, "frames arriving refetched the current view"
        finally:
            page.close()
            server.shutdown()
            thread.join(timeout=5)

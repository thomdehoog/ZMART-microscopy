"""Segmentation masks, colour maps, the time limit, and noticing new work quickly.

Four things that only make sense together, because each is about the viewer being
honest about what is really there: masks are drawn as objects rather than as dim
pixels, a colour map is a shader the engine already compiles, the time slider stops
at frames that exist, and a new acquisition is noticed without asking an expensive
question over and over.
"""

from __future__ import annotations

import json
import threading

import numpy as np
import pytest
import zarr
from pixels import colour_spread, image_middle
from server import make_server
from driving import pick_colormap  # noqa: E402


def _image(path, *, channels=2, frames=1, written=None):
    """A t,c,z,y,x image. ``written`` leaves later frames declared but unwritten."""
    path.mkdir(parents=True)
    group = zarr.open_group(str(path), mode="w", zarr_format=2)
    array = group.create_array(
        "0", shape=(frames, channels, 4, 64, 64), chunks=(1, 1, 1, 64, 64), dtype="uint16"
    )
    for t in range(written if written is not None else frames):
        array[t] = np.full((channels, 4, 64, 64), 4000, dtype=np.uint16)
    (path / ".zattrs").write_text(
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
                                    {"type": "scale", "scale": [30.0, 1.0, 2.0, 0.35, 0.35]}
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


def _add_mask(image, name="nuclei"):
    """A segmentation mask stored the standard way: a labels folder inside the image."""
    labels = image / "labels"
    labels.mkdir(exist_ok=True)
    (labels / ".zgroup").write_text(json.dumps({"zarr_format": 2}), encoding="utf-8")
    (labels / ".zattrs").write_text(json.dumps({"labels": [name]}), encoding="utf-8")
    mask_path = labels / name
    group = zarr.open_group(str(mask_path), mode="w", zarr_format=2)
    mask = np.zeros((4, 64, 64), dtype=np.uint32)
    mask[:, 8:24, 8:24] = 1
    mask[:, 32:56, 32:56] = 2
    group.create_array("0", shape=mask.shape, chunks=(1, 64, 64), dtype="uint32")[:] = mask
    (mask_path / ".zattrs").write_text(
        json.dumps(
            {
                "multiscales": [
                    {
                        "version": "0.4",
                        "axes": [{"name": a, "type": "space", "unit": "micrometer"}
                                 for a in ("z", "y", "x")],
                        "datasets": [
                            {"path": "0", "coordinateTransformations": [
                                {"type": "scale", "scale": [2.0, 0.35, 0.35]}]}
                        ],
                    }
                ],
                "image-label": {"version": "0.4"},
            }
        ),
        encoding="utf-8",
    )
    return mask_path


def _serve(browser, built_dist, folder, store, name="overview"):
    # The load names the dataset, and the panel heading is what the engine builds
    # its layer names from ("overview · nuclei"), so it has to be said here rather
    # than inferred from a temporary folder's name.
    stores = [store] if isinstance(store, str) else list(store)
    server = make_server(
        port=0, data_dir=folder, site_dir=built_dist,
        loads=[{"stores": stores, "name": name}],
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1300, "height": 1000})
    page.goto(f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded")
    page.wait_for_function("() => window.zmartConfig !== undefined", timeout=30_000)
    return page, server, thread


@pytest.fixture
def masked_page(browser, built_dist, tmp_path):
    image = _image(tmp_path / "overview_pos001.ome.zarr", frames=1)
    _add_mask(image)
    page, server, thread = _serve(browser, built_dist, tmp_path, "overview_pos001.ome.zarr")
    try:
        yield page
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def _layers(page):
    return page.evaluate(
        """() => window.zmartViewer.layerManager.managedLayers.map((m) => ({
             name: m.name, type: m.layer?.type, visible: m.visible }))"""
    )


class TestSegmentationMasks:
    """A mask is drawn as objects, not as a dim picture."""

    def test_the_mask_is_found_beside_the_image(self, masked_page):
        config = masked_page.evaluate("() => window.zmartConfig")
        masks = [row for row in config["layers"] if row["kind"] == "segmentation"]
        assert [row["name"] for row in masks] == ["nuclei"]

    def test_the_engine_draws_it_as_a_segmentation(self, masked_page):
        masked_page.wait_for_function(
            """() => window.zmartViewer.layerManager.managedLayers
                 .some((m) => m.layer?.type === 'segmentation')""",
            timeout=20_000,
        )
        kinds = {layer["name"]: layer["type"] for layer in _layers(masked_page)}
        assert kinds.get("overview · nuclei") == "segmentation"
        # The picture channels are still ordinary image layers.
        assert kinds.get("overview · ch0") == "image"

    def test_its_pixels_arrive(self, masked_page):
        """The objects are on screen, checked by looking at the screen.

        The engine can report every piece of the mask fetched and decoded while the
        panel shows nothing of it — a mask drawn at the wrong scale, or behind the
        image, or in a colour indistinguishable from the background, all count as
        arrived as far as the engine is concerned. So the engine is asked only when
        to look, and the picture is asked what is there.

        The two picture channels are hidden before the photograph is taken. Both are
        an even fill, so leaving them on would put a broad flat wash over the panel
        that the mask would have to be picked out of; with only the mask showing,
        any variety in the middle of the picture is the objects themselves. Two
        objects were written into this mask, and the engine gives each its own
        colour, so a drawn mask is unmistakable and a mask that never made it to
        the screen leaves a single flat colour behind.
        """
        # The precondition: the mask's pieces have all arrived, so there is nothing
        # left to wait for. This says when to photograph, not what will be in it.
        masked_page.wait_for_function(
            """() => {
              const m = window.zmartViewer.layerManager.managedLayers
                .find((x) => x.layer?.type === 'segmentation');
              if (!m) return false;
              let needed = 0, available = 0;
              for (const rl of (m.layer?.renderLayers) || []) {
                const p = rl.layerChunkProgressInfo;
                if (p) { needed += p.numVisibleChunksNeeded;
                         available += p.numVisibleChunksAvailable; }
              }
              return available > 0 && available >= needed;
            }""",
            timeout=60_000,
        )

        # Leave the mask alone on screen, so what is measured is the mask.
        masked_page.get_by_label("toggle ch0").first.click()
        masked_page.get_by_label("toggle ch1").first.click()
        masked_page.wait_for_timeout(2000)
        # What is measured, and why it is not `assert_something_was_drawn`. That
        # helper asks whether the middle of the panel has a picture filling it, and
        # its thresholds are set for the demo volume, which covers the whole view.
        # Two small objects do not: measured, they light three distinct colours with
        # a spread of about ten, and leave 99.7% of the middle showing background.
        # That is a mask perfectly present on screen, and the helper would call it
        # blank. So the question here is the narrower one it can actually answer --
        # is there more than one colour in the panel, and does any of it vary -- and
        # the control below is what turns that into evidence about the mask.
        drawn = colour_spread(image_middle(masked_page))
        assert drawn["distinct"] > 1 and drawn["spread"] > 1.0, (
            f"nothing of the segmentation mask reached the screen: {drawn}"
        )

        # The control, which is what keeps the line above from decaying into an
        # assertion that cannot fail. If our own buttons or a background gradient
        # were supplying the variety rather than the mask, hiding the mask would
        # change nothing. It has to go flat.
        masked_page.get_by_label("toggle nuclei").first.click()
        masked_page.wait_for_timeout(2000)
        hidden = colour_spread(image_middle(masked_page))
        assert hidden["distinct"] < drawn["distinct"], (
            "hiding the mask left the picture exactly as varied as before, so what "
            f"was measured was never the mask: {drawn} then {hidden}"
        )

    def test_it_shows_no_contrast_handles(self, masked_page):
        """Brightness and contrast mean nothing on an object's identity number."""
        # Select the mask, so the shared controls are the mask's own. Without
        # selecting it, this would only be checking that some *other* channel's
        # handles are not labelled "nuclei", which proves nothing.
        masked_page.get_by_label("toggle nuclei").locator("xpath=../..").click()
        masked_page.wait_for_timeout(300)
        # The two ends of the window are labelled min and max, following Fiji,
        # and brightness and contrast drive the same window from the other side.
        # None of the four means anything on an identity number, so all four
        # must be absent. Naming them exactly as the panel does is the whole
        # point: while this asked for "black" and "white", which the panel had
        # stopped offering to any layer at all, it passed by finding nothing
        # whatever the mask showed.
        for handle in ("min", "max", "brightness", "contrast"):
            assert masked_page.get_by_label(f"{handle} nuclei").count() == 0
        # It can still be hidden and faded like anything else.
        assert masked_page.get_by_label("toggle nuclei").count() == 1
        assert masked_page.get_by_label("opacity nuclei").count() == 1


class TestLookupTables:
    """A colour map is the shader the engine already compiles, nothing more."""

    def test_choosing_one_rewrites_the_shader(self, masked_page):
        before = masked_page.evaluate(
            """() => window.zmartViewer.layerManager.getLayerByName('overview · ch0')
                 .layer.fragmentMain.value"""
        )
        pick_colormap(masked_page, "ch0", "viridis")
        masked_page.wait_for_function(
            """() => window.zmartViewer.layerManager.getLayerByName('overview · ch0')
                 .layer.fragmentMain.value.includes('zmartLut')""",
            timeout=15_000,
        )
        after = masked_page.evaluate(
            """() => window.zmartViewer.layerManager.getLayerByName('overview · ch0')
                 .layer.fragmentMain.value"""
        )
        assert after != before
        assert "zmartLut" in after

    def test_it_can_be_put_back_to_a_flat_colour(self, masked_page):
        pick_colormap(masked_page, "ch0", "magma")
        masked_page.wait_for_timeout(600)
        pick_colormap(masked_page, "ch0", "green")
        masked_page.wait_for_function(
            """() => !window.zmartViewer.layerManager.getLayerByName('overview · ch0')
                 .layer.fragmentMain.value.includes('zmartLut')""",
            timeout=15_000,
        )

    def test_one_channel_keeps_its_own_choice(self, masked_page):
        pick_colormap(masked_page, "ch0", "fire")
        masked_page.wait_for_timeout(800)
        other = masked_page.evaluate(
            """() => window.zmartViewer.layerManager.getLayerByName('overview · ch1')
                 .layer.fragmentMain.value"""
        )
        assert "zmartLut" not in other, "the other channel must be untouched"


def test_the_time_slider_stops_at_frames_that_exist(browser, built_dist, tmp_path):
    """Declared far ahead, written only part-way: the slider follows what is real.

    This is not tidiness. The engine remembers "there is nothing here" for a frame
    it looked at before the data arrived, and does not look again — so a slider
    running out over unwritten frames would let the operator poison them.
    """
    _image(tmp_path / "overview_pos001.ome.zarr", frames=10, written=3)
    page, server, thread = _serve(browser, built_dist, tmp_path, "overview_pos001.ome.zarr")
    try:
        page.wait_for_selector("[aria-label='t position']", timeout=30_000)
        config = page.evaluate("() => window.zmartConfig")
        assert config["layers"][0]["frames"] == 3, "three frames are written of ten declared"
        readout = page.locator("[aria-label='t position value']").inner_text()
        assert readout.strip().endswith("/ 3")
        slider = page.locator("[aria-label='t position']")
        assert float(slider.get_attribute("max")) == 2.0  # frames 0, 1, 2
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def test_a_new_acquisition_is_noticed_quickly_and_quietly(browser, built_dist, tmp_path):
    """Nothing is asked while nothing happens, and a new acquisition still arrives.

    Both halves matter, and they used to pull against each other. The viewer once
    asked a small question several times a second so that it would notice new data
    quickly; noticing quickly was the point, and the constant asking was the price.
    Now the server says when something has changed, so the page can sit completely
    quiet and still be told at once.

    So this watches for three seconds of an ordinary run with nothing happening and
    insists the page asked for nothing at all, then writes an acquisition and
    insists it appears.
    """
    _image(tmp_path / "overview_pos001.ome.zarr")
    page, server, thread = _serve(browser, built_dist, tmp_path, "overview_pos001.ome.zarr")
    try:
        page.wait_for_function("() => window.zmartConfig !== undefined", timeout=30_000)
        asked = []
        page.on(
            "request",
            lambda r: asked.append(r.url.rsplit("/", 1)[-1]) if "/api/" in r.url else None,
        )
        page.wait_for_timeout(3000)
        # Two things are not counted, and neither is polling.
        #
        # "events" is the one connection the page holds open: it is opened once and
        # then simply waits, which is the whole point of it. "annotations" is the
        # target list being saved, which happens once shortly after the list is
        # first read and then only when the operator draws something.
        #
        # Anything else appearing here means the page has gone back to asking
        # repeatedly, which is exactly what the announcements replaced.
        chatter = [name for name in asked if name not in {"events", "annotations"}]
        assert not chatter, f"the page asked for things while nothing was happening: {chatter}"
        assert asked.count("annotations") <= 1, "the target list is being saved over and over"
        assert asked.count("events") <= 1, "the held connection is being remade"

        # A store appearing in a watched folder joins the dataset that was loaded
        # from it rather than making a heading of its own -- the load decides what a
        # dataset is, not the filenames inside it. So what proves it arrived is the
        # store itself reaching the page, not a new group.
        _image(tmp_path / "targetscan_cell007.ome.zarr")
        page.wait_for_function(
            """() => window.zmartConfig.layers.some(
                 (row) => row.sources.some((s) => s.includes('targetscan_cell007')))""",
            timeout=15_000,
        )
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)

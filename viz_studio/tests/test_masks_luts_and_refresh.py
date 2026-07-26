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
from server import make_server


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


def _serve(browser, built_dist, folder, store):
    server = make_server(port=0, data_dir=folder, site_dir=built_dist, store=store)
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

    def test_it_shows_no_contrast_handles(self, masked_page):
        """Brightness and contrast mean nothing on an object's identity number."""
        assert masked_page.get_by_label("black nuclei").count() == 0
        assert masked_page.get_by_label("white nuclei").count() == 0
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
        masked_page.get_by_label("colour map ch0").select_option("viridis")
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
        masked_page.get_by_label("colour map ch0").select_option("magma")
        masked_page.wait_for_timeout(600)
        masked_page.get_by_label("colour map ch0").select_option("")
        masked_page.wait_for_function(
            """() => !window.zmartViewer.layerManager.getLayerByName('overview · ch0')
                 .layer.fragmentMain.value.includes('zmartLut')""",
            timeout=15_000,
        )

    def test_one_channel_keeps_its_own_choice(self, masked_page):
        masked_page.get_by_label("colour map ch0").select_option("fire")
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


def test_a_new_acquisition_is_noticed_quickly(browser, built_dist, tmp_path):
    """The cheap question is asked often; the expensive one only when it moves."""
    _image(tmp_path / "overview_pos001.ome.zarr")
    page, server, thread = _serve(browser, built_dist, tmp_path, "overview_pos001.ome.zarr")
    try:
        asked = []
        page.on(
            "request",
            lambda r: asked.append(r.url.rsplit("/", 1)[-1])
            if "/api/" in r.url
            else None,
        )
        page.wait_for_timeout(3000)
        # Many cheap questions, and no repeated expensive ones while nothing changes.
        assert asked.count("revision") >= 3, "expected the cheap question to be asked often"
        assert asked.count("config") <= 1, "the expensive question must not be repeated"

        _image(tmp_path / "targetscan_cell007.ome.zarr")
        page.wait_for_function(
            "() => window.zmartConfig.groups.includes('targetscan')", timeout=15_000
        )
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)

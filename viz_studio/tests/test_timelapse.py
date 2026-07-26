"""The time axis: a timelapse store, and the T slider that moves through it.

A timelapse is the one shape of data the viewer could not previously step
through. These tests cover both halves of that: the demo generator really does
write a store with a time axis, and the interface really does offer a time
slider for it — and, just as importantly, offers no such slider for an ordinary
single-moment volume, where it would only be a control that does nothing.
"""

from __future__ import annotations

import json
import threading

import numpy as np
import pytest
import zarr
from demo_data import write_demo_zarr
from server import make_server

FRAMES = 4


@pytest.fixture(scope="module")
def timelapse_store(tmp_path_factory):
    """A small timelapse OME-Zarr, written once for this module."""
    store = tmp_path_factory.mktemp("timelapse") / "demo_t.zarr"
    write_demo_zarr(store, timepoints=FRAMES)
    return store


class TestTheStoreOnDisk:
    """The file has to declare a time axis, or nothing downstream can show one."""

    def test_the_axes_are_written_in_the_standard_order(self, timelapse_store):
        attrs = json.loads((timelapse_store / ".zattrs").read_text(encoding="utf-8"))
        axes = [axis["name"] for axis in attrs["multiscales"][0]["axes"]]
        assert axes == ["t", "c", "z", "y", "x"]

    def test_the_time_axis_declares_itself_as_time(self, timelapse_store):
        attrs = json.loads((timelapse_store / ".zattrs").read_text(encoding="utf-8"))
        time_axis = attrs["multiscales"][0]["axes"][0]
        assert time_axis["type"] == "time"
        assert time_axis["unit"] == "second"

    def test_every_frame_is_present_at_full_resolution(self, timelapse_store):
        group = zarr.open_group(str(timelapse_store), mode="r")
        assert group["0"].shape[0] == FRAMES

    def test_the_pyramid_shrinks_space_but_not_time_or_colour(self, timelapse_store):
        """Averaging two timepoints, or two colours, together would be nonsense."""
        group = zarr.open_group(str(timelapse_store), mode="r")
        attrs = json.loads((timelapse_store / ".zattrs").read_text(encoding="utf-8"))
        levels = [group[str(i)].shape for i in range(len(attrs["multiscales"][0]["datasets"]))]
        assert len(levels) > 1, "expected more than one resolution level"
        for coarse, fine in zip(levels[1:], levels[:-1], strict=True):
            assert coarse[:2] == fine[:2]  # time and channel untouched
            assert coarse[2:] == tuple(n // 2 for n in fine[2:])  # z, y, x halved

    def test_each_frame_carries_its_time_in_the_scale(self, timelapse_store):
        attrs = json.loads((timelapse_store / ".zattrs").read_text(encoding="utf-8"))
        for dataset in attrs["multiscales"][0]["datasets"]:
            scale = dataset["coordinateTransformations"][0]["scale"]
            assert len(scale) == 5
            assert scale[0] > 0  # seconds per frame, the same at every level
            assert scale[1] == 1.0  # no scaling on colour

    def test_the_frames_actually_differ(self, timelapse_store):
        """A slider that reveals nothing is untestable and useless to an operator."""
        group = zarr.open_group(str(timelapse_store), mode="r")
        volume = group["0"][:]
        first, last = volume[0], volume[-1]
        assert not np.array_equal(first, last)
        # marker-a (channel 1) brightens across the series; marker-b (2) fades.
        assert volume[-1, 1].mean() > volume[0, 1].mean()
        assert volume[-1, 2].mean() < volume[0, 2].mean()

    def test_a_single_timepoint_store_has_no_time_axis(self, tmp_path):
        """The ordinary demo must be unchanged, so no stray slider appears."""
        store = write_demo_zarr(tmp_path / "single.zarr")
        attrs = json.loads((store / ".zattrs").read_text(encoding="utf-8"))
        axes = [axis["name"] for axis in attrs["multiscales"][0]["axes"]]
        assert axes == ["c", "z", "y", "x"]

    def test_asking_for_no_frames_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="at least 1"):
            write_demo_zarr(tmp_path / "none.zarr", timepoints=0)


class TestServingATimelapse:
    """The server must describe a timelapse without choking on the extra axis."""

    def test_the_config_still_describes_the_layer(self, timelapse_store, tmp_path):
        site = tmp_path / "site"
        site.mkdir()
        (site / "index.html").write_text("<!doctype html>", encoding="utf-8")
        server = make_server(
            port=0,
            data_dir=timelapse_store.parent,
            site_dir=site,
            store=timelapse_store.name,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            import http.client

            conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
            conn.request("GET", "/api/config")
            config = json.loads(conn.getresponse().read())
            conn.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)

        assert len(config["layers"]) == 1
        layer = config["layers"][0]
        # The contrast window and histogram are measured from the store, so a
        # five-dimensional array must not have broken that measurement.
        assert layer["window"]["high"] > layer["window"]["low"]
        assert layer["histogram"] is not None
        assert len(layer["histogram"]["counts"]) > 0


# --- the slider in a real browser ------------------------------------------


@pytest.fixture(scope="module")
def timelapse_page(browser, built_dist, timelapse_store):
    """The viewer, booted on the timelapse store, with its chunks loaded."""
    server = make_server(
        port=0,
        data_dir=timelapse_store.parent,
        site_dir=built_dist,
        store=timelapse_store.name,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1200, "height": 900})
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined", timeout=30_000)
        page.wait_for_function(
            """() => {
              const v = window.zmartViewer;
              let needed = 0, available = 0;
              for (const managed of v.layerManager.managedLayers) {
                for (const rl of (managed.layer && managed.layer.renderLayers) || []) {
                  const p = rl.layerChunkProgressInfo;
                  if (p) { needed += p.numVisibleChunksNeeded; available += p.numVisibleChunksAvailable; }
                }
              }
              return available > 0 && available >= needed;
            }""",
            timeout=60_000,
        )
        yield page
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def _axis_names(page):
    """The axis names the engine itself reports for the loaded image."""
    return page.evaluate(
        "() => Array.from(window.zmartViewer.navigationState.position.coordinateSpace.value.names)"
    )


class TestTheTimeSlider:
    """The slider exists, spans the frames, and actually moves the engine."""

    def test_the_engine_sees_a_time_axis(self, timelapse_page):
        assert "t" in _axis_names(timelapse_page)

    def test_the_slider_is_offered(self, timelapse_page):
        assert timelapse_page.locator("[aria-label='t position']").count() == 1

    def test_it_spans_exactly_the_frames_that_exist(self, timelapse_page):
        readout = timelapse_page.locator("[aria-label='t position value']").inner_text()
        assert readout.strip().endswith(f"/ {FRAMES}")

    def test_moving_it_moves_the_engine_to_that_frame(self, timelapse_page):
        names = _axis_names(timelapse_page)
        index = names.index("t")
        slider = timelapse_page.locator("[aria-label='t position']")
        before = timelapse_page.evaluate(
            f"() => window.zmartViewer.navigationState.position.value[{index}]"
        )
        # Drive the slider the way a browser does, so React's handler runs.
        timelapse_page.evaluate(
            """([selector, value]) => {
              const el = document.querySelector(selector);
              const setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value').set;
              setter.call(el, String(value));
              el.dispatchEvent(new Event('input', { bubbles: true }));
              el.dispatchEvent(new Event('change', { bubbles: true }));
            }""",
            ["[aria-label='t position']", 2],
        )
        timelapse_page.wait_for_function(
            f"() => window.zmartViewer.navigationState.position.value[{index}] !== {before}",
            timeout=10_000,
        )
        after = timelapse_page.evaluate(
            f"() => window.zmartViewer.navigationState.position.value[{index}]"
        )
        assert after != before
        assert slider.input_value() != ""

    def test_the_time_slider_survives_the_switch_to_3d(self, timelapse_page):
        """Time means something in the volume view too, so it must stay."""
        timelapse_page.get_by_role("button", name="3D", exact=True).click()
        timelapse_page.wait_for_function(
            "() => window.zmartMode === 'volume'", timeout=15_000
        )
        assert timelapse_page.locator("[aria-label='t position']").count() == 1
        # Z, by contrast, is not offered in 3-D: the whole depth is on screen.
        assert timelapse_page.locator("[aria-label='z position']").count() == 0
        timelapse_page.get_by_role("button", name="2D", exact=True).click()
        timelapse_page.wait_for_function("() => window.zmartMode === 'flat'", timeout=15_000)


def test_no_time_slider_for_a_single_moment_volume(viewer_page):
    """The ordinary demo has no time axis, so it must show no time slider."""
    assert viewer_page.locator("[aria-label='z position']").count() == 1
    assert viewer_page.locator("[aria-label='t position']").count() == 0


def test_the_z_slider_reaches_every_plane_of_the_stack(viewer_page):
    """All 48 planes must be reachable, including the last one.

    This guards a real off-by-one: the engine reports a 48-plane stack as an
    extent from -0.5 to 47.5, and taking one off the top end silently made the
    final plane unreachable while everything still looked correct.
    """
    from demo_data import _DEPTH

    readout = viewer_page.locator("[aria-label='z position value']").inner_text()
    assert readout.strip().endswith(f"/ {_DEPTH}")
    slider = viewer_page.locator("[aria-label='z position']")
    # The top of the slider's own range must be the last plane, not the one before.
    assert float(slider.get_attribute("max")) == float(_DEPTH - 1)

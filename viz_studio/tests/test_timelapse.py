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

        # Three channels live inside this store, so it becomes three rows -- one
        # per channel -- rather than a single row hiding two of them.
        assert len(config["layers"]) == 3
        assert [row["channelIndex"] for row in config["layers"]] == [0, 1, 2]
        for layer in config["layers"]:
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
        """Dragging the slider must put the engine on exactly that frame.

        The target frame is chosen relative to where the slider already sits. The
        engine opens a view in the middle of the time axis, which the slider snaps
        to the nearest real frame, so asking for the frame it is already showing
        would be a no-op and would prove nothing.
        """
        names = _axis_names(timelapse_page)
        index = names.index("t")
        slider = timelapse_page.locator("[aria-label='t position']")
        current = float(slider.input_value())
        low, high = float(slider.get_attribute("min")), float(slider.get_attribute("max"))
        target = low if current != low else high

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
            ["[aria-label='t position']", target],
        )
        timelapse_page.wait_for_function(
            f"() => window.zmartViewer.navigationState.position.value[{index}] === {target}",
            timeout=10_000,
        )
        assert float(slider.input_value()) == target

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


# The whole control -- play button, name, slider and reading together -- which is
# what has to be placed and turned, and what two of them must not overlap in.
_BOX = """(label) => {
  const element = document.querySelector(`[aria-label='${label}']`);
  if (!element) return null;
  const box = (element.closest('label') ?? element).getBoundingClientRect();
  return {left: box.left, right: box.right, top: box.top, bottom: box.bottom,
          width: box.width, height: box.height};
}"""

# Just the one element, for asking where a part of a control sits within it.
_PART = """(label) => {
  const element = document.querySelector(`[aria-label='${label}']`);
  if (!element) return null;
  const box = element.getBoundingClientRect();
  return {left: box.left, right: box.right, top: box.top, bottom: box.bottom,
          width: box.width, height: box.height};
}"""


def _box(page, label, whole_control=True):
    """Where something sits on screen, once it is actually there.

    The waiting matters and is not belt-and-braces. These tests share one page
    with the rest of the module, and another test in it switches to the volume
    view and back — which takes the depth slider away and puts it back, since
    depth means nothing when the whole stack is already on screen. The engine
    announces the switch before the interface has finished catching up with it,
    so measuring straight away can find nothing there and fail for reasons that
    have nothing to do with where the sliders are. Waiting for the control first
    makes the answer depend only on this test.
    """
    page.wait_for_selector(f"[aria-label='{label}']", state="attached", timeout=15_000)
    return page.evaluate(_BOX if whole_control else _PART, label)


class TestWhereTheSlidersSit:
    """Each slider is placed and turned the way the thing it moves through is.

    Depth stands upright along the right-hand edge, the way a stack of planes is
    pictured, and time lies along the bottom, the way a recording is. The point is
    that an operator can reach for the right one without stopping to read the
    labels, which matters when both are on screen and their hand is on the stage.

    This is worth pinning because it is easy to lose. The two are the same control
    used twice, so a change to one reaches the other, and an arrangement that
    quietly went back to two identical bars stacked in a corner would still pass
    every other test here.
    """

    def _view(self, page):
        return page.evaluate("() => ({width: innerWidth, height: innerHeight})")

    def test_depth_stands_upright_along_the_right_hand_edge(self, timelapse_page):
        box = _box(timelapse_page, "z position")
        view = self._view(timelapse_page)
        assert box["height"] > box["width"] * 3, (
            f"the depth slider is not standing upright: {box['width']:.0f} wide by "
            f"{box['height']:.0f} tall"
        )
        assert box["left"] > view["width"] / 2, (
            "the depth slider should be on the right-hand side of the view, and its "
            f"left edge is at {box['left']:.0f} of {view['width']}"
        )

    def test_time_lies_along_the_bottom(self, timelapse_page):
        box = _box(timelapse_page, "t position")
        view = self._view(timelapse_page)
        assert box["width"] > box["height"] * 3, (
            f"the time slider is not lying flat: {box['width']:.0f} wide by "
            f"{box['height']:.0f} tall"
        )
        assert box["top"] > view["height"] / 2, (
            "the time slider should be along the bottom of the view, and its top "
            f"edge is at {box['top']:.0f} of {view['height']}"
        )

    def test_neither_is_drawn_over_the_other(self, timelapse_page):
        depth = _box(timelapse_page, "z position")
        time = _box(timelapse_page, "t position")
        assert depth["bottom"] <= time["top"], (
            "the depth slider runs down into the time slider: it ends at "
            f"{depth['bottom']:.0f} and the time slider starts at {time['top']:.0f}"
        )

    def test_the_reading_stays_inside_the_upright_control(self, timelapse_page):
        """Which plane you are on has to be inside the panel showing it.

        Standing the control on end gives it a fixed height to fit into, and a
        reading that spills past the bottom edge lands on the image instead — small
        pale text on whatever happens to be underneath, which is where it is least
        readable.
        """
        control = _box(timelapse_page, "z position")
        reading = _box(timelapse_page, "z position value", whole_control=False)
        assert reading["bottom"] <= control["bottom"], (
            f"the reading ends at {reading['bottom']:.0f}, below the control's own "
            f"bottom edge at {control['bottom']:.0f}"
        )


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


def test_a_store_that_lengthens_its_own_array_is_read_again(browser, built_dist, tmp_path):
    """A run that grows its array must not leave the slider at the old length.

    There are two shapes a timelapse can take on disk and the viewer meets both.
    One declares all its moments up front and fills them in, which is what
    `zmart_storage` writes; the slider is then held back by the count the server
    reads off the disk, and the engine never has to change its mind about anything.
    The other **grows**: the array is written with one moment, and its declared
    length is raised as the run goes. `DATA_LAYOUT.md` records a real instrument
    doing exactly this.

    The second shape is the one that needs work from the viewer, and until this test
    nothing covered it. Neuroglancer remembers everything it has ever read about a
    store, with no time limit, so it goes on answering "one moment" from memory and
    the slider cannot reach a frame that exists on disk and reads back perfectly.
    `syncSources` in `engine.js` is what makes it look again, and the tests that
    seemed to cover this all use the first shape — where the engine's answer was
    never going to change, so it did not matter whether it looked.

    Nothing about that failure is loud. The frames are there, the run is fine, and
    the operator simply cannot get to them.
    """
    import http.client

    store = tmp_path / "growing.ome.zarr"
    _write_a_growing_timelapse(store, frames=1)

    server = make_server(port=0, data_dir=tmp_path, site_dir=built_dist, store=store.name)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1200, "height": 900})
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartViewer !== undefined", timeout=30_000)
        # With a single moment there is nothing to step through, so no slider is
        # offered at all — which is right, and is the state this starts from.
        page.wait_for_function(
            "() => (window.zmartConfig?.layers?.[0] || {}).frames === 1", timeout=30_000
        )

        # The run goes on, and the store grows to hold three moments.
        _write_a_growing_timelapse(store, frames=3)
        connection = http.client.HTTPConnection(
            "127.0.0.1", server.server_address[1], timeout=10
        )
        connection.request("POST", "/api/announce", body=b"{}", headers={"Content-Length": "2"})
        assert json.loads(connection.getresponse().read())["told"] >= 1
        connection.close()

        # What the server reads off the disk is the easy half, and it is not what
        # this test is about — but it has to be true before the hard half can be.
        page.wait_for_function(
            "() => (window.zmartConfig?.layers?.[0] || {}).frames === 3", timeout=30_000
        )

        # The hard half: the slider on screen, whose reach comes from the engine's
        # own idea of how long the image is. If the engine never looked again, this
        # stays at one moment however many the server counted.
        page.wait_for_selector("[aria-label='t position']", state="attached", timeout=30_000)
        page.wait_for_function(
            """() => {
              const slider = document.querySelector("[aria-label='t position']");
              return slider && Number(slider.max) - Number(slider.min) === 2;
            }""",
            timeout=30_000,
        )
        reading = page.locator("[aria-label='t position value']").inner_text()
        assert reading.strip().endswith("/ 3"), (
            "the run reached three moments and the slider still offers "
            f"{reading.strip()}, so two of them cannot be reached"
        )
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def _write_a_growing_timelapse(store, *, frames: int) -> None:
    """Write a timelapse that declares exactly the moments it has imaged so far.

    Called again with a larger number, it lengthens the array in place — which is
    what an instrument that does not know how long a run will be actually does. The
    moments already written keep their pixels, because a piece of a zarr image is
    filed under its position and growing the array does not move any of them.
    """
    height = width = 64
    group = zarr.open_group(str(store), mode="a", zarr_format=2)
    if "0" in group:
        array = group["0"]
        array.resize((frames, 1, height, width))
    else:
        array = group.create_array(
            "0", shape=(frames, 1, height, width), chunks=(1, 1, height, width),
            dtype="uint16",
        )
    for frame in range(frames):
        # Each moment gets a different brightness, so a moment that was never
        # written is plainly distinguishable from one that was.
        array[frame] = np.full((1, height, width), 2000 + 500 * frame, dtype=np.uint16)
    store.joinpath(".zattrs").write_text(
        json.dumps(
            {
                "multiscales": [
                    {
                        "version": "0.4",
                        "axes": [
                            {"name": "t", "type": "time", "unit": "second"},
                            {"name": "z", "type": "space", "unit": "micrometer"},
                            {"name": "y", "type": "space", "unit": "micrometer"},
                            {"name": "x", "type": "space", "unit": "micrometer"},
                        ],
                        "datasets": [
                            {
                                "path": "0",
                                "coordinateTransformations": [
                                    {"type": "scale", "scale": [30.0, 2.0, 0.35, 0.35]}
                                ],
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

"""The layer list: napari's shape, driving neuroglancer's state.

Hiding a layer and recolouring it are the two things anyone does within seconds
of opening a multi-channel acquisition. Both are silently ignorable by the
engine if wired wrongly -- a layer can be marked hidden in our own state and
still draw -- so these assert what the engine ended up with, not what the panel
believes.
"""

from __future__ import annotations

import threading

import pytest
from server import make_server

# What the engine ended up holding, read back from the engine itself rather than
# from the panel. The contrast window is deliberately *not* part of the shader
# text: it is a value sent to a program already compiled, so that dragging a
# contrast handle does not make the graphics card build a new program every time.
# It therefore has to be read from the controls rather than from the text.
_ENGINE_LAYERS = """() => window.zmartViewer.state.toJSON().layers.map(l => ({
  name: l.name,
  visible: l.visible !== false,
  opacity: l.opacity ?? 1,
  shader: l.shader || '',
  controls: l.shaderControls || {},
}))"""


def _window_in_engine(page, layer=0):
    """The contrast window the engine is actually drawing that layer with."""
    return page.evaluate(_ENGINE_LAYERS)[layer]["controls"]["normalized"]["range"]


@pytest.fixture(scope="module")
def two_channel_data(tmp_path_factory):
    """Two single-channel stores, written once for all the tests in this file.

    Generating a demo volume takes a good few seconds, and every test here reads
    the same two stores without ever writing to them — so writing them once rather
    than once per test takes most of a minute out of the run and changes nothing
    about what is being tested. Each test still gets its own fresh page and server
    below, which is where the state a test could pollute actually lives.

    One channel per store, and no channel axis inside them: this is the shape a
    mesoSPIM transfer writes, where the channel is identified by the file's name.
    It matters that these are genuinely single-channel — a three-channel volume
    under a name like Ch488 would correctly show three rows, which is not the
    arrangement these tests are about.
    """
    data = tmp_path_factory.mktemp("channels")
    from demo_data import write_demo_zarr

    for name in ("Tile0_Ch488_FltEmpty.ome.zarr", "Tile0_Ch647_FltEmpty.ome.zarr"):
        write_demo_zarr(data / name, single_channel=True)
    return data


@pytest.fixture
def two_channel_page(browser, built_dist, two_channel_data):
    """A fresh page on those two stores, so no test inherits another's settings."""
    data = two_channel_data
    server = make_server(
        port=0,
        data_dir=data,
        site_dir=built_dist,
        store=["Tile0_Ch488_FltEmpty.ome.zarr", "Tile0_Ch647_FltEmpty.ome.zarr"],
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1200, "height": 900})
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartConfig !== undefined", timeout=30_000)
        page.wait_for_function(
            """() => window.zmartViewer.layerManager.managedLayers
              .filter((managed) => managed.name !== "Targets").length === 2""",
            timeout=30_000,
        )
        yield page
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def test_the_panel_lists_every_layer(two_channel_page):
    # One row per channel. The name also appears in the settings block above the
    # list, naming the channel being adjusted, so the rows are counted by the
    # control that only a row has.
    assert two_channel_page.locator("[aria-label='toggle Ch488']").count() == 1
    assert two_channel_page.locator("[aria-label='toggle Ch647']").count() == 1


def test_channels_arrive_green_and_magenta(two_channel_page):
    shaders = [layer["shader"] for layer in two_channel_page.evaluate(_ENGINE_LAYERS)]
    assert "vec3(0, 1, 0.4)" in shaders[0], "488 should be green"
    assert "vec3(1, 0.2, 1)" in shaders[1], "647 should be magenta"


def test_hiding_a_layer_hides_it_in_the_engine(two_channel_page):
    two_channel_page.click("[aria-label='toggle Ch488']")
    two_channel_page.wait_for_timeout(800)
    layers = two_channel_page.evaluate(_ENGINE_LAYERS)
    assert layers[0]["visible"] is False
    assert layers[1]["visible"] is True, "hiding one layer must not affect the other"


def test_showing_it_again_restores_it(two_channel_page):
    two_channel_page.click("[aria-label='toggle Ch488']")
    two_channel_page.wait_for_timeout(500)
    two_channel_page.click("[aria-label='toggle Ch488']")
    two_channel_page.wait_for_timeout(800)
    assert two_channel_page.evaluate(_ENGINE_LAYERS)[0]["visible"] is True


def test_recolouring_a_layer_reaches_the_shader(two_channel_page):
    two_channel_page.click("[aria-label='colour Ch488']")
    two_channel_page.click("[aria-label='cyan for Ch488']")
    two_channel_page.wait_for_timeout(800)
    shader = two_channel_page.evaluate(_ENGINE_LAYERS)[0]["shader"]
    assert "vec3(0.2, 0.8, 1)" in shader


def test_colour_survives_the_three_d_toggle(two_channel_page):
    """Mode switching rebuilds the shaders; a chosen colour must not be lost."""
    two_channel_page.click("[aria-label='colour Ch488']")
    two_channel_page.click("[aria-label='cyan for Ch488']")
    two_channel_page.wait_for_timeout(500)
    two_channel_page.click("text=3D")
    two_channel_page.wait_for_timeout(1500)
    shader = two_channel_page.evaluate(_ENGINE_LAYERS)[0]["shader"]
    assert "emitRGBA" in shader
    assert "0.2, 0.8, 1" in shader


def test_visibility_survives_the_three_d_toggle(two_channel_page):
    two_channel_page.click("[aria-label='toggle Ch647']")
    two_channel_page.wait_for_timeout(500)
    two_channel_page.click("text=3D")
    two_channel_page.wait_for_timeout(1500)
    assert two_channel_page.evaluate(_ENGINE_LAYERS)[1]["visible"] is False


def _choose(page, channel: str) -> None:
    """Pick a channel out in the list, so the one block of controls acts on it.

    There is a single set of controls, shared, the way napari does it — so a test
    that wants to adjust a particular channel has to select it first, exactly as an
    operator would. Selecting the one already selected is harmless.
    """
    page.locator(f"[aria-label='toggle {channel}']").locator("xpath=../..").click()
    page.wait_for_timeout(250)


def _set_range(page, label: str, value: float) -> None:
    page.locator(f"[aria-label='{label}']").evaluate(
        """(element, value) => {
          // React tracks controlled input values by installing an own-property
          // setter. Use the platform setter, as a real range-thumb movement
          // does, so the subsequent input event is observed as a change.
          const setter = Object.getOwnPropertyDescriptor(
            HTMLInputElement.prototype, 'value'
          ).set;
          setter.call(element, String(value));
          element.dispatchEvent(new Event('input', { bubbles: true }));
        }""",
        value,
    )


def test_contrast_handles_reach_the_engine(two_channel_page):
    _set_range(two_channel_page, "black Ch488", 1200)
    _set_range(two_channel_page, "white Ch488", 9000)
    two_channel_page.wait_for_timeout(800)
    assert _window_in_engine(two_channel_page) == [1200, 9000]


def test_moving_contrast_does_not_rebuild_the_shader(two_channel_page):
    """The program on the graphics card must not change when contrast does.

    This is the whole reason the window is sent as a control rather than written
    into the shader text. If the text changed, the engine would compile a new
    program for every layer on every step of the drag — which on a large
    acquisition is a visible stutter every time anyone adjusts the brightness.
    """
    before = two_channel_page.evaluate(_ENGINE_LAYERS)[0]["shader"]
    _set_range(two_channel_page, "black Ch488", 1300)
    _set_range(two_channel_page, "white Ch488", 7000)
    two_channel_page.wait_for_timeout(800)
    after = two_channel_page.evaluate(_ENGINE_LAYERS)[0]["shader"]
    assert after == before, "the contrast window leaked back into the shader text"
    assert _window_in_engine(two_channel_page) == [1300, 7000]


def test_contrast_survives_the_three_d_toggle(two_channel_page):
    _set_range(two_channel_page, "black Ch488", 1500)
    _set_range(two_channel_page, "white Ch488", 8000)
    two_channel_page.wait_for_timeout(500)
    two_channel_page.click("text=3D")
    two_channel_page.wait_for_timeout(1500)
    assert _window_in_engine(two_channel_page) == [1500, 8000]
    assert "emitRGBA" in two_channel_page.evaluate(_ENGINE_LAYERS)[0]["shader"]


def test_opacity_reaches_the_plane_layer(two_channel_page):
    _set_range(two_channel_page, "opacity Ch488", 0.37)
    two_channel_page.wait_for_timeout(800)
    opacity = two_channel_page.evaluate(_ENGINE_LAYERS)[0]["opacity"]
    assert opacity == pytest.approx(0.37)


def test_opacity_survives_the_three_d_toggle(two_channel_page):
    _set_range(two_channel_page, "opacity Ch488", 0.42)
    two_channel_page.wait_for_timeout(500)
    two_channel_page.click("text=3D")
    two_channel_page.wait_for_timeout(1500)
    layer = two_channel_page.evaluate(_ENGINE_LAYERS)[0]
    # In the volume the intensity drives transparency, so opacity is part of what
    # the shader computes -- but its value, like the contrast window, is sent as a
    # control rather than written into the program.
    assert "normalized() * opacity" in layer["shader"]
    assert layer["controls"]["opacity"] == pytest.approx(0.42)


def test_each_layer_shows_its_measured_histogram(two_channel_page):
    """Each channel has its own measured histogram, shown when it is selected.

    There is one histogram on screen rather than one per row, because there is one
    block of controls; selecting a channel is what brings its own measurement up.
    """
    assert two_channel_page.locator("[aria-label='histogram Ch488']").count() == 1
    _choose(two_channel_page, "Ch647")
    assert two_channel_page.locator("[aria-label='histogram Ch647']").count() == 1
    assert two_channel_page.locator("[aria-label='histogram Ch488']").count() == 0


def test_auto_contrast_restores_the_measured_window(two_channel_page):
    _choose(two_channel_page, "Ch488")
    _set_range(two_channel_page, "black Ch488", 1200)
    _set_range(two_channel_page, "white Ch488", 9000)
    two_channel_page.click("[aria-label='auto contrast Ch488']")
    two_channel_page.wait_for_timeout(800)
    expected = two_channel_page.evaluate(
        "() => window.zmartConfig.layers[0].histogram.autoWindow"
    )
    actual = two_channel_page.evaluate("() => window.zmartLayerState[0].window")
    assert actual == expected
    # Compared loosely on purpose: the engine writes the window out with fewer
    # decimal places than the measurement carries, and a fraction of one count of
    # brightness is far below anything an eye could see.
    low, high = _window_in_engine(two_channel_page)
    assert low == pytest.approx(expected["low"], abs=0.05)
    assert high == pytest.approx(expected["high"], abs=0.05)

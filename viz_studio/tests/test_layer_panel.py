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
    assert "0, 1, 0.4" in shaders[0], "488 should be green"
    assert "1, 0.2, 1" in shaders[1], "647 should be magenta"


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
    assert "0.2, 0.8, 1" in shader


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


def test_the_histogram_of_the_chosen_channel_is_the_one_on_screen(two_channel_page):
    """Whichever channel is picked out, its histogram is the one being shown.

    There is one histogram on screen rather than one per row, because there is one
    block of controls; selecting a channel is what brings its own up. This checks
    only that the right one *appears* — whether the bars in it really come from the
    measurement is the next test, and the two are separate because they can fail
    separately.
    """
    assert two_channel_page.locator("[aria-label='histogram Ch488']").count() == 1
    _choose(two_channel_page, "Ch647")
    assert two_channel_page.locator("[aria-label='histogram Ch647']").count() == 1
    assert two_channel_page.locator("[aria-label='histogram Ch488']").count() == 0


# The bars of the histogram, read back off the drawing itself.
#
# Three kinds of rectangle are drawn in that little picture and only one of them
# is a bar: there is also the shaded band showing the chosen window, and two thin
# lines marking its edges. The bars are the ones drawn in the text colour, and
# that is what picks them out here. Width would nearly always work as well — a bar
# is exactly one unit wide — but "nearly always" is the wrong standard for a
# measurement: a window happening to cover exactly one bin would make the band one
# unit wide too, and it would then be counted as a bar and quietly shift every
# reading by one.
_HISTOGRAM_BARS = """(label) => Array.from(
  document.querySelector(`[aria-label="${label}"]`).querySelectorAll("rect"),
).filter((bar) => bar.getAttribute("fill") === "currentColor")
 .map((bar) => Number(bar.getAttribute("height")))"""


def test_the_bars_on_screen_are_the_brightness_the_server_measured(two_channel_page):
    """The histogram must be a picture of this channel, not a decoration.

    The histogram is the one thing in the panel that answers a question a
    microscopist really asks — is this channel saturating, or is it sitting on
    background? An operator reads it and decides whether the acquisition is worth
    keeping. So it is worth checking that the shape drawn on screen is the shape
    the server measured, and not merely that a drawing appeared.

    That distinction has caught this project out before, in the writer: a whole
    group of tests proved the pictures landed in the right places and proved almost
    nothing about whether the description of them was truthful. The check just above
    was in exactly that shape — it asked whether a histogram was present and never
    looked inside it.

    Two things are compared, and neither repeats the drawing's own arithmetic. There
    must be one bar per measured bin. And the bars must rise and fall where the
    measurement does: the tallest bar has to sit over the fullest bin, and a bar of
    no height has to sit over every bin that counted nothing.
    """
    measured = two_channel_page.evaluate(
        "() => window.zmartConfig.layers[0].histogram.counts"
    )
    drawn = two_channel_page.evaluate(_HISTOGRAM_BARS, "histogram Ch488")
    assert len(drawn) == len(measured), "one bar per measured bin"
    assert drawn.index(max(drawn)) == measured.index(max(measured)), (
        "the tallest bar is not over the fullest bin, so the drawing is not this "
        "channel's measurement"
    )
    assert [at for at, height in enumerate(drawn) if height == 0] == [
        at for at, count in enumerate(measured) if count == 0
    ], "the empty bins on screen are not the ones the measurement found empty"


def test_the_contrast_handles_travel_over_the_brightness_that_is_really_there(
    two_channel_page,
):
    """The black and white sliders must be usable, not merely present.

    This is the one control in the panel that is judged by feel rather than by
    whether it works, and it is worth a test because "works" and "usable" came
    apart badly here once. The handles used to travel over the whole range a
    16-bit camera can produce, nought to 65535. Every one of them still moved, and
    every window still reached the engine — so nothing in the suite noticed. But a
    real acquisition occupies a narrow band of that range, a few hundred counts of
    background with the signal just above, and across a track a few centimetres
    wide the whole useful part was about two pixels of travel. One pixel of
    movement jumped the brightness by hundreds of counts. In practice the only
    control anybody could use was the Auto button.

    So the track is taken from the spread of brightness the server measured, with
    room to spare at each end. What is checked here is that it really is: the
    distance the handles may travel has to be of the order of the measured spread
    rather than of the camera's whole range.

    The demo volume sits in a few thousand counts, so a track that still ran to
    65535 would be more than ten times too wide — which is why a generous factor
    of four is enough to tell the two apart, and keeps this from being a test about
    the exact amount of room left at the ends.
    """
    measured = two_channel_page.evaluate(
        "() => window.zmartConfig.layers[0].histogram"
    )
    spread = measured["high"] - measured["low"]
    assert spread > 0, "the demo volume must have some spread to measure"

    track = two_channel_page.evaluate(
        """() => {
          const handle = document.querySelector("[aria-label='black Ch488']");
          return { min: Number(handle.min), max: Number(handle.max) };
        }"""
    )
    room = track["max"] - track["min"]
    assert room < spread * 4, (
        f"the handles travel over {room:.0f} counts while the brightness in this "
        f"channel spans {spread:.0f}, so the useful part of the track is a few "
        "pixels wide and only the Auto button is any use"
    )
    assert room >= spread, (
        f"the handles travel over only {room:.0f} counts while the brightness "
        f"spans {spread:.0f}, so part of the measured range cannot be reached"
    )


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

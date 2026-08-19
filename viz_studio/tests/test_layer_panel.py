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
    """The colour is chosen in the display settings, not on the row.

    The palette dots sit with the other settings for the selected channel;
    the little swatch on the row only *shows* the choice. One place to
    change it, every place reflecting it.
    """
    two_channel_page.get_by_label("lookup table Ch488").select_option("flat:cyan")
    two_channel_page.wait_for_timeout(800)
    shader = two_channel_page.evaluate(_ENGINE_LAYERS)[0]["shader"]
    assert "0.2, 0.8, 1" in shader


def test_the_row_swatch_shows_the_choice_and_is_not_a_control(two_channel_page):
    """The swatch beside the channel's name follows the palette."""
    two_channel_page.get_by_label("lookup table Ch488").select_option("flat:cyan")
    two_channel_page.wait_for_timeout(500)
    swatch = two_channel_page.locator("[aria-label='colour Ch488']")
    background = swatch.evaluate("(el) => getComputedStyle(el).backgroundColor")
    assert background == "rgb(51, 204, 255)", (
        f"the row swatch shows {background}, not the cyan just chosen"
    )
    assert swatch.evaluate("(el) => el.tagName") != "BUTTON", (
        "the swatch is a read-out; choosing the colour lives in the display "
        "settings"
    )
    # And a chosen colour MAP shows on the swatch too, as its own gradient --
    # the swatch always mirrors the one lookup-table control.
    two_channel_page.get_by_label("lookup table Ch488").select_option("viridis")
    two_channel_page.wait_for_timeout(500)
    background = swatch.evaluate("(el) => getComputedStyle(el).backgroundImage")
    assert "gradient" in background, (
        f"the swatch shows {background!r}, not the chosen colour map"
    )


def test_colour_survives_the_three_d_toggle(two_channel_page):
    """Mode switching rebuilds the shaders; a chosen colour must not be lost."""
    two_channel_page.get_by_label("lookup table Ch488").select_option("flat:cyan")
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
    _set_range(two_channel_page, "min Ch488", 1200)
    _set_range(two_channel_page, "max Ch488", 9000)
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
    _set_range(two_channel_page, "min Ch488", 1300)
    _set_range(two_channel_page, "max Ch488", 7000)
    two_channel_page.wait_for_timeout(800)
    after = two_channel_page.evaluate(_ENGINE_LAYERS)[0]["shader"]
    assert after == before, "the contrast window leaked back into the shader text"
    assert _window_in_engine(two_channel_page) == [1300, 7000]


def test_contrast_survives_the_three_d_toggle(two_channel_page):
    _set_range(two_channel_page, "min Ch488", 1500)
    _set_range(two_channel_page, "max Ch488", 8000)
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
    assert "float v = normalized();" in layer["shader"]
    assert "v * opacity" in layer["shader"]
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
    """The min and max sliders must be usable, not merely present.

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
          const handle = document.querySelector("[aria-label='min Ch488']");
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
    _set_range(two_channel_page, "min Ch488", 1200)
    _set_range(two_channel_page, "max Ch488", 9000)
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


def test_the_saturation_bars_in_the_histogram_can_be_dragged(two_channel_page):
    """The two bars in the histogram ARE the window, and they drag.

    The left bar marks where black begins (everything dimmer saturates to
    black), the right bar where white begins (everything brighter saturates
    to white). Taking hold near a bar and pulling moves that edge of the
    window -- the same window the MIN and MAX sliders move -- and the far
    edge must hold still while its partner is being dragged.
    """
    page = two_channel_page
    before = _window_in_engine(page)
    box = page.locator("[aria-label='histogram Ch488']").bounding_box()
    middle = box["y"] + box["height"] / 2

    # Take hold near the left bar and pull right: the floor rises.
    page.mouse.move(box["x"] + box["width"] * 0.05, middle)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] * 0.4, middle, steps=6)
    page.mouse.up()
    page.wait_for_timeout(600)
    lifted = _window_in_engine(page)
    assert lifted[0] > before[0], (
        "dragging the left bar right must raise the black point"
    )
    assert lifted[1] == pytest.approx(before[1]), (
        "the white point must hold still while the black point is dragged"
    )

    # And the other side: take hold near the right bar and pull left.
    page.mouse.move(box["x"] + box["width"] * 0.95, middle)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] * 0.6, middle, steps=6)
    page.mouse.up()
    page.wait_for_timeout(600)
    lowered = _window_in_engine(page)
    assert lowered[1] < lifted[1], (
        "dragging the right bar left must lower the white point"
    )
    assert lowered[0] == pytest.approx(lifted[0]), (
        "the black point must hold still while the white point is dragged"
    )


def test_the_histogram_dims_the_brightness_outside_the_window(two_channel_page):
    """What saturates is dimmed; what reaches the screen is drawn at full light.

    The part of the brightness spread between the two bars is what the display
    ramp is spent on; everything outside it clips to black or white. The
    histogram says so at a glance by drawing the inside bars at full opacity
    and the outside ones dimmed -- the picture of the window, not just marks
    on it.
    """
    page = two_channel_page
    # Push the black point well into the distribution, so bars exist on both
    # sides of it.
    box = page.locator("[aria-label='histogram Ch488']").bounding_box()
    middle = box["y"] + box["height"] / 2
    page.mouse.move(box["x"] + box["width"] * 0.05, middle)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] * 0.5, middle, steps=6)
    page.mouse.up()
    page.wait_for_timeout(600)

    opacities = page.evaluate(
        """() => Array.from(
          document.querySelector('[aria-label="histogram Ch488"]')
            .querySelectorAll('rect'),
        ).filter((bar) => bar.getAttribute('fill') === 'currentColor')
         .map((bar) => Number(bar.getAttribute('opacity') ?? 1))"""
    )
    distinct = sorted(set(opacities))
    assert len(distinct) == 2, (
        f"expected dimmed and full bars, saw opacities {distinct} -- the "
        "histogram is not showing which brightness reaches the screen"
    )
    dimmed, full = distinct
    assert full == 1 and dimmed < 1
    # The dimmed bars sit at the edges, the full ones in one middle stretch.
    inside = [opacity == full for opacity in opacities]
    first, last = inside.index(True), len(inside) - 1 - inside[::-1].index(True)
    assert all(inside[first:last + 1]), (
        "the full-brightness stretch must be contiguous -- it is the window"
    )
    assert first > 0, "bars below the black point must be dimmed"


def test_the_histogram_axis_can_be_switched_between_linear_and_log(two_channel_page):
    """A skewed channel can spread its dim end out; the choice is explicit.

    Fluorescence often piles most of its brightness near background with a
    long tail, and on a linear axis that reads as everything bunched left.
    The log axis stretches the dim end and compresses the tail. It is a
    visible toggle rather than a rule guessed from bit depth, because the
    skew is a property of the specimen's distribution, not of the container
    the camera writes.

    On the linear axis every bin is drawn one unit wide; on the log axis the
    dim bins widen and the bright ones narrow, so the drawing itself is what
    is checked, before and after and back again.
    """
    page = two_channel_page
    widths = lambda: page.evaluate(  # noqa: E731 -- a tiny page probe
        """() => Array.from(
          document.querySelector('[aria-label="histogram Ch488"]')
            .querySelectorAll('rect'),
        ).filter((bar) => bar.getAttribute('fill') === 'currentColor')
         .map((bar) => Number(bar.getAttribute('width')))"""
    )
    linear = widths()
    assert max(linear) - min(linear) < 1e-6, "the linear axis draws equal bins"

    page.get_by_label("logarithmic brightness axis").click()
    page.wait_for_timeout(300)
    logged = widths()
    assert logged[0] > logged[-1], (
        "on the log axis the dim bins must widen and the bright ones narrow"
    )

    # The bars still drag correctly under the warped axis: the engine's
    # window moves, through the log mapping and back.
    before = _window_in_engine(page)
    box = page.locator("[aria-label='histogram Ch488']").bounding_box()
    middle = box["y"] + box["height"] / 2
    page.mouse.move(box["x"] + box["width"] * 0.05, middle)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] * 0.5, middle, steps=6)
    page.mouse.up()
    page.wait_for_timeout(600)
    assert _window_in_engine(page)[0] > before[0]

    page.get_by_label("linear brightness axis").click()
    page.wait_for_timeout(300)
    back = widths()
    assert max(back) - min(back) < 1e-6, "switching back restores equal bins"


def test_the_numbers_beside_the_sliders_can_be_typed_into(two_channel_page):
    """The value beside a slider is a box, not just a read-out.

    An operator who knows the counts they want should be able to type them.
    Typing commits on Enter (or on leaving the box); sliding still updates
    the number, because box and slider describe the same window.
    """
    page = two_channel_page
    box = page.locator("[aria-label='min value Ch488']")
    box.fill("1234")
    box.press("Enter")
    page.wait_for_timeout(600)
    assert _window_in_engine(page)[0] == pytest.approx(1234), (
        "a typed minimum must reach the engine like a slid one"
    )

    # And the other direction: sliding updates the box.
    page.evaluate(
        """() => {
          const slider = document.querySelector('[aria-label="min Ch488"]');
          const setter = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype, 'value').set;
          setter.call(slider, String(Number(slider.min) + 1));
          slider.dispatchEvent(new Event('input', { bubbles: true }));
          slider.dispatchEvent(new Event('change', { bubbles: true }));
        }"""
    )
    page.wait_for_timeout(600)
    assert box.input_value() != "1234", "sliding must update the number box"


def test_a_lit_auto_with_nothing_to_restore_says_so(browser, built_dist,
                                                    tmp_path):
    """A run that declared no window rests on the measured one, Auto lit.

    The lit light means "the window is the measured one", and clicking it
    puts back the window the run itself declared. A run that declared
    nothing is SERVED the measured window as its window, so the lit button
    used to offer a toggle between two equal values: clicking it visibly
    did nothing, and the operator reasonably reported a button that cannot
    be un-clicked (found with a real 336-well plate, 2026-08-19). With
    nothing to restore the button now rests disabled, and its tooltip says
    the run declared no other window.
    """
    import json

    import numpy as np
    import zarr

    quiet = tmp_path / "unspoken"
    quiet.mkdir()
    store = quiet / "overview_pos001.ome.zarr"
    store.mkdir()
    group = zarr.open_group(str(store), mode="w", zarr_format=2)
    values = (np.random.default_rng(7).integers(90, 400, (1, 4, 64, 64))
              .astype(np.uint16))
    group.create_array("0", shape=values.shape, chunks=(1, 1, 64, 64),
                       dtype="uint16")[:] = values
    (store / ".zattrs").write_text(json.dumps({
        "multiscales": [{
            "version": "0.4",
            "axes": [{"name": "c", "type": "channel"},
                     {"name": "z", "type": "space", "unit": "micrometer"},
                     {"name": "y", "type": "space", "unit": "micrometer"},
                     {"name": "x", "type": "space", "unit": "micrometer"}],
            "datasets": [{"path": "0", "coordinateTransformations": [
                {"type": "scale", "scale": [1.0, 2.0, 0.35, 0.35]}]}],
        }],
        "omero": {"channels": [{"label": "ch0", "color": "00FF66"}]},
    }), encoding="utf-8")
    server = make_server(port=0, data_dir=quiet, site_dir=built_dist,
                         store="overview_pos001.ome.zarr")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1200, "height": 900})
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}",
                  wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartConfig !== undefined",
                               timeout=30_000)
        auto = page.locator("[aria-label='auto contrast ch0']")
        auto.wait_for(timeout=10_000)
        assert auto.get_attribute("aria-pressed") == "true", (
            "with no declared window the channel rests on the measured one, "
            "so the light must be on"
        )
        assert auto.is_disabled(), (
            "lit with nothing to restore, the button must rest rather than "
            "offer a toggle between two equal windows"
        )
        assert "declared no other" in (auto.get_attribute("title") or ""), (
            "the tooltip must say why there is nothing to click"
        )
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)

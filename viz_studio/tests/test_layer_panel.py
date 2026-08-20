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


def _pick_colormap(page, channel, name):
    """Choose what a channel is painted with, the way an operator does.

    The chooser is a small list rather than a dropdown, because every entry
    shows its own colour beside its name and a dropdown can only offer words.
    So this opens it and presses an entry.
    """
    page.locator(f"[aria-label='colormap {channel}']").click()
    page.wait_for_timeout(200)
    page.locator(f"[aria-label='{name} for {channel}']").click()
    page.wait_for_timeout(600)


def _colormap_now(page, channel):
    """What the chooser says the channel is painted with."""
    return page.locator(f"[aria-label='colormap {channel}']").inner_text().strip()


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
    """The wavelength decides the colour, and the colour travels as a value.

    Read from the controls rather than from the program's text: a colour is a
    number handed to a program the engine has already compiled, exactly as the
    contrast window is, so nothing about a channel's colour appears in the
    text at all.
    """
    held = [layer["controls"] for layer in two_channel_page.evaluate(_ENGINE_LAYERS)]
    assert held[0]["color"] == "#00ff66", "488 should be green"
    assert held[1]["color"] == "#ff33ff", "647 should be magenta"


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
    before = two_channel_page.evaluate(_ENGINE_LAYERS)[0]["shader"]
    _pick_colormap(two_channel_page, "Ch488", "cyan")
    layer = two_channel_page.evaluate(_ENGINE_LAYERS)[0]
    assert layer["controls"]["color"] == "#33ccff"
    assert layer["shader"] == before, (
        "a colour is a number sent to the program, so choosing one must not "
        "rewrite the program"
    )


def test_the_row_swatch_shows_the_choice_and_is_not_a_control(two_channel_page):
    """The swatch beside the channel's name follows the palette."""
    _pick_colormap(two_channel_page, "Ch488", "cyan")
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
    _pick_colormap(two_channel_page, "Ch488", "viridis")
    background = swatch.evaluate("(el) => getComputedStyle(el).backgroundImage")
    assert "gradient" in background, (
        f"the swatch shows {background!r}, not the chosen colour map"
    )


def test_colour_survives_the_three_d_toggle(two_channel_page):
    """Mode switching rebuilds the shaders; a chosen colour must not be lost."""
    _pick_colormap(two_channel_page, "Ch488", "cyan")
    two_channel_page.click("text=3D")
    two_channel_page.wait_for_timeout(1500)
    layer = two_channel_page.evaluate(_ENGINE_LAYERS)[0]
    assert "emitRGBA" in layer["shader"]
    assert layer["controls"]["color"] == "#33ccff"


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
    """The channel's own weight carries the fade, and carries it once.

    Channels of one picture are ADDED to each other, and an added row
    contributes exactly the colour its program emits -- so the weight belongs
    in that colour and the transparency the engine blends with stays at one.
    Carried in both, as it once was, a channel faded as its own setting
    squared: a half read a quarter.
    """
    _set_range(two_channel_page, "opacity Ch488", 0.37)
    two_channel_page.wait_for_timeout(800)
    layer = two_channel_page.evaluate(_ENGINE_LAYERS)[0]
    assert layer["controls"]["weight"] == pytest.approx(0.37)
    assert layer["opacity"] == pytest.approx(1.0), (
        "an added row must not fade a second time through its transparency"
    )


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
    assert "v * weight" in layer["shader"]
    assert layer["controls"]["weight"] == pytest.approx(0.42)


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
    # The box spans the camera's whole range now, not the window, so where a
    # bar sits on screen follows from its value's place on that axis.
    axis = page.evaluate(
        "() => Number(document.querySelector(\"[aria-label='min Ch488']\").max)"
    )
    def across(value):
        return box["x"] + box["width"] * (value / axis)

    low0, high0 = before
    reach = (high0 - low0) * 0.3

    # Take hold near the left bar and pull right: the floor rises.
    page.mouse.move(across(low0 + reach * 0.05), middle)
    page.mouse.down()
    page.mouse.move(across(low0 + reach), middle, steps=6)
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
    page.mouse.move(across(high0 - reach * 0.05), middle)
    page.mouse.down()
    page.mouse.move(across(high0 - reach), middle, steps=6)
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
    # sides of it. The box spans the camera's whole range, so the drag's
    # coordinates come from values, not from fractions of the box.
    box = page.locator("[aria-label='histogram Ch488']").bounding_box()
    middle = box["y"] + box["height"] / 2
    axis = page.evaluate(
        "() => Number(document.querySelector(\"[aria-label='min Ch488']\").max)"
    )
    hist = page.evaluate("() => window.zmartConfig.layers[0].histogram")
    low0 = _window_in_engine(page)[0]
    def across(value):
        return box["x"] + box["width"] * (value / axis)
    page.mouse.move(across(low0 + (hist["high"] - low0) * 0.02), middle)
    page.mouse.down()
    page.mouse.move(across((hist["low"] + hist["high"]) / 2), middle, steps=6)
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


def test_a_lit_auto_turns_off_to_the_cameras_whole_range(browser, built_dist,
                                                         tmp_path):
    """A run that declared no window rests on the measured one, Auto lit --
    and clicking the lit light spreads the window over the camera's range.

    The light means "the window is the measured one". Clicking it off puts
    back the window the run declared; a run that declared nothing has no
    such window, and for a while the button then rested disabled -- which
    the operator met as a button that cannot be un-clicked. Off now means
    what it does everywhere else in microscopy: everything shown, nothing
    clipped, the window spread over the whole range the camera can write
    (asked for at the workstation, 2026-08-19). Auto lights again on the
    next click, so the two states genuinely toggle.
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
        assert auto.is_enabled(), (
            "the lit light must offer its off state: the camera's whole range"
        )
        auto.click()
        page.wait_for_timeout(600)
        spread = page.evaluate("() => window.zmartLayerState[0].window")
        assert spread == {"low": 0, "high": 65535}, (
            f"Auto off must spread the window over the camera's range, "
            f"not {spread}"
        )
        assert auto.get_attribute("aria-pressed") == "false", (
            "spread over the camera's range, the window is no longer the "
            "measured one, so the light goes out"
        )
        auto.click()
        page.wait_for_timeout(600)
        assert auto.get_attribute("aria-pressed") == "true", (
            "clicking again re-applies the measurement: a true toggle"
        )
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def test_channels_of_one_picture_blend_like_light(browser, built_dist,
                                                  tmp_path):
    """Channel rows of one picture sum additively; stitched rows still cover.

    On a real four-channel plate the top channel's coverage alpha hid the
    other three completely -- recolouring them changed not one pixel -- so
    the operator asked for the merge every fluorescence viewer does:
    channels sum like light (2026-08-19). Additive is safe exactly when a
    row has ONE source. The engine blends each source as its own pass, so
    a row stitched from many tiles would sum its overlaps into bright
    seams -- the recorded reason additive was once rejected -- and such
    rows must keep the covering rule, including a live row that started
    as one source and grew.
    """
    from test_a_dataset_is_relived_as_a_live_run import _post
    from test_open_and_close import _store

    channels = tmp_path / "twochannel"
    channels.mkdir()
    _store(channels / "overview_pos001.ome.zarr", channels=2)
    stitched = tmp_path / "stitched"
    stitched.mkdir()
    _store(stitched / "overview_pos001.ome.zarr", channels=1)
    _store(stitched / "overview_pos002.ome.zarr", channels=1)
    server = make_server(port=0, data_dir=channels, site_dir=built_dist,
                         store="overview_pos001.ome.zarr")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1200, "height": 900})
    try:
        address = f"http://127.0.0.1:{server.server_address[1]}"
        page.goto(address, wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartConfig !== undefined",
                               timeout=30_000)
        status, _ = _post(address, "/api/stores/open", {"path": str(stitched)})
        assert status == 200
        page.wait_for_function(
            "() => window.zmartConfig.groups.includes('stitched')",
            timeout=30_000)
        page.wait_for_timeout(800)
        blends = page.evaluate("""() => {
            const said = {};
            for (const m of window.zmartViewer.layerManager.managedLayers) {
              if (m.layer?.type !== 'image') continue;
              const sources = (m.layer.dataSources || []).length;
              said[m.name] = {sources, blend: m.layer.blendMode.value};
            }
            return said;
        }""")
        # BLEND_MODES: 0 is the covering default, 1 is additive.
        for name, told in blends.items():
            if told["sources"] == 1:
                assert told["blend"] == 1, (
                    f"{name} is one source and must blend additively, so "
                    "every channel of the picture reaches the screen"
                )
            else:
                assert told["blend"] == 0, (
                    f"{name} is stitched from {told['sources']} sources and "
                    "must keep the covering rule, or tile overlaps sum into "
                    "bright seams"
                )
        kinds = {told["sources"] > 1 for told in blends.values()}
        assert kinds == {True, False}, (
            f"the gate needs both a single-source and a stitched row to "
            f"mean anything; saw {blends}"
        )
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def test_the_colour_control_is_called_a_colormap(two_channel_page):
    """The control says what a microscopist calls it.

    "Lookup table" is what the graphics literature calls it and what nobody at
    a microscope says. The word an operator uses is colormap, and a control
    named for the implementation is a control they have to translate before
    they can use it.
    """
    page = two_channel_page
    assert page.locator("[aria-label='colormap Ch488']").count() == 1
    # Spelled out of one piece so that a later sweep renaming the control
    # cannot quietly rewrite the very name this line exists to forbid.
    old_name = " ".join(["lookup", "table", "Ch488"])
    assert page.locator(f"[aria-label='{old_name}']").count() == 0, (
        "the old name is still on the page, so there are two names for one thing"
    )
    assert "colormap" in page.locator("text=colormap").first.inner_text().lower()


def test_a_channel_can_be_painted_any_colour_at_all(two_channel_page):
    """A colour picker beside the chooser, so the named list is not the limit.

    Six named colours are a quick pick, not the whole of what a specimen might
    need -- and on a picture of many channels the named list runs out long
    before the channels do. The preview beside the chooser is the button: it
    shows what the channel is painted with now, and opens the picker.
    """
    page = two_channel_page
    picker = page.locator("[aria-label='choose a colour for Ch488']")
    assert picker.count() == 1, "there is no way to choose a colour of one's own"
    picker.evaluate("""(element) => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype, 'value').set;
      setter.call(element, '#ff8800');
      element.dispatchEvent(new Event('input', { bubbles: true }));
      element.dispatchEvent(new Event('change', { bubbles: true }));
    }""")
    page.wait_for_timeout(800)
    held = page.evaluate(_ENGINE_LAYERS)[0]["controls"]["color"]
    assert held == "#ff8800", (
        f"the channel is painted {held}, not the colour that was picked"
    )


def test_picking_a_colour_puts_aside_the_colour_map(two_channel_page):
    """A colour chosen by hand replaces a map, rather than fighting it.

    A channel painted through a map has no flat colour, so a picked colour has
    to end the map -- otherwise the preview goes on showing a run of colours
    the channel is no longer painted in, and the operator has two answers to
    one question.
    """
    page = two_channel_page
    _pick_colormap(page, "Ch488", "viridis")
    assert "zmartLut" in page.evaluate(_ENGINE_LAYERS)[0]["shader"]
    page.locator("[aria-label='choose a colour for Ch488']").evaluate("""(element) => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype, 'value').set;
      setter.call(element, '#22ddaa');
      element.dispatchEvent(new Event('input', { bubbles: true }));
      element.dispatchEvent(new Event('change', { bubbles: true }));
    }""")
    page.wait_for_timeout(800)
    layer = page.evaluate(_ENGINE_LAYERS)[0]
    assert "zmartLut" not in layer["shader"], "the colour map is still painting"
    assert layer["controls"]["color"] == "#22ddaa"


def test_red_is_among_the_named_colours(two_channel_page):
    """The colour a microscopist reaches for first was not on the list."""
    page = two_channel_page
    page.locator("[aria-label='colormap Ch488']").click()
    page.wait_for_timeout(200)
    assert page.locator("[aria-label='red for Ch488']").count() == 1, (
        "red is not among the colours a channel can be painted"
    )


def test_a_picked_colour_is_never_shown_under_a_name_it_is_not(two_channel_page):
    """The chooser says "picked", rather than the nearest name in its list.

    A select whose value matches none of its options shows the FIRST one, so a
    channel painted a hand-picked red read as "green" while being red -- seen
    on the plate, 2026-08-20. The panel may not tell an operator they chose
    something they did not.
    """
    page = two_channel_page
    page.locator("[aria-label='choose a colour for Ch488']").evaluate("""(element) => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype, 'value').set;
      setter.call(element, '#ff3b30');
      element.dispatchEvent(new Event('input', { bubbles: true }));
      element.dispatchEvent(new Event('change', { bubbles: true }));
    }""")
    page.wait_for_timeout(800)
    assert _colormap_now(page, "Ch488").startswith("picked"), (
        "the chooser is showing a named colour for a colour picked by hand"
    )
    assert page.evaluate(_ENGINE_LAYERS)[0]["controls"]["color"] == "#ff3b30"


def test_every_entry_shows_the_colour_it_would_paint(two_channel_page):
    """A colour beside every name, so the choice is made by eye.

    The names of the colour maps mean nothing until you have seen one, which
    is why they used to carry a sentence apiece -- "magma (black to purple to
    cream)". Showing each map as itself says it better and in less room, and
    it is the only way to choose a colour without trying it first.
    """
    page = two_channel_page
    page.locator("[aria-label='colormap Ch488']").click()
    page.wait_for_timeout(250)
    for name in ("green", "red", "viridis", "magma"):
        entry = page.locator(f"[aria-label='{name} for Ch488']")
        assert entry.count() == 1, f"{name} is not offered"
        painted = entry.locator("span").first.evaluate(
            "(el) => getComputedStyle(el).backgroundImage + '|' + "
            "getComputedStyle(el).backgroundColor")
        assert "gradient" in painted or "rgb" in painted, (
            f"the entry for {name} shows no colour of its own: {painted}"
        )
    # And the explanations that stood in for those colours are gone.
    assert page.locator("text=black → purple").count() == 0, (
        "a colour map is still explaining itself in words beside its swatch"
    )


_BARS = """() => Array.from(
  document.querySelector('[aria-label="histogram Ch488"]').querySelectorAll('rect'),
).filter((bar) => bar.getAttribute('fill') === 'currentColor')
 .map((bar) => ({
   x: Number(bar.getAttribute('x')),
   width: Number(bar.getAttribute('width')),
   height: Number(bar.getAttribute('height')),
 }))"""


def test_the_brightness_axis_opens_on_the_data(two_channel_page):
    """From the dimmest pixel present to the brightest, and no further.

    An axis drawn to what the camera COULD have written puts a real specimen
    in the first few per cent of the track and leaves the rest as headroom
    nothing occupies. The pixels that are actually there are what an operator
    is adjusting, so that is the axis they get, and anything wider is theirs
    to ask for in the boxes beneath it.
    """
    page = two_channel_page
    measured = page.evaluate("() => window.zmartConfig.layers[0].histogram")
    _choose(page, "Ch488")
    window_ = _window_in_engine(page)
    reach = page.locator("[aria-label='max Ch488']").evaluate(
        "(element) => ({ min: Number(element.min), max: Number(element.max) })")
    # The data's own span, widened only by whatever window is in use -- a run
    # may declare a window wider than its brightest pixel, and a handle
    # stranded past the end of its track is worse than a little slack.
    wanted = max(measured["high"], window_[1])
    assert reach["max"] == pytest.approx(wanted, rel=0.02), (
        f"the handles travel to {reach['max']}, not to the {wanted} that the "
        "channel's pixels and window between them ask for"
    )
    assert reach["max"] < 65535, (
        "the axis is drawn to what the camera could have written, which is "
        "mostly headroom nothing occupies"
    )
    assert reach["min"] == pytest.approx(min(measured["low"], window_[0]), abs=1.0), (
        f"the handles start at {reach['min']}, not at the dimmest pixel "
        f"({measured['low']})"
    )


def test_two_boxes_say_how_much_of_the_axis_to_show(two_channel_page):
    """Under the histogram, the part of the brightness scale on show.

    The axis opens on the data, and what an operator wants next is often
    narrower still -- a dim channel with one bright speck spends the whole
    track on the speck. These two say where the drawing starts and ends, and
    the handles beneath them travel over exactly that.
    """
    page = two_channel_page
    _choose(page, "Ch488")
    low = page.locator("[aria-label='axis from Ch488']")
    high = page.locator("[aria-label='axis to Ch488']")
    assert low.count() == 1 and high.count() == 1, (
        "there is no way to say which part of the brightness axis to draw"
    )
    for box, value in ((low, 400), (high, 2200)):
        box.click()
        box.fill(str(value))
        box.press("Enter")
        page.wait_for_timeout(400)
    reach = page.locator("[aria-label='max Ch488']").evaluate(
        "(element) => ({ min: Number(element.min), max: Number(element.max) })")
    assert reach == pytest.approx({"min": 400, "max": 2200}, rel=0.01), (
        f"the handles travel over {reach}, not the 400 to 2200 that was asked for"
    )


def test_log_stretches_the_bars_upward_not_sideways(two_channel_page):
    """Log is about how many, not about how bright.

    A logarithmic BRIGHTNESS axis moves every bar sideways and drags the
    handles with it, so a window an operator set stops sitting where they put
    it. What actually needs the log is the count: fluorescence piles almost
    every pixel into the dim bins and leaves the interesting tail one pixel
    high, invisible beside them. So the bars keep their places and grow
    taller.
    """
    page = two_channel_page
    _choose(page, "Ch488")
    plain = page.evaluate(_BARS)
    page.get_by_label("logarithmic counts").click()
    page.wait_for_timeout(400)
    logged = page.evaluate(_BARS)

    assert [bar["x"] for bar in logged] == pytest.approx(
        [bar["x"] for bar in plain], abs=1e-6), (
        "the bars moved sideways, so Log is still warping the brightness axis"
    )
    assert [bar["width"] for bar in logged] == pytest.approx(
        [bar["width"] for bar in plain], abs=1e-6), (
        "the bars changed width, so Log is still warping the brightness axis"
    )
    assert [bar["height"] for bar in logged] != pytest.approx(
        [bar["height"] for bar in plain], abs=1e-6), (
        "nothing about the bars changed, so Log did nothing at all"
    )
    # The point of it: the small counts are lifted into view.
    quiet = min((bar["height"] for bar in plain if bar["height"] > 0), default=0)
    lifted = min((bar["height"] for bar in logged if bar["height"] > 0), default=0)
    assert lifted > quiet, (
        f"the quietest bar reads {lifted} on the log scale against {quiet} "
        "plain, so the bins an operator cannot see are still invisible"
    )

"""Every channel of a picture reaches the screen, and only its own dials move it.

A four-channel plate opened on the workstation showing exactly one channel:
the top one covered the rest, so recolouring any other changed not a single
pixel (measured 2026-08-19). Channels of one picture have to MIX -- the
coloured brightnesses added, the way every fluorescence viewer adds them.

The second half of that sentence is the operator's, and it is what these
gates are really for. The display must stay a fact about the data and about
the dials that were set: a channel's contribution may depend on its own
window, its own colour and its own weight, and on nothing else. In
particular it must not depend on which OTHER channels happen to be showing,
which is why nothing here is normalised or scaled to fit. When the sum
overflows it clips, exactly as ImageJ, napari, OMERO, vizarr and stock
neuroglancer clip, and the operator's own white points are the remedy.

The gates photograph the canvas rather than asking the engine what it holds,
because the fault they exist to catch -- a channel that loads perfectly and
draws nothing -- is invisible to every number the engine reports.
"""

from __future__ import annotations

import io
import json
import threading

import numpy as np
import pytest
import zarr
from server import make_server

# Well below the window's top, so four channels can be added without any of
# them reaching the ceiling: these gates are about whether a channel arrives
# at all, and a picture already at full brightness would hide that.
DIM = 1000
WINDOW = (0, 8000)


def _a_picture(path, values, colours, declare=None):
    """One store of several channels, each filled with its own flat value.

    A flat value per channel makes what reaches the screen arithmetic rather
    than texture: the canvas is one colour, and that colour is the sum the
    shader was asked for. A channel given nought is imaged nowhere, which is
    what lets a gate below watch one channel while another is switched.
    """
    path.mkdir(parents=True)
    group = zarr.open_group(str(path), mode="w", zarr_format=2)
    data = np.zeros((len(values), 2, 64, 64), dtype=np.uint16)
    for index, value in enumerate(values):
        data[index] = value
    group.create_array("0", shape=data.shape, chunks=(1, 1, 64, 64),
                       dtype="uint16")[:] = data
    (path / ".zattrs").write_text(json.dumps({
        "multiscales": [{
            "version": "0.4",
            "axes": [{"name": "c", "type": "channel"},
                     {"name": "z", "type": "space", "unit": "micrometer"},
                     {"name": "y", "type": "space", "unit": "micrometer"},
                     {"name": "x", "type": "space", "unit": "micrometer"}],
            "datasets": [{"path": "0", "coordinateTransformations": [
                {"type": "scale", "scale": [1.0, 2.0, 0.35, 0.35]}]}],
        }],
        "omero": {"channels": [
            {"label": name, "color": colour,
             # A window the run asked for, so these gates do not also depend
             # on what a measurement of a flat picture happens to return.
             "window": {"min": 0, "max": 65535,
                        "start": WINDOW[0], "end": WINDOW[1]},
             # Anything else this particular run declares about the channel.
             **((declare or [{}] * len(values))[index])}
            for index, (name, colour)
            in enumerate(zip(_names(len(values)), colours, strict=True))
        ]},
    }), encoding="utf-8")
    return path


def _names(count):
    return [f"ch{chr(ord('A') + index)}" for index in range(count)]


def _serve(folder, built_dist, browser, store):
    """A page on one picture, settled and framed."""
    server = make_server(port=0, data_dir=folder, site_dir=built_dist,
                         store=store)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 900, "height": 700})
    page.goto(f"http://127.0.0.1:{server.server_address[1]}",
              wait_until="domcontentloaded")
    page.wait_for_function("() => window.zmartConfig !== undefined",
                           timeout=30_000)
    page.wait_for_function(
        "() => window.zmartSourcesWaiting && window.zmartSourcesWaiting() === 0",
        timeout=60_000)
    page.wait_for_timeout(1_200)
    return page, server, thread


def _on_screen(page):
    """What the canvas is showing, as one average red, green and blue.

    The background is black and contributes nothing, so this number rises and
    falls exactly as the picture's own brightness does.
    """
    box = page.locator("canvas").first.bounding_box()
    from PIL import Image

    shot = page.screenshot(clip=box)
    pixels = np.array(Image.open(io.BytesIO(shot)).convert("RGB"), dtype=float)
    return pixels.reshape(-1, 3).mean(axis=0)


def _choose(page, channel):
    """Select a channel, so the one block of display settings acts on it."""
    page.locator(f"[aria-label='toggle {channel}']").locator("xpath=../..").click()
    page.wait_for_timeout(200)


def _recolour(page, channel, colour):
    """Paint a channel a named colour, the way an operator does it.

    The colour a channel is painted in is also the control that changes it:
    press the square on its row and the list of everything it could be
    painted in opens under it.
    """
    _choose(page, channel)
    page.locator(f"[aria-label='colour {channel}']").click()
    page.wait_for_timeout(200)
    page.locator(f"[aria-label='{colour} for {channel}']").click()
    page.wait_for_timeout(900)


@pytest.fixture
def four_channels(browser, built_dist, tmp_path):
    """Three channels with signal and a fourth imaged nowhere, on one page."""
    folder = tmp_path / "specimen"
    folder.mkdir()
    # Three different values, so a gate below can tell whether each channel
    # is reading its OWN data: one, two and three parts of the window.
    _a_picture(folder / "overview_pos001.ome.zarr",
               [DIM, 2 * DIM, 3 * DIM, 0],
               ["FF0000", "00FF00", "0000FF", "FFFFFF"])
    page, server, thread = _serve(folder, built_dist, browser,
                                  "overview_pos001.ome.zarr")
    try:
        yield page
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def test_every_channel_of_a_picture_reaches_the_screen(four_channels):
    """Recolouring ANY channel must change the picture, not only the top one.

    This is the workstation's defect stated as a measurement. Under the
    covering rule the topmost channel painted over every other, so the three
    beneath it were loaded, windowed, coloured -- and invisible. A channel
    nobody can see is a channel nobody can use.
    """
    page = four_channels
    deaf = []
    for channel in ("chA", "chB", "chC"):
        before = _on_screen(page)
        _recolour(page, channel, "magenta")
        after = _on_screen(page)
        if float(np.abs(after - before).max()) < 1.0:
            deaf.append(channel)
        _recolour(page, channel, "grey")
    assert not deaf, (
        f"recolouring {', '.join(deaf)} changed nothing on screen -- those "
        "channels are not reaching the picture at all"
    )


def test_a_channel_is_unmoved_by_another_being_hidden(four_channels):
    """Switching one channel off must not touch how the others are drawn.

    The operator's own rule, and the reason this design normalises nothing:
    the black and white points they set for a channel have to mean the same
    thing however many other channels happen to be showing. A viewer that
    rescales the mix to fit would brighten every remaining channel the
    moment one was hidden -- so the fourth channel here is imaged NOWHERE,
    and switching it must therefore be invisible. Anything that scales by
    what is on show fails this by construction.
    """
    page = four_channels
    before = _on_screen(page)
    page.locator("[aria-label='toggle chD']").click()
    page.wait_for_timeout(900)
    without = _on_screen(page)
    page.locator("[aria-label='toggle chD']").click()
    page.wait_for_timeout(900)
    again = _on_screen(page)

    assert float(np.abs(without - before).max()) < 1.0, (
        f"hiding an empty channel moved the picture ({before} to {without}) "
        "-- a channel's appearance is depending on which others are showing"
    )
    assert float(np.abs(again - before).max()) < 1.0, (
        "showing it again did not put the picture back"
    )


def test_a_channel_fades_in_step_with_its_opacity(four_channels):
    """Half opacity draws half as bright, not a quarter.

    Opacity used to be carried twice -- once in the colour the shader emits
    and once as the transparency the engine blends with -- so a blended row
    faded as opacity SQUARED. One carrier, one fade.
    """
    page = four_channels
    for channel in ("chB", "chC"):
        page.locator(f"[aria-label='toggle {channel}']").click()
        page.wait_for_timeout(300)
    # Selected last, because pressing a channel's eye also picks it out, and
    # the one block of display settings acts on whatever is picked.
    _choose(page, "chA")
    page.wait_for_timeout(600)
    full = _on_screen(page)[0]

    page.locator("[aria-label='opacity chA']").evaluate(
        """(element) => {
          const setter = Object.getOwnPropertyDescriptor(
            HTMLInputElement.prototype, 'value').set;
          setter.call(element, '0.5');
          element.dispatchEvent(new Event('input', { bubbles: true }));
        }""")
    page.wait_for_timeout(900)
    halved = _on_screen(page)[0]

    assert full > 2.0, f"the channel must be visible to begin with, saw {full}"
    share = halved / full
    assert 0.42 < share < 0.58, (
        f"at half opacity the channel draws {share:.0%} of its full "
        "brightness; a fade that squares its own setting reads about 25%"
    )


def test_recolouring_leaves_the_drawing_program_alone(four_channels):
    """A colour is a number handed to a program, not a new program.

    The engine's colour control is a uniform -- it is deliberately not part
    of a program's identity -- so recolouring should cost one number and no
    rebuild. Written into the program's text instead, every recolour
    compiles a fresh program, and every channel needs its own.
    """
    page = four_channels
    programs = lambda: page.evaluate(  # noqa: E731 -- a tiny page probe
        """() => window.zmartViewer.layerManager.managedLayers
             .filter((managed) => managed.layer?.type === 'image')
             .map((managed) => managed.layer.fragmentMain.value)""")
    before = programs()
    _recolour(page, "chB", "cyan")
    after = programs()
    assert after == before, (
        "recolouring rewrote the drawing program; the colour belongs in a "
        "control, where it costs no rebuild"
    )
    held = page.evaluate(
        """() => window.zmartViewer.layerManager.managedLayers
             .filter((managed) => managed.layer?.type === 'image')
             .map((managed) => JSON.stringify(
                managed.layer.shaderControlState.toJSON() || {}))""")
    # Cyan is (0.2, 0.8, 1) of full, which is how a colour is spelled on the
    # way to the engine's own control.
    assert any("#33ccff" in one for one in held), (
        f"the chosen colour must arrive as a shader control; saw {held}"
    )


@pytest.fixture
def written_as_positions(browser, built_dist, tmp_path):
    """Two channels of one picture, written as two overlapping positions.

    The shape a real run is written in: the microscope saves a position at a
    time, each holding every channel, and the positions overlap at their
    edges. Both stores here sit on exactly the same ground, which is the
    overlap taken to its limit and needs no stage arithmetic to arrange.
    """
    folder = tmp_path / "survey"
    folder.mkdir()
    for name in ("survey_pos001.ome.zarr", "survey_pos002.ome.zarr"):
        _a_picture(folder / name, [DIM, DIM], ["FF0000", "00FF00"])
    page, server, thread = _serve(folder, built_dist, browser,
                                  ["survey_pos001.ome.zarr",
                                   "survey_pos002.ome.zarr"])
    try:
        yield page
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


@pytest.mark.xfail(strict=True, reason=(
    "A picture written as overlapping positions cannot mix its channels, and "
    "the engine is what says so. Adding is a property of a LAYER, so a layer "
    "fed by several stores adds those stores to each other as well, drawing a "
    "bright seam along every join -- such a picture keeps the covering rule "
    "and shows only its topmost channel. Reading several channels inside ONE "
    "program would settle it, and cannot be done here: a brightness control "
    "binds to a CHANNEL dimension, while an OME-Zarr c axis arrives as a "
    "LOCAL one (measured 2026-08-20 -- the layer reports a channel rank of "
    "nought and `channel=[1]` will not parse). The cure is the composed "
    "picture the server already builds, which is one store and mixes "
    "properly; this gate stands so the day the limit lifts is not missed."))
def test_a_picture_written_as_positions_still_mixes_its_channels(
        written_as_positions):
    """Both rules at once: the channels mix while the positions cover.

    The case the arrangement cannot yet satisfy, kept as a measurement
    rather than as a paragraph. Every row here is fed by two stores, so the
    engine's adding is unavailable and the topmost channel covers the other.
    """
    page = written_as_positions
    deaf = []
    for channel in ("chA", "chB"):
        before = _on_screen(page)
        _recolour(page, channel, "magenta")
        if float(np.abs(_on_screen(page) - before).max()) < 1.0:
            deaf.append(channel)
        _recolour(page, channel, "grey")
    assert not deaf, (
        f"in a picture written as positions, recolouring {', '.join(deaf)} "
        "changed nothing -- its channels are covering one another instead "
        "of mixing"
    )


def test_positions_of_one_picture_still_cover_each_other(browser, built_dist,
                                                         tmp_path):
    """Two positions on the same ground draw as one, not as double.

    Channels add; positions do not. A run is written as many positions that
    overlap at their edges, and adding them there would draw a bright seam
    along every join -- the reason the whole covering arrangement exists.
    Both stores here hold the same picture at the same place, so a viewer
    that added them would read twice as bright as one alone.
    """
    alone = tmp_path / "alone"
    alone.mkdir()
    _a_picture(alone / "overview_pos001.ome.zarr", [DIM], ["FF0000"])
    page, server, thread = _serve(alone, built_dist, browser,
                                  "overview_pos001.ome.zarr")
    try:
        single = _on_screen(page)[0]
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)

    twice = tmp_path / "twice"
    twice.mkdir()
    _a_picture(twice / "overview_pos001.ome.zarr", [DIM], ["FF0000"])
    _a_picture(twice / "overview_pos002.ome.zarr", [DIM], ["FF0000"])
    page, server, thread = _serve(twice, built_dist, browser,
                                  ["overview_pos001.ome.zarr",
                                   "overview_pos002.ome.zarr"])
    try:
        stacked = _on_screen(page)[0]
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)

    assert single > 2.0, f"the one position must be visible, saw {single}"
    assert abs(stacked - single) < max(1.0, single * 0.15), (
        f"two positions of one picture drew {stacked:.1f} where one drew "
        f"{single:.1f} -- overlapping ground is being added instead of covered"
    )


def test_each_channel_draws_its_own_data(four_channels):
    """Channel B is twice channel A on screen, and channel C is three times.

    The three channels hold one, two and three parts of the same window and
    are painted red, green and blue, so what the canvas shows is the mix
    read straight back: a ratio of 1 : 2 : 3. The gate matters most while
    the drawing program is being changed, because a program that reads the
    same channel three times, or reads them in the wrong order, still draws
    a perfectly plausible picture -- just not this specimen's.
    """
    page = four_channels
    red, green, blue = _on_screen(page)
    assert red > 2.0, f"the picture must be on screen to be read, saw {red}"
    assert 1.8 < green / red < 2.2, (
        f"green stands at {green / red:.2f} times red, not the two times its "
        "data says -- the channels are not being read as their own"
    )
    assert 2.7 < blue / red < 3.3, (
        f"blue stands at {blue / red:.2f} times red, not three times"
    )


@pytest.fixture
def as_the_run_declared(browser, built_dist, tmp_path):
    """A picture whose run wrote down how it wants to be shown."""
    folder = tmp_path / "declared"
    folder.mkdir()
    _a_picture(
        folder / "overview_pos001.ome.zarr",
        [DIM, 2 * DIM],
        ["FF0000", "00FF00"],
        declare=[
            # Twelve bits of camera written into sixteen-bit files, which is
            # the ordinary case and not what the number type would say. The
            # window sits inside that range, as a real run's does.
            {"window": {"min": 0, "max": 4095, "start": 0, "end": 3000}},
            {"window": {"min": 0, "max": 4095, "start": 0, "end": 3000},
             "active": False},
        ],
    )
    page, server, thread = _serve(folder, built_dist, browser,
                                  "overview_pos001.ome.zarr")
    try:
        yield page
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


def test_the_range_a_run_declares_bounds_the_window_not_the_axis(as_the_run_declared):
    """A twelve-bit camera cannot produce 9000, so no black or white point goes there.

    The declared range still reaches the viewer, and it still bounds the
    thing that matters: the WINDOW. A black or white point beyond the
    pixels would describe brightness that does not exist, so however the
    window is moved -- slider, typed box, or the bars on the histogram --
    it can never leave the image's own range. The AXIS is different since
    the redesign of 2026-08-23: the boxes beneath the histogram take the
    operator's number as given, past the declared range and below zero
    alike, because the framing promises the window's marks a fixed pair
    of places on the picture. This gate used to clamp the axis too, and
    now pins the split: the axis obeys the operator, the window obeys the
    camera.
    """
    page = as_the_run_declared
    told = page.evaluate("() => window.zmartConfig.layers[0].range")
    assert told == {"low": 0, "high": 4095}, (
        f"the viewer was served a range of {told}; the run declared 0 to 4095"
    )
    _choose(page, "chA")
    # The operator may draw the axis as far as they ask...
    box = page.get_by_label("axis to chA")
    box.click()
    box.fill("9000")
    box.press("Enter")
    page.wait_for_timeout(500)
    reach = page.locator("[aria-label='max chA']").evaluate(
        "(element) => Number(element.max)")
    assert reach == 9000, (
        f"the axis reaches {reach}; the box beneath the histogram takes the "
        "operator's number as given since 2026-08-23"
    )
    # ...but the white point may not follow the axis past the camera.
    value = page.get_by_label("max value chA")
    value.click()
    value.fill("9000")
    value.press("Enter")
    page.wait_for_timeout(500)
    high = page.locator("[aria-label='max chA']").input_value()
    # Within one count: the number makes a round trip through the engine's
    # floating-point window on its way back to the slider, and a seventh of
    # a count is far below anything an eye could see.
    assert abs(float(high) - 4095) < 1, (
        f"the white point was pushed to {high}, past the 4095 the run says "
        "its numbers live in"
    )


def test_a_channel_the_run_switched_off_opens_switched_off(as_the_run_declared):
    """What the microscopist had showing is what the viewer opens showing.

    A run that says a channel was off is a run whose operator turned it off,
    and opening it anyway is the viewer overruling them -- on an 18-channel
    plate that is the difference between a picture and a glare. The channel is
    still listed, and one press brings it back.
    """
    page = as_the_run_declared
    shown = page.evaluate("() => window.zmartLayerState.map((s) => s.visible)")
    assert shown == [True, False], (
        f"the channels opened {shown}; the run declared the second one off"
    )
    assert page.locator("[aria-label='toggle chB']").count() == 1, (
        "a channel switched off is still listed, so it can be brought back"
    )

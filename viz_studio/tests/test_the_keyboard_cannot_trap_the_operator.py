"""The engine's own keyboard shortcuts must not reach past our interface.

The viewer hides the engine's buttons and panels and puts its own controls in
their place. The keyboard was the hole in that: installing the engine's default
bindings also installed a global table of single-key shortcuts, bound to actions
belonging to the interface we hide, active over the whole page from the moment it
loaded — the engine's element holds the keyboard focus straight away, so no click
was needed first.

The worst of them was the space bar. It split the image into four panels, and
there was no way back: clicking "2D" while the viewer already believed it was
showing 2-D changes nothing, so nothing was re-run and the four panels stayed.
An operator who brushed the space bar had to know to switch to 3-D and back.

    fresh load:        layout "yz",         1 panel
    press space:       layout "4panel-alt", 4 panels
    click 2D:          layout "4panel-alt", 4 panels    <- no way back
    click 3D then 2D:  layout "yz",         1 panel     <- the only escape

The others were quieter. The digits hid a channel while the panel's eye still
showed it open, so the operator's next click on the eye appeared to do nothing;
`b`, `a` and `v` restored the engine's own scale bars, axis lines and bounding
box, which this viewer replaces with its own; `s` switched the slices off inside
the volume; `o` added an orthographic projection.

Each test presses a key and checks that nothing moved. "Nothing moved" is also
what a page that never loaded would report, so the first test here proves the
keystrokes are genuinely arriving — by checking that a key we *do* want still
does its job. Without that, this whole file could pass against a blank screen.
"""

from __future__ import annotations

import pytest

_LAYOUT = "() => window.zmartViewer.layout.toJSON()"
_PANELS = "() => document.querySelectorAll('.neuroglancer-panel').length"

# Four of these live on the viewer itself. The orthographic projection does not —
# it belongs to the panel layout — so it is watched through the layout's own
# description instead, which is where it would show up if it were switched on.
# Reading it off the viewer gives nothing at all, and a test comparing nothing
# with nothing passes however broken the viewer is.
_CHROME = """() => {
  const v = window.zmartViewer;
  return {
    scaleBar: v.showScaleBar.value,
    axisLines: v.showAxisLines.value,
    annotations: v.showDefaultAnnotations.value,
    slices: v.showPerspectiveSliceViews.value,
    layout: JSON.stringify(v.layout.toJSON()),
  };
}"""

_VISIBLE = """() => window.zmartViewer.layerManager.managedLayers.map((l) => l.visible)"""


def press(page, key: str) -> None:
    """Send one key to the page the way a stray keystroke would arrive.

    Sent to the engine's own element rather than to the document, because that is
    where the focus sits when the page loads and it is the least forgiving place
    to send it from — a binding that survives here survives anywhere.
    """
    page.focus(".neuroglancer-panel")
    page.keyboard.press(key)
    page.wait_for_timeout(400)


def test_the_keystrokes_really_do_reach_the_engine(viewer_page):
    """Proof that the rest of this file can fail.

    The comma and full stop keys step through z, and they are bound on the image
    panel rather than in the global table — so they are exactly what this viewer
    wants to keep. If this stops working, the tests below are no longer testing
    that a key does nothing; they are testing that no key arrives at all.
    """
    before = viewer_page.evaluate(
        "() => { const v = window.zmartViewer;"
        " const i = v.navigationState.position.coordinateSpace.value.names.indexOf('z');"
        " return v.navigationState.position.value[i]; }"
    )
    press(viewer_page, "Period")
    after = viewer_page.evaluate(
        "() => { const v = window.zmartViewer;"
        " const i = v.navigationState.position.coordinateSpace.value.names.indexOf('z');"
        " return v.navigationState.position.value[i]; }"
    )
    assert after != before, (
        "'.' no longer steps through z, so the keyboard is not reaching the "
        "engine at all and nothing else in this file means anything"
    )


def test_the_space_bar_does_not_split_the_image(viewer_page):
    """The trap itself: one panel before, one panel after."""
    layout_before = viewer_page.evaluate(_LAYOUT)
    assert viewer_page.evaluate(_PANELS) == 1

    press(viewer_page, "Space")

    assert viewer_page.evaluate(_PANELS) == 1, (
        "the space bar split the drawing area into panels, which an operator "
        "cannot undo from our interface"
    )
    assert viewer_page.evaluate(_LAYOUT) == layout_before


def test_shift_space_does_not_split_the_image_either(viewer_page):
    layout_before = viewer_page.evaluate(_LAYOUT)
    press(viewer_page, "Shift+Space")
    assert viewer_page.evaluate(_PANELS) == 1
    assert viewer_page.evaluate(_LAYOUT) == layout_before


@pytest.mark.parametrize("key", ["Digit1", "Digit2", "Digit3"])
def test_the_digits_do_not_hide_a_channel(viewer_page, key):
    """A hidden channel whose eye still reads "open" puts the panel out of phase."""
    before = viewer_page.evaluate(_VISIBLE)
    press(viewer_page, key)
    assert viewer_page.evaluate(_VISIBLE) == before, (
        f"{key} changed which channels are drawn, while the panel's own eye "
        "still shows the old state"
    )


@pytest.mark.parametrize("key", ["b", "a", "v", "s", "o"])
def test_the_engine_furniture_stays_switched_off(viewer_page, key):
    """These keys put back the engine's own scale bars, axes and boxes."""
    before = viewer_page.evaluate(_CHROME)
    press(viewer_page, key)
    assert viewer_page.evaluate(_CHROME) == before, (
        f"'{key}' switched a piece of the engine's own interface back on, and "
        "this viewer draws its own in its place"
    )


def test_the_help_panel_does_not_open(viewer_page):
    """It describes controls that are not on screen, so it can only confuse."""
    press(viewer_page, "h")
    assert (
        viewer_page.evaluate(
            "() => document.querySelectorAll('.neuroglancer-help-body').length"
        )
        == 0
    )


def test_the_statistics_panel_does_not_open(viewer_page):
    """`\\` opened the engine's own timing readout across the image.

    Asked of the engine's own record of whether the panel is showing rather than
    by looking for it in the page. The panel is built only once it is first
    opened, so searching the page for it finds nothing either way and would pass
    however the keyboard behaved.
    """
    showing = "() => window.zmartViewer.statisticsDisplayState.location.visible"
    assert viewer_page.evaluate(showing) is False
    press(viewer_page, "Backslash")
    assert viewer_page.evaluate(showing) is False, (
        "the statistics panel opened over the image, and our interface offers no "
        "way to close it again"
    )


# The `n` key, which opens the engine's own "add a layer" dialog, is deliberately
# not tested here. It reaches that dialog only through the engine's layer panel,
# and this viewer is built with that panel switched off — so the key does nothing
# whether its binding is installed or not, and a test of it would pass in both
# worlds. A test that cannot fail is worse than no test, because it reads as
# cover that is not there.


def test_navigation_still_works_after_all_of_them(viewer_page):
    """The point of the fix is to remove traps, not to deaden the keyboard."""
    for key in ["Space", "Digit1", "b", "a", "v", "s", "o", "h", "n"]:
        press(viewer_page, key)

    before = viewer_page.evaluate(
        "() => window.zmartViewer.navigationState.zoomFactor.value"
    )
    box = viewer_page.locator(".neuroglancer-panel").first.bounding_box()
    viewer_page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    viewer_page.keyboard.down("Control")
    viewer_page.mouse.wheel(0, -600)
    viewer_page.keyboard.up("Control")
    viewer_page.wait_for_timeout(600)

    assert (
        viewer_page.evaluate("() => window.zmartViewer.navigationState.zoomFactor.value")
        != before
    ), "zooming stopped working, so the fix took away more than the traps"
    assert viewer_page.evaluate(_PANELS) == 1

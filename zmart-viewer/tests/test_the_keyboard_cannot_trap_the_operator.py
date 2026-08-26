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

The panel tables were the second hole, closed later (2026-08-18, the decision
recorded in docs/how_it_works/CONTROLS.md): the engine's per-panel defaults still bound a whole
keyboard — arrows panned, comma and full stop stepped z, the brackets stepped
time straight past the written-moments clamp the slider enforces, `r`, `e` and
Shift with the arrows rotated the slice so the picture silently stopped lining
up with the stage coordinates drawn over it, and Ctrl with `=` zoomed. All of
it reachable by a stray keystroke, none of it shown anywhere on screen. Moving
through the stack and through time belongs to the sliders, where it is visible,
labelled, and clamped to what has actually been written; moving around belongs
to the two gestures (drag pans, the wheel zooms). So the panels now install
only the gestures we chose, and no keyboard at all.

Each test presses a key and checks that nothing moved. "Nothing moved" is also
what a page that never loaded would report, so the first test here proves the
keystrokes are genuinely arriving — by watching them land on the engine's own
element. Without that, this whole file could pass against a blank screen.
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

    No key is allowed to move the view any more, so "reaches the engine" is
    watched at the door instead: a listener on the engine's own element sees
    the keystroke arrive. If this stops working, the tests below are no longer
    testing that a key does nothing; they are testing that no key arrives at
    all.
    """
    viewer_page.evaluate(
        "() => { window.zmartKeysSeen = [];"
        " document.querySelector('.neuroglancer-panel').addEventListener("
        "   'keydown', (event) => window.zmartKeysSeen.push(event.code), true); }"
    )
    press(viewer_page, "Period")
    press(viewer_page, "ArrowRight")
    assert viewer_page.evaluate("() => window.zmartKeysSeen") == [
        "Period", "ArrowRight",
    ], (
        "keystrokes are not reaching the engine's element at all, so nothing "
        "else in this file means anything"
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

_POSITION = "() => Array.from(window.zmartViewer.navigationState.position.value)"
_ZOOM = "() => window.zmartViewer.navigationState.zoomFactor.value"
_FACING = (
    "() => Array.from("
    "window.zmartViewer.navigationState.pose.orientation.orientation)"
)


@pytest.mark.parametrize(
    "key",
    [
        "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown",  # panned x and y
        "Comma", "Period",                                  # stepped z
        "BracketLeft", "BracketRight",                      # stepped time
    ],
)
def test_no_key_moves_the_position(viewer_page, key):
    """Moving belongs to the sliders and to dragging, where it is visible.

    The brackets were the worst of these: they stepped time directly, straight
    past the T slider's clamp to the moments that have actually been written,
    onto ground the record has not published — which the screen shows as
    honest black, with nothing to say why.
    """
    before = viewer_page.evaluate(_POSITION)
    press(viewer_page, key)
    assert viewer_page.evaluate(_POSITION) == before, (
        f"{key} moved the view; steering lives on the sliders and the mouse, "
        "never on a key with no label on screen"
    )


@pytest.mark.parametrize("key", ["r", "e", "Shift+ArrowLeft", "Shift+ArrowUp"])
def test_no_key_rotates_the_flat_view(viewer_page, key):
    """A rotated slice silently stops lining up with the stage coordinates.

    The operator's carrier outline and tile positions are drawn in stage
    coordinates, straight. docs/how_it_works/CONTROLS.md section 2 removes rotation from the
    flat view entirely for that reason, and asks for exactly this test:
    an unbound gesture looks like a gesture nobody tried, so without it the
    rotation quietly comes back the next time the bindings are edited.
    """
    before = viewer_page.evaluate(_FACING)
    press(viewer_page, key)
    assert viewer_page.evaluate(_FACING) == before, (
        f"{key} rotated the view, and nothing on screen says how to undo it"
    )


def test_shift_drag_does_not_rotate_either(viewer_page):
    """The same trap on the mouse: Shift and drag is easy to make by accident."""
    before = viewer_page.evaluate(_FACING)
    box = viewer_page.locator(".neuroglancer-panel").first.bounding_box()
    middle = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    viewer_page.keyboard.down("Shift")
    viewer_page.mouse.move(*middle)
    viewer_page.mouse.down()
    viewer_page.mouse.move(middle[0] + 120, middle[1] + 60, steps=8)
    viewer_page.mouse.up()
    viewer_page.keyboard.up("Shift")
    viewer_page.wait_for_timeout(400)
    assert viewer_page.evaluate(_FACING) == before, (
        "Shift+drag rotated the flat view -- the picture no longer lines up "
        "with the stage coordinates drawn over it, and nothing errors"
    )


@pytest.mark.parametrize("key", ["Control+Equal", "Control+Minus"])
def test_no_key_zooms(viewer_page, key):
    """Zoom lives on the wheel, and nowhere else."""
    before = viewer_page.evaluate(_ZOOM)
    press(viewer_page, key)
    assert viewer_page.evaluate(_ZOOM) == before, (
        f"{key} zoomed the view; zoom belongs to the wheel alone"
    )


def test_the_right_button_does_not_recentre(viewer_page):
    """A right click jumped the view to the point clicked, without warning."""
    before = viewer_page.evaluate(_POSITION)
    box = viewer_page.locator(".neuroglancer-panel").first.bounding_box()
    viewer_page.mouse.click(
        box["x"] + box["width"] * 0.75, box["y"] + box["height"] * 0.25,
        button="right",
    )
    viewer_page.wait_for_timeout(400)
    assert viewer_page.evaluate(_POSITION) == before, (
        "a right click recentred the view -- movement an operator did not ask "
        "for and cannot see the reason of"
    )


def test_navigation_still_works_after_all_of_them(viewer_page):
    """The point of the fix is to remove traps, not to deaden the page.

    The two gestures that remain are the two docs/how_it_works/CONTROLS.md promises: the plain
    wheel zooms, and a drag pans.
    """
    for key in ["Space", "Digit1", "b", "a", "v", "s", "o", "h", "n",
                "ArrowRight", "Period", "r", "Control+Equal"]:
        press(viewer_page, key)

    box = viewer_page.locator(".neuroglancer-panel").first.bounding_box()
    middle = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)

    zoom_before = viewer_page.evaluate(_ZOOM)
    viewer_page.mouse.move(*middle)
    viewer_page.mouse.wheel(0, -600)
    viewer_page.wait_for_timeout(600)
    assert viewer_page.evaluate(_ZOOM) != zoom_before, (
        "the wheel stopped zooming, so the fix took away more than the traps"
    )

    place_before = viewer_page.evaluate(_POSITION)
    viewer_page.mouse.move(*middle)
    viewer_page.mouse.down()
    viewer_page.mouse.move(middle[0] - 150, middle[1] - 80, steps=8)
    viewer_page.mouse.up()
    viewer_page.wait_for_timeout(600)
    assert viewer_page.evaluate(_POSITION) != place_before, (
        "dragging stopped panning, so the fix took away more than the traps"
    )
    assert viewer_page.evaluate(_PANELS) == 1

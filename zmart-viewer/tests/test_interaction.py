"""Can the operator actually navigate, in both modes?

This is the regression guard for a bug that made the viewer look finished and
be unusable: neuroglancer's panels received every mouse event, the volume
rendered, and nothing moved -- because ``makeMinimalViewer`` builds a viewer but
does not install the default input bindings. Rendering tests cannot catch that;
only driving the gestures can.

The gestures are checked in the layout we actually ship -- a single plane, and
the volume behind the 3-D toggle:

===================  =========================================
gesture              effect
===================  =========================================
drag                 pans
plain wheel          zooms
shift + wheel        steps through z
drag in 3-D mode     rotates
===================  =========================================

**The plain wheel zooms, and that is ours rather than the engine's.**
Neuroglancer binds the wheel to stepping through z and puts zoom behind Control,
which is right for reading through a volume and wrong here. `docs/how_it_works/CONTROLS.md` section
1 records the decision and the reasoning: the wheel is the gesture an operator
makes most often and without thinking, a browser has taught everyone what it
does, and stepping through the stack already has a slider down the right-hand
side -- which is better than a gesture anyway, because it shows you where in the
stack you are. Zoom had nowhere else to live; there is no zoom button, slider or
key anywhere in this interface.

The decision was written down on the day the controls were reviewed and the code
was never changed to match, which is how an operator came to meet a viewer whose
first instinct -- turn the wheel -- did nothing at all on a run one plane deep.
The operator page next door had it right the whole time (`canvas/panel.js`:
"Dragging pans and the plain wheel zooms"), so the two interfaces disagreed.
"""

from __future__ import annotations

import pytest

_STATE = """() => {
  const v = window.zmartViewer;
  const zIndex = v.navigationState.position.coordinateSpace.value.names.indexOf('z');
  return {
    position: Array.from(v.navigationState.position.value),
    zIndex,
    zPosition: v.navigationState.position.value[zIndex],
    zoom: v.navigationState.zoomFactor.value,
    orientation: Array.from(v.perspectiveNavigationState.pose.orientation.orientation),
  };
}"""

_CENTRE = """() => {
  const r = document.querySelector('.neuroglancer-panel').getBoundingClientRect();
  return {x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2)};
}"""


def centre(page):
    return page.evaluate(_CENTRE)


def drag(page, x, y, dx, dy):
    page.mouse.move(x, y)
    page.mouse.down()
    for step in range(1, 11):
        page.mouse.move(x + dx * step / 10, y + dy * step / 10)
    page.mouse.up()
    page.wait_for_timeout(600)


def set_range(page, label, value):
    page.locator(f"[aria-label='{label}']").evaluate(
        """(element, value) => {
          const setter = Object.getOwnPropertyDescriptor(
            HTMLInputElement.prototype, 'value'
          ).set;
          setter.call(element, String(value));
          element.dispatchEvent(new Event('input', { bubbles: true }));
        }""",
        value,
    )
    page.wait_for_timeout(600)


_WHERE_THE_MIDDLE_IS = """() => {
  const v = window.zmartViewer;
  const space = v.navigationState.position.coordinateSpace.value;
  const drawn = new Set(v.navigationState.pose.displayDimensions.value.displayDimensionIndices);
  const middle = [], at = [];
  for (let axis = 0; axis < space.rank; axis += 1) {
    if (!drawn.has(axis)) continue;
    middle.push((space.bounds.lowerBounds[axis] + space.bounds.upperBounds[axis]) / 2);
    at.push(v.navigationState.position.value[axis]);
  }
  return { middle, at };
}"""


def test_the_viewer_opens_as_a_single_panel(viewer_page):
    assert viewer_page.evaluate("() => document.querySelectorAll('.neuroglancer-panel').length") == 1


def test_the_overview_button_brings_a_lost_picture_back(viewer_page):
    """Pan the specimen off the screen, and get it back in one click.

    This is the state the button exists for and it is worth saying why it cannot
    be reached any other way: the only recentring the engine offers is its right
    button, which centres on the point clicked, and once nothing of the specimen
    is on screen there is nothing left to click on.
    """
    point = centre(viewer_page)
    for _ in range(4):
        drag(viewer_page, point["x"], point["y"], 300, 220)
    lost = viewer_page.evaluate(_WHERE_THE_MIDDLE_IS)
    assert any(
        abs(where - middle) > 1
        for where, middle in zip(lost["at"], lost["middle"], strict=True)
    ), "the drag did not move the view off the picture, so the test proves nothing"

    viewer_page.get_by_role("button", name="Overview").click()
    viewer_page.wait_for_timeout(800)

    found = viewer_page.evaluate(_WHERE_THE_MIDDLE_IS)
    for where, middle in zip(found["at"], found["middle"], strict=True):
        assert abs(where - middle) < 1, f"the view sits at {where}, not at the middle {middle}"


_HOW_THE_PICTURE_FITS = """() => {
  const v = window.zmartViewer;
  const space = v.navigationState.position.coordinateSpace.value;
  const render = v.navigationState.pose.displayDimensionRenderInfo.value;
  const zoom = v.navigationState.zoomFactor.value;
  const panel = [...v.display.panels].find((p) => 'sliceView' in p);
  const viewport = [panel.renderViewport.logicalWidth, panel.renderViewport.logicalHeight];
  return Array.from(render.displayDimensionIndices).slice(0, 2).map((axis, slot) => {
    const extent = space.bounds.upperBounds[axis] - space.bounds.lowerBounds[axis];
    const pixels = (extent * render.canonicalVoxelFactors[slot]) / zoom;
    return pixels / viewport[slot];
  });
}"""

_HOW_THE_VOLUME_FITS = """() => {
  const v = window.zmartViewer;
  const space = v.navigationState.position.coordinateSpace.value;
  const render = v.navigationState.pose.displayDimensionRenderInfo.value;
  const panel = [...v.display.panels].find(
    (p) => 'sliceViews' in p && !('sliceView' in p));
  const width = panel.renderViewport.logicalWidth;
  const height = panel.renderViewport.logicalHeight;
  const perPixel = v.perspectiveNavigationState.zoomFactor.value / height;
  const smaller = Math.min(width, height);
  return Array.from(render.displayDimensionIndices).slice(0, 3).map((axis, slot) => {
    const extent = space.bounds.upperBounds[axis] - space.bounds.lowerBounds[axis];
    const pixels = (extent * render.canonicalVoxelFactors[slot]) / perPixel;
    return pixels / smaller;
  });
}"""


def test_opening_lands_on_the_overview(viewer_page):
    """A freshly opened picture looks exactly as if Overview had been pressed.

    The engine's own default zoom knows nothing about the picture, so what an
    operator met first was some arbitrary magnification and a press of
    Overview to fix it. The first view is now the whole picture, sized to the
    window with the overview's own margin -- asserted through the same
    fractions the button's test uses, so the two can never drift apart.
    """
    shares = viewer_page.evaluate(_HOW_THE_PICTURE_FITS)
    assert all(share <= 0.87 for share in shares), (
        f"the picture opens spilling toward the window's edge: {shares}"
    )
    assert max(shares) >= 0.78, (
        f"the picture opens at {max(shares):.0%} of the window, not at the "
        "overview"
    )


def test_overview_fits_the_whole_picture_to_the_window(viewer_page):
    """Deep in detail, one press shows the whole picture, sized to the window.

    The fractions read back are how much of the window each drawn axis of the
    picture occupies. All must fit inside it, and the largest must genuinely
    fill it -- a button that merely zoomed far out would pass the first half
    and show the specimen as a speck, which is not an overview of anything.
    """
    point = centre(viewer_page)
    viewer_page.mouse.move(point["x"], point["y"])
    for _ in range(6):
        viewer_page.mouse.wheel(0, -300)
    viewer_page.wait_for_timeout(600)

    viewer_page.get_by_role("button", name="Overview").click()
    viewer_page.wait_for_timeout(800)

    shares = viewer_page.evaluate(_HOW_THE_PICTURE_FITS)
    assert all(share <= 0.87 for share in shares), (
        f"the picture reaches the window's edge with too little margin: {shares}"
    )
    assert max(shares) >= 0.78, (
        f"the picture fills at most {max(shares):.0%} of the window, which is "
        "zoomed out past an overview"
    )


def test_overview_fits_the_volume_too(viewer_page):
    """The same press in 3-D sizes the whole box to the window.

    The volume's zoom counts across the height of the panel rather than per
    pixel, and a box can be turned, so the box is fitted against the window's
    smaller side. The largest fraction must still genuinely fill it.
    """
    viewer_page.click("text=3D")
    viewer_page.wait_for_timeout(2000)
    point = centre(viewer_page)
    viewer_page.mouse.move(point["x"], point["y"])
    for _ in range(6):
        viewer_page.mouse.wheel(0, -300)
    viewer_page.wait_for_timeout(600)

    viewer_page.get_by_role("button", name="Overview").click()
    viewer_page.wait_for_timeout(800)

    shares = viewer_page.evaluate(_HOW_THE_VOLUME_FITS)
    assert all(share <= 0.87 for share in shares), (
        f"the volume reaches the window's edge with too little margin: {shares}"
    )
    assert max(shares) >= 0.78, (
        f"the volume fills at most {max(shares):.0%} of the window, which is "
        "zoomed out past an overview"
    )


def test_overview_leaves_the_plane_where_the_operator_put_it(viewer_page):
    """Going back to the whole field must not lose your place in the stack.

    Only the axes being drawn are moved. Depth and time are the operator's, and
    a control that quietly reset them would cost more than it gave.
    """
    point = centre(viewer_page)
    # Moved with the gesture rather than the slider, because the slider only
    # appears for an image with more than one plane and this test should hold for
    # any demo volume.
    viewer_page.mouse.move(point["x"], point["y"])
    viewer_page.keyboard.down("Shift")
    viewer_page.mouse.wheel(0, -300)
    viewer_page.keyboard.up("Shift")
    viewer_page.wait_for_timeout(600)
    before = viewer_page.evaluate(_STATE)

    drag(viewer_page, point["x"], point["y"], 320, 240)
    viewer_page.get_by_role("button", name="Overview").click()
    viewer_page.wait_for_timeout(800)

    after = viewer_page.evaluate(_STATE)
    assert after["zPosition"] == before["zPosition"], (
        "the overview moved the operator through the stack"
    )


def test_dragging_pans(viewer_page):
    before = viewer_page.evaluate(_STATE)
    point = centre(viewer_page)
    drag(viewer_page, point["x"], point["y"], 120, 80)
    after = viewer_page.evaluate(_STATE)
    assert after["position"] != before["position"], "drag did not move the position"


def test_the_plain_wheel_zooms_without_moving_through_z(viewer_page):
    """The gesture an operator makes first, doing what a browser taught them.

    Both halves are asserted. A wheel that zooms *and* steps z would be worse
    than either, and on a run one plane deep the z half would be invisible until
    somebody opened a stack.
    """
    before = viewer_page.evaluate(_STATE)
    point = centre(viewer_page)
    viewer_page.mouse.move(point["x"], point["y"])
    viewer_page.mouse.wheel(0, -300)
    viewer_page.wait_for_timeout(600)
    after = viewer_page.evaluate(_STATE)
    assert after["zoom"] != before["zoom"], "a plain wheel must zoom"
    assert after["zPosition"] == before["zPosition"], (
        "a plain wheel must not also move through z"
    )


def test_shift_wheel_steps_through_z_and_the_slider_follows(viewer_page):
    """Stepping through the stack, moved off the plain wheel but not lost.

    The slider is asserted alongside because it is the reason this could be
    moved at all: the stack has a home that shows where in it you are, which a
    gesture cannot.
    """
    before = viewer_page.evaluate(_STATE)
    slider_before = float(viewer_page.locator("[aria-label='z position']").input_value())
    point = centre(viewer_page)
    viewer_page.mouse.move(point["x"], point["y"])
    viewer_page.keyboard.down("Shift")
    viewer_page.mouse.wheel(0, -300)
    viewer_page.keyboard.up("Shift")
    viewer_page.wait_for_timeout(600)
    after = viewer_page.evaluate(_STATE)
    assert after["zPosition"] != before["zPosition"], "shift+wheel must step z"
    slider_after = float(viewer_page.locator("[aria-label='z position']").input_value())
    assert slider_after != slider_before, "stepping z must update the Z slider"
    assert slider_after == pytest.approx(after["zPosition"])


def test_the_wheel_zooms_the_volume_too(viewer_page):
    """The panel that was left out, and what it cost to leave it out.

    The wheel was rebound to zoom on the flat panel only, so the volume view kept
    the engine's defaults -- wheel steps z, zoom behind Control. On a run one
    plane deep that leaves the wheel doing nothing whatever in three dimensions,
    and an operator who has just been taught that the wheel zooms concludes the
    volume renderer is stuck at its coarsest level. It is not; it refines the
    whole pyramid. Diagnosing that cost an afternoon and two reviews, all of it
    downstream of one panel missing from one loop.

    The volume view keeps its zoom in `perspectiveNavigationState`, a different
    trackable from the flat view's -- which is the same distinction that made the
    original measurement meaningless, so it is the one asserted here.
    """
    viewer_page.click("text=3D")
    viewer_page.wait_for_timeout(2000)
    zoom_of = "() => window.zmartViewer.perspectiveNavigationState.zoomFactor.value"
    before = float(viewer_page.evaluate(zoom_of))
    point = centre(viewer_page)
    viewer_page.mouse.move(point["x"], point["y"])
    viewer_page.mouse.wheel(0, -300)
    viewer_page.wait_for_timeout(600)
    after = float(viewer_page.evaluate(zoom_of))
    assert after != before, (
        "a plain wheel must zoom the volume as it zooms the plane; the "
        "projection zoom did not move"
    )


_FLAT_FIELD = "() => window.zmartViewer.navigationState.zoomFactor.value"

_VOLUME_FIELD = """() => {
  const v = window.zmartViewer;
  const panel = [...v.display.panels].find(
    (p) => 'sliceViews' in p && !('sliceView' in p));
  return v.perspectiveNavigationState.zoomFactor.value
       / panel.renderViewport.logicalHeight;
}"""


def test_switching_modes_keeps_the_field_and_the_place(viewer_page):
    """2-D and 3-D show the same stretch of specimen, before and after a switch.

    The two views keep separate zooms and count them differently -- the flat
    zoom is specimen per screen pixel, the volume zoom is specimen across the
    height of the panel -- so without conversion a switch jumps the
    magnification to wherever the other view happened to last be. Both
    directions are asserted, each after the operator has zoomed, and the
    position must not move either way.
    """
    point = centre(viewer_page)
    viewer_page.mouse.move(point["x"], point["y"])
    for _ in range(3):
        viewer_page.mouse.wheel(0, -300)
    viewer_page.wait_for_timeout(600)
    flat_before = viewer_page.evaluate(_FLAT_FIELD)
    place_before = viewer_page.evaluate(_STATE)["position"]

    viewer_page.click("text=3D")
    viewer_page.wait_for_timeout(2000)
    assert viewer_page.evaluate(_VOLUME_FIELD) == pytest.approx(flat_before, rel=0.01), (
        "switching to 3-D changed how much specimen the window shows"
    )
    assert viewer_page.evaluate(_STATE)["position"] == place_before, (
        "switching to 3-D moved the position"
    )

    viewer_page.mouse.move(point["x"], point["y"])
    for _ in range(2):
        viewer_page.mouse.wheel(0, -300)
    viewer_page.wait_for_timeout(600)
    volume_before = viewer_page.evaluate(_VOLUME_FIELD)
    place_before = viewer_page.evaluate(_STATE)["position"]

    viewer_page.click("text=2D")
    viewer_page.wait_for_timeout(2000)
    assert viewer_page.evaluate(_FLAT_FIELD) == pytest.approx(volume_before, rel=0.01), (
        "switching back to 2-D changed how much specimen the window shows"
    )
    assert viewer_page.evaluate(_STATE)["position"] == place_before, (
        "switching back to 2-D moved the position"
    )


def test_dragging_rotates_once_in_three_d(viewer_page):
    viewer_page.click("text=3D")
    viewer_page.wait_for_timeout(2000)
    before = viewer_page.evaluate(_STATE)
    point = centre(viewer_page)
    drag(viewer_page, point["x"], point["y"], 100, -60)
    after = viewer_page.evaluate(_STATE)
    assert after["orientation"] != before["orientation"], "3-D drag did not rotate"


def test_the_plane_does_not_rotate(viewer_page):
    """In 2-D a drag pans; rotation would be a mode leaking where it shouldn't."""
    before = viewer_page.evaluate(_STATE)
    point = centre(viewer_page)
    drag(viewer_page, point["x"], point["y"], 100, -60)
    after = viewer_page.evaluate(_STATE)
    assert after["orientation"] == before["orientation"]


def test_z_slider_uses_the_loaded_coordinate_bounds(viewer_page):
    """The slider must span exactly the planes the loaded image actually has.

    The engine reports a stack whose plane centres sit on integer coordinates as
    an extent shifted by half a voxel — a 48-plane volume comes back as -0.5 to
    47.5 — so the reachable planes are the integers inside that range, 0 to 47.
    Taking a further one off the top end (which this test previously did, matching
    a bug in the slider) quietly put the last plane of every stack out of reach.
    """
    expected = viewer_page.evaluate(
        """() => {
          const space = window.zmartViewer.navigationState.position.coordinateSpace.value;
          const z = space.names.indexOf('z');
          return {
            min: Math.ceil(space.bounds.lowerBounds[z]),
            max: Math.floor(space.bounds.upperBounds[z]),
          };
        }"""
    )
    slider = viewer_page.locator("[aria-label='z position']")
    assert float(slider.get_attribute("min")) == expected["min"]
    assert float(slider.get_attribute("max")) == expected["max"]


def test_z_slider_moves_the_neuroglancer_position(viewer_page):
    slider = viewer_page.locator("[aria-label='z position']")
    target = float(slider.get_attribute("min")) + 3
    set_range(viewer_page, "z position", target)
    state = viewer_page.evaluate(_STATE)
    assert state["zPosition"] == pytest.approx(target)


def test_z_slider_hides_in_three_d_and_returns_with_position(viewer_page):
    slider = viewer_page.locator("[aria-label='z position']")
    target = float(slider.get_attribute("min")) + 4
    set_range(viewer_page, "z position", target)
    viewer_page.click("text=3D")
    viewer_page.wait_for_timeout(1000)
    assert viewer_page.locator("[aria-label='z position']").count() == 0
    viewer_page.click("text=2D")
    viewer_page.wait_for_timeout(1000)
    restored = float(viewer_page.locator("[aria-label='z position']").input_value())
    assert restored == pytest.approx(target)


_THE_VIEW = """() => {
  const v = window.zmartViewer;
  return {
    flatZoom: v.navigationState.zoomFactor.value,
    volumeZoom: v.perspectiveNavigationState.zoomFactor.value,
    flatTurn: Array.from(v.navigationState.pose.orientation.orientation),
    volumeTurn: Array.from(v.perspectiveNavigationState.pose.orientation.orientation),
    position: Array.from(v.navigationState.position.value),
  };
}"""


def _turn_and_wander(page):
    """Rotate the picture, zoom into it and pan off it, as an operator does."""
    page.evaluate("""() => {
      const v = window.zmartViewer;
      v.navigationState.pose.orientation.restoreState([0.2, 0.1, 0.3, 0.9]);
      v.perspectiveNavigationState.pose.orientation.restoreState([0.3, 0.2, 0.1, 0.9]);
      v.navigationState.zoomFactor.value = v.navigationState.zoomFactor.value / 8;
      v.perspectiveNavigationState.zoomFactor.value =
        v.perspectiveNavigationState.zoomFactor.value / 8;
      const p = v.navigationState.position;
      const moved = Float32Array.from(p.value);
      moved[moved.length - 1] += 400;
      moved[moved.length - 2] += 400;
      p.value = moved;
    }""")
    page.wait_for_timeout(600)


def test_overview_puts_the_whole_view_back(viewer_page):
    """One press undoes every wandering: the turn, the zoom and the place.

    Overview means the same thing in both views: put everything about the
    VIEW back to how it opened, so there is a way out of any arrangement
    without reopening the data. It briefly shared the top-left corner with a
    Reset that did the straightening while Overview only fitted -- a split
    that showed up as one button behaving differently in 2-D and in 3-D, and
    that is not a distinction two button faces can carry (2026-08-20).

    What it must not touch is where the operator is in depth or in time: that
    is which picture they are looking at, not how.
    """
    page = viewer_page
    opening = page.evaluate(_THE_VIEW)
    _turn_and_wander(page)
    disturbed = page.evaluate(_THE_VIEW)
    assert disturbed["flatTurn"] != opening["flatTurn"], (
        "the harness failed to turn the picture, so this proves nothing"
    )

    page.get_by_role("button", name="Overview", exact=True).click()
    page.wait_for_timeout(900)
    back = page.evaluate(_THE_VIEW)

    assert back["flatTurn"] == pytest.approx(opening["flatTurn"], abs=1e-4), (
        f"the picture is still turned: {back['flatTurn']}"
    )
    assert back["flatZoom"] == pytest.approx(opening["flatZoom"], rel=0.02), (
        f"the magnification is {back['flatZoom']}, not the {opening['flatZoom']} "
        "it opened at"
    )
    on_screen = back["position"][-2:]
    assert on_screen == pytest.approx(opening["position"][-2:], abs=1.0), (
        "the view did not come back to the middle of the picture"
    )


def test_overview_puts_the_volume_back_too(viewer_page):
    """The same press, in the view where turning is the whole point."""
    page = viewer_page
    page.click("text=3D")
    page.wait_for_timeout(1500)
    opening = page.evaluate(_THE_VIEW)
    _turn_and_wander(page)
    page.get_by_role("button", name="Overview", exact=True).click()
    page.wait_for_timeout(900)
    back = page.evaluate(_THE_VIEW)

    assert back["volumeTurn"] == pytest.approx(opening["volumeTurn"], abs=1e-4), (
        f"the volume is still turned: {back['volumeTurn']}"
    )
    assert back["volumeZoom"] == pytest.approx(opening["volumeZoom"], rel=0.02), (
        f"the volume sits at {back['volumeZoom']}, not the {opening['volumeZoom']} "
        "it opened at"
    )


def test_overview_leaves_the_plane_and_the_moment_alone(viewer_page):
    """Where you are in the stack is not a view setting.

    Losing your place in depth because you asked for the view to be put
    straight would be its own small betrayal.
    """
    page = viewer_page
    names = page.evaluate(
        "() => Array.from(window.zmartViewer.coordinateSpace.value.names)")
    if "z" not in names:
        pytest.skip("this demo volume has no depth to keep a place in")
    at = names.index("z")
    page.evaluate("""(axis) => {
      const p = window.zmartViewer.navigationState.position;
      const moved = Float32Array.from(p.value);
      moved[axis] = moved[axis] + 2;
      p.value = moved;
    }""", at)
    page.wait_for_timeout(400)
    deep = page.evaluate(_THE_VIEW)["position"][at]
    page.get_by_role("button", name="Overview", exact=True).click()
    page.wait_for_timeout(900)
    assert page.evaluate(_THE_VIEW)["position"][at] == pytest.approx(deep, abs=0.01), (
        "putting the view straight moved the operator to a different plane"
    )

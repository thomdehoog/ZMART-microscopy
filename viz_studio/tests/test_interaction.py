"""Can the operator actually navigate, in both modes?

This is the regression guard for a bug that made the viewer look finished and
be unusable: neuroglancer's panels received every mouse event, the volume
rendered, and nothing moved -- because ``makeMinimalViewer`` builds a viewer but
does not install the default input bindings. Rendering tests cannot catch that;
only driving the gestures can.

The gestures are neuroglancer's own defaults, checked in the layout we actually
ship -- a single plane, and the volume behind the 3-D toggle:

===================  =========================================
gesture              effect
===================  =========================================
drag                 pans
plain wheel          steps one z-plane
control+wheel        zooms
drag in 3-D mode     rotates
===================  =========================================
"""

from __future__ import annotations

_STATE = """() => {
  const v = window.zmartViewer;
  return {
    position: Array.from(v.navigationState.position.value),
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


def test_the_viewer_opens_as_a_single_panel(viewer_page):
    assert viewer_page.evaluate("() => document.querySelectorAll('.neuroglancer-panel').length") == 1


def test_dragging_pans(viewer_page):
    before = viewer_page.evaluate(_STATE)
    point = centre(viewer_page)
    drag(viewer_page, point["x"], point["y"], 120, 80)
    after = viewer_page.evaluate(_STATE)
    assert after["position"] != before["position"], "drag did not move the position"


def test_plain_wheel_steps_through_z_without_zooming(viewer_page):
    before = viewer_page.evaluate(_STATE)
    point = centre(viewer_page)
    viewer_page.mouse.move(point["x"], point["y"])
    viewer_page.mouse.wheel(0, -300)
    viewer_page.wait_for_timeout(600)
    after = viewer_page.evaluate(_STATE)
    assert after["position"][0] != before["position"][0], "the wheel must step z"
    assert after["zoom"] == before["zoom"], "a plain wheel must scroll, not zoom"


def test_control_wheel_zooms(viewer_page):
    before = viewer_page.evaluate(_STATE)
    point = centre(viewer_page)
    viewer_page.mouse.move(point["x"], point["y"])
    viewer_page.keyboard.down("Control")
    viewer_page.mouse.wheel(0, -600)
    viewer_page.keyboard.up("Control")
    viewer_page.wait_for_timeout(600)
    after = viewer_page.evaluate(_STATE)
    assert after["zoom"] != before["zoom"], "control+wheel did not zoom"


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

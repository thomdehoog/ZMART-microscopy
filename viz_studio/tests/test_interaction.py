"""Can the operator actually navigate the volume?

This is the regression guard for a bug that made the viewer look finished and
be unusable: neuroglancer's panels received every mouse event, the volume
rendered, and nothing moved — because ``makeMinimalViewer`` builds a viewer but
does not install the default input bindings (its own entry points call
``setDefaultInputEventBindings`` separately). Rendering tests cannot catch that;
only driving the gestures can.

The gestures asserted here are neuroglancer's own defaults:

===================  =========================================
gesture              effect
===================  =========================================
drag a slice panel   pans (moves the position)
plain wheel          steps one z-plane
control+wheel        zooms
drag the 3-D panel   rotates (changes the orientation)
===================  =========================================
"""

from __future__ import annotations

import pytest

_STATE = """() => {
  const v = window.zmartViewer;
  return {
    position: Array.from(v.navigationState.position.value),
    zoom: v.navigationState.zoomFactor.value,
    orientation: Array.from(v.perspectiveNavigationState.pose.orientation.orientation),
  };
}"""

# The 3-D panel renders many slice views at once (``sliceViews``); a
# cross-section panel holds exactly one (``sliceView``). That distinction
# survives minification, unlike class names.
_PANELS = """() => Array.from(window.zmartViewer.display.panels).map(p => {
  const r = p.element.getBoundingClientRect();
  return {
    cx: Math.round(r.x + r.width / 2),
    cy: Math.round(r.y + r.height / 2),
    perspective: 'sliceViews' in p,
  };
})"""


def panels(page):
    found = page.evaluate(_PANELS)
    assert len(found) == 4, f"expected the 4panel layout, got {len(found)}"
    return found


def slice_panel(page):
    return next(p for p in panels(page) if not p["perspective"])


def perspective_panel(page):
    matches = [p for p in panels(page) if p["perspective"]]
    assert len(matches) == 1, f"expected exactly one 3-D panel, got {len(matches)}"
    return matches[0]


def drag(page, x, y, dx, dy):
    page.mouse.move(x, y)
    page.mouse.down()
    for step in range(1, 11):
        page.mouse.move(x + dx * step / 10, y + dy * step / 10)
    page.mouse.up()
    page.wait_for_timeout(500)


def test_the_four_panel_layout_has_three_slices_and_one_three_d(viewer_page):
    found = panels(viewer_page)
    assert sum(p["perspective"] for p in found) == 1
    assert sum(not p["perspective"] for p in found) == 3


def test_dragging_a_slice_panel_pans_the_volume(viewer_page):
    before = viewer_page.evaluate(_STATE)
    target = slice_panel(viewer_page)
    drag(viewer_page, target["cx"], target["cy"], 120, 80)
    after = viewer_page.evaluate(_STATE)
    assert after["position"] != before["position"], "drag did not move the position"


def test_plain_wheel_steps_through_z(viewer_page):
    before = viewer_page.evaluate(_STATE)
    target = slice_panel(viewer_page)
    viewer_page.mouse.move(target["cx"], target["cy"])
    viewer_page.mouse.wheel(0, -300)
    viewer_page.wait_for_timeout(500)
    after = viewer_page.evaluate(_STATE)
    assert after["position"] != before["position"]
    assert after["zoom"] == before["zoom"], "a plain wheel must scroll, not zoom"


def test_control_wheel_zooms(viewer_page):
    before = viewer_page.evaluate(_STATE)
    target = slice_panel(viewer_page)
    viewer_page.mouse.move(target["cx"], target["cy"])
    viewer_page.keyboard.down("Control")
    viewer_page.mouse.wheel(0, -600)
    viewer_page.keyboard.up("Control")
    viewer_page.wait_for_timeout(500)
    after = viewer_page.evaluate(_STATE)
    assert after["zoom"] != before["zoom"], "control+wheel did not zoom"


def test_dragging_the_three_d_panel_rotates_the_volume(viewer_page):
    before = viewer_page.evaluate(_STATE)
    target = perspective_panel(viewer_page)
    drag(viewer_page, target["cx"], target["cy"], 100, -60)
    after = viewer_page.evaluate(_STATE)
    assert after["orientation"] != before["orientation"], "3-D drag did not rotate"
    assert after["orientation"] != pytest.approx([0.0, 0.0, 0.0, 1.0]), (
        "orientation is still the identity quaternion"
    )

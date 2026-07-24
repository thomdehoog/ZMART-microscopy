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
    slider_before = float(viewer_page.locator("[aria-label='z position']").input_value())
    point = centre(viewer_page)
    viewer_page.mouse.move(point["x"], point["y"])
    viewer_page.mouse.wheel(0, -300)
    viewer_page.wait_for_timeout(600)
    after = viewer_page.evaluate(_STATE)
    assert after["zPosition"] != before["zPosition"], "the wheel must step z"
    assert after["zoom"] == before["zoom"], "a plain wheel must scroll, not zoom"
    slider_after = float(viewer_page.locator("[aria-label='z position']").input_value())
    assert slider_after != slider_before, "wheel movement must update the Z slider"
    assert slider_after == pytest.approx(after["zPosition"])


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


def test_z_slider_uses_the_loaded_coordinate_bounds(viewer_page):
    expected = viewer_page.evaluate(
        """() => {
          const space = window.zmartViewer.navigationState.position.coordinateSpace.value;
          const z = space.names.indexOf('z');
          return {
            min: Math.ceil(space.bounds.lowerBounds[z]),
            max: Math.floor(space.bounds.upperBounds[z] - 1),
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

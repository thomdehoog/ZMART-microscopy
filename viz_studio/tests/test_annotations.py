"""Annotations stay Neuroglancer-native while React supplies operator controls."""

from __future__ import annotations

import json


def add_box(page, annotation_id="browser-box"):
    page.evaluate(
        """(id) => {
          const source = window.zmartAnnotationSource;
          const reference = source.add({
            id,
            type: 2,
            description: "",
            pointA: new Float32Array([2, 3, 4]),
            pointB: new Float32Array([8, 9, 10]),
            properties: [],
          }, true);
          reference.dispose();
        }""",
        annotation_id,
    )


def test_targets_panel_and_native_annotation_source_are_present(viewer_page):
    viewer_page.wait_for_function("() => window.zmartAnnotationSource !== undefined")
    assert viewer_page.get_by_label("targets panel").is_visible()
    assert viewer_page.evaluate(
        """() => {
          const layer = window.zmartViewer.layerManager.getLayerByName("Targets").layer;
          return layer.localAnnotations === window.zmartAnnotationSource;
        }"""
    )


def test_point_and_box_buttons_install_neuroglancer_tools(viewer_page):
    """The two drawing buttons hand Neuroglancer its own placement tools.

    The names are matched exactly: a saved target in the list below is labelled
    "Box 1", which a loose match would also select, and the test would then be
    clicking a list row instead of the tool button.
    """
    viewer_page.get_by_role("button", name="Point", exact=True).click()
    assert viewer_page.evaluate(
        "() => window.zmartViewer.layerManager.getLayerByName('Targets').layer.tool.value.toJSON()"
    ) == "annotatePoint"
    viewer_page.get_by_role("button", name="Box", exact=True).click()
    assert viewer_page.evaluate(
        "() => window.zmartViewer.layerManager.getLayerByName('Targets').layer.tool.value.toJSON()"
    ) == "annotateBoundingBox"


def test_source_changes_drive_list_selection_and_delete(viewer_page):
    add_box(viewer_page)
    row = viewer_page.get_by_role("button", name="Box 1")
    row.wait_for()
    row.click()
    assert viewer_page.evaluate("() => window.zmartSelectedTarget") == "browser-box"
    viewer_page.get_by_label("delete target 1").click()
    viewer_page.get_by_text("Draw a point or box in the image.").wait_for()
    assert viewer_page.evaluate("() => window.zmartAnnotationSource.get('browser-box')") is None


def test_color_and_visibility_reach_the_annotation_layer(viewer_page):
    viewer_page.get_by_label("target color").fill("#00ff88")
    viewer_page.wait_for_timeout(400)
    state = viewer_page.evaluate(
        "() => window.zmartViewer.layerManager.getLayerByName('Targets').toJSON()"
    )
    assert state["annotationColor"].lower() == "#00ff88"
    viewer_page.get_by_text("show", exact=True).click()
    viewer_page.wait_for_timeout(400)
    assert not viewer_page.evaluate(
        "() => window.zmartViewer.layerManager.getLayerByName('Targets').visible"
    )


def test_box_goto_sends_named_physical_coordinates(viewer_page):
    captured = []
    viewer_page.on(
        "request",
        lambda request: captured.append(request.post_data)
        if request.url.endswith("/api/goto")
        else None,
    )
    add_box(viewer_page, "goto-box")
    viewer_page.get_by_role("button", name="Go to").click()
    viewer_page.wait_for_timeout(300)
    payload = json.loads(captured[-1])
    assert payload["id"] == "goto-box"
    assert set(payload["pointA"]) >= {"z", "y", "x"}
    for corner in ("pointA", "pointB"):
        for coordinate in payload[corner].values():
            assert isinstance(coordinate["value"], (int, float))
            assert "unit" in coordinate

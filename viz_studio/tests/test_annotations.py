"""Annotations stay Neuroglancer-native while React supplies operator controls."""

from __future__ import annotations


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
    viewer_page.get_by_text("then click", exact=False).wait_for()
    assert viewer_page.evaluate("() => window.zmartAnnotationSource.get('browser-box')") is None


def test_a_target_survives_an_unrelated_change(viewer_page):
    """Adjusting how the picture looks must not wipe out what has been drawn on it.

    A drawn target lives inside its own layer in the engine. For a while, every
    change made in the panel handed Neuroglancer a fresh description of the whole
    scene — and Neuroglancer takes that as "start again" rather than "here is what
    is different", so it threw every layer away and built them all afresh. Nudging
    a contrast slider therefore quietly destroyed the layer holding the targets and
    put an empty one in its place. The list beside the image still showed the
    target, because that list is ours and nothing had told it otherwise; the target
    itself was gone from the image. It looked, from the operator's chair, like the
    viewer losing their work at random.

    So this checks both halves: the drawing is still there afterwards, and the
    engine was not made to rebuild anything to get there.
    """
    add_box(viewer_page, "kept-through-a-change")
    viewer_page.get_by_role("button", name="Box 1").wait_for()

    # An ordinary adjustment, of the sort made constantly while looking at data.
    viewer_page.get_by_label("opacity structure").fill("0.4")
    viewer_page.wait_for_timeout(600)

    assert viewer_page.evaluate(
        "() => window.zmartAnnotationSource.get('kept-through-a-change') !== undefined"
    ), "the drawn target was lost from the engine when the picture was adjusted"
    assert viewer_page.evaluate("() => window.zmartLayersReshaped") == 0, (
        "adjusting the picture rebuilt layers; on a large acquisition that means "
        "refetching image that was already in hand"
    )


def test_color_and_visibility_reach_the_annotation_layer(viewer_page):
    viewer_page.get_by_label("target color").fill("#00ff88")
    viewer_page.wait_for_timeout(400)
    state = viewer_page.evaluate(
        "() => window.zmartViewer.layerManager.getLayerByName('Targets').toJSON()"
    )
    assert state["annotationColor"].lower() == "#00ff88"
    viewer_page.get_by_text("show on image", exact=True).click()
    viewer_page.wait_for_timeout(400)
    assert not viewer_page.evaluate(
        "() => window.zmartViewer.layerManager.getLayerByName('Targets').visible"
    )

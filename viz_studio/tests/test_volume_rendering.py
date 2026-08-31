"""The 2-D/3-D toggle: one viewer, two ways of looking at the same volume.

The everyday view is a single plane you scroll through. One click ray-casts the
same data instead. Both are silently acceptable to neuroglancer if wired
wrongly -- a misspelled property or a shader that emits no alpha leaves you
looking at a plane and wondering -- so these read the engine's own state rather
than trusting the click.
"""

from __future__ import annotations

import pytest
from server import make_server

_STATE = """() => {
  const v = window.zmartViewer;
  const layer = v.layerManager.managedLayers[0].layer;
  return {
    mode: window.zmartMode,
    volumeMode: layer.volumeRenderingMode.value,
    shader: layer.fragmentMain.value,
    layout: JSON.stringify(v.layout.toJSON()),
    panels: document.querySelectorAll('.neuroglancer-panel').length,
    annotations: v.showDefaultAnnotations.value,
    axisLines: v.showAxisLines.value,
    depthSamples: layer.volumeRenderingDepthSamplesTarget.value,
  };
}"""


def click_mode(page, label: str) -> None:
    page.click(f"text={label}")
    page.wait_for_timeout(1500)


def test_it_opens_on_a_single_plane_not_a_panel_grid(viewer_page):
    """vizarr-like by default: one view, no four-panel grid."""
    state = viewer_page.evaluate(_STATE)
    assert state["mode"] == "flat"
    assert state["panels"] == 1
    assert state["volumeMode"] == 0


def test_the_engine_s_own_furniture_is_hidden(viewer_page):
    """No yellow bounding box, no axis lines -- we supply the interface."""
    state = viewer_page.evaluate(_STATE)
    assert state["annotations"] is False
    assert state["axisLines"] is False


def test_the_plane_scrolls_through_z(viewer_page):
    """Neuroglancer's panel names follow display axes; OME-Zarr arrives z,y,x.

    Its "yz" panel is the one whose wheel steps z -- verified here, because the
    intuitive choice ("xy") steps x instead and looks correct while being wrong.

    **On shift and the wheel, since 6 August 2026.** The plain wheel zooms in this
    viewer; `CONTROLS.md` §1 records the decision and `test_interaction.py` guards
    both halves of it. What is checked here is unchanged in substance -- that the
    gesture bound to stepping z steps z and does not pan -- only which gesture that
    is.
    """
    viewer_page.mouse.move(600, 450)
    viewer_page.keyboard.down("Shift")
    # One notch first, and its result deliberately ignored. A view opens centred,
    # which for an even number of planes is halfway between two of them, and the
    # first move settles onto the nearer one -- so that first step also shifts the
    # other axes by half a voxel. That is the engine tidying up, not panning, and
    # measuring across it would fail the test for something that is quite correct.
    viewer_page.mouse.wheel(0, -120)
    viewer_page.wait_for_timeout(600)
    before = viewer_page.evaluate("() => Array.from(window.zmartViewer.navigationState.position.value)")
    for _ in range(3):
        viewer_page.mouse.wheel(0, -120)
    viewer_page.wait_for_timeout(1200)
    after = viewer_page.evaluate("() => Array.from(window.zmartViewer.navigationState.position.value)")
    viewer_page.keyboard.up("Shift")
    assert after[0] != before[0], "shift and the wheel must step z"
    assert after[1:] == before[1:], "stepping z must not pan"


# What tells the two shaders apart, and it has had to move twice.
#
# It was once "does this emit alpha at all", because the flat view drew solid
# colour. That stopped working when a flat row had to come out transparent where
# nothing has been imaged, or the topmost row blacks out every row beneath it and
# an experiment with two channels shows only one of them.
#
# It was then the opacity control, which lived only in the volume shader. That
# stopped working on 6 August 2026, when the flat shader was given one too --
# because the bottom-most row is drawn with blending off, so an opacity that
# reaches the picture only through the alpha does nothing at all there. See
# `test_opacity_reaches_the_flat_picture.py`.
#
# What is left is the depth fade, which is the one control that could not mean
# anything in a plane: there is no ray to fade along. If it ever gains a flat
# meaning, this has to move again -- and the way to tell will be this test
# failing, which is the point of keeping it a named constant.
VOLUME_ONLY_CONTROL = "attenuation"

# Neuroglancer's own numbering: OFF 0, ON 1, MAX 2, MIN 3. The viewer opens a
# volume on the brightest-along-the-ray projection rather than on accumulation;
# `test_the_volume_projection_can_be_chosen.py` has the measurement behind that.
RAY_CASTING = 2


def test_clicking_3d_switches_to_volume_rendering(viewer_page):
    click_mode(viewer_page, "3D")
    state = viewer_page.evaluate(_STATE)
    assert state["mode"] == "volume"
    assert state["volumeMode"] == RAY_CASTING, "the engine did not enter volume rendering"
    assert "emitRGBA" in state["shader"], "any shader here must emit alpha"
    assert VOLUME_ONLY_CONTROL in state["shader"], (
        f"the volume shader must be the one loaded: {state['shader']}"
    )
    assert state["layout"] == '"3d"'


def test_switching_back_restores_the_plane(viewer_page):
    click_mode(viewer_page, "3D")
    click_mode(viewer_page, "2D")
    state = viewer_page.evaluate(_STATE)
    assert state["mode"] == "flat"
    assert state["volumeMode"] == 0
    assert "emitRGBA" in state["shader"], (
        "a flat row emits alpha too, so that unimaged ground is transparent"
    )
    assert VOLUME_ONLY_CONTROL not in state["shader"], (
        f"the volume shader was left in place: {state['shader']}"
    )
    assert state["panels"] == 1


def test_the_two_modes_use_different_windows(viewer_page):
    """A background-level window is right for a plane and fog in a volume."""
    flat = viewer_page.evaluate("() => window.zmartConfig.layers[0].window")
    volume = viewer_page.evaluate("() => window.zmartConfig.layers[0].volumeWindow")
    assert flat is not None and volume is not None
    assert volume["low"] >= flat["low"]


def test_depth_samples_reach_the_engine(browser, built_dist, demo_store):
    """What actually sets 3-D resolution; the default of 64 stays coarse."""
    import threading

    server = make_server(port=0, data_dir=demo_store, site_dir=built_dist, depth_samples=512)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1200, "height": 900})
    try:
        page.goto(f"http://127.0.0.1:{server.server_address[1]}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.zmartConfig !== undefined", timeout=30_000)
        page.wait_for_function(
            "() => window.zmartViewer.layerManager.managedLayers.length > 0", timeout=30_000
        )
        click_mode(page, "3D")
        assert page.evaluate(_STATE)["depthSamples"] == 512
    finally:
        page.close()
        server.shutdown()
        thread.join(timeout=5)


@pytest.mark.parametrize("label", ["2D", "3D"])
def test_both_buttons_are_present(viewer_page, label):
    assert viewer_page.locator(f"text={label}").count() == 1

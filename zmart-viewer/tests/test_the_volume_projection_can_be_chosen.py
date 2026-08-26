"""How a ray becomes a colour, and letting the operator choose.

Neuroglancer offers four ways of turning the voxels along a line of sight into one
pixel -- off, accumulated, brightest, darkest -- and until 6 August 2026 this
viewer used one of them, written into `scene.js` as a bare string, with nothing on
screen to change it.

It had picked the least forgiving one. Accumulating every voxel a ray passes is
right for dense specimen and wrong for fluorescence, where a run is mostly empty:
measured over a thousand positions, accumulation gave a spread of **8 grey levels**
against **41** for the brightest-voxel projection. The picture was milky, and the
only way out was to tune a transparency that -- as it happens -- was wired to
nothing (see `test_interaction.py` and the opacity finding of the same day).

A projection is also what a microscopist means by looking at a stack in three
dimensions; napari calls it `mip`. So it is now the default, and the other two are
a dropdown away.
"""

from __future__ import annotations

import statistics

MODE_OF_EACH_LAYER = """() => window.zmartViewer.layerManager.managedLayers
    .filter((m) => m.layer && m.layer.type === 'image')
    .map((m) => m.layer.volumeRenderingMode.value)"""

# Neuroglancer's own numbering: OFF 0, ON 1, MAX 2, MIN 3.
OFF, ON, MAX, MIN = 0, 1, 2, 3


def _spread(page) -> float:
    """How much light and shade the picture has, as grey levels.

    The mean says nothing useful here -- a milky picture and a crisp one can share
    it. What separates them is whether anything stands out from anything else.
    """
    import io

    from PIL import Image
    # A generous deadline on purpose. The screenshot waits for a stable
    # frame, and the accumulation projection of the demo volume takes ~35 s
    # to draw one on a machine rendering in software (measured 2026-08-15;
    # the projection mode draws the same frame in under 3 s). This gate is
    # about the two pictures DIFFERING, never about speed -- the drawing-rate
    # gates own speed -- so it must not fail on a machine that merely has no
    # GPU.
    shot = page.screenshot(clip={"x": 0, "y": 0, "width": 600, "height": 600},
                           timeout=180_000)
    return statistics.pstdev(list(Image.open(io.BytesIO(shot)).convert("L").getdata()))


def test_the_volume_opens_as_a_projection_not_an_accumulation(viewer_page):
    """The default, and the whole reason for the change."""
    viewer_page.click("text=3D")
    viewer_page.wait_for_timeout(4000)
    modes = viewer_page.evaluate(MODE_OF_EACH_LAYER)
    assert modes and set(modes) == {MAX}, modes


def test_choosing_a_projection_reaches_the_engine(viewer_page):
    viewer_page.click("text=3D")
    viewer_page.wait_for_timeout(4000)
    chooser = viewer_page.locator("[aria-label='volume projection']")
    for chosen, expected in (("on", ON), ("min", MIN), ("max", MAX)):
        chooser.select_option(chosen)
        viewer_page.wait_for_timeout(2500)
        modes = viewer_page.evaluate(MODE_OF_EACH_LAYER)
        assert modes and set(modes) == {expected}, (chosen, modes)


def test_the_detail_budget_can_be_changed_without_restarting(viewer_page):
    """How many steps a ray takes, which decides how sharp the volume may be.

    It was a launch flag, and finding the right value therefore meant restarting
    the viewer once per guess. The right value is not knowable in advance: on a
    75 GB skin volume, 256 left the picture on its coarsest copy however far you
    zoomed in, 2048 refined properly once zoomed in, and 32768 refined from the
    opening view and was too slow to drive. All three had to be tried by hand.

    The steps double, because the engine compares a level's voxel against the
    cube of one ray step, so the useful settings are spread over orders of
    magnitude rather than evenly.
    """
    viewer_page.click("text=3D")
    viewer_page.wait_for_timeout(4000)
    slider = viewer_page.locator("[aria-label='volume detail']")
    reaches = """() => window.zmartViewer.layerManager.managedLayers
        .filter((m) => m.layer && m.layer.volumeRenderingDepthSamplesTarget)
        .map((m) => m.layer.volumeRenderingDepthSamplesTarget.value)"""
    for step, expected in ((8, 256), (11, 2048), (6, 64)):
        slider.fill(str(step))
        viewer_page.wait_for_timeout(2000)
        reached = viewer_page.evaluate(reaches)
        assert reached and set(reached) == {expected}, (step, reached)


def test_the_chooser_is_only_offered_where_it_means_something(viewer_page):
    """A flat slice has no ray to project along, so the control is not shown."""
    assert viewer_page.locator("[aria-label='volume projection']").count() == 0
    viewer_page.click("text=3D")
    viewer_page.wait_for_timeout(4000)
    assert viewer_page.locator("[aria-label='volume projection']").count() == 1


def test_the_two_projections_do_not_draw_the_same_picture(viewer_page):
    """That the choice reaches the screen, without claiming which is better.

    The first version of this asserted that the projection always stands out more
    than the accumulation, because on a plate of sparse positions it does --
    measured at 41 grey levels of spread against 8. On the dense demo volume the
    order reverses: 102 against 66. Both are true, and which mode suits depends on
    whether the specimen is mostly empty, so the guard is that the control *does*
    something rather than that one answer is right.
    """
    viewer_page.click("text=3D")
    viewer_page.wait_for_timeout(4000)
    chooser = viewer_page.locator("[aria-label='volume projection']")

    chooser.select_option("max")
    viewer_page.wait_for_timeout(4000)
    projected = _spread(viewer_page)

    chooser.select_option("on")
    viewer_page.wait_for_timeout(4000)
    accumulated = _spread(viewer_page)

    assert abs(projected - accumulated) > 5.0, (
        f"the two projections drew much the same picture -- {projected:.1f} "
        f"against {accumulated:.1f} grey levels of spread -- so the choice is "
        "probably not reaching the screen"
    )
    assert min(projected, accumulated) > 5.0, (
        f"only {min(projected, accumulated):.1f} grey levels of spread -- the "
        "panel is nearly flat, so this compared two pictures of nothing"
    )

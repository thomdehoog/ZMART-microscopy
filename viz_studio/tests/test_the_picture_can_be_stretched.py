"""Stretching the picture along an axis, and what that does to the scale bar.

Anisotropic data is the ordinary case here -- 2 um in z against 0.325 in y and x
on a plate run, 5 against 0.85 on a fused volume -- and looking at it sometimes
wants the depth squashed or exaggerated. The engine keeps a factor per dimension
and applies it to the display alone, so this changes how the specimen is drawn
and nothing about what it claims to be.

**The factors are matched by axis name, not by position**, and that is the whole
reason this file exists. Neuroglancer holds *channel* dimensions separately from
the ones you can navigate, so a two-colour store presents `t, z, y, x` for
navigation while its array is `t, c, z, y, x`. An index that is right for one is
wrong for the other, and stretches the wrong axis without saying so.

**And the scale bar was measured rather than reasoned about.** It divides by the
engine's `canonicalVoxelFactors`, which are computed from these very factors, so
it follows a stretch instead of ignoring one. Quadrupling z leaves an in-plane
bar untouched -- correctly, since 30 um across is still 30 um across whatever was
done to depth. Only stretching x differently from y makes a single bar unable to
describe both directions, which is the one case worth warning about.
"""

from __future__ import annotations

FACTORS = """() => {
  const n = window.zmartViewer.navigationState;
  const names = n.coordinateSpace.value.names;
  const factors = Array.from(n.relativeDisplayScales.value.factors);
  return Object.fromEntries(names.map((name, i) => [name, factors[i]]));
}"""


def test_stretching_an_axis_reaches_the_engine(viewer_page):
    viewer_page.locator("[aria-label='stretch z']").fill("4")
    viewer_page.wait_for_timeout(1200)
    assert viewer_page.evaluate(FACTORS)["z"] == 4


def test_each_axis_is_matched_by_name_and_the_others_left_alone(viewer_page):
    """The fault an index would cause, pinned.

    Time is in the navigable space and channel is not, so the array's axis order
    and the engine's are different lists. Stretching z must move z and nothing
    else, whichever store is open.
    """
    viewer_page.locator("[aria-label='stretch z']").fill("3")
    viewer_page.wait_for_timeout(1200)
    got = viewer_page.evaluate(FACTORS)
    assert got["z"] == 3, got
    for axis, factor in got.items():
        if axis != "z":
            assert factor == 1, (axis, got)


def test_the_scale_bar_ignores_a_stretch_in_depth(viewer_page):
    """Because a bar describes the plane you are looking at, as Fiji's does."""
    before = viewer_page.locator("[aria-label='scale bar']").inner_text()
    viewer_page.locator("[aria-label='stretch z']").fill("4")
    viewer_page.wait_for_timeout(1500)
    assert viewer_page.locator("[aria-label='scale bar']").inner_text() == before


def test_the_scale_bar_follows_a_stretch_in_the_plane(viewer_page):
    before = viewer_page.locator("[aria-label='scale bar']").inner_text()
    viewer_page.locator("[aria-label='stretch x']").fill("2")
    viewer_page.locator("[aria-label='stretch y']").fill("2")
    viewer_page.wait_for_timeout(1500)
    assert viewer_page.locator("[aria-label='scale bar']").inner_text() != before


def test_only_a_sheared_aspect_is_warned_about(viewer_page):
    """Warning on a depth stretch would cry wolf on the ordinary case."""
    warning = viewer_page.get_by_text("no single scale bar is true", exact=False)
    viewer_page.locator("[aria-label='stretch z']").fill("4")
    viewer_page.wait_for_timeout(1000)
    assert warning.count() == 0, "a depth stretch keeps the bar true; do not warn"

    viewer_page.locator("[aria-label='stretch x']").fill("2")
    viewer_page.wait_for_timeout(1000)
    assert warning.count() == 1, "x and y now disagree, so the bar cannot be true"

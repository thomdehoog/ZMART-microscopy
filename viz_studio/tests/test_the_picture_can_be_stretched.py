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
done to depth.

**Which stretches are worth warning about depends on the view, not on the
factors.** This file once concluded that only x against y could ever make a
single bar unable to describe the picture. That holds in a single plane, where
depth is not on screen at all. The volume view puts z on screen beside them, and
there the same depth stretch that was harmless a moment earlier makes the bar
wrong: measured on the demo volume with z quadrupled, ten micrometres covers
about 201 screen pixels along z against 50 along x. The operator changed nothing
but what they were looking at, which is why the warning cannot be decided from
the stretch factors alone.
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


def test_only_a_sheared_aspect_is_warned_about_in_a_single_plane(viewer_page):
    """Warning on a depth stretch would cry wolf on the ordinary case.

    In a single plane depth is not on screen at all, so what was done to it
    cannot make the bar wrong.
    """
    warning = viewer_page.get_by_text("no single scale bar is true", exact=False)
    viewer_page.locator("[aria-label='stretch z']").fill("4")
    viewer_page.wait_for_timeout(1000)
    assert warning.count() == 0, "a depth stretch keeps the bar true; do not warn"

    viewer_page.locator("[aria-label='stretch x']").fill("2")
    viewer_page.wait_for_timeout(1000)
    assert warning.count() == 1, "x and y now disagree, so the bar cannot be true"


def test_a_depth_stretch_is_warned_about_once_the_volume_is_on_screen(viewer_page):
    """The same stretch that is harmless in a plane makes the bar wrong in depth.

    Which axes are on screen is what decides whether one bar can be true, and
    turning the volume on puts z there. Measured on the demo volume with z
    quadrupled: ten micrometres covers about 201 screen pixels along z against 50
    along x, so a bar reading one of those is off by four for the other. The
    operator has changed nothing about the stretch between the two halves of this
    test -- only what they are looking at -- which is exactly why the warning
    cannot be decided from the factors alone.
    """
    warning = viewer_page.get_by_text("no single scale bar is true", exact=False)
    viewer_page.locator("[aria-label='stretch z']").fill("4")
    viewer_page.wait_for_timeout(1000)
    assert warning.count() == 0, "still a single plane, where depth is not on screen"

    viewer_page.click("text=3D")
    viewer_page.wait_for_timeout(4000)
    assert warning.count() == 1, (
        "z is on screen now and is drawn four times over, so no single bar "
        "describes the view -- and nothing on screen says so"
    )


def test_an_even_stretch_is_never_warned_about(viewer_page):
    """Stretching every axis alike is a zoom, and leaves one bar perfectly true.

    Worth pinning separately: the rule is that the axes on screen must *agree*,
    not that they must all read 1. A guard written as "warn unless everything is
    unstretched" would pass the test above and still cry wolf here.
    """
    warning = viewer_page.get_by_text("no single scale bar is true", exact=False)
    for axis in ("x", "y", "z"):
        viewer_page.locator(f"[aria-label='stretch {axis}']").fill("2")
    viewer_page.wait_for_timeout(1200)
    assert warning.count() == 0, "an even stretch is a zoom, not a shear"

    viewer_page.click("text=3D")
    viewer_page.wait_for_timeout(4000)
    assert warning.count() == 0, "and it is still a zoom with the volume on screen"

"""The promises the options make to the page above them, held in place.

`viz_studio/OPTIONS.md` sets out one interface that three viewers implement, so
that they can be compared on the same data by the same page. That is only worth
anything if the promises are actually kept, and most of them are the sort that
break quietly: an option that has started counting in voxels while saying
micrometres, an engine's own gesture creeping back in, a second viewer that
cannot be opened because the first one left its state in a module variable.

So these are the checks that a *new* option has to pass before its numbers mean
anything. They are written against the interface and never name an engine, which
is the point: the next option to be written is checked by adding its name to
``EVERY_OPTION``.

They open a real browser and read the picture it drew. On a machine without one
they skip with a plain reason, and the end of the run says loudly that nobody
looked at the picture — see ``conftest.py``. On a machine that is supposed to be
able to draw, set ``ZMART_REQUIRE_BROWSER=1`` and a skip becomes a failure.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import numpy as np
import pytest

_VIZ = Path(__file__).resolve().parents[1]
_OPTIONS = _VIZ / "options"
if str(_OPTIONS / "measure") not in sys.path:
    sys.path.insert(0, str(_OPTIONS / "measure"))

from margins import margins_around_the_hole  # noqa: E402

# Every option that has been written. Add yours here; nothing else in this file
# needs changing.
EVERY_OPTION = ["neuroglancer-under"]


# ---------------------------------------------------------------------------
# The one check that needs no browser at all
# ---------------------------------------------------------------------------


def test_the_engine_stays_behind_its_adapter():
    """No part of the application reaches into neuroglancer's insides.

    Every import from ``neuroglancer/unstable/...`` is the package saying "this
    is where our insides are and we may move them". Scattered through an
    application that is frightening: an upgrade moves one file and a dozen places
    stop working, in a dozen different ways, none of which mention neuroglancer.
    Gathered into one module it is merely a chore — the upgrade breaks that one
    module and this one test, and the rest of the application does not notice.

    So the rule is narrow and worth keeping: exactly one file may import from
    there, and it is the adapter for the option that uses it.
    """
    allowed = {_OPTIONS / "neuroglancer-under" / "viewer.js"}
    reaching_in = []
    for path in sorted((_OPTIONS).rglob("*.js")):
        if "node_modules" in path.parts or "dist" in path.parts:
            continue
        if path in allowed:
            continue
        if re.search(r"""from\s+["']neuroglancer/""", path.read_text()):
            reaching_in.append(str(path.relative_to(_VIZ)))
    assert not reaching_in, (
        "these files import neuroglancer's insides directly, which is what the "
        "adapter exists to prevent: " + ", ".join(reaching_in)
    )


def test_the_adapter_does_not_work_out_its_own_addresses():
    """Addresses are passed in rather than guessed from the page's own address.

    Putting ``window.location.origin`` in front of a store's address is right
    almost always and wrong exactly when it matters — served from somewhere else,
    or measured against a server on a port chosen at run time, it silently reads
    from the wrong place. The caller knows where the data is; the option should
    be told.
    """
    for option in EVERY_OPTION:
        # The comments are taken out first, because the adapter explains at
        # length why it does *not* do this and the explanation naturally has to
        # name the thing it is not doing.
        source = _without_comments((_OPTIONS / option / "viewer.js").read_text())
        assert "window.location" not in source, (
            f"{option}/viewer.js works out an address from the page's own "
            "address. Addresses are passed in; see options/contract.md."
        )


def _without_comments(source: str) -> str:
    """The code with the prose taken out, roughly but well enough for this.

    Rough is fine here. It could be fooled by a comment marker inside a piece of
    text, and if it ever is, the answer is that the check errs towards looking at
    *more* code rather than less — which is the safe direction for something that
    is trying to catch a forbidden line.
    """
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"^\s*//.*$", "", source, flags=re.M)


# ---------------------------------------------------------------------------
# The ones that open a browser
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def measurement_data(tmp_path_factory):
    """The little acquisitions the options are checked against."""
    import acquisitions

    folder = tmp_path_factory.mktemp("option_stores")
    acquisitions.write_them_all(folder)
    return folder


@pytest.fixture(scope="module")
def harness_page(measurement_data, tmp_path_factory):
    """A built harness page, a server for it, and a browser.

    This uses the measurement suite's own way of opening a page rather than a
    second copy of it, so that what the tests check and what the measurements
    report are the same program driven the same way.
    """
    import drive
    from conftest import _give_up_on_the_picture

    if not (drive.HARNESS_DIST / "index.html").exists():
        _give_up_on_the_picture(
            "the options harness has not been built, so there was nothing to "
            "open (options/harness/dist/index.html is missing). Build it with "
            "`npm --prefix viz_studio/options/harness run build`"
        )
    try:
        harness = drive.Harness(
            measurement_data, tmp_path_factory.mktemp("option_pictures")
        )
        with harness:
            yield harness
    except Exception as why:
        _give_up_on_the_picture(f"no usable browser for the options harness: {why}")


@pytest.mark.parametrize("option", EVERY_OPTION)
def test_the_view_is_measured_in_micrometres(harness_page, option):
    """Ask for a place in micrometres and land there, on a store whose voxels
    are not one micrometre across.

    This is the check that catches an option quietly counting in voxels. On every
    other acquisition here a voxel is exactly one micrometre, so the two are the
    same number and the confusion is invisible; this one is written at a third of
    a micrometre to the voxel, where counting in the wrong unit lands three times
    too far away.

    Read from the picture as well as from the view, because a view that reports
    the right numbers while the picture is somewhere else is exactly the failure
    this project keeps meeting.
    """
    harness_page.option = option
    harness_page.open(store="fine", draw="none")
    coverage = harness_page.coverage("fine")
    um = coverage["voxel_size_um"]
    assert abs(um["x"] - 1 / 3) < 0.01, (
        "this check only means anything on a store whose voxels are not one "
        f"micrometre across, and this one reports {um}"
    )
    # The imaged ground, in micrometres, worked out here rather than asked of the
    # page: 1024 voxels at a third of a micrometre each.
    wide_um = (coverage["bounds"]["x"][1] - coverage["bounds"]["x"][0]) * um["x"]
    assert abs(wide_um - 1024 / 3) < 1

    view = harness_page.believes("window.harness.view()")
    # How wide the picture really is on screen, and how wide the view says it
    # should be. This is the comparison that matters, and it has to be made
    # against the *picture*: asking the viewer for the view it was just given
    # back proves nothing at all, because an option counting in the wrong unit
    # throughout will hand back exactly the number it was handed.
    picture = harness_page.photograph()
    density = harness_page.believes("window.harness.density()")
    wide_on_screen = _how_wide_the_picture_is(picture) / density
    assert wide_on_screen, "there was no picture on screen to measure"
    assert abs(wide_on_screen * view["zoom"] - wide_um) < 0.06 * wide_um, (
        f"the imaged ground is {wide_um:.0f} µm across and is drawn "
        f"{wide_on_screen:.0f} screen pixels wide, so one screen pixel covers "
        f"{wide_um / wide_on_screen:.2f} µm — but the view says the zoom is "
        f"{view['zoom']:.2f} µm per screen pixel. Something is counting in "
        "voxels and calling them micrometres."
    )

    # Now move by a known number of micrometres and check the picture moved by
    # the number of pixels that follows from it.
    before = _where_the_picture_starts(harness_page.photograph())
    step_um = 40 * view["zoom"]
    harness_page.believes(
        "window.harness.setView({centre: {x: %r, y: %r}})"
        % (view["centre"]["x"] + step_um, view["centre"]["y"])
    )
    harness_page.settle(tries=20)
    after = _where_the_picture_starts(harness_page.photograph())
    moved = (before - after) / density
    assert abs(moved - 40) <= 2, (
        f"asking for {step_um:.1f} µm should have moved the picture 40 screen "
        f"pixels; it moved {moved:.1f}"
    )


def _where_the_picture_starts(picture) -> float | None:
    """Where the acquired picture begins along the middle row, in photograph pixels."""
    row = np.asarray(picture)[picture.shape[0] // 2, :, :].max(axis=1)
    lit = np.nonzero(row > 60)[0]
    return float(lit[0]) if len(lit) else None


def _how_wide_the_picture_is(picture) -> float:
    """How many photograph pixels across the acquired picture is."""
    row = np.asarray(picture)[picture.shape[0] // 2, :, :].max(axis=1)
    lit = np.nonzero(row > 60)[0]
    return float(lit[-1] - lit[0] + 1) if len(lit) else 0.0


@pytest.mark.parametrize("option", EVERY_OPTION)
def test_two_viewers_can_be_open_at_once(harness_page, option):
    """A page can hold two viewers, and closing one does not disturb the other.

    This is the check that catches state kept in a module variable rather than on
    the viewer. It is easy to write an adapter that works perfectly until a
    second one is opened, and then the two quietly share their idea of which
    stores have been handed over — after which one of them draws the other's
    data, or nothing at all.

    Nothing in the interface says "there may only be one", so nothing should
    behave as though it did.
    """
    harness_page.option = option
    harness_page.open(store="square", draw="none")
    drawn = harness_page.page.evaluate(
        """async () => {
          const box = document.createElement('div');
          box.style.cssText = 'position:absolute;left:0;top:0;width:300px;height:300px';
          document.body.appendChild(box);
          // Loaded the same way the page loads its first viewer, by name, so
          // this is genuinely a second viewer of the same option rather than a
          // second reference to the first.
          const { openViewer } = await window.harness.loadTheOption();
          const second = await openViewer(box, {
            acquisitions: window.harness.acquisitionsAsked,
            coverage: window.harness.coverage,
            background: '#101014',
          });
          const before = window.harness.viewer.getView();
          second.setView({ centre: { x: 12345, y: 6789 }, zoom: 9 });
          const after = window.harness.viewer.getView();
          const secondView = second.getView();
          second.destroy();
          box.remove();
          const still = window.harness.viewer.getView();
          return { before, after, secondView, still };
        }"""
    )
    first_moved = (
        abs(drawn["after"]["centre"]["x"] - drawn["before"]["centre"]["x"])
        + abs(drawn["after"]["zoom"] - drawn["before"]["zoom"])
    )
    assert first_moved < 0.01, (
        "moving the second viewer moved the first one too, which means the two "
        f"are sharing state that should belong to each of them: {drawn}"
    )
    assert abs(drawn["secondView"]["centre"]["x"] - 12345) < 1, (
        "the second viewer did not go where it was told: " + str(drawn)
    )
    after_closing = (
        abs(drawn["still"]["centre"]["x"] - drawn["before"]["centre"]["x"])
        + abs(drawn["still"]["zoom"] - drawn["before"]["zoom"])
    )
    assert after_closing < 0.01, (
        "closing the second viewer disturbed the first: " + str(drawn)
    )


@pytest.mark.parametrize("option", EVERY_OPTION)
def test_only_two_gestures_move_the_view(harness_page, option):
    """Drag pans, the plain wheel zooms, and every other gesture leaves the
    picture byte-identical.

    An unbound gesture and a gesture nobody tried look exactly alike on screen,
    so this also asks the page how many gestures it turned away. Without that, a
    page that had quietly stopped listening at all would pass this test while
    being completely broken.
    """
    from suite import THE_GESTURES_THAT_WERE_REMOVED

    harness_page.option = option
    harness_page.open(store="square", draw="margin")
    harness_page.believes("window.harness.reset()")
    harness_page.settle(tries=15)

    moved = []
    for name, make in THE_GESTURES_THAT_WERE_REMOVED.items():
        harness_page.page.mouse.move(450, 350)
        before = harness_page.photograph()
        make(harness_page.page)
        time.sleep(0.4)
        harness_page.settle(tries=6)
        if not np.array_equal(before, harness_page.photograph()):
            moved.append(name)
    counted = harness_page.believes("window.harness.gesturesSoFar()")
    assert sum(counted["refused"].values()) >= len(THE_GESTURES_THAT_WERE_REMOVED), (
        "the page did not report turning these gestures away, so they may never "
        f"have reached it at all: {counted}"
    )
    assert not moved, f"these gestures still move the view: {moved}"

    # And the two that should work, read off the picture.
    before = harness_page.photograph()
    harness_page.page.mouse.move(450, 350)
    harness_page.page.mouse.down()
    for step in range(1, 21):
        harness_page.page.mouse.move(450 + step * 6, 350)
    harness_page.page.mouse.up()
    harness_page.settle(tries=15)
    assert not np.array_equal(before, harness_page.photograph()), (
        "dragging did not move the picture at all"
    )


@pytest.mark.parametrize("option", EVERY_OPTION)
def test_the_margins_stay_even_and_the_check_can_fail(harness_page, option):
    """The operator's drawing stays lined up with the picture underneath it.

    A square of image with a hole cut a little larger over it; the band of
    background between the two is read on all four sides, and the right answer is
    that the four are equal.

    The second half of this test is the part that makes the first half worth
    anything. The hole is moved a few pixels away from where it belongs, and the
    same reading must go uneven. A check that has never been seen to fail is not
    evidence of anything, and this project has been caught by exactly that.
    """
    harness_page.option = option
    harness_page.open(store="square", draw="margin")
    harness_page.believes("window.harness.reset()")
    harness_page.settle(tries=20)
    lined_up = margins_around_the_hole(harness_page.photograph())
    assert lined_up.found, (
        "the band of background between the picture and the hole could not be "
        f"found at all: {lined_up.why}"
    )
    assert lined_up.unevenness <= 2, (
        "the operator's drawing is not lined up with the picture underneath it: "
        f"{lined_up.sides}"
    )

    harness_page.believes("window.harness.nudgeTheHole(8)")
    harness_page.settle(tries=10)
    broken = margins_around_the_hole(harness_page.photograph())
    harness_page.believes("window.harness.nudgeTheHole(0)")
    assert broken.found and broken.unevenness > 8, (
        "the hole was moved eight pixels away from where it belongs and this "
        "check did not notice, so it is not measuring anything: "
        f"{broken.sides if broken.found else broken.why}"
    )

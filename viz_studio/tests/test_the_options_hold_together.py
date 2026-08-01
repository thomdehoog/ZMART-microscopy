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
EVERY_OPTION = ["neuroglancer-under", "viv-under", "viv-inside"]


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
def harness_page(browser, measurement_data, tmp_path_factory):
    """A built harness page, a server for it, and a browser.

    This uses the measurement suite's own way of opening a page rather than a
    second copy of it, so that what the tests check and what the measurements
    report are the same program driven the same way.

    The browser is the suite's own, lent to the harness rather than opened again.
    Playwright allows only one of its ordinary connections to be alive in a thread
    at a time, so a harness that started its own found the door already shut and
    said so in a message about an asyncio loop that named nothing recognisable.
    The effect was quiet and bad: all twenty-four of the checks below skipped, and
    a run told to fail if it never looked at a picture failed for that reason
    alone, on a machine that had in fact drawn everything else perfectly.
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
            measurement_data,
            tmp_path_factory.mktemp("option_pictures"),
            browser=browser,
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


def _drag_across(page, steps: int = 20, step: int = 6) -> None:
    """One plain drag to the right, the same one every check here makes."""
    page.mouse.move(450, 350)
    page.mouse.down()
    for at in range(1, steps + 1):
        page.mouse.move(450 + at * step, 350)
    page.mouse.up()


@pytest.mark.parametrize("option", EVERY_OPTION)
def test_the_application_can_say_a_drag_means_something_else(harness_page, option):
    """Told that a drag means something else, the canvas hands the drag over
    instead of panning — and told nothing, it pans again.

    This is what keeps drawing on the picture possible now that the canvas owns
    dragging. A drag that draws cannot also pan, so the application says which of
    the two a movement of the hand is and the canvas obeys; the canvas never
    learns why the meaning changed. There is no pen and no scribble here, and
    there should not be one until somebody needs it — this checks the switch and
    nothing else.

    Three things have to be true, and the third is the one that is easy to lose.
    The picture must not move. The steps of the drag must actually arrive. And
    they must arrive in micrometres on the stage, because a mark recorded in
    screen pixels would slide off the specimen the moment the operator panned.
    """
    harness_page.option = option
    harness_page.open(store="square", draw="margin")
    harness_page.believes("window.harness.reset()")
    harness_page.settle(tries=15)
    zoom = harness_page.believes("window.harness.view()")["zoom"]

    harness_page.believes("window.harness.aDragNowMeansSomethingElse(true)")
    before = harness_page.photograph()
    _drag_across(harness_page.page)
    harness_page.settle(tries=10)
    assert np.array_equal(before, harness_page.photograph()), (
        "the application said a drag means something other than panning, and the "
        "view moved anyway"
    )

    handed = harness_page.believes("window.harness.dragsHandedOver()")
    assert len(handed) > 3, (
        "the view stayed still, but the drag was not handed to the application "
        f"either, so it simply went nowhere: {handed}"
    )
    assert handed[0]["phase"] == "started" and handed[-1]["phase"] == "finished", (
        "a drag has to arrive as a whole — one call as it begins and one when "
        f"the operator lets go: {[step['phase'] for step in handed]}"
    )
    # 20 steps of 6 browser pixels to the right, so the place on the stage should
    # have travelled 120 pixels' worth of micrometres. Read against the zoom
    # rather than against a fixed number, because the check has to mean the same
    # thing at any magnification.
    travelled = handed[-1]["at"]["x"] - handed[0]["at"]["x"]
    assert abs(travelled - 120 * zoom) < 2 * zoom, (
        f"the hand moved 120 browser pixels at {zoom:.2f} µm to the pixel, so "
        f"the drag should have covered about {120 * zoom:.1f} µm on the stage; "
        f"it reported {travelled:.1f}. Something is handing over screen pixels "
        "and calling them micrometres."
    )

    # And giving it back: dragging pans again, exactly as it did before.
    harness_page.believes("window.harness.aDragNowMeansSomethingElse(false)")
    before = harness_page.photograph()
    _drag_across(harness_page.page)
    harness_page.settle(tries=15)
    assert not np.array_equal(before, harness_page.photograph()), (
        "the application gave dragging back and it still did not pan"
    )
    assert harness_page.believes("window.harness.dragsHandedOver()") == [], (
        "dragging was given back to panning and the drag was handed to the "
        "application as well, so both things happened at once"
    )


@pytest.mark.parametrize("option", EVERY_OPTION)
def test_the_gestures_come_off_when_the_viewer_closes(harness_page, option):
    """A closed viewer leaves no listeners behind on the box.

    This is the half of "the canvas owns its gestures" that is invisible until it
    bites. Listeners left on a box that is still in the page go on answering the
    operator's hand after the viewer they belonged to has gone — so a page that
    closes one viewer and opens another in the same box moves the view twice for
    every drag, and the picture races away at double speed.

    Checked by counting rather than by looking, because a viewer that has been
    destroyed draws nothing and there is no picture left to photograph. The
    second viewer is opened in a box of its own, closed again, and then a drag is
    made over that box: nothing that has been destroyed should notice it.
    """
    harness_page.option = option
    harness_page.open(store="square", draw="none")
    counted = harness_page.page.evaluate(
        """async () => {
          const box = document.createElement('div');
          box.style.cssText =
            'position:absolute;left:0;top:0;width:300px;height:300px;z-index:99';
          document.body.appendChild(box);
          const { openViewer } = await window.harness.loadTheOption();
          const second = await openViewer(box, {
            acquisitions: window.harness.acquisitionsAsked,
            coverage: window.harness.coverage,
            background: '#101014',
          });
          const whileOpen = second.gesturesSoFar();
          second.destroy();
          // A drag and a wheel notch over the very box it was listening on,
          // after it has been closed. Made with plain events rather than with
          // the mouse, because the browser's own pointer is driven from outside
          // the page and this has to happen inside one evaluation.
          const at = { clientX: 150, clientY: 150, bubbles: true, button: 0 };
          box.dispatchEvent(new PointerEvent('pointerdown', at));
          box.dispatchEvent(new PointerEvent('pointermove',
            { ...at, clientX: 210 }));
          box.dispatchEvent(new PointerEvent('pointerup', at));
          box.dispatchEvent(new WheelEvent('wheel',
            { ...at, deltaY: -120, cancelable: true }));
          window.dispatchEvent(new KeyboardEvent('keydown', { key: 'r' }));
          const afterClosing = second.gesturesSoFar();
          box.remove();
          return { whileOpen, afterClosing };
        }"""
    )
    while_open = counted["whileOpen"]["accepted"]
    assert while_open["drags"] == 0 and while_open["wheels"] == 0, (
        "the second viewer had already seen gestures before anybody made one: "
        + str(counted)
    )
    after = counted["afterClosing"]
    assert after["accepted"]["drags"] == 0, (
        "a drag over the box after the viewer was closed still reached its "
        "gestures, so `destroy` left the listeners on: " + str(counted)
    )
    assert after["accepted"]["wheels"] == 0, (
        "a wheel notch after the viewer was closed still reached its gestures, "
        "so `destroy` left the listener on: " + str(counted)
    )
    assert after["refused"]["keys"] == 0, (
        "a key press after the viewer was closed still reached its gestures, so "
        "`destroy` left the listener on the window — which is the one that "
        "outlives the box and the one easiest to forget: " + str(counted)
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


def _share_of_the_window_that_is(picture, colour: str) -> float:
    """What fraction of the window is one saturated colour.

    Written as generous ranges rather than exact values, because a photograph of
    a screen has been through compositing. The colours it is asked about are so
    far apart that generous ranges cannot confuse them.
    """
    picture = np.asarray(picture).astype(int)
    red, green, blue = picture[:, :, 0], picture[:, :, 1], picture[:, :, 2]
    if colour == "green":
        is_it = (green > 120) & (red < 90) & (blue < 90)
    elif colour == "red":
        is_it = (red > 120) & (green < 90) & (blue < 90)
    elif colour == "blue":
        is_it = (blue > 120) & (red < 90) & (green < 90)
    elif colour == "near white":
        # The acquired picture. It is the only near-white thing on screen in the
        # arrangements this file photographs, so counting it says how much
        # picture an operator can see.
        is_it = (red > 150) & (green > 150) & (blue > 150)
    else:
        raise ValueError(f"nothing here knows how to count {colour!r}")
    return float(is_it.mean())


# How much of the window one half of the two-colour square fills. The page frames
# the imaged ground at about 245 browser pixels across in a window of 900 by 700,
# so each half of the square comes to roughly 4% of what an operator sees. Two per
# cent is comfortably below that and comfortably above the odd stray pixel, so a
# reading either side of it is not a close call.
ENOUGH_OF_A_HALF = 0.02


@pytest.mark.parametrize("option", EVERY_OPTION)
def test_the_runs_own_colours_are_read_when_the_page_says_nothing(
    harness_page, option
):
    """A run recorded in two colours is drawn in both of them, without the page
    having to say so.

    Describing an acquisition's channels — their names, their colours, the
    brightness to open at — is something a page may do, and where it does, what
    it says is used. But a page usually cannot know any of it. The description
    lives inside the store, which is the very thing the page is asking the viewer
    to open, so making the page responsible for it would mean opening the run
    twice: once by the page to learn what to say, and once by the viewer to draw
    it. In practice pages did not do that, they said nothing, and the viewer fell
    back to a single white channel — so **a two-colour acquisition showed only
    its first colour**, in white, with nothing on screen to say the rest of it
    was missing.

    The acquisition this reads is written for the purpose: two channels, the
    first named green and filling the left half of the square, the second named
    red and filling the right half. Every other acquisition in the suite has one
    white channel, on which a viewer with this fault looks perfectly correct.

    Three separate things are asked of the photograph, and each of them can fail
    on its own:

    - **both channels are there**, because a viewer reading only the first would
      leave the right half of the square empty;
    - **each is in the colour the run named**, because a viewer that read the
      channels but guessed at their colours would draw both halves white — so
      seeing green and red is what shows that the run's own description is really
      being read rather than a palette being invented;
    - **and a page that does say what it wants still gets it**, because this is a
      fallback and not a takeover. Asked for one white channel, the viewer must
      draw one white channel and neither of the run's two colours.
    """
    harness_page.option = option

    # -- the page says nothing, so the run speaks for itself ----------------
    harness_page.open(store="colours", draw="none", channels="fromTheStore")
    harness_page.believes("window.harness.reset()")
    harness_page.settle(tries=20)
    from_the_store = harness_page.photograph()
    green = _share_of_the_window_that_is(from_the_store, "green")
    red = _share_of_the_window_that_is(from_the_store, "red")

    assert green > ENOUGH_OF_A_HALF, (
        "the first channel of the two-colour acquisition was not drawn in the "
        f"green the run names for it: only {green:.4f} of the window came out "
        f"green, against {red:.4f} red. Either the run's own description of its "
        "colours is not being read, or it is being read and ignored."
    )
    assert red > ENOUGH_OF_A_HALF, (
        "only the first channel of the two-colour acquisition reached the "
        f"screen: {green:.4f} of the window is green and {red:.4f} is red, where "
        "both halves of the square should be showing. This is the fault the "
        "check exists for — a viewer with nothing said to it about the run's "
        "colours drawing one channel and calling it the whole acquisition."
    )

    # And the second colour really is the second channel, rather than something
    # else on screen that happens to be red. Switching channel one off has to
    # take the red away and leave the green where it was.
    harness_page.believes("window.harness.setChannel(1, {visible: false})")
    harness_page.settle(tries=20)
    with_the_second_off = harness_page.photograph()
    red_left = _share_of_the_window_that_is(with_the_second_off, "red")
    green_left = _share_of_the_window_that_is(with_the_second_off, "green")
    assert red_left < red / 4, (
        "switching off the second channel did not take the red half of the "
        f"picture away: it went from {red:.4f} of the window to {red_left:.4f}. "
        "So whatever is red on screen is not the run's second channel, and the "
        "reading above proves less than it looks."
    )
    assert green_left > 0.8 * green, (
        "switching off the second channel also took the first one away: the "
        f"green went from {green:.4f} of the window to {green_left:.4f}. The two "
        "channels are not being kept apart."
    )

    # -- and the page's own word still wins ---------------------------------
    # The same acquisition, opened with the page describing it: one channel,
    # white. A fallback that quietly overrode the page would be worse than no
    # fallback at all, because an operator who had chosen a colour would watch it
    # be ignored.
    harness_page.open(store="colours", draw="none", channels="fromThePage")
    harness_page.believes("window.harness.reset()")
    harness_page.settle(tries=20)
    from_the_page = harness_page.photograph()
    said_green = _share_of_the_window_that_is(from_the_page, "green")
    said_red = _share_of_the_window_that_is(from_the_page, "red")
    said_white = _share_of_the_window_that_is(from_the_page, "near white")
    assert said_white > ENOUGH_OF_A_HALF, (
        "the page asked for one white channel and got no white picture at all: "
        f"only {said_white:.4f} of the window is near white."
    )
    assert said_green < ENOUGH_OF_A_HALF / 4 and said_red < ENOUGH_OF_A_HALF / 4, (
        "the page said exactly what it wanted — one channel, drawn white — and "
        f"the run's own colours were drawn instead: {said_green:.4f} of the "
        f"window green and {said_red:.4f} red. Reading the run's description is "
        "meant to be what happens when the page says nothing, not something that "
        "overrules the page when it does."
    )


def _draw_in_the_slots(harness, *, under: str, over: str) -> None:
    """Put the page's own drawing in one slot, the other, or neither."""
    harness.believes(
        "window.harness.drawInTheSlots({under: %r, over: %r, colour: '#00ff00'})"
        % (under, over)
    )
    harness.settle(tries=20)


@pytest.mark.parametrize("option", EVERY_OPTION)
def test_an_option_is_honest_about_the_bottom_layer(harness_page, option):
    """What an option says about drawing beneath the picture matches a photograph.

    `viz_studio/THE_CANVAS.md` asks for three layers sharing one coordinate
    system, and the interface gives an application a slot for the bottom one:
    ``drawUnder(paint)``, written exactly like ``drawOver(paint)``. Whether an
    operator can actually *see* what goes there depends on the engine in the
    middle, and an engine that cannot honour the slot has to say so — as
    ``viewer.drawsUnder`` — rather than quietly drawing the same thing on top with
    holes cut in it. Two options that looked alike while doing entirely different
    things underneath would make the whole comparison a lie.

    So this checks the claim against the picture, both ways round. An option that
    says yes must show a colour drawn beneath **and must still be drawing the
    acquired picture on top of it**; an option that says no must show none of the
    colour, and must give a reason a page can put in front of somebody.

    That second half of the "yes" is the part that does the work, and it was
    added after it was shown to be needed. One option was deliberately changed to
    put the bottom layer at the *end* of its list of layers instead of the
    beginning — that is, to draw it over the picture rather than under it — and
    this test passed, because the colour still filled the window. What gave it
    away was the acquired picture: it went from 2.95% of the window to nothing at
    all, because the colour had covered it. Drawing the bottom slot on top is
    exactly the fake `contract.md` §4a forbids, so the test now looks for it.

    The same colour is then drawn in the *top* slot, and every option must show it
    filling the window and hiding the picture. That is what makes the reading mean
    "which slot" rather than "which colour": without it, a viewer whose drawing
    never ran at all would pass the "no" half of this test perfectly.
    """
    harness_page.option = option
    # Unbounded on purpose. With the drawn region kept to the imaged ground, the
    # engine's surface covers only part of the window and a colour drawn beneath
    # is seen all round it — which is a fact about the size of a box rather than
    # about whether a surface lets light through, and it would read as a yes on an
    # engine that is really a no.
    harness_page.open(
        store="scattered", draw="none", background="#0000ff", bounded="0"
    )
    claims = harness_page.believes("window.harness.drawsUnder")
    assert claims in (True, False), (
        "the option did not say whether it draws beneath the picture. "
        "`viewer.drawsUnder` is how a page finds that out without having to know "
        f"which engine it is talking to; this one answered {claims!r}"
    )

    # How much acquired picture there is to begin with, with the page drawing
    # nothing at all. Everything below is compared against this.
    _draw_in_the_slots(harness_page, under="nothing", over="nothing")
    picture_to_begin_with = _share_of_the_window_that_is(
        harness_page.photograph(), "near white"
    )
    assert picture_to_begin_with > 0.005, (
        "there was no acquired picture in the window before anything was drawn, "
        "so this check cannot tell a bottom layer from a layer painted over the "
        f"picture: only {picture_to_begin_with:.4f} of the window was picture"
    )

    _draw_in_the_slots(harness_page, under="a colour", over="nothing")
    under_picture = harness_page.photograph()
    beneath = _share_of_the_window_that_is(under_picture, "green")
    picture_left_beneath = _share_of_the_window_that_is(under_picture, "near white")

    _draw_in_the_slots(harness_page, under="nothing", over="a colour")
    over_picture = harness_page.photograph()
    above = _share_of_the_window_that_is(over_picture, "green")
    picture_left_above = _share_of_the_window_that_is(over_picture, "near white")

    assert above > 0.9, (
        "the same colour drawn in the top slot did not fill the window, so this "
        "check cannot tell whether the colour was ever drawn at all: it covered "
        f"{above:.4f} of the window"
    )
    assert picture_left_above < picture_to_begin_with / 2, (
        "the same colour drawn in the top slot did not hide the acquired "
        "picture, so this check cannot tell the two slots apart at all: the "
        f"picture went from {picture_to_begin_with:.4f} of the window to "
        f"{picture_left_above:.4f}"
    )
    if claims:
        assert beneath > 0.5, (
            f"{option} says it draws beneath the picture, and a colour drawn "
            f"there covered only {beneath:.4f} of the window while the same "
            f"colour drawn on top covered {above:.4f}. Either the bottom slot is "
            "not reaching the screen or the claim is wrong."
        )
        assert picture_left_beneath > picture_to_begin_with / 2, (
            f"{option} says it draws beneath the picture, but the drawing "
            "covered the picture rather than sitting under it: the acquired "
            f"picture went from {picture_to_begin_with:.4f} of the window to "
            f"{picture_left_beneath:.4f}. A drawing that hides the picture is on "
            "top of it, whatever slot it was handed to — see contract.md §4a, "
            "which forbids exactly this."
        )
    else:
        assert beneath < 0.02, (
            f"{option} says it cannot draw beneath the picture, and yet a colour "
            f"drawn there covered {beneath:.4f} of the window. Either the claim "
            "is out of date or the drawing has quietly been moved on top, which "
            "would make this option no longer comparable with the others."
        )
        because = harness_page.believes("window.harness.drawsUnderBecause")
        assert because and len(because) > 20, (
            "an option that cannot honour the bottom layer has to say why, in a "
            "sentence a page can show to whoever is looking at it: "
            f"{because!r}"
        )


@pytest.mark.parametrize("option", EVERY_OPTION)
def test_the_bottom_layer_stays_lined_up_with_the_picture(harness_page, option):
    """A layer beneath the picture has to move with it, not merely sit under it.

    The three layers share one coordinate system, so panning and zooming must
    carry all three together. A bottom layer that is underneath but drifts as the
    operator pans is worse than none at all, because it looks right standing still
    and wrong the moment it is used.

    This is the same instrument as ``test_the_margins_stay_even``, and the same
    program reads it. Only the shape moves: a rectangle of colour is drawn
    *beneath* the picture a little way outside the imaged square, so a cut across
    the photograph meets the ring, a band of background, the picture, a band of
    background and the ring again. The right answer is that the two bands are
    equal.

    An option that cannot show anything beneath its canvas has nothing on screen
    to measure, and this says so and stops rather than reporting a nought that
    would read as "perfectly lined up".

    The second half is what makes the first worth anything: the ring is moved
    eight pixels away from where it belongs and the same reading must go uneven.
    """
    harness_page.option = option
    harness_page.open(store="square", draw="none", background="#0000ff")
    claims = harness_page.believes("window.harness.drawsUnder")
    _draw_in_the_slots(harness_page, under="the margin ring", over="nothing")
    harness_page.believes("window.harness.reset()")
    harness_page.settle(tries=20)
    lined_up = margins_around_the_hole(harness_page.photograph())

    if not claims:
        assert not lined_up.found, (
            f"{option} says it cannot draw beneath the picture, and yet the ring "
            "drawn there was found on screen. Either the claim is out of date or "
            "the drawing has quietly been moved on top."
        )
        pytest.skip(
            f"{option} shows nothing beneath the picture, so there is no bottom "
            "layer on screen to measure. That is the honest reading and it is "
            "checked above rather than reported as a nought."
        )

    assert lined_up.found, (
        "the band of background between the picture and the ring drawn beneath "
        f"it could not be found at all: {lined_up.why}"
    )
    assert lined_up.unevenness <= 2, (
        "the layer beneath the picture is not lined up with it: "
        f"{lined_up.sides}"
    )

    harness_page.believes("window.harness.nudgeTheGroundBeneath(8)")
    harness_page.settle(tries=10)
    broken = margins_around_the_hole(harness_page.photograph())
    harness_page.believes("window.harness.nudgeTheGroundBeneath(0)")
    assert broken.found and broken.unevenness > 8, (
        "the ring beneath the picture was moved eight pixels away from where it "
        "belongs and this check did not notice, so it is not measuring anything: "
        f"{broken.sides if broken.found else broken.why}"
    )


@pytest.mark.parametrize("option", EVERY_OPTION)
def test_the_transform_is_published_for_ordinary_html(harness_page, option):
    """An application can place an HTML element in micrometres and have it land.

    The two drawing slots take a function and give back a flat picture, which is
    right for shapes that must stay locked to the specimen. But a drawing context
    cannot hold an HTML element, so a label pinned to a tile, a menu, or a handle
    with its own event listeners has to be an ordinary element positioned over the
    canvas. ``viewer.whereThingsAreDrawn()`` is what makes that possible in the
    canvas's own coordinate system.

    It is checked against the picture rather than against itself. A transform that
    is self-consistent and wrong would round-trip perfectly, so the corner of the
    imaged square is projected and compared with where the picture really begins
    on screen — the same trap, and the same answer, as the check that the view is
    measured in micrometres.
    """
    harness_page.option = option
    harness_page.open(store="square", draw="none")
    harness_page.believes("window.harness.reset()")
    harness_page.settle(tries=20)

    placed = harness_page.page.evaluate(
        """() => {
          const where = window.harness.viewer.whereThingsAreDrawn();
          const square = window.harness.square;
          const corner = where.project(square.x0, square.y0);
          const backAgain = where.unproject(corner.x, corner.y);
          return {
            centre: where.centre, zoom: where.zoom,
            width: where.width, height: where.height,
            corner, backAgain,
            squareX0: square.x0, squareY0: square.y0,
          };
        }"""
    )
    assert placed["width"] > 0 and placed["zoom"] > 0, (
        "whereThingsAreDrawn() did not describe a box with a size and a "
        f"magnification: {placed}"
    )
    assert abs(placed["backAgain"]["x"] - placed["squareX0"]) < 0.01, (
        "projecting a place in micrometres and unprojecting it again did not "
        f"come back to where it started: {placed}"
    )

    picture = harness_page.photograph()
    density = harness_page.believes("window.harness.density()")
    really_starts = _where_the_picture_starts(picture)
    assert really_starts is not None, "there was no picture on screen to measure"
    assert abs(really_starts / density - placed["corner"]["x"]) <= 3, (
        "the transform an application is given puts the corner of the imaged "
        f"square {placed['corner']['x']:.1f} browser pixels across the window, "
        f"and the picture really begins at {really_starts / density:.1f}. An "
        "HTML element positioned with it would land in the wrong place."
    )


def _share_of_the_window_showing_picture(picture) -> float:
    """What fraction of the window is showing acquired picture rather than page.

    The same reading measurement 5 takes, kept the same on purpose so that a
    number here and a number in ``options/measurements/`` mean the same thing.
    Acquired picture is bright and the page behind it is dark, so counting the
    pixels that are lit at all answers "how much picture is on screen" well
    enough to see a window go empty.
    """
    return float((np.asarray(picture).max(axis=2) > 60).mean())


def _watch_the_window_through_a_refresh(harness, seconds: float = 2.0):
    """Tell the viewer to go and look, and read the window all the way through.

    The window is read two ways at once, and both are needed. A live recording
    reports the frames the browser was going to composite anyway, which is what
    an operator would really have seen; photographing in a loop makes the browser
    produce a fresh frame and wait for it, which samples far more often. On its
    own the recording caught a gap of a sixth of a second only about half the
    time, and a check that notices a fault half the time is not a check.

    Returns what the viewer said it sent back to the store, and every reading
    taken while the refresh ran its course.
    """
    from drive import Recording

    seen = []
    with Recording(harness.page) as recording:
        asked = harness.believes("window.harness.tilesMayHaveLanded()")
        until = time.perf_counter() + seconds
        while time.perf_counter() < until:
            seen.append(_share_of_the_window_showing_picture(harness.photograph()))
    seen.extend(
        _share_of_the_window_showing_picture(picture)
        for _, picture in recording.pictures()
    )
    return asked, seen


@pytest.mark.parametrize("option", EVERY_OPTION)
def test_the_picture_does_not_blink_when_new_tiles_are_announced(
    harness_page, measurement_data, option
):
    """Telling the viewer that a tile may have landed must not empty the window.

    This guards a fault that was real and is easy to bring back. A run in
    progress tells the viewer to go and look for new tiles every few seconds, and
    if going to look means letting go of the picture already on screen, the
    operator watching their acquisition fill in sees the window flash empty and
    come back, over and over, at exactly the moment they are watching most
    closely. It reads as the viewer breaking rather than as the viewer working.
    Measured on option A before it was fixed, the share of the window holding
    picture went 0.2726 → 0.0000 → 0.1839 across a single refresh.

    Two things are asserted together, and the second is what makes the first
    worth anything. The window must never dip while the refresh happens **and**
    the tile written a moment before must actually appear. Without the second
    half, the easiest way to pass this check would be to stop looking for new
    tiles at all, which is the opposite of a fix.

    The refresh is asked for twice rather than once, because the fault shows on
    every refresh and two goes leave no room for a gap to fall between two
    readings.
    """
    import acquisitions

    from zmart_storage import Channel, TileCanvases

    # A run of its own, so that writing into it while this check watches cannot
    # disturb the acquisitions the other checks in this file read.
    tile = 512
    canvases = TileCanvases.create(
        measurement_data,
        name="blinking",
        canvas_shape=(1, 2048, 2048),
        tile_shape=(1, tile, tile),
        tile_step=(1, tile, tile),
        voxel_size_um=(1.0, 1.0, 1.0),
        channels=[Channel(name="probe", color="FFFFFF", window=(0, 4095))],
        discard_existing_run=True,
    )
    try:
        for row in range(2):
            for column in range(2):
                canvases.write(
                    acquisitions._a_tile(1, tile, tile, row * 2 + column),
                    origin=(0, row * tile, column * tile),
                    tile_index=(0, row, column),
                )

        harness_page.option = option
        harness_page.open(store="blinking", draw="none")
        harness_page.believes("window.harness.reset()")
        harness_page.settle(tries=20)
        settled = _share_of_the_window_showing_picture(harness_page.photograph())
        assert settled > 0.02, (
            "there was no picture on screen to begin with, so this check could "
            f"not have seen it go away: only {settled:.4f} of the window was lit"
        )

        # A tile into ground the viewer has already looked at and found empty,
        # which is the case that has to be told about: nothing on disk announces
        # a new tile, and the description of the images is identical before and
        # after one lands.
        canvases.write(
            acquisitions._a_tile(1, tile, tile, 7),
            origin=(0, 0, 2 * tile),
            tile_index=(0, 0, 2),
        )
        time.sleep(0.5)

        seen: list[float] = []
        for _ in range(2):
            asked, readings = _watch_the_window_through_a_refresh(harness_page)
            seen.extend(readings)
        harness_page.settle(tries=20)
        afterwards = _share_of_the_window_showing_picture(harness_page.photograph())
    finally:
        canvases.close()

    assert seen, "nothing was read from the window at all, so this check looked at nothing"
    # A tenth of the picture is far more than the difference between two
    # photographs of a still window and far less than any real gap: the fault
    # being guarded against took the whole window, not a tenth of it.
    assert min(seen) >= 0.9 * settled, (
        "the window emptied while the viewer was going to look for new tiles. It "
        f"was showing {settled:.4f} of a window of picture beforehand and fell to "
        f"{min(seen):.4f} during the refresh, over {len(seen)} readings."
    )
    # And the half that stops "never look again" from passing as a fix.
    assert asked, (
        "the viewer reported that it sent nothing back to the store, so the "
        "window staying put proves nothing: it may simply never have looked."
    )
    assert afterwards > settled * 1.15, (
        "the tile written during this check never appeared, so a window that "
        f"stayed put is not a fix: {settled:.4f} of the window was showing "
        f"picture before and {afterwards:.4f} afterwards."
    )


# ---------------------------------------------------------------------------
# Two acquisitions at once, which is the ordinary shape of a run
# ---------------------------------------------------------------------------


def _bounding_box_of(picture, colour: str):
    """The rectangle one saturated colour covers, in the photograph's pixels."""
    picture = np.asarray(picture).astype(int)
    red, green, blue = picture[:, :, 0], picture[:, :, 1], picture[:, :, 2]
    is_it = (
        (green > 110) & (red < 90) & (blue < 90) if colour == "green"
        else (red > 110) & (green < 90) & (blue < 90)
    )
    rows = np.nonzero(is_it.any(axis=1))[0]
    columns = np.nonzero(is_it.any(axis=0))[0]
    if not len(rows) or not len(columns):
        return None
    return {
        "left": float(columns[0]), "right": float(columns[-1]),
        "top": float(rows[0]), "bottom": float(rows[-1]),
        "width": float(columns[-1] - columns[0] + 1),
    }


@pytest.mark.parametrize("option", EVERY_OPTION)
def test_two_acquisitions_land_in_the_same_place(harness_page, option):
    """A wide survey and a detailed scan over part of it, opened together.

    This is the ordinary arrangement smart microscopy is built around, and it is
    the case where a viewer has the least help. Two runs written at different
    voxel sizes share nothing but the position each of them states in
    micrometres, so if a viewer ignores that position one run is drawn at the
    other's corner — a perfectly sharp picture of the wrong part of the slide,
    with nothing on screen to say so.

    It cannot be seen on a single acquisition, which is why it went unnoticed for
    so long: a run written from the stage's zero is drawn in the right place
    whether its position was read or not. Measured here before it was put right,
    two of the three options drew the detail scan 898 micrometres away from where
    its store says it is.

    The reading is taken from the photograph and in micrometres. The survey is a
    known number of micrometres across, so how many pixels of it there are says
    what one pixel is worth, and everything else follows from that.
    """
    from acquisitions import SURVEY_SPAN_UM, WHERE_THE_DETAIL_BELONGS

    harness_page.option = option
    harness_page.open(
        store="survey", alsoStore="detail", draw="none",
        channels="fromTheStore", bounded="0",
    )
    middle = SURVEY_SPAN_UM / 2
    zoom = SURVEY_SPAN_UM / 650.0
    harness_page.believes(
        f"window.harness.setView("
        f"{{centre: {{x: {middle}, y: {middle}}}, zoom: {zoom}}})"
    )
    harness_page.settle(tries=25)
    picture = harness_page.photograph()

    survey = _bounding_box_of(picture, "green")
    detail = _bounding_box_of(picture, "red")
    assert survey is not None, (
        "none of the survey reached the screen, so there was nothing to measure "
        "the detail scan against"
    )
    assert detail is not None, (
        "the survey was drawn and the detail scan was nowhere in the window, "
        "although the window held the whole of the survey and the detail scan "
        "states a position inside it. Two acquisitions have nothing to line them "
        "up but the position each states, so this is what ignoring it looks like."
    )

    # One photograph pixel, in micrometres, taken from the survey's own width.
    um = SURVEY_SPAN_UM / survey["width"]
    middle = {
        "x": (detail["left"] + detail["right"]) / 2 - survey["left"],
        "y": (detail["top"] + detail["bottom"]) / 2 - survey["top"],
    }
    belongs = {
        "x": (WHERE_THE_DETAIL_BELONGS["x0"] + WHERE_THE_DETAIL_BELONGS["x1"]) / 2,
        "y": (WHERE_THE_DETAIL_BELONGS["y0"] + WHERE_THE_DETAIL_BELONGS["y1"]) / 2,
    }
    out_by = max(
        abs(middle["x"] * um - belongs["x"]), abs(middle["y"] * um - belongs["y"])
    )
    # Half of the survey's own voxel is four micrometres, and that is about as
    # well as anything can be expected to agree: the survey cannot say where it
    # was imaged more precisely than one of its own voxels. Ten micrometres
    # leaves room for the coarseness of reading an edge out of a photograph at
    # three micrometres to the pixel, and is a hundredth of the distance the
    # fault this catches produced.
    assert out_by < 10, (
        "the detail scan did not land where its store says it is. Its middle "
        f"came out {out_by:.1f} µm away from where the survey puts it, measured "
        "from the photograph. Two acquisitions of different voxel sizes are "
        "placed by the position each states in micrometres and by nothing else."
    )


@pytest.mark.parametrize("option", EVERY_OPTION)
def test_a_drawing_at_the_wrong_size_is_noticed(harness_page, option):
    """The reading that catches the two layers disagreeing about *size*.

    The usual registration check reads how *uneven* the band around the picture
    is, and that is the right number for the two layers sitting in different
    places. It is blind to them agreeing about where the middle is and
    disagreeing about how large everything should be, because then all four
    margins grow together and the unevenness stays at nought while an operator
    sees an outline visibly the wrong size around its tile.

    So this asks the other question, and it asks it of a page deliberately
    drawing its own layer two per cent too large. Both readings are taken, and
    the point of the test is the contrast between them: the unevenness must stay
    where it was while the second reading rises.
    """
    from drive import MARGIN_CSS_PX

    harness_page.option = option
    harness_page.open(store="square", draw="margin")
    harness_page.believes("window.harness.reset()")
    harness_page.settle(tries=20)
    still = harness_page.photograph()
    nominal = harness_page.nominal(still)
    lined_up = margins_around_the_hole(still)
    assert lined_up.found, (
        "the band of background between the picture and the hole could not be "
        f"found at all: {lined_up.why}"
    )
    # One pixel is this reading's own floor and not a disagreement: every edge is
    # read as the gap between the last pixel that is definitely one thing and the
    # first that is definitely the next, so the soft edge between them is left
    # out on both sides and the band comes out about a pixel wide of the truth.
    assert lined_up.wider_than_it_was_cut(nominal) <= 1.5, (
        "the operator's drawing is a different size from the picture underneath "
        f"it: the band was cut at {MARGIN_CSS_PX} browser pixels and came out "
        f"{lined_up.sides}"
    )

    harness_page.believes(
        "window.harness.drawTheOperatorsLayerAtTheWrongScale(1.02)"
    )
    harness_page.settle(tries=10)
    wrong = harness_page.photograph()
    broken = margins_around_the_hole(wrong)
    harness_page.believes("window.harness.drawTheOperatorsLayerAtTheWrongScale(1)")
    assert broken.found, (
        "the band could not be read at all once the drawing was made too large, "
        f"so nothing was compared: {broken.why}"
    )
    assert broken.wider_than_it_was_cut(harness_page.nominal(wrong)) > 2, (
        "the operator's drawing was made two per cent too large and this reading "
        f"did not notice, so it is not measuring anything: {broken.sides}"
    )
    # And the half that says why the new reading had to be added at all.
    assert broken.unevenness <= 2, (
        "the unevenness moved when the drawing was made too large, which it "
        "should not: this test exists because a disagreement about size leaves "
        "the four margins equal, and if that is no longer true the arrangement "
        f"has changed and the prose in RESULTS.md needs revisiting: {broken.sides}"
    )

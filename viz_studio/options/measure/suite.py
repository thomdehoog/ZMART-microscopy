"""The measurements every option has to pass, written to run against any of them
by name.

`viz_studio/OPTIONS.md` lists them and says why each one is there. Nothing below
mentions an engine, and nothing below asks the page which option it is driving:
each measurement opens the harness with an option's name, makes a gesture or
writes a tile, and reads the answer out of a photograph.

Two habits run through the whole file and are worth stating once.

**Every number comes from the picture, with one exception that is labelled as
one.** Where a measurement asks the page something — how many gestures it
refused, what the option says it did to go back to the store — that is the means
to make something happen or to tell two identical-looking outcomes apart, and not
the answer to the question being asked. The exception is measurement 5's count of
what the option sent back to the store, which does reach the results table. It is
the option's own account of its own work, it counts a different thing in each of
the three columns, and it is kept only because it tells "the option was asked and
did nothing" apart from "the option was never asked". Its reading in the table
says so, and the comparable number for the same event — how many pieces of image
were really re-fetched — is counted by the server rather than by the page.

**Every check is shown failing.** A check that has never been seen to fail is not
evidence of anything, and this project has been caught out repeatedly by green
checks over broken things. So the registration measurement deliberately puts the
hole in the wrong place, the gesture measurement counts what it refused as well
as what it accepted, the measurement of showing-through hides the surfaces it is
asking about, and the sparseness measurement photographs the same window again
with the picture switched off. The red evidence is reported beside the green.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402

import beneath  # noqa: E402
import showing_through  # noqa: E402
from drive import GESTURES, MARGIN_CSS_PX, Recording, pan_steadily  # noqa: E402
from margins import (  # noqa: E402
    margins_around_the_hole,
    margins_at_every_cut,
    only_the_whole_ones,
    worst_drift,
)


# ---------------------------------------------------------------------------
# 0. Can anything behind the engine's canvas be seen at all?
# ---------------------------------------------------------------------------


def can_a_surface_underneath_be_seen(harness) -> dict:
    """Asked first, because which way up a sandwich must be built depends on it.

    This is about surfaces in the page — one canvas behind another — and not
    about layers inside the engine, which `viz_studio/LAYER_STACK.md` measures
    separately — on the branch `claude/layer-stack-probe` at the time of writing —
    and where a lower layer does show through the one above it.
    """
    found = showing_through.measure(harness)
    found["and the check can fail"] = showing_through.check_it_can_fail(harness)
    return found


# ---------------------------------------------------------------------------
# 0b. Is the bottom layer of the canvas genuinely beneath the picture?
# ---------------------------------------------------------------------------


def is_the_bottom_layer_beneath_the_picture(harness) -> dict:
    """The question above, asked of the slot an application actually uses.

    Measurement 0 asks whether a colour painted on the *box* shows through the
    engine's canvas, which is a fact about the engine. This one asks whether the
    bottom slot of the interface — `drawUnder(paint)`, the thing an application
    writes against — really puts an application's own drawing beneath the
    picture. They are the same physics and they can still come apart, because an
    option could implement the slot and then not honour it. `beneath.py` says how
    it is measured and how it is shown able to give the other answer.
    """
    return beneath.measure(harness)


# ---------------------------------------------------------------------------
# 1. Registration
# ---------------------------------------------------------------------------


def _margins_through_a_gesture(harness, gesture, name: str) -> dict:
    """Make one gesture and read the margins out of every frame it produced."""
    harness.believes("window.harness.reset()")
    harness.settle(tries=20)
    readings = []
    with Recording(harness.page) as recording:
        gesture(harness.page)
        time.sleep(0.4)
    worst_picture, worst_seen, worst_slant = None, -1.0, 0.0
    nominal = None
    for _, picture in recording.pictures():
        if nominal is None:
            nominal = harness.nominal(picture)
        along, slant = margins_at_every_cut(picture)
        readings.extend(along)
        if slant is not None:
            worst_slant = max(worst_slant, slant)
        for reading in along:
            if reading.found and reading.unevenness > worst_seen:
                worst_seen, worst_picture = reading.unevenness, picture
    summary = worst_drift(readings, nominal or MARGIN_CSS_PX)
    summary["band was cut at, in these pixels"] = round(nominal or 0.0, 1)
    summary["worst slant across three cuts"] = round(worst_slant, 1)
    summary["frames"] = len(recording.frames)
    if worst_picture is not None:
        summary["photograph"] = harness.save_frame(worst_picture, name)
    return summary


def registration(harness) -> dict:
    """Do the two layers stay lined up while the view is moved about?

    A square of real acquired image with a hole cut slightly larger over it. The
    four margins are read out of every frame of a live recording, and the answer
    is the worst unevenness seen within any *single* photograph — which is the
    number that matters, because it cannot be explained away by the two layers
    having been photographed a moment apart.
    """
    harness.open(store="square", draw="margin")
    still = harness.photograph()
    at_rest = margins_around_the_hole(still)
    found = {
        "at rest": at_rest.sides if at_rest.found else {"why": at_rest.why},
        "at rest, unevenness": at_rest.unevenness,
        "band was cut at, in a still photograph's pixels": round(
            harness.nominal(still), 1
        ),
        "photograph at rest": harness.save_frame(still, "registration-at-rest"),
    }
    for name, gesture in GESTURES.items():
        found[name] = _margins_through_a_gesture(
            harness, gesture, f"registration-{name.replace(' ', '-')}-worst"
        )
    found["and the check can fail"] = _registration_can_fail(harness)
    return found


def _registration_can_fail(harness) -> dict:
    """Put the hole in the wrong place on purpose and watch the check notice.

    Nothing else changes: the same page, the same picture, the same reading. So
    whatever the margins then report is the check noticing a disagreement that
    really is there, which is the only way to know it would notice a real one.
    """
    broken = {}
    for pixels in (0, 2, 8):
        harness.believes(f"window.harness.nudgeTheHole({pixels})")
        harness.settle(tries=10)
        picture = harness.photograph()
        reading = margins_around_the_hole(picture)
        broken[f"the hole moved {pixels} browser pixels"] = {
            "unevenness": reading.unevenness if reading.found else None,
            "noticed": bool(reading.found and reading.unevenness > 2),
            "photograph": harness.save_frame(
                picture, f"registration-can-fail-nudged-{pixels}"
            ),
        }
    harness.believes("window.harness.nudgeTheHole(0)")
    return broken


# ---------------------------------------------------------------------------
# 1b. Registration of the bottom layer
# ---------------------------------------------------------------------------

# What is said instead of a number when there is no bottom layer on screen to
# measure. Said in words rather than reported as nought, because nought would
# read as "perfectly lined up" and the truth is "there was nothing there". Kept
# to two words so that the results table stays readable; the full explanation
# goes in the reading's own "note", where there is room for it.
NOT_APPLICABLE = "not applicable"


def registration_of_the_bottom_layer(harness) -> dict:
    """Does the layer *beneath* the picture stay locked to it while the view moves?

    A bottom layer that sits underneath but drifts as the operator pans is worse
    than no bottom layer at all, because it looks right standing still and wrong
    the moment it is used. Being beneath the picture and staying locked to it are
    two separate promises, and this measures the second.

    It is the same instrument as measurement 1 and the same program reads it,
    `viz_studio/tests/margins.py`, with nothing changed. Only the shape moves: a
    rectangle of colour is drawn *beneath* the picture a little way outside the
    imaged square, so a cut across the photograph meets the ring, a band of
    background, the picture, a band of background and the ring again — exactly the
    four things measurement 1 reads, in exactly that order. The right answer is
    again "unchanged": the two bands equal, and equal in every frame of a live
    recording of a real gesture.

    An option whose engine cannot show anything beneath its canvas shows none of
    the ring, and this says so in words rather than reporting a number. That is
    the honest reading — there was nothing on screen to measure, which is not the
    same as a measurement of nought.
    """
    # The engine's background is set to the same saturated blue measurement 1
    # uses, because the band between the picture and the ring has to be a colour
    # the reading can name. In a finished viewer it matches the page exactly and
    # the seam cannot be seen; it differs here so that it can be measured.
    harness.open(store="square", draw="none", background="#0000ff")
    harness.believes(
        "window.harness.drawInTheSlots("
        "{under: 'the margin ring', over: 'nothing'})"
    )
    harness.believes("window.harness.reset()")
    harness.settle(tries=20)
    still = harness.photograph()
    at_rest = margins_around_the_hole(still)
    found = {
        "what the option says of itself": harness.believes(
            "window.harness.drawsUnder"
        ),
        "band was cut at, in a still photograph's pixels": round(
            harness.nominal(still), 1
        ),
        "photograph at rest": harness.save_frame(
            still, "bottom-registration-at-rest"
        ),
    }
    if not at_rest.found:
        found["at rest"] = {"why": at_rest.why}
        found["at rest, unevenness"] = NOT_APPLICABLE
        for name in GESTURES:
            found[name] = {"unevenness": NOT_APPLICABLE}
        found["and the check can fail"] = {
            "the ring moved 8 browser pixels": {"unevenness": NOT_APPLICABLE}
        }
        found["note"] = (
            "there was no bottom layer on screen to measure. The page drew one "
            "and the option painted it, on a surface genuinely beneath the "
            "picture; the engine's own canvas covers it completely. See "
            "measurement 0b, which asks that question directly, and "
            "viewer.drawsUnder, which is how a page finds it out without having "
            "to know which engine it is talking to."
        )
        return found

    found["at rest"] = at_rest.sides
    found["at rest, unevenness"] = at_rest.unevenness
    for name, gesture in GESTURES.items():
        found[name] = _margins_through_a_gesture(
            harness, gesture, f"bottom-registration-{name.replace(' ', '-')}-worst"
        )
    found["and the check can fail"] = _bottom_registration_can_fail(harness)
    return found


def _bottom_registration_can_fail(harness) -> dict:
    """Put the ring beneath the picture in the wrong place, and watch it show.

    Exactly the breakage measurement 1 uses, applied to the other slot. Nothing
    else on the page changes, so whatever the reading then reports is it noticing
    a disagreement that really is there — which is the only way to know it would
    notice a real one.
    """
    broken = {}
    for pixels in (0, 2, 8):
        harness.believes(f"window.harness.nudgeTheGroundBeneath({pixels})")
        harness.settle(tries=10)
        picture = harness.photograph()
        reading = margins_around_the_hole(picture)
        broken[f"the ring moved {pixels} browser pixels"] = {
            "unevenness": reading.unevenness if reading.found else None,
            "noticed": bool(reading.found and reading.unevenness > 2),
            "photograph": harness.save_frame(
                picture, f"bottom-registration-can-fail-nudged-{pixels}"
            ),
        }
    harness.believes("window.harness.nudgeTheGroundBeneath(0)")
    return broken


# ---------------------------------------------------------------------------
# 2. Handedness
# ---------------------------------------------------------------------------


def handedness(harness) -> dict:
    """Is the specimen drawn the way round it really is?

    An acquisition written dim at one edge and bright at the other, with the
    bright edge at the high end of the image's own width axis. Measured across
    the picture, the brightness must run *uphill* to the right.

    Do not be tempted to settle this by dragging the picture and watching which
    way it goes. That is the obvious check and it cannot find this fault: an
    engine pans using the same axis mapping it draws with, so the picture follows
    the hand pixel for pixel whichever way round it is drawn — measured at a
    slope of +1.0 both before a mirror was fixed and after. Only something
    asymmetric inside the specimen can say which way round the picture is.

    The dragging check is still made, because a view that slides against the hand
    is unusable. It is simply a different question, and it is reported as one.
    """
    harness.open(store="lopsided", draw="none")
    picture = harness.photograph()
    height, width = picture.shape[0], picture.shape[1]
    # Read along the middle of the picture, over the part of the row that is
    # actually specimen rather than background.
    row = picture[height // 2, :, :].mean(axis=1)
    lit = np.nonzero(row > 40)[0]
    found = {"photograph": harness.save_frame(picture, "handedness")}
    if len(lit) < 50:
        found["why"] = "there was no picture along the middle of the window to read"
        return found
    first, last = int(lit[0]), int(lit[-1])
    inside = row[first + 5:last - 5]
    steps = np.arange(len(inside))
    slope = float(np.polyfit(steps, inside, 1)[0]) * 100
    found["brightness across the picture, grey levels per hundred pixels"] = round(
        slope, 1
    )
    found["the bright edge is drawn on the right"] = slope > 5
    found["and dragging carries the picture with the hand"] = _dragging_follows(harness)
    return found


def _dragging_follows(harness) -> dict:
    """Which way the picture travels when the hand does. A separate question."""
    before = harness.photograph()
    pan_steadily(harness.page, steps=20, step=6)
    harness.settle(tries=15)
    after = harness.photograph()

    def edge(picture):
        row = picture[picture.shape[0] // 2, :, :].mean(axis=1)
        lit = np.nonzero(row > 40)[0]
        return float(lit[0]) if len(lit) else None

    was, now = edge(before), edge(after)
    if was is None or now is None:
        return {"why": "the edge of the picture could not be found"}
    density = harness.believes("window.harness.density()")
    return {
        "the hand moved (browser pixels)": 120,
        "the picture moved (browser pixels)": round((now - was) / density, 1),
        "slope": round(((now - was) / density) / 120, 2),
    }


# ---------------------------------------------------------------------------
# 3. Two gestures and no more
# ---------------------------------------------------------------------------

# The gestures that used to move the view and have been taken away. Each is made
# in earnest and the picture compared with the one before it.
THE_GESTURES_THAT_WERE_REMOVED = {
    "shift and drag (used to rotate)": lambda page: (
        page.keyboard.down("Shift"),
        page.mouse.move(450, 350),
        page.mouse.down(),
        page.mouse.move(560, 400),
        page.mouse.up(),
        page.keyboard.up("Shift"),
    ),
    "the r key (used to rotate)": lambda page: page.keyboard.press("r"),
    "the e key (used to rotate)": lambda page: page.keyboard.press("e"),
    "shift and the arrow keys (used to tilt)": lambda page: [
        page.keyboard.press(f"Shift+{key}")
        for key in ("ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown")
    ],
    "ctrl and the wheel (used to zoom)": lambda page: [
        (page.keyboard.down("Control"), page.mouse.wheel(0, -120),
         page.keyboard.up("Control"))
        for _ in range(3)
    ],
    "the right button (used to recentre)": lambda page: page.mouse.click(
        400, 300, button="right"
    ),
    "the arrow keys (used to step sideways)": lambda page: [
        page.keyboard.press(key)
        for key in ("ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown")
    ],
    "the comma and full stop keys (used to step through the stack)": lambda page: [
        page.keyboard.press(key) for key in (",", ".")
    ],
    "the bracket keys (used to step through time)": lambda page: [
        page.keyboard.press(key) for key in ("[", "]")
    ],
}


def two_gestures_and_no_more(harness) -> dict:
    """Drag pans, the plain wheel zooms, and everything else leaves the picture alone.

    An unbound gesture and a gesture nobody tried look exactly alike on screen,
    so this counts what the page turned away as well as what it accepted. Without
    that, a page that had quietly stopped listening at all would pass.
    """
    harness.open(store="square", draw="margin")
    found = {}

    # First, that the two allowed gestures do what they should — read off the
    # picture rather than out of the numbers that were set.
    harness.believes("window.harness.reset()")
    harness.settle(tries=15)
    before = harness.photograph()
    pan_steadily(harness.page, steps=20, step=6)
    harness.settle(tries=15)
    after = harness.photograph()
    density = harness.believes("window.harness.density()")

    def left_edge(picture):
        reading = margins_around_the_hole(picture)
        return reading.across.image_starts if reading.across else None

    moved = None
    if left_edge(before) is not None and left_edge(after) is not None:
        moved = round((left_edge(after) - left_edge(before)) / density, 1)
    found["dragging pans"] = {
        "the hand moved (browser pixels)": 120,
        "the edge of the picture moved (browser pixels)": moved,
        "the margins stayed even": margins_around_the_hole(after).unevenness,
    }

    harness.believes("window.harness.reset()")
    harness.settle(tries=15)
    before = harness.photograph()
    across_before = _how_wide_the_picture_is(before)
    for _ in range(4):
        harness.page.mouse.wheel(0, -120)
    harness.settle(tries=20)
    after = harness.photograph()
    found["the plain wheel zooms"] = {
        "the picture went from (photograph pixels)": across_before,
        "to": _how_wide_the_picture_is(after),
        "the margins stayed even": margins_around_the_hole(after).unevenness,
    }

    # And now the ones that used to navigate.
    harness.believes("window.harness.reset()")
    harness.settle(tries=15)
    unchanged = {}
    for name, make in THE_GESTURES_THAT_WERE_REMOVED.items():
        harness.page.mouse.move(450, 350)
        before = harness.photograph()
        make(harness.page)
        time.sleep(0.5)
        harness.settle(tries=8)
        after = harness.photograph()
        unchanged[name] = (
            "unchanged, byte for byte"
            if np.array_equal(before, after)
            else "THE VIEW MOVED"
        )
    found["the gestures that were removed"] = unchanged
    # The proof that they were made at all.
    found["what the page counted"] = harness.believes("window.harness.gesturesSoFar()")
    return found


def _how_wide_the_picture_is(picture) -> int | None:
    """How many pixels across the acquired picture is, along the middle row."""
    picture = np.asarray(picture)
    row = picture[picture.shape[0] // 2, :, :3].astype(int)
    bright = (row[:, 0] > 150) & (row[:, 1] > 150) & (row[:, 2] > 150)
    lit = np.nonzero(bright)[0]
    return int(lit[-1] - lit[0]) if len(lit) else None


# ---------------------------------------------------------------------------
# 4. Sparseness
# ---------------------------------------------------------------------------


def sparseness(harness) -> dict:
    """Does the operator's drawing show through where nothing was imaged?

    An acquisition imaged in a few places far apart, with the operator's real
    drawing — a carrier outline and tile rectangles — over it. Two things have to
    be true at once, and they are opposite failures: picture must appear where
    picture was written, and the operator's plan must be plainly visible
    everywhere else.

    **The same window is photographed twice**, once with the acquisition on
    screen and once with every channel switched off, and the answer is the
    difference between the two. That is not fussiness, and it was not always done
    this way. The counting below finds near-white pixels, and the operator's own
    carrier outline is a pale line on a dark sheet — pale enough to be counted as
    picture. Measured, it filled 0.41% of the window on its own, which is more
    than the 0.2% the old reading asked for. So the check passed on a page with
    the holes deliberately not cut in it and no acquired picture on screen
    anywhere. Photographing the same page with the picture switched off says
    exactly how much of the near-white is the drawing's, and subtracting it
    leaves the share that is really acquired picture.
    """
    harness.open(store="scattered", draw="carrier")
    # Backed out a little so that the whole carrier is in the window and the gaps
    # between the imaged places can be seen.
    view = harness.believes("window.harness.view()")
    harness.believes(f"window.harness.setView({{zoom: {view['zoom'] * 1.6}}})")
    harness.settle(tries=20)
    picture = harness.photograph()
    counted = _what_is_on_screen(picture)
    without = _the_same_window_with_the_picture_switched_off(harness)
    really_picture = round(counted["picture"] - without["picture"], 4)
    coverage = harness.coverage("scattered")
    return {
        "places the run imaged": len(coverage["regions"]),
        "share of the window showing acquired picture": really_picture,
        "share showing the operator's own drawing": counted["drawing"],
        "near-white counted with the picture on screen": counted["picture"],
        "and with every channel switched off": without,
        # A few small patches on a canvas mostly not imaged, seen from far
        # enough out to have the whole carrier in the window: a few per cent is
        # the right answer, and anything at all is the thing being asked about.
        # Nought would mean the picture is not being drawn; most of the window
        # would mean unimaged ground is being painted over the operator's plan,
        # which is the opposite failure and just as bad.
        "the picture shows": really_picture > 0.002,
        "the operator's plan shows through the gaps": counted["drawing"] > 0.5,
        "photograph": harness.save_frame(picture, "sparseness"),
    }


def _the_same_window_with_the_picture_switched_off(harness) -> dict:
    """Photograph the same page again with every channel hidden.

    This is both halves of one job. It says how much of the near-white in the
    photograph above belongs to the operator's own pale outlines rather than to
    the acquisition, which is what makes the reported share honest. And it is the
    red evidence for this measurement: with the picture switched off the share
    has to fall away, and a counting program that could only ever answer "there
    is picture" would be caught here.

    Every channel is switched off through the interface every option implements,
    so nothing about any particular engine is assumed. The channels are switched
    back on afterwards, so that a later measurement never finds a page still
    holding this.
    """
    how_many = len(harness.believes("window.harness.acquisitionsAsked[0].channels"))
    for index in range(how_many):
        harness.believes(
            f"window.harness.setChannel({index}, {{visible: false}})"
        )
    harness.settle(tries=20)
    dark = harness.photograph()
    counted = _what_is_on_screen(dark)
    for index in range(how_many):
        harness.believes(f"window.harness.setChannel({index}, {{visible: true}})")
    harness.settle(tries=20)
    return {
        "what was changed": (
            "every channel was switched off, so nothing of the acquisition was "
            "drawn and only the operator's own drawing was left on screen"
        ),
        "picture": counted["picture"],
        "drawing": counted["drawing"],
        "photograph": harness.save_frame(dark, "sparseness-with-no-picture"),
    }


def _what_is_on_screen(picture) -> dict:
    """Roughly what share of the window is near-white and what share is not.

    The acquired picture is near-white and near-flat; the operator's drawing is
    the dark page colour with tinted rectangles on it. Counting the near-white
    separates the two well enough to answer "is there any of each", which is the
    question — with one caveat that the caller has to handle. The operator's
    carrier outline is a pale line, pale enough to land above the threshold, so
    the near-white share is a little larger than the picture alone. See
    `sparseness`, which photographs the same window with the picture switched off
    and takes the difference.
    """
    picture = np.asarray(picture).astype(int)
    red, green, blue = picture[:, :, 0], picture[:, :, 1], picture[:, :, 2]
    is_picture = (red > 150) & (green > 150) & (blue > 150)
    total = picture.shape[0] * picture.shape[1]
    return {
        "picture": round(float(is_picture.sum() / total), 4),
        "drawing": round(float((~is_picture).sum() / total), 4),
    }


# ---------------------------------------------------------------------------
# 5. New data arriving while somebody is watching
# ---------------------------------------------------------------------------


def new_data_arriving(harness, data_dir: Path) -> dict:
    """The measurement that matters most, in its six parts.

    Watching a run fill in is what this viewer is *for*. A run that has to be
    reopened to show what it just acquired is not a smart-microscopy viewer, it
    is a file browser. So this is not "does a tile eventually appear" — it is six
    separate questions, asked with a run genuinely writing throughout.
    """
    from acquisitions import SPARSE_TILE, _a_tile

    from zmart_storage import Channel, TileCanvases

    span = 2048
    canvases = TileCanvases.create(
        data_dir, name="growing",
        canvas_shape=(1, span, span),
        tile_shape=(1, SPARSE_TILE, SPARSE_TILE),
        tile_step=(1, SPARSE_TILE, SPARSE_TILE),
        voxel_size_um=(1.0, 1.0, 1.0),
        channels=[Channel(name="probe", color="FFFFFF", window=(0, 4095))],
        discard_existing_run=True,
    )
    # A corner imaged, so there is plenty of room the engine will certainly have
    # looked at and found empty.
    for row in range(2):
        for column in range(2):
            canvases.write(
                _a_tile(1, SPARSE_TILE, SPARSE_TILE, row * 2 + column),
                origin=(0, row * SPARSE_TILE, column * SPARSE_TILE),
                tile_index=(0, row, column),
            )
    found = {}
    try:
        harness.open(store="growing", draw="none")
        found.update(_does_it_appear_at_all(harness, canvases, span))
        found.update(_does_the_view_stay_put(harness))
        found.update(_how_soon_after_the_tile_lands(harness, canvases))
        found.update(_does_it_keep_up(harness, canvases))
    finally:
        canvases.close()
    return found


def _lit(picture) -> float:
    """What share of the window is showing acquired picture."""
    picture = np.asarray(picture).astype(int)
    bright = picture.max(axis=2) > 60
    return round(float(bright.mean()), 4)


def _does_it_appear_at_all(harness, canvases, span) -> dict:
    """Parts one, two and three: does it appear, what did it cost, did it survive.

    Nothing on disk announces a new tile — the images are declared at full size
    before any tile exists and their description is identical before and after —
    so something has to tell the viewer to look again. This records exactly what
    was needed, and what the looking cost.
    """
    from acquisitions import SPARSE_TILE, _a_tile

    harness.settle(tries=20)
    before = harness.photograph()
    at_first = _lit(before)

    # Now write into room the viewer has already looked at and found empty.
    for row in range(2, 4):
        for column in range(4):
            canvases.write(
                _a_tile(1, SPARSE_TILE, SPARSE_TILE, row * 4 + column),
                origin=(0, row * SPARSE_TILE, column * SPARSE_TILE),
                tile_index=(0, row, column),
            )
    time.sleep(2.0)
    harness.settle(tries=15)
    without_telling = harness.photograph()
    lit_without_telling = _lit(without_telling)

    # And now the one call the interface offers for it.
    harness.clear_ledger()
    started = time.perf_counter()
    asked = harness.believes("window.harness.tilesMayHaveLanded()")
    time.sleep(2.0)
    harness.settle(tries=20)
    after = harness.photograph()
    cost = harness.read_ledger()

    # Did the picture survive the refresh, or did it blank or go patchwork? Read
    # from a recording rather than from stills, because a blank that lasts two
    # frames is invisible to anything that photographs afterwards.
    settled = _lit(after)
    # Two readings of the same moment, because neither can answer on its own.
    #
    # The recording says *what* the window showed, frame by frame, which is how
    # the two failures are told apart: a blank is a share of nought followed by
    # the settled share, while a patchwork of two generations is a run of values
    # in between. It cannot say how *long* any of it lasted, because this
    # browser's frames are only handed over while the measuring program is
    # inside a call of its own — so a stretch of waiting collects them all at the
    # end with almost the same time on each. That caught this measurement out
    # once, reporting a gap of nought seconds over a window that was blank
    # throughout.
    with Recording(harness.page) as recording:
        harness.believes("window.harness.tilesMayHaveLanded()")
        time.sleep(2.0)
    during = [_lit(picture) for _, picture in recording.pictures()]

    # And the clock comes from photographing in a loop, which does keep time
    # honestly because each photograph is a call and a real moment.
    harness.believes("window.harness.tilesMayHaveLanded()")
    went = time.perf_counter()
    back = None
    while time.perf_counter() - went < 20:
        if _lit(harness.photograph()) >= settled * 0.5:
            back = time.perf_counter()
            break
        time.sleep(0.05)
    dark_for = (back - went) if back else None

    return {
        "does it appear at all": {
            "share of the window showing picture, at first": at_first,
            "after eight more tiles were written, without being told":
                lit_without_telling,
            "and after telling it": _lit(after),
            "what was needed": (
                "viewer.tilesMayHaveLanded({coverage}), which sends the option "
                "back to the store to read what is there now. Nothing less "
                "works: every one of these viewers remembers what it has already "
                "read, including the places it found empty, with no time limit — "
                "so a tile written into ground it has already looked at is not "
                "slow to appear, it is never fetched again at all. How an option "
                "goes back is its own business and the page never knows: two of "
                "them open a fresh reader on the store, and the third tells the "
                "drawing engine's background worker to read its resolution "
                "levels again."
            ),
            "what the option said it sent back to the store": asked,
            "and what that number is not": (
                "this one number is the option's own account of what it did, and "
                "it is the only number in this suite that is. It is here for one "
                "narrow purpose: to tell 'the option was asked and nothing "
                "happened' apart from 'the option was never asked', which look "
                "identical on screen. It must not be read across the columns, "
                "because it counts a different thing in each of them. For the "
                "two Viv options it is how many copies of the image the freshly "
                "opened reader has — three, because the writer makes a pyramid "
                "of three — and it would still be three if the fresh reader were "
                "then thrown away without being used. For neuroglancer it is how "
                "many of the engine's own stores of decoded picture were told to "
                "let go, which is also three here and for an unrelated reason. "
                "The number that can be compared is the one below it, 'pieces of "
                "image re-fetched', which the server counted rather than the "
                "page. Measured with one option's refresh deliberately made to "
                "do nothing at all, this went on reporting three while the "
                "pieces re-fetched fell to nought and the window never changed."
            ),
            "it appeared": _lit(after) > lit_without_telling * 1.3,
            "photographs": [
                harness.save_frame(before, "new-data-before"),
                harness.save_frame(without_telling, "new-data-without-telling-it"),
                harness.save_frame(after, "new-data-after-telling-it"),
            ],
        },
        "what the refresh costs": {
            "pieces of image re-fetched to show the new tiles": cost["requests"],
            "of which held picture": cost["found"],
            "seconds": round(cost["seconds"], 2),
            "note": (
                "only the pieces actually on screen are asked for again, so this "
                "follows the size of the window rather than the size of the "
                "specimen. Anything the operator had scrolled past is fetched "
                "again if and when they scroll back to it."
            ),
        },
        "does the picture survive the refresh": {
            "frames the screen changed during the refresh": len(during),
            "the least the picture ever showed during it":
                round(min(during), 4) if during else None,
            "it settled at": settled,
            "seconds before the picture was back to half of that":
                round(dark_for, 2) if dark_for is not None else None,
            "what the window showed, frame by frame": during,
            "note": (
                "all three options are meant to keep the picture already on "
                "screen while the store is read again, and to exchange it only "
                "once the new picture is ready to draw. So the right answer here "
                "is a flat line at the settled share. A reading of nought means "
                "the old picture was let go of before the new one had arrived, "
                "which on a run in progress is a window that flashes empty every "
                "few seconds; a run of values between the two would mean two "
                "generations of the data were on screen at once."
            ),
        },
    }


def _does_the_view_stay_put(harness) -> dict:
    """Part four: a refresh that moved the view would be unusable.

    Easy to get wrong, because on some engines the way to refresh is to hand over
    a fresh source, and a fresh source is a fresh idea of where to look. Read from
    the picture as well as from the view, because a view that reports the right
    numbers while the picture has jumped is exactly the failure this project
    keeps meeting.
    """
    harness.believes("window.harness.reset()")
    harness.settle(tries=15)
    before_picture = harness.photograph()
    before_view = harness.believes("window.harness.view()")
    harness.believes("window.harness.tilesMayHaveLanded()")
    time.sleep(1.5)
    harness.settle(tries=15)
    after_view = harness.believes("window.harness.view()")
    after_picture = harness.photograph()

    def edge(picture):
        row = np.asarray(picture)[picture.shape[0] // 2, :, :].max(axis=1)
        lit = np.nonzero(row > 60)[0]
        return float(lit[0]) if len(lit) else None

    was, now = edge(before_picture), edge(after_picture)
    return {
        "does the view stay where the operator put it": {
            "the centre moved (µm)": round(
                abs(after_view["centre"]["x"] - before_view["centre"]["x"])
                + abs(after_view["centre"]["y"] - before_view["centre"]["y"]),
                3,
            ),
            "the zoom changed (µm per screen pixel)": round(
                abs(after_view["zoom"] - before_view["zoom"]), 4
            ),
            "the edge of the picture moved (photograph pixels)":
                round(abs(now - was), 1) if was is not None and now is not None
                else None,
        }
    }


def _how_soon_after_the_tile_lands(harness, canvases) -> dict:
    """Part five: how many seconds pass between a tile landing and showing."""
    from acquisitions import SPARSE_TILE, _a_tile

    harness.believes("window.harness.reset()")
    harness.settle(tries=15)
    before = _lit(harness.photograph())
    canvases.write(
        _a_tile(1, SPARSE_TILE, SPARSE_TILE, 99),
        origin=(0, 0, 2 * SPARSE_TILE),
        tile_index=(0, 0, 2),
    )
    landed = time.perf_counter()
    harness.believes("window.harness.tilesMayHaveLanded()")
    showed = None
    lit = before
    # One more tile is a small share of a window that already has several in it,
    # so this asks for a definite increase rather than a proportional one. Half a
    # per cent of the window is far more than the noise between two photographs
    # of a still picture and far less than one tile covers.
    while time.perf_counter() - landed < 20:
        lit = _lit(harness.photograph())
        if lit > before + 0.005:
            showed = time.perf_counter()
            break
        time.sleep(0.15)
    return {
        "how soon after the tile lands does it show": {
            "seconds": round(showed - landed, 2) if showed else None,
            "it showed": showed is not None,
            "share of the window showing picture, before": before,
            "and after": lit,
            "note": (
                "the clock starts when the tile is safely on disk and stops when "
                "the window is measurably brighter than it was. It includes the "
                "time spent photographing, so it is an upper bound rather than a "
                "best case."
            ),
        }
    }


def _does_it_keep_up(harness, canvases) -> dict:
    """Part six: a long run at a realistic rate, with the operator moving about.

    Not one tile. Several hundred arriving steadily while the view is panned and
    zoomed throughout, and the question is whether the picture keeps pace or
    falls progressively further behind.
    """
    from acquisitions import SPARSE_TILE, _a_tile

    keep_writing = threading.Event()
    keep_writing.set()
    written = {"tiles": 0}

    def write_hard():
        seed = 0
        while keep_writing.is_set():
            row, column = (seed // 4) % 4, seed % 4
            canvases.write(
                _a_tile(1, SPARSE_TILE, SPARSE_TILE, seed),
                origin=(0, row * SPARSE_TILE, column * SPARSE_TILE),
                tile_index=(0, row, column),
            )
            written["tiles"] += 1
            seed += 1
            time.sleep(0.02)

    harness.believes("window.harness.reset()")
    harness.settle(tries=15)
    writer = threading.Thread(target=write_hard, daemon=True)
    writer.start()
    drawing_rate = []
    lag = []
    try:
        for round_number in range(6):
            with Recording(harness.page) as recording:
                started = time.perf_counter()
                harness.believes("window.harness.tilesMayHaveLanded()")
                pan_steadily(harness.page, steps=12, step=6)
                harness.page.mouse.wheel(0, -120 if round_number % 2 == 0 else 120)
                time.sleep(max(0.0, 2.5 - (time.perf_counter() - started)))
                elapsed = time.perf_counter() - started
            pictures = [picture for _, picture in recording.pictures()]
            changed = sum(
                1 for a, b in zip(pictures, pictures[1:]) if not np.array_equal(a, b)
            )
            drawing_rate.append(round(changed / elapsed, 1))
            lag.append(round(elapsed, 2))
    finally:
        keep_writing.clear()
        writer.join(timeout=10)
    return {
        "does it keep up": {
            "tiles written during the measurement": written["tiles"],
            "frames a second, round by round": drawing_rate,
            "seconds a round took": lag,
            "the drawing rate held up": (
                len(drawing_rate) > 1
                and drawing_rate[-1] >= 0.5 * max(drawing_rate)
            ),
        }
    }


# ---------------------------------------------------------------------------
# 6. Requests
# ---------------------------------------------------------------------------


def requests_to_draw_one_view(harness) -> dict:
    """How many pieces of image are asked for, and how many are for empty ground?

    Measured on the sparse canvas, which is the shape a real run has: a large
    declared room with a small patch imaged in it. Taken with and without the
    coverage record bounding the region the engine is given, because that is the
    single largest saving in the arrangement and it deserves to be shown rather
    than asserted.
    """
    found = {}
    for bounded in (False, True):
        harness.open(store="sparse", draw="margin", bounded="1" if bounded else "0")
        harness.believes("window.harness.reset()")
        harness.settle(tries=20)
        harness.clear_ledger()
        started = time.perf_counter()
        harness.believes("window.harness.tilesMayHaveLanded()")
        seen, quiet_since = -1, None
        while time.perf_counter() - started < 60:
            now = harness.read_ledger()
            if now["requests"] != seen:
                seen, quiet_since = now["requests"], time.perf_counter()
            elif quiet_since and time.perf_counter() - quiet_since > 0.6 and seen > 0:
                break
            time.sleep(0.05)
        ledger = harness.read_ledger()
        found["bounded to the imaged ground" if bounded else "unbounded"] = {
            "requests to redraw the view": ledger["requests"],
            "of which found picture": ledger["found"],
            "of which were for ground nobody imaged": ledger["missing"],
            "how many the browser held at once": ledger["at_once"],
            "rounds of waiting": ledger["rounds"],
            "seconds": round(ledger["seconds"], 2),
        }
    return found


# ---------------------------------------------------------------------------
# 7. Drawing rate with many positions
# ---------------------------------------------------------------------------


# How many times the drawing rate is read before any of it is reported.
#
# One reading of this is worth very little, and that is measured rather than
# feared. Taken five times over on one unchanged build, single readings ranged
# from 4.8 to 10.3 frames a second on the same option at the same number of
# positions — a factor of two — while the medians of two options a reader would
# want to compare sat within a few tenths of each other. A single number in a
# table invites exactly the comparison it cannot support, so the reading is
# repeated and the spread is reported beside the middle value.
#
# Five is a compromise. It costs about fifteen seconds an option and it is enough
# to show plainly when two options' spreads overlap, which is the thing a reader
# has to know before treating a difference as real.
HOW_MANY_TIMES_THE_RATE_IS_READ = 5


def drawing_rate_with_many_positions(harness) -> dict:
    """Does the cost of drawing grow with the number of tiles the operator laid out?

    This is the existing fault, asked of the arrangement rather than of the
    engine: the operator's own drawing carries a rectangle per position, and in
    the sandwich that drawing is repainted from inside every frame the engine
    announces. If the cost of the drawing grows with the number of positions, it
    drags the engine's own frame rate down with it — which is the thing that
    differs between drawing in two canvases and drawing in one.

    Frames are counted from a live recording of the screen over three seconds of
    continuous panning, not from anything the page says about itself.

    **This is the least trustworthy measurement in the suite, and it now says so
    in its own numbers.** On a machine with no graphics card the rate wanders a
    great deal from one reading to the next for reasons that have nothing to do
    with the code — another program waking up is enough. So the three seconds of
    panning is done five times over on the same page, and what is reported is the
    middle reading with the lowest and highest beside it. Two options whose
    ranges overlap have not been shown to differ, however far apart their middle
    readings happen to fall, and the table is written so that a reader can see
    that at a glance.
    """
    found = {}
    for positions in (20, 200):
        harness.open(store="scattered", draw="carrier", positions=positions)
        readings = []
        for _ in range(HOW_MANY_TIMES_THE_RATE_IS_READ):
            # Back to the same view before every reading, so that each of them
            # is of the same scene rather than of wherever the last pan finished.
            harness.believes("window.harness.reset()")
            harness.settle(tries=20)
            with Recording(harness.page) as recording:
                started = time.perf_counter()
                while time.perf_counter() - started < 3.0:
                    pan_steadily(harness.page, steps=10, step=4)
                elapsed = time.perf_counter() - started
            pictures = [picture for _, picture in recording.pictures()]
            changed = sum(
                1 for a, b in zip(pictures, pictures[1:]) if not np.array_equal(a, b)
            )
            readings.append(round(changed / elapsed, 1))
        in_order = sorted(readings)
        found[f"{positions} positions"] = {
            "frames a second": in_order[len(in_order) // 2],
            "frames a second, lowest and highest seen": [in_order[0], in_order[-1]],
            "frames a second, every reading in the order taken": readings,
            "how many times it was read": len(readings),
            "rectangles the page was drawing": harness.believes(
                "window.harness.scene.tiles.length"
            ),
            "note": (
                "the middle of several readings, not a single one. Single "
                "readings of this on a machine with no graphics card have been "
                "seen to vary by a factor of two on an unchanged build, so the "
                "lowest and highest are reported beside the middle value. Two "
                "options whose ranges overlap have not been shown to differ."
            ),
        }
    return found


# ---------------------------------------------------------------------------
# Everything, in order
# ---------------------------------------------------------------------------

# In the order they should be run rather than the order OPTIONS.md lists them.
# The question about showing through comes first because the whole sandwich
# arrangement depends on the answer, and there is no sense measuring anything
# built on top of an assumption that has not been checked.
EVERYTHING = {
    "0. can a surface underneath be seen": lambda h, d: (
        can_a_surface_underneath_be_seen(h)
    ),
    "0b. is the bottom layer beneath the picture": lambda h, d: (
        is_the_bottom_layer_beneath_the_picture(h)
    ),
    "1. registration": lambda h, d: registration(h),
    "1b. registration of the bottom layer": lambda h, d: (
        registration_of_the_bottom_layer(h)
    ),
    "2. handedness": lambda h, d: handedness(h),
    "3. two gestures and no more": lambda h, d: two_gestures_and_no_more(h),
    "4. sparseness": lambda h, d: sparseness(h),
    "5. new data arriving while somebody is watching": new_data_arriving,
    "6. requests": lambda h, d: requests_to_draw_one_view(h),
    "7. drawing rate with many positions": lambda h, d: (
        drawing_rate_with_many_positions(h)
    ),
}

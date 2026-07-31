"""Is the bottom layer really beneath the picture, where an operator can see it?

`viz_studio/THE_CANVAS.md` describes the front end's main surface as three layers
sharing one coordinate system: the application's own drawing beneath the picture,
the acquired picture in the middle, and the operator's marks above. The interface
in `viz_studio/options/contract.md` gives an application a slot for each —
`drawUnder(paint)` and `drawOver(paint)`, written exactly alike — and every option
implements both.

**Implementing a slot and honouring it are two different things**, and this is the
measurement that tells them apart. An engine whose canvas is opaque covers
whatever is behind it, so a drawing handed to `drawUnder` is made, is correct, and
is seen by nobody. Each option therefore also says plainly what it does, as
`viewer.drawsUnder`; this measurement checks that claim against a photograph
rather than taking it on trust, which is the only way a claim like that is worth
anything.

**How it is measured.** The page is opened on an acquisition imaged in a few
scattered places, so most of the window is ground nobody has been to. Three
photographs are then taken of the same page, and it takes all three to answer the
question honestly.

1. **Nothing in either slot.** This says how much of the window the acquired
   picture covers when the application draws nothing at all. Every later reading
   is compared against it.
2. **One saturated colour in the bottom slot.** For the answer to be yes, two
   things have to be true at once: the colour has to appear at all, *and* the
   picture has to still be there on top of it. A colour that covers the picture
   is not beneath it.
3. **The same colour in the top slot instead.** This is the check that the
   reading means what it says.

**Why the second half of the bottom-slot test is not optional.** Without it, an
option that quietly drew the bottom slot *above* the picture would pass. That is
not a hypothetical: it was tried, by moving the bottom layer to the far end of
one option's list of layers, and the reading before this was added said "yes,
the application's own drawing really does sit beneath the picture" while the
picture it was supposed to be underneath had vanished from the window
altogether. The share of the window it reported went from 96.95% to 100%, which
is the whole of the difference between the two arrangements — a number nobody
would have read as a fault. Asking whether the picture survived turns that
silent difference into a plain no. `contract.md` §4a says drawing the bottom
layer on top instead is the exact thing an option must never do; this is what
would catch it.

**And the top-slot check is what shows the reading can go the other way.** It is
the same colour, the same page and the same drawing function, moved from one slot
to the other. In the top slot it must both fill the window and hide the picture,
on every option, including the one that showed none of it in the bottom slot. A
check that has never been seen to give the other answer is not evidence of
anything.

Nothing here asks the engine what it drew. Three photographs and the counting are
the whole of it. The one thing the page *is* asked is what the option claims about
itself, and that is reported beside the photographs so that a claim and a
measurement disagreeing would be visible rather than hidden.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from showing_through import (  # noqa: E402
    BEHIND_IS_GREEN,
    ENGINE_BACKGROUND_IS_BLUE,
    _how_much_of_each,
)

# How much of the window the drawn colour has to fill before it counts as having
# been seen at all. Two per cent is far more than any speck of compression noise
# in a photograph and far less than a layer covering the window, and it is the
# same threshold `showing_through.py` uses for the neighbouring question.
ENOUGH_TO_HAVE_BEEN_SEEN = 0.02

# How much of the acquired picture has to survive a colour drawn in the bottom
# slot before we will say the colour is really underneath it. Half of what the
# picture covered with nothing drawn at all is a generous allowance: a layer
# genuinely beneath the picture takes none of it away, and a layer painted over
# the top takes all of it. Anything in between would be a new and interesting
# fault, and it would fall on the failing side, which is the right way round.
ENOUGH_OF_THE_PICTURE_LEFT = 0.5


def _a_colour_in_one_slot(harness, *, under: str, over: str, name: str) -> dict:
    """Draw the same flat colour in one slot or the other, and photograph it."""
    harness.believes(
        "window.harness.drawInTheSlots({under: %r, over: %r, colour: %r})"
        % (under, over, BEHIND_IS_GREEN)
    )
    harness.settle(tries=20)
    picture = harness.photograph()
    shares = _how_much_of_each(picture)
    return {
        "shares of the window": shares,
        "the colour was seen": shares["behind the engine (green)"]
        > ENOUGH_TO_HAVE_BEEN_SEEN,
        "photograph": harness.save_frame(picture, name),
    }


def _how_much_picture_with_nothing_drawn(harness) -> dict:
    """Photograph the page with both slots empty, to see how much picture there is.

    This is the yardstick the two later photographs are held against. Saying "the
    picture is still there" needs a number for how much of it there was to begin
    with, and taking that from the same page a moment earlier is the only way to
    have one that is not an assumption about the acquisition.
    """
    harness.believes(
        "window.harness.drawInTheSlots({under: 'nothing', over: 'nothing'})"
    )
    harness.settle(tries=20)
    picture = harness.photograph()
    shares = _how_much_of_each(picture)
    return {
        "shares of the window": shares,
        "photograph": harness.save_frame(picture, "beneath-with-nothing-drawn"),
    }


def measure(harness, *, store: str = "scattered") -> dict:
    """Draw a colour beneath the picture and see whether an operator would see it.

    The drawn region is deliberately *not* bounded to the coverage record here,
    and that matters more than anywhere else. Bounded, the engine's surface covers
    only the part of the window holding imaged ground, so a colour drawn beneath
    would be seen everywhere around it — which is a fact about the size of a box
    rather than about whether a surface lets light through, and it would read as a
    yes on an engine that is really a no. Unbounded, the engine covers the whole
    window and the question being asked is the one that was meant.
    """
    harness.open(
        option=harness.option,
        store=store,
        draw="none",
        background=ENGINE_BACKGROUND_IS_BLUE,
        bounded="0",
    )
    with_nothing_drawn = _how_much_picture_with_nothing_drawn(harness)
    picture_to_begin_with = with_nothing_drawn["shares of the window"][
        "acquired picture (near white)"
    ]
    beneath = _a_colour_in_one_slot(
        harness, under="a colour", over="nothing", name="beneath-the-picture"
    )
    seen = beneath["shares of the window"]["behind the engine (green)"]
    engine = beneath["shares of the window"]["the engine's own background (blue)"]
    picture_left = beneath["shares of the window"]["acquired picture (near white)"]
    # Both halves of the question, kept apart so that a reader can see which of
    # them an option failed. The colour has to be visible, and the picture it is
    # supposed to be underneath has to still be visible too.
    the_colour_showed = seen > ENOUGH_TO_HAVE_BEEN_SEEN
    the_picture_survived = picture_left >= (
        picture_to_begin_with * ENOUGH_OF_THE_PICTURE_LEFT
    )
    beneath["the picture is still on top of it"] = {
        "share of the window showing picture, with nothing drawn":
            picture_to_begin_with,
        "and with the colour in the bottom slot": picture_left,
        "the picture survived": bool(the_picture_survived),
    }
    found = {
        "question": (
            "with one flat colour drawn in the bottom slot and nothing in the "
            "top, does an operator see that colour over ground nobody imaged — "
            "and is the acquired picture still on top of it?"
        ),
        "what the option says of itself": {
            "drawsUnder": harness.believes("window.harness.drawsUnder"),
            "because": harness.believes("window.harness.drawsUnderBecause"),
        },
        "with nothing drawn in either slot": with_nothing_drawn,
        "with the colour in the bottom slot": beneath,
        "the bottom layer is genuinely beneath the picture": bool(
            the_colour_showed and the_picture_survived
        ),
    }
    if the_colour_showed and the_picture_survived:
        found["answer"] = (
            f"yes. A colour drawn in the bottom slot fills {seen:.0%} of the "
            "window, and the acquired picture is still drawn on top of it — "
            f"{picture_left:.2%} of the window, against {picture_to_begin_with:.2%} "
            "with nothing drawn at all. So the application's own drawing really "
            "does sit beneath the picture, and an operator sees it wherever the "
            "picture has not been written."
        )
    elif the_colour_showed:
        found["answer"] = (
            f"no. The colour is seen — it fills {seen:.0%} of the window — but it "
            "has covered the acquired picture rather than sitting under it: the "
            f"picture went from {picture_to_begin_with:.2%} of the window with "
            f"nothing drawn to {picture_left:.2%} with the colour in the bottom "
            "slot. A drawing that hides the picture is on top of it, whatever "
            "slot it was handed to."
        )
    else:
        found["answer"] = (
            "no. A colour drawn in the bottom slot is seen nowhere at all: over "
            f"ground nobody imaged an operator sees the engine's own background "
            f"({engine:.0%} of the window) instead. The drawing is made, on a "
            "surface genuinely behind the engine's canvas, and the engine covers "
            "it. This option says so itself, as viewer.drawsUnder, rather than "
            "drawing the same thing on top with holes cut in it — which would "
            "look identical while doing something quite different underneath."
        )
    found["and the check can fail"] = check_it_can_fail(
        harness, picture_to_begin_with
    )
    return found


def check_it_can_fail(harness, picture_to_begin_with: float) -> dict:
    """Move the same colour to the top slot and watch the reading change.

    This is the deliberate breakage, and it is a gentle one: nothing is hidden
    and nothing is lied about. The very same flat colour, painted by the very same
    drawing function on the very same page, is handed to the *other* slot. Every
    option must then show two things at once: the colour filling the window —
    including on the option that showed none of it a moment ago — and the acquired
    picture gone from the window, because a colour on the top slot covers it.

    That second half is what makes the whole reading mean "which slot" rather than
    "which colour". A drawing that fills the window and hides the picture is on
    top of the picture; a drawing that fills the window and leaves the picture
    showing is underneath it. Reading both means an option that quietly drew the
    bottom slot on top would be caught here rather than reported as a success.
    """
    above = _a_colour_in_one_slot(
        harness, under="nothing", over="a colour", name="beneath-can-fail-on-top"
    )
    # Put the page back the way it was found, so that nothing after this measures
    # a page still holding a deliberate breakage.
    harness.believes(
        "window.harness.drawInTheSlots({under: 'nothing', over: 'the scene'})"
    )
    seen = above["shares of the window"]["behind the engine (green)"]
    picture_left = above["shares of the window"]["acquired picture (near white)"]
    above["the picture is still on top of it"] = {
        "share of the window showing picture, with nothing drawn":
            picture_to_begin_with,
        "and with the colour in the top slot": picture_left,
        # The right answer here is "no". A colour in the top slot is meant to
        # cover the picture, and this is the reading that shows the two slots
        # really do behave differently on the same page.
        "the picture survived": bool(
            picture_left >= picture_to_begin_with * ENOUGH_OF_THE_PICTURE_LEFT
        ),
    }
    return {
        "what was changed": (
            "the same flat colour was drawn in the top slot instead of the "
            "bottom one, with everything else on the page left exactly as it was"
        ),
        "with the colour in the top slot": above,
        "the counting noticed": bool(
            seen > 0.5
            and picture_left < picture_to_begin_with * ENOUGH_OF_THE_PICTURE_LEFT
        ),
    }

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
scattered places, so most of the window is ground nobody has been to. One
saturated colour is drawn in the bottom slot and nothing at all in the top. Then a
photograph is taken and the colours counted. If the colour appears, the bottom
layer is genuinely beneath the picture. If only the engine's own background
appears, it is not.

**And then the same colour is drawn in the top slot instead**, with nothing in the
bottom. That is the check that this reading means what it says. It is the same
colour, the same page and the same drawing function, moved from one slot to the
other, so if the top reading fills the window on every option while the bottom
reading does not, the difference is the slot and nothing else. A check that has
never been seen to give the other answer is not evidence of anything.

Nothing here asks the engine what it drew. Two slots, two photographs, and the
counting is the whole of it. The one thing the page *is* asked is what the option
claims about itself, and that is reported beside the photograph so that a claim
and a measurement disagreeing would be visible rather than hidden.
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
    beneath = _a_colour_in_one_slot(
        harness, under="a colour", over="nothing", name="beneath-the-picture"
    )
    seen = beneath["shares of the window"]["behind the engine (green)"]
    engine = beneath["shares of the window"]["the engine's own background (blue)"]
    found = {
        "question": (
            "with one flat colour drawn in the bottom slot and nothing in the "
            "top, does an operator see that colour over ground nobody imaged?"
        ),
        "what the option says of itself": {
            "drawsUnder": harness.believes("window.harness.drawsUnder"),
            "because": harness.believes("window.harness.drawsUnderBecause"),
        },
        "with the colour in the bottom slot": beneath,
        "the bottom layer is genuinely beneath the picture": bool(
            seen > ENOUGH_TO_HAVE_BEEN_SEEN
        ),
    }
    if seen > ENOUGH_TO_HAVE_BEEN_SEEN:
        found["answer"] = (
            f"yes. A colour drawn in the bottom slot fills {seen:.0%} of the "
            "window, so the application's own drawing really does sit beneath "
            "the picture and an operator sees it wherever the picture has not "
            "been written."
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
    found["and the check can fail"] = check_it_can_fail(harness)
    return found


def check_it_can_fail(harness) -> dict:
    """Move the same colour to the top slot and watch the reading change.

    This is the deliberate breakage, and it is a gentle one: nothing is hidden
    and nothing is lied about. The very same flat colour, painted by the very same
    drawing function on the very same page, is handed to the *other* slot. Every
    option must then show it filling the window — including the one that showed
    none of it a moment ago.

    That is what makes the reading above mean "which slot" rather than "which
    colour". Without it, an option reporting nothing beneath the picture could
    equally be an option whose drawing never ran, or a counting program that can
    only ever answer nought.
    """
    above = _a_colour_in_one_slot(
        harness, under="nothing", over="a colour", name="beneath-can-fail-on-top"
    )
    # Put the page back the way it was found, so that nothing after this measures
    # a page still holding a deliberate breakage.
    harness.believes(
        "window.harness.drawInTheSlots({under: 'nothing', over: 'the scene'})"
    )
    return {
        "what was changed": (
            "the same flat colour was drawn in the top slot instead of the "
            "bottom one, with everything else on the page left exactly as it was"
        ),
        "with the colour in the top slot": above,
        "the counting noticed": above["shares of the window"][
            "behind the engine (green)"
        ]
        > 0.5,
    }

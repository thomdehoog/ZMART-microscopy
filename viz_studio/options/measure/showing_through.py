"""Does anything behind the engine's canvas ever show through it?

This is the question the whole sandwich arrangement rests on, and until now
nobody had asked it. It is measured first, before anything is built on top of the
answer, and the answer is reported plainly whichever way it comes out.

**Why it matters.** `LAYERS.md` sets out a stack with the carrier outline at the
bottom, the operator's planned tiles above it, and the acquired picture above
those. Read literally, and drawn as a sandwich, that arrangement wants three
surfaces: the operator's plan underneath, the engine's canvas in the middle
showing picture where there is picture and nothing where there is none, and the
operator's scribbles and selection on top. For the middle surface to be
transparent where nothing was imaged, two things have to be true at once — the
shader has to emit nothing there, which it does, and that nothing has to survive
all the way to the screen.

**How it is measured.** The box the viewer was opened inside is painted one
saturated colour. The engine's own background behind the picture is set to a
different saturated colour. The acquisition is one imaged in a few scattered
places, so most of the window is ground nobody has been to. Then a photograph is
taken and the colours counted. If the box's colour appears, the engine's canvas
is letting what is behind it through. If only the engine's background appears, it
is not.

Nothing here asks the engine anything. Two colours, one photograph, and the
counting is the whole of it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402

# Two colours nothing could confuse, and neither of them anywhere near the
# near-white the picture is drawn in.
BEHIND_IS_GREEN = "#00ff00"
ENGINE_BACKGROUND_IS_BLUE = "#0000ff"


def _how_much_of_each(picture) -> dict:
    """What share of the window is each of the three things we can tell apart."""
    picture = np.asarray(picture).astype(int)
    red, green, blue = picture[:, :, 0], picture[:, :, 1], picture[:, :, 2]
    behind = (green > 120) & (red < 90) & (blue < 90)
    engine = (blue > 120) & (red < 90) & (green < 90)
    image = (red > 150) & (green > 150) & (blue > 150)
    total = picture.shape[0] * picture.shape[1]
    return {
        "behind the engine (green)": round(float(behind.sum() / total), 4),
        "the engine's own background (blue)": round(float(engine.sum() / total), 4),
        "acquired picture (near white)": round(float(image.sum() / total), 4),
    }


def measure(harness, *, store: str = "scattered") -> dict:
    """Open the viewer with a colour behind it, and see whether it shows."""
    harness.open(
        option=harness.option,
        store=store,
        draw="none",
        background=ENGINE_BACKGROUND_IS_BLUE,
        under=BEHIND_IS_GREEN,
        # The engine is given the whole window rather than only the part that
        # covers imaged ground, and that matters here more than anywhere else.
        # With the drawn region bounded, most of the window is not covered by
        # the engine's surface at all, so the colour behind shows around it —
        # which is a fact about the size of a box, not about whether a surface
        # lets light through. Bounded, this measurement read 78% "shows
        # through"; unbounded, on the same page, it reads 0%.
        bounded="0",
    )
    picture = harness.photograph()
    shares = _how_much_of_each(picture)
    behind = shares["behind the engine (green)"]
    engine = shares["the engine's own background (blue)"]
    found = {
        "question": (
            "with a colour painted behind the engine's canvas and a different "
            "colour set as the engine's own background, which does an operator "
            "see over ground nobody imaged?"
        ),
        "shares of the window": shares,
        "photograph": harness.save_frame(picture, "showing-through"),
    }
    if behind > 0.02:
        found["answer"] = (
            "what is behind the engine's canvas does show through it, so a "
            "surface underneath is usable"
        )
        found["a surface underneath is usable"] = True
    else:
        found["answer"] = (
            "nothing behind the engine's canvas shows through. Over ground "
            f"nobody imaged an operator sees the engine's own background "
            f"({engine:.0%} of the window) and none of the colour painted "
            "behind it. A surface underneath the engine cannot be seen at all, "
            "so the operator's carrier and tiles have to be drawn on the "
            "surface ABOVE the engine, with holes cut where the run's coverage "
            "record says there is picture."
        )
        found["a surface underneath is usable"] = False
    return found


def check_it_can_fail(harness) -> dict:
    """Show that the same measurement would notice if the answer were yes.

    A check that has never been seen to give the other answer is not evidence of
    anything. So the same counting is run on a photograph where the colour
    behind *is* visible — by opening on a store with no picture in the window at
    all and painting the box's colour over the whole of it, with no engine
    surface in front. If the counting reports "shows through" there and "does not"
    on the real arrangement, then it is reading the picture rather than reporting
    a constant.
    """
    page = harness.page
    # Hide the option's surfaces outright, leaving only the box and its colour.
    # This is deliberately a lie about the arrangement — it is the deliberate
    # breakage, and it is undone immediately afterwards.
    page.evaluate(
        """() => {
          for (const el of document.getElementById('viewer').children) {
            el.dataset.hiddenForTheCheck = '1';
            el.style.display = 'none';
          }
        }"""
    )
    picture = harness.photograph()
    shares = _how_much_of_each(picture)
    page.evaluate(
        """() => {
          for (const el of document.getElementById('viewer').children) {
            if (el.dataset.hiddenForTheCheck) el.style.display = '';
          }
        }"""
    )
    return {
        "what was broken": (
            "the option's own drawing surfaces were hidden, so that only the "
            "colour painted behind them was left on screen"
        ),
        "shares of the window": shares,
        "the counting noticed": shares["behind the engine (green)"] > 0.5,
        "photograph": harness.save_frame(picture, "showing-through-can-fail"),
    }

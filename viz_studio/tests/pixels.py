"""Looking at what the viewer actually put on screen.

Most of the tests here ask the viewer about itself: how many layers are open,
what the contrast window is, whether a piece of image arrived. Those are useful
questions, but they all share one blind spot — the engine can answer every one of
them correctly and still draw nothing at all.

That is not hypothetical. For a while the viewer opened on a flat grey rectangle
with every piece of image loaded and the engine perfectly satisfied, because the
magnification had been settled before the images had said how big they were, so
the specimen was drawn about a ten-thousandth of a pixel wide. Three hundred
tests passed. None of them looked at the picture.

So this module takes a photograph of the picture and measures it. It is a
deliberately blunt instrument: it cannot tell you the image is *correct*, only
that there is an image rather than an empty panel. That turns out to be the check
that was missing.
"""

from __future__ import annotations

import io

# How much of the image to look at. Half the width and half the height, taken
# from the middle.
#
# The middle rather than the whole of it, because our own controls -- the 2D/3D
# buttons, the scale bar, the sliders -- sit in the corners *on top of* the
# image, and they would supply variety of their own. A check that counted them
# could not tell a drawn specimen from an empty panel with a button on it, which
# is the very mistake this is here to prevent.
_MIDDLE = 0.5


def image_middle(page):
    """The pixels in the middle of the image, as height x width x RGB.

    This is what the operator would see, photographed: the engine's drawing
    surface with everything composited onto it, rather than a number the engine
    reports about itself. That distinction is the whole point.
    """
    import numpy as np
    from PIL import Image

    canvas = page.locator("canvas").first.bounding_box()
    margin = (1 - _MIDDLE) / 2
    shot = page.screenshot(
        clip={
            "x": canvas["x"] + canvas["width"] * margin,
            "y": canvas["y"] + canvas["height"] * margin,
            "width": canvas["width"] * _MIDDLE,
            "height": canvas["height"] * _MIDDLE,
        }
    )
    return np.array(Image.open(io.BytesIO(shot)).convert("RGB"))


def colour_spread(pixels) -> dict:
    """How much variety there is in a patch of image.

    Returns three numbers, which all say the same thing from different angles
    because any single one of them is easy to fool:

    ``distinct``
        how many different colours appear. A panel showing nothing has one.
    ``dominant_fraction``
        what share of the patch is taken up by its most common colour. One means
        every pixel is identical.
    ``spread``
        the standard deviation of the values — roughly, how far a typical pixel
        sits from the average. Zero means perfectly flat.

    Measured on the demo volume, a drawn image gives about 215 colours, a
    dominant share near 0.5, and a spread around 60. The same panel with nothing
    drawn in it gives exactly 1, 1.0 and 0.0. There is a lot of room between
    those two, which is what makes this worth asserting rather than eyeballing.
    """
    import numpy as np

    flat = pixels.reshape(-1, pixels.shape[-1])
    _, counts = np.unique(flat, axis=0, return_counts=True)
    return {
        "distinct": int(len(counts)),
        "dominant_fraction": float(counts.max() / len(flat)),
        "spread": float(pixels.std()),
    }


def fraction_lit(page, floor: int = 40) -> float:
    """How much of the middle of the picture is showing specimen rather than nothing.

    This answers a different question from :func:`assert_something_was_drawn`, and
    the difference matters more than it sounds.

    That one asks "does this panel have variety in it", which is the right question
    when the worry is a viewer that has drawn nothing at all. But it cannot tell a
    blank panel from one *completely covered* by an even tile: both are a single
    flat colour, and both score the same. A canvas being filled in tile by tile
    reaches exactly that state as soon as the tiles cover the view, so a test
    watching for variety would report the picture vanishing at the moment it became
    complete.

    Counting how much of the view is brighter than the background separates the two,
    and it rises steadily as tiles land, which is what a test following a run needs.
    The floor sits well above the near-black of an unimaged region and well below
    any real signal, so it is not sensitive to where it is set.
    """
    pixels = image_middle(page)
    return float((pixels.max(axis=2) > floor).mean())


def assert_something_was_drawn(page, what: str = "the image") -> dict:
    """Fail unless the middle of the image really has a picture in it.

    The thresholds sit a long way from both the drawn and the blank measurements
    quoted above, so this fails on an empty panel without being so eager that it
    passes on anything at all. ``test_render_acceptance`` keeps a companion test
    that empties the panel on purpose and checks this *does* fail — which is what
    stops it quietly rotting into an assertion that cannot fail.
    """
    spread = colour_spread(image_middle(page))
    assert spread["distinct"] > 2, f"{what} is a flat colour: {spread}"
    assert spread["dominant_fraction"] < 0.99, f"{what} is almost entirely one colour: {spread}"
    assert spread["spread"] > 1.0, f"{what} has no variation in it: {spread}"
    return spread

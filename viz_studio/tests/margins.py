"""Do the margins stay even? — a check that two stacked layers stay lined up.

This is the companion to :mod:`pixels`. That module asks "is there a picture on
screen at all", which is the question that catches a viewer drawing nothing. This
one asks a different question, and it is the one that catches a viewer drawing
two things that no longer agree with each other:

    **Draw a square of image. Cut a hole slightly larger than that square,
    centred on it, in whatever is drawn over the image. Then measure the band of
    background between the two, on each of the four sides.**

If the two layers are lined up, those four numbers are equal, and they stay
equal however the view is panned, zoomed or thrown about. If they are not, the
numbers go uneven — and *which way* they go says what has gone wrong:

- one side thick and the opposite side thin: the layer on top is being drawn
  from a position the layer underneath has not reached yet, which is a follower
  lagging behind and is what panning produces;
- all four growing or shrinking together: the two disagree about magnification
  rather than about position.

The reason this is worth having as a general check, rather than as part of one
investigation, is that the right answer is "unchanged". There is no number to
interpret and no threshold to argue over. That also makes it usable on a machine
with no graphics card: software rendering changes *when* a frame appears, so it
changes how often a measurement can be taken, but a margin that is uneven within
a single photograph is the fault itself and slowness cannot invent one.

**How small a disagreement this can see, which is not nothing.** Everything here
is counted in whole pixels of a photograph, so half a pixel is the finest thing
it could ever resolve — and against an engine that draws a hard edge it is
coarser than that. Some engines fade the edge of the picture across the last
pixel and some do not. Where the edge is faded, that half-lit pixel is neither
"image" nor "background" by the tests below, so it is skipped on both sides and
the two margins stay equal. Where the edge is hard, the block of picture always
begins and ends on a whole pixel, and if the true edge happens to fall half way
across one, no amount of correct registration can centre a block of whole pixels
inside the hole: one margin comes out a pixel wider than the one opposite.

So **a reading of one, on an engine with a hard edge, means "these two agree to
within half a screen pixel" and not "these two disagree"**. It was demonstrated
rather than assumed: with the hole moved half a pixel away from where it belongs,
the same reading came out even. `viz_studio/options/RESULTS.md` tells the story
under measurement 1. Readings of two and more are real, which is why the checks
that use this allow one and no more.

**On the colours.** The measurement needs to tell four things apart in a
photograph: the image, the background of whatever draws it, the layer on top,
and — where a test uses one — something the operator has drawn that is supposed
to sit exactly on the edge of the image. So they are given four colours nothing
could confuse: near-white, saturated blue, saturated red and saturated green.

In a finished viewer the background is meant to *match* the page, so that the
seam between the two layers cannot be seen at all — that is the whole point of
the arrangement. They differ here only so that the margin can be seen and
measured. Please do not "tidy" them into agreement: this check would go on
passing while measuring nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# What each colour has to look like for a pixel to count as it. Written as
# ranges rather than exact values because a photograph of a screen has been
# through compositing and, when it comes over a live screen recording,
# compression as well. The four are so far apart that generous ranges cannot
# confuse them.
_IMAGE_FLOOR = 150  # the image: bright in all three of red, green and blue
_STRONG = 110  # a colour that is definitely present
_WEAK = 90  # a colour that is definitely absent


def _classify(line):
    """Turn a line of pixels into one yes-or-no stream per colour."""
    import numpy as np

    red = line[:, 0].astype(int)
    green = line[:, 1].astype(int)
    blue = line[:, 2].astype(int)
    return {
        "image": np.asarray(
            (red > _IMAGE_FLOOR) & (green > _IMAGE_FLOOR) & (blue > _IMAGE_FLOOR)
        ),
        "background": np.asarray((blue > _STRONG) & (red < _WEAK) & (green < _WEAK)),
        "over": np.asarray((red > _STRONG) & (green < _WEAK) & (blue < _WEAK)),
        "drawn": np.asarray((green > _STRONG) & (red < _WEAK) & (blue < _WEAK)),
    }


@dataclass
class Line:
    """Where each edge fell along one cut across the photograph.

    Every number is a position in the photograph's own pixels. On a screen that
    packs more than one real pixel into a browser pixel, that is real pixels,
    which is the unit two stacked layers actually have to agree in.

    ``closed`` means the band of background had vanished on at least one side —
    the layer on top has covered the edge of the image entirely. That is not a
    measurement of zero, it is the absence of a measurement, and it means the
    disagreement was *at least* as wide as the band was cut. It is reported
    rather than quietly counted as nothing, because a test that reported the
    worst cases as zero would be reporting the opposite of the truth.
    """

    before: float | None = None
    after: float | None = None
    image_starts: float | None = None
    image_ends: float | None = None
    drawn_at: list[float] = field(default_factory=list)
    closed: bool = False
    why: str = ""


def read_the_line(line) -> Line:
    """Find the image, the band either side of it, and the sheet framing it.

    Each edge is read as the gap between the last pixel that was definitely one
    thing and the first that is definitely the next, so the soft edge left by
    antialiasing falls inside the gap rather than being counted as belonging to
    either side. Every edge is read the same way, so whatever small bias that
    leaves is the same on all four sides and cancels out of the comparison —
    which is the only thing this check ever makes.
    """
    import numpy as np

    seen = _classify(line)
    image, background, over, drawn = (
        seen["image"], seen["background"], seen["over"], seen["drawn"]
    )
    found = Line()
    found.drawn_at = [float(at) for at in np.nonzero(drawn)[0]]
    if not image.any():
        found.why = "no image along this line"
        return found
    found.image_starts = float(np.argmax(image))
    found.image_ends = float(len(image) - 1 - int(np.argmax(image[::-1])))
    first, last = int(found.image_starts), int(found.image_ends)

    before, after = background[:first], background[last + 1:]
    if not before.any() or not after.any():
        found.closed = True
        found.why = "the band of background had closed on one side of the image"
        return found
    last_before = int(np.max(np.nonzero(before)))
    first_after = last + 1 + int(np.min(np.nonzero(after)))
    if not over[:last_before].any() or not over[first_after:].any():
        found.why = "the layer on top was not found outside the band"
        return found
    found.before = float(first - int(np.max(np.nonzero(over[:last_before]))) - 1)
    found.after = float(
        first_after + int(np.min(np.nonzero(over[first_after:]))) - last - 1
    )
    return found


@dataclass
class Margins:
    """The band of background between the hole and the image, on each side."""

    left: float | None = None
    right: float | None = None
    top: float | None = None
    bottom: float | None = None
    found: bool = False
    closed: bool = False
    why: str = ""
    across: Line | None = None
    down: Line | None = None

    @property
    def sides(self) -> dict:
        return {
            "left": self.left, "right": self.right,
            "top": self.top, "bottom": self.bottom,
        }

    @property
    def unevenness(self) -> float | None:
        """How far apart the widest and the narrowest side are.

        This is the single number that says "these two layers have come apart",
        and zero is the right answer.
        """
        if not self.found:
            return None
        widths = list(self.sides.values())
        return max(widths) - min(widths)


def margins_around_the_hole(picture, at=0.5) -> Margins:
    """Read the four margins out of one photograph.

    ``picture`` is a height by width by three array of red, green and blue —
    whatever was on screen. ``at`` says where to take the two cuts across it, as
    a fraction of the way along; the middle is right unless the square has been
    moved off centre on purpose.
    """
    import numpy as np

    picture = np.asarray(picture)
    height, width = picture.shape[0], picture.shape[1]
    across = read_the_line(picture[int(height * at), :, :3])
    down = read_the_line(picture[:, int(width * at), :3])
    if across.before is None or down.before is None:
        return Margins(
            found=False,
            closed=across.closed or down.closed,
            why=across.why or down.why,
            across=across,
            down=down,
        )
    return Margins(
        left=across.before, right=across.after,
        top=down.before, bottom=down.after,
        found=True, across=across, down=down,
    )


# Where to take the cuts across the photograph.
#
# Three rather than one, and none of them exactly through the middle, because a
# single cut through the centre is blind to one particular fault: a view that has
# been *turned*. A square turned by a few degrees still has almost exactly the
# same width across its middle, so a cut there reports nothing wrong. Its edges
# are slanted, though, so two cuts either side of the middle disagree with each
# other — and by an amount that grows with the angle.
#
# They are kept close to the middle because the square must actually be crossed
# by every cut, and it deliberately occupies only the middle third of the window
# so there is room to move the view about without any edge leaving the picture.
CUTS = (0.42, 0.5, 0.58)


def margins_at_every_cut(picture) -> tuple[list, float | None]:
    """Read the margins along all three cuts, and say how slanted the edges are.

    Returns the readings and the *slant*: how far the same side differs between
    one cut and another. Zero on a square drawing lined up with a square hole;
    it grows with any turn of the view, which is the fault a single cut through
    the middle cannot see.
    """
    readings = [margins_around_the_hole(picture, at=at) for at in CUTS]
    usable = [reading for reading in readings if reading.found]
    if len(usable) < 2:
        return readings, None
    slant = max(
        max(getattr(r, side) for r in usable) - min(getattr(r, side) for r in usable)
        for side in ("left", "right", "top", "bottom")
    )
    return readings, float(slant)


def where_the_drawing_sits(picture, at=0.5) -> dict:
    """How far the operator's own drawing is from the edge of the image.

    Used by the measurement that lets the parts of the sheet an operator is
    touching keep up with the mouse while the hole waits for the engine. The
    thing drawn is a rectangle sitting exactly on the edge of the imaged square,
    which is where a tile rectangle belongs, so any gap between the two is the
    misregistration an operator would see — measured on screen rather than
    worked out from what the page believes.

    Returns the widest gap found, in the photograph's own pixels, or ``None``
    when there was no drawing on screen to measure.
    """
    import numpy as np

    picture = np.asarray(picture)
    height, width = picture.shape[0], picture.shape[1]
    gaps = []
    for line, along in (
        (picture[int(height * at), :, :3], "across"),
        (picture[:, int(width * at), :3], "down"),
    ):
        found = read_the_line(line)
        if found.image_starts is None or not found.drawn_at:
            continue
        marks = np.asarray(found.drawn_at)
        # The drawing is two short runs of green, one on each edge of the square.
        # Each is matched with the edge it is nearest, and how far it is from it
        # is the sliver.
        for edge in (found.image_starts, found.image_ends):
            gaps.append(float(np.min(np.abs(marks - edge))))
    if not gaps:
        return {"found": False, "sliver": None}
    return {"found": True, "sliver": max(gaps)}


def only_the_whole_ones(readings, nominal: float, tolerance: float = 4.0) -> list:
    """The readings taken while the whole picture was on screen.

    On a sparse acquisition read from a slow disk, a great many frames are
    photographed while pieces of the picture are still on their way. In those the
    bright region is genuinely smaller than the imaged ground, and the band
    measured against it is genuinely wider — which is true, and is not a
    disagreement between the two layers.

    The two are told apart by adding opposite sides together. A displacement
    takes from one side exactly what it gives the other, so the pair still comes
    to twice the width the band was cut at. A picture that has not all arrived
    does not: the pair comes to more.

    So this keeps the readings where the pair still adds up, which are the ones
    that can say anything about registration, and the caller reports separately
    how many were set aside.
    """
    kept = []
    for reading in readings:
        if not reading.found:
            continue
        across = abs(reading.left + reading.right - 2 * nominal)
        down = abs(reading.top + reading.bottom - 2 * nominal)
        if across <= tolerance and down <= tolerance:
            kept.append(reading)
    return kept


def worst_drift(readings: list[Margins], nominal: float) -> dict:
    """How far each side ever strayed from the width it was cut at.

    ``nominal`` is how wide the band was designed to be, in the photograph's own
    pixels. The answer is one number per side, plus the worst unevenness seen
    within any single photograph — which is the number that matters most,
    because it cannot be explained away by the two layers having been
    photographed a moment apart.
    """
    usable = [reading for reading in readings if reading.found]
    closed = sum(1 for reading in readings if reading.closed)
    worst = {
        "samples": len(usable),
        "photographs": len(readings),
        # Frames where the band had closed altogether. See ``Line.closed``: these
        # are readings worse than the band was wide, not readings of nothing.
        "closed": closed,
    }
    if not usable:
        return worst
    for side in ("left", "right", "top", "bottom"):
        worst[side] = round(
            max(abs(getattr(r, side) - nominal) for r in usable), 1
        )
    worst["unevenness"] = round(max(r.unevenness for r in usable), 1)
    worst["widest_seen"] = {
        side: max(getattr(r, side) for r in usable)
        for side in ("left", "right", "top", "bottom")
    }
    worst["narrowest_seen"] = {
        side: min(getattr(r, side) for r in usable)
        for side in ("left", "right", "top", "bottom")
    }
    # What two opposite sides add up to, and why it is worth knowing.
    #
    # There are two quite different ways for the band to go uneven, and this
    # tells them apart. If the layer on top is drawn from a position the layer
    # underneath has not reached, the whole image is displaced: one side gains
    # exactly what the other loses, so the pair still adds up to twice the
    # width it was cut at. If instead the *picture* is incomplete — pieces still
    # on their way from a slow disk — the bright region is simply smaller, and
    # the pair adds up to more than it should.
    #
    # The distinction matters a great deal in practice. The first is a fault in
    # the arrangement; the second is an operator waiting for their data, which
    # every arrangement does.
    worst["opposite sides added up to"] = {
        "across": [
            round(min(r.left + r.right for r in usable), 1),
            round(max(r.left + r.right for r in usable), 1),
        ],
        "down": [
            round(min(r.top + r.bottom for r in usable), 1),
            round(max(r.top + r.bottom for r in usable), 1),
        ],
        "when whole and lined up, both stay at": 2 * nominal,
    }
    return worst

"""Choosing how one kind of acquisition should be written to disk.

A facility does not have one storage layout, and it should not pretend to. A
wide overview sweep, the detailed scans it leads to, a light-sheet volume and a
repeated timelapse all produce differently shaped data, and each is best written
differently. This module works out the answer for one of them.

The answer is settled **before** the run starts and then sealed. Once a position
has been published under a profile, changing the profile would mean the pixels
already on disk no longer match their own description, so an acquisition that
genuinely needs a different frame or a different chunking starts a new profile
rather than quietly reinterpreting what came before.

What actually gets chosen
-------------------------

Four numbers, and they answer to different masters.

**The frame** is what the camera or the scanner produces. Sometimes it is fixed
by the hardware, and sometimes — on a confocal, where the scan format is a
software setting — it can be asked for.

**The overlap** is how much neighbouring tiles share. It is honest microscope
time, so less is better, but it cannot go to zero: a stitcher needs the shared
strip as evidence of where the stage really went.

**The chunk** is the smallest piece of the file that can be read on its own. It
is what the viewer asks for, so a bigger chunk means fewer questions to fill a
screen. It is also what a seam has to line up with if the overview is to show a
tile's pixels without anyone copying them first.

**The shard** is how many chunks are bundled into one file. This exists purely
so that half a terabyte is not five million files, which is the difference
between a run you can move between machines and one you cannot. It has no effect
on where seams can fall, provided the viewer can be handed a single chunk from
inside a bundle.

Why nine chunks across
----------------------

There is one arrangement that comes out best at every scale, and it is worth
knowing why before reading the table.

The overview points at the positions' own pixels rather than copying them, and
it can only do that where the arithmetic lines up. Every tile lands at a whole
number of steps, so the *step* — the frame minus the overlap — is the number
that decides how far down the zoomed-out copies that pointing can reach. A step
that halves cleanly several times reaches far; one that does not reach at all
means every zoomed-out level has to be written instead, which costs disk and
costs time during the acquisition.

Make the frame **nine chunks** across and give **one chunk** to the overlap, and
the step is **eight chunks** — which halves cleanly three times. That gives an
overlap of 11.1%, comfortably at the low end of what is useful, and four levels
of pointing, at every scale:

===========  ======  ======  =========  ======  ========
instrument   frame   chunk   overlap    step    pointed
===========  ======  ======  =========  ======  ========
confocal     1152    128     128        1024    4
confocal     2304    256     256        2048    4
mesoSPIM     4608    512     512        4096    4
===========  ======  ======  =========  ======  ========

The round numbers are the trap. A 1024 or 2048 frame cannot do better than 25%
overlap — more than twice the microscope time — for *shallower* pointing than
1152 or 2304 manage at 11.1%. Where the format can be asked for,
:func:`a_kinder_frame` says so.

Frames that are not square
--------------------------

Plenty of instruments do not produce a square frame. Scientific cameras are
often wider than they are tall, and on a confocal the scan format is a software
setting that an operator may well set to something like 1152 by 2304. So a frame
may be given either as one number, meaning a square, or as a height and a width.

Nothing about the reasoning changes; it simply happens once per axis. A single
chunk size is chosen that divides both sides, and each side is then given its
own whole number of chunks of overlap, kept inside the same band. A 1152 by 2304
frame in 128-pixel chunks is nine chunks tall and eighteen across, with one chunk
of overlap on the short side and two on the long one — 11.1% either way, and the
same four levels of pointing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np

from .identity import name_for_a_profile
from .model import (
    AcquisitionProfile,
    FrozenMap,
    LevelGeometry,
    OverlapBand,
    ZmartLiveError,
)

__all__ = [
    "DEFAULTS",
    "AcquisitionDefaults",
    "Geometry",
    "a_kinder_frame",
    "choose_the_geometry",
    "plan_the_writing",
]


# ---------------------------------------------------------------------------
# The arithmetic
# ---------------------------------------------------------------------------


def _how_often_it_halves(number: int) -> int:
    """How many times ``number`` can be halved before it stops being even.

    This is the quantity that decides pointing depth. A step of 2048 halves
    eleven times; a step of 1792 halves only eight, and 1792 is 2048's
    neighbour. Small differences in a frame size therefore make large
    differences to how much has to be written rather than pointed at, which is
    the whole reason this module exists.
    """
    halvings = 0
    while number and number % 2 == 0:
        number //= 2
        halvings += 1
    return halvings


def _read_the_frame(frame: int | tuple[int, int]) -> tuple[int, int]:
    """Understand a frame given either as one number or as a height and a width.

    One number means a square frame, which is what most of this facility's
    instruments produce and what every earlier caller passed. A pair means a
    height and a width, in that order, matching the way image axes are named
    everywhere else in this package: ``y`` before ``x``.
    """
    if isinstance(frame, bool) or not isinstance(frame, (int, tuple, list)):
        raise ZmartLiveError(
            f"A frame is either one number, for a square frame, or a height and a "
            f"width; got {frame!r}."
        )
    sides = (int(frame), int(frame)) if isinstance(frame, int) else tuple(frame)
    if len(sides) != 2 or any(
        not isinstance(side, int) or isinstance(side, bool) for side in sides
    ):
        raise ZmartLiveError(
            f"A frame given as a pair has to hold exactly two whole numbers, the "
            f"height and then the width; got {frame!r}."
        )
    for side in sides:
        if side <= 0:
            raise ZmartLiveError(
                f"A frame has to hold at least one pixel on each side; got {frame!r}."
            )
    return sides[0], sides[1]


@dataclass(frozen=True)
class Geometry:
    """One complete answer: how big a frame, chunk, overlap and step to use.

    Everything is recorded per axis, as a height and a width in that order, so
    that a rectangular camera or scan format is described as honestly as a square
    one. For the ordinary square case there are shorthands — :attr:`frame`,
    :attr:`overlap`, :attr:`step` and :attr:`overlap_fraction` — that give the one
    number both axes share. They refuse to answer for a rectangle rather than
    quietly handing back one of the two sides, because a plausible wrong number
    is the thing that would actually cause harm here.
    """

    frame_shape: tuple[int, int]
    chunk: int
    overlap_shape: tuple[int, int]
    step_shape: tuple[int, int]
    pointed_levels: int
    kept_levels: int
    chunks_per_plane: int

    @property
    def height(self) -> int:
        """How tall the frame is, in pixels."""
        return self.frame_shape[0]

    @property
    def width(self) -> int:
        """How wide the frame is, in pixels."""
        return self.frame_shape[1]

    @property
    def is_square(self) -> bool:
        """True when both sides, and both overlaps, are the same."""
        return self.frame_shape[0] == self.frame_shape[1] and (
            self.overlap_shape[0] == self.overlap_shape[1]
        )

    def _one_number(self, name: str, values: tuple[int, int]) -> int:
        if not self.is_square:
            raise ZmartLiveError(
                f"This frame is {self.height} by {self.width} pixels with "
                f"{self.overlap_shape[0]} and {self.overlap_shape[1]} pixels of "
                f"overlap, so there is no single '{name}' to give. Ask for it per "
                f"axis instead: frame_shape, overlap_shape and step_shape each hold "
                f"the height first and the width second."
            )
        return values[0]

    @property
    def frame(self) -> int:
        """The frame size, for the ordinary square case."""
        return self._one_number("frame", self.frame_shape)

    @property
    def overlap(self) -> int:
        """The overlap, for the ordinary square case."""
        return self._one_number("overlap", self.overlap_shape)

    @property
    def step(self) -> int:
        """The distance between neighbouring tiles, for the square case."""
        return self._one_number("step", self.step_shape)

    @property
    def overlap_fractions(self) -> tuple[float, float]:
        """The overlap on each axis as a fraction of that side of the frame."""
        return (
            self.overlap_shape[0] / self.frame_shape[0],
            self.overlap_shape[1] / self.frame_shape[1],
        )

    @property
    def overlap_fraction(self) -> float:
        """The overlap as a fraction of the frame, which is what an operator says.

        Square frames only. A rectangle has one of these per axis, in
        :attr:`overlap_fractions`.
        """
        self._one_number("overlap_fraction", self.overlap_shape)
        return self.overlap_shape[0] / self.frame_shape[0]

    @property
    def written_levels(self) -> int:
        """How many of a tile's own zoom levels the overview cannot point at.

        These have to be built by reading the tile's pixels back and writing new
        ones, during the acquisition, which is the expensive kind of work. Zero
        is the goal.

        A run-wide overview will still build zoomed-out levels of its own beyond
        this, because the whole mosaic is far larger than any single tile and has
        to be navigable when fully zoomed out. Those are a fixed, modest cost.
        What this counts is the avoidable part.
        """
        return max(0, self.kept_levels - self.pointed_levels)

    def describe(self) -> str:
        """One line an operator can read, for a log or a report."""
        if self.is_square:
            shape = f"{self.frame} pixel frame"
            overlap = (
                f"{self.overlap} pixels of overlap "
                f"({self.overlap_fractions[0] * 100:.1f}%), stepping {self.step}"
            )
        else:
            shape = f"{self.height} by {self.width} pixel frame"
            overlap = (
                f"{self.overlap_shape[0]} and {self.overlap_shape[1]} pixels of overlap "
                f"({self.overlap_fractions[0] * 100:.1f}% and "
                f"{self.overlap_fractions[1] * 100:.1f}%), stepping "
                f"{self.step_shape[0]} and {self.step_shape[1]}"
            )
        return (
            f"{shape} in {self.chunk} pixel chunks, {overlap}; "
            f"{self.pointed_levels} zoom levels pointed at "
            f"and {self.written_levels} written"
        )


def _levels_a_position_keeps(shortest_side: int, chunk: int) -> int:
    """How many zoomed-out copies are worth keeping for one tile.

    Halving stops once a further copy would be smaller than a single chunk,
    because a copy smaller than the piece it is stored in wastes more than it
    saves. For a frame that is not square it is the *shorter* side that decides,
    since that is the side which runs out first.
    """
    kept, across = 1, shortest_side
    while across // 2 >= chunk:
        across //= 2
        kept += 1
    return kept


def _pointing_depth(side: int, overlap: int, chunk: int, kept: int) -> int:
    """How far down the zoomed-out copies the overview can point rather than copy.

    Every tile is trimmed the same way and lands at a whole number of steps, so
    the step is the only number that matters here. At the zoom level ``L``
    everything has to line up with ``chunk * 2**(L-1)``, so the answer is how
    many times the step divides by two after the chunk has been taken out of it.

    This is worked out one axis at a time. A frame that is not square can reach
    further on one axis than the other, and the answer for the tile as a whole is
    then the shallower of the two, because the seam has to line up on both.
    """
    step = side - overlap
    if step <= 0 or step % chunk:
        return 0
    return min(1 + _how_often_it_halves(step // chunk), kept)


def _overlaps_worth_trying(side: int, chunk: int, band: OverlapBand) -> list[int]:
    """Every whole number of chunks of overlap this band permits on one axis.

    Whole chunks, because a seam that falls inside a chunk cannot be pointed at:
    the viewer would have to be handed part of a piece of file, which is not
    something the format allows.
    """
    permitted = []
    for multiples in range(1, side // chunk):
        overlap = multiples * chunk
        fraction = overlap / side
        if fraction < band.permitted_fraction[0]:
            continue
        if fraction > band.permitted_fraction[1]:
            break
        permitted.append(overlap)
    return permitted


def choose_the_geometry(
    frame: int | tuple[int, int],
    *,
    band: OverlapBand,
    chunk_choices: tuple[int, ...] = (128, 144, 160, 192, 256, 288, 320, 384, 512),
    enough_depth: int = 3,
    suggest_a_better_frame: bool = True,
) -> Geometry:
    """Pick the chunk and overlap for a frame of a given size.

    ``frame`` is either one number, for the ordinary square frame, or a height
    and a width for an instrument whose frame is a rectangle. The reasoning is
    identical either way; it simply runs once per axis, and one chunk size is
    chosen that suits both.

    The order of preference encodes what each choice actually costs. First,
    enough pointing depth that the overview barely has to write anything —
    writing during an acquisition is the expensive mistake. Then the largest
    chunk, because that is the fewest questions the viewer has to ask to fill a
    screen. Then the least overlap, because overlap is time on the microscope.

    Raises :class:`~zmart_live.model.ZmartLiveError` when nothing in the
    permitted overlap band lines up at all, which happens for frames that are
    awkward numbers. The message says so plainly and suggests a frame that works.
    """
    height, width = _read_the_frame(frame)
    if enough_depth < 1:
        raise ZmartLiveError(
            f"Pointing depth is counted from one; got enough_depth={enough_depth}."
        )
    if not chunk_choices or any(chunk <= 0 for chunk in chunk_choices):
        raise ZmartLiveError(f"Every candidate chunk has to be positive; got {chunk_choices}.")
    best: tuple[tuple, Geometry] | None = None
    for chunk in chunk_choices:
        if height % chunk or width % chunk:
            continue  # a chunk has to divide both sides of the frame
        kept = _levels_a_position_keeps(min(height, width), chunk)
        for overlap_y in _overlaps_worth_trying(height, chunk, band):
            depth_y = _pointing_depth(height, overlap_y, chunk, kept)
            if not depth_y:
                continue
            for overlap_x in _overlaps_worth_trying(width, chunk, band):
                depth_x = _pointing_depth(width, overlap_x, chunk, kept)
                if not depth_x:
                    continue
                # The seam has to line up on both axes, so the tile as a whole
                # reaches only as far as its shallower axis does.
                depth = min(depth_y, depth_x)
                fractions = (overlap_y / height, overlap_x / width)
                # The order of these terms is the whole policy, so it is worth
                # saying why each sits where it does.
                #
                # Depth first, capped: writing zoom levels during an acquisition
                # is the expensive mistake, but past three levels what remains to
                # write is already tiny, so beyond that it should stop competing.
                #
                # Then whether the overlap is in the comfortable band, ahead of
                # chunk size. This is the one that matters most and is easiest to
                # get backwards. Overlap is time on the microscope — minutes of
                # somebody's experiment — while a bigger chunk buys milliseconds
                # in the viewer. A marginally larger chunk must never be allowed
                # to talk the run into imaging a quarter of every tile twice.
                #
                # Then the largest chunk, then the least overlap averaged over
                # the two axes, and finally — only ever as a tie-break — the more
                # even-handed of two answers that are otherwise identical.
                score = (
                    min(depth, enough_depth),
                    band.prefers(fractions[0]) and band.prefers(fractions[1]),
                    chunk,
                    -(fractions[0] + fractions[1]) / 2,
                    -abs(fractions[0] - fractions[1]),
                )
                candidate = Geometry(
                    frame_shape=(height, width),
                    chunk=chunk,
                    overlap_shape=(overlap_y, overlap_x),
                    step_shape=(height - overlap_y, width - overlap_x),
                    pointed_levels=depth,
                    kept_levels=kept,
                    chunks_per_plane=(height // chunk) * (width // chunk),
                )
                if best is None or score > best[0]:
                    best = (score, candidate)

    if best is None:
        # Asking for a suggestion means asking whether some other frame works,
        # which means choosing again. Turning it off here is what stops a frame
        # that cannot be helped from asking about itself for ever.
        kinder = a_kinder_frame((height, width), band) if suggest_a_better_frame else None
        if height == width:
            described = f"a {height} pixel frame"
            suggestion = f"A {kinder[0]} pixel frame" if kinder else ""
        else:
            described = f"a {height} by {width} pixel frame"
            suggestion = f"A {kinder[0]} by {kinder[1]} pixel frame" if kinder else ""
        raise ZmartLiveError(
            f"No chunk and overlap combination fits {described} while "
            f"keeping the overlap between "
            f"{band.permitted_fraction[0] * 100:.0f}% and "
            f"{band.permitted_fraction[1] * 100:.0f}%. "
            + (f"{suggestion} would work well, at 11.1% overlap. " if suggestion else "")
            + "If the frame cannot be changed, widen the permitted overlap band."
        )
    return best[1]


def _is_already_kind(frame: int, band: OverlapBand) -> bool:
    """True when this frame is nine chunks across, which is the ideal shape.

    Worked out rather than looked up in a list. A 1728 pixel frame is nine
    192-pixel chunks and behaves exactly as well as 2304 does, so telling its
    owner to change would be wrong.
    """
    try:
        geometry = choose_the_geometry(frame, band=band, suggest_a_better_frame=False)
    except ZmartLiveError:
        return False
    return geometry.frame == 9 * geometry.chunk


def _a_kinder_side(side: int, band: OverlapBand) -> int | None:
    """A better size for one axis, or ``None`` when this one is already fine."""
    if _is_already_kind(side, band):
        return None
    candidates = [
        9 * chunk
        for chunk in (64, 96, 128, 144, 160, 192, 256, 288, 320, 384, 512, 640)
        if _is_already_kind(9 * chunk, band)
    ]
    nearby = [size for size in candidates if 0.6 <= size / side <= 1.6]
    if not nearby:
        return None
    return min(nearby, key=lambda size: (abs(size - side), size))


def a_kinder_frame(
    frame: int | tuple[int, int], band: OverlapBand | None = None
) -> int | tuple[int, int] | None:
    """A frame size that would behave better, or ``None`` when this one is fine.

    The ideal shape is **nine chunks across**, which gives 11.1% overlap, four
    levels of pointing, and eighty-one chunks to a plane — all three at their
    best at once. Where the scan format is a software setting, as it is on a
    confocal, asking for one of these is the cheapest improvement available
    anywhere in this design, and it saves real minutes on the microscope rather
    than milliseconds in the viewer.

    Only suggests a size in the same ballpark. Proposing a 1152 pixel frame to
    somebody with a 5120 pixel camera helps nobody.

    Give it one number and it answers with one number. Give it a height and a
    width and it answers with a height and a width, considering each side on its
    own; if only one side could be improved the other is handed back unchanged.
    """
    height, width = _read_the_frame(frame)
    band = band or DEFAULTS["overview"].overlap_band
    if isinstance(frame, int):
        return _a_kinder_side(height, band)
    kinder_height = _a_kinder_side(height, band)
    kinder_width = _a_kinder_side(width, band)
    if kinder_height is None and kinder_width is None:
        return None
    return (kinder_height or height, kinder_width or width)


# ---------------------------------------------------------------------------
# What each kind of acquisition wants
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AcquisitionDefaults:
    """What one kind of acquisition wants, before the camera is known.

    These are the choices that belong to the *purpose* of the acquisition rather
    than to the instrument. Whether the tiles form a connected mosaic, how much
    overlap is worth paying for, whether a seamless overview is wanted at all,
    and how large the files should be.

    The instrument then supplies the frame, and :func:`plan_the_writing` puts the
    two together.
    """

    acquisition_type: str
    purpose: str
    topology: str
    overlap_band: OverlapBand
    wants_seamless: bool
    target_shard_bytes: int
    analysis_ownership: str = "midpoint"

    def with_overlap(self, low: float, high: float, aim: float) -> AcquisitionDefaults:
        """The same defaults with a different overlap band, for an unusual run."""
        return replace(
            self,
            overlap_band=OverlapBand(
                preferred_fraction=(low, min(high, low + 0.10)),
                permitted_fraction=(low, high),
                preferred_target=aim,
            ),
        )


def _band(low: float, high: float, aim: float) -> OverlapBand:
    return OverlapBand(
        preferred_fraction=(low, min(high, low + 0.10)),
        permitted_fraction=(low, high),
        preferred_target=aim,
    )


#: Sensible starting points for the kinds of acquisition this facility runs.
#:
#: None of these is binding. A run may take one and change any part of it before
#: it is sealed, and an acquisition type not listed here can simply be added.
#: They exist so that the ordinary case needs no decisions at all.
DEFAULTS: dict[str, AcquisitionDefaults] = {
    "overview": AcquisitionDefaults(
        acquisition_type="overview",
        purpose=(
            "The wide survey that finds the specimen and shows where everything "
            "is. Its tiles butt up against one another in a regular mosaic, and "
            "it is the view an operator spends most of their time looking at, so "
            "it should be quick to browse and cheap to overlap."
        ),
        topology="grid",
        overlap_band=_band(0.10, 0.25, 0.12),
        wants_seamless=True,
        target_shard_bytes=256 * 1024 * 1024,
    ),
    "targets": AcquisitionDefaults(
        acquisition_type="targets",
        purpose=(
            "The detailed scans of the places the overview picked out. These are "
            "usually scattered rather than adjacent, so they are separate "
            "positions rather than one connected mosaic, and there is no seam to "
            "place. Where a target is imaged as a small patch of several tiles, "
            "that patch is its own little mosaic."
        ),
        topology="independent",
        overlap_band=_band(0.10, 0.25, 0.12),
        wants_seamless=False,
        target_shard_bytes=256 * 1024 * 1024,
    ),
    "timelapse": AcquisitionDefaults(
        acquisition_type="timelapse",
        purpose=(
            "Positions revisited over and over. The arrangement never changes, so "
            "each new moment reuses the layout already agreed and only needs its "
            "own record saying it is complete. Files are kept smaller here "
            "because a moment should become visible soon after it is finished, "
            "and a large bundle has to be filled before it can be closed."
        ),
        topology="grid",
        overlap_band=_band(0.10, 0.25, 0.12),
        wants_seamless=True,
        target_shard_bytes=128 * 1024 * 1024,
    ),
    "mesospim": AcquisitionDefaults(
        acquisition_type="mesospim",
        purpose=(
            "Light-sheet volumes: very large in every direction, with a few "
            "colours and often several hundred planes. One position can be tens "
            "of gigabytes, so the file count is what decides whether the run can "
            "be moved between machines at all, and the bundles are made larger "
            "to suit."
        ),
        topology="grid",
        overlap_band=_band(0.10, 0.25, 0.12),
        wants_seamless=True,
        target_shard_bytes=512 * 1024 * 1024,
    ),
    "confocal": AcquisitionDefaults(
        acquisition_type="confocal",
        purpose=(
            "Point-scanning volumes: moderate in width, up to about a hundred "
            "planes, and often five to ten colours. The scan format is a software "
            "setting here rather than a property of a camera, which means the "
            "frame can be asked for — and asking for a kind one is the cheapest "
            "improvement available anywhere in this design."
        ),
        topology="grid",
        overlap_band=_band(0.10, 0.25, 0.12),
        wants_seamless=True,
        target_shard_bytes=256 * 1024 * 1024,
    ),
}


# ---------------------------------------------------------------------------
# Putting the two together
# ---------------------------------------------------------------------------


def _z_planes_per_shard(
    frame_shape: tuple[int, int], dtype: str, target_bytes: int, z_planes: int
) -> int:
    """How many planes to bundle into one file, to land near the wanted size.

    Sizing to the file rather than to a fixed number of planes is what keeps this
    sensible across the whole range of instruments. A confocal plane and a
    light-sheet plane differ by twenty-five times in size, so a fixed plane count
    would give tiny files on one and unmanageable ones on the other.
    """
    try:
        pixel_type = np.dtype(dtype)
    except (TypeError, ValueError) as why:
        raise ZmartLiveError(
            f"{dtype!r} is not a NumPy pixel dtype, so its storage size is unknown."
        ) from why
    if pixel_type.hasobject:
        raise ZmartLiveError(
            f"{dtype!r} stores Python objects rather than fixed-size pixel values "
            "and cannot be used for an OME-Zarr acquisition."
        )
    plane_bytes = frame_shape[0] * frame_shape[1] * pixel_type.itemsize
    wanted = max(1, round(target_bytes / plane_bytes))
    return max(1, min(wanted, z_planes))


def plan_the_writing(
    acquisition_type: str,
    *,
    frame: int | tuple[int, int],
    dtype: str = "uint16",
    z_planes: int = 1,
    channels: tuple[str, ...] = ("channel 0",),
    voxel_size: tuple[float, float, float] = (1.0, 1.0, 1.0),
    voxel_unit: str = "micrometer",
    readable_prefix: str | None = None,
    defaults: AcquisitionDefaults | None = None,
) -> tuple[AcquisitionProfile, Geometry]:
    """Work out, and seal, how one acquisition will be written.

    Give it the kind of acquisition and the shape the instrument produces, and it
    returns a profile ready to be stored with the run, along with the geometry it
    chose so that the reasoning can be shown to whoever is running the microscope.

    ``frame`` is one number for a square frame, or a height and a width for an
    instrument whose frame is a rectangle.

    ``z_planes`` and ``channels`` do not affect where seams fall or which zoom
    levels can be pointed at. They are recorded because they are part of what
    makes this acquisition the acquisition it is, and the depth is also what
    sizes the file bundles.

    The profile's name is worked out from everything the profile says, so two
    acquisitions that differ anywhere — in pixel type, in depth, in colours, in
    voxel size — can never end up sharing one. ``readable_prefix`` lets a run
    choose the human-readable beginning of that name; the fingerprint is appended
    either way, so choosing a prefix cannot cause a clash.

    The returned profile is sealed, but sealing it is only half the job. Store it
    with :func:`zmart_live.identity.store_the_profile`, or a position committed
    on Tuesday will name a description that no longer exists on Friday.
    """
    wanted = defaults or DEFAULTS.get(acquisition_type)
    if wanted is None:
        raise ZmartLiveError(
            f"There are no stored defaults for an acquisition called "
            f"'{acquisition_type}'. The kinds already described are "
            f"{', '.join(sorted(DEFAULTS))}. Either use one of those, or pass a "
            f"prepared AcquisitionDefaults of your own."
        )
    if wanted.acquisition_type != acquisition_type:
        raise ZmartLiveError(
            f"The supplied defaults describe {wanted.acquisition_type!r}, not the "
            f"requested acquisition type {acquisition_type!r}. Copy the defaults "
            "under the right type rather than sealing a misleading profile."
        )
    if z_planes <= 0:
        raise ZmartLiveError(f"A position has to contain at least one z plane; got {z_planes}.")
    if not channels or any(not str(channel).strip() for channel in channels):
        raise ZmartLiveError("An acquisition has to contain at least one named channel.")
    if len(set(channels)) != len(channels):
        raise ZmartLiveError(f"Channel names have to be unique; got {channels}.")
    if len(voxel_size) != 3 or any(size <= 0 or not math.isfinite(size) for size in voxel_size):
        raise ZmartLiveError(
            f"Voxel size must give finite, positive z, y and x values; got {voxel_size}."
        )
    if not voxel_unit:
        raise ZmartLiveError("Voxel size needs a unit, such as 'micrometer'.")
    if wanted.target_shard_bytes <= 0:
        raise ZmartLiveError(
            f"A target bundle size has to be positive; got {wanted.target_shard_bytes}."
        )

    height, width = _read_the_frame(frame)
    geometry = choose_the_geometry((height, width), band=wanted.overlap_band)

    levels = []
    for level in range(geometry.kept_levels):
        shrink = 2**level
        levels.append(
            LevelGeometry(
                level=level,
                downsampling={"z": 1, "y": shrink, "x": shrink},
                inner_chunk={
                    "z": 1,
                    "y": geometry.chunk,
                    "x": geometry.chunk,
                },
                shard=None,
                linkable=level < geometry.pointed_levels,
            )
        )

    # The bundle: one moment, one colour, the whole width and height of the
    # frame, and a slab of planes chosen to land near the wanted file size.
    #
    # Spanning the whole frame is what makes the file size predictable — nine
    # chunks by nine chunks is the entire tile — and it is why the slab can be
    # worked out from the plane size alone. Never across moments and never across
    # positions: each of those is a separate publication, and a bundle spanning
    # two of them would have to be rewritten after the first was already visible.
    slab = _z_planes_per_shard((height, width), dtype, wanted.target_shard_bytes, z_planes)
    levels = [
        replace(level, shard={"z": slab, "y": height, "x": width}) if level.level == 0 else level
        for level in levels
    ]

    overlap_y, overlap_x = geometry.overlap_shape
    # A placeholder name, only so that the profile can be built at all. It is
    # replaced immediately below by one worked out from the finished profile,
    # which is the only way a name can honestly cover what it names.
    described = AcquisitionProfile(
        profile_id="unnamed",
        acquisition_type=acquisition_type,
        axes=("t", "c", "z", "y", "x"),
        frame_shape={"z": z_planes, "y": height, "x": width},
        dtype=dtype,
        voxel_size=FrozenMap({"z": voxel_size[0], "y": voxel_size[1], "x": voxel_size[2]}),
        voxel_unit=voxel_unit,
        overlap_pixels={"y": overlap_y, "x": overlap_x},
        overlap_band=wanted.overlap_band,
        topology=wanted.topology,
        seamless_ownership="one_sided",
        analysis_ownership=wanted.analysis_ownership,
        analysis_halo={"y": overlap_y // 2, "x": overlap_x // 2},
        levels=tuple(levels),
        codecs=("bytes", "zstd"),
        channels=tuple(channels),
        sealed=True,
    )
    shape = f"{height}" if height == width else f"{height}x{width}"
    profile = replace(
        described,
        profile_id=name_for_a_profile(
            described,
            readable_prefix=readable_prefix or f"{acquisition_type}-{shape}-{geometry.chunk}",
        ),
    )
    return profile, geometry

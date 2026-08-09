"""Choose a strict, zero-copy storage plan for one acquisition type.

The camera frame, useful overlap, viewer request grid and filesystem behaviour
pull in different directions. This module searches those choices before a run
starts and seals the answer in an acquisition profile.

For every tiled axis and every power-of-two pyramid level, a valid plan requires
the frame, overlap and therefore the stage step to contain a whole number of
logical chunks. Equivalently, the chunk is a divisor of ``gcd(frame, overlap)``
at that level. This is stricter than merely allowing a short edge chunk: it is
what lets both views return an existing encoded position chunk byte-for-byte,
including the outermost row and column, without manufacturing view pixels.

Chunks may change between pyramid levels and between ``y`` and ``x``. That is
packaging, not resolution: image resolution still halves exactly at every level.
Shards then bundle many independently encoded chunks into a small number of
files. Sharding controls file count; it neither changes the seam arithmetic nor
allows half a chunk to be linked.

The optimizer returns a recommendation and its Pareto alternatives so an
operator can see an honest trade-off instead of a hidden fallback. If no strict
plan exists inside the acquisition's overlap band, planning stops with concrete
remedies. It never silently materializes pixels in ``views/``.
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
    "OptimizationReport",
    "a_kinder_frame",
    "choose_the_geometry",
    "optimize_the_geometry",
    "plan_the_writing",
]


# ---------------------------------------------------------------------------
# The arithmetic
# ---------------------------------------------------------------------------


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
    """One terminal-free, zero-copy answer for a camera format.

    Resolution always halves between levels. ``level_chunk_shapes`` may change
    independently because packaging is not resolution. Every chunk divides the
    complete frame, overlap and grid step at its own level, so every advertised
    view piece is an existing encoded position chunk.
    """

    frame_shape: tuple[int, int]
    overlap_shape: tuple[int, int]
    step_shape: tuple[int, int]
    level_chunk_shapes: tuple[tuple[int, int], ...]

    @property
    def height(self) -> int:
        return self.frame_shape[0]

    @property
    def width(self) -> int:
        return self.frame_shape[1]

    @property
    def is_square(self) -> bool:
        return self.frame_shape[0] == self.frame_shape[1] and (
            self.overlap_shape[0] == self.overlap_shape[1]
        )

    def _one_number(self, name: str, values: tuple[int, int]) -> int:
        if not self.is_square:
            raise ZmartLiveError(
                f"This frame is {self.height} by {self.width} pixels with "
                f"{self.overlap_shape[0]} and {self.overlap_shape[1]} pixels of "
                f"overlap, so there is no single '{name}' to give. Ask for it per "
                "axis instead."
            )
        return values[0]

    @property
    def frame(self) -> int:
        return self._one_number("frame", self.frame_shape)

    @property
    def overlap(self) -> int:
        return self._one_number("overlap", self.overlap_shape)

    @property
    def step(self) -> int:
        return self._one_number("step", self.step_shape)

    @property
    def overlap_fractions(self) -> tuple[float, float]:
        return (
            self.overlap_shape[0] / self.frame_shape[0],
            self.overlap_shape[1] / self.frame_shape[1],
        )

    @property
    def overlap_fraction(self) -> float:
        self._one_number("overlap_fraction", self.overlap_shape)
        return self.overlap_shape[0] / self.frame_shape[0]

    @property
    def kept_levels(self) -> int:
        return len(self.level_chunk_shapes)

    @property
    def pointed_levels(self) -> int:
        return self.kept_levels

    @property
    def written_levels(self) -> int:
        return 0

    @property
    def chunk_shape(self) -> tuple[int, int]:
        return self.level_chunk_shapes[0]

    @property
    def chunk(self) -> int:
        y, x = self.chunk_shape
        if y != x:
            raise ZmartLiveError(
                f"This format uses a {y} by {x} full-resolution chunk, so there "
                "is no single chunk number. Ask for chunk_shape instead."
            )
        return y

    @property
    def chunks_per_level(self) -> tuple[int, ...]:
        return tuple(
            (self.height // (2**level) // chunk_y)
            * (self.width // (2**level) // chunk_x)
            for level, (chunk_y, chunk_x) in enumerate(self.level_chunk_shapes)
        )

    @property
    def chunks_per_plane(self) -> int:
        return self.chunks_per_level[0]

    @property
    def chunks_across_by_level(self) -> tuple[tuple[int, int], ...]:
        return tuple(
            (
                self.height // (2**level) // chunk_y,
                self.width // (2**level) // chunk_x,
            )
            for level, (chunk_y, chunk_x) in enumerate(self.level_chunk_shapes)
        )

    @property
    def acquisition_multiplier(self) -> float:
        return (self.height * self.width) / (self.step_shape[0] * self.step_shape[1])

    def describe(self) -> str:
        if self.is_square:
            shape = f"{self.frame} pixel frame"
            overlap = (
                f"{self.overlap} pixels of overlap "
                f"({self.overlap_fraction * 100:.1f}%), stepping {self.step}"
            )
        else:
            shape = f"{self.height} by {self.width} pixel frame"
            overlap = (
                f"{self.overlap_shape[0]} and {self.overlap_shape[1]} pixels of "
                f"overlap ({self.overlap_fractions[0] * 100:.1f}% and "
                f"{self.overlap_fractions[1] * 100:.1f}%)"
            )
        chunks = ", ".join(f"{y}x{x}" for y, x in self.level_chunk_shapes)
        return (
            f"{shape}, {overlap}; power-of-two levels use chunks [{chunks}], "
            "all directly linked and none written into a view"
        )


@dataclass(frozen=True)
class OptimizationReport:
    """The recommended plan and its non-dominated alternatives."""

    recommended: Geometry
    alternatives: tuple[Geometry, ...]
    candidates_considered: int


@dataclass(frozen=True)
class _AxisChoice:
    side: int
    overlap: int
    chunks: tuple[int, ...]

    @property
    def fraction(self) -> float:
        return self.overlap / self.side

    @property
    def counts(self) -> tuple[int, ...]:
        return tuple(
            self.side // (2**level) // chunk
            for level, chunk in enumerate(self.chunks)
        )


def _divisors(number: int) -> tuple[int, ...]:
    low: list[int] = []
    high: list[int] = []
    for candidate in range(1, math.isqrt(number) + 1):
        if number % candidate:
            continue
        low.append(candidate)
        paired = number // candidate
        if paired != candidate:
            high.append(paired)
    return tuple((*low, *reversed(high)))


def _axis_choices(
    side: int,
    band: OverlapBand,
    *,
    pyramid_levels: int,
    minimum_chunk: int,
    maximum_chunk: int,
    allowed_chunks: frozenset[int] | None,
) -> tuple[_AxisChoice, ...]:
    deepest = 2 ** (pyramid_levels - 1)
    if side % deepest:
        raise ZmartLiveError(
            f"A {side}-pixel frame cannot be halved exactly through "
            f"{pyramid_levels} pyramid levels. Its deepest level requires "
            f"division by {deepest}; use fewer levels or another camera format."
        )
    low = math.ceil(side * band.permitted_fraction[0])
    high = math.floor(side * band.permitted_fraction[1])
    first = low + (-low % deepest)
    choices: list[_AxisChoice] = []
    for overlap in range(first, high + 1, deepest):
        chunks: list[int] = []
        for level in range(pyramid_levels):
            factor = 2**level
            common = math.gcd(side // factor, overlap // factor)
            permitted = [
                divisor
                for divisor in _divisors(common)
                if minimum_chunk <= divisor <= maximum_chunk
                and (allowed_chunks is None or divisor in allowed_chunks)
            ]
            if not permitted:
                break
            chunks.append(max(permitted))
        if len(chunks) == pyramid_levels:
            choices.append(_AxisChoice(side, overlap, tuple(chunks)))

    frontier = []
    for candidate in choices:
        dominated = any(
            other.fraction <= candidate.fraction
            and all(
                other_count <= candidate_count
                for other_count, candidate_count in zip(
                    other.counts, candidate.counts, strict=True
                )
            )
            and (
                other.fraction < candidate.fraction
                or other.counts != candidate.counts
            )
            for other in choices
        )
        if not dominated:
            frontier.append(candidate)
    return tuple(frontier)


def _geometry_is_dominated(candidate: Geometry, other: Geometry) -> bool:
    return (
        other.acquisition_multiplier <= candidate.acquisition_multiplier
        and all(
            other_count <= candidate_count
            for other_count, candidate_count in zip(
                other.chunks_per_level, candidate.chunks_per_level, strict=True
            )
        )
        and (
            other.acquisition_multiplier < candidate.acquisition_multiplier
            or other.chunks_per_level != candidate.chunks_per_level
        )
    )


def optimize_the_geometry(
    frame: int | tuple[int, int],
    *,
    band: OverlapBand,
    pyramid_levels: int = 4,
    minimum_chunk: int = 8,
    maximum_chunk: int = 1024,
    target_chunks_across: int = 12,
    chunk_choices: tuple[int, ...] | None = None,
) -> OptimizationReport:
    """Enumerate strict zero-copy plans and return their Pareto frontier."""
    height, width = _read_the_frame(frame)
    if pyramid_levels < 1:
        raise ZmartLiveError(
            f"A pyramid needs at least its full-resolution level; got "
            f"{pyramid_levels}."
        )
    if minimum_chunk < 1 or maximum_chunk < minimum_chunk:
        raise ZmartLiveError(
            f"Chunk limits must be positive and ordered; got {minimum_chunk} to "
            f"{maximum_chunk}."
        )
    if target_chunks_across < 1:
        raise ZmartLiveError(
            f"The viewer target must allow at least one chunk across; got "
            f"{target_chunks_across}."
        )
    allowed = None if chunk_choices is None else frozenset(chunk_choices)
    if allowed is not None and (not allowed or any(size < 1 for size in allowed)):
        raise ZmartLiveError(
            f"Every explicitly allowed chunk must be positive; got {chunk_choices}."
        )

    y_choices = _axis_choices(
        height,
        band,
        pyramid_levels=pyramid_levels,
        minimum_chunk=minimum_chunk,
        maximum_chunk=maximum_chunk,
        allowed_chunks=allowed,
    )
    x_choices = (
        y_choices
        if height == width
        else _axis_choices(
            width,
            band,
            pyramid_levels=pyramid_levels,
            minimum_chunk=minimum_chunk,
            maximum_chunk=maximum_chunk,
            allowed_chunks=allowed,
        )
    )
    if height == width:
        pairs = tuple((choice, choice) for choice in y_choices)
    else:
        pairs = tuple(
            (y_choice, x_choice)
            for y_choice in y_choices
            for x_choice in x_choices
        )
    candidates = tuple(
        Geometry(
            frame_shape=(height, width),
            overlap_shape=(y_choice.overlap, x_choice.overlap),
            step_shape=(height - y_choice.overlap, width - x_choice.overlap),
            level_chunk_shapes=tuple(
                (y_choice.chunks[level], x_choice.chunks[level])
                for level in range(pyramid_levels)
            ),
        )
        for y_choice, x_choice in pairs
    )
    if not candidates:
        raise ZmartLiveError(
            f"No overlap between {band.permitted_fraction[0]:.1%} and "
            f"{band.permitted_fraction[1]:.1%} gives the {height} by {width} "
            f"format {pyramid_levels} exactly halved, zero-copy levels with "
            f"chunks between {minimum_chunk} and {maximum_chunk} pixels. Reduce "
            "the number of levels, permit a smaller chunk, widen the overlap "
            "band, or choose another configurable camera format."
        )

    frontier = tuple(
        candidate
        for candidate in candidates
        if not any(
            _geometry_is_dominated(candidate, other)
            for other in candidates
            if other is not candidate
        )
    )

    def recommendation(geometry: Geometry) -> tuple:
        meets_target = all(
            y <= target_chunks_across and x <= target_chunks_across
            for y, x in geometry.chunks_across_by_level
        )
        fractions = geometry.overlap_fractions
        return (
            not meets_target,
            not all(band.prefers(value) for value in fractions),
            sum(band.distance_from_target(value) for value in fractions),
            geometry.acquisition_multiplier,
            max(geometry.chunks_per_level),
            geometry.overlap_shape,
        )

    ordered = tuple(sorted(frontier, key=recommendation))
    return OptimizationReport(
        recommended=ordered[0],
        alternatives=ordered,
        candidates_considered=len(candidates),
    )


def choose_the_geometry(
    frame: int | tuple[int, int],
    *,
    band: OverlapBand,
    chunk_choices: tuple[int, ...] | None = None,
    enough_depth: int | None = None,
    pyramid_levels: int = 4,
    minimum_chunk: int = 8,
    maximum_chunk: int = 1024,
    target_chunks_across: int = 12,
    suggest_a_better_frame: bool = True,
) -> Geometry:
    """Return the recommended strict plan; use the optimizer for alternatives."""
    del suggest_a_better_frame
    levels = pyramid_levels if enough_depth is None else enough_depth
    return optimize_the_geometry(
        frame,
        band=band,
        pyramid_levels=levels,
        minimum_chunk=minimum_chunk,
        maximum_chunk=maximum_chunk,
        target_chunks_across=target_chunks_across,
        chunk_choices=chunk_choices,
    ).recommended


def _is_already_kind(frame: int, band: OverlapBand) -> bool:
    """True when the strict optimizer gives this format at most eight chunks."""
    try:
        geometry = choose_the_geometry(frame, band=band, suggest_a_better_frame=False)
    except ZmartLiveError:
        return False
    return all(max(shape) <= 8 for shape in geometry.chunks_across_by_level)


def _a_kinder_side(side: int, band: OverlapBand) -> int | None:
    """A better size for one axis, or ``None`` when this one is already fine."""
    if _is_already_kind(side, band):
        return None
    candidates = [
        chunks * unit
        for chunks in range(6, 10)
        for unit in (64, 96, 128, 144, 160, 192, 256, 288, 320, 384, 512, 640)
        if _is_already_kind(chunks * unit, band)
    ]
    nearby = [size for size in candidates if 0.6 <= size / side <= 1.6]
    if not nearby:
        return None
    return min(nearby, key=lambda size: (abs(size - side), size))


def a_kinder_frame(
    frame: int | tuple[int, int], band: OverlapBand | None = None
) -> int | tuple[int, int] | None:
    """A nearby format meeting the request target, or ``None`` when this one does.

    Exact zero-copy planning now adapts chunks at every level, so round camera
    formats are no longer rejected merely because they are not nine chunks wide.
    A different format is suggested only when it materially lowers the logical
    request grid while retaining the same strict overlap rules.

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
    pyramid_levels: int = 4
    minimum_chunk: int = 8
    maximum_chunk: int = 1024
    target_chunks_across: int = 12
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
        overlap_band=_band(0.10, 0.20, 0.125),
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
        overlap_band=_band(0.10, 0.20, 0.125),
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
        overlap_band=_band(0.10, 0.20, 0.125),
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
        overlap_band=_band(0.10, 0.20, 0.125),
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
        overlap_band=_band(0.10, 0.20, 0.125),
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
    geometry = choose_the_geometry(
        (height, width),
        band=wanted.overlap_band,
        pyramid_levels=wanted.pyramid_levels,
        minimum_chunk=wanted.minimum_chunk,
        maximum_chunk=wanted.maximum_chunk,
        target_chunks_across=wanted.target_chunks_across,
    )

    levels = []
    for level, (chunk_y, chunk_x) in enumerate(geometry.level_chunk_shapes):
        shrink = 2**level
        level_shape = (height // shrink, width // shrink)
        slab = _z_planes_per_shard(
            level_shape,
            dtype,
            wanted.target_shard_bytes,
            z_planes,
        )
        levels.append(
            LevelGeometry(
                level=level,
                downsampling={"z": 1, "y": shrink, "x": shrink},
                inner_chunk={
                    "z": 1,
                    "y": chunk_y,
                    "x": chunk_x,
                },
                shard={
                    "z": slab,
                    "y": level_shape[0],
                    "x": level_shape[1],
                },
                linkable=True,
            )
        )

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
    chunk_y, chunk_x = geometry.chunk_shape
    chunk_label = str(chunk_y) if chunk_y == chunk_x else f"{chunk_y}x{chunk_x}"
    profile = replace(
        described,
        profile_id=name_for_a_profile(
            described,
            readable_prefix=(
                readable_prefix or f"{acquisition_type}-{shape}-{chunk_label}"
            ),
        ),
    )
    return profile, geometry

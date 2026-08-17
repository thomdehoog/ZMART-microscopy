"""The vocabulary the live-publication machinery shares.

Every module in :mod:`zmart_live` describes the same run, so they all have to
agree on what a *position*, an *overlap*, a *region* and a *revision* are. This
file holds those shared descriptions and nothing else. It makes no decisions and
performs no work; it is the set of words the rest of the package speaks in.

Keeping the vocabulary in one place matters more here than it usually would.
The viewer and the analysis code both look at the same run at the same time, and
the whole point of the design recorded in
``docs/design/live-position-timepoint-publication-decisions.md`` is that they see
*exactly* the same thing. If the viewer and the analysis each carried their own
idea of where a tile sits, they would eventually disagree, and a disagreement of
that kind shows up as a cell counted twice or a stripe of specimen that belongs
to nobody.

Three habits run through everything below.

**Regions are half-open.** A region that runs from 0 to 100 contains pixel 0 and
stops just before pixel 100. Two regions written this way, 0-to-100 and
100-to-200, touch without overlapping, and no pixel is claimed twice or missed.
Written the other way, with both ends included, pixel 100 would belong to both
neighbours, and in an experiment that means one nucleus counted twice.

**Records cannot be edited once made.** These objects are *frozen*: once one is
created its contents can never change. That sounds inconvenient, and it is
occasionally, but it buys the property the design depends on. When a published
result says "I used layout revision 7", revision 7 still means today what it
meant when the result was written. If layouts could be edited in place, a tile
arriving later could quietly change what an already published measurement was
supposed to mean.

**Names have to be safe to write into a path.** A position, a run, a profile and
a mosaic component all become folder names on disk, so every record below checks
its identifiers as it is built. A position called ``../../escaped`` is not an
exotic thing to worry about; it is what a mistyped position list looks like, and
written straight into a folder name it would put that position's images outside
the run entirely. :func:`check_the_name_is_safe` says what is allowed, and why.

The words themselves
--------------------

:class:`Interval` and :class:`Box`
    Where something is, along one axis and along several.

:class:`OverlapBand`
    How much neighbouring tiles are asked to overlap — a range of acceptable
    values rather than one exact number, because the exact number has to fit the
    camera and the chunk size as well.

:class:`LevelGeometry` and :class:`AcquisitionProfile`
    How one kind of acquisition is written to disk: frame size, overlap, the
    zoomed-out copies, and how the file is split up internally.

:class:`GridCell`, :class:`PositionPlacement` and :class:`MosaicComponent`
    Where each tile sits in the mosaic, and which regions of it belong to it.

:class:`SceneLayoutRevision`
    A complete, dated snapshot of the mosaic as it actually turned out.

:class:`CommitEvent`
    The single record that makes a finished position or timepoint visible.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "ANALYSIS_OWNERSHIP_POLICIES",
    "EVENT_TYPES",
    "RESERVED_DEVICE_NAMES",
    "TOPOLOGIES",
    "AcquisitionProfile",
    "Box",
    "CommitEvent",
    "FrozenMap",
    "GridCell",
    "Interval",
    "LevelGeometry",
    "MosaicComponent",
    "OverlapBand",
    "PositionPlacement",
    "SceneLayoutRevision",
    "ZmartLiveError",
    "check_the_name_is_safe",
    "is_a_safe_name",
]


class ZmartLiveError(Exception):
    """Something about the run's description does not hold together.

    Every refusal in this package raises this, or something derived from it, so
    that a caller can catch the whole family in one place. The message is always
    written to be read by the person at the microscope: it says what was
    expected, what arrived instead, and — where there is one — what to do about
    it.
    """


# ---------------------------------------------------------------------------
# What a name is allowed to be
# ---------------------------------------------------------------------------

#: The names Windows keeps for its own hardware. They date from MS-DOS and they
#: are still live: a file called ``CON`` talks to the console instead of the
#: disk, ``PRN`` and ``LPT1`` go to a printer port, and ``NUL`` throws away
#: everything written to it. A folder cannot be created under any of them at all.
#: Because a microscope computer in this facility is usually a Windows machine,
#: a position named after one of these would fail there and nowhere else, which
#: is the worst kind of fault to discover.
RESERVED_DEVICE_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{digit}" for digit in range(1, 10)}
    | {f"lpt{digit}" for digit in range(1, 10)}
)

#: Letters, digits, and the three punctuation marks that are safe everywhere.
#: Everything else — slashes, backslashes, colons, spaces, quotes, control
#: characters — either separates one folder from the next on some operating
#: system or means something special to a shell.
_ALLOWED_IN_A_NAME = re.compile(r"^[A-Za-z0-9._-]+$")

# Replacements are stored as ``<position>.generation-<number>.ome.zarr``.  If a
# caller could choose that suffix for an ordinary position, replacing ``sample``
# would target the canonical store of ``sample.generation-1`` and could delete it
# before copying the replacement.  Case-insensitive filesystems make spelling
# variants collide too, so the internal namespace is reserved without regard to
# case.
_GENERATION_SUFFIX = re.compile(r"\.generation-\d+$", re.IGNORECASE)


def is_a_safe_name(name: object) -> bool:
    """True when ``name`` can be used as a single folder or file name anywhere.

    This is the quiet form of :func:`check_the_name_is_safe`, for the occasions
    when a caller wants to look before it leaps rather than catch a refusal.
    """
    try:
        check_the_name_is_safe(name, what="name")
    except ZmartLiveError:
        return False
    return True


def check_the_name_is_safe(name: object, *, what: str = "identifier") -> str:
    """Refuse any identifier that would not be a plain, harmless folder name.

    Positions, runs, profiles and mosaic components all end up as folder and file
    names on disk. That makes their identifiers more than labels: a position
    called ``../../escaped`` does not merely look odd, it writes that position's
    images two directories above the run, outside the run folder entirely, where
    nobody will think to look for them and where they may quietly overwrite
    something else.

    So a name has to be one plain word: letters, digits, and the three
    punctuation marks ``-``, ``_`` and ``.``. No slashes or backslashes, because
    those separate one folder from the next. No colons, because Windows reads
    them as a drive letter or as a hidden second stream inside a file. Nothing
    that is only dots, because ``.`` and ``..`` mean "here" and "one level up".
    No leading or trailing spaces or dots, because Windows silently removes them
    and two names that looked different then turn out to be the same folder. And
    none of the reserved device names listed in :data:`RESERVED_DEVICE_NAMES`.

    ``what`` names the kind of thing being checked, so that the refusal can say
    "position" or "run" rather than something abstract.

    Returns the name unchanged when it is safe, so that it can be used inline
    where a value is being stored. Raises :class:`ZmartLiveError` otherwise, with
    a message that shows the offending name and says what is allowed instead.
    """
    advice = (
        "A name has to be one plain word made of letters, digits, '-', '_' and "
        "'.', with no folder separators, no leading or trailing dots or spaces, "
        "not ending in the internal '.generation-N' replacement suffix, "
        "and not one of the names Windows reserves for its own hardware "
        "(CON, PRN, AUX, NUL, COM1-9, LPT1-9)."
    )
    # Only so that the message reads as a sentence: "an acquisition profile"
    # rather than "a acquisition profile".
    a = "an" if what[:1].lower() in "aeiou" else "a"
    if not isinstance(name, str):
        raise ZmartLiveError(
            f"{a.capitalize()} {what} has to be named in text; got {type(name).__name__}. {advice}"
        )
    if not name:
        raise ZmartLiveError(f"{a.capitalize()} {what} cannot be left unnamed. {advice}")
    if len(name) > 120:
        raise ZmartLiveError(
            f"This {what} name is {len(name)} characters long, which is more than "
            f"many filesystems will accept once it is joined to a run folder. Keep "
            f"it to 120 characters or fewer."
        )
    if not _ALLOWED_IN_A_NAME.match(name):
        raise ZmartLiveError(f"'{name}' cannot be used as {a} {what} name. {advice}")
    if set(name) == {"."}:
        raise ZmartLiveError(
            f"'{name}' cannot be used as {a} {what} name, because a name made only "
            f"of dots means 'this folder' or 'the folder above' rather than a place "
            f"of its own. {advice}"
        )
    if name[0] in " ." or name[-1] in " .":
        raise ZmartLiveError(
            f"'{name}' cannot be used as {a} {what} name, because Windows quietly "
            f"strips spaces and dots from the ends of a name, so two identifiers "
            f"that look different here would become the same folder there. {advice}"
        )
    if name.split(".")[0].lower() in RESERVED_DEVICE_NAMES:
        raise ZmartLiveError(
            f"'{name}' cannot be used as {a} {what} name, because Windows reserves "
            f"that name for a piece of hardware. Opening it would talk to the "
            f"console or a printer port rather than write to the disk. {advice}"
        )
    if _GENERATION_SUFFIX.search(name):
        raise ZmartLiveError(
            f"'{name}' cannot be used as {a} {what} name, because names ending in "
            "'.generation-N' are reserved for immutable replacement stores. An "
            "ordinary position with that name and generation N of the name before "
            "it would otherwise be the same folder, so replacing one could erase "
            f"the other. {advice}"
        )
    return name


# ---------------------------------------------------------------------------
# A dictionary that cannot be edited afterwards
# ---------------------------------------------------------------------------


class FrozenMap(Mapping):
    """A lookup table that can be read but never changed after it is made.

    Ordinary Python dictionaries can be edited by anyone holding them, which is
    usually what you want and is exactly what we must avoid here. A published
    layout is handed to the viewer and to the analysis at the same time, and
    neither should be able to alter what the other sees. Wrapping the table this
    way makes that impossible rather than merely impolite.

    It behaves like a dictionary for reading — ``m["x"]``, ``for key in m``,
    ``len(m)``, ``m.get(...)`` all work as expected — and simply has no methods
    for changing anything.
    """

    __slots__ = ("_items", "_hash")

    def __init__(self, items: Mapping | Iterable[tuple] | None = None) -> None:
        source = dict(items) if items is not None else {}
        self._items: dict = source
        self._hash: int | None = None

    def __getitem__(self, key):  # noqa: D105 - obvious from the class docstring
        return self._items[key]

    def __iter__(self) -> Iterator:  # noqa: D105
        return iter(self._items)

    def __len__(self) -> int:  # noqa: D105
        return len(self._items)

    def __repr__(self) -> str:  # noqa: D105
        return f"FrozenMap({self._items!r})"

    def __hash__(self) -> int:  # noqa: D105
        if self._hash is None:
            self._hash = hash(frozenset(self._items.items()))
        return self._hash

    def __eq__(self, other: object) -> bool:  # noqa: D105
        if isinstance(other, FrozenMap):
            return self._items == other._items
        if isinstance(other, Mapping):
            return self._items == dict(other)
        return NotImplemented

    def as_dict(self) -> dict:
        """Return an ordinary, editable copy — useful when writing JSON."""
        return dict(self._items)


def _frozen_axis_map(values: Mapping[str, int] | None) -> FrozenMap:
    """Turn an axis-keyed table of whole numbers into an unchangeable one."""
    if values is None:
        return FrozenMap()
    if isinstance(values, FrozenMap):
        return values
    return FrozenMap({str(axis): int(size) for axis, size in values.items()})


def rounded_up(size: int, step: int) -> int:
    """How large an extent is at a coarser level: divided, rounding UP.

    A stack 13 planes deep, halved, is 7 planes deep — the seventh coarse
    plane is only half-filled, but the specimen in plane 13 lives there,
    and rounding down to 6 would cut it off the picture. The same holds
    across and down the image. Every place that turns a full-resolution
    extent into a zoomed-out level's extent divides through this one
    function, so the writer, the gateway and the viewer can never quietly
    disagree about how large the world is (the depth chapter's rounding
    gate, ``test_level_depths_round_up_everywhere``).
    """
    return -(-int(size) // int(step))


# ---------------------------------------------------------------------------
# Where something is
# ---------------------------------------------------------------------------


@dataclass(frozen=True, order=True)
class Interval:
    """A stretch along one axis: from ``start`` up to, but not including, ``stop``.

    Both numbers are pixel positions counted from the beginning of that axis. An
    ``Interval(0, 2048)`` covers the first 2048 pixels; the pixel numbered 2048
    is the first one *outside* it. This is the half-open convention explained at
    the top of the file, and it is what lets two neighbouring stretches meet
    exactly, with no pixel shared and none skipped.
    """

    start: int
    stop: int

    def __post_init__(self) -> None:
        if self.stop < self.start:
            raise ZmartLiveError(
                f"An interval cannot end before it begins: start={self.start}, "
                f"stop={self.stop}. If this came from a crop calculation, the "
                f"overlap is probably wider than the frame it is being cut from."
            )

    @property
    def length(self) -> int:
        """How many pixels this stretch covers."""
        return self.stop - self.start

    @property
    def is_empty(self) -> bool:
        """True when the stretch covers no pixels at all."""
        return self.stop == self.start

    def contains(self, position: int) -> bool:
        """True when ``position`` falls inside, counting the start but not the stop."""
        return self.start <= position < self.stop

    def intersection(self, other: Interval) -> Interval:
        """The stretch the two have in common, which may be empty."""
        start = max(self.start, other.start)
        stop = min(self.stop, other.stop)
        if stop < start:
            return Interval(start, start)
        return Interval(start, stop)

    def overlaps(self, other: Interval) -> bool:
        """True when the two share at least one pixel."""
        return not self.intersection(other).is_empty

    def shifted(self, by: int) -> Interval:
        """The same stretch moved along the axis by ``by`` pixels."""
        return Interval(self.start + by, self.stop + by)

    def to_json(self) -> list[int]:
        """A plain ``[start, stop]`` pair, for writing to disk."""
        return [self.start, self.stop]

    @classmethod
    def from_json(cls, value: Iterable[int]) -> Interval:
        """Read back what :meth:`to_json` wrote."""
        start, stop = value
        return cls(int(start), int(stop))


@dataclass(frozen=True)
class Box:
    """A region described by one :class:`Interval` per axis.

    Axes are named rather than numbered — ``"y"``, ``"x"``, ``"z"`` and so on —
    because a region that says ``{"y": 0-2048, "x": 256-2304}`` can be read at a
    glance, whereas one that says ``[[0, 2048], [256, 2304]]`` requires the
    reader to remember which way round the axes go. Axis order is a real source
    of mistakes in image analysis, and naming them removes the question.

    A box may name only the axes it cares about. The regions used for ownership
    normally describe the tiled axes alone, because a tile's overlap with its
    neighbours is a matter of where it sits on the stage and has nothing to do
    with which colour channel or which moment in time is being looked at.
    """

    intervals: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        if not isinstance(self.intervals, FrozenMap):
            object.__setattr__(self, "intervals", FrozenMap(self.intervals))

    @classmethod
    def of(cls, **axes: tuple[int, int] | Interval) -> Box:
        """Build a box from keyword arguments, as in ``Box.of(y=(0, 100), x=(0, 100))``."""
        built = {}
        for axis, value in axes.items():
            built[axis] = value if isinstance(value, Interval) else Interval(*value)
        return cls(FrozenMap(built))

    @property
    def axes(self) -> tuple[str, ...]:
        """The axis names this box describes, in a settled order."""
        return tuple(sorted(self.intervals))

    def __getitem__(self, axis: str) -> Interval:
        return self.intervals[axis]

    def get(self, axis: str, default: Interval | None = None) -> Interval | None:
        """The stretch along ``axis``, or ``default`` when this box does not describe it."""
        return self.intervals.get(axis, default)

    @property
    def is_empty(self) -> bool:
        """True when the region has no volume, because at least one axis is empty."""
        if not self.intervals:
            return True
        return any(interval.is_empty for interval in self.intervals.values())

    def voxel_count(self) -> int:
        """How many voxels the region holds, multiplying its axes together."""
        if self.is_empty:
            return 0
        total = 1
        for interval in self.intervals.values():
            total *= interval.length
        return total

    def contains_point(self, point: Mapping[str, int]) -> bool:
        """True when ``point`` lies inside, on every axis this box describes.

        Axes the box does not mention are not tested, so a box describing only
        ``y`` and ``x`` will accept a point that also carries a ``z``. This is
        deliberate: an ownership region usually speaks about the stage plane and
        should not accidentally reject an object because of its depth.
        """
        for axis, interval in self.intervals.items():
            if axis not in point:
                return False
            if not interval.contains(int(point[axis])):
                return False
        return True

    def intersection(self, other: Box) -> Box:
        """The region the two boxes share, on the axes they both describe.

        An axis named by only one of them is carried through unchanged, on the
        reasoning that a box which says nothing about an axis is not restricting
        it.
        """
        merged: dict[str, Interval] = {}
        for axis in set(self.intervals) | set(other.intervals):
            mine = self.intervals.get(axis)
            theirs = other.intervals.get(axis)
            if mine is None:
                merged[axis] = theirs
            elif theirs is None:
                merged[axis] = mine
            else:
                merged[axis] = mine.intersection(theirs)
        return Box(FrozenMap(merged))

    def overlaps(self, other: Box) -> bool:
        """True when the two regions share any voxel at all."""
        return not self.intersection(other).is_empty

    def shifted(self, by: Mapping[str, int]) -> Box:
        """The same region moved, by the number of pixels given for each axis."""
        moved = {
            axis: interval.shifted(int(by.get(axis, 0)))
            for axis, interval in self.intervals.items()
        }
        return Box(FrozenMap(moved))

    def to_json(self) -> dict[str, list[int]]:
        """A plain dictionary of ``axis -> [start, stop]``, for writing to disk."""
        return {axis: interval.to_json() for axis, interval in sorted(self.intervals.items())}

    @classmethod
    def from_json(cls, value: Mapping[str, Iterable[int]]) -> Box:
        """Read back what :meth:`to_json` wrote."""
        return cls(FrozenMap({axis: Interval.from_json(pair) for axis, pair in value.items()}))


# ---------------------------------------------------------------------------
# How much neighbours overlap
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OverlapBand:
    """How much neighbouring tiles should share, expressed as a range.

    Overlap is usually described as a percentage — "we image with fifteen per
    cent overlap" — but a single percentage cannot always be honoured. The
    overlap has to be a whole number of pixels, and for the viewer to show the
    mosaic without copying any data, that number also has to be a whole multiple
    of the chunk the file is written in. Insisting on exactly 15% would often
    make those conditions impossible to satisfy at once.

    So overlap is recorded as an intention with room to move: a preferred range,
    a wider permitted range, and a target to aim at. Values such as 12.5% or 21%
    are perfectly good answers and are not rejected merely for being unround.

    Fractions are of the frame: ``overlap_pixels / frame_pixels`` on that axis.
    """

    preferred_fraction: tuple[float, float]
    permitted_fraction: tuple[float, float]
    preferred_target: float

    def __post_init__(self) -> None:
        for name, (low, high) in (
            ("preferred_fraction", self.preferred_fraction),
            ("permitted_fraction", self.permitted_fraction),
        ):
            if not 0.0 <= low <= high < 1.0:
                raise ZmartLiveError(
                    f"{name} must be a range between 0 and 1 with the smaller value "
                    f"first; got {low} to {high}. An overlap of a whole frame or more "
                    f"would mean the neighbouring tile adds nothing new."
                )
        permitted_low, permitted_high = self.permitted_fraction
        preferred_low, preferred_high = self.preferred_fraction
        if preferred_low < permitted_low or preferred_high > permitted_high:
            raise ZmartLiveError(
                f"The preferred overlap range ({preferred_low} to {preferred_high}) "
                f"reaches outside the permitted range ({permitted_low} to "
                f"{permitted_high}). Preferred values should be the comfortable "
                f"middle of what is allowed, not wider than it."
            )
        if not permitted_low <= self.preferred_target <= permitted_high:
            raise ZmartLiveError(
                f"The overlap target {self.preferred_target} lies outside the "
                f"permitted range {permitted_low} to {permitted_high}."
            )

    def permits(self, fraction: float) -> bool:
        """True when ``fraction`` is an overlap this acquisition would accept."""
        low, high = self.permitted_fraction
        return low <= fraction <= high

    def prefers(self, fraction: float) -> bool:
        """True when ``fraction`` sits in the comfortable middle of the range."""
        low, high = self.preferred_fraction
        return low <= fraction <= high

    def distance_from_target(self, fraction: float) -> float:
        """How far ``fraction`` is from the value the acquisition would rather have."""
        return abs(fraction - self.preferred_target)

    def to_json(self) -> dict[str, Any]:
        """A plain dictionary, for writing to disk."""
        return {
            "preferred_fraction": list(self.preferred_fraction),
            "permitted_fraction": list(self.permitted_fraction),
            "preferred_target": self.preferred_target,
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> OverlapBand:
        """Read back what :meth:`to_json` wrote."""
        return cls(
            preferred_fraction=tuple(float(v) for v in value["preferred_fraction"]),  # type: ignore[arg-type]
            permitted_fraction=tuple(float(v) for v in value["permitted_fraction"]),  # type: ignore[arg-type]
            preferred_target=float(value["preferred_target"]),
        )


# ---------------------------------------------------------------------------
# How one kind of acquisition is written to disk
# ---------------------------------------------------------------------------

#: The two shapes a run's positions can be arranged in. ``"independent"`` means
#: the positions are separate places on the slide with no expectation that they
#: touch. ``"grid"`` means they form a regular mosaic whose neighbours overlap on
#: purpose, which is what makes the seamless quick-look view possible.
TOPOLOGIES = ("independent", "grid")

#: Where the boundary sits for deciding which tile's *measurements* count. The
#: picture needs no such policy — positions are drawn whole and a later arrival
#: simply lands on top — but a detected object must still be counted exactly
#: once, and a model usually wants specimen on both sides of the boundary it is
#: asked to judge.
ANALYSIS_OWNERSHIP_POLICIES = ("one_sided", "midpoint")

#: The kinds of thing that can be recorded as having become visible.
EVENT_TYPES = ("position_committed", "timepoint_committed", "position_replaced")


@dataclass(frozen=True)
class LevelGeometry:
    """One rung of the zoomed-out ladder, and how it is stored.

    Microscopy images are kept at several magnifications at once — the full
    resolution, then half, then a quarter, and so on — so that zooming out does
    not mean reading every pixel of a very large image. Each of those rungs is a
    *level*, and level 0 is the full-resolution one.

    Three things about a level matter to this package.

    ``inner_chunk`` is the smallest piece the file can be read in. It is the unit
    the viewer asks for, and it is what a seam has to line up with if the viewer
    is to show a tile's pixels without anyone copying them first.

    ``shard`` is how many of those pieces are bundled into a single file on disk.
    Bundling exists purely to keep the number of files manageable; it changes
    nothing about where seams can fall.

    ``linkable`` says whether the seamless view may point straight at this
    level's chunks. A level can only be pointed at when its complete frame,
    overlap and grid step all contain whole chunks at that magnification. This
    deliberately rules out short terminal chunks: both the seamless and raw
    views must be able to return an existing encoded position chunk unchanged.
    """

    level: int
    downsampling: FrozenMap
    inner_chunk: FrozenMap
    shard: FrozenMap | None = None
    linkable: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "downsampling", _frozen_axis_map(self.downsampling))
        object.__setattr__(self, "inner_chunk", _frozen_axis_map(self.inner_chunk))
        if self.shard is not None:
            object.__setattr__(self, "shard", _frozen_axis_map(self.shard))
        if self.level < 0:
            raise ZmartLiveError(f"Pyramid levels are numbered from zero; got {self.level}.")
        for axis, factor in self.downsampling.items():
            if factor <= 0:
                raise ZmartLiveError(
                    f"The downsampling on axis '{axis}' at level {self.level} is "
                    f"{factor}, but a scale factor has to be positive."
                )
        for axis, size in self.inner_chunk.items():
            if size <= 0:
                raise ZmartLiveError(
                    f"The chunk size on axis '{axis}' at level {self.level} is {size}, "
                    f"but a chunk has to hold at least one pixel."
                )
        if self.shard is not None:
            for axis, shard_size in self.shard.items():
                if shard_size <= 0:
                    raise ZmartLiveError(
                        f"The file bundle on axis '{axis}' at level {self.level} is "
                        f"{shard_size}, but a bundle has to hold at least one pixel."
                    )
                chunk_size = self.inner_chunk.get(axis)
                if chunk_size is None:
                    raise ZmartLiveError(
                        f"Level {self.level} bundles axis '{axis}' into files of "
                        f"{shard_size}, but does not say how large a chunk is on "
                        f"that axis."
                    )
                if shard_size % chunk_size != 0:
                    raise ZmartLiveError(
                        f"On axis '{axis}' at level {self.level}, the file bundle is "
                        f"{shard_size} pixels but the chunk inside it is {chunk_size}. "
                        f"A bundle has to hold a whole number of chunks, so "
                        f"{shard_size} must divide evenly by {chunk_size}."
                    )

    def to_json(self) -> dict[str, Any]:
        """A plain dictionary, for writing to disk."""
        return {
            "level": self.level,
            "downsampling": self.downsampling.as_dict(),
            "inner_chunk": self.inner_chunk.as_dict(),
            "shard": None if self.shard is None else self.shard.as_dict(),
            "linkable": self.linkable,
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> LevelGeometry:
        """Read back what :meth:`to_json` wrote."""
        return cls(
            level=int(value["level"]),
            downsampling=value["downsampling"],
            inner_chunk=value["inner_chunk"],
            shard=value.get("shard"),
            linkable=bool(value.get("linkable", False)),
        )


@dataclass(frozen=True)
class AcquisitionProfile:
    """Everything about how one kind of acquisition is written, settled in advance.

    A microscope facility does not have one storage layout; it has several. An
    overview sweep, a detailed target scan, a light-sheet stack and a confocal
    series all produce differently shaped data and are best written differently.
    A profile is the answer for one of those kinds, and it is agreed *before* the
    run starts and never changed while the run is going.

    That last part is the important one. Once data has been published under a
    profile, changing the profile would mean the pixels already on disk no longer
    mean what their description says. So a profile is sealed: if the acquisition
    genuinely needs a different frame size or a different chunking partway
    through, that starts a new acquisition instance with its own profile rather
    than quietly reinterpreting what came before.

    ``analysis_halo`` is how much specimen, in pixels, a model wants to see
    beyond the region it is being asked to judge. It comes from the analysis, not
    from the viewer, which is why it is recorded here rather than assumed.

    ``channels`` names the colours the acquisition records. It belongs here
    rather than being left to the commit records because two acquisitions that
    image different colours are genuinely different acquisitions, and a profile
    that did not mention them could not tell the two apart.
    """

    profile_id: str
    acquisition_type: str
    axes: tuple[str, ...]
    frame_shape: FrozenMap
    dtype: str
    voxel_size: FrozenMap = field(default_factory=FrozenMap)
    voxel_unit: str = "micrometer"
    overlap_pixels: FrozenMap = field(default_factory=FrozenMap)
    overlap_band: OverlapBand | None = None
    topology: str = "independent"
    analysis_ownership: str = "midpoint"
    analysis_halo: FrozenMap = field(default_factory=FrozenMap)
    levels: tuple[LevelGeometry, ...] = ()
    codecs: tuple[str, ...] = ()
    channels: tuple[str, ...] = ()
    sealed: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "axes", tuple(self.axes))
        object.__setattr__(self, "frame_shape", _frozen_axis_map(self.frame_shape))
        object.__setattr__(
            self,
            "voxel_size",
            FrozenMap({str(axis): float(size) for axis, size in self.voxel_size.items()}),
        )
        object.__setattr__(self, "overlap_pixels", _frozen_axis_map(self.overlap_pixels))
        object.__setattr__(self, "analysis_halo", _frozen_axis_map(self.analysis_halo))
        object.__setattr__(self, "levels", tuple(self.levels))
        object.__setattr__(self, "codecs", tuple(self.codecs))
        object.__setattr__(self, "channels", tuple(self.channels))

        if not self.profile_id or not self.acquisition_type:
            raise ZmartLiveError(
                "An acquisition profile has to name both its identity and its type."
            )
        # Both of these become folder names when the profile is stored beside the
        # run, so both have to be plain, harmless words.
        check_the_name_is_safe(self.profile_id, what="acquisition profile")
        check_the_name_is_safe(self.acquisition_type, what="acquisition type")
        if len(set(self.channels)) != len(self.channels) or any(
            not str(channel).strip() for channel in self.channels
        ):
            raise ZmartLiveError(
                f"An acquisition's channel names have to be present and unique; got "
                f"{self.channels}."
            )
        if not self.axes or len(self.axes) != len(set(self.axes)):
            raise ZmartLiveError(f"Axis names must be present and unique; got {self.axes}.")
        if not self.dtype:
            raise ZmartLiveError("An acquisition profile has to name its pixel dtype.")
        if self.topology not in TOPOLOGIES:
            raise ZmartLiveError(
                f"'{self.topology}' is not a known arrangement of positions. "
                f"Use one of {', '.join(TOPOLOGIES)}."
            )
        if self.analysis_ownership not in ANALYSIS_OWNERSHIP_POLICIES:
            raise ZmartLiveError(
                f"'{self.analysis_ownership}' is not a known way of deciding which "
                f"tile's measurements count. Use one of "
                f"{', '.join(ANALYSIS_OWNERSHIP_POLICIES)}."
            )
        for axis in self.frame_shape:
            if axis not in self.axes:
                raise ZmartLiveError(
                    f"The frame gives a size for axis '{axis}', which is not in the "
                    f"declared axis order {self.axes}."
                )
        for axis, frame in self.frame_shape.items():
            if frame <= 0:
                raise ZmartLiveError(
                    f"The frame size on axis '{axis}' is {frame}, but a frame has "
                    "to hold at least one pixel."
                )
        for axis, size in self.voxel_size.items():
            if axis not in self.axes or size <= 0 or not math.isfinite(size):
                raise ZmartLiveError(
                    f"The voxel size on axis '{axis}' is {size}. It has to be "
                    "finite, positive, and belong to the declared axis order."
                )
        if not self.voxel_unit:
            raise ZmartLiveError("Voxel size needs a unit, such as 'micrometer'.")
        for axis, halo in self.analysis_halo.items():
            if axis not in self.axes or halo < 0:
                raise ZmartLiveError(
                    f"The analysis halo on axis '{axis}' is {halo}. It has to be "
                    "non-negative and belong to the declared axis order."
                )
        for axis, overlap in self.overlap_pixels.items():
            frame = self.frame_shape.get(axis)
            if frame is None:
                raise ZmartLiveError(
                    f"The profile declares {overlap} pixels of overlap on axis "
                    f"'{axis}', but never says how large the frame is on that axis."
                )
            if overlap < 0:
                raise ZmartLiveError(
                    f"Overlap cannot be negative; axis '{axis}' says {overlap}. A gap "
                    f"between tiles is described by a wider grid step, not by a "
                    f"negative overlap."
                )
            if overlap >= frame:
                raise ZmartLiveError(
                    f"Axis '{axis}' overlaps by {overlap} pixels out of a {frame}-pixel "
                    f"frame. A tile that shares its whole width with its neighbour "
                    f"shows nothing new."
                )
            if self.overlap_band is not None and not self.overlap_band.permits(overlap / frame):
                raise ZmartLiveError(
                    f"Axis '{axis}' uses {overlap} pixels of overlap in a "
                    f"{frame}-pixel frame ({overlap / frame:.1%}), outside the "
                    "permitted overlap band recorded by this same profile."
                )
        seen_levels = [level.level for level in self.levels]
        if seen_levels != list(range(len(seen_levels))):
            raise ZmartLiveError(
                f"The zoomed-out levels should be listed once each, in order, "
                f"starting at zero; got {seen_levels}."
            )
        linkable = [level.level for level in self.levels if level.linkable]
        if linkable != list(range(len(linkable))):
            raise ZmartLiveError(
                f"Directly linked pyramid levels have to form one prefix starting "
                f"at zero; got {linkable}. A view cannot skip a level and resume "
                "pointing further down."
            )
        for level in self.levels:
            if not level.linkable:
                continue
            for axis in self.tiled_axes:
                factor = level.downsampling.get(axis)
                chunk = level.inner_chunk.get(axis)
                if factor is None or chunk is None:
                    raise ZmartLiveError(
                        f"Linkable level {level.level} does not describe both the "
                        f"scale and inner chunk on tiled axis '{axis}'."
                    )
                frame = self.frame_shape[axis]
                overlap = self.overlap_pixels[axis]
                step = self.grid_step(axis)
                if frame % factor or overlap % factor or step % factor:
                    raise ZmartLiveError(
                        f"Level {level.level} is marked linkable on axis '{axis}', "
                        f"but its frame ({frame}), overlap ({overlap}) and grid "
                        f"step ({step}) do not all divide exactly by its "
                        f"{factor}x downsampling. A linked view cannot round a "
                        "seam or a camera edge to the nearest coarse pixel."
                    )
                frame_at_level = frame // factor
                overlap_at_level = overlap // factor
                step_at_level = step // factor
                if any(
                    size % chunk
                    for size in (
                        frame_at_level,
                        overlap_at_level,
                        step_at_level,
                    )
                ):
                    raise ZmartLiveError(
                        f"Level {level.level} is marked linkable on axis '{axis}', "
                        f"but at {factor}x downsampling its frame, overlap and "
                        f"step are {frame_at_level}, {overlap_at_level} and "
                        f"{step_at_level} pixels, and its chunk is {chunk}. Every "
                        "one of those lengths must contain whole chunks; otherwise "
                        "the view would need a partial source chunk at a seam or "
                        "camera edge."
                    )

    @property
    def tiled_axes(self) -> tuple[str, ...]:
        """The axes along which tiles are laid out beside one another.

        These are the axes with a declared overlap. For an ordinary mosaic they
        are ``y`` and ``x``; the colour channel and the timepoint are not tiled,
        which is why ownership never speaks about them.
        """
        return tuple(axis for axis in self.axes if self.overlap_pixels.get(axis, 0) > 0)

    def level(self, index: int) -> LevelGeometry:
        """The geometry of one zoom level, by its number."""
        for level in self.levels:
            if level.level == index:
                return level
        raise ZmartLiveError(
            f"This profile has no level {index}. It describes levels "
            f"{[lvl.level for lvl in self.levels]}."
        )

    @property
    def linkable_levels(self) -> tuple[int, ...]:
        """The zoom levels the seamless view may point straight at."""
        return tuple(level.level for level in self.levels if level.linkable)

    def overlap_fraction(self, axis: str) -> float:
        """The overlap on ``axis`` as a fraction of the frame, as a plain number."""
        frame = self.frame_shape.get(axis)
        if not frame:
            return 0.0
        return self.overlap_pixels.get(axis, 0) / frame

    def grid_step(self, axis: str) -> int:
        """How far the stage moves between neighbouring tiles on ``axis``.

        This is the frame minus the overlap: the amount of genuinely new
        specimen each further tile adds.
        """
        return self.frame_shape[axis] - self.overlap_pixels.get(axis, 0)

    def to_json(self) -> dict[str, Any]:
        """A plain dictionary, for writing to disk."""
        return {
            "profile_id": self.profile_id,
            "acquisition_type": self.acquisition_type,
            "axes": list(self.axes),
            "frame_shape": self.frame_shape.as_dict(),
            "dtype": self.dtype,
            "voxel_size": self.voxel_size.as_dict()
            if isinstance(self.voxel_size, FrozenMap)
            else dict(self.voxel_size),
            "voxel_unit": self.voxel_unit,
            "overlap_pixels": self.overlap_pixels.as_dict(),
            "overlap_band": None if self.overlap_band is None else self.overlap_band.to_json(),
            "topology": self.topology,
            "analysis_ownership": self.analysis_ownership,
            "analysis_halo": self.analysis_halo.as_dict(),
            "levels": [level.to_json() for level in self.levels],
            "codecs": list(self.codecs),
            "channels": list(self.channels),
            "sealed": self.sealed,
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> AcquisitionProfile:
        """Read back what :meth:`to_json` wrote."""
        band = value.get("overlap_band")
        return cls(
            profile_id=value["profile_id"],
            acquisition_type=value["acquisition_type"],
            axes=tuple(value["axes"]),
            frame_shape=value["frame_shape"],
            dtype=value["dtype"],
            voxel_size=FrozenMap(value.get("voxel_size", {})),
            voxel_unit=value.get("voxel_unit", "micrometer"),
            overlap_pixels=value.get("overlap_pixels", {}),
            overlap_band=None if band is None else OverlapBand.from_json(band),
            topology=value.get("topology", "independent"),
            analysis_ownership=value.get("analysis_ownership", "midpoint"),
            analysis_halo=value.get("analysis_halo", {}),
            levels=tuple(LevelGeometry.from_json(lvl) for lvl in value.get("levels", ())),
            codecs=tuple(value.get("codecs", ())),
            channels=tuple(value.get("channels", ())),
            sealed=bool(value.get("sealed", True)),
        )


# ---------------------------------------------------------------------------
# Where each tile sits, and what belongs to it
# ---------------------------------------------------------------------------


@dataclass(frozen=True, order=True)
class GridCell:
    """Which square of the mosaic a tile occupies, counted in whole tiles.

    Row 0, column 0 is the first tile. Row 1 is one step down the specimen and
    column 1 is one step across, where a step is the frame minus the overlap. The
    numbers are not stage coordinates and not pixels: they are simply the tile's
    place in the pattern, and that is exactly what makes the seam rule work no
    matter which order the tiles happen to be acquired in.
    """

    row: int
    column: int

    def neighbours(self) -> tuple[GridCell, ...]:
        """The four cells sharing an edge with this one: up, down, left, right.

        Diagonals are deliberately absent. Two tiles touching only at a corner do
        not overlap along any edge, so neither can crop against the other, and a
        mosaic held together only by corners is not one connected mosaic.
        """
        return (
            GridCell(self.row - 1, self.column),
            GridCell(self.row + 1, self.column),
            GridCell(self.row, self.column - 1),
            GridCell(self.row, self.column + 1),
        )

    def to_json(self) -> list[int]:
        """A plain ``[row, column]`` pair, for writing to disk."""
        return [self.row, self.column]

    @classmethod
    def from_json(cls, value: Iterable[int]) -> GridCell:
        """Read back what :meth:`to_json` wrote."""
        row, column = value
        return cls(int(row), int(column))


@dataclass(frozen=True)
class PositionPlacement:
    """One tile: where it sits, and which parts of it are its own responsibility.

    The regions are written down for every tile rather than worked out again by
    each piece of software that needs them. Both are in the tile's *own* pixel
    coordinates at full resolution:
    ``(0, 0)`` is that tile's top-left corner, not the run's.

    The picture itself records no region at all: a tile is drawn whole, and
    where two tiles cover the same ground the one committed later lands on top.
    The regions kept here are the **analysis** boundaries.

    ``analysis_input_roi``
        What a model is given to look at — normally the whole tile, overlap
        included. The overlap is not waste here; it is the context that lets the
        model judge an object sitting near the edge.

    ``analysis_core_roi``
        The part of the tile whose *results* count. An object is kept once, by
        whichever tile owns the place the object sits in. This boundary is
        allowed to sit somewhere different from the visual seam, and usually
        should, so that both neighbours have specimen on either side of it.

    ``origin`` places the tile in the run's shared coordinates, so that a region
    expressed in tile pixels can be turned into a place on the specimen.
    """

    position_id: str
    component_id: str
    cell: GridCell
    origin: FrozenMap
    analysis_input_roi: Box
    analysis_core_roi: Box
    neighbours: FrozenMap = field(default_factory=FrozenMap)
    on_outer_boundary: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        object.__setattr__(self, "origin", _frozen_axis_map(self.origin))
        if not isinstance(self.neighbours, FrozenMap):
            object.__setattr__(self, "neighbours", FrozenMap(self.neighbours))
        if not isinstance(self.on_outer_boundary, FrozenMap):
            object.__setattr__(self, "on_outer_boundary", FrozenMap(self.on_outer_boundary))
        # A tile's name becomes the folder its image is written into, so an
        # identifier that could climb out of the run folder is refused here,
        # before any pixels are written rather than after.
        check_the_name_is_safe(self.position_id, what="position")
        check_the_name_is_safe(self.component_id, what="mosaic component")

    def frame_roi_in_run(self) -> Box:
        """The whole recorded frame, expressed in the run's shared coordinates.

        This is the ground the tile covers on the specimen — the region its
        pixels are drawn over, and the region a later arrival would take back.
        It is the analysis input region shifted into place, because what a
        model is given to look at is exactly the whole recorded frame.
        """
        return self.analysis_input_roi.shifted(self.origin)

    def core_roi_in_run(self) -> Box:
        """The owned part of this tile, expressed in the run's shared coordinates."""
        return self.analysis_core_roi.shifted(self.origin)

    def owns_point_in_run(self, point: Mapping[str, int]) -> bool:
        """True when a place on the specimen falls in this tile's owned region.

        This is the question asked of every detected object exactly once. Because
        the owned regions are half-open and never overlap, exactly one tile in a
        complete mosaic answers yes.
        """
        return self.core_roi_in_run().contains_point(point)

    def to_json(self) -> dict[str, Any]:
        """A plain dictionary, for writing to disk."""
        return {
            "position_id": self.position_id,
            "component_id": self.component_id,
            "cell": self.cell.to_json(),
            "origin": self.origin.as_dict(),
            "analysis_input_roi": self.analysis_input_roi.to_json(),
            "analysis_core_roi": self.analysis_core_roi.to_json(),
            "neighbours": {
                str(side): position for side, position in sorted(self.neighbours.items())
            },
            "on_outer_boundary": {
                str(side): bool(flag) for side, flag in sorted(self.on_outer_boundary.items())
            },
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> PositionPlacement:
        """Read back what :meth:`to_json` wrote."""
        return cls(
            position_id=value["position_id"],
            component_id=value["component_id"],
            cell=GridCell.from_json(value["cell"]),
            origin=value["origin"],
            analysis_input_roi=Box.from_json(value["analysis_input_roi"]),
            analysis_core_roi=Box.from_json(value["analysis_core_roi"]),
            neighbours=FrozenMap(value.get("neighbours", {})),
            on_outer_boundary=FrozenMap(value.get("on_outer_boundary", {})),
        )


@dataclass(frozen=True)
class MosaicComponent:
    """A group of tiles that genuinely form one connected mosaic.

    A smart experiment rarely images one neat rectangle. It sweeps an overview,
    picks out a handful of interesting places, and images a small patch around
    each. Each of those patches is its own component: connected within itself,
    and with no expectation of touching the others.

    Saying so explicitly is what keeps the seam rule honest. Two tiles from
    different patches are not neighbours no matter how close their stage
    coordinates happen to be, so neither crops against the other, and an isolated
    single target is simply a component with one tile in it rather than an
    awkward exception inside somebody else's grid.
    """

    component_id: str
    profile_id: str
    cells: FrozenMap = field(default_factory=FrozenMap)
    complete: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.cells, FrozenMap):
            object.__setattr__(self, "cells", FrozenMap(self.cells))
        check_the_name_is_safe(self.component_id, what="mosaic component")
        # A component may be worked out from the grid alone, before anybody has
        # said which profile it belongs to, so an unattributed one is allowed.
        # Any name that *is* given still has to be safe.
        if self.profile_id:
            check_the_name_is_safe(self.profile_id, what="acquisition profile")
        seen_component_names: dict[str, str] = {}
        for position_id in self.cells.values():
            check_the_name_is_safe(position_id, what="position")
            disk_name = position_id.casefold()
            if disk_name in seen_component_names:
                raise ZmartLiveError(
                    f"Positions {seen_component_names[disk_name]!r} and "
                    f"{position_id!r} "
                    "differ only by letter case and would be the same folder on "
                    "a Windows microscope computer."
                )
            seen_component_names[disk_name] = position_id

    def position_at(self, cell: GridCell) -> str | None:
        """Which tile occupies ``cell``, or ``None`` when nothing has been placed there."""
        return self.cells.get(cell)

    def occupied_cells(self) -> tuple[GridCell, ...]:
        """Every cell that holds a tile, in a settled order."""
        return tuple(sorted(self.cells))

    def bounding_cells(self) -> tuple[GridCell, GridCell]:
        """The top-left and bottom-right corners of the rectangle enclosing the mosaic."""
        cells = self.occupied_cells()
        if not cells:
            raise ZmartLiveError(
                f"Mosaic component '{self.component_id}' holds no tiles yet, so it has "
                f"no extent to describe."
            )
        rows = [cell.row for cell in cells]
        columns = [cell.column for cell in cells]
        return GridCell(min(rows), min(columns)), GridCell(max(rows), max(columns))

    def to_json(self) -> dict[str, Any]:
        """A plain dictionary, for writing to disk."""
        return {
            "component_id": self.component_id,
            "profile_id": self.profile_id,
            "cells": [
                {"cell": cell.to_json(), "position_id": self.cells[cell]}
                for cell in self.occupied_cells()
            ],
            "complete": self.complete,
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> MosaicComponent:
        """Read back what :meth:`to_json` wrote."""
        cells = {
            GridCell.from_json(entry["cell"]): entry["position_id"] for entry in value["cells"]
        }
        return cls(
            component_id=value["component_id"],
            profile_id=value["profile_id"],
            cells=FrozenMap(cells),
            complete=bool(value.get("complete", False)),
        )


# ---------------------------------------------------------------------------
# The mosaic as it actually turned out, and the record that publishes it
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SceneLayoutRevision:
    """A dated snapshot of where the run's tiles ended up and who owns what.

    The profile says what the run *intends* to do. This says what it has actually
    done so far: which tiles exist, where each one landed, which neighbours it
    turned out to have, and the exact regions each one owns. It is the document
    an analysis result points back at when it says which tile a measurement
    belongs to.

    Snapshots are numbered and never edited. When a new tile arrives and changes
    the shape of the mosaic, that produces revision 8; revision 7 goes on meaning
    what it always meant. A measurement published against revision 7 therefore
    stays correct even though the run has moved on, and a tile arriving later can
    never quietly take ownership of something already counted.

    A timepoint added to tiles that are already in place does *not* need a new
    snapshot, because nothing about the arrangement changed. It reuses this one
    and gets its own commit record instead.
    """

    revision: int
    schema_version: str
    run_id: str
    acquisition_type: str
    profile_id: str
    positions: tuple[PositionPlacement, ...] = ()
    components: tuple[MosaicComponent, ...] = ()
    analysis_ownership: str = "midpoint"
    analysis_halo: FrozenMap = field(default_factory=FrozenMap)
    rounding_convention: str = "extra_pixel_to_lower_index"
    created_at: str = ""
    final: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "positions", tuple(self.positions))
        object.__setattr__(self, "components", tuple(self.components))
        object.__setattr__(self, "analysis_halo", _frozen_axis_map(self.analysis_halo))
        if self.revision < 0:
            raise ZmartLiveError(f"Layout revisions start at zero; got {self.revision}.")
        check_the_name_is_safe(self.run_id, what="run")
        check_the_name_is_safe(self.acquisition_type, what="acquisition type")
        check_the_name_is_safe(self.profile_id, what="acquisition profile")
        placed: dict[str, PositionPlacement] = {}
        seen_layout_names: dict[str, str] = {}
        for placement in self.positions:
            if placement.position_id in placed:
                raise ZmartLiveError(
                    f"Position '{placement.position_id}' appears twice in layout "
                    f"revision {self.revision}. Each tile is described exactly once."
                )
            placed[placement.position_id] = placement
            layout_disk_name = placement.position_id.casefold()
            if layout_disk_name in seen_layout_names:
                raise ZmartLiveError(
                    f"Positions {seen_layout_names[layout_disk_name]!r} and "
                    f"{placement.position_id!r} in layout revision {self.revision} "
                    "differ only by letter case and would be the same folder on "
                    "a Windows microscope computer."
                )
            seen_layout_names[layout_disk_name] = placement.position_id
        # The by-name index the uniqueness sweep above has already built.
        # Asking by name is how every publication finds its placement, and a
        # linear scan cost six of a replacement's forty-eight seconds at
        # 12,769 positions -- fifty thousand scans of the whole layout.
        object.__setattr__(self, "_placed", placed)

    def placement(self, position_id: str) -> PositionPlacement:
        """The record for one tile, by its name."""
        found = self._placed.get(position_id)
        if found is not None:
            return found
        raise ZmartLiveError(
            f"Layout revision {self.revision} does not describe a position called "
            f"'{position_id}'. It holds "
            f"{[p.position_id for p in self.positions] or 'no positions at all'}."
        )

    def component(self, component_id: str) -> MosaicComponent:
        """One mosaic component, by its name."""
        for candidate in self.components:
            if candidate.component_id == component_id:
                return candidate
        raise ZmartLiveError(
            f"Layout revision {self.revision} does not describe a mosaic component "
            f"called '{component_id}'."
        )

    @property
    def position_ids(self) -> tuple[str, ...]:
        """The names of every tile in this snapshot, in a settled order."""
        return tuple(sorted(placement.position_id for placement in self.positions))

    def owner_of_point(self, point: Mapping[str, int]) -> str | None:
        """Which tile owns a place on the specimen, or ``None`` when no tile does.

        Because owned regions are half-open and do not overlap, at most one tile
        can answer. Getting ``None`` from somewhere inside the mosaic means the
        run has a hole in it, which is a genuine finding rather than a rounding
        quirk.
        """
        owners = [
            placement.position_id
            for placement in self.positions
            if placement.owns_point_in_run(point)
        ]
        if len(owners) > 1:
            raise ZmartLiveError(
                f"Layout revision {self.revision} gives point {dict(point)} to "
                f"more than one position: {owners}. Returning either one would "
                "silently count the same specimen twice."
            )
        return owners[0] if owners else None

    def to_json(self) -> dict[str, Any]:
        """A plain dictionary, for writing to disk."""
        return {
            "revision": self.revision,
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "acquisition_type": self.acquisition_type,
            "profile_id": self.profile_id,
            "positions": [placement.to_json() for placement in self.positions],
            "components": [component.to_json() for component in self.components],
            "analysis_ownership": self.analysis_ownership,
            "analysis_halo": self.analysis_halo.as_dict(),
            "rounding_convention": self.rounding_convention,
            "created_at": self.created_at,
            "final": self.final,
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> SceneLayoutRevision:
        """Read back what :meth:`to_json` wrote."""
        return cls(
            revision=int(value["revision"]),
            schema_version=value["schema_version"],
            run_id=value["run_id"],
            acquisition_type=value["acquisition_type"],
            profile_id=value["profile_id"],
            positions=tuple(PositionPlacement.from_json(p) for p in value.get("positions", ())),
            components=tuple(MosaicComponent.from_json(c) for c in value.get("components", ())),
            analysis_ownership=value.get("analysis_ownership", "midpoint"),
            analysis_halo=value.get("analysis_halo", {}),
            rounding_convention=value.get("rounding_convention", "extra_pixel_to_lower_index"),
            created_at=value.get("created_at", ""),
            final=bool(value.get("final", False)),
        )


@dataclass(frozen=True)
class CommitEvent:
    """The one record that makes a finished position or timepoint visible.

    Everything else in this package exists to make this record trustworthy. Data
    can be sitting complete on disk for some time before it appears; the presence
    of files means nothing, and this record means everything. Until a commit
    naming a position exists, no viewer and no analysis may act on that
    position's pixels, however finished they look.

    A commit is written only once every prerequisite it names has been checked:
    the pixels, the zoomed-out copies, the pointers the linked view serves them
    through, the view description those pointers answer for, and the layout
    snapshot that says where every tile sits. Because it references all of them, a reader
    who trusts one commit is trusting a set of things that were verified
    together.

    ``revision`` only ever goes up. That single increasing number is what lets a
    viewer that missed an announcement notice, on its next question, that it has
    fallen behind.
    """

    revision: int
    event_type: str
    position_id: str
    run_id: str
    acquisition_type: str
    acquisition_profile_id: str
    scene_layout_revision: int
    link_revision: int
    position_generation: int = 0
    timepoint: int | None = None
    component_id: str | None = None
    cell: GridCell | None = None
    channels: tuple[str, ...] = ()
    levels: tuple[int, ...] = ()
    pyramids_ready: bool = False
    links_ready: bool = False
    view_ready: bool = False
    #: True when this run writes its linked plain-file view once, at the end of
    #: the run, instead of after every commit. Mid-run the live picture is
    #: served straight out of the positions' own stores, so the linked view is
    #: genuinely not one of this commit's prerequisites — this flag records
    #: that honestly, rather than letting ``view_ready`` claim a check that
    #: never ran.
    linked_view_deferred: bool = False
    validated: bool = False
    timestamp: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "channels", tuple(self.channels))
        object.__setattr__(self, "levels", tuple(self.levels))
        if self.event_type not in EVENT_TYPES:
            raise ZmartLiveError(
                f"'{self.event_type}' is not a kind of publication this run "
                f"recognises. Use one of {', '.join(EVENT_TYPES)}."
            )
        if self.revision < 1:
            raise ZmartLiveError(
                f"Published revisions are counted from one, so that 'revision 0' can "
                f"mean 'nothing published yet'; got {self.revision}."
            )
        for name, value in (
            ("position", self.position_id),
            ("run", self.run_id),
            ("acquisition type", self.acquisition_type),
            ("acquisition profile", self.acquisition_profile_id),
        ):
            if not value:
                raise ZmartLiveError(f"A commit has to name its {name}.")
        # Every one of these is looked up as a folder or a file at some point by
        # the viewer or by an analysis, so none of them may be able to point
        # somewhere outside the run.
        check_the_name_is_safe(self.position_id, what="position")
        check_the_name_is_safe(self.run_id, what="run")
        check_the_name_is_safe(self.acquisition_type, what="acquisition type")
        check_the_name_is_safe(self.acquisition_profile_id, what="acquisition profile")
        if self.component_id is not None:
            check_the_name_is_safe(self.component_id, what="mosaic component")
        if self.scene_layout_revision < 0 or self.link_revision < 0:
            raise ZmartLiveError(
                "Layout and link revisions cannot be negative; got "
                f"{self.scene_layout_revision} and {self.link_revision}."
            )
        if self.position_generation < 0:
            raise ZmartLiveError(
                "Position generations are counted from zero; got "
                f"{self.position_generation}."
            )
        if self.timepoint is not None and self.timepoint < 0:
            raise ZmartLiveError(f"Timepoints are counted from zero; got {self.timepoint}.")
        if self.event_type == "timepoint_committed" and self.timepoint is None:
            raise ZmartLiveError(
                "A timepoint commit has to say which timepoint it publishes; this one "
                "leaves it blank."
            )
        if (
            not self.channels
            or len(self.channels) != len(set(self.channels))
            or any(not channel for channel in self.channels)
        ):
            raise ZmartLiveError(
                f"A commit's channel names must be present and unique; got {self.channels}."
            )
        if (
            not self.levels
            or len(self.levels) != len(set(self.levels))
            or any(level < 0 for level in self.levels)
        ):
            raise ZmartLiveError(
                f"A commit's pyramid levels must be unique non-negative numbers; got {self.levels}."
            )

    @property
    def ready(self) -> bool:
        """True only when every prerequisite this commit depends on has been checked.

        Strict publication means all of these together or none of them. A commit
        that is not ready must never be written, because a reader is entitled to
        assume that anything it can see is complete.

        The one prerequisite that can be genuinely absent rather than unmet is
        the linked view's description: a run that writes its linked view once,
        at the end of the run, has no view to check mid-run — and says so with
        ``linked_view_deferred`` instead of pretending the check passed.
        """
        return (
            self.pyramids_ready
            and self.links_ready
            and (self.view_ready or self.linked_view_deferred)
            and self.validated
        )

    def to_json(self) -> dict[str, Any]:
        """A plain dictionary, for appending to the run's event file."""
        return {
            "revision": self.revision,
            "event_type": self.event_type,
            "position_id": self.position_id,
            "run_id": self.run_id,
            "acquisition_type": self.acquisition_type,
            "acquisition_profile_id": self.acquisition_profile_id,
            "scene_layout_revision": self.scene_layout_revision,
            "link_revision": self.link_revision,
            "position_generation": self.position_generation,
            "timepoint": self.timepoint,
            "component_id": self.component_id,
            "cell": None if self.cell is None else self.cell.to_json(),
            "channels": list(self.channels),
            "levels": list(self.levels),
            "pyramids_ready": self.pyramids_ready,
            "links_ready": self.links_ready,
            "view_ready": self.view_ready,
            "linked_view_deferred": self.linked_view_deferred,
            "validated": self.validated,
            "timestamp": self.timestamp,
            "notes": self.notes,
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> CommitEvent:
        """Read back what :meth:`to_json` wrote."""
        cell = value.get("cell")
        return cls(
            revision=int(value["revision"]),
            event_type=value["event_type"],
            position_id=value["position_id"],
            run_id=value["run_id"],
            acquisition_type=value["acquisition_type"],
            acquisition_profile_id=value["acquisition_profile_id"],
            scene_layout_revision=int(value["scene_layout_revision"]),
            link_revision=int(value["link_revision"]),
            position_generation=int(value.get("position_generation", 0)),
            timepoint=None if value.get("timepoint") is None else int(value["timepoint"]),
            component_id=value.get("component_id"),
            cell=None if cell is None else GridCell.from_json(cell),
            channels=tuple(value.get("channels", ())),
            levels=tuple(int(lvl) for lvl in value.get("levels", ())),
            pyramids_ready=bool(value.get("pyramids_ready", False)),
            links_ready=bool(value.get("links_ready", False)),
            view_ready=bool(value.get("view_ready", False)),
            linked_view_deferred=bool(value.get("linked_view_deferred", False)),
            validated=bool(value.get("validated", False)),
            timestamp=value.get("timestamp", ""),
            notes=value.get("notes", ""),
        )

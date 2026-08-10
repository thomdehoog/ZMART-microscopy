"""The zoomed-out picture, and why it is the awkward part of publishing live.

Everything else in this package divides cleanly. A position owns its own pixels,
a commit makes one position visible, and no two positions tread on each other.
The zoomed-out levels are where that tidiness breaks down, and it is worth
understanding why before reading the code.

When you zoom out, one pixel on the screen stands for many pixels of specimen —
and once you are far enough out, a single stored piece of the zoomed-out picture
covers **several positions at once**. That piece is one thing. It cannot be half
published.

So imagine two neighbouring positions sharing one zoomed-out piece. The first has
finished writing; the second is still going. What should that piece contain?

Not both, plainly — the second position is unfinished, and showing it would be
exactly the wrong picture this whole design exists to prevent. But the piece
cannot simply be withheld either, because then the first position would be
invisible when zoomed out despite being complete, and an operator would watch
their run stay blank while it was in fact filling up.

The answer, and the rule this module implements
-----------------------------------------------

    **A zoomed-out piece is built from the committed positions only, and it is
    rebuilt each time another position joins it.**

So the shared piece first shows the first position and empty ground where the
second will go. When the second position commits, the piece is rebuilt to show
both, and that rebuild is published in the same single step as the position
itself. A viewer therefore sees the first position, then both — and never a
glimpse of the second before it was finished.

This is what the architecture record means by rebuilding and validating every
affected zoomed-out piece before the visible revision moves. It is also the
reason a commit is not free: the more positions share a piece, the more work each
commit does. :func:`chunks_touched_by` is what keeps that bounded, by working out
exactly which pieces a position disturbs — and, just as importantly, which it
does not.

What this module does not do
----------------------------

It does not decide *when* to publish; that is :mod:`zmart_live.manifest`. It does
not decide who owns which pixel; that is :mod:`zmart_live.ownership`. It answers
two narrow questions: which zoomed-out pieces does this position disturb, and
what should each of those pieces contain given what has been committed so far.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import AcquisitionProfile, Box, Interval, PositionPlacement, ZmartLiveError

__all__ = [
    "CoarseChunk",
    "chunks_touched_by",
    "contributors_to",
    "what_a_chunk_should_hold",
    "rebuild_after_committing",
]


@dataclass(frozen=True, order=True)
class CoarseChunk:
    """One stored piece of the zoomed-out picture.

    ``level`` counts from zero, where zero is full resolution. The profile says
    how much smaller that level is on each axis; this is deliberately not
    inferred from the level number because anisotropic volumes do not
    necessarily halve every axis together. ``index`` gives the piece's place on
    that level's grid, counted in whole pieces rather than pixels — the piece at
    index ``(2, 5)`` is the third down and the sixth across.
    """

    level: int
    index: tuple[int, ...]
    axes: tuple[str, ...]

    def covers(self, profile: AcquisitionProfile, chunk: dict[str, int]) -> Box:
        """The stretch of the run, in full-resolution pixels, that this piece shows.

        Expressed at full resolution rather than at the level's own scale so that
        it can be compared directly against a position's owned region, which is
        always recorded at full resolution.
        """
        scale = _scale_at(profile, self.level)
        spans = {}
        for axis, place in zip(self.axes, self.index, strict=True):
            across = chunk[axis] * scale[axis]
            spans[axis] = Interval(place * across, (place + 1) * across)
        return Box.of(**spans)


def _chunk_at(profile: AcquisitionProfile, level: int) -> dict[str, int]:
    """The size of one stored piece at ``level``, on each tiled axis."""
    geometry = profile.level(level)
    missing = [axis for axis in profile.tiled_axes if axis not in geometry.inner_chunk]
    if missing:
        raise ZmartLiveError(
            f"Level {level} has no inner-chunk size for tiled axis/axes "
            f"{', '.join(missing)}. It cannot name run-wide coarse chunks."
        )
    return {axis: geometry.inner_chunk[axis] for axis in profile.tiled_axes}


def _scale_at(profile: AcquisitionProfile, level: int) -> dict[str, int]:
    """The full-resolution pixels represented by one pixel at ``level``."""
    geometry = profile.level(level)
    missing = [axis for axis in profile.tiled_axes if axis not in geometry.downsampling]
    if missing:
        raise ZmartLiveError(
            f"Level {level} has no downsampling factor for tiled axis/axes "
            f"{', '.join(missing)}. It cannot locate run-wide coarse chunks."
        )
    return {axis: geometry.downsampling[axis] for axis in profile.tiled_axes}


def chunks_touched_by(
    profile: AcquisitionProfile,
    placement: PositionPlacement,
    level: int,
) -> tuple[CoarseChunk, ...]:
    """Which zoomed-out pieces this position disturbs, and only those.

    A position changes a piece if the ground it owns overlaps the ground that
    piece shows. Everything else is left alone, which is what stops one position
    arriving from making the whole picture stale.

    Being exact in both directions matters. Naming too many pieces means
    rebuilding work that did not need doing, on the path of every commit while
    the microscope is waiting. Naming too few leaves a piece showing the ground
    as it was before this position arrived, which looks like a gap in the
    specimen rather than like a fault.
    """
    if level < 0:
        raise ZmartLiveError(f"Zoom levels are counted from zero; got {level}.")
    chunk = _chunk_at(profile, level)
    scale = _scale_at(profile, level)
    axes = profile.tiled_axes

    owned = placement.visual_source_roi.shifted(placement.origin)
    ranges: list[range] = []
    for axis in axes:
        across = chunk[axis] * scale[axis]
        span = owned[axis]
        if span.is_empty:
            return ()
        first = span.start // across
        # The last piece is the one holding the final pixel, which is one before
        # the half-open end. Using the end itself would name an extra piece that
        # this position does not actually touch.
        last = (span.stop - 1) // across
        ranges.append(range(first, last + 1))

    pieces: list[CoarseChunk] = []

    def walk(so_far: tuple[int, ...], depth: int) -> None:
        if depth == len(axes):
            pieces.append(CoarseChunk(level=level, index=so_far, axes=axes))
            return
        for place in ranges[depth]:
            walk((*so_far, place), depth + 1)

    walk((), 0)
    return tuple(sorted(pieces))


def contributors_to(
    profile: AcquisitionProfile,
    chunk: CoarseChunk,
    placements: tuple[PositionPlacement, ...],
) -> tuple[PositionPlacement, ...]:
    """Every position whose owned ground shows up in this piece.

    This is the answer to "who has a say in what this piece looks like", and it
    is usually more than one, which is the whole difficulty.
    """
    shows = chunk.covers(profile, _chunk_at(profile, chunk.level))
    return tuple(
        placement
        for placement in placements
        if placement.visual_source_roi.shifted(placement.origin).overlaps(shows)
    )


def what_a_chunk_should_hold(
    profile: AcquisitionProfile,
    chunk: CoarseChunk,
    placements: tuple[PositionPlacement, ...],
    committed: frozenset[str],
) -> tuple[PositionPlacement, ...]:
    """Which positions may appear in this piece, given what has been published.

    The rule in one line: a position appears in a zoomed-out piece only once it
    has been committed. A position that is still being written contributes
    nothing, and the ground it will eventually cover stays empty until it does.

    An operator seeing that empty ground is seeing the truth — that part of the
    specimen has not finished imaging yet — rather than a picture assembled from
    half-written data, which would look like a finished result.
    """
    return tuple(
        placement
        for placement in contributors_to(profile, chunk, placements)
        if placement.position_id in committed
    )


@dataclass(frozen=True)
class Rebuild:
    """The zoomed-out work one commit brings with it.

    ``pieces`` are the stored pieces that have to be rebuilt and checked before
    the new position may become visible. ``shared_with`` names the positions that
    were already published and appear in those same pieces — they are not being
    republished, but their pixels have to be put back into each rebuilt piece, or
    committing a new position would erase its neighbours from the zoomed-out
    view.

    That last point is the mistake this record exists to make hard to overlook.
    """

    position_id: str
    level: int
    pieces: tuple[CoarseChunk, ...]
    shared_with: tuple[str, ...]

    @property
    def how_much_work(self) -> int:
        """How many pieces have to be rebuilt for this one commit."""
        return len(self.pieces)


def rebuild_after_committing(
    profile: AcquisitionProfile,
    placements: tuple[PositionPlacement, ...],
    position_id: str,
    committed: frozenset[str],
    *,
    levels: tuple[int, ...] | None = None,
) -> tuple[Rebuild, ...]:
    """Work out the zoomed-out rebuilding one commit requires, level by level.

    Call this before publishing a position: it says exactly which pieces of the
    zoomed-out picture must be rebuilt and checked, and which already-published
    neighbours have to be included in each. Only when all of that has been done
    may the position be committed, because the commit is what makes the whole lot
    visible together.

    ``committed`` should be the positions already published, **not** counting the
    one being committed now.
    """
    placements_by_id = {p.position_id: p for p in placements}
    if position_id not in placements_by_id:
        raise ZmartLiveError(
            f"'{position_id}' is not one of the positions in this layout, so there "
            f"is nothing to work out for it. The layout describes "
            f"{sorted(placements_by_id) or 'no positions at all'}."
        )
    arriving = placements_by_id[position_id]
    wanted = levels if levels is not None else tuple(level.level for level in profile.levels)

    work: list[Rebuild] = []
    for level in wanted:
        pieces = chunks_touched_by(profile, arriving, level)
        neighbours: set[str] = set()
        for piece in pieces:
            for other in what_a_chunk_should_hold(profile, piece, placements, committed):
                if other.position_id != position_id:
                    neighbours.add(other.position_id)
        work.append(
            Rebuild(
                position_id=position_id,
                level=level,
                pieces=pieces,
                shared_with=tuple(sorted(neighbours)),
            )
        )
    return tuple(work)

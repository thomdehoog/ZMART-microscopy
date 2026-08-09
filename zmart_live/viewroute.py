"""Serving one small piece of the seamless view straight out of a bundled position.

Why this exists
---------------

The seamless view is the picture an operator actually looks at: one continuous
image of the whole slide, made out of the positions the microscope has already
written. Nothing of it at full resolution is stored a second time. When the
viewer asks for a piece of it, something has to say which file already holds
those exact bytes, where in that file they start, and how many of them there are.

:mod:`zmart_live.shardlink` can answer that question for a single chunk of a
single position, and it has been proven against real files. What was missing was
the step in front of it: turning *"the viewer wants piece (0, 0, 3, 8, 8) of the
view"* into *"that is chunk (0, 0, 3, 8, 0) of the position in this folder"*, and
then into a byte range. This module is that step.

The one number everything turns on
----------------------------------

A position written by :func:`zmart_live.profiles.plan_the_writing` keeps its
pixels in two nested sizes, and telling them apart is the whole of this module.

* The **chunk** is the small piece the picture is really cut into — 128 pixels
  square in the usual overview plan. It is the smallest amount of image that can
  be decoded on its own.
* The **bundle**, which the Zarr documents call a *shard*, is one file holding
  many of those chunks end to end, with a small table at the back saying where
  each of them begins. Bundling exists for one reason only: without it an
  overnight run leaves millions of tiny files behind, and most disks, network
  shares and backup programs cope with that badly.

The older linked view in :mod:`zmart_storage.linked` hands the viewer **whole
files**, so for a bundled position it measures everything in whole bundles: a
position had to land on a bundle boundary, and the trimmed strip at a seam had to
be a whole number of bundles. That is a much harsher rule than it sounds, and it
is the rule that turns the sensible plan the profile chooses into a refusal. The
overview plan makes a bundle span the entire 1152-pixel frame, so a seam that
falls at 1024 pixels — which is exactly where one-sided ownership puts it — is
not on a bundle boundary at all, even though it sits neatly on the eighth chunk.

This module measures in **chunks** instead, because it hands over a byte range
rather than a file. A seam is then allowed to fall wherever a chunk boundary
falls, and it is perfectly ordinary for it to cut across the middle of a bundle:
the bundle is a container, not a picture, and taking one chunk out of the middle
of it costs a seek and a read.

Why the view itself keeps no bundles
------------------------------------

It is natural to expect the view to be stored exactly like the positions it
points at, bundles and all, and that is what the whole-file arrangement had to
do. Here it would be wrong. What is handed over is one *encoded chunk*, so the
view has to describe itself as an unbundled image whose chunk is the position's
inner chunk and whose compression is the compression applied inside the bundle.
A view that declared bundles while being served single chunks would describe its
own bytes incorrectly, and the viewer would draw noise without reporting
anything.

There is no cost to this. The reason for bundling is the number of files a run
leaves behind, and the view leaves behind no picture files at all — every piece
of it is answered by pointing at a position. So the question of how large the
view's bundles should be simply does not arise.

That is also the honest answer to a limitation recorded in the review of this
branch: :meth:`zmart_storage.canvas.TileCanvases.create` accepts a single number
for the bundle across ``y`` and ``x``, and cannot express the profile's bundle,
which is a slab of ``z`` planes spanning the whole frame. It was left alone
rather than extended, because on this route the view is never bundled and the
positions are written by the acquisition rather than by that writer. Extending it
would have added a setting that nothing on this path uses. If a future writer
does need to write a bundled *view*, that is the place to change, and this note
is here so the next person does not have to rediscover why it was not changed
now.

What this module offers
-----------------------

:func:`route_the_view`
    Reads the positions, checks that they agree with one another and that each
    lands on whole chunks, and returns a :class:`ViewRoute`.

:meth:`ViewRoute.where_this_chunk_is`
    The question the viewer's server asks: given one chunk coordinate of the
    view, which file, which byte, how many bytes — or nothing at all, when that
    part of the slide has not been imaged yet.

:func:`the_bytes_of`
    Reads exactly that range, so the bytes can be handed on undecoded.

:func:`refuse_a_view_stored_differently`
    Compares what the view says about itself with what the positions really
    contain, and refuses the pair rather than letting a viewer draw noise.
"""

from __future__ import annotations

import json
import operator
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .model import ZmartLiveError
from .shardlink import Bundling, Held, StoredArray, how_the_array_is_stored

__all__ = [
    "Placed",
    "Serving",
    "ViewRoute",
    "ViewStorage",
    "refuse_a_view_stored_differently",
    "route_the_view",
    "the_bytes_of",
]


# ---------------------------------------------------------------------------
# What a caller hands in, and what it gets back
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Placed:
    """One position, which part of it the view shows, and where that part goes.

    Every number is in pixels and is given as ``(z, y, x)``, which is the order
    the images themselves are stored in.

    Attributes:
        array: the folder of **one level of one position** — the folder holding a
            ``zarr.json``, such as ``pos00001.ome.zarr/0``. A route is built for
            one level at a time, because each level has its own chunk grid.
        lands_at: where the shown part's low corner sits in the view.
        taken_from: where the shown part begins inside the position. Zero on every
            axis for a position shown whole, and something else where a seam has
            been placed and one neighbour gives up its share of the overlap.
        size: how much of the position the view shows. Left out, it is everything
            from ``taken_from`` to the far edge of the position, which is what a
            position shown whole wants.
    """

    array: Path
    lands_at: tuple[int, int, int]
    taken_from: tuple[int, int, int] = (0, 0, 0)
    size: tuple[int, int, int] | None = None


@dataclass(frozen=True)
class Serving:
    """One piece of the view, said as a stretch of bytes in a file that exists.

    This is everything the viewer's server needs in order to answer a request
    without decoding anything: open ``path``, skip to ``offset``, hand over
    ``length`` bytes. Those bytes are one encoded chunk, exactly as the
    acquisition wrote it, compression and all.

    The two extra fields are for the humans. ``position`` says which position
    supplied the piece, which is what makes a wrong seam recognisable in a log
    rather than only on screen, and ``inside_the_position`` is the chunk
    coordinate it came from within that position.
    """

    path: Path
    offset: int
    length: int
    position: Path
    inside_the_position: tuple[int, ...]

    @property
    def stop(self) -> int:
        """The byte just past the end of the piece, in the half-open style."""
        return self.offset + self.length


@dataclass(frozen=True)
class ViewStorage:
    """How the view's own arrays have to be declared, for its bytes to be readable.

    The view describes a picture it does not store. Every one of these has to
    match what the positions really contain, because the bytes are handed over
    untouched and a disagreement produces a confident picture of noise rather
    than an error.

    Attributes:
        dtype: the kind of number one pixel is, spelled as the file spells it.
        chunk: the shape of one piece of the view, over every axis. This is the
            position's **inner chunk**, not its bundle.
        codecs: what is done to a chunk's pixels on their way to disk. For a
            bundled position these are the codecs from inside the bundle, since
            those are what encoded the bytes being handed over.
        fill_value: what a piece that was never written stands for.
        positions_are_bundled: whether the positions behind this view pack many
            chunks into one file. It changes nothing about how the view is
            declared, and is kept because it is the first thing anybody asks when
            a byte range does not look like a whole file.
    """

    dtype: str
    chunk: tuple[int, ...]
    codecs: tuple[dict, ...]
    fill_value: object
    positions_are_bundled: bool


# ---------------------------------------------------------------------------
# Reading one position, and refusing a set that disagrees
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _HowAPositionIsStored:
    """Everything about one position that the view has to copy exactly.

    ``on_disk`` is the position's own description, read once when the route was
    built. Keeping it is what stops every request re-reading the same small file
    to rediscover facts that cannot have changed.
    """

    array: Path
    on_disk: StoredArray
    dtype: str
    fill_value: object
    chunk_codecs: tuple[dict, ...]

    @property
    def bundling(self) -> Bundling:
        """How this position is chunked and bundled."""
        return self.on_disk.bundling

    @property
    def axes(self) -> int:
        """How many axes the position's picture has, usually five."""
        return len(self.bundling.array_shape)

    def where_one_chunk_lives(self, coordinate: Sequence[int]) -> Held | None:
        """Which file holds one of this position's chunks, at which byte, how long."""
        return self.on_disk.where_one_chunk_lives(coordinate)


def _the_description_of(array: Path) -> dict:
    """Read an array's own ``zarr.json``, which says how it is really stored."""
    described = array / "zarr.json"
    try:
        content = json.loads(described.read_text(encoding="utf-8"))
    except (OSError, ValueError) as problem:
        raise ZmartLiveError(
            f"The description at '{described}' could not be read: {problem}. Without "
            f"it there is no way to know how this position stores its pixels, and a "
            f"view over it would be describing bytes it has never looked at."
        ) from problem
    if not isinstance(content, dict):
        raise ZmartLiveError(f"The description at '{described}' is not a table of metadata.")
    return content


def _how_a_position_is_stored(array: Path) -> _HowAPositionIsStored:
    """Read one level of one position: its chunk grid, its bundling, its encoding.

    The geometry comes from :func:`zmart_live.shardlink.how_the_array_is_stored`,
    which is the part that has been proven against real files. What is added here
    is the encoding: the kind of number a pixel is, and what is done to a chunk on
    its way to disk. Those are what the view has to declare about itself.

    The description is read once here and kept, rather than being read again for
    every piece the viewer asks for. Nothing in it can change while the run goes
    on: an array says how it is chunked and how a chunk is compressed before any
    pixels are written, and rewriting that would mean rewriting the position.
    """
    on_disk = how_the_array_is_stored(array)
    bundling = on_disk.bundling
    content = on_disk.description

    if bundling.sharded:
        # The codecs that matter are the ones *inside* the bundle. The bundle's own
        # entry in the list describes the packing, and packing is exactly what a
        # byte range undoes, so it must not be declared by the view.
        inside: list = []
        for codec in content.get("codecs") or ():
            if isinstance(codec, dict) and codec.get("name") == "sharding_indexed":
                inside = list((codec.get("configuration") or {}).get("codecs") or [])
        if not inside:
            raise ZmartLiveError(
                f"'{array}' bundles its chunks but does not say how the chunks "
                f"inside the bundle are encoded. Handing one of them to a viewer "
                f"would mean guessing at its compression, and a wrong guess draws "
                f"noise rather than reporting anything."
            )
        chunk_codecs = tuple(inside)
    else:
        chunk_codecs = tuple(content.get("codecs") or ())

    return _HowAPositionIsStored(
        array=Path(array),
        on_disk=on_disk,
        dtype=str(content.get("data_type")),
        fill_value=content.get("fill_value"),
        chunk_codecs=chunk_codecs,
    )


def _refuse_positions_stored_differently(
    first: _HowAPositionIsStored, other: _HowAPositionIsStored
) -> None:
    """Stop a view whose positions were not all written the same way.

    The view declares one way of storing a picture and then hands over bytes from
    every position under that one description. A position that disagrees is not
    reported by anything downstream: its pixels are simply read as though they
    were what the view said, and the specimen comes out wrong in a way that looks
    entirely plausible. So each difference is named here instead.
    """
    if other.axes != first.axes:
        raise ZmartLiveError(
            f"'{first.array}' has {first.axes} axes and '{other.array}' has "
            f"{other.axes}. A view is one picture, so every position in it has to "
            f"be arranged over the same axes in the same order."
        )
    if other.bundling.inner_chunk != first.bundling.inner_chunk:
        raise ZmartLiveError(
            f"'{first.array}' is cut into chunks of {first.bundling.inner_chunk} and "
            f"'{other.array}' into chunks of {other.bundling.inner_chunk}. The view "
            f"advertises one chunk shape and answers every request for it with a "
            f"chunk out of a position, so a position cut differently would supply a "
            f"piece of the wrong size and the picture would be misread."
        )
    if other.dtype != first.dtype:
        raise ZmartLiveError(
            f"'{first.array}' stores its pixels as {first.dtype} and '{other.array}' "
            f"as {other.dtype}. Those bytes are handed over untouched, so reading "
            f"one as the other gives a picture of noise rather than an error."
        )
    if other.chunk_codecs != first.chunk_codecs:
        raise ZmartLiveError(
            f"'{first.array}' encodes a chunk as {first.chunk_codecs} and "
            f"'{other.array}' as {other.chunk_codecs}. A view says once how its "
            f"pieces are compressed, so two positions compressed differently cannot "
            f"be shown as one picture. This usually means two acquisitions have been "
            f"gathered up together; build a view over each of them on its own."
        )
    if other.fill_value != first.fill_value:
        raise ZmartLiveError(
            f"'{first.array}' fills unimaged ground with {first.fill_value} and "
            f"'{other.array}' with {other.fill_value}. The view can only say one of "
            f"them, so the other position's blank ground would be drawn as specimen."
        )


# ---------------------------------------------------------------------------
# Small pieces of arithmetic
# ---------------------------------------------------------------------------


def _whole_numbers(values: Sequence[int], what: str) -> tuple[int, ...]:
    """Check that something is made of whole numbers, and return it as a tuple."""
    try:
        return tuple(operator.index(value) for value in values)
    except (TypeError, ValueError) as why:
        raise ZmartLiveError(
            f"The {what} has to be made of whole numbers; got {tuple(values)}. "
            f"Rounding a coordinate would quietly select a different piece of the "
            f"specimen."
        ) from why


@dataclass(frozen=True)
class _Block:
    """One position's share of the view, counted in chunks rather than pixels.

    Everything about placing a position becomes simple once it is counted this
    way: the position supplies a rectangular block of the view's chunk grid, and
    which of its own chunks each of them is comes out of a subtraction.
    """

    stored: _HowAPositionIsStored
    begins: tuple[int, int, int]
    extent: tuple[int, int, int]
    low: tuple[int, int, int]


def _refuse_a_placement_that_does_not_land_on_whole_chunks(
    placed: Placed,
    stored: _HowAPositionIsStored,
    size: tuple[int, int, int],
) -> None:
    """Stop a position whose share of the view is not a whole number of chunks.

    A chunk is the smallest amount of picture that can be decoded on its own, so
    it is also the smallest amount that can be handed over without touching a
    pixel. Where a position lands half a chunk out, answering a request would mean
    decoding two of its chunks, cutting a rectangle out of them and encoding the
    result — which is the copying this whole arrangement exists to avoid, and at a
    scale that would not keep up with the microscope.

    The unit here is the **chunk**, and that is the difference between this route
    and the whole-file one in :mod:`zmart_storage.linked`. A position may bundle
    many chunks into one file, and its share of the view is still allowed to begin
    and end in the middle of such a bundle; only the chunks inside it have to line
    up. The message says so, because an operator who has met the whole-file rule
    will reasonably expect the bundle to be what matters.
    """
    inner = stored.bundling.inner_chunk[-3:]
    bundle = stored.bundling.shard_shape[-3:] if stored.bundling.sharded else None
    for axis, name in ((0, "z"), (1, "y"), (2, "x")):
        piece = inner[axis]
        for what, value in (
            ("lands at", placed.lands_at[axis]),
            ("is taken from", placed.taken_from[axis]),
            ("shows", size[axis]),
        ):
            if value % piece:
                bundled_note = (
                    f"\n\nThe positions do bundle their chunks — one file holds "
                    f"{bundle} pixels' worth of them — but that is not what has to "
                    f"line up here. A bundle is a container rather than a picture, "
                    f"and a single chunk is taken out of the middle of one by "
                    f"reading a stretch of bytes. It is only the chunk that has to "
                    f"line up."
                    if bundle is not None
                    else ""
                )
                raise ZmartLiveError(
                    f"'{placed.array}' {what} {value} pixels in {name}, and its "
                    f"picture is cut into chunks {piece} pixels across, so that is "
                    f"{value / piece:.2f} chunks rather than a whole number of "
                    f"them.\n\n"
                    f"A view shows part of a position by handing over one of its "
                    f"chunks exactly as it is on disk, which it can only do when "
                    f"the two grids line up. Half a chunk out, answering would mean "
                    f"decoding pixels and encoding them again for every request."
                    f"{bundled_note}\n\n"
                    f"Either place the positions on a grid of whole chunks — which "
                    f"for a run whose step is a whole number of chunks happens on "
                    f"its own — or acquire with a chunk that divides {value}."
                )


def _refuse_a_part_that_is_not_there(
    placed: Placed, stored: _HowAPositionIsStored, size: tuple[int, int, int]
) -> None:
    """Stop a view asking a position for more picture than the position holds."""
    shape = stored.bundling.array_shape[-3:]
    for axis, name in ((0, "z"), (1, "y"), (2, "x")):
        if placed.taken_from[axis] < 0 or placed.lands_at[axis] < 0 or size[axis] < 1:
            raise ZmartLiveError(
                f"'{placed.array}' is asked for {size[axis]} pixels starting at "
                f"{placed.taken_from[axis]} on {name}, landing at "
                f"{placed.lands_at[axis]}. That is not a part of a picture that "
                f"could exist."
            )
        if placed.taken_from[axis] + size[axis] > shape[axis]:
            raise ZmartLiveError(
                f"'{placed.array}' is {shape[axis]} pixels across in {name}, and the "
                f"view asks it for {size[axis]} pixels starting at "
                f"{placed.taken_from[axis]}, which reaches past its far edge. The "
                f"part shown has to be inside the position."
            )


# ---------------------------------------------------------------------------
# The route itself
# ---------------------------------------------------------------------------


class ViewRoute:
    """Which position answers for each piece of the view, and where its bytes are.

    Build one with :func:`route_the_view` rather than directly, so that the
    positions are read and checked first.

    A route holds the positions themselves rather than one entry per piece of the
    view, and this is worth knowing before anybody tries to make it simpler. A
    position 1152 pixels across in chunks of 128 is nine by nine chunks; multiply
    that by its planes, its colours and its moments, then by the ten thousand
    positions a long run reaches, and a list with one entry per piece is tens of
    gigabytes held in memory to describe a picture that was never written. The
    viewer's own reader, in ``viz_studio/backend/linking.py``, sets the same
    reasoning out at greater length and arrived at the same arrangement.

    So each position is remembered once, and the only thing spread out is a note
    of which **rows** of the view's chunk grid it reaches into. Finding a piece
    then means looking in one row and checking the few positions there.

    What each position *does* keep is its own description — how it is chunked, how
    it is bundled, what it calls its files. None of that can change while a run is
    going, since an array settles it before any pixels are written, so reading it
    again for every piece would be pure waste.

    A position's table of contents is looked after in
    :mod:`zmart_live.shardlink` rather than here, and it is worth knowing how,
    because an earlier version of this class deliberately refused to keep one. The
    worry then was a live run: chunks are still landing in a bundle while the
    viewer is watching, and a table kept from an hour ago would go on saying
    "nothing was ever written there" long after something was, so an operator would
    watch a position stop filling in halfway and never recover. That worry was
    right, and it is answered rather than ignored. A table is kept against the
    identity of the file it was read from — its size, when it last changed, and
    which inode holds it — so a bundle the acquisition has written into is no
    longer the file that was remembered and its table is read afresh. A bundle that
    has not been touched since is byte for byte the one already read, and answering
    from memory cannot be wrong. That is what turns dozens of full table reads per
    screenful into one.
    """

    def __init__(
        self,
        blocks: Sequence[_Block],
        storage: ViewStorage,
        view_shape: tuple[int, int, int],
    ) -> None:
        self._blocks = tuple(blocks)
        self.storage = storage
        self.view_shape = view_shape
        self.inner_chunk = storage.chunk[-3:]
        self.chunks_in_view = tuple(
            -(-view_shape[axis] // self.inner_chunk[axis]) for axis in range(3)
        )
        # For each row of the view's chunk grid, the positions that cross it,
        # sorted by where they begin across the specimen.
        self._rows: dict[int, list[_Block]] = {}
        for block in self._blocks:
            for row in range(block.begins[1], block.begins[1] + block.extent[1]):
                self._rows.setdefault(row, []).append(block)
        for crossing in self._rows.values():
            crossing.sort(key=lambda block: block.begins[2])
        # How wide the widest position is, in chunks. The search below walks back
        # along a row, and this says when to stop: a position beginning further
        # back than the widest one is wide cannot still be reaching this far.
        self._widest = max((block.extent[2] for block in self._blocks), default=1)

    @property
    def positions(self) -> tuple[Path, ...]:
        """The positions this view is made of, in the order they were given."""
        return tuple(block.stored.array for block in self._blocks)

    def _position_covering(
        self, at: tuple[int, int, int]
    ) -> tuple[_Block, tuple[int, int, int]] | None:
        """Which position supplies the chunk at this place, and which of its own it is.

        ``at`` is a place in the view's grid of chunks, given as ``(z, y, x)``.
        Answering ``None`` is ordinary rather than a fault: most of a scattered
        run's picture is ground nobody imaged.
        """
        crossing = self._rows.get(at[1])
        if not crossing:
            return None
        nearest = bisect_right(crossing, at[2], key=lambda block: block.begins[2])
        for index in range(nearest - 1, -1, -1):
            block = crossing[index]
            if at[2] - block.begins[2] >= self._widest:
                break
            within = tuple(at[axis] - block.begins[axis] for axis in range(3))
            if all(0 <= within[axis] < block.extent[axis] for axis in range(3)):
                return block, tuple(
                    block.low[axis] + within[axis] for axis in range(3)
                )  # type: ignore[return-value]
        return None

    def where_this_chunk_is(self, chunk_coordinate: Sequence[int]) -> Serving | None:
        """Say where one piece of the view really lives: a file, a byte, a length.

        What goes in
            ``chunk_coordinate`` counts **chunks**, not pixels, from the corner of
            the view, with one number per axis in the picture's own order. For the
            five axes this project writes that is ``(moment, colour, z, y, x)``.
            The moment and the colour pass straight through to the position, which
            keeps its own as they are.

        What comes back
            A :class:`Serving` naming the file, the first byte and the number of
            bytes. Reading exactly those bytes gives one encoded chunk, ready to be
            handed to the viewer without being decoded.

            ``None`` means there is nothing to advertise there, and that is an
            ordinary answer rather than a fault. It happens for ground no position
            covers, for a moment a position has not reached yet, and — most often
            of all — for a chunk inside a position that has simply not been written
            yet, because the acquisition is still running or that part of the frame
            holds no specimen.

        What can go wrong
            A :class:`~zmart_live.model.ZmartLiveError` is raised when the
            coordinate names the wrong number of axes or is negative, and when a
            bundle turns out to be damaged or cut short. A piece that is merely
            absent never raises.
        """
        wanted = _whole_numbers(chunk_coordinate, "chunk coordinate")
        axes = len(self.storage.chunk)
        if len(wanted) != axes:
            raise ZmartLiveError(
                f"This view is arranged over {axes} axes, but the chunk coordinate "
                f"given names {len(wanted)} of them ({wanted}). It needs one number "
                f"per axis, in the picture's own axis order."
            )
        if any(index < 0 for index in wanted):
            raise ZmartLiveError(
                f"Chunk coordinate {wanted} counts backwards from the corner of the "
                f"view on at least one axis, and there is no picture there."
            )

        leading, spatial = wanted[:-3], wanted[-3:]
        if any(
            spatial[axis] >= self.chunks_in_view[axis] for axis in range(3)
        ):
            # Beyond the edge of the picture the view declared. Nothing is there to
            # point at, and saying so plainly is kinder than raising: a viewer
            # rounding a screenful up to whole chunks asks for these routinely.
            return None

        found = self._position_covering(spatial)
        if found is None:
            return None
        block, inside = found

        grid = block.stored.bundling.chunks_in_array
        coordinate = (*leading, *inside)
        if any(
            index >= extent for index, extent in zip(coordinate, grid, strict=True)
        ):
            # The position does not reach that far — most often a moment it has not
            # been asked to record yet. There is nothing to hand over.
            return None

        held = block.stored.where_one_chunk_lives(coordinate)
        if held is None:
            # Nothing was ever written at that chunk. The view should advertise
            # nothing there, so that the viewer draws the fill value rather than
            # being handed bytes belonging to some other part of the specimen.
            return None
        return Serving(
            path=held.path,
            offset=held.offset,
            length=held.length,
            position=block.stored.array,
            inside_the_position=coordinate,
        )

    def advertises(self, chunk_coordinate: Sequence[int]) -> bool:
        """Whether the view has anything to offer at this piece.

        This is the question a server asks before it answers: a piece that is
        advertised is served as bytes, and one that is not is answered "there is
        nothing here", which the viewer draws as unimaged ground.

        It deliberately asks the full question rather than only whether some
        position covers that ground. A position covers plenty of chunks it has not
        written yet — the acquisition may still be running, and the edge of a frame
        may hold nothing at all — and advertising those would promise bytes that do
        not exist.
        """
        return self.where_this_chunk_is(chunk_coordinate) is not None

    def covers(self, chunk_coordinate: Sequence[int]) -> bool:
        """Whether a position is responsible for this spatial view chunk.

        Unlike :meth:`advertises`, this does not require the source chunk to
        exist. A server uses the distinction to tell an absent route from a
        routed chunk whose canonical bytes have gone missing. The latter must
        fail closed; a metadata-only view has no copied payload to fall back to.
        """
        wanted = _whole_numbers(chunk_coordinate, "chunk coordinate")
        if len(wanted) != len(self.storage.chunk) or any(index < 0 for index in wanted):
            return False
        spatial = wanted[-3:]
        if any(
            spatial[axis] >= self.chunks_in_view[axis] for axis in range(3)
        ):
            return False
        return self._position_covering(spatial) is not None


def route_the_view(
    positions: Sequence[Placed],
    *,
    view_shape: tuple[int, int, int] | None = None,
) -> ViewRoute:
    """Work out which position answers for each piece of a seamless view.

    What goes in
        ``positions`` says, for each position, which level of it to point at,
        which part of it the view shows and where that part lands. See
        :class:`Placed`. Every position must be one level of one image, and all of
        them must be the same level, since a route describes one chunk grid.

        ``view_shape`` is how large the picture is, as ``(z, y, x)`` in pixels.
        Left out, it is exactly large enough for the positions given, which is
        usually what a finished run wants. Give it when the run means to declare
        the stage's whole travel range, so that positions arriving later still
        land inside the picture.

    What comes back
        A :class:`ViewRoute`. Ask it :meth:`~ViewRoute.where_this_chunk_is` for
        each piece the viewer requests.

    What can go wrong
        A :class:`~zmart_live.model.ZmartLiveError` is raised when no positions
        are given, when they were not all written the same way, when one of them
        does not land on whole chunks, when the view is asked for part of a
        position that is not there, or when two positions claim the same piece of
        the view. That last one matters more than it looks: two positions
        overlapping means the seam between them has not been decided, and
        whichever happened to be found first would be drawn, which is a picture
        that changes depending on the order a list was built in.
    """
    if not positions:
        raise ZmartLiveError(
            "A view has to be built over at least one position, and none were "
            "given. This usually means the run being pointed at has not published "
            "anything yet, or that the folder searched was the wrong one."
        )

    blocks: list[_Block] = []
    first: _HowAPositionIsStored | None = None
    for placed in positions:
        tidy = Placed(
            array=Path(placed.array),
            lands_at=_whole_numbers(placed.lands_at, "place a position lands at"),  # type: ignore[arg-type]
            taken_from=_whole_numbers(placed.taken_from, "place a position is taken from"),  # type: ignore[arg-type]
            size=None if placed.size is None else _whole_numbers(placed.size, "part shown"),  # type: ignore[arg-type]
        )
        stored = _how_a_position_is_stored(tidy.array)
        if first is None:
            first = stored
        else:
            _refuse_positions_stored_differently(first, stored)

        shape = stored.bundling.array_shape[-3:]
        # Shown whole means "everything from where we start to the far edge",
        # rather than "the whole position", so that a position taken from an
        # offset needs no second number to say the obvious.
        size = tidy.size or tuple(
            shape[axis] - tidy.taken_from[axis] for axis in range(3)
        )
        _refuse_a_part_that_is_not_there(tidy, stored, size)  # type: ignore[arg-type]
        _refuse_a_placement_that_does_not_land_on_whole_chunks(tidy, stored, size)  # type: ignore[arg-type]

        inner = stored.bundling.inner_chunk[-3:]
        blocks.append(
            _Block(
                stored=stored,
                begins=tuple(tidy.lands_at[axis] // inner[axis] for axis in range(3)),  # type: ignore[arg-type]
                extent=tuple(size[axis] // inner[axis] for axis in range(3)),  # type: ignore[arg-type]
                low=tuple(tidy.taken_from[axis] // inner[axis] for axis in range(3)),  # type: ignore[arg-type]
            )
        )

    assert first is not None  # a route over no positions was refused above
    _refuse_two_positions_claiming_the_same_piece(blocks)

    inner = first.bundling.inner_chunk[-3:]
    reaches = tuple(
        max(
            (block.begins[axis] + block.extent[axis]) * inner[axis] for block in blocks
        )
        for axis in range(3)
    )
    shape = tuple(_whole_numbers(view_shape, "view shape")) if view_shape else reaches
    for axis, name in ((0, "z"), (1, "y"), (2, "x")):
        if shape[axis] < reaches[axis]:
            raise ZmartLiveError(
                f"The view was declared {shape[axis]} pixels across in {name} and "
                f"its positions reach to {reaches[axis]}, so some of them would sit "
                f"outside the picture and could not be drawn at all. Declaring room "
                f"costs practically nothing, because nothing is written into it."
            )

    storage = ViewStorage(
        dtype=first.dtype,
        chunk=first.bundling.inner_chunk,
        codecs=first.chunk_codecs,
        fill_value=first.fill_value,
        positions_are_bundled=first.bundling.sharded,
    )
    return ViewRoute(blocks, storage, shape)  # type: ignore[arg-type]


def _refuse_two_positions_claiming_the_same_piece(blocks: Sequence[_Block]) -> None:
    """Stop a view in which two positions supply the same piece of the picture.

    Where two positions overlap, somebody has to decide which of them the view
    shows — that decision is what a seam is, and it is made by trimming one of
    them before it gets here. Two positions still claiming the same piece means no
    such decision was made, and the picture would then depend on which position
    happened to be looked at first. That is the kind of fault that shows up as a
    specimen that looks slightly different every time the run is opened.

    Only positions sharing a row are compared, and within a row only those whose
    columns actually meet, so a large mosaic does not pay for comparing every
    position with every other.
    """
    rows: dict[int, list[_Block]] = {}
    for block in blocks:
        for row in range(block.begins[1], block.begins[1] + block.extent[1]):
            rows.setdefault(row, []).append(block)
    for crossing in rows.values():
        ordered = sorted(crossing, key=lambda block: block.begins[2])
        for at, block in enumerate(ordered):
            for other in ordered[at + 1:]:
                if other.begins[2] >= block.begins[2] + block.extent[2]:
                    break
                if (
                    other.begins[0] < block.begins[0] + block.extent[0]
                    and block.begins[0] < other.begins[0] + other.extent[0]
                ):
                    raise ZmartLiveError(
                        f"'{block.stored.array}' and '{other.stored.array}' both "
                        f"claim to supply the same piece of the view. Where two "
                        f"positions overlap, one of them has to give up the shared "
                        f"strip before the view is built — that is what placing a "
                        f"seam means — otherwise the picture depends on which of "
                        f"them happened to be found first."
                    )


# ---------------------------------------------------------------------------
# Handing the bytes over, and checking the view describes them properly
# ---------------------------------------------------------------------------


def the_bytes_of(serving: Serving) -> bytes:
    """Read exactly the stretch of bytes one piece of the view occupies.

    This is what a server hands to the viewer. Nothing is decoded, decompressed or
    copied into a new picture: the bytes come off the disk in the state the
    acquisition wrote them, and the viewer's own engine turns them back into
    pixels exactly as it would for an ordinary image.

    Raises :class:`~zmart_live.model.ZmartLiveError` when fewer bytes are there
    than the piece claims. That means the file has been truncated or is still
    being written, and handing over what was found would give the viewer a partly
    decoded chunk rather than an error.
    """
    with serving.path.open("rb") as opened:
        opened.seek(serving.offset)
        found = opened.read(serving.length)
    if len(found) != serving.length:
        raise ZmartLiveError(
            f"Only {len(found)} of the {serving.length} bytes of the piece at "
            f"{serving.inside_the_position} could be read from '{serving.path}'. "
            f"The file is shorter than its own table of contents says, so it was "
            f"either cut short or is still being written."
        )
    return found


def refuse_a_view_stored_differently(view_array: str | Path, route: ViewRoute) -> None:
    """Check that the view describes the bytes it is about to hand over.

    Everything the view says about itself was worked out from the positions a
    moment earlier, so this should never fail. It is asked anyway, because asking
    costs one small file read and being wrong costs a picture of noise that
    nothing anywhere reports.

    What is compared is what affects the bytes: the kind of number a pixel is, the
    shape of one chunk, what a chunk is compressed with, and what unimaged ground
    stands for. Names, labels and the size of the picture are not compared,
    because a view is larger than any of its positions by design and none of that
    changes how a byte is read.

    The one comparison worth reading twice is the last. A view on this route must
    **not** declare that it bundles its chunks, even though its positions do. What
    is handed over is a single chunk taken out of the middle of a bundle, so a
    view claiming to store bundles would be describing a container that is not
    there, and the viewer would try to read a table of contents out of a picture.
    """
    path = Path(view_array)
    content = _the_description_of(path)
    if content.get("zarr_format") != 3:
        raise ZmartLiveError(
            f"'{path}' is stored in Zarr format {content.get('zarr_format')}. A view "
            f"that points into bundled positions has to be written in format 3, "
            f"because that is the generation which describes both the chunk and the "
            f"codecs applied to it."
        )
    bundled = [
        codec
        for codec in content.get("codecs") or ()
        if isinstance(codec, dict) and codec.get("name") == "sharding_indexed"
    ]
    if bundled:
        raise ZmartLiveError(
            f"'{path}' declares that it bundles many chunks into one file, but this "
            f"view is served one chunk at a time out of the positions' bundles. A "
            f"reader would look for a table of contents where there is only a "
            f"picture. The view has to be declared with the positions' inner chunk "
            f"and no bundling of its own."
        )

    grid = (content.get("chunk_grid") or {}).get("configuration") or {}
    chunk = tuple(int(n) for n in grid.get("chunk_shape") or ())
    if chunk != route.storage.chunk:
        raise ZmartLiveError(
            f"'{path}' says one of its pieces is {chunk} pixels, and the positions "
            f"behind it hand over pieces of {route.storage.chunk}. The view would "
            f"place every piece it is given as though it were a different size, "
            f"which draws the specimen scrambled rather than reporting anything."
        )
    if str(content.get("data_type")) != route.storage.dtype:
        raise ZmartLiveError(
            f"'{path}' stores its pixels as {content.get('data_type')} and the "
            f"positions behind it as {route.storage.dtype}. Those bytes are handed "
            f"over untouched, so reading one as the other is a picture of noise."
        )
    if tuple(content.get("codecs") or ()) != route.storage.codecs:
        raise ZmartLiveError(
            f"'{path}' says its pieces are encoded as "
            f"{tuple(content.get('codecs') or ())} and the positions encode theirs "
            f"as {route.storage.codecs}. A view hands a position's bytes on exactly "
            f"as they are, so the two have to agree about how they were compressed."
        )
    if content.get("fill_value") != route.storage.fill_value:
        raise ZmartLiveError(
            f"'{path}' fills unimaged ground with {content.get('fill_value')} and "
            f"the positions behind it with {route.storage.fill_value}. Ground "
            f"nobody imaged would be drawn as though something had been."
        )

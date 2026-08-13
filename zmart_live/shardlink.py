"""Finding one small chunk inside a big bundled file, without unpacking it.

Why this exists
---------------

When a microscope writes a large image, it has a choice about how to lay the
pixels out on disk. The image is cut into *chunks* — small rectangular pieces,
perhaps 256 by 256 pixels — because a viewer that wants one corner of the
specimen should not have to read the whole plane to get it. That is good for
reading, but it is unkind to the file system: a single overnight run can easily
produce hundreds of thousands of little files, and most storage systems, backup
tools and network shares slow to a crawl long before that.

*Sharding* is the answer. A shard is one file that holds many chunks packed end
to end, with a small table at the back saying where each chunk starts and how
long it is. The file system sees a few large files; the viewer still gets its
individual chunks. Nothing about the picture changes — only the number of files.

The difficulty this module solves is what happens next. Our seamless quick-look
view does not copy pixels. It builds a *linked* view: a second, virtual image
whose chunks are not stored at all, but are described as "the same bytes that
already live over there". For that description to be writable, we have to be
able to say, for one chunk, exactly which file it lives in, at which byte, and
for how many bytes. Sharding hides that behind the packing, and this module
brings it back out.

The important thing is that nothing is decoded, recompressed or copied. We read
the little table, do some arithmetic, and hand back a byte range. The pixels stay
exactly where the acquisition put them.

What a shard file looks like inside
-----------------------------------

Laid out from the beginning of the file, a shard written by Zarr version 3 is:

* the encoded chunks, one after another, in whatever order they happened to be
  written — the order is *not* meaningful and must never be assumed;
* a table with one 16-byte entry per chunk position in the shard, each entry
  being two little-endian 8-byte numbers, the *offset* into the file and the
  *length* in bytes;
* a four-byte checksum guarding the table.

The table is normally at the end of the file, which is what lets a writer append
chunks as they arrive and only settle the table when the shard is closed. The
format also permits the table at the beginning, and both are supported here.

The table has an entry for *every* chunk position the shard could hold, whether
or not anything was written there. A position that was never written is marked
with the largest number an 8-byte field can hold, in both the offset and the
length. That is not damage; it is the ordinary way of saying "nothing here, this
region is the fill value", and it happens constantly at the edges of an image and
wherever the specimen was not imaged.

Entries are in row-major order over the chunk positions inside the shard. That
means the last axis varies fastest: for a shard holding two by two chunks, the
entries describe (0, 0), then (0, 1), then (1, 0), then (1, 1). Getting this
order wrong does not produce an error — it produces the wrong picture, quietly —
which is why it is stated here and checked by the tests.

Why the table is remembered, and how that stays safe
----------------------------------------------------

Reading the table is not free. One bundle written by the overview plan holds a
whole 1152-pixel frame across ninety-six planes, which is 7,776 chunk positions
and a table 124 kilobytes long, and every one of those entries has to be checked
before any chunk in the bundle can be pointed at. Filling one screen of the
viewer takes dozens of chunks, and nearly all of them come from the same few
bundles, so reading that same table dozens of times is most of what the viewer
was waiting for.

So a table that has been read is kept for a while. The danger in keeping anything
is obvious and it is worth saying out loud: a table that has gone out of date does
not produce an error. It produces a byte range that points somewhere real, decodes
perfectly, and shows a plausible picture of the wrong part of the specimen.

What makes it safe is that the table is remembered against the *identity of the
file it came from* — its path, together with the things about it that cannot stay
the same if it were written again: how large it is, when it last changed, and
which inode holds it. A bundle that has grown because the acquisition wrote more
chunks into it, or that has been replaced, no longer matches what was remembered,
so its table is read again. Only a file that is byte for byte the one already
looked at is answered from memory, which is what a committed bundle is: the
publication rules never rewrite one.

The memory has a limit, so that a run lasting all night cannot slowly fill it.
:data:`PLACES_REMEMBERED_AT_MOST` and :data:`BUNDLES_REMEMBERED_AT_MOST` say
what that limit is and explain how each was chosen.

What this module offers
-----------------------

:func:`describe_the_bundling`
    Reads an array's own description and reports how it is chunked and bundled,
    including the perfectly ordinary case of an array that is not sharded at all.

:func:`read_the_index`
    Parses the table out of one shard, so you can ask which chunks it holds.

:func:`where_one_chunk_lives`
    The question this module was written for: given an array and the coordinate
    of one chunk, which file, which byte, how many bytes.

:func:`how_the_array_is_stored`
    Reads an array's description once and hands back something that can answer
    that question many times without reading it again. Use this when you are
    about to ask about more than one chunk of the same array.

:func:`how_the_remembering_is_going`
    Reports how many tables were read from disk and how many were answered from
    memory, which is the honest way to tell whether the remembering is working.

:func:`forget_every_remembered_index`
    Empties the memory. Chiefly for tests, which need each one to start from the
    same place as every other.
"""

from __future__ import annotations

import json
import math
import operator
import os
from collections import OrderedDict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from struct import unpack_from
from threading import Lock

from .model import ZmartLiveError

__all__ = [
    "BUNDLES_REMEMBERED_AT_MOST",
    "Bundling",
    "Held",
    "INDEX_LOCATIONS",
    "PLACES_REMEMBERED_AT_MOST",
    "Remembering",
    "ShardIndex",
    "StoredArray",
    "describe_the_bundling",
    "forget_every_remembered_index",
    "how_the_array_is_stored",
    "how_the_remembering_is_going",
    "read_the_index",
    "where_one_chunk_lives",
]


#: The two places the format allows the table of contents to sit. ``"end"`` is
#: what almost everything writes, because it lets a shard grow while an
#: acquisition is still running and be finished off once at the close.
INDEX_LOCATIONS = ("end", "start")

#: Each entry in the table is two 8-byte numbers: where the chunk starts, and
#: how many bytes it occupies.
_BYTES_PER_ENTRY = 16

#: The table is followed (or, when the table is at the front, preceded from the
#: reader's point of view by nothing and followed immediately) by a four-byte
#: checksum over the table itself.
_BYTES_PER_CHECKSUM = 4

#: The marker meaning "no chunk was ever written at this position". It is simply
#: the largest value an unsigned 8-byte number can hold, used as a flag because
#: no real file is that long.
_NEVER_WRITTEN = 2**64 - 1


# ---------------------------------------------------------------------------
# The small records this module hands back
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Held:
    """Where one chunk's bytes physically are.

    This is the whole answer a linked view needs about a chunk: the file that
    holds it, how far into that file its first byte sits, and how many bytes to
    take. Reading exactly ``length`` bytes starting at ``offset`` gives back the
    chunk precisely as it was encoded, compression and all, so it can be handed
    on without being decoded first.

    The record cannot be edited once made, so a resolved location stays meaning
    what it meant when it was worked out.
    """

    path: Path
    offset: int
    length: int

    @property
    def stop(self) -> int:
        """The byte just past the end of the chunk, in the half-open style."""
        return self.offset + self.length


@dataclass(frozen=True)
class ShardIndex:
    """The table of contents read out of one shard file.

    A shard holds a fixed grid of chunk positions — ``chunks_per_shard`` says how
    many along each axis — and this record says, for every one of those
    positions, either where the chunk sits in the file or that nothing was ever
    written there.

    ``places`` is that answer in row-major order, the same order the format
    stores it in. You will rarely want to index into it directly; ask
    :meth:`place_of` with a chunk's position inside the shard instead, and let it
    do the arithmetic.

    ``shard_bytes`` is how large the file turned out to be. It is kept because it
    is what makes it possible to notice a shard that has been truncated: every
    chunk the table describes has to end inside the file it claims to live in.
    """

    chunks_per_shard: tuple[int, ...]
    places: tuple[tuple[int, int] | None, ...]
    shard_bytes: int
    index_location: str = "end"
    has_checksum: bool = True

    @property
    def entry_count(self) -> int:
        """How many chunk positions this shard has room for, written or not."""
        return len(self.places)

    @property
    def how_many_written(self) -> int:
        """How many of those positions actually hold data.

        A low number is not a fault. A shard sitting at the edge of an image, or
        one covering a part of the slide the run never visited, is expected to be
        mostly empty.
        """
        return sum(1 for place in self.places if place is not None)

    def position_of(self, within_shard: Sequence[int]) -> int:
        """Turn a chunk's position inside the shard into its place in the table.

        ``within_shard`` counts chunks, not pixels, and is measured from the
        shard's own corner: ``(0, 0)`` is the first chunk in the shard whatever
        part of the image that shard covers.

        Raises :class:`~zmart_live.model.ZmartLiveError` when the position names
        a different number of axes than the shard has, or falls outside it.
        """
        if len(within_shard) != len(self.chunks_per_shard):
            raise ZmartLiveError(
                f"This shard is arranged over {len(self.chunks_per_shard)} axes, but "
                f"the chunk position given names {len(within_shard)} of them "
                f"({tuple(within_shard)}). The position has to have one number per "
                f"axis, in the same order as the image's axes."
            )
        position = 0
        for extent, index in zip(self.chunks_per_shard, within_shard, strict=True):
            if not 0 <= index < extent:
                raise ZmartLiveError(
                    f"The chunk position {tuple(within_shard)} falls outside this "
                    f"shard, which holds {self.chunks_per_shard} chunks. Positions "
                    f"inside a shard are counted from that shard's own corner, so "
                    f"they always start again at zero for each shard."
                )
            position = position * extent + index
        return position

    def place_of(self, within_shard: Sequence[int]) -> tuple[int, int] | None:
        """The offset and length of one chunk, or ``None`` when it was never written.

        Getting ``None`` is a normal answer and not a problem. It means that
        region of the image holds the fill value, because nothing was ever
        recorded there.
        """
        return self.places[self.position_of(within_shard)]

    def holds(self, within_shard: Sequence[int]) -> bool:
        """True when there really is a chunk at that position inside the shard."""
        return self.place_of(within_shard) is not None

    def written_chunks(self) -> Iterator[tuple[tuple[int, ...], tuple[int, int]]]:
        """Walk every chunk the shard actually holds.

        Each step gives the chunk's position inside the shard and its offset and
        length, skipping the positions that were never written. This is the
        convenient way to describe a whole shard to a linked view in one pass.
        """
        for position, place in enumerate(self.places):
            if place is None:
                continue
            yield _unflatten(position, self.chunks_per_shard), place


@dataclass(frozen=True)
class Bundling:
    """How one array is cut into chunks, and whether those chunks are bundled.

    This is the plain answer to "what shape are the pieces of this image, and how
    are they stored", asked of an array on disk rather than of a plan on paper.

    ``sharded`` says whether chunks are packed together into larger files. When
    it is false the array is stored the straightforward way, one file per chunk,
    and ``shard_shape`` and ``chunks_per_shard`` are ``None`` because there are no
    bundles to describe. That is a perfectly good way to store an image and is
    reported as such rather than treated as a mistake.

    All the shapes are in pixels except ``chunks_per_shard``, which counts whole
    chunks. ``chunks_in_array`` counts chunks too, and says how far the chunk
    coordinates of this array are allowed to go on each axis.
    """

    array_path: Path
    array_shape: tuple[int, ...]
    inner_chunk: tuple[int, ...]
    chunks_in_array: tuple[int, ...]
    sharded: bool
    shard_shape: tuple[int, ...] | None = None
    chunks_per_shard: tuple[int, ...] | None = None
    index_location: str = "end"
    has_checksum: bool = True

    @property
    def chunks_per_shard_total(self) -> int:
        """How many chunks fit in one bundle, counting every axis together.

        This is also exactly how many entries the table in each shard file has,
        which is what makes it possible to find the table without searching for
        it. For an array that is not sharded it is one, since a file holds one
        chunk.
        """
        if self.chunks_per_shard is None:
            return 1
        return math.prod(self.chunks_per_shard)


# ---------------------------------------------------------------------------
# Small pieces of arithmetic, kept apart so they can be read on their own
# ---------------------------------------------------------------------------


def _unflatten(position: int, extents: Sequence[int]) -> tuple[int, ...]:
    """Undo the row-major flattening, turning a table place back into a position."""
    coordinate: list[int] = []
    for extent in reversed(extents):
        coordinate.append(position % extent)
        position //= extent
    return tuple(reversed(coordinate))


def _whole_numbers(values: Sequence[int], what: str) -> tuple[int, ...]:
    """Check that a shape is made of positive whole numbers, and return it as one."""
    try:
        result = tuple(operator.index(value) for value in values)
    except (TypeError, ValueError) as why:
        raise ZmartLiveError(
            f"The {what} must contain whole numbers; got {tuple(values)}. Rounding "
            "a shape or coordinate would silently select different pixels."
        ) from why
    for value in result:
        if value <= 0:
            raise ZmartLiveError(
                f"The {what} is given as {result}, but every axis has to be at least "
                f"one pixel across. A zero or negative size usually means the shape "
                f"was written in the wrong order or filled in from an empty setting."
            )
    return result


def _one_byte_of_checksum_at_a_time() -> tuple[int, ...]:
    """Work out, once, what the checksum does to each of the 256 possible bytes.

    A checksum of this kind is defined one *bit* at a time, and following that
    definition literally means eight turns of a loop for every byte of the table.
    On a 124-kilobyte table that is a million turns, and it was measured to be
    almost the entire cost of resolving a chunk.

    The eight steps for a given byte always end in the same place, so they can be
    worked out ahead of time and looked up instead. This builds that lookup when
    the module is first imported, which takes about a millisecond and is then done
    with. The answers it produces are identical to following the definition — the
    tests check exactly that against known values.
    """
    table: list[int] = []
    for byte in range(256):
        value = byte
        for _ in range(8):
            value = (value >> 1) ^ 0x82F63B78 if value & 1 else value >> 1
        table.append(value)
    return tuple(table)


_CHECKSUM_OF_EACH_BYTE = _one_byte_of_checksum_at_a_time()


def _crc32c(content: bytes) -> int:
    """The Castagnoli checksum used by Zarr's four-byte ``crc32c`` codec."""
    lookup = _CHECKSUM_OF_EACH_BYTE
    checksum = 0xFFFFFFFF
    for byte in content:
        checksum = lookup[(checksum ^ byte) & 0xFF] ^ (checksum >> 8)
    return (~checksum) & 0xFFFFFFFF


# ---------------------------------------------------------------------------
# Remembering the tables we have already read
# ---------------------------------------------------------------------------


#: How many chunk positions may be held in memory at once, across every bundle
#: remembered.
#:
#: A remembered table costs roughly a hundred and twenty bytes for each chunk
#: position that was actually written and eight for each that was not, so this
#: limit is worth about thirty megabytes in the worst case, where every position
#: in every remembered bundle holds data. That is the number to change if the
#: viewer is ever short of memory.
#:
#: It is counted in chunk positions rather than in bundles because bundles are not
#: all the same size. One bundle of the overview plan holds 7,776 positions, so
#: this is about thirty of them — comfortably more than the handful a screenful of
#: the viewer touches, and far short of the ten thousand positions a long run
#: reaches. The lesson behind that choice is written down in
#: ``viz_studio/LESSONS_ome_zarr_and_neuroglancer.md``: an index with an entry per
#: chunk, held for a whole run, was once sixteen gigabytes of memory.
PLACES_REMEMBERED_AT_MOST = 250_000

#: How many bundles may be remembered at once, whatever their size.
#:
#: The limit above would allow a quarter of a million tiny bundles, and each one
#: costs a few hundred bytes of bookkeeping even when its table is nearly empty.
#: This second limit keeps that in hand. Whichever limit is reached first, the
#: bundle nobody has asked about for longest is forgotten.
BUNDLES_REMEMBERED_AT_MOST = 256


@dataclass(frozen=True)
class Remembering:
    """How the remembering of shard tables is going.

    This is what to look at when you want to know whether keeping tables in
    memory is actually helping. ``read_from_disk`` counts the tables that had to
    be read and checked; ``answered_from_memory`` counts those that did not.

    Counts are given rather than timings on purpose. A timing on a busy machine
    tells you about the machine; a count tells you about the program, and is the
    same every time.
    """

    read_from_disk: int
    answered_from_memory: int
    bundles_held: int
    places_held: int
    # The same accounting for whole-array DESCRIPTIONS: a zarr.json is read
    # once per store and remembered against its file's identity. Publishing
    # one position at 12,769 committed used to re-read every position's
    # description -- 152,300 opens, thirty-three of a replacement's
    # forty-eight seconds -- to relearn what had not changed.
    descriptions_read_from_disk: int = 0
    descriptions_answered_from_memory: int = 0
    descriptions_held: int = 0


@dataclass(frozen=True)
class _WhichFileThisWas:
    """Enough about a shard file to be sure it is still the very same file.

    Remembering a table is only safe while the file it came from has not changed.
    Every one of these is something that cannot stay as it was if the file were
    written again: how large it is, when its contents last changed, when the file
    system last altered anything about it, and which inode — the file system's own
    numbered slot — is holding it. Comparing all of them together means a bundle
    that has grown, been replaced, or been swapped for a different file of the
    same length is recognised as a different file and read afresh.

    The shapes are part of it too. They come from the array's own description, and
    if that description were edited the same bytes on disk would have to be read as
    a different table. Including them costs nothing and removes a whole way of
    being quietly wrong.
    """

    path: str
    device: int
    inode: int
    size: int
    contents_changed_at: int
    file_changed_at: int
    inner_chunk: tuple[int, ...]
    shard_shape: tuple[int, ...]
    index_location: str
    has_checksum: bool


#: The tables already read, oldest-asked-for first, so the one to forget when the
#: limit is reached is simply the first.
_REMEMBERED: OrderedDict[_WhichFileThisWas, ShardIndex] = OrderedDict()
_PLACES_HELD = 0
_READ_FROM_DISK = 0
_ANSWERED_FROM_MEMORY = 0

#: Whole-array descriptions already read, by the array's path, each held with
#: the identity of the zarr.json it came from -- device, inode, size and both
#: timestamps, the shard tables' own rule -- so a description rewritten by the
#: writer is always read afresh. A description is a kilobyte or two, so even a
#: hundred-thousand-position survey fits comfortably under the limit.
DESCRIPTIONS_REMEMBERED_AT_MOST = 200_000
_DESCRIPTIONS: OrderedDict[str, tuple[tuple, "StoredArray"]] = OrderedDict()
_DESCRIPTIONS_READ = 0
_DESCRIPTIONS_FROM_MEMORY = 0

#: The viewer's own server answers several requests at the same time, on separate
#: threads, and they all share the memory above. Only the few lines that look
#: things up or put them away are held under this; the reading and checking of a
#: table, which is the slow part, deliberately happens outside it. Two threads
#: that both want the same new bundle will therefore read it twice, which wastes a
#: little work and is entirely safe. Doing it the other way round — holding the
#: lock while reading — would make every request wait for whichever one happened
#: to arrive first.
_ONE_AT_A_TIME = Lock()


def how_the_remembering_is_going() -> Remembering:
    """Report how many shard tables were read from disk and how many were not.

    Useful in a benchmark, and useful in a test: a test that wants to prove a
    table was not read a second time can watch this count rather than watch a
    clock, which is both quicker and steadier.
    """
    return Remembering(
        read_from_disk=_READ_FROM_DISK,
        answered_from_memory=_ANSWERED_FROM_MEMORY,
        bundles_held=len(_REMEMBERED),
        places_held=_PLACES_HELD,
        descriptions_read_from_disk=_DESCRIPTIONS_READ,
        descriptions_answered_from_memory=_DESCRIPTIONS_FROM_MEMORY,
        descriptions_held=len(_DESCRIPTIONS),
    )


def forget_every_remembered_index() -> None:
    """Empty the memory of shard tables, and reset the counts above.

    Nothing in ordinary use needs this: a table is forgotten by itself once its
    file changes or once the memory is full. It is here for tests, each of which
    has to start from the same place as every other, and for anybody who wants to
    measure the cost of reading a table cold.
    """
    global _PLACES_HELD, _READ_FROM_DISK, _ANSWERED_FROM_MEMORY
    global _DESCRIPTIONS_READ, _DESCRIPTIONS_FROM_MEMORY
    with _ONE_AT_A_TIME:
        _REMEMBERED.clear()
        _PLACES_HELD = 0
        _READ_FROM_DISK = 0
        _ANSWERED_FROM_MEMORY = 0
        _DESCRIPTIONS.clear()
        _DESCRIPTIONS_READ = 0
        _DESCRIPTIONS_FROM_MEMORY = 0


def _which_file_this_was(path: Path, settings: tuple) -> _WhichFileThisWas | None:
    """Take the identity of a shard file, or ``None`` if it cannot be looked at.

    A file that has just vanished, or that the acquisition has not written yet, is
    not an error here. It simply cannot be remembered against, and the caller goes
    on to read it and report whatever it finds.
    """
    try:
        about = os.stat(path)
    except OSError:
        return None
    inner_chunk, shard_shape, index_location, has_checksum = settings
    return _WhichFileThisWas(
        path=str(path),
        device=about.st_dev,
        inode=about.st_ino,
        size=about.st_size,
        contents_changed_at=about.st_mtime_ns,
        file_changed_at=about.st_ctime_ns,
        inner_chunk=inner_chunk,
        shard_shape=shard_shape,
        index_location=index_location,
        has_checksum=has_checksum,
    )


def _remember(which: _WhichFileThisWas, index: ShardIndex) -> None:
    """Keep one shard's table, forgetting older ones if the memory is now too full.

    When there is no room, what goes is whatever nobody has asked about for
    longest. A viewer looks at one part of the slide for a while, so the bundles
    it has just used are the ones it is about to use again, and keeping those is
    the whole benefit.
    """
    global _PLACES_HELD
    with _ONE_AT_A_TIME:
        already = _REMEMBERED.pop(which, None)
        if already is not None:
            _PLACES_HELD -= already.entry_count
        _REMEMBERED[which] = index
        _PLACES_HELD += index.entry_count
        while _REMEMBERED and (
            len(_REMEMBERED) > BUNDLES_REMEMBERED_AT_MOST
            or _PLACES_HELD > PLACES_REMEMBERED_AT_MOST
        ):
            _, forgotten = _REMEMBERED.popitem(last=False)
            _PLACES_HELD -= forgotten.entry_count


# ---------------------------------------------------------------------------
# Reading the table out of one shard
# ---------------------------------------------------------------------------


def read_the_index(
    shard: bytes | bytearray | memoryview | str | Path,
    *,
    inner_chunk: Sequence[int],
    shard_shape: Sequence[int],
    index_location: str = "end",
    has_checksum: bool = True,
    remember: bool = True,
) -> ShardIndex:
    """Read the table of contents out of a single shard file.

    What goes in
        ``shard`` is either the shard's bytes, already in memory, or the path to
        the shard file. Giving a path is usually better: only the few hundred
        bytes of the table are read, and the rest of the file — which can be
        hundreds of megabytes — is never touched.

        ``inner_chunk`` is the shape of one chunk in pixels, and ``shard_shape``
        is the shape of the whole bundle in pixels. Both come from the array's
        own description, which :func:`describe_the_bundling` reads for you.

        ``index_location`` says whether the table sits at the ``"end"`` of the
        file, which is usual, or at the ``"start"``. ``has_checksum`` says
        whether four bytes of checksum sit alongside it.

        ``remember`` decides whether a table read from a file may be kept for the
        next time the same unchanged file is asked about. Leaving it as it is, so
        that tables are kept, is what makes the viewer quick; turning it off is
        for measuring what reading one cold really costs. It has no effect when
        the shard is handed over as bytes, since there is then no file to notice a
        change in.

    What comes back
        A :class:`ShardIndex`: one answer per chunk position in the shard, each
        being either an offset and a length, or ``None`` for a position that was
        never written.

        The same table is never handed back for a file that has changed since it
        was read. See the note at the top of this module for how that is decided,
        and why a wrong answer here would be so hard to notice.

    What can go wrong
        A :class:`~zmart_live.model.ZmartLiveError` is raised when the bundle
        shape is not a whole number of chunks, when the file is too short to
        contain the table it should have, or when the table describes a chunk
        that would run off the end of the file. That last one is the check that
        catches a shard cut short by a full disk or an interrupted copy, and it
        matters: without it a truncated file would quietly yield a byte range
        that reads as plausible-looking nonsense.
    """
    global _READ_FROM_DISK, _ANSWERED_FROM_MEMORY

    if index_location not in INDEX_LOCATIONS:
        raise ZmartLiveError(
            f"'{index_location}' is not a place the table of contents can sit. It is "
            f"either at the '{INDEX_LOCATIONS[0]}' of the shard or at its "
            f"'{INDEX_LOCATIONS[1]}'."
        )

    inner = _whole_numbers(inner_chunk, "chunk shape")
    bundle = _whole_numbers(shard_shape, "bundle shape")
    if len(inner) != len(bundle):
        raise ZmartLiveError(
            f"The chunk shape {inner} and the bundle shape {bundle} describe different "
            f"numbers of axes. Both have to describe the same image, so they have to "
            f"have one number per axis."
        )

    chunks_per_shard: list[int] = []
    for axis, (bundle_size, chunk_size) in enumerate(zip(bundle, inner, strict=True)):
        if bundle_size % chunk_size != 0:
            raise ZmartLiveError(
                f"On axis {axis} the bundle is {bundle_size} pixels across but the "
                f"chunk inside it is {chunk_size}. A bundle has to hold a whole number "
                f"of chunks, so {bundle_size} must divide evenly by {chunk_size}. This "
                f"almost always means the chunk shape and the bundle shape have been "
                f"paired up from two different levels of the image pyramid."
            )
        chunks_per_shard.append(bundle_size // chunk_size)

    entries = math.prod(chunks_per_shard)
    table_bytes = entries * _BYTES_PER_ENTRY
    trailing = _BYTES_PER_CHECKSUM if has_checksum else 0

    # A shard given as a path can be remembered against; one given as bytes has
    # no file behind it to notice a change in, so it is simply read.
    was = None
    if remember and isinstance(shard, (str, Path)):
        was = _which_file_this_was(
            Path(shard), (inner, bundle, index_location, has_checksum)
        )
        if was is not None:
            with _ONE_AT_A_TIME:
                already_read = _REMEMBERED.get(was)
                if already_read is not None:
                    _REMEMBERED.move_to_end(was)
                    _ANSWERED_FROM_MEMORY += 1
                    return already_read
    _READ_FROM_DISK += 1

    shard_bytes, table = _read_the_table_bytes(shard, table_bytes, trailing, index_location)
    index_start = 0 if index_location == "start" else shard_bytes - table_bytes - trailing
    index_stop = table_bytes + trailing if index_location == "start" else shard_bytes

    places: list[tuple[int, int] | None] = []
    for entry in range(entries):
        offset, length = unpack_from("<QQ", table, entry * _BYTES_PER_ENTRY)
        if offset == _NEVER_WRITTEN and length == _NEVER_WRITTEN:
            places.append(None)
            continue
        if offset == _NEVER_WRITTEN or length == _NEVER_WRITTEN:
            raise ZmartLiveError(
                f"Entry {entry} of this shard's table of contents is half marked as "
                f"never written (offset {offset}, length {length}). A chunk is either "
                f"recorded properly or marked absent in both numbers, so this file has "
                f"been damaged and should not be read."
            )
        overlaps_index = offset < index_stop and offset + length > index_start
        if length == 0 or offset + length > shard_bytes or overlaps_index:
            raise ZmartLiveError(
                f"This shard's table of contents claims a chunk running from byte "
                f"{offset} for {length} bytes, but the file is only {shard_bytes} "
                f"bytes long and its index occupies bytes {index_start} to "
                f"{index_stop}. A chunk must be non-empty, end inside the file, and "
                f"not overlap the index. The shard is damaged — most often cut "
                f"short by a full disk or interrupted copy — and needs writing "
                f"again from the source data."
            )
        places.append((int(offset), int(length)))

    occupied = sorted(place for place in places if place is not None)
    for before, after in zip(occupied, occupied[1:], strict=False):
        before_offset, before_length = before
        after_offset, _ = after
        if before_offset + before_length > after_offset:
            raise ZmartLiveError(
                "Two entries in this shard's table point at overlapping bytes. "
                "Distinct chunks cannot occupy the same encoded data, so serving "
                "either range could show pixels belonging to its neighbour."
            )

    index = ShardIndex(
        chunks_per_shard=tuple(chunks_per_shard),
        places=tuple(places),
        shard_bytes=shard_bytes,
        index_location=index_location,
        has_checksum=has_checksum,
    )

    # Look at the file once more before keeping anything. If the acquisition wrote
    # into the bundle while we were reading it, what we have just parsed does not
    # belong to either version of the file, and remembering it under the identity
    # taken beforehand would go on being wrong until the file changed again. The
    # table is still returned — it is the best answer available for a file that is
    # moving underneath us, and the same answer this function has always given —
    # but it is not kept.
    if was is not None and _which_file_this_was(
        Path(shard), (inner, bundle, index_location, has_checksum)  # type: ignore[arg-type]
    ) == was:
        _remember(was, index)
    return index


def _read_the_table_bytes(
    shard: bytes | bytearray | memoryview | str | Path,
    table_bytes: int,
    trailing: int,
    index_location: str,
) -> tuple[int, bytes]:
    """Fetch just the table out of a shard, however the shard was handed to us.

    Returns how long the whole shard is and the raw bytes of its table. Reading
    only this much is what keeps resolving a chunk cheap: a shard can be very
    large, and the table is a few hundred bytes near one of its ends.
    """
    if index_location == "start":
        table_starts_at = 0
    else:
        table_starts_at = -(table_bytes + trailing)

    if isinstance(shard, (str, Path)):
        path = Path(shard)
        try:
            shard_bytes = path.stat().st_size
        except OSError as problem:
            raise ZmartLiveError(
                f"The shard file '{path}' could not be looked at: {problem}. If the "
                f"acquisition is still running, this chunk may simply not have been "
                f"written yet."
            ) from problem
        _refuse_a_shard_that_is_too_short(str(path), shard_bytes, table_bytes, trailing)
        begins_at = table_starts_at if table_starts_at >= 0 else shard_bytes + table_starts_at
        with path.open("rb") as opened:
            opened.seek(begins_at)
            encoded_index = opened.read(table_bytes + trailing)
    else:
        raw = bytes(shard)
        shard_bytes = len(raw)
        _refuse_a_shard_that_is_too_short("shard", shard_bytes, table_bytes, trailing)
        begins_at = table_starts_at if table_starts_at >= 0 else shard_bytes + table_starts_at
        encoded_index = raw[begins_at : begins_at + table_bytes + trailing]

    if len(encoded_index) != table_bytes + trailing:
        raise ZmartLiveError(
            f"Only {len(encoded_index)} bytes of the shard's "
            f"{table_bytes + trailing}-byte encoded table of "
            f"contents could be read. The file is shorter than it says it is, which "
            f"means it was not finished being written."
        )
    table = encoded_index[:table_bytes]
    if trailing:
        expected = int.from_bytes(encoded_index[table_bytes:], "little")
        actual = _crc32c(table)
        if actual != expected:
            raise ZmartLiveError(
                f"The shard index's CRC32C checksum is 0x{expected:08x}, but its "
                f"contents calculate to 0x{actual:08x}. The table has changed or "
                "been damaged, so none of its byte ranges can be trusted."
            )
    return shard_bytes, table


def _refuse_a_shard_that_is_too_short(
    described_as: str, shard_bytes: int, table_bytes: int, trailing: int
) -> None:
    """Stop early when a file is plainly too small to be the shard we expect.

    A shard has to be at least as long as its own table of contents. When it is
    not, reading on would take whatever bytes happened to be there and hand back
    a byte range that looks perfectly reasonable and points at rubbish, so it is
    much better to refuse here.
    """
    if shard_bytes < table_bytes + trailing:
        raise ZmartLiveError(
            f"The shard '{described_as}' is {shard_bytes} bytes long, but its table of "
            f"contents alone should take {table_bytes + trailing} bytes. Either the "
            f"file is still being written, or it has been truncated, or the chunk and "
            f"bundle shapes being used to read it do not belong to this array."
        )


# ---------------------------------------------------------------------------
# Reading an array's own description
# ---------------------------------------------------------------------------


def _read_the_array_description(array_path: str | Path) -> tuple[Path, dict]:
    """Open an array's ``zarr.json`` and check it really describes an array.

    Every Zarr version 3 array keeps a small file called ``zarr.json`` beside its
    data, saying what shape it is, how it is chunked and how it is encoded. That
    file is the only trustworthy source for how to read the shards, so everything
    here starts from it rather than from anything guessed off the folder.
    """
    path = Path(array_path)
    description = path / "zarr.json"
    if not description.is_file():
        raise ZmartLiveError(
            f"No 'zarr.json' was found in '{path}', so there is nothing there saying "
            f"how the image is stored. Check that this path points at a single image "
            f"array and not at the group or the run folder above it."
        )
    try:
        content = json.loads(description.read_text(encoding="utf-8"))
    except (OSError, ValueError) as problem:
        raise ZmartLiveError(
            f"The description at '{description}' could not be read: {problem}. Without "
            f"it there is no way to know how this image is chunked."
        ) from problem

    if not isinstance(content, dict):
        raise ZmartLiveError(
            f"The description at '{description}' is valid JSON but is not a table "
            "of array metadata."
        )
    if content.get("node_type") != "array":
        raise ZmartLiveError(
            f"'{path}' describes a {content.get('node_type', 'thing of unknown kind')} "
            f"rather than an image array. Linked views are made from arrays, so this "
            f"should point at one level of one image."
        )
    if content.get("zarr_format") != 3:
        raise ZmartLiveError(
            f"'{path}' is stored in Zarr format {content.get('zarr_format')}. Bundling "
            f"chunks into shards only exists from format 3 onwards, so this array "
            f"cannot be read that way."
        )
    if content.get("storage_transformers"):
        raise ZmartLiveError(
            f"'{path}' declares storage transformers "
            f"({content['storage_transformers']}), which rearrange the bytes on disk in "
            f"ways this resolver does not know about. A linked view cannot safely point "
            f"into it."
        )
    return path, content


def _the_sharding_settings(content: dict) -> dict | None:
    """Pick the bundling settings out of an array's list of codecs, if there are any.

    An array's ``codecs`` list says what is done to the pixels on their way to
    disk. When chunks are bundled, one entry in that list is named
    ``sharding_indexed`` and carries the bundling settings inside it. When no such
    entry is there, the array simply stores one chunk per file.
    """
    found = [
        codec
        for codec in content.get("codecs", ()) or ()
        if isinstance(codec, dict) and codec.get("name") == "sharding_indexed"
    ]
    if not found:
        return None
    if len(found) > 1:
        raise ZmartLiveError(
            "The array declares more than one sharding codec. There is no single "
            "bundle geometry or index to resolve safely."
        )
    settings = found[0].get("configuration", {}) or {}
    if not isinstance(settings, dict):
        raise ZmartLiveError("The sharding codec's configuration is not a table.")
    return settings


def _index_has_a_supported_encoding(path: Path, settings: dict) -> bool:
    """Validate the fixed little-endian index chain and report CRC32C use."""
    codecs = settings.get("index_codecs")
    if not isinstance(codecs, list) or not codecs:
        raise ZmartLiveError(
            f"'{path}' does not declare how its shard index is encoded. The Zarr "
            "sharding specification requires one array-to-bytes index codec."
        )
    names = [codec.get("name") if isinstance(codec, dict) else None for codec in codecs]
    if names[0] != "bytes":
        raise ZmartLiveError(
            f"'{path}' encodes its shard index with {names}. This resolver supports "
            "the standard bytes codec followed optionally by CRC32C; treating any "
            "other bytes as uint64 offsets would point at the wrong pixels."
        )
    configuration = codecs[0].get("configuration", {}) or {}
    if not isinstance(configuration, dict) or configuration.get("endian") != "little":
        raise ZmartLiveError(
            f"'{path}' does not encode its shard offsets as little-endian numbers. "
            "This resolver will not guess their byte order."
        )
    remaining = names[1:]
    if remaining not in ([], ["crc32c"]):
        raise ZmartLiveError(
            f"'{path}' applies unsupported shard-index codecs {remaining}. Serving "
            "the undecoded bytes as offsets would select the wrong chunks."
        )
    return remaining == ["crc32c"]


def describe_the_bundling(array_path: str | Path) -> Bundling:
    """Report how an image array on disk is chunked, and how it is bundled.

    What goes in
        The path to one array — one level of one image — being the folder that
        holds a ``zarr.json`` file.

    What comes back
        A :class:`Bundling` saying the array's shape, the shape of one chunk, how
        many chunks the array holds along each axis, and whether those chunks are
        packed into shards. An array that is stored one chunk per file is
        reported with ``sharded`` set to false, which is an ordinary answer and
        not a failure.

    What can go wrong
        A :class:`~zmart_live.model.ZmartLiveError` is raised when the path does
        not hold an array description, when that description is in an older
        format that cannot bundle chunks, or when the bundle it declares is not a
        whole number of chunks across.
    """
    return _the_bundling_of(*_read_the_array_description(array_path))


def _the_bundling_of(path: Path, content: dict) -> Bundling:
    """Work out the bundling from a description that has already been read.

    :func:`describe_the_bundling` reads the description and calls this. Resolving
    a chunk needs both the bundling and a couple of other things out of the same
    description, so keeping the two steps apart lets it read the file once rather
    than twice — which matters when a linked view is resolving many thousands of
    chunks in a row.
    """
    grid = content.get("chunk_grid", {}) or {}
    if grid.get("name") != "regular":
        raise ZmartLiveError(
            f"'{path}' lays its chunks out on a '{grid.get('name')}' grid. Only the "
            f"regular grid — every chunk the same size — can be resolved to byte "
            f"ranges, because anything else has no fixed arithmetic from a chunk "
            f"coordinate to a place in a file."
        )

    try:
        array_shape = _whole_numbers(content["shape"], "image shape")
        grid_chunk = _whole_numbers(grid["configuration"]["chunk_shape"], "stored chunk shape")
    except (KeyError, TypeError) as why:
        raise ZmartLiveError(
            f"'{path}' does not contain a complete regular chunk-grid description."
        ) from why
    if len(array_shape) != len(grid_chunk):
        raise ZmartLiveError(
            f"'{path}' has {len(array_shape)} array axes but a chunk shape over "
            f"{len(grid_chunk)} axes."
        )

    settings = _the_sharding_settings(content)
    if settings is None:
        # Nothing is bundled here: the grid's chunk is the chunk, and each one
        # sits in a file of its own. This is a completely normal way to store a
        # small image, and it is reported rather than treated as a problem.
        return Bundling(
            array_path=path,
            array_shape=array_shape,
            inner_chunk=grid_chunk,
            chunks_in_array=_grid_extent(array_shape, grid_chunk),
            sharded=False,
        )

    try:
        inner_chunk = _whole_numbers(settings["chunk_shape"], "chunk shape inside the bundle")
    except (KeyError, TypeError) as why:
        raise ZmartLiveError(
            f"'{path}' does not say how large an inner chunk is on every axis."
        ) from why
    if len(inner_chunk) != len(grid_chunk):
        raise ZmartLiveError(
            f"'{path}' has a {len(grid_chunk)}-axis shard but a "
            f"{len(inner_chunk)}-axis inner chunk."
        )
    index_location = str(settings.get("index_location", "end"))
    if index_location not in INDEX_LOCATIONS:
        raise ZmartLiveError(
            f"'{path}' says its table of contents sits at '{index_location}', which is "
            f"not one of the two places the format allows "
            f"({' or '.join(INDEX_LOCATIONS)})."
        )
    has_checksum = _index_has_a_supported_encoding(path, settings)

    chunks_per_shard: list[int] = []
    for axis, (bundle_size, chunk_size) in enumerate(zip(grid_chunk, inner_chunk, strict=True)):
        if bundle_size % chunk_size != 0:
            raise ZmartLiveError(
                f"In '{path}', axis {axis} is bundled {bundle_size} pixels at a time but "
                f"chunked {chunk_size} pixels at a time, and {bundle_size} does not "
                f"divide evenly by {chunk_size}. The file's own description is "
                f"inconsistent, so nothing can be resolved out of it."
            )
        chunks_per_shard.append(bundle_size // chunk_size)

    return Bundling(
        array_path=path,
        array_shape=array_shape,
        inner_chunk=inner_chunk,
        chunks_in_array=_grid_extent(array_shape, inner_chunk),
        sharded=True,
        shard_shape=grid_chunk,
        chunks_per_shard=tuple(chunks_per_shard),
        index_location=index_location,
        has_checksum=has_checksum,
    )


def _grid_extent(array_shape: Sequence[int], chunk: Sequence[int]) -> tuple[int, ...]:
    """How many chunks it takes to cover the image along each axis.

    The last chunk on an axis is usually not full — an image 300 pixels wide cut
    into 128-pixel chunks needs three of them, and the third only holds 44 real
    pixels. It still counts as a whole chunk, because that is how it is stored.
    """
    return tuple(-(-int(size) // int(step)) for size, step in zip(array_shape, chunk, strict=True))


# ---------------------------------------------------------------------------
# Working out which file holds a chunk
# ---------------------------------------------------------------------------


def _chunk_file(array_path: Path, content: dict, coordinate: Sequence[int]) -> Path:
    """Work out the file name a stored chunk has, from the array's naming rules.

    An array says how it names its chunk files. The usual modern rule puts them
    in nested folders under a ``c``, so the chunk at row 1, column 2 of a
    two-dimensional image is the file ``c/1/2``. The older rule writes the
    numbers joined by a dot into a single name, ``1.2``. Both are read here,
    because data written by other tools may use either.
    """
    encoding = content.get("chunk_key_encoding", {}) or {}
    name = encoding.get("name", "default")
    settings = encoding.get("configuration", {}) or {}
    numbers = [str(int(index)) for index in coordinate]

    if name == "default":
        separator = str(settings.get("separator", "/"))
        if separator not in ("/", "."):
            raise ZmartLiveError(
                f"'{array_path}' declares {separator!r} as its chunk-key separator. "
                "Only '/' and '.' are Zarr separators; accepting path punctuation "
                "here could resolve a chunk outside its array folder."
            )
        key = separator.join(["c", *numbers]) if numbers else "c"
    elif name == "v2":
        separator = str(settings.get("separator", "."))
        if separator not in ("/", "."):
            raise ZmartLiveError(
                f"'{array_path}' declares {separator!r} as its chunk-key separator. "
                "Only '/' and '.' are safe Zarr separators."
            )
        key = separator.join(numbers) if numbers else "0"
    else:
        raise ZmartLiveError(
            f"'{array_path}' names its chunk files by a rule called '{name}', which is "
            f"not one this resolver knows. Without knowing the naming rule there is no "
            f"way to say which file a chunk lives in."
        )
    return array_path.joinpath(*key.split("/"))


class StoredArray:
    """One image array whose own description has already been read.

    Asking where a chunk lives means knowing two things: how the array is chunked
    and bundled, and what it calls its files. Both come out of the array's
    ``zarr.json``, and both are settled for as long as the array exists. Reading
    that file again for every chunk therefore buys nothing, and a viewer filling
    one screen asks about dozens of chunks of the same array in a row.

    So this reads it once. Build one with :func:`how_the_array_is_stored`, then
    ask it :meth:`where_one_chunk_lives` as many times as you like.

    This holds no pixels and no tables of contents. Those are looked after
    separately, and are refreshed whenever the file they came from changes, so a
    :class:`StoredArray` kept for a whole run still gives correct answers about a
    position the acquisition is still writing into.

    Attributes:
        path: the folder of the array this was read from.
        bundling: how the array is chunked and bundled, exactly as
            :func:`describe_the_bundling` reports it.
        description: everything the array's ``zarr.json`` said, for the sake of
            callers that need more of it than the bundling — what a pixel is, what
            a chunk is compressed with. Read it rather than changing it: the
            bundling above was worked out from it and would not follow a change.
    """

    def __init__(self, path: Path, description: dict) -> None:
        self.path = path
        self.description = description
        self.bundling = _the_bundling_of(path, description)

    def where_one_chunk_lives(self, chunk_coordinate: Sequence[int]) -> Held | None:
        """Say which file holds one chunk, at which byte, and for how many bytes.

        This is the same question :func:`where_one_chunk_lives` answers, and it
        gives the same answer; the only difference is that the array's description
        has already been read, so asking is cheap enough to do it for every piece
        of a screenful.
        """
        return _where_one_chunk_lives(
            self.path, self.description, self.bundling, chunk_coordinate
        )


def how_the_array_is_stored(array_path: str | Path) -> StoredArray:
    """Read one array's description once, ready to be asked about many chunks.

    What goes in
        The path to one array — one level of one image — being the folder that
        holds a ``zarr.json`` file.

    What comes back
        A :class:`StoredArray`. Its ``bundling`` says how the array is chunked and
        bundled, exactly as :func:`describe_the_bundling` would, and its
        :meth:`~StoredArray.where_one_chunk_lives` answers for any chunk of it.

    What can go wrong
        The same things that can go wrong in :func:`describe_the_bundling`: the
        path may hold no array description, or one written in a format whose
        chunks cannot be resolved to byte ranges.

    The answer is remembered against the identity of the ``zarr.json`` it came
    from -- device, inode, size and both timestamps, the shard tables' own rule
    -- so asking about the same unchanged array again costs a ``stat``, and a
    description the writer rewrote is always read afresh. Two threads racing a
    new array both read it, exactly as they do a new shard table, which wastes
    a little work and is entirely safe.
    """
    global _DESCRIPTIONS_READ, _DESCRIPTIONS_FROM_MEMORY
    path = Path(array_path)
    mark = None
    try:
        stamp = (path / "zarr.json").stat()
        mark = (stamp.st_dev, getattr(stamp, "st_ino", 0), stamp.st_size,
                stamp.st_mtime_ns, stamp.st_ctime_ns)
    except OSError:
        pass  # unreadable is _read_the_array_description's error to explain
    key = str(path)
    if mark is not None:
        with _ONE_AT_A_TIME:
            held = _DESCRIPTIONS.get(key)
            if held is not None and held[0] == mark:
                _DESCRIPTIONS.move_to_end(key)
                _DESCRIPTIONS_FROM_MEMORY += 1
                return held[1]
    made = StoredArray(*_read_the_array_description(path))
    if mark is not None:
        with _ONE_AT_A_TIME:
            _DESCRIPTIONS_READ += 1
            _DESCRIPTIONS[key] = (mark, made)
            _DESCRIPTIONS.move_to_end(key)
            while len(_DESCRIPTIONS) > DESCRIPTIONS_REMEMBERED_AT_MOST:
                _DESCRIPTIONS.popitem(last=False)
    return made


def where_one_chunk_lives(array_path: str | Path, chunk_coordinate: Sequence[int]) -> Held | None:
    """Say which file holds one chunk, at which byte, and for how many bytes.

    This is the question a linked view asks, once per chunk it wants to advertise.
    The answer lets it describe that chunk as a byte range in an existing file,
    so the pixels never have to be read, decoded or copied to be shown somewhere
    else.

    What goes in
        ``array_path`` is the folder of one image array. ``chunk_coordinate``
        counts *chunks*, not pixels, from the corner of the whole image: for an
        image chunked 128 pixels at a time, the chunk covering pixel rows 256 to
        383 and columns 0 to 127 is at coordinate ``(2, 0)``.

    What comes back
        A :class:`Held` giving the file, the offset and the length — or ``None``
        when that chunk was never written. ``None`` is an ordinary answer: it
        means the region holds the array's fill value, which is what happens
        wherever the run has not imaged anything, and a linked view should simply
        not advertise a chunk there.

        For an array that is not bundled, the answer is the whole of the chunk's
        own file: offset zero, and a length equal to the file's size.

    What can go wrong
        A :class:`~zmart_live.model.ZmartLiveError` is raised when the coordinate
        names the wrong number of axes or points outside the image, and when the
        shard holding it turns out to be damaged or cut short. A chunk that is
        merely absent never raises; it comes back as ``None``.

    A note on asking many times
        This reads the array's description afresh on every call, which is right
        for asking about one chunk and wasteful for asking about a hundred. When
        you are about to ask repeatedly about the same array, read it once with
        :func:`how_the_array_is_stored` and ask that instead.
    """
    return how_the_array_is_stored(array_path).where_one_chunk_lives(chunk_coordinate)


def _where_one_chunk_lives(
    path: Path,
    content: dict,
    bundling: Bundling,
    chunk_coordinate: Sequence[int],
) -> Held | None:
    """The arithmetic behind both ways of asking, once the description is in hand."""
    try:
        coordinate = tuple(operator.index(index) for index in chunk_coordinate)
    except (TypeError, ValueError) as why:
        raise ZmartLiveError(
            f"Chunk coordinate {tuple(chunk_coordinate)} is not made of whole "
            "numbers. Rounding it would silently select another chunk."
        ) from why
    if len(coordinate) != len(bundling.chunks_in_array):
        raise ZmartLiveError(
            f"This image is arranged over {len(bundling.chunks_in_array)} axes, but the "
            f"chunk coordinate given names {len(coordinate)} of them ({coordinate}). "
            f"The coordinate needs one number per axis, in the image's own axis order."
        )
    for axis, (index, extent) in enumerate(zip(coordinate, bundling.chunks_in_array, strict=True)):
        if not 0 <= index < extent:
            raise ZmartLiveError(
                f"Chunk coordinate {coordinate} asks for chunk {index} along axis "
                f"{axis}, but this image only has {extent} chunks there (it is "
                f"{bundling.array_shape[axis]} pixels across, chunked "
                f"{bundling.inner_chunk[axis]} at a time). Remember that chunk "
                f"coordinates count chunks rather than pixels."
            )

    if not bundling.sharded:
        # One chunk to a file, so the chunk is simply the whole file. A missing
        # file means the chunk was never written, exactly as an empty entry does
        # in a bundled array.
        file = _chunk_file(path, content, coordinate)
        if not file.is_file():
            return None
        return Held(path=file, offset=0, length=file.stat().st_size)

    # From here on the array is bundled, so it has said how many chunks fit in a
    # bundle. The chunk's coordinate splits into two parts: which bundle it is
    # in, found by dividing, and where it sits inside that bundle, found by
    # taking the remainder. Positions inside a bundle always start again at zero.
    shard_coordinate = tuple(
        index // per_shard
        for index, per_shard in zip(coordinate, bundling.chunks_per_shard, strict=True)
    )
    within_shard = tuple(
        index % per_shard
        for index, per_shard in zip(coordinate, bundling.chunks_per_shard, strict=True)
    )

    shard_file = _chunk_file(path, content, shard_coordinate)
    if not shard_file.is_file():
        # The whole bundle is absent, so every chunk in it is absent too. This is
        # normal for a region of the slide the run has not reached yet.
        return None

    index = read_the_index(
        shard_file,
        inner_chunk=bundling.inner_chunk,
        shard_shape=bundling.shard_shape,
        index_location=bundling.index_location,
        has_checksum=bundling.has_checksum,
    )
    place = index.place_of(within_shard)
    if place is None:
        return None
    offset, length = place
    return Held(path=shard_file, offset=offset, length=length)

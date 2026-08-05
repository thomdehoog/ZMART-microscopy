"""Answering for a picture that was never written down.

An acquisition can be shown to the viewer as one image without any of it being
copied into one. The tiles stay exactly where the microscope wrote them, and a
small file beside them says which piece of the picture is which piece of which
tile. :mod:`zmart_storage.linked` is what builds such a view; this is the half
that answers for it while the viewer is open.

There is very little to it, and that is the point. When the browser asks for a
piece of the full-size picture, there is no file at that address — so this looks
the piece up in the list of pointers, works out which file already holds those
exact bytes, and the server hands that file over unchanged. Nothing is assembled,
nothing is decompressed, and no arithmetic is done on a single pixel.

The list is written by :mod:`zmart_storage.linked` under the name
``zmart-links.json`` inside the view's own folder. Its shape is::

    {
      "version": 2,
      "level": "0",            which copy of the picture is pointed at
      "separator": "/",        what goes between the numbers of a piece's name
      "prefix": "",            what goes in front of them ("c" for zarr version 3)
      "tiles": [
        {"store": "overview_tiles/overview_pos00000.ome.zarr",
         "at":   [0, 0, 0],    where this tile's pieces begin in the view
         "size": [2, 1, 1],    how many of them it supplies
         "from": [0, 0, 0],    which of its own pieces the first of them is
         "held_as": "file"}    how one of its pieces is stored
      ]
    }

Everything in it is counted in **pieces** rather than voxels, which is why nothing
here has to know how large a piece is. ``at``, ``size`` and ``from`` are given as
``(z, y, x)``; the moment and the colour are not mentioned at all, because a view
keeps its tiles' moments and colours exactly as they are and those numbers pass
straight through. Where a tile lives is written down relative to the folder the
view itself sits in, which is the same folder the viewer serves the view from — so
a pointer is an ordinary address inside the opened folder and needs no special
treatment to be safe.

What a pointer resolves to, and why it is a stretch of bytes
------------------------------------------------------------

Asking where a piece really is gives back three things rather than one: **a file, a
place in it, and how many bytes**. For the stores this reads today the answer is
always the whole of the file — a piece of an ordinary zarr image *is* a file — so
the place is nought and the length is "to the end".

Saying it as a stretch of bytes anyway is what lets this grow. A **sharded** store
keeps many pieces inside one larger file, with a small index saying where each of
them begins; a piece of it is then a stretch in the middle of that file rather than
a file of its own. Formats that are not zarr at all — a TIFF stack, an HDF5 file —
are the same shape of problem, and the established tools for describing them
(Kerchunk, VirtualiZarr) record exactly this triple for the same reason. Answering
in the general shape now means those become a change to what writes the list rather
than a change to everything that reads it.

**What is deliberately not done is recording a stretch for every piece.** That is
how those tools store it, and at the size of run this project is built for it does
not fit: the note below on holding the list by tile works through how ten thousand
tiles become tens of gigabytes that way. So the list still says how a *tile* is
stored, once, and the stretch for any one of its pieces is worked out from that.

Two things this deliberately does not do. It never answers for ground no tile
covers — such a piece is simply not in the list, and the server then answers "there
is nothing here" exactly as it does for a run that has not written that part yet,
which is the ordinary case rather than an error. And it never reaches outside the
folder the operator opened: every pointer is handed back as a path *relative* to
that folder and resolved by the library, so the same guard that protects every
other request protects these.
"""

from __future__ import annotations

import json
import threading
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path

# The file, inside a view's own folder, that holds the list of pointers. The same
# name is written down in ``zmart_storage/linked.py``, which writes the file; the
# two have to be changed together.
LINKS_FILE = "zmart-links.json"

# The shape of that file this reader understands. A file saying anything else is
# ignored rather than guessed at, because guessing wrongly would draw one tile's
# picture in another tile's place with nothing on screen to say so.
LINKS_VERSION = 3

# Shapes this reader still understands from before. Version 1 said nothing about
# how a tile's pieces are stored because there was only one way they could be —
# each piece its own file — so it is read as though it had said so. Version 2 is
# version 3 without the companion file below, and a view written that way simply
# never has one.
LINKS_VERSIONS_UNDERSTOOD = (1, 2, 3)

# The companion file a run still being acquired adds its tiles to, one line each.
#
# A view built from a finished run has none of this: every tile is in the list
# itself. But a run still on the microscope adds a tile at a time, and rewriting
# the whole list for each of them costs more the longer the run goes on — measured
# at 89 milliseconds for one tile once a view held six thousand four hundred. So
# the writer adds a line to the end of this file instead, and the tiles are taken
# from both. When the run finishes the lines are folded back into the list and this
# file goes away, which is why most views never have one.
LINKS_ADDED_FILE = "zmart-links-added.jsonl"

# The ways a tile can keep one of its pieces. Only the plain one is read today; a
# name not in here is refused rather than guessed at, because guessing would hand
# the viewer bytes from the wrong part of a file and it would draw them.
HELD_AS_A_FILE = "file"


@dataclass(frozen=True)
class Held:
    """Where a piece of the picture really is: a file, a place in it, and a length.

    Attributes:
        path: the file holding those bytes, written relative to the folder the
            viewer was opened on.
        offset: how far into that file the piece begins. Nought for an ordinary
            zarr image, where a piece is the whole file.
        length: how many bytes the piece is, or ``None`` for "the rest of the
            file" — which is again the ordinary case.
    """

    path: str
    offset: int = 0
    length: int | None = None

    @property
    def is_the_whole_file(self) -> bool:
        """Whether these bytes are simply all of the file, which is the usual case."""
        return self.offset == 0 and self.length is None


class _WhereThePiecesReallyAre:
    """One view's pointers, held as the tiles themselves rather than piece by piece.

    The file on disk lists each tile once, saying which block of the view's pieces
    it supplies. That is short: ten thousand tiles are ten thousand lines.

    It is tempting to spread that out into a lookup holding every piece, so a
    request can be answered in a single step, and an earlier version of this did
    exactly that. It does not survive a real run. A tile 2048 voxels across, kept in
    pieces of 128, is sixteen by sixteen pieces — multiply that by its planes, its
    colours and its moments, then by ten thousand tiles, and a list that was a few
    megabytes on disk becomes tens of gigabytes in memory. The tests never showed it
    because test tiles are small.

    So each tile is remembered once, and the only thing spread out is a note of
    which **rows** of the picture it reaches into. A picture is a grid of pieces;
    each row of that grid holds a note of the tiles crossing it, and there are as
    many notes per tile as it is pieces tall — sixteen, in the example above, rather
    than twenty-five thousand. Finding a piece then means looking in one row and
    checking the few tiles there, which is quick, and the memory stays in proportion
    to the number of tiles.
    """

    def __init__(self, listed: dict) -> None:
        self.level = str(listed.get("level", "0"))
        # How many copies of the picture are pointed at, counting the full-size
        # one. A view over tiles that carry their own zoomed-out copies points at
        # those as well, so that nothing of the picture is written at any zoom.
        self.pointed_levels = max(1, int(listed.get("pointed_levels", 1) or 1))
        self.separator = str(listed.get("separator") or "/")
        self.prefix = str(listed.get("prefix") or "")
        # For each row of the picture's grid of pieces, the tiles that cross it.
        # A tile is held as (where it begins, how many pieces, which of its own
        # pieces the first one is, which folder it is in) — all counted in pieces
        # and given as (z, y, x) — and the same tuple is shared by every row it
        # appears in rather than copied into each.
        self._rows: dict[int, list[tuple[
            tuple[int, int, int], tuple[int, int, int],
            tuple[int, int, int], str, str,
        ]]] = {}
        # How wide the widest tile is, in pieces. The search below walks back along
        # a row from the query, and this says when to stop: a tile beginning further
        # back than the widest tile is wide cannot still be reaching this far.
        self._widest = 1
        for tile in listed.get("tiles") or []:
            store = str(tile["store"])
            at = tuple(int(n) for n in tile["at"])
            size = tuple(int(n) for n in tile["size"])
            low = tuple(int(n) for n in tile["from"])
            if len(at) != 3 or len(size) != 3 or len(low) != 3:
                raise ValueError("a tile's place in the view needs three numbers")
            if any(n < 0 for n in at + low) or any(n <= 0 for n in size):
                raise ValueError("a tile cannot begin before the view or be empty")
            held_as = str(tile.get("held_as") or HELD_AS_A_FILE)
            if held_as != HELD_AS_A_FILE:
                raise ValueError(
                    f"{store} says its pieces are held as {held_as!r}, which this "
                    "reader does not know how to find. Rather than guess at where "
                    "in a file a piece begins — and hand the viewer somebody else's "
                    "bytes to draw — the whole view is left unread."
                )
            held = (at, size, low, store, held_as)
            self._widest = max(self._widest, size[2])
            for row in range(at[1], at[1] + size[1]):
                self._rows.setdefault(row, []).append(held)
        for crossing in self._rows.values():
            crossing.sort(key=lambda tile: tile[0][2])

    def _tile_covering(
        self, at: tuple[int, int, int]
    ) -> tuple[str, tuple[int, int, int], str] | None:
        """Which tile supplies the piece at this place, and which of its pieces it is.

        ``at`` is a place in the view's grid of pieces, given as ``(z, y, x)``.

        Only the tiles crossing this one row are looked at, and they are sorted by
        where they begin across the picture, so the search starts at the nearest one
        to the left and walks back. It stops as soon as the tiles it is passing
        began further back than the widest tile is wide, since none of those can
        still be reaching this far.

        Returns ``None`` when no tile covers this place — the common answer for a
        scattered run, where most of the picture's area is ground nobody imaged.
        """
        crossing = self._rows.get(at[1])
        if not crossing:
            return None
        nearest = bisect_right(crossing, at[2], key=lambda tile: tile[0][2])
        for index in range(nearest - 1, -1, -1):
            begins, size, low, store, held_as = crossing[index]
            if at[2] - begins[2] >= self._widest:
                break
            if (begins[2] <= at[2] < begins[2] + size[2]
                    and begins[0] <= at[0] < begins[0] + size[0]):
                return store, (
                    low[0] + at[0] - begins[0],
                    low[1] + at[1] - begins[1],
                    low[2] + at[2] - begins[2],
                ), held_as
        return None

    def the_bytes_behind(self, inside: str) -> Held | None:
        """Where this piece of the view really is: a file, a place in it, a length.

        ``inside`` is the address the browser asked for, with the view's own folder
        taken off the front — for example ``0/3/1/0/5/7``: the copy of the picture,
        then the moment, the colour, the plane, and where across the specimen.

        For a tile whose pieces are each a file of their own — every tile this reads
        today — the answer is the whole of that file, so the place is nought and the
        length is "to the end". The answer is given in the general shape all the same,
        so that a store keeping many pieces inside one larger file can be answered for
        later without anything that reads this having to change.

        Returns ``None`` when this is not a piece of the pointed-at copy, or when no
        tile covers that part of the picture. Both are ordinary answers rather than
        faults: the smaller copies are written down in the usual way and are found
        on disk without coming here at all, and most of a scattered run's picture is
        ground nobody imaged.
        """
        named = self._numbers_in(inside)
        if named is None:
            return None
        level, frame, channel, z, y, x = named
        # A smaller copy is the same arrangement with every number across the
        # specimen halved once per level, because shrinking halves the picture and
        # leaves the pieces the same size. A tile is required to begin on a
        # multiple of the piece size times the largest shrink, so these divisions
        # are exact rather than rounded -- and if that were ever not so, the tile
        # would be found at the wrong place rather than not found, which is why the
        # writer refuses such a placement rather than trusting this.
        shrink = 2 ** level
        found = self._tile_covering((z, y * shrink, x * shrink))
        if found is None:
            return None
        store, (from_z, from_y, from_x), held_as = found
        piece = self._named(frame, channel, from_z,
                            from_y // shrink, from_x // shrink)
        where = f"{store}/{level}/{piece}"
        # One piece, one file: all of it, from the beginning. A store that packs
        # several pieces into one file would work out the place and the length from
        # that file's own index here instead, which is why this is not simply a path.
        return Held(path=where, offset=0, length=None)

    def _named(self, *numbers: int) -> str:
        """What a piece at this position is called, in the spelling this view uses.

        A piece is filed under its position. The two generations of zarr spell that
        differently: version 2 simply joins the numbers with whatever the store
        declares — ``0.0.0.1.2`` — while version 3 usually puts a ``c`` in front of
        them as a part of the name in its own right, giving ``c/0/0/0/1/2``.

        The ``c`` being a separate part is easy to miss and was: joining it straight
        onto the first number gives ``c0/0/0/1/2``, which is a file that exists
        nowhere, so every request for a piece of a version 3 view was answered
        "there is nothing here" and the picture came out blank at full size.
        """
        parts = [str(n) for n in numbers]
        if self.prefix:
            parts.insert(0, self.prefix)
        return self.separator.join(parts)

    def _numbers_in(self, inside: str) -> tuple[int, int, int, int, int, int] | None:
        """Which copy, and the five numbers naming a piece of it, or ``None``.

        Anything that is not a pointed-at piece — a description file, a copy zoomed
        out further than any tile goes, a name in a spelling this view does not use
        — is answered ``None`` and looked for on disk in the ordinary way.
        """
        which, _, _ = inside.partition("/")
        try:
            level = int(which)
        except ValueError:
            return None
        # Only the copies the tiles themselves carry can be pointed at. Anything
        # zoomed out further than that was written by the view in the ordinary way
        # and is found on disk without coming here.
        if not 0 <= level < self.pointed_levels:
            return None
        wanted = f"{which}/"
        if not inside.startswith(wanted):
            return None
        rest = inside[len(wanted):]
        parts = rest.split(self.separator) if self.separator else [rest]
        if self.prefix:
            # The ``c`` version 3 puts in front is a part of the name of its own,
            # so it is taken off here rather than being read as a number.
            if not parts or parts[0] != self.prefix:
                return None
            parts = parts[1:]
        if len(parts) != 5:
            return None
        try:
            frame, channel, z, y, x = (int(part) for part in parts)
        except ValueError:
            return None
        return level, frame, channel, z, y, x


# What has been read from each view, against the moment its list of pointers was
# last written. Keyed on when as well as where, so that a view rebuilt while the
# viewer is open is noticed rather than answered from a list that no longer
# describes it.
_known: dict[str, tuple[tuple[int, int], _WhereThePiecesReallyAre]] = {}
_known_lock = threading.Lock()


def the_bytes_behind(store: Path, inside: str) -> Held | None:
    """Where this piece of a pointed-at picture really is, if it is one.

    Args:
        store: the view's own folder on disk.
        inside: the address asked for, with the view's folder taken off the front.

    Returns:
        A :class:`Held` saying which file the bytes are in, how far into it they
        begin and how many there are — or ``None`` if this is not a pointed-at
        piece. The path inside it is relative to the opened folder and the caller
        resolves it through the library, so a pointer can no more reach outside
        the opened folder than any other request can.

    An ordinary image has no list of pointers, and this costs it one look at
    whether that file exists — which is asked of the operating system and reads
    nothing. It is asked afresh every time rather than remembered, so that a view
    built after the viewer was opened is answered for straight away.
    """
    listing = store / LINKS_FILE
    added = store / LINKS_ADDED_FILE
    try:
        written = listing.stat().st_mtime_ns
    except OSError:
        return None
    # A run still being acquired grows its companion file as tiles land, and the
    # file's *length* is what says it has grown — a length rather than a time,
    # because several tiles can land within the resolution of a clock and the last
    # of them would then go unnoticed.
    try:
        grown = added.stat().st_size
    except OSError:
        grown = -1
    key = str(listing)
    with _known_lock:
        remembered = _known.get(key)
    if remembered is None or remembered[0] != (written, grown):
        spread = _read(listing, added)
        if spread is None:
            return None
        with _known_lock:
            _known[key] = ((written, grown), spread)
    else:
        spread = remembered[1]
    return spread.the_bytes_behind(inside)


def _the_tiles_added_since(added: Path) -> list[dict]:
    """The tiles a run still being acquired has added, one to a line.

    Returns an empty list when there is no such file, which is the ordinary case —
    a view built from a finished run keeps every tile in the list itself.

    **A half-written last line is expected and is not a fault.** This is read while
    the writer is still adding to the file, so the final line can be caught partway
    through being written. Such a line is left out, and it will be read on the next
    look a moment later. Only the *last* line is forgiven this way: anything earlier
    that will not read is a real fault, and the whole view is then left unread
    rather than shown with tiles missing and nothing on screen to say so.
    """
    try:
        lines = added.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    tiles = []
    for at, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            tiles.append(json.loads(line))
        except json.JSONDecodeError:
            if at == len(lines) - 1:
                break
            raise
    return tiles


def _read(listing: Path, added: Path) -> _WhereThePiecesReallyAre | None:
    """Read a view's list of pointers, or ``None`` if it cannot be trusted.

    A list that cannot be read, or that was written in a shape this reader does not
    know, is treated as no list at all. The view then answers "there is nothing
    here" for its full-size picture and still draws perfectly well zoomed out, which
    is a far better outcome than pointing at files chosen by guesswork.
    """
    try:
        held = json.loads(listing.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(held, dict) or held.get("version") not in LINKS_VERSIONS_UNDERSTOOD:
        return None
    try:
        held = {**held, "tiles": [*(held.get("tiles") or []),
                                  *_the_tiles_added_since(added)]}
        return _WhereThePiecesReallyAre(held)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def forget(store: Path) -> None:
    """Let go of the pointers remembered for one closed view.

    Closing an acquisition should hand its memory back rather than keeping it for
    the rest of the session. A large view's lookup is the biggest thing this module
    holds, so it is worth dropping.
    """
    with _known_lock:
        _known.pop(str(store / LINKS_FILE), None)

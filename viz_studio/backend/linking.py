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
      "version": 1,
      "level": "0",            which copy of the picture is pointed at
      "separator": "/",        what goes between the numbers of a piece's name
      "prefix": "",            what goes in front of them ("c" for zarr version 3)
      "tiles": [
        {"store": "overview_tiles/overview_pos00000.ome.zarr",
         "at":   [0, 0, 0],    where this tile's pieces begin in the view
         "size": [2, 1, 1],    how many of them it supplies
         "from": [0, 0, 0]}    which of its own pieces the first of them is
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
from pathlib import Path

# The file, inside a view's own folder, that holds the list of pointers. The same
# name is written down in ``zmart_storage/linked.py``, which writes the file; the
# two have to be changed together.
LINKS_FILE = "zmart-links.json"

# The shape of that file this reader understands. A file saying anything else is
# ignored rather than guessed at, because guessing wrongly would draw one tile's
# picture in another tile's place with nothing on screen to say so.
LINKS_VERSION = 1


class _WhereThePiecesReallyAre:
    """One view's pointers, spread out so a piece can be found in a single step.

    The file on disk lists each tile once, saying which block of the view's pieces
    it supplies. That is short — ten thousand tiles are ten thousand lines — but
    answering a request from it would mean looking through every tile. So it is
    spread out into a lookup here, once, the first time the view is asked about.
    """

    def __init__(self, listed: dict) -> None:
        self.level = str(listed.get("level", "0"))
        self.separator = str(listed.get("separator") or "/")
        self.prefix = str(listed.get("prefix") or "")
        self._at: dict[tuple[int, int, int], tuple[str, tuple[int, int, int]]] = {}
        for tile in listed.get("tiles") or []:
            store = str(tile["store"])
            at = [int(n) for n in tile["at"]]
            size = [int(n) for n in tile["size"]]
            low = [int(n) for n in tile["from"]]
            for dz in range(size[0]):
                for dy in range(size[1]):
                    for dx in range(size[2]):
                        self._at[(at[0] + dz, at[1] + dy, at[2] + dx)] = (
                            store, (low[0] + dz, low[1] + dy, low[2] + dx)
                        )

    def the_file_behind(self, inside: str) -> str | None:
        """Which file holds this piece of the view, said relative to the opened folder.

        ``inside`` is the address the browser asked for, with the view's own folder
        taken off the front — for example ``0/3/1/0/5/7``: the copy of the picture,
        then the moment, the colour, the plane, and where across the specimen.

        Returns ``None`` when this is not a piece of the pointed-at copy, or when no
        tile covers that part of the picture. Both are ordinary answers rather than
        faults: the smaller copies are written down in the usual way and are found
        on disk without coming here at all, and most of a scattered run's picture is
        ground nobody imaged.
        """
        named = self._numbers_in(inside)
        if named is None:
            return None
        frame, channel, z, y, x = named
        found = self._at.get((z, y, x))
        if found is None:
            return None
        store, (from_z, from_y, from_x) = found
        piece = self.separator.join(
            str(n) for n in (frame, channel, from_z, from_y, from_x)
        )
        return f"{store}/{self.level}/{self.prefix}{piece}"

    def _numbers_in(self, inside: str) -> tuple[int, int, int, int, int] | None:
        """The five numbers naming a piece of the pointed-at copy, or ``None``.

        Anything that is not a piece of that copy — a description file, a piece of
        one of the smaller copies, a name in a spelling this view does not use — is
        answered ``None`` and looked for on disk in the ordinary way.
        """
        wanted = f"{self.level}/{self.prefix}"
        if not inside.startswith(wanted):
            return None
        rest = inside[len(wanted):]
        parts = rest.split(self.separator) if self.separator else [rest]
        if len(parts) != 5:
            return None
        try:
            frame, channel, z, y, x = (int(part) for part in parts)
        except ValueError:
            return None
        return frame, channel, z, y, x


# What has been read from each view, against the moment its list of pointers was
# last written. Keyed on when as well as where, so that a view rebuilt while the
# viewer is open is noticed rather than answered from a list that no longer
# describes it.
_known: dict[str, tuple[int, _WhereThePiecesReallyAre]] = {}
_known_lock = threading.Lock()


def the_file_behind(store: Path, inside: str) -> str | None:
    """Which file holds this piece of a pointed-at picture, if any.

    Args:
        store: the view's own folder on disk.
        inside: the address asked for, with the view's folder taken off the front.

    Returns:
        Where the bytes really are, as a path relative to the opened folder, or
        ``None`` if this is not a pointed-at piece. The caller resolves that path
        through the library, so a pointer can no more reach outside the opened
        folder than any other request can.

    An ordinary image has no list of pointers, and this costs it one look at
    whether that file exists — which is asked of the operating system and reads
    nothing. It is asked afresh every time rather than remembered, so that a view
    built after the viewer was opened is answered for straight away.
    """
    listing = store / LINKS_FILE
    try:
        written = listing.stat().st_mtime_ns
    except OSError:
        return None
    key = str(listing)
    with _known_lock:
        remembered = _known.get(key)
    if remembered is None or remembered[0] != written:
        spread = _read(listing)
        if spread is None:
            return None
        with _known_lock:
            _known[key] = (written, spread)
    else:
        spread = remembered[1]
    return spread.the_file_behind(inside)


def _read(listing: Path) -> _WhereThePiecesReallyAre | None:
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
    if not isinstance(held, dict) or held.get("version") != LINKS_VERSION:
        return None
    try:
        return _WhereThePiecesReallyAre(held)
    except (KeyError, TypeError, ValueError):
        return None


def forget(store: Path) -> None:
    """Let go of the pointers remembered for one closed view.

    Closing an acquisition should hand its memory back rather than keeping it for
    the rest of the session. A large view's lookup is the biggest thing this module
    holds, so it is worth dropping.
    """
    with _known_lock:
        _known.pop(str(store / LINKS_FILE), None)

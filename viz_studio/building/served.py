"""Supplying the pieces of a built picture while the viewer is open.

This is the other half of :mod:`declare`. The description of a built picture is on
disk and is served as ordinary files; every piece of the picture is not, and is
made here when the browser asks.

It is the counterpart of ``backend/linking.py``, which answers for a picture whose
pieces are files somewhere else. The two answer the same question — *where is this
piece?* — and give opposite answers: linking hands over a file that already exists,
building makes bytes that never existed. A viewer opens both without knowing which
it has.

Held open between requests
--------------------------

A composer keeps every tile of a transfer open, and opening a store is not the
small thing it sounds — measured elsewhere in this repo at 86% of the time spent
building a view, at sixteen hundred tiles. So one composer per built picture is
kept for as long as the viewer is looking at it, rather than made per request.

The one difference from pointing worth knowing about
----------------------------------------------------

A pointed-at piece is resolved by the viewer's own library, so it is held to the
same rule as every other file: it can only reach inside a folder somebody opened.
A built piece is read straight from the transfer the description names, which may
be anywhere on the machine. That is a genuine widening of what the server will
read, and it is deliberate — a transfer usually sits on a different disk from
anything the operator opened — but it should be a decision somebody made rather
than one they discover.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from composer import Composer
from declare import OURS
from mosaic import Mosaic, read_the_mosaic_as_written, read_the_transfer

# One composer per built picture, kept for as long as the viewer is open on it.
_composers: dict[Path, Composer | None] = {}
_guard = threading.Lock()

# One lock per picture, held while its composer is being made.
#
# **Why this is not merely tidiness.** The drawing engine asks for many pieces at
# once the moment a picture is opened -- dozens of requests, each on its own
# thread. Without this, every one of them finds no composer, every one of them
# reads the whole transfer, and one of them wins; the rest of that work is thrown
# away. At six tiles nobody would notice. At ten thousand it was measured at 14
# seconds for the first piece, where every piece after it took under a fifth of
# one. So the first thread through makes the composer and the others wait for it.
#
# A lock per picture rather than one lock for all of them, so that opening a
# second picture is not held up behind the first.
_being_made: dict[Path, threading.Lock] = {}


def _what_it_was_built_from(store: Path) -> dict | None:
    """What a store records about being built, or ``None`` for an ordinary image."""
    described = store / "zarr.json"
    if not described.is_file():
        return None
    try:
        held = json.loads(described.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ours = (held.get("attributes") or {}).get(OURS)
    if isinstance(ours, dict) and ours.get("built_from"):
        return ours
    return None


def _the_mosaic_behind(store: Path, ours: dict) -> Mosaic:
    """The picture's geometry, read from its own ledger when it keeps one.

    Declaring a picture writes the tiles' geometry down (``tiles.json``), so
    opening reads one file however many positions the transfer holds -- before
    this, a 12,800-position survey sat dark for nine seconds while every
    tile's description was walked again to learn what declaring had already
    learned. A picture declared before the ledger existed still opens by
    walking the transfer; declare it again and the wait is gone.
    """
    ledger = store / "tiles.json"
    if ledger.is_file():
        return read_the_mosaic_as_written(
            json.loads(ledger.read_text(encoding="utf-8")))
    return read_the_transfer(Path(ours["built_from"]))


def _composer_for(store: Path) -> Composer | None:
    """The composer for this picture, opened once and kept.

    ``None`` — remembered as well as returned — for an ordinary image, so that a
    store which is not built costs one look at its description for the whole time
    the viewer is open rather than one per piece asked for.
    """
    store = store.resolve()
    with _guard:
        if store in _composers:
            return _composers[store]
        making = _being_made.setdefault(store, threading.Lock())

    # Held across the reading of the transfer, so the many requests the engine
    # makes at once produce one composer between them rather than one each.
    with making:
        with _guard:
            if store in _composers:
                return _composers[store]
        ours = _what_it_was_built_from(store)
        made = None
        if ours is not None:
            # ZMART_BUILD_WORKERS is how many processes build this picture,
            # so one against four is two launches of the same viewer. Unset
            # means one: build in place, the path every recorded figure
            # describes and the one the operator chose as the default.
            workers = int(os.environ.get("ZMART_BUILD_WORKERS") or 1)
            made = Composer(_the_mosaic_behind(store, ours),
                            piece=int(ours.get("piece") or 512),
                            workers=workers)
            # The cold start, paid in the background from the first request on:
            # the coarse levels are built coarsest-first while the viewer shows
            # whatever the operator asked for, stepping aside whenever a real
            # request is being answered. Started here rather than inside the
            # composer, because the measurement harnesses build composers too
            # and must keep meeting the cold costs they exist to measure. A
            # baked picture already holds that ground as files, so warming it
            # again would only burn the processor it was baked to spare.
            if not ours.get("baked"):
                made.keep_the_coarse_levels_warm()
        with _guard:
            _composers[store] = made
            return made


def the_bytes_behind(store: Path, inside: str) -> bytes | None:
    """The piece of a built picture the browser asked for, made now.

    Args:
        store: the built picture's own folder.
        inside: what came after it — ``0/c/145/9/8``: the resolution, then one
            number per axis.

    Returns:
        The encoded piece, or ``None`` when this is not a built picture, when the
        address is not a piece, when it falls outside the picture, or when it is
        ground inside the picture that no tile covers — which on a scattered run
        is most of it. All four are ordinary answers rather than faults, served
        as absent and painted by the engine from the declared fill value.
    """
    composer = _composer_for(Path(store))
    if composer is None:
        return None
    parts = inside.strip("/").split("/")
    if len(parts) != 5 or parts[1] != "c" or not parts[0].isdigit():
        return None
    if not all(one.isdigit() for one in parts[2:]):
        return None
    # Ground the declaration baked is a real file, answered as one: no
    # building, no tiles, immune to everything that makes building slow. This
    # is also the only door to the picture's own levels above the tiles' --
    # those exist nowhere but as baked files, so past this point the composer's
    # bounds rightly refuse them. The address is safe as a path because only
    # digit-shaped five-part names reach here.
    baked = Path(store).joinpath(parts[0], "c", *parts[2:])
    if baked.is_file():
        return baked.read_bytes()
    level = int(parts[0])
    if not 0 <= level < composer.mosaic.levels:
        return None
    plane, row, column = (int(one) for one in parts[2:])
    deep, down, across = composer.grid(level)
    if not (0 <= plane < deep and 0 <= row < down and 0 <= column < across):
        return None
    return composer.bytes_for(level, plane, row, column)


def forget(store: Path) -> None:
    """Let go of a built picture, closing the tiles it was holding open.

    A running warm pass is told to stop first, so a picture being forgotten --
    or, under the live role, swapped for a fresh snapshot -- does not keep a
    thread building slabs nobody can reach any more.
    """
    with _guard:
        where = Path(store).resolve()
        held = _composers.pop(where, None)
        _being_made.pop(where, None)
    if held is not None:
        held.close()

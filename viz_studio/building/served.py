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
import logging
import os
import threading
import time
from pathlib import Path

from composer import Composer, the_piece_address
from declare import OURS
from mosaic import Mosaic, read_the_mosaic_as_written, read_the_transfer

# The governed-run pieces come from zmart_live, and a checkout without that
# package must still serve every ordinary built picture -- the same guard the
# backend server keeps for this module itself.
try:
    from governed import GovernedRun

    from zmart_live.gateway import live_run_holding
except ImportError:  # pragma: no cover - a checkout without zmart_live
    GovernedRun = None  # type: ignore[assignment, misc]

    def live_run_holding(target):  # type: ignore[misc]
        return None


log = logging.getLogger("viz_studio.serving")


class TemporarilyUnanswerable(Exception):
    """This piece cannot be answered right now — which is not the same as absent.

    The viewer treats an absent answer (a 404) as the truth about the ground:
    there is nothing here, stop asking. That is right for ground that was never
    imaged, and dangerously wrong for a picture that merely could not answer at
    this moment — a derive that lost a race for the bake lock, a description
    briefly unreadable while another process replaces it. Answering those as
    absent leaves a hole in the operator's picture that only a reload repairs,
    because nothing ever tells the viewer to ask again.

    So the two answers are kept apart. Genuine absence stays ``None`` and
    becomes a 404. A failure that a retry may cure raises this instead, and the
    server answers 503 — which the viewer's own HTTP layer retries with bounded
    backoff, no ZMART timer involved. The worst case for a persistent fault is
    a bounded burst of retries and an honest failure, never a quiet hole.
    """

# One composer per built picture, kept for as long as the viewer is open on
# it, each remembered WITH the identity of the description it was opened
# from, so a re-declaration is noticed and rebuilt rather than served stale.
# A governed picture keeps its GovernedRun here instead, because its composer
# is not one object but one per manifest state, and the run is what hands out
# the current one.
_composers: dict[Path, tuple[tuple | None,
                             Composer | GovernedRun | None]] = {}
_guard = threading.Lock()

# Pictures whose composer could not be made, each with the moment it failed.
# Remembered briefly rather than forever: one half-written arrival used to
# make every request repeat the whole transfer read behind the making-lock --
# a standing denial of service -- while remembering the failure for good
# would hide a run that has recovered. Two seconds keeps the disk quiet and
# notices recovery on the next ask after it.
_REFUSED_FOR_SECONDS = 2.0
_refused: dict[Path, float] = {}

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
    """What a store records about being built, or ``None`` for an ordinary image.

    ``None`` is only ever the answer of a SUCCESSFUL look -- no description
    at all, or one that carries no building record. A description that exists
    but cannot be read right now raises instead: swallowing that classified
    a briefly-held file as "ordinary image", permanently, and the backend
    then served its baked pieces statically past the manifest (review
    finding D3). The caller turns the raise into a timed refusal, which
    fails closed and retries.
    """
    described = store / "zarr.json"
    if not described.is_file():
        return None
    held = json.loads(described.read_text(encoding="utf-8"))
    ours = (held.get("attributes") or {}).get(OURS)
    if isinstance(ours, dict) and (ours.get("built_from")
                                   or ours.get("governed_from")):
        return ours
    return None


def _the_pictures_mark(store: Path) -> tuple | None:
    """The identity of the picture's own description, for cache honesty.

    A declaration is what says what a picture IS -- baked or not, governed
    or not -- and re-declaring rewrites it. A served picture remembered past
    that rewrite kept serving yesterday's answer (review finding D5), so
    every remembered entry carries this mark and is rebuilt when it moves.
    """
    try:
        stamp = (store / "zarr.json").stat()
    except OSError:
        return None
    return (stamp.st_dev, getattr(stamp, "st_ino", 0), stamp.st_size,
            stamp.st_mtime_ns, stamp.st_ctime_ns)


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


def _composer_for(store: Path) -> Composer | GovernedRun | None:
    """The composer for this picture, opened once and kept.

    ``None`` — remembered as well as returned — for an ordinary image, so that a
    store which is not built costs one look at its description for the whole time
    the viewer is open rather than one per piece asked for. A failure to make
    one is remembered too, but briefly (see ``_refused``): permanent for a
    plain image, timed for damage, so a run that recovers is noticed.
    """
    store = store.resolve()
    mark = _the_pictures_mark(store)
    stale = None
    with _guard:
        if store in _composers:
            kept_mark, kept = _composers[store]
            if kept_mark == mark:
                return kept
            # The picture was re-declared under us: what it IS has changed,
            # so the remembered serving -- baked levels included -- is
            # yesterday's answer. Rebuild from the new description.
            del _composers[store]
            stale = kept
        stumbled = _refused.get(store)
        if stumbled is not None:
            if time.monotonic() - stumbled < _REFUSED_FOR_SECONDS:
                return None
            del _refused[store]
        making = _being_made.setdefault(store, threading.Lock())
    if stale is not None:
        try:
            stale.close()
        except Exception:
            log.exception("the re-declared picture at %s would not close "
                          "cleanly; serving continues from the fresh one",
                          store)

    # Held across the reading of the transfer, so the many requests the engine
    # makes at once produce one composer between them rather than one each.
    with making:
        with _guard:
            if store in _composers and _composers[store][0] == mark:
                return _composers[store][1]
        made = None
        try:
            ours = _what_it_was_built_from(store)
            made = _the_serving_behind(store, ours)
        except Exception:
            log.exception("the picture at %s could not be opened; answering "
                          "absent for the next %.0f seconds", store,
                          _REFUSED_FOR_SECONDS)
            with _guard:
                _refused[store] = time.monotonic()
            return None
        with _guard:
            _composers[store] = (mark, made)
            return made


def _the_serving_behind(store: Path, ours: dict | None
                        ) -> Composer | GovernedRun | None:
    """What answers for this store: a composer, a governed run, or nothing.

    The one policy decision lives here: a picture whose transfer lies inside
    a governed run is refused outright. A declared picture reads its tiles
    straight through zarr, invisible to the gateway, so honouring it would be
    a door past every fail-closed rule the run has — and ``built_from`` is
    file content, not an operator's decision. The run's own ground is served
    through ``governed_from``, where the manifest rules every request.
    """
    if ours is None:
        return None
    governs = ours.get("governed_from")
    if governs:
        if GovernedRun is None:
            raise RuntimeError(
                "this checkout has no zmart_live, so a governed picture "
                "cannot consult any manifest and will not be served."
            )
        return GovernedRun(Path(governs), piece=int(ours.get("piece") or 512),
                           store=store)
    transfer = Path(ours["built_from"])
    holding = live_run_holding(transfer)
    if holding is not None:
        log.warning(
            "refusing the picture at %s: its transfer %s lies inside the "
            "governed run at %s, which would serve the run's pixels past its "
            "manifest. Declare the run itself instead.", store, transfer,
            holding)
        return None
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
    return made


def a_manifest_governs(store: Path) -> bool:
    """Whether this picture's pieces may only be answered through its run.

    Asked by the backend before it serves a piece file that exists on disk:
    a transfer's baked file is frozen truth and the fast door is right, but
    a governed picture's baked file is only true as of the last patch, and
    handing it over without consulting the run is how a withdrawn
    generation outlives its withdrawal. Costs one opening of the picture
    the first time and a dictionary look afterwards.

    A picture that cannot be CLASSIFIED right now answers True: while its
    description is unreadable or its run refuses to open, nothing may be
    served from its files -- treating the failure as "ordinary image"
    opened the static door past the manifest (review finding D3). The
    refusal is timed, so a recovered picture reclassifies itself.
    """
    where = Path(store).resolve()
    held = _composer_for(where)
    if GovernedRun is not None and isinstance(held, GovernedRun):
        return True
    if held is None:
        with _guard:
            return where in _refused
    return False


def the_bytes_behind(store: Path, inside: str) -> bytes | None:
    """The piece of a built picture the browser asked for, made now.

    Args:
        store: the built picture's own folder.
        inside: what came after it — ``0/c/145/9/8`` for a flat picture, or
            ``0/c/2/1/145/9/8`` for one grown along (t, c): the resolution,
            then one number per axis of its own description.

    Returns:
        The encoded piece, or ``None`` when this is not a built picture, when the
        address is not a piece, when it falls outside the picture, or when it is
        ground inside the picture that no tile covers — which on a scattered run
        is most of it. All four are ordinary answers rather than faults, served
        as absent and painted by the engine from the declared fill value.
    """
    where = Path(store)
    held = _composer_for(where)
    if held is None:
        # Nothing to answer with -- but WHY matters at the wire. A plain image
        # that is simply not a built picture is genuine absence, and the
        # request falls through to the ordinary file doors. A picture whose
        # opening FAILED is refused for a moment (see _refused), and that
        # refusal must not dress up as absence: the viewer believes a 404 and
        # never asks again, where a 503 is retried by its own HTTP layer.
        with _guard:
            if where.resolve() in _refused:
                raise TemporarilyUnanswerable(
                    f"the picture at {where} could not be opened just now")
        return None
    address = the_piece_address(inside)
    if address is None:
        return None
    level, moment, channel, plane, row, column = address
    # A governed picture consults its run BEFORE any file may answer: asking
    # for the composer checks the manifest's fingerprint, and a moved
    # fingerprint derives the fresh snapshot -- which patches the baked
    # files inside the derive. Only then is a file a safe answer; a file
    # read first would outrun the manifest and serve ground a commit has
    # already withdrawn. While nothing has been committed the same composer
    # comes straight back and this costs a fingerprint read.
    composer = None
    if GovernedRun is not None and isinstance(held, GovernedRun):
        try:
            composer = held.composer()
        except Exception as problem:
            log.exception("the governed run behind %s could not derive; "
                          "answering 'try again shortly'", store)
            raise TemporarilyUnanswerable(
                f"the governed run behind {store} could not derive"
            ) from problem
    # Ground the declaration baked is a real file, answered as one: no
    # building, no tiles, immune to everything that makes building slow. This
    # is also the only door to the picture's own levels above the tiles' --
    # those exist nowhere but as baked files, so past this point the composer's
    # bounds rightly refuse them. The address is safe as a path because only
    # digit-shaped names reach here. Baked files exist only for flat pictures
    # today -- the per-(t, c) bake is ordered work -- so only the flat frame
    # looks for one.
    if (moment, channel) == (0, 0):
        baked = Path(store).joinpath(str(level), "c",
                                     str(plane), str(row), str(column))
        if baked.is_file():
            return baked.read_bytes()
    # Everything from here can genuinely fail -- a rollback deleting a store
    # mid-read, damage under committed ground refusing to be papered over.
    # An address outside the picture, or ground no tile covers, stays an
    # ordinary absent answer. A FAILURE is different: it may pass -- the
    # rollback finishes, the reader wins the next race -- so it is answered
    # as "try again shortly" rather than as absence the viewer would believe
    # for the rest of the session. Either way the reason lives in the log
    # rather than in a dying connection, and no pixels are ever guessed.
    try:
        if composer is None:
            composer = held
        if not 0 <= level < composer.mosaic.levels:
            return None
        deep, down, across = composer.grid(level)
        moments, channels = composer.mosaic.frame_room
        if not (0 <= plane < deep and 0 <= row < down and 0 <= column < across
                and 0 <= moment < moments and 0 <= channel < channels):
            return None
        return composer.bytes_for(level, plane, row, column, moment, channel)
    except Exception as problem:
        log.exception("the piece %s of %s could not be served; answering "
                      "'try again shortly'", inside, store)
        raise TemporarilyUnanswerable(
            f"the piece {inside} of {store} could not be served just now"
        ) from problem


def forget(store: Path) -> None:
    """Let go of a built picture, closing the tiles it was holding open.

    A running warm pass is told to stop first, so a picture being forgotten --
    or, under the live role, swapped for a fresh snapshot -- does not keep a
    thread building slabs nobody can reach any more.
    """
    with _guard:
        where = Path(store).resolve()
        remembered = _composers.pop(where, None)
        _being_made.pop(where, None)
        _refused.pop(where, None)
    held = remembered[1] if remembered is not None else None
    if held is not None:
        held.close()


def catch_up_governed_runs() -> None:
    """Nudge every opened governed picture after an acquisition announcement.

    The announcement does not name a store, deliberately: it only says that
    disk truth moved. Asking each remembered run to compare its cheap manifest
    fingerprint preserves that contract, and each run coalesces repeated nudges
    behind at most one background derive.
    """
    if GovernedRun is None:
        return
    with _guard:
        governed = [held for _mark, held in _composers.values()
                    if isinstance(held, GovernedRun)]
    for held in governed:
        held.request_catch_up()

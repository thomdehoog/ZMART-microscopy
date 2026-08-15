"""Serving a manifest-governed run as one built picture.

The composer in this folder was written for transfers: finished folders where
everything on disk is real, nothing changes, and a ``glob`` is an honest list
of what exists. A live ZMART run is the opposite on purpose — positions are
written *before* they are published, a position can be replaced by a later
generation, and the run's manifest is the only record of what may be shown
("files existing means nothing; this record means everything").

This module is where the two meet, and the division of labour is strict:

- **What may be shown** is decided by :class:`zmart_live.gateway._LiveRun`,
  the gateway's own fail-closed interpretation of one run folder. It is
  imported rather than reimplemented, deliberately, private name and all: the
  gateway is the reference implementation of the gate, its reading of the
  manifest is validated by its own test suite and sabotage campaigns, and a
  second reading here would be a second truth that could drift from the
  first. If the import ever breaks, the answer is to export the class, not to
  copy it.

- **How it is drawn** stays the composer's, unchanged: the same laying, the
  same caches, the same encoder.

What this module adds between them:

- the tile list comes from the manifest — published positions only, each at
  its current generation, in commit order so the later commit is laid on top;
- the picture's frame comes from the run's layout and profile, never from
  whichever tiles happen to have arrived: an empty run is a valid empty
  picture, and a position landing can neither shrink, grow, nor shift the
  declared world;
- a fresh immutable snapshot per manifest state: the fingerprint is checked
  on every ask, and when it has moved the mosaic and composer are derived
  again from the new truth rather than mutated under whoever is reading them.

The served picture is three axes (z, y, x) for the moment, reading each
position's first moment and first channel; the address space grows t and c
with the gate work's later steps. Positions are stored (t, c, z, y, x) and
the copies carry that difference as a fixed outer index — see
:class:`mosaic.Copy`.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import zarr

from zmart_live.gateway import _LiveRun
from zmart_live.shardlink import how_the_array_is_stored

from composer import PIECE, Composer
from mosaic import IMAGE_SUFFIX, Copy, Mosaic, Tile, _read_one_tile


log = logging.getLogger("viz_studio.governed")

# Page requests own interactive serving while commits are arriving. The
# announcement worker is a safety net for the state left after demand stops,
# so it begins only after this much quiet rather than contending per commit.
_BAKE_CATCH_UP_QUIET_S = 0.25


def _promising_its_blocks(copy: Copy) -> Copy:
    """The same copy, now promising that every block it is asked for exists.

    A committed position's pixels were promised by a commit, so an absent
    chunk is damage the composer must refuse to paper over (see
    :class:`composer.MissingCommittedGround`). The check goes through the
    run's own shard-aware resolver, so a chunk bundled into a shard file is
    found where it really lives; its answer of ``None`` for a chunk never
    written is exactly the absence being refused. The array's description is
    read once, on the first ask, and kept.
    """
    stored = []

    def is_on_disk(at: tuple[int, int, int]) -> bool:
        if not stored:
            stored.append(how_the_array_is_stored(copy.held_in))
        return stored[0].where_one_chunk_lives(copy.outer + tuple(at)) is not None

    copy.presence = is_on_disk
    return copy


def _a_committed_tile(store) -> Tile:
    """One published position, read as a tile whose ground is promised."""
    tile = _read_one_tile(store)
    for copy in tile.copies:
        _promising_its_blocks(copy)
    return tile


@contextmanager
def _holding_the_bake_lock(store: Path):
    """The whole-machine lock on one picture's baked files.

    A lock FILE beside the bake, locked through the operating system
    (``msvcrt`` on the microscope's Windows machine, ``fcntl`` everywhere
    else -- the same split the manifest's writer lock already makes), so
    two processes patching one picture -- a second server, or
    ``declare --bake`` beside a running one -- take turns instead of
    replacing files and tearing down staging directories under each other.
    The OS releases the lock when its holder dies, so a crashed patcher
    cannot wedge the picture; the lock file itself is left in place,
    because deleting it would hand a third process a different file to
    lock than the one a second is already holding.
    """
    store.mkdir(parents=True, exist_ok=True)
    holding = open(store / ".bake.lock", "a+b")
    try:
        if os.name == "nt":  # pragma: no cover - exercised on the Windows target
            import msvcrt

            holding.seek(0)
            # LK_LOCK waits about ten seconds and then raises. A patcher held
            # out longer than that -- the other process is mid-catch-up -- has
            # its derive fail, which the serving path answers as absence and
            # retries: the fail-closed direction, never a stale file.
            msvcrt.locking(holding.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                holding.seek(0)
                msvcrt.locking(holding.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            # flock waits as long as it takes rather than ten seconds; on
            # the machines this branch serves (development and CI, not the
            # microscope) a patient wait beats a raced failure.
            fcntl.flock(holding.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(holding.fileno(), fcntl.LOCK_UN)
    finally:
        holding.close()


def _after_a_windows_reader(operation, *paths):
    """Perform one file swap/removal after a brief Windows sharing lock.

    POSIX permits replacing a file through an open reader; Windows refuses it
    until that reader closes.  Baked chunks are read by the page and the warm
    pass while a commit patches them, so a sharing violation is expected and
    short-lived rather than a reason to turn the whole derive into absence.
    Retry only the Windows sharing-shaped permission errors, for a bounded
    five seconds; real permissions damage still fails closed.
    """
    deadline = time.monotonic() + 5.0
    pause = 0.002
    while True:
        try:
            return operation(*paths)
        except PermissionError as problem:
            sharing = (getattr(problem, "winerror", None) in (5, 32, 33)
                       or getattr(problem, "errno", None) in (5, 13))
            if os.name != "nt" or not sharing or time.monotonic() >= deadline:
                raise
            time.sleep(pause)
            pause = min(pause * 2, 0.05)


def _a_tile_stamped(pattern: Tile, store: Path,
                    corner_um: tuple[float, float, float]) -> Tile:
    """One published position's tile, stamped from the pattern instead of read.

    Every position of a governed run is written by the same writer from the
    same sealed profile, so the whole of a tile's geometry — how many copies
    it keeps, each copy's shape, chunking, kind of number and voxel size — is
    the run's, not the position's. Only two things are the position's own:
    which folder holds its pixels and where the layout puts it, and the layout
    already states the second in the very numbers the writer wrote into the
    store (``origin_pixels`` times the voxel size — see
    ``zmart_live.omezarr._where_the_corner_sits``, which gives every level the
    same corner). Re-learning the run's geometry once per position — seven
    small file reads each — was the whole of the one-time cold derive: 44
    seconds at 12,769 positions against cold filesystem caches, 7.3 warm.

    The stamped tile still promises its blocks the way a read one does, and
    the promise resolves against the store's own description on the first
    pixel ask — so a store whose files disagree with its stamp fails closed
    at the read, exactly where a damaged committed position always has.
    """
    copies = [
        _promising_its_blocks(Copy(
            held_in=store / one.held_in.name,
            shape=one.shape,
            chunks=one.chunks,
            dtype=one.dtype,
            voxel_um=one.voxel_um,
            corner_um=corner_um,
            outer=one.outer,
        ))
        for one in pattern.copies
    ]
    return Tile(name=store.name, store=store, copies=copies,
                axes=pattern.axes, turned=pattern.turned)


class TheWorldFrame(Mosaic):
    """A mosaic whose geometry is the layout's, whatever tiles have arrived.

    A transfer's mosaic derives everything from its tiles, which is right for
    a finished folder and wrong for a growing one: max-over-tiles shrinks the
    world before the last position lands, and min-over-tiles moves the origin
    — and with it every voxel coordinate — the moment a position more
    negative than any before arrives. The layout knows every position the run
    will ever image, so the frame it implies is complete from the first
    moment and never moves.
    """

    # The layout-derived origin per (run, layout revision), worked out once.
    # A layout is immutable per revision and a snapshot is derived per
    # commit, so sweeping every planned placement again each time was
    # measurable waste at thousands of positions -- and the answer cannot
    # have changed.
    _origins: dict[tuple, tuple[float, float, float]] = {}
    # The per-level extent, remembered the same way and for the same reason:
    # a fresh frame is built per derive, and its shape() sweep over every
    # planned placement was 130 ms of every commit at 6,400 positions --
    # recomputing, per commit, a number the immutable layout fixed at declare.
    _shapes: dict[tuple, tuple[int, int, int]] = {}

    def __init__(self, tiles, layout, profile):
        named = (layout.run_id, layout.revision, profile.profile_id)
        remembered = TheWorldFrame._origins.get(named)
        if remembered is None:
            remembered = tuple(
                min((float(placement.origin.get(axis, 0))
                     * float(profile.voxel_size.get(axis, 1.0))
                     for placement in layout.positions),
                    default=0.0)
                for axis in ("z", "y", "x")
            )
            TheWorldFrame._origins[named] = remembered
        origin_um = remembered
        super().__init__(
            tiles=tiles,
            levels=len(profile.levels),
            axes=("z", "y", "x"),
            dtype=str(profile.dtype),
            corner_um=origin_um,
            # The run's writer halves by averaging 2x2 blocks (coordinator
            # _halve), so the picture's levels need the half-voxel-per-halving
            # registration — see Mosaic.averaged for what going without it
            # looks like on screen.
            averaged=True,
        )
        self._layout = layout
        self._profile = profile

    def voxel_um(self, level: int) -> tuple[float, float, float]:
        """From the profile, so it exists before any position does."""
        rung = self._profile.level(level)
        return tuple(
            float(self._profile.voxel_size.get(axis, 1.0))
            * float(rung.downsampling.get(axis, 1))
            for axis in ("z", "y", "x")
        )  # type: ignore[return-value]

    def shape(self, level: int) -> tuple[int, int, int]:
        """The layout's extent: every planned position, arrived or not."""
        found = self._shape.get(level)
        if found is None:
            named = (self._layout.run_id, self._layout.revision,
                     self._profile.profile_id, level)
            found = TheWorldFrame._shapes.get(named)
            if found is None:
                rung = self._profile.level(level)
                frame = self._profile.frame_shape
                reach = []
                for axis in ("z", "y", "x"):
                    down = float(rung.downsampling.get(axis, 1))
                    edge = max(
                        (float(placement.origin.get(axis, 0))
                         + float(frame.get(axis, 1))
                         for placement in self._layout.positions),
                        default=float(frame.get(axis, 1)),
                    )
                    reach.append(-(-int(edge) // int(down)))
                found = tuple(reach)
                TheWorldFrame._shapes[named] = found
            self._shape[level] = found  # type: ignore[assignment]
        return found  # type: ignore[return-value]

    @property
    def channels_recorded(self) -> tuple[str, ...]:
        """The colours the run records — the profile's, not any tile's.

        Asked by the declare door: a picture that can serve one channel must
        refuse a run recording several, and it must be able to refuse before
        a single position has arrived.
        """
        return tuple(self._profile.channels)

    @property
    def slab_depths(self) -> list[int]:
        """How many planes one file holds per level, from the profile.

        Offered so the composer's slab economy works on a run that has
        committed nothing yet — a grid is not allowed to depend on arrivals.
        """
        return [
            int(self._profile.level(level).inner_chunk.get("z", 1))
            for level in range(self.levels)
        ]


class GovernedRun:
    """One governed run, served as a built picture that obeys its manifest.

    Ask :meth:`composer` on every request. While the manifest's fingerprint
    holds, the same composer comes back and every cache in it keeps earning
    its keep; the moment the fingerprint moves — a commit, a replacement, a
    rollback — a fresh snapshot is derived from the new truth and handed out
    instead. Nothing is ever mutated under a reader: a request that began on
    the old composer finishes on the old composer, whose answers were honest
    for the state it was built from.
    """

    def __init__(self, folder: str | Path, piece: int = PIECE,
                 store: str | Path | None = None):
        self.folder = Path(folder).resolve()
        self._run = _LiveRun(self.folder)
        self._piece = piece
        # The declared picture's own folder, when serving one that keeps a
        # baked coarse ground. The bake is real files and the run's ground
        # changes, so every derive patches the touched pieces before the
        # fresh snapshot answers anyone -- see _keep_the_bake_true. Without
        # a store (or without baked levels in it) nothing here changes.
        self._shown = Path(store).resolve() if store is not None else None
        self._baked: tuple[int, ...] | None = None
        self._bake_guard = threading.Lock()
        # A snapshot, its bake patch, and its installation are one ordered
        # transaction.  The bake guard alone is too late: two requests may
        # derive different states before it, then acquire it newest-first;
        # the older patcher rewrites newer ground before installation makes
        # it stand down.  Serial derivation lets the waiter reuse the state
        # just installed, or derive one catch-up snapshot from it.
        self._derive_guard = threading.Lock()
        # Announcements, rather than piece requests, drive the last derive
        # after a burst. One short-lived worker belongs to this opened run;
        # repeated announcements move its quiet deadline rather than baking
        # intermediate states behind the same lock page requests need.
        self._catch_up_guard = threading.Condition()
        self._catch_up_requested = False
        self._catch_up_after = 0.0
        self._catch_up_thread: threading.Thread | None = None
        self._closing = False
        # What the installed snapshot folded and framed, and what the stamp
        # said when this instance last patched -- the anchors that make
        # installation forward-only, frame moves total invalidations, and
        # the per-state patch skippable without re-reading anything.
        self._folded_installed = -1
        self._frame_installed: tuple[int, str] | None = None
        self._stamp_installed: dict | None = None
        self._mark: tuple[int, int, int, int] | None = None
        self._held: Composer | None = None
        # Which generation of which position the held composer draws, so the
        # next snapshot can say exactly what a change touched -- and the tile
        # each was read into, so the next snapshot can reuse it. A tile is
        # immutable per generation, which is what makes the reuse safe; it is
        # also what makes it necessary, because reading every tile again per
        # commit was measured at ~527 ms across ~900 positions, all of it
        # inside the operator's landing-to-visible latency, and linear in
        # the survey.
        self._drawing: dict[str, int] = {}
        self._tiles: dict[str, Tile] = {}
        # The one tile read from disk, standing in for the run's whole
        # geometry: every position is written by the same writer from the
        # same sealed profile, so every other tile is stamped from this one
        # rather than read -- see _a_tile_stamped. Remembered per profile,
        # because a layout revision naming a different profile would make the
        # stamp describe the wrong kind of store.
        self._pattern: Tile | None = None
        self._pattern_of: str | None = None
        # Where each planned position's first voxel sits, in micrometres,
        # worked out once per layout revision -- a revision is immutable, and
        # sweeping thousands of placements again per commit is the kind of
        # O(survey) term the derive has already shed twice.
        self._corners: dict[str, tuple[float, float, float]] = {}
        self._corners_mark: tuple[int, str] | None = None
        self._guard = threading.Lock()
        # What deriving snapshots has cost, for the scale harnesses: how many
        # times, how long the last one took, and how many tiles it read from
        # disk. Read in-process by whoever started the server; never consulted
        # by the serving path itself.
        self.accounting = {"derives": 0, "last_derive_ms": 0.0,
                           "last_tiles_read": 0, "last_positions": 0}

    def composer(self) -> Composer:
        """The composer for the manifest's state as of now."""
        with self._derive_guard:
            return self._derive_and_install_the_composer()

    def request_catch_up(self) -> None:
        """Schedule a demand-free derive, coalescing a burst of announcements."""
        with self._catch_up_guard:
            if self._closing:
                return
            self._catch_up_requested = True
            self._catch_up_after = (time.monotonic()
                                    + _BAKE_CATCH_UP_QUIET_S)
            if self._catch_up_thread is not None:
                self._catch_up_guard.notify_all()
                return
            worker = threading.Thread(
                target=self._catch_up_after_announcements,
                name=f"zmart-bake-catch-up-{self.folder.name}", daemon=True,
            )
            self._catch_up_thread = worker
            worker.start()
            self._catch_up_guard.notify_all()

    def _catch_up_after_announcements(self) -> None:
        """Keep deriving until the last announced manifest state is installed."""
        while True:
            with self._catch_up_guard:
                while True:
                    if self._closing:
                        self._catch_up_thread = None
                        return
                    wait_for = self._catch_up_after - time.monotonic()
                    if self._catch_up_requested and wait_for <= 0:
                        self._catch_up_requested = False
                        break
                    self._catch_up_guard.wait(
                        timeout=max(0.0, wait_for)
                        if self._catch_up_requested else None)
            try:
                self.composer()
                # Take the locks in the same order as composer. A request may
                # have derived between the call above and this check; its state
                # is just as good, and must be allowed to finish first.
                with self._derive_guard:
                    current = self._run.manifest.fingerprint()
                    with self._guard:
                        settled = current == self._mark
            except Exception:
                log.exception("the announced bake at %s could not catch up",
                              self.folder)
                with self._catch_up_guard:
                    if self._catch_up_requested and not self._closing:
                        continue
                    self._catch_up_thread = None
                    return
            with self._catch_up_guard:
                if self._closing:
                    self._catch_up_thread = None
                    return
                if not settled and not self._catch_up_requested:
                    self._catch_up_requested = True
                    self._catch_up_after = (time.monotonic()
                                            + _BAKE_CATCH_UP_QUIET_S)
                if self._catch_up_requested:
                    continue
                self._catch_up_thread = None
                return

    def _derive_and_install_the_composer(self) -> Composer:
        """Derive, patch and install one manifest state without overtaking."""
        mark = self._run.manifest.fingerprint()
        with self._guard:
            if mark == self._mark and self._held is not None:
                return self._held
            previous, before = self._held, dict(self._drawing)
            kept = dict(self._tiles)
        # A DAMAGED publication record must refuse the derive, never pass as
        # an empty run. The manifest's ordinary read deliberately answers
        # damage with "nothing published" -- the right fail-closed answer for
        # one pixel ask, and the wrong one for this long-lived server: folding
        # "nothing" would derive an empty picture, unbake real files to match
        # it, and answer 404s the viewer believes for the rest of its session.
        # The strict read raises for damaged, foreign or unreadable truth, the
        # serving layer answers "try again shortly" (503), and a repaired
        # record simply derives on the next ask. A genuinely empty run has a
        # VALID record saying so, and passes this check untouched.
        self._run.manifest.committed_strict()
        baked_picture = self._shown is not None and bool(
            self._the_baked_levels())
        began = time.perf_counter()
        layout, profile = self._run._geometry()
        # A frame that MOVED -- a new layout revision or another profile --
        # invalidates every piece and every inherited slab at once: one
        # more-negative placement shifts where every tile lands, with no
        # generation changing to say so. Review finding D6.
        framed = (layout.revision, profile.profile_id)
        moved_frame = previous is not None and framed != self._frame_installed
        made, drawing, tiles = self._compose_the_snapshot(before, kept)
        dirtied: dict[int, set[tuple[int, int]]] | None = None
        if previous is not None and not moved_frame:
            # Which positions appeared, vanished, or moved to another
            # generation -- worked out once, in one pass, and every
            # consumer below works from this set in O(change). Sweeping
            # the survey again inside each consumer was most of what
            # remained of the derive's growth at sixteen thousand
            # positions: several sweeps per commit, each identifying the
            # same handful of changes.
            changed_names = frozenset(
                one for one in before.keys() | drawing.keys()
                if before.get(one) != drawing.get(one)
            )
            # The paths the change retired: a replaced or vanished
            # position's old copies. Their cached blocks go no further.
            stale = frozenset(
                copy.held_in
                for one in changed_names
                if one in kept
                for copy in kept[one].copies
            )
            dirtied = self._what_changed_dirtied(
                previous, made,
                {one: kept[one] for one in changed_names if one in kept},
                {one: tiles[one] for one in changed_names if one in drawing},
            )
            made.inherit_the_unchanged(previous, dirtied, stale=stale)
            # The piece index moves house with the slabs, patched only where
            # the change reached -- see Composer.inherit_the_index.
            made.inherit_the_index(
                previous, dirtied, changed_names,
                [(one, tiles[one]) for one in drawing
                 if one in changed_names],
            )
        # The fold's own bookkeeping, NOT a fresh read of the events file:
        # the compose above already folded the manifest, and a second reader
        # racing the writer's appends was measured (twice) spamming
        # refused-history errors. The identity is (count, tail revision,
        # layout): a bare count read AHEAD of a rolled-back history and
        # left withdrawn ground served from files -- review finding D1.
        folded = self._run._folded
        if baked_picture:
            current = {"events": folded,
                       "tail": self._run._last_folded_revision,
                       "layout": layout.revision}
            self._keep_the_bake_true(
                made, None if moved_frame else dirtied, current)
        self.accounting["derives"] += 1
        self.accounting["last_derive_ms"] = (time.perf_counter() - began) * 1000
        self.accounting["last_positions"] = len(drawing)
        with self._guard:
            # Two threads may have derived DIFFERENT states -- a commit can
            # land between their fingerprint reads -- so installation is
            # forward-only by the fold's count: the thread holding the older
            # state stands down rather than replacing a newer one (review
            # finding D10). A ROLLBACK legitimately folds less than what is
            # installed, and is told apart from a stale racer by its
            # fingerprint still being the manifest's current one.
            if ((mark != self._mark or self._held is None)
                    and (folded >= self._folded_installed
                         or mark == self._run.manifest.fingerprint())):
                stood_down = self._held
                self._mark, self._held = mark, made
                self._drawing, self._tiles = drawing, tiles
                self._folded_installed = folded
                self._frame_installed = framed
            else:
                stood_down = made
        if stood_down is not None and stood_down is not self._held:
            stood_down.stop_warming()
        # The coarse ground, warmed in the background and pinned. At survey
        # scale a coarse piece covers a hundred-odd positions, and building
        # them on demand is the one slowness an operator feels on a cold
        # governed picture -- the whole overview arriving piece by expensive
        # piece under their eyes. Warmed pieces inherit across commits minus
        # each change's own footprint, so this is paid once per session and
        # then topped up by the change, never repeated. A BAKED picture
        # warms too, for a different debtor: its files already serve the
        # cold open, but its PATCHER composes every dirty piece, and a
        # change touching a cold region paid 0.5-3 s inside
        # landing-to-visible -- watched as tiles updating with inconsistent
        # timing -- against 60-90 ms wherever the slabs were warm. And a
        # baked picture's warm READS its slabs from those very files
        # instead of composing them -- the pieces already exist, patched to
        # this snapshot's state before anyone was answered.
        if baked_picture:
            self._held.warm_from_the_baked(
                self._shown,
                frozenset(one for one in self._the_baked_levels()
                          if one < self._held.mosaic.levels))
        self._held.keep_the_coarse_levels_warm()
        return self._held

    def _the_baked_levels(self) -> tuple[int, ...]:
        """Which levels the declared picture keeps as baked files, if any.

        Read once from the picture's own description: a declaration is what
        says whether this picture is baked, and re-declaring writes a new
        description and is served by a fresh GovernedRun.
        """
        if self._baked is None:
            held: tuple[int, ...] = ()
            described = self._shown / "zarr.json" if self._shown else None
            if described is not None and described.is_file():
                ours = (json.loads(described.read_text(encoding="utf-8"))
                        .get("attributes") or {}).get("zmart") or {}
                held = tuple(int(one) for one in ours.get("baked") or ())
            self._baked = held
        return self._baked

    def stamp_the_bake(self, store: str | Path | None = None, *,
                       events: int, tail: int, layout: int) -> None:
        """Write down exactly which manifest prefix the baked files absorbed.

        The stamp is an identity, never a bare count: the count of events
        folded, the revision of the LAST of them, and the layout revision
        the geometry was true under. A reopening session verifies the
        prefix -- the event at that count must carry that tail revision --
        so a history that was rolled back or rewritten under the bake reads
        as coverage unknown and everything is repatched, where a bare count
        read AHEAD of a shrunken history and left withdrawn ground served
        (review finding D1). Every caller states what it actually absorbed;
        a default that read the manifest at stamp time claimed commits the
        bake had never seen (finding D2). Written by sidecar and replace,
        because a torn stamp manufactures a full re-bake (finding D9).
        """
        where = Path(store).resolve() if store is not None else self._shown
        stamp = where / "baked.json"
        arriving = stamp.with_name("baked.json.stamping")
        arriving.write_text(
            json.dumps({"events": events, "tail": tail, "layout": layout}),
            encoding="utf-8")
        _after_a_windows_reader(os.replace, arriving, stamp)

    def _the_stamp(self) -> dict | None:
        """The stamp's identity, or ``None`` when nothing can be trusted.

        Missing, unreadable, or missing a field -- including a stamp from
        before the identity had its tail and layout -- all mean the same
        thing: the bake's coverage cannot be known, so everything is dirty.
        """
        stamp = self._shown / "baked.json"
        if not stamp.is_file():
            return None
        try:
            held = json.loads(stamp.read_text(encoding="utf-8"))
            return {"events": int(held["events"]), "tail": int(held["tail"]),
                    "layout": int(held["layout"])}
        except (ValueError, KeyError, TypeError):
            return None

    def _keep_the_bake_true(self, made: Composer,
                            dirtied: dict[int, set[tuple[int, int]]] | None,
                            current: dict) -> None:
        """Patch the baked files the manifest's movement reached, then stamp.

        Runs inside the derive, BEFORE the fresh snapshot is handed to
        anyone: once a reader can know about the new state, the files are
        already true for it, so the file door can never serve a withdrawn
        or superseded piece. ``current`` is the identity this snapshot
        folded -- event count, tail revision, layout revision. ``dirtied``
        is the derive's own footprint, trusted only while the files hold
        the state the previous snapshot stamped; a stamp that says anything
        else -- another state, a rolled-back history, coverage unknown --
        dirties everything, because footprints of ground the current
        records cannot name (finding D1) can only be covered by covering
        all of it.

        Patched once per manifest STATE, never once per racing thread: the
        engine fires many requests at a fresh commit, every one of them may
        derive the same snapshot (either is correct, one wins), and each
        patching again serialized twelve seconds of redundant work behind
        the guard and starved serving -- measured in the first baked churn.
        The stamp equality is the idempotence.

        Guarded across PROCESSES as well as threads: the thread guard means
        nothing to a second server on the same store, or to declare --bake
        running beside a server, and their sidecars and staging directories
        collide (review finding D7). The file lock is held by the operating
        system, so a patcher that dies releases it.
        """
        with self._bake_guard, _holding_the_bake_lock(self._shown):
            stamped = self._the_stamp()
            if stamped == current:
                self._stamp_installed = current
                return
            if dirtied is None or stamped != self._stamp_installed:
                dirtied = self._the_ground_the_bake_missed(made, current)
                if dirtied is None:
                    self._stamp_installed = current
                    return
            baked = self._the_baked_levels()
            for level in sorted(one for one in baked
                                if one < made.mosaic.levels):
                for row, column in sorted(dirtied.get(level, ())):
                    deep = made.grid(level)[0]
                    for plane in range(deep):
                        self._replace_one_piece(made, level, plane, row,
                                                column)
            coarsest = made.mosaic.levels - 1
            reached = dirtied.get(coarsest, set())
            for level in sorted(one for one in baked
                                if one >= made.mosaic.levels):
                reached = {(row // 2, column // 2)
                           for row, column in reached}
                if reached:
                    self._rehalve_one_level(level, sorted(reached))
            self.stamp_the_bake(events=current["events"],
                                tail=current["tail"],
                                layout=current["layout"])
            self._stamp_installed = current

    def _the_ground_the_bake_missed(self, made: Composer, current: dict,
                                    ) -> dict[int, set[tuple[int,
                                                             int]]] | None:
        """The footprints of every event the stamp cannot prove it absorbed.

        ``None`` when the bake is provably current. The stamp's claim is a
        PREFIX -- so many events, ending at such a revision, under such a
        layout -- and it is believed only when the history still carries
        exactly that prefix and the layout has not moved. Anything else --
        no stamp, a shorter history, a different tail, another layout --
        dirties everything, because ground that older records covered
        cannot be named from the current ones. This reads the events file
        (the one deliberate second reader, bounded to the first derive of
        a session and to recoveries); a torn read here refuses the derive,
        which is the fail-closed direction.
        """
        events = self._run.manifest.events()
        stamped = self._the_stamp()
        everything = {level: {(row, column)
                              for row in range(made.grid(level)[1])
                              for column in range(made.grid(level)[2])}
                      for level in range(made.mosaic.levels)}
        if stamped is None or stamped["layout"] != current["layout"]:
            return everything
        absorbed = stamped["events"]
        if absorbed > len(events) or absorbed < 0:
            return everything
        if absorbed and events[absorbed - 1].revision != stamped["tail"]:
            return everything
        if absorbed == len(events):
            return None
        missed = {event.position_id for event in events[absorbed:]}
        dirty: dict[int, set[tuple[int, int]]] = {}
        named = {tile.name.split(".")[0]: tile
                 for tile in made.mosaic.tiles
                 if tile.name.split(".")[0] in missed}
        for tile in named.values():
            for level in range(made.mosaic.levels):
                at = made.mosaic.lands_at(tile, level)
                held = tile.copies[level].shape
                reached = dirty.setdefault(level, set())
                for row in range(at[1] // self._piece,
                                 (at[1] + held[1] - 1) // self._piece + 1):
                    for column in range(
                            at[2] // self._piece,
                            (at[2] + held[2] - 1) // self._piece + 1):
                        reached.add((row, column))
        return dirty

    def _replace_one_piece(self, made: Composer, level: int, plane: int,
                           row: int, column: int) -> None:
        """One baked chunk file made true, atomically, or removed if empty."""
        inside = (self._shown / str(level) / "c" / str(plane) / str(row))
        baked = inside / str(column)
        body = made.bytes_for(level, plane, row, column)
        if body is None:
            if baked.is_file():
                _after_a_windows_reader(os.unlink, baked)
            return
        inside.mkdir(parents=True, exist_ok=True)
        arriving = baked.with_name(f"{baked.name}.baking")
        arriving.write_bytes(body)
        _after_a_windows_reader(os.replace, arriving, baked)

    def _rehalve_one_level(self, level: int,
                           pieces: list[tuple[int, int]]) -> None:
        """Recompute touched pieces of one extended level from the one below.

        The extended levels exist only as baked files, averaged 2x2 in y and
        x from the level beneath -- the same arithmetic the from-scratch
        bake uses, applied to the touched region instead of the whole.
        Reads past the lower level's edge clamp to its last row or column,
        which is what padding the whole array with its own edge produced.

        Written into a STAGING array and moved into place, never in place:
        zarr writes a chunk by truncating the file, and the engine refetches
        exactly these pieces the moment the change is announced -- a read
        catching the truncation decoded garbage and left the region black
        on screen until something touched it again, growing with every
        patch, watched happening at 6,400 positions. The staging array is
        the level's own metadata copied whole, so the encoding cannot drift
        from a fresh bake's; each staged chunk file then replaces the real
        one atomically, and a piece the halving left all-fill has its file
        removed, absence meaning fill here as everywhere.
        """
        below = zarr.open_array(str(self._shown / str(level - 1)), mode="r")
        staging = self._shown / f".patching-{level}"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir()
        shutil.copy2(self._shown / str(level) / "zarr.json",
                     staging / "zarr.json")
        above = zarr.open_array(str(staging), mode="r+")
        deep, height, width = above.shape
        for row, column in pieces:
            top, left = row * self._piece, column * self._piece
            bottom = min(top + self._piece, height)
            right = min(left + self._piece, width)
            wanted = (bottom - top, right - left)
            source = below[:, 2 * top:min(2 * bottom, below.shape[1]),
                           2 * left:min(2 * right, below.shape[2])]
            evened = np.pad(source,
                            ((0, 0), (0, 2 * wanted[0] - source.shape[1]),
                             (0, 2 * wanted[1] - source.shape[2])),
                            mode="edge")
            above[:, top:bottom, left:right] = (
                evened.reshape(deep, wanted[0], 2, wanted[1], 2)
                .mean(axis=(2, 4)).round().astype(above.dtype))
        planes = -(-deep // int(above.chunks[0]))
        for row, column in pieces:
            for plane in range(planes):
                staged = staging / "c" / str(plane) / str(row) / str(column)
                real = (self._shown / str(level) / "c" / str(plane)
                        / str(row) / str(column))
                if staged.is_file():
                    real.parent.mkdir(parents=True, exist_ok=True)
                    _after_a_windows_reader(os.replace, staged, real)
                elif real.is_file():
                    _after_a_windows_reader(os.unlink, real)
        shutil.rmtree(staging, ignore_errors=True)

    def _compose_the_snapshot(self, before: dict[str, int],
                              kept: dict[str, Tile],
                              ) -> tuple[Composer, dict[str, int],
                                         dict[str, Tile]]:
        """Derive tiles, frame and composer from the manifest's current truth.

        Nothing is read from disk here beyond the one pattern store, once per
        session: a position whose generation the previous snapshot already
        drew is carried over as the very object already in hand — open
        arrays, presence promise and all — and a CHANGED position is stamped
        from the pattern and the layout (see :func:`_a_tile_stamped`), which
        together already say everything the position's own files would. The
        cost of a derive is thereby its change, not the survey, cold opens
        included.
        """
        published = self._run._published_units()
        order = self._run._positions_in_commit_order()
        layout, profile = self._run._geometry()

        current: dict[str, int] = {}
        for position_id, _moment, generation in published:
            if generation > current.get(position_id, -1):
                current[position_id] = generation
        drawing = {
            position_id: current[position_id] for position_id in order
            # The two manifest reads above can straddle a commit, and then the
            # order names a position the published set does not know yet. Not
            # drawn HERE, deliberately: that commit moved the fingerprint, so
            # the very next ask derives again and draws it -- found by the
            # burst harness at ~26 adds a second as a KeyError and one piece
            # blinking absent, never at the writer's own cadence.
            if (position_id, 0, current.get(position_id)) in published
        }
        changed = [one for one, generation in drawing.items()
                   if before.get(one) != generation or one not in kept]
        read = 0
        fresh: dict[str, Tile] = {}
        if changed:
            corners = self._corners_of(layout, profile)
            for one in changed:
                if one not in corners:
                    raise ValueError(
                        f"the manifest publishes position {one!r}, but layout "
                        f"revision {layout.revision} does not place it. A "
                        "committed position the layout cannot place has no "
                        "corner to draw it at, so this is drift between the "
                        "run's records, refused rather than guessed around."
                    )
            if self._pattern is None or self._pattern_of != profile.profile_id:
                first = changed[0]
                self._pattern = self._the_pattern_read_and_checked(
                    first, drawing[first], corners[first])
                self._pattern_of = profile.profile_id
                read = 1
            fresh = {
                one: _a_tile_stamped(
                    self._pattern, self._the_store_of(one, drawing[one]),
                    corners[one])
                for one in changed
            }
        self.accounting["last_tiles_read"] = read
        tiles = {
            position_id: fresh.get(position_id) or kept[position_id]
            for position_id in drawing
        }
        ordered = [tiles[position_id] for position_id in drawing]
        return (Composer(TheWorldFrame(ordered, layout, profile),
                         piece=self._piece), drawing, tiles)

    def _the_pattern_read_and_checked(self, position_id: str, generation: int,
                                      corner_um: tuple[float, float, float],
                                      ) -> Tile:
        """Read the one store that stands in for every other, and check it.

        Stamping trusts the layout for every corner, so the one store that IS
        read is where that trust gets checked: its written translation must
        be the layout's placement to the last bit — the writer computed it
        from the very same numbers (``origin_pixels`` times the voxel size),
        so any difference at all means the writer and the layout have drifted
        apart, and every stamped corner would be quietly wrong on screen.
        """
        pattern = _read_one_tile(self._the_store_of(position_id, generation))
        for copy in pattern.copies:
            if copy.corner_um != corner_um:
                raise ValueError(
                    f"position {position_id!r} says its corner sits at "
                    f"{copy.corner_um} micrometres, but the layout places it "
                    f"at {corner_um}. The writer stamps a store's corner from "
                    "the layout's own placement, so a disagreement means the "
                    "run's records have drifted apart — and every other "
                    "position's corner is taken from the layout on that "
                    "store's word, so this is refused rather than drawn "
                    "somewhere quietly wrong."
                )
        return pattern

    def _corners_of(self, layout, profile) -> dict[str, tuple[float, float,
                                                              float]]:
        """Where each planned position's first voxel sits, in micrometres.

        The same arithmetic the writer uses for a store's translation
        (``zmart_live.omezarr._where_the_corner_sits``), applied to the
        layout every position came from — float by float, so the stamped
        corners and the written ones are bit-identical. Worked out once per
        layout revision, which is immutable.
        """
        named = (layout.revision, profile.profile_id)
        if self._corners_mark != named:
            voxel = tuple(float(profile.voxel_size.get(axis, 1.0))
                          for axis in ("z", "y", "x"))
            self._corners = {
                placement.position_id: tuple(
                    float(placement.origin.get(axis, 0.0)) * size
                    for axis, size in zip(("z", "y", "x"), voxel))
                for placement in layout.positions
            }
            self._corners_mark = named
        return self._corners

    def _what_changed_dirtied(self, previous: Composer, fresh: Composer,
                              was_tiles: dict[str, Tile],
                              now_tiles: dict[str, Tile],
                              ) -> dict[int, set[tuple[int, int]]]:
        """Which pieces the manifest's movement reached, per level.

        A position is a change if it appeared, vanished, or moved to another
        generation. Its footprint is collected from **both** snapshots'
        geometry — the ground a removal used to cover has to rebuild just as
        surely as the ground an arrival now covers — and everything outside
        those pieces is, by the manifest's own account, untouched.

        The changed positions' tiles arrive by name — ``was_tiles`` as the
        previous snapshot drew them, ``now_tiles`` as this one will — rather
        than being found by sweeping every tile of both snapshots. The sweep
        was O(survey) per commit spent identifying a handful of changes the
        caller already knew by name.
        """
        dirty: dict[int, set[tuple[int, int]]] = {}
        for composer, named in ((previous, was_tiles), (fresh, now_tiles)):
            for tile in named.values():
                for level in range(composer.mosaic.levels):
                    at = composer.mosaic.lands_at(tile, level)
                    held = tile.copies[level].shape
                    reached = dirty.setdefault(level, set())
                    for row in range(at[1] // self._piece,
                                     (at[1] + held[1] - 1) // self._piece + 1):
                        for column in range(
                                at[2] // self._piece,
                                (at[2] + held[2] - 1) // self._piece + 1):
                            reached.add((row, column))
        return dirty

    def close(self) -> None:
        """Let go of the held snapshot, closing whatever it holds open."""
        with self._catch_up_guard:
            self._closing = True
            catching_up = self._catch_up_thread
            self._catch_up_requested = False
            self._catch_up_guard.notify_all()
        if (catching_up is not None
                and catching_up is not threading.current_thread()):
            catching_up.join()
        with self._derive_guard, self._guard:
            held, self._held, self._mark = self._held, None, None
            self._drawing = {}
        if held is not None:
            held.close()

    def _the_store_of(self, position_id: str, generation: int) -> Path:
        """Where one published position's current pixels live.

        The same naming rule the run's own writer uses: generation zero keeps
        the plain name, every replacement carries its number.
        """
        if generation == 0:
            name = f"{position_id}{IMAGE_SUFFIX}"
        else:
            name = f"{position_id}.generation-{generation}{IMAGE_SUFFIX}"
        return self.folder / "positions" / name

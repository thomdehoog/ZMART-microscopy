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

The served picture carries whatever axes the run records: a flat run is
three axes (z, y, x), and a run whose profile keeps room for several
moments or channels is served grown, five axes with one frame per chunk,
every requested (moment, channel) read against the position stores' own
front axes and gated by the record — see :meth:`TheWorldFrame.frame_room`
and the combined-axes oracle in ``test_every_plane_serves_its_own_stamp``.
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
from composer import PIECE, Composer
from mosaic import Copy, Mosaic, Tile, _read_one_tile

from zmart_live.gateway import _LiveRun
from zmart_live.model import rounded_up
from zmart_live.shardlink import how_the_array_is_stored

log = logging.getLogger("zmart-viewer.governed")

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

    def is_on_disk(index: tuple[int, ...]) -> bool:
        # The FULL chunk index, front axes included -- the composer passes
        # the requested (moment, channel) ahead of (z, y, x), so the promise
        # is checked for exactly the frame being served.
        if not stored:
            stored.append(how_the_array_is_stored(copy.held_in))
        return stored[0].where_one_chunk_lives(tuple(index)) is not None

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
                    corner_um: tuple[float, float, float],
                    moments: frozenset[int] | None = None) -> Tile:
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
            outer_shape=one.outer_shape,
        ))
        for one in pattern.copies
    ]
    return Tile(name=store.name, store=store, copies=copies,
                axes=pattern.axes, turned=pattern.turned, moments=moments)


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

    def __init__(self, tiles, layout, profile, *, run: Path):
        # The RUN FOLDER is part of every remembered key, and load-bearing:
        # a viewer process outlives one acquisition, and the same script run
        # again into a fresh folder carries the same run name, the same
        # sealed profile and a layout starting from the same revision
        # number. Keyed without the folder, the second run read the first
        # run's origin and extent -- a 64-position survey served inside a
        # 16-position frame, its outer tiles composing negative windows and
        # answering 503 for ever (FINDING_grown_slab_windows_race_the_warm,
        # 2026-08-19, and test_two_runs_share_one_process pins it).
        named = (run, layout.run_id, layout.revision, profile.profile_id)
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
        self._run_folder = run

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
            named = (self._run_folder, self._layout.run_id,
                     self._layout.revision, self._profile.profile_id, level)
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
                    reach.append(rounded_up(int(edge), int(down)))
                found = tuple(reach)
                TheWorldFrame._shapes[named] = found
            self._shape[level] = found  # type: ignore[assignment]
        return found  # type: ignore[return-value]

    @property
    def frame_room(self) -> tuple[int, int]:
        """The run's (moments, channels) room, knowable before any arrival.

        The sealed profile declares both, so an empty run's picture already
        has its full shape. The arrays still get a say for runs sealed
        before the profile carried the time room — there the arrays are
        the only durable declaration — so whichever source declares more
        moments is believed.
        """
        from_tiles = super().frame_room
        return (max(int(self._profile.timepoints), from_tiles[0]),
                len(self._profile.channels))

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
        # The zarr handles the bake patcher works through, opened once per
        # opened run rather than once per landing. The declared store's
        # geometry is fixed at declaration -- re-declaring serves a fresh
        # GovernedRun -- so a handle opened for one landing is just as true
        # for every later one, and reopening them per commit was measured as
        # most of what a landing cost on a large survey (see the bake
        # accounting below and test_a_landing_costs_the_change_not_the_survey).
        self._bake_below: dict[int, zarr.Array] = {}
        self._bake_staging: dict[int, zarr.Array] = {}
        # Each baked level's chunk encoding, parsed once from its zarr.json
        # (False marks "not looked yet", None marks "not an encoding the
        # direct path speaks"). See _the_baked_recipe.
        self._bake_recipes: dict[int, dict | None] = {}
        # What deriving snapshots has cost, for the scale harnesses: how many
        # times, how long the last one took, and how many tiles it read from
        # disk. The bake counters say how much machinery the LAST patch built
        # rather than reused -- arrays opened, staging folders constructed --
        # because a landing's cost must be the change, and rebuilding scaffolds
        # per landing was where a large survey's landings quietly grew dear.
        # Read in-process by whoever started the server; never consulted by
        # the serving path itself.
        self.accounting = {"derives": 0, "last_derive_ms": 0.0,
                           "last_tiles_read": 0, "last_positions": 0,
                           "last_bake_arrays_opened": 0,
                           "last_bake_stagings_built": 0,
                           "last_bake_zarr_ops": 0,
                           "last_bake_pieces_rehalved": 0,
                           "last_bake_slabs_built": 0,
                           "last_bake_slabs_warm": 0,
                           "last_snapshot_swept": 0}

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
        # Where this derive's time went, phase by phase, for the scale
        # harnesses. The whole call is covered -- including the tail after
        # the snapshot is installed, which last_derive_ms deliberately does
        # not include -- because a landing's cost to the operator is the
        # whole call, and attributing a slow landing needs every phase to
        # have a name. Filled only on real derives; the cached early return
        # above leaves the previous derive's story in place.
        phases: dict[str, float] = {}
        watch = time.perf_counter
        marked = watch()
        self._run.manifest.committed_strict()
        phases["strict_read"] = (watch() - marked) * 1000
        baked_picture = self._shown is not None and bool(
            self._the_baked_levels())
        began = time.perf_counter()
        marked = watch()
        layout, profile = self._run._geometry()
        # A frame that MOVED -- a new layout revision or another profile --
        # invalidates every piece and every inherited slab at once: one
        # more-negative placement shifts where every tile lands, with no
        # generation changing to say so. Review finding D6.
        framed = (layout.revision, profile.profile_id)
        moved_frame = previous is not None and framed != self._frame_installed
        made, drawing, tiles = self._compose_the_snapshot(before, kept)
        phases["compose"] = (watch() - marked) * 1000
        marked = watch()
        dirtied: dict[int, set[tuple[int, int]]] | None = None
        dirty_moments: frozenset[int] | None = None
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
                # A new MOMENT moves no generation, but the piece it lands
                # in may hold an inherited slab built when that moment was
                # still absent -- serving it warm would show yesterday's
                # emptiness over today's commit (caught by the combined-axes
                # oracle the day this line was written).
                or (one in kept and one in tiles
                    and kept[one].moments != tiles[one].moments)
            )
            # The paths the change retired: a replaced or vanished
            # position's old copies. Their cached blocks go no further. A
            # moments-only change retires nothing -- the store is the same
            # store, and its other moments' decoded blocks stay warm.
            stale = frozenset(
                copy.held_in
                for one in changed_names
                if one in kept and before.get(one) != drawing.get(one)
                for copy in kept[one].copies
            )
            dirtied = self._what_changed_dirtied(
                previous, made,
                {one: kept[one] for one in changed_names if one in kept},
                {one: tiles[one] for one in changed_names if one in drawing},
            )
            # WHICH MOMENTS the change touched, for the baked patch: the
            # footprint above names ground in y and x, and recomposing that
            # ground across a whole timelapse per commit is the frozen
            # picture the stage-0 instruments measured (~165-190 s at a
            # 500-moment retake). A moments-only change touches exactly the
            # moments that came or went; a position that appeared, vanished
            # or moved to another generation touches every moment either
            # side has written, because another store now backs all of them.
            touched: set[int] = set()
            for one in changed_names:
                was = kept[one].moments if one in kept else frozenset()
                now = tiles[one].moments if one in tiles else frozenset()
                touched |= (was | now if before.get(one) != drawing.get(one)
                            else was ^ now)
            dirty_moments = frozenset(touched)
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
        phases["inherit"] = (watch() - marked) * 1000
        if baked_picture:
            current = {"events": folded,
                       "tail": self._run._last_folded_revision,
                       "layout": layout.revision}
            self._keep_the_bake_true(
                made, None if moved_frame else dirtied, current, phases,
                moments=None if moved_frame else dirty_moments)
        self.accounting["derives"] += 1
        self.accounting["last_derive_ms"] = (time.perf_counter() - began) * 1000
        self.accounting["last_positions"] = len(drawing)
        marked = watch()
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
        phases["install"] = (watch() - marked) * 1000
        marked = watch()
        if stood_down is not None and stood_down is not self._held:
            stood_down.stop_warming()
        phases["stop_warming"] = (watch() - marked) * 1000
        marked = watch()
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
        phases["warm"] = (watch() - marked) * 1000
        self.accounting["last_phase_ms"] = phases
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
                            current: dict,
                            phases: dict[str, float] | None = None, *,
                            moments: frozenset[int] | None = None) -> None:
        """Patch the baked files the manifest's movement reached, then stamp.

        ``moments`` bounds the patch along time for a grown run: only these
        moments' frames of the dirty footprint are recomposed (every channel
        of each, since a publication writes all channels at once). ``None``
        means every moment in the room -- the recovery direction, taken
        whenever the footprint itself cannot be trusted. The bound is the
        c-and-t plan's build gate: the stage-0 instruments projected minutes
        of frozen picture per retake for a whole-room patch at 500 moments,
        against a flat cost for patching only what the commit touched.

        ``phases`` is the derive's phase ledger (see the derive), written
        into here so a slow landing can say WHICH bake phase was slow:
        scanning the stamp, composing dirty pieces, re-halving extended
        levels, or writing the stamp back.

        Dirty composed pieces are recomposed whole, deliberately. A
        paste-over variant -- re-lay only the changed ground over the
        decoded existing chunk file -- was built, proven correct against
        an overlap proof and a pixel-equality oracle, and then REVERTED on
        measurement: it cut tile reads from 143 to 4 per landing and made
        every landing SLOWER (17.7 to 59.2 ms on a small survey). The
        compose anatomy that was built afterwards says why the first
        post-mortem was itself wrong: the dirty piece's slab is rebuilt
        from scratch every landing (zero warm hits -- inheritance rightly
        drops dirty slabs), tile reading is 60-75%% of the compose phase,
        so cutting reads WAS aimed at real money -- and the chunk-file
        paste still lost because its own path carried ~50 ms of overhead
        for four reads that was never attributed before the revert. Two
        lessons stand. Measured: reads dominate compose, encode is 3-10 ms,
        and the correctly-aimed cure is to re-lay the changed ground into
        the INHERITED SLAB -- decoded pixels already in memory, no chunk
        decode anywhere -- before encoding as usual. Methodological: that
        cure is not to be built until a red gate denominated in
        bake_compose_read milliseconds exists, and until the cure's own
        path is split the way the compose phase now is.

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
        if phases is None:
            phases = {}
        watch = time.perf_counter
        marked = watch()
        with self._bake_guard, _holding_the_bake_lock(self._shown):
            self.accounting["last_bake_arrays_opened"] = 0
            self.accounting["last_bake_stagings_built"] = 0
            self.accounting["last_bake_zarr_ops"] = 0
            self.accounting["last_bake_pieces_rehalved"] = 0
            self.accounting["last_bake_pieces_composed"] = 0
            self.accounting["last_bake_tile_reads"] = 0
            stamped = self._the_stamp()
            if stamped == current:
                self._stamp_installed = current
                phases["bake_scan"] = (watch() - marked) * 1000
                return
            if dirtied is None or stamped != self._stamp_installed:
                dirtied, moments = self._the_ground_the_bake_missed(made,
                                                                    current)
                if dirtied is None:
                    self._stamp_installed = current
                    phases["bake_scan"] = (watch() - marked) * 1000
                    return
            baked = self._the_baked_levels()
            phases["bake_scan"] = (watch() - marked) * 1000
            marked = watch()
            reads_before = made.tile_reads
            costs_before = dict(made.costs)
            # A grown run bakes one file per (moment, channel) frame. The
            # footprint only names ground in y and x, so time is bounded
            # here: only the touched moments' frames are recomposed, every
            # channel of each (see the ``moments`` contract above).
            moments_room, channels = made.mosaic.frame_room
            patched = (range(moments_room) if moments is None else
                       sorted(one for one in moments if one < moments_room))
            for level in sorted(one for one in baked
                                if one < made.mosaic.levels):
                for row, column in sorted(dirtied.get(level, ())):
                    deep = made.grid(level)[0]
                    for moment in patched:
                        for channel in range(channels):
                            self.accounting[
                                "last_bake_pieces_composed"] += 1
                            for plane in range(deep):
                                self._replace_one_piece(
                                    made, level, plane, row, column,
                                    moment=moment, channel=channel)
            # The compose phase split into its components, from the
            # composer's own cost ledger: time spent reading tiles, building
            # slabs (laying included -- reading happens inside building, so
            # lay time is build minus read), and encoding pieces, beside how
            # many slabs were built against answered warm. This split exists
            # because a cure was once aimed at the read COUNT and made
            # landings slower; whatever is aimed at next is aimed at a
            # measured component of the wall clock, or not at all.
            for cost in ("read_ms", "build_ms", "encode_ms"):
                phases["bake_compose_" + cost[:-3]] = (
                    made.costs[cost] - costs_before[cost])
            self.accounting["last_bake_slabs_built"] = (
                made.costs["slabs_built"] - costs_before["slabs_built"])
            self.accounting["last_bake_slabs_warm"] = (
                made.costs["slabs_warm"] - costs_before["slabs_warm"])
            # How many tile rectangles composing the dirty pieces read --
            # a hundred-odd at survey scale for a one-position change, and
            # measured to be the WRONG number to optimise: shrinking it to
            # four (see the docstring above) made landings slower, because
            # warm slabs already amortize these reads. Kept as a diagnostic,
            # not a target.
            self.accounting["last_bake_tile_reads"] = (
                made.tile_reads - reads_before)
            phases["bake_compose"] = (watch() - marked) * 1000
            marked = watch()
            coarsest = made.mosaic.levels - 1
            reached = dirtied.get(coarsest, set())
            # The extended levels are re-halved under the same time bound:
            # one (moment, channel) address per touched frame, or the single
            # empty address that is the flat form.
            frames = ([()] if (moments_room, channels) == (1, 1) else
                      [(moment, channel) for moment in patched
                       for channel in range(channels)])
            for level in sorted(one for one in baked
                                if one >= made.mosaic.levels):
                reached = {(row // 2, column // 2)
                           for row, column in reached}
                if reached:
                    self._rehalve_one_level(level, sorted(reached), frames)
            phases["bake_rehalve"] = (watch() - marked) * 1000
            marked = watch()
            self.stamp_the_bake(events=current["events"],
                                tail=current["tail"],
                                layout=current["layout"])
            self._stamp_installed = current
            phases["bake_stamp"] = (watch() - marked) * 1000

    def _the_ground_the_bake_missed(self, made: Composer, current: dict,
                                    ) -> tuple[dict[int, set[tuple[int,
                                                                   int]]]
                                               | None,
                                               frozenset[int] | None]:
        """The footprints of every event the stamp cannot prove it absorbed.

        Returns the dirty footprint and WHICH MOMENTS it is dirty at --
        ``(None, None)`` when the bake is provably current. The stamp's
        claim is a PREFIX -- so many events, ending at such a revision,
        under such a layout -- and it is believed only when the history
        still carries exactly that prefix and the layout has not moved.
        Anything else -- no stamp, a shorter history, a different tail,
        another layout -- dirties everything at every moment, because
        ground that older records covered cannot be named from the current
        ones. When the prefix IS believed, the missed events each name the
        moment they committed, and those moments bound the patch along
        time; a replacement event moves its position to a new store whose
        inherited moments the event does not name, so it widens the bound
        back to every moment. This reads the events file (the one
        deliberate second reader, bounded to the first derive of a session
        and to recoveries); a torn read here refuses the derive, which is
        the fail-closed direction.
        """
        events = self._run.manifest.events()
        stamped = self._the_stamp()
        everything = {level: {(row, column)
                              for row in range(made.grid(level)[1])
                              for column in range(made.grid(level)[2])}
                      for level in range(made.mosaic.levels)}
        if stamped is None or stamped["layout"] != current["layout"]:
            return everything, None
        absorbed = stamped["events"]
        if absorbed > len(events) or absorbed < 0:
            return everything, None
        if absorbed and events[absorbed - 1].revision != stamped["tail"]:
            return everything, None
        if absorbed == len(events):
            return None, None
        touched: set[int] | None = set()
        for event in events[absorbed:]:
            if event.event_type == "position_replaced" or touched is None:
                touched = None
            else:
                touched.add(0 if event.timepoint is None
                            else event.timepoint)
        moments = None if touched is None else frozenset(touched)
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
        return dirty, moments

    def _replace_one_piece(self, made: Composer, level: int, plane: int,
                           row: int, column: int, *, moment: int = 0,
                           channel: int = 0) -> None:
        """One baked chunk file made true, atomically, or removed if empty.

        A grown run's chunk files carry the (moment, channel) frame in
        their path, exactly where the from-scratch bake writes them; a
        flat run keeps the three-part path it always had.
        """
        frame = ((str(moment), str(channel))
                 if made.mosaic.frame_room != (1, 1) else ())
        inside = self._shown.joinpath(str(level), "c", *frame, str(plane),
                                      str(row))
        baked = inside / str(column)
        body = made.bytes_for(level, plane, row, column,
                              moment=moment, channel=channel)
        if body is None:
            if baked.is_file():
                _after_a_windows_reader(os.unlink, baked)
            return
        inside.mkdir(parents=True, exist_ok=True)
        arriving = baked.with_name(f"{baked.name}.baking")
        arriving.write_bytes(body)
        _after_a_windows_reader(os.replace, arriving, baked)

    def _rehalve_one_level(self, level: int, pieces: list[tuple[int, int]],
                           frames: list[tuple[int, ...]]) -> None:
        """Recompute touched pieces of one extended level from the one below.

        ``frames`` are the (moment, channel) addresses to re-halve -- the
        touched frames of a grown run, or the one empty address that is the
        flat form. Only these frames' chunk files are staged and moved;
        every other frame's files stay exactly as they were, which is both
        the time bound and the correctness (an untouched frame's ground did
        not move, so its files are still true).

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

        The handles and the staging folder are built ONCE per opened run and
        reused for every later landing. Rebuilding them per landing -- a
        directory teardown, a metadata copy, and five array opens per level,
        under the bake lock -- was measured as the bulk of what one landing
        cost on a 32x32 survey, and none of it changes between landings: the
        declared store's geometry is fixed, and every staged chunk file is
        moved out of the staging folder before the patch ends, so the folder
        comes back empty. The one teardown that still happens is the first
        of a session, which also sweeps away whatever a crashed predecessor
        may have left staged.
        """
        below = self._bake_below.get(level)
        if below is None:
            below = zarr.open_array(str(self._shown / str(level - 1)),
                                    mode="r")
            self._bake_below[level] = below
            self.accounting["last_bake_arrays_opened"] += 1
        staging = self._shown / f".patching-{level}"
        above = self._bake_staging.get(level)
        if above is None:
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir()
            shutil.copy2(self._shown / str(level) / "zarr.json",
                         staging / "zarr.json")
            above = zarr.open_array(str(staging), mode="r+")
            self._bake_staging[level] = above
            self.accounting["last_bake_arrays_opened"] += 1
            self.accounting["last_bake_stagings_built"] += 1
        # A grown run's extended levels carry the (t, c) room in front of
        # the three spatial axes; the halving touches only y and x, so each
        # frame in ``frames`` shrinks as itself, one at a time.
        deep, height, width = above.shape[-3:]
        self.accounting["last_bake_pieces_rehalved"] += len(pieces)
        served_recipe = self._the_baked_recipe(level)
        source_recipe = self._the_baked_recipe(level - 1)
        if (served_recipe is not None and source_recipe is not None
                and served_recipe["shape"][0] == source_recipe["shape"][0]):
            # The direct path: the chunk files are read and written through
            # the recipe their own zarr.json states, skipping the array
            # API's per-operation dispatcher -- measured as milliseconds of
            # thread handoff per call against about one millisecond of
            # actual pixel arithmetic per landing, paid under the bake lock.
            # The recipe check above is what keeps this honest: an encoding
            # this repository did not write takes the general path below.
            for row, column in pieces:
                self._rehalve_one_piece_directly(
                    level, staging, source_recipe, served_recipe,
                    row, column)
        else:
            for row, column in pieces:
                top, left = row * self._piece, column * self._piece
                bottom = min(top + self._piece, height)
                right = min(left + self._piece, width)
                wanted = (bottom - top, right - left)
                for address in frames:
                    # The leading integers pick one (moment, channel) frame
                    # (none for a flat run), so what is read and halved is
                    # always one three-axis block.
                    source = below[(*address, slice(None),
                                    slice(2 * top,
                                          min(2 * bottom, below.shape[-2])),
                                    slice(2 * left,
                                          min(2 * right, below.shape[-1])))]
                    self.accounting["last_bake_zarr_ops"] += 1
                    evened = np.pad(
                        source,
                        ((0, 0), (0, 2 * wanted[0] - source.shape[-2]),
                         (0, 2 * wanted[1] - source.shape[-1])),
                        mode="edge")
                    above[(*address, slice(None), slice(top, bottom),
                           slice(left, right))] = (
                        evened.reshape(deep, wanted[0], 2, wanted[1], 2)
                        .mean(axis=(2, 4)).round().astype(above.dtype))
                    self.accounting["last_bake_zarr_ops"] += 1
        planes = -(-deep // int(above.chunks[-3]))
        # Only the frames that were just re-halved are moved (or removed
        # where the halving left all-fill); an unpatched frame's staged
        # file is absent because nothing was written, and its real file
        # must be LEFT, not unlinked -- it is still true.
        for row, column in pieces:
            for address in frames:
                parts = tuple(str(one) for one in address)
                for plane in range(planes):
                    staged = staging.joinpath("c", *parts, str(plane),
                                              str(row), str(column))
                    real = self._shown.joinpath(str(level), "c", *parts,
                                                str(plane), str(row),
                                                str(column))
                    if staged.is_file():
                        real.parent.mkdir(parents=True, exist_ok=True)
                        _after_a_windows_reader(os.replace, staged, real)
                    elif real.is_file():
                        _after_a_windows_reader(os.unlink, real)
        # The staging folder stays, empty of chunks -- every staged file was
        # just moved out or was never written -- so the next landing reuses
        # it instead of paying to rebuild it. See the docstring above.

    def _the_baked_recipe(self, level: int) -> dict | None:
        """How one baked level's chunk files are encoded, or None to go general.

        Read once per level from the level's own ``zarr.json`` -- the same
        recipe every other reader of these files uses, so the direct path
        below can never drift from what zarr itself would write. ``None``
        means the encoding is not the one this repository's declare writes
        (little-endian raw bytes then zstd, one z-plane per chunk, pieces
        the size of chunks), and the caller must take the general array-API
        path instead: correct for any encoding, merely slower. A GROWN
        run's extended levels are five-axis (their chunk shape is five
        long), so they land on the general path by this same check -- the
        direct recipe only ever speaks for the flat three-axis form.
        """
        found = self._bake_recipes.get(level, False)
        if found is not False:
            return found
        recipe = None
        try:
            described = json.loads(
                (self._shown / str(level) / "zarr.json").read_text(
                    encoding="utf-8"))
            codecs = described["codecs"]
            chunk = described["chunk_grid"]["configuration"]["chunk_shape"]
            if (len(codecs) == 2
                    and codecs[0]["name"] == "bytes"
                    and codecs[0]["configuration"]["endian"] == "little"
                    and codecs[1]["name"] == "zstd"
                    and not codecs[1]["configuration"].get("checksum")
                    and len(chunk) == 3 and chunk[0] == 1
                    and chunk[1] == self._piece and chunk[2] == self._piece):
                recipe = {
                    "shape": tuple(int(one) for one in described["shape"]),
                    "dtype": np.dtype(described["data_type"])
                    .newbyteorder("<"),
                    "fill": described["fill_value"],
                    "zstd_level": int(codecs[1]["configuration"]["level"]),
                }
        except (OSError, KeyError, TypeError, ValueError):
            recipe = None
        self._bake_recipes[level] = recipe
        return recipe

    def _rehalve_one_piece_directly(self, level: int, staging: Path,
                                    source_recipe: dict, served_recipe: dict,
                                    row: int, column: int) -> None:
        """One piece of one extended level, re-halved file by file.

        The same arithmetic as the array path -- assemble the 2x2 ground
        beneath the piece, clamp at the picture's edge by repeating the last
        row or column, average 2x2, round, cast -- performed on chunk files
        decoded and encoded through the level's own recipe. A chunk file
        that does not exist reads as fill, and a result that is entirely
        fill is not written, so absence keeps meaning fill on the way out
        exactly as it does on the way in.
        """
        from numcodecs import Zstd

        deep, height, width = served_recipe["shape"]
        below_deep, below_height, below_width = source_recipe["shape"]
        piece = self._piece
        top, left = row * piece, column * piece
        wanted = (min(top + piece, height) - top,
                  min(left + piece, width) - left)
        src_h = min(2 * (top + wanted[0]), below_height) - 2 * top
        src_w = min(2 * (left + wanted[1]), below_width) - 2 * left
        below_dir = self._shown / str(level - 1)
        source_dtype = source_recipe["dtype"]
        packing = Zstd(level=served_recipe["zstd_level"])
        unpacking = Zstd()
        for plane in range(deep):
            canvas = np.empty((src_h, src_w), dtype=source_dtype)
            for down in (0, 1):
                for across in (0, 1):
                    grid_row, grid_col = 2 * row + down, 2 * column + across
                    row0 = grid_row * piece
                    col0 = grid_col * piece
                    if row0 >= 2 * top + src_h or col0 >= 2 * left + src_w:
                        continue
                    rows = min(piece, 2 * top + src_h - row0)
                    cols = min(piece, 2 * left + src_w - col0)
                    held = (below_dir / "c" / str(plane) / str(grid_row)
                            / str(grid_col))
                    if held.is_file():
                        block = np.frombuffer(
                            unpacking.decode(held.read_bytes()),
                            dtype=source_dtype).reshape(1, piece, piece)
                        part = block[0, :rows, :cols]
                    else:
                        part = np.full((rows, cols),
                                       source_recipe["fill"], source_dtype)
                    canvas[row0 - 2 * top:row0 - 2 * top + rows,
                           col0 - 2 * left:col0 - 2 * left + cols] = part
            evened = np.pad(canvas[None],
                            ((0, 0), (0, 2 * wanted[0] - src_h),
                             (0, 2 * wanted[1] - src_w)), mode="edge")
            halved = (evened.reshape(1, wanted[0], 2, wanted[1], 2)
                      .mean(axis=(2, 4)).round()
                      .astype(served_recipe["dtype"]))
            buffer = np.full((1, piece, piece), served_recipe["fill"],
                             served_recipe["dtype"])
            buffer[0, :wanted[0], :wanted[1]] = halved[0]
            if np.all(buffer == served_recipe["fill"]):
                continue
            staged = staging / "c" / str(plane) / str(row)
            staged.mkdir(parents=True, exist_ok=True)
            (staged / str(column)).write_bytes(
                packing.encode(np.ascontiguousarray(buffer).tobytes()))

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
        # Which moments each position has published AT ITS CURRENT generation
        # -- the set a tile carries so the composer can serve moment t of one
        # position and honest absence of another. Built in ONE pass over the
        # published units (a per-position sweep here would be O(positions x
        # units) on the per-commit hot path this whole derive keeps O(change)).
        # Gating the drawn set on it, rather than on moment zero as this used
        # to, also lets a position whose first commit named a later moment be
        # drawn at all -- the record allows arriving late.
        gathered: dict[str, set[int]] = {}
        for position_id, moment, generation in published:
            if generation == current[position_id]:
                gathered.setdefault(position_id, set()).add(moment)
        moments_of = {position_id: frozenset(moments)
                      for position_id, moments in gathered.items()}
        drawing = {
            position_id: current[position_id] for position_id in order
            # The two manifest reads above can straddle a commit, and then the
            # order names a position the published set does not know yet. Not
            # drawn HERE, deliberately: that commit moved the fingerprint, so
            # the very next ask derives again and draws it -- found by the
            # burst harness at ~26 adds a second as a KeyError and one piece
            # blinking absent, never at the writer's own cadence.
            if moments_of.get(position_id)
        }
        changed = [one for one, generation in drawing.items()
                   if before.get(one) != generation or one not in kept
                   # A new MOMENT moves no generation, but the tile carries
                   # its committed-moment set, so the tile must be restamped
                   # (cheap: no file is read) or the landing would serve as
                   # absent from the carried-over tile.
                   or kept[one].moments != moments_of[one]]
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
                    corners[one], moments=moments_of[one])
                for one in changed
            }
        self.accounting["last_tiles_read"] = read
        tiles = {
            position_id: fresh.get(position_id) or kept[position_id]
            for position_id in drawing
        }
        ordered = [tiles[position_id] for position_id in drawing]
        # How many position entries this snapshot's bookkeeping handled --
        # the fold above, the drawing and tiles dictionaries, and the
        # ordered tile list, each of which currently walks the whole survey
        # however small the change was. Written down so the growth is a
        # number a test can hold, not a suspicion: a landing's bookkeeping
        # should be the size of the landing, and today it is the size of
        # the survey, which at ten thousand positions becomes the dominant
        # cost of every commit (see
        # test_absorbing_a_change_touches_the_change).
        # Two passes over the published units now: the generation fold and
        # the per-position moment gathering above.
        self.accounting["last_snapshot_swept"] = (
            2 * len(published) + len(order) + 2 * len(drawing))
        return (Composer(TheWorldFrame(ordered, layout, profile,
                                       run=self.folder),
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
                    for axis, size in zip(("z", "y", "x"), voxel,
                                          strict=True))
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
            # The bake patcher's handles go with the run. A zarr array holds
            # no file open between operations, so letting the objects go is
            # all the closing they need.
            self._bake_below = {}
            self._bake_staging = {}
            self._bake_recipes = {}
        if held is not None:
            held.close()

    def _the_store_of(self, position_id: str, generation: int) -> Path:
        """Where one published position's current pixels live.

        The same naming rule the run's own writer uses: every position is a
        member of the run's one collection zarr, generation zero keeps the
        plain name, and every replacement carries its number.
        """
        if generation == 0:
            name = position_id
        else:
            name = f"{position_id}.generation-{generation}"
        return self.folder / "data" / "survey.ome.zarr" / name

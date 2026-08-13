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

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from zmart_live.gateway import _LiveRun
from zmart_live.shardlink import how_the_array_is_stored

from composer import PIECE, Composer
from mosaic import IMAGE_SUFFIX, Copy, Mosaic, Tile, _read_one_tile


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

    def __init__(self, tiles, layout, profile):
        origin_um = tuple(
            min((float(placement.origin.get(axis, 0))
                 * float(profile.voxel_size.get(axis, 1.0))
                 for placement in layout.positions),
                default=0.0)
            for axis in ("z", "y", "x")
        )
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

    def __init__(self, folder: str | Path, piece: int = PIECE):
        self.folder = Path(folder).resolve()
        self._run = _LiveRun(self.folder)
        self._piece = piece
        self._mark: tuple[int, int, int, int] | None = None
        self._held: Composer | None = None
        # Which generation of which position the held composer draws, so the
        # next snapshot can say exactly what a change touched.
        self._drawing: dict[str, int] = {}
        self._guard = threading.Lock()
        # What deriving snapshots has cost, for the scale harnesses: how many
        # times, how long the last one took, and how many tiles it read from
        # disk. Read in-process by whoever started the server; never consulted
        # by the serving path itself.
        self.accounting = {"derives": 0, "last_derive_ms": 0.0,
                           "last_tiles_read": 0, "last_positions": 0}

    def composer(self) -> Composer:
        """The composer for the manifest's state as of now."""
        mark = self._run.manifest.fingerprint()
        with self._guard:
            if mark == self._mark and self._held is not None:
                return self._held
            previous, before = self._held, dict(self._drawing)
        began = time.perf_counter()
        made, drawing = self._compose_the_snapshot()
        if previous is not None:
            made.inherit_the_unchanged(
                previous, self._what_changed_dirtied(previous, made,
                                                     before, drawing))
        self.accounting["derives"] += 1
        self.accounting["last_derive_ms"] = (time.perf_counter() - began) * 1000
        self.accounting["last_positions"] = len(drawing)
        with self._guard:
            # Two threads may have derived the same snapshot; either is
            # correct, and the one that loses simply gets garbage-collected.
            if mark != self._mark or self._held is None:
                self._mark, self._held, self._drawing = mark, made, drawing
            return self._held

    def _compose_the_snapshot(self) -> tuple[Composer, dict[str, int]]:
        """Derive tiles, frame and composer from the manifest's current truth."""
        published = self._run._published_units()
        order = self._run._positions_in_commit_order()
        layout, profile = self._run._geometry()

        current: dict[str, int] = {}
        for position_id, _moment, generation in published:
            if generation > current.get(position_id, -1):
                current[position_id] = generation
        drawing = {
            position_id: current[position_id] for position_id in order
            if (position_id, 0, current[position_id]) in published
        }
        stores = [self._the_store_of(one, generation)
                  for one, generation in drawing.items()]
        self.accounting["last_tiles_read"] = len(stores)
        # Several at once for the same reason read_the_transfer does: opening
        # a tile is a handful of small file reads, so this waits on the disk.
        if stores:
            with ThreadPoolExecutor(
                max_workers=min(32, (len(stores) + 3) // 4)
            ) as pool:
                tiles = list(pool.map(_a_committed_tile, stores))
        else:
            tiles = []
        return (Composer(TheWorldFrame(tiles, layout, profile),
                         piece=self._piece), drawing)

    def _what_changed_dirtied(self, previous: Composer, fresh: Composer,
                              before: dict[str, int], now: dict[str, int],
                              ) -> dict[int, set[tuple[int, int]]]:
        """Which pieces the manifest's movement reached, per level.

        A position is a change if it appeared, vanished, or moved to another
        generation. Its footprint is collected from **both** snapshots'
        geometry — the ground a removal used to cover has to rebuild just as
        surely as the ground an arrival now covers — and everything outside
        those pieces is, by the manifest's own account, untouched.
        """
        changed = {one for one in before.keys() | now.keys()
                   if before.get(one) != now.get(one)}
        dirty: dict[int, set[tuple[int, int]]] = {}
        for composer in (previous, fresh):
            named = {
                tile.name: tile for tile in composer.mosaic.tiles
                if tile.name.split(".")[0] in changed
            }
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
        with self._guard:
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

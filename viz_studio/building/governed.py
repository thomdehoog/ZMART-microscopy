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
        mark = self._run.manifest.fingerprint()
        with self._guard:
            if mark == self._mark and self._held is not None:
                return self._held
            previous, before = self._held, dict(self._drawing)
            kept = dict(self._tiles)
        began = time.perf_counter()
        made, drawing, tiles = self._compose_the_snapshot(before, kept)
        if previous is not None:
            # The paths the change retired: a replaced or vanished position's
            # old copies. Their cached blocks go no further -- and naming
            # them is O(change), where checking every current tile's path
            # was a fifth of the whole derive at six thousand positions.
            stale = frozenset(
                copy.held_in
                for position_id, tile in kept.items()
                if drawing.get(position_id) != before.get(position_id)
                for copy in tile.copies
            )
            made.inherit_the_unchanged(
                previous, self._what_changed_dirtied(previous, made,
                                                     before, drawing),
                stale=stale)
        self.accounting["derives"] += 1
        self.accounting["last_derive_ms"] = (time.perf_counter() - began) * 1000
        self.accounting["last_positions"] = len(drawing)
        with self._guard:
            # Two threads may have derived the same snapshot; either is
            # correct, and the one that loses simply gets garbage-collected.
            if mark != self._mark or self._held is None:
                stood_down = self._held
                self._mark, self._held = mark, made
                self._drawing, self._tiles = drawing, tiles
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
        # then topped up by the change, never repeated.
        self._held.keep_the_coarse_levels_warm()
        return self._held

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

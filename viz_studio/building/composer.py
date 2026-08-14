"""Building a piece of the picture out of whichever tiles reach into it.

Nothing here is stored. A request for a piece arrives, the tiles that cover that
ground are read, laid into one array, encoded, and handed back. The picture exists
only for as long as it takes to answer.

The two things that make it affordable
--------------------------------------

Measured on the Thy1 transfer, a plain builder took 253 milliseconds to produce one
full-resolution piece, and every millisecond of it was reading. Two changes take
that apart, and both are about not throwing work away:

**Read a slab, not a plane.** A Thy1 tile keeps 32 depth planes in one file, so a
builder answering for a single plane decompresses all 32 and keeps one. Measured:
one plane 119 ms, all 32 planes 128 ms — the same read either way. So a request for
one plane builds the whole slab its file covers and keeps the rest, and the next 31
requests are already answered. That is a thirtyfold saving and it costs nothing but
memory.

**Read the copy you are drawing, not full resolution.** For a piece of the
eighth-size picture, the tiles' own eighth-size copies hold exactly the ground
wanted; full resolution holds 64 times as much of it, to be averaged straight back
down. Measured: 1494 ms against 57 ms.

That second one is why this reads each tile's copy at the level being asked for
rather than shrinking from level 0. The consequence is that a tile is placed to the
nearest voxel *of that copy*, which :mod:`mosaic` argues at length is not an
approximation — a copy shrunk eight times cannot express a position more finely
than one of its own voxels.

Why it keeps costing the same however large the transfer is
-----------------------------------------------------------

A piece of the picture is covered by a handful of tiles — nine, on a run
overlapping by a tenth — and that is true whether the transfer holds six tiles or
ten thousand. So building a piece ought to cost what its own ground costs and
nothing more, and that is the whole reason this scales where handing the viewer
one source per tile does not.

Ought to, and at first did not. Finding which tiles reached a piece looked at
every tile, and the geometry behind it was recomputed each time: 9 ms a piece at
64 tiles and 89 ms at 4096, with the same nine tiles being read either way. So the
tiles are indexed by which pieces they fall in, once per resolution, and it is now
flat — 9.3 ms at 64 tiles, 9.9 ms at 4096.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import OrderedDict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import zarr
from mosaic import Mosaic

# How large a piece of the built picture is, across height and width. A builder is
# free to choose this, since nothing constrains it to match how the tiles happen to
# be stored -- which is the one real freedom building has over pointing.
#
# 512 rather than 256 because a built piece costs work to produce and fewer, larger
# pieces is therefore the cheaper trade. `measure_the_chunk_size.py` measured the
# other end of it: a written picture cost 46 requests in pieces of 256 and 1925 in
# pieces of 32, and first pixel went 0.8 s to 1.6 s. Nothing above 256 was measured,
# so 512 is reasoning rather than measurement and is worth revisiting.
PIECE = 512

# How much memory the kept slabs may take between them.
#
# Counted in bytes rather than in slabs, and that is the whole point. A slab is
# PIECE x PIECE x however deep the tiles' own files are, and that last number
# belongs to the transfer rather than to us: Thy1 keeps 32 planes in a file at
# full resolution and 64 at every coarser one, so a slab is 16 MB in one place
# and 33 MB in another. A transfer chunking 256 planes would make it 134 MB. So
# "keep sixteen slabs" was a memory limit that the data got to choose, somewhere
# between a quarter of a gigabyte and two -- which is the kind of limit that
# holds on every transfer tried and fails on the one that matters.
SLABS_WEIGH_AT_MOST = 256 * 1024 * 1024

# How much memory the decoded tile blocks may take between them.
#
# **This is the one that decides whether panning feels instant.** A piece of the
# picture is smaller than a block of a tile -- 512 voxels against Thy1's 1264 by
# 1480 -- so neighbouring pieces need the *same* block, and without this each of
# them decompresses it again. Measured on the live viewer: a screenful of sixteen
# fresh pieces at full resolution took 1841 ms, where the same sixteen already
# built took 64. Most of that was one handful of blocks decompressed sixteen times
# over.
#
# It is the same mistake as building a plane at a time instead of a slab, made in
# the other two directions: work is thrown away because the unit asked for is
# smaller than the unit stored.
#
# A gigabyte because a Thy1 block is 120 MB decompressed and a screenful spans six
# to nine of them. On a machine with 31 GB that is a fair share; it is a number to
# lower on a smaller machine rather than a constant of nature.
BLOCKS_WEIGH_AT_MOST = 1024 * 1024 * 1024

# What a piece is encoded with. Declared here and checked against what zarr
# actually writes, because a description promising one encoding over bytes in
# another is not an error anywhere -- it is a window full of noise, with nothing
# on screen or in any log to say why.
CODECS = [
    {"name": "bytes", "configuration": {"endian": "little"}},
    {"name": "zstd", "configuration": {"level": 0, "checksum": False}},
]

# Which levels are warmed ahead of anyone asking, and never let go: every level
# holding at most this share of the full-resolution voxels, and always the
# coarsest. The share rule is the plan's -- with halving in y and x each level
# is a quarter of the one above, so the geometric sum bounds what pinning can
# ever hold near half a percent of the picture. The coarsest is pinned
# unconditionally because it is the whole-survey look: the one view every
# session wants, and on a survey the most expensive ground in the pyramid,
# since its every piece meets every tile beneath it.
PINNED_SHARE = 0.01


class MissingCommittedGround(RuntimeError):
    """A chunk the manifest promised is not on disk, and nothing may stand in.

    Zarr answers the fill value for an absent chunk without a word, which is
    the right behaviour for a transfer -- ground nobody imaged *is* fill. For
    a governed run's committed position it is the wrong behaviour twice over:
    the zeros are indistinguishable on screen from dark specimen, and they are
    laid over whatever published neighbour sits beneath. The gateway's rule,
    quoted in the review that ordered this: "a gap in it is damage to fail
    closed on." Whoever serves the piece turns this into an absent answer with
    a logged reason -- a 404, never invented pixels.
    """


# The composer a worker process builds for itself, held at module level because
# a process pool initializer has nowhere else to put it. Each worker gets its
# own, made once from the written-down mosaic, with small caches and no pinning
# -- pinning is the parent's job, and twelve workers each pinning the coarse
# levels would hold the same ground twelve times over.
_WORKING_ON: Composer | None = None


def _start_working(written: dict, piece: int, budget: int) -> None:
    """Give this worker process its own composer, built from the ledger."""
    global _WORKING_ON
    from mosaic import read_the_mosaic_as_written
    _WORKING_ON = Composer(read_the_mosaic_as_written(written), piece=piece,
                           weighing_at_most=budget,
                           blocks_weighing_at_most=budget, pinning=False)


def _build_in_worker(level: int, plane: int, row: int, column: int):
    return _WORKING_ON._slab_for(level, plane, row, column)


class Composer:
    """Answers for a picture that is never stored, out of the tiles that are.

    ``workers`` is how many processes build the picture. One -- the default,
    and the operator's own choice after watching a baked survey open instantly
    on a single pinned core -- builds in place, and is the path every figure
    in this folder describes. More than one spreads slabs across a pool, so
    one against four against twelve can be measured side by side. Processes
    rather than threads, because the coarse ground is interpreter-bound where
    it is not scanner-bound: twelve threads built the 12,800-position survey's
    coarsest level no faster than one (12.7 s either way).
    """

    def __init__(self, mosaic: Mosaic, piece: int = PIECE,
                 weighing_at_most: int = SLABS_WEIGH_AT_MOST,
                 blocks_weighing_at_most: int = BLOCKS_WEIGH_AT_MOST,
                 workers: int = 1, pinning: bool = True) -> None:
        self.mosaic = mosaic
        self.piece = piece
        self._weighing_at_most = weighing_at_most
        self._workers = max(1, int(workers or 1))
        self._pinning = pinning
        self._pool: ProcessPoolExecutor | None = None
        self._pool_guard = threading.Lock()

        # Decoded blocks of the tiles, most recently used last. Kept because a
        # piece of the picture is smaller than a block of a tile, so neighbouring
        # pieces want the same block and would otherwise each decompress it.
        self._blocks: OrderedDict[tuple, np.ndarray] = OrderedDict()
        self._blocks_weigh = 0
        self._blocks_weighing_at_most = blocks_weighing_at_most
        self._block_guard = threading.Lock()

        # Built slabs, most recently used last. Guarded because the server answers
        # several requests at once and two of them wanting the same slab must not
        # both build it.
        self._slabs: OrderedDict[tuple[int, int, int, int], np.ndarray] = OrderedDict()
        self._weighs = 0
        self._guard = threading.Lock()

        # The slabs of the pinned levels, held apart from the byte bound above so
        # nothing can ever evict them. Bounded by geometry instead: the pinned
        # levels together are a fraction of a percent of the picture, and that is
        # the whole of what this may hold.
        self._pinned: dict[tuple[int, int, int, int], np.ndarray] = {}

        # How many requests are being answered right now, so the warmer can step
        # aside: it builds only while nobody is waiting on an answer.
        self._answering = 0
        self._warmer: threading.Thread | None = None
        self._stop_warming = threading.Event()
        # Which tiles fall in each piece, per resolution, built on first use.
        self._indexed: dict[int, dict[tuple[int, int], list]] = {}
        self._indexing = threading.Lock()
        # Which levels are pinned, worked out once: the answer sweeps the
        # picture's shape at every level, and asking again per slab was
        # measurable per-commit waste at survey scale.
        self._pinned_levels: frozenset[int] | None = None
        # Where the warm may READ its slabs instead of composing them: a
        # baked picture's folder and which levels it keeps as files. Set by
        # whoever serves a baked picture (see GovernedRun); None means every
        # slab is composed from the tiles, as always. The second flag says
        # the warm's follow-up block prefill has finished too — the part of
        # warmth the PATCHER leans on, which "warm" must include or a churn
        # started at the flag races it.
        self._warm_store: tuple[Path, frozenset[int]] | None = None
        self._blocks_prefilled = False

        # One encoder per thread, made when that thread first needs one.
        #
        # **There was one, shared, and it handed pieces to the wrong requests.**
        # Encoding writes the piece into a little array and reads the encoded
        # chunk straight back out of it, and the server answers several requests
        # at once -- so two threads wrote into the same array and both read the
        # same key, and one of them got the other's specimen. Measured before it
        # was fixed: asking for 25 pieces at once, 13 to 22 of them came back as
        # somebody else's, differently every round.
        #
        # It survived every check in this folder because all of them build one
        # piece at a time. A picture that is right when asked politely and wrong
        # when asked in parallel is exactly what nothing here was looking for.
        self._encoders = threading.local()

        # Made once here as well, to check the encoding at the door rather than on
        # the first request. See below: a description promising one encoding over
        # bytes in another is a black window with nothing to explain it.
        _ = zarr.create_array(
            store=zarr.storage.MemoryStore(),
            shape=(1, piece, piece),
            chunks=(1, piece, piece),
            dtype=mosaic.dtype,
            zarr_format=3,
            dimension_names=list(mosaic.axes),
            overwrite=True,
        )
        written = [dict(one) for one in _.metadata.to_dict()["codecs"]]
        if written != CODECS:
            raise RuntimeError(
                f"a piece would be encoded as {written} but the picture is declared "
                f"as {CODECS}. The browser would be handed bytes it cannot read, and "
                "nothing would report it — the window would simply be black."
            )

    def inherit_the_unchanged(self, donor: Composer,
                              dirty: dict[int, set[tuple[int, int]]],
                              stale: frozenset = frozenset()) -> None:
        """Carry a predecessor's warmth forward, minus what a commit touched.

        A governed run swaps in a whole fresh composer whenever its manifest
        moves — that is what makes staleness unreachable — but a commit
        touches a handful of pieces and a survey holds thousands, so paying
        the whole picture's warmth for every landing is the measured
        two-changes-a-second ceiling. This is the other half of the snapshot
        rule: everything the commit did not touch moves house.

        ``dirty`` names the pieces the change reached, per level, as
        ``(row, column)`` — worked out by the caller from the changed
        positions' own footprints, over both the old state and the new, so a
        removal dirties the ground it used to cover. Slabs of dirty pieces
        stay behind. ``stale`` names the store folders a change retired — a
        replaced generation's old path, a rolled-back position's — and their
        decoded blocks stay behind with them. Named by the caller as the
        CHANGE's paths rather than checked against every current tile's,
        deliberately: an earlier version built the everything-current set
        here, and hashing twenty-four thousand paths per commit was a fifth
        of the whole derive — O(survey) housekeeping for an O(change)
        question. Correctness never depended on it: a retired path's blocks
        are unreachable anyway, since every reader keys by the paths it now
        holds; this is memory hygiene, priced accordingly. Everything
        inherited is bytes-identical to what the donor held — the donor
        built it, and ground neither side touched decodes the same either
        way.

        The donor may still be answering a straggler request; its locks are
        held only long enough to read each cache out.
        """
        with donor._block_guard:
            held_blocks = list(donor._blocks.items())
        with self._block_guard:
            for key, block in held_blocks:
                if key[0] in stale or key in self._blocks:
                    continue
                self._blocks[key] = block
                self._blocks_weigh += block.nbytes
            while (len(self._blocks) > 1
                   and self._blocks_weigh > self._blocks_weighing_at_most):
                _, dropped = self._blocks.popitem(last=False)
                self._blocks_weigh -= dropped.nbytes

        with donor._guard:
            held_slabs = list(donor._slabs.items())
            held_pinned = list(donor._pinned.items())
        with self._guard:
            for key, slab in held_slabs:
                level, _, row, column = key
                if (row, column) in dirty.get(level, ()) or key in self._slabs:
                    continue
                self._slabs[key] = slab
                self._weighs += slab.nbytes
            while self._slabs and self._weighs > self._weighing_at_most:
                _, dropped = self._slabs.popitem(last=False)
                self._weighs -= dropped.nbytes
            for key, slab in held_pinned:
                level, _, row, column = key
                if (row, column) in dirty.get(level, ()):
                    continue
                self._pinned.setdefault(key, slab)

    def inherit_the_index(self, donor: Composer,
                          dirty: dict[int, set[tuple[int, int]]],
                          changed: frozenset[str],
                          now_drawn: list[tuple[str, object]]) -> None:
        """Carry the piece index forward, rebuilding only the dirtied pieces.

        The index of which tiles fall in each piece was rebuilt from scratch
        by every fresh snapshot — a sweep over every position at every level,
        90 ms of every commit at 6,400 positions, restating an answer a
        commit changes only inside its own footprint. So the index moves
        house like the slabs do: pieces the change never reached keep the
        donor's entry (the same tile objects — ground neither side touched
        indexes the same either way), and each dirtied piece's entry is
        rebuilt from what changed.

        The rebuild keeps the draw order the index promises: a replaced
        position keeps its slot (its commit-order place does not move), a
        vanished position's entry is dropped, and a new arrival is appended
        at the tail — behind everything published, where the newest commit
        draws. ``changed`` names every position whose drawn generation moved;
        ``now_drawn`` carries the changed positions still drawn, with their
        fresh tiles, in the new snapshot's own draw order.

        Levels the donor never indexed stay lazy here too, and are built the
        ordinary way on first ask.
        """
        with donor._indexing:
            copied = {level: dict(index)
                      for level, index in donor._indexed.items()}
        for level, index in copied.items():
            fresh = []
            for name, tile in now_drawn:
                at = self.mosaic.lands_at(tile, level)
                held = tile.copies[level].shape
                covered = {
                    (row, column)
                    for row in range(at[1] // self.piece,
                                     (at[1] + held[1] - 1) // self.piece + 1)
                    for column in range(at[2] // self.piece,
                                        (at[2] + held[2] - 1) // self.piece + 1)
                }
                fresh.append((name, tile, at, covered))
            for target in dirty.get(level, ()):
                rebuilt = []
                swapped: set[str] = set()
                for tile, at in index.get(target, ()):
                    name = tile.name.split(".")[0]
                    if name not in changed:
                        rebuilt.append((tile, at))
                        continue
                    for fresh_name, fresh_tile, fresh_at, covered in fresh:
                        if fresh_name == name and target in covered:
                            rebuilt.append((fresh_tile, fresh_at))
                            swapped.add(name)
                            break
                for fresh_name, fresh_tile, fresh_at, covered in fresh:
                    if fresh_name not in swapped and target in covered:
                        rebuilt.append((fresh_tile, fresh_at))
                if rebuilt:
                    index[target] = rebuilt
                else:
                    index.pop(target, None)
        with self._indexing:
            for level, index in copied.items():
                self._indexed.setdefault(level, index)

    # -- what the picture is -------------------------------------------------

    def grid(self, level: int) -> tuple[int, int, int]:
        """How many pieces deep, tall and wide the picture is at this resolution."""
        depth, height, width = self.mosaic.shape(level)
        return depth, -(-height // self.piece), -(-width // self.piece)

    def slab_depth(self, level: int) -> int:
        """How many planes one of the tiles' files holds at this resolution.

        This is what a slab is worth building: read one plane and the file's other
        planes have been decompressed already, so building them costs nothing extra.

        A mosaic that knows its own depths — a governed run does, from its
        profile — is believed first, because it has an answer even while it
        holds no tiles at all: a run that has committed nothing yet is still a
        picture, and its grid must not depend on anything having arrived.
        """
        declared = getattr(self.mosaic, "slab_depths", None)
        if declared is not None:
            return int(declared[level])
        return int(self.mosaic.tiles[0].copies[level].chunks[0])

    # -- building ------------------------------------------------------------

    def _tiles_in_each_piece(self, level: int) -> dict[tuple[int, int], list]:
        """Which tiles fall in each piece of the picture, worked out once.

        Building a piece has to know which tiles reach it, and asking every tile
        is what stops this scaling: measured at four thousand tiles, the sweeps
        cost 89 milliseconds a piece where the reading itself took 9.

        The answer does not need a sweep. A tile covers a small rectangle of
        pieces, so every tile is written into the few pieces it touches, once,
        when a resolution is first asked for. Looking up is then a dictionary
        lookup and the cost of building a piece is the cost of its own ground —
        which is the whole claim this arrangement rests on.

        Building the index is proportional to the transfer, not to its square: a
        tile lands in about four pieces whatever else is in the run.
        """
        found = self._indexed.get(level)
        if found is not None:
            return found
        # Built while holding a lock, so that the many requests the engine makes
        # the instant a resolution is first drawn produce one index between them
        # rather than one each. Building it is proportional to the transfer -- 18
        # ms at ten thousand tiles -- and thirty-six threads each doing that and
        # discarding all but one is the same waste that cost 14 seconds when
        # ``served.py`` made composers the same way.
        #
        # A lock of its own rather than the one guarding the slabs, so that
        # requests already being answered are not held up behind it.
        with self._indexing:
            found = self._indexed.get(level)
            if found is not None:
                return found
            index: dict[tuple[int, int], list] = {}
            for tile, at in self.mosaic.placements(level):
                held = tile.copies[level].shape
                for row in range(at[1] // self.piece,
                                 (at[1] + held[1] - 1) // self.piece + 1):
                    for column in range(at[2] // self.piece,
                                        (at[2] + held[2] - 1) // self.piece + 1):
                        index.setdefault((row, column), []).append((tile, at))
            self._indexed[level] = index
            return index

    def _a_block_of(self, copy, at: tuple[int, int, int]) -> np.ndarray:
        """One whole stored block of a tile, decoded, kept for whoever needs it next.

        ``at`` names the block in the tile's own grid of them, as ``(z, y, x)``.

        Asked for **whole** rather than as the part wanted, and that is the point.
        Zarr decompresses the whole block either way -- that is what a block is --
        so asking for a corner of it costs exactly as much as asking for all of it
        and throws the rest away. Keeping it means the next piece of the picture
        along, which wants the same block, gets it for nothing.

        The key carries ``outer`` beside the path: two copies of one store that
        read different moments or channels hold different pixels under the same
        (z, y, x), and a key without it would hand one moment's specimen to
        another's request the day the picture grows those axes.
        """
        key = (copy.held_in, copy.outer, at)
        with self._block_guard:
            found = self._blocks.get(key)
            if found is not None:
                self._blocks.move_to_end(key)
                return found

        size = copy.chunks
        # A copy that promises its blocks exist -- a committed position of a
        # governed run -- is checked before being read, because zarr would
        # answer an absent chunk with silent fill and this ground was promised
        # by a commit. A transfer's copies promise nothing and skip this.
        if copy.presence is not None and not copy.presence(at):
            raise MissingCommittedGround(
                f"{copy.held_in} was published, but its block {at} is not on "
                "disk. Refusing to invent fill for committed ground."
            )
        # ``outer`` holds any axes the store keeps in front of (z, y, x) --
        # empty for a transfer's tile, one moment of one channel for a governed
        # run's position. Indexing with plain integers collapses those axes, so
        # what comes back is three-dimensional either way.
        held = np.asarray(copy.array[copy.outer + (
            slice(at[0] * size[0], (at[0] + 1) * size[0]),
            slice(at[1] * size[1], (at[1] + 1) * size[1]),
            slice(at[2] * size[2], (at[2] + 1) * size[2]),
        )])

        with self._block_guard:
            if key not in self._blocks:
                self._blocks_weigh += held.nbytes
            self._blocks[key] = held
            self._blocks.move_to_end(key)
            # Always keep the newest, however large: a single Thy1 block is 120 MB
            # and dropping the one just decoded would mean decoding it again for
            # the very next piece.
            while (len(self._blocks) > 1
                   and self._blocks_weigh > self._blocks_weighing_at_most):
                _, dropped = self._blocks.popitem(last=False)
                self._blocks_weigh -= dropped.nbytes
        return held

    def _read_from(self, copy, low: tuple[int, int, int],
                   high: tuple[int, int, int]) -> np.ndarray:
        """A rectangle of one tile, assembled out of whichever blocks hold it.

        The same numbers zarr would have returned for the same slice. The only
        difference is which blocks were decoded to get there, and whether they are
        still to hand afterwards.
        """
        size = copy.chunks
        out = np.empty(tuple(high[axis] - low[axis] for axis in range(3)),
                       copy.dtype)
        for bz in range(low[0] // size[0], (high[0] - 1) // size[0] + 1):
            for by in range(low[1] // size[1], (high[1] - 1) // size[1] + 1):
                for bx in range(low[2] // size[2], (high[2] - 1) // size[2] + 1):
                    block = self._a_block_of(copy, (bz, by, bx))
                    began = (bz * size[0], by * size[1], bx * size[2])
                    from_ = tuple(max(low[axis], began[axis]) for axis in range(3))
                    to = tuple(min(high[axis], began[axis] + block.shape[axis])
                               for axis in range(3))
                    if any(from_[axis] >= to[axis] for axis in range(3)):
                        continue
                    out[from_[0] - low[0]:to[0] - low[0],
                        from_[1] - low[1]:to[1] - low[1],
                        from_[2] - low[2]:to[2] - low[2]] = block[
                            from_[0] - began[0]:to[0] - began[0],
                            from_[1] - began[1]:to[1] - began[1],
                            from_[2] - began[2]:to[2] - began[2]]
        return out

    def _build_slab(self, level: int, plane: int, row: int, column: int) -> np.ndarray:
        """Lay the tiles into one column of ground, for every plane of one file.

        Where two tiles cover the same ground the later one wins, which is the rule
        the rest of the project follows and the one an operator already sees.
        """
        depth = self.slab_depth(level)
        low_z = (plane // depth) * depth
        deep, height, width = self.mosaic.shape(level)
        high_z = min(low_z + depth, deep)

        top, left = row * self.piece, column * self.piece
        bottom = min(top + self.piece, height)
        right = min(left + self.piece, width)

        slab = np.zeros((high_z - low_z, self.piece, self.piece),
                        self.mosaic.dtype)
        for tile, at in self._tiles_in_each_piece(level).get((row, column), ()):
            # The copy's own declared spatial extent -- NOT the opened array's.
            # The array of a governed position is five axes and its leading
            # shape entries are the moment and channel singletons, which read
            # here as a one-voxel tile; and opening a store to learn a shape
            # the copy already wrote down is the exact waste the Copy class
            # exists to avoid.
            held = tile.copies[level].shape
            # The index answers by piece across the specimen, which is where tiles
            # differ. Depth it says nothing about, and a tile shallower than the
            # picture -- Thy1's are 256 planes against one of 291 -- reaches this
            # piece without reaching this slab. So depth is checked here.
            if not (max(low_z, at[0]) < min(high_z, at[0] + held[0])):
                continue
            from_z, to_z = max(low_z, at[0]), min(high_z, at[0] + held[0])
            from_y, to_y = max(top, at[1]), min(bottom, at[1] + held[1])
            from_x, to_x = max(left, at[2]), min(right, at[2] + held[2])
            slab[from_z - low_z:to_z - low_z,
                 from_y - top:to_y - top,
                 from_x - left:to_x - left] = self._read_from(
                     tile.copies[level],
                     (from_z - at[0], from_y - at[1], from_x - at[2]),
                     (to_z - at[0], to_y - at[1], to_x - at[2]))
        return slab

    def _slab_for(self, level: int, plane: int, row: int, column: int) -> np.ndarray:
        """The slab holding this plane, built if it is not already to hand.

        A slab of a pinned level is kept in the pinned store, outside the byte
        bound, so the warmed coarse ground can never be evicted by a flood of
        fine work -- see ``PINNED_SHARE`` for why that is safe to hold.
        """
        depth = self.slab_depth(level)
        key = (level, (plane // depth) * depth, row, column)
        pinned = self._pinning and level in self.pinned_levels
        with self._guard:
            found = self._pinned.get(key)
            if found is not None:
                return found
            found = self._slabs.get(key)
            if found is not None:
                self._slabs.move_to_end(key)
                return found
        built = self._built_wherever(level, plane, row, column)
        with self._guard:
            if pinned:
                self._pinned.setdefault(key, built)
                return self._pinned[key]
            if key not in self._slabs:
                self._weighs += built.nbytes
            self._slabs[key] = built
            self._slabs.move_to_end(key)
            # Let go of the least recently wanted until what is held fits. Always
            # keep one, however large it is: dropping the slab that was just built
            # would mean building it again for the very next plane, which is the
            # thing this cache exists to prevent.
            while len(self._slabs) > 1 and self._weighs > self._weighing_at_most:
                _, dropped = self._slabs.popitem(last=False)
                self._weighs -= dropped.nbytes
        return built

    @property
    def pinned_levels(self) -> frozenset[int]:
        """The levels warmed ahead of asking and never let go.

        Every level holding at most ``PINNED_SHARE`` of the full-resolution
        voxels, and the coarsest whatever its share -- the whole-survey look is
        the one view every session wants and, on a survey, the dearest to build.
        """
        if self._pinned_levels is not None:
            return self._pinned_levels
        full = 1
        for side in self.mosaic.shape(0):
            full *= side
        pinned = {self.mosaic.levels - 1}
        for level in range(self.mosaic.levels):
            voxels = 1
            for side in self.mosaic.shape(level):
                voxels *= side
            if voxels <= PINNED_SHARE * full:
                pinned.add(level)
        self._pinned_levels = frozenset(pinned)
        return self._pinned_levels

    @property
    def coarse_levels_are_warm(self) -> bool:
        """Whether every slab of every pinned level has been built and kept.

        On a picture whose warm reads the baked files, warmth also includes
        the follow-up block prefill: the pins alone make the picture
        SERVABLE, but a patch composes from the tiles' blocks, and warmth
        that stops short of them was measured handing the first commits
        multi-second patches the composing warm used to absorb quietly.
        """
        if self._warm_store is not None and not self._blocks_prefilled:
            return False
        wanted = 0
        for level in self.pinned_levels:
            deep, down, across = self.grid(level)
            slabs_deep = -(-self.mosaic.shape(level)[0] // self.slab_depth(level))
            wanted += slabs_deep * down * across
        with self._guard:
            return len(self._pinned) >= wanted

    def warm_the_coarse_levels(self, stop: threading.Event | None = None) -> None:
        """Build every slab of every pinned level, coarsest first.

        This is the cold start, paid deliberately and in the background instead
        of accidentally and in front of the operator: the first look at a fresh
        survey used to spend its opening seconds building exactly this ground,
        piece by piece as the browser asked (12.7 seconds at 12,800 positions,
        measured on the lab machine). Coarsest first, because the whole-survey
        look is the view a fresh picture opens on.

        Idempotent -- ground already warm is skipped, so running it again after
        a commit warms only what the commit made new -- and it steps aside
        whenever a real request is being answered, so warming never makes the
        operator wait. Both properties are what the live role needs of it: a
        snapshot swap stops the old composer's warmer and starts the new one's,
        and the fresh pass re-uses everything still valid.

        A BAKED picture's pinned levels already exist as files (see
        :meth:`warm_from_the_baked`), and reading a ready-made piece back is
        tens of times cheaper than composing it from every tile that touches
        it -- at survey scale the difference between minutes of cold coarse
        ground and seconds. Levels the bake does not keep are composed the
        ordinary way.
        """
        for level in sorted(self.pinned_levels, reverse=True):
            baked = self._the_baked_level(level)
            depth = self.slab_depth(level)
            deep, down, across = self.grid(level)
            planes = self.mosaic.shape(level)[0]
            for low_z in range(0, planes, depth):
                for row in range(down):
                    for column in range(across):
                        if stop is not None and stop.is_set():
                            return
                        while self._answering:
                            time.sleep(0.005)
                        if baked is None:
                            self._slab_for(level, low_z, row, column)
                        else:
                            self._a_slab_read_back(baked, level, low_z,
                                                   row, column)
        # The composing warm filled the tile-block cache on its way, and the
        # patcher leans on exactly those blocks: the first commit after a
        # file-fed warm was measured paying every coarse block's decode at
        # once, on camera. So after the pins are ready -- the picture is
        # already servable by here -- the warmer keeps going quietly and
        # decodes the tiles' coarse blocks too, coarsest first, the same
        # step-aside, stop-any-time background work the slab warm has
        # always been. A block that will not decode is skipped: prefilling
        # is cache hygiene, and the serving path keeps its own gate.
        if self._warm_store is not None:
            if not self._every_coarse_block_decoded(stop):
                return
        self._blocks_prefilled = True

    def _every_coarse_block_decoded(self, stop) -> bool:
        """Fill the block cache for the pinned levels, several blocks at a time.

        The decodes bypass zarr on purpose: every zarr read funnels through
        one per-process event loop, where threads were measured queuing
        instead of overlapping — but a chunk's bytes can be found through
        the run's own shard-aware resolver and undone directly, the same
        two steps the coordinator's fast comparison uses (a settled byte
        order, then zstd), and zstd releases the interpreter's lock, so a
        few threads genuinely decode at once. A block stored some way this
        shortcut does not recognise is read through zarr instead; a block
        that will not decode at all is skipped, because prefilling is cache
        hygiene and the serving path keeps its own gate.

        Returns False when stopped early — an interrupted prefill is not
        warmth.
        """
        try:
            from zmart_live.shardlink import how_the_array_is_stored
        except ImportError:
            how_the_array_is_stored = None
        from numcodecs.zstd import Zstd

        unpacking = Zstd()

        def one_block(copy, storage, at: tuple[int, int, int]) -> None:
            key = (copy.held_in, copy.outer, at)
            with self._block_guard:
                if key in self._blocks:
                    return
            if storage is None:
                self._a_block_of(copy, at)
                return
            held = storage.where_one_chunk_lives(copy.outer + at)
            if held is None:
                return
            with held.path.open("rb") as reading:
                reading.seek(held.offset)
                packed = reading.read(held.length)
            codecs = storage.description.get("codecs") or []
            if (codecs and isinstance(codecs[0], dict)
                    and codecs[0].get("name") == "sharding_indexed"):
                codecs = (codecs[0].get("configuration") or {}).get(
                    "codecs") or []
            named = [step.get("name") if isinstance(step, dict) else None
                     for step in codecs]
            if named[:1] != ["bytes"] or named[1:] not in ([], ["zstd"]):
                self._a_block_of(copy, at)
                return
            if named[1:] == ["zstd"]:
                packed = unpacking.decode(packed)
            order = (codecs[0].get("configuration") or {}).get(
                "endian", "little")
            kind = np.dtype(storage.description["data_type"]).newbyteorder(
                "<" if order == "little" else ">")
            block = np.frombuffer(packed, dtype=kind).reshape(
                storage.bundling.inner_chunk)[copy.outer]
            keep = tuple(
                min(size, whole - place * size) for size, whole, place
                in zip(copy.chunks, copy.shape[-3:], at, strict=True)
            )
            block = block[:keep[0], :keep[1], :keep[2]]
            with self._block_guard:
                if key not in self._blocks:
                    self._blocks[key] = block
                    self._blocks_weigh += block.nbytes
                    while (len(self._blocks) > 1
                           and self._blocks_weigh
                           > self._blocks_weighing_at_most):
                        _, dropped = self._blocks.popitem(last=False)
                        self._blocks_weigh -= dropped.nbytes

        from collections import deque
        from concurrent.futures import ThreadPoolExecutor

        decoding = ThreadPoolExecutor(max_workers=min(4, os.cpu_count() or 1))
        waiting: deque = deque()
        try:
            for level in sorted(self.pinned_levels, reverse=True):
                for tile, _ in self.mosaic.placements(level):
                    if stop is not None and stop.is_set():
                        return False
                    while self._answering:
                        time.sleep(0.005)
                    copy = tile.copies[level]
                    storage = None
                    if how_the_array_is_stored is not None:
                        try:
                            storage = how_the_array_is_stored(copy.held_in)
                        except Exception:
                            storage = None
                    blocks = [
                        -(-whole // size) for whole, size
                        in zip(copy.shape[-3:], copy.chunks, strict=True)
                    ]
                    for z in range(blocks[0]):
                        for y in range(blocks[1]):
                            for x in range(blocks[2]):
                                while len(waiting) >= 16:
                                    try:
                                        waiting.popleft().result()
                                    except Exception:
                                        pass
                                waiting.append(decoding.submit(
                                    one_block, copy, storage, (z, y, x)))
            while waiting:
                try:
                    waiting.popleft().result()
                except Exception:
                    pass
            return True
        finally:
            decoding.shutdown(wait=True, cancel_futures=True)

    def warm_from_the_baked(self, store: Path, levels: frozenset[int]) -> None:
        """Let the warm read these levels' slabs out of this baked folder.

        The files are patched to the current manifest state before any fresh
        snapshot answers anyone, so what the warm reads back is what
        composing would have produced -- pinned by a test, byte for byte. A
        commit landing while the warm is mid-read can leave a slab one state
        newer than this snapshot; those are exactly the pieces the next
        snapshot's inheritance drops as dirty, and the file door was already
        serving those newer bytes, so nothing new becomes visible through
        this path.
        """
        self._warm_store = (Path(store), frozenset(levels))

    def _the_baked_level(self, level: int):
        """The baked array for one level, opened once per warm, or ``None``."""
        if self._warm_store is None or level not in self._warm_store[1]:
            return None
        try:
            return zarr.open_array(str(self._warm_store[0] / str(level)),
                                   mode="r")
        except Exception:
            # A bake that is missing or unreadable is not an error here --
            # the warm simply composes, exactly as an unbaked picture does.
            return None

    def _a_slab_read_back(self, baked, level: int, low_z: int, row: int,
                          column: int) -> None:
        """One slab lifted from the baked files, installed as if built.

        The composed slab is always a full ``piece``-sized square, padded
        with the fill value where the picture's edge falls inside it; the
        baked array answers edge reads trimmed. Padding the read back out
        restores the exact array the builder would have produced, so
        everything downstream sees one kind of slab whichever way it came.
        """
        depth = self.slab_depth(level)
        key = (level, low_z, row, column)
        with self._guard:
            if key in self._pinned or key in self._slabs:
                return
        deep, height, width = self.mosaic.shape(level)
        high_z = min(low_z + depth, deep)
        top, left = row * self.piece, column * self.piece
        lifted = np.asarray(baked[low_z:high_z,
                                  top:min(top + self.piece, height),
                                  left:min(left + self.piece, width)])
        slab = np.zeros((high_z - low_z, self.piece, self.piece),
                        self.mosaic.dtype)
        slab[:, :lifted.shape[1], :lifted.shape[2]] = lifted
        with self._guard:
            if self._pinning and level in self.pinned_levels:
                self._pinned.setdefault(key, slab)
            elif key not in self._slabs:
                self._slabs[key] = slab
                self._weighs += slab.nbytes

    @property
    def working_alone(self) -> bool:
        """Whether every slab is built in this process, the measured default."""
        return self._workers == 1

    def _built_wherever(self, level: int, plane: int, row: int, column: int):
        """Build a slab here, or hand it to a worker process when they exist."""
        if self._workers == 1:
            return self._build_slab(level, plane, row, column)
        with self._pool_guard:
            if self._pool is None:
                # Each worker is handed the written-down mosaic once, so workers
                # read the ledger rather than walking the transfer, exactly as
                # opening does. Their cache budgets are the parent's divided
                # between them, so turning workers on does not multiply memory.
                from mosaic import the_mosaic_written_down
                budget = SLABS_WEIGH_AT_MOST // self._workers
                self._pool = ProcessPoolExecutor(
                    max_workers=self._workers,
                    initializer=_start_working,
                    initargs=(the_mosaic_written_down(self.mosaic), self.piece,
                              max(budget, 64 * 1024 * 1024)),
                )
            pool = self._pool
        return pool.submit(_build_in_worker, level, plane, row, column).result()

    def close(self) -> None:
        """Stop the warmer and let the worker processes go."""
        self.stop_warming()
        with self._pool_guard:
            pool, self._pool = self._pool, None
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)

    def keep_the_coarse_levels_warm(self) -> None:
        """Run the warm pass in the background, once, letting requests through."""
        if self._warmer is not None and self._warmer.is_alive():
            return
        self._stop_warming.clear()
        self._warmer = threading.Thread(
            target=self.warm_the_coarse_levels, args=(self._stop_warming,),
            name="warm-the-coarse-levels", daemon=True,
        )
        self._warmer.start()

    def stop_warming(self) -> None:
        """Tell a running warm pass to stop after the slab it is on."""
        self._stop_warming.set()

    def _my_encoder(self):
        """This thread's own little array to encode a piece through.

        Per thread rather than shared, because encoding writes a piece in and
        reads the encoded chunk straight back out: one array between several
        requests means one request reading another's specimen. Per thread rather
        than behind a lock, because a lock would make every request queue for the
        one part of answering that is otherwise free.
        """
        held = getattr(self._encoders, "array", None)
        if held is None:
            held = zarr.create_array(
                store=zarr.storage.MemoryStore(),
                shape=(1, self.piece, self.piece),
                chunks=(1, self.piece, self.piece),
                dtype=self.mosaic.dtype,
                zarr_format=3,
                dimension_names=list(self.mosaic.axes),
                overwrite=True,
            )
            self._encoders.array = held
        return held

    def bytes_for(self, level: int, plane: int, row: int, column: int) -> bytes | None:
        """One piece of the picture, encoded exactly as its description promises.

        ``None`` for a piece that holds only the fill value, which on a scattered
        run is most of the picture: the grid spans the bounding box of every
        tile, and the ground between them belongs to nobody. Such a piece is
        served as absent — the engine paints it from the declared fill value —
        which is also the one answer the encoder below can give, since zarr
        leaves no chunk behind for it. The emptiness is decided by looking at
        the piece rather than at what the encoder left, because this thread's
        encoder still holds the previous piece it was asked for.
        """
        with self._guard:
            self._answering += 1
        try:
            slab = self._slab_for(level, plane, row, column)
            depth = self.slab_depth(level)
            piece = slab[plane - (plane // depth) * depth]
            if not piece.any():
                return None
            encoder = self._my_encoder()
            encoder[0] = piece
            return bytes(encoder.store._store_dict["c/0/0/0"].to_bytes())
        finally:
            with self._guard:
                self._answering -= 1

    # -- what the picture says about itself ----------------------------------

    def group_json(self) -> bytes:
        """The built picture described as an ordinary OME-Zarr multiscale image.

        The voxel size of each copy is the tiles' own rather than the full-size one
        halved, because a transfer need not halve every axis at every step — the
        Thy1 set leaves depth alone for three levels, its voxels being 1 micrometre
        deep against 0.17 across.

        How the copies were shrunk decides two things here, so the mosaic says
        which it was (see :attr:`Mosaic.averaged`). A decimated copy — every
        second voxel, what a mesoSPIM transfer keeps — has fine voxels' own
        centres and every level shares one translation. An averaged copy's
        centres sit half a fine voxel along each halved axis, so each level's
        translation steps by (voxel_L - voxel_0) / 2 — declared any other way,
        the levels draw a fixed diagonal apart, which the operator saw as a
        deterministic top-left twitch whenever one level stood in for another
        for a frame. The placement arithmetic is untouched either way: content
        and grid shift together, so where a tile lands cancels the offset.
        """
        base = self.mosaic.voxel_um(0)
        datasets = []
        for level in range(self.mosaic.levels):
            voxel = self.mosaic.voxel_um(level)
            at = list(self.mosaic.corner_um)
            if self.mosaic.averaged:
                at = [at[axis] + (voxel[axis] - base[axis]) / 2
                      for axis in range(3)]
            datasets.append({
                "path": str(level),
                "coordinateTransformations": [
                    {"type": "scale", "scale": list(voxel)},
                    {"type": "translation", "translation": at},
                ],
            })
        return json.dumps({
            "attributes": {
                "ome": {
                    "version": "0.5",
                    "multiscales": [{
                        "name": "built",
                        "type": "mean" if self.mosaic.averaged else "nearest",
                        "axes": [
                            {"name": "z", "type": "space", "unit": "micrometer"},
                            {"name": "y", "type": "space", "unit": "micrometer"},
                            {"name": "x", "type": "space", "unit": "micrometer"},
                        ],
                        "datasets": datasets,
                    }],
                }
            },
            "zarr_format": 3,
            "node_type": "group",
        }).encode()

    def array_json(self, level: int) -> bytes:
        """One resolution of the picture, in pieces of :data:`PIECE`."""
        depth, height, width = self.mosaic.shape(level)
        return json.dumps({
            "zarr_format": 3,
            "node_type": "array",
            "shape": [depth, height, width],
            "data_type": self.mosaic.dtype,
            "chunk_grid": {"name": "regular", "configuration": {
                "chunk_shape": [1, self.piece, self.piece]}},
            "chunk_key_encoding": {"name": "default",
                                   "configuration": {"separator": "/"}},
            "fill_value": 0,
            "codecs": CODECS,
            "attributes": {},
            "dimension_names": list(self.mosaic.axes),
        }).encode()

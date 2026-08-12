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
import threading
import time
from collections import OrderedDict

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


class Composer:
    """Answers for a picture that is never stored, out of the tiles that are."""

    def __init__(self, mosaic: Mosaic, piece: int = PIECE,
                 weighing_at_most: int = SLABS_WEIGH_AT_MOST,
                 blocks_weighing_at_most: int = BLOCKS_WEIGH_AT_MOST) -> None:
        self.mosaic = mosaic
        self.piece = piece
        self._weighing_at_most = weighing_at_most

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

    # -- what the picture is -------------------------------------------------

    def grid(self, level: int) -> tuple[int, int, int]:
        """How many pieces deep, tall and wide the picture is at this resolution."""
        depth, height, width = self.mosaic.shape(level)
        return depth, -(-height // self.piece), -(-width // self.piece)

    def slab_depth(self, level: int) -> int:
        """How many planes one of the tiles' files holds at this resolution.

        This is what a slab is worth building: read one plane and the file's other
        planes have been decompressed already, so building them costs nothing extra.
        """
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
        """
        key = (copy.held_in, at)
        with self._block_guard:
            found = self._blocks.get(key)
            if found is not None:
                self._blocks.move_to_end(key)
                return found

        size = copy.chunks
        held = np.asarray(copy.array[
            at[0] * size[0]:(at[0] + 1) * size[0],
            at[1] * size[1]:(at[1] + 1) * size[1],
            at[2] * size[2]:(at[2] + 1) * size[2],
        ])

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
            held = tile.copies[level].array
            # The index answers by piece across the specimen, which is where tiles
            # differ. Depth it says nothing about, and a tile shallower than the
            # picture -- Thy1's are 256 planes against one of 291 -- reaches this
            # piece without reaching this slab. So depth is checked here.
            if not (max(low_z, at[0]) < min(high_z, at[0] + held.shape[0])):
                continue
            from_z, to_z = max(low_z, at[0]), min(high_z, at[0] + held.shape[0])
            from_y, to_y = max(top, at[1]), min(bottom, at[1] + held.shape[1])
            from_x, to_x = max(left, at[2]), min(right, at[2] + held.shape[2])
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
        pinned = level in self.pinned_levels
        with self._guard:
            found = self._pinned.get(key)
            if found is not None:
                return found
            found = self._slabs.get(key)
            if found is not None:
                self._slabs.move_to_end(key)
                return found
        built = self._build_slab(level, plane, row, column)
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
        return frozenset(pinned)

    @property
    def coarse_levels_are_warm(self) -> bool:
        """Whether every slab of every pinned level has been built and kept."""
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
        """
        for level in sorted(self.pinned_levels, reverse=True):
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
                        self._slab_for(level, low_z, row, column)

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

        The picture also says its smaller copies were made by taking every second
        voxel rather than by averaging, because that is what the tiles' own copies
        are: nothing here re-shrinks anything, it places what the tile already has.
        """
        datasets = []
        for level in range(self.mosaic.levels):
            voxel = self.mosaic.voxel_um(level)
            datasets.append({
                "path": str(level),
                "coordinateTransformations": [
                    {"type": "scale", "scale": list(voxel)},
                    {"type": "translation",
                     "translation": list(self.mosaic.corner_um)},
                ],
            })
        return json.dumps({
            "attributes": {
                "ome": {
                    "version": "0.5",
                    "multiscales": [{
                        "name": "built",
                        "type": "nearest",
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

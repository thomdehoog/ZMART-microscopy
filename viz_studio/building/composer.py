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
from collections import OrderedDict
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

# What a piece is encoded with. Declared here and checked against what zarr
# actually writes, because a description promising one encoding over bytes in
# another is not an error anywhere -- it is a window full of noise, with nothing
# on screen or in any log to say why.
CODECS = [
    {"name": "bytes", "configuration": {"endian": "little"}},
    {"name": "zstd", "configuration": {"level": 0, "checksum": False}},
]


class Composer:
    """Answers for a picture that is never stored, out of the tiles that are."""

    def __init__(self, mosaic: Mosaic, piece: int = PIECE,
                 weighing_at_most: int = SLABS_WEIGH_AT_MOST) -> None:
        self.mosaic = mosaic
        self.piece = piece
        self._weighing_at_most = weighing_at_most

        # Built slabs, most recently used last. Guarded because the server answers
        # several requests at once and two of them wanting the same slab must not
        # both build it.
        self._slabs: OrderedDict[tuple[int, int, int, int], np.ndarray] = OrderedDict()
        self._weighs = 0
        self._guard = threading.Lock()
        # Which tiles fall in each piece, per resolution, built on first use.
        self._indexed: dict[int, dict[tuple[int, int], list]] = {}
        self._indexing = threading.Lock()

        self._encoder = zarr.create_array(
            store=zarr.storage.MemoryStore(),
            shape=(1, piece, piece),
            chunks=(1, piece, piece),
            dtype=mosaic.dtype,
            zarr_format=3,
            dimension_names=list(mosaic.axes),
            overwrite=True,
        )
        written = [dict(one) for one in self._encoder.metadata.to_dict()["codecs"]]
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
                 from_x - left:to_x - left] = held[
                     from_z - at[0]:to_z - at[0],
                     from_y - at[1]:to_y - at[1],
                     from_x - at[2]:to_x - at[2],
                 ]
        return slab

    def _slab_for(self, level: int, plane: int, row: int, column: int) -> np.ndarray:
        """The slab holding this plane, built if it is not already to hand."""
        depth = self.slab_depth(level)
        key = (level, (plane // depth) * depth, row, column)
        with self._guard:
            found = self._slabs.get(key)
            if found is not None:
                self._slabs.move_to_end(key)
                return found
        built = self._build_slab(level, plane, row, column)
        with self._guard:
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

    def bytes_for(self, level: int, plane: int, row: int, column: int) -> bytes:
        """One piece of the picture, encoded exactly as its description promises."""
        slab = self._slab_for(level, plane, row, column)
        depth = self.slab_depth(level)
        self._encoder[0] = slab[plane - (plane // depth) * depth]
        return bytes(self._encoder.store._store_dict["c/0/0/0"].to_bytes())

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

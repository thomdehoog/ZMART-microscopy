"""Build a piece of the picture, at any of its four sizes, out of the positions.

The demonstration this is copied from built pieces at one size only. The open
question it left behind was what a *smaller* copy of the picture should even mean
when positions sit at odd offsets, since a view that answers by pointing cannot
point at half a voxel.

A composing server does not point, so the question changes shape. To answer for a
piece of the half-size picture it reads the full-size ground that piece covers —
twice as tall and twice as wide as the piece itself — lays whichever positions
reach into it into one array, averages each two-by-two block down to one voxel,
and encodes the result. The odd offsets never come up, because the positions are
laid out before anything is shrunk.

What that costs is the thing worth measuring. A piece of the quarter-size picture
covers sixteen times the ground of a full-size piece, so it reads sixteen times as
much from the positions to produce the same number of voxels. Whether that shows
up as sixteen times the work is what `check.py` measures rather than assumes.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import zarr

import geometry as g

# The description of one piece: the same shape, kind of number and encoding the
# positions use. Saying it once here is what makes the bytes this file produces
# and the bytes a position holds interchangeable.
CODECS = [
    {"name": "bytes", "configuration": {"endian": "little"}},
    {"name": "zstd", "configuration": {"level": 0, "checksum": False}},
]
AXES = ["t", "c", "z", "y", "x"]


class Composer:
    """Holds the positions open and builds pieces of the picture from them."""

    def __init__(self, positions_folder: Path, places: list[tuple[int, int]]):
        self.places = list(places)
        folders = sorted(Path(positions_folder).glob("*.ome.zarr"))
        if len(folders) != len(self.places):
            raise RuntimeError(
                f"{len(folders)} position images but {len(self.places)} places on "
                "the stage; the two have to agree or tiles would be drawn in "
                "somebody else's place"
            )
        # Opened once and kept open. Opening a store costs a read of its
        # description, and doing that per piece would be measuring the wrong thing
        # entirely. Only the full-size copy of each position is ever read: the
        # smaller copies the writer made are subsampled rather than averaged, and
        # they are on each position's own grid rather than the picture's, so they
        # are no help here. That is the cost this experiment is about.
        self.arrays = [zarr.open_array(str(one / "0"), mode="r") for one in folders]
        self.source_chunk = self.arrays[0].chunks[-2:]

        # One array per size to encode into, reused. A server holds buffers rather
        # than building one for every piece it answers.
        self._out = {}
        self._store = {}
        for level in range(g.LEVELS):
            array = zarr.create_array(
                store=zarr.storage.MemoryStore(),
                shape=(1, 1, 1, g.CHUNK, g.CHUNK),
                chunks=(1, 1, 1, g.CHUNK, g.CHUNK),
                dtype="uint16",
                zarr_format=3,
                dimension_names=AXES,
                overwrite=True,
            )
            # The encoding is checked rather than assumed. If zarr's defaults ever
            # differed from what the picture's description promises, every piece
            # served would be unreadable rubbish and the window would simply be
            # black — a fault with nothing on screen to explain it.
            written = [dict(one) for one in array.metadata.to_dict()["codecs"]]
            if written != CODECS:
                raise RuntimeError(
                    f"a piece would be encoded as {written} but the picture says "
                    f"{CODECS}; the browser would be sent bytes it cannot read"
                )
            self._out[level] = array
            self._store[level] = array.store

    # -- how many pieces there are at each size ----------------------------

    def grid(self, level: int) -> tuple[int, int]:
        """How many pieces tall and wide the picture is at this size.

        The last row and column can be part-empty — the eighth-size picture is only
        64 voxels tall while a piece is 128 — which is ordinary OME-Zarr. The piece
        is still stored and sent whole; a reader simply ignores what falls outside.
        """
        height, width = g.level_shape(level)
        return -(-height // g.CHUNK), -(-width // g.CHUNK)

    # -- the three halves of answering for a piece -------------------------

    def ground(self, level: int, cy: int, cx: int) -> tuple[int, int, int, int]:
        """Which full-size ground a piece at this size covers.

        A piece is always 128 voxels across, but at the half-size picture each of
        those voxels stands for two full-size voxels, so the piece covers 256 of
        them. This is where the cost comes from and it is worth having in one named
        place rather than inline.
        """
        reach = g.CHUNK * 2 ** level
        return cy * reach, cy * reach + reach, cx * reach, cx * reach + reach

    def touching(self, level: int, cy: int, cx: int) -> list[int]:
        """Which positions reach into the piece at row ``cy``, column ``cx``."""
        y0, y1, x0, x1 = self.ground(level, cy, cx)
        found = []
        for number, (ty, tx) in enumerate(self.places):
            if max(y0, ty) < min(y1, ty + g.TILE) and \
               max(x0, tx) < min(x1, tx + g.TILE):
                found.append(number)
        return found

    def source_chunks_read(self, level: int, cy: int, cx: int) -> int:
        """How many of the positions' own files this piece has to be read out of.

        Each position is kept in files of 128 by 128 voxels, so a piece that covers
        a lot of ground reaches into a lot of files. This counts them the way the
        reads below will actually land, and it is the number the whole cost question
        turns on: if it grows by four every time the picture halves, so should the
        work.
        """
        y0, y1, x0, x1 = self.ground(level, cy, cx)
        high, wide = self.source_chunk
        total = 0
        for number in self.touching(level, cy, cx):
            ty, tx = self.places[number]
            ay, by = max(y0, ty) - ty, min(y1, ty + g.TILE) - ty
            ax, bx = max(x0, tx) - tx, min(x1, tx + g.TILE) - tx
            total += (((by - 1) // high) - (ay // high) + 1) * \
                     (((bx - 1) // wide) - (ax // wide) + 1)
        return total

    def compose(self, level: int, cy: int, cx: int) -> np.ndarray:
        """Lay the positions into the ground this piece covers, then shrink it.

        Where two positions cover the same ground the later one wins, which is the
        same rule an operator sees in the viewer and the same rule the ground-truth
        canvas follows. The averaging happens afterwards, on the finished picture,
        so a block of voxels that straddles a seam is averaged across the seam
        rather than inside one position.
        """
        factor = 2 ** level
        y0, y1, x0, x1 = self.ground(level, cy, cx)
        wide = g.CHUNK * factor
        ground = np.zeros((wide, wide), "uint16")
        for number in self.touching(level, cy, cx):
            ty, tx = self.places[number]
            # Where this position and this ground overlap, in the picture's own
            # coordinates, then the same rectangle in the position's.
            ay, by = max(y0, ty), min(y1, ty + g.TILE)
            ax, bx = max(x0, tx), min(x1, tx + g.TILE)
            ground[ay - y0:by - y0, ax - x0:bx - x0] = self.arrays[number][
                0, 0, 0, ay - ty:by - ty, ax - tx:bx - tx]
        return g.shrink(ground, factor)

    def encode(self, level: int, piece: np.ndarray) -> bytes:
        """Turn the assembled numbers into the bytes the browser expects.

        Written through a tiny in-memory zarr array declared with exactly the codecs
        the picture's description names, so the encoding is zarr's own rather than
        something hand-rolled that only looks right.
        """
        self._out[level][0, 0, 0] = piece
        return bytes(self._store[level]._store_dict["c/0/0/0/0/0"].to_bytes())

    def bytes_for(self, level: int, cy: int, cx: int) -> bytes:
        return self.encode(level, self.compose(level, cy, cx))

    # -- what the picture says about itself --------------------------------

    def group_json(self) -> bytes:
        """The whole canvas described as an ordinary OME-Zarr multiscale image.

        Four sizes, five axes, and the scale and the translation written **inside
        each dataset** rather than beside the list of them — that placement is what
        the rest of this project writes and there is a conformance test for it. The
        translation is the same on every size, because it names the corner of the
        first voxel and every size begins at the same corner.

        The image also says how its smaller copies were made. Here that is
        ``mean``: each coarse voxel is the average of the block of fine voxels
        underneath it. The rest of this project writes ``nearest`` instead, because
        keeping every second voxel is what lets a view point at a position's own
        smaller copies. Nothing is pointed at here, so the honest answer is the
        averaged one.
        """
        datasets = []
        for level in range(g.LEVELS):
            factor = 2 ** level
            datasets.append({
                "path": str(level),
                "coordinateTransformations": [
                    {"type": "scale",
                     "scale": [1.0, 1.0, 1.0,
                               g.VOXEL_UM * factor, g.VOXEL_UM * factor]},
                    {"type": "translation",
                     "translation": [0.0, 0.0, 0.0, 0.0, 0.0]},
                ],
            })
        return json.dumps({
            "attributes": {
                "ome": {
                    "version": "0.5",
                    "multiscales": [{
                        "name": "pyramid-anywhere",
                        "type": "mean",
                        "metadata": {
                            "description": (
                                "Each smaller copy is the average of two-by-two "
                                "blocks of the copy above it, worked out from the "
                                "assembled picture rather than from any one "
                                "position."
                            ),
                        },
                        "axes": [
                            {"name": "t", "type": "time", "unit": "second"},
                            {"name": "c", "type": "channel"},
                            {"name": "z", "type": "space", "unit": "micrometer"},
                            {"name": "y", "type": "space", "unit": "micrometer"},
                            {"name": "x", "type": "space", "unit": "micrometer"},
                        ],
                        "datasets": datasets,
                    }],
                    "omero": {"channels": [{
                        "label": "probe", "color": "FFFFFF",
                        "window": {"min": 0, "max": 65535,
                                   "start": 0, "end": 4095},
                    }]},
                }
            },
            "zarr_format": 3,
            "node_type": "group",
        }).encode()

    def array_json(self, level: int) -> bytes:
        """One size of the picture, in pieces of 128, encoded as above."""
        height, width = g.level_shape(level)
        return json.dumps({
            "shape": [1, 1, 1, height, width],
            "data_type": "uint16",
            "chunk_grid": {"name": "regular", "configuration": {
                "chunk_shape": [1, 1, 1, g.CHUNK, g.CHUNK]}},
            "chunk_key_encoding": {"name": "default",
                                   "configuration": {"separator": "/"}},
            "fill_value": 0,
            "codecs": CODECS,
            "attributes": {},
            "dimension_names": AXES,
            "zarr_format": 3,
            "node_type": "array",
            "storage_transformers": [],
        }).encode()

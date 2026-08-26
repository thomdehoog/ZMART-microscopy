"""Build a piece of the whole picture out of whichever positions reach into it.

Today a view answers for a piece of the picture by handing over one position's
own file, untouched. That is as fast as anything can be, but it forces every
position onto the grid of pieces: the bytes asked for have to *be* a file that
already exists.

Here the server does the other thing. For each piece it works out which positions
overlap it, reads just the overlapping rectangle out of each, lays them into one
small array and encodes that the way the description says a piece is encoded. The
browser cannot tell the difference — it receives an ordinary piece of an ordinary
OME-Zarr image — and the positions underneath are free to sit anywhere at all.
"""

from __future__ import annotations

import json
from pathlib import Path

import geometry as g
import numpy as np
import zarr

# The description of one piece: the same shape, kind of number and encoding the
# positions use. Saying it once here is what makes the bytes this file produces
# and the bytes a position holds interchangeable.
CODECS = [
    {"name": "bytes", "configuration": {"endian": "little"}},
    {"name": "zstd", "configuration": {"level": 0, "checksum": False}},
]
AXES = ["t", "c", "z", "y", "x"]
VOXEL_UM = [1.0, 1.0, 1.0, 0.5, 0.5]   # along t, c, z, y, x


class Composer:
    """Holds the positions open and builds pieces of the picture from them."""

    def __init__(self, positions_folder: Path, places: list[tuple[int, int]]):
        self.places = list(places)
        folders = sorted(Path(positions_folder).glob("*.ome.zarr"))
        if len(folders) != len(self.places):
            raise RuntimeError(
                f"{len(folders)} position images but {len(self.places)} places "
                "on the stage; the two have to agree or tiles would be drawn in "
                "somebody else's place"
            )
        # Opened once and kept open. Opening a store costs a read of its
        # description, and doing that per piece would be measuring the wrong
        # thing entirely.
        self.arrays = [zarr.open_array(str(one / "0"), mode="r") for one in folders]

        # One array to encode into, reused. A server holds a buffer rather than
        # building one for every piece it answers.
        self._out = zarr.create_array(
            store=zarr.storage.MemoryStore(),
            shape=(1, 1, 1, g.CHUNK, g.CHUNK),
            chunks=(1, 1, 1, g.CHUNK, g.CHUNK),
            dtype="uint16",
            zarr_format=3,
            dimension_names=AXES,
            overwrite=True,
        )
        self._store = self._out.store
        # The encoding is checked rather than assumed. If zarr's defaults ever
        # differed from what the picture's description promises, every piece
        # served would be unreadable rubbish and the window would simply be
        # black — a fault with nothing on screen to explain it.
        written = [dict(one) for one in
                   self._out.metadata.to_dict()["codecs"]]
        if written != CODECS:
            raise RuntimeError(
                f"a piece would be encoded as {written} but the picture says "
                f"{CODECS}; the browser would be sent bytes it cannot read"
            )

    # -- the two halves of answering for a piece ---------------------------

    def touching(self, cy: int, cx: int) -> list[int]:
        """Which positions reach into the piece at row ``cy``, column ``cx``."""
        y0, x0 = cy * g.CHUNK, cx * g.CHUNK
        found = []
        for number, (ty, tx) in enumerate(self.places):
            if max(y0, ty) < min(y0 + g.CHUNK, ty + g.TILE) and \
               max(x0, tx) < min(x0 + g.CHUNK, tx + g.TILE):
                found.append(number)
        return found

    def compose(self, cy: int, cx: int) -> np.ndarray:
        """Lay every position that reaches into this piece into one small array.

        Where two positions cover the same ground the later one wins, which is
        the same rule an operator sees in the viewer and the same rule the
        ground-truth canvas follows.
        """
        piece = np.zeros((g.CHUNK, g.CHUNK), "uint16")
        y0, x0 = cy * g.CHUNK, cx * g.CHUNK
        for number in self.touching(cy, cx):
            ty, tx = self.places[number]
            # Where this position and this piece overlap, in the picture's own
            # coordinates, then the same rectangle in the position's.
            ay, by = max(y0, ty), min(y0 + g.CHUNK, ty + g.TILE)
            ax, bx = max(x0, tx), min(x0 + g.CHUNK, tx + g.TILE)
            piece[ay - y0:by - y0, ax - x0:bx - x0] = self.arrays[number][
                0, 0, 0, ay - ty:by - ty, ax - tx:bx - tx]
        return piece

    def encode(self, piece: np.ndarray) -> bytes:
        """Turn the assembled numbers into the bytes the browser expects.

        Written through a tiny in-memory zarr array declared with exactly the
        codecs the picture's description names, so the encoding is zarr's own
        rather than something hand-rolled that only looks right.
        """
        self._out[0, 0, 0] = piece
        return bytes(self._store._store_dict["c/0/0/0/0/0"].to_bytes())

    def bytes_for(self, cy: int, cx: int) -> bytes:
        return self.encode(self.compose(cy, cx))

    # -- what the picture says about itself --------------------------------

    def group_json(self) -> bytes:
        """The whole canvas described as an ordinary OME-Zarr multiscale image.

        One level, five axes, and the scale and translation written **inside the
        dataset** rather than beside the set of levels — that placement is what
        the rest of this project writes and there is a conformance test for it.
        """
        return json.dumps({
            "attributes": {
                "ome": {
                    "version": "0.5",
                    "multiscales": [{
                        "name": "anywhere",
                        "axes": [
                            {"name": "t", "type": "time", "unit": "second"},
                            {"name": "c", "type": "channel"},
                            {"name": "z", "type": "space", "unit": "micrometer"},
                            {"name": "y", "type": "space", "unit": "micrometer"},
                            {"name": "x", "type": "space", "unit": "micrometer"},
                        ],
                        "datasets": [{
                            "path": "0",
                            "coordinateTransformations": [
                                {"type": "scale", "scale": VOXEL_UM},
                                {"type": "translation",
                                 "translation": [0.0, 0.0, 0.0, 0.0, 0.0]},
                            ],
                        }],
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

    def array_json(self) -> bytes:
        """The full-size level: the whole canvas, in pieces, encoded as above."""
        return json.dumps({
            "shape": [1, 1, 1, g.CANVAS, g.CANVAS],
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

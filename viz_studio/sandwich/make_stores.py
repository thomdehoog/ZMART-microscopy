"""The two little acquisitions the sandwich measurements are made against.

Both are written by this project's own writer, :class:`zmart_storage.TileCanvases`,
rather than being made up by hand. That matters more than it might sound: the
whole question being settled here is whether a second drawing engine can sit
underneath the operator's own drawing and stay lined up with it, and an answer
obtained on a made-up image would say nothing about the images a run actually
produces — the sparseness, the pyramid of smaller copies, the chunk size, the
many small requests. So these are ordinary runs, only small enough to measure
quickly.

There are two because the measurements ask two different questions.

**The square** is for the margin test. It is a small image that has been imaged
edge to edge, so on screen it is a solid square of picture with the engine's own
background all around it. That square is the thing the margins are measured
against, and having it filled completely is what makes its edges sharp enough to
find in a photograph.

**The sparse canvas** is for the timing measurements. It is shaped the way a
real smart-microscopy run is shaped: a very large canvas declared up front, with
only a small patch of it actually imaged. Nearly every piece the engine asks for
is a piece nobody has written, and answering "there is nothing here" is most of
what the server does during a redraw. That is the case the latency figures have
to be taken on, because it is the case an operator meets.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

# The writer lives at the top of the repository, beside viz_studio.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from zmart_storage import Channel, TileCanvases  # noqa: E402

# How wide and tall the solid square of picture is, in voxels. A thousand or so
# is a comfortable size: large enough that it fills a good part of the window at
# a natural magnification, small enough that the whole of it is written in well
# under a second so a measurement is not spent waiting for a disk.
SQUARE_VOXELS = 1024
SQUARE_TILE = 256

# The brightness written into the square. The shader in the page maps the range
# 0 to 4095 onto black to white, so this lands near white — which is one of the
# three colours the margin test needs to be able to tell apart. See
# `page/src/margin_probe.js`, where the choice of the three colours is explained
# at length.
BRIGHT = 3800

# The sparse canvas: a large declared room with a small imaged patch inside it.
# Eight thousand voxels across is about what a plate-sized carrier comes to at a
# realistic voxel size, and it is far more than any of these tests draws at once.
SPARSE_VOXELS = 8192
SPARSE_TILE = 512
# A chunk of sixty-four is deliberately small. It is what makes a single redraw
# of the whole canvas cost a couple of hundred separate requests rather than a
# dozen, which is the shape the sparse acquisition measured earlier in this
# project had, and the shape the arithmetic in the report is checked against.
SPARSE_CHUNK = 64
# How many tiles across the imaged patch is. Three by three keeps the patch well
# inside the declared room, so most of what the engine looks at really is
# unimaged ground.
SPARSE_PATCH = 3


def _a_tile(depth: int, height: int, width: int, seed: int) -> np.ndarray:
    """One tile's worth of picture: bright, with a gentle texture in it.

    The texture is there on purpose. A perfectly flat tile would still give the
    sharp edges the margin test needs, but it would also pass a check that only
    asks "is there variety on screen" while showing nothing at all, and this
    project has been caught by exactly that before. A slow ramp keeps the edges
    sharp and gives the picture something to say for itself.
    """
    across = np.linspace(0.0, 1.0, width, dtype=np.float32)
    down = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]
    texture = (across + down) * 0.5
    # Kept within a narrow band near the top of the range so the whole square
    # reads as one bright colour to the margin test, while still varying.
    values = BRIGHT - 250.0 * texture + 40.0 * ((seed % 5) / 4.0)
    plane = values.astype(np.uint16)
    return np.repeat(plane[None, :, :], depth, axis=0)


def write_the_square(folder: Path, *, name: str = "square") -> TileCanvases:
    """Image a small canvas from edge to edge, and leave the writer open.

    The writer is handed back still open rather than closed, because one of the
    measurements writes more tiles while the viewer is looking at the picture.
    Close it yourself when you are finished with it.
    """
    canvases = TileCanvases.create(
        folder,
        name=name,
        canvas_shape=(1, SQUARE_VOXELS, SQUARE_VOXELS),
        tile_shape=(1, SQUARE_TILE, SQUARE_TILE),
        tile_step=(1, SQUARE_TILE, SQUARE_TILE),
        voxel_size_um=(1.0, 1.0, 1.0),
        channels=[Channel(name="probe", color="FFFFFF", window=(0, 4095))],
        discard_existing_run=True,
    )
    seed = 0
    for row in range(SQUARE_VOXELS // SQUARE_TILE):
        for column in range(SQUARE_VOXELS // SQUARE_TILE):
            canvases.write(
                _a_tile(1, SQUARE_TILE, SQUARE_TILE, seed),
                origin=(0, row * SQUARE_TILE, column * SQUARE_TILE),
                tile_index=(0, row, column),
            )
            seed += 1
    return canvases


def write_the_sparse_canvas(folder: Path, *, name: str = "sparse") -> TileCanvases:
    """Declare a large canvas and image a small patch in the middle of it.

    This is the ordinary shape of a run: the room is declared to the stage's
    reach, and the specimen occupies a small part of it. The writer is left open
    for the same reason as above.
    """
    canvases = TileCanvases.create(
        folder,
        name=name,
        canvas_shape=(1, SPARSE_VOXELS, SPARSE_VOXELS),
        tile_shape=(1, SPARSE_TILE, SPARSE_TILE),
        tile_step=(1, SPARSE_TILE, SPARSE_TILE),
        voxel_size_um=(1.0, 1.0, 1.0),
        channels=[Channel(name="probe", color="FFFFFF", window=(0, 4095))],
        chunk=SPARSE_CHUNK,
        discard_existing_run=True,
    )
    # Put the patch in the middle, on the tile grid, so the writer places it
    # exactly where a raster scan would have.
    middle = (SPARSE_VOXELS // SPARSE_TILE) // 2 - SPARSE_PATCH // 2
    seed = 0
    for row in range(middle, middle + SPARSE_PATCH):
        for column in range(middle, middle + SPARSE_PATCH):
            canvases.write(
                _a_tile(1, SPARSE_TILE, SPARSE_TILE, seed),
                origin=(0, row * SPARSE_TILE, column * SPARSE_TILE),
                tile_index=(0, row, column),
            )
            seed += 1
    return canvases


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    args.folder.mkdir(parents=True, exist_ok=True)
    square = write_the_square(args.folder)
    sparse = write_the_sparse_canvas(args.folder)
    square.close()
    sparse.close()
    for path in list(square.paths) + list(sparse.paths):
        print(path)

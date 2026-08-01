"""The little acquisitions every option is measured against.

All of them are written by this project's own writer,
:class:`zmart_storage.TileCanvases`, rather than being made up by hand. That
matters more than it sounds. The whole question being settled is how three ways
of drawing behave on the runs this project actually produces, and an answer
obtained on a made-up image would say nothing about the sparseness, the pyramid
of smaller copies, the size of the blocks it is stored in or the many small
requests that make a real one what it is. So these are ordinary runs, only small
enough to measure quickly.

There are six, because the measurements and the checks that go with them ask six
different questions between them.

**The square** is for registration and handedness. It is imaged edge to edge, so
on screen it is a solid block of picture with the background all around it — the
sharp edges the margin measurement needs in order to find anything at all.

**The lopsided square** is the same shape written dim at one edge and bright at
the other. It is the only thing here that can say which way round the picture is
drawn, and it exists because dragging cannot: an engine pans using the same axis
mapping it draws with, so the picture follows the hand pixel for pixel whichever
way round it is. Only something asymmetric *inside* the specimen can tell.

**The sparse canvas** is shaped the way a real smart-microscopy run is shaped: a
very large canvas declared up front with only a small patch of it imaged. Nearly
every piece an engine asks for is a piece nobody has written, and answering
"there is nothing here" is most of what a server does during a redraw. That is
the case the timing figures have to be taken on, because it is the case an
operator meets.

**The scattered canvas** is imaged in a few places far apart from one another,
which is what a run visiting chosen positions looks like. It is what the
sparseness measurement uses: the operator's drawing should show through the gaps
between them, and picture should appear only where picture was written.

**The fine square** is the square again, written at a third of a micrometre to
the voxel instead of one. It exists to catch a viewer that has quietly settled on
counting in voxels while telling everybody it counts in micrometres. On every
other store here a voxel is exactly one micrometre, so the two are the same
number and the confusion cannot be seen.

**The two-colour square** records two channels rather than one, and it names a
different colour for each of them. Every other acquisition here has a single
white channel, which means a viewer that draws only the first channel of a run,
or that draws every channel white, looks exactly right on all of them. This one
is written so that a photograph can tell: the first channel fills the left half
of the square and is named green, the second fills the right half and is named
red. If a viewer is really reading the run's own description of itself, the two
halves come out in those two colours.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

# The writer lives at the top of the repository, beside viz_studio.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from zmart_storage import Channel, TileCanvases  # noqa: E402

# How wide and tall the solid square of picture is, in voxels. A thousand or so
# is comfortable: large enough to fill a good part of the window at a natural
# magnification, small enough that the whole of it is written in well under a
# second, so a measurement is not spent waiting for a disk.
SQUARE_VOXELS = 1024
SQUARE_TILE = 256

# The brightness written into the square. The little program each engine runs to
# turn stored numbers into colour maps 0 to 4095 onto black to white, so this
# lands near white — one of the four colours the margin measurement has to be
# able to tell apart. See `harness/src/drawings.js`.
BRIGHT = 3800

# The sparse canvas: a large declared room with a small imaged patch inside it.
# Eight thousand voxels across is about what a plate-sized carrier comes to at a
# realistic voxel size, and far more than any of these measurements draws at once.
SPARSE_VOXELS = 8192
SPARSE_TILE = 512
# How large a block the picture is stored in — a chunk, in the store's own word.
# It is the smallest piece anything can ask for, so it decides how many separate
# requests a redraw costs. Sixty-four voxels is deliberately small: it makes one
# redraw of the whole canvas cost a couple of hundred requests rather than a
# dozen, which is the shape the sparse acquisitions measured earlier in this
# project had.
SPARSE_CHUNK = 64
SPARSE_PATCH = 3

# One micrometre to a voxel, so that a number of voxels and a number of
# micrometres are the same number. That is a convenience for reading the results
# and nothing more: every conversion still goes through the voxel size recorded
# in the image's own description, so a store written at a different size would
# come out in the right place. `test_the_units_are_micrometres` checks exactly
# that, on a store written at a third of a micrometre to the voxel.
VOXEL_UM = 1.0


def _a_tile(depth: int, height: int, width: int, seed: int) -> np.ndarray:
    """One tile's worth of picture: bright, with a gentle texture in it.

    The texture is there on purpose. A perfectly flat tile would still give the
    sharp edges the margin measurement needs, but it would also pass a check that
    only asks "is there variety on screen" while showing nothing at all, and this
    project has been caught by exactly that before.
    """
    across = np.linspace(0.0, 1.0, width, dtype=np.float32)
    down = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]
    texture = (across + down) * 0.5
    values = BRIGHT - 250.0 * texture + 40.0 * ((seed % 5) / 4.0)
    return np.repeat(values.astype(np.uint16)[None, :, :], depth, axis=0)


def _a_lopsided_tile(height: int, width: int, at: int, across_tiles: int) -> np.ndarray:
    """A tile that is part of a specimen running dim at one edge to bright at the
    other.

    ``at`` is which column of the scan this tile is, counting from the low edge
    of the image's own width axis. The brightness rises with it, so the finished
    picture is dark where width is small and bright where width is large.
    """
    low = 200 + (BRIGHT - 200) * (at / max(1, across_tiles))
    high = 200 + (BRIGHT - 200) * ((at + 1) / max(1, across_tiles))
    ramp = np.linspace(low, high, width, dtype=np.float32)
    plane = np.repeat(ramp[None, :], height, axis=0)
    return plane.astype(np.uint16)[None, :, :]


def _canvas(
    folder: Path, name: str, *, shape, tile, chunk=None, voxel_um=VOXEL_UM,
    channels=None,
):
    return TileCanvases.create(
        folder,
        name=name,
        canvas_shape=shape,
        tile_shape=tile,
        tile_step=tile,
        voxel_size_um=(voxel_um, voxel_um, voxel_um),
        channels=channels or [Channel(name="probe", color="FFFFFF", window=(0, 4095))],
        discard_existing_run=True,
        **({"chunk": chunk} if chunk else {}),
    )


def write_the_square(folder: Path, *, name: str = "square") -> TileCanvases:
    """Image a small canvas edge to edge, and leave the writer open.

    The writer is handed back still open rather than closed, because some of the
    measurements write more tiles while a viewer is looking at the picture. Close
    it yourself when you have finished with it.
    """
    canvases = _canvas(
        folder, name,
        shape=(1, SQUARE_VOXELS, SQUARE_VOXELS),
        tile=(1, SQUARE_TILE, SQUARE_TILE),
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


def write_the_lopsided_square(folder: Path, *, name: str = "lopsided") -> TileCanvases:
    """The same square, dim at the low-width edge and bright at the high one."""
    canvases = _canvas(
        folder, name,
        shape=(1, SQUARE_VOXELS, SQUARE_VOXELS),
        tile=(1, SQUARE_TILE, SQUARE_TILE),
    )
    across = SQUARE_VOXELS // SQUARE_TILE
    for row in range(across):
        for column in range(across):
            canvases.write(
                _a_lopsided_tile(SQUARE_TILE, SQUARE_TILE, column, across),
                origin=(0, row * SQUARE_TILE, column * SQUARE_TILE),
                tile_index=(0, row, column),
            )
    return canvases


def write_the_sparse_canvas(folder: Path, *, name: str = "sparse") -> TileCanvases:
    """Declare a large canvas and image a small patch in the middle of it."""
    canvases = _canvas(
        folder, name,
        shape=(1, SPARSE_VOXELS, SPARSE_VOXELS),
        tile=(1, SPARSE_TILE, SPARSE_TILE),
        chunk=SPARSE_CHUNK,
    )
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


# Where the scattered canvas is imaged, as tile positions on its own grid. Five
# places well apart from one another, which is what a run visiting chosen
# positions looks like, and enough gap between them for the operator's drawing to
# be plainly visible in between.
SCATTERED_AT = ((0, 0), (0, 3), (2, 1), (3, 3), (1, 2))
SCATTERED_ACROSS = 4
SCATTERED_TILE = 256


def write_the_scattered_canvas(folder: Path, *, name: str = "scattered") -> TileCanvases:
    """Image a few places far apart, leaving most of the canvas untouched."""
    span = SCATTERED_ACROSS * SCATTERED_TILE
    canvases = _canvas(
        folder, name,
        shape=(1, span, span),
        tile=(1, SCATTERED_TILE, SCATTERED_TILE),
    )
    for seed, (row, column) in enumerate(SCATTERED_AT):
        canvases.write(
            _a_tile(1, SCATTERED_TILE, SCATTERED_TILE, seed),
            origin=(0, row * SCATTERED_TILE, column * SCATTERED_TILE),
            tile_index=(0, row, column),
        )
    return canvases


def write_a_third_of_a_micrometre_square(
    folder: Path, *, name: str = "fine"
) -> TileCanvases:
    """The same square written at a third of a micrometre to the voxel.

    Its only purpose is to catch a viewer that has quietly settled on counting in
    voxels while claiming to count in micrometres. On the other stores here a
    voxel is exactly one micrometre, so the two are the same number and a
    confusion between them is invisible.
    """
    canvases = _canvas(
        folder, name,
        shape=(1, SQUARE_VOXELS, SQUARE_VOXELS),
        tile=(1, SQUARE_TILE, SQUARE_TILE),
        voxel_um=1.0 / 3.0,
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


# The two colours the two-colour square records, exactly as the run writes them
# into its own description. They are far apart on purpose: a photograph has to be
# able to say which half of the square is which, and two shades of the same
# colour would leave that to the reader's faith rather than to the picture.
GREEN = "00FF00"
RED = "FF0000"


def write_the_two_colour_square(folder: Path, *, name: str = "colours") -> TileCanvases:
    """A square recorded in two channels, each named a different colour.

    Two things about a viewer cannot be seen on a run with one white channel,
    and both of them matter to anybody imaging more than one label at a time. A
    viewer that quietly draws only the first channel looks perfectly correct, and
    so does one that draws every channel white. So this run has two channels, it
    names one of them green and the other red, and it puts them in different
    halves of the square: the first channel fills the left half, the second fills
    the right.

    Writing them side by side rather than on top of one another is what makes the
    photograph readable. Channels drawn over each other add up, so two colours in
    the same place would come out as a third colour and a reader would have to
    reason about what they were seeing. Side by side, green on the left and red
    on the right is what a working viewer shows, and anything else is a fault you
    can point at.
    """
    canvases = _canvas(
        folder, name,
        shape=(1, SQUARE_VOXELS, SQUARE_VOXELS),
        tile=(1, SQUARE_TILE, SQUARE_TILE),
        channels=[
            Channel(name="488", color=GREEN, window=(0, 4095)),
            Channel(name="561", color=RED, window=(0, 4095)),
        ],
    )
    across = SQUARE_VOXELS // SQUARE_TILE
    seed = 0
    for row in range(across):
        for column in range(across):
            # The left half of the square is the first channel and the right half
            # is the second, so each colour has a side of its own on screen.
            channel = 0 if column < across // 2 else 1
            canvases.write(
                _a_tile(1, SQUARE_TILE, SQUARE_TILE, seed),
                origin=(0, row * SQUARE_TILE, column * SQUARE_TILE),
                channel=channel,
                tile_index=(0, row, column),
            )
            seed += 1
    return canvases


def write_them_all(folder: Path) -> None:
    """Write every store the suite needs, and close them."""
    folder.mkdir(parents=True, exist_ok=True)
    for write in (
        write_the_square,
        write_the_lopsided_square,
        write_the_sparse_canvas,
        write_the_scattered_canvas,
        write_a_third_of_a_micrometre_square,
        write_the_two_colour_square,
    ):
        write(folder).close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    write_them_all(args.folder)
    print(f"wrote the measurement stores into {args.folder}")

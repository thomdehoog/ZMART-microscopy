"""The shape of this run, written down once so nothing has to state it twice.

Ten positions in two rows of five, stepped 179 voxels apart. A position is 256
voxels across and a piece of the picture is 128, so the step is neither a
multiple of the piece nor as wide as a position: every neighbour overlaps its
neighbour by 77 voxels, and no seam between two positions lands on the boundary
between two pieces.

The new part, compared with the demonstration this is copied from, is that the
picture is offered at **four sizes** rather than one. Each size halves the height
and the width of the one before it, so the same specimen is available as 1024
voxels across, then 512, then 256, then 128. That is what a viewer needs in order
to draw something sensible when you are zoomed out, and it is the thing that odd
offsets were expected to make impossible: half of 179 is not a whole number of
voxels, so a smaller copy cannot simply *point* at a position sitting there.
"""

from __future__ import annotations

import numpy as np

TILE = 256          # how large one position is, in y and x
CHUNK = 128         # how large one piece of the picture is
STEP = 179          # how far the stage moves between positions
COLUMNS = 5         # positions across
ROWS = 2            # positions down
LEVELS = 4          # sizes of the picture: full, half, quarter, eighth
OVERLAP = TILE - STEP                              # 77 voxels

SPAN_Y = STEP * (ROWS - 1) + TILE                  # 435 voxels of imaged ground
SPAN_X = STEP * (COLUMNS - 1) + TILE               # 972 voxels of imaged ground
CANVAS_Y = -(-SPAN_Y // CHUNK) * CHUNK             # 512, rounded up to whole pieces
CANVAS_X = -(-SPAN_X // CHUNK) * CHUNK             # 1024

PLACES = [(row * STEP, column * STEP)
          for row in range(ROWS)
          for column in range(COLUMNS)]

VOXEL_UM = 0.5      # how large one full-size voxel is, in y and x


def level_shape(level: int) -> tuple[int, int]:
    """How tall and how wide the picture is at one of its four sizes.

    Each size is half the one before it. Both canvas sides are multiples of eight,
    so every halving divides exactly and no row or column is ever left over.
    """
    factor = 2 ** level
    return CANVAS_Y // factor, CANVAS_X // factor


def shrink(picture: np.ndarray, factor: int) -> np.ndarray:
    """Make a smaller copy by **averaging** each square block of voxels.

    Averaging is the choice that matters here, and it is worth saying why. The
    other way to shrink a picture is to keep every second voxel and throw the rest
    away, which is what this project's writer does today. Keeping every second
    voxel is cheap and it has a useful property: a coarse voxel comes from exactly
    one fine voxel, and therefore from exactly one position, so a smaller copy of
    the whole picture can be assembled by pointing at the positions' own smaller
    copies.

    That property is exactly what breaks when positions sit at odd offsets. A
    position beginning at voxel 179 has its own every-second-voxel grid starting on
    an odd number, which is out of step with the picture's. Averaging does not care:
    it looks at the finished picture, not at which position each voxel came from, so
    a block that straddles two overlapping positions is averaged just as happily as
    one that does not. The cost is that the answer can no longer be borrowed from
    any single position; it has to be worked out. That is the trade this whole
    experiment is measuring.

    Args:
        picture: a two-dimensional array whose height and width both divide by
            ``factor``.
        factor: how much smaller to make it. ``1`` gives the picture back unchanged.

    Returns:
        The smaller picture, as the same kind of number it was given.
    """
    if factor == 1:
        return picture
    height, width = picture.shape
    blocks = picture.reshape(height // factor, factor, width // factor, factor)
    averaged = blocks.mean(axis=(1, 3), dtype="float64")
    return np.rint(averaged).astype(picture.dtype)


def a_tile(number: int) -> np.ndarray:
    """One position's picture, made so a person can tell it from its neighbours.

    Each tile carries its own brightness, a bright frame around its edge and a
    number of bright bars along its top, so a photograph of the screen shows both
    which tile is which and exactly where each one begins and ends.
    """
    level = 900 + number * 330
    tile = np.full((TILE, TILE), level, "uint16")

    # A bright border, so the seam between two tiles is visible even where they
    # overlap and the values behind them are similar.
    edge = 4000
    tile[:6, :] = edge
    tile[-6:, :] = edge
    tile[:, :6] = edge
    tile[:, -6:] = edge

    # A dark disc in the middle of each tile: a round thing is the easiest shape to
    # see squashed or shifted if the placement were wrong.
    yy, xx = np.mgrid[0:TILE, 0:TILE]
    middle = (TILE - 1) / 2
    radius = np.hypot(yy - middle, xx - middle)
    tile[radius < 70] = 200
    tile[(radius >= 70) & (radius < 78)] = 4000

    # As many bright bars along the top as the tile's number, counting from one, so
    # tile five is readable as five bars without a legend.
    for bar in range(number + 1):
        left = 20 + bar * 22
        tile[20:56, left:left + 12] = 4000

    return tile


def truth(level: int = 0) -> np.ndarray:
    """The whole canvas at one size, as we mean it to look, built plainly in numpy.

    The full-size canvas is laid out first — later positions drawn over earlier ones
    where they overlap, which is the rule the composing server follows too — and
    then averaged down to the size asked for. Building it this way, rather than by
    asking the server, is what makes it an independent answer to compare against.
    """
    canvas = np.zeros((CANVAS_Y, CANVAS_X), "uint16")
    for number, (y, x) in enumerate(PLACES):
        canvas[y:y + TILE, x:x + TILE] = a_tile(number)
    return shrink(canvas, 2 ** level)

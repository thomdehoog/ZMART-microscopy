"""The geometry of the demonstration, in one place so nothing states it twice.

Nine positions in a three by three raster, stepped 179 voxels apart. A position
is 256 voxels across and a piece of the picture is 128, so the step is neither a
multiple of the piece nor as large as a position: every neighbour overlaps by 77
voxels, and almost every piece of the picture straddles more than one position.
"""

import numpy as np

TILE = 256          # how large one position is, in y and x
CHUNK = 128         # how large one piece of the picture is
STEP = 179          # how far the stage moves between positions
ACROSS = 3          # positions per row and per column
OVERLAP = TILE - STEP                       # 77 voxels
SPAN = STEP * (ACROSS - 1) + TILE           # 614 voxels of imaged ground
CANVAS = -(-SPAN // CHUNK) * CHUNK          # 640, rounded up to whole pieces

PLACES = [(row * STEP, column * STEP)
          for row in range(ACROSS)
          for column in range(ACROSS)]


def a_tile(number: int) -> np.ndarray:
    """One position's picture, made so a person can tell it from its neighbours.

    Each tile carries its own brightness, a bright frame around its edge and a
    number of bright bars along its top, so the screenshot shows both which tile
    is which and exactly where each one begins and ends.
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

    # A dark disc in the middle of each tile: a round thing is the easiest shape
    # to see squashed or shifted if the placement were wrong.
    yy, xx = np.mgrid[0:TILE, 0:TILE]
    middle = (TILE - 1) / 2
    radius = np.hypot(yy - middle, xx - middle)
    tile[radius < 70] = 200
    tile[(radius >= 70) & (radius < 78)] = 4000

    # As many bright bars along the top as the tile's number, counting from one,
    # so tile five is readable as five bars without a legend.
    for bar in range(number + 1):
        left = 20 + bar * 22
        tile[20:56, left:left + 12] = 4000

    return tile


def truth() -> np.ndarray:
    """The whole canvas as we mean it to look, built plainly in numpy.

    Later positions are drawn over earlier ones where they overlap, which is the
    same rule the composing server follows, so this is the answer the composed
    pieces are checked against.
    """
    canvas = np.zeros((CANVAS, CANVAS), "uint16")
    for number, (y, x) in enumerate(PLACES):
        canvas[y:y + TILE, x:x + TILE] = a_tile(number)
    return canvas

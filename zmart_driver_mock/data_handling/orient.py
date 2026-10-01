"""Turning a camera picture so that it lines up with the stage.

A camera is rarely mounted exactly the way the stage moves: it may be turned
by 90° or mirrored. The image-to-stage registration records how. Turning
every picture the same way means that, in a saved image, right is always +x
on the stage and down is always +y, whatever the camera does. That makes
images from different microscopes, and different positions, line up.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

from array import array


def align_to_stage(
    planes: list[array], width: int, height: int, orientation: list[list[int]]
) -> tuple[list[array], int, int]:
    """Turn or mirror every plane so that right is +x and down is +y.

    ``orientation`` is ``[[a, b], [c, d]]`` from the registration: a step of
    one pixel right and one pixel down in the camera picture is a stage step
    of ``(a + b, c + d)``. Returns the new planes and their width and height,
    which swap after a 90° turn.
    """
    (a, b), (c, d) = orientation
    swapped = a == 0
    out_width, out_height = (height, width) if swapped else (width, height)
    aligned = []
    for plane in planes:
        out = array("H", bytes(2 * out_width * out_height))
        for row in range(height):
            v2 = 2 * row - (height - 1)  # twice the distance from the centre, to stay whole
            base = row * width
            for col in range(width):
                u2 = 2 * col - (width - 1)
                x2 = a * u2 + b * v2
                y2 = c * u2 + d * v2
                out_col = (x2 + out_width - 1) // 2
                out_row = (y2 + out_height - 1) // 2
                out[out_row * out_width + out_col] = plane[base + col]
        aligned.append(out)
    return aligned, out_width, out_height

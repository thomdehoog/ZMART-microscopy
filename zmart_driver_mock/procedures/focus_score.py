"""How sharp is a picture? The Brenner focus score.

The score adds up how much each pixel differs from the pixel two places to
its right. A sharp picture has crisp edges and scores high; a blurred one
scores low. It is a quick, widely used measure in light microscopy.

Nothing here is specific to this microscope. In the driver anatomy, this
belongs in the algorithms shared by every driver; it sits here until a
second driver needs it in the same form.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

from collections.abc import Sequence


def brenner(plane: Sequence[int], width: int) -> float:
    """The Brenner score of one plane, given row after row with ``width`` pixels per row."""
    total = 0
    for start in range(0, len(plane), width):
        row = plane[start : start + width]
        total += sum((row[i + 2] - row[i]) ** 2 for i in range(len(row) - 2))
    return float(total)

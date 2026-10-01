"""The pretend sample, and how the pretend camera sees it.

The mock microscope looks at an imaginary slide covered in small, bright,
round spots, like fluorescent beads. The spots never move, so the same stage
position always shows the same picture. That is what makes the mock useful
for setup work: registering images to the stage, calibrating objectives and
autofocus all depend on the sample staying put.

Three things are hidden in how the picture is made, on purpose. A real
microscope never tells you these either; the setup notebooks have to measure
them:

- **The camera orientation.** The camera may be turned by 90° or mirrored
  relative to the stage, so moving the stage to the right can move the
  picture up, down or left.
- **The objective offsets.** Each objective looks at a slightly different spot
  and focuses at a slightly different height.
- **The tilt of the slide.** The sharp focus height changes a little across
  the slide, the way a real slide is never perfectly flat.

:meth:`MockScope.truth` hands these answers out, so a test can check that a
setup notebook found the right ones.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import hashlib
import math
import random
import struct
from array import array
from dataclasses import dataclass

# The spots sit on an invisible grid of square cells, one spot per cell at a
# fixed, pseudo-random place inside it. This gives a sample that covers the
# whole slide without storing millions of spots.
CELL_UM = 20.0

# A spot is a soft round blob this wide (one standard deviation, in
# micrometers) when it is perfectly in focus.
SPOT_SIGMA_UM = 1.2

# How quickly a spot spreads out when it is out of focus: its width grows by
# this many micrometers for every micrometer of defocus.
BLUR_PER_UM_DEFOCUS = 0.35

# Spots blurred wider than this are too faint to matter and are left out,
# which keeps far-out-of-focus images quick to draw.
MAX_SIGMA_UM = 40.0

# The faint glow every camera picture has, even in the dark.
BACKGROUND = 100.0


@dataclass(frozen=True)
class Tilt:
    """The sharp focus height across the slide.

    At the raw stage position (``x0``, ``y0``) the slide is in focus at
    ``z0``. Moving 1 µm in x raises the focus height by ``slope_x`` µm, and
    likewise for y.
    """

    x0: float = 50_000.0
    y0: float = 37_500.0
    z0: float = 5_000.0
    slope_x: float = 0.001
    slope_y: float = -0.0005

    def focus_at(self, x: float, y: float) -> float:
        """The focus height at which the slide is sharp, at raw stage position x, y."""
        return self.z0 + self.slope_x * (x - self.x0) + self.slope_y * (y - self.y0)


def _spot_in_cell(seed: int, cell_x: int, cell_y: int) -> tuple[float, float, float]:
    """The one spot in a grid cell: its position in µm, and its brightness from 0.3 to 1.

    The values come from a hash of the cell's number, so they are the same
    every time, on every computer, without storing anything.
    """
    digest = hashlib.blake2b(struct.pack("<qqq", seed, cell_x, cell_y), digest_size=12).digest()
    a, b, c = struct.unpack("<III", digest)
    scale = 1.0 / 2**32
    x = (cell_x + 0.15 + 0.7 * a * scale) * CELL_UM
    y = (cell_y + 0.15 + 0.7 * b * scale) * CELL_UM
    brightness = 0.3 + 0.7 * c * scale
    return x, y, brightness


def render(
    *,
    seed: int,
    width: int,
    height: int,
    pixel_size_um: float,
    centre_x: float,
    centre_y: float,
    defocus_um: float,
    orientation: tuple[tuple[int, int], tuple[int, int]],
    signal: float,
    noise: random.Random | None,
) -> array:
    """Draw one camera picture and return it as ``array("H")``, row after row.

    ``centre_x`` and ``centre_y`` are the point on the slide (in raw stage
    micrometers) that appears in the middle of the picture. ``defocus_um`` is
    how far the focus is from the sharp height; spots blur as it grows.
    ``orientation`` says how the camera sits on the stage (see
    :class:`MockScope`). ``signal`` scales the brightness of the spots.
    ``noise`` adds camera noise when given; pass ``None`` for a clean picture,
    which makes tests exact.
    """
    sigma = math.hypot(SPOT_SIGMA_UM, BLUR_PER_UM_DEFOCUS * defocus_um)
    pixels = [BACKGROUND] * (width * height)
    if sigma <= MAX_SIGMA_UM:
        # A blurred spot keeps its total light but spreads it out, so its peak
        # drops as it widens. That is what makes the sharpest picture the
        # brightest-looking one, and what autofocus looks for.
        peak = signal * (SPOT_SIGMA_UM / sigma) ** 2
        reach_um = 4.0 * sigma
        (a, b), (c, d) = orientation
        half_w_um = width / 2 * pixel_size_um
        half_h_um = height / 2 * pixel_size_um
        # The picture covers this much of the slide in each direction; a 90°
        # camera turn swaps which side is which, so take the larger one.
        span_um = max(half_w_um, half_h_um) + reach_um
        first_x = math.floor((centre_x - span_um) / CELL_UM)
        last_x = math.floor((centre_x + span_um) / CELL_UM)
        first_y = math.floor((centre_y - span_um) / CELL_UM)
        last_y = math.floor((centre_y + span_um) / CELL_UM)
        two_sigma_sq = 2.0 * sigma * sigma
        reach_px = int(math.ceil(reach_um / pixel_size_um))
        for cell_x in range(first_x, last_x + 1):
            for cell_y in range(first_y, last_y + 1):
                spot_x, spot_y, brightness = _spot_in_cell(seed, cell_x, cell_y)
                dx = spot_x - centre_x
                dy = spot_y - centre_y
                # Turn the stage offset into an offset in the picture. The
                # orientation is a pure turn or mirror, so going back is just
                # reading the table the other way round.
                u_um = a * dx + c * dy
                v_um = b * dx + d * dy
                col_c = (u_um + half_w_um) / pixel_size_um - 0.5
                row_c = (v_um + half_h_um) / pixel_size_um - 0.5
                col_lo = max(0, int(col_c) - reach_px)
                col_hi = min(width - 1, int(col_c) + reach_px)
                row_lo = max(0, int(row_c) - reach_px)
                row_hi = min(height - 1, int(row_c) + reach_px)
                if col_lo > col_hi or row_lo > row_hi:
                    continue
                amplitude = peak * brightness
                for row in range(row_lo, row_hi + 1):
                    dv = (row - row_c) * pixel_size_um
                    base = row * width
                    for col in range(col_lo, col_hi + 1):
                        du = (col - col_c) * pixel_size_um
                        pixels[base + col] += amplitude * math.exp(
                            -(du * du + dv * dv) / two_sigma_sq
                        )
    out = array("H", bytes(2 * width * height))
    for index, value in enumerate(pixels):
        if noise is not None:
            # Camera noise grows with the square root of the light, as it does
            # on a real detector.
            value += noise.gauss(0.0, math.sqrt(max(value, 1.0)))
        out[index] = min(65_535, max(0, int(round(value))))
    return out

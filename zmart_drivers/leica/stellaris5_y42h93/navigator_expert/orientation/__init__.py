"""Record and apply how the camera is turned relative to the stage.

A camera or scanner is often mounted a quarter- or half-turn away from the
stage's own X and Y directions. When that happens, telling the stage to "move
right" shows up in the picture as a shift in some other direction, and the
software would end up chasing features the wrong way. This module records that
fixed turn -- measured once per microscope by the ``set_orientation`` notebook --
and turns each saved image so that its left-right and up-down line up with the
stage's X and Y. After that, the rest of the software can treat image directions
and stage directions as the same thing, with no rotation maths anywhere.

The turn is always a whole quarter-turn: 0, 90, 180, or 270 degrees. A real
microscope never sits at an odd in-between angle. If the measurement ever finds
one, something is physically misaligned, and we stop rather than blur the picture
by rotating it onto a fraction of a pixel. Because the turn is a whole quarter,
rotating the image is lossless -- it only moves pixels to new positions, it never
resamples them.

This is a separate thing from pixel-size calibration and from the stage limits,
and it lives entirely inside the driver. Workflows never deal with it: the images
they receive are already lined up with the stage.

The measured value is machine-specific, so it lives with the microscope's other
measured settings -- its calibration and its limits -- in a dated snapshot under
the ProgramData folder, written by the ``set_orientation`` notebook. Keeping it
there means a driver reinstall or update never loses it. Until the notebook has
run, the shipped ``orientation/defaults/orientation.json`` is a placeholder that
means "no turn," so an un-measured microscope is never turned by guesswork::

    {"schema_version": 1, "rotate_deg": 0, "_notes": "Placeholder, ..."}

The ``_notes`` text in the placeholder is not decoration: its presence is how
the calibration workflow can tell "never measured" from "measured as 0" and
warn the operator. A file the notebook adopts carries ``"measured": true``
instead (and no ``_notes``).

Author: Thom de Hoog (ZMB, University of Zurich).
License: MIT
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_VALID_ROTATIONS = (0, 90, 180, 270)

# How a clockwise turn of ``rotate_deg`` moves an image displacement (column,
# row): each entry is the 2x2 matrix that sends (+1 column, 0 rows) and
# (0 columns, +1 row) to their new places. A measured image->stage matrix, if
# the rig is turned by a whole quarter, is exactly one of these.
_STAGE_FROM_ROTATION: dict[int, tuple[tuple[int, int], tuple[int, int]]] = {
    0: ((1, 0), (0, 1)),
    90: ((0, -1), (1, 0)),
    180: ((-1, 0), (0, -1)),
    270: ((0, 1), (-1, 0)),
}


@dataclass(frozen=True)
class Orientation:
    """How far the camera is turned relative to the stage.

    ``rotate_deg`` is a clockwise quarter-turn: one of 0, 90, 180, or 270.
    ``is_identity`` means no turn at all (nothing to do). ``swaps_axes`` is true
    for 90 and 270, where the turn swaps the image's width and height.
    """

    rotate_deg: int = 0

    def __post_init__(self) -> None:
        if self.rotate_deg not in _VALID_ROTATIONS:
            raise ValueError(
                f"rotate_deg must be a whole quarter-turn -- one of "
                f"{_VALID_ROTATIONS}. An in-between angle means the camera is "
                f"physically misaligned, which is a rig problem to fix, not "
                f"something to rotate around. Got {self.rotate_deg!r}."
            )

    @property
    def is_identity(self) -> bool:
        return self.rotate_deg == 0

    @property
    def swaps_axes(self) -> bool:
        return self.rotate_deg in (90, 270)


def load_orientation(path: Any) -> Orientation:
    """Read an :class:`Orientation` from an ``orientation.json`` file."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Orientation(rotate_deg=int(data.get("rotate_deg", 0)))


def rig_orientation() -> Orientation:
    """The microscope's measured turn, read from its ProgramData snapshot.

    The ``set_orientation`` notebook measures the turn and writes an
    ``orientation.json`` into the microscope's newest snapshot, alongside its
    calibration and limits. The machine profile resolves that file, falling back
    to the shipped ``defaults/orientation.json`` -- a placeholder that means "no
    turn" -- when no snapshot has one yet. The real value is measured, never
    hard-coded, and an un-measured microscope is left exactly as it is.
    """
    from ..config.machine import MACHINE

    return load_orientation(MACHINE.orientation_path())


def orientation_from_image_to_stage(matrix) -> Orientation:
    """Turn a measured image-to-stage matrix into an :class:`Orientation`.

    The ``set_orientation`` measurement produces a small 2x2 matrix that
    describes how directions in the image map onto directions on the stage. This
    finds the matching quarter-turn. A mirrored result (its determinant is
    negative) is refused: a genuine camera turn is never a mirror image, so that
    points to a rig or measurement problem rather than something to paper over.
    """
    import numpy as np

    m = np.asarray(matrix, dtype=float)
    if m.shape != (2, 2):
        raise ValueError(f"image-to-stage matrix must be 2x2, got shape {m.shape}")
    if np.linalg.det(m) < 0:
        raise ValueError(
            f"image-to-stage matrix {matrix} is a mirror image (negative "
            f"determinant), not a plain turn -- check the rig and the "
            f"measurement rather than rotating the picture."
        )
    for deg, expected in _STAGE_FROM_ROTATION.items():
        if np.allclose(np.asarray(expected, dtype=float), m):
            return Orientation(rotate_deg=deg)
    raise ValueError(f"image-to-stage matrix {matrix} is not a whole quarter-turn")


def reorient_array(array, orientation: Orientation):
    """Turn a 2-D image by the orientation, without losing any detail.

    A whole quarter-turn only moves pixels to new positions (via ``np.rot90``),
    so nothing is blurred or resampled. Returns a new array; the original is
    left untouched.
    """
    import numpy as np

    k = orientation.rotate_deg // 90
    if k:
        array = np.rot90(array, k=-k)  # negative k turns clockwise
    return np.ascontiguousarray(array)

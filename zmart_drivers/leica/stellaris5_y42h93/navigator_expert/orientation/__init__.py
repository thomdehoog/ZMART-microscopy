"""Record and apply how the camera is oriented relative to the stage.

A camera or scanner is often mounted a quarter- or half-turn away from the
stage's own X and Y directions. When that happens, telling the stage to "move
right" shows up in the picture as a shift in some other direction, and the
software would end up chasing features the wrong way. This module records that
fixed D4 mapping -- measured once per microscope by the ``set_orientation``
notebook -- and corrects each saved image so that its left-right and up-down line
up with the stage's X and Y. After that, the rest of the software can treat image
and stage directions as the same thing, with no orientation maths anywhere.

The correction is one of the eight lossless D4 transforms: a whole quarter-turn
(0, 90, 180, or 270 degrees), optionally combined with a mirror. Some microscope
acquisition settings mirror the camera image deliberately, so a measured mirror
is recorded and corrected rather than treated as a broken rig. These transforms
only rearrange pixels; they never resample or blur the image.

This is a separate thing from pixel-size calibration and from the instrument limits,
and it lives entirely inside the driver. Workflows never deal with it: the images
they receive are already lined up with the stage.

The measured value is machine-specific, so it lives with the microscope's other
measured settings -- its calibration and its limits -- in a dated snapshot under
the ProgramData folder, written by the ``set_orientation`` notebook. Keeping it
there means a driver reinstall or update never loses it. Until the notebook has
run, the shipped ``orientation/defaults/orientation.json`` is a placeholder that
means "no turn," so an un-measured microscope is never turned by guesswork::

    {"schema_version": 2, "measured": false, "rotate_deg": 0,
     "mirrored": false, "reflection_axis": null, "axis_signs": {...},
     "image_to_stage": [...]}

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

SCHEMA_VERSION = 2
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

# A mirrored orientation is represented canonically as a left-right mirror of
# the raw image followed by the clockwise turn. Together with the four plain
# rotations this covers all eight D4 mappings without an ambiguous mirror axis.
_STAGE_FROM_ORIENTATION: dict[tuple[int, bool], tuple[tuple[int, int], tuple[int, int]]] = {
    **{(deg, False): matrix for deg, matrix in _STAGE_FROM_ROTATION.items()},
    (0, True): ((-1, 0), (0, 1)),
    (90, True): ((0, -1), (-1, 0)),
    (180, True): ((1, 0), (0, -1)),
    (270, True): ((0, 1), (1, 0)),
}


@dataclass(frozen=True)
class Orientation:
    """Lossless correction from the raw image axes to the stage axes.

    ``mirrored=True`` means mirror the raw image left-to-right first, then apply
    the clockwise ``rotate_deg`` quarter-turn. This fixed order gives every D4
    mapping one unique representation. ``axis_mapping`` and ``axis_signs`` are
    derived from the same authoritative matrix used to transform pixels.
    """

    rotate_deg: int = 0
    mirrored: bool = False

    def __post_init__(self) -> None:
        if self.rotate_deg not in _VALID_ROTATIONS:
            raise ValueError(
                f"rotate_deg must be a whole quarter-turn -- one of "
                f"{_VALID_ROTATIONS}. An in-between angle means the camera is "
                f"physically misaligned, which is a rig problem to fix, not "
                f"something to rotate around. Got {self.rotate_deg!r}."
            )
        if not isinstance(self.mirrored, bool):
            raise TypeError(f"mirrored must be bool, got {self.mirrored!r}")

    @property
    def is_identity(self) -> bool:
        return self.rotate_deg == 0 and not self.mirrored

    @property
    def swaps_axes(self) -> bool:
        return self.rotate_deg in (90, 270)

    @property
    def image_to_stage(self) -> tuple[tuple[int, int], tuple[int, int]]:
        return _STAGE_FROM_ORIENTATION[(self.rotate_deg, self.mirrored)]

    @property
    def axis_mapping(self) -> dict[str, str]:
        """Signed raw-image axis used for each positive stage axis."""
        rows = self.image_to_stage
        return {
            "stage_x_from_image": _signed_axis(rows[0]),
            "stage_y_from_image": _signed_axis(rows[1]),
        }

    @property
    def axis_signs(self) -> dict[str, int]:
        """Polarity of the image axis selected for each stage axis."""
        return {
            "stage_x": _axis_sign(self.image_to_stage[0]),
            "stage_y": _axis_sign(self.image_to_stage[1]),
        }

    @property
    def reflection_axis(self) -> str | None:
        """Net reflection axis after applying the canonical correction."""
        if not self.mirrored:
            return None
        return {
            0: "vertical",
            90: "anti_diagonal",
            180: "horizontal",
            270: "main_diagonal",
        }[self.rotate_deg]


def _axis_sign(row: tuple[int, int]) -> int:
    return next(value for value in row if value)


def _signed_axis(row: tuple[int, int]) -> str:
    index = next(index for index, value in enumerate(row) if value)
    sign = "+" if row[index] > 0 else "-"
    return f"{sign}{('X', 'Y')[index]}"


def orientation_config(orientation: Orientation, *, measured: bool = True) -> dict[str, Any]:
    """Build the complete, internally consistent orientation document."""
    return {
        "schema_version": SCHEMA_VERSION,
        "measured": bool(measured),
        "rotate_deg": int(orientation.rotate_deg),
        "mirrored": orientation.mirrored,
        "reflection_axis": orientation.reflection_axis,
        "axis_signs": orientation.axis_signs,
        "axis_mapping": orientation.axis_mapping,
        "image_to_stage": [list(row) for row in orientation.image_to_stage],
    }


def orientation_from_config(data: dict[str, Any]) -> Orientation:
    """Validate and decode either a current or legacy orientation document."""
    schema_version = int(data.get("schema_version", 1))
    if schema_version >= SCHEMA_VERSION:
        required = {
            "rotate_deg",
            "mirrored",
            "axis_signs",
            "axis_mapping",
            "image_to_stage",
        }
        missing = sorted(required.difference(data))
        if missing:
            raise ValueError(f"orientation schema {schema_version} missing fields: {missing}")
        orientation = orientation_from_image_to_stage(data["image_to_stage"])
        expected = orientation_config(orientation, measured=data.get("measured") is True)
        for key in required:
            if data[key] != expected[key]:
                raise ValueError(
                    f"orientation field {key!r} contradicts image_to_stage: "
                    f"got {data[key]!r}, expected {expected[key]!r}"
                )
        if "reflection_axis" in data and data["reflection_axis"] != expected["reflection_axis"]:
            raise ValueError(
                "orientation field 'reflection_axis' contradicts image_to_stage: "
                f"got {data['reflection_axis']!r}, "
                f"expected {expected['reflection_axis']!r}"
            )
        return orientation

    return Orientation(
        rotate_deg=int(data.get("rotate_deg", 0)),
        mirrored=data.get("mirrored") is True,
    )


def load_orientation(path: Any) -> Orientation:
    """Read an :class:`Orientation` from an ``orientation.json`` file."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return orientation_from_config(data)


def rig_orientation() -> Orientation:
    """The microscope's measured D4 mapping, read from its ProgramData snapshot.

    The ``set_orientation`` notebook measures the mapping and writes an
    ``orientation.json`` into ``orientation/<datetime>/``. The machine profile
    resolves the newest orientation timestamp, falling back
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
    finds the matching lossless quarter-turn and mirror combination.
    """
    import numpy as np

    m = np.asarray(matrix, dtype=float)
    if m.shape != (2, 2):
        raise ValueError(f"image-to-stage matrix must be 2x2, got shape {m.shape}")
    for (deg, mirrored), expected in _STAGE_FROM_ORIENTATION.items():
        if np.allclose(np.asarray(expected, dtype=float), m):
            return Orientation(rotate_deg=deg, mirrored=mirrored)
    raise ValueError(f"image-to-stage matrix {matrix} is not a D4 orientation")


def reorient_array(array, orientation: Orientation):
    """Apply a D4 orientation to a 2-D image without losing any detail.

    A mirrored correction flips left-to-right first; the clockwise quarter-turn
    follows. Both operations only rearrange pixels. Returns a new array and
    leaves the original untouched.
    """
    import numpy as np

    if orientation.mirrored:
        array = np.fliplr(array)
    k = orientation.rotate_deg // 90
    if k:
        array = np.rot90(array, k=-k)  # negative k turns clockwise
    return np.ascontiguousarray(array)

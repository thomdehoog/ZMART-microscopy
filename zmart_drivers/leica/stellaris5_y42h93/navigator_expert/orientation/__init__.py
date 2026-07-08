"""Rig image->stage orientation, applied to exported planes at save time.

The image->stage relation on a well-built rig is a **D4 element** -- a
90-degree-increment rotation plus an optional mirror (the ``set_orientation``
setup notebook measures it: acquire home/+X/+Y, register, fit the 2x2 Jacobian,
snap to the nearest D4 and accept only a small residual; a non-D4 skew is a
physical alignment problem, never interpolated away). Because it is pure D4, the
driver aligns the saved image to the stage by **rotating the exported raster
losslessly** (``np.rot90`` / ``np.flip`` -- no resampling) as it persists each
plane. Downstream then treats image axes as stage axes with no rotation math.

This is a *separate concern* from pixel-scale calibration and from limits, and
it lives entirely inside the driver: workflows never see it -- ``acquire``
returns already-stage-aligned images.

Config (mirrors ``limits/``): the measured machine value in
``orientation/current.json`` if present, else the shipped identity template
``orientation/defaults/orientation.json``:

    {"schema_version": 1, "rotate_deg": <0|90|180|270>, "mirror": <bool>}

The value is **measured** by the ``set_orientation`` notebook, never hard-coded.
``rotate_deg`` is a clockwise 90-degree increment; ``mirror`` applies a
horizontal flip first (a reflection-type D4). Identity is a no-op. A quarter-turn
swaps the axes (a transpose) and cannot be expressed by sign flips alone --
hence a rotation, not two signs.

Author: Thom de Hoog (ZMB, University of Zurich).
License: MIT
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_CURRENT = _HERE / "current.json"
_DEFAULT = _HERE / "defaults" / "orientation.json"
_VALID_ROTATIONS = (0, 90, 180, 270)


@dataclass(frozen=True)
class Orientation:
    """A D4 image->stage orientation applied to exported planes.

    ``rotate_deg`` is a clockwise rotation in {0, 90, 180, 270}; ``mirror``
    applies a horizontal flip (``fliplr``) before the rotation. Together they
    span all eight D4 elements. ``is_identity`` is the 0/no-mirror no-op;
    ``swaps_axes`` is True for 90/270 (the transpose cases).
    """

    rotate_deg: int = 0
    mirror: bool = False

    def __post_init__(self) -> None:
        if self.rotate_deg not in _VALID_ROTATIONS:
            raise ValueError(
                f"rotate_deg must be one of {_VALID_ROTATIONS} (a 90-degree "
                f"increment -- a non-D4 skew is a rig-alignment problem, not "
                f"something to resample); got {self.rotate_deg!r}"
            )

    @property
    def is_identity(self) -> bool:
        return self.rotate_deg == 0 and not self.mirror

    @property
    def swaps_axes(self) -> bool:
        return self.rotate_deg in (90, 270)


def load_orientation(path: Any) -> Orientation:
    """Load an :class:`Orientation` from an ``orientation.json`` file."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Orientation(
        rotate_deg=int(data.get("rotate_deg", 0)), mirror=bool(data.get("mirror", False))
    )


def rig_orientation() -> Orientation:
    """The machine's orientation: ``current.json`` if adopted, else the default.

    The ``set_orientation`` notebook measures the rig's D4 and writes it to
    ``current.json``; the shipped ``defaults/orientation.json`` is an identity
    template (no value asserted -- the orientation is discovered, not hard-coded).
    Until the notebook has run, this returns identity -- fail safe (never rotate
    an unmeasured rig).
    """
    for candidate in (_CURRENT, _DEFAULT):
        if candidate.is_file():
            return load_orientation(candidate)
    return Orientation()


def _displacement_transform(orientation: Orientation):
    """The 2x2 map ``reorient_array`` applies to an image displacement (dcol, drow).

    Derived by probing :func:`reorient_array` on unit offsets so it always
    matches the actual raster op (no CW/CCW hand-reasoning). Columns are the
    images of ``(+1, 0)`` and ``(0, +1)``.
    """
    import numpy as np

    def _offset(a):
        r, c = np.argwhere(a == 1)[0]
        h, w = a.shape
        return np.array([c - (w - 1) / 2.0, r - (h - 1) / 2.0])  # (dcol, drow)

    east = np.zeros((3, 3), int)
    east[1, 2] = 1  # offset (dcol=+1, drow=0)
    south = np.zeros((3, 3), int)
    south[2, 1] = 1  # offset (dcol=0, drow=+1)
    col_e = _offset(reorient_array(east, orientation))
    col_s = _offset(reorient_array(south, orientation))
    return np.column_stack([col_e, col_s])


def orientation_from_image_to_stage(matrix) -> Orientation:
    """Convert a measured ``image_to_stage`` D4 matrix to an :class:`Orientation`.

    The ``image_to_stage`` matrix M maps an image-frame displacement to the
    stage frame (``stage = M @ image``). Reorienting the raster so its axes
    match the stage is exactly applying M to the pixel grid, so we return the
    D4 rotation whose raster displacement-transform equals M. Reflections
    (``det < 0``) raise -- a proper rig is a pure rotation.
    """
    import numpy as np

    m = np.asarray(matrix, dtype=float)
    if m.shape != (2, 2):
        raise ValueError(f"image_to_stage must be 2x2, got shape {m.shape}")
    if np.linalg.det(m) < 0:
        raise ValueError(
            f"image_to_stage {matrix} is a reflection (det<0), not a proper "
            f"rotation -- check the rig / registration, do not resample"
        )
    for deg in _VALID_ROTATIONS:
        o = Orientation(rotate_deg=deg)
        if np.allclose(_displacement_transform(o), m):
            return o
    raise ValueError(f"image_to_stage {matrix} is not a D4 rotation")


def reorient_array(array, orientation: Orientation):
    """Apply the D4 orientation to a 2-D array, losslessly. Returns a new array.

    Mirror (``fliplr``) first, then a clockwise rotation by ``rotate_deg``.
    ``np.rot90``'s positive k is counter-clockwise, so clockwise uses ``-k``.
    """
    import numpy as np

    out = array
    if orientation.mirror:
        out = np.fliplr(out)
    k = (orientation.rotate_deg // 90) % 4
    if k:
        out = np.rot90(out, k=-k)  # clockwise
    return np.ascontiguousarray(out)

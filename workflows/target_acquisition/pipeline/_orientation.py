"""Post-export image orientation: rotate the saved plane to stage-aligned axes.

The image-to-stage relation on a well-built rig is always a **D4 element** -- a
90-degree-increment rotation plus an optional mirror (the calibration snaps the
measured Jacobian to the nearest D4 and only accepts it when the residual is
small; a non-D4 skew is a physical alignment problem, never interpolated away).
Because it is a pure D4, we can make the image axes match the stage axes by
**rotating the exported raster losslessly** (``np.rot90`` / ``np.flip`` -- no
resampling, no blurred edges), instead of carrying a rotation matrix through
every pixel->stage conversion. Once the saved plane is stage-aligned,
:func:`pipeline._geom.overview_pixel_to_frame` is a pure scale, exactly as it
already assumes.

Sign flips alone (mirror-X / mirror-Y / 180) can only express the orientations
where the axes do **not** swap. A 90/270 rotation swaps the axes (a transpose),
so it cannot be captured by signs -- hence this is a *rotation*, stored as
degrees, not two axis signs. Leica's rig is 90 degrees.

The orientation is a fixed, one-time-measured property of the rig, kept in a
standalone ``orientation.json`` (beside the machine's limits / calibration
config):

    {"schema_version": 1, "rotate_deg": 90, "mirror": false}

``rotate_deg`` is the clockwise rotation applied to the exported image (one of
0/90/180/270); ``mirror`` applies a horizontal flip first (for a
reflection-type D4). Identity (0, no mirror) is a no-op.
"""

from __future__ import annotations

import os
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_OME_NS = "http://www.openmicroscopy.org/Schemas/OME/2016-06"
_VALID_ROTATIONS = (0, 90, 180, 270)


@dataclass(frozen=True)
class Orientation:
    """A D4 image->stage orientation to apply to exported planes.

    ``rotate_deg`` is a clockwise rotation in {0, 90, 180, 270}; ``mirror``
    applies a horizontal flip (``fliplr``) before the rotation. Together they
    span all eight D4 elements. ``is_identity`` is the 0/no-mirror no-op.
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
        """True when the rotation swaps H<->W (90 or 270)."""
        return self.rotate_deg in (90, 270)


def load_orientation(path: Any) -> Orientation:
    """Load an :class:`Orientation` from an ``orientation.json`` file."""
    import json

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Orientation(
        rotate_deg=int(data.get("rotate_deg", 0)), mirror=bool(data.get("mirror", False))
    )


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


def _swap_pixel_dims(desc: str) -> str:
    """Swap SizeX<->SizeY and PhysicalSizeX<->PhysicalSizeY (+units) in the OME
    ``<Pixels>`` of a tag-270 description, preserving everything else.

    Used for 90/270 rotations, which transpose the pixel grid. Returns the
    re-serialized OME-XML. Raises ``ValueError`` if there is no ``<Pixels>``.
    """
    ET.register_namespace("", _OME_NS)
    root = ET.fromstring(desc)
    pixels = root.find(".//{*}Pixels")
    if pixels is None:
        raise ValueError("no OME <Pixels> element to reorient")
    a = pixels.attrib
    for x_key, y_key in (
        ("SizeX", "SizeY"),
        ("PhysicalSizeX", "PhysicalSizeY"),
        ("PhysicalSizeXUnit", "PhysicalSizeYUnit"),
    ):
        x_val, y_val = a.get(x_key), a.get(y_key)
        if x_val is not None or y_val is not None:
            if y_val is not None:
                a[x_key] = y_val
            elif x_key in a:
                del a[x_key]
            if x_val is not None:
                a[y_key] = x_val
            elif y_key in a:
                del a[y_key]
    xml = ET.tostring(root, encoding="unicode")
    # Preserve the XML declaration the writer emitted (tifffile is happy either
    # way, but the driver's other planes carry one -- keep it uniform).
    if desc.lstrip().startswith("<?xml") and not xml.lstrip().startswith("<?xml"):
        xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml
    return xml


def apply_orientation(records: list[dict], orientation: Orientation) -> int:
    """Rotate every saved plane in ``records`` to stage-aligned axes, in place.

    ``records`` is the list ``run_overview`` / ``acquire_targets`` returns (each
    with ``"images"`` paths). For each plane: read the array + its OME-XML,
    apply the lossless D4 reorientation, swap the OME pixel dims for a 90/270,
    and atomically write the file back (``ome=False`` so the description is
    written verbatim -- the rest of the OME, including the embedded machine
    state, is preserved). A no-op orientation (identity) touches nothing.

    Returns the number of planes rewritten. Call this **after** ``acquire`` and
    **before** discovery, so the segmenter and ``overview_pixel_to_frame`` see
    stage-aligned pixels.
    """
    if orientation.is_identity:
        return 0

    import tifffile

    count = 0
    for record in records:
        for image_path in record.get("images", []):
            image_path = Path(image_path)
            arr = tifffile.imread(image_path)
            if arr.ndim != 2:
                raise RuntimeError(
                    f"orientation supports single-plane frames only; "
                    f"{image_path.name} has shape {arr.shape}"
                )
            with tifffile.TiffFile(image_path) as tif:
                desc = tif.pages[0].description
            new_arr = reorient_array(arr, orientation)
            new_desc = _swap_pixel_dims(desc) if orientation.swaps_axes else desc

            parent = image_path.parent
            tmp_fd, tmp_name = tempfile.mkstemp(
                suffix=".tmp", prefix=image_path.name + ".", dir=str(parent)
            )
            os.close(tmp_fd)
            tmp_path = Path(tmp_name)
            try:
                tifffile.imwrite(
                    tmp_path, new_arr, description=new_desc, ome=False, photometric="minisblack"
                )
                os.replace(tmp_path, image_path)
                tmp_path = None
            finally:
                if tmp_path is not None:
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
            count += 1
    return count

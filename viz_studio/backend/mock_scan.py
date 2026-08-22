"""A pretend microscope export, so the whole path can be built before there is a microscope.

Everything downstream of this is the real thing: the same filenames, the same
flat one-plane-per-file arrangement, the same OME description carrying the size
of a pixel and saying nothing about where the field was taken. Only the source
of the pixels is invented.

That is the point. If the picture works against this, then wiring a microscope
in means replacing this one file with the real export and changing nothing
else — and, just as importantly, the awkward parts can be found now rather than
on a machine with an operator waiting.

The awkward part being looked for here is scale. A scan of ten thousand fields
is the size this has to survive, and it is not a size anybody can conjure by
hand.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

#: What the driver calls this kind of run, in the exported filenames.
AN_OVERVIEW = "overview"

#: Six characters standing in for the run's own hash.
A_RUN = "mock01"


def export_a_mock_scan(
    into: Path | str,
    *,
    across: int = 4,
    down: int = 4,
    pixels: int = 128,
    um_per_pixel: float = 0.5,
    channels: int = 1,
    overlap: float = 0.0,
    seed: int = 0,
) -> dict[str, tuple[float, float]]:
    """Write a grid of fields the way a microscope would, and say where each is.

    Returns the same thing a run knows and a file does not: where the middle of
    every field is, in micrometres. That pairing — files that do not state
    their place, and a caller that does — is the arrangement being rehearsed,
    because it is the one that will be there on the day.

    ``overlap`` is the fraction of a field that its neighbour repeats, since a
    real scan usually overlaps a little and drawing overlapping fields is a
    thing a picture has to get right.
    """
    import numpy as np
    import tifffile

    into = Path(into)
    into.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)

    field_um = pixels * um_per_pixel
    step_um = field_um * (1.0 - float(overlap))
    described = (
        '<OME xmlns="http://www.openmicroscopy.org/Schemas/OME/2016-06">'
        f'<Image><Pixels DimensionOrder="XYCZT" Type="uint16" SizeX="{pixels}" '
        f'SizeY="{pixels}" SizeC="1" SizeZ="1" SizeT="1" '
        f'PhysicalSizeX="{um_per_pixel}" PhysicalSizeY="{um_per_pixel}"/></Image></OME>'
    )

    places: dict[str, tuple[float, float]] = {}
    number = 0
    for row in range(down):
        for column in range(across):
            number += 1
            label = f"P{number:04d}"
            places[label] = (column * step_um, row * step_um)
            for channel in range(channels):
                frame = _a_field_of_cells(rng, pixels)
                name = (
                    f"{AN_OVERVIEW}_{A_RUN}_{label}"
                    f"_T{0:06d}_C{channel:02d}_Z{0:05d}.ome.tiff"
                )
                tifffile.imwrite(into / name, frame, description=described)
    return places


def _a_field_of_cells(rng: Any, pixels: int) -> Any:
    """Something that looks enough like a field to tell one from another.

    Bright blobs on a dim ground. It is not pretending to be microscopy — it
    exists so that a picture drawn from it can be recognised as the right field
    in the right place, and so that a JPEG of it compresses about as badly as a
    real one does. A flat grey field would compress to nothing and make the
    size measurements a lie.
    """
    import numpy as np

    ground = (rng.random((pixels, pixels)) * 400 + 200).astype(np.float32)
    rows, columns = np.mgrid[0:pixels, 0:pixels]
    for _ in range(max(3, pixels // 16)):
        centre_row = rng.integers(0, pixels)
        centre_column = rng.integers(0, pixels)
        radius = rng.integers(max(2, pixels // 40), max(3, pixels // 12))
        blob = np.exp(
            -(((rows - centre_row) ** 2 + (columns - centre_column) ** 2) / (2.0 * radius**2))
        )
        ground += blob * rng.uniform(4000, 20000)
    return np.clip(ground, 0, 65535).astype(np.uint16)

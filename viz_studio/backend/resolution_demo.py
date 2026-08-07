"""A small volume built to make the pyramid visible.

The point of a multi-resolution viewer is that it draws coarse data when you are
far away and fine data when you are close. On a real acquisition that is
surprisingly hard to *see*: lightsheet voxels are ten times taller than they are
wide, so everything looks blocky at every level, and the data lives on a share,
so refinement arrives whenever the network feels like it.

This volume removes both confounds. Voxels are cubic, it is small enough to sit
on local disk and load instantly, and it contains a resolution target: bars 1,
2, 4, 8 and 16 voxels wide. The narrow bars survive only at full resolution --
each halving of the pyramid merges the finest surviving pair into a solid block.
So the level being drawn is legible directly from the picture:

    all four bar groups distinct   -> level 0
    finest group merged            -> level 1
    two finest merged              -> level 2, and so on

A hollow sphere is included so the 3-D view has something recognisably
volumetric to rotate, rather than only flat gratings.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np

_DEPTH = 128
_HEIGHT = 256
_WIDTH = 256
_VOXEL_UM = (1.0, 1.0, 1.0)  # cubic on purpose: no anisotropy to blame

_BACKGROUND = 100
_SIGNAL = 12000

# Bar widths in voxels. A width-w group survives downsampling by a factor f only
# while w >= 2f, so these four groups drop out one level at a time.
_BAR_WIDTHS = (1, 2, 4, 8)
_PYRAMID_LEVELS = 4


def _add_bar_groups(volume: np.ndarray) -> None:
    """Lay one grating per band, each with a different bar width."""
    band_height = _HEIGHT // (len(_BAR_WIDTHS) + 1)
    for index, width in enumerate(_BAR_WIDTHS):
        y0 = band_height * index + band_height // 4
        y1 = y0 + band_height // 2
        columns = np.arange(_WIDTH)
        on = (columns // width) % 2 == 0
        volume[:, y0:y1, :][:, :, on] = _SIGNAL


def _add_sphere_shell(volume: np.ndarray) -> None:
    """A hollow shell, so there is real 3-D structure to rotate around."""
    zz, yy, xx = np.ogrid[0:_DEPTH, 0:_HEIGHT, 0:_WIDTH]
    radius = np.sqrt(
        ((zz - _DEPTH / 2) * 1.0) ** 2
        + ((yy - _HEIGHT * 0.78)) ** 2
        + ((xx - _WIDTH / 2)) ** 2
    )
    shell = (radius > 38) & (radius < 42)
    volume[shell] = _SIGNAL


def _build() -> np.ndarray:
    volume = np.full((_DEPTH, _HEIGHT, _WIDTH), _BACKGROUND, dtype=np.uint16)
    _add_bar_groups(volume)
    _add_sphere_shell(volume)
    return volume


def _downsample(volume: np.ndarray) -> np.ndarray:
    z, y, x = volume.shape
    z2, y2, x2 = z // 2, y // 2, x // 2
    trimmed = volume[: z2 * 2, : y2 * 2, : x2 * 2].astype(np.float32)
    return trimmed.reshape(z2, 2, y2, 2, x2, 2).mean(axis=(1, 3, 5)).astype(np.uint16)


def _multiscales(n_levels: int) -> dict:
    datasets = []
    for level in range(n_levels):
        factor = 2**level
        datasets.append(
            {
                "path": str(level),
                "coordinateTransformations": [
                    {"type": "scale", "scale": [v * factor for v in _VOXEL_UM]}
                ],
            }
        )
    return {
        "version": "0.4",
        "axes": [{"name": n, "type": "space", "unit": "micrometer"} for n in "zyx"],
        "datasets": datasets,
        "name": "resolution-target",
    }


def write_resolution_target(path: str | Path) -> Path:
    """Write the resolution-target volume as an OME-Zarr store at ``path``."""
    import zarr

    path = Path(path)
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)

    levels = [_build()]
    for _ in range(_PYRAMID_LEVELS):
        smaller = _downsample(levels[-1])
        if min(smaller.shape) < 8:
            break
        levels.append(smaller)

    group = zarr.open_group(str(path), mode="w", zarr_format=2)
    for index, volume in enumerate(levels):
        z, y, x = volume.shape
        array = group.create_array(
            str(index), shape=volume.shape, chunks=(min(z, 64), min(y, 128), min(x, 128)),
            dtype="uint16",
        )
        array[:] = volume

    (path / ".zattrs").write_text(
        json.dumps({"multiscales": [_multiscales(len(levels))]}, indent=1), encoding="utf-8"
    )
    return path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="where to write the .zarr store")
    args = parser.parse_args()
    out = write_resolution_target(args.path)
    print(f"wrote the resolution target to {out}")

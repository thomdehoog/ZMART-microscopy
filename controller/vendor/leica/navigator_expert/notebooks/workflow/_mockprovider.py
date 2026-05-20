"""Mock image providers for simulation mode (Plan 2 §4b).

Each provider, given a target shape and dtype plus the tile's
canonical Naming, returns a 2-D image of *exactly* that shape and
dtype, deterministic from (Naming.g, Naming.p). The returned array
becomes the pixel content of the canonical .ome.tiff in simulation
mode -- see workflow/_hijack.py for the OME-preserving overwrite.

The provider must never raise on a sensible (shape, dtype, naming);
shape/dtype mismatches are caught by the hijack and recorded as a
per-tile hijack failure, not a run-fatal error.
"""
from __future__ import annotations

from typing import Callable

import numpy as np


def get_provider(name: str) -> Callable:
    """Look up a mock provider by name. Raises ValueError on unknown."""
    if name == "skimage_human_mitosis":
        return _skimage_human_mitosis
    raise ValueError(
        f"Unknown mock_image_source: {name!r}. "
        f"Known providers: skimage_human_mitosis."
    )


def _skimage_human_mitosis(
    shape: tuple, dtype, *, naming,
) -> np.ndarray:
    """Tile skimage's human_mitosis() image by (g, p), cropped to
    `shape` and cast to `dtype`. Deterministic from (naming.g, naming.p).
    """
    # Lazy: skimage import is heavy and only needed when the provider
    # is actually selected.
    from skimage.data import human_mitosis

    src = human_mitosis()                    # uint8, typically 512x512
    sh, sw = src.shape
    th, tw = shape[:2]
    g, p = int(naming.g), int(naming.p)

    # Deterministic per-(g, p) origin within the source, modulo the
    # available slack. The exact stride does not matter -- the goal is
    # only "different tiles get different content".
    y0 = ((g * 41 + p * 17) * th) % max(1, sh - th + 1) if sh > th else 0
    x0 = ((g * 73 + p * 29) * tw) % max(1, sw - tw + 1) if sw > tw else 0
    tile = src[y0:y0 + th, x0:x0 + tw]

    # If the source is smaller than the target in either dim, repeat.
    if tile.shape[0] < th or tile.shape[1] < tw:
        ry = -(-th // max(1, tile.shape[0]))
        rx = -(-tw // max(1, tile.shape[1]))
        tile = np.tile(tile, (ry, rx))[:th, :tw]

    # Cast to the target dtype. For unsigned-int targets wider than 8
    # bits, scale 0..255 → 0..max so the image uses the dynamic range.
    if np.issubdtype(dtype, np.unsignedinteger):
        info = np.iinfo(dtype)
        scaled = tile.astype(np.float64) * (info.max / 255.0)
        return scaled.astype(dtype)
    return tile.astype(dtype)

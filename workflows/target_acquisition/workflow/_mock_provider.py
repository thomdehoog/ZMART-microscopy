"""Mock image content for simulation mode.

When the workflow runs against the LAS X simulator, the saved overview files
need believable pixels so the analysis afterwards has something real to work
on. A *provider* invents that content: given the shape and dtype of a saved
image plus its :class:`Naming`, it returns an array of mock pixels that
:func:`~workflow._hijack.hijack_records` writes over the saved file.

The one provider here, ``skimage_human_mitosis``, tiles a stock microscopy
image (skimage's ``human_mitosis``) so each overview tile gets distinct but
reproducible content -- distinct because that is what a real overview looks
like, reproducible so a re-run of the same simulation produces the same map. A
provider must never raise on a sensible ``(shape, dtype, naming)``; a
shape/dtype mismatch is caught by the hijack and recorded as a per-tile
failure, not raised here.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import numpy as np

_POSITION_LABEL_RE = re.compile(
    r"K\d{2}_M\d{6}_G(?P<group>\d{6})_P(?P<position>\d{6})_V\d{2}"
)
# Retired form retained so old simulation fixtures remain readable.
_POSITION_LABEL_GP_RE = re.compile(r"g(\d+)-p(\d+)")


def _region_position_from_naming(naming) -> tuple[int, int]:
    """Recover (region_id, position) ints from a canonical
    ``gNNNNN-pNNNNN`` position_label. Falls back to a deterministic
    (0, hash-derived) pair for any non-matching label so the mock content
    generator stays total (never raises on a well-formed Naming)."""
    m = _POSITION_LABEL_RE.fullmatch(naming.position_label)
    if m:
        return int(m.group("group")), int(m.group("position"))
    m = _POSITION_LABEL_GP_RE.fullmatch(naming.position_label)
    if m:
        return int(m.group(1)), int(m.group(2))
    return 0, abs(hash(naming.position_label)) % 10_000


def get_provider(name: str) -> Callable:
    """Look up an overview mock provider by name. Raises ValueError on unknown."""
    if name == "skimage_human_mitosis":
        return _skimage_human_mitosis
    raise ValueError(
        f"Unknown mock_image_source: {name!r}. Known providers: skimage_human_mitosis."
    )


def _skimage_human_mitosis(
    shape: tuple,
    dtype,
    *,
    naming,
) -> np.ndarray:
    """Provider entry point matching the ``(shape, dtype, *, naming)``
    contract. Recovers the (region id, position) ints from
    ``naming.position_label`` and defers to the pure content generator.
    """
    region_id, position = _region_position_from_naming(naming)
    return _human_mitosis_tile(shape, dtype, region_id=region_id, position=position)


def _human_mitosis_tile(
    shape: tuple,
    dtype,
    *,
    region_id: int,
    position: int,
) -> np.ndarray:
    """Tile skimage's human_mitosis() image by (region_id, position),
    cropped to `shape` and cast to `dtype`. Deterministic from the two
    ints passed in directly (no longer read off Naming slots).
    """
    # Lazy: skimage import is heavy and only needed when the provider
    # is actually selected.
    from skimage.data import human_mitosis

    src = human_mitosis()  # uint8, typically 512x512
    sh, sw = src.shape
    th, tw = shape[:2]
    g, p = int(region_id), int(position)

    # Deterministic per-(g, p) origin within the source, modulo the
    # available slack. The exact stride does not matter -- the goal is
    # only "different tiles get different content".
    y0 = ((g * 41 + p * 17) * th) % max(1, sh - th + 1) if sh > th else 0
    x0 = ((g * 73 + p * 29) * tw) % max(1, sw - tw + 1) if sw > tw else 0
    tile = src[y0 : y0 + th, x0 : x0 + tw]

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

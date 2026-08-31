"""A detection mask as a picture a browser can lay over the field.

The pipeline checkpoints each field's label mask as ``masks.tif`` beside the
run (``<type>/analysis/tiles/<frame>/masks.tif``) -- int32 labels, honest and
unviewable. This turns one into a translucent PNG: background transparent,
each object in its own colour, cached beside the mask it was made from.

Imports its rasters lazily, so the bridge still loads on a machine with
nothing installed and only this feature asks for more.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

from pathlib import Path


def mask_view_of(record: dict, label: str) -> Path | None:
    """The colorized mask PNG for *record*'s field, made if it is not yet.

    ``None`` when the field has no checkpointed mask -- detection simply has
    not run there -- or when the record carries no planes to locate it by.
    The PNG is cached as ``masks_view.png`` beside ``masks.tif`` and remade
    whenever the mask is newer (a re-test overwrites the checkpoint).
    """
    planes = record.get("planes") or []
    if not planes:
        return None
    tiles = Path(planes[0]["path"]).parent.parent / "analysis" / "tiles"
    if not tiles.is_dir():
        return None
    masks = [p for p in tiles.glob("*/masks.tif") if label in p.parent.name]
    if not masks:
        return None
    mask = masks[0]
    view = mask.with_name("masks_view.png")
    if view.is_file() and view.stat().st_mtime >= mask.stat().st_mtime:
        return view

    import numpy as np
    import tifffile
    from PIL import Image

    labels = tifffile.imread(mask)
    height, width = labels.shape
    out = np.zeros((height, width, 4), dtype=np.uint8)
    found = labels > 0
    if found.any():
        # The page's own object palette -- golden-angle hues at 68%
        # saturation, 58% lightness, the same law as labelColour() in the
        # test box -- so the masks and every ring drawn beside them speak
        # one set of colours. Full-saturation primaries read as confetti
        # over grey tissue; these read as marks made by the same hand.
        hue = (labels.astype(np.float64) * 137.508) % 360.0
        chroma = (1.0 - abs(2.0 * 0.58 - 1.0)) * 0.68
        ramp = chroma * (1.0 - np.abs((hue / 60.0) % 2.0 - 1.0))
        lift = 0.58 - chroma / 2.0
        zero = np.zeros_like(ramp)
        full = np.full_like(ramp, chroma)
        section = (hue // 60).astype(np.int64) % 6
        r = ((np.choose(section, [full, ramp, zero, zero, ramp, full]) + lift) * 255).astype(np.uint8)
        g = ((np.choose(section, [ramp, full, full, ramp, zero, zero]) + lift) * 255).astype(np.uint8)
        b = ((np.choose(section, [zero, zero, ramp, full, full, ramp]) + lift) * 255).astype(np.uint8)
        out[..., 0] = np.where(found, r, 0)
        out[..., 1] = np.where(found, g, 0)
        out[..., 2] = np.where(found, b, 0)
        out[..., 3] = np.where(found, 255, 0)
    Image.fromarray(out, "RGBA").save(view)
    return view


def label_map_of(record: dict, label: str):
    """The field's raw label mask as a lossless PNG the page can read back.

    Each pixel's mask label rides in the colour -- R the low byte, G the
    next, B the next, opaque wherever an object is -- so a page that reads
    the pixels back holds the exact segmentation, and can light any one
    object's true shape. Cached beside ``masks.tif`` like the view.
    """
    planes = record.get("planes") or []
    if not planes:
        return None
    tiles = Path(planes[0]["path"]).parent.parent / "analysis" / "tiles"
    if not tiles.is_dir():
        return None
    masks = [p for p in tiles.glob("*/masks.tif") if label in p.parent.name]
    if not masks:
        return None
    mask = masks[0]
    out = mask.with_name("masks_labels.png")
    if out.is_file() and out.stat().st_mtime >= mask.stat().st_mtime:
        return out

    import numpy as np
    import tifffile
    from PIL import Image

    labels = tifffile.imread(mask).astype(np.int64)
    height, width = labels.shape
    png = np.zeros((height, width, 4), dtype=np.uint8)
    png[..., 0] = labels & 255
    png[..., 1] = (labels >> 8) & 255
    png[..., 2] = (labels >> 16) & 255
    png[..., 3] = np.where(labels > 0, 255, 0)
    Image.fromarray(png, "RGBA").save(out)
    return out

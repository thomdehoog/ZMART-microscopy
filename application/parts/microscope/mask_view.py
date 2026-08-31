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
        # Each object its own colour, spread around the wheel by a stride
        # coprime to it, so neighbouring labels never share a hue.
        hue = (labels.astype(np.int64) * 47) % 360
        section = (hue // 60) % 6
        ramp = ((hue % 60) * 255 // 60).astype(np.uint8)
        r = np.choose(section, [255, 255 - ramp, 0, 0, ramp, 255])
        g = np.choose(section, [ramp, 255, 255, 255 - ramp, 0, 0])
        b = np.choose(section, [0, 0, ramp, 255, 255, 255 - ramp])
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

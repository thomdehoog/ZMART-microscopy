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

"""Shared geometry for mapping between overview pixels and stage positions.

These helpers are pure math on plain numbers and arrays -- no domain objects --
so every part of the workflow (the crop panels, the visualization rectangles,
the pixel-to-stage conversion) computes the *same* window from the same inputs.
They share one home because independent copies of this math drifted apart in
the past and showed operators two different windows for the same cell.

A note on pixel sizes: the workflow treats pixel size as one scalar (square
pixels, the same size on both axes). Non-square *images* are handled fine --
height and width are derived independently -- but non-square *pixels* are out
of scope.
"""

from __future__ import annotations

import math

import numpy as np


def target_fov_window_in_overview(
    *,
    centroid_col_row_px: tuple[float, float],
    source_pixel_size_um: float,
    target_shape_px: tuple[int, int],
    target_pixel_size_um: float,
) -> tuple[int, int, int, int]:
    """Find where the target job's field of view sits inside the overview image.

    Given a cell centroid in overview pixels, this returns ``(x0, y0, w, h)``:
    the window of overview pixels that covers the same physical area the target
    job will image, centred on the cell. The window may extend past the
    overview's edges when the cell sits near a tile border (``x0``/``y0`` can be
    negative, ``x0 + w`` / ``y0 + h`` can exceed the image size) -- the caller
    decides how to handle that: the crop helper below pads the missing area,
    and the visualization draws the rectangle as-is and lets the axes clip it.
    Width and height are always at least one pixel.
    """
    H_tg, W_tg = int(target_shape_px[0]), int(target_shape_px[1])
    px_ov = float(source_pixel_size_um)
    px_tg = float(target_pixel_size_um)

    # Per-axis physical size in micrometres, converted to overview pixels.
    # math.floor avoids rounding surprises on half-pixel ties, and max(1, ...)
    # keeps the window at least one pixel for degenerate zoom ratios.
    w = max(1, int(math.floor(W_tg * px_tg / px_ov)))
    h = max(1, int(math.floor(H_tg * px_tg / px_ov)))

    cx, cy = centroid_col_row_px
    x0 = int(math.floor(cx - w / 2))
    y0 = int(math.floor(cy - h / 2))
    return (x0, y0, w, h)


def crop_overview_at_target_fov(
    overview: np.ndarray,
    *,
    centroid_col_row_px: tuple[float, float],
    source_pixel_size_um: float,
    target_shape_px: tuple[int, int],
    target_pixel_size_um: float,
) -> np.ndarray:
    """Crop the overview around a cell, sized to the target job's field of view.

    Returns a 2-D array cut from ``overview`` using the window
    :func:`target_fov_window_in_overview` computes, so the crop shows exactly
    the physical area the target acquisition will image. Any part of the window
    that falls outside the overview (a cell near a tile edge) is filled with the
    overview's median intensity -- that is normal, not an error. Raises
    ``ValueError`` if ``overview`` is not a 2-D array.
    """
    if overview.ndim != 2:
        raise ValueError(
            f"crop_overview_at_target_fov requires a 2-D overview; "
            f"got shape {overview.shape} (ndim={overview.ndim}). "
            f"Multi-plane overviews are unsupported."
        )

    H_ov, W_ov = overview.shape
    # The same window math the visualization rectangle uses, so the rectangle
    # on one panel and the crop on the other always show the same region.
    x0, y0, w, h = target_fov_window_in_overview(
        centroid_col_row_px=centroid_col_row_px,
        source_pixel_size_um=source_pixel_size_um,
        target_shape_px=target_shape_px,
        target_pixel_size_um=target_pixel_size_um,
    )

    # Build the padded crop in one allocation, then copy in whatever part of
    # the window actually lies inside the overview.
    pad = int(np.median(overview))
    xs = max(0, x0)
    ys = max(0, y0)
    xe = min(W_ov, x0 + w)
    ye = min(H_ov, y0 + h)
    crop = np.full((h, w), pad, dtype=overview.dtype)
    if xs < xe and ys < ye:
        dst_y0 = ys - y0
        dst_x0 = xs - x0
        crop[dst_y0 : dst_y0 + (ye - ys), dst_x0 : dst_x0 + (xe - xs)] = overview[ys:ye, xs:xe]
    return crop


def overview_pixel_to_frame(
    *,
    centroid_col_row_px: tuple[float, float],
    image_shape_px: tuple[int, int],
    pixel_size_um: float,
    image_center_frame_um: tuple[float, float],
) -> tuple[float, float]:
    """Map an overview pixel ``(col, row)`` to a frame ``(x, y)`` target in um.

    The overview image was captured centred on ``image_center_frame_um`` (the
    frame position the workflow moved to before acquiring), so a pixel's frame
    position is that centre plus its offset from the image centre scaled by the
    pixel size. Image axes align with frame axes (no orientation transform):
    ``col`` -> frame ``x``, ``row`` -> frame ``y``.

    Parameters
    ----------
    centroid_col_row_px : (col, row) pixel coordinates in the overview.
    image_shape_px : (H, W) of the overview image.
    pixel_size_um : overview pixel size in micrometres (square pixels).
    image_center_frame_um : frame (x, y) um the overview was captured at.
    """
    height, width = int(image_shape_px[0]), int(image_shape_px[1])
    col, row = float(centroid_col_row_px[0]), float(centroid_col_row_px[1])
    x_um = image_center_frame_um[0] + (col - width / 2.0) * pixel_size_um
    y_um = image_center_frame_um[1] + (row - height / 2.0) * pixel_size_um
    return (x_um, y_um)

"""Geometry helpers shared across the workflow.

Pure-data primitives only -- no domain objects (no Pick, no
LayoutPlan, no Naming). Callers translate their domain objects to
these inputs at the call site; the helpers stay testable in
isolation and free of import cycles.

Two functions live here:

  ``target_fov_window_in_overview``
      Compute the (x0, y0, width, height) window in overview pixels
      that covers the target job's physical FOV centred on a pick's
      centroid. Pure window math. The window may extend past the
      overview's bounds for edge cells -- the caller decides what
      to do (the crop helper pads with median; the visualization
      rectangle draws as-is, with the off-image portion clipped by
      matplotlib's axis limits).

  ``crop_overview_at_target_fov``
      Use the window to crop the overview, padding with the
      overview's median intensity for any portion outside bounds.
      Returns a 2-D array of shape (h, w) from the window.

Both ``_mockprovider.build_target_provider`` (target hijack content
source) and ``visualize._render_target_crop_panel`` + the left-
panel red-rectangle callout call into this module. Independent
implementations of this math drifted in the past: visualize used
round + clamp, hijack used floor + median pad, and on edge cells
they showed different windows. Sharing structurally closes that
drift class -- the rectangle on the left panel reflects exactly
the same window the centre panel's crop is taken from.
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
    """Compute the (x0, y0, width, height) window in overview pixels
    that covers the target job's physical FOV centred on the pick's
    centroid.

    The window may extend past the overview's bounds (negative x0/y0
    or x0+w > W, y0+h > H) when the cell is near a tile edge. The
    caller decides what to do:

      - ``crop_overview_at_target_fov`` (in this module) pads the
        out-of-bounds portion with the overview's median intensity.
      - ``visualize`` draws a Rectangle at the exact window
        coordinates; matplotlib clips the off-image portion to the
        axis limits, honestly showing "the target FOV extends past
        this tile."

    Pure-data signature, no domain objects. Scalar pixel-size model
    (same on both axes -- consistent with the rest of the pipeline).
    Non-square *images* are honoured (per-axis derivation); non-
    square *pixels* are out of scope.

    Returns
    -------
    (x0, y0, w, h) : tuple[int, int, int, int]
        Top-left column, top-left row, width, height -- all in
        overview pixel coordinates. ``x0``/``y0`` may be negative;
        ``x0 + w`` / ``y0 + h`` may exceed the overview's dimensions.
        Width and height are always >= 1 (defensive floor for
        degenerate zoom ratios).
    """
    H_tg, W_tg = int(target_shape_px[0]), int(target_shape_px[1])
    px_ov = float(source_pixel_size_um)
    px_tg = float(target_pixel_size_um)

    # Per-axis FOV in micrometres -> overview pixels. math.floor
    # avoids banker's-rounding surprises on half-pixel ties.
    # max(1, ...) is a defensive floor for degenerate zoom ratios
    # (the window must have at least one pixel on each axis).
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
    """Crop the overview at a cell centroid, sized to the target's FOV.

    Returns a 2-D array of shape ``(crop_h, crop_w)`` where the crop
    dimensions in overview pixels equal the target job's physical
    FOV (in micrometres) divided by the overview's pixel size.
    Centred on ``centroid_col_row_px``; the area is padded with the
    overview's median intensity if the requested window extends past
    the overview's bounds (cell near tile edge).

    Pure-data signature -- no Pick, no Naming, no LayoutPlan. Both
    call sites (``_mockprovider.build_target_provider`` and
    ``visualize._render_target_crop_panel``) translate their domain
    objects to these primitives at the call site so this helper
    stays import-cycle-free and unit-testable in isolation.

    Parameters
    ----------
    overview : np.ndarray
        2-D array of the overview tile pixels (e.g. as returned by
        ``tifffile.imread`` on the saved overview .ome.tiff).
    centroid_col_row_px : tuple[float, float]
        ``(col, row) = (x, y)`` -- the cell centroid in overview
        pixel coordinates. (Convention matches ``Pick.centroid_col_row_px``.)
    source_pixel_size_um : float
        Overview's pixel size in micrometres. Scalar (square pixels
        assumption -- consistent with the rest of the pipeline; see
        the target-mock-zoom plan, §"Pixel-size model").
    target_shape_px : tuple[int, int]
        Target image's pixel dimensions as ``(H_tg, W_tg)``. Non-
        square *images* are honoured (height and width derive
        independently); non-square *pixels* are out of scope.
    target_pixel_size_um : float
        Target's pixel size in micrometres. Scalar.

    Returns
    -------
    np.ndarray
        2-D array, shape ``(crop_h_ov_px, crop_w_ov_px)``, dtype
        matching ``overview.dtype``. Out-of-bounds areas are filled
        with ``int(np.median(overview))``.

    Raises
    ------
    ValueError
        If ``overview`` is not 2-D. (Multi-plane overviews are
        upstream-blocked by ``hijack_frame``'s 2-D guard for fresh
        simulator runs; this raise defends against stale / hand-
        modified files.)
    """
    if overview.ndim != 2:
        raise ValueError(
            f"crop_overview_at_target_fov requires a 2-D overview; "
            f"got shape {overview.shape} (ndim={overview.ndim}). "
            f"Multi-plane overviews are unsupported."
        )

    H_ov, W_ov = overview.shape
    # Shared window math -- the same call ``visualize.py``'s left-
    # panel red rectangle makes. Structurally enforces "the
    # rectangle on the left panel and the crop on the centre panel
    # show the same physical region."
    x0, y0, w, h = target_fov_window_in_overview(
        centroid_col_row_px=centroid_col_row_px,
        source_pixel_size_um=source_pixel_size_um,
        target_shape_px=target_shape_px,
        target_pixel_size_um=target_pixel_size_um,
    )

    # Median-pad: cell near tile edge -> some of the requested crop
    # window is outside the overview's bounds. Build the padded crop
    # in one allocation; copy in the in-bounds portion.
    pad = int(np.median(overview))
    xs = max(0, x0); ys = max(0, y0)
    xe = min(W_ov, x0 + w); ye = min(H_ov, y0 + h)
    crop = np.full((h, w), pad, dtype=overview.dtype)
    if xs < xe and ys < ye:
        dst_y0 = ys - y0
        dst_x0 = xs - x0
        crop[dst_y0:dst_y0 + (ye - ys),
             dst_x0:dst_x0 + (xe - xs)] = overview[ys:ye, xs:xe]
    return crop

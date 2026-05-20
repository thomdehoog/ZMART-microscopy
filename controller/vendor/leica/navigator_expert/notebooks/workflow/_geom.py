"""Geometry helpers shared across the workflow.

Pure-data primitives only -- no domain objects (no Pick, no
LayoutPlan, no Naming). Callers translate their domain objects to
these inputs at the call site; the helpers stay testable in
isolation and free of import cycles.

The single function currently lives here:
``crop_overview_at_target_fov`` -- both ``_mockprovider.build_target_provider``
(target hijack content source) and ``visualize._render_target_crop_panel``
(Step 5 centre panel) call it. Independent implementations of this
math drifted in the past: visualize used round + clamp, hijack used
floor + median pad, and on edge cells they showed different windows.
Sharing the helper makes that class of bug structurally unreachable.
"""
from __future__ import annotations

import math

import numpy as np


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
    H_tg, W_tg = int(target_shape_px[0]), int(target_shape_px[1])

    # Per-axis FOV. Pixel size is scalar (same on both axes); image
    # may be non-square so width and height are derived independently.
    target_fov_w_um = W_tg * float(target_pixel_size_um)
    target_fov_h_um = H_tg * float(target_pixel_size_um)

    # Express the FOV in overview pixels. math.floor avoids banker's-
    # rounding surprises on half-pixel ties; max(1, ...) is a
    # defensive floor for degenerate zoom ratios (the crop must have
    # at least one pixel on each axis).
    px_ov = float(source_pixel_size_um)
    crop_w_ov_px = max(1, int(math.floor(target_fov_w_um / px_ov)))
    crop_h_ov_px = max(1, int(math.floor(target_fov_h_um / px_ov)))

    # Crop top-left in overview pixels (centred on the cell).
    cx, cy = centroid_col_row_px
    x0 = int(math.floor(cx - crop_w_ov_px / 2))
    y0 = int(math.floor(cy - crop_h_ov_px / 2))

    # Median-pad: cell near tile edge -> some of the requested crop
    # window is outside the overview's bounds. Build the padded crop
    # in one allocation; copy in the in-bounds portion.
    pad = int(np.median(overview))
    xs = max(0, x0); ys = max(0, y0)
    xe = min(W_ov, x0 + crop_w_ov_px); ye = min(H_ov, y0 + crop_h_ov_px)
    crop = np.full(
        (crop_h_ov_px, crop_w_ov_px), pad, dtype=overview.dtype,
    )
    if xs < xe and ys < ye:
        dst_y0 = ys - y0
        dst_x0 = xs - x0
        crop[dst_y0:dst_y0 + (ye - ys),
             dst_x0:dst_x0 + (xe - xs)] = overview[ys:ye, xs:xe]
    return crop

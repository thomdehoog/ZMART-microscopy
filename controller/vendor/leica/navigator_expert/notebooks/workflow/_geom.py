"""Geometry helpers shared across the workflow.

Pure-data primitives only -- no domain objects (no Pick, no
LayoutPlan, no Naming). Callers translate their domain objects to
these inputs at the call site; the helpers stay testable in
isolation and free of import cycles.

Two functions live here:

  ``crop_overview_at_target_fov``
      Just the crop step -- returns an array sized in *overview*
      pixels covering the target job's physical FOV around a cell
      centroid. Median-padded for edge cells.

  ``crop_and_resize_overview_to_target``
      Crop + bilinear resize to target pixel dimensions. Returns an
      array in *target* pixel dimensions, ready for imshow with no
      further matplotlib upscaling.

Both helpers are shared between the target hijack (writes the result
into the canonical .ome.tiff) and Step 5's visualization centre
panel (renders it). Sharing structurally guarantees the centre
panel and the saved target frame agree on both the crop window
*and* the display-resolution upsample -- in simulator mode they
produce byte-identical content, honestly revealing that the
simulator's "high-res" target adds no information beyond the
overview pixels it was derived from.
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


def crop_and_resize_overview_to_target(
    overview: np.ndarray,
    *,
    centroid_col_row_px: tuple[float, float],
    source_pixel_size_um: float,
    target_shape_px: tuple[int, int],
    target_pixel_size_um: float,
) -> np.ndarray:
    """Crop the overview at a cell centroid, then bilinear-resize
    to the target's pixel dimensions.

    Composition of ``crop_overview_at_target_fov`` (the crop step)
    plus a bilinear upsample to ``target_shape_px``. Returns an
    array at *target* resolution, ready for ``imshow`` with no
    further matplotlib upscaling asymmetry between this and the
    actual target frame at the same shape.

    Both call sites share this function:

      ``_mockprovider.build_target_provider`` -- the hijack provider
      writes the result into the saved target .ome.tiff. In
      simulator mode this IS the target file's content.

      ``visualize._render_target_crop_panel`` -- the Step 5 centre
      panel displays the result. In simulator mode this is
      byte-identical to the right panel's content (which is the
      saved target file, which the hijack just wrote).

    The simulator therefore reveals itself honestly: the centre and
    right panels show the same thing because they ARE the same
    thing -- both bilinear upsamples of the same overview crop.
    In real-hardware mode the right panel diverges (genuine
    higher-resolution content), giving the operator a meaningful
    "what the overview gave us vs what the high-res capture added"
    comparison.

    Parameters
    ----------
    overview, centroid_col_row_px, source_pixel_size_um,
    target_shape_px, target_pixel_size_um
        Same as ``crop_overview_at_target_fov``.

    Returns
    -------
    np.ndarray
        Shape ``target_shape_px`` (= ``(H_tg, W_tg)``), dtype
        matching ``overview.dtype``.
    """
    crop = crop_overview_at_target_fov(
        overview,
        centroid_col_row_px=centroid_col_row_px,
        source_pixel_size_um=source_pixel_size_um,
        target_shape_px=target_shape_px,
        target_pixel_size_um=target_pixel_size_um,
    )
    # Lazy: skimage.transform pulls in scipy + several heavy
    # submodules; defer the import to first call (which only fires
    # in simulator mode or in Step 5 rendering).
    from skimage.transform import resize

    H_tg, W_tg = int(target_shape_px[0]), int(target_shape_px[1])
    # anti_aliasing=False because we're scaling *up*; preserve_range
    # keeps intensity values in their original numeric range rather
    # than [0, 1].
    resized = resize(
        crop, (H_tg, W_tg),
        preserve_range=True, anti_aliasing=False,
    )
    return resized.astype(overview.dtype)

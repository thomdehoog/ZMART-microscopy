"""
Image registration for objective-switch protocols.
==================================================

Self-contained registration module for the Leica controller cookbook.
Pure image processing on numpy arrays — no LAS X driver imports, no
hardware. Safe to import and test offline.

Design notes (don't relearn these the hard way)
-----------------------------------------------

**Pixel size matters, not camera format.** PCC and NCC both compare
arrays element-wise (FFT or sliding window). Two images registered
together must share:
    - the same effective um/pixel
    - the same orientation / flip / rotation
    - the same physical FOV (same shape, after resample)
Camera format is convenient when both images come from the same scope
at the same scan settings, but pixel size is the actual contract.

**Always downsample the finer image.** Upsampling fabricates pixels via
interpolation; downsampling preserves real information. Register at
the COARSER of the two pixel sizes.

**FOV must overlap.** Running PCC on a full 10x field against a smaller
20x field means most of the source has no counterpart in the target —
the FFT smears the mismatch into the spectrum and you get borderline
peaks that look like ambiguity but are really FOV mismatch. NCC has
it worse: template-larger-than-image errors outright. Crop the
larger-FOV image to the smaller's physical FOV before registering.

**Crop around the cell-of-interest, not the image centre.** When the
cell is off-centre in the source, cropping at source's geometric
centre throws away the part of the source the target actually sees.
Crop around the picked cell's pixel in source, around the optical /
galvo centre in the target.

**Direction-symmetric prep.** source -> target can go in either mag
direction. The robust abstraction isn't "downsample the target" —
it's: crop whichever has the larger FOV; resample whichever has the
finer pixel size; both end up at the smaller physical FOV at the
coarser pixel size.

**Voting beats single-method gates.** PCC, masked PCC, NCC, and
ORB+RANSAC have orthogonal failure modes (FFT artefacts, periodic
patterns, neighbour-cell ambiguity, featureless regions). Any single
hard threshold either rejects borderline-correct matches (false
alarms) or accepts silent wrong matches. Cluster the four estimates
by tolerance, take the largest agreeing subset, median within. The
single user knob is the agreement tolerance.

**PCC sign convention** (skimage): ``phase_cross_correlation(ref, mov)``
returns ``shift`` such that ``mov = shift_op(ref, +shift)``. So source
content at ``(y, x)`` appears in mov at ``(y + shift_y, x + shift_x)``.
That's image-axis math; stage axes are handled separately by the
calibrated ``image_to_stage_um`` matrix (don't double-apply).

**Don't hardcode signs.** If you find yourself writing ``+X, -Y`` in
caller code, you're probably going to double-apply something the
calibration matrix already handles. Stay in image-pixel space here;
let the caller's ``pixel_to_stage_xy_um`` apply the 2x2 matrix once.

Usage
-----

For the common case (one entry point):

    from registration import register

    result = register(
        source_img, intermediate_img,
        source_pixel_um=2.27,
        intermediate_pixel_um=1.135,
        source_cell_col=cx_px, source_cell_row=cy_px,
        tolerance_um=2.0,
    )
    if not result.ok:
        # See result.failure_reason; full per-method results in result.per_method
        ...
    else:
        # result.cell_in_intermediate_px is the cell's (col, row) in the
        # matched-pixel-size intermediate frame, ready to feed into
        # pixel_to_stage_xy_um anchored at the intermediate's optical centre.
        col, row = result.cell_in_intermediate_px

For lower-level access, ``prepare_pair`` and ``cluster_vote`` are
exposed; the four method functions (``pcc``, ``masked_pcc``, ``ncc``,
``orb_ransac``) are also public.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import combinations
from typing import Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np
from skimage.feature import ORB, match_descriptors
from skimage.measure import ransac
from skimage.registration import phase_cross_correlation
from skimage.transform import EuclideanTransform


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class PreparedPair:
    """Matched ref/tgt arrays ready for voting registration.

    ``ref_img`` and ``tgt_img`` share the same physical FOV at the same
    um/pixel and (modulo edge rounding) the same shape. Voting methods
    can run on them directly.
    """
    ref_img: np.ndarray
    tgt_img: np.ndarray
    registration_pixel_um: float
    common_fov_um: float
    source_cell_in_ref_px: Tuple[float, float]            # (col, row)
    intermediate_centre_in_tgt_px: Tuple[float, float]    # (col, row)
    source_crop_bbox_px: Tuple[int, int, int, int]        # (l, t, r, b)
    intermediate_crop_bbox_px: Tuple[int, int, int, int]  # (l, t, r, b)


@dataclass
class MethodResult:
    name: str
    dx_um: float
    dy_um: float
    quality: float
    failed: bool
    in_cluster: bool = False
    time_s: float = 0.0


@dataclass
class ClusterMeta:
    indices: List[int]
    names: List[str]
    size: int
    spread_um: float
    tolerance_um: float
    min_required: int


@dataclass
class RegistrationResult:
    """Output of :func:`register`.

    ``ok`` is True when the cluster vote converged. When False, inspect
    ``failure_reason`` and ``per_method`` to see which methods agreed
    or disagreed, and use ``prep`` + ``per_method`` to render a
    diagnostic.
    """
    ok: bool
    failure_reason: Optional[str]
    median_shift_um: Optional[Tuple[float, float]]   # (dx_um, dy_um)
    cell_in_intermediate_px: Optional[Tuple[float, float]]  # (col, row) in tgt
    registration_pixel_um: float
    prep: PreparedPair
    per_method: List[MethodResult]
    cluster: Optional[ClusterMeta]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resample(img: np.ndarray, src_pixel_um: float,
              tgt_pixel_um: float) -> np.ndarray:
    """Resample *img* from src to tgt pixel size. Cubic when upsampling,
    area when downsampling — the standard pair for image work."""
    scale = float(src_pixel_um) / float(tgt_pixel_um)
    h, w = img.shape[:2]
    new_h = max(8, int(round(h * scale)))
    new_w = max(8, int(round(w * scale)))
    interp = cv2.INTER_CUBIC if scale > 1.0 else cv2.INTER_AREA
    return cv2.resize(img, (new_w, new_h), interpolation=interp)


def _crop_around(img: np.ndarray, centre_col: float, centre_row: float,
                 half_size_px: int) -> Tuple[np.ndarray, Tuple[int, int, int, int]]:
    """Crop *img* around (centre_col, centre_row) by ±half_size_px,
    clipped at edges. Returns (crop, (left, top, right, bottom))."""
    h, w = img.shape[:2]
    cc = int(round(centre_col))
    cr = int(round(centre_row))
    left = max(0, cc - half_size_px)
    right = min(w, cc + half_size_px)
    top = max(0, cr - half_size_px)
    bottom = min(h, cr + half_size_px)
    return img[top:bottom, left:right], (left, top, right, bottom)


def _to_u8(a: np.ndarray) -> np.ndarray:
    a = a.astype(np.float32)
    if a.size == 0:
        return np.zeros_like(a, dtype=np.uint8)
    lo, hi = np.percentile(a, (1.0, 99.8))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        lo, hi = float(a.min()), float(a.max())
    if hi <= lo:
        return np.zeros_like(a, dtype=np.uint8)
    a = np.clip((a - lo) / (hi - lo), 0.0, 1.0)
    return (a * 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# Pair preparation
# ---------------------------------------------------------------------------


def prepare_pair(
    source_img: np.ndarray,
    intermediate_img: np.ndarray,
    *,
    source_pixel_um: float,
    intermediate_pixel_um: float,
    source_cell_col: float,
    source_cell_row: float,
    intermediate_centre_col: Optional[float] = None,
    intermediate_centre_row: Optional[float] = None,
) -> PreparedPair:
    """Make a matched-shape, matched-um/px image pair for registration.

    The image with the larger physical FOV is cropped to the smaller's
    FOV (centred on the cell of interest in source / on the
    intermediate's optical centre in intermediate). The image with the
    finer pixel size is resampled down to the coarser pixel size.

    See module docstring for the design rationale.
    """
    sh, sw = source_img.shape[:2]
    ih, iw = intermediate_img.shape[:2]
    src_fov_um = sw * source_pixel_um
    int_fov_um = iw * intermediate_pixel_um

    common_fov_um = min(src_fov_um, int_fov_um)
    common_pixel_um = max(source_pixel_um, intermediate_pixel_um)

    src_half_px = int(round(common_fov_um / 2.0 / source_pixel_um))
    int_half_px = int(round(common_fov_um / 2.0 / intermediate_pixel_um))

    if intermediate_centre_col is None:
        intermediate_centre_col = iw / 2.0
    if intermediate_centre_row is None:
        intermediate_centre_row = ih / 2.0

    src_crop, src_bbox = _crop_around(source_img, source_cell_col,
                                      source_cell_row, src_half_px)
    int_crop, int_bbox = _crop_around(intermediate_img,
                                      intermediate_centre_col,
                                      intermediate_centre_row, int_half_px)

    cell_col_in_src_crop = source_cell_col - src_bbox[0]
    cell_row_in_src_crop = source_cell_row - src_bbox[1]
    centre_col_in_int_crop = intermediate_centre_col - int_bbox[0]
    centre_row_in_int_crop = intermediate_centre_row - int_bbox[1]

    if source_pixel_um < intermediate_pixel_um:
        ref_img = _resample(src_crop, source_pixel_um, common_pixel_um)
        tgt_img = int_crop
        scale = source_pixel_um / common_pixel_um
        cell_col_in_ref = cell_col_in_src_crop * scale
        cell_row_in_ref = cell_row_in_src_crop * scale
        centre_col_in_tgt = centre_col_in_int_crop
        centre_row_in_tgt = centre_row_in_int_crop
    else:
        ref_img = src_crop
        tgt_img = _resample(int_crop, intermediate_pixel_um, common_pixel_um)
        cell_col_in_ref = cell_col_in_src_crop
        cell_row_in_ref = cell_row_in_src_crop
        scale = intermediate_pixel_um / common_pixel_um
        centre_col_in_tgt = centre_col_in_int_crop * scale
        centre_row_in_tgt = centre_row_in_int_crop * scale

    return PreparedPair(
        ref_img=ref_img,
        tgt_img=tgt_img,
        registration_pixel_um=common_pixel_um,
        common_fov_um=common_fov_um,
        source_cell_in_ref_px=(float(cell_col_in_ref), float(cell_row_in_ref)),
        intermediate_centre_in_tgt_px=(float(centre_col_in_tgt),
                                       float(centre_row_in_tgt)),
        source_crop_bbox_px=tuple(src_bbox),
        intermediate_crop_bbox_px=tuple(int_bbox),
    )


# ---------------------------------------------------------------------------
# Method functions — each returns (dx_um, dy_um, quality)
# NaN dx/dy means the method failed.
# ---------------------------------------------------------------------------


def pcc(ref: np.ndarray, tgt: np.ndarray, pixel_um: float,
        mask_pct: float = 30.0) -> Tuple[float, float, float]:
    """Phase cross-correlation, unmasked. Returns (dx_um, dy_um, error)."""
    shift, error, _ = phase_cross_correlation(
        ref.astype(np.float64), tgt.astype(np.float64),
        upsample_factor=100,
    )
    dy_px, dx_px = shift
    return dx_px * pixel_um, dy_px * pixel_um, float(error)


def masked_pcc(ref: np.ndarray, tgt: np.ndarray, pixel_um: float,
               mask_pct: float = 30.0) -> Tuple[float, float, float]:
    """Phase cross-correlation with intensity-percentile masks
    (Padfield 2012). Returns (dx_um, dy_um, error)."""
    ref_mask = ref > np.percentile(ref, mask_pct)
    tgt_mask = tgt > np.percentile(tgt, mask_pct)
    shift, error, _ = phase_cross_correlation(
        ref.astype(np.float64), tgt.astype(np.float64),
        upsample_factor=100,
        reference_mask=ref_mask, moving_mask=tgt_mask,
    )
    dy_px, dx_px = shift
    return dx_px * pixel_um, dy_px * pixel_um, float(error)


def ncc(ref: np.ndarray, tgt: np.ndarray, pixel_um: float,
        mask_pct: float = 30.0) -> Tuple[float, float, float]:
    """OpenCV TM_CCOEFF_NORMED with the centre crop of tgt as template
    against full ref. Returns (dx_um, dy_um, peak_correlation)."""
    ref8 = (ref.astype(np.float64) / (ref.max() or 1) * 255).astype(np.uint8)
    tgt8 = (tgt.astype(np.float64) / (tgt.max() or 1) * 255).astype(np.uint8)
    h, w = tgt8.shape
    margin = h // 4
    template = tgt8[margin:h - margin, margin:w - margin]
    result = cv2.matchTemplate(ref8, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    match_cx = max_loc[0] + template.shape[1] / 2.0
    match_cy = max_loc[1] + template.shape[0] / 2.0
    dx_px = match_cx - w / 2.0
    dy_px = match_cy - h / 2.0
    return dx_px * pixel_um, dy_px * pixel_um, float(max_val)


def orb_ransac(ref: np.ndarray, tgt: np.ndarray, pixel_um: float,
               mask_pct: float = 30.0) -> Tuple[float, float, float]:
    """ORB feature matching + RANSAC EuclideanTransform (translation
    only). Returns (dx_um, dy_um, inlier_ratio). NaN on failure."""
    ref_n = (ref.astype(np.float64) / (ref.max() or 1) * 255).astype(np.uint8)
    tgt_n = (tgt.astype(np.float64) / (tgt.max() or 1) * 255).astype(np.uint8)

    orb = ORB(n_keypoints=500, fast_threshold=0.05)
    try:
        orb.detect_and_extract(ref_n)
        kp_ref, desc_ref = orb.keypoints, orb.descriptors
        orb.detect_and_extract(tgt_n)
        kp_tgt, desc_tgt = orb.keypoints, orb.descriptors
    except Exception:
        return float("nan"), float("nan"), 0.0

    if (desc_ref is None or desc_tgt is None
            or len(desc_ref) < 3 or len(desc_tgt) < 3):
        return float("nan"), float("nan"), 0.0

    matches = match_descriptors(desc_ref, desc_tgt, cross_check=True)
    if len(matches) < 3:
        return float("nan"), float("nan"), 0.0

    src = kp_tgt[matches[:, 1]]
    dst = kp_ref[matches[:, 0]]
    model, inliers = ransac(
        (src, dst), EuclideanTransform, min_samples=3,
        residual_threshold=5, max_trials=1000,
    )
    if model is None or inliers is None:
        return float("nan"), float("nan"), 0.0

    dy_px = model.translation[0]
    dx_px = model.translation[1]
    return dx_px * pixel_um, dy_px * pixel_um, float(inliers.sum() / len(matches))


METHODS: List[Tuple[str, Callable]] = [
    ("PCC", pcc),
    ("Masked PCC", masked_pcc),
    ("NCC", ncc),
    ("ORB+RANSAC", orb_ransac),
]


# ---------------------------------------------------------------------------
# Cluster vote
# ---------------------------------------------------------------------------


def _largest_clique(estimates: List[MethodResult],
                    tolerance_um: float) -> List[int]:
    """Largest subset where every pairwise (dx, dy) distance <= tolerance.
    Returns indices into *estimates*. With n=4 the brute-force search is
    trivial; first clique found at the largest size wins (ties not
    disambiguated — the diagnostic shows what agreed)."""
    n = len(estimates)
    if n == 0:
        return []

    def is_clique(indices: Tuple[int, ...]) -> bool:
        for i in range(len(indices)):
            for j in range(i + 1, len(indices)):
                a, b = estimates[indices[i]], estimates[indices[j]]
                if math.hypot(a.dx_um - b.dx_um, a.dy_um - b.dy_um) > tolerance_um:
                    return False
        return True

    for size in range(n, 0, -1):
        for combo in combinations(range(n), size):
            if is_clique(combo):
                return list(combo)
    return []


def cluster_vote(
    ref: np.ndarray,
    tgt: np.ndarray,
    pixel_um: float,
    *,
    tolerance_um: float = 2.0,
    min_cluster: int = 3,
    mask_pct: float = 30.0,
    methods: List[Tuple[str, Callable]] = METHODS,
) -> Tuple[Optional[Tuple[float, float]], List[MethodResult], Optional[ClusterMeta]]:
    """Run all methods; return cluster median + per-method + cluster meta.

    Returns
    -------
    median_shift_um : (dx_um, dy_um) | None
        Median of the chosen cluster, or None if no cluster of at least
        ``min_cluster`` methods agreed within ``tolerance_um``.
    per_method : list[MethodResult]
        One entry per method (in the order of ``methods``). Failed
        methods have NaN dx/dy and ``failed=True``. ``in_cluster``
        flags which methods made it into the chosen cluster.
    cluster : ClusterMeta | None
        Metadata about the chosen cluster, or None on failure.
    """
    import time

    per_method: List[MethodResult] = []
    for name, func in methods:
        t0 = time.time()
        try:
            dx, dy, q = func(ref, tgt, pixel_um, mask_pct)
            failed = not (np.isfinite(dx) and np.isfinite(dy))
        except Exception:
            dx, dy, q, failed = float("nan"), float("nan"), 0.0, True
        per_method.append(MethodResult(
            name=name, dx_um=float(dx), dy_um=float(dy),
            quality=float(q), failed=failed,
            time_s=time.time() - t0,
        ))

    valid_idx = [i for i, m in enumerate(per_method) if not m.failed]
    valid = [per_method[i] for i in valid_idx]
    if not valid:
        return None, per_method, None

    clique = _largest_clique(valid, tolerance_um)
    if len(clique) < min_cluster:
        return None, per_method, None

    chosen_global = [valid_idx[k] for k in clique]
    for gi in chosen_global:
        per_method[gi].in_cluster = True

    dxs = np.array([per_method[i].dx_um for i in chosen_global])
    dys = np.array([per_method[i].dy_um for i in chosen_global])
    median = (float(np.median(dxs)), float(np.median(dys)))

    spread = 0.0
    for ii in range(len(chosen_global)):
        for jj in range(ii + 1, len(chosen_global)):
            a, b = per_method[chosen_global[ii]], per_method[chosen_global[jj]]
            d = math.hypot(a.dx_um - b.dx_um, a.dy_um - b.dy_um)
            if d > spread:
                spread = d

    cluster = ClusterMeta(
        indices=chosen_global,
        names=[per_method[i].name for i in chosen_global],
        size=len(chosen_global),
        spread_um=spread,
        tolerance_um=tolerance_um,
        min_required=min_cluster,
    )
    return median, per_method, cluster


# ---------------------------------------------------------------------------
# Convenience entry point
# ---------------------------------------------------------------------------


def register(
    source_img: np.ndarray,
    intermediate_img: np.ndarray,
    *,
    source_pixel_um: float,
    intermediate_pixel_um: float,
    source_cell_col: float,
    source_cell_row: float,
    intermediate_centre_col: Optional[float] = None,
    intermediate_centre_row: Optional[float] = None,
    tolerance_um: float = 2.0,
    min_cluster: int = 3,
    mask_pct: float = 30.0,
) -> RegistrationResult:
    """One-call registration: prepare matched pair, vote, map cell pixel.

    The shift convention is ``cell_in_intermediate = cell_in_ref +
    voted_shift_in_pixels`` (skimage's PCC convention; NCC / ORB are
    written to match). Stage axis sign-flipping is NOT done here —
    feed ``cell_in_intermediate_px`` to your scope's
    ``pixel_to_stage_xy_um`` (which knows the calibrated 2x2
    image-to-stage matrix) anchored at the intermediate's optical
    centre.

    On vote failure (no cluster of at least ``min_cluster`` methods
    agrees within ``tolerance_um``), ``ok=False`` and
    ``cell_in_intermediate_px=None``. Inspect ``per_method`` to see
    what disagreed. ``prep`` is always populated so the caller can
    render diagnostic overlays even on failure.
    """
    prep = prepare_pair(
        source_img, intermediate_img,
        source_pixel_um=source_pixel_um,
        intermediate_pixel_um=intermediate_pixel_um,
        source_cell_col=source_cell_col,
        source_cell_row=source_cell_row,
        intermediate_centre_col=intermediate_centre_col,
        intermediate_centre_row=intermediate_centre_row,
    )

    median, per_method, cluster = cluster_vote(
        prep.ref_img, prep.tgt_img, prep.registration_pixel_um,
        tolerance_um=tolerance_um,
        min_cluster=min_cluster,
        mask_pct=mask_pct,
    )

    if median is None:
        n_ok = sum(1 for m in per_method if not m.failed)
        reason = (f"no cluster of >= {min_cluster} methods agreed within "
                  f"{tolerance_um:.2f} um ({n_ok}/{len(per_method)} methods "
                  f"produced a valid estimate)")
        return RegistrationResult(
            ok=False,
            failure_reason=reason,
            median_shift_um=None,
            cell_in_intermediate_px=None,
            registration_pixel_um=prep.registration_pixel_um,
            prep=prep,
            per_method=per_method,
            cluster=cluster,
        )

    shift_col_px = median[0] / prep.registration_pixel_um
    shift_row_px = median[1] / prep.registration_pixel_um
    cell_col, cell_row = prep.source_cell_in_ref_px
    cell_in_intermediate_px = (cell_col + shift_col_px, cell_row + shift_row_px)

    return RegistrationResult(
        ok=True,
        failure_reason=None,
        median_shift_um=median,
        cell_in_intermediate_px=cell_in_intermediate_px,
        registration_pixel_um=prep.registration_pixel_um,
        prep=prep,
        per_method=per_method,
        cluster=cluster,
    )

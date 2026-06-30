"""Image-to-image registration: four methods + voting + sign-convention fit.

What's in here
    - ``pcc`` — phase cross-correlation, unmasked.
    - ``masked_pcc`` — phase cross-correlation with intensity-percentile masks.
    - ``ncc`` — OpenCV ``TM_CCOEFF_NORMED`` with the centre crop of TGT
      as template against full REF.
    - ``orb_ransac`` — ORB feature matching + RANSAC EuclideanTransform
      (translation only).
    - ``register_voting`` — runs all four, finds the largest agreeing
      cluster, returns the cluster median.
    - ``register_phase`` — thin wrapper around ``pcc`` used by the
      calibration sign-convention phase (separate so we don't change
      one and silently break the other).
    - ``classify_d4`` — snap a 2×2 fitted matrix to the nearest D4
      reflection / rotation; used to convert the raw stage-to-image
      Jacobian into a clean axis-aligned sign convention.

Sign convention (read this before changing anything)
    All four method functions return ``(dx_um, dy_um, quality)`` where
    a **positive** shift means features in TGT lie at +x / +y relative
    to features in REF. This is the **negation** of skimage's
    ``phase_cross_correlation`` output (which returns the shift you'd
    APPLY TO TGT to align it with REF).

    Why this convention: ``classify_d4`` and the calibration
    sign-convention phase fit ``image_to_stage_um`` against this
    sign. Flipping the sign in any one method silently rotates that
    matrix and the cookbook will land cells in the wrong place.

Quality conventions per method
    - PCC / masked PCC: ``1 - error`` from skimage's residual; higher
      is better, matching NCC.
    - NCC: peak correlation in [-1, 1]; higher is better.
    - ORB: inlier ratio in [0, 1]; higher is better.

Failed methods return ``(NaN, NaN, 0.0)``; the voting wrapper drops
them rather than treating them as outlier votes.
"""

from __future__ import annotations

import cv2
import numpy as np
from skimage.feature import ORB, match_descriptors
from skimage.measure import ransac
from skimage.registration import phase_cross_correlation
from skimage.transform import EuclideanTransform

# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

#: All eight D4 reflections / rotations. ``classify_d4`` snaps a
#: fitted 2×2 matrix to the nearest of these.
D4_ELEMENTS = {
    "+X +Y": [[+1, 0], [0, +1]],
    "+X -Y": [[+1, 0], [0, -1]],
    "-X +Y": [[-1, 0], [0, +1]],
    "-X -Y": [[-1, 0], [0, -1]],
    "+Y +X": [[0, +1], [+1, 0]],
    "+Y -X": [[0, +1], [-1, 0]],
    "-Y +X": [[0, -1], [+1, 0]],
    "-Y -X": [[0, -1], [-1, 0]],
}

#: Maximum acceptable Frobenius distance from the fitted matrix to its
#: nearest D4 element. Above this the fit is too rotated/sheared to
#: snap cleanly — usually means drift, sparse texture, or too small a
#: stage move during the sign-convention phase.
D4_RESIDUAL_MAX: float = 0.3

#: Intensity percentile used as a foreground mask in ``masked_pcc``.
MASK_PCT_DEFAULT: float = 30.0

#: Voting cluster tolerance (um). Methods whose (dx, dy) agree within
#: this distance form one cluster; the largest cluster wins.
VOTING_TOLERANCE_UM: float = 3.0

#: Minimum cluster size for a voting result to be ``trusted``. Below
#: this, the consensus is too weak — usually flag and skip rather than
#: act on a guess.
VOTING_MIN_AGREE: int = 2


# ──────────────────────────────────────────────────────────────────────
# Tiny utilities
# ──────────────────────────────────────────────────────────────────────


def _to_uint8(img: np.ndarray) -> np.ndarray:
    f = img.astype(np.float64)
    return (f / (f.max() or 1) * 255).astype(np.uint8)


def _finite_or_none(value: float) -> float | None:
    value = float(value)
    return value if np.isfinite(value) else None


def _finite_median(values, *, default: float = 0.0) -> float:
    finite = [float(v) for v in values if np.isfinite(v)]
    if not finite:
        return float(default)
    return float(np.median(finite))


# ──────────────────────────────────────────────────────────────────────
# Method functions — each returns (dx_um, dy_um, quality) in the
# package sign convention (TGT minus REF). NaN dx/dy = method failed.
# ──────────────────────────────────────────────────────────────────────


def pcc(
    ref: np.ndarray, tgt: np.ndarray, pixel_um: float, mask_pct: float = MASK_PCT_DEFAULT
) -> tuple[float, float, float]:
    """Phase cross-correlation, unmasked. Quality = ``1 - error``."""
    shift, error, _ = phase_cross_correlation(
        ref.astype(np.float64),
        tgt.astype(np.float64),
        upsample_factor=100,
    )
    dy_px, dx_px = -shift[0], -shift[1]
    return dx_px * pixel_um, dy_px * pixel_um, 1.0 - float(error)


def masked_pcc(
    ref: np.ndarray, tgt: np.ndarray, pixel_um: float, mask_pct: float = MASK_PCT_DEFAULT
) -> tuple[float, float, float]:
    """PCC with intensity-percentile foreground masks (Padfield 2012)."""
    ref_mask = ref > np.percentile(ref, mask_pct)
    tgt_mask = tgt > np.percentile(tgt, mask_pct)
    shift, error, _ = phase_cross_correlation(
        ref.astype(np.float64),
        tgt.astype(np.float64),
        upsample_factor=100,
        reference_mask=ref_mask,
        moving_mask=tgt_mask,
    )
    dy_px, dx_px = -shift[0], -shift[1]
    return dx_px * pixel_um, dy_px * pixel_um, 1.0 - float(error)


def ncc(
    ref: np.ndarray, tgt: np.ndarray, pixel_um: float, mask_pct: float = MASK_PCT_DEFAULT
) -> tuple[float, float, float]:
    """Normalised cross-correlation. Centre crop of TGT vs full REF."""
    ref8 = _to_uint8(ref)
    tgt8 = _to_uint8(tgt)
    h, w = tgt8.shape
    template = tgt8[h // 4 : 3 * h // 4, w // 4 : 3 * w // 4]
    result = cv2.matchTemplate(ref8, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    dx_px = max_loc[0] + template.shape[1] / 2.0 - w / 2.0
    dy_px = max_loc[1] + template.shape[0] / 2.0 - h / 2.0
    return -dx_px * pixel_um, -dy_px * pixel_um, float(max_val)


def orb_ransac(
    ref: np.ndarray, tgt: np.ndarray, pixel_um: float, mask_pct: float = MASK_PCT_DEFAULT
) -> tuple[float, float, float]:
    """ORB descriptors + RANSAC EuclideanTransform. Quality = inlier ratio."""
    ref_n = _to_uint8(ref)
    tgt_n = _to_uint8(tgt)
    orb = ORB(n_keypoints=500, fast_threshold=0.05)
    try:
        orb.detect_and_extract(ref_n)
        kp_ref, desc_ref = orb.keypoints, orb.descriptors
        orb.detect_and_extract(tgt_n)
        kp_tgt, desc_tgt = orb.keypoints, orb.descriptors
    except Exception:
        return float("nan"), float("nan"), 0.0
    if desc_ref is None or desc_tgt is None or len(desc_ref) < 3 or len(desc_tgt) < 3:
        return float("nan"), float("nan"), 0.0
    matches = match_descriptors(desc_ref, desc_tgt, cross_check=True)
    if len(matches) < 3:
        return float("nan"), float("nan"), 0.0
    src = kp_tgt[matches[:, 1]]
    dst = kp_ref[matches[:, 0]]
    model, inliers = ransac(
        (src, dst),
        EuclideanTransform,
        min_samples=3,
        residual_threshold=5,
        max_trials=1000,
    )
    if model is None or inliers is None:
        return float("nan"), float("nan"), 0.0
    dy_px = model.translation[0]
    dx_px = model.translation[1]
    return -dx_px * pixel_um, -dy_px * pixel_um, float(inliers.sum() / len(matches))


VOTING_METHODS: tuple[tuple[str, callable], ...] = (
    ("pcc", pcc),
    ("masked_pcc", masked_pcc),
    ("ncc", ncc),
    ("orb", orb_ransac),
)


# ──────────────────────────────────────────────────────────────────────
# Voting registration
# ──────────────────────────────────────────────────────────────────────


def register_voting(
    ref: np.ndarray,
    tgt: np.ndarray,
    pixel_um: float,
    *,
    mask_pct: float = MASK_PCT_DEFAULT,
    tolerance_um: float = VOTING_TOLERANCE_UM,
    min_agree: int = VOTING_MIN_AGREE,
) -> dict:
    """Multi-method voting registration.

    Runs every method in ``VOTING_METHODS``, drops failures, then finds
    the largest cluster of (dx, dy) estimates pairwise within
    ``tolerance_um``. Returns the median of that cluster + diagnostic
    detail per method.

    The returned ``trusted`` flag is ``confidence >= min_agree``;
    callers should refuse to act on the consensus when ``trusted`` is
    False rather than acting on a guess.
    """
    per_method: dict[str, dict] = {}
    valid: list[tuple[str, float, float, float]] = []
    for name, fn in VOTING_METHODS:
        try:
            dx, dy, q = fn(ref, tgt, pixel_um, mask_pct)
        except Exception as exc:
            per_method[name] = {"error": str(exc)}
            continue
        per_method[name] = {
            "dx_um": _finite_or_none(dx),
            "dy_um": _finite_or_none(dy),
            "quality": _finite_or_none(q),
        }
        if not (np.isnan(dx) or np.isnan(dy)):
            valid.append((name, float(dx), float(dy), float(q)))

    best_cluster: list = []
    for _, dxi, dyi, _ in valid:
        cluster = [v for v in valid if (v[1] - dxi) ** 2 + (v[2] - dyi) ** 2 <= tolerance_um**2]
        if len(cluster) > len(best_cluster):
            best_cluster = cluster

    if best_cluster:
        dx_um = float(np.median([c[1] for c in best_cluster]))
        dy_um = float(np.median([c[2] for c in best_cluster]))
        quality = _finite_median([c[3] for c in best_cluster])
    else:
        dx_um = dy_um = float("nan")
        quality = 0.0

    confidence = len(best_cluster)
    return {
        "dx_um": dx_um,
        "dy_um": dy_um,
        "quality": quality,
        "confidence": confidence,
        "trusted": confidence >= min_agree,
        "agreeing": [c[0] for c in best_cluster],
        "per_method": per_method,
    }


# ──────────────────────────────────────────────────────────────────────
# Sign-convention helper
# ──────────────────────────────────────────────────────────────────────


def register_phase(
    ref: np.ndarray,
    tgt: np.ndarray,
    pixel_um: float,
) -> tuple[float, float]:
    """Phase cross-correlation, returns ``(dx_um, dy_um)``.

    Used by the calibration sign-convention phase only. Voting
    registration uses ``register_voting`` instead. Kept separate so
    that changes to one don't silently break the other.
    """
    shift, _, _ = phase_cross_correlation(
        ref.astype(np.float64),
        tgt.astype(np.float64),
        upsample_factor=100,
    )
    dy_px, dx_px = -shift[0], -shift[1]
    return dx_px * pixel_um, dy_px * pixel_um


# ──────────────────────────────────────────────────────────────────────
# Pair preparation for cookbook-side cross-magnification registration
# ──────────────────────────────────────────────────────────────────────


def _resample(img: np.ndarray, src_um: float, dst_um: float) -> np.ndarray:
    """Cubic resample. Cubic up, area down — the standard pair for
    image work."""
    scale = float(src_um) / float(dst_um)
    h, w = img.shape[:2]
    new_h = max(8, int(round(h * scale)))
    new_w = max(8, int(round(w * scale)))
    interp = cv2.INTER_CUBIC if scale > 1.0 else cv2.INTER_AREA
    return cv2.resize(img, (new_w, new_h), interpolation=interp)


def _crop_around(
    img: np.ndarray,
    centre_col: float,
    centre_row: float,
    half_size_px: int,
) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """Crop ``img`` around ``(centre_col, centre_row)`` by ±half_size,
    clipped at edges. Returns ``(crop, (left, top, right, bottom))``."""
    h, w = img.shape[:2]
    cc = int(round(centre_col))
    cr = int(round(centre_row))
    left = max(0, cc - half_size_px)
    right = min(w, cc + half_size_px)
    top = max(0, cr - half_size_px)
    bottom = min(h, cr + half_size_px)
    return img[top:bottom, left:right], (left, top, right, bottom)


def prepare_pair(
    source_img: np.ndarray,
    intermediate_img: np.ndarray,
    *,
    source_pixel_um: float,
    intermediate_pixel_um: float,
    source_cell_col: float,
    source_cell_row: float,
    intermediate_centre_col: float | None = None,
    intermediate_centre_row: float | None = None,
) -> dict:
    """Crop+resample two images to the same physical FOV at the same
    pixel size, ready for whole-frame voting registration.

    The image with the larger physical FOV is cropped to the smaller's
    FOV, centred on the picked cell in source / on the intermediate
    centre in intermediate. The image with the finer pixel size is
    resampled to the coarser pixel size.

    Returns a dict with:
        ``ref``           — source crop (matched shape + pixel size)
        ``tgt``           — intermediate crop (same)
        ``pixel_um``      — common pixel size
        ``source_cell_in_ref_px``       — (col, row) of the picked
            cell in the ``ref`` crop (sub-pixel)
        ``intermediate_centre_in_tgt_px`` — (col, row) of the
            intermediate FOV centre in the ``tgt`` crop
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

    src_crop, src_bbox = _crop_around(
        source_img,
        source_cell_col,
        source_cell_row,
        src_half_px,
    )
    int_crop, int_bbox = _crop_around(
        intermediate_img,
        intermediate_centre_col,
        intermediate_centre_row,
        int_half_px,
    )

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

    return {
        "ref": ref_img,
        "tgt": tgt_img,
        "pixel_um": float(common_pixel_um),
        "common_fov_um": float(common_fov_um),
        "source_cell_in_ref_px": (
            float(cell_col_in_ref),
            float(cell_row_in_ref),
        ),
        "intermediate_centre_in_tgt_px": (
            float(centre_col_in_tgt),
            float(centre_row_in_tgt),
        ),
    }


# ──────────────────────────────────────────────────────────────────────
# Sign-convention helper (D4)
# ──────────────────────────────────────────────────────────────────────


def classify_d4(matrix) -> tuple[str, np.ndarray, float]:
    """Snap a 2×2 fitted matrix to the nearest D4 reflection/rotation.

    Returns ``(label, canonical_matrix, frobenius_residual)``. The
    caller checks ``residual <= D4_RESIDUAL_MAX`` to accept the snap.
    """
    m = np.asarray(matrix, dtype=float)
    best_label, best_canonical, best_residual = None, None, float("inf")
    for label, canonical in D4_ELEMENTS.items():
        canonical_arr = np.asarray(canonical, dtype=float)
        residual = float(np.linalg.norm(m - canonical_arr))
        if residual < best_residual:
            best_label, best_canonical, best_residual = label, canonical_arr, residual
    return best_label, best_canonical, best_residual

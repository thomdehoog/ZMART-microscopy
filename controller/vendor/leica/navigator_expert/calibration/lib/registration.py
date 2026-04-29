"""Pure image-registration helpers for objective calibration."""

import cv2
import numpy as np
from skimage.feature import ORB, match_descriptors
from skimage.measure import ransac
from skimage.registration import phase_cross_correlation
from skimage.transform import EuclideanTransform


D4_ELEMENTS = {
    "+X +Y": [[+1, 0], [0, +1]], "+X -Y": [[+1, 0], [0, -1]],
    "-X +Y": [[-1, 0], [0, +1]], "-X -Y": [[-1, 0], [0, -1]],
    "+Y +X": [[0, +1], [+1, 0]], "+Y -X": [[0, +1], [-1, 0]],
    "-Y +X": [[0, -1], [+1, 0]], "-Y -X": [[0, -1], [-1, 0]],
}

VOTING_TOLERANCE_UM = 3.0
VOTING_MIN_AGREE = 2
MASK_PCT_DEFAULT = 30


def to_uint8(img):
    f = img.astype(np.float64)
    return (f / (f.max() or 1) * 255).astype(np.uint8)


def finite_median(values, *, default=0.0):
    """Median of finite values only; used for optional quality scores."""
    finite = [float(v) for v in values if np.isfinite(v)]
    if not finite:
        return float(default)
    return float(np.median(finite))


def finite_or_none(value):
    value = float(value)
    return value if np.isfinite(value) else None


def register_phase(ref, tgt, pixel_um):
    """Phase cross-correlation. Returns (dx_um, dy_um) of tgt relative to ref.

    Used by the sign-convention phase only. The D4 fit relies on this
    specific sign convention. XY residual and verification use
    ``register_voting`` instead.
    """
    shift, _, _ = phase_cross_correlation(
        ref.astype(np.float64), tgt.astype(np.float64), upsample_factor=100,
    )
    dy_px, dx_px = -shift[0], -shift[1]
    return dx_px * pixel_um, dy_px * pixel_um


# All four registration methods return (dx_um, dy_um, quality) in the same
# sign convention as ``register_phase``: positive shift = TGT features at
# +x/+y relative to REF features (i.e. the negative of skimage's
# phase_cross_correlation output, which returns the shift to apply to tgt
# to align it with ref). ``image_to_stage`` is fitted against this
# convention; flipping the sign in any one method silently breaks the
# Phase-4 residual application.
def _method_phase(ref, tgt, pixel_um, _mask_pct):
    shift, error, _ = phase_cross_correlation(
        ref.astype(np.float64), tgt.astype(np.float64), upsample_factor=100,
    )
    dy_px, dx_px = -shift[0], -shift[1]
    return dx_px * pixel_um, dy_px * pixel_um, 1.0 - float(error)


def _method_masked(ref, tgt, pixel_um, mask_pct):
    ref_mask = ref > np.percentile(ref, mask_pct)
    tgt_mask = tgt > np.percentile(tgt, mask_pct)
    shift, error, _ = phase_cross_correlation(
        ref.astype(np.float64), tgt.astype(np.float64), upsample_factor=100,
        reference_mask=ref_mask, moving_mask=tgt_mask,
    )
    dy_px, dx_px = -shift[0], -shift[1]
    return dx_px * pixel_um, dy_px * pixel_um, 1.0 - float(error)


def _method_cv2_ncc(ref, tgt, pixel_um, _mask_pct):
    ref8 = to_uint8(ref)
    tgt8 = to_uint8(tgt)
    h, w = tgt8.shape
    # Use central crop as the template; robust against edge changes.
    template = tgt8[h // 4: 3 * h // 4, w // 4: 3 * w // 4]
    result = cv2.matchTemplate(ref8, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    dx_px = max_loc[0] + template.shape[1] / 2.0 - w / 2.0
    dy_px = max_loc[1] + template.shape[0] / 2.0 - h / 2.0
    return -dx_px * pixel_um, -dy_px * pixel_um, float(max_val)


def _method_orb(ref, tgt, pixel_um, _mask_pct):
    ref_n = to_uint8(ref)
    tgt_n = to_uint8(tgt)
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
        (src, dst), EuclideanTransform, min_samples=3,
        residual_threshold=5, max_trials=1000,
    )
    if model is None or inliers is None:
        return float("nan"), float("nan"), 0.0
    dy_px = model.translation[0]
    dx_px = model.translation[1]
    return -dx_px * pixel_um, -dy_px * pixel_um, float(inliers.sum() / len(matches))


_VOTING_METHODS = [
    ("phase", _method_phase),
    ("masked", _method_masked),
    ("ncc", _method_cv2_ncc),
    ("orb", _method_orb),
]


def register_voting(ref, tgt, pixel_um, *, mask_pct=MASK_PCT_DEFAULT,
                    tolerance_um=VOTING_TOLERANCE_UM,
                    min_agree=VOTING_MIN_AGREE):
    """Multi-method voting registration.

    Runs four methods, finds the largest cluster whose (dx, dy) agree within
    ``tolerance_um``, and returns the median of that cluster.
    """
    per_method = {}
    valid = []
    for name, fn in _VOTING_METHODS:
        try:
            dx, dy, q = fn(ref, tgt, pixel_um, mask_pct)
        except Exception as exc:
            per_method[name] = {"error": str(exc)}
            continue
        per_method[name] = {
            "dx_um": finite_or_none(dx),
            "dy_um": finite_or_none(dy),
            "quality": finite_or_none(q),
        }
        if not (np.isnan(dx) or np.isnan(dy)):
            valid.append((name, float(dx), float(dy), float(q)))

    best_cluster = []
    for _, dxi, dyi, _ in valid:
        cluster = [
            v for v in valid
            if (v[1] - dxi) ** 2 + (v[2] - dyi) ** 2 <= tolerance_um ** 2
        ]
        if len(cluster) > len(best_cluster):
            best_cluster = cluster

    if best_cluster:
        dxs = [c[1] for c in best_cluster]
        dys = [c[2] for c in best_cluster]
        qs = [c[3] for c in best_cluster]
        dx_um = float(np.median(dxs))
        dy_um = float(np.median(dys))
        quality = finite_median(qs)
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


def brenner(img):
    f = img.astype(np.float64)
    dx = f[:, 2:] - f[:, :-2]
    return float((dx ** 2).mean())


def subpixel_peak(scores, peak):
    if peak <= 0 or peak >= len(scores) - 1:
        return float(peak)
    y0, y1, y2 = scores[peak - 1], scores[peak], scores[peak + 1]
    denom = 2 * (2 * y1 - y0 - y2)
    if abs(denom) < 1e-10:
        return float(peak)
    return peak + (y0 - y2) / denom


def brenner_focus(stack, z_step):
    scores = [brenner(stack[i]) for i in range(stack.shape[0])]
    peak = int(np.argmax(scores))
    peak_sub = subpixel_peak(scores, peak)
    return {
        "peak_slice": peak,
        "peak_sub": float(peak_sub),
        "peak_um": float(peak_sub * z_step),
        "scores": [float(s) for s in scores],
    }


def classify_d4(matrix):
    """Return (label, canonical, residual) of the nearest D4 element."""
    m = np.asarray(matrix, dtype=float)
    best_label, best_canonical, best_residual = None, None, float("inf")
    for label, canonical in D4_ELEMENTS.items():
        canonical_arr = np.asarray(canonical, dtype=float)
        residual = float(np.linalg.norm(m - canonical_arr))
        if residual < best_residual:
            best_label, best_canonical, best_residual = label, canonical_arr, residual
    return best_label, best_canonical, best_residual

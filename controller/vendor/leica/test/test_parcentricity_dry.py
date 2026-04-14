"""
Parcentricity Registration — Dry Validation
============================================
Tests the registration pipeline on synthetic or real images with known
computational shifts.  No stage movement in either mode.

Three estimators are run independently and then voted on:
  PCC    - masked phase cross-correlation (sub-pixel, dim-image robust)
  NCC    - OpenCV matchTemplate (integer pixel, fast sanity check)
  RANSAC - ORB keypoints + brute-force matching + RANSAC consensus translation

Voting: find the largest cluster of estimators that agree within
VOTE_THRESHOLD_UM, take their mean.  Reports confidence as n_voters/n_total.

Convention:
    tgt = ndi_shift(ref, (row_shift, col_shift))
      -> features move by (+col_shift, +row_shift) px in (X, Y)
    each estimator returns (dx_um, dy_um) such that:
      dx_um ~ -col_shift * pixel_um
      dy_um ~ -row_shift * pixel_um

Usage:
    python test_parcentricity_dry.py                  # synthetic image
    python test_parcentricity_dry.py --acquire        # acquire real image first
    python test_parcentricity_dry.py --acquire --job Overview
"""

import argparse
import sys
import numpy as np
from scipy.ndimage import shift as ndi_shift
import cv2
from skimage.registration import phase_cross_correlation

parser = argparse.ArgumentParser()
parser.add_argument("--acquire", action="store_true",
                    help="Acquire one real image from LAS X instead of synthetic")
parser.add_argument("--job", default="Overview",
                    help="LAS X job name when --acquire is set (default: Overview)")
args = parser.parse_args()

PIXEL_UM = 0.5          # fallback; overridden by actual pixel size when --acquire
IMAGE_SIZE = 512
VOTE_THRESHOLD_UM = 1.0  # estimators within this distance are considered agreeing


# ── Synthetic image ───────────────────────────────────────────────────────

def make_image(size=IMAGE_SIZE, n_blobs=60, seed=0):
    """Gaussian blobs on a dark background — like dim fluorescence."""
    rng = np.random.default_rng(seed)
    img = np.zeros((size, size), dtype=np.float32)
    rows = np.arange(size, dtype=np.float32)[:, None]
    cols = np.arange(size, dtype=np.float32)[None, :]
    for _ in range(n_blobs):
        cy = rng.uniform(size * 0.1, size * 0.9)
        cx = rng.uniform(size * 0.1, size * 0.9)
        r  = rng.uniform(3, 18)
        img += rng.uniform(0.3, 1.0) * np.exp(
            -((rows - cy)**2 + (cols - cx)**2) / (2 * r**2))
    img += rng.normal(0, 0.01, img.shape).clip(0)
    return img


# ── Acquire real image ────────────────────────────────────────────────────

def acquire_real(job):
    """Connect to LAS X, acquire one frame, return (image, pixel_um)."""
    import time
    import tifffile
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    from LasxApi import PYLICamApiConnector as lasx_api
    import lasx as drv
    from lasx.readers import get_job_settings, get_lasx_settings
    from lasx.utils import parse_tile_geometry
    from lasx.prechecks import check_idle

    client = lasx_api.LasxApiClientPyModel
    if not client.Connect("PythonClient"):
        print("ABORT: cannot connect to LAS X")
        sys.exit(1)
    assert drv.ping(client), "ping failed"

    drv.set_stage_limits(
        x_min=1000, x_max=130000,
        y_min=1000, y_max=100000,
        z_galvo_min=-200, z_galvo_max=200,
        z_wide_min=0, z_wide_max=25000,
    )

    settings = get_job_settings(client, job)
    geo = parse_tile_geometry(settings)
    pixel_um = geo["pixel_w_um"]
    print(f"  Job: {job}  |  pixel: {pixel_um:.4f} um  |  size: {geo['pixels_x']}x{geo['pixels_y']}")

    if not check_idle(client, timeout=30)["success"]:
        print("  WARNING: scanner not idle before acquire")

    baseline = drv.read_relative_path(client)
    t0 = time.time()
    r = drv.acquire(client, job)
    if not r or not r["success"]:
        print(f"  ABORT: acquire failed: {r}")
        sys.exit(1)

    media = get_lasx_settings()["export"]["media_path"]
    det = drv.detect_new_files(client, baseline, media, acquire_start=t0)
    if not det["success"]:
        print(f"  ABORT: file detection failed: {det.get('error')}")
        sys.exit(1)

    img = tifffile.imread(str(sorted(det["image_files"])[0]))
    img = img[0] if img.ndim == 3 else img
    img = img.astype(np.float32)
    print(f"  Acquired: {img.shape[1]}x{img.shape[0]} px  "
          f"min={img.min():.0f}  max={img.max():.0f}")
    return img, pixel_um


# ── Estimators ────────────────────────────────────────────────────────────

def _to_u8(a):
    return (a.astype(np.float64) / (a.max() or 1) * 255).astype(np.uint8)


def est_pcc(ref, tgt, pixel_um, mask_pct=30):
    """Masked phase cross-correlation (sub-pixel)."""
    ref_mask = ref > np.percentile(ref, mask_pct)
    tgt_mask = tgt > np.percentile(tgt, mask_pct)
    sub, _, _ = phase_cross_correlation(
        ref.astype(np.float64), tgt.astype(np.float64),
        upsample_factor=100,
        reference_mask=ref_mask, moving_mask=tgt_mask)
    return {"name": "PCC", "dx_um": sub[1] * pixel_um, "dy_um": sub[0] * pixel_um}


def est_ncc(ref, tgt, pixel_um):
    """OpenCV NCC on center 50% crop of tgt (integer pixel)."""
    r8, t8 = _to_u8(ref), _to_u8(tgt)
    H, W = t8.shape
    m = H // 4
    tmpl = t8[m:H-m, m:W-m]
    res = cv2.matchTemplate(r8, tmpl, cv2.TM_CCOEFF_NORMED)
    _, q, _, loc = cv2.minMaxLoc(res)
    dx = (loc[0] + tmpl.shape[1] / 2 - W / 2) * pixel_um
    dy = (loc[1] + tmpl.shape[0] / 2 - H / 2) * pixel_um
    return {"name": "NCC", "dx_um": dx, "dy_um": dy, "quality": float(q)}


def est_ransac(ref, tgt, pixel_um, n_features=2000, ransac_iters=300, inlier_px=2.0):
    """
    ORB keypoints + brute-force matching + RANSAC consensus translation.
    Features in tgt appear shifted relative to ref, so delta = tgt_kp - ref_kp
    gives (col_shift, row_shift), and we return (-col*px, -row*px).
    Returns None if not enough features are found.
    """
    r8, t8 = _to_u8(ref), _to_u8(tgt)
    orb = cv2.ORB_create(nfeatures=n_features)
    kp1, des1 = orb.detectAndCompute(r8, None)
    kp2, des2 = orb.detectAndCompute(t8, None)

    if des1 is None or des2 is None or len(kp1) < 8 or len(kp2) < 8:
        return {"name": "RANSAC", "dx_um": None, "dy_um": None,
                "inliers": 0, "matches": 0, "note": "too few keypoints"}

    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = bf.match(des1, des2)
    if len(matches) < 4:
        return {"name": "RANSAC", "dx_um": None, "dy_um": None,
                "inliers": 0, "matches": len(matches), "note": "too few matches"}

    pts1 = np.array([kp1[m.queryIdx].pt for m in matches])  # (x, y) = (col, row)
    pts2 = np.array([kp2[m.trainIdx].pt for m in matches])
    deltas = pts2 - pts1   # each match: (col_shift_px, row_shift_px)

    # RANSAC: find consensus translation
    rng = np.random.default_rng(0)
    best_inliers = np.array([], dtype=int)
    best_dx_px, best_dy_px = 0.0, 0.0
    for _ in range(ransac_iters):
        idx = rng.integers(len(deltas))
        hyp = deltas[idx]
        dist = np.linalg.norm(deltas - hyp, axis=1)
        inliers = np.where(dist < inlier_px)[0]
        if len(inliers) > len(best_inliers):
            best_inliers = inliers
            best_dx_px = float(np.median(deltas[inliers, 0]))
            best_dy_px = float(np.median(deltas[inliers, 1]))

    inlier_ratio = len(best_inliers) / len(matches)
    # deltas are (col_shift, row_shift) → dx_um = -col*px, dy_um = -row*px
    return {
        "name": "RANSAC",
        "dx_um": -best_dx_px * pixel_um,
        "dy_um": -best_dy_px * pixel_um,
        "inliers": len(best_inliers),
        "matches": len(matches),
        "inlier_ratio": inlier_ratio,
    }


# ── Voting ────────────────────────────────────────────────────────────────

def vote(estimates, threshold_um=VOTE_THRESHOLD_UM):
    """
    Find the largest cluster of estimators agreeing within threshold_um.
    Returns the cluster mean and a confidence label.
    """
    valid = [e for e in estimates if e.get("dx_um") is not None]
    if not valid:
        return {"dx_um": float("nan"), "dy_um": float("nan"),
                "voters": [], "confidence": "none"}

    best_cluster = []
    for i, a in enumerate(valid):
        cluster = [a]
        for j, b in enumerate(valid):
            if i == j:
                continue
            d = ((a["dx_um"] - b["dx_um"])**2 + (a["dy_um"] - b["dy_um"])**2) ** 0.5
            if d < threshold_um:
                cluster.append(b)
        if len(cluster) > len(best_cluster):
            best_cluster = cluster

    dx = float(np.mean([e["dx_um"] for e in best_cluster]))
    dy = float(np.mean([e["dy_um"] for e in best_cluster]))
    voters = [e["name"] for e in best_cluster]

    n = len(best_cluster)
    total = len(valid)
    if n >= 3:
        conf = "high"
    elif n == 2:
        conf = "medium"
    else:
        conf = "low"
    if total < 2:
        conf = "low"

    return {"dx_um": dx, "dy_um": dy, "voters": voters,
            "confidence": conf, "n_voters": n, "n_total": total}


# ── Test cases ────────────────────────────────────────────────────────────

CASES = [
    ("right 20px",              0.0,  20.0),
    ("down  20px",             20.0,   0.0),
    ("right 14.6 + up 9.6",    -9.6,  14.6),
    ("left 10 + down 16.4",    16.4, -10.0),
    ("sub-pixel (0.6r, 1.0c)",  0.6,   1.0),
    ("zero shift",              0.0,   0.0),
    ("diagonal 28px",          20.0,  20.0),
]


def run(ref, pixel_um, label):
    H, W = ref.shape
    print(f"\nmode={label}  pixel_um={pixel_um:.4f}  image={W}x{H}"
          f"  vote_threshold={VOTE_THRESHOLD_UM} um\n")

    hdr = (f"{'case':<28}  {'expected':>16}  {'voted':>16}  "
           f"{'err':>7}  {'conf':<6}  {'voters':<20}  "
           f"{'PCC':>16}  {'NCC':>16}  {'RANSAC':>16}")
    print(hdr)
    print("-" * len(hdr))

    all_ok = True
    for name, row_s, col_s in CASES:
        tgt = ndi_shift(ref, (row_s, col_s), mode="constant", cval=0)

        pcc    = est_pcc(ref, tgt, pixel_um)
        ncc    = est_ncc(ref, tgt, pixel_um)
        ransac = est_ransac(ref, tgt, pixel_um)

        result = vote([pcc, ncc, ransac])

        exp_dx = -col_s * pixel_um
        exp_dy = -row_s * pixel_um
        err = ((result["dx_um"] - exp_dx)**2 + (result["dy_um"] - exp_dy)**2) ** 0.5

        flag = ""
        if err > 1.0:
            flag = " <-FAIL"
            all_ok = False

        def fmt(e):
            if e.get("dx_um") is None:
                return f"{'n/a':>16}"
            return f"({e['dx_um']:+6.2f},{e['dy_um']:+6.2f})"

        voters_str = "+".join(result["voters"])
        print(f"  {name:<26}  ({exp_dx:+6.2f},{exp_dy:+6.2f})  "
              f"({result['dx_um']:+6.2f},{result['dy_um']:+6.2f})  "
              f"{err:6.3f}  {result['confidence']:<6}  {voters_str:<20}  "
              f"{fmt(pcc)}  {fmt(ncc)}  {fmt(ransac)}{flag}")

    print()
    print("PASS - all within 1 um" if all_ok else "FAIL - see flagged rows")
    print()


if __name__ == "__main__":
    if args.acquire:
        print(f"\nAcquiring real image (job={args.job})...")
        ref, pixel_um = acquire_real(args.job)
        run(ref, pixel_um, label=f"real/{args.job}")
    else:
        ref = make_image(seed=42)
        run(ref, PIXEL_UM, label="synthetic")

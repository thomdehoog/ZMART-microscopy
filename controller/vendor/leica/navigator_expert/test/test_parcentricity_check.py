"""
Parcentricity Check - Iterative Correction
==========================================
Measures and corrects the parcentric XY offset between two objectives.
The user manages objective switching and focus manually.

Flow:
  [pause]  1 -- Acquire reference image on objective A (overview / low-mag)
  [pause]  2 -- Switch to objective B, refocus; acquire target, measure offset
           3 -- Iterative correction loop:
                  repeat until residual < threshold or max passes reached:
                    apply calibrated stage correction
                    acquire image
                    register against reference
                    report residual

Calibration (validated empirically, see parcentricity_registration_progress.md):
  stage X -> image -Y  (scale_x ~ 0.97)
  stage Y -> image +X  (scale_y ~ 0.89)
  corr_x =  image_dy / scale_x
  corr_y = -image_dx / scale_y

Why iterative?
  The stage scale factor is non-linear for small displacements (backlash /
  stiction).  The first pass corrects the bulk of the offset (~10-50 um, where
  scale is close to the calibrated value).  Subsequent passes mop up the
  residual, which falls in the non-linear sub-5-um regime.  Typically 3-4
  passes converge to sub-pixel (< 0.3 um).

Test mode (--test):
  Applies a known random stage displacement before step 2 to simulate a
  parcentric offset, then restores the stage at the end.

Usage:
  python test_parcentricity_check.py
  python test_parcentricity_check.py --job Overview --threshold 0.3
  python test_parcentricity_check.py --scale-x 0.97 --scale-y 0.94
  python test_parcentricity_check.py --test --test-move 20
"""

import argparse
import sys
import time
import json
import numpy as np
from pathlib import Path
from datetime import datetime

import tifffile
import cv2
from skimage.registration import phase_cross_correlation

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

parser = argparse.ArgumentParser(description="Parcentricity check - iterative correction")
parser.add_argument("--job", default="Overview",
                    help="LAS X job name (default: Overview)")
parser.add_argument("--scale-x", type=float, default=0.97,
                    help="Stage X -> image -Y scale factor (default 0.97)")
parser.add_argument("--scale-y", type=float, default=0.89,
                    help="Stage Y -> image +X scale factor (default 0.89)")
parser.add_argument("--threshold", type=float, default=0.5,
                    help="Stop when residual drops below this value in um (default 0.5)")
parser.add_argument("--max-passes", type=int, default=4,
                    help="Maximum correction passes (default 4)")
parser.add_argument("--settle", type=float, default=1.0,
                    help="Settle time after each stage move in s (default 1.0)")
parser.add_argument("--test", action="store_true",
                    help="Self-test: skip pauses, simulate parcentric offset via stage move")
parser.add_argument("--test-move", type=float, default=20.0,
                    help="Displacement magnitude for self-test in um (default 20)")
args = parser.parse_args()

import logging
logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from LasxApi import PYLICamApiConnector as lasx_api
import lasx as drv
from lasx.readers import get_job_settings, get_lasx_settings
from lasx.utils import parse_tile_geometry
from lasx.prechecks import check_idle


# -- Connect ---------------------------------------------------------------

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

_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
out_dir = (Path(__file__).resolve().parent.parent
           / "config" / "alignment" / f"parcentric_{_ts}")
out_dir.mkdir(parents=True, exist_ok=True)

settings  = get_job_settings(client, args.job)
pixel_um  = parse_tile_geometry(settings)["pixel_w_um"]

print(f"Output:      {out_dir}")
print(f"Job:         {args.job}  |  pixel: {pixel_um:.4f} um/px")
print(f"Calibration: scale_x={args.scale_x}  scale_y={args.scale_y}")
print(f"Convergence: residual < {args.threshold} um  |  max {args.max_passes} passes")


# -- Helpers ---------------------------------------------------------------

def pause(msg):
    if args.test:
        print(f"\n[test] {msg}")
        return
    print(f"\n>>> {msg}")
    input("    Press Enter to continue... ")
    print()


def acquire(label):
    if not check_idle(client, timeout=30)["success"]:
        print(f"  WARNING: scanner not idle before {label}")
    baseline = drv.read_relative_path(client)
    t0 = time.time()
    r = drv.acquire(client, args.job)
    if not r or not r["success"]:
        print(f"ABORT: acquire failed ({label}): {r}")
        sys.exit(1)
    media = get_lasx_settings()["export"]["media_path"]
    det = drv.detect_new_files(client, baseline, media, acquire_start=t0)
    if not det["success"]:
        print(f"ABORT: file detection failed ({label}): {det.get('error')}")
        sys.exit(1)
    img = tifffile.imread(str(sorted(det["image_files"])[0]))
    img = img[0] if img.ndim == 3 else img
    img = img.astype(np.float32)
    tifffile.imwrite(str(out_dir / f"{label}.tif"), img)
    print(f"  {label}: {img.shape[1]}x{img.shape[0]}  max={img.max():.0f}")
    return img


def _to_u8(a):
    return (a.astype(np.float64) / (a.max() or 1) * 255).astype(np.uint8)


def est_pcc(ref, tgt, px, mask_pct=30):
    # NOTE: integer-pixel precision when masks are supplied (~+/-0.5 px)
    ref_mask = ref > np.percentile(ref, mask_pct)
    tgt_mask = tgt > np.percentile(tgt, mask_pct)
    sub, _, _ = phase_cross_correlation(
        ref.astype(np.float64), tgt.astype(np.float64),
        upsample_factor=100, reference_mask=ref_mask, moving_mask=tgt_mask)
    return {"name": "PCC",
            "dx_um": float(sub[1] * px), "dy_um": float(sub[0] * px),
            "dx_px": float(sub[1]),       "dy_px": float(sub[0])}


def est_ncc(ref, tgt, px):
    # Max detectable shift +/-W/4 px; returns None if at boundary (out of range)
    r8, t8 = _to_u8(ref), _to_u8(tgt)
    H, W = t8.shape
    m = H // 4
    tmpl = t8[m:H-m, m:W-m]
    res = cv2.matchTemplate(r8, tmpl, cv2.TM_CCOEFF_NORMED)
    _, q, _, loc = cv2.minMaxLoc(res)
    rH, rW = res.shape
    margin = 2
    if (loc[0] < margin or loc[0] >= rW - margin
            or loc[1] < margin or loc[1] >= rH - margin):
        return {"name": "NCC", "dx_um": None, "dy_um": None,
                "quality": float(q), "note": "out of NCC range"}
    dx = (loc[0] + tmpl.shape[1] / 2 - W / 2) * px
    dy = (loc[1] + tmpl.shape[0] / 2 - H / 2) * px
    return {"name": "NCC",
            "dx_um": float(dx), "dy_um": float(dy), "quality": float(q)}


def est_ransac(ref, tgt, px, n_features=2000, ransac_iters=300, inlier_px=2.0):
    r8, t8 = _to_u8(ref), _to_u8(tgt)
    orb = cv2.ORB_create(nfeatures=n_features)
    kp1, des1 = orb.detectAndCompute(r8, None)
    kp2, des2 = orb.detectAndCompute(t8, None)
    if des1 is None or des2 is None or len(kp1) < 8 or len(kp2) < 8:
        return {"name": "RANSAC", "dx_um": None, "dy_um": None,
                "note": "too few keypoints"}
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = bf.match(des1, des2)
    if len(matches) < 4:
        return {"name": "RANSAC", "dx_um": None, "dy_um": None,
                "note": "too few matches"}
    pts1 = np.array([kp1[m.queryIdx].pt for m in matches])
    pts2 = np.array([kp2[m.trainIdx].pt for m in matches])
    deltas = pts2 - pts1
    rng = np.random.default_rng(0)
    best_in, best_dx, best_dy = np.array([], dtype=int), 0.0, 0.0
    for _ in range(ransac_iters):
        idx = rng.integers(len(deltas))
        inliers = np.where(
            np.linalg.norm(deltas - deltas[idx], axis=1) < inlier_px)[0]
        if len(inliers) > len(best_in):
            best_in  = inliers
            best_dx  = float(np.median(deltas[inliers, 0]))
            best_dy  = float(np.median(deltas[inliers, 1]))
    return {"name": "RANSAC",
            "dx_um": float(-best_dx * px), "dy_um": float(-best_dy * px),
            "inliers": len(best_in), "matches": len(matches)}


def vote(estimates, threshold_um=1.0):
    valid = [e for e in estimates if e.get("dx_um") is not None]
    if not valid:
        return {"dx_um": float("nan"), "dy_um": float("nan"),
                "voters": [], "confidence": "none"}
    best_cluster = []
    for a in valid:
        cluster = [a] + [
            b for b in valid if b is not a
            and ((a["dx_um"] - b["dx_um"])**2
                 + (a["dy_um"] - b["dy_um"])**2) ** 0.5 < threshold_um]
        if len(cluster) > len(best_cluster):
            best_cluster = cluster
    n, total = len(best_cluster), len(valid)
    if n == 1 and total >= 2:
        return {"dx_um": float("nan"), "dy_um": float("nan"),
                "voters": [], "confidence": "none",
                "note": "no consensus"}
    dx   = float(np.mean([e["dx_um"] for e in best_cluster]))
    dy   = float(np.mean([e["dy_um"] for e in best_cluster]))
    conf = "high" if n >= 3 else ("medium" if n == 2 else "low")
    return {"dx_um": dx, "dy_um": dy,
            "voters": [e["name"] for e in best_cluster],
            "confidence": conf}


def register(ref, tgt, label=""):
    pcc    = est_pcc(ref, tgt, pixel_um)
    ncc    = est_ncc(ref, tgt, pixel_um)
    ransac = est_ransac(ref, tgt, pixel_um)
    result = vote([pcc, ncc, ransac])
    dist   = (result["dx_um"]**2 + result["dy_um"]**2) ** 0.5
    voters = "+".join(result["voters"]) or "none"
    tag = f"[{label}] " if label else ""
    print(f"  {tag}({result['dx_um']:+.2f}, {result['dy_um']:+.2f}) um  "
          f"dist={dist:.2f}  conf={result['confidence']}  voters={voters}")
    if pcc.get("dx_um") is not None:
        print(f"    PCC    ({pcc['dx_um']:+.2f}, {pcc['dy_um']:+.2f}) um  "
              f"({pcc['dx_px']:+.1f}, {pcc['dy_px']:+.1f}) px")
    if ncc.get("dx_um") is not None:
        print(f"    NCC    ({ncc['dx_um']:+.2f}, {ncc['dy_um']:+.2f}) um  "
              f"q={ncc.get('quality', 0):.3f}")
    else:
        print(f"    NCC    n/a  ({ncc.get('note', '')})")
    if ransac.get("dx_um") is not None:
        print(f"    RANSAC ({ransac['dx_um']:+.2f}, {ransac['dy_um']:+.2f}) um  "
              f"inliers={ransac.get('inliers', 0)}/{ransac.get('matches', 0)}")
    else:
        print(f"    RANSAC n/a  ({ransac.get('note', '')})")
    return result, dist


def overlay(a, b):
    an = a.astype(np.float64) / (a.max() or 1)
    bn = b.astype(np.float64) / (b.max() or 1)
    rgb = np.zeros((*a.shape, 3))
    rgb[..., 1] = an   # green  = reference
    rgb[..., 0] = bn   # cyan   = target (R + B)
    rgb[..., 2] = bn
    return np.clip(rgb, 0, 1)


# -- Step 1: reference image -----------------------------------------------

pause("Set up OVERVIEW objective and focus. Press Enter to acquire reference.")

print("\n[Step 1] Acquiring reference...")
img_ref = acquire("step1_ref")

# -- Step 2: target image + initial offset measurement ---------------------

pause("Switch to ACQUISITION objective and refocus. "
      "Press Enter to acquire and measure the parcentric offset.")

origin = drv.get_xy(client)   # saved for test-mode restoration

if args.test:
    rng    = np.random.default_rng()
    test_x = float(rng.choice([-1, 1])) * rng.uniform(
        args.test_move * 0.8, args.test_move * 1.2)
    test_y = float(rng.choice([-1, 1])) * rng.uniform(
        args.test_move * 0.8, args.test_move * 1.2)
    print(f"[test] Simulating parcentric offset: ({test_x:+.1f}, {test_y:+.1f}) um")
    drv.move_xy(client, origin["x_um"] + test_x, origin["y_um"] + test_y)
    time.sleep(args.settle)

pos = drv.get_xy(client)

print("\n[Step 2] Acquiring target...")
img_tgt = acquire("step2_target")

print("\n  Registration (ref vs target):")
result, dist0 = register(img_ref, img_tgt, "initial offset")

if np.isnan(result["dx_um"]):
    print("ABORT: registration returned no consensus -- check image quality / overlap")
    sys.exit(1)

print(f"\n  Initial offset: {dist0:.2f} um")

# -- Step 3: iterative correction loop -------------------------------------

history = [{
    "pass": 0, "label": "initial",
    "dx_um": result["dx_um"], "dy_um": result["dy_um"], "dist_um": dist0,
    "confidence": result["confidence"], "voters": result["voters"],
}]
images    = [img_ref, img_tgt]   # ref + target + corrected images per pass
converged = dist0 < args.threshold
pass_num  = 0

if converged:
    print(f"\n  Offset already within threshold ({args.threshold} um) -- "
          f"no correction needed.")
else:
    print(f"\n[Step 3] Correction loop  "
          f"(stop when < {args.threshold} um, max {args.max_passes} passes)\n")
    print(f"  {'Pass':>5}  {'Correction (um)':>20}  {'Residual (um)':>14}  "
          f"{'Improved':>10}  Conf / Voters")
    print("  " + "-" * 72)

    while pass_num < args.max_passes:
        pass_num += 1

        # Convert measured image shift to required stage correction
        # image_dy = -scale_x * stage_x  =>  corr_x = dy / scale_x
        # image_dx =  scale_y * stage_y  =>  corr_y = -dx / scale_y
        corr_x =  result["dy_um"] / args.scale_x
        corr_y = -result["dx_um"] / args.scale_y

        drv.move_xy(client, pos["x_um"] + corr_x, pos["y_um"] + corr_y)
        time.sleep(args.settle)
        pos = drv.get_xy(client)

        img_pass = acquire(f"pass{pass_num:02d}")
        images.append(img_pass)

        result, dist = register(img_ref, img_pass)

        prev_dist   = history[-1]["dist_um"]
        improvement = prev_dist - dist
        voters      = "+".join(result["voters"]) or "none"
        print(f"  {pass_num:>5}  ({corr_x:+8.2f}, {corr_y:+8.2f})  "
              f"{dist:>12.2f}  {improvement:>+10.2f}  "
              f"{result['confidence']} / {voters}")

        history.append({
            "pass": pass_num, "label": f"pass{pass_num:02d}",
            "dx_um": result["dx_um"], "dy_um": result["dy_um"],
            "dist_um": dist,
            "corr_x_um": corr_x, "corr_y_um": corr_y,
            "confidence": result["confidence"], "voters": result["voters"],
        })

        if np.isnan(result["dx_um"]):
            print(f"\n  WARNING: no consensus at pass {pass_num} -- stopping")
            break

        converged = dist < args.threshold
        if converged:
            print(f"\n  Converged at pass {pass_num}  "
                  f"({dist:.2f} um < threshold {args.threshold} um)")
            break

    if not converged and pass_num >= args.max_passes:
        print(f"\n  Max passes ({args.max_passes}) reached.  "
              f"Final residual: {history[-1]['dist_um']:.2f} um")

# -- Restore (test mode only) ----------------------------------------------

if args.test:
    print(f"\n[test] Restoring stage to "
          f"({origin['x_um']:.1f}, {origin['y_um']:.1f}) um")
    drv.move_xy(client, origin["x_um"], origin["y_um"])
    time.sleep(args.settle)

# -- Summary ---------------------------------------------------------------

final = history[-1]
total_cx = sum(h.get("corr_x_um", 0.0) for h in history)
total_cy = sum(h.get("corr_y_um", 0.0) for h in history)

print(f"\n{'=' * 52}")
print(f"  Parcentricity Check  {_ts}")
print(f"{'=' * 52}")
if args.test:
    print(f"  Test offset:  ({test_x:+.1f}, {test_y:+.1f}) um")
print(f"  Job:          {args.job}  ({pixel_um:.4f} um/px)")
print(f"  Initial:      {dist0:.2f} um")
print(f"  Final:        {final['dist_um']:.2f} um  ({final['confidence']})")
print(f"  Improvement:  {dist0 - final['dist_um']:+.2f} um  "
      f"({(dist0 - final['dist_um']) / dist0 * 100:.0f}%)"
      if dist0 > 0 else "")
print(f"  Passes:       {pass_num}")
print(f"  Converged:    {'yes' if converged else 'no'}")
print(f"  Total stage:  ({total_cx:+.2f}, {total_cy:+.2f}) um")
print(f"  Output:       {out_dir}")

# -- Plot ------------------------------------------------------------------

n_imgs = len(images)                     # ref + target + one per pass
ncols  = min(n_imgs, 5)
fig    = plt.figure(figsize=(6 * ncols, 12))
fig.patch.set_facecolor("white")
gs = fig.add_gridspec(2, ncols, hspace=0.4, wspace=0.2)

# Top row: overlay images (green = ref, cyan = acquired)
col_labels = (["Reference", "Before (target)"]
              + [f"Pass {i}" for i in range(1, pass_num + 1)])

for col in range(ncols):
    ax = fig.add_subplot(gs[0, col])
    if col == 0:
        ax.imshow(images[0], cmap="gray")
        ax.set_title("Reference", fontsize=10)
    else:
        ax.imshow(overlay(images[0], images[col]))
        h = history[col - 1]   # history[0]=initial, history[1]=after pass1, ...
        dist_val = h["dist_um"]
        color = "#006600" if dist_val < args.threshold else "#CC0000"
        ax.set_title(f"{col_labels[col]}\n{dist_val:.2f} um",
                     fontsize=10, color=color)
    ax.axis("off")

# Bottom row: convergence plot spanning all columns
ax_conv = fig.add_subplot(gs[1, :])
pass_xs = [h["pass"] for h in history]
dist_ys = [h["dist_um"] for h in history]
ax_conv.plot(pass_xs, dist_ys, "o-", markersize=8, linewidth=2)
ax_conv.axhline(args.threshold, linestyle="--", color="green", alpha=0.7,
                label=f"threshold = {args.threshold} um")
for px_val, dy_val in zip(pass_xs, dist_ys):
    ax_conv.annotate(f"{dy_val:.2f}",
                     (px_val, dy_val), textcoords="offset points",
                     xytext=(0, 8), ha="center", fontsize=9)
ax_conv.set_xlabel("Correction pass  (0 = before any correction)")
ax_conv.set_ylabel("Residual offset (um)")
ax_conv.set_title("Convergence")
ax_conv.set_xticks(pass_xs)
ax_conv.legend()
ax_conv.grid(True, alpha=0.3)

fig.suptitle(f"Parcentricity Check  {_ts}  job={args.job}",
             fontsize=13, fontweight="bold")
fig.savefig(str(out_dir / "report.png"), dpi=150, bbox_inches="tight")
plt.close(fig)

# -- Save JSON -------------------------------------------------------------

json.dump({
    "timestamp"          : _ts,
    "job"                : args.job,
    "pixel_um"           : float(pixel_um),
    "scale_x"            : args.scale_x,
    "scale_y"            : args.scale_y,
    "threshold_um"       : args.threshold,
    "max_passes"         : args.max_passes,
    "test_mode"          : args.test,
    "converged"          : converged,
    "passes_used"        : pass_num,
    "initial_dist_um"    : dist0,
    "final_dist_um"      : final["dist_um"],
    "improvement_um"     : dist0 - final["dist_um"],
    "total_correction_um": [float(total_cx), float(total_cy)],
    "history"            : history,
}, open(out_dir / "result.json", "w"), indent=2)

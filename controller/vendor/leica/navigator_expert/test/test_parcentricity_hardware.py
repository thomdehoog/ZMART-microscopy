"""
Parcentricity Registration - Hardware Move Test
================================================
Acquires a reference image, moves the stage by a known amount, acquires
a second image, registers the pair with 3-estimator voting, and compares
the measured shift to the expected shift from the stage move.

Expected registration output for a stage move of (move_x, move_y) um:
    dx_um ~ +move_y   (stage X -> image -Y; stage Y -> image +X; axes are swapped ~90 deg)
    dy_um ~ -move_x
(validated empirically; see parcentricity_registration_progress.md section 4.1)

After measurement the stage is restored and a verification image is
acquired to confirm the residual is near zero.

Usage:
    python test_parcentricity_hardware.py
    python test_parcentricity_hardware.py --move-x 10 --move-y 0
    python test_parcentricity_hardware.py --move-x 5 --move-y 5 --job Overview
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
from scipy.ndimage import shift as ndi_shift
from skimage.registration import phase_cross_correlation

parser = argparse.ArgumentParser()
parser.add_argument("--move-x", type=float, default=10.0,
                    help="Stage move in X (um, default 10)")
parser.add_argument("--move-y", type=float, default=0.0,
                    help="Stage move in Y (um, default 0)")
parser.add_argument("--job", default="Overview",
                    help="LAS X job name (default: Overview)")
parser.add_argument("--zoom", type=float, default=None,
                    help="Set zoom before acquiring (default: leave as-is)")
parser.add_argument("--settle", type=float, default=1.0,
                    help="Settle time after stage move (s, default 1)")
parser.add_argument("--scale-x", type=float, default=0.96,
                    help="Calibration: stage X -> image Y scale factor (default 0.96). "
                         "Overridden by a fit from the measured data when the dominant "
                         "axis has a large enough move.")
parser.add_argument("--scale-y", type=float, default=0.90,
                    help="Calibration: stage Y -> image X scale factor (default 0.90). "
                         "Overridden by a fit from the measured data when the dominant "
                         "axis has a large enough move.")
parser.add_argument("--no-correction", action="store_true",
                    help="Skip the calibration correction pass at the end")
parser.add_argument("--linearity", action="store_true",
                    help="Linearity sweep mode: measure image shift at multiple displacement "
                         "magnitudes to verify the scale factor is constant")
parser.add_argument("--linearity-axis", default="x", choices=["x", "y", "both"],
                    help="Axis to sweep in linearity mode (default: x)")
parser.add_argument("--linearity-steps", default="2,5,10,15,20",
                    help="Comma-separated displacement magnitudes in um (default: 2,5,10,15,20)")
args = parser.parse_args()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from LasxApi import PYLICamApiConnector as lasx_api
import navigator_expert.driver as drv
from navigator_expert.driver.readers import get_job_settings, get_lasx_settings
from navigator_expert.driver.utils import parse_tile_geometry
from navigator_expert.driver.prechecks import check_idle

import logging
logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")


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
out_dir = Path(__file__).resolve().parent.parent / "config" / "alignment" / f"hw_{_ts}"
out_dir.mkdir(parents=True, exist_ok=True)
print(f"Output: {out_dir}")

if args.zoom is not None:
    print(f"Setting zoom to {args.zoom}...")
    drv.set_zoom(client, args.job, args.zoom)
    time.sleep(2)

settings = get_job_settings(client, args.job)
geo = parse_tile_geometry(settings)
pixel_um = geo["pixel_w_um"]
print(f"Job: {args.job}  |  zoom: {args.zoom or '(as-is)'}  |  pixel: {pixel_um:.4f} um  |  size: {geo['pixels_x']}x{geo['pixels_y']}")
print(f"Stage move: ({args.move_x:+.1f}, {args.move_y:+.1f}) um")
print(f"Expected:   dx~{+args.move_y:+.2f} um  dy~{-args.move_x:+.2f} um  [axes swapped: stageX->imgY, stageY->imgX]")


# -- Helpers ---------------------------------------------------------------

def acquire(label):
    if not check_idle(client, timeout=30)["success"]:
        print(f"  WARNING: scanner not idle before {label}")
    baseline = drv.read_relative_path(client)
    t0 = time.time()
    r = drv.acquire(client, args.job)
    if not r or not r["success"]:
        print(f"  ABORT: acquire failed ({label}): {r}")
        sys.exit(1)
    media = get_lasx_settings()["export"]["media_path"]
    det = drv.detect_new_files(client, baseline, media, acquire_start=t0)
    if not det["success"]:
        print(f"  ABORT: file detection failed ({label}): {det.get('error')}")
        sys.exit(1)
    img = tifffile.imread(str(sorted(det["image_files"])[0]))
    img = img[0] if img.ndim == 3 else img
    img = img.astype(np.float32)
    tifffile.imwrite(str(out_dir / f"{label}.tif"), img)
    print(f"  {label}: {img.shape[1]}x{img.shape[0]}  max={img.max():.0f}")
    return img


def _to_u8(a):
    return (a.astype(np.float64) / (a.max() or 1) * 255).astype(np.uint8)


# -- Estimators ------------------------------------------------------------

def est_pcc(ref, tgt, px, mask_pct=30):
    # NOTE: skimage ignores upsample_factor when masks are supplied -- precision is
    # integer-pixel only (~+/-0.5 px).  At fine zoom (<=0.06 um/px) this is <0.03 um;
    # at coarse zoom (0.57 um/px) it is +/-0.28 um.
    ref_mask = ref > np.percentile(ref, mask_pct)
    tgt_mask = tgt > np.percentile(tgt, mask_pct)
    sub, _, _ = phase_cross_correlation(
        ref.astype(np.float64), tgt.astype(np.float64),
        upsample_factor=100, reference_mask=ref_mask, moving_mask=tgt_mask)
    return {"name": "PCC", "dx_um": sub[1] * px, "dy_um": sub[0] * px,
            "dx_px": float(sub[1]), "dy_px": float(sub[0])}


def est_ncc(ref, tgt, px):
    # Max detectable shift is +/-W/4 px.  Returns invalid if the best match lands
    # at or near the boundary of the result space (shift is out of range).
    r8, t8 = _to_u8(ref), _to_u8(tgt)
    H, W = t8.shape
    m = H // 4
    tmpl = t8[m:H-m, m:W-m]
    res = cv2.matchTemplate(r8, tmpl, cv2.TM_CCOEFF_NORMED)
    _, q, _, loc = cv2.minMaxLoc(res)
    rH, rW = res.shape
    margin = 2
    if loc[0] < margin or loc[0] >= rW - margin or loc[1] < margin or loc[1] >= rH - margin:
        return {"name": "NCC", "dx_um": None, "dy_um": None,
                "quality": float(q), "note": "shift at search boundary - out of NCC range"}
    dx = (loc[0] + tmpl.shape[1] / 2 - W / 2) * px
    dy = (loc[1] + tmpl.shape[0] / 2 - H / 2) * px
    return {"name": "NCC", "dx_um": dx, "dy_um": dy, "quality": float(q)}


def est_ransac(ref, tgt, px, n_features=2000, ransac_iters=300, inlier_px=2.0):
    r8, t8 = _to_u8(ref), _to_u8(tgt)
    orb = cv2.ORB_create(nfeatures=n_features)
    kp1, des1 = orb.detectAndCompute(r8, None)
    kp2, des2 = orb.detectAndCompute(t8, None)
    if des1 is None or des2 is None or len(kp1) < 8 or len(kp2) < 8:
        return {"name": "RANSAC", "dx_um": None, "dy_um": None, "note": "too few keypoints"}
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = bf.match(des1, des2)
    if len(matches) < 4:
        return {"name": "RANSAC", "dx_um": None, "dy_um": None, "note": "too few matches"}
    pts1 = np.array([kp1[m.queryIdx].pt for m in matches])
    pts2 = np.array([kp2[m.trainIdx].pt for m in matches])
    deltas = pts2 - pts1
    rng = np.random.default_rng(0)
    best_in = np.array([], dtype=int)
    best_dx, best_dy = 0.0, 0.0
    for _ in range(ransac_iters):
        idx = rng.integers(len(deltas))
        dist = np.linalg.norm(deltas - deltas[idx], axis=1)
        inliers = np.where(dist < inlier_px)[0]
        if len(inliers) > len(best_in):
            best_in = inliers
            best_dx = float(np.median(deltas[inliers, 0]))
            best_dy = float(np.median(deltas[inliers, 1]))
    return {"name": "RANSAC", "dx_um": -best_dx * px, "dy_um": -best_dy * px,
            "inliers": len(best_in), "matches": len(matches)}


def vote(estimates, threshold_um=1.0):
    valid = [e for e in estimates if e.get("dx_um") is not None]
    if not valid:
        return {"dx_um": float("nan"), "dy_um": float("nan"),
                "voters": [], "confidence": "none"}
    best_cluster = []
    for a in valid:
        cluster = [a]
        for b in valid:
            if b is a:
                continue
            if ((a["dx_um"]-b["dx_um"])**2 + (a["dy_um"]-b["dy_um"])**2)**0.5 < threshold_um:
                cluster.append(b)
        if len(cluster) > len(best_cluster):
            best_cluster = cluster
    n, total = len(best_cluster), len(valid)

    # When multiple estimators are available but none agree, don't silently
    # return one arbitrarily -- the tie-break would always favour PCC because
    # it appears first in the input list.
    if n == 1 and total >= 2:
        return {"dx_um": float("nan"), "dy_um": float("nan"),
                "voters": [], "confidence": "none",
                "n_voters": 0, "n_total": total,
                "note": "no consensus - all estimators disagree beyond threshold"}

    dx = float(np.mean([e["dx_um"] for e in best_cluster]))
    dy = float(np.mean([e["dy_um"] for e in best_cluster]))
    conf = "high" if n >= 3 else ("medium" if n == 2 else "low")
    return {"dx_um": dx, "dy_um": dy,
            "voters": [e["name"] for e in best_cluster],
            "confidence": conf, "n_voters": n, "n_total": total}


def register_and_report(ref, tgt, label):
    pcc    = est_pcc(ref, tgt, pixel_um)
    ncc    = est_ncc(ref, tgt, pixel_um)
    ransac = est_ransac(ref, tgt, pixel_um)
    result = vote([pcc, ncc, ransac])
    dist   = (result["dx_um"]**2 + result["dy_um"]**2) ** 0.5
    voters = "+".join(result["voters"]) or "none"
    print(f"  {label}: ({result['dx_um']:+.2f}, {result['dy_um']:+.2f}) um  "
          f"dist={dist:.2f}  conf={result['confidence']}  voters={voters}")
    # Log raw pixel values alongside um -- makes it easy to spot a fixed-px offset
    # (software artefact) vs a proportional scale error (hardware calibration).
    pcc_px = f"({pcc.get('dx_px', float('nan')):+.1f}, {pcc.get('dy_px', float('nan')):+.1f}) px"
    print(f"    PCC    ({pcc['dx_um']:+.2f}, {pcc['dy_um']:+.2f}) um  {pcc_px}")
    if ncc.get("dx_um") is not None:
        ncc_dx_px = ncc['dx_um'] / pixel_um
        ncc_dy_px = ncc['dy_um'] / pixel_um
        print(f"    NCC    ({ncc['dx_um']:+.2f}, {ncc['dy_um']:+.2f}) um  "
              f"({ncc_dx_px:+.1f}, {ncc_dy_px:+.1f}) px  q={ncc.get('quality', 0):.3f}")
    else:
        print(f"    NCC    n/a  ({ncc.get('note', '')})")
    if ransac.get("dx_um") is not None:
        r_dx_px = ransac['dx_um'] / pixel_um
        r_dy_px = ransac['dy_um'] / pixel_um
        print(f"    RANSAC ({ransac['dx_um']:+.2f}, {ransac['dy_um']:+.2f}) um  "
              f"({r_dx_px:+.1f}, {r_dy_px:+.1f}) px  "
              f"inliers={ransac.get('inliers', 0)}/{ransac.get('matches', 0)}")
    else:
        print(f"    RANSAC n/a  ({ransac.get('note', '')})")
    return result


# -- Linearity sweep (--linearity mode) ------------------------------------

def run_linearity():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    steps = [float(s.strip()) for s in args.linearity_steps.split(",")]
    axes  = ["x", "y"] if args.linearity_axis == "both" else [args.linearity_axis]

    home = drv.get_xy(client)
    print(f"\nLinearity test")
    print(f"  pixel: {pixel_um:.4f} um/px  |  image: {geo['pixels_x']}x{geo['pixels_y']}")
    print(f"  steps: {steps} um  |  axes: {axes}")
    print(f"  home:  ({home['x_um']:.1f}, {home['y_um']:.1f}) um")

    all_results = {}

    for axis in axes:
        print(f"\n{'=' * 52}")
        print(f"  Axis {axis.upper()} sweep")
        print(f"{'=' * 52}")

        print("Acquiring reference at home...")
        img_ref = acquire(f"ref_lin_{axis}")

        commanded = []
        measured  = []
        scales    = []

        hdr = f"  {'Cmd(um)':>9}  {'Meas(um)':>9}  {'Px':>6}  {'Scale':>7}  {'Conf':<8}  Voters"
        print(hdr)
        print("  " + "-" * 58)

        for step in steps:
            if axis == "x":
                drv.move_xy(client, home["x_um"] + step, home["y_um"])
            else:
                drv.move_xy(client, home["x_um"], home["y_um"] + step)
            time.sleep(args.settle)

            img_d  = acquire(f"lin_{axis}{step:.0f}")
            pcc    = est_pcc(img_ref, img_d, pixel_um)
            ncc    = est_ncc(img_ref, img_d, pixel_um)
            ransac = est_ransac(img_ref, img_d, pixel_um)
            res    = vote([pcc, ncc, ransac])

            # stage +X -> image -dy  =>  scale_x = -dy / step
            # stage +Y -> image +dx  =>  scale_y =  dx / step
            meas_um = (-res["dy_um"] if axis == "x" else res["dx_um"])
            scale   = (meas_um / step) if (step != 0 and not np.isnan(meas_um)) else float("nan")
            meas_px = meas_um / pixel_um if not np.isnan(meas_um) else float("nan")

            commanded.append(step)
            measured.append(meas_um)
            scales.append(scale)

            voters = "+".join(res["voters"]) or "none"
            print(f"  {step:>9.1f}  {meas_um:>9.3f}  {meas_px:>6.1f}  "
                  f"{scale:>7.4f}  {res['confidence']:<8}  {voters}")

            # Restore to home between steps
            drv.move_xy(client, home["x_um"], home["y_um"])
            time.sleep(args.settle)

        # Linear regression through origin: slope = sum(c*m) / sum(c^2)
        c_arr = np.array(commanded, dtype=float)
        m_arr = np.array(measured,  dtype=float)
        ok    = ~np.isnan(m_arr)
        c_v, m_v = c_arr[ok], m_arr[ok]

        if len(c_v) >= 2:
            slope    = float(np.dot(c_v, m_v) / np.dot(c_v, c_v))
            resid    = m_v - slope * c_v
            ss_res   = float(np.dot(resid, resid))
            ss_tot   = float(np.sum((m_v - m_v.mean()) ** 2))
            r2       = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
            sc_ok    = [s for s in scales if not np.isnan(s)]
            sc_range = max(sc_ok) - min(sc_ok) if sc_ok else float("nan")

            linear = r2 > 0.999
            print(f"\n  Linear fit (through origin): slope = {slope:.4f}")
            print(f"  R^2 = {r2:.6f}   "
                  f"{'linear (good)' if linear else 'NON-LINEAR - investigate'}")
            print(f"  Scale range: {min(sc_ok):.4f} - {max(sc_ok):.4f}  "
                  f"(spread: {sc_range:.4f})")

            all_results[axis] = {
                "commanded_um" : list(commanded),
                "measured_um"  : [float(v) for v in measured],
                "scales"       : [float(v) for v in scales],
                "slope"        : slope,
                "r_squared"    : r2,
                "scale_min"    : float(min(sc_ok)),
                "scale_max"    : float(max(sc_ok)),
                "scale_spread" : float(sc_range),
                "linear"       : linear,
            }

            # Two-panel plot: linearity curve + scale vs displacement
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
            fig.patch.set_facecolor("white")

            c_line = np.linspace(0, max(commanded) * 1.05, 200)
            ax1.plot(c_v, m_v, "o", markersize=8, label="measured")
            ax1.plot(c_line, slope * c_line, "--", alpha=0.7,
                     label=f"fit  slope={slope:.4f}  R^2={r2:.5f}")
            ax1.set_xlabel(f"Commanded stage {axis.upper()} (um)")
            ax1.set_ylabel("Measured image shift (um)  "
                           + ("-dy" if axis == "x" else "+dx"))
            ax1.set_title(f"Linearity - axis {axis.upper()}")
            ax1.legend()
            ax1.grid(True, alpha=0.3)

            ax2.plot(commanded, scales, "o-", markersize=8)
            ax2.axhline(slope, linestyle="--", alpha=0.5,
                        label=f"mean slope={slope:.4f}")
            ax2.set_xlabel(f"Commanded stage {axis.upper()} (um)")
            ax2.set_ylabel("Scale factor  (measured / commanded)")
            ax2.set_title(f"Scale factor vs displacement  (spread={sc_range:.4f})")
            ax2.legend()
            ax2.grid(True, alpha=0.3)

            fig.suptitle(f"Linearity test - axis {axis.upper()}  {_ts}",
                         fontsize=12, fontweight="bold")
            fig.tight_layout()
            fig.savefig(str(out_dir / f"linearity_{axis}.png"),
                        dpi=150, bbox_inches="tight")
            plt.close(fig)
            print(f"  Plot: {out_dir / f'linearity_{axis}.png'}")

    json.dump({
        "timestamp" : _ts,
        "job"       : args.job,
        "pixel_um"  : float(pixel_um),
        "steps_um"  : steps,
        "axes"      : axes,
        "axis_note" : "scale_x = -dy_um / cmd_x,  scale_y = +dx_um / cmd_y",
        "results"   : all_results,
    }, open(out_dir / "linearity.json", "w"), indent=2)

    print(f"\nOutput: {out_dir}")


# -- Main sequence ---------------------------------------------------------

if args.linearity:
    run_linearity()
    sys.exit(0)

home = drv.get_xy(client)
print(f"\nHome: ({home['x_um']:.1f}, {home['y_um']:.1f}) um")

# Step 1: reference at home
print("\n[1] Acquiring reference...")
img_ref = acquire("ref")

# Step 2: move and acquire
print(f"\n[2] Moving stage by ({args.move_x:+.1f}, {args.move_y:+.1f}) um...")
drv.move_xy(client, home["x_um"] + args.move_x, home["y_um"] + args.move_y)
time.sleep(args.settle)
pos_moved = drv.get_xy(client)
actual_dx = pos_moved["x_um"] - home["x_um"]
actual_dy = pos_moved["y_um"] - home["y_um"]
print(f"  Actual move: ({actual_dx:+.2f}, {actual_dy:+.2f}) um")

print("\n[3] Acquiring displaced image...")
img_moved = acquire("moved")

# Step 3: register
print("\n[4] Registration (ref vs moved):")
result = register_and_report(img_ref, img_moved, "ref->moved")

exp_dx = +actual_dy   # stage X -> image Y (negated), stage Y -> image X
exp_dy = -actual_dx
err = ((result["dx_um"] - exp_dx)**2 + (result["dy_um"] - exp_dy)**2) ** 0.5
print(f"\n  Expected:  ({exp_dx:+.2f}, {exp_dy:+.2f}) um  [pred: +move_y, -move_x]")
print(f"  Measured:  ({result['dx_um']:+.2f}, {result['dy_um']:+.2f}) um")
print(f"  Error:     {err:.2f} um")

# Step 4: restore and verify
print(f"\n[5] Restoring to home ({home['x_um']:.1f}, {home['y_um']:.1f})...")
drv.move_xy(client, home["x_um"], home["y_um"])
time.sleep(args.settle)

print("\n[6] Acquiring verification image...")
img_verify = acquire("verify")

print("\n[7] Verification registration (ref vs restored):")
resid = register_and_report(img_ref, img_verify, "ref->verify")
resid_dist = (resid["dx_um"]**2 + resid["dy_um"]**2) ** 0.5

# -- Calibration correction pass -------------------------------------------
# Fit scale factors from the measured data for the dominant move axis, then
# apply the inverse calibration matrix to command a corrected position and
# measure the true residual.  This directly tests whether the bias is
# removable by the calibration.
#
# Calibration model:
#   image_dy = -scale_x * stage_x_move  =>  corr_x =  image_dy / scale_x
#   image_dx =  scale_y * stage_y_move  =>  corr_y = -image_dx / scale_y

corr_dist = float("nan")
corr_result = None
used_scale_x = args.scale_x
used_scale_y = args.scale_y

if not args.no_correction and result["confidence"] != "none":
    # Fit scale from data for whichever axis we actually moved
    fit_thresh = 0.5   # only fit if the commanded move is large enough
    if abs(actual_dx) > fit_thresh and abs(result["dy_um"]) > 0.05:
        used_scale_x = -result["dy_um"] / actual_dx
    if abs(actual_dy) > fit_thresh and abs(result["dx_um"]) > 0.05:
        used_scale_y =  result["dx_um"] / actual_dy

    corr_x = result["dy_um"] / used_scale_x
    corr_y = -result["dx_um"] / used_scale_y

    print(f"\n{'-' * 52}")
    print("  Calibration correction pass")
    print(f"{'-' * 52}")
    print(f"  scale_x: {used_scale_x:.4f}  "
          f"({'fitted' if abs(actual_dx) > fit_thresh else f'default {args.scale_x}'})")
    print(f"  scale_y: {used_scale_y:.4f}  "
          f"({'fitted' if abs(actual_dy) > fit_thresh else f'default {args.scale_y}'})")
    print(f"  Measured shift:   ({result['dx_um']:+.2f}, {result['dy_um']:+.2f}) um")
    print(f"  Stage correction: ({corr_x:+.2f}, {corr_y:+.2f}) um")
    print(f"  Corrected target: ({args.move_x + corr_x:+.2f}, {args.move_y + corr_y:+.2f}) um from home")

    print(f"\n[8] Moving to corrected position...")
    drv.move_xy(client,
                home["x_um"] + args.move_x + corr_x,
                home["y_um"] + args.move_y + corr_y)
    time.sleep(args.settle)

    print("\n[9] Acquiring corrected image...")
    img_corr = acquire("corrected")

    print("\n[10] Correction registration (ref vs corrected):")
    corr_result = register_and_report(img_ref, img_corr, "ref->corrected")
    corr_dist = (corr_result["dx_um"]**2 + corr_result["dy_um"]**2) ** 0.5

    meas_dist = (result["dx_um"]**2 + result["dy_um"]**2) ** 0.5
    reduction = meas_dist - corr_dist
    pct = (reduction / meas_dist * 100) if meas_dist > 0 else 0.0
    print(f"\n  Before: {meas_dist:.2f} um  ->  After: {corr_dist:.2f} um  "
          f"({reduction:+.2f} um,  {pct:.0f}% reduction)")

    print(f"\n[11] Restoring to home ({home['x_um']:.1f}, {home['y_um']:.1f})...")
    drv.move_xy(client, home["x_um"], home["y_um"])
    time.sleep(args.settle)

# -- Summary ---------------------------------------------------------------

meas_dist = (result["dx_um"]**2 + result["dy_um"]**2) ** 0.5

print(f"\n{'=' * 52}")
print(f"  Hardware Move Test  {_ts}")
print(f"{'=' * 52}")
print(f"  Job:         {args.job}  ({pixel_um:.4f} um/px)")
print(f"  Stage move:  ({args.move_x:+.1f}, {args.move_y:+.1f}) um  "
      f"(actual: {actual_dx:+.2f}, {actual_dy:+.2f})")
print(f"  Expected:    ({exp_dx:+.2f}, {exp_dy:+.2f}) um")
print(f"  Measured:    ({result['dx_um']:+.2f}, {result['dy_um']:+.2f}) um  "
      f"conf={result['confidence']}  voters={'+'.join(result['voters'])}")
print(f"  Error:       {err:.2f} um  {'PASS' if err < 2.0 else 'FAIL'}")
print(f"  Residual:    {resid_dist:.2f} um  "
      f"({'good' if resid_dist < 1.0 else 'check stage repeatability'})")
if not args.no_correction and corr_result is not None:
    print(f"  Correction:  scale_x={used_scale_x:.4f}  scale_y={used_scale_y:.4f}  "
          f"({'fitted' if abs(actual_dx) > 0.5 or abs(actual_dy) > 0.5 else 'default'})")
    print(f"  Post-corr:   {corr_dist:.2f} um  "
          f"({'good' if corr_dist < 0.5 else 'residual remaining'})")
print(f"  Output:      {out_dir}")

json.dump({
    "timestamp": _ts, "job": args.job, "pixel_um": float(pixel_um),
    "stage_move_um": [args.move_x, args.move_y],
    "actual_move_um": [float(actual_dx), float(actual_dy)],
    "expected_um": [float(exp_dx), float(exp_dy)],
    "axis_mapping": "stageX->imgY(neg), stageY->imgX(pos)",
    "measured_um": [float(result["dx_um"]), float(result["dy_um"])],
    "error_um": float(err),
    "confidence": result["confidence"],
    "voters": result["voters"],
    "residual_dist_um": float(resid_dist),
    "calibration": {
        "scale_x": float(used_scale_x), "scale_y": float(used_scale_y),
        "scale_x_source": "fitted" if abs(actual_dx) > 0.5 else "default",
        "scale_y_source": "fitted" if abs(actual_dy) > 0.5 else "default",
    },
    "post_correction_dist_um": float(corr_dist),
    "post_correction_xy_um": (
        [float(corr_result["dx_um"]), float(corr_result["dy_um"])]
        if corr_result else None
    ),
}, open(out_dir / "result.json", "w"), indent=2)

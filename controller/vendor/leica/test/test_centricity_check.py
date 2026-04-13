"""
Centricity Check — Interactive 3-Step
======================================
Measures and verifies parcentric XY alignment between two objectives.
The user manages objective switching and focus manually between steps.

Steps:
  [break] 1 — Acquire reference image
  [break] 2 — Acquire target image, register against reference, report shift
  [break] 3 — Apply +X −Y correction, acquire, register, report residual

Sign convention (validated 2026-04-13):
    stage_corr_x = +image_shift_x
    stage_corr_y = -image_shift_y

Test mode (--test):
    Skips all pauses and moves the stage by --test-move um before step 2
    to simulate a known misalignment. Stage is restored after step 3.

Usage:
    python test_centricity_check.py
    python test_centricity_check.py --job Overview
"""

import argparse
import json
import os
import sys
import time
import logging
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

parser = argparse.ArgumentParser(description="Interactive centricity check")
parser.add_argument("--job", default="Overview", help="LAS X job name (default: Overview)")
parser.add_argument("--test", action="store_true",
                    help="Self-test: skip pauses, move stage before step 2, restore after")
parser.add_argument("--test-move", type=float, default=20.0,
                    help="Stage displacement in um for self-test (default: 20)")
args = parser.parse_args()

import numpy as np
import tifffile
import cv2
from skimage.registration import phase_cross_correlation

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from LasxApi import PYLICamApiConnector as lasx_api
import lasx as drv
from lasx.readers import get_job_settings, get_lasx_settings
from lasx.utils import parse_tile_geometry
from lasx.prechecks import check_idle

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ── Connect ───────────────────────────────────────────────────────────────

client = lasx_api.LasxApiClientPyModel
if not client.Connect("PythonClient"):
    print("ABORT: Cannot connect to LAS X.")
    sys.exit(1)
assert drv.ping(client), "ping failed"

drv.set_stage_limits(
    x_min=1000, x_max=130000,
    y_min=1000, y_max=100000,
    z_galvo_min=-200, z_galvo_max=200,
    z_wide_min=0, z_wide_max=25000,
)

_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
out_dir = Path(__file__).resolve().parent.parent / "config" / "alignment" / f"centricity_{_ts}"
out_dir.mkdir(parents=True, exist_ok=True)
print(f"Output: {out_dir}")

# ── Helpers ───────────────────────────────────────────────────────────────

def pause(msg):
    if args.test:
        print(f"\n[test] {msg}")
        return
    print(f"\n>>> {msg}")
    input("    Press Enter to continue... ")
    print()


def acquire():
    if not check_idle(client, timeout=30)["success"]:
        print("WARNING: scanner not idle")
    baseline = drv.read_relative_path(client)
    t0 = time.time()
    r = drv.acquire(client, args.job)
    if not r or not r["success"]:
        return None
    media = get_lasx_settings()["export"]["media_path"]
    det = drv.detect_new_files(client, baseline, media, acquire_start=t0)
    if not det["success"]:
        return None
    img = tifffile.imread(str(sorted(det["image_files"])[0]))
    return img[0] if img.ndim == 3 else img


def register(ref, tgt, pixel_um, mask_pct=30):
    """NCC + masked NCC registration. Returns shift in um."""
    ref8 = (ref.astype(np.float64) / (ref.max() or 1) * 255).astype(np.uint8)
    tgt8 = (tgt.astype(np.float64) / (tgt.max() or 1) * 255).astype(np.uint8)
    h, w = tgt8.shape
    m = h // 4
    result = cv2.matchTemplate(ref8, tgt8[m:h-m, m:w-m], cv2.TM_CCOEFF_NORMED)
    _, ncc_q, _, loc = cv2.minMaxLoc(result)
    ncc_dx = (loc[0] + (w - 2*m) / 2 - w / 2) * pixel_um
    ncc_dy = (loc[1] + (h - 2*m) / 2 - h / 2) * pixel_um

    ref_mask = ref > np.percentile(ref, mask_pct)
    tgt_mask = tgt > np.percentile(tgt, mask_pct)
    sub, _, _ = phase_cross_correlation(
        ref.astype(np.float64), tgt.astype(np.float64),
        upsample_factor=100, reference_mask=ref_mask, moving_mask=tgt_mask)
    dy, dx = sub[0] * pixel_um, sub[1] * pixel_um

    agreement = ((ncc_dx - dx)**2 + (ncc_dy - dy)**2) ** 0.5
    return {
        "dx_um": dx, "dy_um": dy,
        "dist_um": (dx**2 + dy**2) ** 0.5,
        "ncc_quality": float(ncc_q),
        "agreement_um": float(agreement),
        "reliable": ncc_q > 0.5 and agreement < 3.0,
    }


def overlay(a, b):
    an = a.astype(np.float64) / (a.max() or 1)
    bn = b.astype(np.float64) / (b.max() or 1)
    rgb = np.zeros((*a.shape, 3))
    rgb[..., 1] = an   # green = reference
    rgb[..., 0] = bn   # cyan = target
    rgb[..., 2] = bn
    return np.clip(rgb, 0, 1)


# ── Step 1: Reference ─────────────────────────────────────────────────────

pause("Set up reference objective and focus. Press Enter to acquire reference.")

settings = get_job_settings(client, args.job)
pixel_um = parse_tile_geometry(settings)["pixel_w_um"]
print(f"Pixel size: {pixel_um:.4f} um  (match this on the target)")

img_ref = acquire()
if img_ref is None:
    print("ABORT: reference acquire failed")
    sys.exit(1)

tifffile.imwrite(str(out_dir / "step1_reference.tif"), img_ref)
print(f"Reference: {img_ref.shape[1]} x {img_ref.shape[0]} px")

# ── Step 2: Target + registration ─────────────────────────────────────────

pause(f"Switch to target objective. Match pixel size to {pixel_um:.4f} um. "
      f"Press Enter to acquire and measure shift.")

pos = drv.get_xy(client)
origin_x, origin_y = pos["x_um"], pos["y_um"]
if args.test:
    rng = np.random.default_rng()
    test_dx = float(rng.choice([-1, 1])) * rng.uniform(args.test_move * 0.8, args.test_move * 1.2)
    test_dy = float(rng.choice([-1, 1])) * rng.uniform(args.test_move * 0.8, args.test_move * 1.2)
    print(f"[test] Moving stage by ({test_dx:+.1f}, {test_dy:+.1f}) um (random)")
    drv.move_xy(client, origin_x + test_dx, origin_y + test_dy)
    time.sleep(1)
    pos = drv.get_xy(client)
print(f"Stage: ({pos['x_um']:.1f}, {pos['y_um']:.1f}) um")

img_target = acquire()
if img_target is None:
    print("ABORT: target acquire failed")
    sys.exit(1)

tifffile.imwrite(str(out_dir / "step2_target.tif"), img_target)
shift = register(img_ref, img_target, pixel_um)
dx, dy = shift["dx_um"], shift["dy_um"]

print(f"Shift:       ({dx:+.2f}, {dy:+.2f}) um  =  {shift['dist_um']:.2f} um")
print(f"NCC quality: {shift['ncc_quality']:.3f}  |  agreement: {shift['agreement_um']:.2f} um"
      f"  {'OK' if shift['reliable'] else '  WARNING: low confidence'}")
print(f"Correction (+X -Y): ({+dx:+.2f}, {-dy:+.2f}) um")

# ── Step 3: Apply correction + verify ────────────────────────────────────

if args.test:
    pause(f"Restoring stage to origin ({origin_x:.1f}, {origin_y:.1f}) um and verifying.")
    corr_x, corr_y = -dx, +dy
else:
    pause(f"Press Enter to apply correction ({+dx:+.2f}, {-dy:+.2f}) um and verify.")
    corr_x, corr_y = +dx, -dy

drv.move_xy(client, pos["x_um"] + corr_x, pos["y_um"] + corr_y)
time.sleep(1)

img_verif = acquire()
if img_verif is None:
    print("WARNING: verification acquire failed")
    resid = {"dx_um": float("nan"), "dy_um": float("nan"), "dist_um": float("nan"),
             "ncc_quality": 0.0, "agreement_um": float("nan"), "reliable": False}
else:
    tifffile.imwrite(str(out_dir / "step3_corrected.tif"), img_verif)
    resid = register(img_ref, img_verif, pixel_um)
    improved = resid["dist_um"] < shift["dist_um"]
    print(f"Residual:    ({resid['dx_um']:+.2f}, {resid['dy_um']:+.2f}) um  =  {resid['dist_um']:.2f} um")
    print(f"Improved:    {'YES' if improved else 'NO'}  ({shift['dist_um']:.2f} -> {resid['dist_um']:.2f} um)")

# ── Report ────────────────────────────────────────────────────────────────

fig, axes = plt.subplots(1, 3 if img_verif is not None else 2,
                         figsize=(18 if img_verif is not None else 12, 6))
fig.patch.set_facecolor("white")

axes[0].imshow(img_ref, cmap="gray")
axes[0].set_title("Step 1 — Reference", fontsize=12)
axes[0].axis("off")

axes[1].imshow(overlay(img_ref, img_target))
axes[1].set_title(f"Step 2 — Before correction\n"
                  f"({dx:+.1f}, {dy:+.1f}) um = {shift['dist_um']:.1f} um",
                  fontsize=12, color="#CC0000")
axes[1].axis("off")

if img_verif is not None:
    color = "#006600" if resid["dist_um"] < shift["dist_um"] else "#CC6600"
    axes[2].imshow(overlay(img_ref, img_verif))
    axes[2].set_title(f"Step 3 — After correction\n"
                      f"({resid['dx_um']:+.1f}, {resid['dy_um']:+.1f}) um = {resid['dist_um']:.1f} um",
                      fontsize=12, color=color)
    axes[2].axis("off")

fig.suptitle(f"Centricity Check  {_ts}", fontsize=13, fontweight="bold")
fig.savefig(str(out_dir / "report.png"), dpi=150, bbox_inches="tight")
plt.close(fig)

# ── Save JSON ─────────────────────────────────────────────────────────────

json.dump({
    "timestamp": _ts,
    "job": args.job,
    "pixel_um": float(pixel_um),
    "sign_convention": "+X -Y",
    "shift_xy_um": [float(dx), float(dy)],
    "shift_dist_um": float(shift["dist_um"]),
    "ncc_quality": float(shift["ncc_quality"]),
    "agreement_um": float(shift["agreement_um"]),
    "reliable": bool(shift["reliable"]),
    "correction_um": [float(corr_x), float(corr_y)],
    "residual_xy_um": [float(resid["dx_um"]), float(resid["dy_um"])],
    "residual_dist_um": float(resid["dist_um"]),
}, open(out_dir / "result.json", "w"), indent=2)

# ── Summary ───────────────────────────────────────────────────────────────

if args.test:
    drv.move_xy(client, origin_x, origin_y)
    time.sleep(1)
    print(f"[test] Stage restored to ({origin_x:.1f}, {origin_y:.1f}) um")

print(f"\n{'=' * 44}")
print(f"  Centricity Check - {_ts}")
print(f"{'=' * 44}")
if args.test:
    print(f"  Test move:   {args.test_move:.1f} um")
print(f"  Shift:       {shift['dist_um']:.2f} um")
if not np.isnan(resid["dist_um"]):
    print(f"  Residual:    {resid['dist_um']:.2f} um")
    print(f"  Improvement: {shift['dist_um'] - resid['dist_um']:.2f} um")
print(f"  Output:      {out_dir}")

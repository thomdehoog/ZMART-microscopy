"""
Sign Convention Finder
=======================
Determines the correct +/-X +/-Y sign convention for parcentric
correction between two objectives.

After measuring the XY shift, applies all 4 sign combinations and
picks the one that gives the smallest residual.

Steps:
  1 — Acquire reference image
  [break] Switch to target objective
  2 — Acquire target image, measure shift
  3 — Try all 4 sign combos, acquire + register each, pick winner

Usage:
    python test_find_sign_convention.py
    python test_find_sign_convention.py --job Overview
"""

import argparse
import json
import sys
import time
import logging
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

parser = argparse.ArgumentParser(description="Sign convention finder")
parser.add_argument("--job", default="Overview", help="LAS X job name (default: Overview)")
parser.add_argument("--test", action="store_true",
                    help="Self-test: skip pause, move stage randomly ~5 um instead of switching objective")
parser.add_argument("--test-move", type=float, default=5.0,
                    help="Stage displacement magnitude for self-test (default: 5)")
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
out_dir = Path(__file__).resolve().parent.parent / "config" / "alignment" / f"sign_{_ts}"
out_dir.mkdir(parents=True, exist_ok=True)
print(f"Output: {out_dir}")

# ── Helpers ───────────────────────────────────────────────────────────────

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


# ── Step 1: Reference ─────────────────────────────────────────────────────

print("\nStep 1: Acquiring reference image...")
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

pos = drv.get_xy(client)
origin_x, origin_y = pos["x_um"], pos["y_um"]

if args.test:
    rng = np.random.default_rng()
    test_dx = float(rng.choice([-1, 1])) * rng.uniform(args.test_move * 0.8, args.test_move * 1.2)
    test_dy = float(rng.choice([-1, 1])) * rng.uniform(args.test_move * 0.8, args.test_move * 1.2)
    print(f"\n[test] Moving stage by ({test_dx:+.1f}, {test_dy:+.1f}) um (random)")
    drv.move_xy(client, origin_x + test_dx, origin_y + test_dy)
    time.sleep(1)
    pos = drv.get_xy(client)
else:
    print(f"\n>>> Switch to target objective. Match pixel size to {pixel_um:.4f} um.")
    input("    Press Enter to continue... ")
print(f"\nStep 2: Acquiring target image...")
img_target = acquire()
if img_target is None:
    print("ABORT: target acquire failed")
    sys.exit(1)

tifffile.imwrite(str(out_dir / "step2_target.tif"), img_target)
shift = register(img_ref, img_target, pixel_um)
dx, dy = shift["dx_um"], shift["dy_um"]

print(f"Shift:       ({dx:+.2f}, {dy:+.2f}) um  =  {shift['dist_um']:.2f} um")
print(f"NCC quality: {shift['ncc_quality']:.3f}  |  agreement: {shift['agreement_um']:.2f} um"
      f"  {'OK' if shift['reliable'] else 'WARNING: low confidence'}")

# ── Step 3: Try all 4 sign combinations ───────────────────────────────────

COMBOS = {
    "+X +Y": (+dx, +dy),
    "+X -Y": (+dx, -dy),
    "-X +Y": (-dx, +dy),
    "-X -Y": (-dx, -dy),
}

print(f"\nStep 3: Testing all 4 sign combinations...")
results = {}

for label, (cx, cy) in COMBOS.items():
    print(f"\n  [{label}]  correction: ({cx:+.2f}, {cy:+.2f}) um")
    drv.move_xy(client, pos["x_um"] + cx, pos["y_um"] + cy)
    time.sleep(1)

    img = acquire()
    if img is None:
        print(f"  SKIP: acquire failed")
        results[label] = None
        drv.move_xy(client, pos["x_um"], pos["y_um"])
        time.sleep(1)
        continue

    tifffile.imwrite(str(out_dir / f"step3_{label.replace(' ', '')}.tif"), img)
    resid = register(img_ref, img, pixel_um)
    print(f"  Residual: ({resid['dx_um']:+.2f}, {resid['dy_um']:+.2f}) um  =  {resid['dist_um']:.2f} um")
    results[label] = {"correction_um": [cx, cy], "residual": resid, "img": img}

    drv.move_xy(client, pos["x_um"], pos["y_um"])
    time.sleep(1)

# ── Pick winner ───────────────────────────────────────────────────────────

valid = {k: v for k, v in results.items() if v is not None}
winner = min(valid, key=lambda k: valid[k]["residual"]["dist_um"])

print(f"\n{'=' * 44}")
print(f"  Sign Convention Results")
print(f"{'=' * 44}")
print(f"  {'Sign':<8}  {'Residual':>10}  {'Winner'}")
print(f"  {'-'*8}  {'-'*10}  {'-'*6}")
for label, r in valid.items():
    mark = "<-- WINNER" if label == winner else ""
    print(f"  {label:<8}  {r['residual']['dist_um']:9.2f} um  {mark}")
print(f"\n  Sign convention: {winner}")
print(f"  Initial shift:   {shift['dist_um']:.2f} um")
print(f"  Best residual:   {valid[winner]['residual']['dist_um']:.2f} um")

# ── Visual report ─────────────────────────────────────────────────────────

def overlay(a, b):
    an = a.astype(np.float64) / (a.max() or 1)
    bn = b.astype(np.float64) / (b.max() or 1)
    rgb = np.zeros((*a.shape, 3))
    rgb[..., 1] = an
    rgb[..., 0] = bn
    rgb[..., 2] = bn
    return np.clip(rgb, 0, 1)

fig, axes = plt.subplots(1, len(valid) + 1, figsize=(6 * (len(valid) + 1), 6))
fig.patch.set_facecolor("white")

axes[0].imshow(overlay(img_ref, img_target))
axes[0].set_title(f"Before correction\n{shift['dist_um']:.1f} um", fontsize=11, color="#CC0000")
axes[0].axis("off")

for i, (label, r) in enumerate(valid.items()):
    color = "#006600" if label == winner else "#888888"
    axes[i + 1].imshow(overlay(img_ref, r["img"]))
    axes[i + 1].set_title(f"{label}\n{r['residual']['dist_um']:.2f} um",
                           fontsize=11, color=color,
                           fontweight="bold" if label == winner else "normal")
    axes[i + 1].axis("off")

fig.suptitle(f"Sign Convention Finder  {_ts}  |  Winner: {winner}", fontsize=13, fontweight="bold")
fig.savefig(str(out_dir / "report.png"), dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"  Output:          {out_dir}")

# ── Save JSON ─────────────────────────────────────────────────────────────

json.dump({
    "timestamp": _ts,
    "job": args.job,
    "pixel_um": float(pixel_um),
    "shift_xy_um": [float(dx), float(dy)],
    "shift_dist_um": float(shift["dist_um"]),
    "winner": winner,
    "combos": {
        k: {
            "correction_um": v["correction_um"],
            "residual_xy_um": [float(v["residual"]["dx_um"]), float(v["residual"]["dy_um"])],
            "residual_dist_um": float(v["residual"]["dist_um"]),
        }
        for k, v in valid.items()
    },
}, open(out_dir / "result.json", "w"), indent=2)

if args.test:
    drv.move_xy(client, origin_x, origin_y)
    time.sleep(1)
    print(f"[test] Stage restored to ({origin_x:.1f}, {origin_y:.1f}) um")

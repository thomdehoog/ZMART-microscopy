"""
Self-Validating Sign Convention Test
======================================
Determines the correct sign mapping from image cross-correlation shift
to stage movement, without any calibration file or hardcoded offsets.

Background
----------
When switching objectives on the STELLARIS, the same physical point
appears at a different position in the image due to parcentric offset
and possibly galvo mirror offset.  Phase cross-correlation measures
this shift in image coordinates, but applying it as a stage correction
requires knowing the sign mapping between image and stage axes.

The optical path can mirror one or both axes, so image +X might
correspond to stage -X.  This script determines the mapping empirically
by testing all 4 sign combinations and measuring which one minimizes
the residual offset.

Method
------
1. Acquire on reference objective (e.g. 10x) — this is the "truth"
2. Switch to target objective (e.g. 20x) with matched pixel size via
   zoom.  Acquire without correction → cross-correlate with step 1 →
   raw image shift (dx, dy) in um
3. Stay on target objective.  For each of the 4 sign combinations
   (+x+y, +x-y, -x+y, -x-y):
     a. Move stage from uncorrected position by the signed shift
     b. Acquire → cross-correlate with step 1 → residual
     c. Return stage to uncorrected position
4. The combination with the smallest residual is the correct sign
   mapping from image shift to stage correction

Results (2026-03-30, STELLARIS 8, 10x→20x)
-------------------------------------------
  Winner: -X +Y  (stage_dx = -image_shift_x, stage_dy = +image_shift_y)
  This means the image X axis is MIRRORED relative to stage X
  (reflection, not rotation — Y axis matches).

  Raw shift:  (+9.35, -13.29) um = 16.25 um
  Residual:   (-2.95,  -4.83) um =  5.66 um  (best of 4 combos)

  The ~5.7 um residual after stage correction suggests a second offset
  component — likely galvo mirror "zero" differing per objective.
  The stage correction fixes the parcentric part; the remainder is the
  galvo offset visible at pan=(0,0).

Usage:
    python test_sign_convention.py --ref-slot 1 --target-slot 2
    python test_sign_convention.py --ref-slot 1 --target-slot 2 --settle 5
    python test_sign_convention.py --ref-slot 1 --target-slot 2 --ref-zoom 10
"""

import argparse
import json
import os
import sys
import time
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

parser = argparse.ArgumentParser(
    description="Self-validating sign convention test")
parser.add_argument("--ref-slot", type=int, required=True,
                    help="Reference objective slot (e.g. 1 for 10x)")
parser.add_argument("--target-slot", type=int, required=True,
                    help="Target objective slot (e.g. 2 for 20x)")
parser.add_argument("--ref-zoom", type=float, default=10,
                    help="Reference zoom level (default: 10)")
parser.add_argument("--settle", type=float, default=0,
                    help="Extra settle time after switching to target (s)")
parser.add_argument("--output", default=None,
                    help="Output directory (default: config/alignment/sign_<ts>)")
args = parser.parse_args()

# ── Imports ──────────────────────────────────────────────────────────────

from skimage.registration import phase_cross_correlation
import numpy as np
import tifffile

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from LasxApi import PYLICamApiConnector as lasx_api
import lasx as drv
from lasx.scanning_templates import TEMPLATE_XML, apply_lrp_change
from lasx.scanning_template_editors_scan import lrp_set_pan
from lasx.scanning_template_editors_roi import lrp_enable_roi_scan
from lasx.readers import get_job_settings, get_lasx_settings
from lasx.utils import parse_tile_geometry
from lasx.prechecks import check_idle

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.ndimage import shift as ndi_shift

# ── Connect ──────────────────────────────────────────────────────────────

client = lasx_api.LasxApiClientPyModel
confirmed = client.Connect("PythonClient")
if not confirmed:
    print("  ABORT: Cannot connect to LAS X.")
    sys.exit(1)
assert drv.ping(client), "ping failed"

job = drv.get_selected_job(client).get("Name")
hw = drv.get_hardware_info(client)
if not hw:
    print("  ABORT: cannot read hardware info")
    sys.exit(1)
print(f"  Job: {job}")

drv.set_stage_limits(
    x_min=1000, x_max=130000,
    y_min=1000, y_max=100000,
    z_galvo_min=-200, z_galvo_max=200,
    z_wide_min=0, z_wide_max=25000,
)

# ── Objective lookup ─────────────────────────────────────────────────────

objs_by_slot = {}
for o in hw.get("Microscope", {}).get("objectives", []):
    if o.get("objectiveNumber", 0) != 0:
        objs_by_slot[o["slotIndex"]] = o


def obj_info(slot):
    o = objs_by_slot.get(slot)
    if not o:
        print(f"  ABORT: no objective in slot {slot}")
        print(f"  Available: {list(objs_by_slot.keys())}")
        sys.exit(1)
    mag = o["magnification"]
    na = o["numericalAperture"]
    imm = o.get("immersion", "").strip()
    name = o.get("name", "").strip()
    label = f"slot{slot}_{mag:.0f}x_{na}NA_{imm}"
    return label, name, mag


ref_label, ref_name, ref_mag = obj_info(args.ref_slot)
tgt_label, tgt_name, tgt_mag = obj_info(args.target_slot)
tgt_zoom = args.ref_zoom * ref_mag / tgt_mag

print(f"  Reference: {ref_name} ({ref_label}) @ zoom {args.ref_zoom}")
print(f"  Target:    {tgt_name} ({tgt_label}) @ zoom {tgt_zoom:.2f}")

# ── Output directory ─────────────────────────────────────────────────────

_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
_default_out = os.path.join(
    str(Path(__file__).resolve().parent.parent),
    "config", "alignment", f"sign_{_ts}")
out_dir = args.output or _default_out
os.makedirs(out_dir, exist_ok=True)
print(f"  Output: {out_dir}")

# ── Helpers ──────────────────────────────────────────────────────────────


def reset_pan_roi(p):
    lrp_set_pan(p, 0, 0, job)
    lrp_enable_roi_scan(p, False, job)


def setup_objective(slot, zoom):
    label, name, mag = obj_info(slot)
    print(f"  Switching to {name} (slot {slot})...")
    r = drv.set_objective(client, job, hw, name=name)
    if not r or not r.get("success"):
        print(f"  ABORT: objective switch failed: {r}")
        sys.exit(1)
    time.sleep(3)
    drv.select_job(client, job)
    time.sleep(2)
    apply_lrp_change(client, TEMPLATE_XML, reset_pan_roi,
                     confirm_delays=(2, 4, 6))
    drv.set_zoom(client, job, zoom)
    time.sleep(1)
    drv.select_job(client, job)
    time.sleep(1)


def acquire_image():
    idle = check_idle(client, timeout=30)
    if not idle["success"]:
        print("  WARNING: scanner not idle, proceeding anyway")
    baseline = drv.read_relative_path(client)
    t0 = time.time()
    r = drv.acquire(client, job)
    if not r or not r["success"]:
        print(f"  Acquire failed: {r}")
        return None
    media = get_lasx_settings()["export"]["media_path"]
    det = drv.detect_new_files(client, baseline, media, acquire_start=t0)
    if not det["success"]:
        print(f"  File detection failed: {det.get('error')}")
        return None
    img = tifffile.imread(str(sorted(det["image_files"])[0]))
    if img.ndim == 3:
        img = img[0]
    return img


def cross_correlate(ref, target, pixel_um):
    shift, error, _ = phase_cross_correlation(
        ref.astype(np.float64), target.astype(np.float64),
        upsample_factor=100)
    dy_px, dx_px = shift
    dx_um = dx_px * pixel_um
    dy_um = dy_px * pixel_um
    dist = (dx_um**2 + dy_um**2)**0.5
    return dx_um, dy_um, dist, error


# ── Step 1: Acquire 10x reference ───────────────────────────────────────

print(f"\n{'=' * 60}")
print(f"  STEP 1: Acquire reference ({ref_name})")
print(f"{'=' * 60}")

setup_objective(args.ref_slot, args.ref_zoom)
home = drv.get_xy(client)
print(f"  Home: ({home['x_um']:.1f}, {home['y_um']:.1f})")

settings = get_job_settings(client, job)
geo = parse_tile_geometry(settings)
ref_pixel = geo["pixel_w_um"]
image_size = geo["pixels_x"]
print(f"  Pixel: {ref_pixel:.4f} um, image: {image_size}x{image_size}")

print(f"  Acquiring reference...")
img_ref = acquire_image()
if img_ref is None:
    print("  ABORT: reference acquire failed")
    sys.exit(1)
print(f"  Reference: {img_ref.shape} {img_ref.dtype}")

# ── Step 2: Switch to 20x, acquire uncorrected ──────────────────────────

print(f"\n{'=' * 60}")
print(f"  STEP 2: Acquire target uncorrected ({tgt_name})")
print(f"{'=' * 60}")

setup_objective(args.target_slot, tgt_zoom)

if args.settle > 0:
    print(f"  Extra settle: {args.settle:.0f}s")
    time.sleep(args.settle)

post_switch = drv.get_xy(client)
print(f"  Post-switch: ({post_switch['x_um']:.1f}, {post_switch['y_um']:.1f})")

motor_dx = post_switch["x_um"] - home["x_um"]
motor_dy = post_switch["y_um"] - home["y_um"]
print(f"  Motor delta: ({motor_dx:+.1f}, {motor_dy:+.1f}) um")

settings_tgt = get_job_settings(client, job)
geo_tgt = parse_tile_geometry(settings_tgt)
tgt_pixel = geo_tgt["pixel_w_um"]
pixel_mismatch = abs(tgt_pixel - ref_pixel) / ref_pixel * 100
print(f"  Target pixel: {tgt_pixel:.4f} um ({pixel_mismatch:.2f}% mismatch)")

print(f"  Acquiring uncorrected...")
img_uncorrected = acquire_image()
if img_uncorrected is None:
    print("  ABORT: uncorrected acquire failed")
    sys.exit(1)

# Cross-correlate: what shift aligns target to ref?
dx_um, dy_um, dist, err = cross_correlate(img_ref, img_uncorrected, ref_pixel)
print(f"  Raw shift: ({dx_um:+.2f}, {dy_um:+.2f}) um = {dist:.2f} um")
print(f"  Correlation error: {err:.4f}")

if dist < 1.0:
    print(f"  WARNING: shift is very small ({dist:.2f} um), sign test may be ambiguous")

# ── Step 3-4: Test all 4 sign combinations ──────────────────────────────

print(f"\n{'=' * 60}")
print(f"  STEPS 3-4: Test sign combinations")
print(f"  Measured shift: ({dx_um:+.2f}, {dy_um:+.2f}) um")
print(f"{'=' * 60}")

sign_combos = [
    ("+X +Y", +1, +1),
    ("+X -Y", +1, -1),
    ("-X +Y", -1, +1),
    ("-X -Y", -1, -1),
]

results = []
images = {}

# Save uncorrected for report
images["uncorrected"] = img_uncorrected

for label, sx, sy in sign_combos:
    corr_x = sx * dx_um
    corr_y = sy * dy_um
    target_x = post_switch["x_um"] + corr_x
    target_y = post_switch["y_um"] + corr_y

    print(f"\n  [{label}] Correction: ({corr_x:+.2f}, {corr_y:+.2f}) um")
    print(f"  [{label}] Moving to ({target_x:.1f}, {target_y:.1f})...")

    r = drv.move_xy(client, target_x, target_y)
    if not r or not r.get("success"):
        print(f"  [{label}] Move failed: {r}")
        results.append({"label": label, "sx": sx, "sy": sy, "failed": True})
        continue
    time.sleep(1)

    actual = drv.get_xy(client)
    print(f"  [{label}] Actual: ({actual['x_um']:.1f}, {actual['y_um']:.1f})")

    print(f"  [{label}] Acquiring...")
    img = acquire_image()
    if img is None:
        print(f"  [{label}] Acquire failed")
        results.append({"label": label, "sx": sx, "sy": sy, "failed": True})
    else:
        rdx, rdy, rdist, rerr = cross_correlate(img_ref, img, ref_pixel)
        print(f"  [{label}] Residual: ({rdx:+.2f}, {rdy:+.2f}) um = {rdist:.2f} um")
        results.append({
            "label": label,
            "sx": sx, "sy": sy,
            "correction_um": [corr_x, corr_y],
            "residual_x_um": rdx,
            "residual_y_um": rdy,
            "residual_dist_um": rdist,
            "correlation_error": rerr,
            "failed": False,
        })
        images[label] = img

    # Return to uncorrected position before next test
    print(f"  [{label}] Returning to post-switch position...")
    drv.move_xy(client, post_switch["x_um"], post_switch["y_um"])
    time.sleep(1)

# ── Summary ──────────────────────────────────────────────────────────────

print(f"\n{'=' * 70}")
print(f"  Sign Convention Test Results")
print(f"  Raw shift: ({dx_um:+.2f}, {dy_um:+.2f}) um = {dist:.2f} um")
print(f"  Motor delta: ({motor_dx:+.1f}, {motor_dy:+.1f}) um")
print(f"{'=' * 70}")
print(f"  {'Label':<10}  {'Correction':>22}  {'Resid X':>10}  {'Resid Y':>10}  {'Dist':>8}")
print(f"  {'-'*10}  {'-'*22}  {'-'*10}  {'-'*10}  {'-'*8}")

best = None
for r in results:
    if r["failed"]:
        print(f"  {r['label']:<10}  {'FAILED':>22}")
        continue
    cx, cy = r["correction_um"]
    print(f"  {r['label']:<10}  ({cx:+8.2f}, {cy:+8.2f})  "
          f"{r['residual_x_um']:+10.2f}  {r['residual_y_um']:+10.2f}  "
          f"{r['residual_dist_um']:8.2f}"
          f"{'  <-- BEST' if best is None or r['residual_dist_um'] < best['residual_dist_um'] else ''}")
    if best is None or r["residual_dist_um"] < best["residual_dist_um"]:
        best = r

if best and best["residual_dist_um"] < dist * 0.5:
    print(f"\n  WINNER: {best['label']}")
    print(f"  Stage correction = ({best['sx']:+d} * image_shift_x, "
          f"{best['sy']:+d} * image_shift_y)")
    print(f"  Residual: {best['residual_dist_um']:.2f} um "
          f"(was {dist:.2f} um uncorrected)")
else:
    print(f"\n  NO CLEAR WINNER — all residuals are large")
    print(f"  Cross-correlation may be unreliable on this sample")

# ── Visual report ────────────────────────────────────────────────────────

ref_norm = img_ref.astype(np.float64)
ref_n = ref_norm / (ref_norm.max() or 1)

n_panels = 1 + 1 + len([r for r in results if not r["failed"]])
fig, axes = plt.subplots(2, max(n_panels, 3), figsize=(6 * max(n_panels, 3), 12))

def make_overlay(a, b):
    an = a.astype(np.float64)
    bn = b.astype(np.float64)
    an = an / (an.max() or 1)
    bn = bn / (bn.max() or 1)
    ov = np.zeros((*a.shape, 3))
    ov[..., 1] = an  # green = ref
    ov[..., 0] = bn  # magenta = target
    ov[..., 2] = bn
    return np.clip(ov, 0, 1)

# Top row: overlays
col = 0

ax = axes[0, col]
ax.imshow(img_ref, cmap="gray")
ax.set_title(f"Reference\n{ref_label} z{args.ref_zoom}", fontsize=10)
ax.plot(image_size/2, image_size/2, "c+", ms=12, mew=2)

col += 1
ax = axes[0, col]
ax.imshow(make_overlay(img_ref, img_uncorrected))
ax.set_title(f"Uncorrected\n({dx_um:+.1f}, {dy_um:+.1f}) um = {dist:.1f} um",
             fontsize=10)

for r in results:
    if r["failed"]:
        continue
    col += 1
    if col >= axes.shape[1]:
        break
    ax = axes[0, col]
    label = r["label"]
    if label in images:
        ax.imshow(make_overlay(img_ref, images[label]))
    cx, cy = r["correction_um"]
    is_best = best and r["label"] == best["label"]
    color = "green" if is_best else "white"
    ax.set_title(
        f"{label}\nresidual: {r['residual_dist_um']:.1f} um"
        f"{'  ★ BEST' if is_best else ''}",
        fontsize=10, color=color if is_best else "black",
        fontweight="bold" if is_best else "normal")

# Hide unused top-row axes
for i in range(col + 1, axes.shape[1]):
    axes[0, i].axis("off")

# Bottom left: vector diagram
ax = axes[1, 0]
lim = max(abs(dx_um), abs(dy_um), 5) * 2.5
ax.set_xlim(-lim, lim)
ax.set_ylim(-lim, lim)
ax.set_aspect("equal")
ax.axhline(0, color="gray", lw=0.5)
ax.axvline(0, color="gray", lw=0.5)
ax.plot(0, 0, "go", ms=10, label="ref (10x)")
ax.plot(dx_um, dy_um, "m^", ms=10, label=f"uncorrected ({dist:.1f}um)")
ax.annotate("", xy=(dx_um, dy_um), xytext=(0, 0),
            arrowprops=dict(arrowstyle="->", color="magenta", lw=2))

colors = ["blue", "orange", "red", "purple"]
for i, r in enumerate(results):
    if r["failed"]:
        continue
    rdx, rdy = r["residual_x_um"], r["residual_y_um"]
    is_best = best and r["label"] == best["label"]
    ms = 12 if is_best else 8
    marker = "*" if is_best else "s"
    ax.plot(rdx, rdy, marker, ms=ms, color=colors[i],
            label=f"{r['label']}: {r['residual_dist_um']:.1f}um")

ax.set_xlabel("X (um)")
ax.set_ylabel("Y (um)")
ax.set_title("Residuals (um)")
ax.legend(fontsize=8)
ax.grid(True, alpha=0.3)

# Bottom middle: bar chart
ax = axes[1, 1]
labels_bar = []
dists_bar = []
colors_bar = []
labels_bar.append("uncorr")
dists_bar.append(dist)
colors_bar.append("magenta")
for i, r in enumerate(results):
    if r["failed"]:
        continue
    labels_bar.append(r["label"])
    dists_bar.append(r["residual_dist_um"])
    is_best = best and r["label"] == best["label"]
    colors_bar.append("green" if is_best else colors[i])
bars = ax.bar(labels_bar, dists_bar, color=colors_bar, alpha=0.7)
ax.set_ylabel("Residual distance (um)")
ax.set_title("Comparison")
ax.axhline(0, color="gray", lw=0.5)
for bar, d in zip(bars, dists_bar):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.2,
            f"{d:.1f}", ha="center", fontsize=9)

# Bottom right: summary text
ax = axes[1, 2]
ax.axis("off")
txt_lines = [
    f"Sign Convention Test",
    f"{ref_label} -> {tgt_label}",
    f"{'─' * 36}",
    f"Raw shift: ({dx_um:+.2f}, {dy_um:+.2f}) um",
    f"Distance:  {dist:.2f} um",
    f"Motor:     ({motor_dx:+.1f}, {motor_dy:+.1f}) um",
    f"Pixel:     {ref_pixel:.4f} / {tgt_pixel:.4f} um",
    f"{'─' * 36}",
]
for r in results:
    if r["failed"]:
        txt_lines.append(f"{r['label']:<10} FAILED")
        continue
    is_best = best and r["label"] == best["label"]
    star = " ★" if is_best else ""
    txt_lines.append(
        f"{r['label']:<10} resid={r['residual_dist_um']:5.2f} um{star}")

if best and best["residual_dist_um"] < dist * 0.5:
    txt_lines.append(f"{'─' * 36}")
    txt_lines.append(f"WINNER: {best['label']}")
    txt_lines.append(f"  stage_dx = {best['sx']:+d} * shift_x")
    txt_lines.append(f"  stage_dy = {best['sy']:+d} * shift_y")

ax.text(0.05, 0.95, "\n".join(txt_lines), transform=ax.transAxes,
        fontsize=11, va="top", fontfamily="monospace",
        bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5))

# Hide remaining bottom axes
for i in range(3, axes.shape[1]):
    axes[1, i].axis("off")

winner_str = best["label"] if best else "???"
fig.suptitle(
    f"Sign Convention: {ref_label} -> {tgt_label}  |  "
    f"Raw shift = ({dx_um:+.1f}, {dy_um:+.1f}) um  |  "
    f"Best: {winner_str} (residual {best['residual_dist_um']:.1f} um)"
    if best and not best["failed"] else
    f"Sign Convention: {ref_label} -> {tgt_label}  |  "
    f"Raw shift = ({dx_um:+.1f}, {dy_um:+.1f}) um",
    fontsize=13, fontweight="bold")

fig.tight_layout()
report_path = os.path.join(out_dir, f"sign_convention_{ref_label}_vs_{tgt_label}.png")
fig.savefig(report_path, dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"\n  Report: {report_path}")

# ── Save JSON ────────────────────────────────────────────────────────────

out_data = {
    "timestamp": _ts,
    "ref_objective": ref_name,
    "ref_label": ref_label,
    "ref_slot": args.ref_slot,
    "ref_zoom": args.ref_zoom,
    "ref_pixel_um": float(ref_pixel),
    "target_objective": tgt_name,
    "target_label": tgt_label,
    "target_slot": args.target_slot,
    "target_zoom": float(tgt_zoom),
    "target_pixel_um": float(tgt_pixel),
    "motor_delta_um": [float(motor_dx), float(motor_dy)],
    "raw_shift_um": [float(dx_um), float(dy_um)],
    "raw_distance_um": float(dist),
    "sign_tests": [r for r in results if not r["failed"]],
    "best": best["label"] if best and best["residual_dist_um"] < dist * 0.5 else None,
    "best_signs": [best["sx"], best["sy"]] if best and best["residual_dist_um"] < dist * 0.5 else None,
}
json_path = os.path.join(out_dir, "sign_convention_results.json")
with open(json_path, "w") as f:
    json.dump(out_data, f, indent=2)
print(f"  JSON: {json_path}")

# ── Restore ──────────────────────────────────────────────────────────────

print(f"\n  Switching back to {ref_name}...")
setup_objective(args.ref_slot, args.ref_zoom)
drv.move_xy(client, home["x_um"], home["y_um"])
time.sleep(1)
print("  Done.")

"""
Pan Correction Test (second step after test_sign_convention.py)
================================================================
Applies the known stage correction (-X +Y) and then tests pan
corrections to eliminate the remaining galvo offset.

1. Acquire 10x reference
2. Switch to 20x, apply stage correction (-shift_x, +shift_y)
3. Acquire → cross-correlate → residual (= galvo offset)
4. Try 4 pan sign combos of that residual → acquire each → find best
5. The combo with residual ≈ 0 is the correct pan mapping

Usage:
    python test_pan_correction.py --ref-slot 1 --target-slot 2
    python test_pan_correction.py --ref-slot 1 --target-slot 2 --ref-zoom 10
"""

import argparse
import json
import os
import sys
import time
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

# PAN_SCALE is objective-dependent; resolved at runtime from base FOV.
# See lasx/utils.py for the physics and lasx.pan_scale_um_from_base_fov
# for the helper. Assigned after `client` and `job` are established below.
PAN_SCALE = None

parser = argparse.ArgumentParser(description="Pan correction test")
parser.add_argument("--ref-slot", type=int, required=True)
parser.add_argument("--target-slot", type=int, required=True)
parser.add_argument("--ref-zoom", type=float, default=10)
parser.add_argument("--settle", type=float, default=0)
parser.add_argument("--output", default=None)
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

# Resolve pan scale from the current objective's base FOV.
_base_fov_m = drv.get_base_fov(client, job)
if not _base_fov_m:
    print("  ABORT: cannot read base FOV")
    sys.exit(1)
PAN_SCALE = drv.pan_scale_um_from_base_fov(_base_fov_m[0] * 1e6)
print(f"  Base FOV: {_base_fov_m[0] * 1e6:.1f} um  "
      f"pan_scale: {PAN_SCALE:.1f} um/unit")

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

# ── Output ───────────────────────────────────────────────────────────────

_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
_default_out = os.path.join(
    str(Path(__file__).resolve().parent.parent),
    "config", "alignment", f"pan_{_ts}")
out_dir = args.output or _default_out
os.makedirs(out_dir, exist_ok=True)
print(f"  Output: {out_dir}")

# ── Helpers ──────────────────────────────────────────────────────────────


def set_pan(px, py):
    """Set galvo pan via LRP."""
    def _edit(p):
        lrp_set_pan(p, px, py, job)
    apply_lrp_change(client, TEMPLATE_XML, _edit, confirm_delays=(2, 4, 6))


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
        print("  WARNING: scanner not idle")
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


def xcorr(ref, target, pixel_um):
    shift, error, _ = phase_cross_correlation(
        ref.astype(np.float64), target.astype(np.float64),
        upsample_factor=100)
    dy_px, dx_px = shift
    dx_um = dx_px * pixel_um
    dy_um = dy_px * pixel_um
    dist = (dx_um**2 + dy_um**2)**0.5
    return dx_um, dy_um, dist, error


def make_overlay(a, b):
    an = a.astype(np.float64)
    bn = b.astype(np.float64)
    an = an / (an.max() or 1)
    bn = bn / (bn.max() or 1)
    ov = np.zeros((*a.shape, 3))
    ov[..., 1] = an
    ov[..., 0] = bn
    ov[..., 2] = bn
    return np.clip(ov, 0, 1)


# ═════════════════════════════════════════════════════════════════════════
#  STEP 1: Acquire 10x reference
# ═════════════════════════════════════════════════════════════════════════

print(f"\n{'=' * 60}")
print(f"  STEP 1: Acquire reference ({ref_name})")
print(f"{'=' * 60}")

setup_objective(args.ref_slot, args.ref_zoom)
home = drv.get_xy(client)
settings = get_job_settings(client, job)
geo = parse_tile_geometry(settings)
ref_pixel = geo["pixel_w_um"]
image_size = geo["pixels_x"]
print(f"  Home: ({home['x_um']:.1f}, {home['y_um']:.1f})")
print(f"  Pixel: {ref_pixel:.4f} um, image: {image_size}x{image_size}")

print(f"  Acquiring reference...")
img_ref = acquire_image()
if img_ref is None:
    print("  ABORT: reference acquire failed")
    sys.exit(1)

# ═════════════════════════════════════════════════════════════════════════
#  STEP 2: Switch to 20x, acquire uncorrected → raw shift
# ═════════════════════════════════════════════════════════════════════════

print(f"\n{'=' * 60}")
print(f"  STEP 2: Acquire target uncorrected ({tgt_name})")
print(f"{'=' * 60}")

setup_objective(args.target_slot, tgt_zoom)
if args.settle > 0:
    print(f"  Settling {args.settle:.0f}s...")
    time.sleep(args.settle)

post_switch = drv.get_xy(client)
motor_dx = post_switch["x_um"] - home["x_um"]
motor_dy = post_switch["y_um"] - home["y_um"]
print(f"  Post-switch: ({post_switch['x_um']:.1f}, {post_switch['y_um']:.1f})")
print(f"  Motor delta: ({motor_dx:+.1f}, {motor_dy:+.1f}) um")

print(f"  Acquiring uncorrected...")
img_uncorr = acquire_image()
if img_uncorr is None:
    print("  ABORT")
    sys.exit(1)

raw_dx, raw_dy, raw_dist, raw_err = xcorr(img_ref, img_uncorr, ref_pixel)
print(f"  Raw shift: ({raw_dx:+.2f}, {raw_dy:+.2f}) um = {raw_dist:.2f} um")

# ═════════════════════════════════════════════════════════════════════════
#  STEP 3: Apply stage correction (-X +Y), measure residual
# ═════════════════════════════════════════════════════════════════════════

print(f"\n{'=' * 60}")
print(f"  STEP 3: Stage correction (-X +Y)")
print(f"{'=' * 60}")

stage_corr_x = -raw_dx
stage_corr_y = +raw_dy
corrected_x = post_switch["x_um"] + stage_corr_x
corrected_y = post_switch["y_um"] + stage_corr_y

print(f"  Stage correction: ({stage_corr_x:+.2f}, {stage_corr_y:+.2f}) um")
print(f"  Moving to ({corrected_x:.1f}, {corrected_y:.1f})...")

r = drv.move_xy(client, corrected_x, corrected_y)
if not r or not r.get("success"):
    print(f"  ABORT: move failed: {r}")
    sys.exit(1)
time.sleep(1)

print(f"  Acquiring after stage correction...")
img_stage_corr = acquire_image()
if img_stage_corr is None:
    print("  ABORT")
    sys.exit(1)

stage_rdx, stage_rdy, stage_rdist, stage_rerr = xcorr(
    img_ref, img_stage_corr, ref_pixel)
print(f"  Stage residual: ({stage_rdx:+.2f}, {stage_rdy:+.2f}) um = {stage_rdist:.2f} um")
print(f"  This is the galvo offset to correct with pan")

# ═════════════════════════════════════════════════════════════════════════
#  STEP 4: Try pan corrections (4 sign combos of the residual)
# ═════════════════════════════════════════════════════════════════════════

print(f"\n{'=' * 60}")
print(f"  STEP 4: Pan correction (galvo offset)")
print(f"  Residual to correct: ({stage_rdx:+.2f}, {stage_rdy:+.2f}) um")
print(f"{'=' * 60}")

pan_combos = [
    ("+X +Y", +1, +1),
    ("+X -Y", +1, -1),
    ("-X +Y", -1, +1),
    ("-X -Y", -1, -1),
]

pan_results = []
pan_images = {}
pan_images["stage_only"] = img_stage_corr

for label, sx, sy in pan_combos:
    pan_x = sx * stage_rdx / PAN_SCALE
    pan_y = sy * stage_rdy / PAN_SCALE

    print(f"\n  [{label}] Pan: ({pan_x:+.8f}, {pan_y:+.8f})")
    print(f"  [{label}] = ({sx * stage_rdx:+.2f}, {sy * stage_rdy:+.2f}) um")

    set_pan(pan_x, pan_y)
    time.sleep(1)

    print(f"  [{label}] Acquiring...")
    img = acquire_image()
    if img is None:
        print(f"  [{label}] Acquire failed")
        pan_results.append({"label": label, "sx": sx, "sy": sy, "failed": True})
    else:
        rdx, rdy, rdist, rerr = xcorr(img_ref, img, ref_pixel)
        print(f"  [{label}] Residual: ({rdx:+.2f}, {rdy:+.2f}) um = {rdist:.2f} um")
        pan_results.append({
            "label": label,
            "sx": sx, "sy": sy,
            "pan_xy": [pan_x, pan_y],
            "pan_um": [sx * stage_rdx, sy * stage_rdy],
            "residual_x_um": rdx,
            "residual_y_um": rdy,
            "residual_dist_um": rdist,
            "correlation_error": rerr,
            "failed": False,
        })
        pan_images[label] = img

    # Reset pan to (0,0) before next test
    set_pan(0, 0)
    time.sleep(1)

# ═════════════════════════════════════════════════════════════════════════
#  Summary
# ═════════════════════════════════════════════════════════════════════════

print(f"\n{'=' * 70}")
print(f"  Two-Step Correction Results")
print(f"{'=' * 70}")
print(f"  Raw shift:      ({raw_dx:+.2f}, {raw_dy:+.2f}) um = {raw_dist:.2f} um")
print(f"  After stage:    ({stage_rdx:+.2f}, {stage_rdy:+.2f}) um = {stage_rdist:.2f} um")
print(f"  Stage signs:    -X +Y")
print(f"{'=' * 70}")
print(f"  {'Pan combo':<10}  {'Pan (um)':>22}  {'Resid X':>10}  {'Resid Y':>10}  {'Dist':>8}")
print(f"  {'-'*10}  {'-'*22}  {'-'*10}  {'-'*10}  {'-'*8}")

best_pan = None
for r in pan_results:
    if r["failed"]:
        print(f"  {r['label']:<10}  {'FAILED':>22}")
        continue
    px, py = r["pan_um"]
    is_best = best_pan is None or r["residual_dist_um"] < best_pan["residual_dist_um"]
    if is_best:
        best_pan = r
    print(f"  {r['label']:<10}  ({px:+8.2f}, {py:+8.2f})  "
          f"{r['residual_x_um']:+10.2f}  {r['residual_y_um']:+10.2f}  "
          f"{r['residual_dist_um']:8.2f}"
          f"{'  <-- BEST' if is_best else ''}")

if best_pan and best_pan["residual_dist_um"] < stage_rdist * 0.5:
    print(f"\n  PAN WINNER: {best_pan['label']}")
    print(f"  pan_dx = {best_pan['sx']:+d} * residual_x / {PAN_SCALE}")
    print(f"  pan_dy = {best_pan['sy']:+d} * residual_y / {PAN_SCALE}")
    print(f"  Final residual: {best_pan['residual_dist_um']:.2f} um "
          f"(was {raw_dist:.2f} uncorrected, {stage_rdist:.2f} stage-only)")
else:
    print(f"\n  NO CLEAR PAN WINNER — residuals still large")

# ═════════════════════════════════════════════════════════════════════════
#  Visual report
# ═════════════════════════════════════════════════════════════════════════

n_top = 2 + 1 + len([r for r in pan_results if not r["failed"]])
n_cols = max(n_top, 4)
fig, axes = plt.subplots(2, n_cols, figsize=(5 * n_cols, 10))

# Top row: ref, uncorrected, stage-only, pan combos
col = 0
ax = axes[0, col]
ax.imshow(img_ref, cmap="gray")
ax.set_title(f"Reference\n{ref_label}", fontsize=10)

col = 1
ax = axes[0, col]
ax.imshow(make_overlay(img_ref, img_uncorr))
ax.set_title(f"Uncorrected\n{raw_dist:.1f} um", fontsize=10)

col = 2
ax = axes[0, col]
ax.imshow(make_overlay(img_ref, img_stage_corr))
ax.set_title(f"Stage only (-X +Y)\n{stage_rdist:.1f} um", fontsize=10,
             color="orange", fontweight="bold")

for r in pan_results:
    if r["failed"]:
        continue
    col += 1
    if col >= n_cols:
        break
    ax = axes[0, col]
    label = r["label"]
    if label in pan_images:
        ax.imshow(make_overlay(img_ref, pan_images[label]))
    is_best = best_pan and r["label"] == best_pan["label"]
    ax.set_title(
        f"Stage + Pan {label}\n{r['residual_dist_um']:.1f} um"
        f"{'  ★' if is_best else ''}",
        fontsize=10,
        color="green" if is_best else "black",
        fontweight="bold" if is_best else "normal")

for i in range(col + 1, n_cols):
    axes[0, i].axis("off")

# Bottom: bar chart, vector diagram, summary text
ax = axes[1, 0]
labels_bar = ["uncorr", "stage"]
dists_bar = [raw_dist, stage_rdist]
colors_bar = ["magenta", "orange"]
for r in pan_results:
    if r["failed"]:
        continue
    labels_bar.append(f"pan\n{r['label']}")
    dists_bar.append(r["residual_dist_um"])
    is_best = best_pan and r["label"] == best_pan["label"]
    colors_bar.append("green" if is_best else "gray")
bars = ax.bar(labels_bar, dists_bar, color=colors_bar, alpha=0.7)
for bar, d in zip(bars, dists_bar):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.2,
            f"{d:.1f}", ha="center", fontsize=8)
ax.set_ylabel("Residual (um)")
ax.set_title("Progression")

# Vector diagram
ax = axes[1, 1]
lim = max(abs(raw_dx), abs(raw_dy), 5) * 1.5
ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim)
ax.set_aspect("equal")
ax.axhline(0, color="gray", lw=0.5); ax.axvline(0, color="gray", lw=0.5)
ax.plot(0, 0, "go", ms=10, label="target (0)")
ax.plot(raw_dx, raw_dy, "m^", ms=10, label=f"uncorr ({raw_dist:.1f})")
ax.plot(stage_rdx, stage_rdy, "o", ms=10, color="orange",
        label=f"stage ({stage_rdist:.1f})")
for r in pan_results:
    if r["failed"]:
        continue
    is_best = best_pan and r["label"] == best_pan["label"]
    ax.plot(r["residual_x_um"], r["residual_y_um"],
            "*" if is_best else "s", ms=10 if is_best else 6,
            color="green" if is_best else "gray",
            label=f"pan {r['label']}: {r['residual_dist_um']:.1f}")
ax.set_xlabel("X (um)"); ax.set_ylabel("Y (um)")
ax.set_title("Residuals")
ax.legend(fontsize=7); ax.grid(True, alpha=0.3)

# Summary text
ax = axes[1, 2]
ax.axis("off")
txt = [
    f"Two-Step Correction",
    f"{ref_label} -> {tgt_label}",
    f"{'─' * 36}",
    f"Uncorrected: {raw_dist:.2f} um",
    f"  ({raw_dx:+.2f}, {raw_dy:+.2f})",
    f"Stage (-X +Y): {stage_rdist:.2f} um",
    f"  ({stage_rdx:+.2f}, {stage_rdy:+.2f})",
    f"{'─' * 36}",
]
for r in pan_results:
    if r["failed"]:
        continue
    is_best = best_pan and r["label"] == best_pan["label"]
    star = " ★" if is_best else ""
    txt.append(f"Pan {r['label']}: {r['residual_dist_um']:.2f} um{star}")
if best_pan and best_pan["residual_dist_um"] < stage_rdist * 0.5:
    txt.append(f"{'─' * 36}")
    txt.append(f"FULL CORRECTION:")
    txt.append(f"  stage = (-shift_x, +shift_y)")
    txt.append(f"  pan_x = {best_pan['sx']:+d} * resid_x/{PAN_SCALE}")
    txt.append(f"  pan_y = {best_pan['sy']:+d} * resid_y/{PAN_SCALE}")
ax.text(0.05, 0.95, "\n".join(txt), transform=ax.transAxes,
        fontsize=10, va="top", fontfamily="monospace",
        bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5))

for i in range(3, n_cols):
    axes[1, i].axis("off")

best_str = f"Pan {best_pan['label']}: {best_pan['residual_dist_um']:.1f} um" if best_pan else "?"
fig.suptitle(
    f"Two-Step: {ref_label} -> {tgt_label}  |  "
    f"Uncorr {raw_dist:.1f}  →  Stage {stage_rdist:.1f}  →  {best_str}",
    fontsize=12, fontweight="bold")
fig.tight_layout()

report_path = os.path.join(out_dir,
    f"pan_correction_{ref_label}_vs_{tgt_label}.png")
fig.savefig(report_path, dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"\n  Report: {report_path}")

# ── Save JSON ────────────────────────────────────────────────────────────

out_data = {
    "timestamp": _ts,
    "ref": {"slot": args.ref_slot, "label": ref_label, "zoom": args.ref_zoom,
            "pixel_um": float(ref_pixel)},
    "target": {"slot": args.target_slot, "label": tgt_label, "zoom": float(tgt_zoom),
               "pixel_um": float(geo_tgt["pixel_w_um"])},
    "motor_delta_um": [float(motor_dx), float(motor_dy)],
    "raw_shift_um": [float(raw_dx), float(raw_dy)],
    "raw_distance_um": float(raw_dist),
    "stage_correction": {"signs": [-1, +1], "label": "-X +Y"},
    "stage_residual_um": [float(stage_rdx), float(stage_rdy)],
    "stage_residual_dist_um": float(stage_rdist),
    "pan_tests": [r for r in pan_results if not r["failed"]],
    "best_pan": best_pan["label"] if best_pan and best_pan["residual_dist_um"] < stage_rdist * 0.5 else None,
}
json_path = os.path.join(out_dir, "pan_correction_results.json")
with open(json_path, "w") as f:
    json.dump(out_data, f, indent=2)
print(f"  JSON: {json_path}")

# ── Restore ──────────────────────────────────────────────────────────────

print(f"\n  Restoring...")
set_pan(0, 0)
setup_objective(args.ref_slot, args.ref_zoom)
drv.move_xy(client, home["x_um"], home["y_um"])
time.sleep(1)
print("  Done.")

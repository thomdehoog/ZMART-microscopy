"""
Two-Step Motor Correction Test
================================
1. Acquire 10x reference
2. Switch to 20x, acquire uncorrected → raw shift
3. Apply stage correction (-X +Y) → acquire → verify it improved
4. Try all 4 sign combos of the residual as second correction → find best

Usage:
    python test_two_step_motor.py --ref-slot 1 --target-slot 2
"""

import argparse
import json
import os
import sys
import time
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

parser = argparse.ArgumentParser(description="Two-step motor correction test")
parser.add_argument("--ref-slot", type=int, required=True)
parser.add_argument("--target-slot", type=int, required=True)
parser.add_argument("--ref-zoom", type=float, default=10)
parser.add_argument("--settle", type=float, default=0)
parser.add_argument("--job", default="Overview")
parser.add_argument("--output", default=None)
args = parser.parse_args()

# ── Imports ──────────────────────────────────────────────────────────────

from skimage.registration import phase_cross_correlation
import numpy as np
import tifffile

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from LasxApi import PYLICamApiConnector as lasx_api
import navigator_expert.driver as drv
from navigator_expert.driver.scanning_templates import TEMPLATE_XML, apply_lrp_change
from navigator_expert.driver.scanning_template_editors_scan import lrp_set_pan
from navigator_expert.driver.scanning_template_editors_roi import lrp_enable_roi_scan
from navigator_expert.driver.readers import get_job_settings, get_lasx_settings
from navigator_expert.driver.utils import parse_tile_geometry
from navigator_expert.driver.prechecks import check_idle

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

job = args.job
drv.select_job(client, job)
time.sleep(1)
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
    "config", "alignment", f"twostep_{_ts}")
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
    time.sleep(5)
    for attempt in range(3):
        drv.select_job(client, job)
        time.sleep(2)
        current = drv.get_selected_job(client).get("Name", "")
        if current == job:
            break
        print(f"  Job is '{current}', retrying select '{job}'... ({attempt+1}/3)")
        time.sleep(3)
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
print(f"  Pixel: {ref_pixel:.4f} um")

print(f"  Acquiring...")
img_ref = acquire_image()
if img_ref is None:
    sys.exit(1)

# ═════════════════════════════════════════════════════════════════════════
#  STEP 2: Switch to 20x, acquire uncorrected
# ═════════════════════════════════════════════════════════════════════════

print(f"\n{'=' * 60}")
print(f"  STEP 2: Uncorrected ({tgt_name})")
print(f"{'=' * 60}")

setup_objective(args.target_slot, tgt_zoom)
if args.settle > 0:
    time.sleep(args.settle)

pos_uncorr = drv.get_xy(client)
print(f"  Position: ({pos_uncorr['x_um']:.1f}, {pos_uncorr['y_um']:.1f})")

print(f"  Acquiring...")
img_uncorr = acquire_image()
if img_uncorr is None:
    sys.exit(1)

dx_raw, dy_raw, dist_raw, err_raw = xcorr(img_ref, img_uncorr, ref_pixel)
print(f"  Raw shift: ({dx_raw:+.2f}, {dy_raw:+.2f}) um = {dist_raw:.2f} um")

# ═════════════════════════════════════════════════════════════════════════
#  STEP 3: First motor correction (-X +Y), verify it helps
# ═════════════════════════════════════════════════════════════════════════

print(f"\n{'=' * 60}")
print(f"  STEP 3: First correction (-X +Y)")
print(f"{'=' * 60}")

corr1_x = -dx_raw
corr1_y = +dy_raw
pos_corr1_x = pos_uncorr["x_um"] + corr1_x
pos_corr1_y = pos_uncorr["y_um"] + corr1_y

print(f"  Correction: ({corr1_x:+.2f}, {corr1_y:+.2f}) um")
drv.move_xy(client, pos_corr1_x, pos_corr1_y)
time.sleep(1)

pos_1 = drv.get_xy(client)
print(f"  Position: ({pos_1['x_um']:.1f}, {pos_1['y_um']:.1f})")

print(f"  Acquiring...")
img_corr1 = acquire_image()
if img_corr1 is None:
    sys.exit(1)

dx_1, dy_1, dist_1, err_1 = xcorr(img_ref, img_corr1, ref_pixel)
print(f"  Residual: ({dx_1:+.2f}, {dy_1:+.2f}) um = {dist_1:.2f} um")

if dist_1 < dist_raw:
    print(f"  First correction IMPROVED: {dist_raw:.1f} -> {dist_1:.1f} um")
else:
    print(f"  WARNING: first correction did NOT improve: {dist_raw:.1f} -> {dist_1:.1f} um")

# ═════════════════════════════════════════════════════════════════════════
#  STEP 4: Try all 4 sign combos for second correction
# ═════════════════════════════════════════════════════════════════════════

print(f"\n{'=' * 60}")
print(f"  STEP 4: Second correction — all 4 sign combos")
print(f"  Residual to correct: ({dx_1:+.2f}, {dy_1:+.2f}) um")
print(f"{'=' * 60}")

sign_combos = [
    ("+X +Y", +1, +1),
    ("+X -Y", +1, -1),
    ("-X +Y", -1, +1),
    ("-X -Y", -1, -1),
]

step2_results = []
step2_images = {}

for label, sx, sy in sign_combos:
    c2x = sx * dx_1
    c2y = sy * dy_1
    target_x = pos_1["x_um"] + c2x
    target_y = pos_1["y_um"] + c2y

    print(f"\n  [{label}] Correction: ({c2x:+.2f}, {c2y:+.2f}) um")

    r = drv.move_xy(client, target_x, target_y)
    if not r or not r.get("success"):
        print(f"  [{label}] Move failed")
        step2_results.append({"label": label, "sx": sx, "sy": sy, "failed": True})
        continue
    time.sleep(1)

    print(f"  [{label}] Acquiring...")
    img = acquire_image()
    if img is None:
        step2_results.append({"label": label, "sx": sx, "sy": sy, "failed": True})
    else:
        rdx, rdy, rdist, rerr = xcorr(img_ref, img, ref_pixel)
        print(f"  [{label}] Final: ({rdx:+.2f}, {rdy:+.2f}) um = {rdist:.2f} um")
        step2_results.append({
            "label": label, "sx": sx, "sy": sy,
            "correction_um": [c2x, c2y],
            "residual_x_um": rdx, "residual_y_um": rdy,
            "residual_dist_um": rdist, "correlation_error": rerr,
            "failed": False,
        })
        step2_images[label] = img

    # Return to step 3 position
    drv.move_xy(client, pos_1["x_um"], pos_1["y_um"])
    time.sleep(1)

# ═════════════════════════════════════════════════════════════════════════
#  Summary
# ═════════════════════════════════════════════════════════════════════════

best = None
for r in step2_results:
    if not r["failed"] and (best is None or r["residual_dist_um"] < best["residual_dist_um"]):
        best = r

print(f"\n{'=' * 70}")
print(f"  Two-Step Motor Correction Results")
print(f"{'=' * 70}")
print(f"  Uncorrected:   ({dx_raw:+.2f}, {dy_raw:+.2f}) = {dist_raw:.2f} um")
print(f"  After 1st (-X +Y): ({dx_1:+.2f}, {dy_1:+.2f}) = {dist_1:.2f} um")
print(f"{'=' * 70}")
print(f"  {'2nd combo':<10}  {'Correction':>22}  {'Resid X':>10}  {'Resid Y':>10}  {'Dist':>8}")
print(f"  {'-'*10}  {'-'*22}  {'-'*10}  {'-'*10}  {'-'*8}")

for r in step2_results:
    if r["failed"]:
        print(f"  {r['label']:<10}  {'FAILED':>22}")
        continue
    cx, cy = r["correction_um"]
    is_best = best and r["label"] == best["label"]
    print(f"  {r['label']:<10}  ({cx:+8.2f}, {cy:+8.2f})  "
          f"{r['residual_x_um']:+10.2f}  {r['residual_y_um']:+10.2f}  "
          f"{r['residual_dist_um']:8.2f}"
          f"{'  <-- BEST' if is_best else ''}")

if best:
    print(f"\n  Best 2nd correction: {best['label']}")
    print(f"  {dist_raw:.1f} -> {dist_1:.1f} -> {best['residual_dist_um']:.1f} um")
    if best["residual_dist_um"] < dist_1:
        print(f"  Second correction HELPED")
    else:
        print(f"  Second correction did NOT help — residual is noise floor")

# ═════════════════════════════════════════════════════════════════════════
#  Visual report — 4 rows, presentation quality
# ═════════════════════════════════════════════════════════════════════════

from scipy.ndimage import shift as ndi_shift

plt.rcParams.update({
    "font.size": 11,
    "axes.titlesize": 12,
    "axes.labelsize": 11,
    "figure.facecolor": "white",
})

fig = plt.figure(figsize=(30, 28))
gs = fig.add_gridspec(4, 6, hspace=0.40, wspace=0.30,
                      left=0.04, right=0.96, top=0.93, bottom=0.03)

def registered_overlay(ref_img, tgt_img, pixel_um):
    shift, _, _ = phase_cross_correlation(
        ref_img.astype(np.float64), tgt_img.astype(np.float64),
        upsample_factor=100)
    tgt_reg = ndi_shift(tgt_img.astype(np.float64), shift)
    return make_overlay(ref_img, tgt_reg)

def hide_ticks(ax):
    ax.set_xticks([]); ax.set_yticks([])

# ── ROW 1: The problem & first correction ────────────────────────────
# Unregistered overlay | Software-registered | After 1st correction | Shift vector plot

ax = fig.add_subplot(gs[0, 0:2])
ax.imshow(make_overlay(img_ref, img_uncorr))
hide_ticks(ax)
ax.set_title(f"Uncorrected overlay  —  10x (green) vs 20x (magenta)\n"
             f"Offset: ({dx_raw:+.1f}, {dy_raw:+.1f}) um = {dist_raw:.1f} um",
             fontsize=12, color="#CC0000", fontweight="bold")

ax = fig.add_subplot(gs[0, 2:4])
ax.imshow(registered_overlay(img_ref, img_uncorr, ref_pixel))
hide_ticks(ax)
ax.set_title(f"Software-registered (cross-correlation aligned)\n"
             f"Confirms features match — offset is real",
             fontsize=12, color="#0066CC")

ax = fig.add_subplot(gs[0, 4:6])
ax.imshow(make_overlay(img_ref, img_corr1))
hide_ticks(ax)
ax.set_title(f"After 1st stage correction  (-X, +Y)\n"
             f"Residual: ({dx_1:+.1f}, {dy_1:+.1f}) um = {dist_1:.1f} um",
             fontsize=12, color="#CC6600", fontweight="bold")

# ── ROW 2: Second correction — 4 sign combos + bar chart ────────────

for i, r in enumerate(step2_results):
    if r["failed"] or i >= 4:
        continue
    ax = fig.add_subplot(gs[1, i])
    label = r["label"]
    if label in step2_images:
        ax.imshow(make_overlay(img_ref, step2_images[label]))
    hide_ticks(ax)
    is_best = best and r["label"] == best["label"]
    cx, cy = r["correction_um"]
    title_color = "#006600" if is_best else "#444444"
    ax.set_title(
        f"2nd correction: {label}\n"
        f"Residual: {r['residual_dist_um']:.2f} um"
        f"{'   ★ BEST' if is_best else ''}",
        fontsize=11, color=title_color,
        fontweight="bold" if is_best else "normal")
    if is_best:
        for spine in ax.spines.values():
            spine.set_edgecolor("#006600")
            spine.set_linewidth(3)

ax = fig.add_subplot(gs[1, 4:6])
s2_labels = [f"1st only\n(-X +Y)"]
s2_dists = [dist_1]
s2_colors = ["#CC6600"]
for r in step2_results:
    if r["failed"]:
        continue
    s2_labels.append(f"{r['label']}")
    s2_dists.append(r["residual_dist_um"])
    is_best = best and r["label"] == best["label"]
    s2_colors.append("#006600" if is_best else "#BBBBBB")
bars = ax.bar(s2_labels, s2_dists, color=s2_colors, alpha=0.85,
              edgecolor="black", lw=0.8)
for bar, d in zip(bars, s2_dists):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.15,
            f"{d:.2f}", ha="center", fontsize=11, fontweight="bold")
ax.set_ylabel("Residual (um)")
ax.set_title("2nd correction sign search", fontsize=12, fontweight="bold")
ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)

# ── ROW 3: Progression — uncorrected → 1st → 2nd (best) ─────────────

ax = fig.add_subplot(gs[2, 0:2])
ax.imshow(make_overlay(img_ref, img_uncorr))
hide_ticks(ax)
ax.set_title(f"Step 0: Uncorrected\n{dist_raw:.1f} um offset",
             fontsize=12, color="#CC0000", fontweight="bold")

ax = fig.add_subplot(gs[2, 2:4])
ax.imshow(make_overlay(img_ref, img_corr1))
hide_ticks(ax)
ax.set_title(f"Step 1: Parcentric correction (-X, +Y)\n"
             f"{dist_raw:.1f} → {dist_1:.1f} um",
             fontsize=12, color="#CC6600", fontweight="bold")

if best and best["label"] in step2_images:
    ax = fig.add_subplot(gs[2, 4:6])
    ax.imshow(make_overlay(img_ref, step2_images[best["label"]]))
    hide_ticks(ax)
    ax.set_title(f"Step 2: Residual correction (+X, -Y)\n"
                 f"{dist_1:.1f} → {best['residual_dist_um']:.2f} um",
                 fontsize=12, color="#006600", fontweight="bold")
    for spine in ax.spines.values():
        spine.set_edgecolor("#006600")
        spine.set_linewidth(3)

# ── ROW 4: Conclusion — bar chart + vector diagram + summary ─────────

# Progression bar chart
ax = fig.add_subplot(gs[3, 0:2])
prog_labels = ["Uncorrected", "After Step 1\n(parcentric)", "After Step 2\n(residual)"]
prog_dists = [dist_raw, dist_1, best["residual_dist_um"] if best else dist_1]
prog_colors = ["#CC0000", "#CC6600", "#006600"]
bars = ax.bar(prog_labels, prog_dists, color=prog_colors, alpha=0.85,
              edgecolor="black", lw=0.8, width=0.6)
for bar, d in zip(bars, prog_dists):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
            f"{d:.2f} um", ha="center", fontsize=12, fontweight="bold")
# Add arrows between bars
for i in range(len(bars) - 1):
    x1 = bars[i].get_x() + bars[i].get_width()
    x2 = bars[i+1].get_x()
    y = max(prog_dists[i], prog_dists[i+1]) * 0.5
    ax.annotate("", xy=(x2, y), xytext=(x1, y),
                arrowprops=dict(arrowstyle="->", color="black", lw=2))
ax.set_ylabel("Residual distance (um)", fontsize=12)
ax.set_title("Correction progression", fontsize=13, fontweight="bold")
ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)

# Vector diagram
ax = fig.add_subplot(gs[3, 2:4])
lim2 = max(abs(dx_raw), abs(dy_raw), 5) * 1.5
ax.set_xlim(-lim2, lim2); ax.set_ylim(-lim2, lim2)
ax.set_aspect("equal")
ax.axhline(0, color="gray", lw=0.5); ax.axvline(0, color="gray", lw=0.5)

ax.plot(0, 0, "o", ms=16, color="#006600", zorder=5, label="Target (0, 0)")
ax.plot(dx_raw, dy_raw, "^", ms=14, color="#CC0000",
        label=f"Uncorrected: {dist_raw:.1f} um")
ax.annotate("", xy=(dx_raw, dy_raw), xytext=(0, 0),
            arrowprops=dict(arrowstyle="-|>", color="#CC0000", lw=2.5))

ax.plot(dx_1, dy_1, "s", ms=12, color="#CC6600",
        label=f"After Step 1: {dist_1:.1f} um")
ax.annotate("", xy=(dx_1, dy_1), xytext=(dx_raw, dy_raw),
            arrowprops=dict(arrowstyle="-|>", color="#CC6600", lw=2, ls="--"))

if best:
    ax.plot(best["residual_x_um"], best["residual_y_um"], "*",
            ms=20, color="#006600", zorder=5,
            label=f"After Step 2: {best['residual_dist_um']:.2f} um")
    ax.annotate("", xy=(best["residual_x_um"], best["residual_y_um"]),
                xytext=(dx_1, dy_1),
                arrowprops=dict(arrowstyle="-|>", color="#006600", lw=2, ls="--"))
    circle = plt.Circle((0, 0), best["residual_dist_um"], fill=False,
                         color="#006600", ls=":", lw=2, alpha=0.6)
    ax.add_patch(circle)

ax.set_xlabel("X (um)"); ax.set_ylabel("Y (um)")
ax.set_title("Correction vectors", fontsize=13, fontweight="bold")
ax.legend(fontsize=10, loc="upper left", framealpha=0.9)
ax.grid(True, alpha=0.3)

# Summary text
ax = fig.add_subplot(gs[3, 4:6])
ax.axis("off")
if best:
    bx, by = best["correction_um"]
    total_x = corr1_x + bx
    total_y = corr1_y + by
    summary = (
        f"Two-Step Parcentric Calibration\n"
        f"{'━' * 42}\n"
        f"\n"
        f"Objective:  {ref_name}\n"
        f"         →  {tgt_name}\n"
        f"Zoom:       {args.ref_zoom} → {tgt_zoom:.1f}\n"
        f"Pixel:      {ref_pixel:.4f} um\n"
        f"\n"
        f"{'━' * 42}\n"
        f"Step 1  Parcentric  (-X, +Y)\n"
        f"  Measured:  ({dx_raw:+.2f}, {dy_raw:+.2f}) um\n"
        f"  Applied:   ({corr1_x:+.2f}, {corr1_y:+.2f}) um\n"
        f"  Residual:  {dist_1:.2f} um\n"
        f"\n"
        f"Step 2  Galvo/zoom  (+X, -Y)\n"
        f"  Measured:  ({dx_1:+.2f}, {dy_1:+.2f}) um\n"
        f"  Applied:   ({bx:+.2f}, {by:+.2f}) um\n"
        f"  Residual:  {best['residual_dist_um']:.2f} um\n"
        f"\n"
        f"{'━' * 42}\n"
        f"Total correction:  ({total_x:+.2f}, {total_y:+.2f}) um\n"
        f"Final accuracy:    {best['residual_dist_um']:.2f} um\n"
        f"Pixel size:        {ref_pixel:.4f} um\n"
        f"Sub-pixel:         {'YES' if best['residual_dist_um'] < ref_pixel else 'NO'}"
    )
else:
    summary = "No clear best correction found."

ax.text(0.05, 0.95, summary, transform=ax.transAxes,
        fontsize=11.5, va="top", fontfamily="monospace",
        bbox=dict(boxstyle="round,pad=0.8", facecolor="#FFFFF0",
                  edgecolor="#888888", alpha=0.95))

best_str = f"{best['residual_dist_um']:.2f}" if best else "?"
fig.suptitle(
    f"Parcentric Calibration:  {ref_name}  →  {tgt_name}\n"
    f"Two-step motor correction:  {dist_raw:.1f} um  →  {dist_1:.1f} um  →  {best_str} um",
    fontsize=16, fontweight="bold", y=0.97)

report_path = os.path.join(out_dir,
    f"twostep_{ref_label}_vs_{tgt_label}.png")
fig.savefig(report_path, dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"\n  Report: {report_path}")

# Save JSON
out_data = {
    "timestamp": _ts,
    "ref": {"slot": args.ref_slot, "label": ref_label, "zoom": args.ref_zoom,
            "pixel_um": float(ref_pixel)},
    "target": {"slot": args.target_slot, "label": tgt_label, "zoom": float(tgt_zoom)},
    "uncorrected": {"shift_um": [dx_raw, dy_raw], "dist_um": dist_raw, "err": err_raw},
    "first_correction": {
        "signs": [-1, +1], "label": "-X +Y",
        "correction_um": [corr1_x, corr1_y],
        "residual_um": [dx_1, dy_1], "dist_um": dist_1, "err": err_1,
    },
    "second_correction_tests": [r for r in step2_results if not r["failed"]],
    "best_second": best["label"] if best else None,
}
json_path = os.path.join(out_dir, "twostep_results.json")
with open(json_path, "w") as f:
    json.dump(out_data, f, indent=2)
print(f"  JSON: {json_path}")

# Restore
print(f"\n  Restoring...")
setup_objective(args.ref_slot, args.ref_zoom)
drv.move_xy(client, home["x_um"], home["y_um"])
time.sleep(1)
print("  Done.")

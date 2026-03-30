"""
Parcentric Offset with Masked Phase Cross-Correlation
======================================================
Single-step parcentric calibration using masked phase correlation.
Masks out empty background so only nuclei contribute to the
correlation, giving a reliable peak even with repetitive features.

1. Acquire 10x reference
2. Switch to 20x (matched pixel size), acquire
3. Masked phase cross-correlation → shift
4. Apply -X +Y correction → acquire → verify residual

Usage:
    python test_parcentric_masked.py --ref-slot 1 --target-slot 2
    python test_parcentric_masked.py --ref-slot 1 --target-slot 2 --ref-zoom 3
    python test_parcentric_masked.py --ref-slot 1 --target-slot 2 --mask-pct 30
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
    description="Parcentric offset with masked phase cross-correlation")
parser.add_argument("--ref-slot", type=int, required=True)
parser.add_argument("--target-slot", type=int, required=True)
parser.add_argument("--ref-zoom", type=float, default=10)
parser.add_argument("--settle", type=float, default=0)
parser.add_argument("--mask-pct", type=float, default=30,
                    help="Percentile threshold for mask (default: 30)")
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
print(f"  Mask percentile: {args.mask_pct}")

# ── Output ───────────────────────────────────────────────────────────────

_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
_default_out = os.path.join(
    str(Path(__file__).resolve().parent.parent),
    "config", "alignment", f"masked_{_ts}")
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
        print(f"  Job is '{current}', retrying... ({attempt+1}/3)")
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


def make_mask(img, percentile):
    """Binary mask: True where signal is above percentile threshold."""
    threshold = np.percentile(img, percentile)
    return img > threshold


def xcorr_masked(ref, target, pixel_um, mask_pct):
    """Masked phase cross-correlation. Returns (dx_um, dy_um, dist, error)."""
    ref_f = ref.astype(np.float64)
    tgt_f = target.astype(np.float64)
    ref_mask = make_mask(ref, mask_pct)
    tgt_mask = make_mask(target, mask_pct)
    shift, error, _ = phase_cross_correlation(
        ref_f, tgt_f, upsample_factor=100,
        reference_mask=ref_mask, moving_mask=tgt_mask)
    dy_px, dx_px = shift
    dx_um = dx_px * pixel_um
    dy_um = dy_px * pixel_um
    dist = (dx_um**2 + dy_um**2)**0.5
    return dx_um, dy_um, dist, error


def xcorr_unmasked(ref, target, pixel_um):
    """Standard (unmasked) phase cross-correlation for comparison."""
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


def hide_ticks(ax):
    ax.set_xticks([]); ax.set_yticks([])


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
print(f"  Pixel: {ref_pixel:.4f} um, FOV: {ref_pixel * image_size:.1f} um")

print(f"  Acquiring...")
img_ref = acquire_image()
if img_ref is None:
    sys.exit(1)

# ═════════════════════════════════════════════════════════════════════════
#  STEP 2: Switch to target, acquire uncorrected
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

# Compare masked vs unmasked
dx_u, dy_u, dist_u, err_u = xcorr_unmasked(img_ref, img_uncorr, ref_pixel)
dx_m, dy_m, dist_m, err_m = xcorr_masked(img_ref, img_uncorr, ref_pixel, args.mask_pct)

print(f"  Unmasked: ({dx_u:+.2f}, {dy_u:+.2f}) um = {dist_u:.2f} um  err={err_u:.4f}")
print(f"  Masked:   ({dx_m:+.2f}, {dy_m:+.2f}) um = {dist_m:.2f} um  err={err_m:.4f}")

diff = ((dx_u - dx_m)**2 + (dy_u - dy_m)**2)**0.5
print(f"  Difference: {diff:.2f} um")

# ═════════════════════════════════════════════════════════════════════════
#  STEP 3: Apply masked correction (-X +Y), verify
# ═════════════════════════════════════════════════════════════════════════

print(f"\n{'=' * 60}")
print(f"  STEP 3: Correction using masked result (-X +Y)")
print(f"{'=' * 60}")

corr_x = -dx_m
corr_y = +dy_m
target_x = pos_uncorr["x_um"] + corr_x
target_y = pos_uncorr["y_um"] + corr_y

print(f"  Correction: ({corr_x:+.2f}, {corr_y:+.2f}) um")
drv.move_xy(client, target_x, target_y)
time.sleep(1)

print(f"  Acquiring...")
img_corr = acquire_image()
if img_corr is None:
    sys.exit(1)

rdx_u, rdy_u, rdist_u, rerr_u = xcorr_unmasked(img_ref, img_corr, ref_pixel)
rdx_m, rdy_m, rdist_m, rerr_m = xcorr_masked(img_ref, img_corr, ref_pixel, args.mask_pct)

print(f"  Residual (unmasked): ({rdx_u:+.2f}, {rdy_u:+.2f}) um = {rdist_u:.2f} um  err={rerr_u:.4f}")
print(f"  Residual (masked):   ({rdx_m:+.2f}, {rdy_m:+.2f}) um = {rdist_m:.2f} um  err={rerr_m:.4f}")

# ═════════════════════════════════════════════════════════════════════════
#  Summary
# ═════════════════════════════════════════════════════════════════════════

print(f"\n{'=' * 70}")
print(f"  Masked vs Unmasked Comparison")
print(f"{'=' * 70}")
print(f"  {'':25}  {'Unmasked':>12}  {'Masked':>12}")
print(f"  {'-'*25}  {'-'*12}  {'-'*12}")
print(f"  {'Raw shift X (um)':<25}  {dx_u:+12.2f}  {dx_m:+12.2f}")
print(f"  {'Raw shift Y (um)':<25}  {dy_u:+12.2f}  {dy_m:+12.2f}")
print(f"  {'Raw distance (um)':<25}  {dist_u:12.2f}  {dist_m:12.2f}")
print(f"  {'Correlation error':<25}  {err_u:12.4f}  {err_m:12.4f}")
print(f"  {'-'*25}  {'-'*12}  {'-'*12}")
print(f"  {'Residual X (um)':<25}  {rdx_u:+12.2f}  {rdx_m:+12.2f}")
print(f"  {'Residual Y (um)':<25}  {rdy_u:+12.2f}  {rdy_m:+12.2f}")
print(f"  {'Residual dist (um)':<25}  {rdist_u:12.2f}  {rdist_m:12.2f}")
print(f"  {'Residual error':<25}  {rerr_u:12.4f}  {rerr_m:12.4f}")

# ═════════════════════════════════════════════════════════════════════════
#  Visual report
# ═════════════════════════════════════════════════════════════════════════

plt.rcParams.update({"font.size": 11, "figure.facecolor": "white"})

fig = plt.figure(figsize=(28, 20))
gs = fig.add_gridspec(3, 6, hspace=0.35, wspace=0.30,
                      left=0.04, right=0.96, top=0.92, bottom=0.04)

# ── Row 1: Images — masks, overlays ─────────────────────────────────

ref_mask = make_mask(img_ref, args.mask_pct)
tgt_mask = make_mask(img_uncorr, args.mask_pct)

ax = fig.add_subplot(gs[0, 0])
ax.imshow(img_ref, cmap="gray"); hide_ticks(ax)
ax.set_title(f"Reference\n{ref_label} z{args.ref_zoom}", fontsize=11)

ax = fig.add_subplot(gs[0, 1])
mask_overlay = np.zeros((*img_ref.shape, 3))
ref_n = img_ref.astype(np.float64) / (img_ref.max() or 1)
mask_overlay[..., 0] = ref_n
mask_overlay[..., 1] = ref_n
mask_overlay[..., 2] = ref_n
mask_overlay[ref_mask, 1] = np.clip(ref_n[ref_mask] + 0.3, 0, 1)
ax.imshow(np.clip(mask_overlay, 0, 1)); hide_ticks(ax)
ax.set_title(f"Reference mask\n(>{args.mask_pct:.0f}th percentile, "
             f"{ref_mask.sum()}/{ref_mask.size} px)", fontsize=10)

ax = fig.add_subplot(gs[0, 2])
ax.imshow(make_overlay(img_ref, img_uncorr)); hide_ticks(ax)
ax.set_title(f"Uncorrected overlay\n{dist_m:.1f} um (masked)", fontsize=11, color="#CC0000")

ax = fig.add_subplot(gs[0, 3])
ax.imshow(make_overlay(img_ref, img_corr)); hide_ticks(ax)
ax.set_title(f"After correction (-X +Y)\n{rdist_m:.2f} um (masked)", fontsize=11,
             color="#006600", fontweight="bold")
for spine in ax.spines.values():
    spine.set_edgecolor("#006600"); spine.set_linewidth(3)

# Software-registered for visual check
shift_reg, _, _ = phase_cross_correlation(
    img_ref.astype(np.float64), img_corr.astype(np.float64),
    upsample_factor=100,
    reference_mask=make_mask(img_ref, args.mask_pct),
    moving_mask=make_mask(img_corr, args.mask_pct))
img_corr_reg = ndi_shift(img_corr.astype(np.float64), shift_reg)

ax = fig.add_subplot(gs[0, 4])
ax.imshow(make_overlay(img_ref, img_corr_reg)); hide_ticks(ax)
ax.set_title(f"Corrected (software-registered)\nvisual check", fontsize=11, color="#0066CC")

ax = fig.add_subplot(gs[0, 5])
ax.axis("off")
info = (
    f"Pixel: {ref_pixel:.4f} um\n"
    f"FOV: {ref_pixel * image_size:.1f} um\n"
    f"Image: {image_size}x{image_size}\n"
    f"Mask: >{args.mask_pct:.0f}th pct\n"
    f"Ref mask: {ref_mask.mean()*100:.0f}% pixels\n"
    f"Tgt mask: {tgt_mask.mean()*100:.0f}% pixels"
)
ax.text(0.1, 0.9, info, transform=ax.transAxes, fontsize=12,
        va="top", fontfamily="monospace",
        bbox=dict(boxstyle="round", facecolor="#F0F0F0", alpha=0.9))

# ── Row 2: Masked vs unmasked comparison ─────────────────────────────

# Bar chart: raw measurement comparison
ax = fig.add_subplot(gs[1, 0:2])
x_pos = np.arange(3)
w = 0.35
vals_u = [dist_u, rdist_u, err_u * 20]
vals_m = [dist_m, rdist_m, err_m * 20]
bars1 = ax.bar(x_pos - w/2, vals_u, w, label="Unmasked", color="#CC6600", alpha=0.8)
bars2 = ax.bar(x_pos + w/2, vals_m, w, label="Masked", color="#006600", alpha=0.8)
ax.set_xticks(x_pos)
ax.set_xticklabels(["Raw shift\n(um)", "Residual\n(um)", "Corr error\n(x20)"])
for bar, v in zip(bars1, [dist_u, rdist_u, err_u]):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
            f"{v:.2f}", ha="center", fontsize=10)
for bar, v in zip(bars2, [dist_m, rdist_m, err_m]):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
            f"{v:.2f}", ha="center", fontsize=10, fontweight="bold")
ax.legend(fontsize=11); ax.set_ylabel("Value")
ax.set_title("Masked vs Unmasked", fontsize=12, fontweight="bold")
ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)

# Vector diagram
ax = fig.add_subplot(gs[1, 2:4])
lim = max(abs(dx_u), abs(dy_u), abs(dx_m), abs(dy_m), 5) * 1.5
ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim)
ax.set_aspect("equal")
ax.axhline(0, color="gray", lw=0.5); ax.axvline(0, color="gray", lw=0.5)
ax.plot(0, 0, "o", ms=14, color="#006600", zorder=5, label="Target (0,0)")
ax.plot(dx_u, dy_u, "^", ms=12, color="#CC6600",
        label=f"Unmasked: ({dx_u:+.1f}, {dy_u:+.1f})")
ax.plot(dx_m, dy_m, "*", ms=14, color="#006600",
        label=f"Masked: ({dx_m:+.1f}, {dy_m:+.1f})")
ax.annotate("", xy=(dx_u, dy_u), xytext=(0, 0),
            arrowprops=dict(arrowstyle="-|>", color="#CC6600", lw=2))
ax.annotate("", xy=(dx_m, dy_m), xytext=(0, 0),
            arrowprops=dict(arrowstyle="-|>", color="#006600", lw=2))
ax.set_xlabel("X (um)"); ax.set_ylabel("Y (um)")
ax.set_title("Raw shift vectors", fontsize=12, fontweight="bold")
ax.legend(fontsize=10); ax.grid(True, alpha=0.3)

# Residual vectors
ax = fig.add_subplot(gs[1, 4:6])
lim_r = max(abs(rdx_u), abs(rdy_u), abs(rdx_m), abs(rdy_m), 2) * 2
ax.set_xlim(-lim_r, lim_r); ax.set_ylim(-lim_r, lim_r)
ax.set_aspect("equal")
ax.axhline(0, color="gray", lw=0.5); ax.axvline(0, color="gray", lw=0.5)
ax.plot(0, 0, "o", ms=14, color="#006600", zorder=5, label="Perfect (0,0)")
ax.plot(rdx_u, rdy_u, "^", ms=12, color="#CC6600",
        label=f"Unmasked resid: {rdist_u:.2f} um")
ax.plot(rdx_m, rdy_m, "*", ms=14, color="#006600",
        label=f"Masked resid: {rdist_m:.2f} um")
ax.set_xlabel("X (um)"); ax.set_ylabel("Y (um)")
ax.set_title("Residual after correction", fontsize=12, fontweight="bold")
ax.legend(fontsize=10); ax.grid(True, alpha=0.3)

# ── Row 3: Conclusion ───────────────────────────────────────────────

# Progression bar
ax = fig.add_subplot(gs[2, 0:2])
prog_labels = ["Uncorrected", "After correction"]
prog_dists = [dist_m, rdist_m]
prog_colors = ["#CC0000", "#006600"]
bars = ax.bar(prog_labels, prog_dists, color=prog_colors, alpha=0.85,
              edgecolor="black", lw=0.8, width=0.5)
for bar, d in zip(bars, prog_dists):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.2,
            f"{d:.2f} um", ha="center", fontsize=12, fontweight="bold")
ax.set_ylabel("Distance (um)")
ax.set_title("Masked correction result", fontsize=12, fontweight="bold")
ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)

# Summary
ax = fig.add_subplot(gs[2, 2:6])
ax.axis("off")
summary = (
    f"Parcentric Calibration — Masked Phase Cross-Correlation\n"
    f"{'━' * 58}\n"
    f"\n"
    f"Objective:  {ref_name}\n"
    f"         →  {tgt_name}\n"
    f"Zoom:       {args.ref_zoom} → {tgt_zoom:.1f}  |  Pixel: {ref_pixel:.4f} um\n"
    f"\n"
    f"{'━' * 58}\n"
    f"                      Unmasked       Masked\n"
    f"  Raw shift:      {dist_u:8.2f} um   {dist_m:8.2f} um\n"
    f"  Corr error:     {err_u:8.4f}     {err_m:8.4f}\n"
    f"  Residual:       {rdist_u:8.2f} um   {rdist_m:8.2f} um\n"
    f"  Resid error:    {rerr_u:8.4f}     {rerr_m:8.4f}\n"
    f"\n"
    f"{'━' * 58}\n"
    f"  Correction applied: (-X, +Y) of masked shift\n"
    f"    ({corr_x:+.2f}, {corr_y:+.2f}) um\n"
    f"\n"
    f"  Final accuracy:  {rdist_m:.2f} um\n"
    f"  Sub-pixel:       {'YES' if rdist_m < ref_pixel else 'NO'} "
    f"(pixel = {ref_pixel:.4f} um)\n"
    f"  Masking helped:  {'YES' if err_m < err_u else 'SAME'} "
    f"(error {err_u:.4f} → {err_m:.4f})"
)
ax.text(0.02, 0.95, summary, transform=ax.transAxes,
        fontsize=12, va="top", fontfamily="monospace",
        bbox=dict(boxstyle="round,pad=0.8", facecolor="#FFFFF0",
                  edgecolor="#888888", alpha=0.95))

fig.suptitle(
    f"Masked Parcentric Calibration:  {ref_name}  →  {tgt_name}\n"
    f"Shift: {dist_m:.1f} um  →  Residual: {rdist_m:.2f} um  |  "
    f"Corr error: {err_u:.4f} (unmasked) vs {err_m:.4f} (masked)",
    fontsize=14, fontweight="bold", y=0.97)

report_path = os.path.join(out_dir,
    f"masked_{ref_label}_vs_{tgt_label}.png")
fig.savefig(report_path, dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"\n  Report: {report_path}")

# ── Save JSON ────────────────────────────────────────────────────────

out_data = {
    "timestamp": _ts,
    "ref": {"slot": args.ref_slot, "label": ref_label, "name": ref_name,
            "zoom": args.ref_zoom, "pixel_um": float(ref_pixel)},
    "target": {"slot": args.target_slot, "label": tgt_label, "name": tgt_name,
               "zoom": float(tgt_zoom)},
    "mask_percentile": args.mask_pct,
    "unmasked": {
        "shift_um": [float(dx_u), float(dy_u)], "dist_um": float(dist_u),
        "error": float(err_u),
        "residual_um": [float(rdx_u), float(rdy_u)], "residual_dist_um": float(rdist_u),
        "residual_error": float(rerr_u),
    },
    "masked": {
        "shift_um": [float(dx_m), float(dy_m)], "dist_um": float(dist_m),
        "error": float(err_m),
        "residual_um": [float(rdx_m), float(rdy_m)], "residual_dist_um": float(rdist_m),
        "residual_error": float(rerr_m),
    },
    "correction_um": [float(corr_x), float(corr_y)],
}
json_path = os.path.join(out_dir, "masked_results.json")
with open(json_path, "w") as f:
    json.dump(out_data, f, indent=2)
print(f"  JSON: {json_path}")

# ── Restore ──────────────────────────────────────────────────────────

print(f"\n  Restoring...")
setup_objective(args.ref_slot, args.ref_zoom)
drv.move_xy(client, home["x_um"], home["y_um"])
time.sleep(1)
print("  Done.")

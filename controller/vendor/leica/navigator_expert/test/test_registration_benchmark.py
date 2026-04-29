"""
Registration Method Benchmark
==============================
Acquires one 10x/20x image pair and tests multiple registration
methods on the same data. Applies the best result and verifies.

Methods tested:
  1. Phase cross-correlation (unmasked)
  2. Masked normalized cross-correlation (Padfield 2012)
  3. OpenCV template matching (TM_CCOEFF_NORMED)
  4. ORB feature matching + RANSAC

Usage:
    python test_registration_benchmark.py --ref-slot 1 --target-slot 2
"""

import argparse
import json
import os
import sys
import time
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

parser = argparse.ArgumentParser(description="Registration method benchmark")
parser.add_argument("--ref-slot", type=int, required=True)
parser.add_argument("--target-slot", type=int, required=True)
parser.add_argument("--ref-zoom", type=float, default=10)
parser.add_argument("--settle", type=float, default=0)
parser.add_argument("--mask-pct", type=float, default=30)
parser.add_argument("--job", default="Overview")
parser.add_argument("--output", default=None)
args = parser.parse_args()

# ── Imports ──────────────────────────────────────────────────────────────

from skimage.registration import phase_cross_correlation
from skimage.feature import ORB, match_descriptors
from skimage.measure import ransac
from skimage.transform import EuclideanTransform
import numpy as np
import tifffile
import cv2

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
    "config", "alignment", f"bench_{_ts}")
out_dir = args.output or _default_out
os.makedirs(out_dir, exist_ok=True)

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
        return None
    img = tifffile.imread(str(sorted(det["image_files"])[0]))
    if img.ndim == 3:
        img = img[0]
    return img


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


# ── Registration methods ─────────────────────────────────────────────────


def method_phase(ref, tgt, pixel_um):
    """Standard phase cross-correlation (unmasked)."""
    shift, error, _ = phase_cross_correlation(
        ref.astype(np.float64), tgt.astype(np.float64),
        upsample_factor=100)
    dy_px, dx_px = shift
    return dx_px * pixel_um, dy_px * pixel_um, float(error)


def method_masked(ref, tgt, pixel_um):
    """Masked cross-correlation (Padfield 2012)."""
    ref_mask = ref > np.percentile(ref, args.mask_pct)
    tgt_mask = tgt > np.percentile(tgt, args.mask_pct)
    shift, error, _ = phase_cross_correlation(
        ref.astype(np.float64), tgt.astype(np.float64),
        upsample_factor=100,
        reference_mask=ref_mask, moving_mask=tgt_mask)
    dy_px, dx_px = shift
    return dx_px * pixel_um, dy_px * pixel_um, float(error)


def method_cv2_ncc(ref, tgt, pixel_um):
    """OpenCV normalized cross-correlation."""
    ref8 = (ref.astype(np.float64) / (ref.max() or 1) * 255).astype(np.uint8)
    tgt8 = (tgt.astype(np.float64) / (tgt.max() or 1) * 255).astype(np.uint8)
    # Use center crop of target as template
    h, w = tgt8.shape
    margin = h // 4
    template = tgt8[margin:h-margin, margin:w-margin]
    result = cv2.matchTemplate(ref8, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    # max_loc is (x, y) of top-left of best match in ref
    # Template center in tgt is at (w/2, h/2)
    # Best match center in ref is at (max_loc[0] + template.shape[1]/2, ...)
    match_cx = max_loc[0] + template.shape[1] / 2
    match_cy = max_loc[1] + template.shape[0] / 2
    dx_px = match_cx - w / 2
    dy_px = match_cy - h / 2
    return dx_px * pixel_um, dy_px * pixel_um, float(max_val)


def method_orb(ref, tgt, pixel_um):
    """ORB feature matching + RANSAC."""
    ref_n = (ref.astype(np.float64) / (ref.max() or 1) * 255).astype(np.uint8)
    tgt_n = (tgt.astype(np.float64) / (tgt.max() or 1) * 255).astype(np.uint8)

    orb = ORB(n_keypoints=500, fast_threshold=0.05)
    orb.detect_and_extract(ref_n)
    kp_ref, desc_ref = orb.keypoints, orb.descriptors

    orb.detect_and_extract(tgt_n)
    kp_tgt, desc_tgt = orb.keypoints, orb.descriptors

    if desc_ref is None or desc_tgt is None or len(desc_ref) < 3 or len(desc_tgt) < 3:
        return np.nan, np.nan, 0.0

    matches = match_descriptors(desc_ref, desc_tgt, cross_check=True)
    if len(matches) < 3:
        return np.nan, np.nan, 0.0

    src = kp_tgt[matches[:, 1]]
    dst = kp_ref[matches[:, 0]]

    model, inliers = ransac(
        (src, dst), EuclideanTransform, min_samples=3,
        residual_threshold=5, max_trials=1000)

    if model is None or inliers is None:
        return np.nan, np.nan, 0.0

    # EuclideanTransform: translation is (tx, ty) in (col, row) = (x, y)
    dy_px = model.translation[0]
    dx_px = model.translation[1]
    n_inliers = inliers.sum()
    return dx_px * pixel_um, dy_px * pixel_um, float(n_inliers / len(matches))


METHODS = [
    ("Phase (unmasked)", method_phase, "#CC6600"),
    ("Masked NCC", method_masked, "#006600"),
    ("OpenCV NCC", method_cv2_ncc, "#0066CC"),
    ("ORB + RANSAC", method_orb, "#9900CC"),
]


# ═════════════════════════════════════════════════════════════════════════
#  Acquire image pair
# ═════════════════════════════════════════════════════════════════════════

print(f"\n{'=' * 60}")
print(f"  Acquiring image pair")
print(f"{'=' * 60}")

setup_objective(args.ref_slot, args.ref_zoom)
home = drv.get_xy(client)
settings = get_job_settings(client, job)
geo = parse_tile_geometry(settings)
ref_pixel = geo["pixel_w_um"]
image_size = geo["pixels_x"]
print(f"  Pixel: {ref_pixel:.4f} um, FOV: {ref_pixel * image_size:.1f} um")

print(f"  Acquiring reference...")
img_ref = acquire_image()
if img_ref is None:
    sys.exit(1)

setup_objective(args.target_slot, tgt_zoom)
if args.settle > 0:
    time.sleep(args.settle)
pos_uncorr = drv.get_xy(client)

print(f"  Acquiring target...")
img_tgt = acquire_image()
if img_tgt is None:
    sys.exit(1)

# ═════════════════════════════════════════════════════════════════════════
#  Run all methods on the same image pair
# ═════════════════════════════════════════════════════════════════════════

print(f"\n{'=' * 60}")
print(f"  Running registration methods")
print(f"{'=' * 60}")

results = []
for name, func, color in METHODS:
    t0 = time.time()
    try:
        dx, dy, quality = func(img_ref, img_tgt, ref_pixel)
        elapsed = time.time() - t0
        dist = (dx**2 + dy**2)**0.5 if not np.isnan(dx) else np.nan
        results.append({
            "name": name, "color": color,
            "dx_um": float(dx), "dy_um": float(dy),
            "dist_um": float(dist), "quality": float(quality),
            "time_s": elapsed, "failed": np.isnan(dx),
        })
        print(f"  {name:<20}  ({dx:+8.2f}, {dy:+8.2f}) um = {dist:6.2f} um  "
              f"q={quality:.4f}  t={elapsed:.3f}s")
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  {name:<20}  FAILED: {e}")
        results.append({
            "name": name, "color": color,
            "dx_um": np.nan, "dy_um": np.nan,
            "dist_um": np.nan, "quality": 0.0,
            "time_s": elapsed, "failed": True,
        })

# ═════════════════════════════════════════════════════════════════════════
#  Apply best correction and verify
# ═════════════════════════════════════════════════════════════════════════

# Use masked NCC as the correction (known to be reliable)
masked_r = next(r for r in results if r["name"] == "Masked NCC")
corr_x = -masked_r["dx_um"]
corr_y = +masked_r["dy_um"]

print(f"\n{'=' * 60}")
print(f"  Applying masked NCC correction (-X +Y)")
print(f"  ({corr_x:+.2f}, {corr_y:+.2f}) um")
print(f"{'=' * 60}")

drv.move_xy(client, pos_uncorr["x_um"] + corr_x, pos_uncorr["y_um"] + corr_y)
time.sleep(1)

print(f"  Acquiring corrected...")
img_corr = acquire_image()
if img_corr is None:
    sys.exit(1)

# Measure residual with all methods
print(f"\n  Residuals:")
residuals = []
for name, func, color in METHODS:
    try:
        rdx, rdy, rq = func(img_ref, img_corr, ref_pixel)
        rdist = (rdx**2 + rdy**2)**0.5 if not np.isnan(rdx) else np.nan
        residuals.append({
            "name": name, "color": color,
            "dx_um": float(rdx), "dy_um": float(rdy),
            "dist_um": float(rdist), "quality": float(rq),
        })
        print(f"  {name:<20}  ({rdx:+8.2f}, {rdy:+8.2f}) um = {rdist:6.2f} um  q={rq:.4f}")
    except Exception as e:
        print(f"  {name:<20}  FAILED: {e}")
        residuals.append({
            "name": name, "color": color,
            "dx_um": np.nan, "dy_um": np.nan,
            "dist_um": np.nan, "quality": 0.0,
        })

# ═════════════════════════════════════════════════════════════════════════
#  Visual report
# ═════════════════════════════════════════════════════════════════════════

plt.rcParams.update({"font.size": 11, "figure.facecolor": "white"})

n_methods = len(results)
fig = plt.figure(figsize=(28, 22))
gs = fig.add_gridspec(3, n_methods + 2, hspace=0.35, wspace=0.30,
                      left=0.04, right=0.96, top=0.92, bottom=0.04)

# ── Row 1: overlays per method ───────────────────────────────────────

ax = fig.add_subplot(gs[0, 0])
ax.imshow(make_overlay(img_ref, img_tgt)); hide_ticks(ax)
ax.set_title(f"Uncorrected\nraw overlay", fontsize=11, color="#CC0000")

for i, r in enumerate(results):
    ax = fig.add_subplot(gs[0, i + 1])
    if not r["failed"]:
        shift_yx = [r["dy_um"] / ref_pixel, r["dx_um"] / ref_pixel]
        tgt_reg = ndi_shift(img_tgt.astype(np.float64), shift_yx)
        ax.imshow(make_overlay(img_ref, tgt_reg))
    else:
        ax.imshow(img_ref, cmap="gray")
    hide_ticks(ax)
    status = f"{r['dist_um']:.2f} um" if not r["failed"] else "FAILED"
    ax.set_title(f"{r['name']}\n{status}", fontsize=11,
                 color=r["color"], fontweight="bold")

ax = fig.add_subplot(gs[0, n_methods + 1])
ax.imshow(make_overlay(img_ref, img_corr)); hide_ticks(ax)
ax.set_title(f"After correction\n(masked NCC)", fontsize=11,
             color="#006600", fontweight="bold")
for spine in ax.spines.values():
    spine.set_edgecolor("#006600"); spine.set_linewidth(3)

# ── Row 2: comparison charts ─────────────────────────────────────────

# Shift vectors
ax = fig.add_subplot(gs[1, 0:3])
valid = [r for r in results if not r["failed"]]
lim = max([max(abs(r["dx_um"]), abs(r["dy_um"])) for r in valid] + [5]) * 1.3
ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim)
ax.set_aspect("equal")
ax.axhline(0, color="gray", lw=0.5); ax.axvline(0, color="gray", lw=0.5)
ax.plot(0, 0, "ko", ms=10, zorder=5, label="Origin")
for r in results:
    if r["failed"]:
        continue
    ax.plot(r["dx_um"], r["dy_um"], "o", ms=12, color=r["color"],
            label=f"{r['name']}: {r['dist_um']:.1f} um")
    ax.annotate("", xy=(r["dx_um"], r["dy_um"]), xytext=(0, 0),
                arrowprops=dict(arrowstyle="-|>", color=r["color"], lw=2))
ax.set_xlabel("X (um)"); ax.set_ylabel("Y (um)")
ax.set_title("Raw shift vectors", fontsize=12, fontweight="bold")
ax.legend(fontsize=9); ax.grid(True, alpha=0.3)

# Bar chart: shift distance
ax = fig.add_subplot(gs[1, 3:5])
names = [r["name"] for r in results]
dists = [r["dist_um"] if not r["failed"] else 0 for r in results]
colors = [r["color"] for r in results]
bars = ax.bar(range(len(names)), dists, color=colors, alpha=0.85,
              edgecolor="black", lw=0.5)
ax.set_xticks(range(len(names)))
ax.set_xticklabels([n.replace(" ", "\n") for n in names], fontsize=9)
for bar, d, r in zip(bars, dists, results):
    if not r["failed"]:
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.2,
                f"{d:.1f}", ha="center", fontsize=10, fontweight="bold")
ax.set_ylabel("Shift distance (um)")
ax.set_title("Raw measurement comparison", fontsize=12, fontweight="bold")
ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)

# Quality + timing
ax = fig.add_subplot(gs[1, 5:])
ax.axis("off")
txt = f"{'Method':<20}  {'Shift':>8}  {'Quality':>8}  {'Time':>6}\n"
txt += f"{'-'*20}  {'-'*8}  {'-'*8}  {'-'*6}\n"
for r in results:
    if r["failed"]:
        txt += f"{r['name']:<20}  {'FAIL':>8}  {'':>8}  {r['time_s']:5.3f}s\n"
    else:
        txt += (f"{r['name']:<20}  {r['dist_um']:7.2f}  "
                f"{r['quality']:8.4f}  {r['time_s']:5.3f}s\n")
txt += f"\n{'Residuals (after masked NCC correction)'}\n"
txt += f"{'-'*50}\n"
for r in residuals:
    if np.isnan(r["dist_um"]):
        txt += f"{r['name']:<20}  {'FAIL':>8}\n"
    else:
        txt += f"{r['name']:<20}  {r['dist_um']:7.2f}  q={r['quality']:.4f}\n"

ax.text(0.02, 0.95, txt, transform=ax.transAxes, fontsize=11,
        va="top", fontfamily="monospace",
        bbox=dict(boxstyle="round,pad=0.6", facecolor="#FFFFF0",
                  edgecolor="#888888", alpha=0.95))

# ── Row 3: residuals ─────────────────────────────────────────────────

# Residual vectors
ax = fig.add_subplot(gs[2, 0:3])
valid_r = [r for r in residuals if not np.isnan(r["dist_um"])]
if valid_r:
    lim_r = max([max(abs(r["dx_um"]), abs(r["dy_um"])) for r in valid_r] + [2]) * 2
else:
    lim_r = 5
ax.set_xlim(-lim_r, lim_r); ax.set_ylim(-lim_r, lim_r)
ax.set_aspect("equal")
ax.axhline(0, color="gray", lw=0.5); ax.axvline(0, color="gray", lw=0.5)
ax.plot(0, 0, "o", ms=14, color="#006600", zorder=5, label="Perfect (0,0)")
for r in residuals:
    if np.isnan(r["dist_um"]):
        continue
    ax.plot(r["dx_um"], r["dy_um"], "o", ms=10, color=r["color"],
            label=f"{r['name']}: {r['dist_um']:.2f} um")
ax.set_xlabel("X (um)"); ax.set_ylabel("Y (um)")
ax.set_title("Residuals after masked NCC correction", fontsize=12, fontweight="bold")
ax.legend(fontsize=9); ax.grid(True, alpha=0.3)

# Residual bar chart
ax = fig.add_subplot(gs[2, 3:5])
r_names = [r["name"] for r in residuals]
r_dists = [r["dist_um"] if not np.isnan(r["dist_um"]) else 0 for r in residuals]
r_colors = [r["color"] for r in residuals]
bars = ax.bar(range(len(r_names)), r_dists, color=r_colors, alpha=0.85,
              edgecolor="black", lw=0.5)
ax.set_xticks(range(len(r_names)))
ax.set_xticklabels([n.replace(" ", "\n") for n in r_names], fontsize=9)
for bar, d, r in zip(bars, r_dists, residuals):
    if not np.isnan(r["dist_um"]):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
                f"{d:.2f}", ha="center", fontsize=10, fontweight="bold")
ax.set_ylabel("Residual (um)")
ax.set_title("Residual comparison", fontsize=12, fontweight="bold")
ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)

# Conclusion
ax = fig.add_subplot(gs[2, 5:])
ax.axis("off")
# Find best by consistency: closest to masked NCC (our trusted reference)
masked_dx = masked_r["dx_um"]
masked_dy = masked_r["dy_um"]
consistency = []
for r in results:
    if r["failed"]:
        consistency.append(("", np.inf))
        continue
    d = ((r["dx_um"] - masked_dx)**2 + (r["dy_um"] - masked_dy)**2)**0.5
    consistency.append((r["name"], d))

conclusion = (
    f"CONCLUSION\n"
    f"{'━' * 40}\n\n"
    f"Agreement with masked NCC:\n"
)
for name, d in consistency:
    if name:
        conclusion += f"  {name:<20} {d:.2f} um\n"
conclusion += (
    f"\n"
    f"Masked NCC correction:\n"
    f"  Applied: ({corr_x:+.2f}, {corr_y:+.2f}) um\n"
)
masked_resid = next((r for r in residuals if r["name"] == "Masked NCC"), None)
if masked_resid and not np.isnan(masked_resid["dist_um"]):
    conclusion += f"  Residual: {masked_resid['dist_um']:.2f} um\n"

ax.text(0.02, 0.95, conclusion, transform=ax.transAxes, fontsize=11,
        va="top", fontfamily="monospace",
        bbox=dict(boxstyle="round,pad=0.6", facecolor="lightyellow",
                  edgecolor="#888888", alpha=0.95))

fig.suptitle(
    f"Registration Benchmark: {ref_name} → {tgt_name}  |  "
    f"zoom {args.ref_zoom}/{tgt_zoom:.1f}  |  pixel {ref_pixel:.4f} um",
    fontsize=14, fontweight="bold", y=0.97)

report_path = os.path.join(out_dir, f"benchmark_{ref_label}_vs_{tgt_label}.png")
fig.savefig(report_path, dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"\n  Report: {report_path}")

# Save JSON
out_data = {
    "timestamp": _ts,
    "ref": {"slot": args.ref_slot, "label": ref_label, "zoom": args.ref_zoom,
            "pixel_um": float(ref_pixel)},
    "target": {"slot": args.target_slot, "label": tgt_label, "zoom": float(tgt_zoom)},
    "methods": results,
    "residuals": residuals,
    "correction_um": [float(corr_x), float(corr_y)],
}
json_path = os.path.join(out_dir, "benchmark_results.json")
with open(json_path, "w") as f:
    json.dump(out_data, f, indent=2, default=str)
print(f"  JSON: {json_path}")

# Restore
print(f"\n  Restoring...")
setup_objective(args.ref_slot, args.ref_zoom)
drv.move_xy(client, home["x_um"], home["y_um"])
time.sleep(1)
print("  Done.")

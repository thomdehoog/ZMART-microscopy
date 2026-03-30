"""
Alignment Calibration Validation (2D)
======================================
Validates the parcentric calibration by acquiring on the reference
objective, switching to the target with calibration-corrected stage
position, acquiring again, and cross-correlating. If calibration is
correct, the residual shift should be near zero.

Usage:
    python test_alignment_validation.py --ref-slot 1 --target-slot 2
    python test_alignment_validation.py --ref-slot 1 --target-slot 2 0 --settle '{"0": 20}'
    python test_alignment_validation.py --ref-slot 1 --target-slot 2 --calibration path/to/alignment_results.json
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
    description="Validate alignment calibration via 2D cross-correlation")
parser.add_argument("--ref-slot", type=int, required=True,
                    help="Reference objective slot number (e.g. 1 for 10x)")
parser.add_argument("--target-slot", type=int, nargs="+", required=True,
                    help="Target objective slot number(s) (e.g. 2 0)")
parser.add_argument("--ref-zoom", type=float, required=True,
                    help="Reference zoom level (e.g. 5)")
parser.add_argument("--settle", type=json.loads, default="{}",
                    help='Extra settle time per slot, e.g. \'{"0": 20}\'')
parser.add_argument("--calibration", default=None,
                    help="Path to alignment_results.json (default: latest in config/alignment/)")
parser.add_argument("--output", default=None,
                    help="Output directory (default: config/alignment/<timestamp>)")
args = parser.parse_args()

# ── Import (skimage before torch to avoid DLL conflicts) ─────────────

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
from lasx.alignment import load_alignment, translate_xy, translate_z, _get_offset

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.ndimage import shift as ndi_shift

# ── Connect ─────────────────────────────────────────────────────────────

client = lasx_api.LasxApiClientPyModel
confirmed = client.Connect("PythonClient")
if not confirmed:
    print("  ABORT: Cannot connect to LAS X.")
    sys.exit(1)

if not drv.ping(client):
    print("  ABORT: ping failed")
    sys.exit(1)

job = drv.get_selected_job(client).get("Name")
hw = drv.get_hardware_info(client)
if not hw:
    print("  ABORT: cannot read hardware info")
    sys.exit(1)
print(f"  Job: {job}")

# Set stage limits (required for move_xy)
drv.set_stage_limits(
    x_min=1000, x_max=130000,
    y_min=1000, y_max=100000,
    z_galvo_min=-200, z_galvo_max=200,
    z_wide_min=0, z_wide_max=25000,
)

# ── Build objective lookup by slot ───────────────────────────────────

objs_by_slot = {}
for o in hw.get("Microscope", {}).get("objectives", []):
    if o.get("objectiveNumber", 0) != 0:
        objs_by_slot[o["slotIndex"]] = o

def obj_info(slot):
    o = objs_by_slot.get(slot)
    if not o:
        print(f"  ABORT: no objective in slot {slot}")
        print(f"  Available slots: {list(objs_by_slot.keys())}")
        sys.exit(1)
    mag = o["magnification"]
    na = o["numericalAperture"]
    imm = o.get("immersion", "").strip()
    label = f"slot{slot}_{mag:.0f}x_{na}NA_{imm}"
    name = o.get("name", "").strip()
    return label, name, mag

# ── Load calibration ────────────────────────────────────────────────

if args.calibration:
    cal_path = args.calibration
else:
    cal_dir = Path(__file__).resolve().parent.parent / "config" / "alignment"
    cal_dirs = sorted(cal_dir.iterdir(), reverse=True)
    cal_path = None
    for d in cal_dirs:
        candidate = d / "alignment_results.json"
        if candidate.exists():
            cal_path = str(candidate)
            break
    if not cal_path:
        print("  ABORT: no calibration file found in config/alignment/")
        sys.exit(1)

cal = load_alignment(cal_path)
print(f"  Calibration: {cal_path}")

# ── Validate slots ──────────────────────────────────────────────────

ref_label, ref_name, ref_mag = obj_info(args.ref_slot)
target_infos = {}
for ts in args.target_slot:
    tl, tn, tm = obj_info(ts)
    target_infos[ts] = {"label": tl, "name": tn, "mag": tm}

print(f"  Reference: {ref_name} ({ref_label})")
for ts, ti in target_infos.items():
    print(f"  Target:    {ti['name']} ({ti['label']})")

# ── Output directory ────────────────────────────────────────────────

_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
_default_out = os.path.join(
    str(Path(__file__).resolve().parent.parent), "config", "alignment",
    f"validation_{_timestamp}")
out_dir = args.output or _default_out
os.makedirs(out_dir, exist_ok=True)
print(f"  Output: {out_dir}")

# ── Helper: acquire single image ────────────────────────────────────

def acquire_image():
    """Acquire a single 2D image, return (image, stage, pixel_size_um)."""
    settings = get_job_settings(client, job)
    geo = parse_tile_geometry(settings)
    stage = drv.get_xy(client)

    print(f"  FOV: {geo['tile_w_um']:.2f} um, pixel: {geo['pixel_w_um']:.4f} um, "
          f"image: {geo['pixels_x']}x{geo['pixels_y']}")

    print(f"  Acquiring...")
    baseline = drv.read_relative_path(client)
    t0 = time.time()
    r = drv.acquire(client, job)
    if not r or not r["success"]:
        print(f"  Acquire failed: {r}")
        return None, None, None

    lasx_settings = get_lasx_settings()
    media_path = lasx_settings["export"]["media_path"]
    detection = drv.detect_new_files(client, baseline, media_path,
                                     acquire_start=t0)
    if not detection["success"]:
        print(f"  File detection failed: {detection.get('error')}")
        return None, None, None

    img_path = sorted(detection["image_files"])[0]
    img = tifffile.imread(str(img_path))
    if img.ndim == 3:
        img = img[0]
    print(f"  Acquired: {img.shape}, {img.dtype}")

    return img, stage, geo["pixel_w_um"]

# ── Main ────────────────────────────────────────────────────────────

ref_zoom = args.ref_zoom

# Set zoom explicitly to avoid stale state
drv.set_zoom(client, job, ref_zoom)
time.sleep(1)

print(f"\n{'=' * 60}")
print(f"  Alignment Validation (2D)")
print(f"  {ref_label} @ zoom {ref_zoom}")
print(f"{'=' * 60}")

# ── Acquire reference ───────────────────────────────────────────────

print(f"\n  Reference: {ref_name} @ zoom {ref_zoom}")
img_ref, ref_stage, ref_pixel_um = acquire_image()
if img_ref is None:
    sys.exit(1)

ref_norm = img_ref.astype(np.float64)
ref_n = ref_norm / (ref_norm.max() or 1)
image_size = img_ref.shape[1]
ref_fov_um = ref_pixel_um * image_size
all_results = {}

# ── Loop over targets ───────────────────────────────────────────────

for ts in args.target_slot:
    ti = target_infos[ts]
    tgt_label = ti["label"]
    tgt_name = ti["name"]
    tgt_mag = ti["mag"]
    settle = args.settle.get(str(ts), 0)

    # Compute matched zoom
    tgt_zoom = ref_zoom * ref_mag / tgt_mag

    # Get image offset for this target
    tgt_offset = _get_offset(ts, cal)
    image_sx, image_sy = tgt_offset["image_xy_um"]
    image_sz = tgt_offset["image_z_um"]

    print(f"\n  Target: {tgt_name} @ zoom {tgt_zoom:.2f}")
    print(f"  Image offset: XY=({image_sx:+.1f}, {image_sy:+.1f}) um, "
          f"Z={image_sz:+.1f} um")

    # Switch objective
    print(f"  Switching to {tgt_name} (slot {ts})...")
    r_obj = drv.set_objective(client, job, hw, name=tgt_name)
    if not r_obj or not r_obj.get("success"):
        print(f"  SKIP: objective switch failed: {r_obj}")
        continue
    time.sleep(3)

    if settle > 0:
        print(f"  Waiting {settle}s for settle...")
        time.sleep(settle)

    # Reset pan, disable ROI scan
    def reset_pan(p):
        lrp_set_pan(p, 0, 0, job)
        lrp_enable_roi_scan(p, False, job)
    apply_lrp_change(client, TEMPLATE_XML, reset_pan, confirm_delays=(2, 4, 6))

    # Set matched zoom — don't block on confirmation
    drv.set_zoom(client, job, tgt_zoom)
    time.sleep(3)

    # Read position AFTER switch (motor_delta already applied by firmware)
    post_switch = drv.get_xy(client)
    # Apply correction: negate Y due to image/stage axis flip
    corrected_x = post_switch["x_um"] + image_sx
    corrected_y = post_switch["y_um"] + image_sy
    print(f"  Post-switch: ({post_switch['x_um']:.1f}, {post_switch['y_um']:.1f}) um")
    print(f"  Corrected:   ({corrected_x:.1f}, {corrected_y:.1f}) um")

    # Apply XY correction
    print(f"  Moving to corrected position...")
    drv.move_xy(client, corrected_x, corrected_y)
    time.sleep(1)

    # Acquire
    img_target, target_stage, target_pixel_um = acquire_image()
    if img_target is None:
        print(f"  SKIP: {tgt_name} acquire failed")
        continue

    # Cross-correlate to measure residual shift
    target_norm = img_target.astype(np.float64)
    tgt_n = target_norm / (target_norm.max() or 1)

    pixel_mismatch = abs(target_pixel_um - ref_pixel_um) / ref_pixel_um * 100
    shift, error, _ = phase_cross_correlation(
        ref_norm, target_norm, upsample_factor=100)

    shift_y_px, shift_x_px = shift
    shift_x_um = shift_x_px * ref_pixel_um
    shift_y_um = shift_y_px * ref_pixel_um
    dist_um = (shift_x_um**2 + shift_y_um**2)**0.5

    print(f"  Residual shift: ({shift_x_um:+.2f}, {shift_y_um:+.2f}) um = {dist_um:.2f} um")
    if dist_um < 5:
        print(f"  PASS: residual < 5 um")
    else:
        print(f"  WARN: residual >= 5 um")

    all_results[tgt_label] = {
        "full_name": tgt_name,
        "slot": ts,
        "residual_shift_px": [float(shift_x_px), float(shift_y_px)],
        "residual_shift_um": [float(shift_x_um), float(shift_y_um)],
        "residual_distance_um": float(dist_um),
        "correlation_error": float(error),
        "corrected_stage_um": [float(post_switch["x_um"]), float(post_switch["y_um"])],
        "actual_stage_um": [float(target_stage["x_um"]), float(target_stage["y_um"])],
        "target_pixel_um": float(target_pixel_um),
        "pixel_mismatch_pct": float(pixel_mismatch),
        "target_zoom": float(tgt_zoom),
    }

    # ── Visual report ───────────────────────────────────────────────

    img_target_shifted = ndi_shift(target_norm, shift)
    tgt_s = img_target_shifted / (img_target_shifted.max() or 1)
    tile = 64

    fig = plt.figure(figsize=(20, 14))
    gs = fig.add_gridspec(2, 4, hspace=0.3, wspace=0.3)

    # Row 1: ref, target, raw overlay, checkerboard
    ax = fig.add_subplot(gs[0, 0])
    ax.imshow(img_ref, cmap="gray")
    ax.set_title(f"{ref_label} (zoom {ref_zoom})", fontsize=11)
    ax.plot(image_size/2, image_size/2, "c+", markersize=12, markeredgewidth=2)

    ax = fig.add_subplot(gs[0, 1])
    ax.imshow(img_target, cmap="gray")
    ax.set_title(f"{tgt_label} (zoom {tgt_zoom:.2f})", fontsize=11)
    ax.plot(image_size/2, image_size/2, "c+", markersize=12, markeredgewidth=2)

    ax = fig.add_subplot(gs[0, 2])
    overlay = np.zeros((*img_ref.shape, 3))
    overlay[..., 1] = ref_n
    overlay[..., 0] = tgt_n
    overlay[..., 2] = tgt_n
    ax.imshow(np.clip(overlay, 0, 1))
    ax.set_title("Corrected overlay (green=ref, magenta=tgt)", fontsize=11)

    ax = fig.add_subplot(gs[0, 3])
    checker = np.zeros_like(img_ref, dtype=np.float64)
    for r in range(0, image_size, tile):
        for c in range(0, image_size, tile):
            src = ref_n if ((r // tile) + (c // tile)) % 2 == 0 else tgt_n
            checker[r:r+tile, c:c+tile] = src[r:r+tile, c:c+tile]
    ax.imshow(checker, cmap="gray")
    ax.set_title("Checkerboard (corrected)", fontsize=11)

    # Row 2: registered overlay, registered checker, vector, text
    ax = fig.add_subplot(gs[1, 0])
    ov_reg = np.zeros((*img_ref.shape, 3))
    ov_reg[..., 1] = ref_n
    ov_reg[..., 0] = tgt_s
    ov_reg[..., 2] = tgt_s
    ax.imshow(np.clip(ov_reg, 0, 1))
    ax.set_title("Registered overlay", fontsize=11)

    ax = fig.add_subplot(gs[1, 1])
    checker_r = np.zeros_like(img_ref, dtype=np.float64)
    for r in range(0, image_size, tile):
        for c in range(0, image_size, tile):
            src = ref_n if ((r // tile) + (c // tile)) % 2 == 0 else tgt_s
            checker_r[r:r+tile, c:c+tile] = src[r:r+tile, c:c+tile]
    ax.imshow(checker_r, cmap="gray")
    ax.set_title("Registered checkerboard", fontsize=11)

    ax = fig.add_subplot(gs[1, 2])
    lim = max(abs(shift_x_px), abs(shift_y_px), 20) * 1.5
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_aspect("equal")
    ax.axhline(0, color="gray", lw=0.5)
    ax.axvline(0, color="gray", lw=0.5)
    ax.plot(0, 0, "go", ms=12, label="expected")
    ax.plot(shift_x_px, shift_y_px, "m^", ms=12, label="actual")
    ax.annotate("", xy=(shift_x_px, shift_y_px), xytext=(0, 0),
                arrowprops=dict(arrowstyle="->", color="red", lw=2.5))
    ax.set_xlabel("X (px)")
    ax.set_ylabel("Y (px)")
    ax.set_title(f"Residual: ({shift_x_um:+.1f}, {shift_y_um:+.1f}) um\n"
                 f"= {dist_um:.1f} um", fontsize=11)
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)

    ax = fig.add_subplot(gs[1, 3])
    ax.axis("off")
    txt = (
        f"Alignment Validation\n"
        f"{ref_label}\n-> {tgt_label}\n"
        f"{'-' * 35}\n"
        f"Residual: ({shift_x_um:+.2f}, {shift_y_um:+.2f}) um\n"
        f"Distance: {dist_um:.2f} um\n"
        f"Corr err: {error:.4f}\n"
        f"{'-' * 35}\n"
        f"{'PASS' if dist_um < 5 else 'WARN'}: "
        f"{'< 5 um' if dist_um < 5 else '>= 5 um'}\n"
        f"{'-' * 35}\n"
        f"Pixel: {ref_pixel_um:.4f} / {target_pixel_um:.4f} um\n"
        f"Mismatch: {pixel_mismatch:.2f}%\n"
        f"FOV: {ref_fov_um:.1f} um\n"
        f"Zoom: {ref_zoom} / {tgt_zoom:.2f}"
    )
    ax.text(0.05, 0.95, txt, transform=ax.transAxes, fontsize=11,
            va="top", fontfamily="monospace",
            bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5))

    status = "PASS" if dist_um < 5 else "WARN"
    fig.suptitle(
        f"Alignment Validation [{status}]: {ref_label} (z{ref_zoom}) -> "
        f"{tgt_label} (z{tgt_zoom:.2f})  |  "
        f"Residual = ({shift_x_um:+.1f}, {shift_y_um:+.1f}) um  |  "
        f"Dist = {dist_um:.1f} um",
        fontsize=14, fontweight="bold")
    fig.tight_layout()

    path = os.path.join(out_dir,
        f"validation_{ref_label}_vs_{tgt_label}.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Report: {path}")

# ── Summary ─────────────────────────────────────────────────────────

print(f"\n{'=' * 70}")
print(f"  Validation Summary: {ref_name} (slot {args.ref_slot}) reference")
print(f"{'=' * 70}")
print(f"  {'Target':<30}  {'Residual X':>10}  {'Residual Y':>10}  {'Dist':>8}  {'Status':>8}")
print(f"  {'-'*30}  {'-'*10}  {'-'*10}  {'-'*8}  {'-'*8}")
for name, r in all_results.items():
    sx, sy = r["residual_shift_um"]
    d = r["residual_distance_um"]
    status = "PASS" if d < 5 else "WARN"
    print(f"  {name:<30}  {sx:>+10.2f}  {sy:>+10.2f}  {d:>8.2f}  {status:>8}")

# Save JSON
combined = {
    "timestamp": _timestamp,
    "calibration": cal_path,
    "ref_objective": ref_name,
    "ref_label": ref_label,
    "ref_slot": args.ref_slot,
    "ref_zoom": ref_zoom,
    "ref_fov_um": float(ref_fov_um),
    "ref_pixel_um": float(ref_pixel_um),
    "targets": all_results,
}
json_path = os.path.join(out_dir, "validation_results.json")
with open(json_path, "w") as f:
    json.dump(combined, f, indent=2)
print(f"\n  JSON: {json_path}")

# ── Switch back to reference ────────────────────────────────────────

print(f"\n  Switching back to {ref_name}...")
drv.set_objective(client, job, hw, name=ref_name)
time.sleep(3)
drv.set_zoom(client, job, ref_zoom)
print("  Done.")

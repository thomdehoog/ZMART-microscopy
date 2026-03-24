"""
Parcentric Offset via Phase Cross-Correlation
================================================
Acquires the same field on two objectives and measures the parcentric
offset using phase cross-correlation (sub-pixel accurate).

1. Acquire on the reference objective (10x)
2. Switch to target objective, match pixel size via zoom, acquire
3. Cross-correlate the two images -> pixel shift -> um

Usage:
    python test_parcentric_offset_crosscorr.py
    python test_parcentric_offset_crosscorr.py --ref-mag 10 --target-mag 20
    python test_parcentric_offset_crosscorr.py --ref-zoom 10
"""

import argparse
import json
import os
import sys
import time
import logging

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

parser = argparse.ArgumentParser(
    description="Parcentric Offset via Phase Cross-Correlation")
parser.add_argument("--ref-mag", type=float, default=10,
                    help="Reference objective magnification (default: 10)")
parser.add_argument("--target-mag", type=float, nargs="+", default=[20],
                    help="Target objective magnification(s) (default: 20)")
parser.add_argument("--ref-zoom", type=int, default=10,
                    help="Reference zoom level (default: 10)")
parser.add_argument("--settle", type=json.loads, default="{}",
                    help='Extra settle time per objective, e.g. \'{"40": 20}\'')
parser.add_argument("--output", default=None,
                    help="Output directory (default: Desktop)")
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
from lasx.readers import get_base_fov, get_job_settings, get_lasx_settings
from lasx.utils import parse_tile_geometry

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
print(f"  Job: {job}")

# ── Compute zoom pairs ───────────────────────────────────────────────

target_zooms = {}
for tmag in args.target_mag:
    tz = max(1, round(args.ref_zoom * args.ref_mag / tmag))
    target_zooms[tmag] = tz
    print(f"  Zoom pair: {args.ref_mag:.0f}x @ {args.ref_zoom} "
          f"-> {tmag:.0f}x @ {tz}")

# ── Helper: prepare and acquire ──────────────────────────────────────

def switch_and_acquire(magnification, zoom, extra_settle=0):
    """Switch objective, set zoom, acquire, return (image, stage, pixel_size)."""
    print(f"  Switching to {magnification:.0f}x...")
    drv.set_objective(client, job, hw, magnification=magnification)
    time.sleep(3)

    if extra_settle > 0:
        print(f"  Waiting {extra_settle}s for settle...")
        time.sleep(extra_settle)

    # Select job to refresh block identifier after objective change
    drv.select_job(client, job)
    time.sleep(2)

    # Reset pan to (0,0)
    def reset_pan(p):
        lrp_set_pan(p, 0, 0, job)
        lrp_enable_roi_scan(p, False, job)
    apply_lrp_change(client, TEMPLATE_XML, reset_pan, confirm_delays=(2, 4, 6))

    # Set zoom via API
    drv.set_zoom(client, job, zoom)
    time.sleep(1)

    # Re-select job after zoom (prevents "invalid block identifier")
    drv.select_job(client, job)
    time.sleep(1)

    # Read actual settings
    settings = get_job_settings(client, job)
    geo = parse_tile_geometry(settings)
    stage = drv.get_xy(client)

    print(f"  FOV: {geo['tile_w_um']:.2f} um, pixel: {geo['pixel_w_um']:.4f} um, "
          f"zoom: {zoom}, image: {geo['pixels_x']}x{geo['pixels_y']}")

    # Acquire
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

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.ndimage import shift as ndi_shift

out_dir = args.output or os.path.join(os.path.expanduser("~"), "Desktop")
targets_str = ", ".join(f"{m:.0f}x" for m in args.target_mag)

print(f"\n{'=' * 60}")
print(f"  Parcentric Offset: {args.ref_mag:.0f}x -> {targets_str}")
print(f"{'=' * 60}")

# ── Acquire reference ────────────────────────────────────────────────

print(f"\n  Reference: {args.ref_mag:.0f}x @ zoom {args.ref_zoom}")
img_ref, ref_stage, ref_pixel_um = switch_and_acquire(args.ref_mag, args.ref_zoom)
if img_ref is None:
    sys.exit(1)

ref_norm = img_ref.astype(np.float64)
ref_n = ref_norm / (ref_norm.max() or 1)
image_size = img_ref.shape[1]
ref_fov_um = ref_pixel_um * image_size
all_results = {}

# ── Loop over targets ────────────────────────────────────────────────

for tmag in args.target_mag:
    tz = target_zooms[tmag]
    settle = args.settle.get(str(int(tmag)), 0)

    print(f"\n  Target: {tmag:.0f}x @ zoom {tz}")
    img_target, target_stage, target_pixel_um = switch_and_acquire(
        tmag, tz, extra_settle=settle)
    if img_target is None:
        print(f"  SKIP: {tmag:.0f}x acquire failed")
        continue

    # Cross-correlate
    target_norm = img_target.astype(np.float64)
    tgt_n = target_norm / (target_norm.max() or 1)

    pixel_mismatch = abs(target_pixel_um - ref_pixel_um) / ref_pixel_um * 100
    shift, error, diffphase = phase_cross_correlation(
        ref_norm, target_norm, upsample_factor=100)

    shift_y_px, shift_x_px = shift
    shift_x_um = shift_x_px * ref_pixel_um
    shift_y_um = shift_y_px * ref_pixel_um
    dist_um = (shift_x_um**2 + shift_y_um**2)**0.5
    target_fov_um = target_pixel_um * image_size

    motor_dx = target_stage["x_um"] - ref_stage["x_um"]
    motor_dy = target_stage["y_um"] - ref_stage["y_um"]

    print(f"  Shift: ({shift_x_um:+.1f}, {shift_y_um:+.1f}) um = {dist_um:.1f} um")
    print(f"  Motor: ({motor_dx:+.1f}, {motor_dy:+.1f}) um")
    print(f"  Pixel mismatch: {pixel_mismatch:.1f}%")

    all_results[f"{tmag:.0f}x"] = {
        "shift_px": [float(shift_x_px), float(shift_y_px)],
        "shift_um": [float(shift_x_um), float(shift_y_um)],
        "distance_um": float(dist_um),
        "correlation_error": float(error),
        "motor_delta_um": [float(motor_dx), float(motor_dy)],
        "target_fov_um": float(target_fov_um),
        "target_pixel_um": float(target_pixel_um),
        "pixel_mismatch_pct": float(pixel_mismatch),
        "target_zoom": tz,
    }

    # ── Per-target visual report ─────────────────────────────────────

    img_target_shifted = ndi_shift(target_norm, shift)
    tgt_s = img_target_shifted / (img_target_shifted.max() or 1)
    tile = 64

    fig = plt.figure(figsize=(20, 14))
    gs = fig.add_gridspec(2, 4, hspace=0.3, wspace=0.3)

    # Row 1: ref, target, raw overlay, checkerboard
    ax = fig.add_subplot(gs[0, 0])
    ax.imshow(img_ref, cmap="gray")
    ax.set_title(f"{args.ref_mag:.0f}x ref (zoom {args.ref_zoom})", fontsize=11)
    ax.plot(image_size/2, image_size/2, "c+", markersize=12, markeredgewidth=2)

    ax = fig.add_subplot(gs[0, 1])
    ax.imshow(img_target, cmap="gray")
    ax.set_title(f"{tmag:.0f}x target (zoom {tz})", fontsize=11)
    ax.plot(image_size/2, image_size/2, "c+", markersize=12, markeredgewidth=2)

    ax = fig.add_subplot(gs[0, 2])
    overlay = np.zeros((*img_ref.shape, 3))
    overlay[..., 1] = ref_n
    overlay[..., 0] = tgt_n
    overlay[..., 2] = tgt_n
    ax.imshow(np.clip(overlay, 0, 1))
    ax.set_title("Raw overlay (green=ref, magenta=tgt)", fontsize=11)

    ax = fig.add_subplot(gs[0, 3])
    checker = np.zeros_like(img_ref, dtype=np.float64)
    for r in range(0, image_size, tile):
        for c in range(0, image_size, tile):
            src = ref_n if ((r // tile) + (c // tile)) % 2 == 0 else tgt_n
            checker[r:r+tile, c:c+tile] = src[r:r+tile, c:c+tile]
    ax.imshow(checker, cmap="gray")
    ax.set_title("Checkerboard (raw)", fontsize=11)

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
    ax.plot(0, 0, "go", ms=12, label=f"{args.ref_mag:.0f}x")
    ax.plot(shift_x_px, shift_y_px, "m^", ms=12, label=f"{tmag:.0f}x")
    ax.annotate("", xy=(shift_x_px, shift_y_px), xytext=(0, 0),
                arrowprops=dict(arrowstyle="->", color="red", lw=2.5))
    ax.set_xlabel("X (px)")
    ax.set_ylabel("Y (px)")
    ax.set_title(f"({shift_x_px:+.1f}, {shift_y_px:+.1f}) px\n"
                 f"({shift_x_um:+.1f}, {shift_y_um:+.1f}) um", fontsize=11)
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)

    ax = fig.add_subplot(gs[1, 3])
    ax.axis("off")
    txt = (
        f"Parcentric Offset\n"
        f"{args.ref_mag:.0f}x -> {tmag:.0f}x\n"
        f"{'-' * 35}\n"
        f"Image shift: ({shift_x_um:+.2f}, {shift_y_um:+.2f}) um\n"
        f"Distance:    {dist_um:.2f} um\n"
        f"Corr error:  {error:.4f}\n"
        f"{'-' * 35}\n"
        f"Motor delta: ({motor_dx:+.2f}, {motor_dy:+.2f}) um\n"
        f"{'-' * 35}\n"
        f"Pixel: {ref_pixel_um:.4f} / {target_pixel_um:.4f} um\n"
        f"Mismatch: {pixel_mismatch:.2f}%\n"
        f"FOV: {ref_fov_um:.1f} / {target_fov_um:.1f} um\n"
        f"Zoom: {args.ref_zoom} / {tz}"
    )
    ax.text(0.05, 0.95, txt, transform=ax.transAxes, fontsize=11,
            va="top", fontfamily="monospace",
            bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5))

    fig.suptitle(
        f"Parcentric Offset: {args.ref_mag:.0f}x (z{args.ref_zoom}) -> "
        f"{tmag:.0f}x (z{tz})  |  "
        f"Shift = ({shift_x_um:+.1f}, {shift_y_um:+.1f}) um  |  "
        f"Dist = {dist_um:.1f} um",
        fontsize=14, fontweight="bold")
    fig.tight_layout()

    path = os.path.join(out_dir,
        f"parcentric_crosscorr_{args.ref_mag:.0f}x_{tmag:.0f}x.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Report: {path}")

# ── Summary ──────────────────────────────────────────────────────────

print(f"\n{'=' * 60}")
print(f"  Summary: {args.ref_mag:.0f}x reference")
print(f"{'=' * 60}")
print(f"  {'Target':<10}  {'Shift X':>10}  {'Shift Y':>10}  {'Dist':>8}  {'Motor dX':>10}  {'Motor dY':>10}")
print(f"  {'-'*10}  {'-'*10}  {'-'*10}  {'-'*8}  {'-'*10}  {'-'*10}")
for name, r in all_results.items():
    sx, sy = r["shift_um"]
    mx, my = r["motor_delta_um"]
    print(f"  {name:<10}  {sx:>+10.2f}  {sy:>+10.2f}  {r['distance_um']:>8.2f}  {mx:>+10.2f}  {my:>+10.2f}")

# Save combined JSON
combined = {
    "ref_objective": f"{args.ref_mag:.0f}x",
    "ref_zoom": args.ref_zoom,
    "ref_fov_um": float(ref_fov_um),
    "ref_pixel_um": float(ref_pixel_um),
    "targets": all_results,
}
json_path = os.path.join(out_dir, "parcentric_crosscorr_all.json")
with open(json_path, "w") as f:
    json.dump(combined, f, indent=2)
print(f"\n  JSON: {json_path}")

# ── Switch back to reference ─────────────────────────────────────────

print(f"\n  Switching back to {args.ref_mag:.0f}x...")
drv.set_objective(client, job, hw, magnification=args.ref_mag)
time.sleep(3)
drv.select_job(client, job)
drv.set_zoom(client, job, args.ref_zoom)
print("  Done.")

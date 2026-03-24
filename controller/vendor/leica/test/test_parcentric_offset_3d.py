"""
3D Parcentric + Parfocal Offset via Phase Cross-Correlation
=============================================================
Acquires Z-stacks on two objectives and measures the (dX, dY, dZ)
offset using 3D phase cross-correlation.

Z-stack must be pre-configured in LAS X (z-galvo, centered on 0).

1. Acquire Z-stack on reference objective (10x)
2. Switch to target objective, match pixel size via zoom, acquire Z-stack
3. 3D cross-correlate -> (dZ, dY, dX) shift in pixels -> um

NOTE: z-wide (motor Z) changes when switching objectives, but z-galvo
range stays centered on 0. The parfocal offset appears as dZ.

Usage:
    python test_parcentric_offset_3d.py
    python test_parcentric_offset_3d.py --ref-mag 10 --target-mag 20
    python test_parcentric_offset_3d.py --ref-zoom 10 --settle 20
"""

import argparse
import json
import os
import sys
import time
import logging

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

parser = argparse.ArgumentParser(
    description="3D Parcentric + Parfocal Offset via Cross-Correlation")
parser.add_argument("--ref-mag", type=float, default=10,
                    help="Reference objective magnification (default: 10)")
parser.add_argument("--target-mag", type=float, nargs="+", default=[20],
                    help="Target objective magnification(s) (default: 20)")
parser.add_argument("--ref-zoom", type=int, default=10,
                    help="Reference zoom level (default: 10)")
parser.add_argument("--settle", type=json.loads, default="{}",
                    help='Extra settle time per objective, e.g. \'{"40": 20}\'')
parser.add_argument("--z-range", type=float, default=40,
                    help="Z-stack half-range in um (default: 40 = +/-40)")
parser.add_argument("--z-step", type=float, default=1.0,
                    help="Z-stack step size in um (default: 1.0)")
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
from lasx.readers import get_job_settings, get_lasx_settings
from lasx.utils import parse_tile_geometry
from lasx.scanning_template_parsers import get_master_attrs
from lasx.scanning_templates import save_and_read_lrp

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

# Compute target zooms
target_zooms = {}
for tmag in args.target_mag:
    tz = max(1, round(args.ref_zoom * args.ref_mag / tmag))
    target_zooms[tmag] = tz
    print(f"  Zoom pair: {args.ref_mag:.0f}x @ {args.ref_zoom} "
          f"-> {tmag:.0f}x @ {tz}")

# ── Helper: switch, acquire Z-stack ──────────────────────────────────

def switch_and_acquire_stack(magnification, zoom, extra_settle=0):
    """Switch objective, set zoom, acquire Z-stack, return (stack, stage, pixel_size_um, z_step_um)."""
    print(f"  Switching to {magnification:.0f}x...")
    drv.set_objective(client, job, hw, magnification=magnification)
    time.sleep(3)

    if extra_settle > 0:
        print(f"  Waiting {extra_settle:.0f}s for settle...")
        time.sleep(extra_settle)

    drv.select_job(client, job)
    time.sleep(2)

    # Reset pan to (0,0), disable ROI scan
    def reset(p):
        lrp_set_pan(p, 0, 0, job)
        lrp_enable_roi_scan(p, False, job)
    apply_lrp_change(client, TEMPLATE_XML, reset, confirm_delays=(2, 4, 6))

    # Set zoom
    drv.set_zoom(client, job, zoom)
    time.sleep(1)
    drv.select_job(client, job)
    time.sleep(1)

    # Set up Z-stack via LRP (z-galvo, active) + API (begin/end, step)
    from lasx.scanning_template_editors_z import (
        lrp_set_z_stack_active, lrp_set_z_use_mode, lrp_set_sections,
    )
    from lasx.scanning_template_editors_focus import lrp_set_stack_calculation_mode

    sections = int(2 * args.z_range / args.z_step) + 1

    def setup_z(p):
        lrp_set_z_stack_active(p, False, job)
        lrp_set_z_use_mode(p, "z-galvo", job)
        lrp_set_stack_calculation_mode(p, 1, job)  # constant step size
        lrp_set_sections(p, sections, job)
        lrp_set_z_stack_active(p, True, job)
    apply_lrp_change(client, TEMPLATE_XML, setup_z, confirm_delays=(2, 4, 6))

    # Begin/end via API (LRP load doesn't apply these)
    drv.set_z_stack_definition(client, job,
                               begin_um=args.z_range, end_um=-args.z_range)
    drv.set_z_stack_step_size(client, job, args.z_step)

    # Read settings
    settings = get_job_settings(client, job)
    geo = parse_tile_geometry(settings)
    stage = drv.get_xy(client)

    z_range_um = 2 * args.z_range
    z_step_um = args.z_step

    print(f"  FOV: {geo['tile_w_um']:.2f} um, pixel: {geo['pixel_w_um']:.4f} um, "
          f"zoom: {zoom}")
    print(f"  Z-stack: {sections} sections, {z_step_um:.2f} um step, "
          f"{z_range_um:.1f} um range")

    # Acquire
    print(f"  Acquiring Z-stack...")
    baseline = drv.read_relative_path(client)
    t0 = time.time()
    r = drv.acquire(client, job)
    elapsed = time.time() - t0
    if not r or not r["success"]:
        print(f"  Acquire failed: {r}")
        return None, None, None, None

    print(f"  Acquired in {elapsed:.1f}s")

    # Find image files
    lasx_settings = get_lasx_settings()
    media_path = lasx_settings["export"]["media_path"]
    detection = drv.detect_new_files(client, baseline, media_path,
                                     acquire_start=t0)
    if not detection["success"]:
        print(f"  File detection failed: {detection.get('error')}")
        return None, None, None, None

    # Load all Z slices into a 3D stack
    image_files = sorted(detection["image_files"])
    print(f"  Found {len(image_files)} file(s)")

    if len(image_files) == 1:
        # Single multi-page TIFF
        stack = tifffile.imread(str(image_files[0]))
        if stack.ndim == 2:
            stack = stack[np.newaxis, ...]
    else:
        # Multiple files, one per Z slice
        slices = []
        for f in image_files:
            img = tifffile.imread(str(f))
            if img.ndim == 3:
                img = img[0]
            slices.append(img)
        stack = np.array(slices)

    print(f"  Stack shape: {stack.shape} ({stack.dtype})")
    return stack, stage, geo["pixel_w_um"], z_step_um

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.ndimage import shift as ndi_shift

out_dir = args.output or os.path.join(os.path.expanduser("~"), "Desktop")
targets_str = ", ".join(f"{m:.0f}x" for m in args.target_mag)

print(f"\n{'=' * 60}")
print(f"  3D Parcentric + Parfocal Offset")
print(f"  {args.ref_mag:.0f}x -> {targets_str}")
print(f"{'=' * 60}")

# ── Acquire reference ────────────────────────────────────────────────

print(f"\n  Reference: {args.ref_mag:.0f}x @ zoom {args.ref_zoom}")
stack_ref, ref_stage, ref_pixel_um, ref_z_step = switch_and_acquire_stack(
    args.ref_mag, args.ref_zoom)
if stack_ref is None:
    sys.exit(1)

ref_vol = stack_ref.astype(np.float64)
image_size = stack_ref.shape[2]
ref_fov_um = ref_pixel_um * image_size
all_results = {}

# ── Helper: make green/magenta overlay ───────────────────────────────

def make_overlay(a, b):
    an = a / (a.max() or 1)
    bn = b / (b.max() or 1)
    ov = np.zeros((*a.shape, 3))
    ov[..., 1] = an
    ov[..., 0] = bn
    ov[..., 2] = bn
    return np.clip(ov, 0, 1)

# ── Loop over targets ────────────────────────────────────────────────

for tmag in args.target_mag:
    tz = target_zooms[tmag]
    settle = args.settle.get(str(int(tmag)), 0)

    print(f"\n  Target: {tmag:.0f}x @ zoom {tz}")
    stack_tgt, tgt_stage, tgt_pixel_um, tgt_z_step = switch_and_acquire_stack(
        tmag, tz, extra_settle=settle)
    if stack_tgt is None:
        print(f"  SKIP: {tmag:.0f}x acquire failed")
        continue

    # Cross-correlate
    pixel_mismatch = abs(tgt_pixel_um - ref_pixel_um) / ref_pixel_um * 100
    z_step_mismatch = abs(tgt_z_step - ref_z_step) / max(abs(ref_z_step), 1e-9) * 100

    min_z = min(ref_vol.shape[0], stack_tgt.shape[0])
    rv = ref_vol[:min_z]
    tv = stack_tgt[:min_z].astype(np.float64)

    shift, error, diffphase = phase_cross_correlation(rv, tv, upsample_factor=20)

    shift_z_sl, shift_y_px, shift_x_px = shift
    shift_x_um = shift_x_px * ref_pixel_um
    shift_y_um = shift_y_px * ref_pixel_um
    shift_z_um = shift_z_sl * abs(ref_z_step)
    dist_xy = (shift_x_um**2 + shift_y_um**2)**0.5
    dist_3d = (shift_x_um**2 + shift_y_um**2 + shift_z_um**2)**0.5

    motor_dx = tgt_stage["x_um"] - ref_stage["x_um"]
    motor_dy = tgt_stage["y_um"] - ref_stage["y_um"]

    print(f"  XY: ({shift_x_um:+.1f}, {shift_y_um:+.1f}) um = {dist_xy:.1f} um")
    print(f"  Z:  {shift_z_um:+.1f} um")
    print(f"  Motor: ({motor_dx:+.1f}, {motor_dy:+.1f}) um")

    all_results[f"{tmag:.0f}x"] = {
        "shift_xy_px": [float(shift_x_px), float(shift_y_px)],
        "shift_z_slices": float(shift_z_sl),
        "shift_xy_um": [float(shift_x_um), float(shift_y_um)],
        "shift_z_um": float(shift_z_um),
        "distance_xy_um": float(dist_xy),
        "distance_3d_um": float(dist_3d),
        "correlation_error": float(error),
        "motor_delta_um": [float(motor_dx), float(motor_dy)],
        "target_pixel_um": float(tgt_pixel_um),
        "pixel_mismatch_pct": float(pixel_mismatch),
        "target_z_step_um": float(tgt_z_step),
        "z_step_mismatch_pct": float(z_step_mismatch),
        "stack_depth": int(min_z),
        "target_zoom": tz,
    }

    # ── Per-target visual report ─────────────────────────────────────

    mid_z = min_z // 2
    ref_mid = rv[mid_z]
    tgt_mid = tv[mid_z]
    ref_n = ref_mid / (ref_mid.max() or 1)
    tgt_n = tgt_mid / (tgt_mid.max() or 1)
    tgt_shifted = ndi_shift(tgt_mid, [shift_y_px, shift_x_px])
    tgt_s = tgt_shifted / (tgt_shifted.max() or 1)

    fig = plt.figure(figsize=(22, 16))
    gs = fig.add_gridspec(3, 4, hspace=0.35, wspace=0.3)

    # Row 1: mid-slices
    ax = fig.add_subplot(gs[0, 0])
    ax.imshow(ref_mid, cmap="gray")
    ax.set_title(f"{args.ref_mag:.0f}x mid (Z={mid_z})", fontsize=11)

    ax = fig.add_subplot(gs[0, 1])
    ax.imshow(tgt_mid, cmap="gray")
    ax.set_title(f"{tmag:.0f}x mid (Z={mid_z})", fontsize=11)

    ax = fig.add_subplot(gs[0, 2])
    ax.imshow(make_overlay(ref_mid, tgt_mid))
    ax.set_title("Raw overlay", fontsize=11)

    ax = fig.add_subplot(gs[0, 3])
    ov_r = np.zeros((*ref_mid.shape, 3))
    ov_r[..., 1] = ref_n; ov_r[..., 0] = tgt_s; ov_r[..., 2] = tgt_s
    ax.imshow(np.clip(ov_r, 0, 1))
    ax.set_title("Registered overlay", fontsize=11)

    # Row 2: MIPs + vector
    ax = fig.add_subplot(gs[1, 0])
    ax.imshow(make_overlay(rv.max(0), tv.max(0)))
    ax.set_title("MIP XY", fontsize=11)

    ax = fig.add_subplot(gs[1, 1])
    ax.imshow(make_overlay(rv.max(1), tv.max(1)), aspect="auto")
    ax.set_title("MIP XZ", fontsize=11)
    ax.set_ylabel("Z"); ax.set_xlabel("X")

    ax = fig.add_subplot(gs[1, 2])
    ax.imshow(make_overlay(rv.max(2), tv.max(2)), aspect="auto")
    ax.set_title("MIP YZ", fontsize=11)
    ax.set_ylabel("Z"); ax.set_xlabel("Y")

    ax = fig.add_subplot(gs[1, 3])
    lim = max(abs(shift_x_px), abs(shift_y_px), abs(shift_z_sl), 10) * 1.5
    ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim); ax.set_aspect("equal")
    ax.axhline(0, color="gray", lw=0.5); ax.axvline(0, color="gray", lw=0.5)
    ax.plot(0, 0, "go", ms=12, label=f"{args.ref_mag:.0f}x")
    ax.plot(shift_x_px, shift_y_px, "m^", ms=12, label=f"{tmag:.0f}x")
    ax.annotate("", xy=(shift_x_px, shift_y_px), xytext=(0, 0),
                arrowprops=dict(arrowstyle="->", color="red", lw=2.5))
    ax.set_xlabel("X (px)"); ax.set_ylabel("Y (px)")
    ax.set_title(f"XY: ({shift_x_um:+.1f}, {shift_y_um:+.1f}) um\nZ: {shift_z_um:+.1f} um")
    ax.legend(fontsize=9); ax.grid(True, alpha=0.3)

    # Row 3: Z profile + text
    ax = fig.add_subplot(gs[2, 0:2])
    z_axis = np.arange(min_z) * abs(ref_z_step)
    rp = rv.mean(axis=(1, 2)); tp = tv.mean(axis=(1, 2))
    ax.plot(z_axis, rp / rp.max(), "g-", lw=2, label=f"{args.ref_mag:.0f}x")
    ax.plot(z_axis, tp / tp.max(), "m-", lw=2, label=f"{tmag:.0f}x")
    ax.set_xlabel("Z (um)"); ax.set_ylabel("Intensity (norm)")
    ax.set_title("Z profile"); ax.legend(fontsize=9); ax.grid(True, alpha=0.3)

    ax = fig.add_subplot(gs[2, 2:4])
    ax.axis("off")
    txt = (
        f"3D Offset: {args.ref_mag:.0f}x -> {tmag:.0f}x\n"
        f"{'-' * 40}\n"
        f"Shift XY: ({shift_x_um:+.2f}, {shift_y_um:+.2f}) um\n"
        f"Shift Z:  {shift_z_um:+.2f} um\n"
        f"Dist XY:  {dist_xy:.2f} um\n"
        f"Dist 3D:  {dist_3d:.2f} um\n"
        f"Corr err: {error:.4f}\n"
        f"{'-' * 40}\n"
        f"Motor:    ({motor_dx:+.2f}, {motor_dy:+.2f}) um\n"
        f"{'-' * 40}\n"
        f"Pixel:    {ref_pixel_um:.4f} / {tgt_pixel_um:.4f} um ({pixel_mismatch:.1f}%)\n"
        f"Z-step:   {abs(ref_z_step):.2f} / {abs(tgt_z_step):.2f} um ({z_step_mismatch:.1f}%)\n"
        f"Depth:    {min_z} slices\n"
        f"FOV:      {ref_fov_um:.1f} um\n"
        f"Zoom:     {args.ref_zoom} / {tz}"
    )
    ax.text(0.05, 0.95, txt, transform=ax.transAxes, fontsize=12,
            va="top", fontfamily="monospace",
            bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5))

    fig.suptitle(
        f"3D Offset: {args.ref_mag:.0f}x (z{args.ref_zoom}) -> {tmag:.0f}x (z{tz})  |  "
        f"XY = ({shift_x_um:+.1f}, {shift_y_um:+.1f}) um  |  "
        f"Z = {shift_z_um:+.1f} um  |  3D = {dist_3d:.1f} um",
        fontsize=14, fontweight="bold")

    path = os.path.join(out_dir, f"parcentric_3d_{args.ref_mag:.0f}x_{tmag:.0f}x.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Report: {path}")

# ── Summary ──────────────────────────────────────────────────────────

print(f"\n{'=' * 60}")
print(f"  Summary: {args.ref_mag:.0f}x reference")
print(f"{'=' * 60}")
print(f"  {'Target':<8}  {'dX um':>8}  {'dY um':>8}  {'dZ um':>8}  {'Dist XY':>8}  {'Dist 3D':>8}  {'Motor dX':>9}  {'Motor dY':>9}")
print(f"  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*9}  {'-'*9}")
for name, r in all_results.items():
    sx, sy = r["shift_xy_um"]
    mx, my = r["motor_delta_um"]
    print(f"  {name:<8}  {sx:>+8.2f}  {sy:>+8.2f}  {r['shift_z_um']:>+8.2f}  "
          f"{r['distance_xy_um']:>8.2f}  {r['distance_3d_um']:>8.2f}  {mx:>+9.2f}  {my:>+9.2f}")

# Save combined JSON
combined = {
    "ref_objective": f"{args.ref_mag:.0f}x",
    "ref_zoom": args.ref_zoom,
    "ref_fov_um": float(ref_fov_um),
    "ref_pixel_um": float(ref_pixel_um),
    "ref_z_step_um": float(ref_z_step),
    "targets": all_results,
}
json_path = os.path.join(out_dir, "parcentric_3d_all.json")
with open(json_path, "w") as f:
    json.dump(combined, f, indent=2)
print(f"\n  JSON: {json_path}")

# ── Switch back ──────────────────────────────────────────────────────

print(f"\n  Switching back to {args.ref_mag:.0f}x...")
drv.set_objective(client, job, hw, magnification=args.ref_mag)
time.sleep(3)
drv.select_job(client, job)
drv.set_zoom(client, job, args.ref_zoom)
print("  Done.")

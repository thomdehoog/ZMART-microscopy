"""
3D Parcentric + Parfocal Offset via Phase Cross-Correlation
=============================================================
Acquires Z-stacks on reference and target objectives, measures the
(dX, dY, dZ) offset using 3D phase cross-correlation.

Objectives are selected by slot number to avoid ambiguity (e.g. two
20x objectives). The script sets up Z-stacks automatically (z-galvo,
centered on 0) and restores original settings when done.

NOTE: z-wide (motor Z) changes when switching objectives, but z-galvo
range stays centered on 0. The parfocal offset appears as dZ.

TODO: For a robust calibration, the measurement should be repeated at
~6 different stage positions spread across the sample (e.g. center +
4 corners + 1 random). This would reveal any position-dependent
variation in the parcentric/parfocal offset and give statistics
(mean, std) for the calibration values.

Usage:
    python test_parcentric_offset_3d.py --ref-slot 1 --target-slot 2 0
    python test_parcentric_offset_3d.py --ref-slot 1 --target-slot 2 --settle '{"0": 20}'
    python test_parcentric_offset_3d.py --ref-slot 1 --target-slot 2 0 --z-range 40 --z-step 1
"""

import argparse
import json
import os
import shutil
import sys
import time
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

parser = argparse.ArgumentParser(
    description="3D Parcentric + Parfocal Offset via Cross-Correlation")
parser.add_argument("--ref-slot", type=int, required=True,
                    help="Reference objective slot number (e.g. 1 for 10x)")
parser.add_argument("--target-slot", type=int, nargs="+", required=True,
                    help="Target objective slot number(s) (e.g. 2 0)")
parser.add_argument("--ref-zoom", type=float, default=10,
                    help="Reference zoom level (default: 10)")
parser.add_argument("--settle", type=json.loads, default="{}",
                    help='Extra settle time per slot, e.g. \'{"0": 20}\'')
parser.add_argument("--z-range", type=float, default=40,
                    help="Z-stack half-range in um (default: 40 = +/-40)")
parser.add_argument("--z-step", type=float, default=1.0,
                    help="Z-stack step size in um (default: 1.0)")
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
import navigator_expert.driver as drv
from navigator_expert.driver.scanning_templates import TEMPLATE_XML, apply_lrp_change, save_and_read_lrp
from navigator_expert.driver.scanning_template_editors_scan import lrp_set_pan
from navigator_expert.driver.scanning_template_editors_roi import lrp_enable_roi_scan
from navigator_expert.driver.scanning_template_editors_z import (
    lrp_set_z_stack_active, lrp_set_z_use_mode, lrp_set_sections,
)
from navigator_expert.driver.scanning_template_editors_focus import lrp_set_stack_calculation_mode
from navigator_expert.driver.readers import get_job_settings, get_lasx_settings
from navigator_expert.driver.scanning_template_parsers import get_master_attrs
from navigator_expert.driver.utils import parse_tile_geometry
from navigator_expert.driver.ome_tiff import fix_ome_tiff, update_ome_tiff_filename
from navigator_expert.driver.prechecks import check_idle

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

# ── Build objective lookup by slot ───────────────────────────────────

objs_by_slot = {}
for o in hw.get("Microscope", {}).get("objectives", []):
    if o.get("objectiveNumber", 0) != 0:
        objs_by_slot[o["slotIndex"]] = o

def obj_info(slot):
    """Return (label, full_name, magnification) for a slot."""
    o = objs_by_slot.get(slot)
    if not o:
        print(f"  ABORT: no objective in slot {slot}")
        print(f"  Available slots: {list(objs_by_slot.keys())}")
        sys.exit(1)
    mag = o["magnification"]
    na = o["numericalAperture"]
    imm = o.get("immersion", "").strip()
    name = o.get("name", "").strip()
    label = f"slot{slot}_{mag:.0f}x_{na}NA_{imm}"
    return label, name, mag

# Validate slots
ref_label, ref_name, ref_mag = obj_info(args.ref_slot)
target_infos = {}
for ts in args.target_slot:
    tl, tn, tm = obj_info(ts)
    target_infos[ts] = {"label": tl, "name": tn, "mag": tm}

print(f"  Reference: {ref_name} ({ref_label})")
for ts, ti in target_infos.items():
    print(f"  Target:    {ti['name']} ({ti['label']})")

# Compute target zooms (fractional, for exact pixel size matching)
target_zooms = {}
for ts, ti in target_infos.items():
    tz = args.ref_zoom * ref_mag / ti["mag"]
    target_zooms[ts] = tz
    print(f"  Zoom: {ref_label} @ {args.ref_zoom} -> {ti['label']} @ {tz:.2f}")

# ── Output directory ──────────────────────────────────────────────────

_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
_default_out = os.path.join(
    str(Path(__file__).resolve().parent.parent), "config", "alignment", _timestamp)
out_dir = args.output or _default_out
os.makedirs(out_dir, exist_ok=True)
print(f"  Output: {out_dir}")

# ── Save original Z-stack settings for restoration ───────────────────

parsed_orig = save_and_read_lrp(client)
orig_attrs = get_master_attrs(parsed_orig, job)
orig_z = {
    "ZUseMode": orig_attrs.get("ZUseMode"),
    "Sections": orig_attrs.get("Sections"),
    "Begin": orig_attrs.get("Begin"),
    "End": orig_attrs.get("End"),
    "StackCalculationMode": orig_attrs.get("StackCalculationMode"),
}
print(f"  Saved original Z-stack settings")

# ── Helper: switch objective by slot, acquire Z-stack ────────────────

sections = int(2 * args.z_range / args.z_step) + 1


def switch_and_acquire_stack(slot, zoom, extra_settle=0):
    """Switch objective by slot, set zoom + Z-stack, acquire, return data."""
    label, name, mag = obj_info(slot)
    print(f"  Switching to {name} (slot {slot})...")

    r_obj = drv.set_objective(client, job, hw, name=name)
    if not r_obj or not r_obj.get("success"):
        print(f"  ABORT: objective switch failed: {r_obj}")
        return None, None, None, None
    time.sleep(3)

    if extra_settle > 0:
        print(f"  Waiting {extra_settle:.0f}s for settle...")
        time.sleep(extra_settle)

    # Verify objective switched
    drv.select_job(client, job)
    time.sleep(2)
    settings = get_job_settings(client, job)
    if settings:
        current_obj = settings.get("objective", {}).get("name", "").strip()
        if current_obj and current_obj != name:
            print(f"  WARNING: expected '{name}', got '{current_obj}'")

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

    # Set up Z-stack: z-galvo, constant step size, via LRP + API
    def setup_z(p):
        lrp_set_z_stack_active(p, False, job)
        lrp_set_z_use_mode(p, "z-galvo", job)
        lrp_set_stack_calculation_mode(p, 1, job)
        lrp_set_sections(p, sections, job)
        lrp_set_z_stack_active(p, True, job)
    apply_lrp_change(client, TEMPLATE_XML, setup_z, confirm_delays=(2, 4, 6))
    drv.set_z_stack_definition(client, job,
                               begin_um=args.z_range, end_um=-args.z_range)
    drv.set_z_stack_step_size(client, job, args.z_step)

    # Read settings
    settings = get_job_settings(client, job)
    geo = parse_tile_geometry(settings)
    stage = drv.get_xy(client)

    print(f"  FOV: {geo['tile_w_um']:.2f} um, pixel: {geo['pixel_w_um']:.4f} um, "
          f"zoom: {zoom:.2f}")
    print(f"  Z-stack: {sections} sections, {args.z_step:.2f} um step, "
          f"{2 * args.z_range:.1f} um range")

    # Wait for idle before acquiring
    idle = check_idle(client, timeout=30)
    if not idle["success"]:
        print("  WARNING: scanner not idle, proceeding anyway")

    # Acquire
    print(f"  Acquiring Z-stack...")
    drv.select_job(client, job)
    time.sleep(1)
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

    image_files = sorted(detection["image_files"])
    print(f"  Found {len(image_files)} file(s) (expected {sections})")

    if len(image_files) != sections:
        print(f"  WARNING: file count mismatch ({len(image_files)} != {sections})")

    # Load stack
    if len(image_files) == 1:
        stack = tifffile.imread(str(image_files[0]))
        if stack.ndim == 2:
            stack = stack[np.newaxis, ...]
    else:
        slices = []
        for f in image_files:
            img = tifffile.imread(str(f))
            if img.ndim == 3:
                img = img[0]
            slices.append(img)
        stack = np.array(slices)

    print(f"  Stack shape: {stack.shape} ({stack.dtype})")

    # Copy, fix OME-TIFF, rename to output dir
    obj_dir = os.path.join(out_dir, label)
    os.makedirs(obj_dir, exist_ok=True)
    for i, src in enumerate(image_files):
        dst_name = f"{label}_z{zoom:.1f}_Z{i:04d}.ome.tif"
        dst = os.path.join(obj_dir, dst_name)
        shutil.copy2(str(src), dst)
        fix_ome_tiff(dst)
        update_ome_tiff_filename(dst)
    print(f"  Saved {len(image_files)} files to {obj_dir}")

    return stack, stage, geo["pixel_w_um"], args.z_step


# ── Helper: green/magenta overlay ────────────────────────────────────

def make_overlay(a, b):
    an = a / (a.max() or 1)
    bn = b / (b.max() or 1)
    ov = np.zeros((*a.shape, 3))
    ov[..., 1] = an
    ov[..., 0] = bn
    ov[..., 2] = bn
    return np.clip(ov, 0, 1)


# ── Main ─────────────────────────────────────────────────────────────

targets_str = ", ".join(ti["label"] for ti in target_infos.values())

print(f"\n{'=' * 60}")
print(f"  3D Parcentric + Parfocal Offset")
print(f"  {ref_label} -> {targets_str}")
print(f"{'=' * 60}")

# Acquire reference
print(f"\n  Reference: {ref_name} @ zoom {args.ref_zoom}")
stack_ref, ref_stage, ref_pixel_um, ref_z_step = switch_and_acquire_stack(
    args.ref_slot, args.ref_zoom)
if stack_ref is None:
    sys.exit(1)

ref_vol = stack_ref.astype(np.float64)
image_size = stack_ref.shape[2]
ref_fov_um = ref_pixel_um * image_size
all_results = {}

# Loop over targets
for ts in args.target_slot:
    ti = target_infos[ts]
    tz = target_zooms[ts]
    settle = args.settle.get(str(ts), 0)
    tgt_label = ti["label"]
    tgt_name = ti["name"]

    print(f"\n  Target: {tgt_name} @ zoom {tz:.2f}")
    stack_tgt, tgt_stage, tgt_pixel_um, tgt_z_step = switch_and_acquire_stack(
        ts, tz, extra_settle=settle)
    if stack_tgt is None:
        print(f"  SKIP: {tgt_name} acquire failed")
        continue

    # Cross-correlate
    pixel_mismatch = abs(tgt_pixel_um - ref_pixel_um) / ref_pixel_um * 100
    z_step_mismatch = abs(tgt_z_step - ref_z_step) / max(abs(ref_z_step), 1e-9) * 100

    min_z = min(ref_vol.shape[0], stack_tgt.shape[0])
    rv = ref_vol[:min_z]
    tv = stack_tgt[:min_z].astype(np.float64)

    shift, error, _ = phase_cross_correlation(rv, tv, upsample_factor=20)

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
    if pixel_mismatch > 1:
        print(f"  WARNING: pixel mismatch {pixel_mismatch:.1f}%")

    all_results[tgt_label] = {
        "full_name": tgt_name,
        "slot": ts,
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
        "target_zoom": float(tz),
    }

    # ── Visual report ────────────────────────────────────────────────

    tv_registered = ndi_shift(tv, [shift_z_sl, shift_y_px, shift_x_px])

    rp = rv.mean(axis=(1, 2))
    tp = tv.mean(axis=(1, 2))
    best_z = int(np.argmax(rp))

    margin = min_z // 10
    z_indices = np.linspace(margin, min_z - margin - 1, 5).astype(int)
    z_indices[2] = best_z

    fig = plt.figure(figsize=(24, 20))
    gs = fig.add_gridspec(5, 5, hspace=0.35, wspace=0.25)

    for col, zi in enumerate(z_indices):
        ref_sl = rv[zi]
        tgt_sl = tv[zi]
        ref_n = ref_sl / (ref_sl.max() or 1)

        ax = fig.add_subplot(gs[0, col])
        ax.imshow(make_overlay(ref_sl, tgt_sl))
        z_um = zi * abs(ref_z_step)
        ax.set_title(f"Z={zi} ({z_um:.0f} um)"
                     f"{' *' if zi == best_z else ''}", fontsize=10)
        if col == 0:
            ax.set_ylabel("Raw overlay", fontsize=11)

        reg_sl = tv_registered[zi]
        reg_n = reg_sl / (reg_sl.max() or 1)
        ax = fig.add_subplot(gs[1, col])
        ov_r = np.zeros((*ref_sl.shape, 3))
        ov_r[..., 1] = ref_n
        ov_r[..., 0] = reg_n
        ov_r[..., 2] = reg_n
        ax.imshow(np.clip(ov_r, 0, 1))
        if col == 0:
            ax.set_ylabel("Registered", fontsize=11)

    ax = fig.add_subplot(gs[2, 0])
    ax.imshow(make_overlay(rv.max(0), tv.max(0)))
    ax.set_title("MIP XY (raw)", fontsize=10)

    ax = fig.add_subplot(gs[2, 1])
    ax.imshow(make_overlay(rv.max(0), tv_registered.max(0)))
    ax.set_title("MIP XY (registered)", fontsize=10)

    ax = fig.add_subplot(gs[2, 2])
    ax.imshow(make_overlay(rv.max(1), tv.max(1)), aspect="auto")
    ax.set_title("MIP XZ (raw)", fontsize=10)
    ax.set_ylabel("Z"); ax.set_xlabel("X")

    ax = fig.add_subplot(gs[2, 3])
    ax.imshow(make_overlay(rv.max(1), tv_registered.max(1)), aspect="auto")
    ax.set_title("MIP XZ (registered)", fontsize=10)
    ax.set_ylabel("Z"); ax.set_xlabel("X")

    ax = fig.add_subplot(gs[2, 4])
    lim = max(abs(shift_x_px), abs(shift_y_px), abs(shift_z_sl), 10) * 1.5
    ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim); ax.set_aspect("equal")
    ax.axhline(0, color="gray", lw=0.5); ax.axvline(0, color="gray", lw=0.5)
    ax.plot(0, 0, "go", ms=12, label=ref_label)
    ax.plot(shift_x_px, shift_y_px, "m^", ms=12, label=tgt_label)
    ax.annotate("", xy=(shift_x_px, shift_y_px), xytext=(0, 0),
                arrowprops=dict(arrowstyle="->", color="red", lw=2.5))
    ax.set_xlabel("X (px)"); ax.set_ylabel("Y (px)")
    ax.set_title(f"XY: ({shift_x_um:+.1f}, {shift_y_um:+.1f}) um\n"
                 f"Z: {shift_z_um:+.1f} um")
    ax.legend(fontsize=9); ax.grid(True, alpha=0.3)

    ax = fig.add_subplot(gs[3, 0])
    ax.imshow(make_overlay(rv.max(2), tv.max(2)), aspect="auto")
    ax.set_title("MIP YZ (raw)", fontsize=10)
    ax.set_ylabel("Z"); ax.set_xlabel("Y")

    ax = fig.add_subplot(gs[3, 1])
    ax.imshow(make_overlay(rv.max(2), tv_registered.max(2)), aspect="auto")
    ax.set_title("MIP YZ (registered)", fontsize=10)
    ax.set_ylabel("Z"); ax.set_xlabel("Y")

    ax = fig.add_subplot(gs[3, 2:4])
    z_axis = np.arange(min_z) * abs(ref_z_step)
    tp_reg = tv_registered.mean(axis=(1, 2))
    ax.plot(z_axis, rp / rp.max(), "g-", lw=2, label=ref_label)
    ax.plot(z_axis, tp / tp.max(), "m--", lw=1.5, alpha=0.5,
            label=f"{tgt_label} (raw)")
    ax.plot(z_axis, tp_reg / (tp_reg.max() or 1), "m-", lw=2,
            label=f"{tgt_label} (registered)")
    ax.axvline(best_z * abs(ref_z_step), color="gray", ls=":", alpha=0.5)
    ax.set_xlabel("Z (um)"); ax.set_ylabel("Intensity (norm)")
    ax.set_title("Z profile: raw vs registered")
    ax.legend(fontsize=9); ax.grid(True, alpha=0.3)

    ax = fig.add_subplot(gs[3, 4])
    ax.axis("off")
    txt = (
        f"3D Offset\n"
        f"{ref_label}\n-> {tgt_label}\n"
        f"{'-' * 32}\n"
        f"XY:  ({shift_x_um:+.2f}, {shift_y_um:+.2f}) um\n"
        f"Z:   {shift_z_um:+.2f} um\n"
        f"dXY: {dist_xy:.2f} um\n"
        f"d3D: {dist_3d:.2f} um\n"
        f"err: {error:.4f}\n"
        f"{'-' * 32}\n"
        f"Motor: ({motor_dx:+.1f}, {motor_dy:+.1f})\n"
        f"{'-' * 32}\n"
        f"px: {ref_pixel_um:.4f}/{tgt_pixel_um:.4f}\n"
        f"    ({pixel_mismatch:.1f}%)\n"
        f"dz: {abs(ref_z_step):.2f}/{abs(tgt_z_step):.2f}\n"
        f"    ({z_step_mismatch:.1f}%)\n"
        f"N:  {min_z} slices\n"
        f"FOV:{ref_fov_um:.0f} um\n"
        f"z:  {args.ref_zoom}/{tz:.1f}"
    )
    ax.text(0.05, 0.95, txt, transform=ax.transAxes, fontsize=10,
            va="top", fontfamily="monospace",
            bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5))

    fig.suptitle(
        f"3D Offset: {ref_label} (z{args.ref_zoom}) -> "
        f"{tgt_label} (z{tz:.1f})  |  "
        f"XY = ({shift_x_um:+.1f}, {shift_y_um:+.1f}) um  |  "
        f"Z = {shift_z_um:+.1f} um  |  3D = {dist_3d:.1f} um",
        fontsize=13, fontweight="bold")

    path = os.path.join(out_dir, f"alignment_{ref_label}_vs_{tgt_label}.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Report: {path}")

# ── Summary ──────────────────────────────────────────────────────────

print(f"\n{'=' * 70}")
print(f"  Summary: {ref_name} (slot {args.ref_slot}) reference")
print(f"{'=' * 70}")
print(f"  {'Target':<30}  {'dX':>6}  {'dY':>6}  {'dZ':>6}  "
      f"{'dXY':>6}  {'d3D':>6}  {'mX':>7}  {'mY':>7}")
print(f"  {'-'*30}  {'-'*6}  {'-'*6}  {'-'*6}  "
      f"{'-'*6}  {'-'*6}  {'-'*7}  {'-'*7}")
for name, r in all_results.items():
    sx, sy = r["shift_xy_um"]
    mx, my = r["motor_delta_um"]
    print(f"  {name:<30}  {sx:>+6.1f}  {sy:>+6.1f}  {r['shift_z_um']:>+6.1f}  "
          f"{r['distance_xy_um']:>6.1f}  {r['distance_3d_um']:>6.1f}  "
          f"{mx:>+7.1f}  {my:>+7.1f}")

# Save JSON
combined = {
    "timestamp": _timestamp,
    "ref_objective": ref_name,
    "ref_label": ref_label,
    "ref_slot": args.ref_slot,
    "ref_zoom": args.ref_zoom,
    "ref_fov_um": float(ref_fov_um),
    "ref_pixel_um": float(ref_pixel_um),
    "ref_z_step_um": float(ref_z_step),
    "z_range_um": args.z_range,
    "targets": all_results,
}
json_path = os.path.join(out_dir, "alignment_results.json")
with open(json_path, "w") as f:
    json.dump(combined, f, indent=2)
print(f"\n  JSON: {json_path}")

# ── Restore original settings and switch back ────────────────────────

print(f"\n  Restoring original settings...")
drv.set_objective(client, job, hw, name=ref_name)
time.sleep(3)
drv.select_job(client, job)
time.sleep(1)
drv.set_zoom(client, job, args.ref_zoom)

# Restore original Z-stack settings via LRP
orig_z_mode = int(orig_z.get("ZUseMode", 2))
orig_sections = int(orig_z.get("Sections", 1))
orig_calc_mode = int(orig_z.get("StackCalculationMode", 2))

def restore_z(p):
    lrp_set_z_use_mode(p, "z-galvo" if orig_z_mode == 1 else "z-wide", job)
    lrp_set_stack_calculation_mode(p, orig_calc_mode, job)
    lrp_set_sections(p, orig_sections, job)
    lrp_set_z_stack_active(p, False, job)
apply_lrp_change(client, TEMPLATE_XML, restore_z, confirm_delays=(2, 4, 6))

# Restore begin/end via API if they were set
orig_begin = float(orig_z.get("Begin", 0)) * 1e6
orig_end = float(orig_z.get("End", 0)) * 1e6
if abs(orig_begin) > 0.01 or abs(orig_end) > 0.01:
    drv.set_z_stack_definition(client, job,
                               begin_um=orig_begin, end_um=orig_end)

print("  Done.")

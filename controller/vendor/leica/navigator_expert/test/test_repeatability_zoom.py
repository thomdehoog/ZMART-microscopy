"""
Repeatability test: measure raw parcentric offset at different zoom levels.
Switches 10x -> 20x N times at each zoom, cross-correlates, reports in um.

Usage:
    python test_repeatability_zoom.py --zooms 5 10 --repeats 3
    python test_repeatability_zoom.py --zooms 5 7.5 10 --repeats 5
"""

import argparse
import json
import os
import sys
import time
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

parser = argparse.ArgumentParser(description="Repeatability at different zooms")
parser.add_argument("--zooms", type=float, nargs="+", required=True,
                    help="Reference zoom levels to test (e.g. 5 10)")
parser.add_argument("--repeats", type=int, default=3,
                    help="Repeats per zoom (default: 3)")
parser.add_argument("--ref-slot", type=int, default=1)
parser.add_argument("--target-slot", type=int, default=2)
parser.add_argument("--output", default=None)
args = parser.parse_args()

# ── Imports ────────────────────────────────────────────────────────────

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

# ── Connect ────────────────────────────────────────────────────────────

client = lasx_api.LasxApiClientPyModel
confirmed = client.Connect("PythonClient")
if not confirmed:
    print("  ABORT: Cannot connect")
    sys.exit(1)

if not drv.ping(client):
    print("  ABORT: ping failed")
    sys.exit(1)

job = drv.get_selected_job(client).get("Name")
hw = drv.get_hardware_info(client)
if not hw:
    print("  ABORT: no hardware info")
    sys.exit(1)
print(f"  Job: {job}")

# ── Objective info ─────────────────────────────────────────────────────

objs_by_slot = {}
for o in hw.get("Microscope", {}).get("objectives", []):
    if o.get("objectiveNumber", 0) != 0:
        objs_by_slot[o["slotIndex"]] = o

ref_obj = objs_by_slot[args.ref_slot]
tgt_obj = objs_by_slot[args.target_slot]
ref_mag = ref_obj["magnification"]
tgt_mag = tgt_obj["magnification"]
ref_name = ref_obj["name"].strip()
tgt_name = tgt_obj["name"].strip()

print(f"  Ref: {ref_name} (slot {args.ref_slot})")
print(f"  Tgt: {tgt_name} (slot {args.target_slot})")

# ── Output ─────────────────────────────────────────────────────────────

_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
_default_out = os.path.join(
    str(Path(__file__).resolve().parent.parent),
    "config", "alignment", f"repeatability_{_ts}")
out_dir = args.output or _default_out
os.makedirs(out_dir, exist_ok=True)
print(f"  Output: {out_dir}")

# ── Helper ─────────────────────────────────────────────────────────────

def reset_pan_roi(p):
    lrp_set_pan(p, 0, 0, job)
    lrp_enable_roi_scan(p, False, job)


def acquire_img():
    """Acquire single image, return numpy array or None."""
    baseline = drv.read_relative_path(client)
    t0 = time.time()
    r = drv.acquire(client, job)
    if not r or not r["success"]:
        print(f"    Acquire failed: {r}")
        return None
    media = get_lasx_settings()["export"]["media_path"]
    det = drv.detect_new_files(client, baseline, media, acquire_start=t0)
    if not det["success"]:
        print(f"    File detection failed: {det.get('error')}")
        return None
    img = tifffile.imread(str(sorted(det["image_files"])[0]))
    if img.ndim == 3:
        img = img[0]
    return img


def get_pixel_size():
    """Read current pixel size in um from job settings."""
    settings = get_job_settings(client, job)
    if settings is None:
        print("    WARNING: get_job_settings failed, cannot read pixel size")
        return None
    geo = parse_tile_geometry(settings)
    return geo["pixel_w_um"]


# ── Main ───────────────────────────────────────────────────────────────

all_results = {}

for ref_zoom in args.zooms:
    tgt_zoom = ref_zoom * ref_mag / tgt_mag

    print(f"\n{'=' * 60}")
    print(f"  Zoom: {ref_name} @ {ref_zoom} -> {tgt_name} @ {tgt_zoom:.2f}")
    print(f"{'=' * 60}")

    measurements = []

    for i in range(args.repeats):
        print(f"\n  --- Repeat {i+1}/{args.repeats} ---")

        # Switch to reference
        print(f"  Switching to {ref_name}...")
        drv.set_objective(client, job, hw, name=ref_name)
        time.sleep(3)
        drv.set_zoom(client, job, ref_zoom)
        time.sleep(1)
        apply_lrp_change(client, TEMPLATE_XML, reset_pan_roi,
                         confirm_delays=(2, 4, 6))

        # Read pixel size on reference
        ref_pixel = get_pixel_size()
        if ref_pixel is None:
            print(f"  SKIP: could not read ref pixel size")
            continue
        print(f"  Ref pixel: {ref_pixel:.4f} um")

        # Acquire reference
        print(f"  Acquiring ref...")
        img_ref = acquire_img()
        if img_ref is None:
            print(f"  SKIP: ref acquire failed")
            continue

        ref_stage = drv.get_xy(client)

        # Switch to target
        print(f"  Switching to {tgt_name}...")
        drv.set_objective(client, job, hw, name=tgt_name)
        time.sleep(3)
        drv.set_zoom(client, job, tgt_zoom)
        time.sleep(1)
        apply_lrp_change(client, TEMPLATE_XML, reset_pan_roi,
                         confirm_delays=(2, 4, 6))

        # Read pixel size on target
        tgt_pixel = get_pixel_size()
        if tgt_pixel is None:
            print(f"  SKIP: could not read tgt pixel size")
            continue
        print(f"  Tgt pixel: {tgt_pixel:.4f} um")

        pixel_mismatch = abs(tgt_pixel - ref_pixel) / ref_pixel * 100
        if pixel_mismatch > 5:
            print(f"  WARNING: pixel mismatch {pixel_mismatch:.1f}%")

        # Acquire target
        print(f"  Acquiring tgt...")
        img_tgt = acquire_img()
        if img_tgt is None:
            print(f"  SKIP: tgt acquire failed")
            continue

        tgt_stage = drv.get_xy(client)

        # Cross-correlate
        shift, err, _ = phase_cross_correlation(
            img_ref.astype(np.float64), img_tgt.astype(np.float64),
            upsample_factor=100)
        dy_px, dx_px = shift

        # Convert to um using EACH objective's pixel size
        # The shift is measured in pixels of the reference image
        dx_um = dx_px * ref_pixel
        dy_um = dy_px * ref_pixel
        dist = (dx_um**2 + dy_um**2)**0.5

        motor_dx = tgt_stage["x_um"] - ref_stage["x_um"]
        motor_dy = tgt_stage["y_um"] - ref_stage["y_um"]

        measurements.append({
            "dx_um": dx_um, "dy_um": dy_um, "dist_um": dist,
            "dx_px": float(dx_px), "dy_px": float(dy_px),
            "ref_pixel_um": ref_pixel, "tgt_pixel_um": tgt_pixel,
            "pixel_mismatch_pct": pixel_mismatch,
            "motor_dx": motor_dx, "motor_dy": motor_dy,
            "corr_error": float(err),
        })

        print(f"  Shift: ({dx_um:+.2f}, {dy_um:+.2f}) um = {dist:.2f} um  "
              f"[px: ({dx_px:+.1f}, {dy_px:+.1f}), "
              f"motor: ({motor_dx:+.1f}, {motor_dy:+.1f})]")

    # Summary for this zoom
    if measurements:
        arr_dx = [m["dx_um"] for m in measurements]
        arr_dy = [m["dy_um"] for m in measurements]
        arr_dist = [m["dist_um"] for m in measurements]
        print(f"\n  Summary @ zoom {ref_zoom}:")
        print(f"    dX: mean={np.mean(arr_dx):+.2f}, std={np.std(arr_dx):.2f} um")
        print(f"    dY: mean={np.mean(arr_dy):+.2f}, std={np.std(arr_dy):.2f} um")
        print(f"    dist: mean={np.mean(arr_dist):.2f}, std={np.std(arr_dist):.2f} um")

    all_results[str(ref_zoom)] = {
        "ref_zoom": ref_zoom,
        "tgt_zoom": tgt_zoom,
        "measurements": measurements,
        "summary": {
            "dx_mean": float(np.mean(arr_dx)) if measurements else None,
            "dy_mean": float(np.mean(arr_dy)) if measurements else None,
            "dist_mean": float(np.mean(arr_dist)) if measurements else None,
            "dx_std": float(np.std(arr_dx)) if measurements else None,
            "dy_std": float(np.std(arr_dy)) if measurements else None,
            "dist_std": float(np.std(arr_dist)) if measurements else None,
            "n": len(measurements),
        },
    }

# ── Final summary ──────────────────────────────────────────────────────

print(f"\n{'=' * 70}")
print(f"  Final Summary")
print(f"{'=' * 70}")
print(f"  {'Zoom':>6}  {'dX mean':>10}  {'dY mean':>10}  {'dist':>8}  "
      f"{'dX std':>8}  {'dY std':>8}  {'N':>3}")
print(f"  {'-'*6}  {'-'*10}  {'-'*10}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*3}")
for z_key, data in all_results.items():
    s = data["summary"]
    if s["n"] > 0:
        print(f"  {data['ref_zoom']:6.1f}  {s['dx_mean']:+10.2f}  "
              f"{s['dy_mean']:+10.2f}  {s['dist_mean']:8.2f}  "
              f"{s['dx_std']:8.2f}  {s['dy_std']:8.2f}  {s['n']:3d}")

# Save JSON
json_path = os.path.join(out_dir, "repeatability_results.json")
with open(json_path, "w") as f:
    json.dump(all_results, f, indent=2)
print(f"\n  JSON: {json_path}")

# Restore 10x
print(f"\n  Restoring {ref_name} @ zoom {args.zooms[0]}...")
drv.set_objective(client, job, hw, name=ref_name)
time.sleep(3)
drv.set_zoom(client, job, args.zooms[0])
print("  Done.")

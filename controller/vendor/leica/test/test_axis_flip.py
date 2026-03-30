"""
Test axis flip between image and stage coordinates.

Acquires on 10x, switches to 20x, then tests three corrections:
1. No correction (baseline)
2. +shift_x, +shift_y
3. +shift_x, -shift_y

Each test switches back to 10x first to reset position, then re-does
the switch + correction. This ensures each test starts from the same
stage position.

Usage:
    python test_axis_flip.py
"""

import sys
import time
import json
import os
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

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
client.Connect("PythonClient")
assert drv.ping(client), "ping failed"

job = drv.get_selected_job(client).get("Name")
hw = drv.get_hardware_info(client)
print(f"  Job: {job}")

drv.set_stage_limits(
    x_min=1000, x_max=130000,
    y_min=1000, y_max=100000,
    z_galvo_min=-200, z_galvo_max=200,
    z_wide_min=0, z_wide_max=25000,
)

REF_ZOOM = 5.0
TGT_ZOOM = 2.5

# Known image shift from repeatability test (um)
SHIFT_X = 9.92
SHIFT_Y = -13.54

# ── Output ─────────────────────────────────────────────────────────────

_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
out_dir = os.path.join(
    str(Path(__file__).resolve().parent.parent),
    "config", "alignment", f"axis_flip_{_ts}")
os.makedirs(out_dir, exist_ok=True)
print(f"  Output: {out_dir}")

# ── Helpers ────────────────────────────────────────────────────────────

def reset_pan_roi(p):
    lrp_set_pan(p, 0, 0, job)
    lrp_enable_roi_scan(p, False, job)


def acquire_img():
    baseline = drv.read_relative_path(client)
    t0 = time.time()
    r = drv.acquire(client, job)
    if not r or not r["success"]:
        return None
    media = get_lasx_settings()["export"]["media_path"]
    det = drv.detect_new_files(client, baseline, media, acquire_start=t0)
    if not det["success"]:
        return None
    img = tifffile.imread(str(sorted(det["image_files"])[0]))
    if img.ndim == 3:
        img = img[0]
    return img


def setup_objective(slot, zoom):
    """Switch objective, set zoom, reset pan."""
    name = next(o["name"].strip() for o in hw["Microscope"]["objectives"]
                if o.get("slotIndex") == slot and o.get("objectiveNumber", 0) != 0)
    drv.set_objective(client, job, hw, name=name)
    time.sleep(3)
    drv.set_zoom(client, job, zoom)
    time.sleep(1)
    apply_lrp_change(client, TEMPLATE_XML, reset_pan_roi,
                     confirm_delays=(2, 4, 6))


def measure_with_correction(label, dx_stage, dy_stage, img_ref, ref_pixel):
    """Switch to 20x, apply correction, acquire, cross-correlate, return result."""
    print(f"\n  [{label}] Switching to 20x...")
    setup_objective(2, TGT_ZOOM)

    post = drv.get_xy(client)
    print(f"  [{label}] Post-switch: ({post['x_um']:.1f}, {post['y_um']:.1f})")

    if dx_stage is not None:
        target_x = post["x_um"] + dx_stage
        target_y = post["y_um"] + dy_stage
        print(f"  [{label}] Moving by ({dx_stage:+.1f}, {dy_stage:+.1f}) "
              f"-> ({target_x:.1f}, {target_y:.1f})")
        r = drv.move_xy(client, target_x, target_y)
        print(f"  [{label}] Move: success={r.get('success')}")
        time.sleep(1)
    else:
        print(f"  [{label}] No correction")

    # Read pixel size
    settings = get_job_settings(client, job)
    tgt_pixel = parse_tile_geometry(settings)["pixel_w_um"]
    print(f"  [{label}] Ref pixel: {ref_pixel:.4f}, Tgt pixel: {tgt_pixel:.4f} um")

    # Acquire
    print(f"  [{label}] Acquiring...")
    img_tgt = acquire_img()
    if img_tgt is None:
        print(f"  [{label}] FAILED")
        return None

    # Cross-correlate
    shift, err, _ = phase_cross_correlation(
        img_ref.astype(np.float64), img_tgt.astype(np.float64),
        upsample_factor=100)
    dy_px, dx_px = shift
    dx_um = dx_px * ref_pixel
    dy_um = dy_px * ref_pixel
    dist = (dx_um**2 + dy_um**2)**0.5

    print(f"  [{label}] Residual: ({dx_um:+.2f}, {dy_um:+.2f}) um = {dist:.2f} um")

    return {
        "label": label,
        "correction_um": [dx_stage, dy_stage],
        "residual_x_um": dx_um,
        "residual_y_um": dy_um,
        "residual_dist_um": dist,
        "ref_pixel_um": ref_pixel,
        "tgt_pixel_um": tgt_pixel,
    }


# ── Main ───────────────────────────────────────────────────────────────

# Record home position on 10x
setup_objective(1, REF_ZOOM)
home = drv.get_xy(client)
print(f"\n  Home (10x): ({home['x_um']:.1f}, {home['y_um']:.1f})")

settings = get_job_settings(client, job)
ref_pixel = parse_tile_geometry(settings)["pixel_w_um"]
print(f"  Ref pixel: {ref_pixel:.4f} um")

# Acquire reference once
print(f"  Acquiring reference...")
img_ref = acquire_img()
assert img_ref is not None, "ref acquire failed"

results = []

# Test 1: No correction (baseline)
r = measure_with_correction("baseline", None, None, img_ref, ref_pixel)
if r:
    results.append(r)

# Return to 10x home
setup_objective(1, REF_ZOOM)
drv.move_xy(client, home["x_um"], home["y_um"])
time.sleep(1)

# Test 2: +shift_x, +shift_y
r = measure_with_correction("+X +Y", +SHIFT_X, +SHIFT_Y, img_ref, ref_pixel)
if r:
    results.append(r)

# Return to 10x home
setup_objective(1, REF_ZOOM)
drv.move_xy(client, home["x_um"], home["y_um"])
time.sleep(1)

# Test 3: +shift_x, -shift_y
r = measure_with_correction("+X -Y", +SHIFT_X, -SHIFT_Y, img_ref, ref_pixel)
if r:
    results.append(r)

# Return to 10x home
setup_objective(1, REF_ZOOM)
drv.move_xy(client, home["x_um"], home["y_um"])
time.sleep(1)

# ── Summary ────────────────────────────────────────────────────────────

print(f"\n{'=' * 70}")
print(f"  Axis Flip Test Results")
print(f"  Image shift: ({SHIFT_X:+.2f}, {SHIFT_Y:+.2f}) um")
print(f"{'=' * 70}")
print(f"  {'Label':<12}  {'Correction':<20}  {'Resid X':>10}  {'Resid Y':>10}  {'Dist':>8}")
print(f"  {'-'*12}  {'-'*20}  {'-'*10}  {'-'*10}  {'-'*8}")
for r in results:
    cx, cy = r["correction_um"]
    corr_str = f"({cx:+.1f}, {cy:+.1f})" if cx is not None else "none"
    print(f"  {r['label']:<12}  {corr_str:<20}  "
          f"{r['residual_x_um']:+10.2f}  {r['residual_y_um']:+10.2f}  "
          f"{r['residual_dist_um']:8.2f}")

# Save
json_path = os.path.join(out_dir, "axis_flip_results.json")
with open(json_path, "w") as f:
    json.dump({"shift": [SHIFT_X, SHIFT_Y], "results": results}, f, indent=2)
print(f"\n  JSON: {json_path}")
print("  Done.")

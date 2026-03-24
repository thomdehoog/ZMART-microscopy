"""
ROI Navigate Test
==================
Reads an existing ROI, computes pan+zoom, removes the ROI,
and navigates there. No acquisition.

Draw an ROI in LAS X **before** running this script.

Usage:
    python test_roi_navigate.py
    python test_roi_navigate.py --job "Overview"
"""

import argparse
import sys
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(name)s: %(message)s",
)

parser = argparse.ArgumentParser(description="ROI Navigate Test")
parser.add_argument("--job", default=None,
                    help="Job name (default: currently selected job)")
args = parser.parse_args()

# ── Import ──────────────────────────────────────────────────────────────

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from LasxApi import PYLICamApiConnector as lasx_api
import lasx as drv
from lasx.scanning_templates import (
    TEMPLATE_XML, apply_lrp_change, save_and_read_lrp,
)
from lasx.scanning_template_editors_scan import lrp_set_pan, lrp_set_zoom
from lasx.scanning_template_editors_roi import (
    lrp_enable_roi_scan, lrp_clear_rois,
    roi_geometry, roi_to_pan_zoom,
)
from lasx.scanning_template_parsers import get_rois, get_master_attrs
from lasx.readers import get_base_fov

# ── Connect ─────────────────────────────────────────────────────────────

client = lasx_api.LasxApiClientPyModel
confirmed = client.Connect("PythonClient")
print(f"  Connected: {confirmed}")
if not confirmed:
    print("  ABORT: Cannot connect to LAS X. Is it running?")
    sys.exit(1)

if not drv.ping(client):
    print("  ABORT: ping failed")
    sys.exit(1)

if args.job:
    job = args.job
else:
    selected = drv.get_selected_job(client)
    job = selected.get("Name") if selected else None
    if not job:
        job = "AF Job"
    print(f"  Auto-detected job: '{job}'")

def save_and_parse():
    return save_and_read_lrp(client)


# ── Step 1: Read ROI ────────────────────────────────────────────────────

print(f"\n{'=' * 60}")
print(f"  ROI Navigate -- job '{job}'")
print(f"{'=' * 60}")

print("\n  Step 1: Reading ROI...")

parsed = save_and_parse()
rois = get_rois(parsed, job)

if not rois:
    print("  ABORT: No ROIs found. Draw an ROI in LAS X first.")
    sys.exit(1)

roi = rois[0]
geo = roi_geometry(roi)

# Base FOV (at zoom 1) from the driver
base_fov = get_base_fov(client, job)
if not base_fov:
    print("  ABORT: cannot read base FOV")
    sys.exit(1)
fov_at_zoom1_um = base_fov[0] * 1e6

# Pan + zoom to frame the ROI
pan_x, pan_y, zoom = roi_to_pan_zoom(roi, fov_at_zoom1_um)

w_um, h_um = geo["bbox_um"]
eff_tx, eff_ty = geo["effective_translation_m"]
print(f"  ROI: {len(geo['vertices'])} vertices")
print(f"  Effective center: ({eff_tx * 1e6:.1f}, {eff_ty * 1e6:.1f}) um")
print(f"  Bbox: {w_um:.1f} x {h_um:.1f} um")
print(f"  FOV at zoom 1: {fov_at_zoom1_um:.1f} um")
print(f"  Target zoom: {zoom} (FOV={fov_at_zoom1_um / zoom:.1f} um)")
print(f"  Target pan: ({pan_x:.6f}, {pan_y:.6f})")

# ── Step 2: Clear ROI, pan+zoom ─────────────────────────────────────────

print("\n  Step 2: Clearing ROI, setting pan+zoom...")


def clear_and_navigate(p):
    lrp_enable_roi_scan(p, False, job)
    lrp_clear_rois(p, job)
    lrp_set_pan(p, pan_x, pan_y, job)
    lrp_set_zoom(p, zoom, job)


apply_lrp_change(client, TEMPLATE_XML, clear_and_navigate,
                 confirm_delays=(2, 4, 6))

# Verify
parsed = save_and_parse()
a = get_master_attrs(parsed, job)
actual_zoom = float(a.get("Zoom", 0))
actual_pan = (float(a.get("PanFirstDim", 0)),
              float(a.get("PanSecondDim", 0)))

print(f"\n  Result:")
print(f"    Zoom: {actual_zoom:.1f} (target: {zoom})")
print(f"    Pan X: {actual_pan[0]:.6f} (target: {pan_x:.6f})")
print(f"    Pan Y: {actual_pan[1]:.6f} (target: {pan_y:.6f})")

ok = (abs(actual_zoom - zoom) < 1 and
      abs(actual_pan[0] - pan_x) < 1e-5 and
      abs(actual_pan[1] - pan_y) < 1e-5)

if ok:
    print("  Navigation OK.")
else:
    print("  WARNING: Navigation did not match targets.")

# ── Step 3: Acquire single image ─────────────────────────────────────────

print("\n  Step 3: Acquiring single image...")
t0 = time.perf_counter()
r = drv.acquire_single_image(client)
elapsed = time.perf_counter() - t0

if r and r["success"]:
    print(f"  Acquired in {elapsed:.1f}s")
else:
    print(f"  Acquire failed: {r}")

print(f"\n{'=' * 60}")
if ok and r and r["success"]:
    print("  PASS: Navigated and acquired.")
elif ok:
    print("  PARTIAL: Navigation OK, acquire failed.")
else:
    print("  FAIL: Navigation did not match targets.")
print(f"{'=' * 60}")

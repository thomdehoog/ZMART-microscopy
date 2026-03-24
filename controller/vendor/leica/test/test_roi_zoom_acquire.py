"""
ROI Zoom & Acquire Test
========================
Reads an existing ROI from LAS X, zooms+pans to that region,
acquires an image, then restores the ROI.

Draw an ROI in LAS X **before** running this script.

Usage:
    python test_roi_zoom_acquire.py
    python test_roi_zoom_acquire.py --job "Overview"
"""

import argparse
import sys
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(name)s: %(message)s",
)

parser = argparse.ArgumentParser(description="ROI Zoom & Acquire Test")
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
    lrp_enable_roi_scan, lrp_clear_rois, lrp_add_roi,
    roi_geometry, roi_to_pan_zoom,
)
from lasx.scanning_template_parsers import get_rois, get_master_attrs
from lasx.readers import get_base_fov

print(f"  Driver version: {drv.__version__}")

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

# Resolve job: --job flag > currently selected job > fallback
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


# ── Step 1: Read existing ROI ──────────────────────────────────────────

print(f"\n{'=' * 60}")
print(f"  ROI Zoom & Acquire -- job '{job}'")
print(f"{'=' * 60}")

print("\n  Step 1: Reading ROI...")

parsed = save_and_parse()
rois = get_rois(parsed, job)

if not rois:
    print("  ABORT: No ROIs found. Draw an ROI in LAS X first.")
    sys.exit(1)

# Take the first ROI
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
print(f"  ROI: type={geo['type']}, {len(geo['vertices'])} vertices")
print(f"  Effective center: ({eff_tx * 1e6:.1f}, {eff_ty * 1e6:.1f}) um")
print(f"  Bbox: {w_um:.1f} x {h_um:.1f} um")
print(f"  FOV at zoom 1: {fov_at_zoom1_um:.1f} um")
print(f"  Target zoom: {zoom} (FOV={fov_at_zoom1_um / zoom:.1f} um)")
print(f"  Target pan: ({pan_x:.6f}, {pan_y:.6f})")

# ── Step 2: Clear ROI, zoom+pan to region ──────────────────────────────

print("\n  Step 2: Removing ROI, zooming+panning to region...")

# Step 2a: Clear ROIs and set pan via LRP
def clear_and_pan(p):
    lrp_enable_roi_scan(p, False, job)
    lrp_clear_rois(p, job)
    lrp_set_pan(p, pan_x, pan_y, job)

apply_lrp_change(client, TEMPLATE_XML, clear_and_pan,
                 confirm_delays=(2, 4, 6))

# Step 2b: Set zoom via API (triggers hardware refresh that applies the pan)
print(f"  Setting zoom={zoom} via API...")
r_zoom = drv.set_zoom(client, job, zoom)
print(f"  Zoom API: success={r_zoom['success']}, confirmed={r_zoom.get('confirmed')}")

# Verify
parsed = save_and_parse()
attrs = get_master_attrs(parsed, job)
actual_zoom = float(attrs.get("Zoom", 0))
actual_pan = (float(attrs.get("PanFirstDim", 0)),
              float(attrs.get("PanSecondDim", 0)))
print(f"  Zoom: {actual_zoom:.1f} (target: {zoom})")
print(f"  Pan: ({actual_pan[0]:.6f}, {actual_pan[1]:.6f}) "
      f"(target: {pan_x:.6f}, {pan_y:.6f})")

# ── Step 3: Acquire ────────────────────────────────────────────────────

print("\n  Step 3: Acquiring...")
t0 = time.perf_counter()
r = drv.acquire(client, job)
elapsed = time.perf_counter() - t0

if r and r["success"]:
    print(f"  Acquired in {elapsed:.1f}s")
else:
    print(f"  Acquire failed: {r}")

# ── Step 4: Restore ROI ───────────────────────────────────────────────

print("\n  Step 4: Restoring ROI...")


# Add ROI back without enabling ROI scan (ROI scan causes auto-zoom on reload)
def restore(p):
    lrp_add_roi(p, job, geo["type"], geo["vertices"],
                name="ROI 1", color=geo["color"],
                rotation=geo["rotation"],
                translation=geo["translation_m"],
                scale=geo["scale"])


apply_lrp_change(client, TEMPLATE_XML, restore, confirm_delays=(3, 5, 8))

print("  ROI restored.")

# ── Summary ─────────────────────────────────────────────────────────────

success = r and r["success"]
print(f"\n{'=' * 60}")
if success:
    print("  PASS: ROI read, zoomed+panned, acquired, ROI restored.")
else:
    print("  FAIL: Acquisition failed.")
print(f"{'=' * 60}")
sys.exit(0 if success else 1)

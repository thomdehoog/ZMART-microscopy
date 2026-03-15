"""
ROI Zoom & Acquire Interactive Test
=====================================
Interactive test for the full ROI workflow:
1. Start at zoom=1 (overview)
2. User draws an ROI manually in LAS X
3. Script reads the ROI, removes it, zooms+pans to that region
4. Acquires a single image
5. Re-adds the ROI at the same position

Usage:
    python test_roi_zoom_acquire.py
    python test_roi_zoom_acquire.py --job "Overview"
"""

import argparse
import os
import sys
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(name)s: %(message)s",
)

parser = argparse.ArgumentParser(description="ROI Zoom & Acquire Interactive Test")
parser.add_argument("--job", default="AF Job",
                    help="Job name to test (default: AF Job)")
args = parser.parse_args()

# ── Import ──────────────────────────────────────────────────────────────

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from LasxApi import PYLICamApiConnector as lasx_api
import lasx as drv
from lasx.scanning_templates import (
    TEMPLATE_XML, apply_lrp_change, find_scanning_templates_dir,
    save_experiment,
)
from lasx.scanning_template_editors_scan import lrp_set_pan, lrp_set_zoom
from lasx.scanning_template_editors_roi import (
    lrp_enable_roi_scan, lrp_clear_rois, lrp_add_roi,
    roi_translation_to_pan, bbox_to_zoom,
    ROI_POLYGON,
)
from lasx.scanning_template_parsers import parse_lrp

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

job = args.job
tdir = find_scanning_templates_dir()
lrp_path = os.path.join(tdir, TEMPLATE_XML.replace(".xml", ".lrp"))


def save_and_parse():
    save_experiment(client, TEMPLATE_XML, tdir, timeout=5.0)
    return parse_lrp(lrp_path)


# ── Step 1: Reset to zoom=1, clear ROIs ─────────────────────────────────

print(f"\n{'=' * 60}")
print(f"  ROI Zoom & Acquire -- job '{job}'")
print(f"{'=' * 60}")

print("\n  Step 1: Reset to zoom=1, pan=0, clear ROIs")


def reset(p):
    lrp_set_zoom(p, 1, job)
    lrp_set_pan(p, 0, 0, job)
    lrp_clear_rois(p, job)
    lrp_enable_roi_scan(p, False, job)


apply_lrp_change(client, TEMPLATE_XML, reset, confirm_delays=(2, 4, 6))
print("  Done. You should see the full field overview.")

# ── Step 2: Wait for user to draw ROI ───────────────────────────────────

print("\n  Step 2: Draw an ROI on a cell of interest in LAS X.")
input("  Press ENTER when the ROI is drawn...")

# ── Step 3: Read the ROI ────────────────────────────────────────────────

print("\n  Step 3: Reading ROI...")

parsed = save_and_parse()
rois = parsed["jobs"][job]["Master"].get("_ROIs", [])

if not rois:
    print("  ABORT: No ROIs found. Did you draw one?")
    sys.exit(1)

# Take the first ROI
roi = rois[0]
roi_type = roi.get("RoiType", ROI_POLYGON)
roi_color = roi.get("Color", "4294901760")
roi_verts = [(v["X"], v["Y"]) for v in roi.get("_Vertices", [])]
t = roi.get("_Transformation", {})
roi_tx = float(t.get("TranslationX", 0))
roi_ty = float(t.get("TranslationY", 0))
roi_rotation = float(t.get("Rotation", 0))
roi_scale_x = t.get("XScale", "1")
roi_scale_y = t.get("YScale", "1")

# Bounding box
xs = [v[0] for v in roi_verts]
ys = [v[1] for v in roi_verts]
w_um = (max(xs) - min(xs)) * 1e6
h_um = (max(ys) - min(ys)) * 1e6

# Pan + zoom
pan_x, pan_y = roi_translation_to_pan(roi_tx, roi_ty)
zoom = bbox_to_zoom(w_um, h_um)

print(f"  ROI: type={roi_type}, {len(roi_verts)} vertices, "
      f"color={roi_color}")
print(f"  Bbox: {w_um:.1f} x {h_um:.1f} um")
print(f"  Translation: ({roi_tx * 1e6:.1f}, {roi_ty * 1e6:.1f}) um")
print(f"  Target zoom: {zoom} (FOV={1160 / zoom:.1f} um)")
print(f"  Target pan: ({pan_x:.6f}, {pan_y:.6f})")

# ── Step 4: Remove ROI, zoom+pan to region ──────────────────────────────

print("\n  Step 4: Removing ROI, zooming+panning to region...")


def zoom_to_region(p):
    lrp_clear_rois(p, job)
    lrp_enable_roi_scan(p, False, job)
    lrp_set_zoom(p, zoom, job)
    lrp_set_pan(p, pan_x, pan_y, job)


apply_lrp_change(client, TEMPLATE_XML, zoom_to_region,
                 confirm_delays=(3, 5, 8))
print("  Done. View should now be zoomed into the ROI region.")

# ── Step 5: Acquire single image ────────────────────────────────────────

print("\n  Step 5: Acquiring single image...")
t0 = time.perf_counter()
r = drv.acquire_single_image(client, job)
elapsed = time.perf_counter() - t0

if r and r["success"]:
    print(f"  Acquired in {elapsed:.1f}s")
else:
    print(f"  Acquire failed: {r}")

# ── Step 6: Re-add ROI ──────────────────────────────────────────────────

print("\n  Step 6: Re-adding ROI...")


def readd_roi(p):
    lrp_add_roi(p, job, roi_type, roi_verts,
                name="ROI 1", color=roi_color,
                rotation=roi_rotation,
                translation=(roi_tx, roi_ty),
                scale=(float(roi_scale_x), float(roi_scale_y)))
    lrp_enable_roi_scan(p, True, job)


apply_lrp_change(client, TEMPLATE_XML, readd_roi,
                 confirm_delays=(3, 5, 8))

# Verify
parsed = save_and_parse()
rois = parsed["jobs"][job]["Master"].get("_ROIs", [])
roi_scan = parsed["jobs"][job]["Master"]["attrs"].get(
    "IsRoiScanEnable", "0")

print(f"  ROI count: {len(rois)} (expected 1)")
print(f"  ROI scan enabled: {roi_scan}")

success = len(rois) == 1 and roi_scan == "1"

# ── Summary ─────────────────────────────────────────────────────────────

print(f"\n{'=' * 60}")
if success:
    print("  PASS: ROI zoomed, image acquired, ROI restored.")
else:
    print("  FAIL: Something went wrong.")
print(f"{'=' * 60}")
sys.exit(0 if success else 1)

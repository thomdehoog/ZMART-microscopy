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
import os
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

# Resolve job: --job flag > currently selected job > fallback
if args.job:
    job = args.job
else:
    selected = drv.get_selected_job(client)
    job = selected.get("Name") if selected else None
    if not job:
        job = "AF Job"
    print(f"  Auto-detected job: '{job}'")

tdir = find_scanning_templates_dir()
lrp_path = os.path.join(tdir, TEMPLATE_XML.replace(".xml", ".lrp"))


def save_and_parse():
    save_experiment(client, TEMPLATE_XML, tdir, timeout=5.0)
    return parse_lrp(lrp_path)


# ── Step 1: Read existing ROI ──────────────────────────────────────────

print(f"\n{'=' * 60}")
print(f"  ROI Zoom & Acquire -- job '{job}'")
print(f"{'=' * 60}")

print("\n  Step 1: Reading ROI...")

parsed = save_and_parse()
rois = parsed["jobs"][job]["Master"].get("_ROIs", [])

if not rois:
    print("  ABORT: No ROIs found. Draw an ROI in LAS X first.")
    sys.exit(1)

# Take the first ROI
roi = rois[0]
roi_type = roi.get("RoiType", ROI_POLYGON)
roi_verts = [(v["X"], v["Y"]) for v in roi.get("_Vertices", [])]
t = roi.get("_Transformation", {})
roi_tx = float(t.get("TranslationX", 0))
roi_ty = float(t.get("TranslationY", 0))
roi_color = roi.get("Color", "4294901760")
roi_rotation = float(t.get("Rotation", 0))
roi_scale_x = float(t.get("XScale", 1))
roi_scale_y = float(t.get("YScale", 1))

# Vertex centroid in local coords (metres)
xs = [v[0] for v in roi_verts]
ys = [v[1] for v in roi_verts]
cx_m = sum(xs) / len(xs)
cy_m = sum(ys) / len(ys)

# Bounding box (um)
w_um = (max(xs) - min(xs)) * 1e6
h_um = (max(ys) - min(ys)) * 1e6

# Effective translation = ROI translation + vertex centroid offset
eff_tx = roi_tx + cx_m
eff_ty = roi_ty + cy_m

# Pan + zoom from effective centroid translation
pan_x, pan_y = roi_translation_to_pan(eff_tx, eff_ty)
zoom = bbox_to_zoom(w_um, h_um)

print(f"  ROI: type={roi_type}, {len(roi_verts)} vertices")
print(f"  Vertex centroid (local): ({cx_m * 1e6:.1f}, {cy_m * 1e6:.1f}) um")
print(f"  Translation: ({roi_tx * 1e6:.1f}, {roi_ty * 1e6:.1f}) um")
print(f"  Effective center: ({eff_tx * 1e6:.1f}, {eff_ty * 1e6:.1f}) um")
print(f"  Bbox: {w_um:.1f} x {h_um:.1f} um")
print(f"  Target zoom: {zoom} (FOV={1160 / zoom:.1f} um)")
print(f"  Target pan: ({pan_x:.6f}, {pan_y:.6f})")

# ── Step 2: Clear ROI, zoom+pan to region ──────────────────────────────

print("\n  Step 2: Removing ROI, zooming+panning to region...")

# Disable ROI scan and clear ROIs first (must disable before pan/zoom,
# otherwise only the ROI area is illuminated)
def clear_and_pan(p):
    lrp_enable_roi_scan(p, False, job)
    lrp_clear_rois(p, job)
    lrp_set_pan(p, pan_x, pan_y, job)

apply_lrp_change(client, TEMPLATE_XML, clear_and_pan,
                 confirm_delays=(2, 4, 6))

# Set zoom via API (more reliable than LRP-only)
print(f"  Setting zoom={zoom} via API...")
r_zoom = drv.set_zoom(client, job, zoom)
if r_zoom["success"]:
    print(f"  Zoom set via API: confirmed={r_zoom.get('confirmed')}")
else:
    print(f"  API zoom failed: {r_zoom['message']}, trying LRP fallback...")
    def set_zoom_fallback(p):
        lrp_set_zoom(p, zoom, job)
    apply_lrp_change(client, TEMPLATE_XML, set_zoom_fallback,
                     confirm_delays=(2, 4, 6))

# Verify zoom persisted
parsed = save_and_parse()
actual_zoom = float(parsed["jobs"][job]["Master"]["attrs"].get("Zoom", 0))
if abs(actual_zoom - zoom) > 1:
    print(f"  WARNING: zoom drifted: expected {zoom}, got {actual_zoom:.1f}")
    print(f"  Retrying via LRP...")
    def set_zoom_retry(p):
        lrp_set_zoom(p, zoom, job)
    apply_lrp_change(client, TEMPLATE_XML, set_zoom_retry,
                     confirm_delays=(3, 5, 8))
else:
    print(f"  Zoom verified: {actual_zoom:.1f}")

print("  Done. View should now be zoomed into the ROI region.")

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
    lrp_add_roi(p, job, roi_type, roi_verts,
                name="ROI 1", color=roi_color,
                rotation=roi_rotation,
                translation=(roi_tx, roi_ty),
                scale=(roi_scale_x, roi_scale_y))


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

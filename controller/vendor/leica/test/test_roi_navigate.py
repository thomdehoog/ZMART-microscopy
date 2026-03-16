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
import os
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
    TEMPLATE_XML, apply_lrp_change, find_scanning_templates_dir,
    save_experiment,
)
from lasx.scanning_template_editors_scan import lrp_set_pan, lrp_set_zoom
from lasx.scanning_template_editors_roi import (
    lrp_enable_roi_scan, lrp_clear_rois,
    roi_translation_to_pan, bbox_to_zoom,
    ROI_POLYGON,
)
from lasx.scanning_template_parsers import parse_lrp
from lasx.readers import get_job_settings
from lasx.utils import parse_tile_geometry

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

tdir = find_scanning_templates_dir()
lrp_path = os.path.join(tdir, TEMPLATE_XML.replace(".xml", ".lrp"))


def save_and_parse():
    save_experiment(client, TEMPLATE_XML, tdir, timeout=5.0)
    return parse_lrp(lrp_path)


# ── Step 1: Read ROI ────────────────────────────────────────────────────

print(f"\n{'=' * 60}")
print(f"  ROI Navigate -- job '{job}'")
print(f"{'=' * 60}")

print("\n  Step 1: Reading ROI...")

parsed = save_and_parse()
rois = parsed["jobs"][job]["Master"].get("_ROIs", [])

if not rois:
    print("  ABORT: No ROIs found. Draw an ROI in LAS X first.")
    sys.exit(1)

roi = rois[0]
roi_verts = [(v["X"], v["Y"]) for v in roi.get("_Vertices", [])]
t = roi.get("_Transformation", {})
roi_tx = float(t.get("TranslationX", 0))
roi_ty = float(t.get("TranslationY", 0))

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

# Read FOV from API (objective-aware)
settings = get_job_settings(client, job)
geo = parse_tile_geometry(settings)
fov_at_zoom1_um = geo["tile_w_um"]

# Pan + zoom
pan_x, pan_y = roi_translation_to_pan(eff_tx, eff_ty)
zoom = bbox_to_zoom(w_um, h_um, fov_at_zoom1_um)

print(f"  ROI: {len(roi_verts)} vertices")
print(f"  Vertex centroid (local): ({cx_m * 1e6:.1f}, {cy_m * 1e6:.1f}) um")
print(f"  Translation: ({roi_tx * 1e6:.1f}, {roi_ty * 1e6:.1f}) um")
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
actual_zoom = float(parsed["jobs"][job]["Master"]["attrs"].get("Zoom", 0))
a = parsed["jobs"][job]["Master"]["attrs"]
actual_pan = (float(a.get("PanFirstDim", 0)),
              float(a.get("PanSecondDim", 0)))

print(f"\n  Result:")
print(f"    Zoom: {actual_zoom:.1f} (target: {zoom})")
print(f"    Pan X: {actual_pan[0]:.6f} (target: {pan_x:.6f})")
print(f"    Pan Y: {actual_pan[1]:.6f} (target: {pan_y:.6f})")

ok = (abs(actual_zoom - zoom) < 1 and
      abs(actual_pan[0] - pan_x) < 1e-5 and
      abs(actual_pan[1] - pan_y) < 1e-5)

print(f"\n{'=' * 60}")
if ok:
    print("  PASS: Navigated to ROI region.")
else:
    print("  FAIL: Navigation did not match targets.")
print(f"{'=' * 60}")

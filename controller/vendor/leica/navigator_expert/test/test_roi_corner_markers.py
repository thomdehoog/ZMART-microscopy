"""
ROI Corner Marker Diagnostic
=============================
Places 4 small rectangle ROIs at the image quadrant corners to
empirically determine the pixel → ROI vertex coordinate mapping.

Expected result: each marker should appear in the corner matching
its label (TL=top-left, TR=top-right, BL=bottom-left, BR=bottom-right).
If they don't, the axis mapping needs adjustment.

Usage:
    python test_roi_corner_markers.py
    python test_roi_corner_markers.py --job "Overview"
"""

import argparse
import sys

parser = argparse.ArgumentParser(
    description="ROI Corner Marker Diagnostic")
parser.add_argument("--job", default=None,
                    help="Job name (default: currently selected)")
args = parser.parse_args()

# ── Import ──────────────────────────────────────────────────────────────

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from LasxApi import PYLICamApiConnector as lasx_api
import navigator_expert.driver as drv
from navigator_expert.driver.scanning_templates import (
    TEMPLATE_XML, apply_lrp_change, find_scanning_templates_dir,
)
from navigator_expert.driver.scanning_template_editors_roi import (
    lrp_enable_roi_scan, lrp_clear_rois, lrp_add_roi,
    lrp_verify_roi_count, lrp_verify_roi_scan,
    make_rectangle, argb_color, ROI_POLYGON,
)
from navigator_expert.driver.readers import get_job_settings
from navigator_expert.driver.utils import parse_tile_geometry

# ── Connect ─────────────────────────────────────────────────────────────

client = lasx_api.LasxApiClientPyModel
confirmed = client.Connect("PythonClient")
print(f"  Connected: {confirmed}")
if not confirmed:
    print("  ABORT: Cannot connect to LAS X.")
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
        print("  ABORT: no job selected. Use --job.")
        sys.exit(1)
    print(f"  Auto-detected job: '{job}'")

# ── Read FOV ────────────────────────────────────────────────────────────

settings = get_job_settings(client, job)
geo = parse_tile_geometry(settings)
fov_w_m = geo["tile_w_um"] * 1e-6  # metres
image_size = geo["pixels_x"]
ps = fov_w_m / image_size  # pixel size in metres
center = image_size / 2.0
marker_size = fov_w_m * 0.02  # small marker

print(f"  FOV: {geo['tile_w_um']:.1f} um, image: {image_size}x{image_size}")
print(f"  Pixel size: {ps * 1e6:.4f} um")

# ── Marker positions ────────────────────────────────────────────────────

offset = image_size * 0.3  # 30% from center → clearly in each quadrant
markers = {
    "TL": (center - offset, center - offset),
    "TR": (center + offset, center - offset),
    "BL": (center - offset, center + offset),
    "BR": (center + offset, center + offset),
}
colors = {
    "TL": argb_color(255, 0, 0),     # red
    "TR": argb_color(0, 255, 0),     # green
    "BL": argb_color(0, 0, 255),     # blue
    "BR": argb_color(255, 255, 0),   # yellow
}

print(f"\n  Placing markers (pixel coords):")
for name, (px, py) in markers.items():
    print(f"    {name}: pixel ({px:.0f}, {py:.0f})")

# ── Coordinate mapping under test ───────────────────────────────────────
# Change this mapping to test different axis conventions.
# Correct mapping (with EnableImageTransformation=false):
#   vx = (col - center) * ps   (positive X = right in display)
#   vy = (row - center) * ps   (positive Y = down in display)


def pixel_to_vertex(col, row):
    """Convert pixel (col, row) to ROI vertex (vx, vy) in metres."""
    vx = (col - center) * ps
    vy = (row - center) * ps
    return vx, vy


# ── Place markers ───────────────────────────────────────────────────────

def edit_fn(p):
    lrp_clear_rois(p, job)
    for name, (px, py) in markers.items():
        vx, vy = pixel_to_vertex(px, py)
        rect = make_rectangle(marker_size, marker_size, vx, vy)
        lrp_add_roi(p, job, ROI_POLYGON, rect,
                     name=name, color=colors[name])
    lrp_enable_roi_scan(p, True, job)


def verify_fn(p):
    return (lrp_verify_roi_count(p, 4, job) and
            lrp_verify_roi_scan(p, True, job))


result = apply_lrp_change(client, TEMPLATE_XML, edit_fn,
                           verify_fn=verify_fn)
if result and result["success"]:
    print(f"\n  Markers placed ({result['attempts']} attempt(s))")
else:
    print(f"\n  FAIL: {result}")
    sys.exit(1)

# ── Legend ───────────────────────────────────────────────────────────────

print(f"\n  Legend:")
print(f"    TL = RED      should be top-left")
print(f"    TR = GREEN    should be top-right")
print(f"    BL = BLUE     should be bottom-left")
print(f"    BR = YELLOW   should be bottom-right")
print(f"\n  If markers are in wrong corners, adjust pixel_to_vertex().")

"""
Galvo Navigation Integration Test
===================================
Tests move_xy_galvo, ROI coordinate helpers, pixel_to_absolute_um,
bbox_to_zoom, and mask_contour_to_roi against a live LAS X instance.

Usage:
    python test_galvo_nav_integration.py
    python test_galvo_nav_integration.py --job "Overview"
"""

import argparse
import math
import os
import sys
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(name)s: %(message)s",
)

parser = argparse.ArgumentParser(description="Galvo Navigation Integration Test")
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
    lrp_verify_roi_count,
    make_star, make_rectangle, um,
    ROI_POLYGON, COLOR_RED, COLOR_GREEN, COLOR_BLUE,
    roi_translation_to_pan, roi_to_absolute_um,
    absolute_um_to_roi_translation,
    pixel_to_absolute_um, bbox_to_zoom, mask_contour_to_roi,
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

# ── Test helpers ────────────────────────────────────────────────────────

passed = 0
failed = 0


def check(desc, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  \033[32m[PASS]\033[0m {desc}")
        passed += 1
    else:
        print(f"  \033[31m[FAIL]\033[0m {desc} {detail}")
        failed += 1


def save_and_parse():
    save_experiment(client, TEMPLATE_XML, tdir, timeout=5.0)
    return parse_lrp(lrp_path)


def read_pan(parsed):
    a = parsed["jobs"][job]["Master"]["attrs"]
    return float(a.get("PanFirstDim", 0)), float(a.get("PanSecondDim", 0))


# ── Setup: reset to clean state ────────────────────────────────────────

print(f"\n{'=' * 60}")
print(f"  Galvo Navigation Integration Test — job '{job}'")
print(f"{'=' * 60}")

print("\n  Setup: reset to zoom=1, pan=0, clear ROIs")


def reset(p):
    lrp_set_zoom(p, 1, job)
    lrp_set_pan(p, 0, 0, job)
    lrp_clear_rois(p, job)
    lrp_enable_roi_scan(p, False, job)


apply_lrp_change(client, TEMPLATE_XML, reset, confirm_delays=(2, 4, 6))
time.sleep(0.5)

stage = drv.get_xy(client)
print(f"  Stage: ({stage['x_um']:.1f}, {stage['y_um']:.1f})")

# ── Test 1: move_xy_galvo basic ─────────────────────────────────────────

print(f"\n  --- move_xy_galvo ---")

# Move 50 um right of stage center
target_x = stage["x_um"] + 50
target_y = stage["y_um"]
r = drv.move_xy_galvo(client, target_x, target_y, job_name=job)
check("move_xy_galvo returns success", r["success"])
check("pan_x is positive (right offset)", r["pan"][0] > 0,
      f"pan_x={r['pan'][0]}")
check("pan_y is ~zero", abs(r["pan"][1]) < 1e-6,
      f"pan_y={r['pan'][1]}")
check("offset_um matches", abs(r["offset_um"][0] - 50) < 0.1,
      f"offset_x={r['offset_um'][0]}")

# Verify pan was written to LRP
parsed = save_and_parse()
actual_pan = read_pan(parsed)
check("pan persisted in LRP",
      abs(actual_pan[0] - r["pan"][0]) < 1e-6,
      f"expected {r['pan'][0]}, got {actual_pan[0]}")

# ── Test 2: move_xy_galvo out of range ──────────────────────────────────

r_ool = drv.move_xy_galvo(client, stage["x_um"] + 1000, stage["y_um"],
                           job_name=job)
check("out-of-range correctly rejected", not r_ool["success"])
check("error message mentions range", "range" in r_ool["message"].lower(),
      f"msg={r_ool['message']}")

# ── Test 3: move_xy_galvo back to center ────────────────────────────────

r_center = drv.move_xy_galvo(client, stage["x_um"], stage["y_um"],
                              job_name=job)
check("move back to center succeeds", r_center["success"])
check("pan is ~zero after centering",
      abs(r_center["pan"][0]) < 1e-6 and abs(r_center["pan"][1]) < 1e-6)

# ── Test 4: ROI translation round-trip ──────────────────────────────────

print(f"\n  --- ROI Translation round-trip ---")

# Place a star at a known absolute position
star_x = stage["x_um"] + 30
star_y = stage["y_um"] - 20
tx_m, ty_m = absolute_um_to_roi_translation(star_x, star_y,
                                              stage["x_um"], stage["y_um"])

def add_star(p):
    lrp_clear_rois(p, job)
    verts = make_star(outer_radius=um(5), inner_radius=um(2))
    lrp_add_roi(p, job, ROI_POLYGON, verts,
                name="Test Star", color=COLOR_RED,
                translation=(tx_m, ty_m))

apply_lrp_change(client, TEMPLATE_XML, add_star, confirm_delays=(2, 4, 6))

# Read it back
parsed = save_and_parse()
rois = parsed["jobs"][job]["Master"].get("_ROIs", [])
check("star ROI saved", len(rois) == 1, f"count={len(rois)}")

if rois:
    t = rois[0].get("_Transformation", {})
    read_tx = float(t.get("TranslationX", 0))
    read_ty = float(t.get("TranslationY", 0))

    # Convert back to absolute
    abs_x, abs_y = roi_to_absolute_um(read_tx, read_ty,
                                       stage["x_um"], stage["y_um"])
    check("ROI absolute X matches",
          abs(abs_x - star_x) < 1,
          f"expected {star_x:.1f}, got {abs_x:.1f}")
    check("ROI absolute Y matches",
          abs(abs_y - star_y) < 1,
          f"expected {star_y:.1f}, got {abs_y:.1f}")

    # Verify pan from translation
    pan_x, pan_y = roi_translation_to_pan(read_tx, read_ty)
    expected_pan_x = 30 / 100_000
    expected_pan_y = -20 / 100_000
    check("roi_translation_to_pan X",
          abs(pan_x - expected_pan_x) < 1e-6,
          f"expected {expected_pan_x}, got {pan_x}")
    check("roi_translation_to_pan Y",
          abs(pan_y - expected_pan_y) < 1e-6,
          f"expected {expected_pan_y}, got {pan_y}")

# ── Test 5: Pan to ROI using translation ────────────────────────────────

print(f"\n  --- Pan to ROI from translation ---")

if rois:
    t = rois[0].get("_Transformation", {})
    pan_x, pan_y = roi_translation_to_pan(
        float(t.get("TranslationX", 0)),
        float(t.get("TranslationY", 0)),
    )

    def pan_to_roi(p):
        lrp_set_pan(p, pan_x, pan_y, job)

    apply_lrp_change(client, TEMPLATE_XML, pan_to_roi,
                     confirm_delays=(2, 4, 6))

    parsed = save_and_parse()
    actual_pan = read_pan(parsed)
    check("pan X matches roi_translation_to_pan",
          abs(actual_pan[0] - pan_x) < 1e-6,
          f"expected {pan_x:.6f}, got {actual_pan[0]:.6f}")
    check("pan Y matches roi_translation_to_pan",
          abs(actual_pan[1] - pan_y) < 1e-6,
          f"expected {pan_y:.6f}, got {actual_pan[1]:.6f}")

# ── Test 6: bbox_to_zoom ────────────────────────────────────────────────

print(f"\n  --- bbox_to_zoom ---")

check("bbox 30x20 -> zoom fits",
      1160 / bbox_to_zoom(30, 20) >= 30,
      f"zoom={bbox_to_zoom(30, 20)}")
check("bbox 1000x1000 -> zoom=1",
      bbox_to_zoom(1000, 1000) == 1)
check("bbox 5x5 -> zoom=48 (clamped)",
      bbox_to_zoom(5, 5) == 48)
check("bbox 0x0 -> zoom=48",
      bbox_to_zoom(0, 0) == 48)

# ── Test 7: pixel_to_absolute_um consistency ────────────────────────────

print(f"\n  --- pixel_to_absolute_um ---")

# Center pixel at zero pan should equal stage position
cx, cy = pixel_to_absolute_um(256, 256, stage["x_um"], stage["y_um"],
                               0, 0, zoom=1)
check("center pixel = stage position",
      abs(cx - stage["x_um"]) < 0.1 and abs(cy - stage["y_um"]) < 0.1)

# Symmetric: pixel 0 and 512 should be equidistant from center
x0, _ = pixel_to_absolute_um(0, 256, stage["x_um"], stage["y_um"],
                              0, 0, zoom=1)
x512, _ = pixel_to_absolute_um(512, 256, stage["x_um"], stage["y_um"],
                                0, 0, zoom=1)
offset0 = abs(x0 - stage["x_um"])
offset512 = abs(x512 - stage["x_um"])
check("pixel 0 and 512 equidistant from center",
      abs(offset0 - offset512) < 0.1,
      f"offset0={offset0:.1f}, offset512={offset512:.1f}")

# ── Test 8: mask_contour_to_roi ─────────────────────────────────────────

print(f"\n  --- mask_contour_to_roi ---")

# Create a square contour in pixel space
contour = [(200, 200), (300, 200), (300, 300), (200, 300)]
verts_m, (tx_m, ty_m) = mask_contour_to_roi(
    contour, stage["x_um"], stage["y_um"], 0, 0, zoom=8)

check("4 vertices returned", len(verts_m) == 4)

# Vertices should be centred
sum_x = sum(v[0] for v in verts_m)
sum_y = sum(v[1] for v in verts_m)
check("vertices centred (sum_x~0)", abs(sum_x) < 1e-12)
check("vertices centred (sum_y~0)", abs(sum_y) < 1e-12)

# Add as ROI and verify it persists
def add_mask_roi(p):
    lrp_clear_rois(p, job)
    lrp_add_roi(p, job, ROI_POLYGON, verts_m,
                name="Mask ROI", color=COLOR_GREEN,
                translation=(tx_m, ty_m))

apply_lrp_change(client, TEMPLATE_XML, add_mask_roi,
                 confirm_delays=(2, 4, 6))

parsed = save_and_parse()
rois = parsed["jobs"][job]["Master"].get("_ROIs", [])
check("mask ROI saved", len(rois) == 1)

if rois:
    roi_verts = rois[0].get("_Vertices", [])
    check("mask ROI has 4 vertices", len(roi_verts) == 4)

# ── Test 9: Full workflow — place star, read ROI, zoom+pan to it ────────

print(f"\n  --- Full workflow: place -> read -> zoom+pan ---")

star_abs_x = stage["x_um"] + 40
star_abs_y = stage["y_um"] - 30
tx_m, ty_m = absolute_um_to_roi_translation(
    star_abs_x, star_abs_y, stage["x_um"], stage["y_um"])
star_verts = make_star(outer_radius=um(8), inner_radius=um(3))


def place_star(p):
    lrp_clear_rois(p, job)
    lrp_enable_roi_scan(p, False, job)
    lrp_set_zoom(p, 1, job)
    lrp_set_pan(p, 0, 0, job)
    lrp_add_roi(p, job, ROI_POLYGON, star_verts,
                name="Workflow Star", color=COLOR_BLUE,
                translation=(tx_m, ty_m))


apply_lrp_change(client, TEMPLATE_XML, place_star, confirm_delays=(2, 4, 6))

# Read ROI back
parsed = save_and_parse()
rois = parsed["jobs"][job]["Master"].get("_ROIs", [])
check("workflow star saved", len(rois) == 1)

if rois:
    roi = rois[0]
    t = roi.get("_Transformation", {})
    rtx = float(t.get("TranslationX", 0))
    rty = float(t.get("TranslationY", 0))

    # Compute pan + zoom from ROI
    pan_x, pan_y = roi_translation_to_pan(rtx, rty)
    vs = roi.get("_Vertices", [])
    w = (max(v["X"] for v in vs) - min(v["X"] for v in vs)) * 1e6
    h = (max(v["Y"] for v in vs) - min(v["Y"] for v in vs)) * 1e6
    zoom = bbox_to_zoom(w, h)

    def zoom_to_roi(p):
        lrp_set_zoom(p, zoom, job)
        lrp_set_pan(p, pan_x, pan_y, job)

    apply_lrp_change(client, TEMPLATE_XML, zoom_to_roi,
                     confirm_delays=(2, 4, 6))

    parsed = save_and_parse()
    actual_pan = read_pan(parsed)
    actual_zoom = float(parsed["jobs"][job]["Master"]["attrs"].get("Zoom", 0))

    check("workflow zoom applied",
          abs(actual_zoom - zoom) < 1,
          f"expected {zoom}, got {actual_zoom:.1f}")
    check("workflow pan X applied",
          abs(actual_pan[0] - pan_x) < 1e-5,
          f"expected {pan_x:.6f}, got {actual_pan[0]:.6f}")
    check("workflow pan Y applied",
          abs(actual_pan[1] - pan_y) < 1e-5,
          f"expected {pan_y:.6f}, got {actual_pan[1]:.6f}")

# ── Cleanup ─────────────────────────────────────────────────────────────

print(f"\n  Cleanup: reset")
apply_lrp_change(client, TEMPLATE_XML, reset, confirm_delays=(2, 4, 6))

# ── Summary ─────────────────────────────────────────────────────────────

total = passed + failed
print(f"\n{'=' * 60}")
print(f"  Results: {passed}/{total} passed, {failed} failed")
print(f"{'=' * 60}")
sys.exit(1 if failed else 0)

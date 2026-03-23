"""
Cellpose Segmentation → Polygon ROI Loading Test
=================================================
Acquire (or load) an image, segment cells with Cellpose, extract
contours, and load them as polygon ROIs into LAS X.

Tests whether segmentation-derived polygon ROIs load correctly and
appear at the correct positions in LAS X.

Usage:
    python test_cellpose_roi.py                       # acquire + segment + load
    python test_cellpose_roi.py --image path.tif      # segment existing image
    python test_cellpose_roi.py --max-rois 5          # limit ROI count
    python test_cellpose_roi.py --diameter 30         # cellpose cell diameter
    python test_cellpose_roi.py --job "Overview"      # specify job
"""

import argparse
import math
import os
import sys
import time
import logging

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

parser = argparse.ArgumentParser(
    description="Cellpose Segmentation → Polygon ROI Loading Test")
parser.add_argument("--job", default=None,
                    help="Job name (default: currently selected)")
parser.add_argument("--image", default=None,
                    help="Path to existing image (skip acquisition)")
parser.add_argument("--max-rois", type=int, default=10,
                    help="Max number of ROIs to load (default: 10)")
parser.add_argument("--diameter", type=float, default=None,
                    help="Cellpose cell diameter in pixels (default: auto)")
parser.add_argument("--gpu", action="store_true",
                    help="Use GPU for Cellpose")
parser.add_argument("--channel", type=int, default=0,
                    help="Channel index for multi-file acquisitions (default: 0)")
parser.add_argument("--tolerance", type=float, default=2.0,
                    help="Contour simplification tolerance in pixels (default: 2.0)")
parser.add_argument("--min-area", type=int, default=50,
                    help="Min cell area in pixels to include (default: 50)")
parser.add_argument("--pause", type=float, default=3.0,
                    help="Pause after loading ROIs for visual check (default: 3.0)")
parser.add_argument("--no-roi-scan", action="store_true",
                    help="Don't enable ROI scan (overlay ROIs on full image)")
args = parser.parse_args()

# ── Imports ─────────────────────────────────────────────────────────────

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tifffile
from skimage.measure import find_contours, approximate_polygon, regionprops
from cellpose import models

from LasxApi import PYLICamApiConnector as lasx_api
import lasx as drv
from lasx.scanning_templates import (
    TEMPLATE_XML, apply_lrp_change, find_scanning_templates_dir,
    save_experiment,
)
from lasx.scanning_template_editors_roi import (
    lrp_enable_roi_scan, lrp_verify_roi_scan,
    lrp_clear_rois, lrp_add_roi,
    lrp_verify_roi_count,
    argb_color,
    ROI_POLYGON,
)
from lasx.scanning_template_parsers import parse_lrp
from lasx.readers import get_job_settings
from lasx.utils import parse_tile_geometry

print(f"  Driver version: {drv.__version__}")

# ── Check image export orientation ─────────────────────────────────────

lasx_settings = drv.get_lasx_settings()
orient = lasx_settings.get("image_orientation", {})
transform_on = orient.get("enable_transform", False)
orientation = orient.get("transformation", "TOPLEFT")
if transform_on and orientation != "TOPLEFT":
    print(f"  ABORT: ImageTransformation is '{orientation}' (need TOPLEFT).")
    print("  Change it in LAS X > Advanced Settings > "
          "Calibration Of Orientation.")
    sys.exit(1)

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

# Resolve job
if args.job:
    job = args.job
else:
    selected = drv.get_selected_job(client)
    job = selected.get("Name") if selected else None
    if not job:
        print("  ABORT: no job selected in LAS X. "
              "Select a job or use --job.")
        sys.exit(1)
    print(f"  Auto-detected job: '{job}'")

# ── Step 1: Read microscope state ──────────────────────────────────────

print(f"\n{'=' * 60}")
print(f"  Cellpose -> ROI Test -- job '{job}'")
print(f"{'=' * 60}")

print("\n  Step 0: Clearing previous ROIs and disabling ROI scan...")


def reset_fn(p):
    lrp_enable_roi_scan(p, False, job)
    lrp_clear_rois(p, job)


apply_lrp_change(client, TEMPLATE_XML, reset_fn,
                 verify_fn=lambda p: (lrp_verify_roi_scan(p, False, job) and
                                      lrp_verify_roi_count(p, 0, job)))
drv.refresh_display(client, job)
print("  ROI scan disabled, ROIs cleared.")

print("\n  Step 1: Reading microscope state...")

# Pixel size and image dimensions from API
settings = get_job_settings(client, job)
if not settings:
    print(f"  ABORT: cannot read job settings for '{job}'")
    sys.exit(1)
geo = parse_tile_geometry(settings)
fov_w_um = geo["tile_w_um"]
fov_h_um = geo["tile_h_um"]
print(f"  FOV: {fov_w_um:.1f} x {fov_h_um:.1f} um")
print(f"  API image size: {geo['pixels_x']} x {geo['pixels_y']} px")
print(f"  API pixel size: {geo['pixel_w_um']:.4f} um")

# Scan orientation from LRP
tdir = find_scanning_templates_dir()
lrp_path = os.path.join(tdir, TEMPLATE_XML.replace(".xml", ".lrp"))
save_experiment(client, TEMPLATE_XML, tdir, timeout=5.0)
parsed = parse_lrp(lrp_path)
master_attrs = parsed["jobs"][job]["Master"]["attrs"]

flip_x = master_attrs.get("FlipX", "0") == "1"
flip_y = master_attrs.get("FlipY", "0") == "1"
rotator_angle = float(master_attrs.get("RotatorAngle", 0))
rot_deg = rotator_angle * 360.0
print(f"  FlipX: {flip_x}, FlipY: {flip_y}, "
      f"RotatorAngle: {rotator_angle} ({rot_deg:.0f} deg)")

# ── Step 2: Get image ──────────────────────────────────────────────────

print("\n  Step 2: Getting image...")

if args.image:
    img_path = Path(args.image)
    if not img_path.exists():
        print(f"  ABORT: image not found: {img_path}")
        sys.exit(1)
    img = tifffile.imread(str(img_path))
    if img.ndim == 3:
        img = img[0]
    print(f"  Loaded: {img_path.name} ({img.shape}, {img.dtype})")
else:
    print("  Acquiring...")
    baseline = drv.read_relative_path(client)
    acquire_start = time.time()

    t0 = time.perf_counter()
    r = drv.acquire(client, job)
    elapsed = time.perf_counter() - t0

    if not (r and r["success"]):
        print(f"  ABORT: acquisition failed: {r}")
        sys.exit(1)
    print(f"  Acquired in {elapsed:.1f}s")

    lasx_settings = drv.get_lasx_settings()
    media_path = lasx_settings["export"]["media_path"]

    detection = drv.detect_new_files(client, baseline, media_path,
                                     acquire_start=acquire_start)
    if not detection["success"]:
        print(f"  ABORT: file detection failed: {detection.get('error')}")
        sys.exit(1)

    image_files = sorted(detection["image_files"])
    print(f"  Detected {len(image_files)} image file(s)")

    stable = drv.wait_all_stable(image_files, timeout=30)
    if not stable["success"]:
        print(f"  WARNING: files may not be stable")

    idx = min(args.channel, len(image_files) - 1)
    img_path = image_files[idx]
    img = tifffile.imread(str(img_path))
    if img.ndim == 3:
        img = img[0]
    print(f"  Read: {Path(img_path).name} ({img.shape}, {img.dtype})")

# Image geometry
actual_h, actual_w = img.shape[:2]
pixel_size_um = fov_w_um / actual_w
pixel_size_m = pixel_size_um * 1e-6
image_center = actual_w / 2.0
print(f"  Image: {actual_w}x{actual_h}, pixel_size: {pixel_size_um:.4f} um")

if actual_w != actual_h:
    print(f"  WARNING: non-square image, using width for center calc")

# ── Step 3: Segment with Cellpose ──────────────────────────────────────

print("\n  Step 3: Segmenting with Cellpose...")

t0 = time.perf_counter()
model = models.CellposeModel(gpu=args.gpu)
masks, flows, styles = model.eval(img, diameter=args.diameter)
elapsed = time.perf_counter() - t0

n_cells = int(masks.max())
print(f"  Found {n_cells} cell(s) in {elapsed:.1f}s")

if n_cells == 0:
    print("  ABORT: no cells found. Try adjusting --diameter.")
    sys.exit(1)

# ── Step 4: Extract contours ──────────────────────────────────────────

print("\n  Step 4: Extracting contours...")

props = regionprops(masks)
props_sorted = sorted(props, key=lambda p: p.area, reverse=True)
props_filtered = [p for p in props_sorted if p.area >= args.min_area]
print(f"  Cells after area filter (>={args.min_area} px): {len(props_filtered)}")

cells_to_process = props_filtered[:args.max_rois]
print(f"  Processing top {len(cells_to_process)} cell(s)")

roi_data = []

for prop in cells_to_process:
    label = prop.label
    binary = (masks == label).astype(float)
    contours = find_contours(binary, 0.5)

    if not contours:
        print(f"    Cell {label}: no contour found, skipping")
        continue

    contour = max(contours, key=len)
    n_orig = len(contour)
    contour_simple = approximate_polygon(contour, tolerance=args.tolerance)

    if len(contour_simple) < 4:
        print(f"    Cell {label}: only {len(contour_simple)} vertices "
              f"after simplification, skipping")
        continue

    # ── Pixel → ROI vertex coordinate conversion ──
    #
    # ROI vertices are in metres, origin at scan field centre.
    # Positive X = right in display, positive Y = down in display.
    # Requires EnableImageTransformation = false in LAS X settings.

    vertices_m = []
    for c in contour_simple:
        col, row = c[1], c[0]
        vx = (col - image_center) * pixel_size_m
        vy = (row - image_center) * pixel_size_m
        vertices_m.append((vx, vy))

    # Ensure closed polygon
    d = ((vertices_m[0][0] - vertices_m[-1][0]) ** 2 +
         (vertices_m[0][1] - vertices_m[-1][1]) ** 2) ** 0.5
    if d > pixel_size_m * 0.5:
        vertices_m.append(vertices_m[0])

    roi_data.append({
        "vertices_m": vertices_m,
        "translation_m": (0.0, 0.0),
        "n_orig": n_orig,
        "n_simple": len(vertices_m),
        "area": prop.area,
        "label": label,
    })
    print(f"    Cell {label}: area={prop.area} px, "
          f"contour {n_orig} -> {len(vertices_m)} vertices")

if not roi_data:
    print("  ABORT: no valid contours extracted")
    sys.exit(1)

print(f"\n  Total ROIs to load: {len(roi_data)}")

# ── Step 5: Load ROIs into LAS X ────────────────────────────────────────

print("\n  Step 5: Loading ROIs into LAS X...")

COLORS = [
    argb_color(255,   0,   0),    # red
    argb_color(  0, 255,   0),    # green
    argb_color(  0, 100, 255),    # blue
    argb_color(255, 255,   0),    # yellow
    argb_color(255,   0, 255),    # magenta
    argb_color(  0, 255, 255),    # cyan
    argb_color(255, 128,   0),    # orange
    argb_color(128,   0, 255),    # purple
    argb_color(255, 128, 128),    # pink
    argb_color(128, 255,   0),    # lime
]

n_rois = len(roi_data)
enable_roi_scan = not args.no_roi_scan


def edit_fn(p):
    """Clear existing ROIs and add cell-contour polygon ROIs."""
    lrp_clear_rois(p, job)
    for i, rd in enumerate(roi_data):
        color = COLORS[i % len(COLORS)]
        lrp_add_roi(
            p, job, ROI_POLYGON,
            rd["vertices_m"],
            translation=rd["translation_m"],
            color=color,
        )
    if enable_roi_scan:
        lrp_enable_roi_scan(p, True, job)


def verify_fn(p):
    ok = lrp_verify_roi_count(p, n_rois, job)
    if enable_roi_scan:
        ok = ok and lrp_verify_roi_scan(p, True, job)
    return ok


t0 = time.perf_counter()
result = apply_lrp_change(client, TEMPLATE_XML, edit_fn, verify_fn=verify_fn)
elapsed = time.perf_counter() - t0

if result and result["success"]:
    print(f"  \033[32m[PASS]\033[0m Loaded {n_rois} ROI(s) in {elapsed:.1f}s "
          f"({result['attempts']} attempt(s))")
else:
    print(f"  \033[31m[FAIL]\033[0m ROI loading failed ({elapsed:.1f}s)")
    print(f"  Result: {result}")
    sys.exit(1)

drv.refresh_display(client, job)
print(f"  Display refreshed")

# ── Step 6: Verify ──────────────────────────────────────────────────────

print(f"\n  Step 6: Verifying...")

save_experiment(client, TEMPLATE_XML, tdir, timeout=5.0)
parsed = parse_lrp(lrp_path)
rois = parsed["jobs"][job]["Master"].get("_ROIs", [])

print(f"  ROIs in LRP: {len(rois)}")
for i, roi in enumerate(rois):
    n_verts = len(roi.get("_Vertices", []))
    roi_type = roi.get("RoiType", "?")
    t = roi.get("_Transformation", {})
    tx = float(t.get("TranslationX", 0)) * 1e6
    ty = float(t.get("TranslationY", 0)) * 1e6
    print(f"    ROI {i+1}: type={roi_type}, {n_verts} vertices, "
          f"translation=({tx:.1f}, {ty:.1f}) um")

# ── Summary ──────────────────────────────────────────────────────────────

success = len(rois) == n_rois

print(f"\n{'=' * 60}")
if success:
    print(f"  \033[32mPASS\033[0m: {n_rois} cell ROI(s) loaded from "
          f"Cellpose segmentation")
    print(f"  Check LAS X -- ROIs should outline the "
          f"{n_rois} largest cells")
else:
    print(f"  \033[31mFAIL\033[0m: expected {n_rois} ROIs, "
          f"found {len(rois)}")
print(f"{'=' * 60}")

print(f"\n  Pausing {args.pause}s for visual inspection...")
time.sleep(args.pause)

# Cleanup prompt
print("\n  Cleanup: disable ROI scan + clear ROIs? [y/N] ",
      end="", flush=True)
try:
    choice = input().strip().lower()
except EOFError:
    choice = "n"

if choice == "y":
    def cleanup_fn(p):
        lrp_enable_roi_scan(p, False, job)
        lrp_clear_rois(p, job)

    apply_lrp_change(
        client, TEMPLATE_XML, cleanup_fn,
        verify_fn=lambda p: (lrp_verify_roi_scan(p, False, job) and
                             lrp_verify_roi_count(p, 0, job)),
    )
    drv.refresh_display(client, job)
    print("  Cleaned up.")
else:
    print("  ROIs left in place.")

sys.exit(0 if success else 1)

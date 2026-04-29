"""
Pan-zero calibration check via Cellpose + NCC registration.
===========================================================

Measures the galvo-pan targeting error at a test zoom by:

    1. Acquiring a low-zoom reference at pan=(0, 0).
    2. Segmenting with Cellpose and picking the cell closest to the
       image centre.
    3. Converting the cell's pixel centroid to an absolute stage XY via
       ``pixel_to_absolute_um``.
    4. Commanding ``move_xy_galvo`` to that XY and setting test zoom.
    5. Acquiring the test frame.
    6. Cropping a padded template from the reference around the cell,
       upsampling it to the test pixel size, and running NCC
       (``cv2.matchTemplate`` with ``TM_CCOEFF_NORMED``) inside the
       test frame.
    7. Peak location relative to the test image centre × test pixel size
       = actual landing offset in um. If the math were perfect and the
       scope were calibrated, this would be (0, 0). What we get IS the
       galvo calibration error at that zoom.

Usage:
    python test_pan_offset_cellpose.py
    python test_pan_offset_cellpose.py --ref-zoom 10 --test-zoom 20
    python test_pan_offset_cellpose.py --diameter 30 --no-gpu

Preconditions:
    - Job selected in LAS X (currently selected is used unless --job).
    - ImageTransformation = TOPLEFT in LAS X Advanced Settings.
    - AFC / autofocus off, no modal dialogs.
    - Cells visible at the ref zoom near the image centre.
"""

import argparse
import json
import math
import sys
import time
import logging
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
log = logging.getLogger("pan_offset_cellpose")

parser = argparse.ArgumentParser(description="Pan-zero calibration via Cellpose + NCC")
parser.add_argument("--job", default=None,
                    help="Job name (default: currently selected)")
parser.add_argument("--ref-zoom", type=float, default=10.0,
                    help="Reference zoom (default: 10)")
parser.add_argument("--test-zoom", type=float, default=20.0,
                    help="Test zoom (default: 20)")
parser.add_argument("--template-pad", type=float, default=2.5,
                    help="Template half-size = pad x bbox half (default: 2.5)")
parser.add_argument("--diameter", type=float, default=None,
                    help="Cellpose cell diameter in px (default: auto)")
parser.add_argument("--no-gpu", action="store_true",
                    help="Disable GPU for Cellpose")
parser.add_argument("--output-dir", type=Path, default=None,
                    help="Output dir (default: config/pan_offset/<timestamp>/)")
args = parser.parse_args()

# ── Imports ─────────────────────────────────────────────────────────────

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import tifffile
import cv2
from skimage.transform import rescale
from skimage.measure import regionprops
from cellpose import models
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from LasxApi import PYLICamApiConnector as lasx_api
import navigator_expert.driver as drv
from navigator_expert.driver.scanning_templates import TEMPLATE_XML, apply_lrp_change
from navigator_expert.driver.scanning_template_editors_scan import lrp_set_pan
from navigator_expert.driver.scanning_template_editors_roi import (
    lrp_enable_roi_scan, pixel_to_absolute_um,
)
from navigator_expert.driver.utils import parse_tile_geometry

# ── Output dir ──────────────────────────────────────────────────────────

out_dir = args.output_dir or (
    Path(__file__).resolve().parent.parent
    / "config" / "pan_offset" / datetime.now().strftime("%Y%m%d_%H%M%S")
)
out_dir.mkdir(parents=True, exist_ok=True)

# ── Connect ─────────────────────────────────────────────────────────────

client = lasx_api.LasxApiClientPyModel
if not client.Connect("PythonClient"):
    print("  ABORT: Cannot connect to LAS X.")
    sys.exit(1)
if not drv.ping(client):
    print("  ABORT: ping failed")
    sys.exit(1)

# TOPLEFT check
orient = (drv.get_lasx_settings() or {}).get("image_orientation", {})
if orient.get("enable_transform", False) and orient.get("transformation", "TOPLEFT") != "TOPLEFT":
    print(f"  ABORT: ImageTransformation is '{orient.get('transformation')}'; "
          f"set it to TOPLEFT.")
    sys.exit(1)

# Stage limits so move_xy_galvo does its limit-check rather than silently no-op
drv.set_stage_limits(
    x_min=1000, x_max=130000,
    y_min=1000, y_max=100000,
    z_galvo_min=-200, z_galvo_max=200,
    z_wide_min=0, z_wide_max=25000,
)

# Resolve job
job = args.job
if not job:
    sel = drv.get_selected_job(client)
    job = sel.get("Name") if sel else None
if not job:
    print("  ABORT: no job selected.")
    sys.exit(1)

print(f"  Driver version: {drv.__version__}")
print(f"  Job: {job}   ref_zoom={args.ref_zoom}   test_zoom={args.test_zoom}")
print(f"  Output: {out_dir}\n")


# ── Helpers ─────────────────────────────────────────────────────────────

def _acquire_one(tag):
    """Acquire, detect new files, return (image_array, path)."""
    baseline = drv.read_relative_path(client)
    t0 = time.time()
    r = drv.acquire(client, job)
    if not r or not r.get("success"):
        raise RuntimeError(f"{tag}: acquire failed: {r}")
    media = drv.get_lasx_settings()["export"]["media_path"]
    det = drv.detect_new_files(client, baseline, media, acquire_start=t0)
    if not det["success"]:
        raise RuntimeError(f"{tag}: file detection failed: {det.get('error')}")
    files = sorted(det["image_files"])
    if not files:
        raise RuntimeError(f"{tag}: no image files produced")
    drv.wait_all_stable(files, timeout=30)
    img = tifffile.imread(str(files[0]))
    if img.ndim == 3:
        img = img[0]
    return img, Path(files[0])


def _pick_central(masks, shape):
    props = regionprops(masks)
    if not props:
        return None
    h, w = shape[:2]
    cy, cx = h / 2.0, w / 2.0
    return min(props, key=lambda p: (p.centroid[0] - cy) ** 2
                                    + (p.centroid[1] - cx) ** 2)


# ── Step 1: Reference at pan=(0,0), ref_zoom ────────────────────────────

print("  Step 1: Reference (pan=0,0, zoom=%.1f)..." % args.ref_zoom)


def _reset(p):
    lrp_enable_roi_scan(p, False, job)
    lrp_set_pan(p, 0.0, 0.0, job)


apply_lrp_change(client, TEMPLATE_XML, _reset, confirm_delays=(2, 4, 6))
drv.set_zoom(client, job, args.ref_zoom)
idle = drv.check_idle(client, timeout=10.0)
if not idle or not idle.get("success"):
    print(f"  ABORT: not idle: {idle}")
    sys.exit(1)

stage = drv.get_xy(client)
if not stage:
    print("  ABORT: could not read XY.")
    sys.exit(1)
src_xy = (stage["x_um"], stage["y_um"])
log.info("stage XY_um = (%.3f, %.3f)", *src_xy)

ref_img, ref_path = _acquire_one("ref")
tifffile.imwrite(str(out_dir / "ref.tif"), ref_img)

ref_settings = drv.get_job_settings(client, job) or {}
ref_geo = parse_tile_geometry(ref_settings)
ref_ps = ref_geo["pixel_w_um"]
ref_n = ref_geo["pixels_x"]
log.info("ref image %s, pixel=%.4f um, size=%d px", ref_img.shape, ref_ps, ref_n)

# ── Step 2: Cellpose pick ───────────────────────────────────────────────

print("\n  Step 2: Cellpose...")
t0 = time.perf_counter()
model = models.CellposeModel(gpu=not args.no_gpu)
masks, _, _ = model.eval(ref_img, diameter=args.diameter)
log.info("Cellpose: %d cell(s) in %.1fs",
         int(masks.max()), time.perf_counter() - t0)

prop = _pick_central(masks, ref_img.shape)
if prop is None:
    print("  ABORT: no cells found; try --diameter or move sample.")
    sys.exit(1)

cy_px, cx_px = prop.centroid
min_r, min_c, max_r, max_c = prop.bbox
bbox_w_um = (max_c - min_c) * ref_ps
bbox_h_um = (max_r - min_r) * ref_ps
log.info("picked cell: centroid=(%.1f, %.1f) px  bbox=(%.1f x %.1f) um",
         cx_px, cy_px, bbox_w_um, bbox_h_um)

# ── Step 3: Predicted cell stage XY ─────────────────────────────────────

cell_x_um, cell_y_um = pixel_to_absolute_um(
    cx_px, cy_px,
    stage_x_um=src_xy[0], stage_y_um=src_xy[1],
    pan_x=0.0, pan_y=0.0,
    pixel_size_um=ref_ps, image_size=ref_n,
    # pan=(0,0) here so pan_scale_um is multiplied by zero, but pass the
    # resolved value anyway (required kwarg + principled documentation).
    pan_scale_um=drv.pan_scale_um_from_base_fov(
        drv.get_base_fov(client, job)[0] * 1e6),
)
log.info("predicted cell absolute XY = (%.3f, %.3f) um", cell_x_um, cell_y_um)

# Range check vs galvo pan
offset_um = (cell_x_um - src_xy[0], cell_y_um - src_xy[1])
mag = math.hypot(*offset_um)
if mag > 775:
    print(f"  ABORT: cell is {mag:.0f} um from stage centre, "
          f"exceeds galvo pan range (775 um).")
    sys.exit(1)

# ── Step 4: Zoom FIRST, then galvo-pan ─────────────────────────────────
# Zoom must be set before pan — changing zoom after a pan write causes
# LAS X to silently re-clamp pan (see move_xy_galvo docstring).

print("\n  Step 3: set_zoom(%.1f) then move_xy_galvo..." % args.test_zoom)
r_zoom = drv.set_zoom(client, job, args.test_zoom)
log.info("set_zoom: success=%s confirmed=%s",
         r_zoom.get("success"), r_zoom.get("confirmed"))

r_pan = drv.move_xy_galvo(client, cell_x_um, cell_y_um, unit="um",
                          job_name=job)
log.info("move_xy_galvo: success=%s pan=%s offset_um=%s",
         r_pan.get("success"), r_pan.get("pan"), r_pan.get("offset_um"))
if not r_pan.get("success"):
    print(f"  ABORT: move_xy_galvo failed: {r_pan.get('message')}")
    sys.exit(1)

idle = drv.check_idle(client, timeout=10.0)
if not idle or not idle.get("success"):
    print(f"  ABORT: not idle after pan+zoom: {idle}")
    sys.exit(1)

# ── Step 5: Acquire test frame ──────────────────────────────────────────

print("\n  Step 4: Acquire test frame...")
test_img, test_path = _acquire_one("test")
tifffile.imwrite(str(out_dir / "test.tif"), test_img)

test_settings = drv.get_job_settings(client, job) or {}
test_geo = parse_tile_geometry(test_settings)
test_ps = test_geo["pixel_w_um"]
test_n = test_geo["pixels_x"]
log.info("test image %s, pixel=%.4f um, size=%d px",
         test_img.shape, test_ps, test_n)

# ── Step 6: NCC registration ────────────────────────────────────────────

print("\n  Step 5: NCC registration...")

# Template: crop around cell in ref, padded
half_um = args.template_pad * max(bbox_w_um, bbox_h_um) / 2.0
half_px_ref = int(round(half_um / ref_ps))
rr0 = max(0, int(cy_px) - half_px_ref)
rr1 = min(ref_img.shape[0], int(cy_px) + half_px_ref + 1)
cc0 = max(0, int(cx_px) - half_px_ref)
cc1 = min(ref_img.shape[1], int(cx_px) + half_px_ref + 1)
template_ref = ref_img[rr0:rr1, cc0:cc1]
log.info("ref template: %s", template_ref.shape)

# Resample template to test pixel size (upsample by ref_ps/test_ps)
scale = ref_ps / test_ps
template = rescale(template_ref.astype(np.float32),
                   scale, order=1, preserve_range=True,
                   anti_aliasing=True)
log.info("resampled template: %s (scale=%.3f)", template.shape, scale)

# Normalise for cv2
template_cv = template.astype(np.float32)
test_cv = test_img.astype(np.float32)

if (template_cv.shape[0] >= test_cv.shape[0] or
        template_cv.shape[1] >= test_cv.shape[1]):
    print(f"  ABORT: resampled template {template_cv.shape} too big for "
          f"test frame {test_cv.shape}. Reduce --template-pad.")
    sys.exit(1)

ncc = cv2.matchTemplate(test_cv, template_cv, cv2.TM_CCOEFF_NORMED)
_, peak, _, peak_loc = cv2.minMaxLoc(ncc)  # (x, y) top-left of match

th, tw = template_cv.shape
cell_test_cx = peak_loc[0] + tw / 2.0
cell_test_cy = peak_loc[1] + th / 2.0

test_cx = test_img.shape[1] / 2.0
test_cy = test_img.shape[0] / 2.0

dx_px = cell_test_cx - test_cx
dy_px = cell_test_cy - test_cy
dx_um = dx_px * test_ps
dy_um = dy_px * test_ps
err_mag = math.hypot(dx_um, dy_um)

print(f"  NCC peak = {peak:.3f}")
print(f"  Offset  = ({dx_um:+.2f}, {dy_um:+.2f}) um   "
      f"magnitude = {err_mag:.2f} um")

# ── Step 7: Overlay ─────────────────────────────────────────────────────

fig, axes = plt.subplots(1, 2, figsize=(12, 6))

ax = axes[0]
ax.imshow(ref_img, cmap="gray")
ax.add_patch(Rectangle((cc0, rr0), cc1 - cc0, rr1 - rr0,
                       edgecolor="lime", facecolor="none", linewidth=1.0,
                       label="template"))
ax.plot(cx_px, cy_px, "r+", markersize=18, markeredgewidth=2)
ax.axvline(ref_img.shape[1] / 2, color="white", linewidth=0.4, alpha=0.3)
ax.axhline(ref_img.shape[0] / 2, color="white", linewidth=0.4, alpha=0.3)
ax.set_title(f"Ref (zoom {args.ref_zoom:g})")
ax.axis("off")

ax = axes[1]
ax.imshow(test_img, cmap="gray")
ax.add_patch(Rectangle(peak_loc, tw, th,
                       edgecolor="lime", facecolor="none", linewidth=1.5))
ax.plot(cell_test_cx, cell_test_cy, "r+", markersize=18, markeredgewidth=2,
        label="landed")
ax.plot(test_cx, test_cy, "c+", markersize=18, markeredgewidth=2,
        label="expected (centre)")
ax.axvline(test_cx, color="white", linewidth=0.4, alpha=0.3)
ax.axhline(test_cy, color="white", linewidth=0.4, alpha=0.3)
ax.set_title(f"Test (zoom {args.test_zoom:g}) - "
             f"offset ({dx_um:+.2f}, {dy_um:+.2f}) um  "
             f"|d|={err_mag:.2f} um   NCC={peak:.2f}")
ax.legend(loc="upper right", fontsize=8)
ax.axis("off")

fig.tight_layout()
fig.savefig(out_dir / "overlay.png", dpi=120)
plt.close(fig)

# ── Step 8: Summary ─────────────────────────────────────────────────────

summary = {
    "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
    "job": job,
    "ref_zoom": args.ref_zoom,
    "test_zoom": args.test_zoom,
    "stage_xy_um": list(src_xy),
    "ref_pixel_size_um": ref_ps,
    "test_pixel_size_um": test_ps,
    "picked_cell": {
        "centroid_px": [cy_px, cx_px],
        "bbox_um": [bbox_w_um, bbox_h_um],
        "area_px": int(prop.area),
    },
    "predicted_cell_xy_um": [cell_x_um, cell_y_um],
    "galvo_offset_requested_um": list(offset_um),
    "pan_applied": list(r_pan.get("pan") or (None, None)),
    "landing": {
        "offset_um": [dx_um, dy_um],
        "offset_magnitude_um": err_mag,
        "ncc_peak": float(peak),
    },
    "outputs": {
        "ref_tif": str(out_dir / "ref.tif"),
        "test_tif": str(out_dir / "test.tif"),
        "overlay_png": str(out_dir / "overlay.png"),
        "ref_lasx_tif": str(ref_path),
        "test_lasx_tif": str(test_path),
    },
}
with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
    json.dump(summary, f, indent=2, sort_keys=True)

print(f"\n  Outputs:")
print(f"    ref     -> {out_dir / 'ref.tif'}")
print(f"    test    -> {out_dir / 'test.tif'}")
print(f"    overlay -> {out_dir / 'overlay.png'}")
print(f"    summary -> {out_dir / 'summary.json'}")

# ── Restore (pan=0) ─────────────────────────────────────────────────────

def _restore(p):
    lrp_set_pan(p, 0.0, 0.0, job)


apply_lrp_change(client, TEMPLATE_XML, _restore, confirm_delays=(2, 4, 6))
drv.set_zoom(client, job, args.ref_zoom)
print(f"\n  Restored: pan=(0,0), zoom={args.ref_zoom:g}")

sys.exit(0)

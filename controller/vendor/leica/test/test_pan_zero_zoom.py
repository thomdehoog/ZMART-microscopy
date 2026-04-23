"""
Pan-zero offset diagnostic — pure zoom-in, no Cellpose, no pan.
================================================================

Stage is assumed centred on a feature (use LAS X centring buttons).
Acquires one frame at ``ref_zoom`` (wide) and one at ``test_zoom``
(narrow), both at ``pan = (0, 0)``. Registers the narrow frame
against the central patch of the wide frame. Any non-zero shift is
the galvo zero-pan error at the test zoom.

Usage:
    python test_pan_zero_zoom.py
    python test_pan_zero_zoom.py --ref-zoom 1 --test-zoom 10

Preconditions:
    - Job selected in LAS X.
    - Sample positioned so the currently visible centre has visible
      texture (any cell, any bright structure).
    - ImageTransformation = TOPLEFT.
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
log = logging.getLogger("pan_zero_zoom")

parser = argparse.ArgumentParser(description="Galvo zero-pan offset via zoom-in")
parser.add_argument("--job", default=None,
                    help="Job name (default: currently selected)")
parser.add_argument("--ref-zoom", type=float, default=1.0,
                    help="Reference zoom (default: 1)")
parser.add_argument("--test-zoom", type=float, default=10.0,
                    help="Test zoom (default: 10)")
parser.add_argument("--upsample", type=int, default=20,
                    help="Sub-pixel upsample factor for phase correlation "
                         "(default: 20 -> ~1/20 pixel precision)")
parser.add_argument("--output-dir", type=Path, default=None,
                    help="Output dir (default: config/pan_offset/<timestamp>/)")
args = parser.parse_args()

# ── Imports ─────────────────────────────────────────────────────────────

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import tifffile
from skimage.transform import rescale
from skimage.registration import phase_cross_correlation
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from LasxApi import PYLICamApiConnector as lasx_api
import lasx as drv
from lasx.scanning_templates import TEMPLATE_XML, apply_lrp_change
from lasx.scanning_template_editors_scan import lrp_set_pan
from lasx.scanning_template_editors_roi import lrp_enable_roi_scan
from lasx.utils import parse_tile_geometry

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

orient = (drv.get_lasx_settings() or {}).get("image_orientation", {})
if orient.get("enable_transform", False) and orient.get("transformation", "TOPLEFT") != "TOPLEFT":
    print(f"  ABORT: ImageTransformation is '{orient.get('transformation')}'; "
          f"set it to TOPLEFT.")
    sys.exit(1)

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


def _acquire_one(tag):
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
        raise RuntimeError(f"{tag}: no image files")
    drv.wait_all_stable(files, timeout=30)
    img = tifffile.imread(str(files[0]))
    if img.ndim == 3:
        img = img[0]
    return img, Path(files[0])


# ── Step 1: Ref at (pan=0, ref_zoom) ────────────────────────────────────

print(f"  Step 1: Reference (pan=0,0, zoom={args.ref_zoom:g})...")


def _reset(p):
    lrp_enable_roi_scan(p, False, job)
    lrp_set_pan(p, 0.0, 0.0, job)


apply_lrp_change(client, TEMPLATE_XML, _reset, confirm_delays=(2, 4, 6))
drv.set_zoom(client, job, args.ref_zoom)
idle = drv.check_idle(client, timeout=10.0)
if not idle or not idle.get("success"):
    print(f"  ABORT: not idle: {idle}")
    sys.exit(1)

ref_img, ref_path = _acquire_one("ref")
tifffile.imwrite(str(out_dir / "ref.tif"), ref_img)

ref_geo = parse_tile_geometry(drv.get_job_settings(client, job) or {})
ref_ps = ref_geo["pixel_w_um"]
log.info("ref image %s, pixel=%.4f um", ref_img.shape, ref_ps)

# ── Step 2: Test at (pan=0, test_zoom) ──────────────────────────────────

print(f"\n  Step 2: Test (pan=0,0, zoom={args.test_zoom:g})...")
drv.set_zoom(client, job, args.test_zoom)
idle = drv.check_idle(client, timeout=10.0)
if not idle or not idle.get("success"):
    print(f"  ABORT: not idle: {idle}")
    sys.exit(1)

test_img, test_path = _acquire_one("test")
tifffile.imwrite(str(out_dir / "test.tif"), test_img)

test_geo = parse_tile_geometry(drv.get_job_settings(client, job) or {})
test_ps = test_geo["pixel_w_um"]
log.info("test image %s, pixel=%.4f um", test_img.shape, test_ps)

# ── Step 3: Register ────────────────────────────────────────────────────

print("\n  Step 3: Register (phase correlation)...")

# Downsample test to ref pixel size so both are on the same physical scale.
scale = test_ps / ref_ps   # test has smaller px -> scale < 1 -> downsample
test_down = rescale(test_img.astype(np.float32), scale,
                    order=1, preserve_range=True, anti_aliasing=True)
log.info("downsampled test: %s (scale=%.3f)", test_down.shape, scale)

# Extract matching central patch of ref (same size as test_down).
rh, rw = ref_img.shape[:2]
th, tw = test_down.shape[:2]
r0 = (rh - th) // 2
c0 = (rw - tw) // 2
ref_patch = ref_img[r0:r0 + th, c0:c0 + tw].astype(np.float32)

shift, error, _ = phase_cross_correlation(
    ref_patch, test_down, upsample_factor=args.upsample,
)
# shift = (row, col) = ref_feature_pos - test_feature_pos.
# Positive shift[0] => the feature sits LOWER in ref than in test, which
# means test's FOV centre landed BELOW the ref centre. So:
#   dy_ref_px = +shift[0]  (image-y: positive = below)
#   dx_ref_px = +shift[1]  (image-x: positive = right)
dy_px_ref, dx_px_ref = shift[0], shift[1]
dy_um = dy_px_ref * ref_ps
dx_um = dx_px_ref * ref_ps
err_mag = math.hypot(dx_um, dy_um)

print(f"  Phase-correlation shift (ref px) = ({dx_px_ref:+.3f}, {dy_px_ref:+.3f})")
print(f"  Offset                          = ({dx_um:+.2f}, {dy_um:+.2f}) um")
print(f"  Magnitude                        = {err_mag:.2f} um")
print(f"  Registration error estimate      = {error:.3f}")

# ── Step 4: Overlay ─────────────────────────────────────────────────────

fig, axes = plt.subplots(1, 2, figsize=(12, 6))

# Ref panel with a rectangle showing where test FOV *should* be
ax = axes[0]
ax.imshow(ref_img, cmap="gray")
ax.add_patch(Rectangle((c0, r0), tw, th,
                       edgecolor="cyan", facecolor="none", linewidth=1.2,
                       label="expected test FOV"))
# And where it actually landed (shift applied, in ref px)
ax.add_patch(Rectangle((c0 + dx_px_ref, r0 + dy_px_ref), tw, th,
                       edgecolor="lime", facecolor="none", linewidth=1.2,
                       linestyle="--", label="actual test FOV"))
ax.axvline(rw / 2, color="white", linewidth=0.4, alpha=0.3)
ax.axhline(rh / 2, color="white", linewidth=0.4, alpha=0.3)
ax.set_title(f"Ref (zoom {args.ref_zoom:g})  pixel={ref_ps:.3f} um")
ax.legend(loc="upper right", fontsize=8)
ax.axis("off")

ax = axes[1]
ax.imshow(test_img, cmap="gray")
th2, tw2 = test_img.shape[:2]
ax.plot(tw2 / 2, th2 / 2, "c+", markersize=18, markeredgewidth=2,
        label="image centre")
ax.axvline(tw2 / 2, color="white", linewidth=0.4, alpha=0.3)
ax.axhline(th2 / 2, color="white", linewidth=0.4, alpha=0.3)
ax.set_title(f"Test (zoom {args.test_zoom:g})  pixel={test_ps:.3f} um\n"
             f"offset ({dx_um:+.2f}, {dy_um:+.2f}) um  |d|={err_mag:.2f} um")
ax.legend(loc="upper right", fontsize=8)
ax.axis("off")

fig.tight_layout()
fig.savefig(out_dir / "overlay.png", dpi=120)
plt.close(fig)

# ── Step 5: Summary ─────────────────────────────────────────────────────

summary = {
    "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
    "job": job,
    "ref_zoom": args.ref_zoom,
    "test_zoom": args.test_zoom,
    "ref_pixel_size_um": ref_ps,
    "test_pixel_size_um": test_ps,
    "shift_px_ref_scale": [float(dx_px_ref), float(dy_px_ref)],
    "offset_um": [float(dx_um), float(dy_um)],
    "offset_magnitude_um": float(err_mag),
    "phase_correlation_error": float(error),
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

# ── Restore ─────────────────────────────────────────────────────────────

drv.set_zoom(client, job, args.ref_zoom)
print(f"\n  Restored: zoom={args.ref_zoom:g} (pan already 0)")

sys.exit(0)

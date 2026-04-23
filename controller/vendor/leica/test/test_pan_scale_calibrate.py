"""
Measure PAN_SCALE for the current objective — no ROI required.
==============================================================

Commands a known pan and measures the resulting image shift via
phase-correlation against a pan=(0,0) reference. The ratio
``measured_shift_um / commanded_pan`` is the objective's PAN_SCALE.

Run once per objective (hypothesis: PAN_SCALE ∝ base_FOV, with
ratio PAN_SCALE / base_FOV ≈ 86.2).

Usage:
    python test_pan_scale_calibrate.py
    python test_pan_scale_calibrate.py --zoom 2 --pan-probe 0.0005
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
log = logging.getLogger("pan_scale_calibrate")

parser = argparse.ArgumentParser(description="Measure PAN_SCALE")
parser.add_argument("--job", default=None,
                    help="Job (default: currently selected)")
parser.add_argument("--zoom", type=float, default=2.0,
                    help="Zoom for all acquisitions (default: 2)")
parser.add_argument("--pan-probe", type=float, default=0.0005,
                    help="Pan value to apply for the probe (default: 0.0005)")
parser.add_argument("--upsample", type=int, default=20,
                    help="Phase-correlation subpixel factor (default: 20)")
parser.add_argument("--output-dir", type=Path, default=None)
args = parser.parse_args()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import tifffile
from skimage.registration import phase_cross_correlation
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from LasxApi import PYLICamApiConnector as lasx_api
import lasx as drv
from lasx.scanning_templates import TEMPLATE_XML, apply_lrp_change
from lasx.scanning_template_editors_scan import lrp_set_pan
from lasx.scanning_template_editors_roi import lrp_enable_roi_scan
from lasx.utils import parse_tile_geometry

out_dir = args.output_dir or (
    Path(__file__).resolve().parent.parent
    / "config" / "pan_scale" / datetime.now().strftime("%Y%m%d_%H%M%S")
)
out_dir.mkdir(parents=True, exist_ok=True)

client = lasx_api.LasxApiClientPyModel
if not client.Connect("PythonClient"):
    print("  ABORT: Cannot connect to LAS X."); sys.exit(1)
if not drv.ping(client):
    print("  ABORT: ping failed"); sys.exit(1)

orient = (drv.get_lasx_settings() or {}).get("image_orientation", {})
if orient.get("enable_transform", False) and orient.get("transformation", "TOPLEFT") != "TOPLEFT":
    print(f"  ABORT: ImageTransformation is '{orient.get('transformation')}'.")
    sys.exit(1)

job = args.job
if not job:
    sel = drv.get_selected_job(client)
    job = sel.get("Name") if sel else None
if not job:
    print("  ABORT: no job selected."); sys.exit(1)

base_fov_m = drv.get_base_fov(client, job)
if not base_fov_m:
    print("  ABORT: could not read base FOV."); sys.exit(1)
base_fov_um = base_fov_m[0] * 1e6

print(f"  Driver version: {drv.__version__}")
print(f"  Job: {job}  zoom={args.zoom:g}  pan-probe={args.pan_probe}")
print(f"  Base FOV @ zoom 1: {base_fov_um:.1f} um")
print(f"  Output: {out_dir}\n")


def _set_pan_and_zoom(px, py):
    def fn(p):
        lrp_enable_roi_scan(p, False, job)
        lrp_set_pan(p, px, py, job)
    apply_lrp_change(client, TEMPLATE_XML, fn, confirm_delays=(2, 4, 6))
    drv.set_zoom(client, job, args.zoom)
    idle = drv.check_idle(client, timeout=10.0)
    if not idle or not idle.get("success"):
        raise RuntimeError(f"not idle: {idle}")


def _acquire(tag):
    baseline = drv.read_relative_path(client)
    t0 = time.time()
    r = drv.acquire(client, job)
    if not r or not r.get("success"):
        raise RuntimeError(f"{tag}: acquire failed: {r}")
    media = drv.get_lasx_settings()["export"]["media_path"]
    det = drv.detect_new_files(client, baseline, media, acquire_start=t0)
    if not det["success"]:
        raise RuntimeError(f"{tag}: file detection failed")
    files = sorted(det["image_files"])
    drv.wait_all_stable(files, timeout=30)
    img = tifffile.imread(str(files[0]))
    if img.ndim == 3:
        img = img[0]
    return img


# ── Reference at pan = (0, 0) ──────────────────────────────────────────

print(f"  Step 1: Reference (pan=0, zoom={args.zoom:g})...")
_set_pan_and_zoom(0.0, 0.0)
ref_img = _acquire("ref")
tifffile.imwrite(str(out_dir / "ref.tif"), ref_img)

geo = parse_tile_geometry(drv.get_job_settings(client, job) or {})
ps = geo["pixel_w_um"]
log.info("ref: %s, pixel=%.4f um", ref_img.shape, ps)


def _shift_um(test_img):
    """Return (dx_um, dy_um) = where test landed relative to ref, image frame."""
    shift, err, _ = phase_cross_correlation(
        ref_img.astype(np.float32), test_img.astype(np.float32),
        upsample_factor=args.upsample,
    )
    # shift[0]=row, shift[1]=col; positive shift => test below/right of ref
    dy_um = float(shift[0]) * ps
    dx_um = float(shift[1]) * ps
    return dx_um, dy_um, float(err)


# ── Probe 1: pan_x only ────────────────────────────────────────────────

print(f"\n  Step 2: Pan probe X (pan=({args.pan_probe}, 0))...")
_set_pan_and_zoom(args.pan_probe, 0.0)
x_img = _acquire("probe_x")
tifffile.imwrite(str(out_dir / "probe_x.tif"), x_img)
dxx_um, dxy_um, x_err = _shift_um(x_img)
log.info("probe X shift (image frame): dx=%.3f dy=%.3f um (err=%.3f)",
         dxx_um, dxy_um, x_err)

# ── Probe 2: pan_y only ────────────────────────────────────────────────

print(f"\n  Step 3: Pan probe Y (pan=(0, {args.pan_probe}))...")
_set_pan_and_zoom(0.0, args.pan_probe)
y_img = _acquire("probe_y")
tifffile.imwrite(str(out_dir / "probe_y.tif"), y_img)
dyx_um, dyy_um, y_err = _shift_um(y_img)
log.info("probe Y shift (image frame): dx=%.3f dy=%.3f um (err=%.3f)",
         dyx_um, dyy_um, y_err)

# ── Derive PAN_SCALE ───────────────────────────────────────────────────

# shift_um = pan × PAN_SCALE.  Solve for PAN_SCALE on the dominant axis.
pan_scale_x = dxx_um / args.pan_probe if args.pan_probe else float("nan")
pan_scale_y = dyy_um / args.pan_probe if args.pan_probe else float("nan")

# Average magnitude (sign of shift depends on how the galvo and image axes line up)
pan_scale_avg = (abs(pan_scale_x) + abs(pan_scale_y)) / 2.0

ratio_to_fov = pan_scale_avg / base_fov_um if base_fov_um else float("nan")

print()
print(f"  -- Results ------------------------------------------------")
print(f"  Pan probe value:    {args.pan_probe:+.6f}")
print(f"  Image shift on +X pan: dx={dxx_um:+.3f} um, dy={dxy_um:+.3f} um")
print(f"  Image shift on +Y pan: dx={dyx_um:+.3f} um, dy={dyy_um:+.3f} um")
print()
print(f"  PAN_SCALE (from X pan): {pan_scale_x:+.1f} um/unit")
print(f"  PAN_SCALE (from Y pan): {pan_scale_y:+.1f} um/unit")
print(f"  PAN_SCALE (avg |x|,|y|): {pan_scale_avg:.1f} um/unit")
print()
print(f"  Base FOV @ zoom 1:  {base_fov_um:.1f} um")
print(f"  PAN_SCALE / base_FOV = {ratio_to_fov:.2f}  (hypothesis: ~86.2)")

# ── Overlay ────────────────────────────────────────────────────────────

fig, axes = plt.subplots(1, 3, figsize=(15, 5))
for ax, img, title in zip(axes, [ref_img, x_img, y_img],
                          ["ref (pan 0)", f"probe X ({args.pan_probe:+.4f}, 0)",
                           f"probe Y (0, {args.pan_probe:+.4f})"]):
    ax.imshow(img, cmap="gray")
    h, w = img.shape[:2]
    ax.axvline(w / 2, color="white", linewidth=0.4, alpha=0.3)
    ax.axhline(h / 2, color="white", linewidth=0.4, alpha=0.3)
    ax.set_title(title); ax.axis("off")
fig.tight_layout()
fig.savefig(out_dir / "overlay.png", dpi=120)
plt.close(fig)

# ── Summary ────────────────────────────────────────────────────────────

summary = {
    "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
    "job": job,
    "zoom": args.zoom,
    "pan_probe": args.pan_probe,
    "pixel_size_um": float(ps),
    "base_fov_um": float(base_fov_um),
    "probe_x_shift_um": [float(dxx_um), float(dxy_um)],
    "probe_y_shift_um": [float(dyx_um), float(dyy_um)],
    "pan_scale_x": float(pan_scale_x),
    "pan_scale_y": float(pan_scale_y),
    "pan_scale_avg_abs": float(pan_scale_avg),
    "pan_scale_over_base_fov": float(ratio_to_fov),
}
with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
    json.dump(summary, f, indent=2, sort_keys=True)

print(f"\n  Outputs at {out_dir}")

# Restore pan=0
_set_pan_and_zoom(0.0, 0.0)
print(f"  Restored: pan=(0,0), zoom={args.zoom:g}")
sys.exit(0)

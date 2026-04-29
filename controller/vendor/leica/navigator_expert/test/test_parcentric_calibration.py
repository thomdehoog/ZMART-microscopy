"""
Parcentric + Parfocal Calibration (Self-Contained)
=====================================================
Complete calibration between objectives. Measures XY (parcentric)
and Z (parfocal) offsets, determines sign convention empirically,
and validates everything — no hardcoded values or prior calibration.

Workflow:
  Phase 1 — Sign convention (ref objective, before any target switch)
    1. Single slice at ref Z=0 → sign-test reference image
    2. Move stage +sign-move um in X → acquire displaced image
    3. Register NCC → measured shift
    4. Test 4 combos (+X+Y, +X-Y, -X+Y, -X-Y): apply each correction,
       acquire single slice, measure residual
    5. Winner = sign convention (property of stage/image axes, same for all targets)

  Phase 2 — Z-stacks (fast, no accumulation)
    6. Z-stack on ref → Brenner peak → ref focus position
    7. Z-stack on target → Brenner peak → target focus position → dZ
    8. Z-shifted verification stack → confirm Brenner peaks match

  Phase 3 — High-quality focus slices (8x line accumulation)
    9. Single slice at ref focus Z → high-SNR reference image
   10. Single slice at target focus Z (corrected) → high-SNR target
   11. OpenCV NCC → precise XY shift → apply Phase 1 sign convention

Methods:
  XY: OpenCV NCC (TM_CCOEFF_NORMED) — fast, reliable, quality metric
  Z:  Brenner gradient — matches Leica's contrast-based autofocus

Usage:
    python test_parcentric_calibration.py --ref-slot 1 --target-slot 2
    python test_parcentric_calibration.py --ref-slot 1 --target-slot 2 0
    python test_parcentric_calibration.py --ref-slot 1 --target-slot 2 --z-range 40
"""

import argparse
import json
import os
import sys
import time
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

parser = argparse.ArgumentParser(description="Parcentric + parfocal calibration")
parser.add_argument("--ref-slot", type=int, required=True,
                    help="Reference objective slot (e.g. 1 for 10x)")
parser.add_argument("--target-slot", type=int, nargs="+", required=True,
                    help="Target objective slot(s) (e.g. 2 or 2 0)")
parser.add_argument("--ref-zoom", type=float, default=10,
                    help="Reference zoom level (default: 10)")
parser.add_argument("--z-range", type=float, default=15,
                    help="Z-stack half-range in um (default: 15 = +/-15)")
parser.add_argument("--z-step", type=float, default=1.0,
                    help="Z-stack step size in um (default: 1.0)")
parser.add_argument("--settle", type=float, default=0,
                    help="Extra settle time per target after switch (s)")
parser.add_argument("--job", default="Overview",
                    help="LAS X job name (default: Overview)")
parser.add_argument("--sign-move", type=float, default=20.0,
                    help="Stage displacement in X for sign convention test in um (default: 20)")
parser.add_argument("--output", default=None)
args = parser.parse_args()

# ── Imports ──────────────────────────────────────────────────────────────

import numpy as np
import tifffile
import cv2

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from LasxApi import PYLICamApiConnector as lasx_api
import navigator_expert.driver as drv
from navigator_expert.driver.scanning_templates import TEMPLATE_XML, apply_lrp_change
from navigator_expert.driver.scanning_template_editors_scan import lrp_set_pan
from navigator_expert.driver.scanning_template_editors_roi import lrp_enable_roi_scan
from navigator_expert.driver.scanning_template_editors_z import (
    lrp_set_z_stack_active, lrp_set_z_use_mode, lrp_set_sections,
)
from navigator_expert.driver.scanning_template_editors_focus import lrp_set_stack_calculation_mode
from navigator_expert.driver.readers import get_job_settings, get_lasx_settings
from navigator_expert.driver.scanning_templates import save_and_read_lrp
from navigator_expert.driver.scanning_template_parsers import get_master_attrs
from navigator_expert.driver.utils import parse_tile_geometry
from navigator_expert.driver.prechecks import check_idle

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ── Connect ──────────────────────────────────────────────────────────────

client = lasx_api.LasxApiClientPyModel
confirmed = client.Connect("PythonClient")
if not confirmed:
    print("  ABORT: Cannot connect to LAS X.")
    sys.exit(1)
assert drv.ping(client), "ping failed"

job = args.job
drv.select_job(client, job)
time.sleep(1)

current_job = drv.get_selected_job(client).get("Name", "")
if current_job != job:
    print(f"  ABORT: Expected '{job}', got '{current_job}'.")
    sys.exit(1)

hw = drv.get_hardware_info(client)
if not hw:
    print("  ABORT: cannot read hardware info")
    sys.exit(1)
print(f"  Job: {job}")

drv.set_stage_limits(
    x_min=1000, x_max=130000,
    y_min=1000, y_max=100000,
    z_galvo_min=-200, z_galvo_max=200,
    z_wide_min=0, z_wide_max=25000,
)

sections = int(2 * args.z_range / args.z_step) + 1

# ── Objective lookup ─────────────────────────────────────────────────────

objs_by_slot = {}
for o in hw.get("Microscope", {}).get("objectives", []):
    if o.get("objectiveNumber", 0) != 0:
        objs_by_slot[o["slotIndex"]] = o


def obj_info(slot):
    o = objs_by_slot.get(slot)
    if not o:
        print(f"  ABORT: no objective in slot {slot}")
        print(f"  Available: {list(objs_by_slot.keys())}")
        sys.exit(1)
    mag = o["magnification"]
    na = o["numericalAperture"]
    imm = o.get("immersion", "").strip()
    name = o.get("name", "").strip()
    label = f"slot{slot}_{mag:.0f}x_{na}NA_{imm}"
    return label, name, mag


ref_label, ref_name, ref_mag = obj_info(args.ref_slot)
targets = {}
for ts in args.target_slot:
    tl, tn, tm = obj_info(ts)
    tz = args.ref_zoom * ref_mag / tm
    targets[ts] = {"label": tl, "name": tn, "mag": tm, "zoom": tz}

print(f"  Reference: {ref_name} ({ref_label}) @ zoom {args.ref_zoom}")
for ts, ti in targets.items():
    print(f"  Target:    {ti['name']} ({ti['label']}) @ zoom {ti['zoom']:.2f}")
print(f"  Z-stack: +/-{args.z_range} um, {args.z_step} um step, {sections} sections")

# ── Output ───────────────────────────────────────────────────────────────

_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
_default_out = os.path.join(
    str(Path(__file__).resolve().parent.parent),
    "config", "alignment", f"calib_{_ts}")
out_dir = args.output or _default_out
os.makedirs(out_dir, exist_ok=True)
print(f"  Output: {out_dir}")

# ── Save original Z settings ─────────────────────────────────────────

parsed_orig = save_and_read_lrp(client)
orig_attrs = get_master_attrs(parsed_orig, job)
orig_z = {k: orig_attrs.get(k) for k in
           ("ZUseMode", "Sections", "Begin", "End",
            "StackCalculationMode", "ZStackActive")}

# ── Helpers ──────────────────────────────────────────────────────────────


def reset_pan_roi(p):
    lrp_set_pan(p, 0, 0, job)
    lrp_enable_roi_scan(p, False, job)


def setup_objective(slot, zoom):
    label, name, mag = obj_info(slot)
    print(f"  Switching to {name} (slot {slot})...")
    r = drv.set_objective(client, job, hw, name=name)
    if not r or not r.get("success"):
        print(f"  ABORT: objective switch failed: {r}")
        sys.exit(1)
    time.sleep(5)
    for attempt in range(3):
        drv.select_job(client, job)
        time.sleep(2)
        current = drv.get_selected_job(client).get("Name", "")
        if current == job:
            break
        print(f"  Job is '{current}', retrying... ({attempt+1}/3)")
        time.sleep(3)
    else:
        cur = drv.get_selected_job(client).get("Name", "")
        if cur != job:
            print(f"  ABORT: Cannot select '{job}' (stuck on '{cur}')")
            sys.exit(1)
    apply_lrp_change(client, TEMPLATE_XML, reset_pan_roi,
                     confirm_delays=(2, 4, 6))
    drv.set_zoom(client, job, zoom)
    time.sleep(1)
    drv.select_job(client, job)
    time.sleep(1)


def configure_z_stack(begin_um=None, end_um=None):
    """Configure Z-stack. If begin/end not given, uses +/-z_range."""
    b = begin_um if begin_um is not None else args.z_range
    e = end_um if end_um is not None else -args.z_range
    def _setup(p):
        lrp_set_z_stack_active(p, False, job)
        lrp_set_z_use_mode(p, "z-galvo", job)
        lrp_set_stack_calculation_mode(p, 1, job)
        lrp_set_sections(p, sections, job)
        lrp_set_z_stack_active(p, True, job)
    apply_lrp_change(client, TEMPLATE_XML, _setup, confirm_delays=(2, 4, 6))
    drv.set_z_stack_definition(client, job, begin_um=b, end_um=e)
    drv.set_z_stack_step_size(client, job, args.z_step)


def disable_z_stack():
    """Disable Z-stack for single-slice acquisition."""
    def _disable(p):
        lrp_set_z_stack_active(p, False, job)
        lrp_set_sections(p, 1, job)
    apply_lrp_change(client, TEMPLATE_XML, _disable, confirm_delays=(2, 4, 6))


def acquire_stack():
    """Acquire Z-stack, return (Z, Y, X) array."""
    idle = check_idle(client, timeout=30)
    if not idle["success"]:
        print("  WARNING: scanner not idle")
    drv.select_job(client, job)
    time.sleep(1)
    baseline = drv.read_relative_path(client)
    t0 = time.time()
    r = drv.acquire(client, job)
    elapsed = time.time() - t0
    if not r or not r["success"]:
        print(f"  Acquire failed: {r}")
        return None
    print(f"  Acquired in {elapsed:.1f}s")
    media = get_lasx_settings()["export"]["media_path"]
    det = drv.detect_new_files(client, baseline, media, acquire_start=t0)
    if not det["success"]:
        print(f"  File detection failed: {det.get('error')}")
        return None
    image_files = sorted(det["image_files"])
    print(f"  Found {len(image_files)} file(s)")
    if len(image_files) == 1:
        stack = tifffile.imread(str(image_files[0]))
        if stack.ndim == 2:
            stack = stack[np.newaxis, ...]
    else:
        slices = [tifffile.imread(str(f)) for f in image_files]
        slices = [s[0] if s.ndim == 3 else s for s in slices]
        stack = np.array(slices)
    return stack


def acquire_single():
    """Acquire single 2D image."""
    idle = check_idle(client, timeout=30)
    if not idle["success"]:
        print("  WARNING: scanner not idle")
    baseline = drv.read_relative_path(client)
    t0 = time.time()
    r = drv.acquire(client, job)
    if not r or not r["success"]:
        print(f"  Acquire failed: {r}")
        return None
    media = get_lasx_settings()["export"]["media_path"]
    det = drv.detect_new_files(client, baseline, media, acquire_start=t0)
    if not det["success"]:
        return None
    img = tifffile.imread(str(sorted(det["image_files"])[0]))
    if img.ndim == 3:
        img = img[0]
    return img


# ── Registration ─────────────────────────────────────────────────────────


def to_uint8(img):
    f = img.astype(np.float64)
    return (f / (f.max() or 1) * 255).astype(np.uint8)


def register_ncc(ref, tgt, pixel_um):
    """OpenCV NCC. Returns (dx_um, dy_um, quality)."""
    ref8 = to_uint8(ref)
    tgt8 = to_uint8(tgt)
    h, w = tgt8.shape
    margin = h // 4
    template = tgt8[margin:h-margin, margin:w-margin]
    result = cv2.matchTemplate(ref8, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    dx_px = max_loc[0] + template.shape[1] / 2 - w / 2
    dy_px = max_loc[1] + template.shape[0] / 2 - h / 2
    return dx_px * pixel_um, dy_px * pixel_um, float(max_val)


def brenner_gradient(img):
    """Brenner focus metric."""
    f = img.astype(np.float64)
    dx = f[:, 2:] - f[:, :-2]
    return (dx**2).mean()


def subpixel_peak(scores, peak):
    if peak <= 0 or peak >= len(scores) - 1:
        return float(peak)
    y0, y1, y2 = scores[peak-1], scores[peak], scores[peak+1]
    denom = 2 * (2*y1 - y0 - y2)
    if abs(denom) < 1e-10:
        return float(peak)
    return peak + (y0 - y2) / denom


def measure_brenner(stack, z_step):
    """Find best-focus Z using Brenner gradient. Returns dict."""
    scores = [brenner_gradient(stack[i]) for i in range(stack.shape[0])]
    peak = int(np.argmax(scores))
    peak_sub = subpixel_peak(scores, peak)
    return {"peak_slice": peak, "peak_sub": peak_sub,
            "peak_um": peak_sub * z_step, "scores": scores}


def make_overlay(a, b):
    an = a.astype(np.float64) / (a.max() or 1)
    bn = b.astype(np.float64) / (b.max() or 1)
    ov = np.zeros((*a.shape, 3))
    ov[..., 1] = an
    ov[..., 0] = bn
    ov[..., 2] = bn
    return np.clip(ov, 0, 1)


def hide_ticks(ax):
    ax.set_xticks([]); ax.set_yticks([])


# ═════════════════════════════════════════════════════════════════════════
#  PHASE 1: Sign convention (ref objective, before any target switch)
# ═════════════════════════════════════════════════════════════════════════

print(f"\n{'=' * 60}")
print(f"  PHASE 1: Sign convention ({args.sign_move:.0f} um test move)")
print(f"{'=' * 60}")

setup_objective(args.ref_slot, args.ref_zoom)
home = drv.get_xy(client)
settings = get_job_settings(client, job)
geo = parse_tile_geometry(settings)
ref_pixel = geo["pixel_w_um"]
image_size = geo["pixels_x"]
fov_um = ref_pixel * image_size
print(f"  Home: ({home['x_um']:.1f}, {home['y_um']:.1f})")
print(f"  Pixel: {ref_pixel:.4f} um | FOV: {fov_um:.1f} um")

disable_z_stack()
drv.set_z_stack_definition(client, job, begin_um=0, end_um=0)

print(f"  Acquiring sign-test reference image...")
p1_sign_ref = acquire_single()
if p1_sign_ref is None:
    print("  ABORT: sign-test reference acquire failed")
    sys.exit(1)

print(f"  Moving +{args.sign_move:.0f} um in X...")
drv.move_xy(client, home["x_um"] + args.sign_move, home["y_um"])
time.sleep(1)

p1_disp = acquire_single()
if p1_disp is None:
    print("  ABORT: sign-test displaced acquire failed")
    sys.exit(1)

sign_meas_dx, sign_meas_dy, sign_meas_q = register_ncc(p1_sign_ref, p1_disp, ref_pixel)
print(f"  Measured shift: ({sign_meas_dx:+.2f}, {sign_meas_dy:+.2f}) um  q={sign_meas_q:.3f}")

_sign_combos = [("+X +Y", +1, +1), ("+X -Y", +1, -1), ("-X +Y", -1, +1), ("-X -Y", -1, -1)]
p1_sign_results = []
p1_sign_images = {}
disp_pos = drv.get_xy(client)

for _label, _sx, _sy in _sign_combos:
    _cx = _sx * sign_meas_dx
    _cy = _sy * sign_meas_dy
    print(f"\n  [{_label}] Correction: ({_cx:+.2f}, {_cy:+.2f}) um")
    drv.move_xy(client, disp_pos["x_um"] + _cx, disp_pos["y_um"] + _cy)
    time.sleep(1)
    _img = acquire_single()
    if _img is None:
        p1_sign_results.append({"label": _label, "sx": _sx, "sy": _sy, "failed": True})
    else:
        _rdx, _rdy, _rq = register_ncc(p1_sign_ref, _img, ref_pixel)
        _rdist = (_rdx**2 + _rdy**2)**0.5
        print(f"  [{_label}] Residual: ({_rdx:+.2f}, {_rdy:+.2f}) um = {_rdist:.2f} um  q={_rq:.3f}")
        p1_sign_results.append({
            "label": _label, "sx": _sx, "sy": _sy, "failed": False,
            "correction_um": [float(_cx), float(_cy)],
            "residual_x_um": float(_rdx), "residual_y_um": float(_rdy),
            "residual_dist_um": float(_rdist), "ncc_quality": float(_rq),
        })
        p1_sign_images[_label] = _img
    drv.move_xy(client, disp_pos["x_um"], disp_pos["y_um"])
    time.sleep(1)

p1_best = None
for _r in p1_sign_results:
    if not _r["failed"] and (p1_best is None or _r["residual_dist_um"] < p1_best["residual_dist_um"]):
        p1_best = _r

if p1_best is None:
    print("  ABORT: all sign combos failed")
    sys.exit(1)

sign_convention = {"label": p1_best["label"], "sx": p1_best["sx"], "sy": p1_best["sy"]}
print(f"\n  Sign convention: {sign_convention['label']} "
      f"(sx={sign_convention['sx']:+d}, sy={sign_convention['sy']:+d})")
print(f"  Returning to home...")
drv.move_xy(client, home["x_um"], home["y_um"])
time.sleep(1)

# ═════════════════════════════════════════════════════════════════════════
#  PHASE 2: Z-stacks -> parfocal offset + coarse XY
# ═════════════════════════════════════════════════════════════════════════

print(f"\n{'=' * 60}")
print(f"  PHASE 2: Z-stacks (parfocal + coarse XY)")
print(f"{'=' * 60}")

# 2a. Reference Z-stack
configure_z_stack()
print(f"  Acquiring reference Z-stack...")
ref_stack = acquire_stack()
if ref_stack is None:
    sys.exit(1)
ref_brenner = measure_brenner(ref_stack, args.z_step)
ref_focus_galvo = args.z_range - ref_brenner["peak_sub"] * args.z_step
print(f"  Ref focus: Z={ref_brenner['peak_slice']} ({ref_brenner['peak_sub']:.1f}), z-galvo={ref_focus_galvo:+.1f} um")

# Pre-acquire reference focus slice now (still on ref objective), before
# any target switch. Avoids switching back through water residue later.
print(f"  Acquiring reference focus slice at z-galvo={ref_focus_galvo:+.1f} um...")
disable_z_stack()
drv.set_z_stack_definition(client, job, begin_um=ref_focus_galvo, end_um=ref_focus_galvo)
img_ref = acquire_single()
if img_ref is None:
    print("  ABORT: reference focus slice acquire failed")
    sys.exit(1)

all_results = {}

for ts in args.target_slot:
    ti = targets[ts]
    print(f"\n{'-' * 60}")
    print(f"  Target: {ti['name']} (slot {ts})")
    print(f"{'-' * 60}")

    # 2b. Target Z-stack
    setup_objective(ts, ti["zoom"])
    if args.settle > 0:
        time.sleep(args.settle)
    pos_uncorr = drv.get_xy(client)
    motor_dx = pos_uncorr["x_um"] - home["x_um"]
    motor_dy = pos_uncorr["y_um"] - home["y_um"]
    print(f"  Motor delta: ({motor_dx:+.1f}, {motor_dy:+.1f}) um")

    configure_z_stack()
    print(f"  Acquiring target Z-stack...")
    tgt_stack = acquire_stack()
    if tgt_stack is None:
        print(f"  SKIP: acquire failed")
        continue
    tgt_brenner = measure_brenner(tgt_stack, args.z_step)
    dz_um = (tgt_brenner["peak_sub"] - ref_brenner["peak_sub"]) * args.z_step
    print(f"  Tgt focus: Z={tgt_brenner['peak_slice']} ({tgt_brenner['peak_sub']:.1f})")
    print(f"  Parfocal dZ: {dz_um:+.2f} um")

    # Coarse XY from MIP
    min_z = min(ref_stack.shape[0], tgt_stack.shape[0])
    ref_mip = ref_stack[:min_z].max(axis=0)
    tgt_mip = tgt_stack[:min_z].max(axis=0)
    mip_dx, mip_dy, mip_q = register_ncc(ref_mip, tgt_mip, ref_pixel)
    mip_dist = (mip_dx**2 + mip_dy**2)**0.5
    print(f"  Coarse XY (MIP): ({mip_dx:+.2f}, {mip_dy:+.2f}) um = {mip_dist:.1f} um  q={mip_q:.3f}")

    # 2c. Validate Z: shifted verification stack
    print(f"\n  Validating Z: acquiring shifted verification stack...")
    z_begin = args.z_range - dz_um
    z_end = -args.z_range - dz_um
    configure_z_stack(begin_um=z_begin, end_um=z_end)
    ver_z_stack = acquire_stack()
    ver_brenner = None
    if ver_z_stack is not None:
        ver_brenner = measure_brenner(ver_z_stack, args.z_step)
        dz_resid = (ver_brenner["peak_sub"] - ref_brenner["peak_sub"]) * args.z_step
        print(f"  Ver focus: Z={ver_brenner['peak_slice']} ({ver_brenner['peak_sub']:.1f})")
        print(f"  Z residual: {dz_resid:+.2f} um (should be ~0)")

    # ═════════════════════════════════════════════════════════════════
    #  PHASE 3: High-quality focus slices -> precise XY
    # ═════════════════════════════════════════════════════════════════

    print(f"\n{'=' * 60}")
    print(f"  PHASE 3: High-quality focus slices (8x accumulation)")
    print(f"{'=' * 60}")

    # Disable Z-stack for single-slice acquisition
    disable_z_stack()

    # Reference focus slice was pre-acquired before the loop — use it
    # directly. No switch back to the dry objective is needed or safe.

    # 3b. Target focus slice (switch to target, at corrected Z)
    setup_objective(ts, ti["zoom"])
    time.sleep(1)
    disable_z_stack()
    # Set z-galvo to the corrected focus position
    # The focus offset in z-galvo coordinates: target was dz_um deeper
    # We want to acquire at the plane that matches the ref focus
    # z-galvo 0 = center. Target focus was at dz_um relative to ref.
    # To image the ref focal plane on target, shift z-galvo by -dz_um
    drv.set_z_stack_definition(client, job,
                               begin_um=-dz_um, end_um=-dz_um)
    print(f"  Acquiring target focus slice at z-galvo={-dz_um:+.1f} um (8x accum)...")
    img_tgt = acquire_single()
    if img_tgt is None:
        print(f"  ABORT: target focus acquire failed")
        continue

    # Precise XY from focus slices
    focus_dx, focus_dy, focus_q = register_ncc(img_ref, img_tgt, ref_pixel)
    focus_dist = (focus_dx**2 + focus_dy**2)**0.5
    print(f"  Precise XY: ({focus_dx:+.2f}, {focus_dy:+.2f}) um = {focus_dist:.1f} um  q={focus_q:.3f}")

    # Apply sign convention established in Phase 1
    sx, sy = sign_convention["sx"], sign_convention["sy"]
    cx = sx * focus_dx
    cy = sy * focus_dy
    best = {
        "label": sign_convention["label"], "sx": sx, "sy": sy,
        "correction_um": [float(cx), float(cy)],
    }
    print(f"  Sign: {sign_convention['label']}  ->  correction ({cx:+.2f}, {cy:+.2f}) um")

    # ═════════════════════════════════════════════════════════════════
    #  Store results
    # ═════════════════════════════════════════════════════════════════

    all_results[ts] = {
        "slot": ts, "label": ti["label"], "name": ti["name"],
        "mag": ti["mag"], "zoom": ti["zoom"],
        "motor_delta_um": [motor_dx, motor_dy],
        # Phase 2
        "ref_brenner": ref_brenner, "tgt_brenner": tgt_brenner,
        "dz_um": dz_um,
        "ver_brenner": ver_brenner,
        "mip_shift": {"dx_um": mip_dx, "dy_um": mip_dy, "dist_um": mip_dist, "quality": mip_q},
        "ref_mip": ref_mip, "tgt_mip": tgt_mip,
        # Phase 3
        "focus_shift": {"dx_um": focus_dx, "dy_um": focus_dy, "dist_um": focus_dist, "quality": focus_q},
        "img_ref": img_ref, "img_tgt": img_tgt,
        "best": best,
    }

# ═════════════════════════════════════════════════════════════════════════
#  Summary
# ═════════════════════════════════════════════════════════════════════════

print(f"\n{'=' * 90}")
print(f"  Calibration Results - {ref_name} (slot {args.ref_slot})")
print(f"{'=' * 90}")

print(f"\n  Sign convention (Phase 1, {args.sign_move:.0f} um test move):")
print(f"    Winner: {sign_convention['label']}  "
      f"(sx={sign_convention['sx']:+d}, sy={sign_convention['sy']:+d})")
print(f"    stage_dx = {sign_convention['sx']:+d} * shift_x  |  "
      f"stage_dy = {sign_convention['sy']:+d} * shift_y")
for sr in p1_sign_results:
    if sr["failed"]:
        print(f"      {sr['label']}: FAILED")
    else:
        star = " *" if sr["label"] == p1_best["label"] else ""
        print(f"      {sr['label']}: {sr['residual_dist_um']:6.2f} um  q={sr['ncc_quality']:.3f}{star}")

for ts, r in all_results.items():
    best = r["best"]
    print(f"\n  {r['label']}:")
    print(f"    Parfocal dZ:   {r['dz_um']:+.2f} um (Brenner)")
    if r["ver_brenner"]:
        vdz = (r["ver_brenner"]["peak_sub"] - r["ref_brenner"]["peak_sub"]) * args.z_step
        print(f"    Z validation:  {vdz:+.2f} um residual")
    print(f"    Parcentric:    ({r['focus_shift']['dx_um']:+.2f}, {r['focus_shift']['dy_um']:+.2f}) um "
          f"= {r['focus_shift']['dist_um']:.2f} um  q={r['focus_shift']['quality']:.3f}")
    if best:
        print(f"    Correction:    ({best['correction_um'][0]:+.2f}, {best['correction_um'][1]:+.2f}) um")

# ═════════════════════════════════════════════════════════════════════════
#  Visual report
# ═════════════════════════════════════════════════════════════════════════

plt.rcParams.update({"font.size": 11, "figure.facecolor": "white"})

for ts, r in all_results.items():
    best = r["best"]

    fig = plt.figure(figsize=(30, 28))
    gs = fig.add_gridspec(4, 6, hspace=0.35, wspace=0.30,
                          left=0.04, right=0.96, top=0.92, bottom=0.03)

    # ── Row 1: Phase 2 — Z measurement ──────────────────────────────
    ax = fig.add_subplot(gs[0, 0:2])
    ax.imshow(make_overlay(r["ref_mip"], r["tgt_mip"])); hide_ticks(ax)
    ax.set_title(f"Coarse XY (MIP)\n({r['mip_shift']['dx_um']:+.1f}, {r['mip_shift']['dy_um']:+.1f}) um "
                 f"q={r['mip_shift']['quality']:.3f}", fontsize=11, color="#CC0000", fontweight="bold")

    ax = fig.add_subplot(gs[0, 2:4])
    z_axis = np.arange(len(r["ref_brenner"]["scores"])) * args.z_step
    ref_s = np.array(r["ref_brenner"]["scores"]); ref_s = ref_s / ref_s.max()
    tgt_s = np.array(r["tgt_brenner"]["scores"]); tgt_s = tgt_s / tgt_s.max()
    ax.plot(z_axis, ref_s, "g-", lw=2, label=f"Ref")
    ax.plot(z_axis, tgt_s, "m-", lw=2, label=f"Target")
    ax.axvline(r["ref_brenner"]["peak_sub"] * args.z_step, color="g", ls=":", lw=1.5)
    ax.axvline(r["tgt_brenner"]["peak_sub"] * args.z_step, color="m", ls=":", lw=1.5)
    if r["ver_brenner"]:
        ver_s = np.array(r["ver_brenner"]["scores"]); ver_s = ver_s / ver_s.max()
        ax.plot(z_axis[:len(ver_s)], ver_s, "b--", lw=1.5, label="Z-corrected")
        ax.axvline(r["ver_brenner"]["peak_sub"] * args.z_step, color="b", ls=":", lw=1.5)
    ax.set_xlabel("Z (um)"); ax.set_ylabel("Brenner (norm)")
    ax.set_title(f"Parfocal: dZ = {r['dz_um']:+.2f} um", fontsize=11, fontweight="bold")
    ax.legend(fontsize=9); ax.grid(True, alpha=0.3)
    ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)

    ax = fig.add_subplot(gs[0, 4:6])
    ax.imshow(make_overlay(ref_stack[r["ref_brenner"]["peak_slice"]],
                           tgt_stack[r["tgt_brenner"]["peak_slice"]])); hide_ticks(ax)
    ax.set_title(f"Best-focus overlay (before correction)\n"
                 f"Ref Z={r['ref_brenner']['peak_slice']}, "
                 f"Tgt Z={r['tgt_brenner']['peak_slice']}", fontsize=11)

    # ── Row 2: Phase 3 — High-quality focus slices ───────────────────
    ax = fig.add_subplot(gs[1, 0:2])
    ax.imshow(r["img_ref"], cmap="gray"); hide_ticks(ax)
    ax.set_title(f"Reference focus slice (8x accum)\n{ref_label}", fontsize=11)

    ax = fig.add_subplot(gs[1, 2:4])
    ax.imshow(make_overlay(r["img_ref"], r["img_tgt"])); hide_ticks(ax)
    ax.set_title(f"Focus-slice overlay (Z-matched)\n"
                 f"({r['focus_shift']['dx_um']:+.1f}, {r['focus_shift']['dy_um']:+.1f}) um "
                 f"= {r['focus_shift']['dist_um']:.1f} um  q={r['focus_shift']['quality']:.3f}",
                 fontsize=11, color="#CC0000", fontweight="bold")

    ax = fig.add_subplot(gs[1, 4:6])
    ax.axis("off")
    phase2_txt = (
        f"Phase 3: Precise XY\n"
        f"{'━' * 36}\n\n"
        f"MIP (coarse):\n"
        f"  ({r['mip_shift']['dx_um']:+.2f}, {r['mip_shift']['dy_um']:+.2f})\n"
        f"  = {r['mip_shift']['dist_um']:.2f} um\n\n"
        f"Focus slice (precise):\n"
        f"  ({r['focus_shift']['dx_um']:+.2f}, {r['focus_shift']['dy_um']:+.2f})\n"
        f"  = {r['focus_shift']['dist_um']:.2f} um\n"
        f"  q = {r['focus_shift']['quality']:.3f}"
    )
    ax.text(0.05, 0.95, phase2_txt, transform=ax.transAxes, fontsize=11, va="top",
            fontfamily="monospace", bbox=dict(boxstyle="round", facecolor="#F0F0FF", alpha=0.9))

    # ── Row 3: Phase 1 — Sign convention test ────────────────────────
    for i, sr in enumerate(p1_sign_results):
        if sr["failed"] or i >= 4:
            continue
        ax = fig.add_subplot(gs[2, i])
        if sr["label"] in p1_sign_images:
            ax.imshow(make_overlay(p1_sign_ref, p1_sign_images[sr["label"]]))
        hide_ticks(ax)
        is_best = sr["label"] == p1_best["label"]
        color = "#006600" if is_best else "#444444"
        ax.set_title(f"{sr['label']}\n{sr['residual_dist_um']:.2f} um  q={sr['ncc_quality']:.3f}"
                     f"{'  *' if is_best else ''}", fontsize=11,
                     color=color, fontweight="bold" if is_best else "normal")
        if is_best:
            for spine in ax.spines.values():
                spine.set_edgecolor("#006600"); spine.set_linewidth(3)

    ax = fig.add_subplot(gs[2, 4:6])
    s_labels = [sr["label"] for sr in p1_sign_results if not sr["failed"]]
    s_dists = [sr["residual_dist_um"] for sr in p1_sign_results if not sr["failed"]]
    s_colors = ["#006600" if sr["label"] == p1_best["label"] else "#BBBBBB"
                for sr in p1_sign_results if not sr["failed"]]
    bars = ax.bar(s_labels, s_dists, color=s_colors, alpha=0.85, edgecolor="black", lw=0.5)
    for bar, d in zip(bars, s_dists):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
                f"{d:.2f}", ha="center", fontsize=10, fontweight="bold")
    ax.set_ylabel("Residual (um)")
    ax.set_title(f"Phase 1 sign test  winner: {sign_convention['label']}", fontsize=12, fontweight="bold")
    ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)

    # ── Row 4: Summary ───────────────────────────────────────────────
    ax = fig.add_subplot(gs[3, 0:3])
    ax.axis("off")
    summary = (
        f"Parcentric + Parfocal Calibration\n"
        f"{'━' * 50}\n"
        f"\n"
        f"Reference:  {ref_name}\n"
        f"Target:     {r['name']}\n"
        f"Zoom:       {args.ref_zoom} → {r['zoom']:.1f}  |  Pixel: {ref_pixel:.4f} um\n"
        f"\n"
        f"{'━' * 50}\n"
        f"PARFOCAL (Z)\n"
        f"  dZ: {r['dz_um']:+.2f} um (Brenner gradient)\n"
    )
    if r["ver_brenner"]:
        vdz = (r["ver_brenner"]["peak_sub"] - r["ref_brenner"]["peak_sub"]) * args.z_step
        summary += f"  Z validation residual: {vdz:+.2f} um\n"
    summary += (
        f"\n"
        f"PARCENTRIC (XY)\n"
        f"  MIP (coarse):   {r['mip_shift']['dist_um']:.2f} um\n"
        f"  Focus (precise): {r['focus_shift']['dist_um']:.2f} um\n"
        f"    ({r['focus_shift']['dx_um']:+.2f}, {r['focus_shift']['dy_um']:+.2f}) um\n"
    )
    summary += (
        f"\n"
        f"SIGN CONVENTION (Phase 1)\n"
        f"  Convention: {sign_convention['label']}\n"
        f"  P1 residual: {p1_best['residual_dist_um']:.2f} um\n"
        f"  stage_dx = {sign_convention['sx']:+d} * shift_x\n"
        f"  stage_dy = {sign_convention['sy']:+d} * shift_y\n"
    )
    ax.text(0.02, 0.95, summary, transform=ax.transAxes, fontsize=11.5, va="top",
            fontfamily="monospace",
            bbox=dict(boxstyle="round,pad=0.8", facecolor="#FFFFF0",
                      edgecolor="#888888", alpha=0.95))

    # Vector diagram
    ax = fig.add_subplot(gs[3, 3:6])
    fx, fy = r["focus_shift"]["dx_um"], r["focus_shift"]["dy_um"]
    lim = max(abs(fx), abs(fy), 5) * 1.3
    ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim)
    ax.set_aspect("equal")
    ax.axhline(0, color="gray", lw=0.5); ax.axvline(0, color="gray", lw=0.5)
    ax.plot(0, 0, "o", ms=14, color="#006600", zorder=5, label="Target")
    ax.plot(fx, fy, "^", ms=12, color="#CC0000",
            label=f"Uncorr: {r['focus_shift']['dist_um']:.1f} um")
    ax.annotate("", xy=(fx, fy), xytext=(0, 0),
                arrowprops=dict(arrowstyle="-|>", color="#CC0000", lw=2.5))
    sign_colors = ["#0066CC", "#CC6600", "#006600", "#9900CC"]
    for i, sr in enumerate(p1_sign_results):
        if sr["failed"]:
            continue
        is_best = sr["label"] == p1_best["label"]
        ax.plot(sr["residual_x_um"], sr["residual_y_um"],
                "*" if is_best else "s", ms=14 if is_best else 8,
                color=sign_colors[i], zorder=5 if is_best else 3,
                label=f"{sr['label']}: {sr['residual_dist_um']:.2f} um")
    ax.set_xlabel("X (um)"); ax.set_ylabel("Y (um)")
    ax.set_title("Phase 1 sign vectors", fontsize=12, fontweight="bold")
    ax.legend(fontsize=9); ax.grid(True, alpha=0.3)

    fig.suptitle(
        f"Calibration: {ref_name} -> {r['name']}  |  "
        f"dXY: {r['focus_shift']['dist_um']:.1f} um  dZ: {r['dz_um']:+.1f} um  |  "
        f"Sign: {sign_convention['label']} (Phase 1)",
        fontsize=14, fontweight="bold", y=0.97)

    report_path = os.path.join(out_dir, f"calib_{ref_label}_vs_{r['label']}.png")
    fig.savefig(report_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Report: {report_path}")

# ═════════════════════════════════════════════════════════════════════════
#  Save calibration JSON
# ═════════════════════════════════════════════════════════════════════════

calib = {
    "timestamp": _ts,
    "method": {"xy": "opencv_ncc_focus_slice", "z": "brenner_gradient",
               "sign": "phase1_empirical_4combo"},
    "ref_objective": ref_name, "ref_label": ref_label,
    "ref_slot": args.ref_slot, "ref_zoom": args.ref_zoom,
    "ref_pixel_um": float(ref_pixel), "ref_fov_um": float(fov_um),
    "z_range_um": args.z_range, "z_step_um": args.z_step,
    "sign_convention": {
        "label": sign_convention["label"],
        "sx": sign_convention["sx"],
        "sy": sign_convention["sy"],
        "test_move_um": float(args.sign_move),
        "p1_residual_um": float(p1_best["residual_dist_um"]),
        "p1_quality": float(p1_best["ncc_quality"]),
        "p1_all": [
            {"label": sr["label"], "residual_um": sr["residual_dist_um"],
             "quality": sr["ncc_quality"]}
            for sr in p1_sign_results if not sr["failed"]
        ],
    },
    "targets": {},
}

for ts, r in all_results.items():
    best = r["best"]
    entry = {
        "full_name": r["name"], "slot": ts,
        "magnification": r["mag"], "target_zoom": r["zoom"],
        "motor_delta_um": r["motor_delta_um"],
        "shift_xy_um": [float(r["focus_shift"]["dx_um"]), float(r["focus_shift"]["dy_um"])],
        "shift_dist_xy_um": float(r["focus_shift"]["dist_um"]),
        "shift_z_um": float(r["dz_um"]),
        "mip_xy_um": [float(r["mip_shift"]["dx_um"]), float(r["mip_shift"]["dy_um"])],
        "mip_quality": float(r["mip_shift"]["quality"]),
        "focus_quality": float(r["focus_shift"]["quality"]),
    }
    if r["ver_brenner"]:
        vdz = (r["ver_brenner"]["peak_sub"] - r["ref_brenner"]["peak_sub"]) * args.z_step
        entry["z_validation_residual_um"] = float(vdz)
    if best:
        entry["correction_um"] = [float(best["correction_um"][0]), float(best["correction_um"][1])]
    calib["targets"][r["label"]] = entry

json_path = os.path.join(out_dir, "calibration.json")
with open(json_path, "w") as f:
    json.dump(calib, f, indent=2)
print(f"\n  Calibration: {json_path}")

# ═════════════════════════════════════════════════════════════════════════
#  Restore
# ═════════════════════════════════════════════════════════════════════════

print(f"\n  Restoring Z settings (leaving objective as-is)...")

orig_z_mode = int(orig_z.get("ZUseMode", 2))
orig_sections = int(orig_z.get("Sections", 1))
orig_calc_mode = int(orig_z.get("StackCalculationMode", 2))
orig_active = orig_z.get("ZStackActive", "0")

def restore_z(p):
    lrp_set_z_use_mode(p, "z-galvo" if orig_z_mode == 1 else "z-wide", job)
    lrp_set_stack_calculation_mode(p, orig_calc_mode, job)
    lrp_set_sections(p, orig_sections, job)
    lrp_set_z_stack_active(p, str(orig_active) == "1", job)
apply_lrp_change(client, TEMPLATE_XML, restore_z, confirm_delays=(2, 4, 6))

drv.move_xy(client, home["x_um"], home["y_um"])
time.sleep(1)
print("  Done.")

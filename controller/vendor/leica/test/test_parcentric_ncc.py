"""
Parcentric Calibration — 2D OpenCV NCC
========================================
Simple single-plane parcentric calibration using OpenCV normalized
cross-correlation (TM_CCOEFF_NORMED).

Acquires a single image on each objective (pixel-matched via zoom),
registers with OpenCV NCC + masked NCC for sub-pixel refinement,
applies -X +Y correction, and verifies.

For parfocal (Z) calibration or out-of-focus robustness, use the
MIP-based version: test_parcentric_calibration.py

Sign convention (validated 2026-03-30):
    stage_dx = -image_shift_x   (image X is mirrored vs stage)
    stage_dy = +image_shift_y   (image Y matches stage)

Usage:
    python test_parcentric_ncc.py --ref-slot 1 --target-slot 2
    python test_parcentric_ncc.py --ref-slot 1 --target-slot 2 0
    python test_parcentric_ncc.py --ref-slot 1 --target-slot 2 --ref-zoom 3
"""

import argparse
import json
import os
import sys
import time
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

parser = argparse.ArgumentParser(description="Parcentric calibration (2D NCC)")
parser.add_argument("--ref-slot", type=int, required=True,
                    help="Reference objective slot (e.g. 1 for 10x)")
parser.add_argument("--target-slot", type=int, nargs="+", required=True,
                    help="Target objective slot(s) (e.g. 2 or 2 0)")
parser.add_argument("--ref-zoom", type=float, default=10,
                    help="Reference zoom level (default: 10)")
parser.add_argument("--settle", type=float, default=0,
                    help="Extra settle time per target after switch (s)")
parser.add_argument("--mask-pct", type=float, default=30,
                    help="Mask percentile for sub-pixel refinement (default: 30)")
parser.add_argument("--job", default="Overview",
                    help="LAS X job name (default: Overview)")
parser.add_argument("--output", default=None)
args = parser.parse_args()

# ── Imports ──────────────────────────────────────────────────────────────

import numpy as np
import tifffile
import cv2
from skimage.registration import phase_cross_correlation

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from LasxApi import PYLICamApiConnector as lasx_api
import lasx as drv
from lasx.scanning_templates import TEMPLATE_XML, apply_lrp_change
from lasx.scanning_template_editors_scan import lrp_set_pan
from lasx.scanning_template_editors_roi import lrp_enable_roi_scan
from lasx.readers import get_job_settings, get_lasx_settings
from lasx.utils import parse_tile_geometry
from lasx.prechecks import check_idle

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.ndimage import shift as ndi_shift

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
    print(f"  ABORT: Expected job '{job}', got '{current_job}'.")
    print(f"  Please select '{job}' in LAS X and retry.")
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

# ── Output ───────────────────────────────────────────────────────────────

_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
_default_out = os.path.join(
    str(Path(__file__).resolve().parent.parent),
    "config", "alignment", f"ncc_{_ts}")
out_dir = args.output or _default_out
os.makedirs(out_dir, exist_ok=True)
print(f"  Output: {out_dir}")

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


def acquire_image():
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
        print(f"  File detection failed: {det.get('error')}")
        return None
    img = tifffile.imread(str(sorted(det["image_files"])[0]))
    if img.ndim == 3:
        img = img[0]
    return img


# ── Registration ─────────────────────────────────────────────────────────


def to_uint8(img):
    f = img.astype(np.float64)
    f = f / (f.max() or 1) * 255
    return f.astype(np.uint8)


def register_ncc(ref, tgt, pixel_um):
    """OpenCV NCC (integer pixel). Returns (dx_um, dy_um, quality)."""
    ref8 = to_uint8(ref)
    tgt8 = to_uint8(tgt)
    h, w = tgt8.shape
    margin = h // 4
    template = tgt8[margin:h-margin, margin:w-margin]
    result = cv2.matchTemplate(ref8, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    match_cx = max_loc[0] + template.shape[1] / 2
    match_cy = max_loc[1] + template.shape[0] / 2
    dx_px = match_cx - w / 2
    dy_px = match_cy - h / 2
    return dx_px * pixel_um, dy_px * pixel_um, float(max_val)


def register_masked(ref, tgt, pixel_um, mask_pct):
    """Masked NCC for sub-pixel (Padfield 2012). Returns (dx_um, dy_um, quality)."""
    ref_mask = ref > np.percentile(ref, mask_pct)
    tgt_mask = tgt > np.percentile(tgt, mask_pct)
    shift, error, _ = phase_cross_correlation(
        ref.astype(np.float64), tgt.astype(np.float64),
        upsample_factor=100,
        reference_mask=ref_mask, moving_mask=tgt_mask)
    dy_px, dx_px = shift
    return dx_px * pixel_um, dy_px * pixel_um, float(error)


def measure_shift(ref, tgt, pixel_um, mask_pct):
    """Measure shift with OpenCV NCC + masked NCC cross-validation."""
    dx_ncc, dy_ncc, q_ncc = register_ncc(ref, tgt, pixel_um)
    dx_mask, dy_mask, q_mask = register_masked(ref, tgt, pixel_um, mask_pct)
    dist_ncc = (dx_ncc**2 + dy_ncc**2)**0.5
    dist_mask = (dx_mask**2 + dy_mask**2)**0.5
    agreement = ((dx_ncc - dx_mask)**2 + (dy_ncc - dy_mask)**2)**0.5

    return {
        "dx_um": dx_mask, "dy_um": dy_mask, "dist_um": dist_mask,
        "ncc_dx_um": dx_ncc, "ncc_dy_um": dy_ncc, "ncc_dist_um": dist_ncc,
        "ncc_quality": q_ncc,
        "agreement_um": agreement,
        "reliable": q_ncc > 0.5 and agreement < 3.0,
    }


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
#  Acquire reference
# ═════════════════════════════════════════════════════════════════════════

print(f"\n{'=' * 60}")
print(f"  Acquiring reference ({ref_name})")
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

img_ref = acquire_image()
if img_ref is None:
    print("  ABORT: reference acquire failed")
    sys.exit(1)

# ═════════════════════════════════════════════════════════════════════════
#  Calibrate each target
# ═════════════════════════════════════════════════════════════════════════

all_results = {}

for ts in args.target_slot:
    ti = targets[ts]

    print(f"\n{'=' * 60}")
    print(f"  Calibrating {ti['name']} (slot {ts})")
    print(f"{'=' * 60}")

    setup_objective(ts, ti["zoom"])
    if args.settle > 0:
        print(f"  Settling {args.settle:.0f}s...")
        time.sleep(args.settle)

    pos_uncorr = drv.get_xy(client)
    motor_dx = pos_uncorr["x_um"] - home["x_um"]
    motor_dy = pos_uncorr["y_um"] - home["y_um"]
    print(f"  Motor delta: ({motor_dx:+.1f}, {motor_dy:+.1f}) um")

    print(f"  Acquiring uncorrected...")
    img_uncorr = acquire_image()
    if img_uncorr is None:
        print(f"  SKIP: acquire failed")
        continue

    raw = measure_shift(img_ref, img_uncorr, ref_pixel, args.mask_pct)
    print(f"  Shift (masked): ({raw['dx_um']:+.2f}, {raw['dy_um']:+.2f}) um = {raw['dist_um']:.2f} um")
    print(f"  Shift (NCC):    ({raw['ncc_dx_um']:+.2f}, {raw['ncc_dy_um']:+.2f}) um  q={raw['ncc_quality']:.3f}")
    print(f"  Agreement: {raw['agreement_um']:.2f} um  {'OK' if raw['reliable'] else 'WARNING'}")

    # Apply correction: -X +Y
    corr_x = -raw["dx_um"]
    corr_y = +raw["dy_um"]
    print(f"  Correction (-X +Y): ({corr_x:+.2f}, {corr_y:+.2f}) um")
    drv.move_xy(client, pos_uncorr["x_um"] + corr_x, pos_uncorr["y_um"] + corr_y)
    time.sleep(1)

    print(f"  Acquiring corrected...")
    img_corr = acquire_image()
    if img_corr is not None:
        resid = measure_shift(img_ref, img_corr, ref_pixel, args.mask_pct)
        print(f"  Residual: ({resid['dx_um']:+.2f}, {resid['dy_um']:+.2f}) um = {resid['dist_um']:.2f} um")
    else:
        resid = {"dx_um": np.nan, "dy_um": np.nan, "dist_um": np.nan,
                 "ncc_quality": 0, "reliable": False}

    all_results[ts] = {
        "slot": ts, "label": ti["label"], "name": ti["name"],
        "mag": ti["mag"], "zoom": ti["zoom"],
        "motor_delta_um": [motor_dx, motor_dy],
        "raw": raw, "correction_um": [corr_x, corr_y], "resid": resid,
        "img_ref": img_ref, "img_uncorr": img_uncorr, "img_corr": img_corr,
    }

# ═════════════════════════════════════════════════════════════════════════
#  Summary
# ═════════════════════════════════════════════════════════════════════════

print(f"\n{'=' * 70}")
print(f"  Calibration Results — {ref_name}")
print(f"{'=' * 70}")
print(f"  {'Target':<28}  {'Shift':>8}  {'Residual':>10}  {'NCC q':>7}  {'OK':>4}")
print(f"  {'-'*28}  {'-'*8}  {'-'*10}  {'-'*7}  {'-'*4}")

for ts, r in all_results.items():
    ok = "YES" if r["raw"]["reliable"] and r["resid"]["dist_um"] < 5 else "NO"
    print(f"  {r['label']:<28}  {r['raw']['dist_um']:7.2f}  "
          f"{r['resid']['dist_um']:9.2f}  {r['raw']['ncc_quality']:7.3f}  {ok:>4}")

# ═════════════════════════════════════════════════════════════════════════
#  Visual report — one page per target
# ═════════════════════════════════════════════════════════════════════════

plt.rcParams.update({"font.size": 11, "figure.facecolor": "white"})

for ts, r in all_results.items():
    raw = r["raw"]
    resid = r["resid"]

    fig = plt.figure(figsize=(24, 16))
    gs = fig.add_gridspec(2, 4, hspace=0.30, wspace=0.30,
                          left=0.04, right=0.96, top=0.90, bottom=0.05)

    # Row 1: ref | uncorrected | corrected | software-registered
    ax = fig.add_subplot(gs[0, 0])
    ax.imshow(r["img_ref"], cmap="gray"); hide_ticks(ax)
    ax.set_title(f"Reference\n{ref_label} z{args.ref_zoom}", fontsize=12)

    ax = fig.add_subplot(gs[0, 1])
    ax.imshow(make_overlay(r["img_ref"], r["img_uncorr"])); hide_ticks(ax)
    ax.set_title(f"Uncorrected\n{raw['dist_um']:.1f} um offset",
                 fontsize=12, color="#CC0000", fontweight="bold")

    if r["img_corr"] is not None:
        ax = fig.add_subplot(gs[0, 2])
        ax.imshow(make_overlay(r["img_ref"], r["img_corr"])); hide_ticks(ax)
        rdist = resid["dist_um"]
        color = "#006600" if rdist < 3 else "#CC6600"
        ax.set_title(f"Corrected (-X +Y)\n{rdist:.2f} um residual",
                     fontsize=12, color=color, fontweight="bold")
        for spine in ax.spines.values():
            spine.set_edgecolor(color); spine.set_linewidth(3)

        ax = fig.add_subplot(gs[0, 3])
        ref_mask = r["img_ref"] > np.percentile(r["img_ref"], args.mask_pct)
        corr_mask = r["img_corr"] > np.percentile(r["img_corr"], args.mask_pct)
        shift_vis, _, _ = phase_cross_correlation(
            r["img_ref"].astype(np.float64),
            r["img_corr"].astype(np.float64),
            upsample_factor=100,
            reference_mask=ref_mask, moving_mask=corr_mask)
        img_reg = ndi_shift(r["img_corr"].astype(np.float64), shift_vis)
        ax.imshow(make_overlay(r["img_ref"], img_reg)); hide_ticks(ax)
        ax.set_title(f"Software-registered\n(visual check)", fontsize=12, color="#0066CC")

    # Row 2: bar chart | vectors | summary
    ax = fig.add_subplot(gs[1, 0])
    labels = ["Uncorrected", "Corrected"]
    dists = [raw["dist_um"], resid["dist_um"]]
    colors = ["#CC0000", "#006600"]
    bars = ax.bar(labels, dists, color=colors, alpha=0.85,
                  edgecolor="black", lw=0.8, width=0.5)
    for bar, d in zip(bars, dists):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                f"{d:.2f} um", ha="center", fontsize=12, fontweight="bold")
    ax.set_ylabel("Distance (um)")
    ax.set_title("Correction result", fontsize=12, fontweight="bold")
    ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)

    ax = fig.add_subplot(gs[1, 1])
    sx, sy = raw["dx_um"], raw["dy_um"]
    rx, ry = resid["dx_um"], resid["dy_um"]
    lim = max(abs(sx), abs(sy), 5) * 1.3
    ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim)
    ax.set_aspect("equal")
    ax.axhline(0, color="gray", lw=0.5); ax.axvline(0, color="gray", lw=0.5)
    ax.plot(0, 0, "o", ms=14, color="#006600", zorder=5, label="Target")
    ax.plot(sx, sy, "^", ms=12, color="#CC0000",
            label=f"Uncorr: {raw['dist_um']:.1f} um")
    ax.annotate("", xy=(sx, sy), xytext=(0, 0),
                arrowprops=dict(arrowstyle="-|>", color="#CC0000", lw=2.5))
    if not np.isnan(rx):
        ax.plot(rx, ry, "*", ms=16, color="#006600", zorder=5,
                label=f"Corrected: {resid['dist_um']:.2f} um")
        ax.annotate("", xy=(rx, ry), xytext=(sx, sy),
                    arrowprops=dict(arrowstyle="-|>", color="#006600", lw=2, ls="--"))
    ax.set_xlabel("X (um)"); ax.set_ylabel("Y (um)")
    ax.set_title("Shift vectors", fontsize=12, fontweight="bold")
    ax.legend(fontsize=10); ax.grid(True, alpha=0.3)

    ax = fig.add_subplot(gs[1, 2:4])
    ax.axis("off")
    cx, cy = r["correction_um"]
    summary = (
        f"Parcentric Calibration (2D NCC)\n"
        f"{'━' * 48}\n"
        f"\n"
        f"Reference:  {ref_name}\n"
        f"Target:     {r['name']}\n"
        f"Zoom:       {args.ref_zoom} → {r['zoom']:.1f}\n"
        f"Pixel:      {ref_pixel:.4f} um  |  FOV: {fov_um:.0f} um\n"
        f"\n"
        f"{'━' * 48}\n"
        f"Motor delta:   ({r['motor_delta_um'][0]:+.1f}, {r['motor_delta_um'][1]:+.1f}) um\n"
        f"Image shift:   ({sx:+.2f}, {sy:+.2f}) um = {raw['dist_um']:.2f} um\n"
        f"NCC quality:   {raw['ncc_quality']:.3f}\n"
        f"Method agree:  {raw['agreement_um']:.2f} um\n"
        f"\n"
        f"Correction:    ({cx:+.2f}, {cy:+.2f}) um  [sign: -X +Y]\n"
        f"Residual:      ({rx:+.2f}, {ry:+.2f}) um = {resid['dist_um']:.2f} um\n"
        f"\n"
        f"{'━' * 48}\n"
        f"Sub-pixel:     {'YES' if resid['dist_um'] < ref_pixel else 'NO'}\n"
        f"Reliable:      {'YES' if raw['reliable'] else 'NO'}\n"
        f"Method:        OpenCV NCC + masked NCC\n"
        f"Sign:          stage = (-shift_x, +shift_y)\n"
    )
    ax.text(0.02, 0.95, summary, transform=ax.transAxes,
            fontsize=12, va="top", fontfamily="monospace",
            bbox=dict(boxstyle="round,pad=0.8", facecolor="#FFFFF0",
                      edgecolor="#888888", alpha=0.95))

    fig.suptitle(
        f"Parcentric Calibration:  {ref_name}  →  {r['name']}\n"
        f"Shift: {raw['dist_um']:.1f} um  →  Residual: {resid['dist_um']:.2f} um  |  "
        f"NCC quality: {raw['ncc_quality']:.3f}",
        fontsize=15, fontweight="bold", y=0.96)

    report_path = os.path.join(out_dir, f"ncc_{ref_label}_vs_{r['label']}.png")
    fig.savefig(report_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Report: {report_path}")

# ═════════════════════════════════════════════════════════════════════════
#  Save calibration JSON
# ═════════════════════════════════════════════════════════════════════════

calib = {
    "timestamp": _ts,
    "method": "opencv_ncc_2d",
    "sign_convention": "-X +Y",
    "ref_objective": ref_name,
    "ref_label": ref_label,
    "ref_slot": args.ref_slot,
    "ref_zoom": args.ref_zoom,
    "ref_pixel_um": float(ref_pixel),
    "ref_fov_um": float(fov_um),
    "targets": {},
}

for ts, r in all_results.items():
    raw = r["raw"]
    resid = r["resid"]
    calib["targets"][r["label"]] = {
        "full_name": r["name"],
        "slot": ts,
        "magnification": r["mag"],
        "target_zoom": r["zoom"],
        "motor_delta_um": r["motor_delta_um"],
        "shift_xy_um": [float(raw["dx_um"]), float(raw["dy_um"])],
        "shift_dist_um": float(raw["dist_um"]),
        "correction_um": [float(r["correction_um"][0]), float(r["correction_um"][1])],
        "ncc_quality": float(raw["ncc_quality"]),
        "agreement_um": float(raw["agreement_um"]),
        "reliable": bool(raw["reliable"]),
        "residual_xy_um": [float(resid["dx_um"]), float(resid["dy_um"])],
        "residual_dist_um": float(resid["dist_um"]),
    }

json_path = os.path.join(out_dir, "calibration.json")
with open(json_path, "w") as f:
    json.dump(calib, f, indent=2)
print(f"\n  Calibration: {json_path}")

# ═════════════════════════════════════════════════════════════════════════
#  Restore
# ═════════════════════════════════════════════════════════════════════════

print(f"\n  Restoring...")
setup_objective(args.ref_slot, args.ref_zoom)
drv.move_xy(client, home["x_um"], home["y_um"])
time.sleep(1)
print("  Done.")

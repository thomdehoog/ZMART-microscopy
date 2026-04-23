"""
Objective-switch galvo targeting — three-image single-pass NCC alignment.
=========================================================================

Pick a cell in 10x, register a 20x intermediate acquisition against
the 10x template, zoom in on the registered position. Classical image
registration in the alignment path — no ML, no re-segmentation of the
target.

Three images:

    1. SOURCE (10x, zoom 1). Cellpose picks a nucleus near the image
       centre. That centroid defines the target. A padded template is
       cropped around the cell for later registration.

    2. INTERMEDIATE (20x, "match zoom" = nearest zoom that puts target
       pixel size close to source). The frame is downsampled to exactly
       source pixel size before NCC — this gives much higher NCC peaks
       empirically (0.96 range) than acquiring at natively-matched
       format (0.12 — LAS X SNR or scan timing seems tied to default
       format 512). The initial aim is the calibration-predicted
       target XY; NCC searches a large radius (``--search-radius-um
       200`` default) and relies on the ``--ncc-ratio-min 4.0``
       uniqueness gate to reject neighbour-cell mismatches, which is
       more reliable than constraining where the match can live.
       ``--template-pad 4.0`` gives plenty of surrounding context to
       make the template geometrically unique.

    3. FINAL (20x, high zoom framed to --fov-bbox-margin x bbox). Zoom
       set FIRST, then move_xy_galvo to the corrected XY. Cell should
       land at sub-um precision.

No iterative refinement: galvo pan is sub-um reproducible when
PAN_SCALE is resolved from base FOV and the zoom-before-pan order is
respected. One registration is enough to close the calibration
residual. The stage-iterative sibling needs a loop because the
motorized stage's settle error (~9 um) accumulates across corrections.

Zoom-before-pan (critical!)
    Writing pan then changing zoom causes LAS X to silently clamp pan
    (verified on 40x: 0.00431 -> 0.00194). This script always calls
    set_zoom BEFORE move_xy_galvo. See driver docstring.

Galvo range caveat
    Reachable pan ≈ ±775/388/194 um on 10x/20x/40x from the current
    stage position. If the calibration-predicted target XY is outside
    that radius the script aborts — pick a cell closer to the source
    image centre, or use the stage-targeting sibling.

Operator preconditions
    - --job currently selected in the LAS X UI.
    - ImageTransformation = TOPLEFT in LAS X Advanced Settings.
    - AFC / autofocus OFF, no modal dialogs.
    - Stage over a sample region with cells visible at source zoom.
    - config/objective_offsets.json present (from measure_objective_offsets.py).

Usage
    python objective_switch_galvo_targeting.py --job HiRes \\
        --source-slot 1 --target-slot 2
"""

import argparse
import json
import logging
import math
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np
import tifffile
from skimage.measure import regionprops
from cellpose import models
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from LasxApi import PYLICamApiConnector as lasx_api
import lasx as drv


log = logging.getLogger("objective_switch_galvo_targeting")


# ── CLI ───────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description=(
            "Single-pass galvo targeting across an objective switch. "
            "Cellpose picks the cell at source; NCC registration "
            "aligns a 20x intermediate against the 10x template; "
            "the final zoom is framed on the registered position."
        )
    )
    p.add_argument("--job", required=True)
    p.add_argument("--source-slot", type=int, required=True)
    p.add_argument("--target-slot", type=int, required=True)

    p.add_argument("--fov-bbox-margin", type=float, default=1.5,
                   help="Final target FOV = margin x nucleus bbox (default: 1.5).")
    p.add_argument("--template-pad", type=float, default=4.0,
                   help="Template half-size = pad x bbox half (default: 4.0 — "
                        "bigger context helps rule out neighbour-cell hits in "
                        "dense fields).")

    p.add_argument("--ncc-peak-min", type=float, default=0.4,
                   help="Reject NCC match below this correlation peak "
                        "(default: 0.4).")
    p.add_argument("--ncc-ratio-min", type=float, default=2.0,
                   help="Reject if peak / second-peak < this ratio "
                        "(default: 2.0 — tight enough to reject ambiguous "
                        "twins in dense fields, not so strict that it "
                        "rejects real matches that happen to have a few "
                        "similar-looking neighbours).")
    p.add_argument("--search-radius-um", type=float, default=200.0,
                   help="NCC search radius around the image centre "
                        "(default: 200 um — generous to tolerate calibration "
                        "residuals. Uniqueness is enforced by --ncc-ratio-min "
                        "rather than this search window).")

    p.add_argument("--diameter", type=float, default=None,
                   help="Cellpose diameter in pixels (default: auto).")
    p.add_argument("--pick-pixel", type=int, nargs=2, default=None,
                   metavar=("ROW", "COL"),
                   help="Source pixel near which to pick (default: image centre).")
    p.add_argument("--no-gpu", action="store_true",
                   help="Disable GPU for Cellpose.")
    p.add_argument("--settle", type=float, default=3.0,
                   help="Seconds after each objective switch (default: 3).")

    p.add_argument("--output-dir", type=Path, default=None,
                   help="Output dir (default: "
                        "config/objective_targeting/galvo/<timestamp>/).")
    p.add_argument("--no-restore", action="store_true",
                   help="Do not switch back to the source objective at the end.")
    return p.parse_args()


# ── Small helpers ─────────────────────────────────────────────────

def _abort(msg, code=1):
    print(f"ABORT: {msg}")
    sys.exit(code)


def _default_output_dir():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return (Path(__file__).resolve().parent.parent
            / "config" / "objective_targeting" / "galvo" / ts)


def _check_image_orientation():
    settings = drv.get_lasx_settings() or {}
    orient = settings.get("image_orientation", {})
    if orient.get("enable_transform", False) and \
            orient.get("transformation", "TOPLEFT") != "TOPLEFT":
        _abort(f"ImageTransformation is '{orient.get('transformation')}'; "
               f"set to TOPLEFT in LAS X Advanced Settings.", 2)


def _acquire_one(client, job_name):
    baseline = drv.read_relative_path(client)
    t_start = time.time()
    r = drv.acquire(client, job_name)
    if not r or not r.get("success"):
        raise RuntimeError(f"acquire failed: {r}")
    media = drv.get_lasx_settings()["export"]["media_path"]
    det = drv.detect_new_files(client, baseline, media, acquire_start=t_start)
    if not det["success"]:
        raise RuntimeError(f"file detection failed: {det.get('error')}")
    files = sorted(det["image_files"])
    if not files:
        raise RuntimeError("no image files produced by acquisition")
    drv.wait_all_stable(files, timeout=30)
    path = Path(files[0])
    img = tifffile.imread(str(path))
    if img.ndim == 3:
        img = img[0]
    return img, path


def _pick_nearest_cell(masks, image_shape, target_pixel=None):
    props = regionprops(masks)
    if not props:
        return None
    h, w = image_shape[:2]
    if target_pixel is None:
        target_row, target_col = h / 2.0, w / 2.0
    else:
        target_row, target_col = float(target_pixel[0]), float(target_pixel[1])
    return min(props,
               key=lambda p: (p.centroid[0] - target_row) ** 2
                              + (p.centroid[1] - target_col) ** 2)


# ── Template + resampling ─────────────────────────────────────────

def _extract_template(image, centroid, bbox, pad_factor):
    """Crop a square template around a cell (padded by pad_factor x bbox).

    Returns (template, (top, left), (centroid_col, centroid_row)). The
    sub-pixel centroid position inside the template avoids half-pixel
    bias when mapping NCC matches back to the cell's true location.
    """
    cy, cx = centroid
    min_r, min_c, max_r, max_c = bbox
    half = int(round(pad_factor * max(max_r - min_r, max_c - min_c) / 2))
    h, w = image.shape[:2]
    cy_int = int(round(cy))
    cx_int = int(round(cx))
    top = max(0, cy_int - half)
    left = max(0, cx_int - half)
    bottom = min(h, cy_int + half)
    right = min(w, cx_int + half)
    template = image[top:bottom, left:right].copy()
    return template, (top, left), (cx - left, cy - top)


def _resample_to_pixel_size(img, src_pixel_um, tgt_pixel_um):
    """Resample img from src to tgt pixel size (cubic interp)."""
    scale = src_pixel_um / tgt_pixel_um
    h, w = img.shape[:2]
    new_h = max(8, int(round(h * scale)))
    new_w = max(8, int(round(w * scale)))
    return cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_CUBIC)


# ── NCC with triple gate + sub-pixel peak refinement ──────────────

def _to_u8(a):
    a = a.astype(np.float32)
    hi = a.max()
    if hi <= 0:
        return np.zeros_like(a, dtype=np.uint8)
    return (a / hi * 255).astype(np.uint8)


def _ncc_match(target_img, template, *,
               template_centre_xy_px,
               search_center_xy_px, search_radius_px,
               peak_min, ratio_min):
    t8 = _to_u8(target_img)
    k8 = _to_u8(template)
    th, tw = t8.shape
    kh, kw = k8.shape
    if kh >= th or kw >= tw:
        return {"ok": False, "reason": "template >= target image",
                "match_xy_px": None, "peak_val": None, "ratio": None}

    result = cv2.matchTemplate(t8, k8, cv2.TM_CCOEFF_NORMED)
    rh, rw = result.shape

    tcx, tcy = template_centre_xy_px
    cx_px, cy_px = search_center_xy_px
    exp_col = cx_px - tcx
    exp_row = cy_px - tcy

    mask = np.zeros_like(result, dtype=bool)
    col_lo = max(0, int(round(exp_col - search_radius_px)))
    col_hi = min(rw, int(round(exp_col + search_radius_px)) + 1)
    row_lo = max(0, int(round(exp_row - search_radius_px)))
    row_hi = min(rh, int(round(exp_row + search_radius_px)) + 1)
    if col_hi <= col_lo or row_hi <= row_lo:
        return {"ok": False, "reason": "empty search window",
                "match_xy_px": None, "peak_val": None, "ratio": None}
    mask[row_lo:row_hi, col_lo:col_hi] = True

    masked = np.where(mask, result, -np.inf)
    peak_flat = int(np.argmax(masked))
    peak_row, peak_col = np.unravel_index(peak_flat, result.shape)
    peak_val = float(result[peak_row, peak_col])

    # Sub-pixel parabolic refinement
    sub_dcol, sub_drow = 0.0, 0.0
    if 0 < peak_col < rw - 1:
        vL = float(result[peak_row, peak_col - 1])
        vR = float(result[peak_row, peak_col + 1])
        denom = 2 * peak_val - vL - vR
        if abs(denom) > 1e-10:
            sub_dcol = float((vL - vR) / (2 * denom))
    if 0 < peak_row < rh - 1:
        vU = float(result[peak_row - 1, peak_col])
        vD = float(result[peak_row + 1, peak_col])
        denom = 2 * peak_val - vU - vD
        if abs(denom) > 1e-10:
            sub_drow = float((vU - vD) / (2 * denom))
    sub_dcol = max(-1.0, min(1.0, sub_dcol))
    sub_drow = max(-1.0, min(1.0, sub_drow))
    peak_col_f = peak_col + sub_dcol
    peak_row_f = peak_row + sub_drow

    # Second peak
    exclude_r = max(3, int(round(min(kh, kw) * 0.5)))
    second = masked.copy()
    r_lo = max(0, peak_row - exclude_r)
    r_hi = min(rh, peak_row + exclude_r + 1)
    c_lo = max(0, peak_col - exclude_r)
    c_hi = min(rw, peak_col + exclude_r + 1)
    second[r_lo:r_hi, c_lo:c_hi] = -np.inf
    second_val = float(np.max(second))
    ratio = (peak_val / second_val) if second_val > 1e-6 else float("inf")

    match_cx = peak_col_f + tcx
    match_cy = peak_row_f + tcy

    if peak_val < peak_min:
        reason = f"NCC peak {peak_val:.3f} < {peak_min}"
        ok = False
    elif ratio < ratio_min:
        reason = f"peak/second-peak {ratio:.2f} < {ratio_min}"
        ok = False
    else:
        dist = math.hypot(match_cx - cx_px, match_cy - cy_px)
        if dist > search_radius_px:
            reason = (f"match {dist:.1f} px outside search radius "
                      f"{search_radius_px:.0f}")
            ok = False
        else:
            reason = None
            ok = True

    return {"ok": ok, "reason": reason,
            "match_xy_px": (float(match_cx), float(match_cy)),
            "peak_val": peak_val, "ratio": ratio}


# ── Overlay ───────────────────────────────────────────────────────

def _save_overlay(png_path, source_img, source_prop, final_target_img,
                  match_peak, match_ratio, correction_um):
    fig, axes = plt.subplots(1, 2, figsize=(12, 6))

    ax = axes[0]
    ax.imshow(source_img, cmap="gray")
    min_r, min_c, max_r, max_c = source_prop.bbox
    ax.add_patch(Rectangle((min_c, min_r), max_c - min_c, max_r - min_r,
                           edgecolor="lime", facecolor="none", linewidth=1.5))
    sy, sx = source_prop.centroid
    ax.plot(sx, sy, "r+", markersize=18, markeredgewidth=2)
    sh, sw = source_img.shape[:2]
    ax.axvline(sw / 2.0, color="white", linewidth=0.5, alpha=0.3)
    ax.axhline(sh / 2.0, color="white", linewidth=0.5, alpha=0.3)
    ax.set_title("Source 10x: picked cell")
    ax.axis("off")

    ax = axes[1]
    ax.imshow(final_target_img, cmap="gray")
    th, tw = final_target_img.shape[:2]
    ax.plot(tw / 2.0, th / 2.0, "c+", markersize=18, markeredgewidth=2)
    ax.axvline(tw / 2.0, color="white", linewidth=0.5, alpha=0.3)
    ax.axhline(th / 2.0, color="white", linewidth=0.5, alpha=0.3)
    corr_mag = math.hypot(*correction_um) if correction_um else 0.0
    ax.set_title(
        f"Target final 20x — NCC peak {match_peak:.2f} ratio {match_ratio:.1f}, "
        f"correction {corr_mag:.1f} um"
    )
    ax.axis("off")

    fig.tight_layout()
    fig.savefig(png_path, dpi=120)
    plt.close(fig)


# ── Main ──────────────────────────────────────────────────────────

def main():
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    args = parse_args()

    out_dir = args.output_dir or _default_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.source_slot == args.target_slot:
        _abort("source-slot and target-slot must differ.")

    cfg = drv.load_objective_offsets()

    client = lasx_api.LasxApiClientPyModel
    if not client.Connect("PythonClient"):
        _abort("Cannot connect to LAS X.", 2)
    if not drv.ping(client):
        _abort("LAS X ping failed.", 2)

    _check_image_orientation()

    hw = drv.get_hardware_info(client)
    if not hw:
        _abort("Could not read hardware info.", 2)

    drv.set_stage_limits(
        x_min=1000, x_max=130000,
        y_min=1000, y_max=100000,
        z_galvo_min=-200, z_galvo_max=200,
        z_wide_min=0, z_wide_max=25000,
    )

    idle = drv.check_idle(client, timeout=5.0)
    if not idle or not idle.get("success"):
        _abort(f"LAS X not idle: {idle}")

    drv.validate_slots(hw, args.source_slot, [args.target_slot])

    print(f"Job:           {args.job}")
    print(f"Source slot:   {args.source_slot}")
    print(f"Target slot:   {args.target_slot}")
    print(f"Targeting:     GALVO PAN (single-pass, NCC align)")
    print(f"Output dir:    {out_dir}\n")

    # ─── 1. Source 10x: pick cell + template ──────────────────────
    log.info("switching to source objective")
    drv.set_objective(client, args.job, hw, slot_index=args.source_slot)
    time.sleep(args.settle)
    drv.set_zoom(client, args.job, 1.0)
    time.sleep(0.5)

    stage = drv.get_xy(client)
    src_stage_xy_um = (stage["x_um"], stage["y_um"])
    geo_src = drv.parse_tile_geometry(drv.get_job_settings(client, args.job) or {})
    src_pixel_size_um = geo_src["pixel_w_um"]
    src_image_size = geo_src["pixels_x"]
    log.info("source: stage=(%.3f, %.3f) pixel=%.4f um size=%d",
             *src_stage_xy_um, src_pixel_size_um, src_image_size)

    log.info("acquiring source frame")
    src_img, src_path = _acquire_one(client, args.job)
    tifffile.imwrite(str(out_dir / "source.tif"), src_img)

    log.info("Cellpose pick (gpu=%s)", not args.no_gpu)
    t0 = time.perf_counter()
    model = models.CellposeModel(gpu=not args.no_gpu)
    masks, _, _ = model.eval(src_img, diameter=args.diameter)
    log.info("Cellpose: %d cell(s) in %.1fs",
             int(masks.max()), time.perf_counter() - t0)

    prop = _pick_nearest_cell(masks, src_img.shape, target_pixel=args.pick_pixel)
    if prop is None:
        _abort("no cells found; move to a denser region or adjust --diameter")

    cy_px, cx_px = prop.centroid
    min_r, min_c, max_r, max_c = prop.bbox
    bbox_w_um = (max_c - min_c) * src_pixel_size_um
    bbox_h_um = (max_r - min_r) * src_pixel_size_um
    log.info("picked: centroid=(%.1f, %.1f) px  bbox=(%.1f x %.1f) um",
             cy_px, cx_px, bbox_w_um, bbox_h_um)

    template_src, template_origin, template_centre_xy = _extract_template(
        src_img, prop.centroid, prop.bbox, args.template_pad,
    )
    log.info("template: %s px  centroid_in_template=(%.2f, %.2f)",
             template_src.shape, *template_centre_xy)

    # Calibration-predicted cell XY in source and target frames
    cell_source_xy_um = drv.pixel_to_stage_xy_um(
        cx_px, cy_px,
        stage_xy_um=src_stage_xy_um,
        pixel_size_um=src_pixel_size_um,
        image_size=src_image_size,
        config=cfg,
    )
    cell_target_xy_um_initial = drv.translate_stage_xy_between_objectives(
        *cell_source_xy_um, cfg,
        from_slot=args.source_slot, to_slot=args.target_slot,
    )
    log.info("cell source-frame=(%.3f, %.3f)  target-frame (predicted)=(%.3f, %.3f)",
             *cell_source_xy_um, *cell_target_xy_um_initial)

    # ─── 2. Intermediate 20x: aim + acquire + NCC register ────────
    log.info("switching to target objective")
    drv.set_objective(client, args.job, hw, slot_index=args.target_slot)
    time.sleep(args.settle)

    target_base_fov_m = drv.get_base_fov(client, args.job)
    if not target_base_fov_m:
        _abort("Could not read target base FOV.")
    target_base_fov_um = target_base_fov_m[0] * 1e6
    pan_scale_um = drv.pan_scale_um_from_base_fov(target_base_fov_um)
    max_pan_um = drv.PAN_LIMIT * pan_scale_um

    # Intermediate zoom that gets target pixel size close to source.
    # We downsample the intermediate to source pixel size for NCC — this
    # empirically gives much higher NCC peaks (0.96+) than acquiring at
    # matched native format (0.12), because LAS X's SNR / line dwell
    # behaviour seems tied to format 512. Keep format alone, resample
    # post-acquisition.
    ideal_intermediate_zoom = (
        target_base_fov_um / (src_pixel_size_um * src_image_size)
    )
    intermediate_zoom = max(1, int(round(ideal_intermediate_zoom)))
    intermediate_fov_um = target_base_fov_um / intermediate_zoom
    intermediate_pixel_size_um = intermediate_fov_um / src_image_size
    resample_factor = intermediate_pixel_size_um / src_pixel_size_um
    log.info("intermediate zoom=%d  FOV=%.1f um  pixel=%.4f um  "
             "(down-sample to source by %.2fx before NCC)",
             intermediate_zoom, intermediate_fov_um,
             intermediate_pixel_size_um, 1.0 / resample_factor)

    # ZOOM FIRST, then pan
    log.info("set_zoom(%d) then move_xy_galvo to predicted target XY",
             intermediate_zoom)
    drv.set_zoom(client, args.job, intermediate_zoom)

    # Reachability check before aiming
    cur_xy = drv.get_xy(client)
    cur = (cur_xy["x_um"], cur_xy["y_um"])
    off0 = (cell_target_xy_um_initial[0] - cur[0],
            cell_target_xy_um_initial[1] - cur[1])
    if abs(off0[0]) > max_pan_um or abs(off0[1]) > max_pan_um:
        _abort(f"cell outside galvo range (pan would need "
               f"({off0[0]:.1f}, {off0[1]:.1f}) um, max ±{max_pan_um:.0f} um). "
               f"Pick a cell closer to centre or use the stage sibling.")

    r_pan = drv.move_xy_galvo(client, *cell_target_xy_um_initial, unit="um",
                              job_name=args.job)
    if not r_pan.get("success"):
        _abort(f"intermediate move_xy_galvo failed: {r_pan.get('message')}")

    log.info("acquiring intermediate frame")
    int_img, int_path = _acquire_one(client, args.job)
    tifffile.imwrite(str(out_dir / "target_intermediate.tif"), int_img)

    # Downsample intermediate to source pixel size for NCC.
    int_for_match = _resample_to_pixel_size(
        int_img, intermediate_pixel_size_um, src_pixel_size_um,
    )
    # Save the downsampled intermediate so the user can visually compare
    # it against source.tif at matched pixel size.
    tifffile.imwrite(str(out_dir / "target_intermediate_matched.tif"),
                     int_for_match.astype(int_img.dtype))
    mh, mw = int_for_match.shape[:2]
    search_radius_px = args.search_radius_um / src_pixel_size_um
    match = _ncc_match(
        int_for_match, template_src,
        template_centre_xy_px=template_centre_xy,
        search_center_xy_px=(mw / 2.0, mh / 2.0),
        search_radius_px=search_radius_px,
        peak_min=args.ncc_peak_min,
        ratio_min=args.ncc_ratio_min,
    )

    # Diagnostic overlay regardless of gate pass/fail — shows the
    # predicted centre (cyan cross) and the NCC match location (green
    # cross) on the downsampled intermediate. Lets the user see by eye
    # whether the match landed on a plausible cell.
    fig, ax = plt.subplots(1, 1, figsize=(8, 8))
    ax.imshow(int_for_match, cmap="gray")
    ax.plot(mw / 2.0, mh / 2.0, "c+", markersize=20, markeredgewidth=2,
            label="predicted centre (aim)")
    if match["match_xy_px"] is not None:
        mcx, mcy = match["match_xy_px"]
        ax.plot(mcx, mcy, "g+", markersize=20, markeredgewidth=2,
                label=f"NCC match (peak {match['peak_val']:.2f} "
                      f"ratio {match['ratio']:.2f})")
        # Draw the template bbox at the match location for scale
        from matplotlib.patches import Rectangle as _Rect
        th_t, tw_t = template_src.shape
        tcx, tcy = template_centre_xy
        ax.add_patch(_Rect((mcx - tcx, mcy - tcy), tw_t, th_t,
                           edgecolor="lime", facecolor="none", linewidth=1.2))
    ax.set_title(f"Downsampled intermediate vs template "
                 f"(pixel = {src_pixel_size_um:.3f} um — matched to source)")
    ax.legend(loc="upper right", fontsize=8)
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(out_dir / "ncc_diagnostic.png", dpi=120)
    plt.close(fig)
    log.info("NCC: peak=%s ratio=%s match=%s",
             None if match["peak_val"] is None else f"{match['peak_val']:.3f}",
             None if match["ratio"]    is None else f"{match['ratio']:.2f}",
             match["match_xy_px"])
    if not match["ok"]:
        _abort(f"NCC gate failed: {match['reason']}. Source template probably "
               f"wasn't visible in the intermediate frame — increase "
               f"--search-radius-um, widen --template-pad, or pick a more "
               f"distinctive cell.")

    # Convert the match pixel (at source pixel size) to a target-frame
    # stage XY. The stage hasn't moved since the objective switch, so
    # `get_xy` still reports the target-frame coord we need.
    stage_now = drv.get_xy(client)
    match_px = match["match_xy_px"]
    cell_target_xy_um_corrected = drv.pixel_to_stage_xy_um(
        match_px[0], match_px[1],
        stage_xy_um=(stage_now["x_um"], stage_now["y_um"]),
        pixel_size_um=src_pixel_size_um,
        image_size=mw,
        config=cfg,
    )
    correction_um = (cell_target_xy_um_corrected[0] - cell_target_xy_um_initial[0],
                     cell_target_xy_um_corrected[1] - cell_target_xy_um_initial[1])
    log.info("calibration residual correction: (%+.3f, %+.3f) um  mag=%.3f",
             *correction_um, math.hypot(*correction_um))

    # ─── 3. Final 20x: zoom first, then pan to corrected XY ───────
    final_zoom = drv.bbox_to_zoom(
        bbox_w_um, bbox_h_um, target_base_fov_um, margin=args.fov_bbox_margin,
    )
    log.info("final zoom=%d  FOV=%.1f um",
             final_zoom, target_base_fov_um / final_zoom)
    drv.set_zoom(client, args.job, final_zoom)
    r_pan_final = drv.move_xy_galvo(client, *cell_target_xy_um_corrected,
                                    unit="um", job_name=args.job)
    if not r_pan_final.get("success"):
        log.warning("final move_xy_galvo failed: %s", r_pan_final.get("message"))

    log.info("acquiring final frame")
    final_img, final_path = _acquire_one(client, args.job)
    tifffile.imwrite(str(out_dir / "target_final.tif"), final_img)

    # ─── Outputs ──────────────────────────────────────────────────
    _save_overlay(out_dir / "overlay.png", src_img, prop, final_img,
                  match["peak_val"], match["ratio"], correction_um)

    summary = {
        "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "method": "galvo_pan_single_pass_ncc",
        "job": args.job,
        "source_slot": args.source_slot,
        "target_slot": args.target_slot,
        "source_stage_xy_um": list(src_stage_xy_um),
        "source_pixel_size_um": src_pixel_size_um,
        "source_image_size_px": src_image_size,
        "picked_cell": {
            "centroid_px": [cy_px, cx_px],
            "bbox_px": [min_r, min_c, max_r, max_c],
            "bbox_um": [bbox_w_um, bbox_h_um],
            "area_px": int(prop.area),
            "template_origin_px": list(template_origin),
            "template_shape_px": list(template_src.shape),
        },
        "cell_source_xy_um": list(cell_source_xy_um),
        "cell_target_xy_um_initial_predicted": list(cell_target_xy_um_initial),
        "cell_target_xy_um_corrected": list(cell_target_xy_um_corrected),
        "calibration_residual_um": list(correction_um),
        "calibration_residual_magnitude_um": math.hypot(*correction_um),
        "intermediate": {
            "zoom": intermediate_zoom,
            "fov_um": intermediate_fov_um,
            "pixel_size_um": intermediate_pixel_size_um,
            "registered_at_pixel_size_um": src_pixel_size_um,
            "target_downsample_factor": 1.0 / resample_factor,
            "ncc_peak": match["peak_val"],
            "ncc_ratio": match["ratio"],
            "match_xy_px_at_source_res": list(match_px),
            "downsampled_image_size_px": mw,
        },
        "final": {
            "zoom": final_zoom,
            "fov_um": target_base_fov_um / final_zoom,
            "pan": list(r_pan_final.get("pan") or (None, None)),
        },
        "pan_scale_um": pan_scale_um,
        "pan_max_reachable_um": max_pan_um,
        "fov_bbox_margin": args.fov_bbox_margin,
        "offsets_config": str(drv.default_current_path()),
        "outputs": {
            "source_tif": str(out_dir / "source.tif"),
            "target_intermediate_tif": str(out_dir / "target_intermediate.tif"),
            "target_final_tif": str(out_dir / "target_final.tif"),
            "overlay_png": str(out_dir / "overlay.png"),
            "source_lasx_tif": str(src_path),
            "target_intermediate_lasx_tif": str(int_path),
            "target_lasx_tif": str(final_path),
        },
    }
    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True)

    print(f"\nNCC peak: {match['peak_val']:.3f}  ratio: {match['ratio']:.2f}")
    print(f"Calibration residual: ({correction_um[0]:+.2f}, "
          f"{correction_um[1]:+.2f}) um  mag={math.hypot(*correction_um):.2f} um")
    print(f"\nSource       : {out_dir / 'source.tif'}")
    print(f"Intermediate : {out_dir / 'target_intermediate.tif'}")
    print(f"Final        : {out_dir / 'target_final.tif'}")
    print(f"Overlay      : {out_dir / 'overlay.png'}")
    print(f"Summary      : {out_dir / 'summary.json'}")

    if not args.no_restore:
        log.info("restoring source objective")
        drv.set_objective(client, args.job, hw, slot_index=args.source_slot)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)

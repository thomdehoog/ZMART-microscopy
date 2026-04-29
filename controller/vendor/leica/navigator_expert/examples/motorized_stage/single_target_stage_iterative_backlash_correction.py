"""
Single-target objective switch with iterative NCC refinement, with stage
backlash correction applied before every acquisition.
=======================================================================

Identical recipe to ``single_target_stage_iterative.py``, with one extra
step: just before each acquisition (source, every refinement iteration,
and the final framed image), the stage performs a takeup move that
drives it to ``(x - overshoot, y - overshoot)`` and back to ``(x, y)``.
This pins the slack-state of both leadscrews to the +X+Y side, so all
NCC measurements are made from a consistent mechanical state.

Yesterday's iterative cookbook hit a 1-2 um noise floor because each
refinement step reversed direction on at least one axis, eating
backlash on the way back. With takeup before every acquire, all NCC
measurements share the same slack-state and the loop should converge
below 1 um.

See ``vendor/leica/docs/session_notes_20260428_backlash_correction.md``
for the full reasoning.

Usage
-----
    python single_target_stage_iterative_backlash_correction.py --job HiRes \\
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

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import cv2
import matplotlib
import numpy as np
import tifffile
from cellpose import models
from skimage.measure import regionprops

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from LasxApi import PYLICamApiConnector as lasx_api
import navigator_expert.driver as drv


log = logging.getLogger("single_target_stage_iterative_backlash_correction")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description=(
            "Single-target objective switch on the motorized stage with "
            "iterative NCC refinement and backlash correction before "
            "every acquisition."
        )
    )
    p.add_argument("--job", required=True,
                   help="LAS X job name. Must already be selected in LAS X.")
    p.add_argument("--source-slot", type=int, required=True)
    p.add_argument("--target-slot", type=int, required=True)

    p.add_argument("--fov-bbox-margin", type=float, default=1.5,
                   help="Final target FOV = margin x source bbox "
                        "(default: 1.5).")
    p.add_argument("--template-pad", type=float, default=2.5,
                   help="Template size = pad x bbox (default: 2.5).")

    p.add_argument("--max-iterations", type=int, default=4,
                   help="Max refinement iterations (default: 4). "
                        "Set 0 to skip refinement entirely.")
    p.add_argument("--converge-um", type=float, default=1.0,
                   help="Stop when |correction| < this (default: 1.0).")
    p.add_argument("--min-improvement-um", type=float, default=0.5,
                   help="Stop when an iteration improves the correction "
                        "magnitude by less than this (default: 0.5).")

    p.add_argument("--ncc-peak-min", type=float, default=0.4,
                   help="Reject NCC match below this peak (default: 0.4).")
    p.add_argument("--ncc-ratio-min", type=float, default=1.3,
                   help="Reject if peak / second-peak ratio is below this "
                        "(default: 1.3).")
    p.add_argument("--search-radius-um", type=float, default=50.0,
                   help="NCC search radius around the image center "
                        "(default: 50 um).")

    p.add_argument("--diameter", type=float, default=None,
                   help="Cellpose diameter in pixels (default: auto).")
    p.add_argument("--pick-pixel", type=int, nargs=2, default=None,
                   metavar=("ROW", "COL"),
                   help="Pick the cell nearest this source pixel. Default: "
                        "nearest image center.")
    p.add_argument("--no-gpu", action="store_true",
                   help="Disable GPU for Cellpose.")
    p.add_argument("--settle", type=float, default=3.0,
                   help="Seconds after objective switch (default: 3).")
    p.add_argument("--stage-tolerance-um", type=float, default=20.0,
                   help="Stage readback tolerance for the coarse target "
                        "move (default: 20 um). Refinement moves use a "
                        "tighter tolerance derived from --converge-um.")

    p.add_argument("--backlash-overshoot-um", type=float, default=50.0,
                   help="Takeup overshoot distance in -X-Y before the final "
                        "+X+Y leg (default: 50 um).")
    p.add_argument("--backlash-settle-ms", type=int, default=100,
                   help="Pause between overshoot and final leg in ms "
                        "(default: 100).")

    p.add_argument("--output-dir", type=Path, default=None,
                   help="Output directory (default: "
                        "config/cookbook/motorized_stage_iterative/<ts>"
                        "_backlash_correction).")
    p.add_argument("--no-restore", action="store_true",
                   help="Do not switch back to source objective at the end.")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _abort(msg, code=1):
    print(f"ABORT: {msg}")
    sys.exit(code)


def _default_output_dir():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return (Path(__file__).resolve().parents[3]
            / "config" / "cookbook" / "motorized_stage_iterative"
            / f"{ts}_backlash_correction")


def _write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(path)


def _check_image_orientation():
    settings = drv.get_lasx_settings() or {}
    orient = settings.get("image_orientation", {})
    if orient.get("enable_transform", False) and \
            orient.get("transformation", "TOPLEFT") != "TOPLEFT":
        _abort(f"ImageTransformation is '{orient.get('transformation')}'; "
               f"set it to TOPLEFT in LAS X Advanced Settings.", 2)


def correct_backlash(client, overshoot_um=50.0, settle_ms=100,
                     tolerance_um=20.0):
    """Pin the stage to the +X+Y slack-state with no net displacement.

    Reads current XY, drives to ``(x - overshoot, y - overshoot)``, pauses,
    then drives back to ``(x, y)``. The final +X +Y leg engages both
    leadscrews against the same flank, removing backlash variance.
    """
    pos = drv.get_xy(client)
    x, y = pos["x_um"], pos["y_um"]
    log.info("backlash takeup at (%.2f, %.2f) um, overshoot %.1f um",
             x, y, overshoot_um)
    r = drv.move_xy_stage(client, x - overshoot_um, y - overshoot_um,
                          unit="um", tolerance=tolerance_um)
    if not r or not r.get("success"):
        raise RuntimeError(f"backlash overshoot move failed: {r}")
    time.sleep(settle_ms / 1000.0)
    r = drv.move_xy_stage(client, x, y, unit="um", tolerance=tolerance_um)
    if not r or not r.get("success"):
        raise RuntimeError(f"backlash return move failed: {r}")


def _acquire_one(client, job_name):
    baseline = drv.read_relative_path(client)
    t_start = time.time()
    result = drv.acquire(client, job_name)
    if not result or not result.get("success"):
        raise RuntimeError(f"acquire failed: {result}")

    media = drv.get_lasx_settings()["export"]["media_path"]
    detected = drv.detect_new_files(
        client, baseline, media, acquire_start=t_start,
    )
    if not detected["success"]:
        raise RuntimeError(f"file detection failed: {detected.get('error')}")

    files = sorted(detected["image_files"])
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
    return min(
        props,
        key=lambda p: (p.centroid[0] - target_row) ** 2
                      + (p.centroid[1] - target_col) ** 2,
    )


def _segment_pick(img, model, args):
    log.info("Cellpose pick")
    masks, _, _ = model.eval(img, diameter=args.diameter)
    prop = _pick_nearest_cell(masks, img.shape, args.pick_pixel)
    if prop is None:
        _abort("no cells found; move to a denser region or adjust diameter")
    return masks, prop


def _measure_target_error_um(img, pixel_size_um, model, args):
    masks, _, _ = model.eval(img, diameter=args.diameter)
    prop = _pick_nearest_cell(masks, img.shape)
    if prop is None:
        return None
    h, w = img.shape[:2]
    cy, cx = prop.centroid
    dx_um = (cx - w / 2.0) * pixel_size_um
    dy_um = (cy - h / 2.0) * pixel_size_um
    return {
        "centroid_px": [float(cy), float(cx)],
        "offset_from_center_px": [float(cx - w / 2.0), float(cy - h / 2.0)],
        "offset_from_center_image_um": [float(dx_um), float(dy_um)],
        "distance_from_center_um": float(math.hypot(dx_um, dy_um)),
    }


# ---------------------------------------------------------------------------
# Template + NCC
# ---------------------------------------------------------------------------

def _extract_template(image, centroid, bbox, pad_factor):
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
    if template.size == 0:
        raise ValueError("template crop is empty")
    return template, (top, left), (cx - left, cy - top)


def _resample_to_pixel_size(img, src_pixel_um, tgt_pixel_um):
    scale = float(src_pixel_um) / float(tgt_pixel_um)
    h, w = img.shape[:2]
    new_h = max(8, int(round(h * scale)))
    new_w = max(8, int(round(w * scale)))
    interp = cv2.INTER_CUBIC if scale > 1.0 else cv2.INTER_AREA
    return cv2.resize(img, (new_w, new_h), interpolation=interp)


def _to_u8(a):
    a = a.astype(np.float32)
    if a.size == 0:
        return np.zeros_like(a, dtype=np.uint8)
    lo, hi = np.percentile(a, (1.0, 99.8))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        lo, hi = float(a.min()), float(a.max())
    if hi <= lo:
        return np.zeros_like(a, dtype=np.uint8)
    a = np.clip((a - lo) / (hi - lo), 0.0, 1.0)
    return (a * 255).astype(np.uint8)


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

    sub_dcol, sub_drow = 0.0, 0.0
    if 0 < peak_col < rw - 1:
        v_l = float(result[peak_row, peak_col - 1])
        v_r = float(result[peak_row, peak_col + 1])
        denom = 2 * peak_val - v_l - v_r
        if abs(denom) > 1e-10:
            sub_dcol = float((v_l - v_r) / (2 * denom))
    if 0 < peak_row < rh - 1:
        v_u = float(result[peak_row - 1, peak_col])
        v_d = float(result[peak_row + 1, peak_col])
        denom = 2 * peak_val - v_u - v_d
        if abs(denom) > 1e-10:
            sub_drow = float((v_u - v_d) / (2 * denom))
    sub_dcol = max(-1.0, min(1.0, sub_dcol))
    sub_drow = max(-1.0, min(1.0, sub_drow))
    peak_col_f = peak_col + sub_dcol
    peak_row_f = peak_row + sub_drow

    exclude_r = max(3, int(round(min(kh, kw) * 0.5)))
    second = masked.copy()
    second[max(0, peak_row - exclude_r):min(rh, peak_row + exclude_r + 1),
           max(0, peak_col - exclude_r):min(rw, peak_col + exclude_r + 1)] = -np.inf
    second_val = float(np.max(second))
    ratio = (peak_val / second_val) if second_val > 1e-6 else float("inf")

    match_cx = peak_col_f + tcx
    match_cy = peak_row_f + tcy
    dist = math.hypot(match_cx - cx_px, match_cy - cy_px)

    if peak_val < peak_min:
        ok, reason = False, f"NCC peak {peak_val:.3f} < {peak_min}"
    elif ratio < ratio_min:
        ok, reason = False, f"peak/second-peak {ratio:.2f} < {ratio_min}"
    elif dist > search_radius_px:
        ok = False
        reason = f"match {dist:.1f} px outside search radius {search_radius_px:.0f}"
    else:
        ok, reason = True, None

    return {"ok": ok, "reason": reason,
            "match_xy_px": (float(match_cx), float(match_cy)),
            "peak_val": peak_val, "ratio": ratio}


# ---------------------------------------------------------------------------
# Refinement loop
# ---------------------------------------------------------------------------

def _refine(client, job_name, template_src, template_centre_xy,
            src_pixel_size_um, intermediate_pixel_size_um,
            *, max_iterations, converge_um, min_improvement_um,
            peak_min, ratio_min, search_radius_um, output_dir, cfg,
            backlash_overshoot_um, backlash_settle_ms, backlash_tolerance_um):
    iter_log = []
    last_img = None
    prev_mag = None

    for i in range(1, max_iterations + 1):
        log.info("refine iter %d/%d: acquiring", i, max_iterations)
        correct_backlash(client,
                         overshoot_um=backlash_overshoot_um,
                         settle_ms=backlash_settle_ms,
                         tolerance_um=backlash_tolerance_um)
        img, _ = _acquire_one(client, job_name)
        last_img = img
        tifffile.imwrite(str(output_dir / f"target_iter{i:02d}.tif"), img)

        img_for_match = _resample_to_pixel_size(
            img, intermediate_pixel_size_um, src_pixel_size_um,
        )
        mh, mw = img_for_match.shape[:2]
        search_radius_px = search_radius_um / src_pixel_size_um

        match = _ncc_match(
            img_for_match, template_src,
            template_centre_xy_px=template_centre_xy,
            search_center_xy_px=(mw / 2.0, mh / 2.0),
            search_radius_px=search_radius_px,
            peak_min=peak_min, ratio_min=ratio_min,
        )
        log.info("  NCC peak=%.3f ratio=%.2f match=%s",
                 match["peak_val"] if match["peak_val"] is not None else float("nan"),
                 match["ratio"] if match["ratio"] is not None else float("nan"),
                 match["match_xy_px"])

        if not match["ok"]:
            raise RuntimeError(f"refinement iter {i}: {match['reason']}")

        stage_xy = drv.get_xy(client)
        current = (stage_xy["x_um"], stage_xy["y_um"])
        match_px = match["match_xy_px"]
        cell_stage = drv.pixel_to_stage_xy_um(
            match_px[0], match_px[1],
            stage_xy_um=current,
            pixel_size_um=src_pixel_size_um,
            image_size=mw,
            config=cfg,
        )
        correction = (cell_stage[0] - current[0], cell_stage[1] - current[1])
        mag = math.hypot(*correction)
        log.info("  iter %d: correction_um=(%+.3f, %+.3f)  mag=%.3f",
                 i, correction[0], correction[1], mag)

        iter_log.append({
            "iteration": i,
            "match_peak": match["peak_val"],
            "match_ratio": match["ratio"],
            "match_xy_px_at_source_res": list(match_px),
            "downsampled_image_size_px": mw,
            "stage_before_um": list(current),
            "cell_stage_um": list(cell_stage),
            "correction_um": list(correction),
            "correction_um_mag": mag,
        })

        if mag < converge_um:
            log.info("  converged: |correction| %.3f < %.2f um", mag, converge_um)
            break

        if prev_mag is not None and (prev_mag - mag) < min_improvement_um:
            log.info(
                "  stopping at noise floor: %.3f -> %.3f um "
                "(improvement < %.2f)",
                prev_mag, mag, min_improvement_um,
            )
            break

        # Tight tolerance — default 20 um would let small corrections
        # never settle and the loop would oscillate.
        move_tol = max(0.5, converge_um / 2.0)
        log.info("  moving stage by (%+.3f, %+.3f) tol=%.2f",
                 correction[0], correction[1], move_tol)
        move_result = drv.move_xy_stage(
            client, cell_stage[0], cell_stage[1],
            unit="um", tolerance=move_tol,
        )
        if not move_result or not move_result.get("success"):
            log.warning(
                "  stage did not settle within %.2f um after iter %d — "
                "hardware repeatability limit; stopping",
                move_tol, i,
            )
            break
        time.sleep(0.5)
        prev_mag = mag

    return last_img, iter_log


# ---------------------------------------------------------------------------
# Overlay
# ---------------------------------------------------------------------------

def _save_overlay(path, source_img, source_prop,
                  target_img, target_error, iter_log):
    fig, axes = plt.subplots(1, 2, figsize=(12, 6))

    ax = axes[0]
    ax.imshow(source_img, cmap="gray")
    min_r, min_c, max_r, max_c = source_prop.bbox
    ax.add_patch(Rectangle((min_c, min_r), max_c - min_c, max_r - min_r,
                           edgecolor="lime", facecolor="none", linewidth=1.5))
    cy, cx = source_prop.centroid
    ax.plot(cx, cy, "r+", markersize=18, markeredgewidth=2)
    ax.set_title("Source target")
    ax.axis("off")

    ax = axes[1]
    ax.imshow(target_img, cmap="gray")
    h, w = target_img.shape[:2]
    ax.plot(w / 2.0, h / 2.0, "c+", markersize=18, markeredgewidth=2)
    if target_error:
        tc_y, tc_x = target_error["centroid_px"]
        ax.plot(tc_x, tc_y, "r+", markersize=18, markeredgewidth=2)
        title = (f"Landing error {target_error['distance_from_center_um']:.2f} um")
    else:
        title = "Target final"
    if iter_log:
        title += f"  ({len(iter_log)} iter)"
    ax.set_title(title)
    ax.axis("off")

    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    args = parse_args()

    if args.source_slot == args.target_slot:
        _abort("source-slot and target-slot must differ")

    out_dir = args.output_dir or _default_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

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

    print(f"Job:                {args.job}")
    print(f"Source slot:        {args.source_slot}")
    print(f"Target slot:        {args.target_slot}")
    print("Actuator:           motorized XY stage + NCC refinement")
    print(f"Iterations:         {args.max_iterations}  converge<{args.converge_um} um")
    print(f"Backlash overshoot: {args.backlash_overshoot_um:.1f} um")
    print(f"Backlash settle:    {args.backlash_settle_ms} ms")
    print(f"Output dir:         {out_dir}\n")

    log.info("switching to source objective")
    drv.set_objective(client, args.job, hw, slot_index=args.source_slot)
    time.sleep(args.settle)
    drv.set_zoom(client, args.job, 1.0)
    time.sleep(0.5)

    source_stage = drv.get_xy(client)
    src_stage_xy_um = (source_stage["x_um"], source_stage["y_um"])
    source_geo = drv.parse_tile_geometry(
        drv.get_job_settings(client, args.job) or {},
    )
    src_pixel_size_um = float(source_geo["pixel_w_um"])
    src_image_size = int(source_geo["pixels_x"])

    log.info("loading Cellpose (gpu=%s)", not args.no_gpu)
    cp_model = models.CellposeModel(gpu=not args.no_gpu)

    correct_backlash(client,
                     overshoot_um=args.backlash_overshoot_um,
                     settle_ms=args.backlash_settle_ms,
                     tolerance_um=args.stage_tolerance_um)
    src_img, src_path = _acquire_one(client, args.job)
    tifffile.imwrite(str(out_dir / "source.tif"), src_img)

    _, src_prop = _segment_pick(src_img, cp_model, args)
    cy_px, cx_px = src_prop.centroid
    min_r, min_c, max_r, max_c = src_prop.bbox
    bbox_w_um = (max_c - min_c) * src_pixel_size_um
    bbox_h_um = (max_r - min_r) * src_pixel_size_um

    template_src, template_origin, template_centre_xy = _extract_template(
        src_img, src_prop.centroid, src_prop.bbox, args.template_pad,
    )
    log.info("template %s px  centroid_in_template=(%.2f, %.2f)",
             template_src.shape, *template_centre_xy)

    cell_source_xy_um = drv.pixel_to_stage_xy_um(
        cx_px, cy_px,
        stage_xy_um=src_stage_xy_um,
        pixel_size_um=src_pixel_size_um,
        image_size=src_image_size,
        config=cfg,
    )
    cell_target_xy_um = drv.translate_stage_xy_between_objectives(
        *cell_source_xy_um, cfg,
        from_slot=args.source_slot,
        to_slot=args.target_slot,
    )
    log.info("source target XY=(%.3f, %.3f)", *cell_source_xy_um)
    log.info("target objective command XY=(%.3f, %.3f)", *cell_target_xy_um)

    log.info("switching to target objective")
    drv.set_objective(client, args.job, hw, slot_index=args.target_slot)
    time.sleep(args.settle)

    target_base_fov_m = drv.get_base_fov(client, args.job)
    if not target_base_fov_m:
        _abort("Could not read target base FOV.")
    target_base_fov_um = target_base_fov_m[0] * 1e6

    iter_log = []
    intermediate_info = None

    if args.max_iterations >= 1:
        # Intermediate zoom that puts target pixel size near source pixel
        # size, minimising the resample factor for NCC.
        ideal = target_base_fov_um / (src_pixel_size_um * src_image_size)
        intermediate_zoom = max(1, int(round(ideal)))
        intermediate_fov_um = target_base_fov_um / intermediate_zoom
        intermediate_pixel_size_um = intermediate_fov_um / src_image_size
        resample_factor = intermediate_pixel_size_um / src_pixel_size_um
        log.info("intermediate zoom=%d FOV=%.1f um pixel=%.4f um "
                 "(downsample target by %.2fx for NCC)",
                 intermediate_zoom, intermediate_fov_um,
                 intermediate_pixel_size_um, 1.0 / resample_factor)

        drv.set_zoom(client, args.job, intermediate_zoom)
        time.sleep(0.5)

        log.info("coarse stage move to predicted target XY")
        move_result = drv.move_xy_stage(
            client, cell_target_xy_um[0], cell_target_xy_um[1],
            unit="um", tolerance=args.stage_tolerance_um,
        )
        if not move_result or not move_result.get("success"):
            _abort(f"coarse stage move failed: {move_result}")
        time.sleep(0.5)

        _, iter_log = _refine(
            client, args.job, template_src, template_centre_xy,
            src_pixel_size_um, intermediate_pixel_size_um,
            max_iterations=args.max_iterations,
            converge_um=args.converge_um,
            min_improvement_um=args.min_improvement_um,
            peak_min=args.ncc_peak_min,
            ratio_min=args.ncc_ratio_min,
            search_radius_um=args.search_radius_um,
            output_dir=out_dir,
            cfg=cfg,
            backlash_overshoot_um=args.backlash_overshoot_um,
            backlash_settle_ms=args.backlash_settle_ms,
            backlash_tolerance_um=args.stage_tolerance_um,
        )

        intermediate_info = {
            "zoom": intermediate_zoom,
            "fov_um": intermediate_fov_um,
            "pixel_size_um": intermediate_pixel_size_um,
            "registration_at_pixel_size_um": src_pixel_size_um,
            "target_downsample_factor": 1.0 / resample_factor,
            "template_shape_px": list(template_src.shape),
        }
    else:
        log.info("refinement disabled (--max-iterations 0); "
                 "moving stage and going straight to final zoom")
        move_result = drv.move_xy_stage(
            client, cell_target_xy_um[0], cell_target_xy_um[1],
            unit="um", tolerance=args.stage_tolerance_um,
        )
        if not move_result or not move_result.get("success"):
            _abort(f"coarse stage move failed: {move_result}")
        time.sleep(0.5)

    converged = (
        bool(iter_log)
        and iter_log[-1]["correction_um_mag"] < args.converge_um
    )

    final_zoom = drv.bbox_to_zoom(
        bbox_w_um, bbox_h_um, target_base_fov_um,
        margin=args.fov_bbox_margin,
    )
    drv.set_zoom(client, args.job, final_zoom)
    time.sleep(0.5)

    correct_backlash(client,
                     overshoot_um=args.backlash_overshoot_um,
                     settle_ms=args.backlash_settle_ms,
                     tolerance_um=args.stage_tolerance_um)
    final_img, final_path = _acquire_one(client, args.job)
    tifffile.imwrite(str(out_dir / "target_final.tif"), final_img)

    final_geo = drv.parse_tile_geometry(
        drv.get_job_settings(client, args.job) or {},
    )
    final_pixel_size_um = float(final_geo["pixel_w_um"])
    target_error = _measure_target_error_um(
        final_img, final_pixel_size_um, cp_model, args,
    )
    _save_overlay(out_dir / "overlay.png", src_img, src_prop,
                  final_img, target_error, iter_log)

    summary = {
        "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "method": "single_target_stage_iterative_backlash_correction",
        "actuator": "motorized_stage_iterative",
        "job": args.job,
        "source_slot": args.source_slot,
        "target_slot": args.target_slot,
        "source_image_center_xy_um": list(src_stage_xy_um),
        "source_pixel_size_um": src_pixel_size_um,
        "source_image_size_px": src_image_size,
        "picked_cell": {
            "centroid_px": [float(cy_px), float(cx_px)],
            "bbox_px": [int(min_r), int(min_c), int(max_r), int(max_c)],
            "bbox_um": [float(bbox_w_um), float(bbox_h_um)],
            "area_px": int(src_prop.area),
            "template_origin_px": list(template_origin),
            "template_centre_xy_px": list(template_centre_xy),
        },
        "cell_source_xy_um": list(cell_source_xy_um),
        "cell_target_xy_um_initial": list(cell_target_xy_um),
        "intermediate": intermediate_info,
        "iterations": iter_log,
        "converged": converged,
        "backlash_overshoot_um": args.backlash_overshoot_um,
        "backlash_settle_ms": args.backlash_settle_ms,
        "final": {
            "zoom": final_zoom,
            "fov_um": target_base_fov_um / final_zoom,
            "pixel_size_um": final_pixel_size_um,
        },
        "target_error": target_error,
        "outputs": {
            "source_tif": str(out_dir / "source.tif"),
            "target_final_tif": str(out_dir / "target_final.tif"),
            "overlay_png": str(out_dir / "overlay.png"),
            "summary_json": str(out_dir / "summary.json"),
            "source_lasx_tif": str(src_path),
            "target_lasx_tif": str(final_path),
        },
    }
    _write_json(out_dir / "summary.json", summary)

    if iter_log:
        last = iter_log[-1]
        print(f"\nIterations: {len(iter_log)}  "
              f"final |correction| = {last['correction_um_mag']:.3f} um  "
              f"converged = {converged}")
    else:
        print("\nNo refinement iterations ran.")
    if target_error:
        print(f"Landing error: {target_error['distance_from_center_um']:.2f} um")
    print(f"Summary: {out_dir / 'summary.json'}")

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

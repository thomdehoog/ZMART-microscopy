"""
Objective-switch iterative targeting — stage-only, NCC-based refinement.
========================================================================

End-to-end demonstration of sub-µm cell targeting across an objective
switch, using motorized-stage motion and classical image registration
(no ML in the registration path).

Recipe
    1. Switch to source objective; acquire one frame at its configured zoom.
    2. Cellpose segment; pick the nucleus closest to the image centre.
       Cellpose is used ONLY here — to choose which cell to visit. The
       refinement loop that follows is Cellpose-free.
    3. Crop a template from the source image around the picked cell
       (padded by ``--template-pad`` × the cell's bounding box so the
       match is geometrically unique, not just "any cell").
    4. Compute the cell's stage XY in the source frame (sign-convention
       matrix applied) and translate across the objective boundary to a
       target-objective stage command (motor delta applied).
    5. Switch to target objective, set the *intermediate* zoom (wide
       enough to catch the initial miss, narrow enough for good
       registration — principled default below).
    6. Resample the source template once to the target pixel size.
    7. Refine loop (up to ``--max-iterations``):
         a. Acquire at intermediate zoom.
         b. NCC template match (``cv2.matchTemplate`` with
            ``TM_CCOEFF_NORMED``), restricted to the expected region
            (image centre ± miss budget).
         c. Triple gate:
              - peak height ≥ ``--ncc-peak-min``
              - peak-to-second-peak ratio ≥ ``--ncc-ratio-min``
              - peak within expected region
            A gate failure raises — no blind stage moves.
         d. Convert the cell's pixel position in the target to a stage XY
            via ``pixel_to_stage_xy_um`` and compute the stage correction.
         e. If |correction| < ``--converge-um``: break, converged.
            Else: ``move_xy_stage`` by the correction and loop.
    8. Set final zoom (``--fov-bbox-margin`` × bounding box); acquire the
       final framed image.
    9. Save source.tif, target_final.tif, each iteration's target
       acquisition, overlay.png, summary.json.

Intermediate-zoom choice
    Driven by a max resample factor. We upsample the source template to
    match the target pixel size; past ~6× the template becomes too
    blurry for reliable NCC. Choose:

        intermediate_pixel_size_um ≈ source_pixel_size_um / 6
        intermediate_zoom ≈ target_base_fov_um / (intermediate_pixel_size_um × image_size)

    On this scope (source ps = 2.27 µm) that lands around zoom 3 on 20x
    → FOV ~194 µm, ~20× margin on a 9 µm initial miss, template stays
    sharp after 6× upsample.

Operator preconditions
    - ``--job`` currently selected in the LAS X UI.
    - ``ImageTransformation = TOPLEFT`` in LAS X Advanced Settings.
    - AFC / autofocus OFF, no modal dialogs.
    - Stage over a sample region with cells visible at source zoom.
    - ``config/objective_offsets.json`` present (run
      ``measure_objective_offsets.py`` first).

Usage
    python objective_switch_stage_iterative_targeting.py --job Overview \\
        --source-slot 1 --target-slot 2 \\
        [--max-iterations 4] [--converge-um 0.5] [--no-gpu]

Sibling examples will cover galvo / ROI based iterative targeting.
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


log = logging.getLogger("objective_switch_stage_iterative_targeting")


# ── CLI ───────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description=(
            "Iterative stage targeting across an objective switch. "
            "Cellpose picks the cell at the source; the refinement loop "
            "uses NCC template matching and classical image stats."
        )
    )
    p.add_argument("--job", required=True,
                   help="LAS X job name. Must be selected in the LAS X UI.")
    p.add_argument("--source-slot", type=int, required=True)
    p.add_argument("--target-slot", type=int, required=True)

    p.add_argument("--fov-bbox-margin", type=float, default=1.5,
                   help="Final target FOV = margin x nucleus bbox (default: 1.5).")
    p.add_argument("--template-pad", type=float, default=2.5,
                   help="Template size = pad x nucleus bbox "
                        "(default: 2.5 - includes enough context for the "
                        "match to be geometrically unique).")

    p.add_argument("--max-iterations", type=int, default=4,
                   help="Max refinement iterations (default: 4). "
                        "Set 0 to skip refinement entirely: the stage moves "
                        "to the calibrated target XY and the script goes "
                        "straight to the final-zoom acquire (equivalent to "
                        "the non-iterative sibling example).")
    p.add_argument("--converge-um", type=float, default=2.0,
                   help="Converge when |stage correction| < this (default: 2.0). "
                        "This is the practical floor for stage-only targeting on "
                        "this class of motorised stage; asking for sub-um will "
                        "oscillate on stage-repeatability noise.")

    p.add_argument("--ncc-peak-min", type=float, default=0.4,
                   help="Reject NCC match below this correlation peak "
                        "(default: 0.4).")
    p.add_argument("--ncc-ratio-min", type=float, default=1.3,
                   help="Reject if peak / second-peak < this ratio "
                        "(default: 1.3 - catches ambiguous templates).")
    p.add_argument("--search-radius-um", type=float, default=50.0,
                   help="Restrict NCC search to this radius around the "
                        "image centre (default: 50 um - a few x the "
                        "expected initial miss).")

    p.add_argument("--diameter", type=float, default=None,
                   help="Cellpose nucleus diameter in pixels (default: auto).")
    p.add_argument("--no-gpu", action="store_true",
                   help="Disable GPU for Cellpose.")
    p.add_argument("--settle", type=float, default=3.0,
                   help="Seconds after each objective switch (default: 3).")

    p.add_argument("--output-dir", type=Path, default=None,
                   help="Output dir (default: "
                        "config/objective_targeting/iterative/<timestamp>/).")
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
            / "config" / "objective_targeting" / "iterative" / ts)


def _check_image_orientation():
    settings = drv.get_lasx_settings() or {}
    orient = settings.get("image_orientation", {})
    if orient.get("enable_transform", False) and \
            orient.get("transformation", "TOPLEFT") != "TOPLEFT":
        _abort(f"ImageTransformation is '{orient.get('transformation')}'; "
               f"set to TOPLEFT in LAS X Advanced Settings.", 2)


def _acquire_one(client, job_name):
    """Acquire a single frame. Returns (image, path)."""
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


def _pick_central_cell(masks, image_shape):
    props = regionprops(masks)
    if not props:
        return None
    h, w = image_shape[:2]
    cy, cx = h / 2.0, w / 2.0
    return min(props,
               key=lambda p: (p.centroid[0] - cy) ** 2 + (p.centroid[1] - cx) ** 2)


# ── Template extraction and resampling ────────────────────────────

def _extract_template(image, centroid, bbox, pad_factor):
    """Crop a square template around a cell, padded by pad_factor × bbox.

    Returns (template, top_left_px, centroid_in_template_xy_px). The third
    element is the cell centroid's sub-pixel position within the template,
    as (col, row). Callers use it — rather than the template's geometric
    centre (kw/2, kh/2) — when mapping NCC match positions back to the
    cell's physical location, so the sub-pixel rounding done at crop time
    does not bias downstream stage corrections.
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
    # Sub-pixel position of the cell centroid inside the template.
    centre_col = cx - left
    centre_row = cy - top
    return template, (top, left), (centre_col, centre_row)


def _resample_to_pixel_size(template, src_pixel_um, tgt_pixel_um):
    """Resample template from src to tgt pixel size (cubic interp)."""
    scale = src_pixel_um / tgt_pixel_um
    h, w = template.shape[:2]
    new_h = max(8, int(round(h * scale)))
    new_w = max(8, int(round(w * scale)))
    # INTER_CUBIC handles both up- and downsampling reasonably; for very
    # large upsample factors the output is blurry but NCC still works.
    return cv2.resize(template, (new_w, new_h), interpolation=cv2.INTER_CUBIC)


# ── NCC registration with triple gate ─────────────────────────────

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
    """NCC template match with a triple gate.

    Args:
        target_img, template: 2-D arrays (any dtype, converted to u8).
        template_centre_xy_px: (col, row) sub-pixel position of the point
            of interest (e.g. the cell centroid) within the template.
            Using this — rather than the template's geometric centre
            (kw/2, kh/2) — avoids a systematic sub-pixel bias when the
            template was cropped with the centroid rounded to an integer.
        search_center_xy_px: (col, row) where we expect the point of
            interest to appear in the target image (typically the image
            centre after the refinement has aimed there).
        search_radius_px: match must fall within this radius of the search
            centre (in pixels).
        peak_min: minimum acceptable correlation value.
        ratio_min: minimum acceptable peak / second-peak ratio.

    Returns:
        dict with keys:
            ``match_xy_px`` — (col, row) of the POI in the target
            ``peak_val``    — correlation at peak
            ``ratio``       — peak / second-peak
            ``ok``          — True iff all three gates pass
            ``reason``      — None if ok, otherwise a short string
    """
    t8 = _to_u8(target_img)
    k8 = _to_u8(template)
    th, tw = t8.shape
    kh, kw = k8.shape
    if kh >= th or kw >= tw:
        return {"ok": False, "reason": "template larger than target image",
                "match_xy_px": None, "peak_val": None, "ratio": None}

    result = cv2.matchTemplate(t8, k8, cv2.TM_CCOEFF_NORMED)
    rh, rw = result.shape

    # Restrict the allowed peak region to a window around search_center.
    # search_center is the expected POI location; the result-map coordinate
    # of that POI is (cx - tcx, cy - tcy), where (tcx, tcy) is the POI's
    # sub-pixel position inside the template.
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
        return {"ok": False, "reason": "search window empty — bad inputs",
                "match_xy_px": None, "peak_val": None, "ratio": None}
    mask[row_lo:row_hi, col_lo:col_hi] = True

    masked = np.where(mask, result, -np.inf)
    peak_flat = int(np.argmax(masked))
    peak_row, peak_col = np.unravel_index(peak_flat, result.shape)
    peak_val = float(result[peak_row, peak_col])

    # Sub-pixel peak refinement: parabolic fit of the correlation map in
    # each axis. Without this, the integer peak combined with a fractional
    # template centre quantises matches to the template's sub-pixel lattice
    # and the refinement loop oscillates on half-pixel corrections.
    sub_dcol, sub_drow = 0.0, 0.0
    if 0 < peak_col < rw - 1:
        vL = float(result[peak_row, peak_col - 1])
        v0 = peak_val
        vR = float(result[peak_row, peak_col + 1])
        denom = 2 * v0 - vL - vR
        if abs(denom) > 1e-10:
            sub_dcol = float((vL - vR) / (2 * denom))
    if 0 < peak_row < rh - 1:
        vU = float(result[peak_row - 1, peak_col])
        v0 = peak_val
        vD = float(result[peak_row + 1, peak_col])
        denom = 2 * v0 - vU - vD
        if abs(denom) > 1e-10:
            sub_drow = float((vU - vD) / (2 * denom))
    # Clamp the sub-pixel shift to ±1 to reject pathological fits.
    sub_dcol = max(-1.0, min(1.0, sub_dcol))
    sub_drow = max(-1.0, min(1.0, sub_drow))
    peak_col_f = peak_col + sub_dcol
    peak_row_f = peak_row + sub_drow

    # Second peak: same window, exclude a neighbourhood around the peak.
    exclude_r = max(3, int(round(min(kh, kw) * 0.5)))
    second = masked.copy()
    r_lo = max(0, peak_row - exclude_r)
    r_hi = min(rh, peak_row + exclude_r + 1)
    c_lo = max(0, peak_col - exclude_r)
    c_hi = min(rw, peak_col + exclude_r + 1)
    second[r_lo:r_hi, c_lo:c_hi] = -np.inf
    second_val = float(np.max(second))
    ratio = (peak_val / second_val) if second_val > 1e-6 else float("inf")

    # POI (cell centroid) location in the target, in target pixels — using
    # the sub-pixel-refined peak location and the sub-pixel template centre.
    match_cx = peak_col_f + tcx
    match_cy = peak_row_f + tcy

    # Gates
    if peak_val < peak_min:
        reason = (f"NCC peak {peak_val:.3f} < {peak_min} — template "
                  f"doesn't match the target frame well (featureless or "
                  f"wrong content)")
        ok = False
    elif ratio < ratio_min:
        reason = (f"peak-to-second-peak ratio {ratio:.2f} < {ratio_min} — "
                  f"template is not unique in the target (probably a "
                  f"neighbouring cell looks similar)")
        ok = False
    else:
        dist = math.hypot(match_cx - cx_px, match_cy - cy_px)
        if dist > search_radius_px:
            # Shouldn't happen because the mask enforces it, but keep
            # the check for defensive clarity.
            reason = (f"match centre {dist:.1f} px from expected — outside "
                      f"search radius {search_radius_px:.0f} px")
            ok = False
        else:
            reason = None
            ok = True

    return {"ok": ok, "reason": reason,
            "match_xy_px": (float(match_cx), float(match_cy)),
            "peak_val": peak_val, "ratio": ratio}


# ── Overlay ───────────────────────────────────────────────────────

def _save_overlay(png_path, source_img, source_prop,
                  final_target_img, iteration_log):
    """2-panel PNG: source with picked cell, final target with landed cell."""
    fig, axes = plt.subplots(1, 2, figsize=(12, 6))

    ax = axes[0]
    ax.imshow(source_img, cmap="gray")
    ax.set_title("Source: picked cell (green bbox, red cross)")
    min_r, min_c, max_r, max_c = source_prop.bbox
    ax.add_patch(Rectangle((min_c, min_r), max_c - min_c, max_r - min_r,
                           edgecolor="lime", facecolor="none", linewidth=1.5))
    sy, sx = source_prop.centroid
    ax.plot(sx, sy, "r+", markersize=18, markeredgewidth=2)
    sh, sw = source_img.shape[:2]
    ax.axvline(sw / 2.0, color="white", linewidth=0.5, alpha=0.3)
    ax.axhline(sh / 2.0, color="white", linewidth=0.5, alpha=0.3)
    ax.axis("off")

    ax = axes[1]
    ax.imshow(final_target_img, cmap="gray")
    th, tw = final_target_img.shape[:2]
    ax.plot(tw / 2.0, th / 2.0, "c+", markersize=18, markeredgewidth=2)
    ax.axvline(tw / 2.0, color="white", linewidth=0.5, alpha=0.3)
    ax.axhline(th / 2.0, color="white", linewidth=0.5, alpha=0.3)
    last = iteration_log[-1] if iteration_log else None
    if last is not None:
        ax.set_title(
            f"Target (final): converged after {len(iteration_log)} iter(s). "
            f"Last correction = {last['correction_um_mag']:.2f} um"
        )
    else:
        ax.set_title("Target (final): no refinement iterations recorded")
    ax.axis("off")

    fig.tight_layout()
    fig.savefig(png_path, dpi=120)
    plt.close(fig)


# ── Refinement loop ───────────────────────────────────────────────

def _refine(client, job_name, template_src, template_centre_xy,
            src_pixel_size_um, intermediate_pixel_size_um,
            *, max_iterations, converge_um, peak_min, ratio_min,
            search_radius_um, output_dir, cfg):
    """Run the NCC-gated refinement loop. Returns (final_target_img, log).

    The target image is acquired at the intermediate zoom (higher
    resolution than source) and then downsampled to source pixel size
    for registration. That keeps the template sharp and averages noise
    on the target side — better than upsampling the template.
    *template_centre_xy* is the cell centroid's sub-pixel position within
    the source template, used to map NCC matches back to the actual cell
    location without the half-pixel rounding of the template crop.
    """
    iter_log = []
    last_img = None

    for i in range(1, max_iterations + 1):
        log.info("refine iter %d/%d: acquiring", i, max_iterations)
        img, _ = _acquire_one(client, job_name)
        last_img = img
        tifffile.imwrite(str(output_dir / f"target_iter{i:02d}.tif"), img)

        # Downsample target to source pixel size, so NCC runs at source
        # resolution against the native-resolution source template.
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

        # Convert the match position (in downsampled / source-pixel
        # coordinates) to a stage XY via the source pixel size.
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

        # Tight tolerance — default 20 um would let the stage settle
        # anywhere within ±20 um of target, so small corrections would
        # never actually complete and the loop would oscillate.
        log.info("  moving stage by (%+.3f, %+.3f)", *correction)
        move_tol = max(0.5, converge_um / 2.0)
        move_result = drv.move_xy_stage(
            client, cell_stage[0], cell_stage[1],
            unit="um", tolerance=move_tol,
        )
        if not move_result or not move_result.get("success"):
            log.warning(
                "  stage did not settle within %.2f um after iter %d — "
                "hardware repeatability limit; stopping refinement",
                move_tol, i,
            )
            break
        time.sleep(0.5)

    return last_img, iter_log


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

    # move_xy_stage silently no-ops when stage limits aren't set.
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
    print(f"Output dir:    {out_dir}\n")

    # ─── Source pass ─────────────────────────────────────────────
    log.info("switching to source objective")
    drv.set_objective(client, args.job, hw, slot_index=args.source_slot)
    time.sleep(args.settle)

    # Always acquire source at zoom 1 — wide FOV, many cells in view,
    # independent of whatever zoom was left on the job by prior work.
    log.info("setting source zoom to 1.0")
    drv.set_zoom(client, args.job, 1.0)
    time.sleep(0.5)

    stage = drv.get_xy(client)
    src_stage_xy_um = (stage["x_um"], stage["y_um"])
    log.info("source stage XY_um=(%.3f, %.3f)", *src_stage_xy_um)

    geo_src = drv.parse_tile_geometry(drv.get_job_settings(client, args.job) or {})
    src_pixel_size_um = geo_src["pixel_w_um"]
    src_image_size = geo_src["pixels_x"]
    log.info("source FOV_um=(%.1f, %.1f) image=%dx%d pixel=%.4f um",
             geo_src["tile_w_um"], geo_src["tile_h_um"],
             src_image_size, geo_src["pixels_y"], src_pixel_size_um)

    log.info("acquiring source frame")
    src_img, src_path = _acquire_one(client, args.job)
    tifffile.imwrite(str(out_dir / "source.tif"), src_img)

    log.info("running Cellpose to pick a cell (gpu=%s)", not args.no_gpu)
    t0 = time.perf_counter()
    model = models.CellposeModel(gpu=not args.no_gpu)
    masks, _, _ = model.eval(src_img, diameter=args.diameter)
    log.info("Cellpose found %d cells in %.1fs",
             int(masks.max()), time.perf_counter() - t0)

    prop = _pick_central_cell(masks, src_img.shape)
    if prop is None:
        _abort("no cells found in source frame; move to a denser region "
               "or adjust --diameter")

    cy_px, cx_px = prop.centroid
    min_r, min_c, max_r, max_c = prop.bbox
    bbox_w_um = (max_c - min_c) * src_pixel_size_um
    bbox_h_um = (max_r - min_r) * src_pixel_size_um
    log.info("picked cell: centroid=(%.1f, %.1f) px  bbox=(%.1f x %.1f) um",
             cy_px, cx_px, bbox_w_um, bbox_h_um)

    template_src, template_origin, template_centre_xy = _extract_template(
        src_img, prop.centroid, prop.bbox, args.template_pad,
    )
    log.info("template cropped from source: %s px (pad=%.1f x bbox)  "
             "cell centroid in template = (%.2f, %.2f) px",
             template_src.shape, args.template_pad, *template_centre_xy)

    cell_source_xy_um = drv.pixel_to_stage_xy_um(
        cx_px, cy_px,
        stage_xy_um=src_stage_xy_um,
        pixel_size_um=src_pixel_size_um,
        image_size=src_image_size,
        config=cfg,
    )
    log.info("cell_source_xy_um=(%.3f, %.3f)", *cell_source_xy_um)

    cell_target_xy_um = drv.translate_stage_xy_between_objectives(
        *cell_source_xy_um, cfg,
        from_slot=args.source_slot, to_slot=args.target_slot,
    )
    log.info("cell_target_xy_um=(%.3f, %.3f)", *cell_target_xy_um)

    # ─── Target: intermediate zoom, refine loop ──────────────────
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
        # Intermediate target zoom chosen to match the source pixel size as
        # closely as possible — this minimises the template resample factor
        # and gives the cleanest NCC locks. Clamped to zoom >= 1 (the
        # scanner minimum); a source pixel smaller than the target's best
        # achievable pixel at zoom 1 just means a >1x upsample.
        ideal_intermediate_zoom = (
            target_base_fov_um / (src_pixel_size_um * src_image_size)
        )
        intermediate_zoom = max(1, int(round(ideal_intermediate_zoom)))
        intermediate_fov_um = target_base_fov_um / intermediate_zoom
        # Real pixel size at that zoom (integer zoom may differ from ideal).
        intermediate_pixel_size_um = intermediate_fov_um / src_image_size

        resample_factor = intermediate_pixel_size_um / src_pixel_size_um
        log.info("intermediate zoom=%d  FOV=%.1f um  pixel=%.4f um  "
                 "(target will be downsampled by %.2fx to match source)",
                 intermediate_zoom, intermediate_fov_um,
                 intermediate_pixel_size_um, 1.0 / resample_factor)
        drv.set_zoom(client, args.job, intermediate_zoom)

        log.info("moving stage to target XY")
        drv.move_xy_stage(client, *cell_target_xy_um, unit="um")
        time.sleep(0.5)

        _, iter_log = _refine(
            client, args.job, template_src, template_centre_xy,
            src_pixel_size_um, intermediate_pixel_size_um,
            max_iterations=args.max_iterations,
            converge_um=args.converge_um,
            peak_min=args.ncc_peak_min,
            ratio_min=args.ncc_ratio_min,
            search_radius_um=args.search_radius_um,
            output_dir=out_dir,
            cfg=cfg,
        )

        intermediate_info = {
            "zoom": intermediate_zoom,
            "fov_um": intermediate_fov_um,
            "pixel_size_um": intermediate_pixel_size_um,
            "template_shape_px": list(template_src.shape),
            "registration_at_pixel_size_um": src_pixel_size_um,
            "target_downsample_factor": 1.0 / resample_factor,
        }
    else:
        # Refinement disabled — skip intermediate zoom + loop, just move
        # to the calibrated target XY and acquire at the final zoom.
        log.info("refinement disabled (--max-iterations 0); "
                 "moving stage and going straight to final zoom")
        drv.move_xy_stage(client, *cell_target_xy_um, unit="um")
        time.sleep(0.5)

    converged = (
        bool(iter_log)
        and iter_log[-1]["correction_um_mag"] < args.converge_um
    )

    # ─── Final zoom + final acquire ──────────────────────────────
    final_zoom = drv.bbox_to_zoom(
        bbox_w_um, bbox_h_um, target_base_fov_um, margin=args.fov_bbox_margin,
    )
    log.info("final zoom=%d  FOV=%.1f um",
             final_zoom, target_base_fov_um / final_zoom)
    drv.set_zoom(client, args.job, final_zoom)

    log.info("acquiring final framed image")
    final_img, final_path = _acquire_one(client, args.job)
    tifffile.imwrite(str(out_dir / "target_final.tif"), final_img)

    # ─── Overlay + summary ───────────────────────────────────────
    _save_overlay(out_dir / "overlay.png", src_img, prop, final_img, iter_log)

    summary = {
        "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
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
        "cell_target_xy_um_initial": list(cell_target_xy_um),
        "intermediate": intermediate_info,
        "final": {
            "zoom": final_zoom,
            "fov_um": target_base_fov_um / final_zoom,
        },
        "iterations": iter_log,
        "converged": converged,
        "fov_bbox_margin": args.fov_bbox_margin,
        "offsets_config": str(drv.default_current_path()),
        "outputs": {
            "source_tif": str(out_dir / "source.tif"),
            "target_final_tif": str(out_dir / "target_final.tif"),
            "overlay_png": str(out_dir / "overlay.png"),
            "source_lasx_tif": str(src_path),
            "target_lasx_tif": str(final_path),
        },
    }
    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True)

    if iter_log:
        last = iter_log[-1]
        print(f"\nIterations: {len(iter_log)}  "
              f"final |correction| = {last['correction_um_mag']:.3f} um  "
              f"converged = {converged}")
    else:
        print("\nNo refinement iterations ran.")

    print(f"\nSource       : {out_dir / 'source.tif'}")
    print(f"Target final : {out_dir / 'target_final.tif'}")
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

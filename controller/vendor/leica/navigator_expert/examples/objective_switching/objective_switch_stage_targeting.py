"""
Objective-switch targeting example — stage-only.
================================================

End-to-end demonstration of the objective-switch coordinate flow,
using motorized-stage motion to aim. Acquires one image under a source
objective, picks a central cell with Cellpose, crosses the objective
boundary using the calibrated motor delta + sign convention, and acquires
a second image framed to that cell under the target objective.

Recipe (the script's ``main()`` reads top-to-bottom as this flow):

    1. Switch to source objective; acquire one frame.
    2. Cellpose segment; pick the nucleus closest to the image centre.
    3. Convert its pixel centroid to a stage XY in the source frame using
       ``pixel_to_stage_xy_um`` — which applies the measured sign/rotation
       matrix, no hardcoded axis flips.
    4. Translate that stage XY across the objective boundary with
       ``translate_stage_xy_between_objectives`` — which adds the measured
       motor delta in the correct direction.
    5. Switch to target objective; set a zoom that frames ~1.5× the
       nucleus bounding box; ``move_xy_stage`` to the target-frame command.
    6. Acquire one frame under the target objective.
    7. Re-segment the target frame to measure landing error — the
       quantitative "did we land the cell in the centre" signal.
    8. Save source.tif, target.tif, overlay.png, summary.json; restore.

Scope
    Single FOV at each objective. No tiling, no mosaic, no pan. Galvo/pan
    and ROI-based acquisition are the subject of sibling examples.

Operator preconditions
    - ``--job`` is already selected in the LAS X UI (the driver's
      ``IsSelected`` flag lags the UI, so this script does not call
      ``select_job``).
    - ``ImageTransformation = TOPLEFT`` in LAS X Advanced Settings.
    - AFC / autofocus OFF, no modal dialogs.
    - Stage positioned over a region with cells visible at the source
      objective's current zoom.
    - ``navigator_expert/calibration/config/config.json`` exists (generate it with
      ``calibrate_objectives.py``).

Usage
    python objective_switch_stage_targeting.py --job Overview \\
        --source-slot 1 --target-slot 2 \\
        [--fov-bbox-margin 1.5] [--diameter 30] [--no-gpu]

What's expected in the output
    Validated on ZMB STELLARIS 8 (10x → 20x, 2026-04-23): landing error
    ~9 µm, consistent with the motorized stage's settle accuracy. The
    picked cell is reliably within the 30 µm target FOV, but not
    necessarily at its exact centre. Sub-µm targeting requires either
    galvo pan (sibling example) or an image-based refinement step.
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

import numpy as np
import tifffile
from skimage.measure import regionprops
from cellpose import models
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from LasxApi import PYLICamApiConnector as lasx_api
import navigator_expert.driver as drv


log = logging.getLogger("objective_switch_stage_targeting")


# ── CLI ───────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Switch objective and revisit a detected cell in one FOV."
    )
    p.add_argument("--job", required=True,
                   help="LAS X job name. Must be selected in the LAS X UI.")
    p.add_argument("--source-slot", type=int, required=True,
                   help="Objective slot used for detection (e.g. 1 for 10x).")
    p.add_argument("--target-slot", type=int, required=True,
                   help="Objective slot used for acquisition (e.g. 2 for 20x).")
    p.add_argument("--fov-bbox-margin", type=float, default=1.5,
                   help="Target-objective FOV = this x nucleus bounding box "
                        "(default: 1.5).")
    p.add_argument("--diameter", type=float, default=None,
                   help="Cellpose nucleus diameter in pixels (default: auto).")
    p.add_argument("--no-gpu", action="store_true",
                   help="Disable GPU for Cellpose.")
    p.add_argument("--settle", type=float, default=3.0,
                   help="Seconds to wait after each objective switch "
                        "(default: 3).")
    p.add_argument("--output-dir", type=Path, default=None,
                   help="Output directory for frames, overlay, and summary "
                        "(default: config/objective_targeting/stage/<timestamp>/).")
    p.add_argument("--no-restore", action="store_true",
                   help="Do not switch back to the source objective at the end.")
    return p.parse_args()


# ── Small helpers ─────────────────────────────────────────────────

def _abort(msg, code=1):
    print(f"ABORT: {msg}")
    sys.exit(code)


def _default_output_dir():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return (Path(__file__).resolve().parents[3]
            / "config" / "objective_targeting" / "stage" / ts)


def _check_image_orientation():
    """Verify LAS X image export uses TOPLEFT; pixel math depends on it."""
    settings = drv.get_lasx_settings() or {}
    orient = settings.get("image_orientation", {})
    if orient.get("enable_transform", False) and orient.get("transformation", "TOPLEFT") != "TOPLEFT":
        _abort(f"ImageTransformation is '{orient.get('transformation')}'; "
               f"set it to TOPLEFT in LAS X Advanced Settings.", 2)


def _acquire_one(client, job_name):
    """Acquire a single frame and return (image_array, image_path)."""
    baseline = drv.read_relative_path(client)
    t_start = time.time()
    result = drv.acquire(client, job_name)
    if not result or not result.get("success"):
        raise RuntimeError(f"acquire failed: {result}")

    media_path = drv.get_lasx_settings()["export"]["media_path"]
    detection = drv.detect_new_files(
        client, baseline, media_path, acquire_start=t_start,
    )
    if not detection["success"]:
        raise RuntimeError(f"file detection failed: {detection.get('error')}")

    files = sorted(detection["image_files"])
    if not files:
        raise RuntimeError("no image files produced by acquisition")

    stable = drv.wait_all_stable(files, timeout=30)
    if not stable["success"]:
        log.warning("image file(s) may not be stable on disk yet")

    path = Path(files[0])
    img = tifffile.imread(str(path))
    if img.ndim == 3:
        img = img[0]
    return img, path


def _pick_central_cell(masks, image_shape):
    """Pick the nucleus whose centroid is closest to the image centre.

    Returns a regionprops object or None if no cells were segmented.
    """
    props = regionprops(masks)
    if not props:
        return None
    h, w = image_shape[:2]
    cy, cx = h / 2.0, w / 2.0
    return min(props, key=lambda p: (p.centroid[0] - cy) ** 2
                                     + (p.centroid[1] - cx) ** 2)


def _save_overlay(png_path, source_img, target_img, source_prop,
                  target_prop, landing_error_um):
    """Two-panel PNG: source with picked cell, target with landed cell.

    target_prop may be None if no cells were found in the target frame.
    """
    fig, axes = plt.subplots(1, 2, figsize=(12, 6))

    # Source panel
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

    # Target panel
    ax = axes[1]
    ax.imshow(target_img, cmap="gray")
    th, tw = target_img.shape[:2]
    ax.plot(tw / 2.0, th / 2.0, "c+", markersize=18, markeredgewidth=2)
    ax.axvline(tw / 2.0, color="white", linewidth=0.5, alpha=0.3)
    ax.axhline(th / 2.0, color="white", linewidth=0.5, alpha=0.3)
    if target_prop is not None:
        min_r, min_c, max_r, max_c = target_prop.bbox
        ax.add_patch(Rectangle((min_c, min_r), max_c - min_c, max_r - min_r,
                               edgecolor="lime", facecolor="none", linewidth=1.5))
        ty, tx = target_prop.centroid
        ax.plot(tx, ty, "r+", markersize=18, markeredgewidth=2)
        err_dx, err_dy = landing_error_um
        err_mag = math.sqrt(err_dx * err_dx + err_dy * err_dy)
        ax.set_title(f"Target: landed cell (red cross) vs centre (cyan). "
                     f"Error = {err_mag:.2f} um")
    else:
        ax.set_title("Target: no cells segmented — landing not verified")
    ax.axis("off")

    fig.tight_layout()
    fig.savefig(png_path, dpi=120)
    plt.close(fig)


def _measure_landing_error(target_img, target_prop, target_pixel_size_um):
    """Return (dx_um, dy_um) of the cell centroid from the image centre,
    or None when *target_prop* is None.
    """
    if target_prop is None:
        return None
    h, w = target_img.shape[:2]
    cy, cx = target_prop.centroid
    dy_px = cy - h / 2.0
    dx_px = cx - w / 2.0
    return (dx_px * target_pixel_size_um, dy_px * target_pixel_size_um)


# ── Main ──────────────────────────────────────────────────────────

def main():
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    args = parse_args()

    out_dir = args.output_dir or _default_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = drv.load_calibration()
    if args.source_slot == args.target_slot:
        _abort("source-slot and target-slot must differ.")

    # Connect
    client = lasx_api.LasxApiClientPyModel
    if not client.Connect("PythonClient"):
        _abort("Cannot connect to LAS X.", 2)
    if not drv.ping(client):
        _abort("LAS X ping failed.", 2)

    _check_image_orientation()

    hw = drv.get_hardware_info(client)
    if not hw:
        _abort("Could not read hardware info.", 2)

    # move_xy_stage silently no-ops if stage limits aren't set (returns
    # success=False). Configure them up-front for the ZMB STELLARIS range.
    drv.set_stage_limits(
        x_min=1000, x_max=130000,
        y_min=1000, y_max=100000,
        z_galvo_min=-200, z_galvo_max=200,
        z_wide_min=0, z_wide_max=25000,
    )

    idle = drv.check_idle(client, timeout=5.0)
    if not idle or not idle.get("success"):
        _abort(f"LAS X not idle: {idle}")

    # Validate slots against the hw_info, same rule as measurement.
    drv.validate_slots(hw, args.source_slot, [args.target_slot])

    print(f"Job:            {args.job}")
    print(f"Source slot:    {args.source_slot}")
    print(f"Target slot:    {args.target_slot}")
    print(f"FOV margin:     {args.fov_bbox_margin}x bounding box")
    print(f"Output dir:     {out_dir}\n")

    # 1. Switch to source objective
    log.info("switching to source objective")
    drv.set_objective(client, args.job, hw, slot_index=args.source_slot)
    time.sleep(args.settle)

    stage = drv.get_xy(client)
    if not stage:
        _abort("Could not read XY after source switch.")
    src_stage_xy_um = (stage["x_um"], stage["y_um"])
    log.info("source stage XY_um=(%.3f, %.3f)", *src_stage_xy_um)

    # 2. Read source FOV + pixel size
    geo = drv.parse_tile_geometry(drv.get_job_settings(client, args.job) or {})
    src_image_size = geo["pixels_x"]
    src_pixel_size_um = geo["pixel_w_um"]
    log.info("source FOV_um=(%.1f, %.1f)  image=%dx%d  pixel=%.4f um",
             geo["tile_w_um"], geo["tile_h_um"],
             src_image_size, geo["pixels_y"], src_pixel_size_um)

    # 3. Acquire one source frame
    log.info("acquiring source frame")
    src_img, src_path = _acquire_one(client, args.job)
    src_tif = out_dir / "source.tif"
    tifffile.imwrite(str(src_tif), src_img)
    log.info("source image %s (%s) → %s", src_img.shape, src_img.dtype, src_tif.name)

    # 4. Cellpose — uses the default model (Cellpose v4 ignores model_type
    #    and loads the built-in cpsam model regardless).
    log.info("running Cellpose (gpu=%s)", not args.no_gpu)
    t0 = time.perf_counter()
    model = models.CellposeModel(gpu=not args.no_gpu)
    masks, _, _ = model.eval(src_img, diameter=args.diameter)
    log.info("Cellpose found %d cells in %.1fs",
             int(masks.max()), time.perf_counter() - t0)

    prop = _pick_central_cell(masks, src_img.shape)
    if prop is None:
        _abort("No cells found. Try adjusting --diameter or move to a denser "
               "region of the sample.")

    cy_px, cx_px = prop.centroid
    min_r, min_c, max_r, max_c = prop.bbox
    bbox_w_um = (max_c - min_c) * src_pixel_size_um
    bbox_h_um = (max_r - min_r) * src_pixel_size_um
    log.info("picked cell: centroid=(%.1f, %.1f) px  bbox=(%.1f x %.1f) um  "
             "area=%d px", cy_px, cx_px, bbox_w_um, bbox_h_um, prop.area)

    # 5. Cell's stage XY in the source objective's frame.
    #    Uses the scope-specific sign-convention matrix measured during
    #    calibration — no hardcoded axis-flip assumptions.
    cell_source_xy_um = drv.pixel_to_stage_xy_um(
        cx_px, cy_px,
        stage_xy_um=src_stage_xy_um,
        pixel_size_um=src_pixel_size_um,
        image_size=src_image_size,
        config=cfg,
    )
    log.info("cell_source_xy_um=(%.3f, %.3f)", *cell_source_xy_um)

    # 6. Translate across the objective boundary to a target-slot stage command.
    cell_target_xy_um = drv.translate_stage_xy_between_objectives(
        *cell_source_xy_um, cfg,
        from_slot=args.source_slot, to_slot=args.target_slot,
    )
    log.info("cell_target_xy_um=(%.3f, %.3f)", *cell_target_xy_um)

    # 7. Switch to target objective
    log.info("switching to target objective")
    drv.set_objective(client, args.job, hw, slot_index=args.target_slot)
    time.sleep(args.settle)

    # 8. Compute target zoom to frame ~margin × bbox
    target_base_fov_m = drv.get_base_fov(client, args.job)
    if not target_base_fov_m:
        _abort("Could not read target base FOV.")
    target_base_fov_um = target_base_fov_m[0] * 1e6
    zoom = drv.bbox_to_zoom(bbox_w_um, bbox_h_um, target_base_fov_um,
                            margin=args.fov_bbox_margin)
    log.info("target base FOV=%.1f um @ zoom 1  →  zoom=%d "
             "(FOV=%.1f um at that zoom)",
             target_base_fov_um, zoom, target_base_fov_um / zoom)
    drv.set_zoom(client, args.job, zoom)

    # 9. Move the stage to the target (this example uses stage-only motion;
    #    a sibling example will demonstrate galvo/pan targeting).
    log.info("moving stage to target")
    drv.move_xy_stage(client, *cell_target_xy_um, unit="um")

    log.info("acquiring target frame")
    tgt_img, tgt_path = _acquire_one(client, args.job)
    tgt_tif = out_dir / "target.tif"
    tifffile.imwrite(str(tgt_tif), tgt_img)
    log.info("target image %s (%s) → %s", tgt_img.shape, tgt_img.dtype, tgt_tif.name)

    # 10. Verify: segment the target frame and measure the landing error.
    tgt_h, tgt_w = tgt_img.shape[:2]
    tgt_pixel_size_um = (target_base_fov_um / zoom) / tgt_w

    tgt_masks, _, _ = model.eval(tgt_img, diameter=args.diameter)
    tgt_n_cells = int(tgt_masks.max())
    log.info("target frame: %d cell(s) segmented", tgt_n_cells)

    tgt_prop = _pick_central_cell(tgt_masks, tgt_img.shape) if tgt_n_cells else None
    landing_error_um = _measure_landing_error(tgt_img, tgt_prop, tgt_pixel_size_um)
    if landing_error_um is not None:
        dx, dy = landing_error_um
        log.info("landing error: (%+.2f, %+.2f) um  magnitude=%.2f um",
                 dx, dy, math.hypot(dx, dy))
    else:
        log.warning("could not measure landing error — no cells found in target frame")

    # 11. Overlay + summary
    _save_overlay(
        out_dir / "overlay.png",
        src_img, tgt_img, prop, tgt_prop, landing_error_um or (0.0, 0.0),
    )

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
        },
        "cell_source_xy_um": list(cell_source_xy_um),
        "cell_target_xy_um": list(cell_target_xy_um),
        "target_zoom": zoom,
        "target_base_fov_um": target_base_fov_um,
        "target_fov_at_zoom_um": target_base_fov_um / zoom,
        "target_pixel_size_um": tgt_pixel_size_um,
        "fov_bbox_margin": args.fov_bbox_margin,
        "landing": {
            "cells_segmented": tgt_n_cells,
            "error_um": list(landing_error_um) if landing_error_um else None,
            "error_magnitude_um": (math.hypot(*landing_error_um)
                                   if landing_error_um else None),
        },
        "offsets_config": str(drv.default_current_path()),
        "outputs": {
            "source_tif": str(src_tif),
            "target_tif": str(tgt_tif),
            "overlay_png": str(out_dir / "overlay.png"),
            "source_lasx_tif": str(src_path),
            "target_lasx_tif": str(tgt_path),
        },
    }
    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True)

    if landing_error_um is not None:
        dx, dy = landing_error_um
        print(f"\nLanding error: ({dx:+.2f}, {dy:+.2f}) um  "
              f"magnitude={math.hypot(dx, dy):.2f} um")
    else:
        print(f"\nLanding error: unknown (no cells in target frame)")

    print(f"\nSource : {src_tif}")
    print(f"Target : {tgt_tif}")
    print(f"Overlay: {out_dir / 'overlay.png'}")
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

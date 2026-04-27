"""
Single-target objective switch using the motorized XY stage.
===========================================================

This is the cookbook baseline for objective switching without galvo pan
and without registration refinement.

Recipe
------
1. Switch to the source objective.
2. Acquire one source image.
3. Use Cellpose once to pick a target cell near the image center, or near
   ``--pick-pixel``.
4. Convert that source-image pixel to absolute source-objective XY using
   the measured image-to-stage sign convention.
5. Translate the source-objective XY into a target-objective stage command
   using ``objective_offsets.json``.
6. Switch to the target objective.
7. Move the motorized XY stage to the translated target coordinate.
8. Acquire a final image and, if possible, measure the landing error by
   re-segmenting the target image.

Actuator model
--------------
The motorized stage is a physical sample transport. For this script:

    image_center_xy = get_xy()

That equality is what makes this script simpler than the galvo scripts.
The cost is precision: final landing is limited by motorized-stage
settling and repeatability.

Operator preconditions
----------------------
- ``--job`` is currently selected in the LAS X UI.
- ImageTransformation is TOPLEFT.
- AFC/autofocus is off.
- No LAS X modal dialogs are open.
- ``config/objective_offsets.json`` exists and covers the source/target
  objective slots.

Usage
-----
    python single_target_stage_one_shot.py --job HiRes \\
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

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import matplotlib
import numpy as np
import tifffile
from cellpose import models
from skimage.measure import regionprops

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from LasxApi import PYLICamApiConnector as lasx_api
import lasx as drv


log = logging.getLogger("single_target_stage_one_shot")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description=(
            "Single-target objective switch using only the motorized XY stage."
        )
    )
    p.add_argument("--job", required=True,
                   help="LAS X job name. Must already be selected in LAS X.")
    p.add_argument("--source-slot", type=int, required=True)
    p.add_argument("--target-slot", type=int, required=True)

    p.add_argument("--fov-bbox-margin", type=float, default=1.5,
                   help="Final target FOV = margin x source bbox "
                        "(default: 1.5).")
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
                   help="Stage readback tolerance for the target move "
                        "(default: 20 um).")

    p.add_argument("--output-dir", type=Path, default=None,
                   help="Output directory (default: "
                        "config/cookbook/motorized_stage/<timestamp>).")
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
    return (Path(__file__).resolve().parents[2]
            / "config" / "cookbook" / "motorized_stage" / ts)


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


def _segment_pick(img, args):
    log.info("Cellpose pick (gpu=%s)", not args.no_gpu)
    model = models.CellposeModel(gpu=not args.no_gpu)
    masks, _, _ = model.eval(img, diameter=args.diameter)
    prop = _pick_nearest_cell(masks, img.shape, args.pick_pixel)
    if prop is None:
        _abort("no cells found; move to a denser region or adjust diameter")
    return masks, prop


def _measure_target_error_um(img, pixel_size_um, args):
    model = models.CellposeModel(gpu=not args.no_gpu)
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


def _save_overlay(path, source_img, source_prop, target_img, target_error):
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
        ax.set_title(
            f"Target landing error {target_error['distance_from_center_um']:.1f} um"
        )
    else:
        ax.set_title("Target final")
    ax.axis("off")

    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main protocol
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

    print(f"Job:           {args.job}")
    print(f"Source slot:   {args.source_slot}")
    print(f"Target slot:   {args.target_slot}")
    print("Actuator:      motorized XY stage")
    print(f"Output dir:    {out_dir}\n")

    log.info("switching to source objective")
    drv.set_objective(client, args.job, hw, slot_index=args.source_slot)
    time.sleep(args.settle)
    drv.set_zoom(client, args.job, 1.0)
    time.sleep(0.5)

    source_stage = drv.get_xy(client)
    source_center_xy_um = (source_stage["x_um"], source_stage["y_um"])
    source_geo = drv.parse_tile_geometry(
        drv.get_job_settings(client, args.job) or {},
    )
    source_pixel_size_um = float(source_geo["pixel_w_um"])
    source_image_size_px = int(source_geo["pixels_x"])

    source_img, source_path = _acquire_one(client, args.job)
    tifffile.imwrite(str(out_dir / "source.tif"), source_img)

    _, source_prop = _segment_pick(source_img, args)
    cy_px, cx_px = source_prop.centroid
    min_r, min_c, max_r, max_c = source_prop.bbox
    bbox_w_um = (max_c - min_c) * source_pixel_size_um
    bbox_h_um = (max_r - min_r) * source_pixel_size_um

    source_target_xy_um = drv.pixel_to_stage_xy_um(
        cx_px, cy_px,
        stage_xy_um=source_center_xy_um,
        pixel_size_um=source_pixel_size_um,
        image_size=source_image_size_px,
        config=cfg,
    )
    target_command_xy_um = drv.translate_stage_xy_between_objectives(
        *source_target_xy_um, cfg,
        from_slot=args.source_slot,
        to_slot=args.target_slot,
    )

    log.info("source target XY=(%.3f, %.3f)", *source_target_xy_um)
    log.info("target objective command XY=(%.3f, %.3f)", *target_command_xy_um)

    log.info("switching to target objective")
    drv.set_objective(client, args.job, hw, slot_index=args.target_slot)
    time.sleep(args.settle)

    target_base_fov_m = drv.get_base_fov(client, args.job)
    if not target_base_fov_m:
        _abort("Could not read target base FOV.")
    target_base_fov_um = target_base_fov_m[0] * 1e6
    final_zoom = drv.bbox_to_zoom(
        bbox_w_um, bbox_h_um, target_base_fov_um,
        margin=args.fov_bbox_margin,
    )
    drv.set_zoom(client, args.job, final_zoom)
    time.sleep(0.5)

    move_result = drv.move_xy_stage(
        client, target_command_xy_um[0], target_command_xy_um[1],
        unit="um", tolerance=args.stage_tolerance_um,
    )
    if not move_result or not move_result.get("success"):
        _abort(f"stage move failed: {move_result}")
    time.sleep(0.5)

    target_img, target_path = _acquire_one(client, args.job)
    tifffile.imwrite(str(out_dir / "target.tif"), target_img)

    target_geo = drv.parse_tile_geometry(
        drv.get_job_settings(client, args.job) or {},
    )
    target_pixel_size_um = float(target_geo["pixel_w_um"])
    target_error = _measure_target_error_um(
        target_img, target_pixel_size_um, args,
    )
    _save_overlay(out_dir / "overlay.png", source_img, source_prop,
                  target_img, target_error)

    summary = {
        "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "method": "single_target_stage_one_shot",
        "actuator": "motorized_stage",
        "job": args.job,
        "source_slot": args.source_slot,
        "target_slot": args.target_slot,
        "source_image_center_xy_um": list(source_center_xy_um),
        "source_pixel_size_um": source_pixel_size_um,
        "source_target_xy_um": list(source_target_xy_um),
        "target_command_xy_um": list(target_command_xy_um),
        "final_zoom": final_zoom,
        "final_fov_um": target_base_fov_um / final_zoom,
        "move_result": move_result,
        "target_error": target_error,
        "picked_cell": {
            "centroid_px": [float(cy_px), float(cx_px)],
            "bbox_px": [int(min_r), int(min_c), int(max_r), int(max_c)],
            "bbox_um": [float(bbox_w_um), float(bbox_h_um)],
            "area_px": int(source_prop.area),
        },
        "outputs": {
            "source_tif": str(out_dir / "source.tif"),
            "target_tif": str(out_dir / "target.tif"),
            "overlay_png": str(out_dir / "overlay.png"),
            "summary_json": str(out_dir / "summary.json"),
            "source_lasx_tif": str(source_path),
            "target_lasx_tif": str(target_path),
        },
    }
    _write_json(out_dir / "summary.json", summary)

    print(f"\nSummary: {out_dir / 'summary.json'}")
    if target_error:
        print(
            "Landing error: "
            f"{target_error['distance_from_center_um']:.2f} um"
        )

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


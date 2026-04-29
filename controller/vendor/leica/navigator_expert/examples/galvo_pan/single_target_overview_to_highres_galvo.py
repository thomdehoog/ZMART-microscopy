"""
Single 10x-overview target to high-resolution galvo acquisition.
================================================================

This cookbook script is the single-target bridge between a saved 10x
overview and a high-resolution objective run.

Recipe
------
1. Load one target from an overview manifest.
2. Convert the target into source-objective absolute XY.
3. Translate that XY through ``objective_offsets.json`` into the target
   objective frame.
4. Switch to the target objective.
5. Move the motorized stage coarsely to the predicted target position.
6. Zero galvo pan and acquire one wide registration image.
7. Register the saved 10x template against that high-resolution image.
8. Convert the matched pixel back to absolute XY using the optical image
   center, not blindly ``get_xy()``.
9. Set final zoom, then apply galvo pan to the corrected XY.
10. Acquire the final high-resolution image.

Actuator model
--------------
The motorized stage is used only for coarse transport. The galvo pan is
used for precise final centering:

    motorized stage: image_center_xy = get_xy()
    galvo pan:       image_center_xy = get_xy() + pan * pan_scale_um

That second equation is the main reason this script exists. It makes the
coordinate frame explicit before scaling to batch protocols.

Manifest target schema
----------------------
The target may provide precomputed source XY:

    {
      "id": "cell_001",
      "source_xy_um": [22790.6, 17524.7],
      "template_path": "templates/cell_001.tif",
      "template_centroid_xy_px": [32.0, 31.0],
      "bbox_um": [25.0, 23.0]
    }

Or it may provide tile-local overview pixels:

    {
      "id": "cell_001",
      "tile_center_xy_um": [22793.3, 17534.1],
      "centroid_px": [257.2, 251.8],
      "source_image_path": "overview_tiles/tile_001.tif",
      "bbox_px": [252, 247, 263, 258]
    }

``centroid_px`` is row/col. ``centroid_xy_px`` is col/row.

Usage
-----
    python single_target_overview_to_highres_galvo.py --job HiRes \\
        --manifest config/overview_targets/session_001.json \\
        --target-id cell_001 --source-slot 1 --target-slot 3
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

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from LasxApi import PYLICamApiConnector as lasx_api
import navigator_expert.driver as drv


log = logging.getLogger("single_target_overview_to_highres_galvo")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description=(
            "Visit one saved overview target at a high-resolution objective "
            "using coarse motorized-stage motion and final galvo pan."
        )
    )
    p.add_argument("--job", required=True,
                   help="LAS X job name. Must already be selected in LAS X.")
    p.add_argument("--manifest", type=Path, required=True,
                   help="Overview target manifest.")
    p.add_argument("--target-id", default=None,
                   help="Target id to run. Default: first target.")
    p.add_argument("--target-index", type=int, default=0,
                   help="Target index when --target-id is omitted "
                        "(default: 0).")
    p.add_argument("--source-slot", type=int, required=True,
                   help="Overview objective slot.")
    p.add_argument("--target-slot", type=int, required=True,
                   help="High-resolution objective slot.")

    p.add_argument("--match-fov-um", type=float, default=250.0,
                   help="Minimum useful FOV for the wide registration image "
                        "(default: 250 um).")
    p.add_argument("--final-fov-um", type=float, default=40.0,
                   help="Final FOV if target lacks bbox_um/final_fov_um "
                        "(default: 40 um).")
    p.add_argument("--fov-bbox-margin", type=float, default=1.5,
                   help="Final FOV = margin x bbox when bbox is present "
                        "(default: 1.5).")

    p.add_argument("--template-pad", type=float, default=3.0,
                   help="Template pad x bbox when cropping from source image "
                        "(default: 3.0).")
    p.add_argument("--fallback-template-half-size-px", type=int, default=32,
                   help="Half-size for source-image template crop if bbox_px "
                        "is absent (default: 32 px).")

    p.add_argument("--ncc-peak-min", type=float, default=0.4,
                   help="Reject NCC match below this peak (default: 0.4).")
    p.add_argument("--ncc-ratio-min", type=float, default=1.5,
                   help="Reject if peak / second peak is below this ratio "
                        "(default: 1.5).")
    p.add_argument("--search-radius-um", type=float, default=80.0,
                   help="NCC search radius around the registration image "
                        "center (default: 80 um).")

    p.add_argument("--stage-tolerance-um", type=float, default=20.0,
                   help="Readback tolerance for the coarse stage move "
                        "(default: 20 um).")
    p.add_argument("--settle", type=float, default=3.0,
                   help="Seconds after objective switch (default: 3).")

    p.add_argument("--output-dir", type=Path, default=None,
                   help="Output directory (default: "
                        "config/cookbook/galvo_pan/<timestamp>).")
    p.add_argument("--dry-run", action="store_true",
                   help="Resolve manifest coordinates and templates, but do "
                        "not connect to LAS X.")
    p.add_argument("--restore-source", action="store_true",
                   help="Switch back to source objective at the end. Default "
                        "is to stay at high-resolution objective.")
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
            / "config" / "cookbook" / "galvo_pan" / ts)


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(path)


def _resolve_path(path_value, base_dir):
    if path_value is None:
        return None
    path = Path(path_value)
    if not path.is_absolute():
        path = Path(base_dir) / path
    return path


def _read_image(path):
    img = tifffile.imread(str(path))
    if img.ndim == 3:
        img = img[0]
    return img


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
    return _read_image(path), path


def _zoom_for_min_fov(base_fov_um, min_fov_um):
    if min_fov_um <= 0:
        raise ValueError("FOV must be > 0")
    ratio = float(base_fov_um) / float(min_fov_um)
    return max(1, int(math.floor(ratio + 1e-9)))


def _zoom_for_requested_fov(base_fov_um, requested_fov_um):
    if requested_fov_um <= 0:
        raise ValueError("FOV must be > 0")
    return max(1, int(round(float(base_fov_um) / float(requested_fov_um))))


def _as_xy_um(value, name):
    if isinstance(value, dict):
        if "x_um" in value and "y_um" in value:
            return float(value["x_um"]), float(value["y_um"])
        if "x" in value and "y" in value:
            return float(value["x"]), float(value["y"])
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return float(value[0]), float(value[1])
    raise ValueError(f"{name} must be [x_um, y_um] or x/y dict")


def _get_first(mapping, names, default=None):
    for name in names:
        if name in mapping:
            return mapping[name]
    return default


# ---------------------------------------------------------------------------
# Manifest target resolution
# ---------------------------------------------------------------------------

def _select_target(manifest, target_id, target_index):
    targets = list(manifest.get("targets") or [])
    if not targets:
        raise ValueError("manifest has no targets")
    if target_id is not None:
        for i, target in enumerate(targets):
            if str(target.get("id") or target.get("target_id") or i) == target_id:
                return i, target
        raise ValueError(f"target id not found: {target_id}")
    if target_index < 0 or target_index >= len(targets):
        raise ValueError(f"target-index out of range: {target_index}")
    return target_index, targets[target_index]


def _target_id(target, idx):
    return str(target.get("id") or target.get("target_id") or f"target_{idx:04d}")


def _overview_defaults(manifest):
    return manifest.get("overview") or {}


def _target_pixel_size_um(target, manifest):
    overview = _overview_defaults(manifest)
    value = _get_first(target, ["pixel_size_um", "overview_pixel_size_um"],
                       _get_first(overview, ["pixel_size_um"]))
    if value is None:
        raise ValueError("target needs pixel_size_um or overview.pixel_size_um")
    return float(value)


def _target_image_size_px(target, manifest):
    overview = _overview_defaults(manifest)
    value = _get_first(target, ["image_size_px", "overview_image_size_px"],
                       _get_first(overview, ["image_size_px"]))
    if value is None:
        raise ValueError("target needs image_size_px or overview.image_size_px")
    return int(value)


def _target_centroid_col_row(target):
    xy = target.get("centroid_xy_px")
    if xy is not None:
        if not isinstance(xy, (list, tuple)) or len(xy) != 2:
            raise ValueError("centroid_xy_px must be [col, row]")
        return float(xy[0]), float(xy[1])

    rc = target.get("centroid_px")
    if rc is not None:
        if not isinstance(rc, (list, tuple)) or len(rc) != 2:
            raise ValueError("centroid_px must be [row, col]")
        return float(rc[1]), float(rc[0])

    raise ValueError("target needs centroid_px, centroid_xy_px, or source_xy_um")


def _target_tile_center_xy_um(target, manifest):
    overview = _overview_defaults(manifest)
    value = _get_first(
        target,
        ["tile_center_xy_um", "image_center_xy_um", "stage_xy_um"],
        _get_first(overview, ["tile_center_xy_um", "image_center_xy_um"]),
    )
    if value is None:
        raise ValueError("target needs source_xy_um or tile_center_xy_um")
    return _as_xy_um(value, "tile center XY")


def _target_source_xy_um(target, manifest, cfg):
    value = _get_first(target, ["source_xy_um", "overview_xy_um"])
    if value is not None:
        return _as_xy_um(value, "source_xy_um")

    centre_xy = _target_tile_center_xy_um(target, manifest)
    pixel_size_um = _target_pixel_size_um(target, manifest)
    image_size_px = _target_image_size_px(target, manifest)
    col_px, row_px = _target_centroid_col_row(target)
    return drv.pixel_to_stage_xy_um(
        col_px, row_px,
        stage_xy_um=centre_xy,
        pixel_size_um=pixel_size_um,
        image_size=image_size_px,
        config=cfg,
    )


def _target_bbox_um(target, manifest):
    value = _get_first(target, ["bbox_um", "target_bbox_um"])
    if isinstance(value, dict):
        if "width_um" in value and "height_um" in value:
            return float(value["width_um"]), float(value["height_um"])
        if "w_um" in value and "h_um" in value:
            return float(value["w_um"]), float(value["h_um"])
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return float(value[0]), float(value[1])

    bbox_px = target.get("bbox_px")
    if bbox_px is not None:
        if not isinstance(bbox_px, (list, tuple)) or len(bbox_px) != 4:
            raise ValueError("bbox_px must be [min_row, min_col, max_row, max_col]")
        pixel_size_um = _target_pixel_size_um(target, manifest)
        min_r, min_c, max_r, max_c = [float(v) for v in bbox_px]
        return ((max_c - min_c) * pixel_size_um,
                (max_r - min_r) * pixel_size_um)

    return None


def _target_final_zoom(target, manifest, target_base_fov_um, args):
    if "final_zoom" in target:
        return max(1, int(round(float(target["final_zoom"]))))
    if "final_fov_um" in target:
        return _zoom_for_requested_fov(
            target_base_fov_um, float(target["final_fov_um"]),
        )
    bbox = _target_bbox_um(target, manifest)
    if bbox is not None:
        return drv.bbox_to_zoom(
            bbox[0], bbox[1], target_base_fov_um,
            margin=args.fov_bbox_margin,
        )
    return _zoom_for_requested_fov(target_base_fov_um, args.final_fov_um)


def _extract_template(image, centroid_col_row, bbox_px, pad_factor,
                      fallback_half_size_px):
    cx, cy = centroid_col_row
    h, w = image.shape[:2]
    if bbox_px is not None:
        min_r, min_c, max_r, max_c = [int(round(float(v))) for v in bbox_px]
        half = int(round(pad_factor * max(max_r - min_r, max_c - min_c) / 2.0))
    else:
        half = int(fallback_half_size_px)
    cy_i = int(round(cy))
    cx_i = int(round(cx))
    top = max(0, cy_i - half)
    left = max(0, cx_i - half)
    bottom = min(h, cy_i + half)
    right = min(w, cx_i + half)
    template = image[top:bottom, left:right].copy()
    if template.size == 0:
        raise ValueError("template crop is empty")
    return template, (cx - left, cy - top), (top, left)


def _template_centroid_xy_from_target(target, template_shape):
    xy = target.get("template_centroid_xy_px")
    if xy is not None:
        if not isinstance(xy, (list, tuple)) or len(xy) != 2:
            raise ValueError("template_centroid_xy_px must be [col, row]")
        return float(xy[0]), float(xy[1])

    rc = target.get("template_centroid_px")
    if rc is not None:
        if not isinstance(rc, (list, tuple)) or len(rc) != 2:
            raise ValueError("template_centroid_px must be [row, col]")
        return float(rc[1]), float(rc[0])

    th, tw = template_shape[:2]
    return tw / 2.0, th / 2.0


def _load_target_template(target, manifest_path, manifest, args):
    base_dir = manifest_path.parent
    template_path = _resolve_path(target.get("template_path"), base_dir)
    if template_path is not None:
        template = _read_image(template_path)
        centre = _template_centroid_xy_from_target(target, template.shape)
        return template, centre, str(template_path), target.get("template_origin_px")

    source_path = _resolve_path(target.get("source_image_path"), base_dir)
    if source_path is None:
        raise ValueError(
            "target needs template_path, or source_image_path plus centroid"
        )
    source_img = _read_image(source_path)
    centroid = _target_centroid_col_row(target)
    template, centre, origin = _extract_template(
        source_img, centroid, target.get("bbox_px"),
        args.template_pad, args.fallback_template_half_size_px,
    )
    return template, centre, str(source_path), list(origin)


# ---------------------------------------------------------------------------
# Registration and galvo-aware geometry
# ---------------------------------------------------------------------------

def _resample_to_pixel_size(img, src_pixel_um, tgt_pixel_um):
    scale = float(src_pixel_um) / float(tgt_pixel_um)
    h, w = img.shape[:2]
    new_h = max(8, int(round(h * scale)))
    new_w = max(8, int(round(w * scale)))
    interpolation = cv2.INTER_CUBIC if scale > 1.0 else cv2.INTER_AREA
    return cv2.resize(img, (new_w, new_h), interpolation=interpolation)


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
        ok = False
        reason = f"NCC peak {peak_val:.3f} < {peak_min}"
    elif ratio < ratio_min:
        ok = False
        reason = f"peak/second-peak {ratio:.2f} < {ratio_min}"
    elif dist > search_radius_px:
        ok = False
        reason = f"match {dist:.1f} px outside search radius {search_radius_px:.0f}"
    else:
        ok = True
        reason = None

    return {"ok": ok, "reason": reason,
            "match_xy_px": (float(match_cx), float(match_cy)),
            "peak_val": peak_val, "ratio": ratio}


def _current_stage_xy(client):
    stage = drv.get_xy(client)
    if stage is None:
        raise RuntimeError("failed to read XY stage position")
    return float(stage["x_um"]), float(stage["y_um"])


def _image_center_from_pan(stage_xy_um, pan_result):
    pan = pan_result.get("pan")
    pan_scale_um = pan_result.get("pan_scale_um")
    if pan is None or pan_scale_um is None:
        raise ValueError("pan result missing pan or pan_scale_um")
    return (
        float(stage_xy_um[0]) + float(pan[0]) * float(pan_scale_um),
        float(stage_xy_um[1]) + float(pan[1]) * float(pan_scale_um),
    )


def _zero_galvo(client, job_name):
    stage_xy = _current_stage_xy(client)
    result = drv.move_xy_galvo(
        client, stage_xy[0], stage_xy[1],
        unit="um", job_name=job_name,
    )
    if not result or not result.get("success"):
        raise RuntimeError(f"zero galvo pan failed: {result}")
    return result


def _within_galvo_range(target_xy_um, stage_xy_um, pan_scale_um):
    dx = float(target_xy_um[0]) - float(stage_xy_um[0])
    dy = float(target_xy_um[1]) - float(stage_xy_um[1])
    max_um = drv.PAN_LIMIT * float(pan_scale_um)
    return abs(dx) <= max_um and abs(dy) <= max_um, (dx, dy), max_um


def _save_overlay(path, template, registration_img, match,
                  template_centre_xy, final_img=None):
    cols = 3 if final_img is not None else 2
    fig, axes = plt.subplots(1, cols, figsize=(5 * cols, 5))

    ax = axes[0]
    ax.imshow(template, cmap="gray")
    tcx, tcy = template_centre_xy
    ax.plot(tcx, tcy, "r+", markersize=16, markeredgewidth=2)
    ax.set_title("Overview template")
    ax.axis("off")

    ax = axes[1]
    ax.imshow(registration_img, cmap="gray")
    h, w = registration_img.shape[:2]
    ax.plot(w / 2.0, h / 2.0, "c+", markersize=16, markeredgewidth=2)
    if match.get("match_xy_px") is not None:
        mx, my = match["match_xy_px"]
        ax.plot(mx, my, "g+", markersize=16, markeredgewidth=2)
        th, tw = template.shape[:2]
        ax.add_patch(Rectangle((mx - tcx, my - tcy), tw, th,
                               edgecolor="lime", facecolor="none",
                               linewidth=1.2))
    ax.set_title("Registration")
    ax.axis("off")

    if final_img is not None:
        ax = axes[2]
        ax.imshow(final_img, cmap="gray")
        fh, fw = final_img.shape[:2]
        ax.plot(fw / 2.0, fh / 2.0, "c+", markersize=16, markeredgewidth=2)
        ax.set_title("Final")
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

    manifest_path = args.manifest.resolve()
    manifest = _load_json(manifest_path)
    cfg = drv.load_objective_offsets()
    target_index, target = _select_target(
        manifest, args.target_id, args.target_index,
    )
    target_id = _target_id(target, target_index)

    source_xy_um = _target_source_xy_um(target, manifest, cfg)
    predicted_xy_um = drv.translate_stage_xy_between_objectives(
        *source_xy_um, cfg,
        from_slot=args.source_slot,
        to_slot=args.target_slot,
    )
    template, template_centre_xy, template_source, template_origin = \
        _load_target_template(target, manifest_path, manifest, args)
    template_pixel_size_um = _target_pixel_size_um(target, manifest)

    print(f"Job:           {args.job}")
    print(f"Manifest:      {manifest_path}")
    print(f"Target:        {target_id}")
    print(f"Source slot:   {args.source_slot}")
    print(f"Target slot:   {args.target_slot}")
    print("Actuators:     motorized stage coarse, galvo pan final")
    print(f"Output dir:    {out_dir}")
    print("Mode:          dry-run\n" if args.dry_run else "Mode:          acquire\n")

    if args.dry_run:
        summary = {
            "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "method": "single_target_overview_to_highres_galvo",
            "status": "dry_run",
            "target_id": target_id,
            "source_slot": args.source_slot,
            "target_slot": args.target_slot,
            "source_xy_um": list(source_xy_um),
            "predicted_target_xy_um": list(predicted_xy_um),
            "template": {
                "source": template_source,
                "shape_px": list(template.shape),
                "centroid_xy_px": list(template_centre_xy),
                "origin_px": template_origin,
                "pixel_size_um": template_pixel_size_um,
            },
        }
        _write_json(out_dir / "summary.json", summary)
        print(f"Dry-run summary: {out_dir / 'summary.json'}")
        return 0

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

    log.info("switching to target objective")
    drv.set_objective(client, args.job, hw, slot_index=args.target_slot)
    time.sleep(args.settle)

    target_base_fov_m = drv.get_base_fov(client, args.job)
    if not target_base_fov_m:
        _abort("Could not read target base FOV.")
    target_base_fov_um = target_base_fov_m[0] * 1e6
    match_zoom = _zoom_for_min_fov(target_base_fov_um, args.match_fov_um)
    final_zoom = _target_final_zoom(target, manifest, target_base_fov_um, args)
    pan_scale_um = drv.pan_scale_um_from_base_fov(target_base_fov_um)

    log.info("coarse stage move to predicted target XY")
    move_result = drv.move_xy_stage(
        client, predicted_xy_um[0], predicted_xy_um[1],
        unit="um", tolerance=args.stage_tolerance_um,
    )
    if not move_result or not move_result.get("success"):
        _abort(f"coarse stage move failed: {move_result}")
    time.sleep(0.5)

    # Registration image: zero pan keeps the expected target at image center
    # and leaves full pan range available for the final correction.
    drv.set_zoom(client, args.job, match_zoom)
    time.sleep(0.5)
    zero_pan = _zero_galvo(client, args.job)
    registration_stage_xy = _current_stage_xy(client)
    registration_center_xy = _image_center_from_pan(
        registration_stage_xy, zero_pan,
    )

    registration_img, registration_path = _acquire_one(client, args.job)
    tifffile.imwrite(str(out_dir / "registration.tif"), registration_img)

    registration_geo = drv.parse_tile_geometry(
        drv.get_job_settings(client, args.job) or {},
    )
    registration_pixel_size_um = float(registration_geo["pixel_w_um"])
    registration_for_match = _resample_to_pixel_size(
        registration_img, registration_pixel_size_um, template_pixel_size_um,
    )
    tifffile.imwrite(str(out_dir / "registration_matched_pixel.tif"),
                     registration_for_match.astype(registration_img.dtype))

    mh, mw = registration_for_match.shape[:2]
    match = _ncc_match(
        registration_for_match, template,
        template_centre_xy_px=template_centre_xy,
        search_center_xy_px=(mw / 2.0, mh / 2.0),
        search_radius_px=args.search_radius_um / template_pixel_size_um,
        peak_min=args.ncc_peak_min,
        ratio_min=args.ncc_ratio_min,
    )

    if not match["ok"]:
        _save_overlay(out_dir / "diagnostic.png", template,
                      registration_for_match, match, template_centre_xy)
        failure_summary = {
            "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "method": "single_target_overview_to_highres_galvo",
            "status": "ncc_failed",
            "failure_reason": match["reason"],
            "target_id": target_id,
            "job": args.job,
            "source_slot": args.source_slot,
            "target_slot": args.target_slot,
            "source_xy_um": list(source_xy_um),
            "predicted_target_xy_um": list(predicted_xy_um),
            "template": {
                "source": template_source,
                "shape_px": list(template.shape),
                "centroid_xy_px": list(template_centre_xy),
                "origin_px": template_origin,
                "pixel_size_um": template_pixel_size_um,
            },
            "registration": {
                "zoom": match_zoom,
                "fov_um": target_base_fov_um / match_zoom,
                "stage_xy_um": list(registration_stage_xy),
                "image_center_xy_um": list(registration_center_xy),
                "pixel_size_um": registration_pixel_size_um,
                "matched_image_size_px": mw,
                "ncc_peak": match["peak_val"],
                "ncc_ratio": match["ratio"],
                "match_xy_px": (list(match["match_xy_px"])
                                if match.get("match_xy_px") is not None
                                else None),
                "registration_lasx_tif": str(registration_path),
            },
            "outputs": {
                "registration_tif": str(out_dir / "registration.tif"),
                "registration_matched_tif": str(
                    out_dir / "registration_matched_pixel.tif"
                ),
                "diagnostic_png": str(out_dir / "diagnostic.png"),
                "summary_json": str(out_dir / "summary.json"),
            },
        }
        _write_json(out_dir / "summary.json", failure_summary)
        _abort(f"NCC gate failed: {match['reason']}")

    match_px = match["match_xy_px"]
    registered_xy_um = drv.pixel_to_stage_xy_um(
        match_px[0], match_px[1],
        stage_xy_um=registration_center_xy,
        pixel_size_um=template_pixel_size_um,
        image_size=mw,
        config=cfg,
    )
    residual_um = (
        registered_xy_um[0] - predicted_xy_um[0],
        registered_xy_um[1] - predicted_xy_um[1],
    )

    current_stage_xy = _current_stage_xy(client)
    in_range, final_offset_um, max_pan_um = _within_galvo_range(
        registered_xy_um, current_stage_xy, pan_scale_um,
    )
    if not in_range:
        _save_overlay(out_dir / "diagnostic.png", template,
                      registration_for_match, match, template_centre_xy)
        _abort(
            "registered target is outside galvo range from current stage "
            f"position: needed ({final_offset_um[0]:.1f}, "
            f"{final_offset_um[1]:.1f}) um, max +/-{max_pan_um:.1f} um. "
            "Move the stage and acquire another registration image."
        )

    # Critical ordering: final zoom first, then write pan. A zoom change
    # after pan can make LAS X silently clamp pan.
    drv.set_zoom(client, args.job, final_zoom)
    time.sleep(0.5)
    final_pan = drv.move_xy_galvo(
        client, registered_xy_um[0], registered_xy_um[1],
        unit="um", job_name=args.job,
    )
    if not final_pan or not final_pan.get("success"):
        _abort(f"final galvo pan failed: {final_pan}")

    final_stage_xy = _current_stage_xy(client)
    final_center_xy = _image_center_from_pan(final_stage_xy, final_pan)

    final_img, final_path = _acquire_one(client, args.job)
    tifffile.imwrite(str(out_dir / "final.tif"), final_img)
    _save_overlay(out_dir / "overlay.png", template, registration_for_match,
                  match, template_centre_xy, final_img=final_img)

    summary = {
        "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "method": "single_target_overview_to_highres_galvo",
        "actuators": {
            "coarse": "motorized_stage",
            "fine": "galvo_pan",
        },
        "target_id": target_id,
        "job": args.job,
        "source_slot": args.source_slot,
        "target_slot": args.target_slot,
        "source_xy_um": list(source_xy_um),
        "predicted_target_xy_um": list(predicted_xy_um),
        "registered_target_xy_um": list(registered_xy_um),
        "registration_residual_um": list(residual_um),
        "registration_residual_magnitude_um": math.hypot(*residual_um),
        "template": {
            "source": template_source,
            "shape_px": list(template.shape),
            "centroid_xy_px": list(template_centre_xy),
            "origin_px": template_origin,
            "pixel_size_um": template_pixel_size_um,
        },
        "registration": {
            "zoom": match_zoom,
            "fov_um": target_base_fov_um / match_zoom,
            "stage_xy_um": list(registration_stage_xy),
            "image_center_xy_um": list(registration_center_xy),
            "pixel_size_um": registration_pixel_size_um,
            "matched_image_size_px": mw,
            "ncc_peak": match["peak_val"],
            "ncc_ratio": match["ratio"],
            "match_xy_px": list(match_px),
            "registration_lasx_tif": str(registration_path),
        },
        "final": {
            "zoom": final_zoom,
            "fov_um": target_base_fov_um / final_zoom,
            "stage_xy_um": list(final_stage_xy),
            "image_center_xy_um": list(final_center_xy),
            "pan": list(final_pan.get("pan") or (None, None)),
            "offset_um": list(final_pan.get("offset_um") or (None, None)),
            "pan_scale_um": final_pan.get("pan_scale_um"),
            "final_lasx_tif": str(final_path),
        },
        "outputs": {
            "registration_tif": str(out_dir / "registration.tif"),
            "registration_matched_tif": str(
                out_dir / "registration_matched_pixel.tif"
            ),
            "final_tif": str(out_dir / "final.tif"),
            "overlay_png": str(out_dir / "overlay.png"),
            "summary_json": str(out_dir / "summary.json"),
        },
    }
    _write_json(out_dir / "summary.json", summary)

    print(f"\nNCC peak: {match['peak_val']:.3f}  ratio: {match['ratio']:.2f}")
    print(
        "Registration residual: "
        f"({residual_um[0]:+.2f}, {residual_um[1]:+.2f}) um"
    )
    print(f"Summary: {out_dir / 'summary.json'}")

    if args.restore_source:
        log.info("restoring source objective")
        drv.set_objective(client, args.job, hw, slot_index=args.source_slot)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)


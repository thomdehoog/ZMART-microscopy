"""
Single-target objective switch with consensus-cluster galvo registration.
=========================================================================

Cookbook companion to ``single_target_stage_one_shot.py`` for the galvo
actuator. Live source acquire (no manifest). Cellpose picks a cell at
the source objective, then four registration methods estimate the
translation between the source field and a target-objective
intermediate acquisition. A consensus-cluster vote selects the
agreeing subset; the galvo applies the cluster median.

Why consensus clustering and not single-method NCC: PCC and NCC alone
work most of the time but each has failure modes (featureless regions,
periodic patterns, neighbour-cell lookalikes). A plain median of all
methods can still be pulled around if two methods share the same
failure mode. Clustering the estimates and taking the largest agreeing
subset makes outliers visible and refuses to land on them.

Methods (lifted from vendor/leica/test/test_registration_benchmark.py):
    1. PCC          — phase_cross_correlation, unmasked
    2. Masked PCC   — phase_cross_correlation with intensity masks
    3. NCC          — cv2.matchTemplate(TM_CCOEFF_NORMED)
    4. ORB+RANSAC   — feature-based, translation only

ECC refinement seeded from the cluster median is the natural next step
if the unrefined median is not tight enough; not implemented here.

Recipe
------
1. Switch to source objective; force zoom 1.0; acquire one source image.
2. Cellpose picks a target cell (centre, or near ``--pick-pixel``).
3. Convert source pixel -> absolute source-objective XY; translate to
   target-objective stage frame via ``objective_offsets.json``.
4. Switch to target objective; set the intermediate zoom (target pixel
   size near source pixel size).
5. ZOOM FIRST, then galvo-pan to the calibration-predicted target XY.
6. Acquire intermediate; resample to source pixel size.
7. Run all four registration methods. Drop hard failures. Find the
   largest subset where every pairwise (dx, dy) distance is within
   ``--agreement-tolerance-um`` (a clique by tolerance).
8. Require the chosen cluster to contain at least ``--min-cluster``
   methods. Cluster median = correction. Cluster spread is reported
   prominently so the operator sees real confidence, not just a
   binary accept/reject.
9. Convert the cluster median into a target-frame stage XY using the
   intermediate image's optical centre (stage_xy + pan * pan_scale_um).
10. Set final zoom; galvo-pan to the corrected XY; acquire final.
11. Re-segment final image to measure landing error.
12. Restore source objective unless ``--no-restore``.

Galvo range caveat
------------------
Reachable pan from the current stage XY is roughly +/-775/388/194 um at
10x/20x/40x. If the predicted or corrected target XY is outside that
radius from the current stage position, the script aborts.

Operator preconditions
----------------------
- ``--job`` is currently selected in the LAS X UI.
- ImageTransformation is TOPLEFT.
- AFC/autofocus is off, no LAS X modal dialogs.
- Stage focused at the source objective before running.
- ``config/objective_offsets.json`` exists.
- No ROI scan currently enabled.

Usage
-----
    python single_target_galvo_one_shot.py --job HiRes \\
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
from skimage.feature import ORB, match_descriptors
from skimage.measure import ransac, regionprops
from skimage.registration import phase_cross_correlation
from skimage.transform import EuclideanTransform

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from LasxApi import PYLICamApiConnector as lasx_api
import navigator_expert.driver as drv


log = logging.getLogger("single_target_galvo_one_shot")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description=(
            "Single-target objective switch using galvo pan with multi-method "
            "voting registration."
        )
    )
    p.add_argument("--job", required=True,
                   help="LAS X job name. Must already be selected in LAS X.")
    p.add_argument("--source-slot", type=int, required=True)
    p.add_argument("--target-slot", type=int, required=True)

    p.add_argument("--fov-bbox-margin", type=float, default=1.5,
                   help="Final target FOV = margin x source bbox "
                        "(default: 1.5).")
    p.add_argument("--agreement-tolerance-um", type=float, default=2.0,
                   help="Max pairwise distance for two estimates to be in "
                        "the same cluster (default: 2 um). Tighten to make "
                        "the consensus stricter.")
    p.add_argument("--min-cluster", type=int, default=3,
                   help="Minimum cluster size to accept (default: 3 of 4 "
                        "methods).")
    p.add_argument("--mask-pct", type=float, default=30.0,
                   help="Intensity percentile for masked PCC mask "
                        "(default: 30). Lower = more permissive mask.")

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

    p.add_argument("--output-dir", type=Path, default=None,
                   help="Output directory (default: "
                        "config/cookbook/galvo_pan_oneshot/<timestamp>).")
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
            / "config" / "cookbook" / "galvo_pan_oneshot" / ts)


def _write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True, default=str)
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


def _resample_to_pixel_size(img, src_pixel_um, tgt_pixel_um):
    scale = float(src_pixel_um) / float(tgt_pixel_um)
    h, w = img.shape[:2]
    new_h = max(8, int(round(h * scale)))
    new_w = max(8, int(round(w * scale)))
    interp = cv2.INTER_CUBIC if scale > 1.0 else cv2.INTER_AREA
    return cv2.resize(img, (new_w, new_h), interpolation=interp)


def _crop_around(img, centre_col, centre_row, half_size_px):
    """Crop *img* around (centre_col, centre_row) by ±half_size_px. Clips at
    image edges. Returns (cropped_img, (left, top, right, bottom))."""
    h, w = img.shape[:2]
    cc = int(round(centre_col))
    cr = int(round(centre_row))
    left = max(0, cc - half_size_px)
    right = min(w, cc + half_size_px)
    top = max(0, cr - half_size_px)
    bottom = min(h, cr + half_size_px)
    return img[top:bottom, left:right], (left, top, right, bottom)


def _prepare_registration_pair(source_img, intermediate_img, *,
                               source_pixel_um, intermediate_pixel_um,
                               source_cell_col, source_cell_row,
                               intermediate_centre_col=None,
                               intermediate_centre_row=None):
    """Make a matched-shape, matched-um/px image pair for registration.

    The image with the larger physical FOV is cropped to the smaller's FOV,
    centred on the cell of interest in source / on the intermediate's
    optical centre in intermediate. The image with the finer pixel size
    is then resampled down to the coarser pixel size. After this the
    returned ``ref_img`` and ``tgt_img`` have the same physical FOV and
    the same um/px and the same shape (modulo edge rounding). Voting
    methods (PCC, NCC, ORB) all run on these matched images.
    """
    sh, sw = source_img.shape[:2]
    ih, iw = intermediate_img.shape[:2]
    src_fov_um = sw * source_pixel_um
    int_fov_um = iw * intermediate_pixel_um

    common_fov_um = min(src_fov_um, int_fov_um)
    common_pixel_um = max(source_pixel_um, intermediate_pixel_um)

    src_half_px = int(round(common_fov_um / 2.0 / source_pixel_um))
    int_half_px = int(round(common_fov_um / 2.0 / intermediate_pixel_um))

    if intermediate_centre_col is None:
        intermediate_centre_col = iw / 2.0
    if intermediate_centre_row is None:
        intermediate_centre_row = ih / 2.0

    src_crop, src_bbox = _crop_around(source_img, source_cell_col,
                                      source_cell_row, src_half_px)
    int_crop, int_bbox = _crop_around(intermediate_img,
                                      intermediate_centre_col,
                                      intermediate_centre_row, int_half_px)

    # Cell position inside the source crop, in source pixels.
    cell_col_in_src_crop = source_cell_col - src_bbox[0]
    cell_row_in_src_crop = source_cell_row - src_bbox[1]
    # Intermediate optical centre inside the intermediate crop, in intermediate pixels.
    centre_col_in_int_crop = intermediate_centre_col - int_bbox[0]
    centre_row_in_int_crop = intermediate_centre_row - int_bbox[1]

    if source_pixel_um < intermediate_pixel_um:
        # Source is finer; downsample source, keep intermediate.
        ref_img = _resample_to_pixel_size(src_crop, source_pixel_um,
                                          common_pixel_um)
        tgt_img = int_crop
        scale = source_pixel_um / common_pixel_um
        cell_col_in_ref = cell_col_in_src_crop * scale
        cell_row_in_ref = cell_row_in_src_crop * scale
        centre_col_in_tgt = centre_col_in_int_crop
        centre_row_in_tgt = centre_row_in_int_crop
    else:
        # Intermediate is finer (or equal); downsample intermediate, keep source.
        ref_img = src_crop
        tgt_img = _resample_to_pixel_size(int_crop, intermediate_pixel_um,
                                          common_pixel_um)
        cell_col_in_ref = cell_col_in_src_crop
        cell_row_in_ref = cell_row_in_src_crop
        scale = intermediate_pixel_um / common_pixel_um
        centre_col_in_tgt = centre_col_in_int_crop * scale
        centre_row_in_tgt = centre_row_in_int_crop * scale

    return {
        "ref_img": ref_img,
        "tgt_img": tgt_img,
        "registration_pixel_um": common_pixel_um,
        "common_fov_um": common_fov_um,
        "source_cell_in_ref_px": (float(cell_col_in_ref),
                                  float(cell_row_in_ref)),
        "intermediate_centre_in_tgt_px": (float(centre_col_in_tgt),
                                          float(centre_row_in_tgt)),
        "source_crop_bbox_px": list(src_bbox),
        "intermediate_crop_bbox_px": list(int_bbox),
        "ref_shape": list(ref_img.shape),
        "tgt_shape": list(tgt_img.shape),
    }


# ---------------------------------------------------------------------------
# Registration methods + consensus clustering
# ---------------------------------------------------------------------------
# Methods lifted from vendor/leica/test/test_registration_benchmark.py.
# Each returns (dx_um, dy_um, quality). NaN dx/dy means the method failed.


def _method_pcc(ref, tgt, pixel_um, _mask_pct):
    shift, error, _ = phase_cross_correlation(
        ref.astype(np.float64), tgt.astype(np.float64),
        upsample_factor=100,
    )
    dy_px, dx_px = shift
    return dx_px * pixel_um, dy_px * pixel_um, float(error)


def _method_masked_pcc(ref, tgt, pixel_um, mask_pct):
    ref_mask = ref > np.percentile(ref, mask_pct)
    tgt_mask = tgt > np.percentile(tgt, mask_pct)
    shift, error, _ = phase_cross_correlation(
        ref.astype(np.float64), tgt.astype(np.float64),
        upsample_factor=100,
        reference_mask=ref_mask, moving_mask=tgt_mask,
    )
    dy_px, dx_px = shift
    return dx_px * pixel_um, dy_px * pixel_um, float(error)


def _method_ncc(ref, tgt, pixel_um, _mask_pct):
    ref8 = (ref.astype(np.float64) / (ref.max() or 1) * 255).astype(np.uint8)
    tgt8 = (tgt.astype(np.float64) / (tgt.max() or 1) * 255).astype(np.uint8)
    h, w = tgt8.shape
    margin = h // 4
    template = tgt8[margin:h - margin, margin:w - margin]
    result = cv2.matchTemplate(ref8, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    match_cx = max_loc[0] + template.shape[1] / 2.0
    match_cy = max_loc[1] + template.shape[0] / 2.0
    dx_px = match_cx - w / 2.0
    dy_px = match_cy - h / 2.0
    return dx_px * pixel_um, dy_px * pixel_um, float(max_val)


def _method_orb(ref, tgt, pixel_um, _mask_pct):
    ref_n = (ref.astype(np.float64) / (ref.max() or 1) * 255).astype(np.uint8)
    tgt_n = (tgt.astype(np.float64) / (tgt.max() or 1) * 255).astype(np.uint8)

    orb = ORB(n_keypoints=500, fast_threshold=0.05)
    try:
        orb.detect_and_extract(ref_n)
        kp_ref, desc_ref = orb.keypoints, orb.descriptors
        orb.detect_and_extract(tgt_n)
        kp_tgt, desc_tgt = orb.keypoints, orb.descriptors
    except Exception:
        return float("nan"), float("nan"), 0.0

    if (desc_ref is None or desc_tgt is None
            or len(desc_ref) < 3 or len(desc_tgt) < 3):
        return float("nan"), float("nan"), 0.0

    matches = match_descriptors(desc_ref, desc_tgt, cross_check=True)
    if len(matches) < 3:
        return float("nan"), float("nan"), 0.0

    src = kp_tgt[matches[:, 1]]
    dst = kp_ref[matches[:, 0]]
    model, inliers = ransac(
        (src, dst), EuclideanTransform, min_samples=3,
        residual_threshold=5, max_trials=1000,
    )
    if model is None or inliers is None:
        return float("nan"), float("nan"), 0.0

    dy_px = model.translation[0]
    dx_px = model.translation[1]
    return dx_px * pixel_um, dy_px * pixel_um, float(inliers.sum() / len(matches))


METHODS = [
    ("PCC", _method_pcc),
    ("Masked PCC", _method_masked_pcc),
    ("NCC", _method_ncc),
    ("ORB+RANSAC", _method_orb),
]


def _largest_clique(estimates, tolerance_um):
    """Largest subset where every pairwise (dx, dy) distance is
    <= tolerance_um. Returns indices into *estimates*. With n=4 the
    brute-force enumeration is trivial; first clique found at the
    largest size wins (ties not disambiguated — they're rare and the
    diagnostic shows which methods agreed).
    """
    n = len(estimates)
    if n == 0:
        return []

    def is_clique(indices):
        for ii in range(len(indices)):
            for jj in range(ii + 1, len(indices)):
                a, b = estimates[indices[ii]], estimates[indices[jj]]
                if math.hypot(a["dx_um"] - b["dx_um"],
                              a["dy_um"] - b["dy_um"]) > tolerance_um:
                    return False
        return True

    from itertools import combinations
    for size in range(n, 0, -1):
        for combo in combinations(range(n), size):
            if is_clique(combo):
                return list(combo)
    return []


def _cluster_vote(ref, tgt, pixel_um, *, tolerance_um, min_cluster, mask_pct):
    """Run methods, cluster valid estimates, return cluster median + meta."""
    per_method = []
    for name, func in METHODS:
        t0 = time.time()
        try:
            dx, dy, q = func(ref, tgt, pixel_um, mask_pct)
            failed = not (np.isfinite(dx) and np.isfinite(dy))
        except Exception as e:
            dx, dy, q, failed = float("nan"), float("nan"), 0.0, True
            log.warning("  %s raised: %s", name, e)
        per_method.append({
            "name": name,
            "dx_um": float(dx), "dy_um": float(dy),
            "quality": float(q), "failed": failed,
            "in_cluster": False,
            "time_s": time.time() - t0,
        })
        if failed:
            log.info("  %-12s FAILED", name)
        else:
            log.info("  %-12s (%+7.2f, %+7.2f) um  q=%.3f  t=%.2fs",
                     name, dx, dy, q, per_method[-1]["time_s"])

    valid = [m for m in per_method if not m["failed"]]
    if not valid:
        return None, per_method, None

    valid_idx = [i for i, m in enumerate(per_method) if not m["failed"]]
    clique = _largest_clique(valid, tolerance_um)
    if len(clique) < min_cluster:
        return None, per_method, None

    chosen_global = [valid_idx[k] for k in clique]
    for gi in chosen_global:
        per_method[gi]["in_cluster"] = True

    dxs = np.array([per_method[i]["dx_um"] for i in chosen_global])
    dys = np.array([per_method[i]["dy_um"] for i in chosen_global])
    chosen_xy = (float(np.median(dxs)), float(np.median(dys)))

    spread = 0.0
    for ii in range(len(chosen_global)):
        for jj in range(ii + 1, len(chosen_global)):
            a = per_method[chosen_global[ii]]
            b = per_method[chosen_global[jj]]
            d = math.hypot(a["dx_um"] - b["dx_um"], a["dy_um"] - b["dy_um"])
            if d > spread:
                spread = d

    cluster_meta = {
        "indices": chosen_global,
        "names": [per_method[i]["name"] for i in chosen_global],
        "size": len(chosen_global),
        "spread_um": spread,
        "min_required": min_cluster,
        "tolerance_um": tolerance_um,
    }
    return chosen_xy, per_method, cluster_meta


# ---------------------------------------------------------------------------
# Galvo geometry
# ---------------------------------------------------------------------------

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


def _within_galvo_range(target_xy_um, stage_xy_um, pan_scale_um):
    dx = float(target_xy_um[0]) - float(stage_xy_um[0])
    dy = float(target_xy_um[1]) - float(stage_xy_um[1])
    max_um = drv.PAN_LIMIT * float(pan_scale_um)
    return abs(dx) <= max_um and abs(dy) <= max_um, (dx, dy), max_um


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def _save_voting_diagnostic(path, source_img, intermediate_for_match,
                            per_method, median_xy_um, cluster_spread_um,
                            pixel_um):
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    ax = axes[0]
    ax.imshow(source_img, cmap="gray")
    ax.set_title("Source")
    ax.axis("off")

    ax = axes[1]
    ax.imshow(intermediate_for_match, cmap="gray")
    h, w = intermediate_for_match.shape[:2]
    cx0, cy0 = w / 2.0, h / 2.0

    colors = {"PCC": "#CC6600", "Masked PCC": "#006600",
              "NCC": "#0066CC", "ORB+RANSAC": "#9900CC"}
    for m in per_method:
        if m["failed"]:
            continue
        px = cx0 + m["dx_um"] / pixel_um
        py = cy0 + m["dy_um"] / pixel_um
        marker = "+" if m["in_cluster"] else "x"
        tag = "" if m["in_cluster"] else " [outlier]"
        ax.plot(px, py, marker, color=colors.get(m["name"], "white"),
                markersize=18, markeredgewidth=2,
                label=f"{m['name']}{tag}  ({m['dx_um']:+.1f}, {m['dy_um']:+.1f})")
    if median_xy_um is not None:
        mdx, mdy = median_xy_um
        mx = cx0 + mdx / pixel_um
        my = cy0 + mdy / pixel_um
        ax.plot(mx, my, "x", color="red", markersize=20, markeredgewidth=3,
                label=f"CLUSTER MEDIAN  ({mdx:+.1f}, {mdy:+.1f})")
    ax.plot(cx0, cy0, "c+", markersize=14, markeredgewidth=2,
            label="centre (aim)")
    title = "Intermediate (matched pixel size)"
    if cluster_spread_um is not None:
        title += f"  cluster spread: {cluster_spread_um:.2f} um"
    ax.set_title(title)
    ax.legend(loc="upper right", fontsize=8)
    ax.axis("off")

    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def _save_overlay(path, source_img, source_prop, final_img, target_error,
                  median_xy_um, cluster_spread_um):
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
    ax.imshow(final_img, cmap="gray")
    h, w = final_img.shape[:2]
    ax.plot(w / 2.0, h / 2.0, "c+", markersize=18, markeredgewidth=2)
    if target_error:
        tc_y, tc_x = target_error["centroid_px"]
        ax.plot(tc_x, tc_y, "r+", markersize=18, markeredgewidth=2)
        title = (f"Landing {target_error['distance_from_center_um']:.2f} um  "
                 f"corr ({median_xy_um[0]:+.1f}, {median_xy_um[1]:+.1f}) um  "
                 f"spread {cluster_spread_um:.2f}")
    else:
        title = (f"Final  corr ({median_xy_um[0]:+.1f}, {median_xy_um[1]:+.1f}) um  "
                 f"spread {cluster_spread_um:.2f}")
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

    print(f"Job:           {args.job}")
    print(f"Source slot:   {args.source_slot}")
    print(f"Target slot:   {args.target_slot}")
    print("Actuator:      galvo pan, voting registration")
    print(f"Tolerance:     {args.agreement_tolerance_um} um pairwise")
    print(f"Output dir:    {out_dir}\n")

    # ---- Source pass: pick cell --------------------------------------------

    log.info("switching to source objective")
    drv.set_objective(client, args.job, hw, slot_index=args.source_slot)
    time.sleep(args.settle)
    drv.set_zoom(client, args.job, 1.0)
    time.sleep(0.5)

    src_stage = drv.get_xy(client)
    src_stage_xy_um = (src_stage["x_um"], src_stage["y_um"])
    src_geo = drv.parse_tile_geometry(
        drv.get_job_settings(client, args.job) or {},
    )
    src_pixel_size_um = float(src_geo["pixel_w_um"])
    src_image_size = int(src_geo["pixels_x"])

    log.info("loading Cellpose (gpu=%s)", not args.no_gpu)
    cp_model = models.CellposeModel(gpu=not args.no_gpu)

    src_img, src_path = _acquire_one(client, args.job)
    tifffile.imwrite(str(out_dir / "source.tif"), src_img)

    _, src_prop = _segment_pick(src_img, cp_model, args)
    cy_px, cx_px = src_prop.centroid
    min_r, min_c, max_r, max_c = src_prop.bbox
    bbox_w_um = (max_c - min_c) * src_pixel_size_um
    bbox_h_um = (max_r - min_r) * src_pixel_size_um

    cell_source_xy_um = drv.pixel_to_stage_xy_um(
        cx_px, cy_px,
        stage_xy_um=src_stage_xy_um,
        pixel_size_um=src_pixel_size_um,
        image_size=src_image_size,
        config=cfg,
    )
    cell_target_xy_um_initial = drv.translate_stage_xy_between_objectives(
        *cell_source_xy_um, cfg,
        from_slot=args.source_slot,
        to_slot=args.target_slot,
    )
    log.info("cell source-frame=(%.3f, %.3f)  predicted=(%.3f, %.3f)",
             *cell_source_xy_um, *cell_target_xy_um_initial)

    # ---- Target: switch, intermediate zoom + galvo pan ---------------------

    log.info("switching to target objective")
    drv.set_objective(client, args.job, hw, slot_index=args.target_slot)
    time.sleep(args.settle)

    target_base_fov_m = drv.get_base_fov(client, args.job)
    if not target_base_fov_m:
        _abort("Could not read target base FOV.")
    target_base_fov_um = target_base_fov_m[0] * 1e6
    pan_scale_um = drv.pan_scale_um_from_base_fov(target_base_fov_um)
    max_pan_um = drv.PAN_LIMIT * pan_scale_um

    ideal_intermediate_zoom = (
        target_base_fov_um / (src_pixel_size_um * src_image_size)
    )
    intermediate_zoom = max(1, int(round(ideal_intermediate_zoom)))
    intermediate_fov_um = target_base_fov_um / intermediate_zoom
    intermediate_pixel_size_um = intermediate_fov_um / src_image_size
    resample_factor = intermediate_pixel_size_um / src_pixel_size_um
    log.info("intermediate zoom=%d FOV=%.1f um pixel=%.4f um "
             "(downsample by %.2fx for registration)",
             intermediate_zoom, intermediate_fov_um,
             intermediate_pixel_size_um, 1.0 / resample_factor)

    drv.set_zoom(client, args.job, intermediate_zoom)
    time.sleep(0.5)

    cur_xy = _current_stage_xy(client)
    in_range, off0, _ = _within_galvo_range(
        cell_target_xy_um_initial, cur_xy, pan_scale_um,
    )
    if not in_range:
        _abort(f"cell outside galvo range: pan would need "
               f"({off0[0]:.1f}, {off0[1]:.1f}) um, max +/-{max_pan_um:.0f} um.")

    r_pan = drv.move_xy_galvo(client, *cell_target_xy_um_initial, unit="um",
                              job_name=args.job)
    if not r_pan or not r_pan.get("success"):
        _abort(f"intermediate galvo pan failed: {r_pan}")

    log.info("acquiring intermediate frame")
    int_img, int_path = _acquire_one(client, args.job)
    tifffile.imwrite(str(out_dir / "target_intermediate.tif"), int_img)

    # ---- Prepare matched registration pair --------------------------------

    prep = _prepare_registration_pair(
        src_img, int_img,
        source_pixel_um=src_pixel_size_um,
        intermediate_pixel_um=intermediate_pixel_size_um,
        source_cell_col=cx_px, source_cell_row=cy_px,
    )
    ref_img = prep["ref_img"]
    tgt_img = prep["tgt_img"]
    reg_pixel_um = prep["registration_pixel_um"]
    ref_cell_col, ref_cell_row = prep["source_cell_in_ref_px"]
    log.info("registration prep: ref %s tgt %s pixel=%.4f um FOV=%.1f um "
             "(source crop=%s, intermediate crop=%s)",
             prep["ref_shape"], prep["tgt_shape"],
             reg_pixel_um, prep["common_fov_um"],
             prep["source_crop_bbox_px"], prep["intermediate_crop_bbox_px"])
    tifffile.imwrite(str(out_dir / "registration_ref.tif"),
                     ref_img.astype(src_img.dtype))
    tifffile.imwrite(str(out_dir / "registration_tgt.tif"),
                     tgt_img.astype(int_img.dtype))

    # ---- Cluster-vote registration -----------------------------------------

    log.info("running cluster-vote registration (%d methods, tol=%.2f um, "
             "min cluster=%d)", len(METHODS),
             args.agreement_tolerance_um, args.min_cluster)
    median_xy_um, per_method, cluster_meta = _cluster_vote(
        ref_img, tgt_img, reg_pixel_um,
        tolerance_um=args.agreement_tolerance_um,
        min_cluster=args.min_cluster,
        mask_pct=args.mask_pct,
    )
    cluster_spread_um = cluster_meta["spread_um"] if cluster_meta else None

    _save_voting_diagnostic(
        out_dir / "voting_diagnostic.png",
        ref_img, tgt_img, per_method, median_xy_um, cluster_spread_um,
        reg_pixel_um,
    )

    if median_xy_um is None:
        n_ok = sum(1 for m in per_method if not m["failed"])
        failure = {
            "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "method": "single_target_galvo_one_shot",
            "status": "cluster_vote_unconverged",
            "failure_reason": (
                f"no clique of >= {args.min_cluster} methods within "
                f"{args.agreement_tolerance_um} um tolerance "
                f"({n_ok}/{len(METHODS)} methods produced a valid estimate)"
            ),
            "job": args.job,
            "source_slot": args.source_slot,
            "target_slot": args.target_slot,
            "cell_source_xy_um": list(cell_source_xy_um),
            "cell_target_xy_um_initial": list(cell_target_xy_um_initial),
            "voting": {
                "per_method": per_method,
                "tolerance_um": args.agreement_tolerance_um,
                "min_cluster": args.min_cluster,
            },
            "outputs": {
                "source_tif": str(out_dir / "source.tif"),
                "target_intermediate_tif": str(out_dir / "target_intermediate.tif"),
                "registration_ref_tif": str(out_dir / "registration_ref.tif"),
                "registration_tgt_tif": str(out_dir / "registration_tgt.tif"),
                "voting_diagnostic_png": str(out_dir / "voting_diagnostic.png"),
                "summary_json": str(out_dir / "summary.json"),
            },
        }
        _write_json(out_dir / "summary.json", failure)
        _abort(failure["failure_reason"]
               + f". See {out_dir / 'voting_diagnostic.png'}")

    log.info("cluster median dx=%+.3f dy=%+.3f um  spread=%.3f um  "
             "(cluster=%s, %d/%d methods)",
             median_xy_um[0], median_xy_um[1], cluster_spread_um,
             cluster_meta["names"], cluster_meta["size"], len(METHODS))

    # Direct mapping: voting gave us the median translation between ref
    # and tgt in registration-frame um. The cell's pixel position in
    # tgt = its position in ref + the voted shift (in image-pixel
    # axes; both ref and tgt share the same pixel grid orientation).
    # pixel_to_stage_xy_um then applies the calibrated sign matrix
    # (cfg["sign_convention"]["image_to_stage_um"]) to translate that
    # tgt pixel into stage XY relative to the intermediate's optical
    # centre. No hardcoded sign convention here.
    intermediate_image_center_xy = _image_center_from_pan(
        _current_stage_xy(client), r_pan,
    )
    shift_col_px = median_xy_um[0] / reg_pixel_um
    shift_row_px = median_xy_um[1] / reg_pixel_um
    cell_col_in_tgt = ref_cell_col + shift_col_px
    cell_row_in_tgt = ref_cell_row + shift_row_px
    tgt_image_size = tgt_img.shape[1]
    cell_target_xy_um_corrected = drv.pixel_to_stage_xy_um(
        cell_col_in_tgt, cell_row_in_tgt,
        stage_xy_um=intermediate_image_center_xy,
        pixel_size_um=reg_pixel_um,
        image_size=tgt_image_size,
        config=cfg,
    )
    correction_um = (cell_target_xy_um_corrected[0] - cell_target_xy_um_initial[0],
                     cell_target_xy_um_corrected[1] - cell_target_xy_um_initial[1])
    log.info("calibration residual: (%+.3f, %+.3f) um  mag=%.3f",
             *correction_um, math.hypot(*correction_um))

    # ---- Final pan and acquire --------------------------------------------

    final_zoom = drv.bbox_to_zoom(
        bbox_w_um, bbox_h_um, target_base_fov_um,
        margin=args.fov_bbox_margin,
    )

    cur_xy_now = _current_stage_xy(client)
    in_range_final, off_f, _ = _within_galvo_range(
        cell_target_xy_um_corrected, cur_xy_now, pan_scale_um,
    )
    if not in_range_final:
        _abort(f"corrected XY outside galvo range: need "
               f"({off_f[0]:.1f}, {off_f[1]:.1f}) um, max +/-{max_pan_um:.0f}.")

    drv.set_zoom(client, args.job, final_zoom)
    time.sleep(0.5)
    r_pan_final = drv.move_xy_galvo(client, *cell_target_xy_um_corrected,
                                    unit="um", job_name=args.job)
    if not r_pan_final or not r_pan_final.get("success"):
        _abort(f"final galvo pan failed: {r_pan_final}")

    final_stage_xy = _current_stage_xy(client)
    final_image_center_xy = _image_center_from_pan(final_stage_xy, r_pan_final)

    log.info("acquiring final frame (zoom=%d FOV=%.1f um)",
             final_zoom, target_base_fov_um / final_zoom)
    final_img, final_path = _acquire_one(client, args.job)
    tifffile.imwrite(str(out_dir / "target_final.tif"), final_img)

    final_geo = drv.parse_tile_geometry(
        drv.get_job_settings(client, args.job) or {},
    )
    final_pixel_size_um = float(final_geo["pixel_w_um"])
    target_error = _measure_target_error_um(
        final_img, final_pixel_size_um, cp_model, args,
    )

    _save_overlay(out_dir / "overlay.png", src_img, src_prop, final_img,
                  target_error, median_xy_um, cluster_spread_um)

    summary = {
        "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "method": "single_target_galvo_one_shot",
        "actuator": "galvo_pan_oneshot",
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
        },
        "cell_source_xy_um": list(cell_source_xy_um),
        "cell_target_xy_um_initial": list(cell_target_xy_um_initial),
        "cell_target_xy_um_corrected": list(cell_target_xy_um_corrected),
        "calibration_residual_um": list(correction_um),
        "calibration_residual_magnitude_um": math.hypot(*correction_um),
        "intermediate": {
            "zoom": intermediate_zoom,
            "fov_um": intermediate_fov_um,
            "pixel_size_um": intermediate_pixel_size_um,
            "image_center_xy_um": list(intermediate_image_center_xy),
            "intermediate_lasx_tif": str(int_path),
        },
        "registration_prep": {
            "registration_pixel_um": reg_pixel_um,
            "common_fov_um": prep["common_fov_um"],
            "ref_shape": prep["ref_shape"],
            "tgt_shape": prep["tgt_shape"],
            "source_crop_bbox_px": prep["source_crop_bbox_px"],
            "intermediate_crop_bbox_px": prep["intermediate_crop_bbox_px"],
            "source_cell_in_ref_px": list(prep["source_cell_in_ref_px"]),
            "intermediate_centre_in_tgt_px": list(prep["intermediate_centre_in_tgt_px"]),
        },
        "voting": {
            "per_method": per_method,
            "median_xy_um": list(median_xy_um),
            "cluster": cluster_meta,
            "tolerance_um": args.agreement_tolerance_um,
            "min_cluster": args.min_cluster,
            "mask_pct": args.mask_pct,
        },
        "final": {
            "zoom": final_zoom,
            "fov_um": target_base_fov_um / final_zoom,
            "pixel_size_um": final_pixel_size_um,
            "stage_xy_um": list(final_stage_xy),
            "image_center_xy_um": list(final_image_center_xy),
            "pan": list(r_pan_final.get("pan") or (None, None)),
            "offset_um": list(r_pan_final.get("offset_um") or (None, None)),
            "pan_scale_um": r_pan_final.get("pan_scale_um"),
            "final_lasx_tif": str(final_path),
        },
        "pan_scale_um": pan_scale_um,
        "pan_max_reachable_um": max_pan_um,
        "target_error": target_error,
        "outputs": {
            "source_tif": str(out_dir / "source.tif"),
            "target_intermediate_tif": str(out_dir / "target_intermediate.tif"),
            "registration_ref_tif": str(out_dir / "registration_ref.tif"),
            "registration_tgt_tif": str(out_dir / "registration_tgt.tif"),
            "target_final_tif": str(out_dir / "target_final.tif"),
            "voting_diagnostic_png": str(out_dir / "voting_diagnostic.png"),
            "overlay_png": str(out_dir / "overlay.png"),
            "summary_json": str(out_dir / "summary.json"),
            "source_lasx_tif": str(src_path),
        },
    }
    _write_json(out_dir / "summary.json", summary)

    print(f"\nCluster: {cluster_meta['names']} ({cluster_meta['size']}/"
          f"{len(METHODS)} methods)")
    print(f"Cluster median: ({median_xy_um[0]:+.2f}, {median_xy_um[1]:+.2f}) um  "
          f"spread: {cluster_spread_um:.2f} um (tol {args.agreement_tolerance_um})")
    print(f"Calibration residual: ({correction_um[0]:+.2f}, "
          f"{correction_um[1]:+.2f}) um  mag={math.hypot(*correction_um):.2f} um")
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

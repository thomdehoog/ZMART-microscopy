"""
Galvo zoom-in example — same objective, no stage move.
======================================================

What this script does, in one line
----------------------------------
Acquire an overview at zoom 1, pick a cell, then galvo-pan + zoom-in
on the SAME objective to image that cell at high zoom — without
moving the motorised stage.

Why galvo, not stage?
---------------------
The galvo deflects the scan beam, the motorised stage moves the
sample. For sub-FOV navigation:

    - **Stage**: large range (cm), but settle is ~5–10 µm and slow
      (hundreds of ms per move).
    - **Galvo**: tiny range (~775 µm at 10×, scaling DOWN with
      magnification — see PAN_SCALE note below), but sub-µm
      reproducibility and effectively instantaneous.

When the cell of interest lies inside the galvo reach, panning is
strictly better than driving the stage. This script is the canonical
"go from overview to high zoom on one cell" recipe.

The PAN_SCALE caveat
--------------------
A unit of galvo pan is a fixed *angle*. The resulting sample shift in
microns scales with the objective's focal length, which is captured
by the objective's base FOV. ``drv.pan_scale_um_from_base_fov(base)``
resolves it at call time:

    pan_scale_um  ≈ base_fov_um × 86.07
    galvo_reach_um = pan_scale_um × PAN_LIMIT (= 0.00775)

So at 10× (base FOV ≈ 1160 µm) the galvo reaches ±775 µm; at 20×
(base FOV ≈ 581 µm) it's ±388 µm; at 40× ±194 µm. ``move_xy_galvo``
already resolves this internally — the script only uses pan_scale to
sanity-check reachability before moving.

Recipe
------
The pipeline is one function per step; ``main()`` chains them.

    1. Setup: connect, validate orientation, resolve job, set limits.
    2. Acquire overview at zoom 1 on the currently selected objective.
    3. Cellpose-segment; pick the n-th-closest cell to image centre.
    4. Convert pixel centroid → absolute stage XY in the image frame
       (uses ``pixel_to_absolute_um``, NOT ``pixel_to_stage_xy_um`` —
       the galvo draws the image, so its axes are image-aligned;
       see memory ``feedback_pan_uses_image_frame``).
    5. Choose target zoom that frames ``--fov-bbox-margin × bbox``.
    6. Disable ROI scan (otherwise scanner only illuminates the ROI
       region and panning shows nothing — see memory
       ``feedback_roi_scan_before_pan``).
    7. Set zoom FIRST, then pan. Reversing the order makes LAS X
       silently re-clamp pan during the zoom change (see memory
       ``feedback_pan_then_zoom_clamps``).
    8. Acquire the framed image. Do not insert ``time.sleep`` or
       ``check_idle`` between pan and acquire (memory
       ``feedback_no_check_idle_after_pan``).
    9. Optionally restore overview state (zoom 1, pan 0).
   10. Save source.tif, framed.tif, overlay.png, summary.json.

Operator preconditions
----------------------
- A job is currently selected in LAS X.
- ``ImageTransformation = TOPLEFT`` in LAS X Advanced Settings.
- AFC / autofocus OFF; no LAS X modal dialogs.
- Stage positioned over a region with cells visible at the current
  objective at zoom 1.

Usage
-----
    python galvo_zoom_in.py
    python galvo_zoom_in.py --pick-rank 3
    python galvo_zoom_in.py --fov-bbox-margin 2.0 --no-restore
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

# Allow ``import navigator_expert`` from any CWD.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import tifffile
from cellpose import models
from matplotlib.patches import Rectangle
from skimage.measure import regionprops

from LasxApi import PYLICamApiConnector as lasx_api  # type: ignore
import navigator_expert.driver as drv


log = logging.getLogger("galvo_zoom_in")


# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

#: Overview is always acquired at this zoom — gives the widest FOV at
#: the current objective and the most cells for Cellpose to choose from.
OVERVIEW_ZOOM: float = 1.0

#: Target FOV = this × the picked cell's bounding box.
DEFAULT_FOV_BBOX_MARGIN: float = 1.5

#: Wait this long between successive zoom/job edits to let LAS X
#: commit the LRP changes.
SETTLE_AFTER_LAS_X_EDIT_S: float = 0.5

#: Maximum time to wait for LAS X to report "scanner idle" (used only
#: at the very start; never between pan and acquire — that path
#: triggers "Scan not started" timeouts).
IDLE_TIMEOUT_S: float = 5.0

#: Maximum time to wait for OME-TIFF files to be unlocked + size-stable.
FILE_STABILITY_TIMEOUT_S: int = 30

#: Backlash takeup is applied before every acquire by default. The
#: galvo doesn't move the stage, so backlash only matters for the
#: stage state at the start of the run (and any future stage moves).
DEFAULT_APPLY_BACKLASH: bool = True


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Pick a cell at zoom 1 and galvo-pan + zoom-in on the "
                    "same objective.",
    )
    p.add_argument("--job", default=None,
                   help="LAS X job name. Default: the currently selected job.")
    p.add_argument("--fov-bbox-margin", type=float, default=DEFAULT_FOV_BBOX_MARGIN,
                   help=f"Target FOV = this × cell bbox "
                        f"(default: {DEFAULT_FOV_BBOX_MARGIN}).")
    p.add_argument("--pick-rank", type=int, default=0,
                   help="Which cell to target by distance from the overview "
                        "centre: 0=closest, 1=next, ... Default: 0.")
    p.add_argument("--diameter", type=float, default=None,
                   help="Cellpose nucleus diameter in overview pixels "
                        "(default: auto). The framed-frame diameter is "
                        "always derived from the picked cell's bbox.")
    p.add_argument("--no-gpu", action="store_true",
                   help="Disable GPU for Cellpose.")
    p.add_argument("--output-dir", type=Path, default=None,
                   help="Where to save outputs "
                        "(default: config/galvo_zoom/<timestamp>/).")
    p.add_argument("--no-restore", action="store_true",
                   help="Leave the scope at the framed zoom + pan; do not "
                        "return to zoom 1 + pan 0.")
    p.add_argument("--no-backlash", action="store_true",
                   help="Skip the +X+Y backlash takeup before the overview "
                        "acquire. The galvo moves don't need backlash, but "
                        "settling the stage at the start gives a reproducible "
                        "starting position.")
    return p.parse_args(argv)


# ──────────────────────────────────────────────────────────────────────
# Domain types
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FrameGeometry:
    """Geometry of one acquired frame."""
    pixel_size_um: float
    image_size_px: int

    @property
    def fov_um(self) -> float:
        return self.pixel_size_um * self.image_size_px


@dataclass(frozen=True)
class CellPick:
    """The cell chosen at the overview frame."""
    centroid_xy_px: tuple[float, float]
    bbox_px: tuple[int, int, int, int]
    bbox_um: tuple[float, float]
    area_px: int
    eccentricity: float
    geometry: FrameGeometry
    overview_stage_xy_um: tuple[float, float]


@dataclass(frozen=True)
class LandingResult:
    """Outcome of identifying the picked cell in the framed frame."""
    cells_segmented: int
    error_um: tuple[float, float] | None
    error_magnitude_um: float | None
    morphology_score: float | None
    matched_prop: Any | None


# ──────────────────────────────────────────────────────────────────────
# Tiny utilities
# ──────────────────────────────────────────────────────────────────────


def _abort(msg: str, code: int = 1) -> None:
    print(f"ABORT: {msg}")
    sys.exit(code)


def _default_output_dir() -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return (Path(__file__).resolve().parents[2]
            / "config" / "galvo_zoom" / ts)


def _now_iso_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


# ──────────────────────────────────────────────────────────────────────
# LAS X interaction
# ──────────────────────────────────────────────────────────────────────


def connect_lasx() -> Any:
    client = lasx_api.LasxApiClientPyModel
    if not client.Connect("PythonClient"):
        _abort("Cannot connect to LAS X.", 2)
    if not drv.ping(client):
        _abort("LAS X ping failed.", 2)
    return client


def check_image_orientation_is_topleft() -> None:
    settings = drv.get_lasx_settings() or {}
    orient = settings.get("image_orientation", {}) or {}
    if (orient.get("enable_transform", False)
            and orient.get("transformation", "TOPLEFT") != "TOPLEFT"):
        _abort(f"ImageTransformation is "
               f"'{orient.get('transformation')}'; set it to TOPLEFT in "
               f"LAS X Advanced Settings.", 2)


def resolve_job(client: Any, override: str | None) -> str:
    if override:
        return override
    selected = drv.get_selected_job(client) or {}
    name = selected.get("Name")
    if not name:
        _abort("No job selected in LAS X. Pass --job or select one in the UI.")
    return name




def read_frame_geometry(client: Any, job: str) -> FrameGeometry:
    settings = drv.get_job_settings(client, job) or {}
    geo = drv.parse_tile_geometry(settings)
    return FrameGeometry(
        pixel_size_um=float(geo["pixel_w_um"]),
        image_size_px=int(geo["pixels_x"]),
    )


def disable_roi_scan(client: Any, job: str) -> None:
    """ROI scan must be off before pan/zoom or the scanner only
    illuminates the ROI region.
    """
    from navigator_expert.driver.scanning_template_editors_roi import (
        lrp_enable_roi_scan, lrp_verify_roi_scan,
    )
    from navigator_expert.driver.scanning_templates import (
        TEMPLATE_XML, apply_lrp_change,
    )
    apply_lrp_change(
        client, TEMPLATE_XML,
        lambda p: lrp_enable_roi_scan(p, False, job),
        verify_fn=lambda p: lrp_verify_roi_scan(p, False, job),
    )


# ──────────────────────────────────────────────────────────────────────
# Image analysis
# ──────────────────────────────────────────────────────────────────────


def pick_cell_by_distance_rank(masks: np.ndarray, rank: int) -> Any | None:
    """Return the regionprops object at the given distance-from-centre rank."""
    props = regionprops(masks)
    if not props:
        return None
    h, w = masks.shape[:2]
    cy, cx = h / 2.0, w / 2.0
    by_dist = sorted(
        props,
        key=lambda p: (p.centroid[0] - cy) ** 2 + (p.centroid[1] - cx) ** 2,
    )
    if rank >= len(by_dist):
        return None
    return by_dist[rank]


def measure_landing_error_by_morphology(
    target_masks: np.ndarray,
    target_image_shape: tuple[int, ...],
    source_pick: CellPick,
    target_pixel_size_um: float,
) -> LandingResult:
    """Identify the source cell in the framed frame by morphology.

    Compares each segmented cell's area (normalised) and eccentricity
    to the picked cell, then reports the best match's centroid offset
    from the FOV centre.
    """
    target_props = regionprops(target_masks)
    src_area_um2 = source_pick.area_px * (source_pick.geometry.pixel_size_um ** 2)
    src_ecc = float(source_pick.eccentricity)

    if not target_props:
        return LandingResult(0, None, None, None, None)

    h, w = target_image_shape[:2]
    cy_centre, cx_centre = h / 2.0, w / 2.0

    best = None
    best_score = float("inf")
    for p in target_props:
        tgt_area_um2 = p.area * (target_pixel_size_um ** 2)
        tgt_ecc = float(p.eccentricity)
        area_diff = abs(tgt_area_um2 - src_area_um2) / max(src_area_um2, 1.0)
        ecc_diff = abs(tgt_ecc - src_ecc)
        score = area_diff + ecc_diff
        if score < best_score:
            best_score = score
            best = p

    assert best is not None
    cy, cx = best.centroid
    dx_um = (cx - cx_centre) * target_pixel_size_um
    dy_um = (cy - cy_centre) * target_pixel_size_um
    return LandingResult(
        cells_segmented=len(target_props),
        error_um=(dx_um, dy_um),
        error_magnitude_um=math.hypot(dx_um, dy_um),
        morphology_score=float(best_score),
        matched_prop=best,
    )


# ──────────────────────────────────────────────────────────────────────
# Visualisation
# ──────────────────────────────────────────────────────────────────────


def save_overlay_png(
    png_path: Path,
    overview_img: np.ndarray, framed_img: np.ndarray,
    pick: CellPick, landing: LandingResult,
) -> None:
    """Two-panel diagnostic PNG."""
    fig, axes = plt.subplots(1, 2, figsize=(12, 6))

    ax = axes[0]
    ax.imshow(overview_img, cmap="gray")
    ax.set_title("Overview (zoom 1): picked cell")
    min_r, min_c, max_r, max_c = pick.bbox_px
    ax.add_patch(Rectangle((min_c, min_r), max_c - min_c, max_r - min_r,
                           edgecolor="lime", facecolor="none", linewidth=1.5))
    sx, sy = pick.centroid_xy_px
    ax.plot(sx, sy, "r+", markersize=18, markeredgewidth=2)
    h, w = overview_img.shape[:2]
    ax.axvline(w / 2.0, color="white", linewidth=0.5, alpha=0.3)
    ax.axhline(h / 2.0, color="white", linewidth=0.5, alpha=0.3)
    ax.axis("off")

    ax = axes[1]
    ax.imshow(framed_img, cmap="gray")
    th, tw = framed_img.shape[:2]
    ax.plot(tw / 2.0, th / 2.0, "c+", markersize=18, markeredgewidth=2)
    ax.axvline(tw / 2.0, color="white", linewidth=0.5, alpha=0.3)
    ax.axhline(th / 2.0, color="white", linewidth=0.5, alpha=0.3)
    if landing.matched_prop is not None and landing.error_magnitude_um is not None:
        min_r, min_c, max_r, max_c = landing.matched_prop.bbox
        ax.add_patch(Rectangle((min_c, min_r), max_c - min_c, max_r - min_r,
                               edgecolor="lime", facecolor="none", linewidth=1.5))
        ty, tx = landing.matched_prop.centroid
        ax.plot(tx, ty, "r+", markersize=18, markeredgewidth=2)
        ax.set_title(f"Framed (galvo): matched cell vs FOV centre. "
                     f"Error = {landing.error_magnitude_um:.2f} um")
    else:
        ax.set_title("Framed (galvo): no cells segmented — "
                     "landing not verified")
    ax.axis("off")

    fig.tight_layout()
    fig.savefig(png_path, dpi=120)
    plt.close(fig)


# ──────────────────────────────────────────────────────────────────────
# Pipeline steps
# ──────────────────────────────────────────────────────────────────────


def step_setup(args: argparse.Namespace) -> tuple[Any, str, dict, Path]:
    """Connect, resolve job, set limits, idle check.

    Returns (client, job, stage_cfg, output_dir).
    """
    out_dir = args.output_dir or _default_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    stage_cfg = drv.load_stage_config()
    client = connect_lasx()
    check_image_orientation_is_topleft()
    drv.apply_stage_limits_from_config(stage_cfg)

    idle = drv.check_idle(client, timeout=IDLE_TIMEOUT_S)
    if not idle or not idle.get("success"):
        _abort(f"LAS X not idle: {idle}")

    job = resolve_job(client, args.job)

    print(f"Job:            {job}")
    print(f"Pick rank:      {args.pick_rank}")
    print(f"FOV margin:     {args.fov_bbox_margin}× bounding box")
    print(f"Backlash:       {'on' if not args.no_backlash else 'off'}")
    print(f"Restore on exit:{'no' if args.no_restore else 'yes'}")
    print(f"Output dir:     {out_dir}\n")

    return client, job, stage_cfg, out_dir


def step_acquire_overview(
    client: Any, job: str, args: argparse.Namespace, out_dir: Path,
    backlash_params: dict | None,
) -> tuple[np.ndarray, FrameGeometry, tuple[float, float], Path]:
    """Set zoom 1, acquire one frame, save it.

    Returns (image, geometry, stage_xy_um, source_tif_path).
    """
    drv.set_zoom(client, job, OVERVIEW_ZOOM)
    time.sleep(SETTLE_AFTER_LAS_X_EDIT_S)

    stage = drv.get_xy(client)
    if not stage:
        _abort("Could not read stage XY.")
    stage_xy_um = (float(stage["x_um"]), float(stage["y_um"]))
    log.info("overview stage XY = (%.3f, %.3f) um", *stage_xy_um)

    geometry = read_frame_geometry(client, job)
    log.info("overview geometry: pixel=%.4f um  FOV=%.1f um",
             geometry.pixel_size_um, geometry.fov_um)

    log.info("acquiring overview frame")
    img, _ = drv.acquire_frame(client, job, backlash_params=backlash_params)
    overview_tif = out_dir / "overview.tif"
    tifffile.imwrite(str(overview_tif), img)
    log.info("overview image %s saved → %s", img.shape, overview_tif.name)

    return img, geometry, stage_xy_um, overview_tif


def step_pick_cell(
    overview_img: np.ndarray, args: argparse.Namespace,
    geometry: FrameGeometry, stage_xy_um: tuple[float, float],
    cellpose_model: models.CellposeModel,
) -> CellPick:
    """Cellpose-segment and pick the n-th-closest cell to image centre."""
    log.info("running Cellpose on overview (gpu=%s)", not args.no_gpu)
    t0 = time.perf_counter()
    masks, _, _ = cellpose_model.eval(overview_img, diameter=args.diameter)
    n_cells = int(masks.max())
    log.info("Cellpose found %d cell(s) in %.1fs",
             n_cells, time.perf_counter() - t0)
    if n_cells == 0:
        _abort("Cellpose found no cells in the overview frame.")

    prop = pick_cell_by_distance_rank(masks, args.pick_rank)
    if prop is None:
        _abort(f"No cell at rank {args.pick_rank}. Lower --pick-rank or "
               f"move to a denser region.")

    cy, cx = prop.centroid
    min_r, min_c, max_r, max_c = prop.bbox
    bbox_w_um = (max_c - min_c) * geometry.pixel_size_um
    bbox_h_um = (max_r - min_r) * geometry.pixel_size_um
    pick = CellPick(
        centroid_xy_px=(float(cx), float(cy)),
        bbox_px=(int(min_r), int(min_c), int(max_r), int(max_c)),
        bbox_um=(float(bbox_w_um), float(bbox_h_um)),
        area_px=int(prop.area),
        eccentricity=float(prop.eccentricity),
        geometry=geometry,
        overview_stage_xy_um=stage_xy_um,
    )
    log.info("picked cell (rank %d): centroid=(%.1f, %.1f) px  "
             "bbox=(%.1f × %.1f) um  area=%d px",
             args.pick_rank, cx, cy, bbox_w_um, bbox_h_um, pick.area_px)
    return pick


def step_compute_target(
    client: Any, job: str, pick: CellPick, args: argparse.Namespace,
) -> tuple[tuple[float, float], int, float, float]:
    """Compute target absolute XY (image frame), framed zoom, base FOV.

    Aborts if the cell lies outside the galvo's reach.

    Returns (target_xy_um, framed_zoom, base_fov_um, pan_scale_um).
    """
    base_fov_m = drv.get_base_fov(client, job)
    if not base_fov_m:
        _abort("Could not read base FOV.")
    base_fov_um = float(base_fov_m[0] * 1e6)
    pan_scale_um = drv.pan_scale_um_from_base_fov(base_fov_um)
    galvo_reach_um = pan_scale_um * drv.PAN_LIMIT
    log.info("galvo reach = ±%.1f um at this objective "
             "(pan_scale=%.0f um/unit)", galvo_reach_um, pan_scale_um)

    # Image frame: pixel → absolute stage XY. At pan=(0,0) only the
    # stage XY and the pixel offset (with NO sign matrix — galvo is
    # image-aligned) contribute.
    cx, cy = pick.centroid_xy_px
    target_xy = drv.pixel_to_absolute_um(
        cx, cy,
        stage_x_um=pick.overview_stage_xy_um[0],
        stage_y_um=pick.overview_stage_xy_um[1],
        pan_x=0.0, pan_y=0.0,
        pixel_size_um=pick.geometry.pixel_size_um,
        image_size=pick.geometry.image_size_px,
        pan_scale_um=pan_scale_um,
    )
    target_xy_um = (float(target_xy[0]), float(target_xy[1]))
    offset_um = (target_xy_um[0] - pick.overview_stage_xy_um[0],
                 target_xy_um[1] - pick.overview_stage_xy_um[1])
    offset_mag = math.hypot(*offset_um)
    log.info("target XY = (%.3f, %.3f) um  pan offset = (%+.1f, %+.1f) um  "
             "|Δ|=%.1f um", *target_xy_um, *offset_um, offset_mag)

    if abs(offset_um[0]) > galvo_reach_um or abs(offset_um[1]) > galvo_reach_um:
        _abort(f"Picked cell is outside galvo reach "
               f"(offset {offset_um[0]:+.1f}, {offset_um[1]:+.1f} um vs "
               f"reach ±{galvo_reach_um:.0f} um). Pick a more central cell, "
               f"use the stage cookbook, or pre-centre the stage on the "
               f"region of interest.")

    bbox_w_um, bbox_h_um = pick.bbox_um
    framed_zoom = drv.bbox_to_zoom(bbox_w_um, bbox_h_um, base_fov_um,
                                   margin=args.fov_bbox_margin)
    log.info("framed zoom = %d (base FOV %.1f um → FOV at zoom %.1f um)",
             framed_zoom, base_fov_um, base_fov_um / framed_zoom)
    return target_xy_um, framed_zoom, base_fov_um, pan_scale_um


def step_zoom_then_pan(
    client: Any, job: str,
    target_xy_um: tuple[float, float], framed_zoom: int,
) -> None:
    """Disable ROI scan, set zoom FIRST, then galvo-pan to target.

    Order matters: pan-then-zoom causes LAS X to silently re-clamp pan
    during the zoom change.
    """
    log.info("disabling ROI scan")
    disable_roi_scan(client, job)

    log.info("setting framed zoom = %d", framed_zoom)
    drv.set_zoom(client, job, framed_zoom)
    time.sleep(SETTLE_AFTER_LAS_X_EDIT_S)

    log.info("galvo-panning to (%.3f, %.3f) um", *target_xy_um)
    r = drv.move_xy_galvo(client, target_xy_um[0], target_xy_um[1],
                          unit="um", job_name=job)
    if not r or not r.get("success"):
        _abort(f"galvo pan failed: {r}")
    # IMPORTANT: do NOT call check_idle or sleep here. The next step
    # is acquire — the LRP save/load inside move_xy_galvo already
    # confirms state, and any extra query causes "Scan not started"
    # timeouts (memory: feedback_no_check_idle_after_pan).


def step_acquire_and_verify(
    client: Any, job: str, args: argparse.Namespace, out_dir: Path,
    pick: CellPick, cellpose_model: models.CellposeModel,
    framed_zoom: int, base_fov_um: float,
    backlash_params: dict | None,
) -> tuple[np.ndarray, Path, float, LandingResult]:
    """Acquire the framed frame and measure landing error.

    Returns (framed_image, framed_tif_path, framed_pixel_size_um, landing).
    """
    log.info("acquiring framed frame")
    img, _ = drv.acquire_frame(client, job, backlash_params=backlash_params)
    framed_tif = out_dir / "framed.tif"
    tifffile.imwrite(str(framed_tif), img)
    log.info("framed image %s saved → %s", img.shape, framed_tif.name)

    framed_pixel_size_um = (base_fov_um / framed_zoom) / img.shape[1]
    log.info("framed pixel size = %.4f um/px", framed_pixel_size_um)

    # Cellpose at high zoom needs an explicit diameter — auto is too
    # small for a whole nucleus at sub-micron pixel sizes.
    src_bbox_diam_um = sum(pick.bbox_um) / 2.0
    tgt_diameter_px = src_bbox_diam_um / framed_pixel_size_um
    log.info("framed Cellpose diameter = %.0f px "
             "(%.1f um source bbox / %.4f um/px framed pixel)",
             tgt_diameter_px, src_bbox_diam_um, framed_pixel_size_um)
    masks, _, _ = cellpose_model.eval(img, diameter=tgt_diameter_px)
    log.info("framed frame: %d cell(s) segmented", int(masks.max()))

    landing = measure_landing_error_by_morphology(
        masks, img.shape, pick, framed_pixel_size_um,
    )
    if landing.error_magnitude_um is not None:
        dx, dy = landing.error_um  # type: ignore[misc]
        log.info("landing error = (%+.2f, %+.2f) um  magnitude=%.2f um  "
                 "(morphology score=%.3f over %d candidate(s))",
                 dx, dy, landing.error_magnitude_um,
                 landing.morphology_score, landing.cells_segmented)
    else:
        log.warning("could not measure landing error — no cells segmented")

    return img, framed_tif, framed_pixel_size_um, landing


def step_save_outputs(
    out_dir: Path, args: argparse.Namespace, job: str,
    pick: CellPick, target_xy_um: tuple[float, float],
    framed_zoom: int, base_fov_um: float, framed_pixel_size_um: float,
    pan_scale_um: float,
    overview_img: np.ndarray, framed_img: np.ndarray,
    overview_tif: Path, framed_tif: Path,
    landing: LandingResult,
) -> Path:
    """Write overlay.png and summary.json."""
    overlay_path = out_dir / "overlay.png"
    save_overlay_png(overlay_path, overview_img, framed_img, pick, landing)

    summary = {
        "timestamp": _now_iso_ts(),
        "job": job,
        "overview_stage_xy_um": list(pick.overview_stage_xy_um),
        "overview_pixel_size_um": pick.geometry.pixel_size_um,
        "overview_image_size_px": pick.geometry.image_size_px,
        "picked_cell": {
            "rank": args.pick_rank,
            "centroid_xy_px": list(pick.centroid_xy_px),
            "bbox_px": list(pick.bbox_px),
            "bbox_um": list(pick.bbox_um),
            "area_px": pick.area_px,
            "eccentricity": pick.eccentricity,
        },
        "target_xy_um": list(target_xy_um),
        "pan_offset_um": [target_xy_um[0] - pick.overview_stage_xy_um[0],
                          target_xy_um[1] - pick.overview_stage_xy_um[1]],
        "pan_scale_um": pan_scale_um,
        "galvo_reach_um": pan_scale_um * drv.PAN_LIMIT,
        "framed_zoom": framed_zoom,
        "base_fov_um": base_fov_um,
        "framed_fov_um": base_fov_um / framed_zoom,
        "framed_pixel_size_um": framed_pixel_size_um,
        "fov_bbox_margin": args.fov_bbox_margin,
        "landing": {
            "method": "morphology_match",
            "cells_segmented": landing.cells_segmented,
            "error_um": (list(landing.error_um)
                         if landing.error_um is not None else None),
            "error_magnitude_um": landing.error_magnitude_um,
            "morphology_score": landing.morphology_score,
        },
        "outputs": {
            "overview_tif": str(overview_tif),
            "framed_tif": str(framed_tif),
            "overlay_png": str(overlay_path),
        },
    }
    summary_path = out_dir / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
    return summary_path


def step_restore(client: Any, job: str) -> None:
    """Return to overview state: zoom 1, pan 0."""
    log.info("restoring overview state (zoom 1, pan 0)")
    drv.set_zoom(client, job, OVERVIEW_ZOOM)
    time.sleep(SETTLE_AFTER_LAS_X_EDIT_S)
    stage = drv.get_xy(client)
    if stage:
        drv.move_xy_galvo(client, float(stage["x_um"]), float(stage["y_um"]),
                          unit="um", job_name=job)


# ──────────────────────────────────────────────────────────────────────
# Orchestrator
# ──────────────────────────────────────────────────────────────────────


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    args = parse_args(argv)

    client, job, stage_cfg, out_dir = step_setup(args)
    backlash_params = None if args.no_backlash else stage_cfg["backlash"]

    cellpose_model = models.CellposeModel(gpu=not args.no_gpu)

    overview_img, geometry, stage_xy_um, overview_tif = step_acquire_overview(
        client, job, args, out_dir, backlash_params,
    )
    pick = step_pick_cell(overview_img, args, geometry, stage_xy_um,
                          cellpose_model)

    target_xy_um, framed_zoom, base_fov_um, pan_scale_um = step_compute_target(
        client, job, pick, args,
    )

    step_zoom_then_pan(client, job, target_xy_um, framed_zoom)

    framed_img, framed_tif, framed_pixel_um, landing = step_acquire_and_verify(
        client, job, args, out_dir, pick, cellpose_model,
        framed_zoom, base_fov_um,
        # Backlash on the galvo path is unnecessary — galvo doesn't
        # move the stage. We only paid for it on the overview acquire.
        backlash_params=None,
    )

    summary_path = step_save_outputs(
        out_dir, args, job, pick, target_xy_um,
        framed_zoom, base_fov_um, framed_pixel_um, pan_scale_um,
        overview_img, framed_img, overview_tif, framed_tif, landing,
    )

    if landing.error_magnitude_um is not None:
        dx, dy = landing.error_um  # type: ignore[misc]
        print(f"\nLanding error: ({dx:+.2f}, {dy:+.2f}) um  "
              f"magnitude={landing.error_magnitude_um:.2f} um")
    else:
        print("\nLanding error: unknown (no cells in framed frame)")

    print(f"\nOverview: {overview_tif}")
    print(f"Framed  : {framed_tif}")
    print(f"Overlay : {out_dir / 'overlay.png'}")
    print(f"Summary : {summary_path}")

    if not args.no_restore:
        step_restore(client, job)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)

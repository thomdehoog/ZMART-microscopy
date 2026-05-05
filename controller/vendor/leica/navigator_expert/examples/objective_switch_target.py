"""
Objective-switch targeting example — motorised-stage variant.
=============================================================

What this script does, in one line
----------------------------------
Pick a cell at low magnification, switch objectives, and re-image
that same cell — centred — at high magnification. Stage moves only;
no galvo pan, no ROI, no refinement loop.

Why this matters (the educational bit)
--------------------------------------
Switching objectives on a motorised microscope shifts the optical
axis on the sample by a few microns (parcentricity) and the focal
plane by a few microns more (parfocality). At high zoom, those few
microns are the difference between "cell in the centre of the FOV
and in focus" and "blurry empty FOV". Calibration measures both
shifts; this script demonstrates how a downstream "production"
script should consume that calibration to revisit a feature across
an objective swap.

The full coordinate model lives in
``vendor/leica/navigator_expert/driver/calibration.py`` (v9 schema).
The short version:

    For each non-reference objective ``slot``, calibration stores
        - ``offset_xy_um`` — stage XY delta the firmware applies on
                             objective switch (cumulative ref→slot).
        - ``shift_xy_um``  — optical-axis offset vs reference (XY).
        - ``offset_z_um``  — z-wide delta the firmware applies on
                             objective switch (cumulative ref→slot).
        - ``shift_z_um``   — Brenner-derived z-wide correction
                             (peak_target − peak_ref − offset_z).

    To map a stage XY + z-wide from one objective's frame to another:
        x', y', z' = drv.translate_xyz_between_objectives(x, y, z, cfg,
                         from_slot=src, to_slot=tgt)
    and absolute-move the stage to (x', y') and z-wide to z'. Z-galvo
    stays at 0 throughout — all focus motion lives on z-wide.

Recipe
------
The pipeline is one function per step; ``main()`` simply chains them.

    1. Connect, load configs, set stage limits.
    2. Switch to source objective at zoom 1 (widest FOV).
    3. Acquire one source frame; record stage XY and z-wide.
    4. Cellpose-segment; pick a cell by distance-from-centre rank.
    5. Convert pixel centroid to a stage XY (calibration sign matrix).
    6. Translate (x, y, z) across the objective boundary in one call.
    7. Switch to target objective; absolute-move z-wide and stage.
    8. Set zoom to frame ~1.5× the cell's bounding box; acquire.
    9. Verify by morphology-matching the source cell in the target.
   10. Save source.tif, target.tif, overlay.png, summary.json.

Identity & landing-error caveats
--------------------------------
The "landing error" reported here is *the centroid offset of the
target cell whose morphology best matches the source cell, from the
target FOV centre*. It is honest about identity (does not just take
"closest cell to centre") but inherits Cellpose's behaviour:

    - At 20× the auto diameter is far too small for a whole nucleus,
      so we pass an explicit diameter scaled from the source bbox.
    - If Cellpose still fragments or merges nuclei, the morphology
      score (also reported in summary.json) flags it.
    - Centroid accuracy is ~1 target pixel; sub-pixel template NCC
      is impractical here because the 20× FOV is too narrow to fit
      a padded source template. For sub-µm targeting, see the
      iterative or galvo siblings.

Operator preconditions
----------------------
- ``--job`` already selected in the LAS X UI (the driver's
  ``IsSelected`` flag lags the UI, so this script does not
  ``select_job`` defensively).
- ``ImageTransformation = TOPLEFT`` in LAS X Advanced Settings.
- AFC / autofocus OFF; no LAS X modal dialogs.
- Stage positioned over a region with cells visible at 10×.
- ``calibration/config/config.json`` (v9) and ``stage.json`` exist.

Usage
-----
    python objective_switch_stage_targeting.py \\
        --job Overview --source-slot 1 --target-slot 2

    # Pick the n-th-closest cell to the FOV centre instead of closest:
    python objective_switch_stage_targeting.py \\
        --job Overview --source-slot 1 --target-slot 2 --pick-rank 5
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

# Allow ``import navigator_expert`` from any CWD by inserting the package root.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import tifffile
from cellpose import models
from matplotlib.patches import Rectangle
from skimage.measure import regionprops

import navigator_expert.driver as drv


log = logging.getLogger("objective_switch_stage_targeting")


# ──────────────────────────────────────────────────────────────────────
# Constants — magic numbers documented; change here if your scope or
# acquisition speed differs.
# ──────────────────────────────────────────────────────────────────────

#: Source acquisition zoom. 1.0 = the objective's widest native FOV.
#: A wider FOV gives Cellpose more cells to choose from.
SOURCE_ZOOM: float = 1.0

#: Default target FOV = this × the source-cell bounding box (square).
#: 1.5 leaves visual margin; tighter zoom risks clipping if the cell
#: lands a few µm off-centre.
DEFAULT_FOV_BBOX_MARGIN: float = 1.5

#: Wait this many seconds after every objective switch. The firmware
#: needs to settle the wide-focus motor and the parfocal compensation.
SETTLE_AFTER_OBJECTIVE_SWITCH_S: float = 3.0

#: Wait this long between two successive zoom/job edits to let LAS X
#: commit the LRP edits.
SETTLE_AFTER_LAS_X_EDIT_S: float = 0.5

#: Maximum time to wait for LAS X to report "scanner idle".
IDLE_TIMEOUT_S: float = 5.0

#: Maximum time to wait for OME-TIFF files to be unlocked + size-stable
#: on the export drive after an acquire.
FILE_STABILITY_TIMEOUT_S: int = 30


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Switch objective and revisit a detected cell in one FOV.",
    )
    p.add_argument("--job", required=True,
                   help="LAS X job name. Must be selected in the LAS X UI.")
    p.add_argument("--source-slot", type=int, required=True,
                   help="Objective slot used for detection (e.g. 1 for 10x).")
    p.add_argument("--target-slot", type=int, required=True,
                   help="Objective slot used for acquisition (e.g. 2 for 20x).")
    p.add_argument("--fov-bbox-margin", type=float, default=DEFAULT_FOV_BBOX_MARGIN,
                   help=f"Target-objective FOV = this × cell bounding box "
                        f"(default: {DEFAULT_FOV_BBOX_MARGIN}).")
    p.add_argument("--pick-rank", type=int, default=0,
                   help="Which cell to target by distance from the source "
                        "image centre: 0=closest, 1=next, … Default: 0.")
    p.add_argument("--diameter", type=float, default=None,
                   help="Cellpose nucleus diameter at the SOURCE objective, "
                        "in source pixels. Default: auto. The target diameter "
                        "is always derived from the picked cell's bbox.")
    p.add_argument("--no-gpu", action="store_true",
                   help="Disable GPU for Cellpose.")
    p.add_argument("--settle", type=float, default=SETTLE_AFTER_OBJECTIVE_SWITCH_S,
                   help="Seconds to wait after each objective switch "
                        f"(default: {SETTLE_AFTER_OBJECTIVE_SWITCH_S}).")
    p.add_argument("--output-dir", type=Path, default=None,
                   help="Output directory (default: "
                        "config/objective_targeting/stage/<timestamp>/).")
    p.add_argument("--no-restore", action="store_true",
                   help="Do not switch back to the source objective at the end.")
    p.add_argument("--no-backlash", action="store_true",
                   help="Skip backlash takeup before each acquire. Backlash "
                        "is on by default and matches calibration's takeup, "
                        "so repeat acquires sample identical mechanical state.")
    p.add_argument("--refine", choices=("ncc", "pcc", "voting"), default=None,
                   help="Run an iterative registration refinement after the "
                        "predicted move and before the framed acquire. Modes: "
                        "'ncc' (template-match, fastest, default if a value is "
                        "expected), 'pcc' (phase cross-correlation), 'voting' "
                        "(4-method consensus — most robust, slowest). Off by "
                        "default; the calibration alone is usually enough.")
    p.add_argument("--refine-iterations", type=int, default=4,
                   help="Maximum refinement iterations (default: 4).")
    p.add_argument("--refine-converge-um", type=float, default=0.5,
                   help="Stop refinement once |correction| < this (default: 0.5 um).")
    return p.parse_args(argv)


# ──────────────────────────────────────────────────────────────────────
# Domain types — small dataclasses keep call signatures honest.
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FrameGeometry:
    """Geometry of one acquired frame.

    pixel_size_um is the physical extent of a single pixel; image_size_px
    is the side length in pixels. FOV in um is image_size_px * pixel_size_um.
    """
    pixel_size_um: float
    image_size_px: int

    @property
    def fov_um(self) -> float:
        return self.pixel_size_um * self.image_size_px


@dataclass(frozen=True)
class SourcePick:
    """The cell chosen at the source objective."""
    centroid_xy_px: tuple[float, float]      # (col, row) order
    bbox_px: tuple[int, int, int, int]       # (min_r, min_c, max_r, max_c)
    bbox_um: tuple[float, float]             # (width, height)
    area_px: int
    eccentricity: float
    geometry: FrameGeometry
    stage_xy_um: tuple[float, float]         # stage XY at acquire time
    zwide_um: float                          # z-wide at acquire time


@dataclass(frozen=True)
class LandingResult:
    """Outcome of identifying the source cell in the target frame.

    error_um is (dx, dy) of the matched cell's centroid from the target
    FOV centre, in physical microns. None when no cells were segmented.
    """
    cells_segmented: int
    error_um: tuple[float, float] | None
    error_magnitude_um: float | None
    morphology_score: float | None
    source_features: dict[str, float] | None
    candidates: list[dict[str, Any]]
    matched_prop: Any | None  # skimage regionprops object; not serialised


# ──────────────────────────────────────────────────────────────────────
# Tiny utilities
# ──────────────────────────────────────────────────────────────────────


def _abort(msg: str, code: int = 1) -> None:
    """Print an ABORT line and exit. Used only for hard pre-conditions."""
    print(f"ABORT: {msg}")
    sys.exit(code)


def _default_output_dir() -> Path:
    """Default output is config/objective_target/<timestamp>/."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return (Path(__file__).resolve().parents[2]
            / "config" / "objective_target" / ts)


def _now_iso_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


# ──────────────────────────────────────────────────────────────────────
# LAS X interaction
# ──────────────────────────────────────────────────────────────────────







def read_frame_geometry(client: Any, job: str) -> FrameGeometry:
    """Pixel size and image extent for the currently-active acquisition."""
    settings = drv.get_job_settings(client, job) or {}
    geo = drv.parse_tile_geometry(settings)
    return FrameGeometry(
        pixel_size_um=float(geo["pixel_w_um"]),
        image_size_px=int(geo["pixels_x"]),
    )


# ──────────────────────────────────────────────────────────────────────
# Image analysis
# ──────────────────────────────────────────────────────────────────────


def pick_cell_by_distance_rank(masks: np.ndarray, rank: int) -> Any | None:
    """Return the regionprops object at the given distance-from-centre rank.

    rank=0 is the cell closest to the image centre, rank=1 the next, etc.
    Returns None if the masks have fewer than ``rank+1`` cells.
    """
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
    source_pick: SourcePick,
    target_pixel_size_um: float,
) -> LandingResult:
    """Identify the source cell in the target frame and measure landing error.

    Compares each segmented target cell's area (normalised to physical
    units) and eccentricity to the source cell, picks the smallest
    (area-diff + eccentricity-diff), and reports its centroid offset
    from the target FOV centre.

    Why morphology and not "closest to centre": a neighbour cell can
    easily land closer to the FOV centre than the cell we picked,
    especially at high zoom. Morphology gives an honest identity check.
    """
    target_props = regionprops(target_masks)
    src_area_um2 = source_pick.area_px * (source_pick.geometry.pixel_size_um ** 2)
    src_ecc = float(source_pick.eccentricity)

    if not target_props:
        return LandingResult(
            cells_segmented=0, error_um=None, error_magnitude_um=None,
            morphology_score=None,
            source_features={"area_um2": float(src_area_um2),
                             "eccentricity": src_ecc},
            candidates=[], matched_prop=None,
        )

    h, w = target_image_shape[:2]
    cy_centre, cx_centre = h / 2.0, w / 2.0

    best = None
    best_score = float("inf")
    candidates: list[dict[str, Any]] = []
    for p in target_props:
        tgt_area_um2 = p.area * (target_pixel_size_um ** 2)
        tgt_ecc = float(p.eccentricity)
        area_diff = abs(tgt_area_um2 - src_area_um2) / max(src_area_um2, 1.0)
        ecc_diff = abs(tgt_ecc - src_ecc)
        score = area_diff + ecc_diff
        candidates.append({
            "centroid_px": (float(p.centroid[1]), float(p.centroid[0])),
            "area_um2": float(tgt_area_um2),
            "eccentricity": tgt_ecc,
            "score": float(score),
        })
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
        source_features={"area_um2": float(src_area_um2),
                         "eccentricity": src_ecc},
        candidates=candidates,
        matched_prop=best,
    )


# ──────────────────────────────────────────────────────────────────────
# Visualisation
# ──────────────────────────────────────────────────────────────────────


def save_overlay_png(
    png_path: Path,
    source_img: np.ndarray, target_img: np.ndarray,
    source_pick: SourcePick, landing: LandingResult,
) -> None:
    """Two-panel diagnostic PNG.

    Left panel  : source image with picked cell highlighted (green bbox,
                  red cross at centroid).
    Right panel : target image with FOV-centre cyan cross, plus matched
                  cell (green bbox + red cross) when one was identified.
    """
    fig, axes = plt.subplots(1, 2, figsize=(12, 6))

    # Source panel
    ax = axes[0]
    ax.imshow(source_img, cmap="gray")
    ax.set_title("Source: picked cell (green bbox, red cross)")
    min_r, min_c, max_r, max_c = source_pick.bbox_px
    ax.add_patch(Rectangle((min_c, min_r), max_c - min_c, max_r - min_r,
                           edgecolor="lime", facecolor="none", linewidth=1.5))
    sx, sy = source_pick.centroid_xy_px
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
    if landing.matched_prop is not None and landing.error_magnitude_um is not None:
        min_r, min_c, max_r, max_c = landing.matched_prop.bbox
        ax.add_patch(Rectangle((min_c, min_r), max_c - min_c, max_r - min_r,
                               edgecolor="lime", facecolor="none", linewidth=1.5))
        ty, tx = landing.matched_prop.centroid
        ax.plot(tx, ty, "r+", markersize=18, markeredgewidth=2)
        ax.set_title(f"Target: matched cell (red+) vs FOV centre (cyan+). "
                     f"Error = {landing.error_magnitude_um:.2f} um")
    else:
        ax.set_title("Target: no cells segmented — landing not verified")
    ax.axis("off")

    fig.tight_layout()
    fig.savefig(png_path, dpi=120)
    plt.close(fig)


# ──────────────────────────────────────────────────────────────────────
# Pipeline steps
# ──────────────────────────────────────────────────────────────────────


def step_setup(
    args: argparse.Namespace,
) -> tuple[Any, dict[str, Any], dict[str, Any], Any, Path]:
    """Prepare the world: connect, validate, set limits, idle check.

    Returns (client, calibration_cfg, stage_cfg, hardware_info, output_dir).
    """
    out_dir = args.output_dir or _default_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.source_slot == args.target_slot:
        _abort("source-slot and target-slot must differ.")

    cfg = drv.load_calibration()
    stage_cfg = drv.load_stage_config()
    client = drv.connect_python_client()
    drv.require_canonical_scan_orientation()

    hw = drv.get_hardware_info(client)
    if not hw:
        _abort("Could not read hardware info.", 2)
    drv.validate_slots(hw, args.source_slot, [args.target_slot])

    drv.apply_stage_limits_from_config(stage_cfg)

    idle = drv.check_idle(client, timeout=IDLE_TIMEOUT_S)
    if not idle or not idle.get("success"):
        _abort(f"LAS X not idle: {idle}")

    print(f"Job:            {args.job}")
    print(f"Source slot:    {args.source_slot}")
    print(f"Target slot:    {args.target_slot}")
    print(f"FOV margin:     {args.fov_bbox_margin}× bounding box")
    print(f"Pick rank:      {args.pick_rank}")
    print(f"Backlash:       {'on' if not args.no_backlash else 'off'}")
    if args.refine:
        print(f"Refine mode:    {args.refine} "
              f"(max {args.refine_iterations} iterations, "
              f"converge < {args.refine_converge_um} um)")
    print(f"Output dir:     {out_dir}\n")

    return client, cfg, stage_cfg, hw, out_dir


def step_acquire_source(
    client: Any, args: argparse.Namespace, hw: Any, out_dir: Path,
    backlash_params: dict | None,
) -> tuple[np.ndarray, FrameGeometry, tuple[float, float], float, Path]:
    """Switch to source objective at zoom 1, acquire one frame, save it.

    Returns (source_image, geometry, stage_xy_um, zwide_um, source_tif_path).
    """
    log.info("switching to source objective (slot %d)", args.source_slot)
    drv.set_objective(client, args.job, hw, slot_index=args.source_slot)
    time.sleep(args.settle)
    drv.set_zoom(client, args.job, SOURCE_ZOOM)
    time.sleep(SETTLE_AFTER_LAS_X_EDIT_S)

    stage = drv.get_xy(client)
    if not stage:
        _abort("Could not read XY after source switch.")
    src_stage_xy_um = (float(stage["x_um"]), float(stage["y_um"]))
    log.info("source stage XY = (%.3f, %.3f) um", *src_stage_xy_um)

    geometry = read_frame_geometry(client, args.job)
    src_zwide_um = drv.read_zwide_um(client, args.job)
    log.info("source geometry: pixel=%.4f um  FOV=%.1f um  z-wide=%.2f um",
             geometry.pixel_size_um, geometry.fov_um, src_zwide_um)

    log.info("acquiring source frame")
    img, lasx_path = drv.acquire_frame(client, args.job, backlash_params=backlash_params)
    src_tif = out_dir / "source.tif"
    tifffile.imwrite(str(src_tif), img)
    log.info("source image %s saved → %s", img.shape, src_tif.name)

    return img, geometry, src_stage_xy_um, src_zwide_um, src_tif


def step_pick_source_cell(
    source_img: np.ndarray, args: argparse.Namespace,
    geometry: FrameGeometry,
    stage_xy_um: tuple[float, float], zwide_um: float,
    cellpose_model: models.CellposeModel,
) -> tuple[SourcePick, np.ndarray]:
    """Run Cellpose on the source frame and pick a cell by rank.

    Returns (source_pick, segmentation_masks). ``masks`` is kept so the
    caller can re-use it for diagnostics.
    """
    log.info("running Cellpose on source (gpu=%s)", not args.no_gpu)
    t0 = time.perf_counter()
    masks, _, _ = cellpose_model.eval(source_img, diameter=args.diameter)
    n_cells = int(masks.max())
    log.info("Cellpose found %d cell(s) in %.1fs",
             n_cells, time.perf_counter() - t0)
    if n_cells == 0:
        _abort("Cellpose found no cells in the source frame.")

    prop = pick_cell_by_distance_rank(masks, args.pick_rank)
    if prop is None:
        _abort(f"No cell at rank {args.pick_rank}. "
               f"Lower --pick-rank or move to a denser region.")

    cy, cx = prop.centroid
    min_r, min_c, max_r, max_c = prop.bbox
    bbox_w_um = (max_c - min_c) * geometry.pixel_size_um
    bbox_h_um = (max_r - min_r) * geometry.pixel_size_um
    pick = SourcePick(
        centroid_xy_px=(float(cx), float(cy)),
        bbox_px=(int(min_r), int(min_c), int(max_r), int(max_c)),
        bbox_um=(float(bbox_w_um), float(bbox_h_um)),
        area_px=int(prop.area),
        eccentricity=float(prop.eccentricity),
        geometry=geometry,
        stage_xy_um=stage_xy_um,
        zwide_um=zwide_um,
    )
    log.info("picked cell (rank %d): centroid=(%.1f, %.1f) px  "
             "bbox=(%.1f × %.1f) um  area=%d px  ecc=%.3f",
             args.pick_rank, cx, cy, bbox_w_um, bbox_h_um,
             pick.area_px, pick.eccentricity)
    return pick, masks


def step_translate_to_target(
    source_pick: SourcePick, cfg: dict[str, Any],
    source_slot: int, target_slot: int,
) -> tuple[tuple[float, float, float], tuple[float, float]]:
    """Map the cell's source-frame coordinates to a target-frame command.

    Returns (target_stage_xyz_um, cell_source_xy_um). cell_source_xy_um
    is recorded for the summary so the math is fully reproducible from
    disk.
    """
    cx, cy = source_pick.centroid_xy_px
    cell_source_xy_um = drv.pixel_to_stage_xy_um(
        cx, cy,
        stage_xy_um=source_pick.stage_xy_um,
        pixel_size_um=source_pick.geometry.pixel_size_um,
        image_size=source_pick.geometry.image_size_px,
        config=cfg,
    )
    log.info("cell stage XY in source frame = (%.3f, %.3f) um",
             *cell_source_xy_um)

    target_x, target_y, target_zwide = drv.translate_xyz_between_objectives(
        cell_source_xy_um[0], cell_source_xy_um[1], source_pick.zwide_um, cfg,
        from_slot=source_slot, to_slot=target_slot,
    )
    log.info("translated to target frame: XY=(%.3f, %.3f) um  z-wide=%.2f um",
             target_x, target_y, target_zwide)
    return (target_x, target_y, target_zwide), cell_source_xy_um


def step_switch_and_position(
    client: Any, args: argparse.Namespace, hw: Any,
    target_xyz_um: tuple[float, float, float],
) -> float:
    """Switch to the target objective, apply z-wide, move stage to target XY.

    Does NOT change zoom — refinement (if any) runs at an intermediate
    zoom matched to source pixel size; the framed zoom is set later.

    Returns the target objective's base FOV in um (zoom-1 FOV).
    """
    log.info("switching to target objective (slot %d)", args.target_slot)
    drv.set_objective(client, args.job, hw, slot_index=args.target_slot)
    time.sleep(args.settle)

    target_x, target_y, target_zwide = target_xyz_um

    # Z first: firmware moved z-wide on the switch; we override with
    # the absolute value the translator computed.
    rz = drv.move_z(client, args.job, target_zwide,
                    unit="um", z_mode="zwide")
    if not rz or not rz.get("success"):
        _abort(f"could not move z-wide to translated target: {rz}")

    base_fov_m = drv.get_base_fov(client, args.job)
    if not base_fov_m:
        _abort("Could not read target base FOV.")
    target_base_fov_um = float(base_fov_m[0] * 1e6)

    log.info("moving stage to target XY")
    drv.move_xy_stage(client, target_x, target_y, unit="um")

    return target_base_fov_um


def step_set_framed_zoom(
    client: Any, args: argparse.Namespace,
    target_base_fov_um: float, bbox_um: tuple[float, float],
) -> tuple[int, float]:
    """Set the final framed zoom and report (zoom, target_pixel_size_um)."""
    bbox_w_um, bbox_h_um = bbox_um
    zoom = drv.bbox_to_zoom(bbox_w_um, bbox_h_um, target_base_fov_um,
                            margin=args.fov_bbox_margin)
    log.info("framed zoom=%d (base FOV=%.1f um → FOV at zoom=%.1f um)",
             zoom, target_base_fov_um, target_base_fov_um / zoom)
    drv.set_zoom(client, args.job, zoom)

    target_pixel_size_um = (target_base_fov_um / zoom) / drv.parse_tile_geometry(
        drv.get_job_settings(client, args.job) or {}
    )["pixels_x"]
    return zoom, float(target_pixel_size_um)


# ──────────────────────────────────────────────────────────────────────
# Optional refinement: image-based stage correction at intermediate zoom
# ──────────────────────────────────────────────────────────────────────


def _intermediate_zoom_for(
    target_base_fov_um: float, source_pixel_um: float, source_image_size_px: int,
) -> int:
    """Pick the integer zoom that makes target pixel ≈ source pixel.

    Equivalent to choosing the smallest target FOV that still lets us
    register a source-pixel-sized template against a comparably-coarse
    intermediate without an aggressive resample.
    """
    ideal = target_base_fov_um / (source_pixel_um * source_image_size_px)
    return max(1, int(round(ideal)))


def _ncc_template_match(
    source_img: np.ndarray, source_pick: SourcePick,
    intermediate_img: np.ndarray, intermediate_pixel_um: float,
    template_pad_factor: float = 1.5,
) -> tuple[float, float, float]:
    """NCC template-match a source-cell crop against the intermediate.

    Crops a square template around the picked cell in source (padded
    to ``template_pad_factor × bbox_max`` so the match has surrounding
    context to be unique), resamples it to the intermediate's pixel
    size, runs ``cv2.matchTemplate`` with ``TM_CCOEFF_NORMED``, and
    returns the cell's offset from the intermediate FOV centre in
    image-frame microns.

    Returns ``(dx_image_um, dy_image_um, peak_correlation)``.
    """
    import cv2  # local import keeps top-level imports lean

    cy_src, cx_src = source_pick.centroid_xy_px[1], source_pick.centroid_xy_px[0]
    bbox_max_px = max(
        source_pick.bbox_px[2] - source_pick.bbox_px[0],
        source_pick.bbox_px[3] - source_pick.bbox_px[1],
    )
    pad_px = int(round(template_pad_factor * bbox_max_px / 2))
    h_s, w_s = source_img.shape[:2]
    cy_int = int(round(cy_src))
    cx_int = int(round(cx_src))
    top = max(0, cy_int - pad_px)
    bottom = min(h_s, cy_int + pad_px)
    left = max(0, cx_int - pad_px)
    right = min(w_s, cx_int + pad_px)
    template = source_img[top:bottom, left:right]

    src_pixel_um = source_pick.geometry.pixel_size_um
    scale = src_pixel_um / intermediate_pixel_um
    new_h = max(8, int(round(template.shape[0] * scale)))
    new_w = max(8, int(round(template.shape[1] * scale)))
    template_rs = cv2.resize(
        template, (new_w, new_h), interpolation=cv2.INTER_CUBIC,
    )

    def _to_u8(a: np.ndarray) -> np.ndarray:
        a = a.astype(np.float32)
        hi = a.max() or 1
        return (a / hi * 255).astype(np.uint8)

    int_u8 = _to_u8(intermediate_img)
    tpl_u8 = _to_u8(template_rs)
    if tpl_u8.shape[0] >= int_u8.shape[0] or tpl_u8.shape[1] >= int_u8.shape[1]:
        raise RuntimeError(
            f"NCC: resampled template {tpl_u8.shape} ≥ intermediate "
            f"{int_u8.shape}. Pick a smaller --refine-template-pad or "
            f"increase --refine-zoom."
        )

    result = cv2.matchTemplate(int_u8, tpl_u8, cv2.TM_CCOEFF_NORMED)
    _, peak_val, _, max_loc = cv2.minMaxLoc(result)

    cell_int_x = max_loc[0] + tpl_u8.shape[1] / 2.0
    cell_int_y = max_loc[1] + tpl_u8.shape[0] / 2.0
    h_i, w_i = intermediate_img.shape[:2]
    dx_um = (cell_int_x - w_i / 2.0) * intermediate_pixel_um
    dy_um = (cell_int_y - h_i / 2.0) * intermediate_pixel_um
    return float(dx_um), float(dy_um), float(peak_val)


def step_refine_position(
    client: Any, args: argparse.Namespace,
    source_pick: SourcePick, source_img: np.ndarray,
    target_base_fov_um: float, image_to_stage: list,
    backlash_params: dict | None, out_dir: Path,
) -> dict[str, Any]:
    """Iterative stage correction at intermediate zoom.

    Runs only when ``--refine`` is set. The intermediate zoom is
    chosen so target-pixel-size ≈ source-pixel-size; the chosen
    method (NCC / PCC / voting) reports the cell's offset from the
    intermediate FOV centre in image-frame microns; the offset is
    converted to a stage correction via the calibrated
    ``image_to_stage`` matrix and the stage moves; the loop stops
    when the correction magnitude drops below
    ``--refine-converge-um`` or after ``--refine-iterations`` passes.

    Returns a report fragment with the chosen mode, intermediate
    zoom/pixel, and one entry per iteration.
    """
    from navigator_expert import analysis as _ana

    src_pixel_um = source_pick.geometry.pixel_size_um
    src_size_px = source_pick.geometry.image_size_px
    int_zoom = _intermediate_zoom_for(target_base_fov_um, src_pixel_um, src_size_px)
    int_pixel_um = (target_base_fov_um / int_zoom) / src_size_px
    log.info("refine: mode=%s, intermediate zoom=%d, pixel=%.4f um "
             "(source %.4f um), max iterations=%d, converge=%.2f um",
             args.refine, int_zoom, int_pixel_um, src_pixel_um,
             args.refine_iterations, args.refine_converge_um)
    drv.set_zoom(client, args.job, int_zoom)
    time.sleep(SETTLE_AFTER_LAS_X_EDIT_S)

    iterations: list[dict[str, Any]] = []
    for i in range(args.refine_iterations):
        img, _ = drv.acquire_frame(
            client, args.job, backlash_params=backlash_params,
        )
        tifffile.imwrite(str(out_dir / f"refine_{i:02d}.tif"), img)

        if args.refine == "ncc":
            dx_um, dy_um, quality = _ncc_template_match(
                source_img, source_pick, img, int_pixel_um,
            )
            mode_detail: dict[str, Any] = {"ncc_peak": quality}
        else:
            pair = _ana.prepare_pair(
                source_img, img,
                source_pixel_um=src_pixel_um,
                intermediate_pixel_um=int_pixel_um,
                source_cell_col=source_pick.centroid_xy_px[0],
                source_cell_row=source_pick.centroid_xy_px[1],
            )
            ref, tgt, pixel_um = pair["ref"], pair["tgt"], pair["pixel_um"]
            if args.refine == "pcc":
                dx_um, dy_um, quality = _ana.pcc(ref, tgt, pixel_um)
                mode_detail = {"pcc_quality": quality}
            else:  # voting
                vote = _ana.register_voting(ref, tgt, pixel_um)
                mode_detail = {
                    "voting_agreeing": vote["agreeing"],
                    "voting_confidence": vote["confidence"],
                    "voting_trusted": vote["trusted"],
                    "per_method": vote["per_method"],
                }
                if not vote["trusted"]:
                    log.warning(
                        "refine: voting not trusted (%d agreeing); "
                        "stopping refinement at iteration %d",
                        vote["confidence"], i,
                    )
                    iterations.append({
                        "iteration": i, "skipped": True,
                        "reason": "voting_low_confidence",
                        **mode_detail,
                    })
                    break
                dx_um = float(vote["dx_um"])
                dy_um = float(vote["dy_um"])
                quality = float(vote["quality"])

        # Image-frame offset → stage correction via calibration matrix.
        stage_dx = image_to_stage[0][0] * dx_um + image_to_stage[0][1] * dy_um
        stage_dy = image_to_stage[1][0] * dx_um + image_to_stage[1][1] * dy_um
        correction_mag = math.hypot(stage_dx, stage_dy)

        log.info(
            "refine iter %d: image=(%+.2f, %+.2f) um → "
            "stage=(%+.2f, %+.2f) um  |Δ|=%.2f um  q=%.3f",
            i, dx_um, dy_um, stage_dx, stage_dy, correction_mag, quality,
        )
        iterations.append({
            "iteration": i,
            "image_offset_um": [dx_um, dy_um],
            "stage_correction_um": [float(stage_dx), float(stage_dy)],
            "correction_magnitude_um": float(correction_mag),
            "quality": float(quality),
            **mode_detail,
        })

        if correction_mag < args.refine_converge_um:
            log.info("refine: converged after %d iteration(s)", i + 1)
            break

        cur = drv.get_xy(client)
        if not cur:
            _abort("could not read stage XY between refine iterations.")
        drv.move_xy_stage(
            client, float(cur["x_um"]) + stage_dx, float(cur["y_um"]) + stage_dy,
            unit="um",
        )

    return {
        "mode": args.refine,
        "intermediate_zoom": int_zoom,
        "intermediate_pixel_um": float(int_pixel_um),
        "iterations": iterations,
    }


def step_acquire_and_verify(
    client: Any, args: argparse.Namespace, out_dir: Path,
    source_pick: SourcePick, cellpose_model: models.CellposeModel,
    target_pixel_size_um: float,
    backlash_params: dict | None,
) -> tuple[np.ndarray, Path, LandingResult]:
    """Acquire the target frame and measure landing error.

    Returns (target_image, target_tif_path, landing_result).
    """
    log.info("acquiring target frame")
    img, lasx_path = drv.acquire_frame(client, args.job, backlash_params=backlash_params)
    tgt_tif = out_dir / "target.tif"
    tifffile.imwrite(str(tgt_tif), img)
    log.info("target image %s saved → %s", img.shape, tgt_tif.name)

    # Cellpose at high zoom needs an explicit diameter — its auto value
    # is way too small at 0.03 µm/px and segments sub-nuclear features.
    src_bbox_diam_um = sum(source_pick.bbox_um) / 2.0
    tgt_diameter_px = src_bbox_diam_um / target_pixel_size_um
    log.info("target Cellpose diameter = %.0f px "
             "(%.1f um source bbox / %.4f um/px target pixel)",
             tgt_diameter_px, src_bbox_diam_um, target_pixel_size_um)
    masks, _, _ = cellpose_model.eval(img, diameter=tgt_diameter_px)
    log.info("target frame: %d cell(s) segmented", int(masks.max()))

    landing = measure_landing_error_by_morphology(
        masks, img.shape, source_pick, target_pixel_size_um,
    )
    if landing.error_magnitude_um is not None:
        dx, dy = landing.error_um  # type: ignore[misc]
        log.info("landing error = (%+.2f, %+.2f) um  magnitude=%.2f um  "
                 "(morphology score=%.3f over %d candidate(s))",
                 dx, dy, landing.error_magnitude_um,
                 landing.morphology_score, landing.cells_segmented)
    else:
        log.warning("could not measure landing error — no cells in target")
    return img, tgt_tif, landing


def step_save_outputs(
    out_dir: Path,
    source_img: np.ndarray, target_img: np.ndarray,
    source_pick: SourcePick, landing: LandingResult,
    args: argparse.Namespace,
    source_tif: Path, target_tif: Path,
    cell_source_xy_um: tuple[float, float],
    target_xyz_um: tuple[float, float, float],
    target_geom: tuple[int, float, float],
    refine_report: dict[str, Any] | None = None,
) -> Path:
    """Write overlay.png and summary.json. Returns the summary path."""
    overlay_path = out_dir / "overlay.png"
    save_overlay_png(overlay_path, source_img, target_img, source_pick, landing)

    target_zoom, target_base_fov_um, target_pixel_size_um = target_geom

    summary: dict[str, Any] = {
        "timestamp": _now_iso_ts(),
        "job": args.job,
        "source_slot": args.source_slot,
        "target_slot": args.target_slot,
        "source_stage_xy_um": list(source_pick.stage_xy_um),
        "source_pixel_size_um": source_pick.geometry.pixel_size_um,
        "source_image_size_px": source_pick.geometry.image_size_px,
        "picked_cell": {
            "centroid_xy_px": list(source_pick.centroid_xy_px),
            "bbox_px": list(source_pick.bbox_px),
            "bbox_um": list(source_pick.bbox_um),
            "area_px": source_pick.area_px,
            "eccentricity": source_pick.eccentricity,
            "rank": args.pick_rank,
        },
        "cell_source_xy_um": list(cell_source_xy_um),
        "cell_target_xy_um": list(target_xyz_um[:2]),
        "target_zoom": target_zoom,
        "target_base_fov_um": target_base_fov_um,
        "target_fov_at_zoom_um": target_base_fov_um / target_zoom,
        "target_pixel_size_um": target_pixel_size_um,
        "fov_bbox_margin": args.fov_bbox_margin,
        "z_translation": {
            "source_zwide_um": source_pick.zwide_um,
            "target_zwide_um": target_xyz_um[2],
            "delta_um": target_xyz_um[2] - source_pick.zwide_um,
        },
        "landing": {
            "method": "morphology_match",
            "cells_segmented": landing.cells_segmented,
            "error_um": (list(landing.error_um)
                         if landing.error_um is not None else None),
            "error_magnitude_um": landing.error_magnitude_um,
            "morphology_score": landing.morphology_score,
            "source_features": landing.source_features,
            "candidates": landing.candidates,
        },
        "calibration_config": str(drv.default_calibration_path()),
        "refine": refine_report,
        "outputs": {
            "source_tif": str(source_tif),
            "target_tif": str(target_tif),
            "overlay_png": str(overlay_path),
        },
    }
    summary_path = out_dir / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
    return summary_path


# ──────────────────────────────────────────────────────────────────────
# Orchestrator
# ──────────────────────────────────────────────────────────────────────


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    args = parse_args(argv)

    client, cfg, stage_cfg, hw, out_dir = step_setup(args)
    backlash_params = None if args.no_backlash else stage_cfg["backlash"]

    cellpose_model = models.CellposeModel(gpu=not args.no_gpu)

    source_img, source_geom, src_stage_xy_um, src_zwide_um, src_tif = (
        step_acquire_source(client, args, hw, out_dir, backlash_params)
    )
    source_pick, _src_masks = step_pick_source_cell(
        source_img, args, source_geom, src_stage_xy_um, src_zwide_um,
        cellpose_model,
    )

    target_xyz_um, cell_source_xy_um = step_translate_to_target(
        source_pick, cfg, args.source_slot, args.target_slot,
    )

    target_base_fov_um = step_switch_and_position(
        client, args, hw, target_xyz_um,
    )

    refine_report: dict[str, Any] | None = None
    if args.refine:
        refine_report = step_refine_position(
            client, args, source_pick, source_img,
            target_base_fov_um, cfg["image_to_stage"],
            backlash_params, out_dir,
        )

    zoom, target_pixel_size_um = step_set_framed_zoom(
        client, args, target_base_fov_um, source_pick.bbox_um,
    )

    target_img, tgt_tif, landing = step_acquire_and_verify(
        client, args, out_dir, source_pick, cellpose_model,
        target_pixel_size_um, backlash_params,
    )

    summary_path = step_save_outputs(
        out_dir, source_img, target_img, source_pick, landing, args,
        src_tif, tgt_tif, cell_source_xy_um, target_xyz_um,
        target_geom=(zoom, target_base_fov_um, target_pixel_size_um),
        refine_report=refine_report,
    )

    if landing.error_magnitude_um is not None:
        dx, dy = landing.error_um  # type: ignore[misc]
        print(f"\nLanding error: ({dx:+.2f}, {dy:+.2f}) um  "
              f"magnitude={landing.error_magnitude_um:.2f} um")
    else:
        print("\nLanding error: unknown (no cells in target frame)")

    print(f"\nSource : {src_tif}")
    print(f"Target : {tgt_tif}")
    print(f"Overlay: {out_dir / 'overlay.png'}")
    print(f"Summary: {summary_path}")

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

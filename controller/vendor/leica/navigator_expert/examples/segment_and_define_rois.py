"""
Segment-and-define-ROIs example.
================================

What this script does, in one line
----------------------------------
Acquire a frame, segment cells with Cellpose, and load each cell's
contour as a polygon ROI in LAS X — ready to use as a region-of-interest
scan list.

Why it matters (the educational bit)
------------------------------------
Most acquisitions waste time scanning empty regions. ROI scans
restrict pixel-by-pixel acquisition to the cells you care about,
dropping wall-clock time per stack proportionally to the foreground
fraction. The hard part is going from "image" to "list of polygon
vertices in LAS X stage coordinates" without losing the orientation
between the camera frame and the LRP description.

This script demonstrates the full chain end-to-end:

    image (numpy)
      → Cellpose masks
      → skimage contours, polygon-simplified
      → LRP polygon vertices via ``pixels_to_roi`` (handles the
        image-centre-relative metres convention LAS X expects)
      → ``lrp_add_roi`` writes the polygons + colours into the
        scanning template, optionally enabling ROI scan.

Recipe
------
The pipeline is one function per step; ``main()`` chains them.

    1. Connect, validate orientation, resolve the selected job, set
       stage limits.
    2. Reset state (clear existing ROIs, disable ROI scan).
    3. Acquire one frame (or load ``--image``).
    4. Cellpose-segment; sort cells by area, keep the top N.
    5. Extract each cell's contour, simplify to a polygon, convert
       pixel coordinates to the LRP metres convention.
    6. Apply: clear-then-add the polygon ROIs in the LRP and (by
       default) enable ROI scan.
    7. Verify by re-parsing the saved LRP. Pause for visual check.
    8. Optional cleanup (clear ROIs, disable ROI scan).

Operator preconditions
----------------------
- A job is currently selected in LAS X (the script does not call
  ``select_job`` defensively — the driver's ``IsSelected`` lags the
  UI). Use ``--job`` to override the auto-detected name if needed.
- ``ImageTransformation = TOPLEFT`` in LAS X Advanced Settings.
- AFC / autofocus OFF; no LAS X modal dialogs.
- Stage positioned over a region with cells visible at the current
  zoom / objective.

Usage
-----
    # Acquire + segment + load all cells
    python segment_and_define_rois.py

    # Re-segment an existing image instead of acquiring
    python segment_and_define_rois.py --image source.tif

    # Limit to the 5 largest cells, custom Cellpose diameter
    python segment_and_define_rois.py --max-rois 5 --diameter 30
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

# Allow ``import navigator_expert`` from any CWD.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import tifffile
from cellpose import models
from skimage.measure import approximate_polygon, find_contours, regionprops

import navigator_expert.driver as drv
from navigator_expert.driver.experimental.lrp_edits.roi import (
    ROI_POLYGON,
    argb_color,
    lrp_add_roi,
    lrp_clear_rois,
    lrp_enable_roi_scan,
    lrp_verify_roi_count,
    lrp_verify_roi_scan,
    pixels_to_roi,
)
from navigator_expert.driver.templates.parsers import (
    get_master_attrs,
    get_rois,
    parse_lrp,
)
from navigator_expert.driver.templates.files import (
    TEMPLATE_XML,
    find_scanning_templates_dir,
    save_experiment,
)
from navigator_expert.driver.templates.transaction import apply_lrp_change


log = logging.getLogger("segment_and_define_rois")


# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

#: Default minimum cell area (in pixels) to include as an ROI. Filters
#: out segmentation noise without tuning per dataset.
DEFAULT_MIN_AREA_PX: int = 50

#: Tolerance (pixels) for polygon simplification. Larger = fewer
#: vertices, more angular outline. 2 px is a good default — keeps the
#: outline visually faithful while staying well under LAS X's polygon
#: vertex budget.
DEFAULT_CONTOUR_TOLERANCE_PX: float = 2.0

#: Pause this many seconds after loading ROIs so the operator can
#: inspect them in the LAS X UI before the optional cleanup prompt.
DEFAULT_VISUAL_PAUSE_S: float = 3.0

#: How long to wait for OME-TIFF files to settle on the export drive.
FILE_STABILITY_TIMEOUT_S: int = 30

#: Distinct ARGB colours cycled through the loaded ROIs so they are
#: visually separable in the LAS X overlay.
ROI_COLOUR_PALETTE: tuple[int, ...] = (
    argb_color(255,   0,   0),    # red
    argb_color(  0, 255,   0),    # green
    argb_color(  0, 100, 255),    # blue
    argb_color(255, 255,   0),    # yellow
    argb_color(255,   0, 255),    # magenta
    argb_color(  0, 255, 255),    # cyan
    argb_color(255, 128,   0),    # orange
    argb_color(128,   0, 255),    # purple
    argb_color(255, 128, 128),    # pink
    argb_color(128, 255,   0),    # lime
)


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Acquire, Cellpose-segment, and load polygon ROIs in LAS X.",
    )
    p.add_argument("--job", default=None,
                   help="LAS X job name. Default: the currently selected job.")
    p.add_argument("--image", type=Path, default=None,
                   help="Re-segment an existing TIFF instead of acquiring.")
    p.add_argument("--channel", type=int, default=0,
                   help="Channel index for multi-file acquires (default: 0).")
    p.add_argument("--max-rois", type=int, default=0,
                   help="Cap the number of ROIs (largest first). 0 = unlimited.")
    p.add_argument("--min-area-px", type=int, default=DEFAULT_MIN_AREA_PX,
                   help=f"Minimum cell area in pixels (default: "
                        f"{DEFAULT_MIN_AREA_PX}).")
    p.add_argument("--diameter", type=float, default=None,
                   help="Cellpose nucleus diameter in image pixels. Default: auto.")
    p.add_argument("--no-gpu", action="store_true",
                   help="Disable GPU for Cellpose.")
    p.add_argument("--tolerance-px", type=float,
                   default=DEFAULT_CONTOUR_TOLERANCE_PX,
                   help=f"Contour simplification tolerance, in pixels "
                        f"(default: {DEFAULT_CONTOUR_TOLERANCE_PX}).")
    p.add_argument("--no-roi-scan", action="store_true",
                   help="Add ROIs but leave ROI scan disabled (overlay only).")
    p.add_argument("--no-backlash", action="store_true",
                   help="Skip backlash takeup before the acquire.")
    p.add_argument("--pause", type=float, default=DEFAULT_VISUAL_PAUSE_S,
                   help=f"Seconds to pause after load for visual inspection "
                        f"(default: {DEFAULT_VISUAL_PAUSE_S}).")
    p.add_argument("--no-cleanup-prompt", action="store_true",
                   help="Leave ROIs in place; don't prompt for cleanup.")
    p.add_argument("--output-dir", type=Path, default=None,
                   help="Where to save image + summary "
                        "(default: config/segment_and_rois/<timestamp>/).")
    return p.parse_args(argv)


# ──────────────────────────────────────────────────────────────────────
# Domain types
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FrameGeometry:
    """Geometry of the segmented frame."""
    pixel_size_um: float
    image_size_px: int


@dataclass(frozen=True)
class CellRoi:
    """One polygon ROI ready to load via the LRP editor."""
    label: int
    area_px: int
    n_orig_vertices: int
    vertices_m: np.ndarray             # (N, 2) array, polygon in metres
    translation_m: tuple[float, float] # ROI translation, metres


# ──────────────────────────────────────────────────────────────────────
# Tiny utilities
# ──────────────────────────────────────────────────────────────────────


def _abort(msg: str, code: int = 1) -> None:
    print(f"ABORT: {msg}")
    sys.exit(code)


def _default_output_dir() -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return (Path(__file__).resolve().parents[2]
            / "config" / "segment_and_rois" / ts)


def _now_iso_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


# ──────────────────────────────────────────────────────────────────────
# LAS X interaction
# ──────────────────────────────────────────────────────────────────────


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


def reset_roi_state(client: Any, job: str) -> None:
    """Clear any ROIs already in the template and disable ROI scan."""
    def _setup(p):
        lrp_enable_roi_scan(p, False, job)
        lrp_clear_rois(p, job)
    apply_lrp_change(
        client, TEMPLATE_XML, _setup,
        verify_fn=lambda p: (lrp_verify_roi_scan(p, False, job)
                             and lrp_verify_roi_count(p, 0, job)),
    )


# ──────────────────────────────────────────────────────────────────────
# Image analysis
# ──────────────────────────────────────────────────────────────────────


def segment_cells(
    image: np.ndarray, diameter: float | None, gpu: bool,
) -> np.ndarray:
    """Cellpose nucleus segmentation. Returns the integer mask array."""
    log.info("running Cellpose (gpu=%s)", gpu)
    t0 = time.perf_counter()
    model = models.CellposeModel(gpu=gpu)
    masks, _, _ = model.eval(image, diameter=diameter)
    n_cells = int(masks.max())
    log.info("Cellpose found %d cell(s) in %.1fs",
             n_cells, time.perf_counter() - t0)
    if n_cells == 0:
        _abort("Cellpose found no cells. Try adjusting --diameter or move "
               "to a denser region.")
    return masks


def extract_polygon_rois(
    masks: np.ndarray, geometry: FrameGeometry,
    min_area_px: int, tolerance_px: float, max_rois: int,
) -> list[CellRoi]:
    """Convert each segmented cell into a polygon ROI.

    Sorted by area (largest first), filtered by ``min_area_px``, and
    capped by ``max_rois`` (0 = no cap). Polygons with fewer than 4
    simplified vertices are skipped — LAS X needs a closed polygon.
    """
    image_centre_px = geometry.image_size_px / 2.0
    pixel_size_m = geometry.pixel_size_um * 1e-6

    props_sorted = sorted(regionprops(masks),
                          key=lambda p: p.area, reverse=True)
    props_filtered = [p for p in props_sorted if p.area >= min_area_px]
    log.info("cells above min-area %d px: %d", min_area_px, len(props_filtered))

    cells = props_filtered if max_rois <= 0 else props_filtered[:max_rois]
    log.info("processing %d cell(s)", len(cells))

    rois: list[CellRoi] = []
    for prop in cells:
        binary = (masks == prop.label).astype(float)
        contours = find_contours(binary, 0.5)
        if not contours:
            log.warning("cell %d: no contour, skipping", prop.label)
            continue

        contour = max(contours, key=len)
        n_orig = len(contour)
        contour_simple = approximate_polygon(contour, tolerance=tolerance_px)
        if len(contour_simple) < 4:
            log.warning("cell %d: %d vertices after simplification, skipping",
                        prop.label, len(contour_simple))
            continue

        vertices_m, translation_m = pixels_to_roi(
            contour_simple, image_centre_px, pixel_size_m,
        )
        rois.append(CellRoi(
            label=int(prop.label),
            area_px=int(prop.area),
            n_orig_vertices=int(n_orig),
            vertices_m=vertices_m,
            translation_m=tuple(translation_m),
        ))
        log.info("cell %d: area=%d px, contour %d → %d vertices",
                 prop.label, prop.area, n_orig, len(vertices_m))

    if not rois:
        _abort("No valid polygon contours extracted (after simplification).")
    return rois


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
    client = drv.connect_python_client()
    drv.require_canonical_scan_orientation()
    drv.apply_stage_limits_from_config(stage_cfg)

    job = resolve_job(client, args.job)

    print(f"Job:            {job}")
    print(f"Acquire mode:   {'use --image' if args.image else 'live acquire'}")
    print(f"Min area:       {args.min_area_px} px")
    print(f"Tolerance:      {args.tolerance_px} px")
    print(f"Max ROIs:       {args.max_rois if args.max_rois > 0 else 'unlimited'}")
    print(f"Backlash:       {'on' if not args.no_backlash else 'off'}")
    print(f"ROI scan:       {'on' if not args.no_roi_scan else 'off (overlay only)'}")
    print(f"Output dir:     {out_dir}\n")

    return client, job, stage_cfg, out_dir


def step_load_image(
    client: Any, job: str, args: argparse.Namespace, out_dir: Path,
    backlash_params: dict | None,
) -> tuple[np.ndarray, Path, FrameGeometry]:
    """Acquire (or load) a frame and return (image, path, geometry)."""
    if args.image:
        if not args.image.exists():
            _abort(f"Image not found: {args.image}")
        img = tifffile.imread(str(args.image))
        if img.ndim == 3:
            img = img[args.channel]
        path = args.image
        log.info("loaded %s (%s)", path.name, img.shape)
        # Geometry must come from LAS X — the file alone doesn't tell us
        # the pixel size. The user must keep the image's job state.
        geometry = read_frame_geometry(client, job)
    else:
        log.info("setting zoom to 1 for overview acquire")
        drv.set_zoom(client, job, 1.0)
        time.sleep(0.5)
        log.info("acquiring image")
        img, path = drv.acquire_frame(
            client, job, channel=args.channel,
            backlash_params=backlash_params,
        )
        log.info("acquired %s (%s)", path.name, img.shape)
        local_tif = out_dir / "source.tif"
        tifffile.imwrite(str(local_tif), img)
        geometry = read_frame_geometry(client, job)

    log.info("frame: %d×%d px  pixel=%.4f um  FOV=%.1f um",
             geometry.image_size_px, geometry.image_size_px,
             geometry.pixel_size_um,
             geometry.image_size_px * geometry.pixel_size_um)
    return img, path, geometry


def step_apply_rois(
    client: Any, job: str, rois: list[CellRoi], enable_roi_scan: bool,
) -> dict[str, Any]:
    """Atomically clear-then-load polygon ROIs in the scanning template."""
    n = len(rois)

    def _edit(p):
        lrp_clear_rois(p, job)
        for i, roi in enumerate(rois):
            lrp_add_roi(
                p, job, ROI_POLYGON, roi.vertices_m,
                translation=roi.translation_m,
                color=ROI_COLOUR_PALETTE[i % len(ROI_COLOUR_PALETTE)],
            )
        if enable_roi_scan:
            lrp_enable_roi_scan(p, True, job)

    def _verify(p):
        ok = lrp_verify_roi_count(p, n, job)
        if enable_roi_scan:
            ok = ok and lrp_verify_roi_scan(p, True, job)
        return ok

    t0 = time.perf_counter()
    result = apply_lrp_change(client, TEMPLATE_XML, _edit, verify_fn=_verify)
    elapsed = time.perf_counter() - t0
    if not (result and result.get("success")):
        _abort(f"ROI loading failed after {elapsed:.1f}s: {result}")
    log.info("loaded %d ROI(s) in %.1fs (%d attempt(s))",
             n, elapsed, result.get("attempts", 1))
    return {"elapsed_s": elapsed, "attempts": result.get("attempts", 1)}


def step_verify_rois_in_lrp(
    client: Any, job: str, expected_count: int,
) -> list[dict[str, Any]]:
    """Re-parse the LRP and report what's actually there."""
    templates_dir = find_scanning_templates_dir()
    lrp_path = Path(templates_dir) / TEMPLATE_XML.replace(".xml", ".lrp")
    save_experiment(client, TEMPLATE_XML, str(templates_dir), timeout=5.0)

    parsed = parse_lrp(str(lrp_path))
    rois = get_rois(parsed, job)

    log.info("LRP reports %d ROI(s) (expected %d)", len(rois), expected_count)
    summary = []
    for i, roi in enumerate(rois):
        n_vertices = len(roi.get("_Vertices", []))
        roi_type = roi.get("RoiType", "?")
        t = roi.get("_Transformation", {}) or {}
        tx_um = float(t.get("TranslationX", 0)) * 1e6
        ty_um = float(t.get("TranslationY", 0)) * 1e6
        summary.append({
            "index": i,
            "type": roi_type,
            "vertex_count": n_vertices,
            "translation_um": [tx_um, ty_um],
        })
        log.info("  ROI %d: type=%s, %d vertices, translation=(%.1f, %.1f) um",
                 i + 1, roi_type, n_vertices, tx_um, ty_um)
    return summary


def step_save_outputs(
    out_dir: Path, args: argparse.Namespace, job: str,
    image_path: Path, rois: list[CellRoi], lrp_summary: list[dict[str, Any]],
    geometry: FrameGeometry,
) -> Path:
    """Write summary.json with everything reproducible from disk."""
    summary = {
        "timestamp": _now_iso_ts(),
        "job": job,
        "image_path": str(image_path),
        "frame": {
            "pixel_size_um": geometry.pixel_size_um,
            "image_size_px": geometry.image_size_px,
            "fov_um": geometry.pixel_size_um * geometry.image_size_px,
        },
        "settings": {
            "min_area_px": args.min_area_px,
            "tolerance_px": args.tolerance_px,
            "max_rois": args.max_rois,
            "diameter": args.diameter,
            "no_gpu": args.no_gpu,
            "no_backlash": args.no_backlash,
            "no_roi_scan": args.no_roi_scan,
        },
        "rois": [
            {
                "index": i,
                "label": r.label,
                "area_px": r.area_px,
                "n_original_vertices": r.n_orig_vertices,
                "n_simplified_vertices": len(r.vertices_m),
                "translation_um": [r.translation_m[0] * 1e6,
                                   r.translation_m[1] * 1e6],
            }
            for i, r in enumerate(rois)
        ],
        "lrp_after_apply": lrp_summary,
    }
    path = out_dir / "summary.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
    return path


def step_cleanup_prompt(client: Any, job: str, args: argparse.Namespace) -> None:
    """Optional: clear ROIs + disable ROI scan after the visual pause."""
    if args.no_cleanup_prompt:
        return
    print("\n  Cleanup: disable ROI scan + clear ROIs? [y/N] ",
          end="", flush=True)
    try:
        choice = input().strip().lower()
    except EOFError:
        choice = "n"
    if choice != "y":
        log.info("ROIs left in place")
        return

    def _cleanup(p):
        lrp_enable_roi_scan(p, False, job)
        lrp_clear_rois(p, job)

    apply_lrp_change(
        client, TEMPLATE_XML, _cleanup,
        verify_fn=lambda p: (lrp_verify_roi_scan(p, False, job)
                             and lrp_verify_roi_count(p, 0, job)),
    )
    log.info("ROIs cleared, ROI scan disabled")


# ──────────────────────────────────────────────────────────────────────
# Orchestrator
# ──────────────────────────────────────────────────────────────────────


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    args = parse_args(argv)

    client, job, stage_cfg, out_dir = step_setup(args)
    backlash_params = None if args.no_backlash else stage_cfg["backlash"]

    log.info("clearing existing ROIs and disabling ROI scan")
    reset_roi_state(client, job)

    image, image_path, geometry = step_load_image(
        client, job, args, out_dir, backlash_params,
    )

    masks = segment_cells(image, args.diameter, gpu=not args.no_gpu)
    rois = extract_polygon_rois(
        masks, geometry,
        min_area_px=args.min_area_px,
        tolerance_px=args.tolerance_px,
        max_rois=args.max_rois,
    )

    step_apply_rois(client, job, rois, enable_roi_scan=not args.no_roi_scan)
    lrp_summary = step_verify_rois_in_lrp(client, job, expected_count=len(rois))
    summary_path = step_save_outputs(
        out_dir, args, job, image_path, rois, lrp_summary, geometry,
    )

    print(f"\nLoaded {len(rois)} polygon ROI(s) into job '{job}'.")
    print(f"Image  : {image_path}")
    print(f"Summary: {summary_path}")

    if args.pause > 0:
        log.info("pausing %.1fs for visual inspection in LAS X", args.pause)
        time.sleep(args.pause)

    step_cleanup_prompt(client, job, args)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)

"""summary.py -- Step 6: write run_summary.json, plot results, cleanup.

The driver owns `summary.json` (canonical per-acquisition append log,
one record per acquire_and_save call, written incrementally). This
module owns `run_summary.json` -- the rich workflow-level aggregate
written once at end-of-run: operator config, focus map, scan field,
preflight telemetry, overview stats, picks, target records.

write_summary: serialize the full workflow state into run_summary.json.
plot_results: overview-frame plot with pick markers by category.
finish: restore source job (optional) and shutdown the engine.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

import navigator_expert.driver as drv

from .context import Config, Context
from ._job_state import ensure_job_state
from .focus import FocusMap
from .overview import OverviewResult, Pick, Picks
from .selection import SelectionResult
from .target import TargetRecord


def write_summary(
    ctx: Context,
    focus_map: FocusMap,
    overview: OverviewResult,
    picks: Picks,
    selection: SelectionResult,
    records: list[TargetRecord],
) -> Path:
    """Write run_summary.json (rich workflow aggregate) into ctx.out_dir.

    rev7 schema:
      - `overview` block stays (acquisition counters + failure lists),
        but `n_picks_*` fields move to `selection`.
      - `selection` block is NEW: thresholds, mode, per-stage accounting,
        per-tile sparseness counters.
      - All `n_tiles_*` overview counters come from `OverviewResult`
        attributes (which are either persisted in overview_meta.json or
        derived from v2 NPZ scan) -- NEVER from `overview.n_tiles`, which
        means "drained AND saved tiles" (a stricter subset).
    """
    cfg = ctx.cfg
    scan_field = ctx.scan_field or {}
    tile_positions = scan_field.get("tile_positions", {})

    zs = np.array([m["zwide_um"] for m in focus_map.measured])

    config_dict = _serialize_config(cfg)
    # Transition compat: inject derived slots into config for old readers
    config_dict["source_slot"] = ctx.source_slot
    config_dict["target_slot"] = ctx.target_slot

    summary: dict[str, Any] = {
        "timestamp": ctx.out_dir.name,
        "config": config_dict,
        "source_slot": ctx.source_slot,
        "target_slot": ctx.target_slot,
        "scan_field": {
            "n_regions": len(tile_positions),
            "n_tiles": scan_field.get("n_tiles", 0),
        },
        "focus_map": {
            "model": focus_map.model,
            "origin_xy_um": list(focus_map.origin_xy_um),
            "axis": "z-wide",
            "n_markers": len(focus_map.measured),
            "z_range_um": float(zs.max() - zs.min()) if len(zs) else 0.0,
            "tilt_x_deg": float(np.degrees(np.arctan(focus_map.coeffs[0])))
            if focus_map.model == "plane" else None,
            "tilt_y_deg": float(np.degrees(np.arctan(focus_map.coeffs[1])))
            if focus_map.model == "plane" else None,
            "max_residual_um": float(np.max(np.abs(focus_map.residuals_um)))
            if len(focus_map.residuals_um) else 0.0,
            "zwide_at_focus_markers_um": [
                m["zwide_um"] for m in focus_map.measured
            ],
        },
        "preflight": {
            "source_zgalvo_um": ctx.source_zgalvo_um,
            "source_zgalvo_warning": ctx.source_zgalvo_warning,
            "cellpose_env_present": ctx.cellpose_env_present,
        },
        "overview": {
            "n_tiles_planned": overview.n_tiles_planned,
            "n_tiles_submitted": overview.n_tiles_submitted,
            "n_tiles_acquired": overview.n_tiles_acquired,
            "n_tiles_acquire_failed": len(overview.tile_acquire_failures),
            "tile_acquire_failures": overview.tile_acquire_failures,
            "n_engine_failures": len(overview.engine_failures),
            "engine_failures": overview.engine_failures,
            "n_npz_save_failures": len(overview.npz_save_failures),
            "npz_save_failures": overview.npz_save_failures,
            "completed": overview.completed,
            "simulated": picks.simulated,
        },
        "selection": {
            "mode": selection.mode,
            "n_total": selection.n_total,
            "n_qualifying": selection.n_qualifying,
            "n_selected_pre_dedup": selection.n_selected_pre_dedup,
            "n_removed_duplicate": selection.n_removed_duplicate,
            "n_removed_out_of_limits_xy": selection.n_removed_out_of_limits_xy,
            "n_removed_out_of_limits_z": selection.n_removed_out_of_limits_z,
            "n_removed_translation": selection.n_removed_translation,
            "n_final": selection.n_final,
            "n_tiles_below_sparse_cutoff":
                selection.n_tiles_below_sparse_cutoff,
            "n_tiles_empty": selection.n_tiles_empty,
            "area_threshold": selection.area_threshold,
            "intensity_threshold": selection.intensity_threshold,
            "area_threshold_auto": selection.area_threshold_auto,
            "intensity_threshold_auto": selection.intensity_threshold_auto,
            "seed_material": selection.seed_material,
        },
        "removed_picks": picks.removed_picks,
    }

    ts = ctx.target_state
    if ts.started:
        summary["target_state"] = {
            "started": True,
            "setup_stage": ts.setup_stage,
            "setup_error": ts.setup_error,
            "post_switch_zgalvo_um": ts.post_switch_zgalvo_um,
            "zgalvo_read_error": ts.zgalvo_read_error,
            "drift_um": ts.drift_um,
            "drift_warning": ts.drift_warning,
        }
    else:
        summary["target_state"] = {"started": False}

    summary["picks"] = [_serialize_pick(p) for p in picks.items]
    summary["targets"] = [_serialize_target(r, ctx.out_dir) for r in records]

    # `summary.json` is owned by the driver (canonical per-acquisition append
    # log; written by acquire_and_save). This workflow-level aggregate goes
    # to a separate file at run_dir top level.
    out_path = ctx.out_dir / "run_summary.json"
    out_path.write_text(json.dumps(summary, indent=2, default=_json_default))
    print(f"[step 6] Saved {out_path}")
    return out_path


def plot_results(
    ctx: Context,
    focus_map: FocusMap,
    picks: Picks,
    records: list[TargetRecord],
) -> None:
    """Overview-frame plot with pick markers by category."""
    import matplotlib.patches as patches
    import matplotlib.pyplot as plt

    if ctx.scan_field is None:
        print("[step 6] No scan field — skipping results plot.")
        return

    tile_positions = ctx.scan_field["tile_positions"]
    lim = ctx.boundary_limits

    fig, ax = plt.subplots(figsize=(14, 10))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#f5f5f8")

    all_x, all_y = [], []

    # Draw tiles
    for rid, region in tile_positions.items():
        ts = region.get("tile_size_um")
        if ts is None:
            continue
        half = ts / 2
        for pos in region["positions"]:
            cx, cy = pos["x_um"], pos["y_um"]
            ax.add_patch(patches.Rectangle(
                (cx - half, cy - half), ts, ts,
                linewidth=0.4, edgecolor="#cccccc",
                facecolor="#f0f0f0", zorder=1,
            ))
            all_x.extend([cx - half, cx + half])
            all_y.extend([cy - half, cy + half])

    # Boundary
    if lim:
        ax.add_patch(patches.Rectangle(
            (lim["x_min"], lim["y_min"]),
            lim["x_max"] - lim["x_min"],
            lim["y_max"] - lim["y_min"],
            linewidth=1.0, edgecolor="#aaaaaa", facecolor="none",
            linestyle=(0, (5, 4)), zorder=2,
        ))
        all_x.extend([lim["x_min"], lim["x_max"]])
        all_y.extend([lim["y_min"], lim["y_max"]])

    # Build category sets for markers
    record_map = {tuple(r.pick_id): r for r in records}

    categories = {
        "acquired": {"color": "#22aa22", "marker": "o", "picks": []},
        "failed": {"color": "#dd3333", "marker": "x", "picks": []},
        "duplicate": {"color": "#999999", "marker": ".", "picks": []},
        "out_of_xy": {"color": "#dd8800", "marker": "s", "picks": []},
        "out_of_z": {"color": "#8800dd", "marker": "^", "picks": []},
        "translation": {"color": "#cc4488", "marker": "d", "picks": []},
    }

    # Surviving picks -> acquired or failed
    for pick in picks.items:
        rec = record_map.get(tuple(pick.pick_id))
        if rec and rec.success:
            categories["acquired"]["picks"].append(pick.cell_source_stage_xy_um)
        elif rec:
            categories["failed"]["picks"].append(pick.cell_source_stage_xy_um)
        else:
            categories["acquired"]["picks"].append(pick.cell_source_stage_xy_um)

    # Removed picks -> by reason
    for rp in picks.removed_picks:
        reason = rp.get("reason", "")
        xy = rp.get("cell_source_stage_xy_um")
        if xy is None:
            continue
        if reason == "duplicate":
            categories["duplicate"]["picks"].append(xy)
        elif reason == "xy":
            categories["out_of_xy"]["picks"].append(xy)
        elif reason == "z":
            categories["out_of_z"]["picks"].append(xy)
        elif reason == "translation":
            categories["translation"]["picks"].append(xy)

    # Plot markers
    for label, cat in categories.items():
        pts = cat["picks"]
        if not pts:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        ax.scatter(
            xs, ys,
            c=cat["color"], marker=cat["marker"],
            s=30, zorder=10, label=f"{label} ({len(pts)})",
        )
        all_x.extend(xs)
        all_y.extend(ys)

    if all_x:
        span = max(max(all_x) - min(all_x), max(all_y) - min(all_y))
        pad = span * 0.05
        ax.set_xlim(min(all_x) - pad, max(all_x) + pad)
        ax.set_ylim(min(all_y) - pad, max(all_y) + pad)

    ax.set_aspect("equal")
    ax.invert_yaxis()
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_linewidth(0.8)
        spine.set_edgecolor("#cccccc")

    ok = sum(1 for r in records if r.success)
    total = len(records)
    ax.set_title(
        f"Results  ({ok}/{total} acquired, "
        f"{picks.n_picks_raw} raw picks)",
        fontsize=13, fontweight="bold", color="#222222", pad=12,
    )
    ax.legend(loc="upper right", fontsize=9, facecolor="white",
              edgecolor="#cccccc", labelcolor="#444444")
    plt.tight_layout()

    out_path = ctx.out_dir / "results.png"
    fig.savefig(out_path, dpi=150)
    print(f"[step 6] Saved {out_path}")
    plt.show()


def finish(ctx: Context) -> None:
    """Step 6.3-6.4: optionally restore source job, then shutdown."""
    cfg = ctx.cfg

    if cfg.restore_source_at_end:
        try:
            ensure_job_state(ctx, cfg.acquisition_job)
            print(f"[step 6] Restored source job (slot {ctx.source_slot}).")
        except Exception as exc:
            print(f"[step 6] WARNING: could not restore source job: {exc}")

    ctx.shutdown()
    print("[step 6] Shutdown complete.")


# ─── Internals ────────────────────────────────────────────────────


def _serialize_config(cfg: Config) -> dict:
    d = asdict(cfg)
    for k, v in d.items():
        if isinstance(v, Path):
            d[k] = str(v)
    return d


def _serialize_pick(pick: Pick) -> dict:
    return {
        "pick_id": list(pick.pick_id),
        "tile_stage_xy_um": list(pick.tile_stage_xy_um),
        "tile_zwide_um": pick.tile_zwide_um,
        "source_pixel_size_um": list(pick.source_pixel_size_um),
        "source_image_size_px": list(pick.source_image_size_px),
        "centroid_col_row_px": list(pick.centroid_col_row_px),
        "bbox_px": list(pick.bbox_px),
        "bbox_um": list(pick.bbox_um),
        "area_px": pick.area_px,
        "eccentricity": pick.eccentricity,
        "mean_intensity": pick.mean_intensity,
        "cell_source_stage_xy_um": list(pick.cell_source_stage_xy_um),
    }


def _serialize_target(rec: TargetRecord, out_dir: Path) -> dict:
    return {
        "pick_id": list(rec.pick_id),
        "cell_source_stage_xy_um": list(rec.cell_source_stage_xy_um),
        "source_zwide_um": rec.source_zwide_um,
        "target_stage_xy_um": list(rec.target_stage_xy_um)
        if rec.target_stage_xy_um else None,
        "target_zwide_um": rec.target_zwide_um,
        "target_zoom": rec.target_zoom,
        "target_pixel_size_um": rec.target_pixel_size_um,
        "tif_path": str(rec.tif_path.relative_to(out_dir))
        if rec.tif_path else None,
        "success": rec.success,
        "error": rec.error,
        "failure_stage": rec.failure_stage,
    }


def _json_default(obj):
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

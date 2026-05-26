"""summary.py -- Step 6: write run_summary.json, plot results, cleanup.

The driver owns `summary.json` (canonical per-acquisition append log,
one record per acquire_and_save call, written incrementally). This
module owns `run_summary.json` -- the rich workflow-level aggregate
written once at end-of-run: operator config, focus map, scan field,
preflight telemetry, overview stats, picks, target records.

write_summary: serialize the full pipeline state into run_summary.json.
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
    """Write run_summary.json (rich pipeline aggregate) into ctx.out_dir.

    Schema shape:
      - `overview` block holds acquisition counters + failure lists; the
        `n_picks_*` fields live in `selection`, not here.
      - `selection` block holds thresholds, mode, per-stage accounting,
        and per-tile sparseness counters.
      - All `n_tiles_*` overview counters come from `OverviewResult`
        attributes (either persisted in overview_meta.json or derived
        from the v2 NPZ scan) -- never from `overview.n_tiles`, which
        means "drained AND saved tiles" (a stricter subset).

    Per-tile sparseness counter:
      - `selection.n_tiles_below_eligible_cutoff` uses post-border
        eligible cell counts (predicate
        `eligible_count < min_cells_for_threshold`, including 0). This
        replaced an earlier `n_tiles_below_sparse_cutoff` that used raw
        cellpose counts and excluded raw-empty tiles; there is no
        machine-readable schema version field, so external consumers of
        the old name must rename.
      - The raw-detection aggregate is intentionally absent from
        run_summary.json. Raw per-tile counts remain in
        `OverviewResult.tile_cell_counts` when overview state is loaded.
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
            # Plan 2 -- hijack counters and per-tile failure list. On a
            # non-simulate run these are 0 / []; the keys are always
            # present so consumers don't have to branch on simulated.
            "n_tiles_hijacked": overview.n_tiles_hijacked,
            "n_hijack_failures": len(overview.hijack_failures),
            "hijack_failures": overview.hijack_failures,
            "mock_image_source": overview.mock_image_source,
            "completed": overview.completed,
            "simulated": picks.simulated,
        },
        "selection": {
            "mode": selection.mode,
            "n_total": selection.n_total,
            "n_near_border": selection.n_near_border,
            "n_qualifying": selection.n_qualifying,
            "n_selected_pre_dedup": selection.n_selected_pre_dedup,
            "n_removed_duplicate": selection.n_removed_duplicate,
            "n_removed_out_of_limits_xy": selection.n_removed_out_of_limits_xy,
            "n_removed_out_of_limits_z": selection.n_removed_out_of_limits_z,
            "n_removed_translation": selection.n_removed_translation,
            "n_final": selection.n_final,
            "n_tiles_below_eligible_cutoff":
                selection.n_tiles_below_eligible_cutoff,
            "n_tiles_empty": selection.n_tiles_empty,
            "area_threshold": selection.area_threshold,
            "intensity_threshold": selection.intensity_threshold,
            "area_threshold_auto": selection.area_threshold_auto,
            "intensity_threshold_auto": selection.intensity_threshold_auto,
            "border_margin_px": selection.border_margin_px,
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
    # allow_nan=False: defense-in-depth. select_targets() coerces the
    # empty-eligible threshold to the 0.0 sentinel so the known NaN path
    # never reaches here; strict JSON mode makes any future NaN source
    # raise at write time rather than emit a non-RFC "NaN" / "Infinity"
    # token to disk.
    out_path = ctx.out_dir / "run_summary.json"
    out_path.write_text(
        json.dumps(summary, indent=2, default=_json_default, allow_nan=False)
    )
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

    from .visualize import (
        _FRAME_WIDTH_IN, _FONT_FIGURE_TITLE, _COLOR_INK_PRIMARY, _TITLE_PAD,
    )

    if ctx.scan_field is None:
        print("[step 6] No scan field — skipping results plot.")
        return

    tile_positions = ctx.scan_field["tile_positions"]
    lim = ctx.boundary_limits

    fig, ax = plt.subplots(figsize=(_FRAME_WIDTH_IN, 10))
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

    # Surviving picks -> acquired or failed. Picks without a record
    # (acquire_targets was interrupted or returned early before reaching
    # them) are NOT shown as "acquired" -- the plot must never show more
    # markers than there are actual TargetRecords.
    for pick in picks.items:
        rec = record_map.get(tuple(pick.pick_id))
        if rec is None:
            continue
        if rec.success:
            categories["acquired"]["picks"].append(pick.cell_source_stage_xy_um)
        else:
            categories["failed"]["picks"].append(pick.cell_source_stage_xy_um)

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
        fontsize=_FONT_FIGURE_TITLE, fontweight="bold",
        color=_COLOR_INK_PRIMARY, pad=_TITLE_PAD,
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
        "position": pick.position,
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
        "source_tile_position": rec.source_tile_position,
        # Plan 2 -- per-record provenance. simulated=True means the
        # saved .ome.tiff carries mock pixels; failure_stage="hijack"
        # identifies a hijack-specific failure path.
        "simulated": rec.simulated,
        "mock_image_source": rec.mock_image_source,
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

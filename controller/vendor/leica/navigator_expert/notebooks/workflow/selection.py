"""Selection step: interactive target selection from overview results.

Operator runs select_targets(overview, limits, ...) after overview, sees
scatter + 6 example crops via display_selection(), adjusts thresholds and
re-runs if unhappy.

Thresholds: GLOBAL (median across all cells in all tiles). One mode per
selection (not per tile). Per-tile sparseness is reported as a descriptive
counter, not a mode. MODE_NO_QUALIFYING returns zero picks (no random
fallback) -- operator sees the empty intersection in display_selection
and adjusts.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .context import LimitsContext
from .overview import (
    OverviewResult, Pick, Picks, _dedup_picks, _filter_out_of_limits,
)


MODE_THRESHOLD = "threshold"
MODE_SPARSE = "sparse_fallback"
MODE_NO_QUALIFYING = "no_qualifying"
MODE_EMPTY = "empty"


# ─── Dataclasses ──────────────────────────────────────────────────


@dataclass
class SelectionResult:
    # Distribution data (for scatter plot)
    all_cells_area: np.ndarray
    all_cells_intensity: np.ndarray
    all_cells_labels: np.ndarray
    all_cells_tile_ids: list[tuple[str, int, int]]
    qualifying_mask: np.ndarray
    # True for cells whose bbox is within border_margin_px of any tile edge.
    # These cells are excluded from `qualifying_mask` (cannot be picked) but
    # remain in all_cells_* so display can show them as a distinct category.
    near_border_mask: np.ndarray

    # Thresholds + provenance
    area_threshold: float
    intensity_threshold: float
    area_threshold_auto: bool
    intensity_threshold_auto: bool
    border_margin_px: int
    seed_material: str
    mode: str

    # Per-stage accounting (global)
    n_total: int
    n_near_border: int
    n_qualifying: int
    n_selected_pre_dedup: int
    n_removed_duplicate: int
    n_removed_out_of_limits_xy: int
    n_removed_out_of_limits_z: int
    n_removed_translation: int
    n_final: int

    # Per-tile descriptive counters (NOT modes).
    # n_tiles_below_eligible_cutoff: tiles whose post-border eligible count
    #   (non-near-border picks per tile) is < min_cells_for_threshold.
    #   Includes tiles with 0 eligible cells (e.g. raw-empty tiles or all
    #   cells near-border within that tile).
    # n_tiles_empty: tiles whose raw cellpose detection count is 0
    #   (overview.n_tiles_empty, pre-border).
    # These are NOT mutually exclusive: a raw-empty tile counts toward
    # both, since 0 raw cells implies 0 eligible cells.
    n_tiles_below_eligible_cutoff: int
    n_tiles_empty: int

    # Final selection -- full Pick objects so display can read bbox/centroid
    selected_picks: list[Pick]

    @property
    def selected_pick_ids(self) -> list[tuple[str, int, int, int]]:
        return [p.pick_id for p in self.selected_picks]


# ─── Public API ───────────────────────────────────────────────────


def load_overview_result(analysis_dir: Path) -> OverviewResult:
    """Reconstruct OverviewResult from disk. Kernel-restart safe.

    Single pass over v2 NPZ files: builds all_picks and tile_cell_counts.
    Empty tiles (cell_labels.shape[0] == 0) contribute (tile_id, 0) to
    tile_cell_counts. Failure lists + acquire-loop counters + completed
    sentinel come from overview_meta.json if present; missing/corrupt
    meta is tolerated with a warning and completed=False.
    """
    all_picks: list[Pick] = []
    tile_cell_counts: dict[tuple[str, int, int], int] = {}

    if analysis_dir.exists():
        for npz_path in sorted(analysis_dir.glob("*.npz")):
            try:
                with np.load(npz_path, allow_pickle=True) as data:
                    version = (
                        int(data["schema_version"])
                        if "schema_version" in data.files else 1
                    )
                    if version < 2:
                        print(
                            f"[load] skipping {npz_path.name} "
                            f"(schema v{version}, need v2)"
                        )
                        continue
                    tile_id_str = tuple(str(x) for x in data["tile_id"])
                    tile_id = (
                        tile_id_str[0], int(tile_id_str[1]), int(tile_id_str[2]),
                    )
                    n = len(data["cell_labels"])
                    tile_cell_counts[tile_id] = n
                    for i in range(n):
                        all_picks.append(Pick(
                            pick_id=(
                                tile_id[0], tile_id[1], tile_id[2],
                                int(data["cell_labels"][i]),
                            ),
                            tile_stage_xy_um=tuple(data["pick_tile_stage_xy_um"][i]),
                            tile_zwide_um=float(data["pick_tile_zwide_um"][i]),
                            source_pixel_size_um=tuple(data["pick_source_pixel_size_um"][i]),
                            source_image_size_px=tuple(
                                int(x) for x in data["pick_source_image_size_px"][i]),
                            centroid_col_row_px=tuple(data["pick_centroid_col_row_px"][i]),
                            bbox_px=tuple(int(x) for x in data["pick_bbox_px"][i]),
                            bbox_um=tuple(data["pick_bbox_um"][i]),
                            area_px=int(data["cell_area_px"][i]),
                            eccentricity=float(data["pick_eccentricity"][i]),
                            mean_intensity=float(data["cell_mean_intensity"][i]),
                            cell_source_stage_xy_um=tuple(
                                data["pick_cell_source_stage_xy_um"][i]),
                        ))
            except Exception as exc:
                print(f"[load] WARNING: failed to read {npz_path.name}: {exc}")
                continue

    meta_path = analysis_dir / "overview_meta.json"
    tile_acquire_failures: list[dict] = []
    engine_failures: list[dict] = []
    npz_save_failures: list[dict] = []
    n_tiles_planned = 0
    n_tiles_submitted = 0
    completed = False
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            tile_acquire_failures = meta.get("tile_acquire_failures", [])
            engine_failures = meta.get("engine_failures", [])
            npz_save_failures = meta.get("npz_save_failures", [])
            completed = bool(meta.get("completed", False))
            n_tiles_planned = int(meta.get("n_tiles_planned", 0))
            n_tiles_submitted = int(meta.get("n_tiles_submitted", 0))
            if "n_tiles_planned" not in meta or "n_tiles_submitted" not in meta:
                print(
                    "[load] WARNING: overview_meta.json predates schema v2 "
                    "(missing n_tiles_planned/n_tiles_submitted). "
                    "Summary counters for planned/submitted will be 0."
                )
        except (json.JSONDecodeError, OSError) as exc:
            print(
                f"[load] WARNING: overview_meta.json unreadable ({exc}); "
                f"failure lists default to []. Treating run as incomplete."
            )
    else:
        print(
            "[load] WARNING: no overview_meta.json found at "
            f"{analysis_dir}; either zero tiles ran or the previous "
            "run_overview crashed before writing meta. Treating run as "
            "incomplete; failure lists default to []."
        )

    if not completed:
        print(
            f"[load] NOTE: overview run at {analysis_dir} is marked "
            f"incomplete. Selecting from {len(all_picks)} picks across "
            f"{len(tile_cell_counts)} tile(s) anyway -- operator should verify."
        )

    return OverviewResult(
        all_picks=all_picks,
        tile_acquire_failures=tile_acquire_failures,
        engine_failures=engine_failures,
        npz_save_failures=npz_save_failures,
        tile_cell_counts=tile_cell_counts,
        n_tiles_planned=n_tiles_planned,
        n_tiles_submitted=n_tiles_submitted,
        completed=completed,
    )


def select_targets(
    overview: OverviewResult,
    limits: LimitsContext,
    *,
    n_per_tile: int = 4,
    area_threshold: float | None = None,
    intensity_threshold: float | None = None,
    min_cells_for_threshold: int = 10,
    border_margin_px: int = 64,
    seed: int | None = None,
) -> tuple[Picks, SelectionResult]:
    """Global-threshold selection. Mode is global, not per-tile.

    border_margin_px (default 64): cells whose bbox falls within this many
    pixels of any tile edge are excluded from qualifying. Border cells have
    truncated area/intensity stats (the cell extends beyond the field of
    view) and produce unreliable picks. Set to 0 to disable the filter.
    When n_eligible == n_total - n_near_border == 0 (all cells near-border),
    auto-thresholds default to the 0.0 sentinel and mode is forced to
    MODE_NO_QUALIFYING; the on-disk run_summary.json stays strict-JSON-safe
    (no NaN tokens).

    Mode dispatch is gated on n_eligible (not n_total) so the population
    used for the cutoff matches the population the median is computed on:
      - n_total == 0                                  -> MODE_EMPTY
      - n_eligible == 0  (n_total > 0)                -> MODE_NO_QUALIFYING
      - 0 < n_eligible < min_cells_for_threshold      -> MODE_SPARSE
      - else                                          -> MODE_THRESHOLD
    A final override flips any non-EMPTY result with n_qualifying == 0 to
    MODE_NO_QUALIFYING (defensive: makes "sparse with zero qualifying"
    unreachable).

    NO_QUALIFYING returns zero picks. No random fallback -- operator sees
    the empty intersection in display_selection and adjusts.

    See plan rev7 sections "Commit C / 3. workflow/selection.py" for the
    full state machine.
    """
    all_picks = overview.all_picks
    tile_cell_counts = overview.tile_cell_counts

    n_tiles_empty = overview.n_tiles_empty

    n_total = len(all_picks)
    areas = np.array([p.area_px for p in all_picks], dtype=np.float64)
    intensities = np.array(
        [p.mean_intensity for p in all_picks], dtype=np.float64,
    )
    labels = np.array(
        [p.pick_id[3] for p in all_picks], dtype=np.int64,
    )
    cell_tile_ids = [
        (p.pick_id[0], p.pick_id[1], p.pick_id[2]) for p in all_picks
    ]

    # Border-distance mask. Excluded from qualifying; preserved for display.
    near_border_mask = _compute_near_border_mask(all_picks, border_margin_px)
    n_near_border = int(near_border_mask.sum())
    n_eligible = n_total - n_near_border

    # Per-tile eligible counts (post-border). Seeded with every tile_id from
    # tile_cell_counts so raw-empty tiles still appear with eligible=0 and
    # count toward n_tiles_below_eligible_cutoff.
    eligible_per_tile: dict[tuple[str, int, int], int] = {
        tile_id: 0 for tile_id in tile_cell_counts
    }
    for pick, is_border in zip(all_picks, near_border_mask):
        if not is_border:
            tile_key = (pick.pick_id[0], pick.pick_id[1], pick.pick_id[2])
            if tile_key in eligible_per_tile:
                eligible_per_tile[tile_key] += 1
    n_tiles_below_eligible_cutoff = sum(
        1 for count in eligible_per_tile.values()
        if count < min_cells_for_threshold
    )

    area_threshold_auto = area_threshold is None
    intensity_threshold_auto = intensity_threshold is None

    if n_total == 0:
        mode = MODE_EMPTY
        area_t = 0.0 if area_threshold_auto else float(area_threshold)
        intensity_t = (
            0.0 if intensity_threshold_auto else float(intensity_threshold)
        )
        qualifying_mask = np.zeros(0, dtype=bool)
    elif n_eligible == 0:
        # All cells are near-border. np.median([]) would return NaN and
        # contaminate run_summary.json. Sentinel: thresholds = 0.0,
        # mode = MODE_NO_QUALIFYING. Operator sees the empty intersection
        # in display_selection and reduces border_margin_px or re-acquires.
        mode = MODE_NO_QUALIFYING
        area_t = 0.0 if area_threshold_auto else float(area_threshold)
        intensity_t = (
            0.0 if intensity_threshold_auto else float(intensity_threshold)
        )
        qualifying_mask = np.zeros(n_total, dtype=bool)
    elif n_eligible < min_cells_for_threshold:
        # Gate on n_eligible (not n_total): we never compute statistics on
        # the border-excluded subset, so the population used for the cutoff
        # must match the population the median would be computed on.
        mode = MODE_SPARSE
        area_t = 0.0 if area_threshold_auto else float(area_threshold)
        intensity_t = (
            0.0 if intensity_threshold_auto else float(intensity_threshold)
        )
        qualifying_mask = np.ones(n_total, dtype=bool) & ~near_border_mask
    else:
        # Compute thresholds on non-border cells only — border cells have
        # truncated stats and would skew the median. The n_eligible == 0
        # branch above guarantees non_border_areas is non-empty here.
        non_border_areas = areas[~near_border_mask]
        non_border_intensities = intensities[~near_border_mask]
        area_t = (
            float(np.median(non_border_areas)) if area_threshold_auto
            else float(area_threshold)
        )
        intensity_t = (
            float(np.median(non_border_intensities)) if intensity_threshold_auto
            else float(intensity_threshold)
        )
        qualifying_mask = (
            (areas >= area_t) & (intensities >= intensity_t) & ~near_border_mask
        )
        mode = MODE_THRESHOLD

    n_qualifying = int(qualifying_mask.sum())

    # Final override: if no cells qualify (threshold rejected all, sparse
    # path with all-border tiles, etc.), force MODE_NO_QUALIFYING so
    # downstream consumers can rely on "qualifying >= 1 in this mode".
    # MODE_EMPTY is preserved as a separate "no cells detected at all"
    # signal that the operator may want to distinguish.
    if mode != MODE_EMPTY and n_qualifying == 0:
        mode = MODE_NO_QUALIFYING

    # Sampling
    seed_str = str(seed) if seed is not None else "auto"
    seed_material = f"seed={seed_str}"

    pre_dedup_picks: list[Pick] = []
    if mode in (MODE_THRESHOLD, MODE_SPARSE) and n_qualifying > 0:
        # Group qualifying picks by tile_id, preserving input order
        groups: dict[tuple[str, int, int], list[Pick]] = {}
        for pick, q in zip(all_picks, qualifying_mask):
            if not q:
                continue
            key = (pick.pick_id[0], pick.pick_id[1], pick.pick_id[2])
            groups.setdefault(key, []).append(pick)

        for tile_id, group in sorted(groups.items()):
            rid, row, col = tile_id
            material = f"{seed_str}_{rid}_{row}_{col}"
            rng_seed = int.from_bytes(
                hashlib.sha256(material.encode()).digest()[:8], "big",
            )
            rng = np.random.default_rng(rng_seed)
            k = min(n_per_tile, len(group))
            if k == 0:
                continue
            idx = rng.choice(len(group), size=k, replace=False)
            for j in sorted(idx):
                pre_dedup_picks.append(group[j])

    n_selected_pre_dedup = len(pre_dedup_picks)

    # Dedup + filter
    deduped, removed_dup = _dedup_picks(pre_dedup_picks)
    final, removed_xy, removed_z, removed_xlat = _filter_out_of_limits(
        deduped, limits,
    )

    picks = Picks(
        items=final,
        n_picks_raw=n_total,
        n_picks_removed_duplicate=len(removed_dup),
        n_picks_out_of_limits_xy=len(removed_xy),
        n_picks_out_of_limits_z=len(removed_z),
        removed_picks=removed_dup + removed_xy + removed_z + removed_xlat,
        tile_acquire_failures=overview.tile_acquire_failures,
        engine_failures=overview.engine_failures,
    )

    selection = SelectionResult(
        all_cells_area=areas,
        all_cells_intensity=intensities,
        all_cells_labels=labels,
        all_cells_tile_ids=cell_tile_ids,
        qualifying_mask=qualifying_mask,
        near_border_mask=near_border_mask,
        area_threshold=area_t,
        intensity_threshold=intensity_t,
        area_threshold_auto=area_threshold_auto,
        intensity_threshold_auto=intensity_threshold_auto,
        border_margin_px=int(border_margin_px),
        seed_material=seed_material,
        mode=mode,
        n_total=n_total,
        n_near_border=n_near_border,
        n_qualifying=n_qualifying,
        n_selected_pre_dedup=n_selected_pre_dedup,
        n_removed_duplicate=len(removed_dup),
        n_removed_out_of_limits_xy=len(removed_xy),
        n_removed_out_of_limits_z=len(removed_z),
        n_removed_translation=len(removed_xlat),
        n_final=len(final),
        n_tiles_below_eligible_cutoff=n_tiles_below_eligible_cutoff,
        n_tiles_empty=n_tiles_empty,
        selected_picks=list(final),
    )

    print(
        f"[step 4] mode={mode}, total={n_total} "
        f"({n_near_border} near-border excluded), "
        f"qualifying={n_qualifying}, "
        f"selected_pre_dedup={n_selected_pre_dedup}, final={len(final)} "
        f"(area_threshold={area_t:.1f} "
        f"{'auto' if area_threshold_auto else 'override'}, "
        f"intensity_threshold={intensity_t:.1f} "
        f"{'auto' if intensity_threshold_auto else 'override'}, "
        f"border_margin_px={border_margin_px})"
    )

    return picks, selection


def _compute_near_border_mask(
    all_picks: list[Pick], border_margin_px: int,
) -> np.ndarray:
    """True for picks whose bbox is within border_margin_px of any tile edge.

    bbox_px convention is skimage regionprops: (y0, x0, y1, x1).
    source_image_size_px is (width, height) -- (pixels_x, pixels_y).
    """
    if border_margin_px <= 0 or not all_picks:
        return np.zeros(len(all_picks), dtype=bool)
    mask = np.zeros(len(all_picks), dtype=bool)
    for i, p in enumerate(all_picks):
        y0, x0, y1, x1 = p.bbox_px
        width, height = p.source_image_size_px
        if (x0 < border_margin_px
                or y0 < border_margin_px
                or x1 > width - border_margin_px
                or y1 > height - border_margin_px):
            mask[i] = True
    return mask

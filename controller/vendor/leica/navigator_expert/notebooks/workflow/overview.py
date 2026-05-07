"""overview.py -- Step 4: overview acquisition with live analysis.

Snake-ordered tile acquisition with per-tile engine submission,
opportunistic + blocking drain, dedup, and out-of-limits filter.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import navigator_expert.driver as drv

from .context import Context
from .focus import FocusMap
from ._acquire import acquire, save_acquired


# ─── Dataclasses ──────────────────────────────────────────────────


@dataclass
class Pick:
    pick_id: tuple[str, int, int, int]

    # Provenance
    tile_stage_xy_um: tuple[float, float]
    tile_zwide_um: float
    source_pixel_size_um: tuple[float, float]
    source_image_size_px: tuple[int, int]

    # Cell geometry
    centroid_col_row_px: tuple[float, float]
    bbox_px: tuple[int, int, int, int]
    bbox_um: tuple[float, float]
    area_px: int
    eccentricity: float
    mean_intensity: float

    # Canonical pick address
    cell_source_stage_xy_um: tuple[float, float]


@dataclass
class Picks:
    items: list[Pick]

    n_picks_raw: int = 0
    n_picks_removed_duplicate: int = 0
    n_picks_out_of_limits_xy: int = 0
    n_picks_out_of_limits_z: int = 0

    removed_picks: list[dict] = field(default_factory=list)

    tile_acquire_failures: list[dict] = field(default_factory=list)
    engine_failures: list[dict] = field(default_factory=list)

    simulated: bool = False


# ─── Public API ───────────────────────────────────────────────────


def run_overview_with_picks(
    ctx: Context,
    focus_map: FocusMap,
) -> Picks:
    """Step 4: acquire overview tiles, submit to engine, drain, filter.

    Returns Picks with surviving items for Step 5 and full accounting
    of removed/failed picks for summary.json.
    """
    cfg = ctx.cfg
    client = ctx.client
    engine = ctx.engine

    tile_positions = ctx.scan_field["tile_positions"]

    # 4.0 -- strip template before acquisition
    if not drv.strip_template(client):
        raise RuntimeError("strip_template failed before overview acquisition.")

    try:
        # 4.0b -- read source frame geometry (pixel size + image size)
        settings = drv.get_job_settings(client, cfg.acquisition_job)
        geo = drv.parse_tile_geometry(settings)
        pixel_size_um = (float(geo["pixel_w_um"]), float(geo["pixel_h_um"]))
        image_size_px = (int(geo["pixels_x"]), int(geo["pixels_y"]))

        # 4.1 -- build snake order
        sequence = _build_snake_sequence(tile_positions)
        print(f"[step 4] {len(sequence)} tiles in snake order")

        # Snapshot engine failure count so we only report new ones (D19)
        failure_count_before = len(
            engine.status("overview").get("failures", [])
        )

        # 4.2-4.3 -- acquire + submit + opportunistic drain
        buffer: list[dict] = []
        n_submitted = 0
        tile_acquire_failures: list[dict] = []

        for i, tile in enumerate(sequence):
            rid = tile["region"]
            x_um = tile["x_um"]
            y_um = tile["y_um"]
            zwide_um = float(focus_map.interpolate_zwide(x_um, y_um))
            tile_id = (str(rid), tile["row"], tile["col"])

            print(
                f"[{i + 1}/{len(sequence)}] R{rid} "
                f"r{tile['row']}c{tile['col']}  "
                f"x={x_um:.0f} y={y_um:.0f} z={zwide_um:.2f}",
                end="", flush=True,
            )

            try:
                image, lasx_path = acquire(
                    ctx, cfg.acquisition_job, x_um, y_um, zwide_um,
                )
                tif_name = f"tile_R{rid:>02s}_r{tile['row']:02d}_c{tile['col']:02d}.tif"
                tif_path = save_acquired(
                    image, lasx_path, ctx.out_dir / "overview" / tif_name,
                )
                engine.submit("overview", {
                    "image_path": str(tif_path),
                    "tile_id": tile_id,
                    "tile_stage_xy_um": (x_um, y_um),
                    "tile_zwide_um": zwide_um,
                    "source_pixel_size_um": pixel_size_um,
                    "source_image_size_px": image_size_px,
                    "image_to_stage": ctx.calibration["image_to_stage"],
                    "n_picks": cfg.n_picks_per_tile,
                    "feature": cfg.feature,
                    "analysis_image_source": cfg.analysis_image_source,
                })
                n_submitted += 1
                print(f"  ok")
            except Exception as exc:
                tile_acquire_failures.append({
                    "tile_id": tile_id, "error": str(exc),
                })
                print(f"  FAIL ({exc})")
                continue

            # Opportunistic drain
            buffer.extend(engine.results("overview"))

        # 4.4 -- blocking drain
        s = None
        while True:
            s = engine.status("overview")
            buffer.extend(engine.results("overview"))
            if s["pending"] == 0 and s["running"] == 0:
                break
            time.sleep(0.05)

        # New failures only (D19) — reuse s from the final loop iteration
        new_failures = s.get("failures", [])[failure_count_before:]

        # Phase-0 only: each submit produces exactly one result or failure
        assert len(buffer) + len(new_failures) == n_submitted, (
            f"Drain mismatch: {len(buffer)} results + {len(new_failures)} "
            f"failures != {n_submitted} submitted"
        )

        print(f"\n[step 4] Drain complete: {len(buffer)} result(s), "
              f"{len(new_failures)} engine failure(s), "
              f"{len(tile_acquire_failures)} tile acquire failure(s)")

        # 4.5 -- collect picks from engine results
        raw_picks = _collect_picks_from_results(buffer)
        n_picks_raw = len(raw_picks)

        # 4.6 -- dedup by cell_source_stage_xy_um (D5)
        deduped, removed_dup = _dedup_picks(raw_picks)

        # 4.7 -- filter out-of-limits (D6)
        surviving, removed_xy, removed_z, removed_xlat = _filter_out_of_limits(
            deduped, ctx,
        )

        print(f"[step 4] Picks: {n_picks_raw} raw -> "
              f"{len(removed_dup)} dup, "
              f"{len(removed_xy)} out-xy, "
              f"{len(removed_z)} out-z, "
              f"{len(removed_xlat)} xlat-fail -> "
              f"{len(surviving)} final")

        all_removed = removed_dup + removed_xy + removed_z + removed_xlat
    finally:
        try:
            drv.restore_template(client)
            print("[step 4] Template restored.")
        except Exception as exc:
            print(f"[step 4] WARNING: could not restore template: {exc}")

    return Picks(
        items=surviving,
        n_picks_raw=n_picks_raw,
        n_picks_removed_duplicate=len(removed_dup),
        n_picks_out_of_limits_xy=len(removed_xy),
        n_picks_out_of_limits_z=len(removed_z),
        removed_picks=all_removed,
        tile_acquire_failures=tile_acquire_failures,
        engine_failures=new_failures,
    )


# ─── Internals ────────────────────────────────────────────────────


def _build_snake_sequence(
    tile_positions: dict,
) -> list[dict]:
    """Build a snake-ordered acquisition sequence from tile positions."""
    sequence: list[dict] = []
    for rid, region in sorted(tile_positions.items(), key=lambda r: str(r[0])):
        rows: dict[int, list[dict]] = {}
        for p in region["positions"]:
            rows.setdefault(p["row"], []).append(p)
        for i, row_idx in enumerate(sorted(rows)):
            row_tiles = sorted(rows[row_idx], key=lambda p: p["col"])
            if i % 2 == 1:
                row_tiles = row_tiles[::-1]
            for p in row_tiles:
                sequence.append({
                    "region": str(rid),
                    "row": p["row"],
                    "col": p["col"],
                    "x_um": p["x_um"],
                    "y_um": p["y_um"],
                })
    return sequence


def _collect_picks_from_results(buffer: list[dict]) -> list[Pick]:
    """Extract Pick objects from engine result dicts."""
    picks: list[Pick] = []
    for result in buffer:
        pick_data = result.get("pick_targets", {}).get("picks", [])
        for pd in pick_data:
            picks.append(Pick(
                pick_id=tuple(pd["pick_id"]),
                tile_stage_xy_um=tuple(pd["tile_stage_xy_um"]),
                tile_zwide_um=pd["tile_zwide_um"],
                source_pixel_size_um=tuple(pd["source_pixel_size_um"]),
                source_image_size_px=tuple(pd["source_image_size_px"]),
                centroid_col_row_px=tuple(pd["centroid_col_row_px"]),
                bbox_px=tuple(pd["bbox_px"]),
                bbox_um=tuple(pd["bbox_um"]),
                area_px=pd["area_px"],
                eccentricity=pd["eccentricity"],
                mean_intensity=pd["mean_intensity"],
                cell_source_stage_xy_um=tuple(pd["cell_source_stage_xy_um"]),
            ))
    return picks


def _dedup_picks(picks: list[Pick]) -> tuple[list[Pick], list[dict]]:
    """Deduplicate picks by cell_source_stage_xy_um distance (D5).

    Two picks are duplicates when distance < 0.75 * max(bbox_diag).
    Keeps the one with higher area; loser goes to removed list.
    """
    removed: list[dict] = []
    surviving: list[Pick] = []

    for pick in sorted(picks, key=lambda p: p.area_px, reverse=True):
        is_dup = False
        for winner in surviving:
            dist = math.hypot(
                pick.cell_source_stage_xy_um[0] - winner.cell_source_stage_xy_um[0],
                pick.cell_source_stage_xy_um[1] - winner.cell_source_stage_xy_um[1],
            )
            pick_diag = math.hypot(*pick.bbox_um)
            winner_diag = math.hypot(*winner.bbox_um)
            threshold = max(pick_diag, winner_diag) * 0.75
            if dist < threshold:
                removed.append({
                    "pick_id": pick.pick_id,
                    "reason": "duplicate",
                    "cell_source_stage_xy_um": pick.cell_source_stage_xy_um,
                    "winner_pick_id": winner.pick_id,
                })
                is_dup = True
                break
        if not is_dup:
            surviving.append(pick)

    return surviving, removed


def _filter_out_of_limits(
    picks: list[Pick],
    ctx: Context,
) -> tuple[list[Pick], list[dict], list[dict]]:
    """Filter picks whose target position falls outside stage limits (D6).

    Predicts target XY and Z via the translator (no hardware).
    """
    cfg = ctx.cfg
    calibration = ctx.calibration
    stage_cfg = ctx.stage_config

    lim = ctx.boundary_limits or {}
    x_min = lim.get("x_min")
    x_max = lim.get("x_max")
    y_min = lim.get("y_min")
    y_max = lim.get("y_max")
    z_wide_min, z_wide_max = stage_cfg["limits_um"]["z_wide"]

    has_xy_limits = all(v is not None for v in (x_min, x_max, y_min, y_max))

    surviving: list[Pick] = []
    removed_xy: list[dict] = []
    removed_z: list[dict] = []
    removed_translation: list[dict] = []

    for pick in picks:
        try:
            tx, ty, tz = drv.translate_xyz_between_objectives(
                pick.cell_source_stage_xy_um[0],
                pick.cell_source_stage_xy_um[1],
                pick.tile_zwide_um,
                calibration,
                from_slot=ctx.source_slot,
                to_slot=ctx.target_slot,
            )
        except Exception as exc:
            removed_translation.append({
                "pick_id": pick.pick_id,
                "reason": "translation",
                "cell_source_stage_xy_um": pick.cell_source_stage_xy_um,
                "error": str(exc),
            })
            continue

        if has_xy_limits and not (x_min <= tx <= x_max and y_min <= ty <= y_max):
            removed_xy.append({
                "pick_id": pick.pick_id,
                "reason": "xy",
                "cell_source_stage_xy_um": pick.cell_source_stage_xy_um,
                "target_xy_um": (tx, ty),
            })
            continue

        if not (z_wide_min <= tz <= z_wide_max):
            removed_z.append({
                "pick_id": pick.pick_id,
                "reason": "z",
                "cell_source_stage_xy_um": pick.cell_source_stage_xy_um,
                "target_z_um": tz,
            })
            continue

        surviving.append(pick)

    return surviving, removed_xy, removed_z, removed_translation

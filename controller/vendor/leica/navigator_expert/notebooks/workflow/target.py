"""target.py -- Step 5: acquire targets at the high-magnification objective.

Switch to the target job + objective once, then per pick: translate,
compute zoom, move, acquire, save. Per-pick failure isolation (D17).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import navigator_expert.driver as drv
from navigator_expert.driver.commands import select_job as drv_select_job

from .context import Context, TargetState
from .overview import Picks
from ._acquire import acquire, save_acquired


@dataclass
class TargetRecord:
    pick_id: tuple[str, int, int, int]
    cell_source_stage_xy_um: tuple[float, float]
    source_zwide_um: float
    target_stage_xy_um: tuple[float, float] | None
    target_zwide_um: float | None
    target_zoom: int | None
    target_pixel_size_um: float | None
    tif_path: Path | None
    success: bool
    error: str | None
    failure_stage: str | None = None


def acquire_targets(ctx: Context, picks: Picks) -> list[TargetRecord]:
    """Step 5: switch objective, translate picks, acquire each target.

    Per-pick failure isolation: if translation, zoom, move, or acquire
    fails for one pick, it yields a TargetRecord with success=False,
    failure_stage set to the step that failed, and the loop continues.
    """
    cfg = ctx.cfg
    client = ctx.client
    calibration = ctx.calibration

    # Reset target state for this run
    ts = TargetState()
    ctx.target_state = ts

    if not picks.items:
        print("[step 5] No picks to acquire -- skipping target pass.")
        return []

    ts.started = True

    try:
        # 5.0 -- strip template before acquisition
        ts.setup_stage = "strip"
        if not drv.strip_template(client):
            raise RuntimeError("strip_template failed before target acquisition.")

        # 5.1 -- switch to target job + objective (in that order, D10)
        ts.setup_stage = "select_job"
        r = drv_select_job(client, cfg.target_job)
        if not r or not r.get("success"):
            raise RuntimeError(
                f"select_job({cfg.target_job!r}) failed: {r!r}")
        ctx.current_job = cfg.target_job

        ts.setup_stage = "set_objective"
        set_result = drv.set_objective(
            client, cfg.target_job, ctx.hw, slot_index=cfg.target_slot,
        )
        if not set_result or not set_result.get("success"):
            raise RuntimeError(
                f"set_objective(slot={cfg.target_slot}) failed: "
                f"{set_result!r}")
        ts.objective_switched = True

        ts.setup_stage = "settle"
        time.sleep(cfg.settle_after_objective_switch_s)

        # 5.1b -- read target z-galvo for telemetry (D3)
        ts.setup_stage = "read_zgalvo"
        try:
            settings = drv.get_job_settings(client, cfg.target_job)
            ch = drv.make_changeable_copy(settings)
            ts.post_switch_zgalvo_um = float(ch["zPosition"]["z-galvo"])
            ts.drift_um = (
                ts.post_switch_zgalvo_um - ctx.source_zgalvo_um)
            ts.drift_warning = abs(ts.drift_um) > 0.5
            if ts.drift_warning:
                print(
                    f"[step 5] WARNING: z-galvo drift = "
                    f"{ts.drift_um:+.3f} um "
                    f"(source={ctx.source_zgalvo_um:+.3f}, "
                    f"target={ts.post_switch_zgalvo_um:+.3f})")
        except Exception as exc:
            ts.zgalvo_read_error = str(exc)
            print(f"[step 5] WARNING: could not read target z-galvo: "
                  f"{exc}")

        ts.setup_stage = None  # setup complete

    except Exception as exc:
        ts.setup_error = str(exc)
        raise

    # 5.3 -- sort picks by source XY (deterministic order)
    sorted_picks = sorted(
        picks.items,
        key=lambda p: (p.cell_source_stage_xy_um[0],
                       p.cell_source_stage_xy_um[1]),
    )

    print(f"[step 5] {len(sorted_picks)} picks to acquire at "
          f"slot {cfg.target_slot}")

    records: list[TargetRecord] = []

    for i, pick in enumerate(sorted_picks):
        print(
            f"[{i + 1}/{len(sorted_picks)}] "
            f"pick={pick.pick_id}  "
            f"src=({pick.cell_source_stage_xy_um[0]:.0f}, "
            f"{pick.cell_source_stage_xy_um[1]:.0f})",
            end="", flush=True,
        )

        # Track partial state so failures preserve what succeeded
        tx = ty = tz = None
        target_pixel_size_um = None
        tif_path = None
        stage = "translate"

        try:
            tx, ty, tz = drv.translate_xyz_between_objectives(
                pick.cell_source_stage_xy_um[0],
                pick.cell_source_stage_xy_um[1],
                pick.tile_zwide_um,
                calibration,
                from_slot=cfg.source_slot,
                to_slot=cfg.target_slot,
            )

            stage = "geometry"
            target_settings = drv.get_job_settings(client, cfg.target_job)
            target_geo = drv.parse_tile_geometry(target_settings)
            target_pixel_size_um = float(target_geo["pixel_w_um"])

            stage = "acquire"
            image, lasx_path = acquire(ctx, cfg.target_job, tx, ty, tz)

            stage = "save"
            rid, row, col, label = pick.pick_id
            tif_name = f"pick_R{rid:>02s}_r{row:02d}_c{col:02d}_l{label:04d}.tif"
            tif_path = save_acquired(
                image, lasx_path, ctx.out_dir / "target" / tif_name,
            )

            records.append(TargetRecord(
                pick_id=pick.pick_id,
                cell_source_stage_xy_um=pick.cell_source_stage_xy_um,
                source_zwide_um=pick.tile_zwide_um,
                target_stage_xy_um=(tx, ty),
                target_zwide_um=tz,
                target_zoom=None,
                target_pixel_size_um=target_pixel_size_um,
                tif_path=tif_path,
                success=True,
                error=None,
            ))
            print(f"  ok  tz={tz:.1f}")

        except Exception as exc:
            records.append(TargetRecord(
                pick_id=pick.pick_id,
                cell_source_stage_xy_um=pick.cell_source_stage_xy_um,
                source_zwide_um=pick.tile_zwide_um,
                target_stage_xy_um=(tx, ty) if tx is not None else None,
                target_zwide_um=tz,
                target_zoom=None,
                target_pixel_size_um=target_pixel_size_um,
                tif_path=tif_path,
                success=False,
                error=str(exc),
                failure_stage=stage,
            ))
            print(f"  FAIL@{stage} ({exc})")

    ok = sum(1 for r in records if r.success)
    print(f"\n[step 5] Done: {ok}/{len(records)} targets acquired")

    try:
        drv.restore_template(client)
        print("[step 5] Template restored.")
    except Exception as exc:
        print(f"[step 5] WARNING: could not restore template: {exc}")

    return records

"""Step 5: acquire each pick at the high-magnification objective.

Switches the objective once at the start (via job selection -- the job
binds the objective), then for every pick: translates the source-objective
stage XY into the target frame using the calibration, moves, acquires,
saves. Failures are isolated per pick; one bad target does not abort the
run. Each result becomes a `TargetRecord` for the run summary.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import navigator_expert as drv
from navigator_expert.calibration.core import model as calib

from shared.output_layout import Naming

from ._acquire import acquire
from ._hijack import NonSimulatorFrameError, hijack_frame
from ._job_state import ensure_job_state
from ._log_capture import _logged
from ._mock_provider import build_target_provider
from ._saved import require_single_plane
from .context import Context, TargetState
from .overview import Pick, _validate_callback_flags
from .selection import Picks


@dataclass
class TargetRecord:
    pick_id: tuple[str, int, int, int]
    cell_source_stage_xy_um: tuple[float, float]
    source_zwide_um: float
    target_stage_xy_um: tuple[float, float] | None
    target_zwide_um: float | None
    target_pixel_size_um: float | None
    tif_path: Path | None
    success: bool
    error: str | None
    failure_stage: str | None = None
    # Flat tile index ("Position N") of the SOURCE overview tile this
    # target came from -- the overview-scan file index p, NOT the
    # target-acquisition index.
    source_tile_position: int | None = None
    # Per-record provenance. simulated=True means this target's saved
    # .ome.tiff carries mock pixels under the LAS X simulator's OME
    # envelope; mock_image_source names the provider. Default
    # False/None means the target came from acquired microscope data.
    simulated: bool = False
    mock_image_source: str | None = None


def _position_label(position) -> str:
    """'Position N' / 'Position unknown' for the Step 5 console.

    A one-line twin of pipeline.visualize._position_label -- target.py
    cannot import from visualize.py at module top (import cycle)."""
    return f"Position {position}" if position is not None else "Position unknown"


def _build_default_on_target_callback(
    ctx: Context,
    *,
    live_display: bool,
    save_png: bool,
    save_queue: object = None,
) -> Callable[[Pick, TargetRecord], None]:
    """Build the default per-target callback when the operator hasn't
    supplied an explicit on_target. display_target is imported LOCALLY
    here because pipeline.visualize imports TargetRecord at module top;
    hoisting this import reintroduces the cycle.

    The tile_cache that callers previously created in the notebook
    becomes an implementation detail of this callback.

    save_queue: optional _FigureSaveQueue. When provided, per-target
    savefig + plt.close run on the queue's worker thread so the
    acquisition loop returns immediately.
    """
    from .visualize import display_target

    analysis_dir = ctx.run.layout.analysis_dir("overview-scan")
    logs_dir = ctx.run.layout.logs_dir("target-acquisition") if save_png else None
    tile_cache: dict = {}

    def _on_target(pick: Pick, record: TargetRecord) -> None:
        display_target(
            pick,
            record,
            analysis_dir,
            logs_dir=logs_dir,
            tile_cache=tile_cache,
            live_display=live_display,
            save_png=save_png,
            _save_queue=save_queue,
        )

    return _on_target


@_logged("target-acquisition")
def acquire_targets(
    ctx: Context,
    picks: Picks,
    *,
    live_display: bool = True,
    save_png: bool = True,
    on_target: Callable[[Pick, TargetRecord], None] | None = None,
) -> list[TargetRecord]:
    """Step 5: switch objective, translate picks, acquire each target.

    Per-pick failure isolation: if translation, zoom, move, or acquire
    fails for one pick, it yields a TargetRecord with success=False,
    failure_stage set to the step that failed, and the loop continues.

    Display/save behavior mirrors run_overview:
      - live_display=True (default): render each target inline.
      - save_png=True (default): save each figure to
        ctx.run.layout.logs_dir("target-acquisition").
      - on_target (default None): explicit callback. Mutually exclusive
        with the two flags; passing on_target alongside live_display=True
        or save_png=True raises ValueError. To supply on_target, also
        pass live_display=False, save_png=False.
      - all three off: silent acquisition (no per-target rendering).
    """
    _validate_callback_flags(
        on_target,
        live_display,
        save_png,
        callback_param="on_target",
    )

    cfg = ctx.cfg
    client = ctx.client
    calibration = ctx.calibration

    # Reset target state for this run
    ts = TargetState()
    ctx.target_state = ts

    if not picks.items:
        # Hoisted above queue construction so the early return doesn't
        # orphan a _FigureSaveQueue without a matching shutdown.
        print("[step 5] No picks to acquire -- skipping target pass.")
        return []

    # Async PNG save queue. Owned here when we build the default callback
    # AND will save (save_png=True); see run_overview for the symmetric
    # construct + drain-on-return contract.
    save_queue = None
    if on_target is None and save_png:
        from ._save_queue import _FigureSaveQueue

        save_queue = _FigureSaveQueue(name="target-savefig")
    if on_target is None and (live_display or save_png):
        on_target = _build_default_on_target_callback(
            ctx,
            live_display=live_display,
            save_png=save_png,
            save_queue=save_queue,
        )

    ts.started = True

    try:
        try:
            # 5.1 -- switch to target job (LAS X handles the objective)
            ts.setup_stage = "select_job"
            ensure_job_state(ctx, cfg.target_job)

            # Read target z-galvo for telemetry.
            ts.setup_stage = "read_zgalvo"
            try:
                settings = drv.get_job_settings(client, cfg.target_job, mode="api")
                ch = drv.make_changeable_copy(settings)
                ts.post_switch_zgalvo_um = float(ch["zPosition"]["z-galvo"])
                ts.drift_um = ts.post_switch_zgalvo_um - ctx.source_zgalvo_um
                ts.drift_warning = abs(ts.drift_um) > 0.5
                if ts.drift_warning:
                    print(
                        f"[step 5] WARNING: z-galvo drift = "
                        f"{ts.drift_um:+.3f} um "
                        f"(source={ctx.source_zgalvo_um:+.3f}, "
                        f"target={ts.post_switch_zgalvo_um:+.3f})"
                    )
            except Exception as exc:
                ts.zgalvo_read_error = str(exc)
                print(f"[step 5] WARNING: could not read target z-galvo: {exc}")

            ts.setup_stage = None  # setup complete

        except Exception as exc:
            ts.setup_error = str(exc)
            raise

        # 5.3 -- sort picks by source XY (deterministic order)
        sorted_picks = sorted(
            picks.items,
            key=lambda p: (p.cell_source_stage_xy_um[0], p.cell_source_stage_xy_um[1]),
        )

        print(f"[step 5] {len(sorted_picks)} picks to acquire at slot {ctx.target_slot}")

        records: list[TargetRecord] = []

        for i, pick in enumerate(sorted_picks):
            rid, _, _, label = pick.pick_id
            print(
                f"[{i + 1}/{len(sorted_picks)}] "
                f"Group {rid}, {_position_label(pick.position)}, "
                f"label {label}  "
                f"src=({pick.cell_source_stage_xy_um[0]:.0f}, "
                f"{pick.cell_source_stage_xy_um[1]:.0f})",
                end="",
                flush=True,
            )

            # Track partial state so failures preserve what succeeded
            tx = ty = tz = None
            target_pixel_size_um = None
            tif_path = None
            stage = "translate"

            try:
                tx, ty, tz = calib.translate_xyz_between_objectives(
                    pick.cell_source_stage_xy_um[0],
                    pick.cell_source_stage_xy_um[1],
                    pick.tile_zwide_um,
                    calibration,
                    from_slot=ctx.source_slot,
                    to_slot=ctx.target_slot,
                )

                stage = "geometry"
                target_settings = drv.get_job_settings(
                    client,
                    cfg.target_job,
                    mode="api",
                )
                target_geo = drv.parse_tile_geometry(target_settings)
                target_pixel_size_um = float(target_geo["pixel_w_um"])

                stage = "acquire"
                acquire(ctx, cfg.target_job, tx, ty, tz)
                rid, row, col, label = pick.pick_id
                naming = Naming(
                    acquisition_type="target-acquisition",
                    hash6=ctx.run.layout.hash6,
                    g=int(rid),
                    p=i,
                )
                lineage = {
                    "source_tile_rid": rid,
                    "source_tile_position": pick.position,
                    "row": row,
                    "col": col,
                    "label": label,
                    "cell_source_stage_xy_um": list(pick.cell_source_stage_xy_um),
                }
                acq = drv.acquire(ctx.client, cfg.target_job)
                result = drv.save(
                    ctx.client,
                    acq,
                    ctx.run.layout.run_dir,
                    naming,
                    lineage=lineage,
                )
                plane = require_single_plane(result, context="target-acquisition")
                tif_path = plane.image_path
                stage = "save"

                if cfg.simulate:
                    # NonSimulatorFrameError propagates past the per-pick
                    # `except Exception` below (we re-raise it
                    # explicitly there) so the run hard-aborts -- a
                    # real-hardware frame must never be silently logged
                    # as a per-pick failure.
                    stage = "hijack"
                    # Per-pick provider -- closes over this pick's
                    # centroid + source-tile lineage so the high-res
                    # mock is a zoom of *that pick's* cell from the
                    # overview file. See _mock_provider.build_target_provider.
                    target_provider = build_target_provider(
                        pick=pick,
                        target_pixel_size_um=target_pixel_size_um,
                        layout=ctx.run.layout,
                    )
                    hijack_frame(
                        plane,
                        kind="target-acquisition",
                        layout=ctx.run.layout,
                        provider=target_provider,
                    )
                    stage = "save"  # hijack complete; back to terminal

                rec = TargetRecord(
                    pick_id=pick.pick_id,
                    cell_source_stage_xy_um=pick.cell_source_stage_xy_um,
                    source_zwide_um=pick.tile_zwide_um,
                    target_stage_xy_um=(tx, ty),
                    target_zwide_um=tz,
                    target_pixel_size_um=target_pixel_size_um,
                    tif_path=tif_path,
                    success=True,
                    error=None,
                    source_tile_position=pick.position,
                    simulated=cfg.simulate,
                    mock_image_source=cfg.mock_image_source,
                )
                records.append(rec)
                print(f"  ok  tz={tz:.1f}")

                if on_target is not None:
                    try:
                        on_target(pick, rec)
                    except Exception as exc:
                        print(f"  [viz] WARNING: on_target failed: {exc}")

            except NonSimulatorFrameError:
                # Run-fatal: re-raise past the broad except below and
                # past the outer finally so the caller sees the
                # simulator-mismatch and the run hard-aborts mid-list.
                raise
            except Exception as exc:
                records.append(
                    TargetRecord(
                        pick_id=pick.pick_id,
                        cell_source_stage_xy_um=pick.cell_source_stage_xy_um,
                        source_zwide_um=pick.tile_zwide_um,
                        target_stage_xy_um=(tx, ty) if tx is not None else None,
                        target_zwide_um=tz,
                        target_pixel_size_um=target_pixel_size_um,
                        # A hijack failure means the .ome.tiff was saved
                        # but its pixels were NOT replaced with mock content.
                        # Hide the path so downstream consumers don't pick
                        # up the simulator-content file as if it were a
                        # successful (mock) acquisition.
                        tif_path=None if stage == "hijack" else tif_path,
                        success=False,
                        error=str(exc),
                        failure_stage=stage,
                        source_tile_position=pick.position,
                        simulated=cfg.simulate,
                        mock_image_source=cfg.mock_image_source,
                    )
                )
                print(f"  FAIL@{stage} ({exc})")

        ok = sum(1 for r in records if r.success)
        print(f"\n[step 5] Done: {ok}/{len(records)} targets acquired")
    finally:
        # Drain async per-target savefig queue (if owned by this run).
        if save_queue is not None:
            save_queue.shutdown()

    return records

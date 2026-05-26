"""overview.py -- Step 4: overview acquisition with live analysis.

Snake-ordered tile acquisition with per-tile engine submission,
opportunistic + blocking drain, NPZ persistence (schema v2). Selection
moves to selection.py in Commit C.

Public entry points:
  - run_overview(ctx, focus_map) -- returns OverviewResult (picks + failure
    lists + tile_cell_counts + acquire-loop counters + completion sentinel).
  - Selection now lives in workflow.selection (select_targets + load_overview_result).
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np

import navigator_expert.driver as drv

from .context import Context
from .focus import FocusMap
from shared.output_layout import Naming, build_position_analysis_name
from ._acquire import acquire
from ._job_state import ensure_job_state
from ._logcapture import _logged
from ._hijack import hijack_frame, NonSimulatorFrameError
from ._mockprovider import get_provider


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

    # Flat tile index ("Position N") of this pick's overview tile --
    # the overview-scan file index p (= naming_p). None only when the
    # pick is reconstructed from a pre-`position` NPZ.
    position: int | None = None


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


@dataclass
class OverviewResult:
    all_picks: list[Pick]
    tile_acquire_failures: list[dict]
    engine_failures: list[dict]
    npz_save_failures: list[dict]
    tile_cell_counts: dict[tuple[str, int, int], int]
    n_tiles_planned: int
    n_tiles_submitted: int
    completed: bool

    # Plan 2 -- stored counters (not derived). A tile can now be
    # acquired-but-not-hijacked-not-submitted, so the prior derived
    # n_tiles_acquired = submitted - acquire_failed breaks. These all
    # default to 0 / [] for back-compat; run_overview /
    # load_overview_result populate them.
    n_tiles_acquired: int = 0
    n_tiles_hijacked: int = 0
    hijack_failures: list[dict] = field(default_factory=list)

    # True when the run executed in simulation mode (cfg.simulate); the
    # canonical .ome.tiffs in data/ then carry mock pixels under their
    # real LAS-X-simulator OME envelopes.
    simulated: bool = False
    mock_image_source: str | None = None

    @property
    def n_tiles(self) -> int:
        # Successfully drained AND saved tiles (= v2 NPZ files written).
        # Excludes acquire/engine/save failures. NOT for summary.overview.*
        # counters — use n_tiles_acquired / n_tiles_submitted instead.
        return len(self.tile_cell_counts)

    @property
    def n_tiles_empty(self) -> int:
        return sum(1 for n in self.tile_cell_counts.values() if n == 0)


@dataclass(frozen=True)
class TileEvent:
    """Per-tile data passed to on_tile callbacks during live visualization.

    `n_cells` is the cellpose-detected cell count for this tile, computed
    once from `masks.max()` so the callback doesn't have to. Selection
    no longer happens during overview (it ships in Commit C as a separate
    step), so this replaces the rev6 `picked_labels` tuple.
    """
    image_2d: np.ndarray
    masks: np.ndarray
    tile_id: tuple[str, int, int]
    n_cells: int
    # Flat tile index ("Position N") -- the overview-scan file index p
    # (= naming_p). None only on a pre-`position` reload.
    position: int | None = None
    # Plan 2 -- True when the saved .ome.tiff's pixels were hijacked
    # with mock content (cfg.simulate). The "(mock)" figure prefix
    # reads this. Single source of truth for the dry-run mode; the
    # earlier `analysis_image_source` field was removed when the
    # engine-side mock branch was deleted (Plan 2 §6 / D1).
    simulated: bool = False
    mock_image_source: str | None = None


# ─── Public API ───────────────────────────────────────────────────


def _validate_callback_flags(
    callback: Any,
    live_display: bool,
    save_png: bool,
    *,
    callback_param: str,
) -> None:
    """Mutex: explicit per-event callback vs default-flag-driven rendering.

    Shared by run_overview (callback_param="on_tile") and acquire_targets
    (callback_param="on_target"). Raises ValueError when the caller
    supplies an explicit callback alongside live_display=True or
    save_png=True; the two paths are intentionally exclusive.
    """
    if callback is not None and (live_display or save_png):
        raise ValueError(
            f"Cannot pass {callback_param} together with live_display=True "
            f"or save_png=True. The default per-event rendering and an "
            f"explicit {callback_param} are mutually exclusive. To use "
            f"{callback_param}, also pass live_display=False, save_png=False; "
            f"to use defaults, drop {callback_param}."
        )


def _build_default_on_tile_callback(
    ctx: Context,
    *,
    live_display: bool,
    save_png: bool,
    save_queue: Any = None,
) -> Callable[[TileEvent], None]:
    """Build the default per-tile callback when the operator hasn't
    supplied an explicit on_tile. The renderer (display_tile) lives in
    workflow.visualize, which imports TileEvent from this module -- so
    overview.py imports display_tile LOCALLY here, not at module top.
    Hoisting this import to module top reintroduces the cycle.

    save_queue: optional _FigureSaveQueue threaded through to display_tile.
    When provided, the per-tile savefig runs on the queue's worker thread
    so the producer (acquisition loop) returns immediately.
    """
    from .visualize import display_tile

    logs_dir = (
        ctx.run.layout.logs_dir("overview-scan") if save_png else None
    )
    hash6 = ctx.run.layout.hash6
    scan_field = ctx.scan_field
    boundary_limits = ctx.boundary_limits

    def _on_tile(event: TileEvent) -> None:
        display_tile(
            event,
            scan_field=scan_field,
            boundary_limits=boundary_limits,
            logs_dir=logs_dir,
            live_display=live_display,
            save_png=save_png,
            hash6=hash6,
            _save_queue=save_queue,
        )

    return _on_tile


@_logged("overview-scan")
def run_overview(
    ctx: Context,
    focus_map: FocusMap,
    *,
    live_display: bool = True,
    save_png: bool = True,
    on_tile: Callable[[TileEvent], None] | None = None,
) -> OverviewResult:
    """Step 4: acquire tiles, submit to engine, drain, persist. NO selection.

    Per drained result: build per-tile Pick objects via _picks_from_result;
    save NPZ schema v2 via _save_single_tile_analysis(extra_arrays=...);
    fire on_tile. Only when the save returns True is the tile added to
    all_picks AND tile_cell_counts; otherwise the tile is recorded in
    npz_save_failures. This guarantees:
        same-kernel OverviewResult == load_overview_result(analysis_dir)
    after run_overview returns.

    At end of drain (before return) _write_overview_meta persists failure
    lists + n_tiles_planned + n_tiles_submitted + completion sentinel.
    If run_overview raises mid-drain, meta is still written from the
    finally block but with completed=False.

    Display/save behavior:
      - live_display=True (default): render each tile inline.
      - save_png=True (default): save each tile figure to
        ctx.run.layout.logs_dir("overview-scan").
      - on_tile (default None): explicit per-tile callback. Mutually
        exclusive with the two flags above -- supplying on_tile alongside
        live_display=True or save_png=True raises ValueError. To use an
        explicit callback, also pass live_display=False, save_png=False.
      - all three off: silent acquisition (no per-tile rendering or save).
    """
    _validate_callback_flags(
        on_tile, live_display, save_png, callback_param="on_tile",
    )
    # Async PNG save queue. Owned by run_overview when we build the
    # default callback AND will save (save_png=True). Otherwise None
    # (sync savefig on the producer thread, or no save at all).
    save_queue = None
    if on_tile is None and save_png:
        from ._save_queue import _FigureSaveQueue
        save_queue = _FigureSaveQueue(name="overview-savefig")
    if on_tile is None and (live_display or save_png):
        on_tile = _build_default_on_tile_callback(
            ctx,
            live_display=live_display,
            save_png=save_png,
            save_queue=save_queue,
        )

    cfg = ctx.cfg
    client = ctx.client
    engine = ctx.engine

    tile_positions = ctx.scan_field["tile_positions"]

    all_picks: list[Pick] = []
    tile_acquire_failures: list[dict] = []
    npz_save_failures: list[dict] = []
    tile_cell_counts: dict[tuple[str, int, int], int] = {}
    new_failures: list[dict] = []
    n_tiles_planned = 0
    n_tiles_submitted = 0
    n_tiles_acquired = 0
    n_tiles_hijacked = 0
    hijack_failures: list[dict] = []
    n_results = 0
    completed = False

    # Plan 2 simulation mode. provider is None for a real run; set to a
    # mock-image callable when cfg.simulate, with the per-frame
    # NonSimulatorFrameError allowlist enforced by hijack_frame().
    provider = get_provider(cfg.mock_image_source) if cfg.simulate else None

    analysis_dir = ctx.run.layout.analysis_dir("overview-scan")

    try:
        ensure_job_state(ctx, cfg.acquisition_job)

        settings = drv.get_job_settings(client, cfg.acquisition_job)
        geo = drv.parse_tile_geometry(settings)
        pixel_size_um = (float(geo["pixel_w_um"]), float(geo["pixel_h_um"]))
        image_size_px = (int(geo["pixels_x"]), int(geo["pixels_y"]))

        sequence = _build_snake_sequence(tile_positions)
        n_tiles_planned = len(sequence)
        print(f"[step 3] {n_tiles_planned} tiles in snake order")

        failure_count_before = len(
            engine.status("overview").get("failures", [])
        )

        analysis_dir_ready = False
        try:
            analysis_dir.mkdir(parents=True, exist_ok=True)
            analysis_dir_ready = True
        except Exception as exc:
            print(f"[step 3] WARNING: could not create {analysis_dir}: {exc}")

        for i, tile in enumerate(sequence):
            rid = tile["region"]
            x_um = tile["x_um"]
            y_um = tile["y_um"]
            zwide_um = float(focus_map.interpolate_zwide(x_um, y_um))
            tile_id = (str(rid), tile["row"], tile["col"])

            print(
                f"[{i + 1}/{n_tiles_planned}] "
                f"Group {rid}, Position {i}  "
                f"x={x_um:.0f} y={y_um:.0f} z={zwide_um:.2f}",
                end="", flush=True,
            )

            try:
                tx, ty, tz = drv.translate_xyz_between_objectives(
                    x_um, y_um, zwide_um, ctx.calibration,
                    from_slot=ctx.source_slot,
                    to_slot=ctx.source_slot,
                )
                acquire(ctx, cfg.acquisition_job, tx, ty, tz)
                naming = Naming(
                    acquisition_type="overview-scan",
                    hash6=ctx.run.layout.hash6,
                    g=int(rid), p=i,
                )
                result = drv.acquire_and_save(
                    ctx.client, ctx.run, cfg.acquisition_job, naming,
                )
                n_tiles_acquired += 1

                if cfg.simulate:
                    try:
                        hijack_frame(
                            result, kind="overview-scan",
                            layout=ctx.run.layout, provider=provider,
                        )
                        n_tiles_hijacked += 1
                    except NonSimulatorFrameError:
                        # Run-fatal: re-raise past the broad except
                        # below so the loop hard-aborts on the very
                        # first non-simulator frame instead of silently
                        # logging a tile failure and continuing onto
                        # more real-hardware frames.
                        raise
                    except Exception as exc:
                        hijack_failures.append({
                            "tile_id": tile_id, "error": str(exc),
                        })
                        print(f"  HIJACK-FAIL ({exc})")
                        continue

                engine.submit("overview", {
                    "image_path": str(result.image_path),
                    "tile_id": tile_id,
                    "naming_p": i,
                    "tile_stage_xy_um": (x_um, y_um),
                    "tile_zwide_um": zwide_um,
                    "source_pixel_size_um": pixel_size_um,
                    "source_image_size_px": image_size_px,
                    "image_to_stage": ctx.calibration["image_to_stage"],
                    "n_picks": None,
                    "feature": "area",
                    # Engine-ignored provenance keys -- they reach
                    # _fire_on_tile and _save_single_tile_analysis via
                    # result["input"]. The engine itself reads only
                    # image_path (D1: no per-source branch); a simulate
                    # run hijacked image_path's content above, so a
                    # plain file read gives the engine the mock pixels.
                    "simulated": cfg.simulate,
                    "mock_image_source": cfg.mock_image_source,
                })
                n_tiles_submitted += 1
                print(f"  ok")
            except NonSimulatorFrameError:
                # Announced inside the inner try; re-raise here so the
                # outer finally writes meta with completed=False and
                # the exception surfaces to the caller (run-fatal).
                raise
            except Exception as exc:
                tile_acquire_failures.append({
                    "tile_id": tile_id, "error": str(exc),
                })
                print(f"  FAIL ({exc})")
                continue

            # Opportunistic drain
            for r in engine.results("overview"):
                _process_drained_result(
                    r, ctx, analysis_dir, analysis_dir_ready,
                    all_picks, tile_cell_counts, npz_save_failures,
                    on_tile,
                )
                n_results += 1

        # Blocking drain
        s = None
        while True:
            s = engine.status("overview")
            for r in engine.results("overview"):
                _process_drained_result(
                    r, ctx, analysis_dir, analysis_dir_ready,
                    all_picks, tile_cell_counts, npz_save_failures,
                    on_tile,
                )
                n_results += 1
            if s["pending"] == 0 and s["running"] == 0:
                break
            time.sleep(0.05)

        new_failures = s.get("failures", [])[failure_count_before:]

        assert n_results + len(new_failures) == n_tiles_submitted, (
            f"Drain mismatch: {n_results} results + {len(new_failures)} "
            f"failures != {n_tiles_submitted} submitted"
        )

        print(
            f"\n[step 3] Drain complete: {n_results} result(s), "
            f"{len(new_failures)} engine failure(s), "
            f"{len(tile_acquire_failures)} tile acquire failure(s), "
            f"{len(npz_save_failures)} npz save failure(s). "
            f"{len(tile_cell_counts)} tile(s) persisted."
        )

        completed = True
    finally:
        # Persist meta even when the drain raised, so load_overview_result
        # can show partial state. completed=False signals the incompleteness.
        try:
            _write_overview_meta(
                analysis_dir,
                n_tiles_planned=n_tiles_planned,
                n_tiles_submitted=n_tiles_submitted,
                n_tiles_acquired=n_tiles_acquired,
                n_tiles_hijacked=n_tiles_hijacked,
                tile_acquire_failures=tile_acquire_failures,
                engine_failures=new_failures,
                npz_save_failures=npz_save_failures,
                hijack_failures=hijack_failures,
                completed=completed,
                simulated=cfg.simulate,
                mock_image_source=cfg.mock_image_source,
            )
        except Exception as exc:
            print(f"[step 3] WARNING: could not write overview_meta.json: {exc}")

        # Drain async per-tile savefig queue (if owned by this run).
        # The queue holds figure references; shutdown drains + closes the
        # worker so all PNGs promised by call-return exist on disk.
        if save_queue is not None:
            save_queue.shutdown()

    return OverviewResult(
        all_picks=all_picks,
        tile_acquire_failures=tile_acquire_failures,
        engine_failures=new_failures,
        npz_save_failures=npz_save_failures,
        tile_cell_counts=tile_cell_counts,
        n_tiles_planned=n_tiles_planned,
        n_tiles_submitted=n_tiles_submitted,
        completed=completed,
        n_tiles_acquired=n_tiles_acquired,
        n_tiles_hijacked=n_tiles_hijacked,
        hijack_failures=hijack_failures,
        simulated=cfg.simulate,
        mock_image_source=cfg.mock_image_source,
    )


# load_overview_result lives in selection.py (re-homed in Commit C so the
# notebook imports it from where the consumer lives).


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


def _picks_from_result(result: dict) -> list[Pick]:
    """Extract Pick objects from ONE engine result dict (per-tile).

    NOT an aggregate over all tiles -- the per-tile NPZ blocks use this
    to avoid the name collision with OverviewResult.all_picks.
    """
    picks: list[Pick] = []
    pick_data = result.get("pick_targets", {}).get("picks", [])
    position = result.get("input", {}).get("naming_p")
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
            position=position,
        ))
    return picks


def _process_drained_result(
    result: dict,
    ctx: Context,
    analysis_dir: Path,
    analysis_dir_ready: bool,
    all_picks: list[Pick],
    tile_cell_counts: dict[tuple[str, int, int], int],
    npz_save_failures: list[dict],
    on_tile: Callable[[TileEvent], None] | None,
) -> None:
    """Handle one drained engine result.

    Save-failure invariant: only when _save_single_tile_analysis returns
    True does the tile contribute to all_picks AND tile_cell_counts. On
    False (any cause -- _save_single_tile_analysis catches its own
    exceptions and returns False, never raises), the tile is recorded in
    npz_save_failures and excluded from the aggregates. on_tile fires
    regardless so live display still works.
    """
    tile_picks = _picks_from_result(result)
    tile_id_raw = result.get("input", {}).get("tile_id")

    if tile_id_raw is None:
        # No tile_id => nothing we can save or attribute to a tile.
        # Still fire the callback for parity with the old behavior.
        _fire_on_tile(on_tile, result)
        return

    tile_id = (str(tile_id_raw[0]), int(tile_id_raw[1]), int(tile_id_raw[2]))

    if analysis_dir_ready:
        extra_arrays = _build_npz_extra_arrays(tile_picks)
        if _save_single_tile_analysis(
            result, analysis_dir,
            hash6=ctx.run.layout.hash6,
            acquisition_type="overview-scan",
            extra_arrays=extra_arrays,
        ):
            tile_cell_counts[tile_id] = len(tile_picks)
            all_picks.extend(tile_picks)
        else:
            npz_save_failures.append({
                "tile_id": list(tile_id),
                "reason": "save_returned_false",
            })
    else:
        # Without a writable analysis_dir there's nowhere to persist —
        # record as save failure to preserve the same-kernel==restart
        # invariant (load_overview_result would see no NPZ either).
        npz_save_failures.append({
            "tile_id": list(tile_id),
            "reason": "analysis_dir_unavailable",
        })

    _fire_on_tile(on_tile, result)


def _array_from_field(
    values: list, *, shape_suffix: tuple = (), dtype=np.float64,
) -> np.ndarray:
    """Construct array preserving per-element shape even when values is empty.

    np.array([]) gives shape (0,) regardless of intended shape.
    For empty tiles, we need (0, K) for K-tuple fields and (0,) for scalars,
    so the loader can index uniformly via data[key][i].
    """
    if not values:
        return np.empty((0, *shape_suffix), dtype=dtype)
    return np.array(values, dtype=dtype)


def _build_npz_extra_arrays(tile_picks: list[Pick]) -> dict[str, Any]:
    """NPZ schema v2 extra_arrays for ONE tile (per-tile, NOT aggregate).

    Writing OverviewResult.all_picks here would inflate every tile's NPZ
    to O(total cells) and corrupt tile_cell_counts on load.

    Parallel arrays indexed by cell within this tile:
      cell_labels[i] <-> cell_area_px[i] <-> pick_bbox_px[i] <-> ...
    Tuple Pick fields -> 2D arrays: (N, 2) xy-pairs, (N, 4) bbox.
    Empty tiles produce (0, K) arrays via _array_from_field, not (0,).
    """
    return {
        "schema_version": np.int32(2),

        # Cell-level metrics (scatter plot)
        "cell_labels": _array_from_field(
            [p.pick_id[3] for p in tile_picks], dtype=np.int32),
        "cell_area_px": _array_from_field(
            [p.area_px for p in tile_picks], dtype=np.int32),
        "cell_mean_intensity": _array_from_field(
            [p.mean_intensity for p in tile_picks], dtype=np.float64),

        # Full Pick reconstruction
        "pick_tile_stage_xy_um": _array_from_field(
            [p.tile_stage_xy_um for p in tile_picks],
            shape_suffix=(2,), dtype=np.float64),
        "pick_tile_zwide_um": _array_from_field(
            [p.tile_zwide_um for p in tile_picks], dtype=np.float64),
        "pick_source_pixel_size_um": _array_from_field(
            [p.source_pixel_size_um for p in tile_picks],
            shape_suffix=(2,), dtype=np.float64),
        "pick_source_image_size_px": _array_from_field(
            [p.source_image_size_px for p in tile_picks],
            shape_suffix=(2,), dtype=np.int32),
        "pick_centroid_col_row_px": _array_from_field(
            [p.centroid_col_row_px for p in tile_picks],
            shape_suffix=(2,), dtype=np.float64),
        "pick_bbox_px": _array_from_field(
            [p.bbox_px for p in tile_picks],
            shape_suffix=(4,), dtype=np.int32),
        "pick_bbox_um": _array_from_field(
            [p.bbox_um for p in tile_picks],
            shape_suffix=(2,), dtype=np.float64),
        "pick_eccentricity": _array_from_field(
            [p.eccentricity for p in tile_picks], dtype=np.float64),
        "pick_cell_source_stage_xy_um": _array_from_field(
            [p.cell_source_stage_xy_um for p in tile_picks],
            shape_suffix=(2,), dtype=np.float64),
    }


def _write_overview_meta(
    analysis_dir: Path,
    *,
    n_tiles_planned: int,
    n_tiles_submitted: int,
    n_tiles_acquired: int = 0,
    n_tiles_hijacked: int = 0,
    tile_acquire_failures: list[dict],
    engine_failures: list[dict],
    npz_save_failures: list[dict],
    hijack_failures: list[dict] | None = None,
    completed: bool,
    simulated: bool = False,
    mock_image_source: str | None = None,
) -> None:
    """Persist failure lists + acquire-loop counters + completion sentinel.

    `tile_cell_counts` is NOT stored — it's reconstructed from the v2 NPZ
    files by load_overview_result. n_tiles_planned, n_tiles_submitted,
    n_tiles_acquired, n_tiles_hijacked cannot be recovered from disk
    after a kernel restart (no NPZ for planned-but-not-submitted or
    acquire-failed-or-hijack-failed tiles), so they live here.

    Plan 2: simulated / mock_image_source / n_tiles_hijacked /
    hijack_failures land in meta so a reload knows the run was a
    simulation hijack (the canonical .ome.tiff carries mock pixels but
    the OME envelope still says SIMULATOR).

    Ensures analysis_dir exists in case zero tiles succeeded.
    """
    analysis_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "schema_version": 2,
        "completed": completed,
        "n_tiles_planned": n_tiles_planned,
        "n_tiles_submitted": n_tiles_submitted,
        "n_tiles_acquired": n_tiles_acquired,
        "n_tiles_hijacked": n_tiles_hijacked,
        "tile_acquire_failures": tile_acquire_failures,
        "engine_failures": engine_failures,
        "npz_save_failures": npz_save_failures,
        "hijack_failures": hijack_failures or [],
        "simulated": simulated,
        "mock_image_source": mock_image_source,
    }
    (analysis_dir / "overview_meta.json").write_text(json.dumps(meta, indent=2))


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
    limits,                       # workflow.context.LimitsContext (imported lazily to avoid cycle)
) -> tuple[list[Pick], list[dict], list[dict], list[dict]]:
    """Filter picks whose target position falls outside stage limits (D6).

    Predicts target XY and Z via the translator (no hardware).
    Takes a LimitsContext rather than a full Context — selection.py
    constructs one via ctx.limits_context() so this function doesn't
    need the LAS X client / engine fields.
    """
    calibration = limits.calibration
    stage_cfg = limits.stage_config

    lim = limits.boundary_limits or {}
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
                from_slot=limits.source_slot,
                to_slot=limits.target_slot,
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


def _save_single_tile_analysis(
    result: dict,
    analysis_dir: Path,
    *,
    hash6: str,
    acquisition_type: str,
    extra_arrays: dict[str, Any] | None = None,
) -> bool:
    """Save one tile's analysis artifacts. Returns True if saved, False
    on any failure (catches its own exceptions). Callers branch on the
    bool — this function never raises."""
    try:
        inp = result.get("input", {})
        seg = result.get("segment_tile", {})

        masks = seg.get("masks")
        image_2d = seg.get("image_2d")
        tile_id = inp.get("tile_id")
        naming_p = inp.get("naming_p")

        if masks is None or image_2d is None or tile_id is None:
            tid = inp.get("tile_id", "?")
            missing = [k for k, v in [("masks", masks),
                       ("image_2d", image_2d), ("tile_id", tile_id)]
                       if v is None]
            print(f"[step 3] WARNING: missing {', '.join(missing)} "
                  f"for tile {tid}, skipping analysis save")
            return False

        if naming_p is None:
            print(f"[step 3] WARNING: missing naming_p for tile "
                  f"{tile_id}, skipping analysis save")
            return False

        rid = tile_id[0]
        naming = Naming(
            acquisition_type=acquisition_type,
            hash6=hash6,
            g=int(rid),
            p=int(naming_p),
        )
        dest = analysis_dir / build_position_analysis_name(naming)

        save_kwargs: dict[str, Any] = {
            "image_2d": image_2d,
            "masks": masks,
            "tile_id": np.array(tile_id, dtype=str),
            # Flat tile index ("Position N"). naming_p is guaranteed
            # non-None here -- the None check above returns False first.
            "position": np.int32(int(naming_p)),
            # Plan 2 -- True when the saved .ome.tiff's pixels were
            # hijacked with mock content. mock_image_source is the
            # provider name or "" when not simulating. _load_tile_npz
            # reads `simulated` directly; pre-Plan-2 NPZs lacking the
            # key are handled by a load-boundary back-compat branch
            # that derives `simulated` from the dropped
            # `analysis_image_source` key.
            "simulated": np.bool_(bool(inp.get("simulated", False))),
            "mock_image_source": np.array(
                inp.get("mock_image_source") or ""
            ),
        }
        if extra_arrays:
            # Invariant: cell_labels[i] <-> cell_area_px[i] <-> ...
            save_kwargs.update(extra_arrays)
        np.savez_compressed(dest, **save_kwargs)
        return True
    except Exception as exc:
        tid = result.get("input", {}).get("tile_id", "?")
        print(f"[step 3] WARNING: could not save tile analysis "
              f"for {tid}: {exc}")
        return False


def _save_tile_analysis(
    analysis_dir: Path,
    buffer: list[dict],
    *,
    hash6: str,
    acquisition_type: str,
) -> None:
    """Bulk wrapper for _save_single_tile_analysis (used by tests)."""
    if not buffer:
        return

    try:
        analysis_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        print(f"[step 3] WARNING: could not create {analysis_dir}: {exc}")
        return

    saved = sum(
        _save_single_tile_analysis(r, analysis_dir,
                                   hash6=hash6,
                                   acquisition_type=acquisition_type)
        for r in buffer
    )
    if saved:
        print(f"[step 3] Saved {saved} tile analysis artifact(s) to "
              f"{analysis_dir}")


def _fire_on_tile(
    on_tile: Callable[[TileEvent], None] | None,
    result: dict,
) -> None:
    """Call on_tile callback with fault isolation."""
    if on_tile is None:
        return

    inp = result.get("input", {})
    seg = result.get("segment_tile", {})
    masks = seg.get("masks")
    image_2d = seg.get("image_2d")
    tile_id = inp.get("tile_id")

    if masks is None or image_2d is None or tile_id is None:
        return

    try:
        n_cells = int(masks.max())
    except Exception:
        n_cells = 0

    try:
        on_tile(TileEvent(
            image_2d=image_2d,
            masks=masks,
            tile_id=tuple(tile_id),
            n_cells=n_cells,
            position=inp.get("naming_p"),
            simulated=bool(inp.get("simulated", False)),
            mock_image_source=inp.get("mock_image_source"),
        ))
    except Exception as exc:
        tid = tile_id
        print(f"[step 3] WARNING: on_tile callback failed for "
              f"{tid}: {exc}")

# Plan: Restructured smart_microscopy_v3 notebook — separate overview, selection, acquisition

**Status:** Ready to implement
**Branch:** `cleanup/wave-2`
**Plan revision:** rev7 (final, after 7 review rounds — data-model refactor: `OverviewResult` carries `tile_cell_counts`, `npz_save_failures`, and a `completed` sentinel; `select_targets` takes the full `overview` rather than `all_picks` + `n_tiles_attempted`; save-failure invariant pinned; corrupt-meta-tolerant loader; summary counter sources pinned)

---

## Context

The smart-microscopy v3 notebook currently bundles target selection into the
overview drain loop. A first attempt at this (commits `5174f67` through `842df33`
on `cleanup/wave-2`, six commits in sequence) integrated median-threshold + random
sampling into `_process_drained_result`, with a 5-panel live triptych during
overview. After review, two structural problems surfaced:

1. **Selection should be operator-inspectable before commitment**, not auto-applied
   during acquisition. The integrated version made the operator commit to picks
   without seeing the cell distribution.
2. **Per-tile median thresholds** in the integrated version were statistically noisy
   on sparse tiles. Global median (across all cells from all tiles) is meaningful
   and only computable after the overview completes.

This plan reverts the six integrated commits and rebuilds with:

- **Separate selection step** between Overview and Target Acquisition.
- **Global thresholds** (median across all cells in all tiles), with operator
  override.
- **Persistence** of all selection-relevant data per tile, so the workflow survives
  kernel restart between overview and selection.
- **No automatic random fallback when zero cells qualify** — operator sees
  the empty intersection in the scatter and adjusts.

The smart-analysis engine change (`n_picks=None` guard + `SUPPORTS_NONE_NPICKS`
flag in `pick_targets.py`) was deployed earlier and is **not reverted**. The
revert only affects smart-microscopy.

---

## Goals

After implementation, the operator runs the v3 notebook through these cells:

```
Init       — boot LAS X, connect, preflight, capability check
Setup (×3) — stage limits, scan field, focus map
Overview   — acquire tiles, segment, persist all cells. Live 2-panel per tile.
Selection  — interactive. Compute distribution, apply thresholds (auto or
             override), see scatter + 6 example crops, decide.
Acquisition — acquire selected targets at the target objective.
Finish     — summary, plot, finish.
```

Operator can:

- See segmentation results live during overview.
- Inspect the cell distribution before committing to picks.
- Override `area_threshold` and/or `intensity_threshold` independently.
- Re-run selection with different parameters without re-acquiring overview.
- Restart the kernel between overview and selection (picks are on disk).

---

## Background reading for a new agent

Before implementing, read:

1. **This file** — the plan.
2. **The branch state**:
   ```bash
   cd Z:/zmbstaff/10374/Protocols_Notes/thom/notes/repositories/smart-microscopy
   git log --oneline cleanup/wave-2 | head -20
   ```
   The HEAD should currently be at `842df33` (or whatever the latest fix
   commit is on `cleanup/wave-2`). The revert range is `a61244d..842df33`.
3. **Current code structure**:
   - `controller/vendor/leica/navigator_expert/notebooks/workflow/`
     - `overview.py` — Step 4 (overview acquisition + analysis)
     - `target.py` — Step 5 (high-mag target acquisition)
     - `visualize.py` — display helpers, called via on_tile/on_target callbacks
     - `context.py` — `Config`, `Context` dataclasses
     - `preflight.py` — Step 0 hardware/engine validation
     - `summary.py` — run_summary.json writer
     - `__init__.py` — public exports
   - `controller/vendor/_shared/output_layout/naming.py` — file naming + LayoutPlan
   - `controller/vendor/leica/navigator_expert/notebooks/smart_microscopy_v3.ipynb`
4. **The cross-repo dependency**:
   `Z:/zmbstaff/10374/Protocols_Notes/thom/notes/repositories/smart-analysis/workflows/target_acquisition/steps/pick_targets.py`
   has `SUPPORTS_NONE_NPICKS = True` and accepts `n_picks=None` (returns all cells
   sorted by label). Confirm before starting Commit A.
5. **Tests**:
   `controller/vendor/leica/navigator_expert/notebooks/workflow/test/`
   - `test_save_tile_analysis.py` (15 tests)
   - `test_visualize.py` (21 tests)
   - existing `TestFireOnTile` (4 tests) in test_save_tile_analysis.py
   - `controller/vendor/_shared/output_layout/test/test_naming.py` (54 tests)

   Pre-implementation test count after revert: **94** green.

---

## Constraints

- **Driver and calibration subsystems are off-limits.** All changes live in
  `notebooks/workflow/` and `notebooks/smart_microscopy_v3.ipynb`. Do not touch
  `controller/vendor/leica/navigator_expert/driver/` or `calibration/`.
- **smart-analysis is a different repo.** No edits to smart-analysis as part
  of this work; the engine change was deployed previously.
- **The branch has been through PR review** — use `git revert`, not
  `git reset --hard`. Force-push is not appropriate.
- **AppLocker:** smart-microscopy runs from `Z:` but development happens at
  `Z:/zmbstaff/.../smart-microscopy/`. Tests run via the env at
  `C:\ProgramData\MinicondaZMB\envs\lasxapi_extended\python.exe`.
- **Overview output directories are single-run artifacts.** Re-running overview
  into a populated `overview-scan/` directory is unsupported — clean the
  directory or use a fresh `experiment_hash6` between runs. `load_overview_result`
  trusts every v2 NPZ it finds, including stale ones from prior runs.

---

## Plan: revert + 3 sequential commits

Each commit leaves the workflow runnable.

```
revert    git revert -n a61244d..842df33  — undoes 1b/1c/2/3 + 2 fix commits
A         Config + engine submit + preflight + intermediate-state safety gate
B         NPZ schema v2 + drain restructuring + additive run_overview + compat wrapper
C         TileEvent + display + selection.py + notebook + summary schema
```

---

## Revert (preparation)

```bash
cd Z:/zmbstaff/10374/Protocols_Notes/thom/notes/repositories/smart-microscopy
git checkout cleanup/wave-2
git revert -n a61244d..842df33
git commit -m "revert: integrated threshold selection; rebuilding as separate step"
```

**Range semantics**: `a61244d..842df33` reverts every commit *after* `a61244d`
through `842df33` inclusive — six commits (1b, 1c, 2, 3, and two fix commits).

**Do not** use `5174f67..842df33` — that excludes `5174f67` (commit 1b)
and leaves it in the tree.

After revert: `pytest controller/vendor/leica/navigator_expert/notebooks/workflow/test/`
should report **94 tests green**.

---

## Commit A: Config + engine submit + preflight + intermediate-state safety gate

**Goal:** plumb `n_picks=None` end-to-end. No data-flow changes, no API changes.

### Changes

**`workflow/context.py`** — remove fields from `Config`:
```python
# REMOVE:
n_picks_per_tile: int          # was used by overview.py engine submit
feature: str = "area"          # was used by overview.py engine submit
```

**`workflow/overview.py`** — engine submit (around line 177):
```python
# BEFORE:
"n_picks": cfg.n_picks_per_tile,
"feature": cfg.feature,
# AFTER:
"n_picks": None,
"feature": "area",
```

**`workflow/preflight.py`** — after `sys.path.insert(0, str(analysis_repo))`:
```python
# Import path assumes analysis_repo is smart-analysis root with workflows/ at top level.
try:
    from workflows.target_acquisition.steps.pick_targets import SUPPORTS_NONE_NPICKS  # noqa: E402
    if not SUPPORTS_NONE_NPICKS:
        raise RuntimeError
except (ImportError, AttributeError, RuntimeError):
    raise RuntimeError(
        f"smart-analysis at {analysis_repo} does not support n_picks=None. "
        f"Update to the latest version."
    )
```

**`workflow/overview.py`** — `run_overview_with_picks` otherwise unchanged.
Existing `_collect_picks_from_results` produces a `Pick` for every engine cell.
Existing `_dedup_picks` and `_filter_out_of_limits` run on the full set.
This is over-permissive (many picks per tile) but functional.

Add intermediate-state warning at the end of `run_overview_with_picks`
(before `return`):
```python
import os
if len(surviving) > 50:
    print(
        f"[step 4] WARNING: {len(surviving)} picks selected. "
        f"This is commit-A intermediate state. Selection step ships in Commit C; "
        f"do NOT run Step 5 on production hardware."
    )
    if os.environ.get("SMART_MICROSCOPY_ALLOW_INTERMEDIATE_RUN") != "1":
        print(
            "[step 4] To run Step 5 anyway, set "
            "SMART_MICROSCOPY_ALLOW_INTERMEDIATE_RUN=1 in your environment."
        )
```

**`workflow/target.py`** — `acquire_targets` adds env-var gate at top of body:
```python
import os
if (len(picks.items) > 50
        and os.environ.get("SMART_MICROSCOPY_ALLOW_INTERMEDIATE_RUN") != "1"):
    raise RuntimeError(
        f"Refusing to acquire {len(picks.items)} targets — "
        f"intermediate-state safety check. "
        f"Set SMART_MICROSCOPY_ALLOW_INTERMEDIATE_RUN=1 to override."
    )
```

Both the warning and the gate are **removed in Commit C** when selection is
in place. They protect debug/bisect sessions that accidentally land on this
commit with hardware connected.

**`smart_microscopy_v3.ipynb`** — Config cell loses two fields:
```python
cfg = Config(
    acquisition_job="Overview",
    target_job="HiRes",
    af_job="AF Job",
    analysis_repo=Path(r"Z:\...\smart-analysis"),
    experiment="v3-test",
    analysis_image_source="acquired",
)
```

### References to update before commit

Run before committing:
```bash
git grep "n_picks_per_tile" -- ':!*.md'
git grep "cfg\.feature" -- ':!*.md'
```

Update any non-doc references found.

### Tests

- 94 existing pass (Config fixtures in test files: drop the two fields).
- **+1 new**: `test_preflight_capability_check_fails_on_old_engine`. Mock the
  import to either raise `ImportError` or return a module with
  `SUPPORTS_NONE_NPICKS = False`. Assert `RuntimeError` from preflight with
  `analysis_repo` path in the message.

**Total after Commit A: 95 tests.**

---

## Commit B: NPZ schema v2 + drain restructuring + additive `run_overview` + compat wrapper

**Goal:** persist all selection-relevant data. Add new `run_overview` API. Notebook
stays on the legacy API until Commit C migrates it.

### 1. `workflow/overview.py` — new function + dataclass

```python
from dataclasses import dataclass

@dataclass
class OverviewResult:
    all_picks: list[Pick]
    tile_acquire_failures: list[dict]
    engine_failures: list[dict]
    npz_save_failures: list[dict]            # NEW: tiles that drained but failed to persist
    tile_cell_counts: dict[tuple[str, int, int], int]
    n_tiles_planned: int                     # NEW: from scan_field at submit time
    n_tiles_submitted: int                   # NEW: tiles actually submitted to acquire
    completed: bool                          # NEW: True iff drain loop reached normal end and _write_overview_meta ran. Per-tile acquire/engine/NPZ-save failures may still be present — they're tracked separately in the failure lists.

    @property
    def n_tiles(self) -> int:
        # Successfully drained AND saved tiles (= v2 NPZ files written).
        # Excludes acquire failures, engine failures, and npz save failures.
        return len(self.tile_cell_counts)

    @property
    def n_tiles_empty(self) -> int:
        return sum(1 for n in self.tile_cell_counts.values() if n == 0)

    @property
    def n_tiles_acquired(self) -> int:
        # tiles submitted minus those that failed at acquire
        return self.n_tiles_submitted - len(self.tile_acquire_failures)


def run_overview(
    ctx: Context,
    focus_map: FocusMap,
    *,
    on_tile: Callable[[TileEvent], None] | None = None,
) -> OverviewResult:
    """Step 4: acquire tiles, segment, persist. NO selection, NO dedup, NO filter.

    Per-result drain processing:
      - Build Pick objects via _picks_from_result
      - Save npz with schema v2 (cell metrics + full Pick reconstruction arrays)
      - Record tile_cell_counts[tile_id] = n_cells (includes 0 for empty tiles)
      - Fire on_tile callback (TileEvent — 5 fields, unchanged from post-revert:
        image_2d, masks, tile_id, picked_labels, analysis_image_source.
        picked_labels reflects the full set of engine-returned cell labels for
        live display; renamed to n_cells in Commit C when selection moves out
        of overview.)
      - Accumulate Picks into all_picks

    At end of drain (before return): _write_overview_meta persists failure
    lists + acquire-loop counters (n_tiles_planned, n_tiles_submitted) +
    completion sentinel to overview_meta.json. tile_cell_counts is NOT
    persisted — it's reconstructed from the v2 NPZ files by
    load_overview_result. The acquire-loop counters MUST be persisted
    because they're not derivable from disk after kernel restart.

    **Save-failure invariant**: a tile contributes to all_picks AND
    tile_cell_counts only when _save_single_tile_analysis returns True.
    `_save_single_tile_analysis` catches its own exceptions and returns
    False on any failure (verified at overview.py:539,586-590 — it does
    NOT raise). The drain calls it and branches on the boolean:
        if not _save_single_tile_analysis(result, analysis_dir, ...):
            npz_save_failures.append({"tile_id": tile_id, "reason": "save_returned_false"})
            continue   # do NOT add to all_picks or tile_cell_counts
        all_picks.extend(tile_picks)
        tile_cell_counts[tile_id] = len(tile_picks)
    This guarantees:
        same-kernel OverviewResult == load_overview_result(analysis_dir)
    after run_overview returns. Without this invariant, in-kernel selection
    could see picks that restart-selection cannot.

    Returns OverviewResult with raw picks across all tiles. No dedup, no
    out-of-limits filter — selection step handles those.
    """
```

Internals:
- Per-result drain (opportunistic + blocking sections, same shape as current).
- Replace `buffer: list[dict]` with `n_results: int` counter — drain assert reads
  `n_results + len(new_failures) == n_submitted`. Engine results are processed
  per-result and not retained.
- Delete `_collect_picks_from_results`. Replace with `_picks_from_result(result)`
  (per-result Pick construction, same field mapping).

### 2. `workflow/overview.py` — compat wrapper (DEPRECATED, removed in C)

```python
def run_overview_with_picks(
    ctx: Context,
    focus_map: FocusMap,
    *,
    on_tile: Callable[[TileEvent], None] | None = None,
) -> Picks:
    """DEPRECATED: removed in Commit C. Use run_overview() + select_targets()."""
    result = run_overview(ctx, focus_map, on_tile=on_tile)

    # Legacy dedup+filter on all engine cells
    deduped, removed_dup = _dedup_picks(result.all_picks)
    final, removed_xy, removed_z, removed_xlat = _filter_out_of_limits(
        deduped, ctx,  # still takes ctx; LimitsContext migration is Commit C
    )

    return Picks(
        items=final,
        n_picks_raw=len(result.all_picks),
        n_picks_removed_duplicate=len(removed_dup),
        n_picks_out_of_limits_xy=len(removed_xy),
        n_picks_out_of_limits_z=len(removed_z),
        removed_picks=removed_dup + removed_xy + removed_z + removed_xlat,
        tile_acquire_failures=result.tile_acquire_failures,
        engine_failures=result.engine_failures,
    )
```

**The wrapper must populate every existing `Picks` field** so summary.py and
downstream callers don't break in Commit B's intermediate state. The wrapper
reads `result.all_picks`; `result.tile_cell_counts` is unused at this stage
(it becomes load-bearing in Commit C via `select_targets`).

### 3. NPZ schema v2 — shape-preserving empty handling

Helper (in `overview.py`):
```python
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
```

`_save_single_tile_analysis` accepts an `extra_arrays: dict | None = None` parameter
(it does not exist on the function at the post-revert point — add it). When
called from `run_overview` per-result, pass:

```python
# NPZ schema v2 (Commit B). Per-tile NPZ — `tile_picks` is the picks from
# ONE drained engine result, NOT OverviewResult.all_picks (the aggregate).
# Writing the aggregate into each tile NPZ would corrupt tile_cell_counts
# and inflate per-tile arrays to O(total cells).
#
# Parallel arrays indexed by cell within this tile:
#   cell_labels[i] <-> cell_area_px[i] <-> pick_bbox_px[i] <-> ...
# Tuple Pick fields -> 2D arrays: (N, 2) for xy-pairs, (N, 4) for bbox.
# Empty tiles produce (0, K) arrays via _array_from_field, not (0,).
# Shape invariants pinned by test_picks_roundtrip_through_npz.
tile_picks = _picks_from_result(result)   # picks for THIS tile only
extra_arrays = {
    "schema_version": np.int32(2),

    # Cell-level metrics (scatter plot)
    "cell_labels": _array_from_field(
        [p.pick_id[3] for p in tile_picks], dtype=np.int32),              # (N,)
    "cell_area_px": _array_from_field(
        [p.area_px for p in tile_picks], dtype=np.int32),                 # (N,)
    "cell_mean_intensity": _array_from_field(
        [p.mean_intensity for p in tile_picks], dtype=np.float64),        # (N,)

    # Full Pick reconstruction
    "pick_tile_stage_xy_um": _array_from_field(
        [p.tile_stage_xy_um for p in tile_picks],
        shape_suffix=(2,), dtype=np.float64),                             # (N, 2)
    "pick_tile_zwide_um": _array_from_field(
        [p.tile_zwide_um for p in tile_picks], dtype=np.float64),         # (N,)
    "pick_source_pixel_size_um": _array_from_field(
        [p.source_pixel_size_um for p in tile_picks],
        shape_suffix=(2,), dtype=np.float64),                             # (N, 2)
    "pick_source_image_size_px": _array_from_field(
        [p.source_image_size_px for p in tile_picks],
        shape_suffix=(2,), dtype=np.int32),                               # (N, 2)
    "pick_centroid_col_row_px": _array_from_field(
        [p.centroid_col_row_px for p in tile_picks],
        shape_suffix=(2,), dtype=np.float64),                             # (N, 2)
    "pick_bbox_px": _array_from_field(
        [p.bbox_px for p in tile_picks],
        shape_suffix=(4,), dtype=np.int32),                               # (N, 4)
    "pick_bbox_um": _array_from_field(
        [p.bbox_um for p in tile_picks],
        shape_suffix=(2,), dtype=np.float64),                             # (N, 2)
    "pick_eccentricity": _array_from_field(
        [p.eccentricity for p in tile_picks], dtype=np.float64),          # (N,)
    "pick_cell_source_stage_xy_um": _array_from_field(
        [p.cell_source_stage_xy_um for p in tile_picks],
        shape_suffix=(2,), dtype=np.float64),                             # (N, 2)
}
```

### 4. Failure-list persistence — `_write_overview_meta`

```python
import json

def _write_overview_meta(
    analysis_dir: Path,
    *,
    n_tiles_planned: int,
    n_tiles_submitted: int,
    tile_acquire_failures: list[dict],
    engine_failures: list[dict],
    npz_save_failures: list[dict],
    completed: bool,
) -> None:
    """Persist OverviewResult failure lists + acquire-loop counters +
    completion sentinel. tile_cell_counts is NOT stored — it's derivable
    from the v2 NPZ files on load. Called once at end of run_overview,
    before return.

    `n_tiles_planned` and `n_tiles_submitted` are persisted because they
    cannot be recovered from disk after a kernel restart: planned tiles
    that were never submitted leave no NPZ; tiles submitted but acquire-
    failed leave no NPZ either (only an entry in tile_acquire_failures).
    The summary writer needs these counters when the finish cell runs in
    a kernel that didn't run overview.

    `completed=True` iff run_overview reached normal end and wrote this
    file. If run_overview raises mid-drain, the meta is absent and
    load_overview_result warns + defaults `completed=False`.

    Ensures analysis_dir exists in case zero tiles succeeded (no NPZ would
    have been saved, so the npz-save path wouldn't have mkdir'd)."""
    analysis_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "schema_version": 2,                              # was 1 in earlier rev7
        "completed": completed,
        "n_tiles_planned": n_tiles_planned,
        "n_tiles_submitted": n_tiles_submitted,
        "tile_acquire_failures": tile_acquire_failures,
        "engine_failures": engine_failures,
        "npz_save_failures": npz_save_failures,
    }
    (analysis_dir / "overview_meta.json").write_text(json.dumps(meta, indent=2))
```

The meta JSON `schema_version` is bumped to 2 because the schema added two
required-for-summary fields. `load_overview_result` reads either schema —
missing `n_tiles_planned` / `n_tiles_submitted` default to `0` with a
warning (legacy meta from very early rev7 builds).

### 5. Loader — `load_overview_result` (public, no underscore)

Added in Commit B to `overview.py` temporarily. **Re-homed to `selection.py`
in Commit C** so the notebook imports it from where the consumer lives.

**Single-pass design**: opens each v2 NPZ once and extracts both Pick
reconstruction data and the per-tile cell count in the same loop. Two
callers (selection cell, finish cell) each pay one full disk pass.

```python
def load_overview_result(analysis_dir: Path) -> OverviewResult:
    """Reconstruct OverviewResult from disk. Kernel-restart safe.

    Single pass over v2 NPZ files: builds all_picks and tile_cell_counts.
    Empty tiles (cell_labels.shape[0] == 0) contribute a (tile_id, 0) entry
    to tile_cell_counts. Failure lists come from overview_meta.json if
    present, else default to []. Skips schema_version < 2 files with warning.
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
            "[load] WARNING: no overview_meta.json found; either zero tiles "
            "ran or the previous run_overview crashed before writing meta. "
            "Treating run as incomplete; failure lists default to []."
        )

    if not completed:
        print(
            f"[load] NOTE: overview run at {analysis_dir} is marked incomplete. "
            f"Selecting from {len(all_picks)} picks across "
            f"{len(tile_cell_counts)} tiles anyway — operator should verify."
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
```

`load_overview_picks` from earlier plan revisions is **deleted, not retained
as a compat helper**. `load_overview_result(...).all_picks` replaces every
call site.

### 6. Notebook is unchanged in Commit B

Step 4 cell still calls `run_overview_with_picks(...)` and gets a `Picks`.
Workflow functional throughout.

### Tests (Commit B)

- **+1** `test_run_overview_returns_overview_result` — type assertion.
- **+1** `test_run_overview_with_picks_wrapper_populates_all_picks_fields` —
  wrapper preserves every `Picks` field that existed pre-revert.
- **+1** `test_picks_roundtrip_through_npz` — single test with per-field
  shape AND value assertions:
  ```python
  with np.load(npz_path) as data:
      assert int(data["schema_version"]) == 2
      assert data["cell_labels"].shape == (n,)
      assert data["pick_tile_stage_xy_um"].shape == (n, 2)
      assert data["pick_bbox_px"].shape == (n, 4)
      assert data["pick_centroid_col_row_px"].shape == (n, 2)
      assert data["pick_source_image_size_px"].shape == (n, 2)
      assert data["pick_bbox_um"].shape == (n, 2)
      assert data["pick_cell_source_stage_xy_um"].shape == (n, 2)
      assert data["pick_source_pixel_size_um"].shape == (n, 2)
      assert data["pick_tile_zwide_um"].shape == (n,)
      assert data["pick_eccentricity"].shape == (n,)
      assert data["cell_area_px"].shape == (n,)
      assert data["cell_mean_intensity"].shape == (n,)
  reconstructed = load_overview_result(analysis_dir).all_picks
  for orig, loaded in zip(original_picks, reconstructed):
      assert orig.pick_id == loaded.pick_id
      assert orig.tile_stage_xy_um == loaded.tile_stage_xy_um
      assert orig.bbox_px == loaded.bbox_px
      # ... all 12 Pick fields
  ```
- **+1** `test_empty_tile_npz_has_correct_shapes` — save a tile with zero picks,
  assert `(0, 4)` for bbox arrays, `(0, 2)` for xy-pair arrays, `(0,)` for scalars.
- **+1** `test_load_overview_result_skips_old_schema` — write a mix of v1
  and v2 npz files, assert (a) only v2 picks returned, (b) v1 files do NOT
  contribute to `tile_cell_counts` (so `n_tiles` ignores them), (c) warning
  printed per skipped file.
- **+1** `test_overview_meta_persisted_and_loaded` — run `run_overview` with
  a stub engine producing 2 acquire failures, 1 engine failure, 1 save
  failure (mock `_save_single_tile_analysis` to **return False** on one
  tile — matching the function's actual contract; it does not raise), and
  3 successful tiles; assert `overview_meta.json` exists with all four
  failure-list fields and `completed: true`; round-trip via
  `load_overview_result` returns equivalent `OverviewResult` (all failure
  lists match; `n_tiles == 3`; `completed is True`; the save-failed tile is
  NOT in `tile_cell_counts` and its picks are NOT in `all_picks`).
- **+1** `test_overview_meta_corrupt_json_tolerated` — write a truncated
  `overview_meta.json` next to valid v2 NPZ files; `load_overview_result`
  warns, defaults failure lists to `[]`, sets `completed=False`, and still
  returns the picks/tile_cell_counts from the NPZ scan.
- **+1** `test_overview_meta_missing_marked_incomplete` — write v2 NPZ
  files but no `overview_meta.json`; `load_overview_result` warns,
  `completed=False`, picks/counts still loaded.
- **+1** `test_overview_meta_persists_acquire_loop_counters` — run
  `run_overview` against a stub with 10 planned, 8 submitted (2 skipped
  pre-submit), 1 acquire failure, 1 engine failure. Assert
  `overview_meta.json` contains `n_tiles_planned == 10` and
  `n_tiles_submitted == 8`. Round-trip via `load_overview_result` returns
  `overview.n_tiles_planned == 10`, `overview.n_tiles_submitted == 8`,
  `overview.n_tiles_acquired == 7` (property). Pins post-restart summary
  recoverability for #4 from rev7 review.
- **+1** `test_load_overview_result_populates_tile_cell_counts` — fixture of
  3 tiles with cell counts (5, 0, 12); assert `tile_cell_counts` has 3 keys
  with values `{tile_a: 5, tile_b: 0, tile_c: 12}`; assert `n_tiles == 3` and
  `n_tiles_empty == 1`. Pins single-pass behavior and empty-tile handling.

**Total after Commit B: 105 tests** (+3 over rev6 baseline for the new
corrupt-meta-tolerated, missing-meta-marked-incomplete, and
acquire-loop-counters-persisted tests — each covers a distinct rev7
robustness invariant).

---

## Commit C: TileEvent + display + selection.py + notebook + summary schema

**Goal:** the user-facing surface. Selection becomes a separate interactive step.

### 1. `workflow/overview.py`

**`TileEvent` change is a true 1-field rename, in place, no reorder.**
Post-revert `TileEvent` has 5 fields (verified at a61244d):
`(image_2d, masks, tile_id, picked_labels, analysis_image_source)`.

Commit C replaces `picked_labels: tuple[int, ...]` with `n_cells: int` at
the same position. Same 5-field shape, `analysis_image_source` stays last —
selection no longer happens during overview, so `picked_labels` is
meaningless. `n_cells` (derivable from `masks.max()`) carries the
operator-relevant info for live display.

```python
@dataclass(frozen=True)
class TileEvent:
    image_2d: np.ndarray
    masks: np.ndarray
    tile_id: tuple[str, int, int]
    n_cells: int                     # was picked_labels: tuple[int, ...]
    analysis_image_source: str
```

Update `_fire_on_tile` to compute `n_cells = int(masks.max())` and pass it.

**Delete:**
- `run_overview_with_picks` compat wrapper.
- The intermediate-state warning print in `run_overview`.
- The env-var safety gate in `acquire_targets` (no longer needed once
  selection is in place).

Change `_filter_out_of_limits` signature to take `LimitsContext` instead of
`Context`:
```python
def _filter_out_of_limits(
    picks: list[Pick],
    limits: LimitsContext,
) -> tuple[list[Pick], list[dict], list[dict], list[dict]]:
```

**Annotation correction**: at HEAD the function declares a 3-tuple return type
(`tuple[list[Pick], list[dict], list[dict]]`) but actually returns 4 lists
(adds `removed_translation`). The Commit C signature update corrects this
incidentally. **Intentional fix, not a quiet change.**

**Migration safety**: the only existing caller (post-drain in the deleted
compat wrapper) is removed in this same commit. Confirm via grep before
committing:
```bash
git grep "_filter_out_of_limits"  # expect: definition site + selection.py caller
```

### 2. `workflow/context.py` — add `LimitsContext`

```python
@dataclass(frozen=True)
class LimitsContext:
    calibration: dict
    stage_config: dict
    boundary_limits: dict | None
    source_slot: int
    target_slot: int


# On Context:
def limits_context(self) -> LimitsContext:
    return LimitsContext(
        calibration=self.calibration,
        stage_config=self.stage_config,
        boundary_limits=self.boundary_limits,
        source_slot=self.source_slot,
        target_slot=self.target_slot,
    )
```

### 3. `workflow/selection.py` (new module)

```python
"""Selection step: interactive target selection from overview results.

Operator runs select_targets(overview, ...) after overview, sees scatter +
6 example crops via display_selection(), adjusts thresholds and re-runs if
unhappy.

Thresholds: GLOBAL (median across all cells in all tiles). One mode per
selection (not per tile). Per-tile sparseness is reported as a descriptive
counter, not a mode.
"""
from __future__ import annotations

import hashlib
import json                                       # for load_overview_result meta read
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


# Re-home from overview.py (was placed there in Commit B). Same body.
def load_overview_result(analysis_dir: Path) -> OverviewResult:
    """Reconstruct OverviewResult from disk. Single-pass over v2 NPZ + meta."""
    ...


@dataclass
class SelectionResult:
    # Distribution data (for scatter plot)
    all_cells_area: np.ndarray          # (N,)
    all_cells_intensity: np.ndarray     # (N,)
    all_cells_labels: np.ndarray        # (N,) -- Pick.pick_id[3] values
    all_cells_tile_ids: list[tuple[str, int, int]]
    qualifying_mask: np.ndarray         # (N,) bool

    # Thresholds + provenance -- separate auto flags per axis
    area_threshold: float
    intensity_threshold: float
    area_threshold_auto: bool           # True if not overridden
    intensity_threshold_auto: bool
    seed_material: str
    mode: str                           # global selection mode

    # Per-stage accounting (global counts)
    n_total: int
    n_qualifying: int
    n_selected_pre_dedup: int
    n_removed_duplicate: int
    n_removed_out_of_limits_xy: int
    n_removed_out_of_limits_z: int
    n_removed_translation: int
    n_final: int

    # Per-tile descriptive counters (NOT modes)
    # Both come directly from overview.tile_cell_counts.values():
    #   n_tiles_below_sparse_cutoff = count where 0 < n < min_cells_for_threshold
    #   n_tiles_empty               = count where n == 0  (i.e. overview.n_tiles_empty)
    # Empty tiles are NOT counted as "below sparse cutoff" — that bucket is
    # specifically tiles with some cells but fewer than min_cells_for_threshold.
    n_tiles_below_sparse_cutoff: int    # 0 < cells_in_tile < min_cells_for_threshold
    n_tiles_empty: int                  # cells_in_tile == 0 (= overview.n_tiles_empty)

    # Final selection -- full Pick objects so display can read bbox/centroid
    selected_picks: list[Pick]

    @property
    def selected_pick_ids(self) -> list[tuple[str, int, int, int]]:
        return [p.pick_id for p in self.selected_picks]


def select_targets(
    overview: OverviewResult,
    limits: LimitsContext,
    *,
    n_per_tile: int = 4,
    area_threshold: float | None = None,
    intensity_threshold: float | None = None,
    min_cells_for_threshold: int = 10,
    seed: int | None = None,
) -> tuple[Picks, SelectionResult]:
    """Global-threshold selection. Mode is global, not per-tile.

    Takes the full OverviewResult — selection needs both all_picks and the
    per-tile cell counts (the latter carries empty-tile information that
    all_picks alone cannot express).

    NO_QUALIFYING returns zero picks (no random fallback). Operator
    sees the empty intersection in display_selection and adjusts thresholds.

    Implementation outline:
      1. all_picks = overview.all_picks
         tile_cell_counts = overview.tile_cell_counts
         (already populated by load_overview_result or run_overview)
      2. Compute per-tile descriptive counters from overview.tile_cell_counts
         (raw engine cell counts per tile, pre-threshold, pre-dedup):
         - n_tiles_below_sparse_cutoff = sum(
               1 for count in tile_cell_counts.values()
               if 0 < count < min_cells_for_threshold
           )
         - n_tiles_empty = overview.n_tiles_empty   # property on OverviewResult
      3. Determine global mode:
         - 0 cells in all_picks -> MODE_EMPTY
         - 0 < len(all_picks) < min_cells_for_threshold -> MODE_SPARSE
         - else: MODE_THRESHOLD (or MODE_NO_QUALIFYING after threshold check)
      4. Compute thresholds:
         - area_threshold_auto = area_threshold is None
         - intensity_threshold_auto = intensity_threshold is None
         - For auto, use np.median across all cells in all_picks.
         - For SPARSE/EMPTY, thresholds are nominal (0.0) but flagged auto.
      5. qualifying_mask = (area >= area_threshold) & (intensity >= intensity_threshold)
         Reclassify MODE_THRESHOLD -> MODE_NO_QUALIFYING if no cells qualify.
      6. Sampling (only THRESHOLD and SPARSE modes select picks):
         - Group qualifying picks by tile_id.
         - Per-tile: deterministic seed via hashlib.sha256.
           seed_str = seed if seed is not None else "auto"  # handles seed=0
           seed_material = f"{seed_str}_{rid}_{row}_{col}"
           rng_seed = int.from_bytes(
               hashlib.sha256(seed_material.encode()).digest()[:8], "big"
           )
           rng = np.random.default_rng(rng_seed)
           indices = rng.choice(len(tile_group),
                                size=min(n_per_tile, len(tile_group)),
                                replace=False)
         - Concatenate sampled picks across tiles -> pre_dedup.
         - For EMPTY and NO_QUALIFYING: selected_picks = [] (no sampling).
      7. Dedup + filter:
         deduped, removed_dup = _dedup_picks(pre_dedup)
         final, removed_xy, removed_z, removed_xlat = _filter_out_of_limits(
             deduped, limits)
      8. Build Picks(items=final, ...). tile_acquire_failures and
         engine_failures stay empty here -- they belong to overview, merged
         at summary time.
      9. Build SelectionResult with all counters (including
         n_tiles_below_sparse_cutoff and n_tiles_empty from step 2),
         selected_picks=final, flags.
    """
```

**Key semantics** (different from the reverted version):
- `MODE_NO_QUALIFYING` returns zero picks. **No random fallback.**
- One global mode per selection.
- `area_threshold_auto` and `intensity_threshold_auto` are independent.
- `seed if seed is not None else "auto"` (handles `seed=0` correctly).
- Per-tile sparseness is a descriptive counter, not a mode.
- `select_targets` takes `OverviewResult`, not loose `all_picks` — eliminates
  the `n_tiles_attempted` footgun and lets the function see empty tiles
  via `overview.tile_cell_counts`.

### 4. `workflow/visualize.py`

Simplify `display_tile` to 2-panel:
```python
def display_tile(event: TileEvent, *, feedback_dir: Path | None = None) -> None:
    """Live 2-panel during overview: grayscale | segmentation overlay.
    Title: tile_id + n_cells.
    """
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    ax1.imshow(event.image_2d, cmap="gray")
    ax1.set_title("Tile image")
    ax1.axis("off")
    _segmentation_overlay(ax2, event.image_2d, event.masks)
    ax2.set_title(f"Segmentation ({event.n_cells} cells)")
    ax2.axis("off")
    is_mock = event.analysis_image_source != "acquired"
    prefix = "(mock) " if is_mock else ""
    rid, row, col = event.tile_id
    fig.suptitle(f"{prefix}Tile R{rid} r{row}c{col} -- {event.n_cells} cells")
    # ... display + close + optional save ...
```

**No scan field panel in `display_tile`** — scan field renders once in the
Setup cell via existing `plot_scan_field`.

Add `display_selection`:
```python
def display_selection(
    selection: SelectionResult,
    analysis_dir: Path,
    *,
    feedback_dir: Path | None = None,
) -> None:
    """Row 1: scatter (intensity x, area y, threshold lines when applicable).
    Row 2: 6 example crops -- one largest per tile, up to 6 distinct tiles.
    """
```

Crop selection rule (operator UX — diversity over absolute size):
1. Group `selection.selected_picks` by `pick_id[:3]` (tile_id).
2. Within each tile group, sort by `area_px` descending.
3. Take the largest from each of up to 6 distinct tiles.
4. If fewer than 6 distinct tiles have picks: fill remaining slots from
   already-represented tiles (next-largest within each).
5. Load `image_2d` from each unique tile's npz (cache across crops in this call).
6. Crop via `pick.bbox_px`.

Scatter rendering:
- `MODE_THRESHOLD`: draw threshold lines (dashed red).
- `MODE_NO_QUALIFYING`: draw threshold lines + annotation "0 cells qualified — adjust thresholds".
- `MODE_SPARSE`: no threshold lines, annotation "Thresholds skipped (sparse sample)".
- `MODE_EMPTY`: placeholder "No cells detected".

Empty `selection.selected_picks`: scatter only (no row 2).

Old npz (schema v1, no `cell_labels`): render placeholder
"No cell metrics in this run."

### 5. `workflow/summary.py` — schema restructure (NOT purely additive)

**`write_summary` signature changes**: 4 args -> 6 args.

```python
# BEFORE:
def write_summary(ctx, focus_map, picks, records): ...

# AFTER:
def write_summary(ctx, focus_map, overview_result, picks, selection_result, records): ...
```

**`plot_results` signature unchanged**. Verify with `git grep "plot_results"` —
it reads `picks` and `records`, not selection internals.

**This is a structural change, not additive.** Pick-accounting fields move out
of `overview` (where the legacy flow put them) into a new `selection` section.
Some fields are also renamed or reshaped. Below is the actual post-revert
schema (verified at `summary.py` a61244d) with explicit preserve / modify /
move / new annotations.

**Post-revert schema (top-level keys at a61244d):**

| Key | Status in Commit C |
|---|---|
| `timestamp` | PRESERVED (string, `ctx.out_dir.name`) |
| `config` | PRESERVED (dict, full `Config` dump) |
| `source_slot` | PRESERVED (int) |
| `target_slot` | PRESERVED (int) |
| `scan_field` | PRESERVED (dict: `n_regions`, `n_tiles`) |
| `focus_map` | PRESERVED (dict: model, origin, residuals, etc.) |
| `preflight` | PRESERVED (dict: zgalvo, cellpose env) |
| `overview` | MODIFIED — see below |
| `removed_picks` | PRESERVED (top-level list, NOT nested under `picks`) |
| `target_state` | PRESERVED (dict: drift, setup, zgalvo) |
| `picks` | PRESERVED (top-level list of pick dicts; NOT renamed/reshaped) |
| `targets` | PRESERVED (top-level list of target dicts) |
| `selection` | NEW |

**`overview` section — MODIFIED**:

Current post-revert `overview` contains:
- Acquisition counters: `n_tiles_planned`, `n_tiles_acquired`, `n_tiles_submitted`, `n_tiles_acquire_failed`
- Failure lists: `tile_acquire_failures`, `n_engine_failures`, `engine_failures`
- Pick counters: `n_picks_raw`, `n_picks_removed_duplicate`, `n_picks_out_of_limits_xy`, `n_picks_out_of_limits_z`, `n_picks_final`, `simulated`

Commit C splits this:
- **Stays in `overview`**: acquisition counters + failure lists + `simulated`.
- **Moves to `selection`**: all `n_picks_*` fields plus `n_picks_final`.

Operator-facing tooling that reads `summary["overview"]["n_picks_raw"]` will
break. Search-and-replace target: any external script reading these fields
must move to `summary["selection"]`.

**`selection` section — NEW**:

```json
"selection": {
  "n_total": ...,                     // total cells across all tiles
  "n_qualifying": ...,                // cells above both thresholds
  "n_selected_pre_dedup": ...,
  "n_removed_duplicate": ...,
  "n_removed_out_of_limits_xy": ...,
  "n_removed_out_of_limits_z": ...,
  "n_removed_translation": ...,
  "n_final": ...,
  "n_tiles_below_sparse_cutoff": ...,  // 0 < cells_in_tile < min_cells_for_threshold
  "n_tiles_empty": ...,                // cells_in_tile == 0
  "area_threshold": ...,
  "intensity_threshold": ...,
  "area_threshold_auto": ...,
  "intensity_threshold_auto": ...,
  "seed_material": "...",
  "mode": "..."                        // one of MODE_THRESHOLD/SPARSE/NO_QUALIFYING/EMPTY
}
```

**`overview` section — FINAL SHAPE in Commit C**:

```json
"overview": {
  "n_tiles_planned": ...,
  "n_tiles_acquired": ...,
  "n_tiles_submitted": ...,
  "n_tiles_acquire_failed": ...,
  "tile_acquire_failures": [...],
  "n_engine_failures": ...,
  "engine_failures": [...],
  "n_npz_save_failures": ...,         // NEW (rev7)
  "npz_save_failures": [...],         // NEW (rev7)
  "completed": ...,                    // NEW (rev7) — drain-completion sentinel
  "simulated": ...
  // n_picks_* fields are now in selection.*
}
```

**Counter-source mapping (PIN — do not derive from `OverviewResult.n_tiles`)**:

`OverviewResult.n_tiles` means *successfully drained and saved* tiles — a
strict subset of "acquired" and "submitted". Wiring it to
`summary["overview"]["n_tiles_acquired"]` would silently miscount: engine
failures and NPZ-save failures would be lost.

The summary writer reads everything from `OverviewResult` — all fields are
either persisted to `overview_meta.json` or derivable from the v2 NPZ files,
so the finish cell works after the supported overview→selection kernel
restart:

| Field | Source on `OverviewResult` |
|---|---|
| `n_tiles_planned` | `overview.n_tiles_planned` (persisted in meta) |
| `n_tiles_submitted` | `overview.n_tiles_submitted` (persisted in meta) |
| `n_tiles_acquired` | `overview.n_tiles_acquired` (= submitted − acquire_failures) |
| `n_tiles_acquire_failed` | `len(overview.tile_acquire_failures)` |
| `n_engine_failures` | `len(overview.engine_failures)` |
| `n_npz_save_failures` | `len(overview.npz_save_failures)` |
| `completed` | `overview.completed` |

`OverviewResult.n_tiles` itself does NOT appear in the summary `overview`
block — it's an internal-to-selection concept (= "drained AND saved tiles",
a strict subset of `n_tiles_acquired`). If a future need surfaces, add it
as a distinct field (e.g., `n_tiles_drained_and_saved`) rather than
overloading `n_tiles_acquired` or any existing name.

**Audit** (replace the old "additive only" check):

```bash
# After Commit C, verify:
# 1. No accidental top-level key deletions:
git diff <revert>..HEAD -- summary.py | grep '^-.*".*":' | grep -v "n_picks"
# Expected: only the n_picks_* removals from the overview block.
#
# 2. New top-level "selection" key is present:
python -c "import json; print('selection' in json.load(open('run_summary.json')))"
#
# 3. Existing keys (timestamp, config, source_slot, target_slot, scan_field,
#    focus_map, preflight, overview, removed_picks, target_state, picks,
#    targets) all still present after a real run.
```

The change is intentional, not accidental. Document it as a breaking change
in the commit message.

### 6. Notebook restructure

Cell sequence:

```
[md]    # Smart Microscopy v3 (title + workflow table)
[code]  Init -- sys.path, Config, connect, preflight
[md]    ## Setup
[code]  Stage limits + template
[code]  Scan field -- renders plot_scan_field ONCE here
[code]  Focus map
[md]    ## Overview
[code]  Overview cell (live 2-panel per tile)
[md]    ## Target Selection
[code]  Selection cell (interactive)
[md]    ## Target Acquisition
[code]  Acquisition cell (live 3-panel per target)
[md]    ## Finish
[code]  Summary + finish + cleanup
```

**Overview cell**:
```python
from workflow import run_overview
from workflow.visualize import display_tile

_fb_ov = ctx.run.layout.feedback_dir("overview-scan")

def _on_tile(event):
    display_tile(event, feedback_dir=_fb_ov)

overview = run_overview(ctx, focus_map, on_tile=_on_tile)
```

**Selection cell** (always loads from disk — kernel-restart safe):
```python
from workflow.selection import select_targets, load_overview_result
from workflow.visualize import display_selection

_analysis_dir = ctx.run.layout.analysis_dir("overview-scan")

overview = load_overview_result(_analysis_dir)  # kernel-restart safe

# Auto thresholds by default. To override, uncomment one or both:
picks, selection = select_targets(
    overview,
    ctx.limits_context(),
    n_per_tile=4,
    # area_threshold=200,
    # intensity_threshold=100,
    # seed=42,
)
display_selection(
    selection,
    _analysis_dir,
    feedback_dir=ctx.run.layout.feedback_dir("overview-scan"),
)
```

**Acquisition cell**:
```python
from workflow import acquire_targets
from workflow.visualize import display_target

_fb_tgt = ctx.run.layout.feedback_dir("target-acquisition")
_tile_cache = {}

def _on_target(pick, rec):
    display_target(
        pick, rec, _analysis_dir,
        feedback_dir=_fb_tgt, tile_cache=_tile_cache,
    )

records = acquire_targets(ctx, picks, on_target=_on_target)
```

**Finish cell** (reloads overview from disk for symmetry with selection cell —
reloading is harmless and keeps the cell's input source consistent with
selection. Restart between selection/acquisition/finish is NOT supported in
this PR: `picks`, `selection`, and `records` must still be in-kernel
when finish runs):
```python
from workflow import write_summary, plot_results, finish
from workflow.selection import load_overview_result

overview = load_overview_result(ctx.run.layout.analysis_dir("overview-scan"))
write_summary(ctx, focus_map, overview, picks, selection, records)
plot_results(ctx, focus_map, picks, records)
finish(ctx)
```

### 7. `workflow/__init__.py` — exports

Add to the public surface:
- `run_overview`, `OverviewResult` (from overview)
- `LimitsContext` (from context)
- `select_targets`, `SelectionResult`, `load_overview_result` (from selection)

Update or remove (depending on policy): `run_overview_with_picks` (deleted in C).
`load_overview_picks` from earlier plan revisions is deleted entirely — not
exported, not retained as a compat helper.

### 8. `smoke_visualization.py`

Update to exercise the new pipeline:
1. Generate synthetic data via cellpose + `human_mitosis`.
2. Build a fake engine that yields per-tile results.
3. Call `run_overview` -> save npz + overview_meta.json, accumulate.
4. Call `load_overview_result` and `select_targets(overview, ...)`.
5. Call `display_selection`.
6. Run `acquire_targets` with a no-op acquire function.

Document env requirement at top: cellpose, scikit-image, tifffile, matplotlib.

### Tests (Commit C)

- **Update** `TestFireOnTile` (4 tests): `TileEvent` now 5 fields; update fixture
  construction in each test.
- **+8** `TestSelectTargets`:
  - `test_global_mode_threshold_when_qualifying_cells_exist`
  - `test_global_mode_empty_when_zero_cells`
  - `test_global_mode_sparse_when_below_cutoff`
  - `test_global_mode_no_qualifying_returns_zero_picks_no_fallback` *(validates no random fallback)*
  - `test_override_one_threshold_sets_auto_flag_per_axis`
  - `test_seed_zero_does_not_collide_with_auto`
  - `test_per_stage_counts_sum_correctly`
  - `test_selected_pick_ids_use_full_pick_id_tuple`
- **+3** `TestDisplaySelection`:
  - `test_scatter_threshold_lines_in_threshold_mode`
  - `test_scatter_no_lines_with_annotation_in_sparse_mode`
  - `test_empty_picks_renders_scatter_only_with_annotation`
- **+1** `TestExampleCropsSpread` — 8-tile fixture with varying picks/tile,
  assert one largest from each of 6 distinct tiles, fallback to next-largest
  within already-represented tiles when fewer than 6 tiles have picks.
- **+1** `TestFilterOutOfLimitsTakesLimitsContext` — construct `LimitsContext`
  directly, call `_filter_out_of_limits`, assert works without Context mock.
- **+1** `TestLoadOverviewResultFromSelectionModule` — import path
  `from workflow.selection import load_overview_result`. No underscore.
  Asserts `load_overview_picks` is NOT importable (deleted, not re-homed).
- **+1** `test_kernel_restart_selection_loads_from_disk` — write npz + meta
  files manually (simulating a prior overview run). The test body must NOT
  import or call `run_overview`; it executes only the selection-cell code
  path (`load_overview_result(...)` + `select_targets(overview, ...)`).
  Assertions: `overview.completed is True`, `overview.n_tiles_empty` correct
  for the fixture, `selection.selected_picks` non-empty (for a fixture with
  qualifying cells), `tile_cell_counts` matches the fixture exactly. The
  "no `run_overview` call" structural property is what makes this a real
  restart-safety test, not a `NameError` check.
- **+1** `test_full_pipeline_with_synthetic_engine` (integration).
  Fixture: 3 tiles with **30 cells (normal), 5 cells (sparse-per-tile),
  0 cells (empty-per-tile)**. Total = 35 cells globally.
  Assertions:
  - `selection.mode == MODE_THRESHOLD` (global, since 35 > 10)
  - `selection.n_tiles_below_sparse_cutoff == 1` (the 5-cell tile)
  - `selection.n_tiles_empty == 1` (the 0-cell tile)
  - `overview.tile_cell_counts == {tile_a: 30, tile_b: 5, tile_c: 0}` after
    `load_overview_result` — pins single-pass loader produces the 0-cell entry
  - `len(selection.selected_picks) <= 8` (4 per tile from 2 tiles with cells)
  - Records produced via no-op acquire function
  - Summary written with all sections populated; `summary["selection"]`
    contains the counters above; `summary["overview"]` no longer contains
    `n_picks_*` fields (those moved to selection)
- **+1** `test_summary_pick_fields_moved_from_overview_to_selection` —
  asserts the schema migration: run write_summary, parse JSON, confirm
  `summary["overview"]` has no `n_picks_raw` key, `summary["selection"]`
  has it.
- **+1** `test_summary_preserved_top_level_keys` — asserts every
  pre-revert top-level key (`timestamp`, `config`, `source_slot`,
  `target_slot`, `scan_field`, `focus_map`, `preflight`, `target_state`,
  `removed_picks`, `picks`, `targets`) is present in the new schema.

**Note on Commit B test cleanup**: `test_run_overview_with_picks_wrapper_populates_all_picks_fields`
(added in Commit B) covers a wrapper that Commit C deletes. **Remove that
test in Commit C** along with the wrapper.

**Test count math**:
- Commit C additions: +8 (TestSelectTargets) +3 (TestDisplaySelection) +1 (TestExampleCropsSpread) +1 (TestFilterOutOfLimitsTakesLimitsContext) +1 (TestLoadOverviewResultFromSelectionModule) +1 (test_kernel_restart_selection_loads_from_disk) +1 (test_full_pipeline) +1 (test_summary_pick_fields_moved) +1 (test_summary_preserved_top_level_keys) = **+18**
- Commit C removals: -1 (wrapper test from B that no longer applies)
- Net Commit C: +17
- Total: 105 + 17 = **122 tests**

Rolling math: 94 (post-revert) + 1 (Commit A) + 10 (Commit B) + 17 (Commit C
net) = **122**.

**Total after Commit C: 122 tests.**

---

## Cross-repo coordination

`smart-analysis` already has `SUPPORTS_NONE_NPICKS=True` (commit 1a from the
original cycle, not reverted). After the revert, smart-microscopy at the revert
point doesn't check the flag — runs against any engine version. Commit A
reintroduces the check.

No new coordination required. Verify `smart-analysis`'s `pick_targets.py`
has the flag before starting Commit A.

---

## Out of scope (deferred)

### Persistence and recovery: not in scope for this PR

Kernel-restart between **overview and selection** IS supported (selection
cell loads `OverviewResult` from disk). Restart at any later boundary is
deferred:

- **Restart between selection and finish**: would require persisting
  `SelectionResult`, `Picks`, and target `records` to disk. Currently they
  live only in kernel memory.
- **Restart between acquisition and finish**: same — `records` are
  in-memory only until `write_summary`.
- **Mid-run crash recovery during acquisition**: partial records from a
  crashed `acquire_targets` are lost; no resume.
- **Stale NPZ cleanup between runs**: `load_overview_result` trusts every
  v2 NPZ in `analysis_dir`. Re-running overview into a populated directory
  is unsupported. The per-experiment `experiment_hash6` naming convention
  already gives each run a fresh dir, so this is documented (Constraints)
  rather than enforced in code.

### Performance / observability deferrals

- **Synchronous I/O in drain critical path**: every drained engine result
  triggers `_save_single_tile_analysis` + `on_tile` callback inside the loop.
  On Z: drive at 200-tile scale this serializes. Same risk profile as today;
  not made worse. Defer to Commit D if observed.
- **Dedup threshold (`0.75 × max(bbox_diag)`)**: tuned for the old top-N-by-area
  pick distribution. Now applied to random-from-qualifying picks. Different
  distribution, same constant. Re-evaluation pending operator feedback.

### Feature deferrals

- **Example crops show selected only**: no rejected-cells in the grid. The
  scatter plot is the comparison tool. Future enhancement to mix selected
  and just-below-threshold rejected cells.
- **`plot_overview_tiles` / `plot_target_pairs` batch functions**: exist
  in `visualize.py` but not called from the notebook after this restructure.
  Currently zombie code. Decision deferred: either delete in a cleanup
  commit or migrate to the new layouts.

---

## Files touched (summary)

| File | Commit | Action |
|---|---|---|
| `workflow/context.py` | A | Remove `n_picks_per_tile`, `feature` |
| `workflow/context.py` | C | Add `LimitsContext`, `Context.limits_context()` |
| `workflow/overview.py` | A | Engine submit, intermediate-state warning |
| `workflow/overview.py` | B | Add `run_overview`, `OverviewResult` (with `tile_cell_counts` + `n_tiles`/`n_tiles_empty` properties), `_picks_from_result`, expand `_save_single_tile_analysis` with `extra_arrays` + `_array_from_field`, add `_write_overview_meta` + `load_overview_result` (temp home), keep compat wrapper, buffer→counter, delete `_collect_picks_from_results` |
| `workflow/overview.py` | C | Rename `picked_labels`→`n_cells` in `TileEvent` (in-place, no reorder), delete compat wrapper, delete warning, `_filter_out_of_limits` takes `LimitsContext` |
| `workflow/preflight.py` | A | Capability check import |
| `workflow/target.py` | A | Env-var safety gate in `acquire_targets` (removed in C) |
| `workflow/selection.py` | C | NEW: re-home `load_overview_result`, add `select_targets(overview, limits, ...)` (no `n_tiles_attempted` param), `SelectionResult`, mode constants |
| `workflow/visualize.py` | C | `display_tile` -> 2-panel, add `display_selection` |
| `workflow/__init__.py` | C | Update exports (`OverviewResult`, `LimitsContext`, `select_targets`, `SelectionResult`, `load_overview_result`) |
| `workflow/summary.py` | C | New `write_summary` signature; restructured schema (n_picks_* fields move from `overview` block to new `selection` block — NOT purely additive) |
| `smart_microscopy_v3.ipynb` | A, C | Config cell (A); restructure overview/selection/acquisition (C) |
| `smoke_visualization.py` | C | Update to new pipeline |
| Tests | A, B, C | Per-commit additions enumerated above |

---

## Key decisions

| Decision | Rationale |
|---|---|
| `git revert -n a61244d..842df33` | Inclusive range covers all 6 commits |
| One revert commit | Reviewable, preserves history on a shared branch |
| Env-var safety gate in Commit A (`SMART_MICROSCOPY_ALLOW_INTERMEDIATE_RUN`) | Stronger than print, no permanent Config field, removed in C |
| Additive `run_overview` + compat wrapper in Commit B | No empty-Picks shim, notebook runnable at every commit |
| `_array_from_field` helper | Empty-tile npz preserves `(0, K)` shapes, not `(0,)` |
| Global mode + per-tile descriptive counters | Coherent with global thresholds; per-tile sparseness available without per-tile mode confusion |
| `MODE_NO_QUALIFYING` returns zero picks | Operator-controlled selection — no random fallback hiding the empty intersection |
| `selected_picks: list[Pick]` on `SelectionResult` | `display_selection` reads bbox/centroid directly; `selected_pick_ids` is a `@property` |
| `area_threshold_auto` + `intensity_threshold_auto` (two booleans) | Per-axis override granularity |
| `seed if seed is not None else "auto"` | Handles `seed=0` (subtle bug fix) |
| `load_overview_result` public, in `selection.py` | No underscore-prefixed import in notebook; replaces earlier `load_overview_picks` |
| Single-pass loader (`load_overview_result`) | Builds `all_picks` and `tile_cell_counts` in one read of each v2 NPZ; halves disk I/O vs separate count + load passes |
| `OverviewResult.tile_cell_counts` (dict) | Carries empty-tile information that `all_picks` alone cannot express; lets `select_targets` see the empties without a separate `n_tiles_attempted` parameter |
| `select_targets(overview, ...)` (no `n_tiles_attempted`) | Removes a footgun where caller could forget to pass the count and silently get `n_tiles_empty == 0` |
| `overview_meta.json` stores failure lists + acquire-loop counters + completion sentinel | `tile_cell_counts` is recoverable from v2 NPZs and is NOT persisted. Failure lists, `n_tiles_planned`, `n_tiles_submitted`, and `completed` cannot be recovered from disk after kernel restart — they're the JSON-persisted fields. Schema v2. |
| NPZ `schema_version=2` key | Forward-compat for future migrations; loader skips v1 with warning, v1 files do NOT inflate `n_tiles` |
| `LimitsContext` (5 fields) | Selection tests construct directly, no full Context mock |
| `write_summary` schema is restructured (not additive) | Adds top-level `selection` block; reshapes `overview` block by moving `n_picks_*` fields to `selection`. Other top-level keys (`timestamp`, `config`, `scan_field`, `focus_map`, `preflight`, `target_state`, `removed_picks`, `picks`, `targets`) are preserved |
| Integration test: 3 tiles × (30, 5, 0) cells | Exercises global threshold mode, per-tile empty handling, per-tile sparse counter, empty-npz shape correctness, `tile_cell_counts` round-trip through `load_overview_result` |

---

## Implementation sequence

1. **Revert**:
   ```bash
   git checkout cleanup/wave-2
   git revert -n a61244d..842df33
   git commit -m "revert: integrated threshold selection; rebuilding as separate step"
   ```
   Run tests: 94 green expected. Push for review.

2. **Commit A**: Implement Config + engine + preflight + safety gate.
   Run tests: 95 green. Push.

3. **Commit B**: Implement npz schema + drain restructuring + additive
   `run_overview` (with `OverviewResult.tile_cell_counts`) + compat wrapper +
   `_array_from_field` + `_write_overview_meta` + `load_overview_result`
   (single-pass).
   Run tests: 105 green. Push.

4. **Commit C**: Implement `TileEvent` in-place rename (`picked_labels` →
   `n_cells`, same field position) + `display_tile` 2-panel + `selection.py`
   + `select_targets(overview, ...)` (no `n_tiles_attempted` param) +
   `display_selection` + notebook restructure (selection cell and finish
   cell both load via `load_overview_result`) + summary schema migration +
   `LimitsContext`. Re-home `load_overview_result` to `selection.py`.
   Delete compat wrapper, warnings, env-var gate. Remove the B-era wrapper
   test.
   Run tests: 122 green. Run `smoke_visualization.py` end-to-end. Push.

5. **Merge** `cleanup/wave-2` to main.

Each commit is independently reviewable, runnable, and revertable.

---

## Pre-implementation checklist for the new agent

Before starting the revert:

- [ ] Confirm working directory: `Z:/zmbstaff/.../smart-microscopy`
- [ ] Confirm branch: `git rev-parse --abbrev-ref HEAD` shows `cleanup/wave-2`
- [ ] Confirm HEAD: `git log --oneline -1` shows `842df33` (or latest tip)
- [ ] Confirm smart-analysis is deployed:
      `grep SUPPORTS_NONE_NPICKS Z:/zmbstaff/.../smart-analysis/workflows/target_acquisition/steps/pick_targets.py`
      should show `SUPPORTS_NONE_NPICKS = True`
- [ ] Confirm tests run: `pytest controller/vendor/leica/navigator_expert/notebooks/workflow/test/`
      reports 52 tests at current HEAD (will be 94 after revert — naming + workflow combined varies by which directories run together)
- [ ] Run `git grep "n_picks_per_tile"` and `git grep "cfg\.feature"` —
      record references that need updating in Commit A
- [ ] Read `controller/vendor/leica/navigator_expert/notebooks/workflow/overview.py`
      and `target.py` end-to-end before starting
- [ ] Read this plan in full before editing

After Commit C:

- [ ] All 122 tests green
- [ ] `smoke_visualization.py` runs end-to-end
- [ ] `git diff revert_commit..HEAD -- controller/vendor/leica/navigator_expert/notebooks/workflow/summary.py`
      shows: (a) signature change, (b) new `selection` top-level block,
      (c) `n_picks_*` fields removed from the `overview` block (intentional
      migration, documented in commit message), (d) no other top-level keys
      removed
- [ ] Manual review: notebook structure matches the cell sequence above
- [ ] `git grep "n_picks_per_tile"` and `git grep "cfg\.feature"` return empty
- [ ] `git grep "run_overview_with_picks"` returns empty (compat wrapper deleted)
- [ ] `git grep "SMART_MICROSCOPY_ALLOW_INTERMEDIATE_RUN"` returns empty (gate deleted)
- [ ] `git grep "load_overview_picks"` returns empty (replaced by `load_overview_result`)
- [ ] `git grep "n_tiles_attempted"` returns empty (parameter removed)
- [ ] `git grep "overview\.n_tiles\b"` returns only `select_targets` and
      internal property usage — **never** appears in `summary.py`. (Summary
      uses `overview.n_tiles_acquired`, `overview.n_tiles_submitted`,
      `overview.n_tiles_planned`, but not `overview.n_tiles`.)
- [ ] Kernel-restart smoke test: in a fresh kernel, after a completed
      overview-scan run, execute only Init + Setup + Selection cells against
      the existing `overview-scan/` directory. Should complete without
      NameError. (Restart between selection and finish is NOT supported in
      this PR — see "Persistence and recovery: not in scope".)

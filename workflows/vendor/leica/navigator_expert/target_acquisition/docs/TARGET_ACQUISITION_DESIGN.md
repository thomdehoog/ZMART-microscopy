# Target Acquisition -- Notebook Design

A comprehensive design for a new `smart_microscopy_v3.ipynb` (sibling of the
existing `_v2`, which is left untouched) that
runs an adaptive overview -> target-acquire workflow at two objectives,
with on-the-fly per-tile analysis powered by the `smart-analysis`
engine. Document written for review before any code is written.

ASCII-only by policy (matches `smart-analysis/AGENTS.md` rule).

---

## 1. Scope

**v1 goal.** From the notebook, the operator runs:

1. A low-magnification *overview* survey at the source objective.
2. Per-tile cellpose segmentation while the survey runs (warm-worker,
   non-blocking submits to the `smart-analysis` engine).
3. A *target* acquisition pass at a higher-magnification objective --
   one framed acquire per picked cell, using the calibrated
   objective-switch translator to land each cell centred and in focus.

**v1 explicitly does NOT:**

- Run the optional NCC / PCC / voting refine loop from
  `objective_switch_target.py` (deferred -- flag-driven add later).
- Acquire 3-D z-stacks. Both overview and target are 2-D for v1
  (the `ACQUISITION_JOB` and `TARGET_JOB` LRP jobs may technically be
  z-stacks, but the workflow treats them as 2-D and ignores the
  authored z-range).
- Verify landing error against the source cell (the example's
  morphology match is informative but adds Cellpose dependency to
  the target loop; can be added later).
- Run AF on the target objective.
- Touch the calibration or driver subsystems.

---

## 2. Repos and key existing files

| Repo | Path on disk |
|---|---|
| `smart-microscopy` | `Z:\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\` |
| `smart-analysis`   | `Z:\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-analysis\` |

### 2.1 Files we read (no edits, reference only)

| Purpose | Path |
|---|---|
| Reference notebook (read-only, untouched) | `smart-microscopy/controller/vendor/leica/navigator_expert/notebooks/smart_microscopy_v2.ipynb` |
| Reference target-acquire pipeline | `smart-microscopy/controller/vendor/leica/navigator_expert/examples/objective_switch_target.py` |
| Calibration v9 + translator | `smart-microscopy/controller/vendor/leica/navigator_expert/driver/calibration.py` |
| Driver public API (`drv`) | `smart-microscopy/controller/vendor/leica/navigator_expert/driver/__init__.py` |
| Existing notebook helpers | `smart-microscopy/controller/vendor/leica/navigator_expert/driver/notebook_workflow.py` |
| Engine API | `smart-analysis/engine/_pipeline.py` |
| Adaptive pattern | `smart-analysis/examples/04_adaptive_microscopy/` |
| Production workflow template (mirror) | `smart-analysis/workflows/rare_event_selection/` |

### 2.2 Files we will modify

(none -- `_v2` is left untouched. The new notebook is `_v3`, listed
in 2.3 below.)

### 2.3 Files we will create (smart-microscopy side -- notebook helpers)

```
smart-microscopy/controller/vendor/leica/navigator_expert/notebooks/
  smart_microscopy_v3.ipynb      THE notebook -- thin operator UI
  workflow/
    __init__.py        Re-exports public API.
    context.py         Config (frozen) and Context (mutable) dataclasses.
    preflight.py       preflight(cfg, client) -> Context
    template.py        prepare_template(ctx); read_scan_field(ctx); plot_scan_field(ctx)
    focus.py           build_focus_map(ctx) -> FocusMap
    overview.py        run_overview_with_picks(ctx, focus_map) -> Picks
    target.py          acquire_targets(ctx, picks) -> list[TargetRecord]
    summary.py         write_summary(...); plot_results(...)
    _acquire.py        acquire(...), save_acquired(...) shared helpers
```

### 2.4 Files we will create (smart-analysis side -- analysis pipeline)

Mirror the `rare_event_selection` workflow layout exactly.

```
smart-analysis/workflows/target_acquisition/
  pipelines/
    overview.yaml
  steps/
    segment_tile.py    cellpose v4 (warm worker, METADATA env)
    pick_targets.py    top-N picks per tile by feature
  environments/
    setup_env.py       creates "SMART--target_acquisition--main" conda env
  tests/
    test_target_acquisition.py
```

---

## 3. Design decisions

Numbered so review feedback can reference them.

### D1. Two-job model (overview + target)

Both `ACQUISITION_JOB` (overview) and `TARGET_JOB` exist as separate
LRP jobs in the LAS X template. Reason: target is typically a
different channel set / exposure / dwell than the survey. The
acquisition helper switches jobs lazily.

**Rationale:** Matches operator practice; matches LAS X's job model.
Single-job designs (like `objective_switch_target.py`) work for the
example because it only changes zoom. For real workflows the channel
set differs.

### D2. Single Z axis: z-wide on all jobs

Step 1 enforces `z-wide` on **every** job in the LRP:
`ACQUISITION_JOB`, `AF_JOB`, `TARGET_JOB`.

The reference `smart_microscopy_v2.ipynb` enforces `z-galvo` on
every job; v3 deliberately moves away from that. Reasons:

- The calibration translator (`drv.translate_xyz_between_objectives`)
  is z-wide native; using z-wide everywhere removes the need for
  any galvo-to-wide bridge identity (no untested hardware
  assumption to validate).
- One Z axis end-to-end is simpler: the focus map, the per-tile
  acquire, the translator input, and the target acquire all speak
  the same units in the same coordinate.
- The reference example (`objective_switch_target.py`) is already
  z-wide-only ("z-galvo stays at 0 throughout -- all focus motion
  lives on z-wide"); we adopt the same contract.

**The workflow never commands z-galvo.** It only reads it for
telemetry (preflight + once after the Step 5.1 objective switch,
per D3). Whatever LAS X has z-galvo set to is left alone.

### D3. Focus map in z-wide; same Z axis end-to-end

The Step 3 focus plane is fit in **z-wide**: at each focus marker
we run the AF job and read back the resulting z-wide value via

```python
settings = drv.get_job_settings(client, AF_JOB)
ch       = drv.make_changeable_copy(settings)
zwide_um = ch["zPosition"]["z-wide"]
```

Step 4 commands z-wide for every overview tile from the fitted
plane. The translator
(`drv.translate_xyz_between_objectives`) consumes that z-wide
directly and produces a target z-wide. Step 5 commands the target
z-wide. **One Z axis throughout** -- no bridge identity, no
mode-switching mid-flow.

**No per-tile read of z-wide.** Because we *commanded* the value
via `move_z(..., z_mode="zwide")` immediately before the acquire,
the value we write into the pick (`tile_zwide_um`) is exactly the
commanded value. No round-trip read needed.

**Operator precondition: z-galvo at 0 before starting.** The
workflow never commands z-galvo, but a non-zero z-galvo at the
start adds a constant focal offset that the focus map (fit in
z-wide) will silently absorb -- *as long as z-galvo does not
change during the run*. The objective switch in Step 5 is the
risky moment because the firmware may re-centre z-galvo on the
target slot, shifting the focal plane.

To make this safe in v1 *without* touching z-galvo:

1. Preflight reads z-galvo at the source objective via

   ```python
   settings  = drv.get_job_settings(client, ACQUISITION_JOB)
   ch        = drv.make_changeable_copy(settings)
   zgalvo_um = ch["zPosition"]["z-galvo"]
   ```

   If `|zgalvo_um| > 0.5 um` it **warns** with an actionable
   message ("set z-galvo to 0 in LAS X before re-running for best
   accuracy") and continues. Recorded in `summary.json` under
   `preflight.source_zgalvo_um`.

2. The same read happens once after the Step 5.1 objective
   switch, comparing against the preflight value. Any drift
   `> 0.5 um` is recorded under `target_state.zgalvo_drift_um`
   (warning only; workflow continues).

The reference `objective_switch_target.py` example does not check
this either, but it operates inside calibration scripts that
explicitly initialise z-galvo. The notebook is operator-driven and
cannot rely on that.

### D4. Pick policy: top-N per tile by feature

`pick_targets` runs *per tile* (no scope aggregation). Top N detected
cells per tile, ranked by `feature` (default `area`). Param exposed
in YAML.

Cross-tile global ranking (or per-region scoped ranking) is a future
extension -- change to a scoped step then.

### D5. Pick deduplication across overlapping tiles

After Step 4 drains, dedup picks by source-frame **cell** coordinate
(not tile centre). Two picks are duplicates when

```
distance(pick_a.cell_source_stage_xy_um,
         pick_b.cell_source_stage_xy_um)
  <  max(bbox_diag(pick_a), bbox_diag(pick_b)) * 0.75
```

where `bbox_diag = hypot(*pick.bbox_um)`. Keep the higher-`feature`
one; the loser is appended to `picks.removed_picks` with
`reason="duplicate"` and counted in
`picks.n_picks_removed_duplicate`.

**Why this criterion (not target FOV).** Framed zoom is per-pick
(derived from each pick's bbox at acquire time), so a target-FOV
threshold is not well defined at dedup time. Cell bbox is known at
pick time and is the natural scale: if two centroids are within
~one cell diameter, they are almost certainly the same cell
re-segmented in an adjacent tile.

**Why dedup at all:** Adjacent overview tiles overlap (~10-20%);
the same cell near a tile edge gets picked twice, wasting target
acquisitions.

### D6. Out-of-stage-limits filter (XY and Z)

For each pick, predict the target-frame `(tx, ty, tz)` via the
translator (no hardware). Drop the pick when:

- `tx` or `ty` falls outside the XY stage limits set in Step 1, or
- `tz` falls outside the physical z-wide envelope from
  `stage_config["limits_um"]["z_wide"]` (loaded from `stage.json`
  by preflight; not a Config field).

Both checks are cheap (pure math). Drops are counted in
`picks.n_picks_out_of_limits_xy` and `picks.n_picks_out_of_limits_z`
respectively. Each dropped pick is also appended to
`picks.removed_picks` with `reason="xy"` or `reason="z"` so it
surfaces in `summary.json` and the Step 6 plot.

The Z check is non-trivial: a parfocally-corrected source z-wide
near the source range edge can translate to a target z-wide
outside the wide motor's safe range.

### D7. Pick coordinates: tile-centre and cell-source, both recorded

Every pick records both axes of provenance:

| Field | Meaning |
|---|---|
| `tile_stage_xy_um` | Stage XY at which the *tile* was acquired (centre of tile FOV). Provenance / debug only. |
| `cell_source_stage_xy_um` | Stage XY of the **cell**, computed by the pick step from `image_to_stage @ centroid_offset`. **Canonical pick address.** |
| `centroid_col_row_px` | Pixel centroid in tile frame, order **(col, row)** -- matches the reference example's storage and what `drv.pixel_to_stage_xy_um` consumes. skimage's `regionprops.centroid` returns `(row, col)`; the swap happens inside `pick_targets`. |
| `bbox_px` | `(min_row, min_col, max_row, max_col)` -- skimage row-major. |
| `bbox_um` | `(width_um, height_um)`. |
| `area_px`, `eccentricity` | regionprops. |
| `tile_zwide_um` | z-wide commanded at tile acquire. Translator-ready Z (D3). |
| `source_pixel_size_um` | `(pixel_w_um, pixel_h_um)` -- both axes (frames may be non-square). |
| `source_image_size_px` | `(pixels_x, pixels_y)` -- both axes. |
| `pick_id` | `(region, row, col, cell_label)`. |

**All downstream operations consume `cell_source_stage_xy_um`**:
dedup distance (D5), out-of-limits filter (D6), Step 5 stage sort
order, and the input to the objective translator (Step 5.4).
`tile_stage_xy_um` is recorded only for traceability.

**Why:** "We want to find targets back on the coordinate system of
the overview scan." The translation to target frame happens at
acquire time and is recorded *alongside* the source values in
`summary.json`. Source is the address, target is the realization.

### D8. Engine submissions carry image PATHS, not arrays

`drv.acquire_frame` returns `(numpy_array, lasx_path)`. The notebook
copies the OME-TIFF into `out_dir/overview/` (because LAS X export
paths can be ephemeral) and submits the *path*. `segment_tile`
re-reads with `tifffile.imread`.

**Why:** A 2k x 2k uint16 tile is 8 MB; pickling that across an IPC
pipe per tile per worker call wastes time and memory. Matches the
smart-analysis examples.

### D9. Preflight engine check (no synchronous submit by default)

Step 0:

1. Boots the engine.
2. Registers `overview.yaml`. This *will* raise on a malformed YAML
   -- legitimate hard failure.
3. Resolves the conda env named in `segment_tile.py`'s METADATA on
   disk and checks it exists. The exact resolution helper is a
   private function in `notebooks/workflow/preflight.py`; it can
   delegate to `engine.conda_utils` if that module is part of the
   public engine surface, otherwise it inspects `CONDA_ROOT`/`envs/`
   directly. If the env is missing, **warn loudly and continue**
   (per operator preference).

Preflight does **not** submit anything synthetic by default.
Reason: the engine is fully asynchronous; `submit()` does not raise
on step failure, and a real synchronous smoke would require
`status("overview")` polling with a timeout -- extra coupling for
marginal gain. The first tile that fails in Step 4 surfaces
engine-side failures via `status("overview")["failures"]`, and
Step 4 is designed to keep going past tile failures (D17).

**Optional smoke flag** (`Config.smoke_test_pipeline: bool = False`)
enables a synchronous path for debugging: submit a synthetic 64x64
zero-image tile, poll `status` until `pending + running == 0` with
a short timeout, then **drain and discard** the smoke result via
`engine.results("overview")` so it cannot leak into Step 4's
buffer. Failure entries cannot be discarded (cumulative in the
Engine), but Step 4's `failure_count_before` snapshot (D19) is
taken *after* preflight returns, so any smoke-time failures stay
on the historical side of the cut and are not counted against
Step 4. Preflight prints any smoke-time failures and warns on
non-empty result.

### D10. Lazy job switching, explicit objective + job at boundary

Within Step 4, `acquire(...)` switches the job only if needed. Within
Step 4 it is a no-op every call. The Step 4 -> 5 boundary explicitly
calls, in order:

1. `select_job(TARGET_JOB)` + settle
2. `drv.set_objective(client, TARGET_JOB, hw, slot_index=TARGET_SLOT)` + settle
3. update `current_job` tracker

Reason: Leica firmware applies parfocal compensation in the context
of the selected job. Wrong order means the wrong parfocal offsets.

The driver's `IsSelected` flag lags the UI (called out in the
example's preconditions), so the helper tracks `current_job` in
Python rather than reading it from the driver.

### D11. Two dataclasses: immutable `Config`, mutable `Context`

`Config` (immutable, dataclass with `frozen=True`) holds operator
inputs: slot numbers, job names, paths, thresholds. Constructed
once in the notebook config cell.

`Context` (mutable) holds runtime state that workflow helpers
update in place: `client`, `hw`, `calibration`, `stage_config`,
`engine`, `out_dir`, `current_job`, `boundary_limits`,
`scan_field`, `templates_dir`, plus a back-reference to `cfg`. No
globals; every public function takes `ctx` first.

Splitting the two prevents accidental mutation of operator inputs
and makes "what was the run configured with" trivially serialisable
into `summary.json`.

### D12. Compute / view separation

`build_focus_map` returns a `FocusMap`; `focus_map.plot(ctx)` is a
separate call. Same for picks / `plot_results`. The notebook chooses
when to plot.

### D13. 2-D only for v1

Both overview and target are treated as single 2-D frames. Jobs may
be authored as z-stacks; we ignore the authored range and acquire
one frame at the calibrated focus.

### D14. No refine pass for v1

Calibrated translation alone. Add NCC / PCC / voting later behind a
flag, mirroring the example's `--refine` option.

### D15. Cellpose conda env is a precondition

The env (`SMART--target_acquisition--main`, mirroring rare-event
naming) must exist on the workstation. AppLocker requires it under
`C:\ProgramData\MinicondaZMB\home\t.de\...`. Created by
`environments/setup_env.py`. Preflight warns if absent (D9).

### D16. Notebook is thin, helpers do the work

Each notebook cell is 2-5 lines. All logic lives in
`notebooks/workflow/`. The notebook imports only from `workflow`,
never directly from `drv` or `Engine` -- single seam for future swaps.

### D17. Per-tile / per-target failure isolation

One bad tile (cellpose error, file missing, acquire timeout) does
not stop the survey. One bad target acquire does not stop the
loop. Failures are split by where they happen:

- `tile_acquire_failures` -- `drv.acquire_frame` raised before any
  engine submit. Recorded as `{tile_id, error}` dicts. The tile is
  *not* submitted; nothing to wait for.
- `engine_failures` -- failure surfaced via
  `status("overview")["failures"]` (worker spawn / segment / pick
  step crashed). Only the *new* tail since `failure_count_before`
  (D19) is reported and counted -- the historical prefix is
  ignored.

After Step 4 we print:

```python
print("Tile acquire failures:", picks.tile_acquire_failures)
print("Engine failures:",       picks.engine_failures)
```

Both lists go into `summary.json` under
`overview.tile_acquire_failures` and `overview.engine_failures`.
Counters: `n_tiles_acquire_failed`, `n_engine_failures`.

### D18. The driver and calibration subsystems are off-limits

No edits to `driver/` or `calibration/`. New behaviour goes into
`notebooks/workflow/` (consumes `drv`) or
`smart-analysis/workflows/target_acquisition/` (consumes the
engine).

### D19. Engine drain semantics

`Engine.results(name)` returns whatever has completed since the
last call **and removes those results from the queue**.
`Engine.status(name)["failures"]` is **cumulative for the
registered pipeline name**: failures from any earlier submits
(e.g. an optional D9 smoke test) remain in the list.

So the notebook side must

1. accumulate results in its own buffer between drains, and
2. snapshot the failure count at the start of Step 4 so it only
   counts failures that belong to *this* run.

The Step 4 pattern (private helper inside
`notebooks/workflow/overview.py`):

```python
buffer: list[dict] = []
n_submitted = 0
failure_count_before = len(engine.status("overview")["failures"])

for tile in tile_sequence:
    ... acquire + submit ...
    n_submitted += 1
    buffer.extend(engine.results("overview"))   # opportunistic, non-blocking

while True:
    s = engine.status("overview")
    buffer.extend(engine.results("overview"))
    if s["pending"] == 0 and s["running"] == 0:
        break
    time.sleep(0.05)

new_failures = s["failures"][failure_count_before:]
assert len(buffer) + len(new_failures) == n_submitted
```

A submitted tile produces *exactly one* result on success
(`overview` has no scoped phase in v1) or shows up in
`new_failures` on error. The accumulated buffer therefore
satisfies `len(buffer) == n_submitted - len(new_failures)` at end
of drain. Only `new_failures` is reported in `summary.json` and
printed; the historical prefix is ignored.

The notebook never sees this loop -- it just receives `Picks` from
`run_overview_with_picks`.

### D20. Cleanup is idempotent and operator-visible

`ctx.shutdown()` is **idempotent**: calling it twice is a no-op the
second time. Implementation: a `_shutdown_done` flag on `Context`;
the method early-returns when set.

The notebook ends with a dedicated cleanup cell that the operator
is expected to run after a successful or failed run:

```python
# Cell N - cleanup (always run last)
try:
    ctx.shutdown()
except NameError:
    pass   # ctx never created (preflight failed)
```

For longer-term safety the `preflight()` helper also registers an
`atexit` hook that calls `ctx.shutdown()` if the Python kernel
itself is torn down without the cell running. The hook is
idempotent with the manual call.

---

## 4. Architecture

### 4.1 Two-repo split

```
   +-----------------------------------------+
   |  smart-microscopy (this repo)           |
   |                                         |
   |  notebooks/smart_microscopy_v3.ipynb    | <-- operator UI
   |  notebooks/workflow/   <-- all logic    |
   |      uses navigator_expert.driver       |
   |      uses Engine (from sibling repo)    |
   +--------------------+--------------------+
                        | engine.submit(...)
                        v
   +-----------------------------------------+
   |  smart-analysis (sibling repo)          |
   |                                         |
   |  engine/    <-- Engine, WorkerPool      |
   |  workflows/target_acquisition/  <-- NEW |
   |      pipelines/overview.yaml            |
   |      steps/segment_tile.py              |
   |      steps/pick_targets.py              |
   +-----------------------------------------+
```

### 4.2 Per-tile data flow during Step 4

```
LAS X acquire (job=ACQUISITION_JOB)
        |
        v
drv.acquire_frame  ->  numpy + lasx_path
        |
        +--> save_acquired(image, lasx_path,
        |                  out_dir/overview/tile_RxxCxx.tif)
        |
        v
   engine.submit("overview", {
       image_path,
       tile_id=(rid, row, col),
       tile_stage_xy_um=(x, y),
       tile_zwide_um=zwide_commanded,
       source_pixel_size_um=(pw, ph),
       source_image_size_px=(nx, ny),
       image_to_stage=ctx.calibration["image_to_stage"],   # 2x2, used by pick_targets
   })
        |
        v
   worker (warm cellpose):
       segment_tile  ->  pick_targets
                         |
                         |  rank top-N by feature
                         |  swap centroid (row,col) -> (col,row)
                         |  pixel-offset -> cell_source_stage_xy_um
                         |     via image_to_stage matrix (pure numpy)
                         |  emit Pick records (carry tile_zwide_um through)
                         v
                {picks: [Pick(...), ...]}
```

### 4.3 Coordinate frames

| Frame | Used for | Carrier |
|---|---|---|
| Tile pixel (col, row) | Cellpose centroid (after swap from skimage's row,col) | `centroid_col_row_px` |
| Tile pixel (row, col) | bbox (skimage native) | `bbox_px = (min_row, min_col, max_row, max_col)` |
| Tile-acquire stage XY (um) | Provenance / debug | `tile_stage_xy_um` |
| Source-objective stage XY (um) | **Pick canonical address** | `cell_source_stage_xy_um` |
| Source-objective z-wide (um)   | Z carrier across objective boundary | `tile_zwide_um` (commanded value, fed directly to translator) |
| Target-objective stage XY (um) | Realization at acquire time | `target_stage_xy_um` |
| Target-objective z-wide (um)   | Realization at acquire time | `target_zwide_um` |

**Conventions.** All `*_xy_um` fields are `(x, y)` tuples in
microns. All `*_px` fields make their order explicit per the table
above. Bbox follows skimage's row-major convention so regionprops
bridges stay trivial.

---

## 5. Module contracts (`notebooks/workflow/`)

All signatures are the public surface -- these are what the notebook
calls. Internal helpers are `_underscore`.

### 5.1 `context.py`

```python
@dataclass(frozen=True)
class Config:
    # Stage XY and z-wide are NOT operator-typed coordinates. They
    # come from LAS X markers (XY) and stage.json (envelope). The
    # only XY override here is a fallback escape hatch (all four
    # must be set together; validated against stage.json).

    # Slots & jobs (required)
    source_slot: int
    target_slot: int
    acquisition_job: str
    target_job: str
    af_job: str

    # Pick policy (required)
    n_picks_per_tile: int

    # Paths (required)
    analysis_repo: Path
    output_root: Path

    # Optional behaviour flags (defaults)
    feature: str = "area"
    fov_bbox_margin: float = 1.5
    settle_after_objective_switch_s: float = 3.0
    restore_template_after_af: bool = True   # restore stripped template after Step 3
    restore_source_at_end: bool = True       # restore source objective in Step 6
    smoke_test_pipeline: bool = False        # see D9

    # Boundary marker margin (only consumed when markers are present)
    limit_margin_um: float = 500.0

    # Stage XY fallback (escape hatch -- prefer LAS X markers).
    # All four must be set together (or all left None). Validated
    # against the physical envelope from stage.json; ValueError if
    # any value falls outside.
    stage_x_min_um: float | None = None
    stage_x_max_um: float | None = None
    stage_y_min_um: float | None = None
    stage_y_max_um: float | None = None


@dataclass
class Context:
    cfg: Config
    client: Any                              # LAS X CAM API client
    hw: Any                                  # drv.get_hardware_info(...)
    calibration: dict                        # drv.load_calibration()
    stage_config: dict                       # drv.load_stage_config()
    engine: "engine.Engine"
    out_dir: Path
    current_job: str                         # tracked locally; updated lazily
    templates_dir: Path                      # required after preflight (D9);
                                             # preflight resolves it via
                                             # drv.find_scanning_templates_dir()
                                             # and hard-fails if None.
    boundary_limits: dict | None = None      # set in Step 1
    scan_field: dict | None = None           # set in Step 2
    _shutdown_done: bool = False             # used by D20 idempotency

    def shutdown(self) -> None:
        """Idempotent. Stops engine workers. Safe to call multiple times."""
```

### 5.2 `preflight.py`

```python
def preflight(cfg: Config) -> Context:
    """Connect, load calibration, validate slots, force source objective,
    create output dir, boot Engine, register the overview pipeline.

    - Warns (does not abort) if cellpose conda env is missing (D9, D15).
    - Reads source-objective z-galvo and warns if `|zgalvo| > 0.5 um`
      (D3); records value under summary.json `preflight.source_zgalvo_um`.
    - Registers an atexit hook that idempotently calls ctx.shutdown()
      (D20).
    - If cfg.smoke_test_pipeline is True: runs a synchronous
      synthetic-tile submit, drains and discards the result
      (failure entries are *cumulative* in the engine and cannot
      be removed -- D19's `failure_count_before` snapshot, taken
      after preflight returns, is what excludes any pre-Step-4
      failures from this run's accounting).
    """
```

### 5.3 `template.py`

```python
def prepare_template(ctx: Context) -> None:
    """Step 1: read boundary markers, set XY + z-wide stage limits,
    strip template, enforce z-wide on every job (overview, AF,
    target). z-galvo is not used by this workflow (D2)."""

def read_scan_field(ctx: Context) -> None:
    """Step 2: parse Navigator Expert positions; synthesize tiles
    from geometries if needed; populate ctx.scan_field."""

def plot_scan_field(ctx: Context) -> None:
    """Visualisation only."""
```

### 5.4 `focus.py`

```python
@dataclass
class FocusMap:
    coeffs: np.ndarray            # plane coefficients [a, b, c]
    measured: list[dict]          # per-marker x_um, y_um, zwide_um
    residuals_um: np.ndarray

    def interpolate_zwide(self, x: float, y: float) -> float: ...
    def plot(self, ctx: Context) -> None: ...

def build_focus_map(ctx: Context) -> FocusMap:
    """Step 3: at each focus marker, run AF job, read back z-wide.
    Fit z-wide plane. Return FocusMap."""
```

### 5.5 `overview.py`

```python
@dataclass
class Pick:
    pick_id: tuple[str, int, int, int]   # (region_id, row, col, cell_label) -- region_id is str (template parser key); row/col/label are int

    # Provenance
    tile_stage_xy_um: tuple[float, float]
    tile_zwide_um: float                         # z-wide commanded at acquire; translator-ready
    source_pixel_size_um: tuple[float, float]    # (pw, ph) um/px
    source_image_size_px: tuple[int, int]        # (nx, ny)

    # Cell geometry (from cellpose / regionprops)
    centroid_col_row_px: tuple[float, float]     # (col, row) -- see D7 / 4.3
    bbox_px: tuple[int, int, int, int]           # (min_row, min_col, max_row, max_col)
    bbox_um: tuple[float, float]                 # (width, height)
    area_px: int
    eccentricity: float
    mean_intensity: float                        # always recorded for debug

    # Canonical pick address (pre-translation)
    cell_source_stage_xy_um: tuple[float, float]


@dataclass
class Picks:
    items: list[Pick]                            # the surviving picks Step 5 will acquire

    # Counters
    n_picks_raw: int                             # before any filtering
    n_picks_removed_duplicate: int
    n_picks_out_of_limits_xy: int
    n_picks_out_of_limits_z: int

    # Records of every removed pick, with reason (so plot_results
    # can render them and summary.json can audit them)
    removed_picks: list[dict]                    # each: {pick_id, reason: "duplicate"|"xy"|"z", ...pick fields...}

    # Failure buckets (D17)
    tile_acquire_failures: list[dict]            # drv.acquire_frame raised; never submitted
    engine_failures: list[dict]                  # only new failures since Step 4 start (D19)


def run_overview_with_picks(ctx: Context, focus_map: FocusMap) -> Picks:
    """Step 4: snake-acquire each tile with ACQUISITION_JOB, submit
    each tile to engine non-blocking, opportunistic + blocking drain
    (D19), dedup by cell coord (D5), filter out-of-limits (D6)."""
```

### 5.6 `target.py`

```python
@dataclass
class TargetRecord:
    pick_id: tuple[str, int, int, int]           # matches Pick.pick_id
    cell_source_stage_xy_um: tuple[float, float]
    source_zwide_um: float                       # = pick.tile_zwide_um
    target_stage_xy_um: tuple[float, float]
    target_zwide_um: float
    target_zoom: int
    target_pixel_size_um: float
    tif_path: Path | None
    success: bool
    error: str | None


def acquire_targets(ctx: Context, picks: Picks) -> list[TargetRecord]:
    """Step 5: switch to target job + objective once (in that order),
    sort picks by cell_source_stage_xy_um for travel; per pick:
    translate (cell_source_xy, tile_zwide_um) via
    drv.translate_xyz_between_objectives(...) -> (tx, ty, tz),
    compute zoom = drv.bbox_to_zoom(*bbox_um, target_base_fov_um,
    margin=cfg.fov_bbox_margin), set zoom, acquire, save_acquired(...),
    record.

    Per-pick failure isolation covers ALL per-pick steps -- not
    only acquire. If translation, zoom computation, or any move
    raises, the pick yields TargetRecord(success=False,
    error=str(exc), tif_path=None) and the loop continues."""
```

### 5.7 `summary.py`

```python
def write_summary(ctx: Context, picks: Picks,
                  records: list[TargetRecord]) -> Path:
    """Write summary.json into ctx.out_dir."""

def plot_results(ctx: Context, picks: Picks,
                 records: list[TargetRecord]) -> None:
    """Overview-frame plot: tiles + focus heatmap + markers for
    every pick. Markers are styled per category, all consumed from
    `picks` and `records`:

    - acquired   (TargetRecord.success == True)
    - failed     (TargetRecord.success == False)
    - duplicate  (in picks.removed_picks with reason == "duplicate")
    - out_of_xy  (reason == "xy")
    - out_of_z   (reason == "z")
    """
```

### 5.8 `_acquire.py`

```python
def acquire(ctx: Context, job: str, x_um: float, y_um: float,
            zwide_um: float) -> tuple[np.ndarray, Path]:
    """Lazy-switch job if needed, move XY, move z-wide, call
    drv.acquire_frame, return (image, lasx_path).

    Z is always commanded as z-wide (D2/D3); no z_mode parameter.
    Updates ctx.current_job in place when a switch happens.
    """

def save_acquired(image: np.ndarray, lasx_path: Path | None,
                  destination: Path) -> Path:
    """Persist an acquired frame to `destination` deterministically.

    - If lasx_path exists and is readable: copy it (preserves the
      LAS X OME-TIFF including any metadata LAS X writes).
    - Else: tifffile.imwrite the numpy array to `destination`.

    Returns the destination path actually written. Used by both
    Step 4 (overview tiles) and Step 5 (target frames) so on-disk
    layout is identical for both.
    """
```

---

## 6. Pipeline contracts (`smart-analysis/workflows/target_acquisition/`)

### 6.1 `pipelines/overview.yaml`

```yaml
metadata:
  purpose: "Per-tile cellpose segmentation + top-N pick selection"
  version: "1.0"
  verbose: 1
  functions_dir: "../steps"

overview:
  - segment_tile:
      diameter: null      # cellpose auto unless overridden
      channel: 0          # 2D, single channel for v1
      gpu: true

  - pick_targets:
      n_picks: 5
      feature: "area"     # rank field; one of: area, mean_intensity, eccentricity
```

### 6.2 `steps/segment_tile.py`

Contract:

- METADATA: `environment="SMART--target_acquisition--main"`, `max_workers=1`.
- Reads `pipeline_data["input"]["image_path"]`, params `diameter`, `channel`, `gpu`.
- Loads cellpose model into `state["model"]` on first call (warm).
- Reads the TIFF with `tifffile.imread`, takes `[channel, :, :]` if multi-channel.
- Writes `pipeline_data["segment_tile"] = {"masks": <ndarray>, "n_cells": int}`.

### 6.3 `steps/pick_targets.py`

Contract:

- METADATA: process isolation only (no env declared) -- runs in
  orchestrator's env (needs `numpy` + `scikit-image`, no GPU).
- Reads:
  - `pipeline_data["segment_tile"]["masks"]` (label image)
  - `pipeline_data["input"]` carrying:
    `tile_id`, `tile_stage_xy_um`, `tile_zwide_um`,
    `source_pixel_size_um=(pw, ph)`, `source_image_size_px=(nx, ny)`,
    `image_to_stage` (2x2 matrix from `calibration["image_to_stage"]`)
  - params: `n_picks` (int), `feature` (default `"area"`; one of
    `"area"`, `"mean_intensity"`, `"eccentricity"`).
- **`feature` validation:** if `feature` is not one of the
  three accepted strings, raise `ValueError` immediately. Hard
  failure is preferred to silent fallback because a misspelled
  ranking field would silently degrade pick quality.
- For each region in `regionprops(masks, intensity_image=tile_image)`:
  - Extract `centroid` (skimage's row, col), `bbox`, `area`,
    `eccentricity`, `mean_intensity`. Always record `mean_intensity`
    for debug regardless of ranking field.
  - Swap centroid order: `centroid_col_row_px = (centroid[1], centroid[0])`.
  - Compute `cell_source_stage_xy_um`:
    ```
    offset_px  = centroid_col_row_px - (nx/2, ny/2)
    offset_um  = offset_px * (pw, ph)               # elementwise
    delta_xy   = image_to_stage @ offset_um         # 2x2 matrix mul
    cell_source_stage_xy_um = tile_stage_xy_um + delta_xy
    ```
    Pure numpy -- no `drv` import needed in the worker.
  - Compute `bbox_um = ((max_col - min_col) * pw, (max_row - min_row) * ph)`.
  - `tile_zwide_um` is carried straight through to the Pick (the
    translator-ready Z; no per-pick Z math now that z-galvo is gone).
- Sort regions by `feature` descending, take top `n_picks`.
- **Empty-mask handling:** if `regionprops` returns nothing, write
  `pipeline_data["pick_targets"] = {"picks": []}` and return
  successfully. Empty tiles are normal (uneven samples); failing
  the pipeline on them would noisily abort an otherwise good
  survey.
- Writes `pipeline_data["pick_targets"] = {"picks": [<Pick dict>, ...]}`
  using the schema in 5.5.

**Why pixel->stage in the worker (not Step 5).** Picks become
self-contained, translator-ready addresses. Step 5 stays simple
(consume -> translate -> acquire). The 2x2 calibration matrix is
small enough to ship with each tile submission; no module imports
needed in the worker beyond `numpy` + `skimage`.

### 6.4 `environments/setup_env.py`

Mirror `rare_event_selection/environments/setup_env.py`:

- Detect conda root.
- `conda env create -n SMART--target_acquisition--main` with cellpose
  + torch + scikit-image + numpy + tifffile.

### 6.5 `tests/test_target_acquisition.py`

Synthetic tests, no LAS X dependency. Cellpose can be skipped if
not installed (mark `cellpose`, mirror smart-analysis's pattern).

Required test cases:

1. **Ranking.** Handcrafted mask with N known regions of distinct
   areas; assert `pick_targets` returns the top `n_picks` by area
   in descending order.
2. **Centroid order + pixel-to-stage.** Synthetic mask with a
   single cell at skimage-(row, col) = (100, 200), tile centre at
   `(nx/2, ny/2) = (256, 256)`, identity `image_to_stage`,
   `pixel_size_um = (0.5, 0.5)`, `tile_stage_xy_um = (1000, 2000)`.
   Assert `centroid_col_row_px ~= (200, 100)` and
   `cell_source_stage_xy_um ~= (1000 + (200 - 256) * 0.5,
                                2000 + (100 - 256) * 0.5)
                             == (972.0, 1922.0)`.
   This is the most dangerous class of bug here; the test catches
   any future regression in pixel-to-stage conversion.
3. **Non-identity `image_to_stage`.** Same as case 2 with a 90-deg
   rotation matrix; assert the conversion respects the matrix.
4. **Non-square frames.** `pixel_size_um=(0.5, 0.7)`,
   `image_size_px=(2048, 1024)`; assert `bbox_um` and
   `cell_source_stage_xy_um` use the right per-axis values.
5. **Empty mask.** Zero-region input; assert
   `pipeline_data["pick_targets"] == {"picks": []}` and no
   exception.
6. **Z carry-through.** Assert each pick's `tile_zwide_um` equals
   the value passed in `pipeline_data["input"]["tile_zwide_um"]`
   (the worker must not mangle Z).

---

## 7. Step-by-step sequence

| # | Step | Substeps |
|---|---|---|
| 0 | **Preflight** | 0.1 imports & paths ; 0.2 connect LAS X ; 0.3 load calibration & stage config ; 0.4 force source objective ; 0.5 read source-objective z-galvo, warn if `\|z\| > 0.5 um` (D3) ; 0.6 boot engine, register overview, env-presence check (warn if missing) ; 0.7 register atexit shutdown hook ; 0.8 create output dir |
| 1 | **Limits + template** | 1.1 stage XY limits (markers / config / fallback) ; 1.2 apply z-wide limits ; 1.3 strip template ; 1.4 enforce z-wide on every job (overview, AF, target) |
| 2 | **Scan field** | 2.1 parse template ; 2.2 synthesize tiles if geometry-only ; 2.3 visualise |
| 3 | **Focus map** | 3.1 read focus markers ; 3.2 per marker: move, AF acquire, read z-wide via `get_job_settings + make_changeable_copy + ["zPosition"]["z-wide"]` ; 3.3 fit z-wide plane ; 3.4 visualise |
| 4 | **Overview + live analysis** | 4.1 build snake order ; 4.2 per tile: `acquire(ACQ_JOB, x, y, zwide=focus_map.interpolate_zwide(x,y))`, save_acquired(...) to overview/, submit (path + tile_stage_xy_um + tile_zwide_um + source_pixel_size_um + source_image_size_px + image_to_stage) ; 4.3 opportunistic drain (accumulate per D19) ; 4.4 final drain: poll status until pending+running == 0 ; 4.5 print both `picks.tile_acquire_failures` and `picks.engine_failures` (the latter is `new_failures` per D19) ; 4.6 dedup by `cell_source_stage_xy_um` (D5) ; 4.7 filter out-of-limits XY+Z (D6) ; 4.8 short-circuit Step 5 if zero surviving picks (overview tile acquires already happened; target acquires are skipped) |
| 5 | **Target acquire** | 5.1 select_job(TARGET_JOB) + drv.set_objective(client, TARGET_JOB, hw, slot_index=TARGET_SLOT) + settle ; 5.1b read target z-galvo, compare against preflight; record drift in `target_state.zgalvo_drift_um` ; 5.2 read target base FOV via `drv.get_base_fov(client, TARGET_JOB)[0] * 1e6` ; 5.3 sort picks by `cell_source_stage_xy_um` ; 5.4 per pick (every step inside try/except, see 5.6 contract): translate via `drv.translate_xyz_between_objectives(cell_xy[0], cell_xy[1], pick.tile_zwide_um, cfg=ctx.calibration, from_slot=SOURCE_SLOT, to_slot=TARGET_SLOT)` -> (tx, ty, tz), `zoom = drv.bbox_to_zoom(*pick.bbox_um, target_base_fov_um, margin=cfg.fov_bbox_margin)`, set zoom, `acquire(TARGET_JOB, tx, ty, tz)`, save_acquired(...) to target/, record ; 5.5 per-pick failure isolation across the *entire* per-pick block (translate / zoom / move / acquire) |
| 6 | **Outputs + cleanup** | 6.1 write summary.json ; 6.2 plot results in overview frame ; 6.3 restore source objective (optional) ; 6.4 ctx.shutdown() (idempotent, D20) |

---

## 8. Output structure

```
<output_root>/
  <YYYYMMDD_HHMMSS>/
    overview/
      tile_R01_r00_c00.tif
      tile_R01_r00_c01.tif
      ...
    target/
      pick_R01_r02_c03_l017.tif
      pick_R01_r02_c03_l031.tif
      ...
    logs/
      engine.log                    (optional)
    summary.json
    overview_field.png              (Step 2 plot)
    focus_map.png                   (Step 3 plot)
    results.png                     (Step 6 plot)
```

### 8.1 `summary.json` schema (sketch)

```jsonc
{
  "timestamp": "20260506_153012",
  "config": { /* Config dataclass dump */ },
  "calibration_path": "...",
  "scan_field": {
    "n_regions": 2,
    "n_tiles": 64,
    "tile_size_um": 220.5
  },
  "focus_map": {
    "axis": "z-wide",
    "n_markers": 4,
    "z_range_um": 3.4,
    "tilt_x_deg": 0.012,
    "tilt_y_deg": -0.008,
    "max_residual_um": 0.21,
    "zwide_at_focus_markers_um": [...]
  },
  "preflight": {
    "source_zgalvo_um": 0.02,                 // (D3) warn if abs > 0.5
    "source_zgalvo_warning": false,
    "cellpose_env_present": true
  },
  "overview": {
    // Tile counters (define each precisely):
    "n_tiles_planned": 64,                    // length of snake-ordered tile sequence
    "n_tiles_acquired": 64,                   // = planned - tile_acquire_failed
    "n_tiles_submitted": 64,                  // = n_tiles_acquired (only successful acquires are submitted)
    "n_tiles_acquire_failed": 0,
    "tile_acquire_failures": [],              // list of {tile_id, error}
    "n_engine_failures": 0,
    "engine_failures": [],                    // new failures since Step 4 start (D19)
    // Pick counters:
    "n_picks_raw": 312,                       // produced by pick_targets across all tiles
    "n_picks_removed_duplicate": 11,          // removed by D5 dedup
    "n_picks_out_of_limits_xy": 0,            // removed by D6 XY filter
    "n_picks_out_of_limits_z": 0,             // removed by D6 Z filter
    "n_picks_final": 301                      // == n_picks_raw - n_picks_removed_duplicate - n_picks_out_of_limits_xy - n_picks_out_of_limits_z
  },
  "removed_picks": [                          // every pick dropped before Step 5, with reason
    {
      "pick_id": ["1", 2, 3, 47],
      "reason": "duplicate",
      "cell_source_stage_xy_um": [12345.6, -789.0],
      "winner_pick_id": ["1", 2, 3, 17]
    }
    // ...
  ],
  // target_state is present only when Step 5 actually starts.
  // When n_picks_final == 0 the target objective switch is skipped
  // and this key is omitted.
  "target_state": {
    "post_switch_zgalvo_um": 0.02,            // read after objective switch in Step 5.1b
    "zgalvo_drift_um": 0.00,                  // post_switch - preflight.source_zgalvo_um
    "zgalvo_drift_warning": false             // true if abs(drift) > 0.5
  },
  "picks": [
    {
      "pick_id": ["1", 2, 3, 17],            // (region_id_str, row, col, cell_label)
      "tile_stage_xy_um": [12300.0, -800.0],
      "tile_zwide_um": -40.87,
      "source_pixel_size_um": [0.323, 0.323],
      "source_image_size_px": [2048, 2048],
      "centroid_col_row_px": [512.3, 480.7],
      "bbox_px": [468, 500, 492, 524],
      "bbox_um": [12.4, 11.0],
      "area_px": 1840,
      "eccentricity": 0.41,
      "mean_intensity": 18234.5,
      "cell_source_stage_xy_um": [12345.6, -789.0]
    }
    // ...
  ],
  "targets": [
    {
      "pick_id": ["1", 2, 3, 17],
      "cell_source_stage_xy_um": [12345.6, -789.0],
      "source_zwide_um": -40.87,
      "target_stage_xy_um": [12348.1, -787.5],
      "target_zwide_um": -38.42,
      "target_zoom": 8,
      "target_pixel_size_um": 0.040,
      "tif_path": "target/pick_R01_r02_c03_l017.tif",
      "success": true,
      "error": null
    }
    // ...
  ]
}
```

---

## 9. Failure handling

| Failure | Behaviour |
|---|---|
| Conda env missing at preflight | Warn, continue (D9 / D15). |
| Source z-galvo non-zero at preflight | Warn, continue; recorded under `summary.json::preflight.source_zgalvo_um` (D3). |
| YAML registration fails | Hard abort -- legitimate config error. |
| Cellpose worker spawn fails | Failure surfaces in `engine.status("overview")["failures"]` (asynchronously). Step 4 keeps acquiring overview tiles for the rest of the snake order; new failures are reported each drain and recorded in `summary.json`. If every tile's segmentation failed and zero picks survive Step 4.6/4.7, Step 5 short-circuits (no target acquires). v1 does not auto-abort the survey. |
| Single tile segmentation crashes | Same path as above: failure appears in `status()["failures"]`; Step 4 keeps acquiring; failure recorded in summary. |
| Cellpose returns empty mask | Treated as success with `picks: []` (D17, 6.3). |
| `feature` param invalid in pick_targets YAML | Hard fail -- `ValueError` from `pick_targets`; surfaces as engine failure (6.3). |
| `acquire_frame` raises mid-survey | Tile recorded in `picks.tile_acquire_failures`; never submitted to engine; survey continues. |
| Pick translates outside stage limits | Recorded in `picks.removed_picks` with `reason="xy"` or `"z"`; counted; not acquired (D6). |
| Per-pick step in Step 5 raises (translate / zoom / move / acquire) | Target record `success=false, error=str(exc), tif_path=None`; loop continues (5.6). |
| Unexpected exception in notebook cell | Engine remains alive; user runs cleanup cell or relies on atexit hook (D20). |

---

## 10. Open questions before implementation

| # | Question | Default if unanswered |
|---|---|---|
| Q1 | Cellpose env name -- `SMART--target_acquisition--main`? | yes |
| Q2 | Output root path -- under `out_dir = .../navigator_expert/output/target_acquisition/<ts>/`? | yes |
| Q3 | Snake order vs nearest-neighbour for Step 5 stage travel? | snake by region then row/col |
| Q4 | Should `plot_results` overlay the *target* zoom box at each pick to preview framing? | yes |
| Q5 | Does `SMART--rare_event_selection--main` already exist on this workstation, and can its package set be reused as a base for `SMART--target_acquisition--main`? | confirm before writing setup_env.py |
| Q6 | Should `save_acquired` keep both the LAS X copy and the numpy write (when both are available), or only one? | only one -- LAS X copy preferred, fallback to numpy |

---

## 11. Out of scope for v1 (deferred)

- Refine pass (NCC / PCC / voting) at intermediate zoom.
- Z-stack target acquisitions (centred on `tz`).
- Multi-channel image handling beyond `channel=0`.
- AF on the target objective.
- Landing-error verification via morphology match.
- Cross-tile / cross-region global pick ranking (would require a
  scoped `pick_targets` step).
- Time-series / repeated revisits.
- Live preview of picks in the LAS X UI during Step 4.

---

## 12. Review checklist

For the operator reviewing this document before implementation:

- [ ] Slot numbers, job names, conda env name match the workstation reality.
- [ ] D2 / D3 (z-wide-only Z handling, z-galvo precondition warning) is the right approach for the hardware.
- [ ] D4 (top-N per tile) matches the desired pick semantics.
- [ ] D7 (cell_source_stage_xy_um as canonical address) matches "find targets back on the overview coord system".
- [ ] Output directory structure (section 8) is acceptable.
- [ ] Open questions Q1-Q6 are answered or accepted as defaults.
- [ ] Out-of-scope list (section 11) matches v1 expectations.

---

## 13. Changelog

**Rev 2.** Folded in two rounds of external review:

- D3: spelled out the z-galvo == 0 assumption at translator boundary
  and the post-switch warning policy (no blind force-to-zero).
- D5: switched dedup criterion from target-FOV-based to bbox-based,
  since framed zoom is per-pick.
- D6: extended the out-of-limits filter to include z-wide (was XY only).
- D7: split `source_stage_xy_um` into `tile_stage_xy_um` (provenance)
  and `cell_source_stage_xy_um` (canonical address); explicit
  centroid order `(col, row)`; per-axis `pixel_size_um` and
  `image_size_px` (non-square frames).
- D9: dropped the synchronous synthetic-tile smoke test from the
  default path; kept it behind `Config.smoke_test_pipeline`.
- D10: corrected `set_objective` keyword to `slot_index=...`.
- D11: split immutable `Config` from mutable `Context` (was
  incorrectly marked "frozen-after-init").
- D17 / D19 / D20: per-tile + per-target failure isolation, explicit
  drain semantics with consume-on-read buffering, idempotent
  `ctx.shutdown()` and atexit hook.
- 5.5 Pick: added `mean_intensity` (always recorded), per-axis
  pixel/image-size, both tile- and cell-source coords,
  `equivalent_zwide_um` field.
- 5.6 TargetRecord: replaced opaque `source` dict with explicit
  `cell_source_stage_xy_um` + `equivalent_zwide_um`.
- 5.8 `_acquire.py`: added `save_acquired(...)` -- LAS X copy
  preferred, numpy fallback; used by both Step 4 and Step 5.
- 6.3 pick_targets: documented pixel->stage math performed in the
  worker; explicit empty-mask handling.
- 6.5 tests: added required cases for centroid order,
  pixel-to-stage with identity and rotated `image_to_stage`,
  non-square frames, empty mask, and `equivalent_zwide_um`.
- summary.json schema: updated to new field names.
- ASCII normalization throughout (no em-dashes, no mu, no arrows,
  no box-drawing characters, no middle-dot list separators).

**Rev 3.** Second pass review fixes:

- Section 9: corrected the "first submit raises" wording. Engine
  `submit()` is async; worker failures surface via
  `status()["failures"]`. Step 4 reports new failures each drain
  and continues; v1 does not auto-abort on worker spawn failure.
- D19: `status()["failures"]` is cumulative for the registered
  pipeline name. Added `failure_count_before` snapshot at start of
  Step 4 so only the new tail is counted against this run; the
  drain-end assertion uses `new_failures` rather than the full
  list. Critical when D9's optional smoke test has already pushed
  failure entries into the list.
- D9: described the conda-env existence check as a private helper
  in `preflight.py` (delegates to `engine.conda_utils` if public,
  otherwise inspects `CONDA_ROOT/envs/`) instead of binding the
  design to a possibly-non-public engine API.
- D6: corrected stale field name -- now references the split
  `out_of_limits_xy_count` / `out_of_limits_z_count` per the Pick
  dataclass.
- 4.2 data flow: corrected `cfg["image_to_stage"]` to
  `ctx.calibration["image_to_stage"]` (calibration lives on the
  mutable Context, not the immutable Config).
- D3 / Step 5.1b: spelled out the concrete API for reading target
  z-galvo (`get_job_settings` + `make_changeable_copy` + index
  `["zPosition"]["z-galvo"]`), matching what Step 3 already does.
  No new driver function required.

**Rev 4.** Third pass review fixes:

- D9 / D19: smoke-test result drained-and-discarded by preflight
  before returning, so it cannot leak into Step 4's buffer; the
  failure-count snapshot is taken after preflight returns.
- D17: print and count *new* failures only (per D19), not the
  cumulative `status()["failures"]` list. Failures split into two
  buckets: `tile_acquire_failures` (acquire raised pre-submit)
  vs `engine_failures` (worker / step crashed). Both surfaced in
  `summary.json`.
- 5.5 Picks: added `tile_acquire_failures` field; renamed
  `engine_failures` doc to clarify it's the new tail only.
- 8.1 summary.json: added `tile_acquire_failures`,
  `n_tiles_acquire_failed`, `n_engine_failures`,
  `n_tiles_planned`.
- D3 z-galvo read: aligned spelling with the rest of the doc
  (`drv.get_job_settings` not `lasx.get_job_settings`).

**Rev 5.** Z-galvo removed entirely:

- D2 rewritten: enforce z-wide on every job (overview, AF, target).
  No more per-job z-mode split.
- D3 rewritten: focus map is fit in z-wide, not z-galvo. Step 4
  commands z-wide directly from the fitted plane. The translator
  consumes the same value. One Z axis end-to-end. Removed the
  galvo-to-wide bridge identity (no untested hardware assumption
  to validate). Removed the post-switch z-galvo warning.
- 5.4 FocusMap: `interpolate_zgalvo` -> `interpolate_zwide`;
  `measured` no longer carries `zgalvo_um`.
- 5.5 Pick: dropped `tile_zgalvo_um` and `equivalent_zwide_um`.
  `tile_zwide_um` is the single Z field, used directly as the
  translator input.
- 5.6 TargetRecord: renamed `equivalent_zwide_um` to
  `source_zwide_um` (it equals `pick.tile_zwide_um`).
- 5.8 acquire helper: dropped the `z_mode` parameter; signature
  is `acquire(ctx, job, x_um, y_um, zwide_um)`.
- 6.3 pick_targets: no per-pick Z math; `tile_zwide_um` carried
  through unchanged.
- 6.5 tests: case 6 retired (no equivalent identity to verify);
  replaced with a Z carry-through assertion.
- Section 7 step table: Step 1.4 (z-wide on all jobs), Step 3.2
  (read z-wide), Step 4.2 (no z-galvo), Step 5 (no 5.1b z-galvo
  warning), Step 5.4 (translate with `tile_zwide_um`).
- Section 8 summary.json: dropped `target_state` block,
  `tile_zgalvo_um`, `equivalent_zwide_um`. Picks carry only
  `tile_zwide_um`. Targets carry `source_zwide_um`.
- Section 9 failure table: dropped the post-switch z-galvo row.
- Section 11: dropped the deferred D3 bench experiment (no longer
  needed).

**Rev 6 (this revision).** Stale-reference and consistency pass:

- D3: re-introduced an explicit z-galvo precondition. Preflight
  reads source-objective z-galvo and warns if `|z| > 0.5 um`;
  Step 5.1b re-reads after the objective switch and records any
  drift. The workflow still does not *command* z-galvo, but the
  read provides telemetry against the silent-failure mode where a
  non-zero z-galvo at preflight gets re-centred during the
  switch.
- Config: dropped `z_galvo_min` / `z_galvo_max` (no longer used).
- Config: renamed `restore_after_af` to `restore_template_after_af`
  for clarity.
- Step 4.2 step-table cell: added `source_image_size_px` to the
  submission payload (was already in the data-flow diagram and
  the pick_targets contract).
- Step 4.5: now prints both `tile_acquire_failures` and
  `engine_failures` (the engine list is the new tail per D19).
- Step 4.8 / failure table: clarified that Step 4 always finishes
  the tile snake order; Step 5 short-circuits when the surviving
  picks list is empty.
- Step 5.1b: re-added (z-galvo drift telemetry only -- no
  command, no abort).
- Step 5.4 / 5.6: spelled out the per-pick driver calls
  (`drv.translate_xyz_between_objectives`, `drv.bbox_to_zoom`,
  `drv.get_base_fov`) so implementation cannot diverge.
- 5.5 Picks: dropped `deduped_count`; added `n_picks_raw`,
  `n_picks_removed_duplicate`, `n_picks_out_of_limits_xy`,
  `n_picks_out_of_limits_z`, and `removed_picks: list[dict]`
  (with `reason` field). Plot and summary now have the data they
  promised.
- 5.7 plot_results: docstring spells out which categories come
  from which list.
- 5.5 Pick: `pick_id` typed as `tuple[str, int, int, int]` --
  region IDs come from the template parser as strings.
- 6.3 pick_targets: `feature` validation is hard-fail
  (`ValueError`) on unknown values.
- summary.json: new `preflight` block; new `removed_picks` list;
  new `target_state` block (post-switch z-galvo + drift); tile
  counters precisely defined inline.
- Section 9 failure table: new rows for source z-galvo warning,
  invalid `feature`, tile_acquire_failures bucket; per-pick
  failure row covers the entire per-pick block, not just acquire.
- Section 12 review checklist: D3 wording updated to z-wide-only.
- Changelog: prior "(this revision)" tags rewritten to plain
  "Rev N." for clarity.

**Rev 7 (this revision).** Stale-counter and wording cleanup:

- D5: dedup now references `picks.removed_picks` and
  `picks.n_picks_removed_duplicate` (was `picks.deduped_count`).
- D6: filter now references `picks.n_picks_out_of_limits_xy` and
  `picks.n_picks_out_of_limits_z` (were `*_count`); also writes to
  `picks.removed_picks` with `reason`.
- D2: softened "z-galvo not touched" to "never commands; only
  reads for telemetry" so it does not contradict D3.
- 5.2 preflight: corrected the "discards failure entries"
  wording. Failures are cumulative in the Engine and cannot be
  removed; D19's `failure_count_before` baseline is what
  excludes pre-Step-4 entries.
- D9 smoke section: same correction.
- 5.6 TargetRecord: `pick_id` typed `tuple[str, int, int, int]`
  to match Pick.
- summary.json: `pick_id` examples normalised to
  `["1", 2, 3, 17]`; `n_picks_final` formula spelled out
  explicitly (`raw - duplicate - xy - z`); `target_state` block
  documented as conditional (omitted when Step 5 short-circuits).

**Rev 8.** Notebook split: implementation goes into a brand-new
`smart_microscopy_v3.ipynb`. The existing `_v2` is left untouched
as a reference. Sections 1, 2.1, 2.2, 2.3, D2, and 4.1 updated
accordingly. No design changes.

**Rev 9 (this revision).** Stage-limits source-of-truth pass:

- Step 1 reads stage XY from LAS X boundary markers (primary) and
  the physical envelope from `stage.json` (safety ceiling).
  Operator never types coordinates.
- `Config` no longer has `z_wide_min` / `z_wide_max` -- z-wide
  envelope always comes from `stage.json` via
  `ctx.stage_config["limits_um"]["z_wide"]`. z-galvo same.
- `Config.stage_x/y_min/max_um` demoted to `None`-defaulted
  fallback fields (escape hatch only). All four must be set
  together; partially set raises `ValueError`. Explicit values
  outside the physical envelope also raise.
- D6: out-of-limits Z filter now references the
  `stage_config["limits_um"]["z_wide"]` envelope, not removed
  Config fields.
- 5.1 Config dataclass updated: dropped z-wide fields, demoted XY
  to fallback, added the operator-doesn't-type-coordinates
  rationale at the top.
- v3 notebook Cell 2 has no stage / z-wide coordinates -- only
  slots, jobs, pick policy, paths, and behaviour flags.

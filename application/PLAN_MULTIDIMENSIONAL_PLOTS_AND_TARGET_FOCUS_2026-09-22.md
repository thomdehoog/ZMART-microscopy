# Plan: multidimensional plots on request, and focussing before each target

Two additions to the operator page, asked for on 2026-09-22 after the 864-field run. Neither is built.
Both follow the page's rule: the page composes and orchestrates, the bridge executes and answers.

## A. "Multidimensional plots" under Feature gating (Step 7)

### What the operator sees

A second white box under Feature gating, headed **Multidimensional plots**. In it:

- a row per plot that can be computed: **UMAP** and **Principal components**, each with a **Compute** press
  and, once computed, a sentence saying what it was computed over ("UMAP over 5,643 targets in the gates,
  2026-09-22 15:41") and a **Recompute** press;
- the population it runs over, said and chosen once for the box: **the targets in the gates** (default when
  a gate exists) or **every candidate**;
- a progress line while it runs, with Interrupt, like detection's.

When a plot lands, its two columns (`umap_1`/`umap_2`, `pc_1`/`pc_2`) appear in the axis pickers of the
feature plot above, and the plot can be gated on like any pair. The pickers already offer the union of every
cell's feature columns, so no picker work: the columns arrive on the cells and the pickers follow.

Nothing is computed unless pressed. Detection never waits on it again (it was removed from detection on
2026-09-22 because it grew with the population and stalled the run).

### Why on request, and over which cells

UMAP scales to the whole population: single-cell atlases run umap-learn over millions of cells on a
workstation, in minutes, once. What it does not do is come for free at every detection, which is why it
was taken out of detection on 2026-09-22 and comes back here on a press. No sample, no ceiling: the
press runs over the whole chosen population, and the sentence under it says how long the last one took.
Not yet measured on today's run (589,382 objects, 114 columns); see the note at the end.

The default population is the targets in the gates, the set the operator is about to refine; "every
candidate" is the first look at an ungated population, which is what UMAP is for.

The two plots share their conditioning: the components are computed first, UMAP runs on the first 50 of
them, so a UMAP press yields the components too, and a components press is the cheap half alone.

### Where it runs

In the bridge, in a worker process of its own (the shape `embedding.in_another_process` had: a child
process so umap's compile never blocks the bridge), reading its input from the population table the bridge
already writes (`overview_<hash>_objects.csv`) filtered to the ids the page sends. Conditioning as before:
identity and position columns out, per-field background out, median imputation, robust scaling, PCA to
at most 50 components, then UMAP with a pinned seed.

Routes, in the page-drives shape:

- `POST /api/plots/compute {kind: "umap"|"pca", ids: [...] | null}` starts it; refuses while one runs or
  while detection runs.
- `GET /api/plots/compute` answers `{running, kind, done, of, doing, error}` for the progress line.
- `POST /api/plots/compute/stop` puts the worker down (as detection's Interrupt does).
- The answer lands as columns: the bridge writes `overview_<hash>_<kind>.csv` (id and the two columns)
  beside the population table, and the page fetches it once when `running` turns
  false and merges the two columns into its cells by id.

The page's `live.js` gets one verb, `computePlot({kind, ids, onDoing, onProgress})`, polled like detection;
the mock answers with a deterministic fake (two columns from a hash of the id), so the walk can press it.

### Environment

`umap-learn` goes back into `environment.yml`, in the operator's own environment (the worker is a child of
the bridge, not an analysis worker). PCA needs only scikit-learn, already present.

### Tests, first

- Bridge: compute on two fields' cells writes the columns file; `ids` restricts; a second compute while
  one runs is refused; stop puts the worker down; the conditioning is pinned on a fixture without umap.
- Page unit: `computePlot` polls and hands back the columns; the gate plot's pickers offer `umap_1` after a
  landing (the existing picker test, with the column arriving late).
- Walk: at Step 7, press Compute for principal components on the mock, see the pickers gain `pc_1`, choose
  it, and the plot redraws.

### Not in this plan

Any plot other than a 2-D scatter; t-SNE; computing on the analysis workers; a third population choice.

## B. "Target focussing settings" under Target acquisition settings (Step 9)

### What the operator sees

- The box now headed **Acquisition settings** is renamed **Target acquisition settings**.
- Under it, a second white box, **Target focussing settings**, with a checkbox **Focus before each
  target**. Unchecked (the default), the step is as today: every target is imaged at the height the focus
  map of Step 4 gives for its position. Checked, one settings line appears under the checkbox, in the
  shape of Step 9's own "Target acquisition settings" line and not Step 4's box: choose the focussing
  job in LAS X, press **Import**, and the line reads the job's optics and stack ("20x · 0.75 NA dry ·
  61 planes, 0.5 µm step"). It is a job of its own, recorded here; Step 4's job is not reused, since the
  targets are imaged at another magnification and need a focussing job at that one.
- The line warns, the way "Target acquisition settings" already warns "Same setting as for the overview
  scan", when the job imported is one already recorded elsewhere in the session: Step 4's focussing job
  ("Same job as the focus map's"), the overview job, or the target acquisition job ("Same job as the
  target acquisition's"). A warning, not a refusal: the operator may mean it, but a job left selected in
  LAS X from the step before is the usual cause, and it should be seen.
- The progress box during the run says which half it is in: "focussing on target 12 of 96" then "imaging
  target 12 of 96".

### What happens at each target when it is on

For each target tile, in order: drive to the tile's x, y and the map's z; capture one stack with the
target focussing job; score it and choose the peak the way the focus map does (`focus-peaks.js`, the same
metric and the same settle rule); drive to the peak; capture the target with the target acquisition job.
A stack whose peak cannot be chosen (flat, or the edge of the range) falls back to the map's height and is
said in the target's row ("focus not found, imaged at the map's height"). The focussing stack is filed as
its own acquisition (`target_focussing`) so it can be looked at, the way Step 4's stacks are.

### Where the loop lives

Today the target run is a bridge scan whose positions are the target tiles (`/api/scan` with the tiles
planned). Focussing before each target needs a per-position procedure between drive and capture. Two ways:

1. **Bridge:** the scan worker takes an optional `focus` in the scan request and, per position, captures the
   focussing stack, scores it and chooses the peak in Python before the target capture. Needs a Python peak
   chooser equivalent to `focus-peaks.js` (a second copy of one rule), and the bridge runs a procedure again,
   which is what the focus map was moved away from on 2026-09-21.
2. **Page:** the target run becomes a page-driven loop like the focus map's (`begin`, then per target
   `xyz` → `acquire` focussing → `score` → peak in the page → `xyz` → `acquire` target, then `end`), with or
   without focussing, one path. The bridge keeps a ledger (`GET /api/targets/acquire`) so a reopened page
   and the specs can read progress, as the focus map does. A stop lands after the capture in hand. A target
   costs seconds on the instrument, so the round trips cost nothing visible.

**Recommended: 2.** One loop for both cases, the peak rule in one place, the stop the page's own, and no
procedure in the bridge. The cost is that the target run's bridge scan path is replaced, not extended:
`main.js`'s run of Step 9, `live.js`'s verb, `mock.js`, the gallery's progress, and `walk.spec.js` Step 9 all
change together. That is a day, not an hour.

### Settings and records

The focussing job is recorded like every other job: the same recording slot, stored in the session under
`targetFocus` beside `targetType`, carried to the run's `settings` and into every target record
(`focus: {job, z_peak_um, z_map_um, found}`) so a later reading knows which height a target was imaged at
and why.

### Tests, first

- Page unit: the loop calls focussing capture and score only when the setting is on; a stack with no peak
  falls back to the map's height and marks the record; Interrupt stops after the capture in hand.
- Bridge: the ledger fills per target; scan refused while a target run has the stage.
- Walk: Step 9 with focussing on the mock (the mock's focussing job has a peak by construction), the
  progress box saying both halves, every target's record carrying `focus.found`.
- Mock: focussing off is byte-identical to today's records.

### Open questions for Thom

- Focus **once per scan area** instead of per tile is cheaper on the instrument and enough for flat
  samples. Offered as a later option in the same box, not built first.
- Whether the target focussing stack should be kept on disk for every target (it is one stack per target;
  at 96 targets that is 96 stacks) or only its curve.

## Order of work

Plan B first (Thom's order of need), then A. Each in its own commits, tests first, the walk once at the end
of each.

### B, the target run as the page's own loop with optional focussing

1. `parts/microscope/live.js`: a verb `acquireTargets({tiles, settings, focus, onProgress, onDoing})` that
   runs the loop: `POST /api/targets/acquire/begin` (clears the targets acquisition unless appending, resets
   the ledger, refuses while a scan or map has the stage), then per tile `xyz` → (`acquire` focussing →
   `score` → peak in the page via `focus-peaks.js` → `xyz` to the peak, when `focus`) → `acquire` targets
   → `POST /api/targets/acquire/landed {record, focus}` (the ledger), then `end`. `stopAcquireTargets()`
   sets the page's flag; the loop ends after the capture in hand. `mock.js`: the same verb, deterministic.
2. `framework/bridge.py`: the three routes and the ledger `_acquired = {running, done, of, records}`,
   `GET /api/targets/acquire` answering it; `_a_run_has_the_stage()` counts it. The targets scan path
   (`scanOverview` with `acquisition_type: "targets"`) is no longer used by the page and goes.
3. `framework/window/main.js` Step 9 run (`s.mode === "targets"`, lines ~913–1010 today): calls the new
   verb; `accountFor` per landed record as now; the record carries `focus: {job, z_map_um, z_peak_um, found}`.
4. `steps/acquire_targets/gallery.js`: "Target acquisition settings"; the **Target focussing settings**
   box: checkbox `#target-focus-on`, and when on a settings line through `ctx.recordingSlot` with key
   `targetFocus` (session slot `emptySlot("focussing", 1)` beside `targetType`), the same-job warning
   against `focusType`, `overviewType`, `targetType`. Progress says "focussing on target k of n" / "imaging
   target k of n". A row whose record says `focus.found === false` reads "focus not found, imaged at the
   map's height".
5. Tests: `live-targets.test.js` (the loop with and without focus, the fallback, the stop);
   `test_operator_bridge.py` (ledger, refusals); `walk.spec.js` Step 9 with focussing on the mock.

### A, the multidimensional plots box

1. `parts/analysis/plots.py` (the conditioning and the two computations, the child process), with
   `test_plots.py` pinning the conditioning without umap installed. `environment.yml`: `umap-learn>=0.5`.
2. `framework/bridge.py`: `/api/plots/compute` (POST, GET, stop) reading the population CSV, writing the
   columns file; tests as listed above.
3. `parts/microscope/live.js` + `mock.js`: `computePlot`.
4. `steps/refine_targets/gate.js`: the **Multidimensional plots** box under Feature gating; on landing,
   the columns merged into the cells by id (`ctx.landColumns(kind, rows)` in `main.js`), `redraw()`.
5. `walk.spec.js` Step 7: press Compute for the components on the mock, pick `pc_1`.

## The UMAP timing

Partly measured on 2026-09-22 (this desk PC, 24 cores) on today's population table, 597,063 rows,
122 columns, before Thom set the UMAP aside and the run was stopped:

| Stage | Time | Memory |
| --- | --- | --- |
| Read the CSV | 6.7 s | 0.74 GB |
| Condition 95 numeric columns | 2.6 s | 1.38 GB |
| PCA to 50 components, all rows | 0.3 s | 1.50 GB |
| UMAP on the first 50,000 rows (first call, numba compile included) | 62.7 s | 1.83 GB |
| UMAP on 200,000 and on all rows | not reached | |

So the components are free at any size, and UMAP's time at the whole population is still unmeasured.
Plan A is parked behind plan B; finish the measurement before building it.

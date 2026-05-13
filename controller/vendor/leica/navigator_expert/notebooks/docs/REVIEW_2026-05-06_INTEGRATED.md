# Smart Microscopy v3 Workflow — Integrated Review Report

**Date:** 2026-05-06
**Scope:** workflow package (`notebooks/workflow/`), v3 notebook (`smart_microscopy_v3.ipynb`),
design doc (`TARGET_ACQUISITION_DESIGN.md`), driver call sites, engine API & internals
(`_run.py`, `_pool.py`, `_loader.py`), smart-analysis stubs, worker IPC boundaries,
notebook re-execution paths, simulator-vs-real contract, Windows/network-share file handling.
**Reviewers:** Claude + Codex (independent passes), then Opus 4.6 gap analysis (6 parallel agents).

Three review passes consolidated into one report. The first two (Claude + Codex) covered
the workflow package, notebook, design doc, driver call sites, and engine API surface.
The gap analysis targeted blind spots: engine internals the first reviewers did not read,
worker subprocess boundaries, notebook re-execution paths, simulator-vs-real-worker contract,
Windows/network-share file handling, design-doc invariant verification, and operator UX.

Provenance per finding: **(Claude)**, **(Codex)**, **(both)**, or **(gap)**.

---

## Critical

### C1. `SIMULATE_PICKS = True` is committed in the v3 notebook with executed outputs **(Codex)**

**File:** `notebooks/smart_microscopy_v3.ipynb` simulator cell

The notebook ships with the simulator flag enabled and the synthetic-pick
injection cell already executed (10 picks). On a real microscope, Run-All
injects fake picks after Step 4 returns empty (v0 stubs) and Step 5 then
acquires "targets" at random stage positions.

**Fix:** default `SIMULATE_PICKS = False`, clear all notebook outputs
(especially the simulator output line), and ideally guard the cell with a
runtime check (e.g., raise unless `cfg.smoke_test_pipeline` or an explicit
`SIMULATOR_OK` env var is set).

---

## High

### H1. Focus-map step ignores return values from `select_job`, `move_xy`, and AF `acquire` **(both)**

**File:** `workflow/focus.py:221, 230, 231`

```python
drv.select_job(client, cfg.af_job)         # L221 — ignored
drv.move_xy(client, fp["x_um"], fp["y_um"])    # L230 — ignored
drv_acquire(client, cfg.af_job)             # L231 — ignored
settings = drv.get_job_settings(client, cfg.af_job)
```

All three return `{"success": ..., ...}` rather than raising on driver-level
failure. If `move_xy` fails, AF runs at the previous stage position; if
`acquire` fails, `get_job_settings` returns whatever z-wide LAS X currently
has. The fitted plane silently absorbs the bad samples.

**Fix:** capture each return, require `success`, raise on failure with the
marker index.

### H2. `drv.set_stage_limits(...)` return is never checked **(Codex)**

**File:** `workflow/template.py:132, 235`

After computing XY/Z limits, the workflow fires `drv.set_stage_limits(...)`
and immediately reads back via `drv.get_stage_limits()`. If LAS X rejects the
limits, the readback may report old or partial limits but the workflow proceeds.
Step 4's out-of-limits filter then runs against wrong bounds.

**Fix:** capture the result, require success, and raise before updating
`ctx.boundary_limits`.

### H3. Strip-to-restore regions are not wrapped in `try/finally` **(Codex)**

**Files:**
- `workflow/focus.py:219` strip → `:239` restore
- `workflow/overview.py:80` strip → `:192` restore
- `workflow/target.py:59` strip → `:195` restore

Any exception between strip and restore leaves the LAS X template in the
stripped state. The next run's `prepare_template` then overwrites the
operator's original markers with the stripped state — silent data loss.

**Fix:** wrap each strip-to-restore region in `try/finally`.

### H4. `plot_results` mis-categorizes surviving picks as "acquired" when records is empty **(both)**

**File:** `workflow/summary.py:170-178`

```python
if rec and rec.success:
    categories["acquired"]["picks"].append(...)
elif rec:
    categories["failed"]["picks"].append(...)
else:
    categories["acquired"]["picks"].append(...)   # <-- wrong
```

If Step 5 short-circuits, raises during setup, or is simply not run before
plotting, every surviving pick lands in "acquired" and the plot lies.

**Fix:** add a "pending" / "not_acquired" category for the `rec is None` case.

### H5. `finish()` updates `ctx.current_job` without confirming `select_job` / `set_objective` succeeded **(both)**

**File:** `workflow/summary.py:248-253`

Both functions return `{"success": False, ...}` on driver-level failure; the
`try/except` only catches Python exceptions. A failed restore prints
"Restored source objective" anyway and `ctx.current_job` is now wrong.

**Fix:** check `success` on both calls; only mutate `ctx.current_job` on
confirmed success.

### H6. Translation failures break the documented `n_picks_final` invariant **(Claude)**

**Files:** `workflow/overview.py:46-58, 178-189`, `workflow/summary.py:73-77`,
design `8.1`

Translation failures land in `picks.removed_picks` with
`reason="translation"` but `Picks` has no counter. The design's invariant
silently breaks whenever `translate_xyz_between_objectives` raises.

**Fix:** add `n_picks_translation_failures: int = 0` to `Picks`; surface in
summary and update the invariant in the design doc.

### H7. `shutdown(wait=False)` abandons queued tasks without recording failures **(gap)**

**Citation:** `engine/_pipeline.py:79-101`, `engine/_pipeline.py:292-298`

When `shutdown(wait=False)` fires, tasks still on the heap are never popped;
their futures hang in PENDING state forever. No failure is recorded in
`status()["failures"]`, and `status()["pending"]` remains positive
indefinitely. `_n_submitted` is already incremented, so the engine's
bookkeeping is permanently wrong if inspected after a partial shutdown.

**Fix:** In `_PriorityThreadPool.shutdown()`, drain the heap after setting
the flag and cancel/fail each remaining future. Or record synthetic failures
for pending submissions.

### H8. Engine failure list has complementary bugs that break scoped-phase accounting **(gap)**

**Citation:** `engine/_run.py:258-269`, `workflow/overview.py:93-96`

**(a)** `_collect_phase0` builds `remaining_failures` but never assigns it
back to `self._failures`. Failures accumulate unboundedly. For Phase-0-only
pipelines this is benign; for scoped phases it causes silent double-counting.

**(b)** If (a) is fixed naively, the overview workflow's index-based
`failure_count_before` snapshot breaks: mid-run scope-collection can shrink
`_failures`, causing index overshoot.

Both bugs are dormant in the current Phase-0-only configuration.

**Fix:** Either make `_failures` permanently append-only (remove the dead
`remaining_failures` code), or add the assignment AND change `overview.py`
to diff failures by identity/timestamp rather than by list index.

---

## Medium

### M1. `Context.shutdown` from atexit can hang the kernel **(Claude)**

**Files:** `workflow/context.py:109-117`, `workflow/preflight.py:163`

`engine.shutdown()` is called with `wait=True`. If an acquire is mid-flight
or a worker is loading cellpose, kernel teardown blocks indefinitely.

**Fix:** propagate `wait=False` through `Context.shutdown` for the atexit
hook.

### M2. Step 4 drain loop has no timeout **(Codex)**

**File:** `workflow/overview.py:149-155`

A stuck worker leaves the loop spinning forever; the notebook cell hangs.

**Fix:** add a timeout (e.g., `cfg.drain_timeout_s`), and on expiry log
status, hard-fail with `engine.shutdown(wait=False)`.

### M3. Setup failure in `acquire_targets` aborts before `write_summary` can capture it **(Claude)**

**File:** `workflow/target.py:56-107`

If strip / select_job / set_objective fails, the exception re-raises.
`records` is never assigned — `write_summary` then fails with `NameError`.

**Fix:** catch in `acquire_targets` and return a sentinel (`[]`) so
write_summary can still run; or document the operator should wrap Step 5
in try/except.

### M4. Focus plane fit doesn't validate rank or geometry **(both)**

**File:** `workflow/focus.py:241-248`

With ≤2 or collinear markers, `lstsq` returns a minimum-norm solution; the
plane's tilt along the unspanned axis is whatever lstsq picks.

**Fix:** require `len(measured) >= 3` and check
`np.linalg.matrix_rank(A) == 3`; degrade to constant plane with warning.

### M5. `_filter_out_of_limits` return-type annotation is stale **(both)**

**File:** `workflow/overview.py:293-296`

Annotation says 3-tuple but the body returns 4 lists. Both call sites unpack
4 correctly.

**Fix:** fix the annotation.

### M6. Design doc has multiple stale references **(Codex)**

**File:** `notebooks/TARGET_ACQUISITION_DESIGN.md`

- L648: `preflight(cfg)` → current is `preflight(cfg, client)`.
- L725: `Picks` schema missing `simulated`.
- L771, L962: per-pick zoom / `bbox_to_zoom` (removed).
- L1039: old field names `zgalvo_drift_um` / `zgalvo_drift_warning`.

**Fix:** reconciliation pass (implementation is authoritative).

### M7. Engine result-shape coupling is brittle for future scoped pipelines **(Claude)**

**File:** `workflow/overview.py:236-256`

`_collect_picks_from_results` reads `result["pick_targets"]["picks"]`.
If/when scoped phases are added, the shape may differ. Not broken today.

**Fix:** defer until scopes are introduced; document the contract.

### M8. `publish_result` shallow-copies `pipeline_data`, mutating the stored Phase 0 dict **(gap)**

**Citation:** `engine/_pipeline.py:354-360`, `engine/_run.py:187-192`

`dict()` is a shallow copy, so nested sub-dicts are shared. `publish_result`
mutates its argument by injecting `_phase`, `_scope`, `_scope_level`.
For Phase-0-only pipelines the path is not reached; for future scoped phases
the stored Phase 0 result carries stale publish metadata into scope-phase input.

**Fix:** use `copy.deepcopy(pipeline_data)` or inject metadata on a fresh dict.

### M9. `drain_results()` / `status()` TOCTOU race in the drain loop **(gap)**

**Citation:** `engine/_run.py:298-306`, `engine/_pipeline.py:358-361`,
`workflow/overview.py:149-164`

The workflow reads `status()` then `results()` without a shared lock.
Between these two calls, a concurrent completion can publish a result or
decrement pending. The assertion could fire. The 50 ms sleep makes this
extremely unlikely in practice.

**Fix:** add a final `buffer.extend(engine.results("overview"))` after
exiting the drain loop to sweep any result published in the window.

### M10. numpy scalar types contaminate `Pick` fields after IPC round-trip **(gap)**

**Citation:** `workflow/overview.py:251-253`, `workflow/target.py:155-156`

When the real `pick_targets` step lands, values from
`skimage.measure.regionprops` will be numpy scalar types. These propagate
through the entire workflow and can cause `TypeError` in unexpected locations.

**Fix:** cast scalar fields in `_collect_picks_from_results`:
`area_px=int(pd["area_px"])`, `eccentricity=float(pd["eccentricity"])`, etc.

### M11. atexit hooks accumulate on preflight rerun; previous Engine leaks **(gap)**

**Citation:** `preflight.py:92`, `preflight.py:163`

Each call to `preflight()` creates a new `Engine()` and registers a new
`atexit` hook. The old `ctx` is overwritten but never shut down. Old workers
remain alive and all old atexit hooks try to join orphaned workers at kernel exit.

**Fix:** accept an optional `previous_ctx` parameter in `preflight()`; if
provided, call `previous_ctx.shutdown()` first. Or add a notebook guard:
`if 'ctx' in dir(): ctx.shutdown()`.

### M12. `finish()` never runs if `plot_results` raises in Cell 14 **(gap)**

**Citation:** `smart_microscopy_v3.ipynb` Cell 14,
`workflow/summary.py:107-239`, `:242-259`

Cell 14 executes `write_summary`, `plot_results`, `finish` in sequence.
If `plot_results` raises, `finish(ctx)` never runs and engine workers
remain alive. The atexit hook (M1) hangs with `wait=True`.

**Fix:** `try: plot_results(...) finally: finish(ctx)`. Or split `finish`
into its own cell.

### M13. Dedicated cleanup cell from D20 is missing **(gap)**

**Citation:** `TARGET_ACQUISITION_DESIGN.md:469-484` vs. notebook cell listing

D20 specifies a dedicated cleanup cell (`try: ctx.shutdown() except
NameError: pass`). No such cell exists. If any earlier step fails, the
operator has no recovery cell.

**Fix:** add a final cell matching D20 — one cell, three lines.

### M14. Simulator cell skips `_dedup_picks`, exercising a different pipeline shape **(gap)**

**Citation:** `smart_microscopy_v3.ipynb` simulator cell (cell id `e7cec76e`);
cf. `workflow/overview.py:175-178`

The simulator constructs picks and passes them directly to
`_filter_out_of_limits`, skipping `_dedup_picks`. Overlapping synthetic cells
survive when they would be collapsed in production, hiding dedup-related bugs.

**Fix:** insert `deduped, removed_dup = _dedup_picks(synthetic_picks)` before
the filter call.

### M15. `summary.json` written non-atomically to network share **(gap)**

**Citation:** `workflow/summary.py:102`

`out_path.write_text(json.dumps(...))` writes directly to the final path on
`Z:\`. Network drop mid-write leaves the file truncated with no recovery.

**Fix:** write to `summary.json.tmp`, flush + `os.fsync`, then `os.replace`.

### M16. "0 picks" with v0 stubs is indistinguishable from a real engine failure **(gap)**

**Citation:** `workflow/overview.py:182-187`

When the engine uses v0 stubs, every tile returns zero picks. The preflight
`UserWarning` about the missing conda env appears in a different cell. By
Step 4, there is no in-context reminder that 0 picks is expected.

**Fix:** if `n_picks_raw == 0` and cellpose env was not found, print:
`[step 4] NOTE: 0 picks expected -- cellpose env not found (v0 stubs).`

### M17. Step 5 silently consumes stale picks when run out of cell order **(gap)**

**Citation:** `workflow/target.py:50-52`

`acquire_targets` receives `picks` as a function argument. Re-running Step 5
without re-running Step 4 uses the object from a previous run (possibly with
stale coordinates from a repositioned sample). No staleness guard exists.

**Fix:** stamp `picks` with `ctx.out_dir.name` at end of
`run_overview_with_picks`; check at top of `acquire_targets`.

---

## Low

- **L1.** `Config.fov_bbox_margin` is unused (dead since per-pick zoom removal).
  Notebook still passes `fov_bbox_margin=1.5`. Remove. *(Claude)*
- **L2.** `TargetRecord.target_zoom` is always `None`; serialized as `null`.
  Drop field and serializer line. *(Claude)*
- **L3.** Unused imports in `workflow/template.py:19` (`Path`) and `:27`
  (`STRIPPED_XML`). *(Codex)*
- **L4.** Inconsistent `select_job` import style: `focus.py:221` uses
  `drv.select_job`; other files use `drv_select_job` alias. Pick one.
  *(Codex/Claude)*
- **L5.** `r = drv_select_job(...)` at `summary.py:248` is unused local.
  Becomes useful once H5 is fixed. *(Claude)*
- **L6.** `_strip_and_enforce_zwide` mutates the LRP directly instead of going
  through `apply_lrp_change`. z-wide enforcement is best-effort, so Low.
  *(Claude)*
- **L7.** `Pick.bbox_px` order `(min_row, min_col, max_row, max_col)` is never
  validated at construction time. *(Claude)*
- **L8.** `read_scan_field`'s `save_experiment(TEMPLATE_XML, ...)` overwrites
  on-disk markers. Re-running `prepare_template` after Step 2 falls through
  to the cfg/envelope path. By design, but worth a docstring note. *(Claude)*
- **L9.** pickle protocol 2 hardcoded in engine IPC (`engine/_worker.py:212`,
  `engine/worker_script.py:158`). Both sides are Python 3; no reason for
  protocol 2. Use `pickle.DEFAULT_PROTOCOL` or protocol 5. *(gap)*
- **L10.** KeyboardInterrupt during Step 5 per-pick loop skips template restore
  (`workflow/target.py:136-189`). Ctrl+C propagates past restore at L195.
  Arguably correct design. Wrap in `try/finally` for single-interrupt
  robustness, or document the trade-off. *(gap)*
- **L11.** `save_acquired` silently falls back to numpy TIFF without logging
  (`workflow/_acquire.py:64-68`). If `shutil.copy2` fails, the fallback loses
  all OME metadata with no record. Log a warning when the fallback fires.
  *(gap)*

---

## What was verified working

Both initial reviews and the gap analysis independently confirmed:

- No `cfg=calibration` keyword anywhere — `translate_xyz_between_objectives`
  called with `calibration` as 4th positional arg in both call sites.
- No `drv.acquire(...)` calls. Module-vs-function shadow correctly dodged.
- No `drv.TEMPLATE_*` references. Constants imported from
  `navigator_expert.driver.scanning_templates` directly.
- No `bbox_to_zoom` references in the workflow package.
- `set_objective(client, job_name, hw_info, *, slot_index=...)` signature
  respected at all three call sites.
- Engine drain assertion holds for Phase-0-only pipelines.
- Engine submission payload matches the `pick_targets` contract.
- `ctx.shutdown` is idempotent via `_shutdown_done` flag.
- `Picks.simulated` serialized into `summary.json["overview"]["simulated"]`.
- `tif_path` serialized relative to `out_dir`; gracefully `None` for failures.
- `Engine.shutdown(wait=False)` supported by engine API.
- `py_compile` passes on the workflow package.
- Format spec `:>02s` zero-pads correctly in CPython 3.12.
- D5 dedup: threshold `0.75 * max(bbox_diag)` matches implementation exactly.
- D6 out-of-limits: XY from `ctx.boundary_limits`, Z from
  `stage_config["limits_um"]["z_wide"]` — correct.
- D7 conventions: centroid (col, row), bbox (min_row, min_col, max_row,
  max_col), bbox_um (width, height) — consistent everywhere.
- D10 boundary order: target.py does select_job → set_objective → settle;
  preflight does not violate.
- D19 failure_count_before: safe for Phase-0-only (append-only list).
- Phase 0 result ordering: out of submission order, but workflow does not
  depend on ordering.
- No metadata key collision: `_phase`, `_scope`, `_scope_level` do not collide
  with `pick_targets`, `segment_tile`, `input`, `metadata`.
- Simulator centroid/bbox/bbox_um conventions match D7 exactly.
- `.bak` recoverability: original XML recoverable via
  `drv.load_experiment(TEMPLATE_XML)`.

---

## Summary

| Severity | Count | IDs |
|----------|-------|-----|
| Critical | 1     | C1 |
| High     | 8     | H1–H8 |
| Medium   | 17    | M1–M17 |
| Low      | 11    | L1–L11 |
| **Total** | **37** | |

---

## Recommended fix order

### Immediate (one afternoon)

1. **C1** (clear notebook + flip flag) — 5 min, prevents garbage acquisitions.
2. **H3** (try/finally around strip/restore) — prevents data loss across crashes.
3. **M13** (add D20 cleanup cell) — 1 cell, 3 lines; closes the gap for M12 and M1.
4. **M12** (try/finally in Cell 14) — prevents zombie engine on plot failure.
5. **M11** (preflight rerun guard) — prevents engine leak on retry.
6. **H1** (focus AF return checks) — most consequential silent-corruption path.
7. **H2** + **H5** (set_stage_limits + finish() return checks) — cheap plumbing.
8. **H4** (plot_results pending category) — the plot is the artifact you show.
9. **H6** (translation failure counter) — schema change; tackle while touching `Picks`.

### Before real `pick_targets` lands

10. **M10** (cast numpy scalars in `_collect_picks_from_results`).
11. **M14** (add dedup to simulator cell) — makes simulator exercise real pipeline shape.
12. **M1** (atexit `wait=False`) — 10-line change, prevents kernel hangs.
13. **M2** (drain loop timeout) — pair with M1.
14. **M3** (setup failure summary capture).
15. **M4** (focus plane rank check) — pair with H1.
16. **M5** (`_filter_out_of_limits` annotation) — 1-line fix.

### Before scoped phases are wired

17. **H8** (engine failure list fix) — choose append-only or diff-by-ID.
18. **H7** (shutdown records abandoned tasks).
19. **M8** (deepcopy in publish_result).

### When convenient

20. **M9** (final drain sweep after break) — one-line theoretical fix.
21. **M15** (atomic summary.json write).
22. **M16** + **M17** (UX: 0-picks note, stale-picks guard).
23. **M6** (design doc reconciliation) — separate session after code settles.
24. **M7** (result-shape coupling) — defer until scopes are introduced.
25. **L1–L11** — cleanup commit after the above lands.

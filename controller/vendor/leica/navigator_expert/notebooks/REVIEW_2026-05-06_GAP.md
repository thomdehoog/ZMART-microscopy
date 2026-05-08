# Smart Microscopy v3 Workflow -- Gap Analysis

**Date:** 2026-05-06
**Scope:** Blind spots from REVIEW_2026-05-06.md. Engine internals
(`_run.py`, `_pool.py`, `_loader.py`), worker IPC boundaries, notebook
re-execution paths, simulator-vs-real contract, Windows/network-share
file handling, design-doc invariant verification, operator UX.
**Method:** Six parallel agents, one per category. Each read files the
original reviewers did not, or traced scenarios they did not cover.

---

## High

### G1. `shutdown(wait=False)` abandons queued tasks without recording failures

**Category:** 1 (Engine internals)
**Citation:** `engine/_pipeline.py:79-101`, `engine/_pipeline.py:292-298`

When `shutdown(wait=False)` fires (e.g., preflight hard-fail path at
`preflight.py:122-124`), the `_PriorityThreadPool` sets `_shutdown =
True` and notifies idle workers. Tasks still on the heap are never
popped; their futures hang in PENDING state forever. No failure is
recorded in `status()["failures"]` for these abandoned submissions, and
`status()["pending"]` remains positive indefinitely. The workflow's
drain assertion (`len(buffer) + len(new_failures) == n_submitted`)
would fail if the drain loop were reached after a partial shutdown.

More importantly, `_n_submitted` is already incremented at
`next_submission_idx()` time, so the engine's bookkeeping is
permanently wrong if it is reused or inspected after a partial
shutdown.

**Fix:** In `_PriorityThreadPool.shutdown()`, drain the heap after
setting the flag and cancel/fail each remaining future. Or have
`Engine.shutdown(wait=False)` record synthetic failures for pending
submissions.

### G2. Engine failure list has complementary bugs that break scoped-phase accounting

**Category:** 1 + 6 (Engine internals + Design-doc invariants)
**Citation:** `engine/_run.py:258-269` (`_collect_phase0`),
`workflow/overview.py:93-96` (failure_count_before snapshot)

Two sides of the same coin:

**(a)** `_collect_phase0` builds a `remaining_failures` list that
partitions `self._failures` into matched (returned to the scoped
phase) and unmatched, but **never assigns `remaining_failures` back to
`self._failures`**. Failures therefore accumulate unboundedly. For
Phase-0-only pipelines this is benign (the overview workflow's
index-based D19 snapshot works because the list is append-only). For
scoped phases it means failures from one scope group leak into the
next group's failure collection -- silent double-counting.

**(b)** If someone fixes (a) by adding the assignment, the overview
workflow's `failure_count_before = len(status["failures"])` snapshot
breaks: mid-run scope-collection signals can shrink `_failures`,
causing the index to overshoot and either skip legitimate new failures
or raise an IndexError.

For the current Phase-0-only configuration both bugs are dormant. They
activate the moment a scoped phase is wired into the overview pipeline.

**Fix:** Either (a) make `_failures` permanently append-only and
document that contract (remove the dead `remaining_failures` code), or
(b) add `self._failures = remaining_failures` AND change
`overview.py` to diff failures by identity/timestamp rather than by
list index.

---

## Medium

### G3. `publish_result` shallow-copies `pipeline_data`, mutating the stored Phase 0 dict

**Category:** 1 (Engine internals)
**Citation:** `engine/_pipeline.py:354-360`, `engine/_run.py:187-192`

When Phase 1+ scoped phases exist, `_execute_phase0` stores the
original `pipeline_data` dict and then calls
`publish_result(dict(pipeline_data), ...)`. `dict()` is a shallow
copy, so nested sub-dicts (`metadata`, `input`, `pick_targets`) are
shared between the stored copy and the published copy. `publish_result`
then mutates its argument by injecting `_phase`, `_scope`,
`_scope_level` keys. For Phase-0-only pipelines this path is not
reached. For future scoped phases the stored Phase 0 result carries
stale publish metadata into the scope-phase input.

**Fix:** Use `copy.deepcopy(pipeline_data)` in the `publish_result`
call, or inject metadata on a fresh dict.

### G4. `drain_results()` / `status()` TOCTOU race in the drain loop

**Category:** 1 (Engine internals)
**Citation:** `engine/_run.py:298-306`, `engine/_pipeline.py:358-361`,
`workflow/overview.py:149-164`

The workflow reads `status()` then `results()` without a shared lock.
Inside the engine, Phase 0 completion calls `publish_result` (puts
result on queue) then `record_completion` (decrements pending). Between
these two calls, `pending > 0` but the result is already queued. The
reverse window also exists: `status()` reads `pending == 0` while a
concurrent completion publishes between the two calls. The assertion
`len(buffer) + len(new_failures) == n_submitted` could fire.

The 50 ms sleep makes this extremely unlikely in practice but it is a
correctness gap.

**Fix:** Add a final `buffer.extend(engine.results("overview"))` after
exiting the drain loop (after the `break`) to sweep any result
published in the status/results window.

### G5. numpy scalar types contaminate `Pick` fields after IPC round-trip

**Category:** 2 (Worker IPC)
**Citation:** `workflow/overview.py:251-253` (`_collect_picks_from_results`),
`workflow/target.py:155-156`

When the real `pick_targets` step lands, values from
`skimage.measure.regionprops` will be numpy scalar types (`np.int64`
for `area_px`, `np.float64` for `eccentricity`, `mean_intensity`).
These pickle-roundtrip intact through the engine's protocol-2 IPC.
`_collect_picks_from_results` passes them directly into the `Pick`
dataclass without casting. The type annotations (`area_px: int`) are
not enforced at runtime.

This is harmless for arithmetic and formatting, but `summary.py`'s
`_json_default` fallback only fires for the top-level `json.dumps`
call, not for nested dicts constructed elsewhere. And numpy scalars
propagate through the entire workflow, making debugging harder when
they eventually cause a `TypeError` in an unexpected location.

**Fix:** In `_collect_picks_from_results`, cast scalar fields:
`area_px=int(pd["area_px"])`, `eccentricity=float(pd["eccentricity"])`,
etc. Same for `pick_id` integer elements.

### G6. atexit hooks accumulate on preflight rerun; previous Engine leaks

**Category:** 3 (Notebook re-execution)
**Citation:** `preflight.py:92` (new `Engine()`), `preflight.py:163`
(`atexit.register`)

Each call to `preflight()` creates a new `Engine()` and registers a
new `atexit` hook bound to the new `ctx`. The old `ctx` is overwritten
in the notebook namespace but never shut down. The old Engine's thread
pool and subprocess workers remain alive. Each old atexit hook still
references a distinct `ctx` with `_shutdown_done = False`, so all of
them will try to join their respective (now-orphaned) workers at kernel
exit.

On a long Jupyter session with several retries this can exhaust OS
threads and sockets.

**Fix:** Accept an optional `previous_ctx` parameter in `preflight()`;
if provided, call `previous_ctx.shutdown()` before booting the new
engine. Or: add `if 'ctx' in dir(): ctx.shutdown()` as a notebook
guard before `ctx = preflight(...)`.

### G7. `finish()` never runs if `plot_results` raises in Cell 14

**Category:** 3 (Notebook re-execution)
**Citation:** `smart_microscopy_v3.ipynb` Cell 14,
`workflow/summary.py:107-239` (`plot_results`), `:242-259` (`finish`)

Cell 14 executes `write_summary`, `plot_results`, `finish` in
sequence. If `plot_results` raises (matplotlib backend, missing data,
unwritable output dir), Python stops the cell. `finish(ctx)` never
runs, `ctx.shutdown()` is never called, engine workers remain alive.
The atexit hook is the only backstop, but per M1 it hangs with
`wait=True`.

**Fix:** Wrap in try/finally: `try: plot_results(...) finally:
finish(ctx)`. Or split `finish(ctx)` into its own cell.

### G8. Dedicated cleanup cell from D20 is missing

**Category:** 3 (Notebook re-execution)
**Citation:** `TARGET_ACQUISITION_DESIGN.md:469-484` (D20 spec) vs.
`smart_microscopy_v3.ipynb` (cell listing)

D20 specifies a dedicated cleanup cell:
```python
try:
    ctx.shutdown()
except NameError:
    pass
```
No such cell exists. The last code cell (Cell 14) bundles `finish(ctx)`
with `write_summary` and `plot_results`. If any earlier step fails,
the operator has no obvious recovery cell.

**Fix:** Add a final cell matching D20. One cell, three lines.

### G9. Simulator cell skips `_dedup_picks`, exercising a different pipeline shape

**Category:** 4 (Simulator vs real contract)
**Citation:** `smart_microscopy_v3.ipynb` simulator cell (cell id
`e7cec76e`); cf. `workflow/overview.py:175-178`

The simulator constructs synthetic picks and passes them directly to
`_filter_out_of_limits`, skipping `_dedup_picks` entirely. The real
path in `run_overview_with_picks` runs dedup first. Overlapping
synthetic cells (easily generated by `random.uniform` offsets) survive
when they would be collapsed in production. Step 5 then acquires
redundant targets, and `picks.n_picks_removed_duplicate` stays at 0.

The simulator exercises a different pipeline shape from the real path,
hiding any dedup-related bugs.

**Fix:** Insert `deduped, removed_dup = _dedup_picks(synthetic_picks)`
before the filter call. Import `_dedup_picks` alongside
`_filter_out_of_limits`.

### G10. `summary.json` written non-atomically to network share

**Category:** 5 (File handling)
**Citation:** `workflow/summary.py:102`

`out_path.write_text(json.dumps(...))` writes directly to the final
path on `Z:\`. If the network drops mid-write or the process is
killed, the file is left truncated or zero-length with no recovery.
The driver module already uses `_wait_file_stable` and
write-then-rename patterns, but `summary.json` has no such protection.

**Fix:** Write to `summary.json.tmp`, flush + `os.fsync`, then
`os.replace` to the final name.

### G11. "0 picks" with v0 stubs is indistinguishable from a real engine failure

**Category:** 7 (Operator UX)
**Citation:** `workflow/overview.py:182-187`

When the engine uses v0 stubs, every tile returns zero picks. Preflight
emits a `UserWarning` about the missing conda env, but that appears in
a different cell (Cell 3). By the time the operator reaches Step 4
output, there is no in-context reminder that 0 picks is expected.

**Fix:** After the picks summary print, if `n_picks_raw == 0` and the
cellpose env was not found, print a contextual note:
`[step 4] NOTE: 0 picks expected -- cellpose env not found (v0 stubs).`

### G12. Step 5 silently consumes stale picks when run out of cell order

**Category:** 7 (Operator UX)
**Citation:** `workflow/target.py:50-52`

`acquire_targets` receives `picks` as a function argument. If the
operator re-runs Step 5 without re-running Step 4, the `picks` variable
holds the object from a previous run (possibly with stale coordinates
from a repositioned sample). There is no staleness guard.

**Fix:** Stamp `picks` with `ctx.out_dir.name` (the run timestamp) at
the end of `run_overview_with_picks`; check it at the top of
`acquire_targets`.

---

## Low

### G13. pickle protocol 2 hardcoded in engine IPC

**Category:** 2 (Worker IPC)
**Citation:** `engine/_worker.py:212`, `engine/worker_script.py:158`

Both sides hardcode `pickle.dumps(..., protocol=2)`. Protocol 2 is the
Python 2.x ceiling, slower and more memory-hungry than protocols 4/5
for large objects. Since both orchestrator and worker are Python 3,
there is no reason to stay on protocol 2.

**Fix:** Use `pickle.DEFAULT_PROTOCOL` or explicitly protocol 5.

### G14. KeyboardInterrupt during Step 5 per-pick loop skips template restore

**Category:** 6 (Design-doc invariants, D17)
**Citation:** `workflow/target.py:136-189`

The per-pick `try/except Exception` correctly does not catch
`KeyboardInterrupt` (operator should be able to interrupt). But
`KeyboardInterrupt` propagates past the per-pick handler and the
post-loop `restore_template` call at line 195. A second Ctrl+C during
`restore_template` itself leaves the microscope with the stripped
template and target objective active. The atexit handler shuts down
the engine but does not restore the template or source objective.

This is arguably correct design (Ctrl+C should work), but the cleanup
guarantee is lost.

**Fix:** Wrap the per-pick loop + post-loop restore in `try/finally`
for single-interrupt robustness. Or document that Ctrl+C may leave
the microscope in an intermediate state.

### G15. `save_acquired` silently falls back to numpy TIFF without logging

**Category:** 5 (File handling)
**Citation:** `workflow/_acquire.py:64-68`

If `shutil.copy2(lasx_path, destination)` fails (file lock, antivirus
scan, SMB oplock break), the fallback writes a numpy-only TIFF,
silently losing all OME metadata. Neither the caller nor summary.json
records that the fallback fired.

**Fix:** Log a warning when the OSError fallback fires.

---

## Covered by existing report (not new)

- D6 return-type annotation on `_filter_out_of_limits` -- **REPORT.M5**
- Scenario 2 (rerun Step 1 after Step 2 ran) -- no new finding beyond
  **REPORT.L8** (markers lost on re-strip, recoverable via
  `load_experiment(TEMPLATE_XML)`)
- Concern 4 (ephemeral LAS X export path in Step 5) -- no finding;
  `save_acquired` copies synchronously before next acquire

## Verified working (negative signals)

- D5 dedup: threshold `0.75 * max(bbox_diag)` matches implementation
  exactly (`overview.py:259-290`)
- D6 out-of-limits: substantive logic correct; XY from
  `ctx.boundary_limits`, Z from `stage_config["limits_um"]["z_wide"]`
- D7 conventions: centroid (col, row), bbox (min_row, min_col,
  max_row, max_col), bbox_um (width, height) -- consistent everywhere
- D10 boundary order: target.py does select_job -> set_objective ->
  settle; preflight does not violate (only touches source objective)
- D19 failure_count_before: safe for Phase-0-only (append-only list);
  index is stable; smoke-test failures are below the baseline
- Phase 0 result ordering: out of submission order, but workflow does
  not depend on ordering (flat buffer + dedup)
- No metadata key collision: `_phase`, `_scope`, `_scope_level` do not
  collide with `pick_targets`, `segment_tile`, `input`, `metadata`
- Simulator centroid/bbox/bbox_um conventions match D7 exactly
- `.bak` recoverability after H3: original XML is recoverable via
  `drv.load_experiment(TEMPLATE_XML)` (backups are made inside
  `restore_template`, not `strip_template`, so they don't exist in
  the H3 scenario -- but the original XML was never deleted)

---

## Summary

| Severity | Count | IDs |
|----------|-------|-----|
| High     | 2     | G1, G2 |
| Medium   | 10    | G3-G12 |
| Low      | 3     | G13-G15 |
| **Total new** | **15** | |

### Fix order recommendation

**Immediate (pair with existing H-fixes):**

1. **G8** (add D20 cleanup cell) -- 1 cell, 3 lines; closes the gap
   for G7 and M1.
2. **G7** (try/finally in Cell 14) -- prevents zombie engine on plot
   failure.
3. **G6** (preflight rerun guard) -- prevents engine leak on retry.

**Before real pick_targets lands:**

4. **G5** (cast numpy scalars in `_collect_picks_from_results`) --
   prevents type contamination throughout the workflow.
5. **G9** (add dedup to simulator cell) -- makes simulator exercise
   the real pipeline shape.

**Before scoped phases are wired:**

6. **G2** (engine failure list fix) -- choose append-only or diff-by-ID.
7. **G1** (shutdown records abandoned tasks) -- prevents silent task
   loss.
8. **G3** (deepcopy in publish_result) -- prevents cross-phase
   contamination.

**When convenient:**

9. **G4** (final drain sweep after break) -- one-line theoretical fix.
10. **G10** (atomic summary.json write) -- write-then-rename.
11. **G11** + **G12** (UX: 0-picks note, stale-picks guard).
12. **G13-G15** (low-severity cleanup).

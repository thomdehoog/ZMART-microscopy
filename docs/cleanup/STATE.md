# Cleanup state — pick up here

> Historical note: this file records the older `cleanup/wave-2` cleanup plan.
> It is not the active branch state for `restructure/layered-driver`.
Last updated: 2026-05-05.

A future-you / future-Claude reads this first when working on cleanup.
The branch graph and commit messages are the source of truth for *what
changed*; this doc captures *why*, *what's next*, and *what not to touch*.

## Where we are

Active branch: `cleanup/wave-2` at `5c5db95`.

```
* cleanup/wave-2     5c5db95 chore(tooling): pyproject.toml (ruff, calibration excluded)
* cleanup/wave-2     fd2b0a4 baseline: snapshot 25 summary.json from 2026-05-04
* cleanup/production 9f43df2 calibration: persist 10x->20x/40x values
* cleanup/production 95dcb41 fix(readers): retry get_job_settings when imageSize blank
* cleanup/production 0419a9e cleanup(examples): drop unused lasx_api / DEFAULT_APPLY_BACKLASH / dangling comment
* cleanup/production 3c78f1a chore(gitignore): *.zip, .pytest_cache, nested .claude settings
* clean-refactor     78942e2 [trusted baseline — last validated end-to-end on 2026-05-04]
```

Working tree on `cleanup/wave-2`: tracked files clean. Untracked = 3
personal notebooks (`smart_microscopy_codex.ipynb`,
`smart_microscopy_user.ipynb`, `t_user.ipynb`) plus ~45 binary run
outputs (`.tif`, `.png`) inside the example-script output dirs. The
binaries are individually listed because the parent dirs got partially
tracked when JSONs were force-added — same files that existed before,
just enumerated differently now.

## Historical Constraints

This file records the older `cleanup/wave-2` cleanup plan. It is
historical context, not the active structure for
`restructure/layered-driver`.

1. **Driver and calibration were off-limits for that cleanup wave.**
   That constraint no longer applies to this restructuring branch, where
   the driver and calibration package layout were intentionally cleaned.

2. **The 3 example scripts are the integration test.** They must run
   end-to-end on the microscope after every cleanup wave:
   - `workflows/vendor/leica/navigator_expert/examples/galvo_zoom_in.py`
   - `workflows/vendor/leica/navigator_expert/examples/segment_and_define_rois.py`
   - `workflows/vendor/leica/navigator_expert/examples/objective_switch_target.py`

3. **Don't extend mocks for `commands.py` or `confirmations.py`.**
   Mock-vs-real divergence has bitten before. Live runs are the truth.

4. **Calibration is a two-acquisition process.** A z-stack alone is not
   enough; there is also a separate XY registration acquisition.

## What's already done in this cleanup effort

- **Phase 0 — tooling baseline.** `pyproject.toml` with ruff config.
  Conservative starter rule set (E, F, W, I, UP, B). Calibration tree
  excluded. No tools have actually been *run* yet — config only.
- **Phase 1 partial.** `.gitignore` extended (`*.zip`,
  `.pytest_cache/`, nested `.claude/settings.local.json`). Removed
  unused `lasx_api` import alias from the 3 example scripts. Removed
  the `DEFAULT_APPLY_BACKLASH` constant (defined-never-read in all 3
  example scripts). Removed dangling `# drv.read_zwide_um lives in...`
  breadcrumb in `objective_switch_target.py`.
- **Driver fix (not strictly cleanup).** `get_job_settings` in
  `driver/core/readers.py` now treats a populated-but-empty-`imageSize`
  response as transient and lets the retry loop wait. Surfaced during
  the slow LAS X session on 2026-05-04.
- **Calibration values.** New 10x->20x and 10x->40x calibration values
  committed (the values that worked yesterday). Slot 0 (40x WATER) is
  a new entry; slot 2 (20x DRY) was refined.
- **Run-output JSON baseline.** 25 `summary.json` files from yesterday
  force-added as a known-good reference. Future cleanup phases that
  produce structurally divergent summaries should be reviewed.

## What's next

### Wave A — visible cleanup, low risk (continue on `cleanup/wave-2`)

Pure file moves and prose cleanup on the periphery only. None of
these change runtime behaviour or touch driver/calibration.
Hardware test once at the end of the wave.

Done:
- ✅ Removed `lasx_notes.zip`, `smart_microscopy.ipynb`,
  `smart_microscopy_codex.ipynb`, `smart_microscopy_user.ipynb`,
  `t_user.ipynb` from this branch (`31af51c`).
- ✅ Deleted top-level `analysis/` empty stubs (`f422776`).
- ✅ Moved 4 root spike scripts to `scripts/legacy/` (`34962dc`),
  then deleted the entire `scripts/legacy/` directory — they're not
  part of any active workflow and the supported example surface is
  `workflows/vendor/leica/navigator_expert/examples/`. Anything
  still useful from the spikes can be pulled from git history.
- ✅ Moved `smart_microscopy_v2.ipynb` to
  `workflows/vendor/leica/navigator_expert/target_acquisition/smart_microscopy_v3.2.ipynb` — the
  notebook lives inside the package as a subfolder, keeping the
  repo root free of notebook clutter (`5b32460` → relocated later
  this session).
- ✅ Trimmed empty whitespace under the LAS X interaction banners
  in all 3 example scripts (`32c94ee`).

**Wave A pending only:** end-of-wave hardware test — run all 3
example scripts + `calibrate_objectives.py` once. If any misbehaves,
bisect by commit on `cleanup/wave-2` and revert.

**Deferred from Wave A** items were handled later on
`restructure/layered-driver`.

### Wave B — test-suite cleanup, low-medium risk (next branch off Wave A)

Driver and calibration off-limits, so the dead-code removal in
`driver/` is now deferred. What remains in Wave B is the test-suite
cleanup, which only changes import statements in tests:

- `test/test_unit.py` now imports canonical `navigator_expert.core`
  modules directly. `test/conftest.py` only sets import paths and no
  longer installs `lasx.*` aliases.

**Deferred from Wave B**: no known driver cleanup items remain here.

### Then — production-prep (further out)

- Phase 5: coverage gap analysis. Run pytest under coverage, commit
  the report to `docs/cleanup/coverage/<date>/`. Expected dark zones:
  `commands.py` (44KB), `confirmations.py` (46KB),
  `driver/acquisition/files.py`, `driver/positions/parsers.py`, and the large core command/readback modules.
- Phase 6: targeted unit tests for pure-Python helpers
  (`pick_cell_by_distance_rank`, `measure_landing_error_by_morphology`,
  `_intermediate_zoom_for`, `bbox_to_zoom`, `pixels_to_roi`,
  `extract_polygon_rois`, the calibration translators). Property
  tests via Hypothesis for the calibration sign-convention math.
  **Do not** extend `mock_lasx_api.py` to cover commands or
  confirmations.
- Phase 7: incremental refactors of internal driver APIs, *only*
  behind the coverage built in Phase 6, *only* one boundary at a
  time, *each* gated on a real example-script run.

### Later cleanup context

- Calibration state later moved out of the Leica driver package to
  `calibration/vendor/leica/navigator_expert/current/` on
  `restructure/layered-driver`.
- Flattening `driver/vendor/leica/navigator_expert/` to
  `src/navigator_expert/`. Multi-day; rewrites every import statement
  in the codebase. Worthwhile but its own dedicated workstream.

## Sequencing rule

Each wave's contract:
1. Per-commit grep evidence for any deletion.
2. End-of-wave hardware run of the 3 example scripts.
3. If anything regresses, bisect on the wave branch and revert.
4. Only merge the wave back to `clean-refactor` after the hardware
   run is clean.

Coverage-gated refactors (Phase 7+) carry an additional rule: each
refactor commit comes with new tests added in Phase 6 already proving
the boundary's behaviour, *and* a hardware run of the affected
example script before merge.

## How to test what's already on this branch

```
git switch cleanup/wave-2
python workflows/vendor/leica/navigator_expert/examples/galvo_zoom_in.py
python workflows/vendor/leica/navigator_expert/examples/segment_and_define_rois.py
python workflows/vendor/leica/navigator_expert/examples/objective_switch_target.py
```

Same invocation as the validated 78942e2 baseline. CLI args unchanged.

Rollback to the trusted baseline at any time:
```
git switch clean-refactor
```

## Findings — hardware test 2026-05-05

Wave-2 hardware run (3 example scripts, 10x/20x):

- `objective_switch_target.py` 10x->20x — pass, landing 6.04 um.
- `galvo_zoom_in.py` — pass, landing 2.17 um.
- `segment_and_define_rois.py` (110 ROIs) — failed first attempt
  with `PermissionError` on the LRP file (verify_fn opened the file
  while LAS X still held the write handle); the script's own retry
  loop succeeded on attempt 4 (timeouts ballooned 0.5s -> 1s -> 2s).
- Re-run of `objective_switch_target.py` immediately after the
  segment run — `get_hardware_info` timed out 3x and aborted before
  any acquire. LAS X looked wedged for at least the period of the
  retry, not just the single LRP write.

Pattern: mtime-poll save confirmation is racy *and* slow under load,
and after a heavy LRP write LAS X stops answering API calls for a
while. The existing retry loop only papers over the fast-confirm
race; it doesn't help with LAS X being locked up downstream.

This makes the existing `project_apply_lrp_change_fast_confirm_race`
note (memory) more concrete: not just a "next acquire fails" risk,
but a "heavier LRP writes wedge LAS X long enough that *unrelated*
reads time out" failure mode. Worth a clean diagnosis pass before
touching code — pin down whether the lockup is LAS X processing the
ROI batch, an LRP-load that hasn't actually finished, or a transport
issue similar to the startup `get_xy()` race.

## Open questions for next session

- Are the 3 untracked notebooks (`_codex`, `_user`, `t_user`)
  keepers? `t_user.ipynb` reads as an in-progress sandbox; the
  others may be experimental.
- Should the calibration-off-limits rule loosen specifically for the
  two-config-folders fix? It's a small surgical change to one line
  of path resolution, but it does live in calibration code.
- Pin ruff in a `requirements-dev.txt`, or defer until pre-commit
  setup?
- Once Wave A is done, the `driver/vendor/leica/navigator_expert/`
  layout is the next big visual-mess signal. Decide whether to
  schedule the flatten as Wave C or punt indefinitely.

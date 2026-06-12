# Conference Readiness Review - `fable5_tryout`

Date: 2026-06-12  
Branch reviewed: `fable5_tryout`  
Remote state: `HEAD` is pushed to `origin/fable5_tryout` at `b08388b` (`Split driver core into commands and runtime`).

## Verdict

The pushed branch is technically strong enough to discuss and demonstrate: the repository now has a clear two-root structure (`microscopes/`, `workflows/`), the Leica Navigator Expert driver is organized into coherent packages, the selected-job reader problem has a measured hybrid solution, and the workflow tests pass.

It is not yet "clean" in the strict release-engineering sense because the current lint baseline fails and this local checkout contains untracked runtime artifacts. Those are cleanup/readiness issues, not evidence that the hybrid reader or workflow implementation is broken.

## Findings

### Blocking For A Polished Conference Snapshot

1. **Local checkout is not clean, even though the pushed branch is.**  
   `git status --short --branch` reports `fable5_tryout...origin/fable5_tryout` with no tracked deltas, but 22 untracked files remain locally: 19 hardware JSONL records and 3 worked notebooks. The pushed branch is clean; this working directory is not. Before packaging or sharing from this checkout, either archive/remove those files or add explicit ignore rules. Current `.gitignore` only ignores hardware outputs ending in `*_results.jsonl` ([.gitignore](../../.gitignore:17)), while several untracked files are named without that suffix.

2. **`ruff check .` fails the current repository baseline.**  
   The configured lint policy is active in [pyproject.toml](../../pyproject.toml:20) and selects `E`, `F`, `W`, `I`, `UP`, and `B` rules, but the repo currently reports 227 findings. Most are import-order cleanup, but there are real hygiene items mixed in: unused imports, unused variables, lambda assignments, and one undefined annotation name. Example concrete hits:
   - `F821 Undefined name Path` at [image_to_stage.py](../calibration/vendor/leica/navigator_expert/core/image_to_stage.py:90). `from __future__ import annotations` makes this nonfatal at import time, but static checking is right to flag it.
   - `F401` unused `_default_error_check` import at [dispatch.py](../driver/vendor/leica/navigator_expert/commands/dispatch.py:45).
   - `E731` lambda assignments at [commands.py](../driver/vendor/leica/navigator_expert/commands/commands.py:136), [commands.py](../driver/vendor/leica/navigator_expert/commands/commands.py:141), and [commands.py](../driver/vendor/leica/navigator_expert/commands/commands.py:143).

### Non-Blocking But Worth Fixing Before A Public Repo Link

3. **The root README is clear, but intentionally admits the agnostic layer is not production-ready.**  
   This is honest and probably fine for a conference, but the wording should be understood as part of the public story: the Leica driver is production-tested; the cross-microscope layer is under construction ([README.md](../../README.md:12), [README.md](../../README.md:46)).

4. **Historical docs still contain old path names by design.**  
   Current code and READMEs have moved from `core/` to `commands/` + `runtime/`, but historical notes under `microscopes/docs/` still reference old paths. I would not rewrite those unless they are explicitly framed as current instructions; they are evidence/history. Current active scans found no live `navigator_expert.core` imports except the separate calibration package imports (`calibration.vendor.leica.navigator_expert.core`), which are valid.

5. **The committed validation story is good, but there are many raw measurement files.**  
   Twelve JSONL evidence files are tracked intentionally. Many more runtime JSONLs are ignored or untracked. For conference sharing, keep the curated evidence and avoid presenting the whole hardware folder as a tidy artifact archive.

## What Changed On This Branch

### Repository Shape

The repo now presents two main folders:

- `microscopes/`: microscope-facing code and configuration.
- `workflows/`: smart-microscopy workflows.

The root README now says exactly that and points users to:

- Leica driver: `microscopes/driver/vendor/leica/navigator_expert/`
- Target acquisition workflow: `workflows/target_acquisition/`

Removed or retired from the branch:

- `workflows/examples/`
- `CLAUDE.md`
- old `both` reader naming in active code/docs, replaced by `hybrid`

### Leica Driver Organization

The Leica Navigator Expert driver now has a cleaner package structure:

- `commands/`: command wrappers, dispatch, confirmations, objective/settings/precheck command logic.
- `runtime/`: profiles, session runtime, errors, shared utilities.
- `state_readers/`: API/log/hybrid passive readers, capability table, log waits, change-wait diagnostics.
- `scanfields/`: scan-field parsing, planning, file I/O, strip/restore, transaction helpers.
- `acquisition/`: acquisition materialization, file watching, native autosave, OME handling.
- `stage/`: stage limits, config, and movement helpers.

The final split landed as `b08388b`.

### Reader And Confirmation Design

The important production change is not just "use both sources"; it is "use the first admissible evidence."

Current selected-job policy is in [profiles.py](../driver/vendor/leica/navigator_expert/runtime/profiles.py:103):

- Passive selected-job reads still default to API (`selected_job_mode = "api"` at [profiles.py](../driver/vendor/leica/navigator_expert/runtime/profiles.py:100)).
- Command confirmation defaults to hybrid (`selected_job_confirm_source = "hybrid"` at [profiles.py](../driver/vendor/leica/navigator_expert/runtime/profiles.py:113)).
- Hybrid races the API leg and log leg within one confirm attempt.

The selected-job race is centralized in [confirmations.py](../driver/vendor/leica/navigator_expert/commands/confirmations.py:1519):

- `api`: API poll only.
- `log`: post-command `CurrentBlock` wait only.
- `hybrid`: both legs race; the API leg requires transition evidence.

The critical stale-API guard is present: in hybrid mode, an API readback that already showed the target before the command is not admissible evidence for the command ([confirmations.py](../driver/vendor/leica/navigator_expert/commands/confirmations.py:1549)). No-op handling is also source-coherent: when log participates, fresh log state must prove the no-op; stale API cannot suppress a real command ([confirmations.py](../driver/vendor/leica/navigator_expert/commands/confirmations.py:1664)).

### Change-Wait Diagnostics

`state_readers/change_wait.py` remains diagnostic, not a command confirmation path. It answers "did anything visibly change?" by comparing each source against its own baseline and reporting disagreement rather than resolving it silently. The XY jitter threshold is now per-datum via `change_wait_xy_min_delta_um` ([profiles.py](../driver/vendor/leica/navigator_expert/runtime/profiles.py:137)).

### Scanfield Consolidation

The previous `positions` / `templates` split was merged into `scanfields/`. That name fits the Leica domain better: the code is about scan-field files and planned field geometry, not generic positions or reusable templates.

### Hardware Validator

The validator now supports three reader families:

- `api`
- `log`
- `hybrid`

`--state-reader-mode X` implies selected-job confirm source `X` unless explicitly overridden. XY validation now uses a 10-position pattern by default.

## Verification Run During This Review

### Offline Tests

These were run after the `commands/` + `runtime/` split:

| Suite | Result |
| --- | ---: |
| Leica driver unit tests | 468 passed, 62 subtests passed |
| Target-acquisition workflow tests | 250 passed, 9 matplotlib display warnings |
| Calibration + shared output-layout tests | 151 passed |
| Hardware pytest wrappers | 15 passed |

Total offline/pytest checks run in this review pass: 884 tests plus subtests.

### Live Hardware/Simulator Validator

On 2026-06-12, after the package split, the validator was run in all three reader modes with:

```powershell
--yes --allow-xy --allow-z --allow-objective --allow-acquire
```

This includes the 10-position XY pattern.

| Mode | PASS | WARN | FAIL | SKIP | Exit | XY moves |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `api` | 118 | 0 | 0 | 1 | 0 | 10 |
| `log` | 118 | 0 | 3 | 1 | 1 | 10 |
| `hybrid` | 118 | 0 | 0 | 1 | 0 | 10 |

The pure-log failures were not hybrid failures:

- passive `job: resolve` returned no jobs in log mode;
- `HiRes` log selected-job confirmation timed out while the state still read as `AF Job`;
- the separate log-poll check for `HiRes` timed out for the same reason.

Hybrid passed because the API leg produced admissible evidence when the log leg missed the event. That is the intended behavior of the race.

### Committed Real-Scope Evidence

The strongest acceptance record is the real-scope 10-XY matrix from 2026-06-11:

| Mode | PASS | WARN | FAIL | SKIP | Exit | XY moves |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `api` | 116 | 1 | 4 | 1 | 1 | 10 |
| `log` | 113 | 1 | 9 | 1 | 1 | 10 |
| `hybrid` | 120 | 2 | 0 | 0 | 0 | 10 |

Interpretation:

- API-only is not accepted for selected-job confirmation on the real microscope because selected-job readback is stale.
- Log-only is not accepted as a blanket default because passive/log availability has gaps.
- Hybrid is accepted because it confirms selected-job transitions through the admissible source available in that environment and fails closed otherwise.

## Review Of Conference Claims

### Claim: "The Leica driver works and is tested."

Supported, with scope. The driver is tested by:

- broad offline unit/integration-style tests;
- simulator/current hardware-validator runs;
- real-scope validator evidence;
- committed JSONL evidence for selected-job reader behavior.

The caveat is that "works" should mean "the Leica Navigator Expert path is production-tested"; the microscope-agnostic layer is explicitly not production-ready yet.

### Claim: "Hybrid is the robust reader strategy."

Supported. The data shows:

- simulator/current run: API and hybrid pass, log-only fails selected-job/log gaps;
- real-scope 10-XY run: hybrid passes with zero failures, API/log-only do not;
- the code enforces admissibility rather than first-response-wins.

### Claim: "Three reader families exist."

Supported. The public mode vocabulary is now `api`, `log`, `hybrid`; `both` is no longer the active naming in current validator/profile docs. Historical docs still mention `both` where they record old runs.

### Claim: "The repo is clean and sharable."

Partially supported.

The pushed branch is clean and structured. The local checkout is not clean because of untracked measurement artifacts and worked notebooks. Static lint also does not pass. I would phrase the conference state as:

> The branch is tested and architecturally coherent. It is suitable for a technical conference demo, but the repository should get a small hygiene pass before being presented as release-polished.

## Suggested Pre-Conference Cleanup

### High Priority

1. Decide what to do with local untracked files:
   - archive/remove the untracked JSONLs and worked notebooks; or
   - commit selected evidence intentionally; or
   - extend `.gitignore` so non-`*_results.jsonl` hardware outputs and `*_worked.ipynb` notebooks cannot pollute status.

2. Make `ruff check` meaningful:
   - either fix the current 227 findings;
   - or narrow the configured lint scope to the production packages you want to claim are lint-gated;
   - but do not leave a configured lint command that fails if "production ready" is the claim.

3. Fix the small concrete lint issues in current production paths:
   - remove unused `_default_error_check` from `commands/dispatch.py`;
   - replace or explicitly tolerate the lambda assignments in `commands/commands.py`;
   - import `Path` in calibration `image_to_stage.py` or change the annotation.

### Medium Priority

4. Add a short "Validation Summary" section to the root README pointing to:
   - `READER_VALIDATION_SIMULATOR_20260611.md`
   - `READER_VALIDATION_REAL_SCOPE_20260611_HYBRID_MATRIX.md`
   - this review report

5. Add a one-command test recipe to the root README:

```powershell
python -m pytest -q microscopes/driver/vendor/leica/navigator_expert/tests/unit
python -m pytest -q workflows/target_acquisition/tests
python -m pytest -q microscopes/calibration/vendor/leica/navigator_expert/tests microscopes/shared/output_layout/tests
```

6. Add a short "what is not production yet" note:
   - microscope-agnostic layer is in construction;
   - log-only selected-job on simulator is insufficient;
   - API-only selected-job on the real scope is rejected;
   - hybrid is the supported default.

### Low Priority

7. Rename `test_core_driver.py` eventually. The test name is now historical after the `commands/` + `runtime/` split. It is not a functional problem.

8. Consider moving raw hardware JSONL evidence out of `tests/hardware/` into a curated evidence folder, or keep only the specific committed records referenced by docs.

## Final Assessment

The branch has the right architecture and the central technical argument is well supported:

- API and log are both incomplete;
- their failures differ by environment and datum;
- hybrid confirmation works because it races admissible evidence, not responses;
- the validation data shows hybrid catching the weak side of each single-source reader.

For a conference demo, this is a strong story. For a public "production-ready" repository, I would do one more cleanup pass focused on lint baseline and local artifact hygiene.

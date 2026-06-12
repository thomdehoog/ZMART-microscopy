# Fable5 Tryout Synthesis

Date: 2026-06-12  
Branch: `fable5_tryout`  
Inputs synthesized:

- `CONFERENCE_READINESS_REVIEW_20260612.md`
- `TEST_CLEANUP_REFACTOR_PLAN_20260612.md`
- local deep review notes in `DEEP_REVIEW_FABLE5_TRYOUT_20260612.md`
- latest simulator/current hardware validator results
- committed real-scope hybrid reader evidence

## Executive Summary

The implementation is in better shape than the repository packaging around it.

No review found a correctness blocker in the shipping driver/workflow path. The Leica driver, hybrid reader/confirmation design, validation scripts, calibration state, shared algorithms, and output naming are all defensible. The central technical claim is strong: API-only and log-only each fail in different ways, while hybrid confirmation works because it accepts the first admissible evidence, not the first response.

What still prevents the branch from feeling clean, production-ready, and conference-shareable is hygiene:

1. lint baseline fails;
2. local runtime artifacts are untracked;
3. executed worked notebooks and output-bearing operator notebook cells need cleanup;
4. docs mix durable design notes with dated session scratch;
5. tests are correct but not organized as well as the code now is.

This is not a redesign problem. It is a focused cleanup branch.

## What Is Solid

### Hybrid Reader Story

The reader design should be kept.

- Three reader families now exist: `api`, `log`, `hybrid`.
- `hybrid` is the supported selected-job confirmation default.
- Selected-job confirmation is centralized in `commands/confirmations.py`.
- The API leg in hybrid is transition-admissible: stale API readback that already equals the target cannot confirm a command.
- The log leg uses post-command `CurrentBlock` evidence.
- No-op handling is source-coherent: when log participates, fresh log state must prove the no-op.

Evidence:

- Current simulator/latest validator run:
  - `api`: `118 PASS / 0 WARN / 0 FAIL / 1 SKIP`
  - `log`: `118 PASS / 0 WARN / 3 FAIL / 1 SKIP`
  - `hybrid`: `118 PASS / 0 WARN / 0 FAIL / 1 SKIP`
- Real-scope 10-XY matrix:
  - `api`: `116 PASS / 1 WARN / 4 FAIL / 1 SKIP`
  - `log`: `113 PASS / 1 WARN / 9 FAIL / 1 SKIP`
  - `hybrid`: `120 PASS / 2 WARN / 0 FAIL / 0 SKIP`

Interpretation: hybrid is not just a compromise. It is the only mode validated to handle both simulator/current behavior and real-scope behavior without environment-specific branching.

### Repo Shape

The new top-level structure is right:

- `microscopes/`
- `workflows/`

The Leica driver split is also right:

- `commands/`
- `runtime/`
- `state_readers/`
- `scanfields/`
- `acquisition/`
- `stage/`

`scanfields` is the right word for the former positions/templates ambiguity.

### Test Coverage

The offline test situation is strong:

- Driver unit tests pass.
- Workflow tests pass.
- Calibration/shared tests pass.
- Hardware pytest wrappers pass in mock/offline mode.

The tests are not fragile in the important sense. The problem is organization, naming, and lint hygiene.

### Safety

The hardware tooling is safe-by-default:

- live writes require `--yes`;
- XY/Z/objective/acquire are separately gated by `--allow-*`;
- validator restores state in `finally` paths;
- pure-log/hybrid failures are fail-closed, not guessed.

## What Is Not Clean Yet

### 1. Lint Baseline

`ruff check .` reports 227 findings. Most are mechanical:

- import sorting;
- unused imports;
- pyupgrade typing changes;
- explicit `strict=` on `zip`;
- a few lambda-assignment style issues.

The findings that matter most:

- missing `Path` import in calibration `image_to_stage.py`;
- unused `_default_error_check` import in `commands/dispatch.py`;
- lambda assignments in `commands/commands.py`;
- a few unused variables in tests.

Decision: make lint meaningful, either by fixing the repo baseline or by scoping lint to the production/test paths you want to claim as gated. A configured lint command that fails should not be left as the public story.

### 2. Working-Tree Artifacts

The local checkout still has untracked hardware JSONLs and worked notebooks. The `.gitignore` only covers hardware output names ending in `*_results.jsonl`, so many real validator outputs escape it.

Decision: choose one artifact policy:

- move curated validation evidence to `microscopes/docs/evidence/`;
- ignore all runtime JSONLs in `tests/hardware/`;
- explicitly unignore only curated evidence if it must stay beside the scripts;
- ignore `workflows/target_acquisition/*_worked.ipynb`;
- add `.ruff_cache/` to `.gitignore`.

The safest public-facing choice is: keep reports in `microscopes/docs/`, move or archive curated JSONLs, and ignore all runtime validator output by default.

### 3. Operator Notebook

The deep review flags the operator notebook as mostly good but not fully thin:

- one selection cell still contains control flow that belongs in the pipeline;
- committed outputs include local Windows paths;
- worked notebooks are large runtime artifacts.

Decision: for conference sharing, strip outputs from the tracked operator notebook and move selection logic into `pipeline.run_selection()` or equivalent.

### 4. Docs

There are two kinds of docs mixed together:

- durable design/validation docs;
- dated session scratch and handoff notes.

Both are useful, but they should not be presented as one flat documentation set.

Decision: create a docs index and either:

- move scratch docs to `microscopes/docs/archive/`; or
- keep them in place but label them clearly as historical/session notes.

Durable current docs should include:

- root README;
- Leica driver README;
- target acquisition README;
- hybrid reader rationale;
- simulator/real-scope validation reports;
- conference readiness synthesis.

### 5. Test Organization

The tests pass, but they still reflect older package boundaries.

Main issues:

- `test_core_driver.py` is a historical bucket after the `commands/` + `runtime/` split;
- hardware tools, offline tests for hardware tools, runtime JSONLs, and evidence JSONLs live in the same folder;
- workflow visualization tests are large and mixed;
- fixture/helper duplication can be reduced.

Decision: do a test cleanup branch after artifact hygiene, not before.

## Decisions For The Owner

These are the things that should not be decided silently by an implementation session.

1. **Worked notebooks:** delete, archive outside repo, or ignore and keep local?
2. **JSONL evidence:** keep in `tests/hardware/`, move to `docs/evidence/`, or keep only summarized Markdown reports?
3. **Docs archive policy:** move session scratch to `docs/archive/` or keep flat with an index?
4. **`experimental/lrp_edits`:** rename because it is effectively public API, or leave for now?
5. **Packaging:** add minimal `[project]` metadata now, or defer until after the conference?
6. **Calibration lint fix:** approve the one-line `Path` import in calibration code.

## Recommended Cleanup Branch

Create:

```powershell
git switch -c conference_cleanup fable5_tryout
```

### Commit 1 - Artifact Policy

Purpose: make `git status` clean after ordinary work.

Actions:

- add `.ruff_cache/` to `.gitignore`;
- ignore hardware runtime JSONLs broadly;
- ignore `*_worked.ipynb`;
- decide whether curated JSONLs move to `microscopes/docs/evidence/reader_validation/`;
- leave no untracked artifacts after running tests.

Do not delete worked notebooks or JSONLs unless the owner explicitly approves.

### Commit 2 - Notebook Cleanup

Purpose: make the operator notebook shareable.

Actions:

- strip outputs from `smart_microscopy_v3.2.ipynb`;
- remove embedded local paths from committed notebook output;
- move selection-cell logic into a pipeline function;
- keep notebook cells thin and procedural.

Verification:

```powershell
python -m pytest -q workflows/target_acquisition/tests
```

### Commit 3 - Lint Baseline, Production Paths

Purpose: remove obvious static hygiene issues.

Actions:

- fix missing `Path` import if approved;
- remove unused `_default_error_check`;
- clean lambda assignments or add targeted ignores;
- run scoped `ruff --fix` only on touched production paths;
- avoid broad unsafe autofixes.

Verification:

```powershell
python -m ruff check microscopes/driver/vendor/leica/navigator_expert workflows/target_acquisition microscopes/shared
python -m pytest -q microscopes/driver/vendor/leica/navigator_expert/tests/unit
python -m pytest -q workflows/target_acquisition/tests
```

### Commit 4 - Docs Index And Archive

Purpose: make the docs navigable for a conference visitor.

Actions:

- add `microscopes/docs/README.md`;
- classify docs as current, validation evidence, historical/session notes, cleanup plans;
- move dated scratch docs to `microscopes/docs/archive/` if approved;
- add validation summary links to root README.

Do not rewrite historical docs for path changes unless they are presented as current instructions.

### Commit 5 - Test Structure Preparation

Purpose: prepare test cleanup without moving everything at once.

Actions:

- add `tests/hardware/README.md`;
- decide final folder names for offline hardware tool tests;
- optionally create empty target folders only if a subsequent commit moves tests into them.

### Commit 6+ - Test Refactor

Use the separate `TEST_CLEANUP_REFACTOR_PLAN_20260612.md` as the detailed guide.

First moves:

- split `test_core_driver.py`;
- separate hardware pytest wrappers from live hardware scripts;
- split large workflow visualization tests.

Every commit should run the relevant subset and preserve behavior.

## What Not To Touch In Cleanup

Do not change these unless a test proves an actual bug:

- selected-job hybrid confirmation semantics;
- API transition-admissibility rule;
- log no-op proof rule;
- validator pass/fail semantics;
- calibration JSON schema;
- workflow output schema.

Do not make pure-log simulator failures green by accepting stale log evidence. Those failures are part of the measured reason hybrid exists.

## Suggested Public Story

For the conference, say:

> This repository contains a working Leica Navigator Expert integration and a target-acquisition workflow. The robust state-reader work is the main engineering result: API and log each fail differently, so command confirmation uses a hybrid evidence race. The first admissible source wins. That passed the real-scope 10-position XY validation with zero failures, while API-only and log-only each failed in environment-specific ways. The microscope-agnostic layer is still under construction.

Avoid saying:

> The whole repo is release-polished.

Better:

> The implementation is validated; the cleanup branch is about public packaging, lint, docs, and test organization.

## Final Recommendation

Proceed with a cleanup branch. Keep it mechanical and reviewable:

1. artifact policy;
2. notebook output cleanup;
3. lint baseline;
4. docs index/archive;
5. test organization.

The core reader/driver implementation should be left alone. It is the strongest part of the branch.

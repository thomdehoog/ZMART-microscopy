# Test Cleanup And Refactor Plan

Date: 2026-06-12  
Target branch to create: `test_cleanup` or `conference_test_cleanup`  
Base branch: `fable5_tryout`

## Goal

Make the test suite easier to understand, faster to navigate, and safer to extend without changing driver or workflow behavior.

This should be a cleanup branch, not a feature branch. The hybrid reader design, command confirmation semantics, hardware validator behavior, and workflow behavior should stay unchanged unless a test cleanup exposes a real bug.

## Current Test Surface

The repository currently has four main test areas:

- Leica driver tests:
  - `microscopes/driver/vendor/leica/navigator_expert/tests/unit/`
  - `microscopes/driver/vendor/leica/navigator_expert/tests/hardware/`
  - `microscopes/driver/vendor/leica/navigator_expert/tests/helpers/`
  - `microscopes/driver/vendor/leica/navigator_expert/tests/data/`
- Leica calibration tests:
  - `microscopes/calibration/vendor/leica/navigator_expert/tests/unit/`
  - `microscopes/calibration/vendor/leica/navigator_expert/tests/integration/`
- Shared utility tests:
  - `microscopes/shared/output_layout/tests/`
- Workflow tests:
  - `workflows/target_acquisition/tests/`

The main pain points are:

- test names still reflect old package names, especially `test_core_driver.py`;
- hardware scripts, hardware pytest wrappers, committed JSONL evidence, ignored runtime JSONLs, and untracked JSONLs all live in one folder;
- workflow tests are mostly good but large files such as visualization tests carry mixed responsibilities;
- fixtures and fake clients are duplicated across driver/hardware/workflow tests;
- lint fails across tests, mostly import order and unused imports.

## Principles

1. **One test answers one question.**  
   If a file tests dispatch, it should not also test scan-field parsing or workflow output naming.

2. **Separate offline contract tests from live hardware evidence.**  
   Offline tests should be deterministic and run on every machine. Live hardware validators should be explicit tools with JSONL output, not mixed into ordinary unit-test discovery.

3. **Do not hide measured hardware behavior.**  
   API/log/hybrid disagreements are important evidence. Preserve curated JSONLs and reports, but do not let every local run pollute `git status`.

4. **Prefer shared fixtures over clever mocks.**  
   The mock LAS X client and sample JSONL/driver result records should live in one support location per package.

5. **Refactor tests before broad lint cleanup.**  
   Moving test boundaries first makes lint fixes less noisy and reduces duplicate cleanup.

## Proposed Final Layout

### Driver Tests

```text
microscopes/driver/vendor/leica/navigator_expert/tests/
  conftest.py
  data/
    scanfield_parsing/
    general_workflow/
    validation_records/
  helpers/
    mock_lasx_api.py
    result_builders.py
    fake_logs.py
  unit/
    commands/
      test_dispatch.py
      test_command_wrappers.py
      test_confirmations_settings.py
      test_confirmations_selected_job.py
      test_confirmation_race.py
      test_idle_prechecks.py
    runtime/
      test_profiles.py
      test_lasx_runtime.py
      test_driver_bootstrap.py
    state_readers/
      test_api_reader.py
      test_log_reader.py
      test_log_wait.py
      test_router.py
      test_change_wait.py
      test_capabilities.py
    scanfields/
      test_parsers.py
      test_strip_restore.py
    acquisition/
      test_acquisition.py
      test_native_autosave.py
    stage/
      test_stage_backlash.py
      test_stage_config.py
    cli/
      test_validate_hardware_cli.py
  hardware/
    README.md
    validate_hardware.py
    stress_hardware.py
    probe_four_readers.py
    compare_select_job_confirm_sources.py
    ...
  hardware_tests/
    test_validate_hardware.py
    test_stress_hardware.py
```

The exact folder names can vary, but the boundary should be explicit:

- `unit/`: deterministic pytest tests.
- `hardware/`: runnable live tools.
- `hardware_tests/`: offline tests for the live tools.
- `data/validation_records/`: curated JSONL fixtures used by tests or docs.

### Workflow Tests

```text
workflows/target_acquisition/tests/
  conftest.py
  support.py
  fixtures/
  unit/
    test_connect.py
    test_preflight.py
    test_geom.py
    test_selection.py
    test_summary_schema.py
    test_focus_map.py
    test_save_queue.py
  visualization/
    test_display_tile.py
    test_display_selection.py
    test_display_target.py
    test_plot_overview_tiles.py
    test_plot_target_pairs.py
  integration/
    test_target_mock.py
    test_overview_persistence.py
    test_callback_api.py
```

This does not need to happen all at once. The immediate value is splitting the largest files by responsibility, especially visualization.

## Concrete Refactor Steps

### Phase 1 - Artifact Hygiene

Do this first so reviews are not polluted.

1. Extend `.gitignore`:

```gitignore
# Hardware validator/probe runtime outputs.
microscopes/driver/vendor/leica/navigator_expert/tests/hardware/*.jsonl
!microscopes/driver/vendor/leica/navigator_expert/tests/hardware/*_real_*.jsonl
!microscopes/driver/vendor/leica/navigator_expert/tests/hardware/noop_select_job_log_probe_20260611_215425.jsonl

# Operator scratch notebooks.
workflows/target_acquisition/*_worked.ipynb
```

Alternative: do not use negated ignore rules and instead move curated evidence to `microscopes/docs/evidence/`. That is cleaner long-term.

2. Decide where curated validation JSONLs live:
   - recommended: `microscopes/docs/evidence/reader_validation/`;
   - acceptable: keep the currently committed records in `tests/hardware/` but add a README explaining which are evidence and which are runtime output.

3. Remove local untracked JSONLs and worked notebooks from the working tree or leave them ignored.

### Phase 2 - Rename And Split Driver Unit Tests

Current issue: `test_core_driver.py` is a large historical bucket. After the `commands/` + `runtime/` split, that name is stale.

Target split:

- `test_dispatch.py`: `confirm_and_fire`, retry ceilings, fire block behavior, timing shape.
- `test_command_wrappers.py`: wrapper-level setup, profile overrides, command result shape.
- `test_confirmations_settings.py`: setting readback confirmations.
- `test_confirmations_selected_job.py`: selected-job API/log/hybrid semantics and no-op handling.
- `test_confirmations_acquire.py`: acquisition confirmation semantics.

Rules:

- Move tests in small commits.
- Run the moved file after each split.
- Avoid rewriting assertions while moving unless names are actively misleading.
- Keep old helper functions only if at least two new files use them; otherwise inline.

Acceptance:

```powershell
python -m pytest -q microscopes/driver/vendor/leica/navigator_expert/tests/unit/commands
python -m pytest -q microscopes/driver/vendor/leica/navigator_expert/tests/unit
```

### Phase 3 - Make Hardware Tests And Hardware Tools Separate

Current issue: `tests/hardware/` contains:

- live validators/probes;
- offline pytest wrappers;
- committed evidence JSONLs;
- ignored/untracked runtime JSONLs.

Target:

- live scripts stay in `tests/hardware/`;
- pytest wrappers move to `tests/hardware_tests/`;
- curated JSONLs either move to `microscopes/docs/evidence/` or `tests/data/validation_records/`;
- runtime JSONLs are ignored.

Add `tests/hardware/README.md` with:

- safe-by-default policy;
- commands for simulator and real scope;
- explanation that live scripts require explicit `--yes` and opt-in motion/acquire flags;
- where result JSONLs go;
- which scripts are production validators versus exploratory probes.

Acceptance:

```powershell
python -m pytest -q microscopes/driver/vendor/leica/navigator_expert/tests/hardware_tests
python microscopes/driver/vendor/leica/navigator_expert/tests/hardware/validate_hardware.py --help
```

### Phase 4 - Consolidate Fixtures

Create shared test helpers only where duplication is real.

Driver helper candidates:

- fake `Reading` builders;
- fake log snapshots;
- fake `LogPollResult`;
- command result builders;
- selected-job job-list builders;
- mock LAS X setup helpers.

Workflow helper candidates:

- minimal `Context`;
- minimal `Config`;
- minimal calibration;
- fake acquisition records;
- temporary output-layout helper.

Do not create generic "test utilities" for one caller. That just moves complexity.

### Phase 5 - Split Large Workflow Test Files

Priority files:

1. `test_visualize.py`
   - Split by user-facing output:
     - tile display
     - selection display
     - target display
     - overview plots
     - target-pair plots
   - Keep shared image/plot fixtures in a local support module.

2. `test_polish.py`
   - It is a historical regression bucket. Move tests into the files that own the behavior, then delete the bucket.

3. `test_target_mock.py`
   - Split pure mock-provider behavior from target-step integration behavior.

Acceptance:

```powershell
python -m pytest -q workflows/target_acquisition/tests
```

### Phase 6 - Lint The Test Baseline

After splitting files, clean lint in this order:

1. production driver files touched by test refactor;
2. driver tests;
3. workflow tests;
4. calibration tests.

Most current lint failures are import-order issues. Use `ruff --fix` only in narrow scopes and review the diff:

```powershell
python -m ruff check microscopes/driver/vendor/leica/navigator_expert/tests/unit --fix
python -m ruff check workflows/target_acquisition/tests --fix
```

Do not run repo-wide unsafe fixes as a single commit.

Acceptance target for this branch:

```powershell
python -m ruff check microscopes/driver/vendor/leica/navigator_expert/tests workflows/target_acquisition/tests
```

Optional later target:

```powershell
python -m ruff check .
```

## What Not To Change

Do not change these in the test cleanup branch unless a specific failing test proves a bug:

- selected-job hybrid confirmation semantics;
- API transition-admissibility rule;
- log no-op proof rule;
- hardware validator status semantics;
- workflow output schema;
- microscope calibration JSON schema.

Do not "fix" pure-log simulator failures by weakening timestamp gates or allowing stale evidence. Those failures are measured behavior and are part of why hybrid exists.

## Suggested Commit Sequence

1. `Ignore runtime validator outputs and worked notebooks`
2. `Document hardware test artifacts and evidence records`
3. `Split driver command tests by package responsibility`
4. `Move hardware pytest wrappers out of live-script folder`
5. `Consolidate driver test fixtures`
6. `Split workflow visualization tests`
7. `Clean test lint baseline`
8. `Record test cleanup verification`

Each commit should keep the relevant test subset green.

## Verification Matrix For The Cleanup Branch

Run after each major phase:

```powershell
python -m pytest -q microscopes/driver/vendor/leica/navigator_expert/tests/unit
python -m pytest -q workflows/target_acquisition/tests
```

Run before final review:

```powershell
python -m pytest -q microscopes/driver/vendor/leica/navigator_expert/tests/unit
python -m pytest -q microscopes/driver/vendor/leica/navigator_expert/tests/hardware_tests
python -m pytest -q workflows/target_acquisition/tests
python -m pytest -q microscopes/calibration/vendor/leica/navigator_expert/tests microscopes/shared/output_layout/tests
python -m ruff check microscopes/driver/vendor/leica/navigator_expert/tests workflows/target_acquisition/tests
git status --short
```

Live hardware validation is not required for a test-only refactor if no production code changes. If import paths for hardware scripts move, run:

```powershell
python microscopes/driver/vendor/leica/navigator_expert/tests/hardware/validate_hardware.py --help
```

Optionally run the full hybrid validator on the simulator:

```powershell
python microscopes/driver/vendor/leica/navigator_expert/tests/hardware/validate_hardware.py --yes --allow-xy --allow-z --allow-objective --allow-acquire --state-reader-mode hybrid
```

## Done Criteria

The cleanup is complete when:

- `git status --short` is clean after ordinary test runs;
- runtime JSONLs and worked notebooks no longer appear as untracked files;
- test names match current package boundaries (`commands`, `runtime`, `state_readers`, `scanfields`);
- live hardware scripts and offline tests are clearly separated;
- the scoped test lint command passes;
- the same pytest suites pass as before the refactor;
- no production behavior changes are included.

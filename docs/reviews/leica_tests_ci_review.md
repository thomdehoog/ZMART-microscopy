# Leica Stellaris5 (navigator_expert) — Test Suite & CI Review

- **Scope:** the driver's test suite as a system — `tests/` (conftest, `_diagnostics.py`, `unit/`, `hardware/`, `helpers/mock_lasx_api.py`, `data/`), `calibration/tests/`, `pytest.ini`, `.coveragerc`, `run_ci.py`, `requirements-dev.txt`, and `.github/workflows/` (navigator-expert.yml, controller.yml). Local per-test quality was covered by reviews 2–5; this review covers architecture, coverage strategy, mock realism, hygiene, speed/determinism, and CI wiring.
- **Date:** 2026-07-03
- **Reviewed commit:** `c7964dd` (working tree == origin/main)
- **Reviewer:** Claude (review 6 of series)
- **Verification:** the full offline suite was executed twice on Linux/py3.11 during this review (660 passed, 3 skipped, 61 subtests; 124–130 s wall clock) and instrumented with `--durations` and `coverage.py` (branch coverage). All runtime and coverage numbers below are measured, not estimated.

---

## Executive summary

This is a genuinely strong suite by scientific-software standards: ~660 offline tests (~21.8k test LOC against ~21.4k production LOC), a behavioral LAS X mock with state and realistic error strings, a full-stack offline gate that drives the *same* validator used against the live scope, a self-contained CI runner (`run_ci.py`) with cross-machine diagnostics, and a real 3-OS × 3-Python GitHub matrix. The failure-mode orientation (fail-closed staleness, race admissibility, DST folds, encoding traps) is exemplary.

The problems are concentrated in four places. **(1) Speed:** ~95 s of the 124 s wall clock is real sleeping — one test burns a full 60 s default timeout (`test_missing_xml_raises`) and ~15 confirm-path tests in `test_core_driver.py` each burn 1–3 s of unmocked poll windows. The suite could run in ~25 s with two mechanical fixes. **(2) Coverage strategy:** coverage is collected but enforced nowhere, and the riskiest byte-level code is near-zero: `scanfields/lrp.py` (the LRP parser) is at **7 %**, `acquisition/ome.py` (the binary TIFF patcher) at **41 %**, and the LRP *write* primitives (`experimental/lrp_edits/{z,roi,scan}.py`) at 13–26 % — exactly the modules earlier reviews flagged as highest-risk. **(3) Marker/docs drift:** the `hardware` and `slow` markers are registered, documented, and filtered on (`-m "not hardware"`), but **zero tests carry either marker**. **(4) Dead weight:** ~360 lines of self-referential "protocol" tests that only exercise their own mocks, six unreferenced one-shot dev scripts in `tests/hardware/`, fossil "removed-API" tests, and 14 copies of the same `sys.path` bootstrap.

One adjacent CI defect is severe: `.github/workflows/controller.yml` runs `pytest controller/tests`, a directory that does not exist (`zmart_controller/tests` is the real path), so the Controller workflow — which gates the `zmart_controller` surface the Leica adapter registers into — can never pass.

---

## What works well

Credit where due; these are worth preserving through any cleanup:

1. **The mock-and-live shared validator is the right architecture.** `tests/hardware/validate_hardware.py` is one flow that runs against the in-process mock (`--mock`), the LAS X simulator, or the real scope; `tests/hardware/test_validate_hardware.py:121` (`test_validate_hardware_full_mock_run`) runs the *entire* reversible validation (job select, 14 setting writes, 10 XY moves, Z, objective, acquire; asserts ≥30 PASS, 0 FAIL/WARN) inside the offline suite. This is what pins mock fidelity: the exact code path that passes against the mock is re-run against live LAS X by `run_ci.py online` (run_ci.py:234–276). Same pattern for the adapter (`test_validate_zmart_adapter.py` drives a real `zmart_controller.Session`).
2. **`tests/_diagnostics.py` + `pytest_report_header`** (tests/conftest.py:35–49): every run — local or CI — opens with platform, Python, package versions, git rev/dirty, and LAS X runtime availability, and `run_ci.py` persists the same as `tests/_report/env.json`. Defensive throughout ("diagnostics must never break a run"). This is exactly what cross-institute triage needs.
3. **`run_ci.py` as the single CI definition** with `.github/workflows/navigator-expert.yml` as a thin trigger (navigator-expert.yml:1–7) is the correct split; the workflow runs a real 3 OS × 3 Python matrix, uploads reports `if: always()` (navigator-expert.yml:57), and path-filters on the driver + `shared/`. `run_ci.py` streams every step with timing, writes `ci_summary.json`, and keeps lint non-fatal with a documented rationale (run_ci.py:22–24).
4. **Mock realism in `tests/helpers/mock_lasx_api.py`** is unusually good for a hand-written mock: echo clear-on-command and warning-with-`Result=1` semantics (`_EchoModel.set_warning`, mock_lasx_api.py:206), "cannot be set while the block is being scanned" while busy (mock_lasx_api.py:590–592), realistic out-of-range error strings, pinhole clamp-with-warning hardware behavior (mock_lasx_api.py:746–758), command-channel dispatch matching `api_reader`'s clear-then-fire-then-poll protocol (mock_lasx_api.py:463–485 vs readers/api_reader.py:98–119), and a *documented* `_scan_min_reads` guarantee (mock_lasx_api.py:348–356) fixing a real suite-load flake — itself regression-tested at tests/hardware/test_validate_hardware.py:87 (`test_mock_scan_window_survives_delayed_first_poll`).
5. **`tests/unit/test_log_reader.py`** builds synthetic log lines that reproduce the real traps: latin-1 `µ` (line 340), `<LF>`/`<TAB>` tokens (127), truncated final lines (265), duplicate-name fail-closed (145), DST fold disambiguation (419–441), dialog open/close decided by line order (365). Combined with the live `validate_readers_side_by_side.py` parity gate, log-format drift has a detection path.
6. **Hermetic machine root** — the package-root `conftest.py:8–21` autouse fixture points `SMART_MICROSCOPY_ROOT` at an empty tmp dir for *every* test, so nothing reads or writes `C:\ProgramData`. Simple, global, correct.
7. **Strictness defaults** in pytest.ini:21–25 (`-ra`, `--strict-markers`, `--strict-config`, `--durations=20`) — the suite is configured to surface its own problems.
8. **`tests/unit/test_driver_bootstrap.py`** tests the import bootstrap in a *subprocess* with only `leica/` on `sys.path`, with a comment explaining why in-process would silently mask the failure (lines 6–10). This is the right way to test path bootstrap.
9. **`tests/unit/test_confirm_specs.py`** pins the descriptor table ↔ generated-wrapper relationship (exact set equality, tolerance defaults matched against signatures) so the Stage-4 collapse can't silently drift.
10. **Fixture data is proportionate**: `tests/data/` is 2.4 MB of real LAS X template bundles (5 scanfield bundles + 1 workflow bundle) used by parser/strip-restore tests and installed by the hardware stress runner — committed, small, and load-bearing.
11. **`requirements-dev.txt`** documents *why* each heavy dependency is present ("every heavy dependency below is a traced transitive import", lines 8–10) — rare and valuable.
12. **`.gitignore` hygiene** covers `tests/_report/`, `tests/hardware/*.jsonl`, `.pytest_cache/`, coverage artifacts, and calibration sessions.

---

## Findings

### Critical

**LT-01 — The Controller CI workflow tests a directory that does not exist.**
*Severity: Critical (CI). File: `.github/workflows/controller.yml:36`.*
The workflow runs `python -m pytest controller/tests --tb=short`, but the package lives at `zmart_controller/tests` (`controller/` does not exist at the repo root). pytest exits 4 ("file or directory not found") on every trigger, so the workflow that gates the `zmart_controller` registry/Session surface — the exact contract `tests/unit/test_zmart_adapter.py` and the Leica adapter depend on — can never pass. Its comment (controller.yml:34–36, "Driver/calibration suites need LAS X + a microscope") also contradicts reality: the navigator-expert workflow runs those suites offline on every push.
**Action:** change the path to `zmart_controller/tests`; fix or delete the stale comment. Consider whether one workflow calling both suites is simpler than two drifting ones.

### High

**LT-02 — One test spends 60 s (48 % of suite wall clock) waiting on a default timeout.** **[PATCHWORK]**
*Severity: High. File: `tests/unit/test_acquisition.py:577–592` (`TestSave::test_missing_xml_raises`).*
Measured at **60.06 s** of the 124 s suite. The test unlinks the companion XML and calls `drv.save(...)` without overriding `export_completion_timeout_s`, so the collector polls for the missing XML for the full `DEFAULT_EXPORT_COMPLETION_TIMEOUT_S = 60.0` (acquisition/navigator_expert_export.py:37) before raising. Sibling tests in the same file already pass `export_completion_timeout=0.01` (e.g. lines 930–936); this one simply forgot. The 5.00 s runner-up, `test_uses_mtime_fallback_when_relative_path_is_empty` (line 794), has the same shape: it overrides `mtime_poll_timeout=0.1` but not the 5 s `path_poll_timeout`.
**Action:** pass `export_completion_timeout_s=0.1` (and `path_poll_timeout=0.1` in the mtime test). Two one-line changes remove 65 s from every CI leg (×9 matrix jobs ≈ 10 CPU-minutes per push).

**LT-03 — ~35 s of real, unmocked poll-window sleeps in `test_core_driver.py`.**
*Severity: High. File: `tests/unit/test_core_driver.py`, `TestConfirmFunctions` (~1214–1556), `TestConfirmAndFire`/`TestConfirmation` (~261–1147).*
The durations report shows a wall of 1.00–3.03 s tests: every negative confirm test (`test_confirm_zoom_fail`, `test_confirm_rotation`, `test_confirm_scan_speed`, …) burns the full default 3 s readback poll window with real `time.sleep`, and each `confirm_and_fire` retry/confirm test burns ~1 s/attempt of echo-poll sleep. The suite already demonstrates both remedies elsewhere: some tests pass `poll_window=0.1` (e.g. line 1351) and others patch `time.sleep` (lines 2574, 2809). It is applied inconsistently, so ~25 tests pay real time.
**Action:** add a module-level fixture (or per-class `patch("time.sleep")` where the code polls a monotonic deadline, plus explicit tiny `poll_window=`/`poll_interval=` arguments on every negative confirm call). Combined with LT-02 the suite drops from ~124 s to ~25 s.

**LT-04 — The riskiest byte-level code is effectively untested, and coverage is enforced nowhere.**
*Severity: High. Files: `scanfields/lrp.py`, `acquisition/ome.py`, `experimental/lrp_edits/*`, `.coveragerc`, `run_ci.py:211–222`.*
Measured branch coverage from the offline suite: **`scanfields/lrp.py` 7 %** (249 stmts, 224 missed — the LRP parser earlier reviews flagged), **`acquisition/ome.py` 41 %** (the binary TIFF tag-270 reader/patcher), **`experimental/lrp_edits/z.py` 13 %, `roi.py` 14 %, `scan.py` 26 %, `general.py` 30 %, `focus.py` 31 %** (code that *rewrites vendor template files* consumed by LAS X), `scanfields/files.py` 21 %, `_file_utils.py` 10 %, `readers/api_reader.py` 62 %. Suite total ≈ 71 %. `tests/unit/test_lrp_edit_primitives.py` covers `_primitives.py` regressions well, but the per-parameter edit modules above it are exercised only by live-hardware scripts. Meanwhile `.coveragerc` sets no `fail_under`, `run_ci.py` treats pytest-cov as optional (silently skipping coverage when absent, run_ci.py:219–222), and no workflow step reads `coverage.xml`. Coverage is measured, uploaded, and then ignored.
**Action:** (a) add offline tests for `scanfields/lrp.py` against the five committed `.lrp` fixtures (parse → assert real geometry values, round-trip) and for `acquisition/ome.py`'s tag-270 paths using small crafted TIFFs (classic + BigTIFF + truncated); (b) add `fail_under` (start at the current ~71 % floor) to `.coveragerc` so regressions fail CI; (c) either make pytest-cov mandatory in `run_ci.py` or have its absence flip the step to WARN in the CI summary rather than a one-line print.

### Medium

**LT-05 — `hardware`/`slow` markers are registered, documented, and filtered — but used by zero tests.** *[Drift]*
*Severity: Medium. Files: `pytest.ini:29–32`, `run_ci.py:205–206`, `README.md:308`, `tests/hardware/*`.*
`grep -rn "mark.hardware\|mark.slow" tests calibration` returns nothing. `run_ci.py`'s `-m "not hardware"` deselects nothing; the offline/online split actually works because the live validators are plain scripts pytest never collects (no `test_` prefix), and the `test_*.py` wrappers there are mock-only. README §"repo map" (line 308) claims `hardware/ (@pytest.mark.hardware)` — false. pytest.ini's own comment ("the offline/online split is explicit rather than relying on tests to self-skip") describes a mechanism that doesn't exist.
**Action:** either (a) drop both marker registrations and the `-m` filter and document the real split ("pytest collects only mock-backed tests; live validation is scripts via `run_ci.py online`"), or (b) actually mark something. (a) is simpler and honest. Fix README:308 either way.

**LT-06 — `TestAcquisitionProtocol` (~360 lines, 12 tests) mostly tests its own mocks.** **[PATCHWORK]**
*Severity: Medium. File: `tests/unit/test_core_driver.py:2175–2535`.*
The "protocol" is a table (`PROTOCOL_POSITIONS`) plus a loop (`_run_protocol`) defined *in the test file*, run with `drv.select_job`, `drv.move_xy`, `drv.acquire`, **and** `commands.confirm_and_fire` all patched out. The assertions then verify that the test's own loop called the test's own mocks in the order the test's own table dictates (`test_job_switches_only_when_needed` re-derives expected switches with `_protocol_job_switches()`, a reimplementation of the loop's `if job != last_job`). The failure-injection variants (`test_acquire_failure_at_position_5` etc.) assert that the loop's own `assert` statements raise. The only production code touched is the thin `set_*`→`confirm_and_fire` wiring, which `TestSetFunctionWiring` (line 1564) already covers per-function. Zero driver behavior is protected; any refactor of real sequencing logic would not be caught, and any rename forces 360 lines of churn.
**Action:** delete the class, or reduce it to the two or three set-wiring value checks not already in `TestSetFunctionWiring`. If an offline end-to-end sequence test is wanted, drive the real `commands` layer against `MockLasxClient` instead — the machinery already exists (`test_validate_hardware_full_mock_run` proves it).

**LT-07 — `pytest` (what developers run) and `run_ci.py` (what CI runs) disagree on scope.**
*Severity: Medium. Files: `pytest.ini:8` (`testpaths = tests`), `run_ci.py:45` (`TEST_PATHS = [tests, calibration/tests]`).*
A bare `pytest` from the driver root silently omits the calibration suite (97 tests: 19 model + 78 workflows); README §9 (lines 363–364) papers over this with two separate commands. This is exactly the run_ci-vs-pytest drift the file headers promise to avoid ("pytest run from this folder discovers and runs the driver's own offline suite", pytest.ini:3–4 — it doesn't, not all of it).
**Action:** `testpaths = tests calibration/tests` in pytest.ini, and let `run_ci.py` inherit it instead of hardcoding `TEST_PATHS`.

**LT-08 — `tests/hardware/` mixes 4 maintained validators with ~6 unreferenced one-shot dev scripts.** **[YAGNI]**
*Severity: Medium. Files: `tests/hardware/probe_export_layout.py`, `verify_save_product.py`, `compare_select_job_confirm_sources.py`, `move_xy_pattern_api_vs_log.py`, `smoke_two_tile_save.py`, `compare_export_metadata.py`.*
The maintained set is clear: `validate_hardware.py`, `validate_zmart_adapter.py`, `probe_four_readers.py`, `validate_readers_side_by_side.py` are wired into `run_ci.py online` (run_ci.py:236–276) and have pytest mock gates. The other six are referenced by nothing (no README, no run_ci, no wrapper). Two are self-declared one-shots whose moment has passed: `probe_export_layout.py` ("so we stop guessing … before restructuring the collector") and `verify_save_product.py` ("Run AFTER the driver fix lands"— it landed; `test_acquisition.py` now covers the contract offline). `compare_select_job_confirm_sources.py` is the measurement study behind the 2026-06-11 hybrid-confirm decision (already recorded in test docstrings). `compare_export_metadata.py` (1164 lines) is, per its own docstring, an **offline** verifier misfiled under `hardware/`. `stress_hardware.py` is legitimately kept (mock gate exists).
**Action:** delete or move to a `tools/`-style archive: `probe_export_layout.py`, `verify_save_product.py`, `compare_select_job_confirm_sources.py`. Decide whether `move_xy_pattern_api_vs_log.py` and `smoke_two_tile_save.py` earn a place in `run_ci online` or the archive. Relocate `compare_export_metadata.py` out of `hardware/` (or wire it into the offline gate if it's load-bearing).

**LT-09 — Fossil "removed-API" and structure-assertion tests.** **[YAGNI]**
*Severity: Medium. Files: `tests/unit/test_core_driver.py:1155–1160` (`TestApiSetRemoved`), :2093–2094 (`test_no_api_set`, duplicating the former), :2721–2723 (`TestReadbackCacheRemoved`), :2089–2091 (`test_version` pins `__version__ == "6.0.0"`), :2105–2168 (`TestModuleStructure` hasattr-lists of 23 private confirm fns and 20 set fns), `tests/unit/test_acquisition.py:1152–1161` (`test_old_public_workflow_helpers_are_not_exported`, 9 hasattr asserts).*
These assert the *absence* of long-deleted attributes or the mere existence of private callables. They protect against a resurrection that version control already prevents, and they punish legitimate refactors (rename a private `_confirm_*` and a "module structure" test fails with no behavioral signal). The `__version__` pin guarantees a test edit on every release.
**Action:** delete the removed-API tests and the hasattr inventories; keep behavioral coverage (which exists elsewhere for every listed function). If the public-surface freeze matters, one test comparing `drv.__all__` against a literal list is the honest version.

**LT-10 — 14 copies of the `sys.path.insert` bootstrap in unit tests, three different variants overall.**
*Severity: Medium. Files: `tests/unit/*.py` (14 files, e.g. test_core_driver.py:30, test_zmart_adapter.py:16–17), `tests/hardware/*` wrappers, `calibration/tests/unit/test_model.py:8–16` (its own `_repo_root()` + lazy `_load_calibration_module()` despite `calibration/tests/conftest.py` doing the same job).*
`tests/conftest.py:9–28` already inserts the machine dir, repo root, and helpers for every collected test. The per-file inserts are redundant when running under pytest and exist only to support direct `python test_x.py` execution — a mode half the files advertise in stale docstrings (see LT-16). Redundant bootstraps mask breakage of the real one (a conftest regression would be invisible until a file without its own insert appears) and each new test file cargo-cults the block, sometimes with different `parents[N]` depths (a relayout landmine).
**Action:** delete the per-file inserts and the `if __name__ == "__main__": unittest.main()` tails; standardize on conftest. Keep exactly one documented exception: `test_driver_bootstrap.py`, whose subprocess *is* the test.

**LT-11 — Hand-rolled global-profile save/restore is duplicated across ≥6 files.**
*Severity: Medium. Files: `tests/unit/test_state_readers.py:22–26`, `test_select_job_confirm.py:42–50`, `test_log_wait.py:44–48`, `test_validate_hardware_cli.py:23–28`, `test_core_driver.py:1245–1273` and :2550–2563 (inline try/finally), `test_log_reader.py:282–298` (`profiles.LOG_READER`).*
Every file that swaps `profiles.STATE_READERS`/`LOG_READER` re-implements setUp/tearDown (or try/finally) restore. It works today, but it is six copies of the same fixture and the two inline try/finally sites in `test_core_driver.py` are one refactor away from leaking global state into later tests (the same class of bug as the `_stage_limits` globals mutated by `test_core_driver.py:1955–1965` and `test_zmart_adapter.py:91–106`, which rely on every consumer re-setting limits first).
**Action:** one shared pytest fixture (e.g. `state_reader_profile(**overrides)` using `monkeypatch.setattr(profiles, "STATE_READERS", ...)`) in `tests/conftest.py`; likewise a `stage_limits` fixture that restores on teardown. Delete the per-file plumbing.

**LT-12 — The offline suite never exercises the log/hybrid reader routes end-to-end; the mock is API-only.**
*Severity: Medium. Files: `tests/helpers/mock_lasx_api.py` (no log emission), `run_ci.py:260–274`.*
The mock models the CAM API but writes no LCS/msgbox log lines, so `validate_hardware.py --mock` can only run meaningfully with `--state-reader-mode api`; the log and hybrid routes get end-to-end coverage *only* in `run_ci.py online` (which runs per-mode against live LAS X). Unit tests cover log parsing and routing against synthetic snapshots well, but no offline test drives commands → confirmation through a log-backed route. Given that hybrid is the *default* selected-job confirm source (test_select_job_confirm.py:201–208), the default confirm path's integration behavior is untestable offline.
**Action:** teach the mock to append the few log line shapes `log_reader` consumes (the `test_log_reader.py` factories `atl_line`/`xy_line`/`current_block_lines` are already reusable constructors — move them to `tests/helpers/` and have the mock emit them to a temp log), then add one mock-gate run with `--state-reader-mode hybrid`. This also de-duplicates the log-line format definitions, which currently live only inside one test file.

**LT-13 — Skips can silently hollow out the suite on partially-provisioned machines.**
*Severity: Medium. Files: `calibration/tests/integration/test_workflows.py:28` (`pytest.importorskip("cv2")` gates all 78 tests), `tests/unit/test_acquisition.py:706` (`ome_types` skip), `run_ci.py:219–222` (silent no-coverage mode).*
On the environment used for this review (no cv2/ome_types/pytest-cov), 79 tests vanish as 2 skip lines and coverage silently doesn't run — the run still exits 0 and prints PASSED. CI installs everything via `requirements-dev.txt`, so the *gate* is fine, but the local/microscope-PC story run_ci.py explicitly targets ("the new institute's microscope PC", run_ci.py:5–6) degrades silently.
**Action:** make `run_ci.py` report skip counts in the CI SUMMARY (parse the junit it already writes) and WARN when cv2/ome_types/pytest-cov are absent, so a hollow green run is visible as such.

**LT-14 — Test-dependency drift risks between `requirements-dev.txt` and root `requirements.txt`.**
*Severity: Medium. Files: `requirements-dev.txt:30`, `requirements.txt:18–19`, `environment.yml`.*
`requirements-dev.txt` pins `opencv-python-headless` while the root runtime file pins `opencv-python`; installing both files into one env (the documented local flow: runtime env + dev extras) yields two wheels owning `cv2` with pip-order-dependent results. Also `ipython>=8` is pulled into the *test* gate solely for a lazy `IPython.display` import in calibration visualize — heavy for CI.
**Action:** align on one cv2 distribution (headless works for the runtime paths CI touches; if the scope PC needs GUI cv2, document the override instead), and consider guarding the `IPython` import so the test gate can drop it.

### Low

**LT-15 — Wall-clock-sensitive assertions in threaded reader/race tests.**
*Severity: Low. Files: `tests/unit/test_state_readers.py:84–105` (0.25 s "slow API" + source assertion), :341–357 (`elapsed < 2.0`), `tests/unit/test_confirmation_race.py:119–141` (`budget_s=0.3`, `elapsed < 2.0`), `tests/unit/test_select_job_confirm.py:158–161` (real `time.sleep(0.35)` to keep a patch alive past an abandoned leg).*
These test genuinely concurrent behavior, so some real time is justified, and thresholds are generous — but they are the residual flake surface (the mock's `_scan_min_reads` comment records that this class of failure has already happened under CI load). Total cost ~1.5 s.
**Action:** keep, but prefer event-based synchronization over fixed sleeps where possible (the 0.35 s sleep in test_select_job_confirm could join the abandoned leg via an Event the fake sets), and keep elapsed upper bounds ≥4× the nominal budget.

**LT-16 — Stale docstrings and self-run tails in unit tests.**
*Severity: Low. Files: `tests/unit/test_core_driver.py:12–17` ("Usage: python test_unit.py" — no such file), `tests/unit/test_scanfield_parsers.py:4–5` (references `tests/unit/test_position_parsers.py`, the file's old name; also a `zmart_drivers/vendor/leica/...` path that no longer exists), plus `if __name__ == "__main__"` blocks in ~12 files.*
**Action:** fix the two docstrings; drop the main-blocks together with LT-10.

**LT-17 — Duplicated fixtures between the two acquisition test files.**
*Severity: Low. Files: `tests/unit/test_acquisition.py:28–35, 113–120` and `tests/unit/test_native_autosave.py:24–31, 34–41` (`naming`, `successful_acq` re-declared verbatim).*
**Action:** move both to `tests/conftest.py` (or a `tests/unit/conftest.py`).

**LT-18 — Dead `workflows/target_acquisition` path insertion in tests/conftest.py.** **[YAGNI]**
*Severity: Low. File: `tests/conftest.py:24–28`.*
Inserted "so workflow tests imported from this suite can resolve `from pipeline...`" — no test in this suite imports `pipeline` (verified by grep). A driver test suite silently reaching into a workflow package's import space is also a layering smell.
**Action:** delete the block.

**LT-19 — Mixed unittest/pytest styles with no stated convention.**
*Severity: Low. Files: `tests/unit/` — 11 files are `unittest.TestCase` (test_core_driver, test_log_reader, test_state_readers, …), 8 are pytest-style (test_acquisition, test_machine_profile, test_confirm_specs, …).*
Both work, but the split doubles the idiom surface (setUp/addCleanup vs fixtures/monkeypatch — directly feeding LT-11) and newer files are pytest-style, suggesting the convention has already moved.
**Action:** declare pytest-style for new/modified tests; convert opportunistically (no big-bang rewrite needed).

**LT-20 — `run_ci.py` exists in three per-driver variants with deliberate but unmanaged divergence.**
*Severity: Low. Files: `zmart_drivers/leica/.../run_ci.py` (336 lines), `zmart_drivers/mesospim/run_ci.py` (219), `zmart_drivers/zeiss/zenapi/run_ci.py` (70).*
The step-runner scaffolding (`run_step`, summary printing, env building, report dir) is re-implemented per driver with the mesospim copy explicitly claiming to "match the sibling drivers' run_ci.py" while already diverging in structure. For the Leica file specifically no defect found — it is the most complete of the three — but every harness fix now needs three edits.
**Action:** if a fourth driver appears, extract the step-runner into `shared/` and keep only the step *lists* per driver; until then, accept the duplication consciously.

**LT-21 — Coverage denominator excludes never-imported modules.**
*Severity: Low. Files: `.coveragerc:6–10`, `run_ci.py:213` (`--cov=navigator_expert`).*
`--cov=navigator_expert` measures imported modules, so a module nothing imports (e.g. calibration core when cv2 is absent; any future orphan) appears at 100 % by omission rather than 0 %. With pytest-cov's package arg this is mostly handled *when the import works*; the cv2-skip case (LT-13) shows the hole.
**Action:** set `[run] source = .` in `.coveragerc` (with the existing omits) so unimported files count as uncovered.

**LT-22 — Assertions on private kwargs plumbing in dispatch tests.**
*Severity: Low. File: `tests/unit/test_core_driver.py:664–791` (`test_profile_backoff_passed_through_dispatch` and friends assert the exact kwargs `commands._dispatch` forwards to a patched `confirm_and_fire`).*
These pin the internal parameter-passing seam rather than observable behavior; a rename of a kwarg with unchanged behavior breaks them, while a behavioral regression *inside* `confirm_and_fire`'s handling of those kwargs would not. Mitigated by the fact that `TestRetryBackoff` also tests the backoff behavior itself (sleep sequences) — the behavioral half is the valuable half.
**Action:** keep the behavioral tests; treat the kwargs-forwarding asserts as candidates for deletion next time they break.

---

## Summary table

| ID | Severity | Title |
|-------|----------|-------|
| LT-01 | Critical | controller.yml runs `pytest controller/tests` — path doesn't exist; workflow can never pass |
| LT-02 | High | `test_missing_xml_raises` burns the full 60 s default export timeout (48 % of suite runtime) |
| LT-03 | High | ~35 s of unmocked confirm/echo poll-window sleeps across `test_core_driver.py` |
| LT-04 | High | LRP parser 7 %, binary TIFF patcher 41 %, lrp_edits 13–31 % coverage; no `fail_under`, coverage optional & unenforced |
| LT-05 | Medium | `hardware`/`slow` markers registered, documented, filtered — used by zero tests; README claims otherwise |
| LT-06 | Medium | `TestAcquisitionProtocol` (~360 lines) patches out everything and tests its own loop **[PATCHWORK]** |
| LT-07 | Medium | `pytest` runs `tests/` only; `run_ci.py` runs `tests/` + `calibration/tests` — dev/CI scope drift |
| LT-08 | Medium | 6 unreferenced one-shot scripts in `tests/hardware/`; offline verifier misfiled there **[YAGNI]** |
| LT-09 | Medium | Fossil removed-API / hasattr-inventory / version-pin tests **[YAGNI]** |
| LT-10 | Medium | 14 duplicated `sys.path.insert` bootstraps despite conftest doing the job |
| LT-11 | Medium | Global profile save/restore hand-rolled in ≥6 files; global stage-limits mutation risk |
| LT-12 | Medium | Mock is API-only: log/hybrid confirm routes have no offline end-to-end coverage (hybrid is the default) |
| LT-13 | Medium | cv2/ome_types/pytest-cov skips can hollow the suite silently on target machines |
| LT-14 | Medium | opencv-python vs opencv-python-headless conflict between requirements files; ipython in test gate |
| LT-15 | Low | Wall-clock-sensitive race tests are the residual flake surface |
| LT-16 | Low | Stale docstrings (`test_unit.py`, `test_position_parsers.py`, old vendor path) |
| LT-17 | Low | `naming`/`successful_acq` fixtures duplicated across two files |
| LT-18 | Low | Dead `workflows/target_acquisition` sys.path insert in tests/conftest.py **[YAGNI]** |
| LT-19 | Low | Mixed unittest/pytest styles without a stated convention |
| LT-20 | Low | run_ci.py harness triplicated across drivers with unmanaged divergence |
| LT-21 | Low | Coverage denominator misses never-imported modules |
| LT-22 | Low | Dispatch tests assert private kwargs plumbing rather than behavior |

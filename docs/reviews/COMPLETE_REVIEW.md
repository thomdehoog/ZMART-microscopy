# ZMART Controller & Leica Stellaris5 Driver — Complete Code Review

- **Date:** 2026-07-03 · **Reviewed commit:** `c7964dd` (identical to `origin/main` at review time)
- **Scope:** `zmart_controller/` and `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/` only (code, tests, config, docs, notebooks). All other drivers and `shared/` were read for context but not reviewed.
- **Method:** twelve specialist reviews (six component-scoped, six cross-cutting), each reading its scope line-by-line and verifying claims against real call sites — followed by an adversarial verification pass that independently re-checked **every Critical/High finding with the explicit goal of refuting it**, reproducing five of them at runtime. Result: **30/30 Critical+High findings confirmed, 0 refuted, 0 downgraded** (`findings_verification.md`).

---

## 1. Overall verdict

**The architecture is sound; the codebase needs subtraction, not rework.** Both components are design-driven at their core: the controller's ops-table registry is a rare example of an abstraction proven by two independent real consumers, and the driver's dispatch backbone (`confirm_and_fire` + the `CONFIRM_SPECS` table), fail-closed log reader, machine-snapshot config, and atomic materialization are deliberate, well-tested engineering. The refactor review's conclusion — upheld by verification — is that **no architectural rework is warranted**.

The debits cluster in five places:

1. **A confirmation model that leaks at the edges.** The driver's own central invariant — `success` (accepted) ≠ `confirmed` (verified) — is enforced at only one of six seam call sites, ships with `success_on_unconfirmed=True`, and its "hybrid" verification machinery is inoperative at runtime (the race's API leg deadlocks on its own in-flight claim; the passive hybrid path is unreachable at shipped defaults).
2. **Fail-closed reads composed into fail-hung commands.** Unbounded waits (`timeout=None` in every shipped profile for the idle pre-check; `poll_timeout=None` for acquire) turn a hung/crashed LASX into a permanently hung driver.
3. **Safety that exists on paper.** A README-documented orientation safety gate has zero call sites and fails open; calibrated backlash values are schema-required, validated, loaded — and then shadowed by hardcoded defaults on every controller-path move (invisible today only because the bundled values coincide).
4. **~4,000 lines of dead weight** (a zero-consumer evidence subsystem, 24+ dead `lrp_verify_*` wrappers, six orphan debugging scripts totaling 2,686 lines, ≈135 of 216 facade exports unconsumed) plus ~1,100 lines pending a deliberate keep/delete decision.
5. **Broken on-ramps.** Reference documentation is remarkably accurate, but everything a new user touches first — flagship notebook, package docstring recipe, quick-start connection dict — is drifted or crashes.

The single **Critical** finding is operational, not code: the controller CI workflow points at a directory that doesn't exist (`controller/tests` vs `zmart_controller/tests`) and can never pass.

Totals: **~308 numbered actionable items** across twelve documents (including 17 refactor proposals with before/after designs and 12 explicitly rejected refactors), of which 1 Critical and 29 High — all 30 independently re-verified. The YAGNI/dead-weight tally: **≈3,900 lines deletable now**, ≈1,100 more behind one deliberate decision each.

---

## 2. Document index

| Document | Scope | Findings (C/H/M/L) |
|---|---|---|
| `zmart_controller_review.md` | Controller package (layer, registry, tests, notebooks) | 19 (0/2/4/13) |
| `leica_commands_connection_readers_review.md` | commands/, connection/, readers/ + their tests | 31 (0/2/13/16) |
| `leica_scanfields_acquisition_review.md` | scanfields/, experimental/lrp_edits/, acquisition/ + tests | 36 (0/3/14/19) |
| `leica_calibration_config_motion_review.md` | calibration/, config/, motion/, limits/ + tests | 32 (0/2/10/20) |
| `leica_zmart_adapter_toplevel_review.md` | zmart_adapter/, package __init__, utils, run_ci | 28 (0/1/8/19) |
| `leica_tests_ci_review.md` | Test suite as a system, mocks, hardware scripts, CI | 22 (1/3/…) |
| `fossils_dead_code_review.md` | Dead code sweep, both components, whole-repo greps | 25 (0/4/13/8) + TODO inventory (empty — a credit) |
| `overfitting_patchwork_review.md` | Workarounds, magic constants (~40-row inventory), test-shaped code | 35 (0/3/23/9) |
| `refactor_opportunities_review.md` | 17 ranked proposals + 12 considered-and-rejected | RF-01…RF-17 |
| `concurrency_failure_modes_review.md` | Threads, races, LASX hang/crash walkthroughs (runtime-reproduced) | 15 (0/3/…) |
| `api_surface_review.md` | Ops contract, return shapes, units, naming, error taxonomy | 21 (0/1/9/11) |
| `docs_drift_review.md` (rev 2) | Every doc claim vs code, execution-verified | 27 (0/4/14/9) |
| `findings_verification.md` | Adversarial re-check of all 30 Critical/High + cluster map | 30/30 confirmed |

(`driver-cleanup-code-review.md` in the same directory predates this series and is not part of it.)

---

## 3. What genuinely works well

Credited with file:line evidence in the individual documents; the recurring standouts:

- **The controller's ops-table registry** — minimal, boring on purpose, and proven by two real drivers (Leica, mesoSPIM) plugging in unchanged. Copy discipline, credential-safe error messages, and lifecycle ordering are tested behavior, not aspiration.
- **The dispatch backbone and `CONFIRM_SPECS` table** — one command path, table-driven confirmation with drift-pinning tests (`test_confirm_specs.py`), and an honest `success` vs `confirmed` contract *where it is enforced*.
- **The fail-closed log reader** — monotonic deadlines, stateless rotation-safe parsing, measured provenance on every reading, DST-fold-aware timestamp handling, and no silently-dying threads.
- **The exporter → `ExportedAcquisition` → save contract** — fail-closed export collection, honest metadata-authority model, atomic materialization; the transactional LRP editing is explicit about its no-rollback limits.
- **The machine-snapshot config store** — adopt-time provenance hashing and rerun-invalidation discipline, exhaustively pinned.
- **The adapter's safety posture** — fail-closed function limits with a `_MUTATING_OPS` completeness guard (a pattern the other drivers should copy), whole-move pre-flight with actionable hints, loud-degrade reads vs refusing moves.
- **Mock fidelity discipline** — the same validator runs against the mock and the live scope; 660 offline tests pass on a 3-OS × 3-Python CI matrix.
- **Hygiene negatives worth noting:** zero TODO/FIXME markers in both components; the controller is essentially fossil-free; the driver README's reference tables verified accurate by import-and-inspect.

---

## 4. Priority action plan

Findings are grouped by the 18 verified root-cause clusters (`findings_verification.md` §4); fixing the cluster fixes all member findings. IDs reference the detailed documents, where each item carries file:line, evidence, and a concrete recommended fix.

### P0 — Do first (broken gate; wrong-hardware-action risk)

1. **Fix the controller CI path** — `.github/workflows/controller.yml:36` runs `pytest controller/tests`; the directory is `zmart_controller/tests`. The workflow has never been able to pass. *(LT-01, Critical — one-line fix)*
2. **Ignored-calibrated-backlash cluster** — thread `stage_cfg["backlash"]` from the connected machine snapshot into `move_xy_with_backlash`/`correct_backlash` at all three adapter call sites (`zmart_adapter.py:600,753,892`); decide whether `tolerance_um`/`approach` become consumed or leave the schema. Today's correctness is a numeric coincidence with the bundled defaults. *(LA-01 = LM-01 = OP-02 = DD-04)*
3. **Accepted-vs-confirmed seam cluster** — enforce `confirmed` (or an explicit, logged opt-out) at the five seam points that currently accept `success` alone: `set_state`, `acquire`'s job selection, both autofocus selections, `capture.acquire`, and `correct_backlash`; revisit the shipped `success_on_unconfirmed=True` default. This is the wrong-job/wrong-position acquisition class the confirmation layer exists to prevent. *(AS-01, LM-02)*
4. **`strip_template` warn-and-succeed** — a failed template strip logs a warning and returns `success=True`; the in-place sibling correctly fails. A slow LASX session can silently image a stored scan-field pattern instead of the current position. Make it fail like its sibling. *(OP-01)*
5. **Fail-hung-unbounded-waits cluster** — give `check_idle` and `confirm_acquire`'s phase-2 loop real deadlines (all shipped profiles have `timeout=None`; acquire's is `t_start + 1e9`), so a dead LASX produces an error instead of a permanent hang. *(CF-02, CF-03)*
6. **Paper-safety-gates cluster** — either call `require_canonical_scan_orientation` at session start (and make it fail closed on unreadable settings) or delete it and its README section. A safety net that exists only as text is worse than none. *(FD-03 = DD-03, LC-10)*

### P1 — Correctness debt in the confirmation model

7. **Select-job-evidence-window cluster** — anchor the log-evidence window after the idle pre-check (not at wrapper entry), use monotonic time, and give `selected_job_log_cluster_max_age_s` a real default (one consumer treats `None` as "no limit", another silently aliases it to 2.0 s). *(LC-02 = OP-03, CF-04, OP-05)*
8. **Inoperative-hybrid-machinery cluster** — the confirmation race's API leg self-blocks on its own non-reentrant in-flight claim (reproduced: zero CAM reads inside a race) and the abandoned leg outlives its budget; the passive hybrid read race is unreachable at shipped `"api"` defaults. Decide: make hybrid real (re-entrant claim or claim handoff) or delete the machinery and ship honest log-only/api-only modes. *(CF-01, CF-05, LC-11, FD-11, RF-03)*
9. **Flush-fire-poll-drift cluster** — collapse the four copied CAM read skeletons in `api_reader.py` into one primitive with stale-response correlation as a structural property (today only `get_job_settings` has it); this also fixes the tautological `observed_after` freshness gates. *(LC-09 = RF-04, OP-04, OP-14)*
10. **Echo-flush swallow** — `dispatch.py:299-302` silently swallows a failed echo `Result` reset, letting `_await_echo_result` settle on the previous command's echo. *(LC-03)*
11. **Teardown-gap cluster** — implement real CAM client teardown in `disconnect` (today flag-only; reconnects leak live connections), and fix the controller's module-level `set_instrument` docstring/semantics (the ">1 microscope" recipe kills the first session). *(ZC-01 = DD-01, CF-06, ZC-03)*
12. **Non-atomic template writes** — two sites rewrite the live `.lrp` in place; use the write-temp-then-rename pattern the rest of the code already uses. *(CF-07)*
13. **Units trap on a public reader** — `readers.get_xy` returns metres under bare `x`/`y` keys beside `x_um`/`y_um`; the root export `um()` converts *to* metres. Rename or remove the metre keys. *(AS-07, AS-20)*
14. **Verdict-by-prose plumbing** — calibration layers re-derive verdicts by substring-matching `failure_reason` text in four places; error taxonomy across the seam is bare `RuntimeError` prose for 8+ distinct failure classes. Introduce small typed verdicts/exceptions. *(LM-04, AS-03, RF-10)*

### P2 — Subtraction: dead weight and YAGNI (≈3,900 lines deletable)

15. **Dead-evidence-leg subsystem** — delete `readers/capabilities.py`'s change/target evidence machinery (~95 lines + `xy_min_delta_um` knob); zero call sites; its docstring claims it powers the race it never touches. *(LC-01 = FD-01, RF-03)*
16. **Dead-lrp_edits-surface cluster** — promote the 3 production-consumed functions out of `experimental/` (the name misleads in both directions), delete the 24+2 dead `lrp_verify_*` wrappers, dead coordinate helpers, and ~60 consumer-less facade exports. *(FD-02, LS-13/14/15, RF-05; +`lrp_verify_roi`/`lrp_verify_roi_count` per verification §5)*
17. **Orphan-hardware-scripts** — delete or archive the six referenced-by-nothing one-shot scripts in `tests/hardware/` (2,686 lines), and fix `validate_readers_side_by_side.py`, which crashes on nonexistent profile fields — or delete it too. *(FD-04, FD-12, LT-08)*
18. **Facade-bloat cluster** — shrink the 216-name package `__all__` to the real public surface (≈135 names have no consumer via the root; 14 are underscore-private; the mutable `_stage_limits` dict shouldn't be exported). The API-surface review's minimal-surface proposal + RF-06 give the target list. *(LA-05/06, FD-05, AS-20, DD-21)*
19. **Fossil-self-referential-tests cluster** — delete `TestAcquisitionProtocol` (360 lines asserting on its own mocks), removed-API tombstones, hasattr inventories, and the 13 redundant `sys.path` bootstraps. *(LT-06, LT-09, FD-14, RF-01 — ~550 lines, zero risk)*
20. **Dead config keys** — remove `LIMITS_SOURCE_MIGRATION` (written/read by nothing); keep `LIMITS_SOURCE_CFG_FALLBACK` (production caller found — adjudicated in verification §3). Stop tracking runtime `limits/current.json` in VCS. *(LM-19 as corrected by FD-07, LM-07)*

### P3 — Test suite, packaging, docs

21. **Uninjected-test-sleeps cluster** — make timeouts injectable; one test burns 60.06 s (measured) of a ~124 s suite and nine more burn 3 s each. Fixing drops the offline suite to ~25 s, ×9 CI jobs. *(LS-34 = LT-02, LT-03, RF-02)*
22. **Untested-byte-level-code cluster** — add direct tests for the 380-line LRP parser (five real fixtures already sit in `tests/data/`) and the binary TIFF tag-270 patcher (every existing test mocks it; production repairs files in place); add `fail_under` to `.coveragerc` and make CI consume coverage. *(LS-01, LS-21, LT-04)*
23. **Packaging-gap cluster** — add a `[project]` table to `pyproject.toml`; retire the ≥20 `sys.path` bootstrap copies. *(ZC-14, LA-19, LT-10, RF-17)*
24. **Marker-fiction** — `hardware`/`slow` markers are registered, documented, filtered on — and used by zero tests; either apply them or delete them and document the real filename-based split. *(LT-05 = FD-15 = DD-07)*
25. **Broken-tuning-advice cluster** — `utils.py`'s "import and override" for `RECEIPT_TIMEOUT`/`CONFIRM_POLL_S` cannot work (import-time value binding); move these into the profile system built for exactly this. *(LA-07 = DD-06, RF-02)*
26. **Fix the on-ramps** — repair `example_experiment.ipynb` (crashes at step 2 on stale `mutable`/`immutable` keys), the package docstring's multi-microscope recipe, the README connection dict (missing required `output_root`, stale host/delay values), and document the five load-bearing behaviors no doc mentions (session teardown, persisted `origin.json`, the fail-closed function-limits gate, default scan-field stripping, naming/overwrite semantics). *(ZC-02 = DD-02, ZC-01, ZC-05, DD-05/08/15/16/17)*
27. **Controller-side contract gaps** — document how ops report failure (raise vs error-dict is currently convention-by-imitation), and drop the implemented-by-no-driver `with_actuators` read semantics. *(AS-02, AS-04, LA-03)*

The remaining ~200 Medium/Low items (naming, typing, docstrings, small dedups, notebook hygiene) are enumerated per document with file:line and a concrete action each; they are real but should ride along with the P0–P3 work rather than be scheduled separately.

### Explicitly rejected (do not do)

The refactor review records 12 considered-and-rejected refactors so they don't get re-proposed — notably: a driver-wide typed-result dataclass migration, merging `ome.py`/`ome_canonical.py` (verified: a coherent split sharing exactly one helper), and full collector unification. See `refactor_opportunities_review.md` §4.

---

## 5. Confidence statement

Every Critical/High finding in this series was independently re-verified against the code at `c7964dd` by an adversarial pass instructed to refute them; five were reproduced at runtime against the mock/offline package (the multi-microscope disconnect, the self-blocking hybrid race leg, the `check_idle` permanent hang, and both slow-test measurements). Dead-code claims were verified by whole-repo reference search including notebooks, workflows, and other drivers. Two findings carry rationale corrections that do not change their verdicts; three "High" ratings are High under maintainer-cost rubrics rather than production risk and are grouped accordingly above. No Critical/High issue was found that all twelve documents missed.

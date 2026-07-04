# Review: Leica Stellaris5 driver — `calibration/`, `config/`, `motion/`, `limits/` (+ their unit tests)

- **Scope**: `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/` — subpackages `calibration/` (core, defaults, notebooks, tests), `config/` (`machine.py`, `profiles.py`), `motion/` (`movement.py`, `limits.py`, `stage_config.py`), `limits/` (`current.json`, `defaults/`, notebook bootstrap), and the unit tests pinning these modules (`tests/unit/test_stage_backlash.py`, `test_stage_config.py`, `test_machine_profile.py`, `calibration/tests/`). `shared/limits/spec.py` and `shared/algorithms/{focus,registration}.py` were read for context only; no findings are filed against `shared/`. Call sites in `zmart_adapter/` and `workflows/` were inspected only to trace consumers of the modules under review.
- **Date**: 2026-07-03
- **Reviewed commit**: `c7964dd` (working tree == origin/main)
- **Review 4 in the series** for this driver; commands/connection/readers, scanfields/acquisition, and zmart_adapter/top-level are covered by other reviews.

---

## Executive summary

This is a strong subsystem. The machine-snapshot model (`config/machine.py`) is a small, correct, well-reasoned design: dated cumulative snapshots with a monotonic-stamp guard, atomic publish via staged rename, copy-forward of untouched files, and loud fallback to bundled last-known-good defaults. The calibration workflows carry an unusually disciplined invariant culture — staging configs are invalidated *before* any driver call on rerun, every upstream rerun clears exactly the downstream state it stales, and the adopt path refuses translations whose `image_to_stage` provenance hash does not match the active matrix. The test suite pins all of this behaviorally, including exception-path invariants and stale-TIFF wipes, which is rare and valuable.

The main problems are (1) **a broken promise around calibrated backlash**: the calibration schema requires and validates a backlash block (`approach`/`overshoot_um`/`settle_ms`/`tolerance_um`), `stage_config.load()` faithfully returns it, and `movement.py`'s docstrings insist production callers pass it — yet the adapter (the primary runtime motion path) calls both backlash primitives with hardcoded defaults, `tolerance_um` and `approach` are consumed by *nothing anywhere*, and the calibration sessions store `stage_cfg` without ever reading it; (2) **an asymmetric confirmation contract** between the two backlash primitives (`move_xy_with_backlash` demands `confirmed`, `correct_backlash` silently accepts unconfirmed jogs); and (3) **string-typed verdict state**: the measure/report/plot/print layers communicate the rejection verdict by substring-matching `failure_reason` prose in four places — classic patchwork that a rewording will silently break. Below those, there is a tail of duplication (three-and-a-half atomic JSON writers with real behavioral drift, duplicated `_f`/report helpers, duplicated clear-step logic), some test-only public API in `model.py`, and assorted hygiene.

Nothing here is a data-corruption or safety Critical. The two Highs are about calibrated values silently not reaching the hardware path they were calibrated for.

---

## What works well

Credit where due — these are specific and worth preserving:

- **Snapshot store design** (`config/machine.py`): the monotonic guard in `new_snapshot_dir()` (machine.py:248–263) makes "newest wins" immune to backward clocks and same-microsecond collisions; `publish_snapshot()` (machine.py:275–319) stages into `.<name>.partial` and `os.replace()`s into place, with cleanup on any `BaseException`, so a crash mid-publish can never corrupt the calibration currently being read. The Windows-safe, lexically-sortable UTC stamp format is documented with its rationale (machine.py:27–37).
- **Adopt-time provenance gate** (`calibration/core/adopt.py:86–116`): staged objective translations record the `image_to_stage_hash` they were measured under, and adoption refuses a mismatch or a missing hash with a message that explains *why* the correction is invalid. This closes a real silent-corruption channel, and `test_workflows.py:781–833` pins both refusal paths fail-closed.
- **Rerun-invalidation discipline** (`objective_pair.py:314–424`, `image_to_stage.py:143–168`): staging configs are unlinked *before* any driver call so a mid-measure exception cannot leave a stale adoptable artifact; each `measure_*` step composes exactly the `_clear_*` helpers for the state it stales, with the dependency reasoning written down at each call site (e.g. objective_pair.py:410–418, 503–508). The test matrix (`test_workflows.py:1973–2330`) drives every rerun permutation plus the exception-during-rerun paths.
- **Refusal to guess z positions** (`common.py:331–446`): stack positions come only from an explicit override or LAS X's authoritative `begin`/`end`/`sections`; slice-count/section mismatches, missing metadata, and wrong z-drive all raise with operator-actionable messages. The decision *not* to cross-check the vendor's display-rounded `stepSize` is documented with the measured evidence (common.py:438–445) and pinned by a regression test (`test_workflows.py:2821–2860`).
- **Numerically careful focus fit**: `_parabolic_peak` (objective_pair.py:255–276) rejects edge peaks with a diagnosis-quality error message and guards the zero-denominator case; the signed z-step handling is pinned by the descending-stack test (`test_workflows.py:2685–2734`), which asserts the sub-slice correction moves in the correct direction — exactly the kind of sign-convention test this math needs.
- **Strict JSON posture in the workflows**: `write_json_atomic` uses `allow_nan=False` (common.py:452–460) and `_f()` coerces NaN/inf to `None` before serialization; tests parse reports with a strict parser that rejects NaN tokens (`test_workflows.py:963–1008`).
- **`move_xy_with_backlash` contract** (motion/movement.py:83–107): requiring `confirmed` (not just `success`) on both legs, with the comment explaining why `success=True` alone is insufficient under `success_on_unconfirmed=True`, plus the pinning unit test (`test_stage_backlash.py:11–28`).
- **Schema versioning everywhere**: calibration v11 with `OldSchemaError` pointing at the recovery action (model.py:57–81), limits v1 with a source-provenance vocabulary (`stage_config.py:25–39`), staging schema v1 checked at adopt (adopt.py:144–148).
- **Honest, load-bearing comments**: `absolute()` vs `resolve()` justified by a real rig failure (common.py:89–92); the hybrid select-job confirm rationale (profiles.py:104–111); `_STACK_LEADING_SLICES_TO_SKIP` provenance (objective_pair.py:205–211).
- **Test quality**: `test_machine_profile.py` covers the full resolver surface including partial snapshots, origin round-trip/carry-forward, and no-partial-leftover on failure; `test_workflows.py`'s driver mock (`_patch_objective_driver`, 1216–1436) simulates stack phases and Brenner response cleanly enough to test the real analysis code rather than mocking it away.

---

## Findings

### High

**LM-01 — Calibrated backlash parameters are validated, loaded, and then largely ignored** **[YAGNI]**
`High` — `motion/stage_config.py:129–143`, `motion/movement.py:24–25,133–135`, `calibration/core/model.py:98–110`, `zmart_adapter/zmart_adapter.py:600,753,892`
The calibration schema *requires* a `backlash` block with `approach`, `overshoot_um`, `settle_ms`, `tolerance_um`, `session_id` (validated twice: `model.validate_calibration` and `stage_config._validate_backlash`). `movement.py`'s module and function docstrings state "Production callers should pass `stage_cfg['backlash']` … the function defaults below are last-resort fallbacks, not the source of truth." Reality:
- The zmart adapter — the primary runtime motion path — calls `move_xy_with_backlash(handle.client, abs_x, abs_y)` and `correct_backlash(handle.client)` with **no** backlash arguments (zmart_adapter.py:600, 753, 892), despite loading the stage config at connect.
- The target-acquisition workflow passes `overshoot_um` and `settle_ms` but not `tolerance_um` (`workflows/target_acquisition/pipeline/focus.py:325–332`, `_acquire.py:40–47`).
- `tolerance_um` and `approach` are therefore consumed by **nothing in the repository**; `approach` is a pure schema ornament (the "+X+Y" direction is hardcoded in `movement.py`).
- The calibration sessions' own test fixture returns `{"backlash": {"x_um": 50.0, "y_um": 50.0}}` (`test_workflows.py:277,1257`) — a shape matching no real schema — and nothing notices, which is direct evidence nothing reads it.
*Why it matters*: an operator who recalibrates backlash (the schema's stated purpose) will see no behavior change on the adapter path; the docstrings actively mislead the next maintainer. *Action*: either wire the calibrated block through the adapter (it already holds `stage_cfg` at connect) and pass `tolerance_um` in the workflow, or delete `tolerance_um`/`approach` from the schema and fix the movement.py docstrings to match reality. Pick one; the current half-state is the worst option.

**LM-02 — `correct_backlash` accepts unconfirmed moves, contradicting its sibling's contract**
`High` — `motion/movement.py:146–151` vs `motion/movement.py:96–104`
`move_xy_with_backlash` raises unless both legs are `success` **and** `confirmed`, with a comment explaining that under `success_on_unconfirmed=True` a bare `success` proves nothing about position. `correct_backlash` — the same physical operation, used immediately before acquisitions (`zmart_adapter.py:753`) — checks only `r.get("success")` on both legs. An unconfirmed jog or return silently "succeeds": the slack-state may be unpinned, or worse, the stage may still be at the −X−Y overshoot point when the acquisition fires, and nothing raises. This is precisely the failure mode the module docstring says the raise-contract exists to prevent. *Action*: require `confirmed` on both legs of `correct_backlash` exactly as in `move_xy_with_backlash`, and add the missing unit test (see LM-24).

### Medium

**LM-03 — `float(read_zwide_um(...))` crashes with a bare `TypeError` when readback is unavailable; mode not pinned**
`Medium` — `calibration/core/objective_pair.py:441,519`
`drv.read_zwide_um` fails closed with `None` (readers/router.py:435–444). `session.home_z = float(drv.read_zwide_um(...))` and `z_post = float(drv.read_zwide_um(...))` turn that into `TypeError: float() argument must be … not 'NoneType'` — useless at the rig, and inconsistent with `move_zwide_and_verify`, which checks `None` and raises a labeled error (common.py:207–209). Both reads also omit `mode="api"`, while every other calibration-value read in this package pins it explicitly with a comment (common.py:123–124, 364–366); `z_post` parameterizes `motor_shift_z_um`, a persisted report value, so per the driver's own stated rule (profiles.py:79–84) it must pin API rather than inherit the profile default. *Action*: check `None` with a clear message and pass `mode="api"` at both call sites.

**LM-04 — Verdict state machine implemented as substring matching over `failure_reason` prose in four places** **[PATCHWORK]**
`Medium` — `calibration/core/image_to_stage.py:364–366,594–596`, `calibration/core/common.py:845–846`, `calibration/core/objective_pair.py:287`
`measure()` encodes its verdict in an English sentence (`"reflection candidate selected; this workflow assumes a reflection-free optical path"`, `"singular stage_to_image matrix (…)"`), and then `_operator_status_header`, the `save_and_visualize` status ladder, and `plot_d4_candidates` each re-derive the verdict by checking `"reflection-free" in failure_reason` / `"singular" in failure_reason`. `_print_step5_summary` similarly re-parses the composed status string with `status.split(" (", 1)[0]`. Rewording any failure message — a natural doc-polish change — silently reroutes three UI layers to the generic `NO WINNER`/`FAILED` branch with no test loudly failing at the source. *Action*: add a small verdict enum/code field (`session.verdict: "ok" | "weak_vote" | "reflection" | "residual" | "singular"`) set once in `measure()`; keep `failure_reason` as prose for humans only. All four consumers switch on the code.

**LM-05 — Two unlinked constants encode the same "minimum stack sections" invariant**
`Medium` — `calibration/core/common.py:45` and `calibration/core/objective_pair.py:211–216`
`MIN_FOCUS_STACK_SECTIONS = 5` (gates `read_stack_z_positions`) and `_MIN_STACK_SECTIONS_FOR_FOCUS_FIT = lead + trail + min_fit = 5` (gates `_fit_focus_z`) are numerically equal today but live in different modules with no reference to each other. Change the trim policy (e.g. skip 2 trailing slices) and the position reader will happily accept a 5-section stack that the fitter then rejects — a late, confusing failure after acquisition has already run. *Action*: define one in terms of the other (export the trim constants from `objective_pair` or move them to `common` and derive `MIN_FOCUS_STACK_SECTIONS`), so the invariant has one home.

**LM-06 — Three-and-a-half atomic-JSON writers with real behavioral drift (fsync, NaN policy, key order)**
`Medium` — `calibration/core/model.py:45–54`, `motion/stage_config.py:92–100`, `calibration/core/common.py:452–460`, `config/machine.py:89–92,232–246`
Four JSON writers exist in this review's scope: `model._atomic_write_json` (fsync, `sort_keys=True`, **allows NaN**), `stage_config._atomic_write_json` (identical copy of the previous), `common.write_json_atomic` (no fsync, `sort_keys=False`, `allow_nan=False`), and `machine._write_json` (no tmp-file, no fsync; atomic only via `write_origin`'s own replace or the snapshot-folder rename). The NaN drift is the substantive one: `validate_calibration` never checks finiteness of `translation_um`, so a NaN introduced via `update_objective` would be serialized as a bare `NaN` token into the canonical `calibration.json` — which the strict-JSON posture elsewhere in this package exists to prevent, and which some parsers reject. *Action*: one shared `write_json_atomic(path, payload, *, fsync=..., sort_keys=...)` with `allow_nan=False` everywhere; add a finiteness check to `validate_calibration`.

**LM-07 — `limits/current.json` is per-run runtime data tracked in VCS inside the package tree**
`Medium` — `limits/current.json`, `motion/stage_config.py:11–13,59–66`
The committed file carries a rig- and run-specific boundary-marker envelope (x ≈ 28170–35214 µm). Every target-acquisition run rewrites it via `write_stage_limits_config` (`workflows/target_acquisition/pipeline/template.py:731`), dirtying the working tree, and the calibration README explicitly says runtime session artifacts "should not be committed" — the same principle applies here. The module docstring already admits `current_path`/`write_limits` are legacy pending a lift into the workflow. *Action*: do the lift (write the working envelope under the run's output root), or at minimum gitignore/untrack `limits/current.json` and commit a placeholder elsewhere. Until then this file is a standing merge-conflict and false-provenance hazard.

**LM-08 — Backlash overshoot leg makes targets near the low envelope corner unreachable, with a misleading error**
`Medium` — `motion/movement.py:89–101,143–147`
Both primitives drive to `(x − overshoot, y − overshoot)` unconditionally. Within `overshoot_um` (default 50 µm) of `x_min`/`y_min`, the overshoot waypoint violates the Phase-A stage-limit check and the whole move fails — the operator sees "X=… outside limits" for a target that is itself perfectly legal. With the tight boundary-marker working envelope in `current.json` (a few-mm span), this corner is not hypothetical. *Action*: document the constraint in the docstrings at minimum; better, clamp the waypoint to the envelope (a shorter takeup still exceeds the 3–5 µm physical backlash by a wide margin) and log the clamp.

**LM-09 — `model.py` ships four public functions used only by tests** **[YAGNI]**
`Medium` — `calibration/core/model.py:148–157,296–309,368–381,384–401`
`save_calibration`, `set_reference`, `reference_to_objective_command_xy`, and `pixel_to_stage_xy_um` have no production callers anywhere in the repo (adopt publishes via `prepared_calibration` + `publish_snapshot`; workflows use `translate_xyz_between_objectives`; the adapter uses `get_translation_um`). `pixel_to_stage_xy_um` additionally hardcodes a square image (`image_size: int`, `centre = image_size / 2.0`) — a latent trap inconsistent with the (h, w) handling elsewhere. Test-only public API is bloat that must be maintained and reviewed forever. *Action*: delete the four (and their tests), or move whichever is genuinely imminent into the module that will call it. If `pixel_to_stage_xy_um` survives, take `(h, w)`.

**LM-10 — Step 5 re-implements `_clear_parcentricity_target` inline**
`Medium` — `calibration/core/objective_pair.py:636–647` vs `objective_pair.py:332–343`
The "reset this step's outputs" block in `measure_parcentricity_target_and_save` duplicates the existing helper field-for-field (including the `target_xy.tif` unlink). The invalidation helpers exist precisely so each cell composes them (module comment, objective_pair.py:316–323); this one inline copy is where the next added session field will be forgotten. *Action*: call `_clear_parcentricity_target(session)` and keep only the extra `config_written = False` line (or fold that into the helper).

**LM-11 — `_f` and `_registration_for_report` duplicated across the two workflow modules**
`Medium` — `calibration/core/objective_pair.py:184–202` vs `calibration/core/image_to_stage.py:297–313`
Byte-for-byte duplicate `_f`; near-duplicate `_registration_for_report` (one accepts `None`, one doesn't — drift has already started). These are report-serialization helpers that belong in `common.py` next to `write_json_atomic`. *Action*: move both to `common.py`; keep the `None`-tolerant signature.

**LM-12 — `read_job_geometry` reads without None-guard on `pixel_h_um`; `ImageGeometry` carries three redundant pixel fields** **[YAGNI]**
`Medium/Low` — `calibration/core/common.py:126–150`, `common.py:60–66`
The guard checks `pixel_w_um` and `pixels_x` for `None` but then does `float(geom["pixel_h_um"])` unguarded (common.py:132) — a settings dict with `pixel_w_um` present but `pixel_h_um: None` produces a `TypeError` instead of the curated `ValueError`. Separately, after non-square pixels are rejected, `pixel_size_um == pixel_w_um == pixel_h_um` always, and `format_px` has no production reader — three of five dataclass fields are dead weight kept "for v1 symmetry". *Action*: include `pixel_h_um`/`pixels_y` in the None-check; drop `pixel_w_um`/`pixel_h_um`/`format_px` from `ImageGeometry` until something reads them.

### Low

**LM-13 — `objective_config_name()` helper exists but the workflow re-derives the name inline**
`Low` — `calibration/core/objective_pair.py:144–145` vs `calibration/core/common.py:80–81`
`start_session` builds `f"objective_{slug(from)}_to_{slug(to)}.json"` by hand; the shared helper is used only by tests. Two constructors for a filename that `adopt._expected_kind_for` (adopt.py:29–40) pattern-matches against is drift waiting to happen. *Action*: use the helper in `start_session`.

**LM-14 — Dead singular-candidate branch in `compute_d4_candidate_residuals`** **[YAGNI]**
`Low` — `calibration/core/common.py:606–619`
Every D4 element is orthogonal (det ±1); `np.linalg.inv` cannot raise `LinAlgError` for any entry of `D4_ELEMENTS`. The 14-line defensive branch (inf residuals, `None` predictions) is unreachable and its handling is itself untested. *Action*: delete the try/except; a comment "D4 elements are orthogonal, inversion cannot fail" is cheaper.

**LM-15 — `_norm` closure and magenta/green overlay composition duplicated three ways inside `common.py`**
`Low` — `calibration/core/common.py:481–487,647–652,725–731` and `common.py:492–496` vs `732–739`
Three identical `_norm` implementations and two copies of the RGB overlay stacking in one module. *Action*: hoist a module-level `_normalize01(img)` and `_magenta_green(ref, tgt)`.

**LM-16 — IPython-display / `plt.close` boilerplate repeated five times**
`Low` — `calibration/core/objective_pair.py:428–431,470–478,513–516,555–563,656–658,742–749`; `image_to_stage.py:447–454`
The `try: from IPython.display import display except: display=None` + `display(fig)` + `try: plt.close(fig) except: pass` dance is copy-pasted per step. *Action*: one `common._display_and_close(fig)` helper; also removes four bare `except Exception: pass` blocks.

**LM-17 — `CommandProfile` typing hygiene: `callable` as an annotation, `float = None` defaults**
`Low` — `config/profiles.py:229–246`
`pre_check_fn: callable = None`, `confirm_tolerance: float = None`, `poll_interval: float = None`, etc. — `callable` is the builtin, not a type, and the `None` defaults belie the annotations. Static checkers get nothing from this dataclass, which is the driver's central tuning surface. *Action*: `Callable[..., dict] | None`, `float | None`; no behavior change.

**LM-18 — `_leica_setting_profile` no longer earns its existence** **[YAGNI]**
`Low` — `config/profiles.py:259–273`
The helper's own docstring admits everything it once configured "is the `CommandProfile` default now, so the helper only binds the confirm function." Fourteen call sites route through a wrapper that is `CommandProfile(confirm_fn=..., **overrides)`. *Action*: either inline it (14 mechanical edits) or keep it *only* if you value the semantic marker "this is a Leica setting command" — in which case say so in the docstring instead of the historical explanation.

**LM-19 — `LIMITS_SOURCE_MIGRATION` is written by nothing; `CFG_FALLBACK` only by a test** **[YAGNI]**
`Low` — `motion/stage_config.py:30,28`
Of the five provenance tags, `defaults`, `boundary_markers`, and `scan_field` have real writers (adopt default, workflow template.py:128/263); `migration` appears nowhere outside its definition and export, and `cfg_fallback` only in `test_stage_config.py:268`. *Action*: delete `migration`; keep `cfg_fallback` only if the workflow lift (LM-07) will use it.

**LM-20 — Session dataclasses store `stage_cfg` that nothing reads**
`Low` — `calibration/core/objective_pair.py:77,169`, `calibration/core/image_to_stage.py:65,113`
`start_session` loads and *applies* the stage limits (good), then also stashes the dict on the session, where no code touches it again. Dead field on both dataclasses. *Action*: apply the limits and drop the field (or actually use its backlash block for the calibration moves — cross-ref LM-01).

**LM-21 — `_load_image_to_stage` returns a single-key dict that is immediately unpacked**
`Low` — `calibration/core/objective_pair.py:124–132,155,174`
`return {"image_to_stage": ...}` followed by `i2s["image_to_stage"]` at the sole call site. *Action*: return the matrix.

**LM-22 — `adopt._contains_ordered_tokens` matches token *subsequences*, which over-matches**
`Low` — `calibration/core/adopt.py:59–83`
The operator label is matched as an ordered subsequence of the objective-name tokens, so `"hc dry"` matches `"HC PL APO CS2 10x/0.40 DRY"` and `"cs2 40x"` matches slot 0 — looser than the presumably-intended contiguous match. The `len(matches) != 1` ambiguity check catches collisions between slots but not a single wrong-but-unique fuzzy hit. Also note `_norm_label("0.5x") == "0_5x"` while `common.slug` produces `"0p5x"` — two normalizations for objective names in the same package. *Action*: require a contiguous token run (or exact normalized substring), and consider reusing one normalizer.

**LM-23 — Hardware validator references `LOG_READER` fields that do not exist**
`Low` — `tests/hardware/validate_readers_side_by_side.py:315–316,401–402` vs `config/profiles.py:63–69`
`profiles.LOG_READER.poll_timeout` / `.poll_interval` — `LogReaderProfile` has neither field; the script dies with `AttributeError` on first use. Evidence the profile was slimmed without sweeping consumers. *Action*: fix or delete the stale references in the validator.

**LM-24 — Backlash unit-test gaps mirror the code asymmetry**
`Low` — `tests/unit/test_stage_backlash.py`
Good coverage of `move_xy_with_backlash` (order, values, both failure legs, unconfirmed-final). Missing: unconfirmed *overshoot* leg (only `success=False` is tested), and — decisively — nothing pins `correct_backlash`'s confirmation behavior at all, which is how LM-02 survives. `TestCorrectBacklash` checks only the API-mode pin and move sequence. *Action*: after fixing LM-02, add unconfirmed-leg tests for both primitives.

**LM-25 — `test_runtime_paths_preserve_drive_letter` is a tautology on POSIX**
`Low` — `calibration/tests/integration/test_workflows.py:104–116`
On non-Windows, `sessions_root.absolute().drive == ""`, so `str(...).startswith("")` is always true and the `or` short-circuits — the test can never fail where CI runs. The real property (`absolute()` not `resolve()`, no UNC conversion) is only enforced by the comment in `make_session_paths`. *Action*: assert `paths.session_dir == sessions_root.absolute() / "probe"` instead, and/or monkeypatch a fake `resolve` to prove it is never called.

**LM-26 — `test_model.py` re-inserts `sys.path` inside every test via `_load_calibration_module()`**
`Low` — `calibration/tests/unit/test_model.py:8–16`
`conftest.py` already sets up both path roots; the per-test `sys.path.insert` (never removed, appended 18 times per run) and the indirection of `cal = _load_calibration_module()` in every test add noise for zero benefit. *Action*: plain module-level `import navigator_expert.calibration.core.model as cal`.

**LM-27 — `migrate_legacy_snapshots` is manual-only, and its reminder only fires on the fallback path**
`Low` — `config/machine.py:135–151,202–209`
The migration hint is logged only when `resolve()` falls back to bundled defaults. If a post-migration-era snapshot exists *and* legacy snapshots also exist, the legacy history is silently invisible forever — no warning, no migration. One-time migration code also tends to fossilize (cross-ref the fossil-sweep review). *Action*: either call the migration opportunistically from `snapshots()`/`resolve()` (it's idempotent and cheap), or log the legacy-exists warning unconditionally; schedule deletion once the rig's tree is migrated.

**LM-28 — Stale docstring: `acquire_frame_to` advertises slash-subdirectory names no caller uses**
`Low` — `calibration/core/common.py:223–228`
"``name`` may contain forward slashes to create subdirectories (e.g. ``target_z_stack/z_003``)" — stacks now go through `acquire_stack_to`; every `acquire_frame_to` caller passes a bare name. The `out.parent.mkdir` support code is kept alive by a doc example that no longer exists. *Action*: trim the docstring (and the `mkdir` if you want it strict).

**LM-29 — `_geometry_for_label` swallows exceptions into `det = 0.0`, mislabeling garbage as "rotation"**
`Low` — `calibration/core/image_to_stage.py:336–351`
The `except Exception: det = 0.0` fallback means a malformed `snapped` matrix falls through the `det < 0` reflection check and returns the dictionary default `"rotation"` — a wrong-but-confident operator label. The input is always a D4 matrix in practice, so the try/except is defensive dead weight that *degrades* behavior in the case it defends against. *Action*: let it raise, or return `"not evaluated"` on failure.

**LM-30 — Duplicated `_bootstrap.py` between `calibration/notebooks/` and `limits/notebooks/`**
`Low` — `calibration/notebooks/_bootstrap.py`, `limits/notebooks/_bootstrap.py`
Two near-identical 15-line sys.path shims (one word of comment differs). Fragile `parents[6]`/`parents[3]` indexing duplicated means a tree reshuffle must be fixed twice. *Action*: acceptable as-is for notebook ergonomics, but a single shared `notebooks/_bootstrap.py` (or a comment cross-linking them) would prevent silent divergence.

**LM-31 — `set_stage_limits` accepts unvalidated values into the safety-critical singleton**
`Low` — `motion/limits.py:38–51`
The public setter (exported at the driver top level) does no validation: partial `None`s, min > max, or strings all land in `_stage_limits`, and the checks then fail with raw `TypeError`s on comparison (`_check_xy_limits` only probes `x_min` for `None`). The validated path (`apply_stage_limits_from_config` ← `stage_config._validate_limits`) is safe, but the raw setter is the one a hurried script will reach for. Also note `_stage_limits` itself (a private mutable dict) is exported in `__init__.py:352`. *Action*: validate numerics and min ≤ max in `set_stage_limits`; stop exporting `_stage_limits`.

**LM-32 — `machine.read_origin` parses without error context**
`Low` — `config/machine.py:222–230`
A corrupted `origin.json` (partial write predates the atomic writer, or hand-editing) surfaces as a bare `json.JSONDecodeError` from deep inside frame-restore at connect. Every other config read in this package wraps parse failures with the offending path. *Action*: wrap with a message naming the file and the recovery (`set_origin` again / delete the file).

---

## Summary table

| ID | Severity | Title |
|-------|----------|-------|
| LM-01 | High | Calibrated backlash block validated everywhere, consumed almost nowhere; docstrings promise otherwise **[YAGNI]** |
| LM-02 | High | `correct_backlash` accepts unconfirmed moves, contradicting `move_xy_with_backlash`'s contract |
| LM-03 | Medium | `float(read_zwide_um(...))` crashes on `None` readback; API mode not pinned for persisted values |
| LM-04 | Medium | Verdict communicated by substring-matching `failure_reason` prose in four places **[PATCHWORK]** |
| LM-05 | Medium | Two unlinked constants encode the min-stack-sections invariant |
| LM-06 | Medium | Four JSON writers with fsync/NaN/key-order drift; NaN can reach canonical calibration.json |
| LM-07 | Medium | `limits/current.json` is per-run runtime data tracked in VCS inside the package |
| LM-08 | Medium | Backlash overshoot makes targets near the low envelope corner unreachable with a misleading error |
| LM-09 | Medium | Four `model.py` public functions have test-only callers **[YAGNI]** |
| LM-10 | Medium | Step 5 re-implements `_clear_parcentricity_target` inline |
| LM-11 | Medium | `_f` / `_registration_for_report` duplicated across workflow modules |
| LM-12 | Medium/Low | `pixel_h_um` unguarded in geometry read; redundant `ImageGeometry` fields **[YAGNI]** |
| LM-13 | Low | `objective_config_name()` helper bypassed by its intended caller |
| LM-14 | Low | Unreachable singular-D4 defensive branch **[YAGNI]** |
| LM-15 | Low | `_norm` / overlay composition duplicated 3× inside `common.py` |
| LM-16 | Low | IPython-display / `plt.close` boilerplate repeated five times |
| LM-17 | Low | `CommandProfile` typing hygiene (`callable`, `float = None`) |
| LM-18 | Low | `_leica_setting_profile` wrapper no longer earns its existence **[YAGNI]** |
| LM-19 | Low | `LIMITS_SOURCE_MIGRATION` unused; `CFG_FALLBACK` test-only **[YAGNI]** |
| LM-20 | Low | Session dataclasses store `stage_cfg` nothing reads |
| LM-21 | Low | Single-key dict indirection in `_load_image_to_stage` |
| LM-22 | Low | Ordered-subsequence objective-label matching over-matches; dual name normalizers |
| LM-23 | Low | Hardware validator references nonexistent `LOG_READER` fields |
| LM-24 | Low | Backlash test gaps: unconfirmed overshoot leg; `correct_backlash` confirmation unpinned |
| LM-25 | Low | Drive-letter preservation test is a tautology on POSIX |
| LM-26 | Low | Per-test `sys.path.insert` indirection in `test_model.py` |
| LM-27 | Low | Legacy-snapshot migration is manual-only and its reminder is conditional |
| LM-28 | Low | Stale slash-subdirectory docstring on `acquire_frame_to` |
| LM-29 | Low | `_geometry_for_label` swallows errors into a wrong "rotation" label |
| LM-30 | Low | Duplicated notebook `_bootstrap.py` shims |
| LM-31 | Low | `set_stage_limits` accepts unvalidated values; `_stage_limits` exported |
| LM-32 | Low | `read_origin` parse failures lack file context |

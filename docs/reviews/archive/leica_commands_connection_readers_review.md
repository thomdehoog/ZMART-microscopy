# Review: Leica Stellaris5 driver — `commands/`, `connection/`, `readers/` (+ their unit tests)

- **Scope**: `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/` — subpackages `commands/`, `connection/`, `readers/`, and the unit tests that pin them (`tests/unit/test_core_driver.py`, `test_confirm_specs.py`, `test_confirmation_race.py`, `test_select_job_confirm.py`, `test_log_reader.py`, `test_log_wait.py`, `test_state_readers.py`, `test_lasx_runtime.py`, `test_idle_prechecks.py`, `tests/helpers/mock_lasx_api.py`). `__init__.py`, `utils.py`, `config/profiles.py` skimmed for wiring context only.
- **Date**: 2026-07-03
- **Reviewed commit**: `c7964dd` (working tree == origin/main)
- **Review 2 of 4** for this driver; acquisition/, scanfields/, motion/, calibration/, zmart_adapter/ are covered by other reviews.
- Verification: all in-scope unit tests were run (`387 passed, 61 subtests passed in 54.22s`).

---

## Executive summary

This is a well-above-average hardware driver. The command path has a single dispatch backbone (`confirm_and_fire`) with per-command profiles, a table-driven confirmation layer, an honest `success` vs `confirmed` result contract, and a log-backed evidence path with a genuinely careful admissibility model for the one command (`select_job`) where the CAM API readback is measured-wrong on real hardware. Fail-closed behavior is the default posture throughout the log reader, and the code is unusually rich in measurement provenance (dates, measured constants, rationale for every deviation).

The main criticisms are of two kinds. First, **speculative generality that shipped without a consumer**: an entire "change/target evidence" subsystem in `readers/capabilities.py` (~90 lines plus a profile knob) has zero call sites; the passive `hybrid` read race in `router.py` is unreachable at shipped defaults (every datum pins `api`). Second, a handful of **real correctness gaps at the edges of the confirmation model**: the `select_job` log-evidence window opens before an *unbounded* idle pre-check, so pre-fire `CurrentBlock` events can falsely confirm; the echo flush silently tolerates a failed `Result` reset and can then mis-attribute a stale echo; the unconfirmed-correction path re-fires even when the idle re-check fails. There is also some patchwork: a production branch that exists only to accommodate old test patch shapes, a duplicated galvo safety constant, and four copies of the flush-fire-poll skeleton in `api_reader.py` of which only one has stale-response correlation.

Test quality is high overall (behavioral, drift-pinning, race-aware), but the unit suite burns ~54 s of real sleeps because confirm windows and the echo-settle timeout are not injected, and the echo-settle logic itself has no direct test.

No Critical findings. 2 High, 13 Medium, 16 Low.

---

## What works well

Concrete design decisions worth keeping, with references:

1. **One dispatch backbone, dumb on purpose** — `commands/dispatch.py:1-45` states the contract ("The backbone is dumb — it owns pipeline order, retry ceilings, and timing… It calls zero-arg callables and acts on their result dicts") and the code honors it: `_fire_block` (dispatch.py:176) and `confirm_and_fire` (dispatch.py:447) contain no command knowledge. All 20+ commands route through `_dispatch`/`_dispatch_setting` (commands.py:120, 241). Adding a command is a profile + a wrapper; nothing else changes.
2. **Two explicit retry ceilings, never conflated** — transient-error retries (`max_retries`, inside `_fire_block`) vs confirmation re-attempts (`max_confirm_attempts`, in the wrapper), documented at dispatch.py:26-29 and pinned by tests (test_core_driver.py `TestRetryBackoff`, `TestConfirmation`).
3. **Honest result contract** — `success` means *accepted*, `confirmed` means *verified*, spelled out at commands.py:25-28, dispatch.py:502-507, and profiles.py:222-227 (`success_on_unconfirmed` rationale). The unconfirmed message even carries the last readback (`_confirmation_detail`, dispatch.py:56-63). This avoids the classic driver lie of "success" meaning "I sent bytes".
4. **`CONFIRM_SPECS` table + drift-pinning tests** — confirm_specs.py collapses 16 identical poll loops into one skeleton (`_confirm_readback`, confirmations.py:283) plus a pure-data table, and `test_confirm_specs.py:213-258` asserts the table covers *exactly* the collapsed set, that bespoke confirms stay out, and that descriptor tolerances match wrapper signatures byte-for-byte. This is the right way to prevent copy-paste drift between similar confirmation flows, and the `BESPOKE_CONFIRMS` list (test_confirm_specs.py:57-66) documents *why* each exception stays bespoke.
5. **Fail-closed log reader** — log_reader.py never returns a wrong value: duplicate job names within the current window fail closed (`_current_blocks`, log_reader.py:360-391), a partial ATL cluster refuses to map the element-index intent (log_reader.py:549-554), staleness policy is explicit (`_too_old`, log_reader.py:394-401), and "state beats intent" (`CurrentBlock` over `SetCurrentSelectedElementID`) is enforced and tested (test_log_reader.py:217-227, 382-397).
6. **DST-fold disambiguation** — `_fold_disambiguate` (log_reader.py:120-131) handles the fall-back hour that would otherwise misdate fresh lines by up to an hour and trip every sub-2s freshness gate; tested (test_log_reader.py:419-441). This is the kind of rare-but-real edge most log parsers get wrong.
7. **Dialog detection by line order, not timestamps** (log_reader.py:318-352), with an explicitly documented crashed-session staleness caveat (log_reader.py:598-604), and its use as a *diagnostic only* in dispatch (`_dialog_warning_since`, dispatch.py:66-81: "log-reader failures must never add another command failure mode").
8. **`select_job` hybrid admissibility gate** — the transition-witness rule (an API readback that already equalled the target pre-command can never confirm) is the correct epistemics for a persistently-stale readback, is confined to one policy point (`select_job_confirm_legs`, confirm_select_job.py:166-212), carries measured rationale (profiles.py:107-111, "stale 15 s+, wrong job… validated 2026-06-11"), and is TDD-pinned (test_select_job_confirm.py:53-127, the A→B→A restore case).
9. **In-flight API cap** — `_fire_api_read`/`_claim_api_read` (router.py:86-150) guarantees one CAM read in flight per client, with the worker holding the claim until the CAM call actually returns ("a hung read must keep blocking further API attempts…, not pile up threads behind it"). Tested for both the hang and the pile-on case (test_state_readers.py:150-190, 359-374) and respected by the confirmation race (`test_api_leg_skipped_while_cap_held`).
10. **Stale-response correlation in `get_job_settings`** — the response is matched to *this* query by `jobName` (api_reader.py:122-135) and blank-`imageSize` transients are rejected via the shared `settings_geometry_ready` guard used identically by both backends (derived.py:56-63, log_reader.py:288-296). Real observed hardware behavior, handled at the right layer.
11. **Profile coherence guards** — `CommandProfile.__post_init__` (profiles.py:248-256) rejects incoherent combinations (`fire_async` with an echo error check; single confirm window with re-fire), and tests construct every shipped profile through the guard (test_core_driver.py `TestCommandProfileGuard`).
12. **`confirm_acquire` fail-closed status handling** — an `Unknown`/failed status read is treated as evidence of *neither* scanning nor idle (confirmations.py:1104-1116), preventing both a false start-detection and a false completion; the short-scan blind spot is documented with its backstop (confirmations.py:1063-1067). The idle-before-anything policy is pinned as an operator decision with a date (test_idle_prechecks.py:1-8).
13. **Test realism where it matters** — test_log_reader.py fixtures are byte-realistic LAS X lines (latin-1 µ, `<LF>` tokens, truncated final lines, session block-id reassignment), and test_confirmation_race.py exercises actual thread races with hung legs and cap contention rather than mocked orderings.

---

## Findings

Severity: **Critical** (data loss / wrong hardware action), **High** (wrong result reported or significant dead weight), **Medium** (correctness edge, contract violation, meaningful bloat/efficiency), **Low** (hygiene).

---

### LC-01 — **High** **[YAGNI]** — Entire change/target "evidence leg" subsystem in `capabilities.py` is dead code

- **File**: `readers/capabilities.py:59-64, 66-71, 112-164, 204-208, 227-229, 241-249`; `config/profiles.py:128`
- **Problem**: `DatumSpec.evidence_log_fn`, `key_fn`, `target_fn`, `min_delta_attr`, `numeric`, the module-level `key_delta()` and `change_spec()`, the six supporting functions (`_selected_job_key`, `_selected_job_target`, `_selected_job_evidence`, `_xy_key`, `_xy_target`, `_xy_evidence`), and the profile knob `StateReaderProfile.xy_min_delta_um` have **zero call sites** anywhere in the package (verified by grep: `change_spec`/`key_delta` are referenced only inside `capabilities.py` itself). The module docstring (capabilities.py:10-15) advertises these as powering "the confirmation race", but the actual race (`confirmations.race_confirmations`) and the select_job legs (`confirm_select_job` + `log_wait`) never touch them — `_selected_job_evidence` duplicates logic that `log_wait._selected_job_reason` implements independently.
- **Why it matters**: ~90 lines of validated-looking, docstring-endorsed infrastructure that nothing runs. It misleads readers about how confirmation evidence flows, doubles the places selection/XY evidence semantics are (partially) encoded, and silently rots (e.g. `_xy_evidence` bypasses `max_age_s` with `max_age_s=None`). This is exactly speculative generality: a second implementation path for a mechanism that has one real implementation elsewhere.
- **Action**: Delete the evidence fields, `key_delta`, `change_spec`, the six helper functions, `xy_min_delta_um`, and the "evidence legs" section of the module docstring. If a generic change-detection race is ever built, resurrect from git history with a consumer in hand.

---

### LC-02 — **High** — `select_job` log-confirmation window opens before the *unbounded* idle pre-check; pre-fire `CurrentBlock` events can falsely confirm

- **File**: `commands/commands.py:1438` (`command_started_at = time.time()` before `_dispatch`); `commands/dispatch.py:521` (same pattern for the dialog anchor); `readers/log_wait.py:139-174` (admissibility = `ts > command_started_at`); `config/profiles.py:117` (`selected_job_log_cluster_max_age_s: None`), `config/profiles.py:449-458` (SELECT_JOB has `pre_check_fn=check_idle(timeout=None)`).
- **Problem**: `command_started_at` is captured before dispatch, but the SELECT_JOB profile then waits **indefinitely** for scanner idle inside `_fire_block` before the command is actually sent. Every `CurrentBlock/Name` event logged between timestamp capture and the actual fire is admissible evidence (`current_block_after = current_block_ts > command_started_at`, log_wait.py:142). `CurrentBlock` is emitted by LAS X per block *during a running matrix acquisition* — precisely the situation in which the idle wait is long. If the in-flight acquisition sequence passes through a block named like the target job, the log leg confirms a selection the command never caused. The freshness backstop is disabled by default: `selected_job_log_cluster_max_age_s=None` makes `current_block_fresh` always true (log_wait.py:143-145 → `_too_old(..., max_age_s=None)` → `LOG_READER.max_age_s=None` → `False`), so even a minutes-old pre-fire event within the window is accepted.
- **Why it matters**: The hybrid design exists because the API leg cannot be trusted; this hole makes the *log* leg trustable-but-wrong in the same multi-job workflows the driver targets. A falsely confirmed `select_job` leads to acquiring with the wrong job — the exact failure the confirmation layer is built to prevent. (Note: the deliberate reuse of the original timestamp across re-fires, pinned by `test_refires_reuse_the_original_command_timestamp`, is fine — the issue is only the pre-fire window.)
- **Action**: Anchor the evidence window at fire time, not wrapper-entry time — e.g. have `_fire_block` record the post-pre-check fire timestamp and pass it to the confirm legs, or run the idle pre-check in the wrapper before capturing `command_started_at`. Independently, give `selected_job_log_cluster_max_age_s` a finite default so an old open event can't satisfy the gate. Add a regression test: idle wait spans a `CurrentBlock` event naming the target; the log leg must not confirm.

---

### LC-03 — **Medium** — Silent failure of the echo `Result` flush can settle `_await_echo_result` on a *stale* echo

- **File**: `commands/dispatch.py:297-302` (flush; `Result = 0` reset wrapped in `except Exception: pass`), `commands/dispatch.py:128-168` (`_await_echo_result` settles on `Result != 0 or HasError`).
- **Problem**: The fire step clears `HasError`/`Error` and *tries* to reset `Result` to 0, swallowing failure ("Some API versions may not allow Result assignment"). On such a version, the previous command's `Result` (e.g. 1 = Success) survives the flush, `_await_echo_result` returns True immediately, and `_check_api_error` (errors.py:111) reads what is effectively the *previous* command's echo — reporting success before LAS X has processed the new command, or conversely attributing a late prior error to this command. This is precisely the cross-attribution race the flush-then-settle design exists to prevent, re-opened by one silent `pass`.
- **Why it matters**: The error check is the only channel that catches an outright LAS X rejection early; readback confirmation is the backstop but returns `success=True, confirmed=False` under `success_on_unconfirmed`, so a rejection can be reported as an accepted-but-unconfirmed command with no error text. The failure mode is version-dependent and invisible.
- **Action**: On the first `Result`-reset failure, log a warning (once) and degrade explicitly: either treat the echo as unsettleable (skip `_await_echo_result` and rely on `HasError` alone with a fresh-cleared flag), or record a pre-fire `Result` snapshot and require it to *change* before treating the echo as settled. Add a unit test for the "Result not assignable" client shape (see also LC-14).

---

### LC-04 — **Medium** — Unconfirmed-correction path re-fires even when the idle re-check fails

- **File**: `commands/dispatch.py:653-666`.
- **Problem**: In the correction branch of `confirm_and_fire`, `idle_result = pre_check_fn()` is called, its logs appended, and its `success` **ignored** — the re-fire proceeds unconditionally with `pre_check_fn=None` ("Already waited for idle above"). On the first fire, a failed pre-check aborts the pipeline (dispatch.py:256-268); on correction, the same failure is silently overridden.
- **Why it matters**: With the shipped profiles (`timeout=None`) the pre-check cannot fail, so the bug is latent — but every wrapper exposes `pre_check_timeout` as a supported override (commands.py:134, 168-171), and any caller using it gets a re-fire into a busy scanner, exactly what the pre-check exists to prevent. Inconsistent semantics between first-fire and correction is also a comprehension trap.
- **Action**: If the correction pre-check fails, skip the re-fire for that attempt (fall through to the next confirm attempt or return unconfirmed), mirroring first-fire semantics. One-line check plus a test.

---

### LC-05 — **Medium** **[PATCHWORK]** — Production freshness gate contains a branch that exists only to accommodate old test patch shapes

- **File**: `commands/confirmations.py:260-275` (`_reading_value_after`), consumers at confirmations.py:1016-1019, 1097-1100 and confirm_select_job.py:102-105.
- **Problem**: The docstring says it plainly: "Tests sometimes patch routed readers with their old plain return shape; those values are accepted here so the tests can stay focused on confirmation logic." The `not hasattr(reading, "value") → return reading` branch bypasses the observed-after freshness gate entirely for any non-`Reading` value. In production, routed readers with `diagnostics=True` always return `Reading` or `None`, so the branch is test-only — but it is live code in the safety path, and a future reader refactor returning plain values would silently lose the freshness gate rather than fail loudly.
- **Why it matters**: This is test-induced production code — the tests should conform to the production contract, not vice versa. It also hides the fact that several tests (e.g. test_core_driver.py:1322-1335 `test_confirm_move_xy`, patching `readers.get_xy` to return a plain dict) never exercise the real gate.
- **Action**: Delete the plain-value branch (make a non-`Reading` a hard failure or `None`), and update the handful of tests to patch with `Reading` objects (test_state_readers.py:230-257 already shows the pattern).

---

### LC-06 — **Medium** — `make_changeable_copy` silently drops bare-float `zPosition` entries; the bare-float guard downstream is dead code

- **File**: `commands/settings.py:139-145`; `readers/derived.py:73-83`.
- **Problem**: `make_changeable_copy` maps each `zPosition` entry to `_safe_float(entry.get("position")) if isinstance(entry, dict) else None` — a bare numeric value (the alternate shape that `zwide_um_from_settings`'s docstring explicitly says LAS X can emit: "LAS X sometimes nests the value as `{'position': ...}` rather than a bare float") is converted to `None`, not to its value. Consequently (a) on a LAS X version emitting bare floats, `confirm_move_z` (confirmations.py:415) can never confirm and `read_zwide_um` always raises, and (b) the `isinstance(val, dict)` re-guard in derived.py:81-83 is unreachable, because `make_changeable_copy` output is always float-or-None.
- **Why it matters**: Either the bare-float shape is real (then Z readback silently breaks on that version) or it is not (then two docstrings and a dead guard describe a phantom hardware quirk). Both states are bad; the current code is internally contradictory about which world it lives in.
- **Action**: Make `make_changeable_copy` handle both shapes: `_safe_float(entry.get("position")) if isinstance(entry, dict) else _safe_float(entry)`. Then delete the dead dict-guard in `zwide_um_from_settings` or keep it with a comment pointing at the single normalization point. Add a unit test for the bare-float shape.

---

### LC-07 — **Medium** — `router.read_zwide_um` violates its own documented no-raise contract

- **File**: `readers/router.py:435-444` (docstring: "Like every routed reader this fails closed with None instead of raising"); `readers/derived.py:66-86` (raises `RuntimeError`); `commands/settings.py:44-50` (`make_changeable_copy` raises `ValueError` on schema mismatch).
- **Problem**: When `get_job_settings` returns a value but `zPosition`/z-wide is missing (documented as "almost always means the job is not selected"), `derived.zwide_um_from_settings` raises `RuntimeError`, and a malformed settings dict raises `ValueError` from `make_changeable_copy` — both propagate straight out of the routed reader whose docstring promises `None`. Real callers exist on both sides of the ambiguity: `calibration/core/objective_pair.py:441` does `float(drv.read_zwide_um(...))` (would crash on `None`), so the *docstring* is what's wrong today, but any new caller written to the docstring will mishandle the raise.
- **Why it matters**: A reader-layer contract violation in a package whose whole design rides on "readers fail closed, commands decide". Whichever behavior is intended must be the one documented and tested.
- **Action**: Pick one: (a) make the docstring say "raises RuntimeError when z-wide is unavailable" (matches all current callers), or (b) catch and return `None`, updating the calibration callers. Add the missing unit test either way (there is currently no unit test of `router.read_zwide_um`).

---

### LC-08 — **Medium** — Galvo pan safety limit is defined twice

- **File**: `commands/commands.py:1138` (`_PAN_LIMIT = 0.00775`) vs `utils.py:70` (`PAN_LIMIT = 0.00775`, exported in `__init__.__all__`).
- **Problem**: The same hardware safety constant (max galvo pan per axis, used to refuse an out-of-range pan in `move_galvo_to_pixel`, commands.py:1216-1220) is defined independently in two modules. `utils.py` even derives `pan_scale_um_from_base_fov` from its copy, so the *limit check* and the *scale calculation* currently agree only by coincidence of two literals.
- **Why it matters**: If Leica changes the software limit (or a new scope differs) and one copy is edited, the check and the physics silently diverge — the check could permit a pan the scale math considers out of range, or vice versa. Duplicated safety constants are the canonical copy-paste-drift hazard the maintainer asked to flag.
- **Action**: Delete `_PAN_LIMIT` in commands.py and import `PAN_LIMIT` from `..utils` (commands.py already imports from utils).

---

### LC-09 — **Medium** — Four near-identical flush-fire-poll readers in `api_reader.py`; only one has stale-response correlation

- **File**: `readers/api_reader.py:88-159` (`get_job_settings`), `162-194` (`get_hardware_info`), `197-237` (`get_xy`), `240-272` (`get_jobs`).
- **Problem**: The retry/flush/fire/poll/timeout/log skeleton is copy-pasted four times (~40 lines each), varying only in model object, sentinel, field, and validator. More substantively: only `get_job_settings` correlates the response with the query (`jobName` check, api_reader.py:122-135). `get_jobs`, `get_hardware_info`, and `get_xy` accept the first non-sentinel value after the flush — a delayed response to a *previous* fire (the very race the job-settings comment describes) lands post-flush and is returned as fresh. For `get_xy` this can hand a confirm loop the pre-move position stamped with a post-command `observed_at`, defeating the `_reading_value_after` gate in `confirm_move_xy` for A→B→A move patterns.
- **Why it matters**: Duplication has already produced protection drift between the copies. The skeleton is exactly the kind of thing this codebase elsewhere collapses well (cf. `CONFIRM_SPECS`).
- **Action**: Extract one `_flush_fire_poll(client, command, model_attr, field, *, flush, validate, timeout, poll_interval, max_retries)` helper; give `get_jobs`/`get_xy` at least a sequence-token or double-read-agreement guard where the protocol allows no correlation field. At minimum, document the uncorrelated-response risk on the three readers that have it.

---

### LC-10 — **Medium** — `require_canonical_scan_orientation` fails open when the settings file is missing or unparseable

- **File**: `connection/session.py:108-119`; `readers/api_reader.py:396-407` (returns `None` on missing/corrupt file).
- **Problem**: The validator exists because a non-TOPLEFT export "silently misnavigates downstream coordinate math" (its own words). But `get_lasx_settings()` returning `None` (file missing, `APPDATA` unset, XML corrupt) yields `settings = {}` → `orient = {}` → `enable_transform` defaults False → the check **passes**. A safety precondition that cannot be evaluated is treated as satisfied.
- **Why it matters**: The failure it guards against is silent by definition; failing open converts "cannot verify" into "verified". On a misconfigured machine (wrong user profile, renamed settings path) the guard evaporates exactly when configuration is most likely wrong.
- **Action**: Raise (or at least warn loudly with an explicit `RuntimeError` opt-out) when `get_lasx_settings()` returns `None` or the `image_orientation` section is absent, distinguishing "verified canonical" from "could not verify".

---

### LC-11 — **Medium** **[YAGNI]** — Passive `hybrid` read race (`_log_rescue_concurrent`) is unreachable at shipped defaults

- **File**: `readers/router.py:239-343`; `config/profiles.py:86-128` (every `*_mode` defaults `"api"`; `hybrid_log_grace_s` consumed only at router.py:260).
- **Problem**: All six datums ship with `mode="api"`, and no production code path passes `mode="hybrid"` or `mode="log"` for passive reads (verified: production `mode=` call sites all pin `"api"`; the log backend's real consumers are `get_pending_dialog`, dispatch's dialog diagnostic, and the select_job confirm leg — none of which go through `_log_rescue_concurrent`). The ~80-line log-preferred grace-window race, its `hybrid_log_grace_s` knob, and the hybrid degradation branches are exercised solely by unit tests.
- **Why it matters**: This is a "reader path kept just in case", live and maintained but with no runtime consumer. It is *better-justified* than LC-01 (the hang-resistance rationale is documented and measured, the profile is the declared switch, and hardware validators compare backends side-by-side), so removal is a judgment call — but it should be a conscious one: either some datum should actually default to `hybrid` (the design's stated point), or the passive race should be trimmed to the simple "log if fresh else api" that the validators need.
- **Action**: Decide and record: flip at least `scan_status` or `xy` to `hybrid` in the shipped profile (it is claimed to be strictly more hang-resistant), or delete `_log_rescue_concurrent` + `hybrid_log_grace_s` and let `hybrid` mean "api with log fallback on error/timeout". Keeping a dead race "for later" is the outcome to avoid.

---

### LC-12 — **Medium** — Every log poll re-reads and re-parses up to 4 MB (plus the msgbox log) from scratch

- **File**: `readers/log_reader.py:95-117` (`_LOG_TAIL_BYTES = 4 MiB`, `_tail_lines`), `248-307` (`parse_log` also always calls `_read_msgbox_state`); `readers/log_wait.py:77-98` (calls `parse_log()` per poll at `poll_interval_s=0.1`).
- **Problem**: The parse is deliberately stateless (rotation-safe — good), but a `wait_for_selected_job_log` window at defaults performs ~10 full 4 MiB reads + regex scans per second, plus a second file read for the msgbox log, even when only selection state is needed. Confirm attempts multiply this (up to 3 windows per select_job). On the production machine (multi-hour logs, spinning metadata caches, LAS X itself writing the file) this is meaningful I/O and CPU inside the driver's most latency-sensitive path — and it is the *log* leg, whose selling point is beating the API leg's latency.
- **Why it matters**: Efficiency of the hot confirmation path; the 4 MiB constant is also a hardcoded magic number outside the profile system that everything else uses ("Parameters live in config.profiles.LOG_READER — no hardcoded values in the read paths", log_reader.py:48, contradicted by `_LOG_TAIL_BYTES`).
- **Action**: Cheap fix: short-circuit on `(st_size, st_mtime_ns)` — reparse only when the file changed since the last snapshot (keeps statelessness per process, no rotation hazard since a rotation changes both). Move `_LOG_TAIL_BYTES` into `LogReaderProfile`. Optionally let `parse_log` skip the lcs pass when only msgbox data is needed (there is already `parse_msgbox_log`; `log_wait` could use a selection-focused parse).

---

### LC-13 — **Medium** — Unit suite burns ~54 s in real sleeps because poll windows and echo settles are not injected

- **File**: `tests/unit/test_core_driver.py` (e.g. `TestConfirmFunctions.test_confirm_scan_speed`, `test_confirm_scan_resonant`, `test_confirm_pinhole_airy`, `test_confirm_frame_accumulation` — each 3.0 s; `TestConfirmAndFire.test_success`, `test_permanent_error_no_retry`, `test_timing_dict_structure` — each 1.0 s), measured in this review's run (`387 passed … in 54.22s`).
- **Problem**: Negative-path confirm tests that omit `poll_window` run the full `CONFIRM_POLL_S = 3 s` wall-clock window with real `time.sleep(0.01)` loops; and every `confirm_and_fire` test that doesn't patch `_await_echo_result` pays its full 1.0 s timeout because the `MagicMock` echo is flushed to `Result=0`/`HasError=False` and never "settles". Roughly 30+ seconds of the suite is pure sleeping.
- **Why it matters**: Slow unit suites get run less; worse, the 1.0 s stalls are *accidental* (the tests don't know they're timing out the echo poll), so a future change to the settle logic would silently alter test durations rather than assertions.
- **Action**: Pass `poll_window=0.05` in every negative confirm test (the positive ones already return on first poll); in `make_client()`, give the echo a `Result` that settles (or patch `_await_echo_result` in the shared helper as `TestRetryBackoff` already does). Target: full suite < 10 s.

---

### LC-14 — **Medium** — `_await_echo_result` and the echo flush have no direct tests

- **File**: `commands/dispatch.py:128-168, 296-316`; test gap in `tests/unit/test_core_driver.py` (the function is only ever patched: lines 497, 527, 557, …).
- **Problem**: The echo-settle poll — its settle condition (`Result != 0 or HasError`), the unreadable-attribute fallback ("Unreadable → treat as not settled"), the timeout path and its "may miss a late rejection" warning log entry (dispatch.py:308-316), and the flush including the swallowed `Result` reset — is entirely untested. This is the piece of the fire pipeline with the subtlest failure modes (LC-03 lives here).
- **Why it matters**: The suite pins retry ceilings and confirm policy thoroughly but leaves the transport/echo timing layer, which encodes real observed hardware behavior, unpinned. A regression here (e.g. inverting the settle condition) would pass the whole suite.
- **Action**: Add direct tests: settles on `Result=1`, settles on `HasError=True` with `Result=0`, times out on cleared echo (with fake clock), treats raising attributes as not-settled, and — per LC-03 — the non-assignable-`Result` client shape.

---

### LC-15 — **Medium** — Mock LAS X drifts from both the real API and the driver's expectations

- **File**: `tests/helpers/mock_lasx_api.py:192-214, 221-243, 151-176, 794-841`.
- **Problem**, three specific drifts:
  1. `_EchoModel.clear()` sets `Result = 1` (Success) while the driver flushes to `0` (NotDefined) and *waits* for a transition (dispatch.py:300, 128-168). Because every mock handler calls `_echo.clear()` synchronously inside `UpdateAwaitReceipt`, the echo is always pre-settled — the settle-timeout path can never occur against the mock, masking exactly the behavior LC-03/LC-14 concern.
  2. `UpdateAwaitReceipt` executes the command handler synchronously before returning (mock_lasx_api.py:234-238); the real API acknowledges transport and processes asynchronously. Any driver bug that reads results too early is invisible.
  3. `PyApiSetLaserShutterByJobName`, `PyApiSetFilterWheelSlotByJobName`, `PyApiSetFilterWheelSpectrumPositionByJobName` are mapped to `_set_noop` (mock_lasx_api.py:171-174), so shutter/filter-wheel confirmations can never observe a change against the mock — a validator exercising those commands sees `confirmed=False` and can't distinguish driver bugs from mock gaps. (Also minor: `_handle_move_z` stores µm in `zPosition[...]["position"]` — consistent with `confirm_move_z`'s assumption but worth a comment, since the real unit is unverified in-repo.)
- **Why it matters**: The mock's docstring sells it as a "behavioral mock … matches the real LAS X API attribute names and command dispatch patterns"; consumers (hardware validators, adapter tests) will trust it accordingly. Silent no-ops and always-settled echoes are the classic way mock suites diverge from hardware.
- **Action**: Make `clear()` set `Result = 0` and have handlers set `Result = 1` on completion (matching the flush-then-settle protocol); implement the shutter/filter-wheel mutations (the state fields already exist in `_DEFAULT_JOBS`); at minimum, document each intentional divergence at the top of the mock.

---

### LC-16 — **Low** **[YAGNI]** — Dead `observed_after` parameter on `_readback`

- **File**: `commands/confirmations.py:229-253`.
- **Problem**: `_readback(client, job_name, *, observed_after=None)` implements a freshness gate that no caller uses — every call site in the package is `_readback(client, job_name)` (verified by grep).
- **Why it matters**: A dead safety knob suggests confirmations are freshness-gated when they are not (per-setting confirms rely on polling-forward, not observed-after). Dead parameters accumulate confusion in exactly the layer where the freshness story is subtle.
- **Action**: Remove the parameter and the gate block, or wire it in from `_confirm_readback` if per-setting confirms should reject pre-command readings (then test it).

---

### LC-17 — **Low** **[YAGNI]** — Vestigial `timing["method"]` field, always `"async"`

- **File**: `utils.py:246, 259` (`method="async"` default, docstring "'sync' or 'async'"); `commands/dispatch.py:561, 586, 636, 705, 733` (every call passes the literal `"async"`).
- **Problem**: The field never varies; nothing reads it (tests only assert it equals `"async"`, test_core_driver.py:299). It is a fossil of a removed sync dispatch path (cf. `TestApiSetRemoved`).
- **Action**: Drop the key from `_make_timing` and the five call sites, or repurpose it honestly (e.g. record `fire_async` vs receipt). Update the timing-shape test.

---

### LC-18 — **Low** — Hardcoded transport/echo tuning outside the profile system

- **File**: `commands/dispatch.py:98` (`max_attempts=3, retry_delay=0.5` in `_fire_with_receipt`), `dispatch.py:128` (`timeout=1.0, poll_interval=0.01` in `_await_echo_result`).
- **Problem**: The package's stated rule is that machine-sensitive tuning lives in profiles (profiles.py:1-26; log_reader.py:48). Transport retry count/delay and the echo-settle window are as machine-sensitive as anything in `CommandProfile`, yet they are function defaults never plumbed from a profile. The 1.0 s settle window is also a per-command latency floor whenever the echo doesn't settle (see LC-13's measured 1.0 s tests).
- **Action**: Move both into `CommandProfile`/`LasxApiProfile` (or a small transport profile), keep current values as defaults.

---

### LC-19 — **Low** — Router timeout returns bare `None`, breaking the documented diagnostics contract

- **File**: `readers/router.py:220-231, 244-247` vs the comment at 221-224 ("Failed reads return the error-carrying Reading (value=None) … so diagnostics=True callers can see *why*").
- **Problem**: When `_capped_api_read` times out or the in-flight slot never frees, `_route_read` returns `None`, so `diagnostics=True` callers get `None` with no source/error — unlike API exceptions (error-carrying `Reading`) and unsupported legs (`UnsupportedSource` Reading, router.py:182-189). The one failure mode most in need of a "why" (hung CAM call) is the one that loses it.
- **Action**: Return `Reading(value=None, source="api", observed_at=None, age_s=None, error=TimeoutError(...))` on timeout; `_plain_or_diagnostic` already collapses it to `None` for plain callers.

---

### LC-20 — **Low** — Confirmation race can misreport a late-confirming loser as "had not confirmed"

- **File**: `commands/confirmations.py:163-198`.
- **Problem**: The post-win bounded drain (confirmations.py:166-177) exists so "a completed leg is reported as disagreement, not misreported as abandoned" — but the subsequent reporting branch (`elif loser in outcomes:` → warning "`{loser}` leg had not confirmed when the `{winner}` leg confirmed", line 196) never checks the drained outcome's `success`. A loser that *did* confirm 50 ms late is logged as a disagreement warning, which is the opposite of what happened (both sources agreed).
- **Why it matters**: The race's value is honest evidence reporting; a false "source disagreement" warning in the driver log will send an operator hunting a stale-source problem that doesn't exist.
- **Action**: In the loser-reporting branch, if `outcomes[loser].get("success")`, log info "both legs confirmed (loser +X ms)" instead of the warning.

---

### LC-21 — **Low** — `"warning" in error_msg` substring heuristic treats any error mentioning "warning" as success

- **File**: `commands/errors.py:152-156` (`if echo.HasError and "warning" in error_msg.lower(): return None`).
- **Problem**: The intent (LAS X flags non-fatal parameter adjustments as `HasError` + "Warning: …") is legitimate and tested (test_core_driver.py:175-185), but the match is an unanchored substring over the whole message: an actual error like "failed to apply warning threshold" would be swallowed as success. The same brittleness applies to the taxonomy lists (errors.py:31-51) — acknowledged there by the priority ordering and the unclassified-error warning log (errors.py:75), which are good mitigations.
- **Action**: Anchor the check (`error_msg.lower().startswith("warning")` matches the observed "Warning on command: …" / "Warning: …" shapes in the tests and mock), and keep a debug log of swallowed warnings (already present at errors.py:154-155).

---

### LC-22 — **Low** — Boilerplate duplication: seven hand-built failure dicts in `commands.py`, four timing dicts in `_fire_block`

- **File**: `commands/commands.py:407-414, 422-430, 546-555, 565-574, 1063-1071, 1081-1089, 1274-1289, 1302-1309` (identical `{"success": False, "confirmed": None, "message": …, "timing": _make_timing(total_s=0.0, attempts=0), "logs": []}` blocks, two of which add `"position": None`); `commands/dispatch.py:259-268, 280-291, 322-333, 343-354, 414-425, 428-439` (six copies of the same 4-key timing dict).
- **Problem**: Pure copy-paste; the Phase-A validation returns are already drifting (move_xy's includes `position`, others don't).
- **Action**: Add `_phase_a_failure(message, **extra)` in commands.py and a local `_timing()` closure (or dict built once and updated) in `_fire_block`. Mechanical, ~60 lines removed.

---

### LC-23 — **Low** — `move_galvo_to_pixel` breaks the command result contract and reaches into `experimental/`

- **File**: `commands/commands.py:1142-1245` (function-local imports from `..experimental.lrp_edits.*` and `..scanfields.*` at 1165-1170; result dict lacks `confirmed`/`timing`/`logs`).
- **Problem**: Every other command in this module returns the backbone envelope; this one returns `{"success", "pan", "delta_pan", "pan_scale_um", "message"}` with no timing or logs, and it is the only `commands/` function that depends on the `experimental` package (whose own docstring in `__init__` labels it "LRP mutation helpers without live-state readback"). A caller iterating command results uniformly (as the protocol tests do, asserting `r["success"]`) gets a different shape here; the docstring at commands.py:1159-1163 does document the shape, which mitigates.
- **Why it matters**: Shape drift between commands is exactly what the backbone was built to eliminate; and "primary galvo navigation primitive" (its own words) living on `experimental` code is a layering inversion that will surprise someone during an `experimental/` cleanup.
- **Action**: Either move the function next to its dependencies (a `galvo` module) or promote the LRP-edit primitives it needs out of `experimental`; add `logs`/`timing` keys (even minimal) so callers can treat command results uniformly.

---

### LC-24 — **Low** — Test name contradicts the shipped default: `test_select_job_log_confirmation_is_off_by_default`

- **File**: `tests/unit/test_core_driver.py:2899-2913`; vs `config/profiles.py:111` (`selected_job_confirm_source: str = "hybrid"`) and `test_select_job_confirm.py:201-208` (`test_selected_job_confirmation_defaults_to_hybrid`).
- **Problem**: The test actually verifies that the *pure api confirm leg* never calls `log_wait` — correct and useful — but its name asserts a policy default ("off by default") that was true before the hybrid default landed and is now false, directly contradicted by another test in the suite.
- **Action**: Rename to `test_api_confirm_leg_never_touches_log_wait` (and drop `command_started_at=100.0` from the call, which is irrelevant to what's asserted).

---

### LC-25 — **Low** — Log-backed job list fabricates API fields with constant placeholder values

- **File**: `readers/log_reader.py:199-221` (`_matrix_jobs_from_result`: `"IsPattern": False, "IsLightning": False, "IsPause": False, "RotationAngle": 0.0`).
- **Problem**: To be "API-shaped", the log job list invents values the log does not contain. A consumer switching a jobs read to `mode="log"` gets `RotationAngle=0.0` presented identically to a real reading. (`IsSelected: None` is handled correctly — the honest "unknown" pattern — which makes the fabricated constants stand out more.)
- **Action**: Use `None` for fields the log cannot supply, matching the `IsSelected` convention, or document per-field provenance in the docstring.

---

### LC-26 — **Low** — Log scan-status mapping collapses all non-zero states to `eScanRunning` on an unverified code table

- **File**: `readers/log_reader.py:583-590` (comment: "0 = idle (confirmed on sim); … Re-confirm the non-idle codes on real hardware").
- **Problem**: The mapping is load-bearing for the log leg of `scan_status` (a pre-check/confirm-adjacent datum) yet self-declares unverified for every non-idle code. The idle-side risk is the dangerous one: if some non-zero code also means idle-equivalent, log mode would block forever; if some transient code 0 occurs mid-scan, log mode would report idle during a scan. Mitigated today because `scan_status_mode` defaults to `api` and `check_idle` pins `api` explicitly (prechecks.py:51-54 — good).
- **Action**: Either verify the code table on hardware and record it (the codebase's own provenance style), or restrict the log mapping to `{0: idle}` + `Unknown` for unrecognized codes.

---

### LC-27 — **Low** — Docstring/typing drift in the dispatch plumbing

- **File**: `commands/commands.py:149-177` (`_dispatch` Args section omits `log_confirm_fn` and `confirm_race_budget_s`, both parameters since the race landed); `commands/dispatch.py:203-231` (`_fire_block` Args omits `skip_echo`, `receipt_timeout`, `fire_async`); `commands/confirm_specs.py:142-145` and `config/profiles.py:229-231` (fields annotated `callable`/bare `tuple` — the builtin, not a type; `default_tolerance: float = None`); `readers/log_reader.py:229-244` (`Snapshot` annotations `xy: tuple = None`, `selected_element: int = None` etc. — `Optional` values typed as non-optional).
- **Problem**: None of these mislead badly, but this package's docstrings are its architecture documentation; parameter omissions in the two central plumbing functions are the ones most likely to bite the next maintainer, and the annotations would fail any type checker the repo adopts.
- **Action**: Complete the two Args lists; switch annotations to `Callable`, `tuple | None`, `float | None`, `int | None` (the codebase already uses `from __future__ import annotations` style elsewhere, e.g. objectives.py).

---

### LC-28 — **Low** — `old_begin_um`/`old_end_um` are reset *flags* disguised as value parameters

- **File**: `commands/commands.py:601-640`.
- **Problem**: "Reset flags, not values — passing any non-None value asks LAS X to reset that field … The numeric value itself is never sent" (the docstring, to its credit, says so). A parameter named `old_begin_um` that accepts a micrometer number and discards it is an API that invites misuse (`set_z_stack_definition(c, j, old_begin_um=-3.0)` reads like "restore -3.0").
- **Action**: Deprecate in favor of `reset_begin: bool = False, reset_end: bool = False`; keep the old names as aliases for one release if external callers exist.

---

### LC-29 — **Low** — `_confirmation_detail` can inline arbitrarily large diagnostics into the result message

- **File**: `commands/dispatch.py:56-63, 711-716`; producer at `commands/confirm_select_job.py:157-163` (failure outcome carries `log_diagnostics`, a dict with job name lists, cluster diagnostics, timestamps).
- **Problem**: The unconfirmed log line appends `repr()` of every non-`success`/`logs` key of the last confirmation result. For select_job's log leg that includes the full `log_diagnostics` dict — a multi-hundred-character repr in a WARNING line and in `result["message"]` consumers may surface to UIs.
- **Action**: Truncate the detail repr (e.g. 200 chars) or whitelist scalar keys (`source`, `reason`, `log_reason`).

---

### LC-30 — **Low** **[YAGNI-watch]** — Single-consumer generality, acknowledged as acceptable

- **File**: `commands/commands.py:127-129, 210-217` (`log_confirm_fn`/`confirm_race_budget_s`/`api_key` plumbing in `_dispatch`, used only by `select_job`); `readers/log_reader.py:569-623` (`get_job_by_name`, `get_fov`, `get_base_fov`, `read_zwide_um` — log-side convenience readers used only by `tests/hardware/validate_readers_side_by_side.py` and unit tests); `router.py:469-478` (`get_job_by_name` has no in-repo production caller; it is public API per README).
- **Problem**: Each of these has exactly one (or zero) consumers. They survive review because each is cheap and has a stated purpose: the race plumbing is identity-pass-through for single legs (confirmations.py:62-66), the log convenience readers exist for the side-by-side hardware validator, and `get_job_by_name` is documented public surface. Listed so the pattern doesn't grow unexamined.
- **Action**: No change required now. If a second log-participating command never materializes, consider folding the `_dispatch` race parameters into a select_job-local composition; drop the log-side FOV readers if the side-by-side validator is ever retired.

---

### LC-31 — **Low** — Minor test-suite hygiene

- **File**: `tests/unit/test_core_driver.py` (3,074 lines, 20 numbered sections spanning error classification, dispatch, confirms, wiring, protocol simulation, log entries — several of which have since gained dedicated files like test_confirm_specs.py); `test_core_driver.py:1322-1329` (patched `get_xy` returns `x_m`/`y_m` keys that the real reader does not produce — harmless but drift-y, and it exercises the LC-05 accommodation branch instead of the real `Reading` gate); `test_lasx_runtime.py:34-40` (`setUp`/`tearDown` defined after the tests — legal, but unconventional); every test file re-inserts `sys.path` (workable given the repo layout, but a `conftest.py` at `tests/` already exists and could own it once).
- **Problem**: None of these are wrong; together they add friction. The monolith file in particular makes it hard to see what is and isn't covered (which is how the LC-14 gap survived).
- **Action**: Opportunistically split test_core_driver.py along its own section headers (dispatch / confirms / wiring / protocol); fix the fake `get_xy` keys to match `api_reader.get_xy`'s real shape when addressing LC-05.

---

## Summary table

| ID | Severity | Title |
|-------|----------|-------|
| LC-01 | High | **[YAGNI]** Unused change/target "evidence leg" subsystem in `capabilities.py` (+ dead profile knob) |
| LC-02 | High | `select_job` log-evidence window opens before the unbounded idle pre-check → pre-fire `CurrentBlock` events can falsely confirm |
| LC-03 | Medium | Silently-failed echo `Result` flush lets `_await_echo_result` settle on a stale echo (error misattribution) |
| LC-04 | Medium | Unconfirmed-correction path re-fires even when the idle re-check fails |
| LC-05 | Medium | **[PATCHWORK]** `_reading_value_after` production branch exists only for old test patch shapes, bypassing the freshness gate |
| LC-06 | Medium | `make_changeable_copy` drops bare-float `zPosition`; downstream bare-float guard is dead code |
| LC-07 | Medium | `router.read_zwide_um` docstring promises no-raise; implementation raises |
| LC-08 | Medium | Galvo pan safety limit duplicated (`commands._PAN_LIMIT` vs `utils.PAN_LIMIT`) |
| LC-09 | Medium | Four copies of flush-fire-poll in `api_reader.py`; stale-response correlation only on one of them |
| LC-10 | Medium | `require_canonical_scan_orientation` fails open when settings are unreadable |
| LC-11 | Medium | **[YAGNI]** Passive hybrid read race (`_log_rescue_concurrent`) unreachable at shipped defaults |
| LC-12 | Medium | 4 MiB log tail re-read/re-parsed on every poll; `_LOG_TAIL_BYTES` hardcoded outside profiles |
| LC-13 | Medium | Unit suite spends ~30+ s in real sleeps (3 s confirm windows, 1 s echo settles) |
| LC-14 | Medium | `_await_echo_result` / echo-flush semantics have no direct tests |
| LC-15 | Medium | Mock LAS X drift: pre-settled echo (`Result=1` on clear), synchronous receipt, no-op shutter/filter-wheel handlers |
| LC-16 | Low | **[YAGNI]** Dead `observed_after` parameter on `_readback` |
| LC-17 | Low | **[YAGNI]** Vestigial `timing["method"]` always `"async"` |
| LC-18 | Low | Transport/echo tuning hardcoded outside the profile system |
| LC-19 | Low | Router timeout returns bare `None`, losing diagnostics contrary to documented contract |
| LC-20 | Low | Race misreports a late-confirming loser as source disagreement |
| LC-21 | Low | Unanchored `"warning"` substring treats matching errors as success |
| LC-22 | Low | Duplicated failure-dict and timing-dict boilerplate (commands.py ×7, `_fire_block` ×6) |
| LC-23 | Low | `move_galvo_to_pixel` breaks the command result envelope and depends on `experimental/` |
| LC-24 | Low | Test name contradicts shipped default (`…log_confirmation_is_off_by_default` vs hybrid default) |
| LC-25 | Low | Log job list fabricates constant placeholder values for API-shaped fields |
| LC-26 | Low | Log scan-status maps all non-zero codes to running on an unverified table |
| LC-27 | Low | Docstring/typing drift in `_dispatch`, `_fire_block`, `ConfirmSpec`, `Snapshot` |
| LC-28 | Low | `old_begin_um`/`old_end_um` are reset flags disguised as value parameters |
| LC-29 | Low | Unconfirmed message can inline arbitrarily large diagnostics reprs |
| LC-30 | Low | **[YAGNI-watch]** Single-consumer generality (race plumbing in `_dispatch`, log-side FOV readers, `get_job_by_name`) — acceptable, keep examined |
| LC-31 | Low | Test hygiene: 3,074-line monolith, fake reader keys, `sys.path` boilerplate |

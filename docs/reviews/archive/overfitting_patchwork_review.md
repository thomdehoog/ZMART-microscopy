# Overfitting / Patchwork Sweep — `zmart_controller` + Leica `navigator_expert`

- **Scope:** `zmart_controller/` (all files, incl. tests/notebooks) and
  `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/` (all production modules and tests).
  Everything else in the repo was read for context only; no findings are filed against it.
- **Date:** 2026-07-03
- **Reviewed commit:** `c7964dd` (working tree == origin/main)
- **Charter:** hunt specifically for *incident-shaped* code — magic constants tuned to one bench
  session, special-case branches for one observed quirk, defensive code that hides bugs,
  test-shaped production branches, copy-paste drift between siblings, and retry/sleep band-aids
  where a real completion signal exists.
- **Method:** all prior reviews (`docs/reviews/*.md`, series 1–6) were read first; every claim below
  was re-verified against the code at this commit with file:line evidence. Findings that confirm a
  prior review's item say so explicitly (`confirms LC-xx`) and add the cross-cutting angle; findings
  marked **NEW** appear in no prior review.

All driver paths below are relative to `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/`.

---

## 1. Executive summary

**Verdict: design-driven core, with patchwork concentrated in four specific seams.** This is not a
codebase built by stacking hotfixes. The command backbone (one dispatch pipeline, per-command
profiles, an explicit `success` vs `confirmed` contract), the machine-snapshot config system, the
fail-closed log reader, and the entire `zmart_controller` package are deliberate designs, and the
code carries an unusually strong provenance culture — dated operator decisions, measured constants
with dates and instruments, and comments that explain *why* deviations exist. `zmart_controller`
in particular is nearly patchwork-free (its only structural workaround is the missing packaging
metadata that forces `sys.path` surgery in three places, ZC-14).

Patchwork clusters in four places:

1. **The file-mediated LRP/template layer** (`scanfields/`, `experimental/lrp_edits/`,
   `_file_utils.py`). Because LAS X gives no completion signal for template save/load, everything
   here is mtime polling, size-stability heuristics, and escalating retry ladders —
   `confirm_delays=(2, 4, 8, 16)`, `_RESTORE_SAVE_TIMEOUTS=(120, 120, 180, 240)`, a bare
   `_wait_file_stable(rgn_path, 15)` — none with recorded provenance, and one comment
   (commands.py:1223–1227) that *explicitly records* tuning-by-incident ("A shorter retry budget
   runs out when LAS X is slow late in a long session"). The worst concrete defect found in this
   sweep lives here: `strip_template` **warns and returns success** when the strip demonstrably
   failed, while its in-place sibling correctly fails (OP-01).
2. **Timing/freshness constants.** The profile system centralizes tuning (good), but almost none of
   the numbers in it carry provenance: 3 s confirm windows, 3+3 retry ceilings, 15 s acquire start
   timeout, 20 µm XY tolerance, 6 s hybrid budget, 2 s reader caps that are *smaller than the inner
   read budgets they wrap* (OP-08). Several freshness gates turn out to be tautological on the API
   path they guard (OP-04) — timing machinery that looks protective and is decorative.
3. **Vendor-quirk handling duplicated instead of normalized once.** The µ-mojibake quirk is handled
   by three different implementations with three failure behaviors (OP-13); the phantom
   "zPosition sometimes a bare float" belief is encoded in two dead guards plus one normalizer that
   contradicts it (OP-12); the flush-fire-poll skeleton exists in four copies of which only one has
   stale-response correlation (OP-14); the LRP prolog is carefully preserved by one writer and
   destroyed by its sibling (OP-25).
4. **A small but real residue of test-shaped production code**: the `_reading_value_after`
   old-patch-shape branch (OP-20, confirms LC-05), the adapter's dead dict branch kept alive by
   identity-patched tests (OP-12, confirms LA-02), a dead ~90-line "evidence" subsystem
   (OP-21, confirms LC-01), and a mock that guarantees two scanning reads specifically so the
   production polling blind spot cannot flake CI (OP-06).

Where the code *does* handle a real measured quirk — the select_job transition-witness gate, the
DST fold disambiguation, the blank-`imageSize` transient guard, the resonant no-change echo
acceptance gated on readback — it is documented, dated, and mostly tested. Those are the model the
rest of the constants should be held to.

---

## 2. Magic-constants inventory

Provenance legend: **doc+meas** = commented with measurement/date/instrument; **doc** = role
commented, value unexplained; **none** = bare number; **pinned** = a test asserts the value (drift
pin only — pins the number, not the rationale).

| Value | Meaning | Location | Provenance |
|---|---|---|---|
| `RECEIPT_TIMEOUT = 2` s | transport ACK deadline | utils.py:19 | doc; override mechanism broken (OP-26) |
| `CONFIRM_POLL_S = 3` s | per-attempt readback window | utils.py:21 | doc; value unexplained |
| `PAN_LIMIT = 0.00775` | max galvo pan/axis | utils.py:70 **and duplicated** commands.py:1138 | doc ("known exactly"); duplicated (OP-22) |
| `GALVO_FIELD_FRACTION = 0.667` | FOV shift at max pan | utils.py:71 | doc+meas — but measured on a *different instrument* (OP-22) |
| `max_attempts=3, retry_delay=0.5` s | transport retry | dispatch.py:98 | none (LC-18) |
| `timeout=1.0, poll_interval=0.01` s | echo settle | dispatch.py:128 | none (LC-18); untested (LC-14) |
| `max_retries=3`, `max_confirm_attempts=3` | retry ceilings | profiles.py:232–233 | none |
| confirm tolerances 0.1 / 0.5 / 1.0 / 0.5 / 1.5 / 1.0 / 0.05 / 0.005 / 1 | zoom…fw-spectrum | profiles.py:280–399 | none; pinned (test_confirm_specs) |
| `confirm_tolerance=20.0` µm | MOVE_XY | profiles.py:410; movement.py:110; calibration default | none; three homes (OP-18) |
| `start_timeout=15.0` s, `poll_interval=0.1`, `heartbeat=30.0` | ACQUIRE | profiles.py:441–444 | none; pinned (test_core_driver.py:817) (OP-07) |
| `idle_streak_required = 2` | acquire completion | confirmations.py:1092 | partial comment; count unexplained (OP-06) |
| `1e9` | "no deadline" sentinel | confirmations.py:1095 | none (hygiene) |
| `poll_timeout=5.0`, `poll_interval=0.01` | SELECT_JOB | profiles.py:456–457 | none |
| `selected_job_hybrid_budget_s=6.0` | dual-leg race budget | profiles.py:112 | hybrid *policy* doc+dated; value none |
| `selected_job_log_confirm_timeout_s=2.0`, `log_poll_timeout_s=5.0`, `log_poll_interval_s=0.1` | log leg | profiles.py:114–116 | none |
| `selected_job_log_cluster_max_age_s=None` | log evidence freshness | profiles.py:117 | none; dual meaning (OP-05); disables backstop (OP-03) |
| `hybrid_log_grace_s=0.25` | passive hybrid grace | profiles.py:86 | none; unreachable at defaults (LC-11) |
| `xy_log_max_age_s=1.0` / others `2.0` / scan `0.5` | log freshness | profiles.py:88–125 | none |
| `*_timeout_s = 2.0` | capped API read budget | profiles.py:90–125 | none; smaller than inner budgets (OP-08) |
| `xy_min_delta_um=0.5` | jitter threshold | profiles.py:128 | none; **dead knob** (OP-21) |
| `current_window_s=180.0` | ATL cluster recency | profiles.py:68 | none |
| `_LOG_TAIL_BYTES = 4 MiB` | log tail cap | log_reader.py:99 | doc; value none; outside profiles (LC-12) |
| `delay_ms=250` | Leica API pacing | profiles.py:145 | doc (vendor knob) |
| `timeout=1.0, poll=0.01, max_retries=3` | flush-fire-poll readers | api_reader.py:88,162,197,240 | none |
| `time.sleep(0.05)` @ 20 Hz | idle poll | prechecks.py:76 | none |
| `0.005` s / `0.05` s | race poll / late-loser drain | confirmations.py:160,171; router.py:123,324 | none |
| `MTIME_SKEW_ALLOWANCE_S = 2.0` | SMB clock skew | acquisition/files.py:93 | **doc+bounded-risk — the model comment** |
| `DEFAULT_FILE_STABILITY_TIMEOUT_S = 120` | export stability | navigator_expert_export.py:33 | doc-ish; conflicts with 60 below (OP-10) |
| `DEFAULT_EXPORT_COMPLETION_TIMEOUT_S = 60.0` | grid completeness | navigator_expert_export.py:37 | comment says "same regime as 120 s" (OP-10) |
| `timeout=60` | `wait_all_stable` default | acquisition/files.py:121 | none; third value for the same concept (OP-10) |
| `path_poll_timeout=5.0`, `mtime_poll_timeout=15.0` | export detection | navigator_expert_export.py:52–54 | none |
| `poll_interval=0.5, stable_readings=3` | file stability | _file_utils.py:29 | none (≥1.5 s floor per file) |
| `JOB_SETTINGS_READ_TIMEOUT_S=1.0`, `API_TIMEOUT_S=0.25` | canonical-metadata read | ome_canonical.py:28–29 | none; fallback keeps known-wrong values (OP-11) |
| `timeout=30` / `timeout=5.0` / `save_timeout=120` | save_experiment / save_and_read_lrp / strip | scanfields/files.py:143,263; strip_restore.py:89,164 | none |
| `confirm_delays=(2, 4, 8, 16)` s | LRP confirm-save ladder | transaction.py:105 | none; incident-tuned per commands.py:1223–1227 (OP-09) |
| `_RESTORE_SAVE_TIMEOUTS = (120, 120, 180, 240)` s | restore ladder | strip_restore.py:264 | none (OP-09) |
| `_wait_file_stable(rgn_path, 15)` | lock wait before rollback | strip_restore.py:332,350 | none (OP-09) |
| `overshoot_um=50.0`, `settle_ms=100` | backlash takeup | movement.py:41,110 | doc+meas ("10× margin on 3–5 µm") — but bypassed calibrated values (OP-02) |
| `_OVERLAP_TOL=0.005`, `tol=0.05`, fallback `5.0`, 501 steps | planner | planning.py:19,81,102,221–226; parsers.py:1091 | none (confirms LS-05) |
| `_scan_busy_until +0.1`, `_scan_min_reads=2` | mock scan window | tests/helpers/mock_lasx_api.py:348–356,542–554 | doc (CI flake fix); patches a production blind spot (OP-06) |

`zmart_controller/` contributes **no** entries — it contains no timeouts, retries, sleeps, or
tolerances at all, which is exactly right for its layer.

---

## 3. Findings

Severity: **High** = a patch that can cause real misbehavior when conditions shift; **Medium** =
unexplained tuning/branch that will trap a maintainer; **Low** = hygiene.

### High

---

**OP-01 — `strip_template` warns and returns success when the strip demonstrably failed; its
in-place sibling correctly fails** — **NEW**

- **Where:** `scanfields/strip_restore.py:142–161` vs `scanfields/strip_restore.py:234–242`;
  consumer `zmart_adapter/zmart_adapter.py:666–684` (`_ensure_scan_fields_stripped`).
- **The patch:** after the confirm-save, `strip_template` counts residual objects and, when the
  stripped template *still contains scan fields*, logs
  `"Stripped template still has objects after confirm-save: …"` — then returns
  `{"success": True, ...}` anyway. The sibling `strip_template_in_place`, written later for the
  same operation, logs at error level and returns `None` in the identical situation. Classic
  copy-paste drift: the failure check was hardened in one copy only.
- **Incident it smells like:** an early bench run where the residual-object count was noisy/laggy
  and a hard failure blocked the workflow, so the check was demoted to a warning — and the newer
  sibling shows the team later decided the hard failure was correct.
- **What breaks when conditions shift:** `acquire()` (the controller path) calls
  `_ensure_scan_fields_stripped`, which trusts `strip_template`'s truthiness. On a slow LAS X
  session (exactly the regime the retry ladders elsewhere were tuned for), the strip can not-take,
  `strip_template` returns success, and the acquisition **images the stored scan-field pattern
  instead of the current position** — the precise failure the strip guard exists to prevent, with
  only a log warning as evidence.
- **Fix:** make `strip_template` fail (return `None` or raise) on a non-empty post-strip count,
  matching `strip_template_in_place`; add a unit test for the residual-object path (currently
  untestable-by-accident because strip/restore tests monkeypatch `save_experiment`, LS-35).

---

**OP-02 — Calibrated backlash parameters are validated, loaded, and then shadowed by hardcoded
defaults on every controller-path move** — confirms **LA-01 / LM-01**

- **Where:** `zmart_adapter/zmart_adapter.py:600, 753, 892` (bare calls);
  `motion/movement.py:41, 110` (fallback defaults `overshoot_um=50.0, settle_ms=100`,
  `tolerance_um=20.0`); `motion/stage_config.py:129–143` (schema *requires* the block);
  `motion/movement.py:23–25, 131–134` (docstrings demand production callers pass it).
- **Verified:** the adapter loads `stage_cfg` at connect (`_configure_stage_limits`,
  zmart_adapter.py:188–190) and uses only its limits; `move_xy_with_backlash(handle.client, abs_x,
  abs_y)` and both `correct_backlash(handle.client)` call sites pass no backlash arguments.
  `tolerance_um`/`approach` have no consumer anywhere in the repo.
- **Cross-cutting angle:** this is the overfitting pattern at system level — the machine-snapshot
  system was *built* so per-scope measured values replace bench defaults, and the primary runtime
  motion path quietly opted out. It works today only because the bundled calibration coincides
  with the hardcoded numbers (50/100/20). The first adopted snapshot with a different measured
  backlash is silently ignored.
- **Fix:** keep the loaded `backlash` block on `ZmartHandle` and thread it through all three call
  sites; add a test asserting calibrated values reach `move_xy`.

---

**OP-03 — `select_job` log-evidence window opens before the unbounded idle wait, and the freshness
backstop ships disabled** — confirms **LC-02**

- **Where:** `commands/commands.py:1438` (`command_started_at = time.time()` before `_dispatch`);
  `config/profiles.py:449–458` (`SELECT_JOB` pre-check `check_idle(timeout=None)`);
  `readers/log_wait.py:139–174` (admissibility = `ts > command_started_at`);
  `config/profiles.py:117` (`selected_job_log_cluster_max_age_s: None` →
  `log_reader._too_old(..., None)` → never refuses, log_reader.py:394–401).
- **Verified as described in LC-02.** The cross-cutting addition: the `None` default interacts with
  OP-05 below — the same knob that disables the freshness backstop here is silently *re-interpreted
  as 2.0 s* on the no-op path, so the shipped config is simultaneously "no freshness policy" for
  positive confirmation evidence and "strict 2 s" for the cheaper decision. Whatever value was
  being tuned when `None` landed, the two consumers did not move together.
- **Fix:** anchor the evidence window at fire time (post-pre-check); give
  `selected_job_log_cluster_max_age_s` a finite default; see OP-05 for the aliasing.

---

### Medium

---

**OP-04 — The `observed_after` freshness gates are tautological for API reads: they gate on
read-*completion* time, which is always after the command start** — **NEW**

- **Where:** gate: `commands/confirmations.py:260–275` (`_reading_value_after`); consumers:
  `confirmations.py:1010–1019` (`confirm_move_xy`), `confirmations.py:1087–1100`
  (`confirm_acquire`), `commands/confirm_select_job.py:98–105` (`confirm_select_job`). Timestamp
  producer: `readers/router.py:62–74` — `_api_read` stamps `observed_at = time.time()` **after the
  CAM call returns**, with the honest comment "observed_at/age_s mark call completion, not proof
  that LAS X returned newly-produced state".
- **The patch:** the gates compare `reading.observed_at <= observed_after` and reject. For any API
  read fired after `observed_after` was captured, `observed_at` is by construction later — the
  branch can never fire in production API mode. The only reading it can reject is a test-injected
  one (and log-mode readings, which these confirmations never use).
- **Incident it smells like:** the measured select_job staleness ("stale 15 s+, wrong job",
  profiles.py:104–111). A timestamp gate was added everywhere as the generic fix; for select_job it
  was then discovered to be insufficient and the real fix (the transition-witness baseline,
  confirm_select_job.py:72–97) was built — but the decorative gates stayed, and reviewers now read
  them as protection.
- **What breaks:** nothing *shifts* — that is the problem: the gate gives zero protection against
  exactly the hazard it names. A stale pre-move XY delivered by an uncorrelated flush-fire-poll
  response (OP-14) arrives with a fresh completion stamp and sails through `confirm_move_xy` in an
  A→B→A move pattern. Meanwhile the machinery *looks* load-bearing and has its own test-shape
  accommodation branch (OP-20).
- **Fix:** either make the gate honest — correlate responses to queries (per OP-14) so `value`
  freshness, not call-completion, is what's gated — or delete the gates outside select_job and
  document that API reads have no independent freshness. Keep the transition-witness gate; it is
  the one real protection.

---

**OP-05 — One profile knob, two contradictory meanings: `selected_job_log_cluster_max_age_s=None`
is "no freshness limit" on the confirmation path and "fall back to 2.0 s" on the no-op path** —
**NEW**

- **Where:** evidence path: `readers/log_wait.py:59` (uses the value as-is; `None` →
  `_too_old` → never refuse, log_reader.py:396–398); no-op path:
  `commands/confirm_select_job.py:288–296` (`_selected_job_name_from_log`: `if max_age_s is None:
  max_age_s = profile.selected_job_log_max_age_s` → 2.0 s).
- **The patch:** the no-op reader was evidently written after someone noticed `None` would accept
  arbitrarily old log state for the "already selected" decision — and the fallback-to-2.0 was
  bolted on locally instead of fixing the knob's default. Result: positive confirmation evidence
  (which fires acquisitions on the selected job) is accepted with *no* age limit, while the far
  cheaper no-op short-circuit demands sub-2 s freshness. That is backwards.
- **What breaks:** anyone tuning the knob reasons from one call site and silently changes the other;
  setting it to a finite value tightens the no-op path *less* than they expect (the 2.0 fallback
  disappears), setting it to `None` looks safe by reading `prepare_select_job` and isn't.
- **Fix:** give the knob one meaning: a finite default (e.g. 2.0 s) used identically in both
  places; delete the local aliasing in `_selected_job_name_from_log`.

---

**OP-06 — Acquisition completion = "2 consecutive idle reads at 0.1 s": a hardcoded heuristic whose
known blind spot is patched in the mock, not the protocol** — **NEW** (extends documented
limitation M6 and LT-15)

- **Where:** `commands/confirmations.py:1091–1092` (`idle_streak_required = 2`, local constant, not
  in any profile), `1053–1067` (docstring documenting the short-scan blind spot),
  `profiles.py:441` (`poll_interval=0.1`); mock accommodation
  `tests/helpers/mock_lasx_api.py:348–356, 540–554` (`_scan_min_reads = 2` — the mock *guarantees*
  two observable scanning reads because a starved poller once missed the window under CI load).
- **The patch:** completion is level-based polling with a 2-sample idle debounce. Why 2 and not 3?
  Why is 0.2 s of observed idle proof that a matrix acquisition (which may pause between blocks) is
  finished? No comment, no hardware measurement, no profile knob. Conversely the start-side blind
  spot (scan shorter than one poll gap) is real, documented — and then *solved in the mock* so the
  offline suite can't flake, which means the suite systematically cannot exercise the failure mode
  the real scope can produce.
- **What breaks:** (a) if any LAS X job type reports transient idle >0.2 s mid-acquisition,
  `confirm_acquire` declares completion early and `save()` collects a partial export — the grid
  validator is then the only backstop; (b) a future poll-interval increase silently widens the
  start blind spot with no failing test (the mock guarantees visibility regardless of interval).
- **Fix:** move `idle_streak_required` (and its rationale) into the ACQUIRE profile; record on the
  scope whether mid-acquisition idle blips exist (one afternoon with the matrix job); long-term,
  this is the canonical "polling where a completion signal may exist" case — LAS X logs an
  `AcquisitionState` transition (log_reader.py:583–590) that could corroborate completion instead
  of a debounce count.

---

**OP-07 — `start_timeout=15.0 s` is unexplained, and its failure message admits the ambiguity the
design leaves behind** — **NEW**

- **Where:** `config/profiles.py:443`; `commands/confirmations.py:1132–1140` — the timeout message
  is literally "either it did not start, or it finished between two status polls";
  pinned by `tests/unit/test_core_driver.py:817` (value only).
- **The patch:** 15 s to first non-idle observation, else the acquire is reported failed and (by
  deliberate policy) never re-fired; `capture.acquire` then raises (acquisition/capture.py:57–58).
- **What breaks:** a large template/slow session where LAS X takes >15 s to start scanning: the
  driver raises while the scan *subsequently runs* — data lands on disk unowned by any `save()`
  call, and the next command's idle pre-check silently absorbs the still-running scan. Nothing
  records why 15 s is enough for every job type on this machine.
- **Fix:** a provenance comment with the slowest measured start on this scope (the codebase's own
  standard, cf. acquisition/files.py:87–93), or derive the value per job from measured history;
  log loudly if a scan is observed *after* a start-timeout failure (the log leg can see it).

---

**OP-08 — Nested read budgets are incoherent: the router's 2.0 s cap wraps an inner read that can
legitimately take 6 s+, turning slow reads into claim-contention** — **NEW**

- **Where:** outer cap: `config/profiles.py:94` (`job_settings_timeout_s: 2.0`) consumed at
  `readers/router.py:109–129` (`_capped_api_read`); inner budget:
  `commands/confirmations.py:236–241` — `_readback` passes `timeout=STATE_READERS.
  job_settings_timeout_s` (2.0 s) as the **per-attempt** poll window of
  `api_reader.get_job_settings`, which retries the full cycle `max_retries=3` times
  (api_reader.py:96–158) → worst case ≥6 s inside a 2.0 s cap. Same shape for `get_xy`/`get_jobs`
  (inner 1.0 s × 3 retries vs 2.0 s cap).
- **The patch:** two timeout systems added at different times (the flush-fire-poll retries predate
  the router cap) were never reconciled. When the cap fires, `_capped_api_read` returns `None` but
  the worker thread *keeps the in-flight claim* until the inner retries finish (by design,
  router.py:86–105) — so the next confirmation poll logs "another read in flight" and is skipped
  (confirmations.py:129–133), serially degrading the very confirm loop the budgets serve.
- **What breaks:** on a slow session, a single sluggish settings read cascades: cap timeout →
  claim held ~4 more seconds → subsequent confirm polls skipped → confirm window exhausted →
  spurious re-fire (for `refire_on_unconfirmed` commands). The operator sees "unconfirmed" noise
  whose actual cause is budget arithmetic.
- **Fix:** make the inner budget a function of the outer one (e.g. `max_retries=1`,
  `timeout=cap`), or plumb one budget through; document the claim-holding interaction where the
  cap is defined.

---

**OP-09 — Escalating retry ladders in the template layer are bench-tuned with no provenance, and
one comment records the tuning incident outright** — **NEW** (extends LS-35's coverage gap)

- **Where:** `scanfields/transaction.py:105` (`confirm_delays=(2, 4, 8, 16)` — per-attempt save
  timeouts); `scanfields/strip_restore.py:264` (`_RESTORE_SAVE_TIMEOUTS = (120, 120, 180, 240)`),
  `:332, 350` (`_wait_file_stable(rgn_path, 15)` before each rollback copy);
  `commands/commands.py:1223–1227` — "Use the default confirm_delays … A shorter retry budget runs
  out when LAS X is slow late in a long session — the ROI cookbook with the default budget keeps
  working in those same conditions."
- **The patch:** each tuple is an answer to a specific observed slowness (the commands.py comment
  says so for one of them), with no note of what was measured, on which session, or what the
  ladder's total worst case is (restore: up to 11 min of retries). The 15 s lock-wait before
  rollback has no stated relationship to anything.
- **Why this is the band-aid pattern:** the underlying protocol genuinely lacks a completion
  signal (LAS X save is confirm-by-mtime), so *some* polling is legitimate — but ladder shapes and
  totals chosen by "the run that failed last Tuesday" will be re-tuned by the next incident unless
  the constraint is written down. LS-35 already found the entire ladder has zero test coverage.
- **Fix:** one comment per ladder recording the slowest observed save on this machine and the
  chosen safety factor; name the totals (`RESTORE_WORST_CASE_S`); add the failure-path tests LS-35
  specifies so the rollback ordering is pinned.

---

**OP-10 — Three different numbers for "how long an export file may take to stabilize", one of them
contradicted by its own comment** — extends **LS-29**

- **Where:** `acquisition/navigator_expert_export.py:33` (`DEFAULT_FILE_STABILITY_TIMEOUT_S = 120`);
  `:34–37` (comment: completeness gets "a budget in the same regime as file stability (120 s)" —
  attached to a constant that is `60.0`); `acquisition/files.py:121` (`wait_all_stable(...,
  timeout=60, ...)` — a third default for the same concept, used whenever a caller omits the
  argument, as `lasx_native_autosave.py:78–81` *almost* does not); `scanfields/files.py:143`
  (`save_experiment` uses 30 s for the same physical operation on the template side).
- **What breaks:** the next maintainer "fixing a stability timeout" has four places to choose from,
  and history (the 120-vs-60 comment) shows one edit already missed its sibling. A long
  time-series export that needs the documented 120 s regime falls to the completeness constant's
  60 s and hard-fails.
- **Fix:** one named constant (or one profile field) for file-stability, one for completeness, both
  with the regime rationale; fix the 120/60 comment either way (LS-29).

---

**OP-11 — Canonical OME metadata falls back to *known-wrong* vendor values behind a 0.25 s API
budget, on a machine where the CAM is measured to stall for seconds** — **NEW** (extends LS-27)

- **Where:** `acquisition/ome_canonical.py:28–29` (`JOB_SETTINGS_READ_TIMEOUT_S = 1.0`,
  `JOB_SETTINGS_API_TIMEOUT_S = 0.25`); `:110–134` (`metadata_with_job_physical_sizes`: on timeout,
  warn and keep vendor values — including the documented native-AutoSave `PhysicalSizeZ` bug);
  `:356–387` (`_read_job_settings_bounded`, `max_retries=1`).
- **The patch:** a bounded read (good — an unbounded CAM hang must not stall persistence) with
  budgets tuned tight enough that the driver's own documented environment (modal dialogs freeze the
  CAM "for seconds", log_reader.py:1–7; select_job readback "stale 15 s+", profiles.py:109) will
  routinely miss them. The fallback then *persists* metadata the module itself declares
  semantically wrong, with only a log warning.
- **What breaks when conditions shift:** any session with a slow CAM writes OME files whose Z
  spacing is the vendor's range/sections artifact; downstream quantification is silently wrong.
  The warning is honest but not machine-readable — nothing in `summary.json` records that the
  fallback fired.
- **Fix:** widen the budget to the same regime as other reads (2 s) or retry once after the save
  (the data is already on disk; persistence is not latency-critical); record
  `physical_sizes_source: "job" | "vendor_fallback"` in the summary record so a wrong-Z file is
  identifiable after the fact.

---

**OP-12 — The phantom "zPosition is sometimes a bare float / sometimes a dict" quirk is encoded in
three mutually contradictory places, including a duplicated helper** — confirms **LC-06 + LA-02**,
elevated to a systemic finding

- **Where:** normalizer: `commands/settings.py:139–145` (dict shape → float, **bare float →
  `None`**, silently); dead dict-guard #1: `readers/derived.py:66–86` (`zwide_um_from_settings`,
  docstring asserts "LAS X sometimes nests the value as `{'position': ...}`"); dead dict-guard #2:
  `zmart_adapter/zmart_adapter.py:373–383` (`_z_um_from_settings` — a near-verbatim copy of the
  derived helper, kept "covered" only by tests that patch `make_changeable_copy` to identity,
  test_zmart_adapter.py:84–87).
- **Verified:** both `isinstance(val, dict)` branches are unreachable through the real normalizer;
  the one shape the docstrings say LAS X can emit (bare float) is the one the normalizer destroys.
- **Cross-cutting angle:** this is what an unfixed quirk looks like after two copy-pastes — the
  *belief* propagated (twice), the *handling* never met the data path, and the helper itself was
  duplicated rather than imported (`_z_um_from_settings` vs `zwide_um_from_settings` differ only in
  the key parameter and error strings). If the bare-float shape is real, Z readback breaks on that
  LAS X version in every consumer simultaneously; if it is not, two docstrings teach a phantom.
- **Fix:** normalize both shapes in `make_changeable_copy` (one line), delete both dict-guards,
  have the adapter call `derived` (or a keyed variant) instead of owning a copy, and fix the tests
  to feed the real normalized shape (LA-09).

---

**OP-13 — One vendor encoding quirk (`µm` mojibake), three independent implementations with three
different failure behaviors** — confirms **LS-06 + LA-20**, elevated

- **Where:** `utils.py:147–162` (`_parse_dim_um`: regex `[Ânmuµμ]*m`, the `Â` unexplained;
  returns `(None, None)` on surprise); `scanfields/parsers.py:85–100` (`_parse_size_string`:
  literal `"Âµm"` replace + keep-digits-and-dots filter that would silently *misparse* an
  exponent-format value, wrapped in `except Exception: return None`); plus
  `_tile_size_from_image_size_str` (parsers.py:103–113) silently averaging X and Y on top.
- **The patch:** the UTF-8-as-Latin-1 double encoding was observed once and fixed at each consumer
  independently. utils' version raises on unparseable `imageSize` (good), parsers' version returns
  `None`/garbage; a future LAS X format change will be handled three different ways.
- **Fix:** one `parse_size_string` in `utils.py` with a comment naming the mojibake's producer,
  strict parsing (fail loudly on unknown shapes), consumed by parsers; warn on X≠Y instead of
  averaging (LS-06).

---

**OP-14 — Four copies of the flush-fire-poll reader; the stale-response protection was added to one
and never propagated** — confirms **LC-09** (verified at this commit)

- **Where:** `readers/api_reader.py:88–159` (`get_job_settings` — has `jobName` correlation,
  :122–135), `:162–194` (`get_hardware_info`), `:197–237` (`get_xy`), `:240–272` (`get_jobs`) —
  three copies accept the first non-sentinel post-flush value.
- **Cross-cutting addition:** the correlation comment in `get_job_settings` (:122–124) describes a
  *generic* race ("a delayed response for an earlier job can land after our flush"), i.e. the
  author knew the mechanism applies to every reader on the shared command channel — and fixed only
  the reader where the incident occurred. `get_xy`'s uncorrelated response is what makes OP-04's
  decorative gate an actual hazard (a stale pre-move position with a fresh stamp confirms an
  A→B→A move).
- **Fix:** extract one `_flush_fire_poll` helper; add double-read agreement (or a sequence token)
  where the protocol has no correlation field; at minimum document the risk on the three
  unprotected readers.

---

**OP-15 — The echo `Result` flush failure is swallowed, re-opening the cross-attribution race the
flush exists to close** — confirms **LC-03** (verified)

- **Where:** `commands/dispatch.py:299–302` (`except Exception: pass  # Some API versions may not
  allow Result assignment`), settle condition at `:128–168`.
- **Verified as described in LC-03**; the patchwork angle: this is a version-quirk special case
  ("some API versions") whose degraded mode was never designed — on such a version every
  `_await_echo_result` settles instantly on the *previous* command's `Result`, silently, on every
  command. No test covers the non-assignable shape (LC-14), and the mock pre-settles the echo
  (LC-15), so the whole regime is invisible offline.
- **Fix:** per LC-03 — warn once and degrade explicitly (snapshot-and-require-change, or skip the
  settle and rely on `HasError`), plus the missing tests.

---

**OP-16 — `check_idle` cannot distinguish "scanner busy" from "status unreadable": with the shipped
`timeout=None`, a broken status channel becomes an infinite wait instead of an error** — **NEW**
(interacts with the documented M5 idle policy)

- **Where:** `readers/api_reader.py:53–58` (`get_scan_status`: `except Exception → "Unknown"`);
  `commands/prechecks.py:50–76` (`"Idle" in status` else keep polling at 20 Hz; timeout=None →
  loop forever); `config/profiles.py:311, 407, 417, 430, 450` (every motion/acquire/select profile
  ships `check_idle(timeout=None)`).
- **The patch:** mapping every read failure to the `"Unknown"` sentinel is fail-closed for the
  *busy* interpretation (correct for confirm_acquire, confirmations.py:1104–1116) — but the idle
  pre-check inherits it, so a dead CAM channel, a modal dialog, or a disconnected client turns
  every command into an indefinite hang whose heartbeat says "Waiting for idle: Unknown". The
  unbounded wait was a dated operator decision for a *busy scanner*; nothing in that decision
  covers an unreadable one.
- **What breaks:** the one condition where an operator most needs an actionable error (API wedged
  by a dialog — a scenario this driver documents extensively and can even *detect* via
  `get_pending_dialog`) instead produces an infinite, uninformative wait.
- **Fix:** inside `check_idle`, track consecutive `Unknown` reads; after a threshold, consult the
  dialog diagnostic (`readers.get_pending_dialog`) and fail with a message naming the real cause.
  Keep the unbounded wait for genuine busy states per the operator decision.

---

**OP-17 — `ping()` falls back to reading a cached model attribute, reporting the connection alive
when the command transport is dead** — **NEW**

- **Where:** `readers/api_reader.py:66–80`: if `PyApiPing.UpdateAwaitReceipt` fails **or returns
  False (transport failure)**, fall back to `client.PyApiStatus.Model.ScanStatus` — an in-process
  attribute read that can succeed against a stale .NET model with LAS X gone; consumer:
  `connection/session.py:82–83` (connect-time health gate).
- **The patch:** a fallback added so ping "works" on some client state where the receipt path
  misbehaved — but the fallback tests liveness of the *object model*, not the *channel*. A connect
  that passes this gate can then fail every actual command with confusing transport errors.
- **Fix:** treat receipt failure as failure (that is what `RECEIPT_TIMEOUT`'s own comment says:
  "expiry after transport retries is a hard delivery failure"); if the fallback exists for a real
  client shape, name that shape in a comment and log which path answered.

---

**OP-18 — 20 µm: one unexplained XY tolerance living in three homes** — **NEW** (ties into OP-02)

- **Where:** `config/profiles.py:410` (`MOVE_XY.confirm_tolerance = 20.0`);
  `motion/movement.py:110` (`correct_backlash(..., tolerance_um=20.0)` — a hardcoded default the
  sibling `move_xy_with_backlash` expresses as `None`→profile instead);
  `calibration/defaults/calibration.json` backlash block (`tolerance_um: 20.0`, mirrored by
  test_zmart_adapter.py:914).
- **The patch:** no comment anywhere says what 20 µm is — encoder noise? worst measured settle
  error? just "loose enough that confirms stopped flaking"? For a stage whose backlash is measured
  at 3–5 µm and whose calibration pipeline reports sub-µm residuals, a 20 µm acceptance on every
  confirmed move is a large, silent accuracy ceiling. Because the number is copied in three
  representations, tightening it after a stage service means three edits (and per OP-02, the
  calibrated copy is currently ignored anyway).
- **Fix:** one provenance comment at the profile (what was measured, when); make
  `correct_backlash`'s default `None`→profile like its sibling; wire the calibrated value (OP-02).

---

**OP-19 — The unconfirmed-correction re-fire ignores a failed idle re-check** — confirms **LC-04**
(verified)

- **Where:** `commands/dispatch.py:653–666` — `idle_result = pre_check_fn()` is called, its logs
  appended, its `success` never read; the re-fire proceeds with `pre_check_fn=None` ("Already
  waited for idle above").
- Latent at shipped defaults (`timeout=None` can't fail) but every wrapper exposes
  `pre_check_timeout`; a caller using it gets a correction re-fire into a busy scanner — the exact
  event the pre-check exists to block, with first-fire and correction silently disagreeing.
- **Fix:** one `if not idle_result["success"]: continue` (or return unconfirmed) + a test.

---

**OP-20 — Test-shaped production code in the confirmation safety path** — confirms **LC-05 +
LC-16** (verified)

- **Where:** `commands/confirmations.py:260–275` — `_reading_value_after`'s docstring states its
  reason for existing: "Tests sometimes patch routed readers with their old plain return shape;
  those values are accepted here so the tests can stay focused on confirmation logic." The
  `not hasattr(reading, "value") → return reading` branch bypasses the (already decorative, OP-04)
  freshness gate for any non-`Reading` value. Companion dead knob: `_readback(...,
  observed_after=None)` (confirmations.py:229–253) — a freshness gate parameter with zero callers.
- **Judgment:** textbook test-induced production code: the production contract was bent to old test
  fixtures rather than the fixtures updated (`test_state_readers.py:230–257` shows the correct
  `Reading` pattern already exists). A future reader refactor returning plain values would
  *silently* lose the gate instead of failing loudly.
- **Fix:** delete the plain-value branch and the dead parameter; update the handful of tests to
  patch with `Reading` objects.

---

**OP-21 — A dead ~90-line "change/target evidence" subsystem plus its dead profile knob ship in the
readers package** — confirms **LC-01** (re-verified by grep at this commit: `change_spec` /
`key_delta` / `xy_min_delta_um` have zero call sites outside `capabilities.py` and the profile
definition)

- **Where:** `readers/capabilities.py:59–71, 112–164, 204–249`; `config/profiles.py:128`.
- **Patchwork angle:** speculative machinery that duplicates semantics the real implementations own
  (`_selected_job_evidence` vs `log_wait._selected_job_reason`), advertised by the module docstring
  as powering the confirmation race, which never touches it. It will drift (its `_xy_evidence`
  already bypasses `max_age_s`).
- **Fix:** delete; resurrect from git with a consumer in hand.

---

**OP-22 — Galvo pan calibration: a safety constant duplicated, and a scope constant measured on a
different instrument outside the snapshot system** — confirms **LC-08 + LA-08** (verified)

- **Where:** `commands/commands.py:1138` (`_PAN_LIMIT = 0.00775`) duplicating `utils.py:70`
  (`PAN_LIMIT`, from which `pan_scale_um_from_base_fov` derives the physics); `utils.py:65–71` —
  `GALVO_FIELD_FRACTION = 0.667` measured on the ZMB **STELLARIS 8** (2026-04-23) while this driver
  targets the STELLARIS 5, with the code's own WARNING that no snapshot path can correct it.
- The provenance comment is exemplary; the *placement* is the patch: the one calibrated quantity
  that didn't get a snapshot home is the one that targets the galvo. Range-check and scale math
  agree only by coincidence of two literals.
- **Fix:** import `PAN_LIMIT` in commands.py (one line); move `GALVO_FIELD_FRACTION` into the
  calibration schema with the current value as bundled default (LA-08).

---

**OP-23 — `save_experiment` confirms by raw `mtime >` with no skew allowance, under a blanket
`except Exception`, while the acquisition side of the same driver documents 2 s of mtime skew as a
real hazard** — confirms **LS-08** (verified), cross-module inconsistency emphasized

- **Where:** `scanfields/files.py:180–194` (bare `st_mtime > old_mtime` on `poll`), `:222–224`
  (`except Exception → None` around the whole body — a programming error is indistinguishable from
  a save timeout) vs `acquisition/files.py:87–103` (documented `MTIME_SKEW_ALLOWANCE_S = 2.0`).
- One team member solved the clock problem and wrote the model comment; the template layer —
  which drives the OP-09 retry ladders precisely because saves "fail" — never adopted it. On a
  coarse-mtime filesystem, a genuinely-completed save inside one mtime tick reads as "not saved",
  feeding the escalating ladders more incidents to be tuned against.
- **Fix:** reuse the skew allowance (or `>=` + the existing size/stability check); narrow the
  except to the client call.

---

**OP-24 — Template state "fresh" is also the answer when the environment is unknowable, and the
acquire path trusts it** — confirms **LS-09**, elevated because of the consumer

- **Where:** `scanfields/files.py:93–96` (`templates_dir is None → "fresh"`);
  `zmart_adapter/zmart_adapter.py:675–677` (`if state in ("stripped", "fresh"): return` — the strip
  guard passes without verifying anything).
- On a host with `%APPDATA%` unset or multiple LAS X user profiles (files.py:63–70 refuses to pick
  one — correctly — and returns None), the guard that exists to prevent pattern-acquisition
  evaporates silently. Combined with OP-01, both layers of the strip defense can no-op.
- **Fix:** return a distinct `"unknown"` state and have `_ensure_scan_fields_stripped` raise on it
  with the same actionable message it already has for `"unreadable"`.

---

**OP-25 — Two LRP write strategies: `reorder_jobs` preserves the vendor prolog verbatim; the ROI
editors in the same transaction destroy it** — confirms **LS-16** (verified)

- **Where:** `scanfields/transaction.py:83–89` (prolog splice + `insert_comments=True`, with the
  rationale) vs `experimental/lrp_edits/roi.py:268, 292, 553, 625` (`ET.parse` + `tree.write` —
  drops pre-root comments and every in-document comment); strategy split self-documented at
  roi.py:8 but silent on the prolog loss.
- Inside one `apply_lrp_change` call the pipeline strips the prolog (ROI edit) and then carefully
  preserves what's left (reorder). Either the prolog matters — then every ROI edit corrupts the
  template — or it doesn't, and reorder's machinery is unjustified. Evidence for one or the other
  (a hardware round-trip showing LAS X regenerates the header) is recorded nowhere.
- **Fix:** per LS-16 — same parser treatment in roi.py, or record the round-trip evidence at both
  sites.

---

**OP-26 — The documented tuning mechanism for the two global timeouts cannot work, and transport
tuning lives outside the profile system that exists for exactly this** — confirms **LA-07 + LC-18**
(verified)

- **Where:** `utils.py:16–18` ("Import and override these to tune for your hardware") vs
  import-time value binding at `config/profiles.py:59, 235, 244`, `commands/dispatch.py:51, 112`,
  `readers/api_reader.py:42`, `scanfields/files.py:19`; hardcoded transport/echo tuning at
  `dispatch.py:98, 128`.
- An operator on slow hardware following the documented instruction sees no effect and no error —
  broken tuning advice on a timeout is worse than none. Meanwhile the package's stated rule
  ("machine-sensitive tuning lives in profiles", profiles.py:1–12) is contradicted by the very
  constants most likely to need per-machine tuning.
- **Fix:** route both through a profile (read at call time) and fix the comment; move
  `max_attempts/retry_delay` and the echo-settle window into `CommandProfile`/`LasxApiProfile`.

---

### Low

---

**OP-27 — Log scan-status code table is self-declared unverified; all non-zero codes map to
"running"** — confirms **LC-26** (verified at log_reader.py:583–590). Mitigated today by
`check_idle` pinning API. Verify on hardware or restrict to `{0: idle}` + `Unknown`.

**OP-28 — Vendor-prose substring matching: inventory and judgment.**
Where: `commands/errors.py:31–51` (transient/permanent pattern lists), `:152–156` (unanchored
`"warning" in error_msg.lower()` — confirms LC-21), `commands/commands.py:282–301`
(`_SCAN_RESONANT_NO_CHANGE` exact-prose match), `prechecks.py:57` / `confirmations.py:1112`
(`"Idle" in status`). Judgment: the taxonomy lists are principled (priority order, unclassified →
permanent with a warning log) and `_scan_resonant_error_check` is the *model* quirk handler — the
prose match is gated on an independent readback, so a Leica rewording fails loud, not silent. The
one to fix is the unanchored `"warning"` substring (an error *mentioning* "warning" is swallowed as
success): anchor it to the observed `Warning...` prefix shapes.

**OP-29 — Poll-window injection decided by `functools.partial` introspection** — **NEW**.
`commands/commands.py:110–112, 184–194` (`_has_bound_keyword`) and `:198`
(`getattr(profile.pre_check_fn, "keywords", {})`): whether a confirm gets `poll_window` injected
depends on it being a `partial` with specific keyword names. A confirm bound with a lambda (the
pattern the module docstring itself teaches at commands.py:14–19) silently gets `poll_window`
injected into a function that may not accept it → `TypeError` at confirm time, absorbed by
dispatch's blanket confirm-exception handler (dispatch.py:604–610) as a generic failed
confirmation. Convention enforced by shape-sniffing rather than declaration; a
`binds_own_window: bool` on the profile (or a marker attribute) would fail loud instead.

**OP-30 — .NET enum int fallbacks (`eMoveXY=2 (NOT 0 which is eDontMove!)`)** —
`commands/commands.py:1094–1106, 1269–1323`. Hardcoded interop ints used when enum resolution
raises for *any* reason. Judged acceptable: the comment records a real prior bug (0 = eDontMove),
a warning is logged, and the fallback values are load-bearing on some client shapes. Keep;
consider failing hard for `MoveXyMode` specifically, where the wrong int silently does nothing.

**OP-31 — Best-effort swallow on the JobName commit receipt** — **NEW low**.
`readers/api_reader.py:99–102`: the parameter-commit `UpdateAwaitReceipt` is wrapped in
`except Exception: pass` ("best-effort; command channel is the real transport"). A dropped commit
means polling for the *previous* job's settings; today the `jobName` correlation guard catches it
(the one reader that has it — OP-14), so this is only safe by co-location. Document the coupling or
check the receipt.

**OP-32 — 4 MiB log tail re-read and re-parsed per poll; the constant lives outside the profile
system the module header promises** — confirms **LC-12** (verified: log_reader.py:48 "no hardcoded
values in the read paths" vs `_LOG_TAIL_BYTES` at :99, plus the double file read via
`_read_msgbox_state` per `parse_log`). Cheap fix: `(st_size, st_mtime_ns)` short-circuit; move the
constant into `LogReaderProfile`.

**OP-33 — `sys.path` bootstrap patchwork, counted** — confirms **ZC-14 / LA-19 / LT-10 / LM-26 /
LM-30**. One root cause (no packaging metadata) has produced ≥20 copies across the two components:
`zmart_controller/tests/conftest.py:13–17` + both notebooks; driver `__init__.py:260–274`;
`tests/conftest.py`; 14 per-file inserts in `tests/unit/`; two notebook `_bootstrap.py` shims;
`run_ci.py`. Every copy is a relayout landmine (`parents[N]` indexing). The `[project]` table fix
(ZC-14) retires all of them.

**OP-34 — `limits/current.json`: per-run runtime data committed inside the driver package** —
confirms **LM-07** (verified present at this commit; module docstring at stage_config.py:59–66
admits it is legacy "for now"). A workaround documented as temporary that is aging into permanence
— schedule the lift or untrack the file.

**OP-35 — `zmart_controller` is certified near-clean for this sweep.** The package contains zero
timeouts/retries/sleeps/tolerances, no vendor special cases, no test-shaped branches, and its mock
is a faithful reference rather than a drifted stub. Residuals, all previously filed: the
signature-erasing `set_instrument(*args, **kwargs)` (`__init__.py:43`, ZC-04), the ZC-14 packaging
gap, and docs drift (ZC-01/02/05). Nothing new found.

---

## 4. Summary table

| ID | Sev | Component | Title | Prior ref |
|---|---|---|---|---|
| OP-01 | High | scanfields | `strip_template` warns-and-succeeds on a failed strip; in-place sibling fails — acquire can image a stored pattern | NEW |
| OP-02 | High | adapter/motion | Calibrated backlash validated+loaded, shadowed by hardcoded 50/100/20 on every controller move | LA-01/LM-01 ✔ |
| OP-03 | High | commands/readers | select_job evidence window opens pre-fire; freshness backstop ships disabled (`None`) | LC-02 ✔ |
| OP-04 | Med | confirmations/router | `observed_after` freshness gates are tautological for API reads (completion-time stamps) | NEW |
| OP-05 | Med | profiles/select_job | `selected_job_log_cluster_max_age_s=None` means "unlimited" on one path, "2.0 s" on the other | NEW |
| OP-06 | Med | confirmations/mock | `idle_streak_required=2` completion heuristic; blind spot patched in the mock, not the protocol | NEW (M6/LT-15) |
| OP-07 | Med | profiles | `start_timeout=15 s` unexplained; failure message admits start-vs-missed ambiguity | NEW |
| OP-08 | Med | router/readers | Inner read budgets (≥6 s) exceed the 2.0 s router cap → claim contention degrades confirm loops | NEW |
| OP-09 | Med | scanfields | Retry ladders (2,4,8,16)/(120,120,180,240)/15 s bench-tuned; incident-tuning recorded in a comment | NEW (LS-35 adj.) |
| OP-10 | Med | acquisition | Three conflicting stability budgets (120 / 60 / 60) + self-contradicting comment | LS-29 ✔ + NEW |
| OP-11 | Med | acquisition | 0.25 s metadata read budget silently persists known-wrong vendor PhysicalSizeZ | NEW (LS-27 adj.) |
| OP-12 | Med | settings/derived/adapter | Phantom bare-float z quirk encoded in 3 contradictory places; duplicated helper | LC-06/LA-02 ✔ elevated |
| OP-13 | Med | utils/parsers | µm-mojibake quirk implemented 3 ways with 3 failure behaviors | LS-06/LA-20 ✔ elevated |
| OP-14 | Med | api_reader | Flush-fire-poll ×4; stale-response correlation on one copy only | LC-09 ✔ |
| OP-15 | Med | dispatch | Swallowed echo `Result` reset re-opens cross-attribution race on some API versions | LC-03 ✔ |
| OP-16 | Med | prechecks | `Unknown`-on-exception + `timeout=None` turns an unreadable status channel into an infinite wait | NEW |
| OP-17 | Med | api_reader/session | `ping()` model-attribute fallback reports alive when command transport is dead | NEW |
| OP-18 | Med | profiles/motion/cal | 20 µm XY tolerance, unexplained, in three homes | NEW |
| OP-19 | Med | dispatch | Correction re-fire ignores a failed idle re-check | LC-04 ✔ |
| OP-20 | Med | confirmations | Test-shape accommodation branch in the freshness gate; dead `observed_after` knob | LC-05/LC-16 ✔ |
| OP-21 | Med | capabilities | Dead ~90-line evidence subsystem + dead `xy_min_delta_um` knob | LC-01 ✔ |
| OP-22 | Med | utils/commands | `_PAN_LIMIT` duplicated; `GALVO_FIELD_FRACTION` measured on a STELLARIS 8, outside snapshots | LC-08/LA-08 ✔ |
| OP-23 | Med | scanfields | `mtime >` confirm without the skew allowance the sibling module documents; blanket except | LS-08 ✔ |
| OP-24 | Med | scanfields/adapter | "fresh" returned for unknowable template state; strip guard trusts it | LS-09 ✔ elevated |
| OP-25 | Med | lrp_edits/transaction | ROI editors destroy the LRP prolog `reorder_jobs` preserves | LS-16 ✔ |
| OP-26 | Med | utils/dispatch | "Import and override" tuning cannot work; transport/echo tuning outside profiles | LA-07/LC-18 ✔ |
| OP-27 | Low | log_reader | Unverified scan-status code table (all non-zero → running) | LC-26 ✔ |
| OP-28 | Low | errors/commands | Vendor-prose substring inventory; anchor the `"warning"` match; resonant no-change handler is the model | LC-21 ✔ |
| OP-29 | Low | commands | `partial`-introspection decides poll-window injection; lambdas silently misroute | NEW |
| OP-30 | Low | commands | .NET enum int fallbacks — documented, acceptable; consider hard-fail for MoveXyMode | NEW (noted OK) |
| OP-31 | Low | api_reader | Best-effort swallow on JobName commit receipt, safe only via the correlation guard | NEW |
| OP-32 | Low | log_reader | 4 MiB tail re-read per poll; constant outside profiles despite module's own rule | LC-12 ✔ |
| OP-33 | Low | repo-wide | ≥20 `sys.path` bootstrap copies from one missing `[project]` table | ZC-14/LT-10/LA-19 ✔ |
| OP-34 | Low | limits | `limits/current.json` runtime artifact in VCS, "for now" aging into permanence | LM-07 ✔ |
| OP-35 | Low | zmart_controller | Certified near-clean: no magic constants, no quirk branches, no test-shaped code | ZC-04/ZC-14 ✔ |

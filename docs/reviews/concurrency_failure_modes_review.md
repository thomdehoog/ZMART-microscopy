# Concurrency & Failure-Mode Review: `zmart_controller` + Leica Stellaris5 `navigator_expert` driver

- **Scope:** (1) `zmart_controller/` (all); (2) `zmart_drivers/leica/stellaris5_y42h93/navigator_expert/` (all, including tests). Rest of repo read for context only.
- **Focus:** thread lifecycle, shared state, waits/timeouts, failure modes (LASX hang/crash, log stall/rotation, process kill mid-move, concurrent callers, reconnect cycles), time handling, confirmation-race happens-before reasoning.
- **Date:** 2026-07-03
- **Reviewed commit:** `c7964dd` (working tree == origin/main)
- **Verification:** all Critical/High claims were reproduced with runtime experiments against this tree (scripts in scratchpad; key results quoted inline). The in-scope concurrency test files pass (`test_confirmation_race.py`, `test_log_wait.py`, `test_select_job_confirm.py`, `test_state_readers.py`: 62 passed in 1.71s).
- Cross-references: prior reviews `leica_commands_connection_readers_review.md` (LC-xx), `zmart_controller_review.md` (ZC-xx), `leica_scanfields_acquisition_review.md` (LS-xx). Findings below are new unless explicitly marked as confirming/extending a prior item.

---

## 1. Executive summary

The driver's *read* side is genuinely well engineered for a hostile peer: every deadline in the polling infrastructure uses a monotonic clock, the log parser is stateless and rotation-safe, failed reads fail closed to `None` rather than a wrong value, the single-flight API cap prevents thread pile-up behind a hung CAM call, and worker threads can never die silently (all exceptions are captured into `Reading`s or result dicts, and every wait on them is bounded). DST-fold disambiguation is implemented once (`_parse_ts`) and is the only log-timestamp parser, so the prior review's credit holds everywhere.

Three structural problems undercut this:

1. **The hybrid confirmation race's API leg is dead code at runtime (CF-01, High, verified).** `race_confirmations` runs the API leg inside the single-flight worker, which holds the per-client in-flight claim — and the leg's own readbacks (`get_jobs` via the router) then try to claim the *same* key and are refused until they time out. Reproduced: the raw CAM reader is called **zero** times inside a race; the identical leg succeeds outside one. `select_job`'s shipped `hybrid` policy is therefore log-only in practice, contradicting its own validation rationale ("log-only is insufficient on the simulator").
2. **The command path has unbounded waits that turn a LASX crash into a permanent driver hang (CF-02/CF-03, High, verified).** Every hardware profile ships `check_idle(timeout=None)`, and `ACQUIRE` ships `poll_timeout=None`. Both loops treat an unreadable status as "not idle / not done" — correct fail-closed reads composed into a fail-*hung* wait. Reproduced: `check_idle(timeout=None)` against a dead client never returns.
3. **Single-flight is a comment, not a mechanism (CF-08), and disconnect is a flag, not a teardown (CF-06).** `dispatch.py` documents "commands are single-threaded by convention"; nothing in `Session`, the adapter, or the driver enforces it, and the controller's own module-level `set_instrument` swap (ZC-01) leaves the previous CAM client connected forever while opening a second one under the same client name.

Everything else is medium/low: wall-clock anchors in the confirmation happens-before model (CF-04), the abandoned race leg outliving its budget (CF-05), two non-atomic in-place writes of the live LAS X template (CF-07), and assorted hygiene. On-disk state management (`machine.py` snapshots, origin persistence, acquisition materialization) is atomic and crash-safe; a driver kill mid-move leaves recoverable state everywhere except the two CF-07 write sites.

**1 verified High-with-Critical-consequences design break (CF-01), 2 further High, 5 Medium, 7 Low.**

---

## 2. Thread & shared-state inventory

### 2.1 Threads

No thread anywhere is joined, stopped, or tracked at disconnect; there are no timers, no `atexit`, and no signal handlers in scope. All threads are daemons, so interpreter exit abandons them mid-CAM-call (see CF-14).

| # | Thread (name) | Created by | Cardinality / lifetime | Daemon | Exception behavior | How the main flow notices death/hang |
|---|---|---|---|---|---|---|
| 1 | `lasx-api-read` | `router._fire_api_read` (router.py:105) | one per capped API read; also hosts the race's API leg. Lives until the CAM call returns — **forever if it hangs** | yes | `_api_read` (router.py:62-83) catches all exceptions into an error `Reading`; claim released in `finally` (router.py:100-103) | caller waits on a `Queue` with a monotonic deadline (`_capped_api_read`, router.py:117-129) → bounded `None`. A permanently hung worker holds the in-flight claim, so later reads return `None` fast (by design) |
| 2 | `lasx-log-reader` | `router._log_rescue_concurrent` (router.py:288) | one per hybrid passive read — **unreachable at shipped defaults** (LC-11) | yes | `_snapshot_read` catches all exceptions | race loop bounded by `timeout_s`; thread abandoned on deadline (no I/O bound inside — CF-09) |
| 3 | `lasx-confirm-log` | `confirmations.race_confirmations` (confirmations.py:124) | one per dual-leg confirm attempt (select_job hybrid: up to 3 per command) | yes | `run_log_leg` wrapper catches all exceptions into a failed outcome (confirmations.py:114-122) | race loop bounded by `budget_s`; abandoned thread writes into a dead per-attempt queue (no cross-attempt attribution — good design) |
| 4 | (unnamed) | `ome_canonical._read_job_settings_bounded` (ome_canonical.py:383) | one per bounded settings read during save | yes | worker stores the exception, which is then never logged (LS-27) | `Event.wait(timeout)` → bounded `None`; thread leaked per timeout (LS-27) |

`zmart_controller` creates no threads. Test threads (`test_confirmation_race.py`, `test_state_readers.py`) are event-gated and released in the tests themselves.

### 2.2 Shared state

| Structure | Location | Writers / readers | Protection | Assessment |
|---|---|---|---|---|
| `_API_IN_FLIGHT` set | router.py:23-24 | capped-read workers + all read callers | `threading.Lock` | correct; claim/release always paired via `finally`. Claim can be held past the race budget (CF-05) and forever on a hung call (documented) |
| result `queue.Queue`s | router.py:97, 283; confirmations.py:111 | one worker, one consumer, per call | queue's own lock | correct; abandoned queues garbage-collect; no cross-attempt reuse |
| CAM client model objects (`PyApiCommandEcho`, `PyApi*` models) | .NET side, shared per client | command path (main thread) + capped read workers | **convention only** (dispatch.py:20-24) | the cap serializes router reads; nothing serializes commands vs. reads or commands vs. commands (CF-05, CF-08) |
| `motion.limits._stage_limits` | limits.py:26-35 | `connect()` writes; every move reads | none (module global, "intentional", limits.py:13-15) | process-global across handles; torn update possible during concurrent connect + move (CF-10) |
| `ZmartHandle.origin` / `used_p` / `closed` / `function_limits` | zmart_adapter.py:114-157 | all adapter ops | none | single-writer assumption; `used_p` race duplicates a `p` slot → product overwrite (CF-08) |
| `zmart_controller._active`, `registry.REGISTRY` | `__init__.py:40`, registry.py:52 | `set_instrument`/`disconnect`/`register` | none | ZC-08 (confirmed); swap is non-atomic |
| profile singletons (`LOG_READER`, `STATE_READERS`, `LASX_API`, command profiles) | profiles.py | none after import | `@dataclass(frozen=True)` | immutable — correct |
| LAS X log files | ProgramData | LCS.exe writes; driver reads | stateless re-read per poll | rotation-safe by construction (log_reader.py:95-117) |
| `Snapshot` | log_reader.py:224 | one per parse, never shared across threads that mutate it | n/a | correct |

---

## 3. Failure-mode walkthroughs

### (a) LASX process hangs mid-command (modal dialog, GUI wedge)

- **Passive reads:** the CAM call parks in the `lasx-api-read` daemon worker; the caller gets `None` after `timeout_s` (2.0s) and the in-flight claim stays held so no threads pile up (router.py:86-129 — the documented design, works as stated). If the hung call *never* returns (dialog dismissed but channel dead), that client is permanently read-blind: every subsequent capped read returns `None` until a new client is connected. There is no recovery hook.
- **Command fire:** `UpdateAwaitReceipt(receipt_timeout)` carries a Leica-side 2s deadline and returns `False` on transport failure → structured failure + dialog diagnostic (`_append_dialog_warning`, dispatch.py:84-90) — bounded, and the diagnostic is exactly right here. But the echo **flush** (dispatch.py:297-302), `_await_echo_result`'s per-iteration property reads (dispatch.py:153-158), and `_check_api_error` (errors.py:126) are raw CAM property accesses on the caller thread with no watchdog; if property access blocks the way the read path documents CAM calls can block, the fire pipeline hangs before any timeout is consulted (CF-15).
- **Pre-checks:** `check_idle` gets `None`/`"Unknown"` from the capped reader and, with the shipped `timeout=None`, **spins forever** at ~2s per iteration (CF-02, verified).
- **Verdict:** reads degrade exactly as designed; the command path partially hangs. The dialog diagnostic is unreachable in the one scenario it names when the hang happens inside the fire step rather than after it.

### (b) LASX crashes / socket drops mid-command

- Interop calls raise → `_fire_block` converts every step's exception into a structured failure (dispatch.py:246-333) — correct, bounded, caller can distinguish (message carries the exception).
- Reads produce error-carrying `Reading`s → `None` to plain callers — correct.
- **But:** if the crash lands during `check_idle(timeout=None)` (every MOVE/OBJECTIVE/ACQUIRE/SELECT_JOB pre-check) the driver hangs forever (CF-02, verified against a raising client). If it lands **mid-acquisition**, `confirm_acquire` is in phase 2 (`saw_scanning=True`), its deadline is `t_start + 1e9` (confirmations.py:1095), every status read is `None` → `consecutive_idle=0` → **infinite loop**; the phase-1 permanent-error check is unreachable once `saw_scanning` is set (CF-03).
- Crash *before* scan start: phase 1's `_check_api_error` raises → caught by `confirm_and_fire` → `success=True, confirmed=False` (ACQUIRE `success_on_unconfirmed=True`) → `capture.acquire` proceeds and `save()`'s freshness/grid gate is the backstop — the documented posture (profiles.py:433-437). Defensible, though "LASX just died" and "readback shy" are reported identically.
- **Verdict:** fire path sound; wait loops turn a crash into a hang (CF-02/CF-03).

### (c) Log file rotates or stalls while a confirmation wait is active

- Every poll re-opens and re-reads the tail (`_tail_lines`, log_reader.py:102-117); there is no retained file handle, offset, or inode cache → rotation/truncation between polls is invisible and safe. A partial last line and a mid-file seek's first line are dropped (log_reader.py:115-116). `OSError` → empty snapshot → fail closed (log_reader.py:260-264, 348-349).
- A **stalled** log (LCS.exe wedged): no fresh `CurrentBlock` events → `wait_for_selected_job_log` returns `reason="timeout"` (log_wait.py:112-121) → log leg fails closed → select_job unconfirmed. Correct, and correctly distinguishable via `log_reason`/`log_diagnostics` (confirm_select_job.py:157-163).
- A stalled **msgbox** log silently disables the dialog diagnostic and log-side scan status — degradations, never wrong values.
- The residual admissibility risks are the known LC-02 pre-fire window (confirmed at commands.py:1438 → `check_idle(timeout=None)` in profiles.py:450 → `ts > command_started_at` in log_wait.py:139-145 with the freshness backstop disabled by `selected_job_log_cluster_max_age_s=None`, profiles.py:117) and the wall-clock anchor itself (CF-04).
- **Verdict:** sound and fail-closed. Cost side (4 MiB re-read per 0.1s poll) already flagged as LC-12.

### (d) Driver process killed mid-move — state on disk, recovery

- **Hardware:** `move_xy` fires `UpdateAsync` (fire-and-forget, profiles.py:406-414); the stage completes the commanded *absolute* move autonomously inside LASX. No hardware-unsafe intermediate state is possible from the kill itself; limits were checked pre-fire (zmart_adapter.py:586-597).
- **On-disk, correct:** `machine.py` is exemplary — origin written tmp+`os.replace` (machine.py:242-246), snapshots staged and atomically renamed with cleanup on `BaseException` (machine.py:299-318), monotonic snapshot-name guard against backward clocks (machine.py:248-263). Acquisition products: unique tmp suffix + `os.replace` (materialize.py:131-134, LS review credit confirmed). Strip/restore: sidecar-only strip, `.bak` files deliberately kept when rollback fails (strip_restore.py:353-365) and a crashed run's stale `.lrp.bak` is guarded against on the next run (strip_restore.py:293-295). `strip_template_in_place` uses tmp+replace (strip_restore.py:200-205).
- **On-disk, broken:** `transaction.reorder_jobs` rewrites the live `.lrp` **in place** with a plain `write_text` (transaction.py:89), as do `_primitives._set_job_attr`/`_set_sequential_attr` (\_primitives.py:84, 170). Kill mid-write → truncated template that LAS X will load next (CF-07). The `apply_lrp_change` docstring documents "no rollback" for *logical* failures but not this torn-write case.
- **Recovery:** implicitly defined — reconnect restores the persisted origin (zmart_adapter.py:333-360), limits reload from the newest snapshot, `hash6` is new per session so `used_p` reuse cannot collide with the previous session's filenames (Naming carries `hash6`). No in-flight-move journal exists; none is needed for absolute moves.
- **Verdict:** good except CF-07.

### (e) Two commands issued concurrently from user code

- **Enforced or hoped?** Hoped. dispatch.py:20-24 says it plainly ("two threads issuing commands on one client would trample each other's echo… single-threaded by convention"). Neither `Session` (layer.py has no lock), nor the adapter ops, nor the driver wrappers serialize anything (CF-08; ZC-08 confirmed on the controller side).
- **What actually breaks:** thread B's echo flush (dispatch.py:297-302) erases the echo thread A's `_await_echo_result` is polling → A settles on B's result or times out; `_check_api_error` cross-attributes B's rejection to A. Two concurrent `acquire()` calls race `handle.used_p` (`_assign_p_slot`, zmart_adapter.py:695-702) → same `p` → `save()` upserts one acquisition over the other (silent product loss). Concurrent `connect()` + move: torn `_stage_limits` (CF-10). Passive reads *are* protected (the cap), which may lull a caller into assuming commands are too.
- **Verdict:** the single-flight assumption is real and load-bearing but exists only as a comment; one `RLock` per handle would make it a mechanism (CF-08).

### (f) Disconnect/reconnect cycles

- Module-level `set_instrument` swap (ZC-01 confirmed): the previous session's `disconnect()` reaches `zmart_adapter.disconnect`, which is **flag-only** (`handle.closed = True`, zmart_adapter.py:363-365) — "the CAM client itself has no teardown". So what actually happens on the Leica side is: **nothing**. The old TCP/CAM registration stays alive for the process lifetime.
- The new `connect()` then loads the assemblies again, creates a **new** `LasxApiClientPyModel` (lasx_runtime.py:55-60), and calls `Connect("PythonClient")` with the *same default client name* (session.py:72, CONNECTION dict zmart_adapter.py:94). Whether LASX rejects the duplicate name (→ `ConnectionError`, in which case module-level reconnect is impossible without a process restart) or accepts it (→ two live clients, connection accumulation per cycle) is unverified on hardware; there is no `Disconnect` call anywhere in the package (grep-verified) (CF-06). `connect_python_client` also leaks a successfully-connected client when the follow-up ping raises (session.py:82-84).
- **Stale threads/claims:** hung `lasx-api-read` workers keyed by `id(old_client)` keep the old client alive via the closure, so their claims can never collide with a new client's key — no cross-session attribution. Log readers are client-independent. No stale-thread hazard beyond the leaks.
- Failure ordering in the controller itself is careful and tested (resolve-before-teardown, mark-closed-before-teardown — layer.py:168-174, `__init__.py:52-57`).
- **Verdict:** controller-side ordering is right; driver-side "disconnect" does not exist, so every reconnect cycle leaks a connected CAM client and may not work at all (CF-06).

### Time handling (audit item)

- **Deadlines:** every polling deadline uses `time.monotonic()` or `time.perf_counter()` — router.py:117,291; log_wait.py:62-64; confirmations.py:126-137, 325-328, 1094; dispatch.py:149; prechecks.py:47. **No wall-clock deadlines exist.** Good.
- **DST:** `_fold_disambiguate` (log_reader.py:120-131) is used by `_parse_ts`, and `_parse_ts` is the *only* log-timestamp parser in the package (grep: `strptime` appears once) — the prior review's credit is verified to hold everywhere log timestamps are produced. Spring-forward's nonexistent hour cannot appear in LAS X-stamped lines.
- **Cross-domain anchors are wall-clock:** `command_started_at = time.time()` (commands.py:1438, dispatch.py:521) is compared against LCS-stamped log epochs (log_wait.py:139-145) and against `Reading.observed_at = time.time()` (router.py:67; gates at confirmations.py:260-275, 1010, 1087; confirm_select_job.py:98). A wall-clock step during a command window breaks the happens-before model in both directions (CF-04).
- Sleep granularity (5-100 ms) is appropriate for the poll windows used.

---

## 4. Findings

Severity: **Critical** = plausible data loss / hardware-unsafe state / permanent hang in normal operation; **High** = wrong result or deadlock under realistic failure; **Medium** = unhandled edge needing unusual timing; **Low** = hygiene.

---

### CF-01 — **High** — The hybrid confirmation race's API leg self-blocks on its own in-flight claim: it can never perform a CAM read

- **Files:** `commands/confirmations.py:112` (`api_results = _router._fire_api_read(api_leg, api_key)` — the worker claims `api_key` and holds it for the leg's entire duration, router.py:95-105); `commands/confirm_select_job.py:101-103` (the leg's poll body: `_readers.get_jobs(client, mode="api", …)`); `readers/router.py:192-231` (that call routes to `_capped_api_read(api_fn, api_key=id(client), timeout_s=2.0)`, which tries to claim the **same key** and is refused); `commands/commands.py:212-218` (`api_key` is set precisely when a log leg exists, i.e. exactly the dual-leg case).
- **Scenario:** any `select_job` under the shipped `selected_job_confirm_source="hybrid"` (profiles.py:111). The race starts the API leg inside the single-flight worker; every `get_jobs` readback inside the leg spins on `_claim_api_read` for its full 2.0s timeout and returns `None`; `_reading_value_after(None, …)` → `None`; the leg polls uselessly until its own 5s timeout.
- **Verified:** runtime reproduction on this tree — inside the race the raw `api_reader.get_jobs` was called **0 times** and the race failed at budget; the identical leg run outside the race succeeded immediately (`race result success=False … raw_api_reader_calls=0` / `control (no race) success: True`). No unit test catches this: `test_confirmation_race.py` uses synthetic lambdas that never touch the router, and `test_select_job_confirm.py` tests the legs outside the race.
- **Consequence:** the API leg of the deployed default policy is structurally dead. On the real scope (log leg measured fast) the race still confirms via the log, so the defect is masked; on the simulator — where the profile's own rationale says "log-only is insufficient" (profiles.py:108-110) — hybrid `select_job` can **never confirm**: 3 confirm attempts, 2 futile re-fires, ~15s wasted, and every result is `success=True, confirmed=False`. Any environment where the log leg degrades (rotated/stalled log, non-default install path, CF-04 clock step) silently loses its only working confirmation source. The "confirmed by api leg" outcome and its disagreement warnings (confirmations.py:185-204) are unreachable code in production.
- **Fix:** the leg must *own* the claim it runs under, not contend with it. Options: (1) run the API leg on the caller thread (the race already has the log leg on a worker; the caller is otherwise just sleeping) and pass `api_key` only to guard against *external* in-flight reads before starting; (2) make the claim ownership-aware (store the claiming thread id; `_claim_api_read` succeeds re-entrantly for the owner); (3) have `confirm_select_job` bypass the router cap (call `api_reader.get_jobs` directly) when executing inside the race worker, since the worker's claim already provides the single-flight guarantee. Add a regression test whose API leg reads through the router (the exact shape of the repro above).

---

### CF-02 — **High** — `check_idle(timeout=None)` on every hardware profile: a LASX hang/crash before the fire is a permanent driver hang

- **Files:** `commands/prechecks.py:50-76` (`while True`, `timeout=None` documented as "wait indefinitely"; `None`/`"Unknown"` status treated as not idle); `config/profiles.py:311, 407, 417, 430, 450` (OBJECTIVE, MOVE_XY, MOVE_Z, ACQUIRE, SELECT_JOB all ship `partial(check_idle, timeout=None)`); `commands/dispatch.py:654-656` (the same unbounded pre-check re-runs in the correction path of every confirm attempt).
- **Scenario:** LASX crashes or its CAM channel hangs while (or just before) any move/acquire/select is dispatched. `get_scan_status(client, mode="api")` fails closed to `None` → `"Unknown"` → not idle → loop, forever, at ~2s (read timeout) + 0.05s per iteration. Same loop if an acquisition is aborted in a state where LASX never reports idle again.
- **Verified:** runtime reproduction — `check_idle(timeout=None)` against a client whose every attribute access raises did not return within the watchdog window (`returned within 4s against dead LASX: False`); by code inspection the loop has no other exit.
- **Consequence:** deadlock of the calling workflow under a realistic failure. Because it happens *inside* a command, the caller cannot distinguish "waiting for a long scan" from "LASX is gone" — the heartbeat log line is the only sign of life, and it reports "Waiting for idle: Unknown" forever. Prior review LC-02 flagged this pre-check as unbounded only for its evidence-window side effect; the hang itself was unflagged.
- **Fix:** two independent knobs. (1) Give the profiles a finite default (e.g. 600s — longer than any legitimate scan wait the operators expect) so the wrapper returns a structured pre-check failure instead of hanging. (2) Track *unreadable* status separately inside `check_idle`: N consecutive `None`/`"Unknown"` reads (say 10 ≈ 20s) is evidence the peer is gone, not busy — return `{"success": False, "reason": "status_unreadable"}` regardless of `timeout`. Callers already handle pre-check failure (dispatch.py:256-268).

---

### CF-03 — **High** — `confirm_acquire` with `poll_timeout=None` loops forever after `saw_scanning` when LASX dies mid-scan

- **Files:** `commands/confirmations.py:1094-1159` (`deadline = t_start + 1e9` when `timeout is None`; the `status is None or "Unknown"` branch resets the idle streak and continues; the phase-1 `_check_api_error`/start-timeout block is guarded by `if not saw_scanning:`); `config/profiles.py:442` (`poll_timeout=None` shipped).
- **Scenario:** acquisition starts (phase 2 armed), then LASX crashes or the CAM channel wedges. Every status read is `None` → the loop can neither complete (`consecutive_idle` never reaches 2) nor error out (phase-1 checks skipped) nor time out (deadline is ~31 years). The heartbeat logs "Scanning: Unknown" indefinitely.
- **Consequence:** permanent hang of `acquire()` — and therefore of `zmart_adapter.acquire` and the controller `Session.acquire` above it — under the single most realistic failure for a multi-hour acquisition. Note the asymmetry: the same fail-closed status handling that correctly prevents false completion (credited in the prior review) is what converts a dead peer into an infinite wait once combined with an unbounded deadline.
- **Fix:** keep `timeout=None` for legitimate long scans, but add a liveness bound: abort with a distinct failure (`"scan status unreadable for {N}s — LAS X may have crashed"`) after N consecutive unreadable reads in phase 2 (mirror of CF-02's fix; the constant belongs in the ACQUIRE profile). `save()`'s freshness gate already protects against acting on the aborted result.

---

### CF-04 — **Medium** — The confirmation happens-before model is anchored on non-monotonic wall clocks; a clock step can make stale evidence admissible (or reject genuine evidence)

- **Files:** `commands/commands.py:1438` and `commands/dispatch.py:521` (`command_started_at = time.time()`); `readers/log_wait.py:139-145` (`selected_ts > command_started_at`, `current_block_ts > command_started_at` — LCS-stamped epochs vs. Python wall clock); `readers/router.py:67` (`observed_at = time.time()`); `commands/confirmations.py:1010, 1087` (`observed_after = time.time()` gates in `confirm_move_xy`/`confirm_acquire`); `commands/confirm_select_job.py:98`.
- **Scenario:** Windows time service steps the clock (routine on lab PCs; the machine is the same for driver and LCS.exe, so *skew* is not the issue — *steps* are). A backward step between a pre-fire `CurrentBlock` event and the `select_job` window opening makes that pre-fire event's timestamp exceed `command_started_at` → the log leg confirms a selection the command did not cause — the same class of false confirm as LC-02, via a different door, and with the freshness backstop off by default (`selected_job_log_cluster_max_age_s=None`, profiles.py:117). A forward step makes *all* genuine post-fire evidence "pre-command" → every confirmation spuriously times out for the step duration (log leg reports `selected_before_command`). The `observed_after` gates have the same failure shape internally (both ends are `time.time()`, so only a step *between* capture and read completion matters — narrower, but the gates guard A→B→A moves where a false accept means "confirmed at the wrong position").
- **Consequence:** wrong confirm or systematic unconfirmed during clock adjustments — rare, but the log leg's entire value proposition is its admissibility reasoning, and that reasoning currently assumes a monotonic wall clock, which Windows does not provide. Note all *deadlines* in the package correctly use monotonic clocks (verified — see walkthrough); it is only these cross-domain anchors that cannot avoid wall clock, and they currently do so without any sanity bound.
- **Fix:** (1) give `selected_job_log_cluster_max_age_s` a finite default (also LC-02's ask) so an admissible event must additionally be *recent* — this collapses the exploitable window of a backward step to a few seconds; (2) capture `time.time()` and `time.monotonic()` together at command start, and when evaluating evidence, discard the wall-clock anchor if `time.time() - command_started_at` disagrees with the monotonic elapsed by more than the freshness gate (a 5-line skew detector); (3) log a warning when evidence is rejected as pre-command by less than ~1s, which is the observable signature of a forward step.

---

### CF-05 — **Medium** — The abandoned race API leg outlives the budget, blanks the next attempt's API leg, and (once CF-01 is fixed) reads the CAM concurrently with the correction re-fire

- **Files:** `commands/confirm_select_job.py:206-211` (`budget_s = min(6.0, timeout)` with SELECT_JOB `poll_timeout=5.0` → budget 5.0 while the API leg's own poll window is *also* 5.0 — the leg systematically outlives the race that abandoned it, plus up to one more in-flight 2s read); `readers/router.py:95-105` (claim held until the leg returns); `commands/dispatch.py:653-680` (the correction path re-fires immediately after the race returns); `commands/confirmations.py:129-134` (next attempt's race finds the claim held → API leg skipped).
- **Scenario (today, verified):** attempt 1's race expires at 5.0s; the leg worker keeps the claim for up to ~2s more (runtime-verified: claim still held at budget expiry, released only when the leg ends). Attempt 2 and often attempt 3 therefore run **log-only** even after CF-01 is fixed — the "api leg skipped: api read in flight" branch, designed for *external* readers, is triggered by the race's own leftovers. The correction path's `check_idle` also runs against the held claim (status reads → `None` → treated as not idle) until the leg dies.
- **Scenario (after CF-01 fix):** an abandoned leg that is actively polling `get_jobs` (flush-fire-poll writes to `PyApiCommand.Model.Command`, api_reader.py:254-256) runs concurrently with the main thread's re-fire (echo flush + `UpdateAwaitReceipt`) — the driver's own machinery violates the single-writer convention dispatch.py:20-24 declares, with the uncorrelated-response consequences LC-09 describes.
- **Fix:** make the leg's poll window strictly smaller than the budget (e.g. `budget_s - 0.5`) so an abandoned leg drains before the next attempt; better, pass the race's deadline into the leg (a `threading.Event` or absolute monotonic deadline argument) so abandonment is cooperative rather than nominal. Before a correction re-fire, wait (bounded) for the claim to clear.

---

### CF-06 — **Medium** — No CAM client teardown exists anywhere: reconnect cycles leak live connections, and double-connect behavior under the same client name is unverified

- **Files:** `zmart_adapter/zmart_adapter.py:363-365` (`disconnect` = flag only; "the CAM client itself has no teardown"); `connection/session.py:70-84` (`connect_python_client` — a client that connects but fails the follow-up ping is abandoned *connected*; no `Disconnect` exists in the package, grep-verified); `connection/lasx_runtime.py:55-60` (every connect re-runs `Assembly.LoadFile` + `Activator.CreateInstance` — a fresh client object per call); `zmart_controller/__init__.py:52-57` (the swap that invokes all of this; ZC-01).
- **Scenario:** the documented workflow `set_instrument(a); set_instrument(a)` (retry after an error, notebook re-run) or the ZC-01 multi-scope pattern. Old client: still connected, forever. New client: `Connect("PythonClient")` with the *same* name (CONNECTION dict, zmart_adapter.py:94). If LASX enforces unique client names, the second connect returns `False` → `ConnectionError` → **reconnection is impossible without restarting Python**, which materially changes the (b)/(f) recovery story: after a LASX crash+restart, the driver-side prescription is undefined. If LASX allows duplicates, each cycle accumulates a registered client and its socket.
- **Consequence:** resource leak at best; a dead-end recovery path at worst. Either way the behavior is currently unknown, on the axis (reconnect after failure) where this system most needs a defined answer.
- **Fix:** probe the connector surface for a disconnect (`client.Disconnect()` / `Dispose()`) and call it from `zmart_adapter.disconnect` and from the `connect_python_client` ping-failure path; if none exists, cache one process-lifetime client per `(runtime_root, client_name)` in `connection/` and hand it to every session (making reconnect a re-`Connect` of the same object), and document the LASX-crash recovery procedure explicitly. Add a hardware validator step that performs connect→disconnect→connect.

---

### CF-07 — **Medium** — Live LAS X template `.lrp` rewritten in place, non-atomically, at two sites; a kill mid-write corrupts the file LAS X loads next

- **Files:** `scanfields/transaction.py:89` (`reorder_jobs`: `lrp_path.write_text(prolog + …)` directly onto the live template); `experimental/lrp_edits/_primitives.py:84, 170` (same pattern for every LRP attribute edit). Contrast with the correct patterns already in this codebase: `strip_restore.py:200-205` (tmp + `Path.replace`), `acquisition/materialize.py:131-134` (unique tmp + `os.replace` with a comment explaining why), `config/machine.py:242-246`.
- **Scenario:** failure mode (d) — driver process killed (or disk-full/OSError) between truncate and completion of `write_text` during `apply_lrp_change` (which runs under `move_galvo_to_pixel` and the LRP edit workflows). The on-disk `.lrp` is truncated mid-XML. `apply_lrp_change`'s next step is `load_experiment` of exactly that template (transaction.py:159); after a kill, the *operator's* next template load in the GUI hits it instead.
- **Consequence:** a corrupt vendor template file — the artifact the transaction docstring already identifies as unprotected ("There is no rollback…", transaction.py:126-128), made worse because a *torn* file (unlike a logically-wrong one) may fail to load at all, and there is no `.bak` at these two sites (unlike `restore_template`).
- **Fix:** mechanical — write to a sibling tmp and `os.replace`, at both sites (three lines each; the codebase has the pattern to copy). `[PATCHWORK]`-adjacent note: this is the third distinct file-write idiom in the package; consider one shared `atomic_write_text()` in `_file_utils.py`.

---

### CF-08 — **Medium** — Single-flight command dispatch is enforced nowhere: concurrent ops trample the shared echo and race `used_p`/`origin`

- **Files:** `commands/dispatch.py:20-24` (the convention, stated); `zmart_controller/layer.py:23-174` (`Session` — no lock, no owner-thread check); `zmart_adapter/zmart_adapter.py:695-702` (`_assign_p_slot`: check-then-add on `handle.used_p`), 444-489 (`set_origin` mutates `handle.origin` non-atomically across a CAM snapshot + file write); `commands/dispatch.py:297-302` + 128-168 (the echo flush/settle pair that concurrent fires corrupt).
- **Scenario:** failure mode (e). The controller README targets "humans and AI agents alike" driving sessions from notebooks; a watchdog thread, a UI callback, or an agent framework calling `Session.acquire()` while a `set_xyz()` is confirming is the natural first misuse. Thread B's echo flush erases what thread A's `_await_echo_result` is waiting on → A reports B's outcome or a spurious settle-timeout; B's error is attributed to A or lost. Two concurrent `acquire()` calls can compute the same `p` slot → `save()` upserts one dataset over the other (silent product loss). Note the asymmetry that invites the mistake: *reads* are single-flight capped and hang-proofed (router), so the API surface feels concurrency-safe.
- **Consequence:** cross-attributed errors and silent data overwrite under a plausible integration pattern; currently prevented only by a comment two layers below the public surface. (ZC-08 flagged the controller globals; this finding is about the per-session op path and the driver's own shared CAM state.)
- **Fix:** one `threading.RLock` on `ZmartHandle`, taken by every adapter op (a 12-line decorator) — serializing at the ops boundary preserves all internal timing assumptions. Alternatively (cheaper, honest): record the owning thread id at connect and raise on use from another thread. Either way, promote dispatch.py's comment into an enforced contract and state it in the controller README.

---

### CF-09 — **Low** — Log-leg worker threads have no I/O bound: a stalled filesystem leaks one thread per confirm attempt

- **Files:** `commands/confirmations.py:114-124` (log leg thread; `log_wait` bounds its *polling*, but each `parse_log()` inside it does unbounded blocking file I/O — log_reader.py:108-114); `readers/router.py:285-288` (`_log_rescue_concurrent`'s log thread, same shape, currently unreachable — LC-11).
- **Scenario:** the LAS X log lives on a path that can stall (ProgramData is normally local, but the profile makes the path configurable — profiles.py:66-67 — and lab setups do point these at shares). An `open()`/`read()` that blocks parks the daemon thread past every deadline; the race correctly times out (fail-closed), but each of up to 3 confirm attempts per select_job leaks one thread for the stall's duration, plus one 4 MiB buffer each.
- **Consequence:** bounded-rate thread/memory leak during exactly the incident (storage stall) that already degrades everything else; diagnostic confusion ("why are there 40 lasx-confirm-log threads?"). Same family as LS-27.
- **Fix:** low priority. Reuse a single long-lived log-poller thread per process (queue in requests, monotonic-deadline responses) instead of thread-per-attempt; or accept and document, mirroring the api-leg abandonment note in the `race_confirmations` docstring (confirmations.py:73-76), which currently mentions only the CAM leg.

---

### CF-10 — **Low** — `motion.limits._stage_limits` is a process-global mutated without a lock, shared across sessions

- **Files:** `motion/limits.py:26-51` (module dict, `update()` at connect); `zmart_adapter/zmart_adapter.py:275` (written per `connect()`); `commands/commands.py:1080, motion checks` (read per move).
- **Scenario:** unusual timing — a reconnect (`_configure_stage_limits`) concurrent with a move on the old session: `dict.update` sets keys one at a time, so `_check_xy_limits` can read a mixed old/new envelope; also two handles in one process share one envelope by construction (fine today with one Leica, latent if a second machine profile ever lands).
- **Consequence:** a limit check against a torn envelope — the failure the check exists to prevent, though it requires concurrent connect+move (already outlawed by CF-08's fix) and both envelopes to be wrong in the same direction to matter physically.
- **Fix:** replace the eight-key update with a single atomic rebind (`_stage_limits = new_dict` behind a module function), or hang the envelope off `ZmartHandle`/pass it explicitly (better layering anyway). One-line docstring note that the state is per-process, not per-session.

---

### CF-11 — **Low** — `write_origin` uses a fixed tmp filename; concurrent writers clobber each other's staging file

- **Files:** `config/machine.py:242-245` (`tmp = path.with_suffix(".json.tmp")` — fixed name; contrast materialize.py:131-134, which documents why fixed tmp names are unsafe and uses pid+uuid).
- **Scenario:** two `set_origin` calls racing (requires CF-08's missing lock to be absent, plus two sessions or threads) interleave `_write_json(tmp)`/`os.replace` → one origin write silently contains the other's payload half, or one `os.replace` fails on a vanished tmp.
- **Consequence:** worst case a torn/mixed `origin.json` — but `_write_json` to the tmp is complete before either replace, so the realistic bad outcome is "last writer wins with a confusing intermediate", not corruption. Kept as hygiene because the same repo already documents the correct idiom.
- **Fix:** reuse materialize's unique-suffix helper (or add `os.getpid()` to the name). Optionally `fsync` before replace for kill-during-flush durability (the current code can lose the *new* origin on power loss, never the old one — acceptable, worth a comment).

---

### CF-12 — **Low** — `select_job`'s docstring denies the pre-check that its profile ships — on the exact line LC-02/CF-02 need changed

- **Files:** `commands/commands.py:1413-1415` ("No pre_check_fn (job switching doesn't need scanner idle)") vs. `config/profiles.py:450` (`SELECT_JOB = CommandProfile(pre_check_fn=partial(check_idle, timeout=None), …)`).
- **Consequence:** a maintainer acting on the docstring will conclude LC-02's "window opens before the unbounded idle pre-check" cannot apply to select_job and mis-scope the fix; the drift is between the two files that must be edited together.
- **Fix:** correct the docstring (and state *why* select_job waits for idle, since the original rationale evidently changed).

---

### CF-13 — **Low** — `_capped_api_read` busy-polls for the in-flight slot at 5 ms with no backoff, and slot-timeout loses diagnostics

- **Files:** `readers/router.py:117-129` (slot wait: `time.sleep(0.005)` + re-claim attempt in a loop for up to `timeout_s`; on failure, bare `None` — the diagnostics half is LC-19, confirmed).
- **Scenario:** during a hung CAM call every routed read burns ~400 claim attempts/2s spin before failing; several callers (check_idle loop, confirm polls) multiply this. Purely a CPU/pressure hygiene point — correctness is fine (deadline is monotonic).
- **Fix:** exponential backoff to ~50 ms, or a `threading.Condition` signaled by `_release_api_read`. Fold in LC-19's error-carrying `Reading` on timeout while touching it.

---

### CF-14 — **Low** — No `atexit`/signal handling: interpreter exit abandons daemon threads mid-CAM-call, and nothing records an in-flight command

- **Files:** package-wide (grep-verified: no `atexit`, no `signal` in production code); `readers/router.py:105` etc. (daemon threads); `config/profiles.py:406-414` (`fire_async` moves — fire-and-forget by design).
- **Scenario:** failure mode (d)'s software half. On `SIGTERM`/kernel kill nothing can run anyway; on *clean* interpreter exit (notebook restart), daemon threads are killed inside pythonnet interop calls — historically a source of crash-on-exit noise (`.NET` callbacks into a finalizing interpreter). No journal records "a move to (x, y) was in flight", so post-mortem reconstruction relies on the LAS X log alone.
- **Consequence:** cosmetic-to-annoying; the physical recovery story is sound without it (absolute moves complete in hardware, origin persisted atomically). Listed for completeness of the audit item; not worth machinery beyond:
- **Fix (optional):** an `atexit` hook that logs any held `_API_IN_FLIGHT` claims (evidence of a hung CAM call at exit) — 5 lines, pure diagnostics. `[YAGNI]` beyond that: do not build a move journal; nothing needs it.

---

### CF-15 — **Medium** — The fire pipeline's raw CAM property accesses run unbounded on the caller thread; the hang-proofing covers only router reads

- **Files:** `commands/dispatch.py:297-302` (echo flush: three property writes), `dispatch.py:153-158` (`_await_echo_result`: property reads per 10 ms iteration — the monotonic deadline is only consulted *between* reads), `commands/errors.py:126-139` (`_check_api_error`: direct echo reads), `commands/confirmations.py:1120` (`confirm_acquire` phase 1 calls `_check_api_error` outside the cap), `readers/api_reader.py:66-80` (`ping`, used at connect, uncapped); versus `readers/router.py:109-129` (the capped path, whose docstring says "a hung CAM call (modal dialog) parks in the daemon worker instead of blocking the caller forever").
- **Scenario:** failure mode (a). The package's own read-side design asserts CAM calls can block indefinitely behind a modal dialog (log_reader.py:5-7 exists *because* of this). If model property access blocks the same way (the capped functions being protected are themselves mostly property reads/writes, e.g. api_reader.py:98-119 — so the design implies it can), then the flush or settle poll hangs the command thread with no deadline, and the dialog diagnostic that would explain the hang (dispatch.py:66-81) never runs because it only runs on *completed* failures.
- **Consequence:** an unbounded hang inside `confirm_and_fire` on the one failure the codebase most explicitly models. Uncertainty is acknowledged: if echo model reads are client-side memory (never blocking), only `UpdateAwaitReceipt`'s Leica-side timeout matters and this reduces to Low. The evidence in-tree points both ways, and nothing pins it.
- **Fix:** first, *measure*: add a hardware-validator step that opens the manual-turret dialog and records which of {property read, property write, UpdateAwaitReceipt} block (the validators already exist for reader comparisons). If property access can block, route the echo flush/settle/check through the same capped-worker pattern as reads (they are on the command channel, so the claim key must differ from the read key), or wrap the fire step in a bounded worker like `_read_job_settings_bounded`. Document the answer either way in dispatch.py's concurrency note.

---

### Confirmed prior findings (verified in this audit, not re-numbered)

- **LC-02** (select_job evidence window opens before the unbounded pre-check; freshness backstop off by default) — confirmed at commands.py:1438, profiles.py:117/450, log_wait.py:139-145. CF-02 adds the hang dimension, CF-04 the clock-step dimension, CF-12 the doc drift on the same lines.
- **LC-03/LC-14** (silently-failed echo `Result` flush; no direct echo tests) — confirmed at dispatch.py:299-302; CF-15 extends the same code region's failure envelope.
- **LC-04** (correction path ignores a failed idle re-check) — confirmed at dispatch.py:653-666.
- **LC-09** (uncorrelated flush-fire-poll responses in `get_xy`/`get_jobs`/`get_hardware_info`) — confirmed; noted here as the mechanism by which the `observed_after` gates (confirmations.py:1010) can pass a stale value in A→B→A patterns (`correct_backlash` is A→B→A by construction, movement.py:143-149).
- **LC-19** (router timeout returns bare `None`) — confirmed at router.py:229-231; folded into CF-13's touchpoint.
- **LC-20** (race misreports a late-confirming loser) — confirmed at confirmations.py:195-198.
- **ZC-01/ZC-03/ZC-08** (module swap disconnects previous session; post-disconnect safety mock-owned; unstated single-thread assumption) — confirmed; CF-06 and CF-08 supply the driver-side halves.
- **LS-27** (bounded settings read leaks a thread and swallows the worker error) — confirmed at ome_canonical.py:378-385; CF-09 is the same disease at two more sites.

---

## 5. Summary table

| ID | Severity | Title |
|-------|----------|-------|
| CF-01 | High | Hybrid race API leg self-blocks on its own in-flight claim — never performs a CAM read (verified; select_job hybrid is log-only in practice) |
| CF-02 | High | `check_idle(timeout=None)` on every hardware profile → permanent hang when LASX hangs/crashes pre-fire (verified) |
| CF-03 | High | `confirm_acquire` `poll_timeout=None` + fail-closed status → infinite loop when LASX dies mid-scan |
| CF-04 | Medium | Wall-clock anchors (`command_started_at`, `observed_at`, log epochs) break the happens-before model under clock steps; false confirm possible with the freshness backstop off |
| CF-05 | Medium | Abandoned race leg outlives the budget: next attempts' API leg skipped by leftover claim; concurrent CAM access with the re-fire once CF-01 is fixed (verified claim lifetime) |
| CF-06 | Medium | No CAM teardown anywhere: flag-only disconnect, connection leak per reconnect, double-connect under one client name unverified |
| CF-07 | Medium | `reorder_jobs` + `_primitives` rewrite the live `.lrp` in place non-atomically — kill mid-write corrupts the template LAS X loads next |
| CF-08 | Medium | Single-flight dispatch is convention only: echo trample, `used_p` race → silent product overwrite under concurrent ops |
| CF-15 | Medium | Fire-pipeline CAM property accesses unbounded on the caller thread; hang-proofing covers router reads only (needs one hardware measurement) |
| CF-09 | Low | Log-leg worker threads have no I/O bound; one leaked thread per confirm attempt during a filesystem stall |
| CF-10 | Low | `_stage_limits` process-global, lock-free, torn-update possible; shared across handles |
| CF-11 | Low | `write_origin` fixed tmp filename (repo elsewhere documents why that is unsafe); no fsync before replace |
| CF-12 | Low | `select_job` docstring denies the idle pre-check its profile ships — on the LC-02/CF-02 fix site |
| CF-13 | Low | `_capped_api_read` 5 ms busy-poll for the slot, no backoff (plus LC-19's lost diagnostics) |
| CF-14 | Low | No atexit/signal handling; daemon threads abandoned mid-interop on exit; held claims never reported **[YAGNI beyond a log hook]** |

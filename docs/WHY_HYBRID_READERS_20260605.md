# Why We Need Hybrid Readers

Date: 2026-06-05
Status: design rationale / proposal
Grounding: all numbers below are measured on this machine (LAS X 1.0.108.0),
see `SELECTED_JOB_LOG_READER_FIX_20260605.md`, `API_VS_LOG_READER_COMPARISON_20260605.md`,
`SESSION_SUMMARY_20260605.md`.

## 1. Executive summary

A single state-reader backend is wrong somewhere, no matter which one you pick:

- **API-only** is fast and fresh for actively-queried state, but it is
  *persistently stale/wrong for selected-job* on this LAS X version, and it can
  *hang or time out* (modal dialogs, transport hiccups, observed `get_jobs`
  timing out 3/3).
- **Log-only** never hangs (it is a file read) and is the fast, correct source
  for *event confirmation* (a job switch is reflected in ~0.2 s), but it is
  *empty on an idle scope* (freshness gates) and *cannot be polled to freshness*
  for passive reads (a settled stage emits no new lines).

The two backends fail in **opposite** places. So the right reader is not "API"
or "log" - it is a **hybrid** that runs both **concurrently** and takes the
**first trustworthy answer**, i.e. the readers *compete to be the first to notice
the committed change*. The loser is cancelled. If neither can vouch for a fresh
answer, the hybrid returns "unknown" (fail closed) rather than a stale guess.

## 2. The evidence (why single-source fails)

Measured this session:

| Datum | API | Log | Who is correct |
|---|---|---|---|
| XY position | fresh, ~12 ms, exact | empty when idle; cannot poll to fresh | **API** |
| scan status / hardware info | fresh, fast | empty when idle (stale, gated) | **API** |
| job settings | correct (self-freshens the log) | matches API when fresh | either |
| job list | correct | full list **when fresh**, else gated `[]` | API (log when fresh) |
| **selected job after a switch** | **stale 15 s+, returns previous job** | **fresh ~0.2 s, correct** | **Log** |
| any read while API is hung | **times out (15 s) / returns nothing** | **still answers from the file** | **Log** |
| both stale | possibly stale | `None` (fail closed) | **neither -> "unknown"** |

Two hard measurements anchor the case:

- **Selected-job, API is wrong:** a switch confirmed in the log/UI in ~0.13 s
  never converged in the API readback over **60 s**. Full validator: API-confirm
  job switches **time out 15 s and report the wrong job** (4 FAIL); log-confirm
  switches **pass in ~0.17 s**. Per 3-switch cycle: API 30.3 s (6 wrong) vs Log
  2.4 s (0 wrong).
- **Passive XY, log cannot be forced fresh:** moving the stage and reading back,
  log returned the exact position when fresh (`tries=1`, ~330 ms) but `None` when
  the line aged past the 1.0 s gate - and polling **8 s / 21 re-reads did not
  recover it**, because nothing re-queries a settled stage.

Neither column is safe as a blanket default. That is the whole argument.

## 3. The core idea: concurrent readers racing to notice the change

Run the API reader and the log reader **at the same time** for the same datum.
Whichever first produces a **trustworthy** observation wins; the other is
cancelled. This is the user's framing - the readers *compete to be the first to
notice the committed change*.

Why a race rather than a fixed primary + fallback:

- **You never pre-commit to the wrong source.** A fixed "API, else log" loses
  15 s every selected-job switch before failing over. A race pays only
  `min(api_latency, log_latency)`.
- **It auto-adapts per situation without a policy lookup.** For XY the API wins
  the race (~12 ms) and you never wait on log. For selected-job the log wins
  (~0.2 s) and you never wait on the API that would never answer.
- **It is hang-immune for free.** If the API blocks (dialog/transport), the log
  thread still wins; if the log is stale, the API thread still wins. A single
  source has no such safety net.

### What "notice the change" means precisely (confirmation)

For a **confirmation** (did the state become TARGET after a command?), both
readers poll concurrently for the *same predicate*: "selected == TARGET, observed
**after** `command_started_at`." The first thread to see that predicate true
returns success; identity is unambiguous because both are checking for the same
TARGET, so a disagreement cannot produce a wrong confirmation - at worst one
source simply never fires and the other wins. This is the strongest case for the
race and exactly where log already beats API by ~75x.

### What it means for passive reads (no target)

For a **passive read** (what is the value now?) there is no TARGET predicate, so
the race rule is "first source that returns a value it can **vouch for as fresh**
wins." In practice the API wins for actively-queried state (it is fresh by
construction), and the log only wins when the API is hung. On disagreement, a
per-datum tiebreak decides (Section 5).

## 4. The freshness arbiter (trust, not just speed)

"First answer" is not enough - it must be the first *trustworthy* answer. Each
backend must be able to **prove freshness**, and the hybrid trusts only proven
freshness:

- **Log** proves freshness with the **log-line timestamp**: a value is
  trustworthy only if its line is newer than the command (for confirmation) or
  within the freshness gate (for passive reads). This is why the log fails closed
  to `None` instead of returning a stale value - a property the hybrid keeps.
- **API** proves freshness by **responding without hanging**: an API value is
  current *if the call returned*. The failure mode is not staleness but *not
  returning* (hang/timeout) - which the race handles by letting log win.

The arbiter therefore never returns a value no backend can vouch for. That is the
fail-closed guarantee.

## 5. Conflict resolution (when both answer and disagree)

Disagreement is only possible for passive reads (confirmation checks a single
TARGET). When both return a value and they differ, resolve by **per-datum
source-of-truth**, derived from Section 2:

- **selected job:** trust **log** (`CurrentBlock`). The API readback is the known
  stale one. (This is the `API lag` case we logged repeatedly.)
- **XY / scan status / hardware info:** trust **API**. It is actively queried and
  fresh; the log is only an echo.
- **job list / settings:** trust whichever is fresh; they agree when both fresh.

Critically, the hybrid should **report** the conflict (telemetry), not hide it -
those `API lag` events are exactly the signal that the API readback is drifting
and worth a vendor note.

## 6. Fail-closed

If, within the time budget, neither backend produces a value it can vouch for,
return **"unknown"** - never a stale or guessed value. Downstream command gates
must treat "unknown" as "do not fire / re-read," never as a real state. This
preserves the safety property the log reader already has and the API reader lacks
(the API will happily hand back a confidently-wrong selected job).

## 7. Per-datum policy (the table that drives the hybrid)

| Datum | Race primary (usually wins) | Rescue / tiebreak | Notes |
|---|---|---|---|
| `get_xy` | API (~12 ms) | log if API hung | log can't be polled fresh; API authoritative |
| `get_scan_status` | API | log if API hung | gate 0.5 s, log empty when idle |
| `get_hardware_info` | API | log if API hung | static-ish; API fine |
| `get_jobs` | API | **log** if API hung/timeout | we saw API time out; log had full list |
| `get_job_settings` | API | log (self-freshens) | both agree when fresh |
| `get_selected_job` | **log** (`CurrentBlock`) | API cross-check only | **API is stale here** |
| job-switch confirm | **race both** | first to see TARGET wins | log ~0.2 s, API ~never |

## 8. What already exists vs what the hybrid adds

- **Exists:** `state_readers.router` has `mode="both"` -
  `_log_rescue_concurrent(api_fn, log_fn, ...)` already runs API and log
  concurrently with a log grace window. This is the **race primitive**.
- **Missing (the hybrid):**
  1. **Per-datum source-of-truth + conflict resolution** (Section 5/7) instead of
     a naive "trust API, rescue with log."
  2. **Confirmation-as-race** wired into command confirmation so selected-job
     switches race API vs log and take the winner (today it is one source via
     `--select-job-confirm-source`).
  3. **Freshness as a first-class trust signal** (Section 4), uniform across
     backends.
  4. **Conflict telemetry** (surface `API lag`, don't bury it).

So the hybrid is not a rewrite - it is `both` mode promoted from "fallback" to a
principled, per-datum, race-with-arbiter reader, using the policy this session
measured.

## 9. Risks and caveats

- **Double work:** every read runs two backends. Cheap for API (~12 ms); the log
  parse is ~320 ms (full-file). Mitigation: only race where it pays (confirmation
  and hang-prone reads); for plainly API-authoritative reads (XY) keep API
  primary and only spin up log on a hang/timeout, not every call.
- **Log parse cost:** re-parsing a multi-MB file per poll is the log's real cost.
  A tail/incremental parser would make the log cheap enough to race everywhere.
- **False-confirm guard:** the "observed after `command_started_at`" gate must
  stay - without it a race could confirm on a pre-command log line (we saw a
  -74 s stale `CurrentBlock` match once when state leaked across runs).
- **Objective-changing switches:** the confirm window must exceed the physical
  turret/parfocal time (seconds), not just the same-objective ~0.2 s. Size the
  race/confirm timeout accordingly (open item).

## 10. Next steps

1. Lock the per-datum source-of-truth table (Section 7) as the policy contract.
2. Extend `_log_rescue_concurrent` into a `hybrid` mode that consults that table
   and reports conflicts, with fail-closed "unknown".
3. Wire confirmation to race API vs log (selected-job first - biggest win).
4. Add an incremental log tail-parser so racing everywhere is cheap.
5. Re-run the side-by-side and the switch-timing comparison under `hybrid` to
   confirm it is correct in every quadrant of the Section 2 table.
```

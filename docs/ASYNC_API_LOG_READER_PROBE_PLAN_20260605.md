# Async API + Log Reader Race Probe Plan

Date: 2026-06-05
Branch context: `defaults/native-autosave-log`
Status: proof-of-principle plan only; do not wire into production driver yet

## Review Request

This document is intended to be readable without further conversation context.

Please review the plan critically for whether it is the simplest robust way to
test an async API + log-reader race without breaking the working driver. Focus
on:

- whether the probe is isolated enough from production code;
- whether the concurrency model is safe around the fragile Leica CAM API
  channel;
- whether `UpdateAsync() + model polling` is a reasonable thing to test;
- whether the stop rules are strict enough to prevent a wrong confirmation from
  becoming production behavior;
- whether the selected-job and XY examples correctly cover both sides of the
  API/log tradeoff;
- whether the plan is overfitted, overengineered, or missing a simpler test.

Do not assume the goal is to replace the current readers immediately. The goal
is only to collect proof-of-principle evidence while preserving the current
working driver.

## Current Driver State / Assumptions

The driver currently has working production paths that should not be broken:

- The LAS X CAM API runtime is loaded from the installed LAS X Program Files
  directory, not from DLLs committed to the repo or copied into the Python env.
- Native LAS X AutoSave is the default export source on this branch.
- The log reader can parse LAS X logs and is used for selected-job evidence.
- Selected-job confirmation from the log was measured to be much faster and more
  correct than the API readback on this microscope.
- Passive readers are still safety-sensitive: command-control reads and
  persisted-artifact reads must not blindly trust stale log values.
- The existing `mode="both"` router is not considered final production hybrid
  behavior; this plan is about testing a cleaner bounded race before changing
  production wiring.

## Goal

Test whether a reader can use the Leica CAM API and LAS X logs together without
letting either one block the whole read path.

The specific idea is:

- fire the API read with `UpdateAsync()` instead of blocking on
  `UpdateAwaitReceipt()`;
- poll the API result model for a short bounded window;
- also poll the log reader during the same overall confirmation window;
- return the first source that produces a trustworthy, fresh answer;
- fail closed when neither source can prove a fresh answer.

This is a proof-of-principle. It must not change existing production reader
behavior until the data proves the approach is safe.

## Non-Goals

- Do not modify `state_readers/api_reader.py`.
- Do not modify `state_readers/router.py`.
- Do not modify `core/commands.py`.
- Do not modify production profiles.
- Do not change default reader behavior.
- Do not replace existing `UpdateAwaitReceipt()` readers.
- Do not make `both` or hybrid the production default.

The current driver works well enough to protect. This experiment must live at
the edge as a hardware probe.

## Why This Probe Exists

The current API readers often follow this pattern:

```text
flush model to sentinel
set PyApiCommand.Model.Command
PyApiCommand.UpdateAwaitReceipt(...)
poll the result model until it changes from the sentinel
```

The concern is that `UpdateAwaitReceipt()` can itself block or stall. If it
blocks inside the main reader loop, then the log reader cannot rescue the read,
because the loop never gets control back.

Using `UpdateAsync()` may give the loop control immediately:

```text
flush model to sentinel
set PyApiCommand.Model.Command
PyApiCommand.UpdateAsync()
poll API model and log snapshots under our own timeout
```

If this works, the reader timeout belongs to our code instead of being partly
hidden inside `UpdateAwaitReceipt()`.

## Current Evidence

### Selected Job

Selected-job confirmation is the strongest case for log involvement.

Measured on this setup:

- API selected-job readback can stay stale for 15 seconds or longer.
- In some runs the API reported the previous job even after the UI/log had
  already switched.
- Log `CurrentBlock/Name` tracked the applied selected job and confirmed switches
  in roughly 0.17-0.7 seconds.
- Full three-switch cycle:
  - API confirmation: about 30 seconds and wrong-state failures.
  - Log confirmation: about 2.4 seconds and no wrong confirmations.

So for job switching, the log is not just a backup; it is closer to the applied
state than the API readback.

### XY Position

XY behaves differently.

Measured with `move_xy_pattern_api_vs_log.py`:

- API XY readback is fast and exact.
- Log XY is exact only when a fresh `GetStageHwPosition` line already exists.
- If the XY log line is older than the freshness gate, polling the log does not
  help.
- One long log-only poll re-read the log for 8 seconds and still returned
  `None`, because no new XY line was written while the stage was settled.

Conclusion: polling the log can only find events that LAS X writes during the
poll window. It cannot create new passive state. For passive XY, the API remains
the primary useful source unless the API is blocked and the log happens to have a
fresh enough echo.

### Job Settings

Job settings often match between API and log when fresh, because the API
settings read triggers the same `ATL_GetBlockApiInfoAsJsonString` dump that the
log parser reads.

But the log only has settings for jobs that were dumped. It can be incomplete.
This makes job settings useful for comparison and rescue only when the relevant
job block is actually present and fresh.

### Passive Reads on an Idle Scope

On an idle scope, strict log readers can return `None` or `[]` because the log
state lines are old and freshness-gated. This is safe fail-closed behavior, not
a parser failure.

## Core Hypothesis

For event-driven reads, especially selected-job confirmation, an async API/log
race may be both faster and more robust than either source alone:

- API can win if it returns quickly and correctly.
- Log can win if the API is stale, slow, or blocked.
- If the log is stale or incomplete, it fails closed and the API can still win.

For passive reads like XY, the result may be different:

- API likely wins most of the time.
- Log only helps if a fresh log line already exists or the API is blocked.
- Polling the log longer does not help unless LAS X writes a new line during the
  poll window.

The probe should measure these differences rather than assume one universal
policy.

## Safety Principles

1. The probe must not call a potentially blocking API reader directly inside the
   main loop.
2. At most one API read may be in flight per client.
3. The probe must not start a new API request every 50 ms blindly.
4. API requests must use sentinel flushing where possible.
5. A value is accepted only after a trustworthy transition:
   - API: result model changed from the sentinel.
   - Log: value is fresh enough, or observed after `command_started_at` for a
     confirmation.
6. Confirmations must match the expected target and be observed after command
   start.
7. A wrong confirmation is a hard failure of the design.
8. Timeout returns unknown/fail-closed, not a guessed state.

## Probe Location

Add one isolated hardware script:

```text
driver/vendor/leica/navigator_expert/tests/hardware/probe_async_api_log_reader_race.py
```

This script may import the driver connection/session helpers and low-level
reader modules, but it must not be imported by production code.

The script should be removable without affecting the driver.

## Reader Mechanics to Compare

For each target datum, compare three read mechanics:

### 1. Current API Reader

Use the existing production reader:

```text
UpdateAwaitReceipt() + poll model
```

This is the baseline.

### 2. Experimental Async API Reader

Use a local implementation inside the probe:

```text
flush model to sentinel
set PyApiCommand.Model.Command
PyApiCommand.UpdateAsync()
poll model until it changes from sentinel or slice timeout expires
```

This must not touch `api_reader.py`.

### 3. Async API + Log Race

Use the async API request plus periodic log snapshots:

```text
deadline = now + timeout
api_in_flight = False

while now < deadline:
    if not api_in_flight and api_probe_due:
        flush API model to sentinel
        fire API command with UpdateAsync()
        api_in_flight = True
        api_started_at = now

    api_value = check_api_model_without_refiring()
    if api_value transitioned from sentinel and is trustworthy:
        return api

    log_value = read_log_snapshot()
    if log_value is fresh/trustworthy:
        return log

    if api_in_flight and now - api_started_at > api_slice_timeout:
        api_in_flight = False
        schedule next API attempt after backoff

    sleep(loop_interval)
```

For selected-job confirmation, the acceptance condition is stricter:

```text
selected_job == target_job
and observed_at > command_started_at
```

## Initial Parameters

Put these in the probe CLI, not production profiles yet:

```text
--loop-interval-s 0.05
--api-slice-timeout-s 0.25
--api-retry-interval-s 0.25
--log-max-age-s 2.0
--selected-timeout-s 20.0
--xy-timeout-s 5.0
--runs 10
```

These are experiment parameters. If the probe succeeds and later becomes
production, then the final tunables should move into `core/profiles.py`.

## Phase 1: Read-Only Baseline

Purpose: confirm that the probe can connect and compare without changing scope
state.

Run against:

- `get_jobs`
- `get_selected_job`
- `get_job_settings` for the selected job
- `get_xy`
- `get_scan_status`

Record for each:

- current API result and latency
- async API result and latency
- log result and latency
- race winner
- value equality
- source disagreements
- whether the log value was stale/absent

This phase should not move the stage, switch jobs, acquire, or save.

## Phase 2: Selected-Job Switch Race

Purpose: test the main use case where the API was measured stale and the log was
measured correct.

For each run:

1. Pick two known jobs, for example `Overview` and `HiRes`.
2. Ensure the starting job is not the target.
3. Record `command_started_at = time.time()` before firing the switch.
4. Fire the job switch.
5. Race async API selected-job read against log selected-job read.
6. Return immediately when either source confirms:

```text
selected.Name == target
observed_at > command_started_at
```

Record:

- target job
- previous job
- winning source
- elapsed time
- API attempts
- log attempts
- last API value
- last log value
- API/log disagreement
- whether API later converged
- timeout reason if no source confirms

Expected based on current evidence:

- log should usually win selected-job confirmation;
- API may remain stale or return the previous job;
- the probe must report this conflict, not hide it.

## Phase 3: XY After Move

Purpose: test the case where API is expected to be better and log polling is
known not to create freshness.

Use a reversible XY pattern with safe limits, similar to
`move_xy_pattern_api_vs_log.py`.

For each move:

1. Move to target position using existing production command path.
2. Race async API XY read against log XY read.
3. Accept only values within the configured tolerance of the move target.

Record:

- target XY
- API value and latency
- log value and age
- winner
- whether log was exact, stale, or absent
- whether polling produced a fresh log value later

Expected based on current evidence:

- API should normally win;
- log may be correct only if a fresh `GetStageHwPosition` line exists;
- longer log polling should not help when no new XY line is written.

This phase is important because it prevents overfitting the design to
selected-job switching. A good hybrid strategy must let API win where API is the
right source.

## Phase 4: Job Settings

Purpose: test the case where API can self-freshen the log.

For each selected or named job:

1. Run current API `get_job_settings`.
2. Run async API `get_job_settings`.
3. Run log `get_job_settings`.
4. Run the race.

Compare key fields:

- `jobName`
- `id`
- `imageSize`
- `pixelSize`
- `format`
- `scanMode`
- objective name

Expected:

- API and log should match when the ATL block was dumped recently.
- Log may fail closed when the job block is absent or stale.
- Async API is only acceptable if it matches current API and does not create
  stale or blank `imageSize` reads.

## Metrics

Each probe row should be JSONL with:

```json
{
  "reader": "selected_job",
  "mode": "race_async_api_log",
  "target": "HiRes",
  "winner": "log",
  "success": true,
  "elapsed_s": 0.21,
  "api_attempts": 1,
  "log_attempts": 4,
  "api_last_value": "Overview",
  "log_last_value": "HiRes",
  "api_error": null,
  "log_age_s": 0.04,
  "conflict": true,
  "message": "log confirmed target; api still stale"
}
```

The summary should report:

- pass/fail count
- timeout count
- wrong-confirmation count
- winner counts by reader
- median / p95 latency by reader and source
- conflict count
- API blocking/timeouts
- log stale/absent count

## Stop Rules

Stop and do not promote the design if:

- any race confirms the wrong selected job;
- any race confirms the wrong XY target;
- async API returns stale data after sentinel flushing;
- async API causes CAM socket/transport instability;
- repeated async calls create overlapping API requests;
- the probe requires production-code changes to work.

Continue only if:

- selected-job race confirms correctly and faster than API;
- XY race lets API win and does not wait unnecessarily on stale log data;
- log failures are fail-closed (`None`/unknown), not wrong values;
- API/log conflicts are reported clearly.

## Interpretation Rules

Do not read one result as universal.

Expected source by datum:

| Datum | Expected best source | Why |
|---|---|---|
| selected job after switch | log | `CurrentBlock` is fresh; API selected-job readback was stale |
| XY after move | API | actively queried and exact; log only has echoes |
| scan status | API | direct status read; log can be stale/unknown |
| hardware info | API | static-ish; API works cold |
| job settings | API or log when fresh | API self-freshens ATL dumps; log can be incomplete |
| job list | API cold, log when fresh | log matrix summary is good when present but age-gated |

The desired outcome is not "log wins everywhere" or "API wins everywhere". The
desired outcome is that the race picks the source that can prove the freshest
correct value for that datum.

## Production Promotion Criteria

Only consider production wiring after the probe proves:

1. The async API reader gives the same values as the current API reader.
2. `UpdateAsync()` does not cause dropped reads or late stale values.
3. The race loop never blocks behind a single source.
4. Selected-job confirmation is correct and faster.
5. XY/passive reads still prefer API naturally.
6. Source conflicts are visible in logs/diagnostics.
7. All new production tunables can live in `core/profiles.py`.

If promoted, do it incrementally:

1. Add internal async API probe helpers behind tests.
2. Add a hybrid mode for selected-job confirmation only.
3. Validate on hardware.
4. Only then consider other readers.

## Open Questions

- Does `UpdateAsync()` reliably dispatch read commands on this LAS X version?
- Does `UpdateAsync()` ever drop commands when the API channel is busy?
- Can late API model updates be distinguished from the current request using
  only sentinel flushing?
- What is the right API slice timeout: 100 ms, 250 ms, or 500 ms?
- Should log parsing be optimized with a tail/incremental parser before racing
  more readers?
- How should conflicts be surfaced to users: warning log, result field, JSONL,
  or all three?

## Bottom Line

This probe tests the concurrency idea without risking the driver.

The current production path remains intact. The experiment asks one focused
question:

Can `UpdateAsync()` plus a bounded API/log race confirm state faster and more
robustly than either source alone, while still failing closed when neither
source can prove freshness?

If yes, the next production target is selected-job confirmation only. If no, the
driver remains on the known working paths.

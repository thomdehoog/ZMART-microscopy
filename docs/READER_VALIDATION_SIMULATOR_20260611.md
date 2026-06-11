# Reader Validation on Simulator - api / log / both + change-wait

Date: 2026-06-11
Branch: `fable5_tryout`
Environment: LAS X simulator (stage quantized to 20 um steps), env
`lasxapi_extended`. Numbers are simulator-specific - see "Interpretation".

## What ran

1. Offline suite: **842 passed, 0 failed** (after fixing two pre-existing
   test fixtures that had not been updated for the `mode=` keyword
   introduced by `94afb45`; see commit log).
2. `validate_hardware.py --yes --allow-xy --allow-z --allow-objective
   --allow-acquire` in all three `--state-reader-mode` values.
3. `probe_change_wait.py --yes --runs 3` - the new alternating API/log
   change-wait reader (`state_readers.change_wait`).

JSONL records live beside the validator
(`validate_hardware_fable5_{api,log,both}_results.jsonl`,
`probe_change_wait_20260611_170356_results.jsonl`; ignored by git).

## Validator results by reader mode

| mode | pass | warn | fail | skip | notes |
|---|---|---|---|---|---|
| api  | 82 | 0 | 0 | 1 | clean baseline; skip = HyD gain not writable |
| log  | 73 | 0 | 3 | 2 | known log gaps, see below |
| both | 80 | 0 | 0 | 2 | survived a transient api `get_xy` 3-attempt failure |

`log` mode failures, all consistent with the previously measured limits of
the log backend:

- `job: resolve` - no jobs returned (the ATL job-cluster is not always
  present in the log window; fails closed, never wrong).
- 2 of 3 select-job log-poll confirms timed out with
  `selected_other_job`: the log *saw an event* 14-24 ms after the command
  but still carried the previous job name. The log lags too - in a
  different pattern than the API (event-flush lag rather than stale
  readback).

`both` mode: one api-leg `get_xy` failed all 3 attempts mid-run; the routed
reader absorbed it (80 pass, 0 fail) - the hang/failure rescue working as
designed.

## Change-wait probe (new reader)

| phase | outcome | winning source | noticed after fire |
|---|---|---|---|
| select_job x3 | 3/3 changed | api | 0.57-0.93 s |
| move_xy x3 | 3/3 changed | api | 33-43 ms |

- Conflicts were *reported, not buried* in 5/6 runs: at win time the other
  source still showed the pre-change value (`sources_agree=false`).
- The stale-log guard fired live (`observed_before_log_boundary`): a days-old
  XY log echo from a previous session could not signal a change.
- XY moves landed 5 um off target (20 um stage quantization) - reported
  via `target_delta`, within the 20 um tolerance, and correctly NOT
  treated as acceptance criteria (tolerance is report-only by design).
- A move refused by stage limits produced `command_success=false` +
  `unconfirmed` with both sources reporting `unchanged` - fail-closed, no
  fabricated change.

## Interpretation - do not generalize winners across environments

The API won every race here, but that is not "the log is slow". The log
saw switch events 14-24 ms after the command (`log_event_delta`) - it
briefly carried the previous job name while the API readback had already
converged on this simulator. Earlier operator testing showed the same
shape from the other side: the log tracked everything very fast and its
hiccups were specifically in the XY readout - passive state, where a
settled stage writes no new lines and the log cannot be polled to
freshness. On the real scope the selected-job picture inverts outright:
the API readback stays stale (wrong job for 15 s+) while the log
CurrentBlock lands in ~0.2 s. Even this simulator run shows the API's lag
flavor: the post-move XY readback returned the previous quantized position
(65520 vs 65525 requested) - "fresh by call-time" is not "true by data".

The change-wait reader is deliberately source-agnostic: API/log disagreement
alone never confirms a change, and the result exposes disagreements instead of
burying them. The safety boundary is:

- a source that keeps reporting its own baseline value cannot confirm a change;
- the API leg has no independent event timestamp, so its baseline is only
  trustworthy after any previous API readback has converged;
- a lagging log line older than the baseline is rejected by timestamp;
- every disagreement is surfaced (`sources_agree`, `last_reasons`,
  per-observation `trace`).

Operator experience on the real scope, for the record: the API's hiccups
concentrate in XY reads and job changes (hangs on modal dialogs, trailing
readbacks, stale selected-job); the log's hiccups concentrate in passive
XY freshness. XY is weak for BOTH sources in opposite ways - which is why
`xy` is a change-wait datum with both legs polled and conflicts reported.

## Follow-ups

- Re-run `probe_change_wait.py` on the real scope; expect the log to win
  selected-job and the API to win XY.
- `log` mode remains unsuitable as a blanket default (job-list resolution
  gap); unchanged conclusion from `WHY_HYBRID_READERS_20260605.md`.

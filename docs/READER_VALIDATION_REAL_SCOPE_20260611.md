# Leica STELLARIS Real-Scope Reader Validation - 2026-06-11

## Run Context

- Date/time: 2026-06-11 18:51-18:57 Europe/Berlin (16:51-16:57 UTC).
- System under test: real Leica STELLARIS microscope through LAS X / LasxApi, not simulator.
- Operator confirmation: scope/sample was confirmed physically safe for XY motion, Z motion, objective changes, and acquisition before the run.
- Repository: `Z:\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy`
- Python: `C:\ProgramData\MinicondaZMB\envs\lasxapi_extended\python.exe`
- No code was changed or committed for this validation. This report and the JSONL output artifacts are the only intended outputs from this session.

## Commands Run

```powershell
& 'C:\ProgramData\MinicondaZMB\envs\lasxapi_extended\python.exe' `
  'Z:\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\driver\vendor\leica\navigator_expert\tests\hardware\probe_four_readers.py' `
  --yes --all-jobs --job-rounds 2 --positions 10 `
  --output 'Z:\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\driver\vendor\leica\navigator_expert\tests\hardware\probe_four_readers_20260611_185038_real_scope.jsonl'

& 'C:\ProgramData\MinicondaZMB\envs\lasxapi_extended\python.exe' `
  'Z:\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\driver\vendor\leica\navigator_expert\tests\hardware\validate_hardware.py' `
  --yes --allow-xy --allow-z --allow-objective --allow-acquire `
  --state-reader-mode api `
  --output 'Z:\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\driver\vendor\leica\navigator_expert\tests\hardware\validate_hardware_20260611_185038_real_scope_api.jsonl'

& 'C:\ProgramData\MinicondaZMB\envs\lasxapi_extended\python.exe' `
  'Z:\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\driver\vendor\leica\navigator_expert\tests\hardware\validate_hardware.py' `
  --yes --allow-xy --allow-z --allow-objective --allow-acquire `
  --state-reader-mode log `
  --output 'Z:\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\driver\vendor\leica\navigator_expert\tests\hardware\validate_hardware_20260611_185038_real_scope_log.jsonl'

& 'C:\ProgramData\MinicondaZMB\envs\lasxapi_extended\python.exe' `
  'Z:\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\driver\vendor\leica\navigator_expert\tests\hardware\validate_hardware.py' `
  --yes --allow-xy --allow-z --allow-objective --allow-acquire `
  --state-reader-mode both `
  --output 'Z:\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\driver\vendor\leica\navigator_expert\tests\hardware\validate_hardware_20260611_185038_real_scope_both.jsonl'
```

All four commands returned exit code 1 because at least one validation check
failed or was unconfirmed. Important correction: these validator runs did not
enable the 2026-06-05 selected-job fix configuration
(`--select-job-confirm-source log`). Therefore `select_job()` was still judged
by the known-stale API selected-job readback, even in the `--state-reader-mode
log` run. The resulting selected-job failures reproduce the documented API
staleness behavior; they do not by themselves disprove the log `CurrentBlock`
signal.

## JSONL Output Paths

- Four-reader probe: `Z:\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\driver\vendor\leica\navigator_expert\tests\hardware\probe_four_readers_20260611_185038_real_scope.jsonl`
- API validator: `Z:\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\driver\vendor\leica\navigator_expert\tests\hardware\validate_hardware_20260611_185038_real_scope_api.jsonl`
- LOG validator: `Z:\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\driver\vendor\leica\navigator_expert\tests\hardware\validate_hardware_20260611_185038_real_scope_log.jsonl`
- BOTH validator: `Z:\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\driver\vendor\leica\navigator_expert\tests\hardware\validate_hardware_20260611_185038_real_scope_both.jsonl`

## Four-Reader Probe Summary

Phase counts:

| Phase | Count | OK | Fail |
| --- | ---: | ---: | ---: |
| read_only | 7 | 7 | 0 |
| job_change | 6 | 0 | 6 |
| xy_position | 10 | 10 | 0 |

Read-only reader results:

| Datum | API | LOG | BOTH |
| --- | --- | --- | --- |
| selected_job | `AF Job` | none | `AF Job` via API |
| xy | `(32100.181, 28427.363) um` | same via log | same via API |
| jobs | 3 jobs, selected `AF Job` | none | 3 jobs, selected `AF Job` via API |
| scan_status | ok | none | ok via API |
| hardware_info | ok | none | ok via API |
| job_settings | ok | none | ok via API |
| pending_dialog | n/a | none | n/a |

Change-wait winners:

- Overall sources: API 10, LOG 4.
- Job-change steps: LOG reported `changed` for 4/6 attempts; 2/6 were `unconfirmed`.
- XY-position steps: API reported `changed` for 10/10 attempts.

Job-change details:

- All 6 job-change probe records failed the probe's current success criteria.
  That criterion includes the API-confirmed command result and passive
  API/BOTH agreement, so it is not a valid arbiter for selected-job on this
  LAS X version. The 2026-06-05 fix established that API selected-job readback
  can remain persistently stale, and `both` commonly falls back to that same API
  witness when passive log fails closed.
- Steps 1 and 4 targeted `HiRes`: command `success=False`, `confirmed=False`
  because the command used API confirmation; change_wait reported `changed`
  from LOG, `matches_target=True`, with a post-command `CurrentBlock` timestamp.
  Passive API and BOTH still read `AF Job`, which matches the known stale-API
  signature.
- Steps 2 and 5 targeted `Overview`: command `success=False`, `confirmed=False`
  because the command used API confirmation; change_wait reported `changed`
  from LOG, `matches_target=True`, with a post-command `CurrentBlock` timestamp.
  Passive API and BOTH still read `AF Job`, again matching the stale-API
  signature.
- Steps 3 and 6 targeted `AF Job`: command `success=True`, `confirmed=True`; change_wait was `unconfirmed`; passive API and BOTH read `AF Job`, LOG passive was none.

XY details:

- All 10 XY moves succeeded and confirmed.
- API and BOTH readbacks matched the target on all 10 moves.
- LOG readback matched on 5/10 moves and returned none on 5/10 moves.
- Maximum recorded target delta among reported XY readbacks was about `0.0022 um`, far below the `20 um` tolerance.

Restore observations:

- The probe script printed and executed restore paths for the original job (`AF Job`) and original XY (`32100.1806640625, 28427.36328125 um`).
- Subsequent validator starts observed the same selected job and XY, consistent with restoration.

## Full Validator Summaries

### API Mode

Counts: PASS 81, WARN 1, FAIL 4, SKIP 0.

Failures:

- `job selection: select job` for `Overview`: `SelectJob 'Overview' (readback unconfirmed); [total=15.207s, att=3, conf=3, m=async]`
- `job selection: confirmed Overview`: expected `Overview`, actual `AF Job`
- `job selection: select job` for `HiRes`: `SelectJob 'HiRes' (readback unconfirmed); [total=15.202s, att=3, conf=3, m=async]`
- `job selection: confirmed HiRes`: expected `HiRes`, actual `AF Job`

Warnings:

- `sequential_mode: restore`: target `Line` was sent but readback did not confirm after 3 confirmation attempts over about 15.2 s.

Skips: none.

Motion/acquire outcomes:

- XY: PASS. Moved from `(32100.1806640625, 28427.36328125) um` to `(32125.1806640625, 28452.36328125) um`; x/y readbacks passed within `20 um`; XY restore PASS.
- Z: PASS. Moved galvo Z from `-0.0 um` to `2.0 um`; readback passed within `1 um`; Z restore PASS.
- Objective: PASS. Switched from `HC PL APO CS2    10x/0.40 DRY` to `HC PL APO CS2    40x/1.10 WATER`; objective restore PASS.
- Acquire: PASS. Acquired `AF Job` in about `0.203 s`.
- Original job restore: PASS, `AF Job` already selected.
- Original XY/Z/objective restore: PASS. Sequential mode restore was WARN, so setting restoration should be checked manually if `Line` vs `Frame` matters.

### LOG Mode

Counts: PASS 76, WARN 1, FAIL 6, SKIP 2.

Configuration note: this run used `--state-reader-mode log` but did not use
`--select-job-confirm-source log`. The command-level failures below therefore
come from the default API selected-job confirmation path, not from the fixed
log-confirmation path documented in `docs/SELECTED_JOB_LOG_READER_FIX_20260605.md`.

Failures:

- `job: resolve`: no jobs returned with `--state-reader-mode log`.
- `job selection: select job` for `Overview`: command readback unconfirmed after about 15.2 s.
- `job selection: confirmed Overview`: expected `Overview`, actual `AF Job`.
- `job selection: select job` for `HiRes`: command readback unconfirmed after about 15.2 s.
- `job selection: confirmed HiRes`: expected `HiRes`, actual `AF Job`.
- `job selection: log poll confirmed AF Job`: timeout; last value remained `HiRes`, with the last selected timestamp before the command.

Log-poll evidence:

- `job selection: log poll confirmed Overview`: PASS in `0.641 s`,
  `CurrentBlock/Name=Overview`, `current_block_after_command=True`.
- `job selection: log poll confirmed HiRes`: PASS in `0.625 s`,
  `CurrentBlock/Name=HiRes`, `current_block_after_command=True`.
- `job selection: log poll confirmed AF Job`: FAIL because the stale API path
  considered `AF Job` already selected and emitted no new post-command
  `CurrentBlock` event; the log correctly rejected the older `HiRes` event as
  `selected_before_command`.

Warnings:

- `sequential_mode: write alternate`: target `Line` was sent but readback did not confirm after 3 confirmation attempts over about 15.2 s.

Skips:

- `sequential_mode: readback`: skipped because the alternate write was unconfirmed.
- `xy: round-trip`: skipped because log `get_xy` returned None.

Motion/acquire outcomes:

- XY: SKIP. The log reader could not provide the starting XY for the round trip.
- Z: PASS. Moved galvo Z to `2.0 um`, readback PASS, Z restore PASS to `0.0 um`.
- Objective: not exercised beyond `objective: read hardware` and `objective: read start`. No switch/restore record was emitted in LOG mode.
- Acquire: PASS. Acquired `AF Job` in about `10.161 s`.
- Original job restore: PASS, `AF Job` already selected.
- Original Z restore: PASS. XY and objective restore were not applicable because those movements were not performed in LOG mode.

### BOTH Mode

Counts: PASS 80, WARN 1, FAIL 4, SKIP 1.

Failures:

- `job selection: select job` for `Overview`: command readback unconfirmed after about 15.2 s.
- `job selection: confirmed Overview`: expected `Overview`, actual `AF Job`.
- `job selection: select job` for `HiRes`: command readback unconfirmed after about 15.2 s.
- `job selection: confirmed HiRes`: expected `HiRes`, actual `AF Job`.

Warnings:

- `sequential_mode: write alternate`: target `Line` was sent but readback did not confirm after 3 confirmation attempts over about 15.2 s.

Skips:

- `sequential_mode: readback`: skipped because the alternate write was unconfirmed.

Motion/acquire outcomes:

- XY: PASS. Moved from `(32100.1806640625, 28427.36328125) um` to `(32125.1806640625, 28452.36328125) um`; x/y readbacks passed within `20 um`; XY restore PASS.
- Z: PASS. Moved galvo Z to `2.0 um`; readback passed within `1 um`; Z restore PASS.
- Objective: PASS. Switched from `HC PL APO CS2    10x/0.40 DRY` to `HC PL APO CS2    40x/1.10 WATER`; objective restore PASS.
- Acquire: PASS. Acquired `AF Job` in about `10.959 s`.
- Original job restore: PASS, `AF Job` already selected.
- Original XY/Z/objective restore: PASS.

## Reader Disagreements After Commands

- Selected-job commands reproduced the known 2026-06-05 disagreement: log
  `CurrentBlock` saw `HiRes`/`Overview` quickly, while passive API and BOTH
  still returned `AF Job`. API/BOTH are not independent witnesses here; BOTH
  falls back to API when passive log fails closed, and the command result was
  still API-confirmed because `--select-job-confirm-source log` was not enabled.
- For `AF Job`, API and BOTH confirmed `AF Job`, while change_wait could not
  confirm a change because API already read `AF Job` at baseline and no fresh
  post-command log event was emitted.
- XY commands did not show numeric disagreement between readers when values were present. API and BOTH matched every target; LOG matched 5/10 targets and returned none for the other 5/10.
- Read-only passive LOG was frequently absent for selected_job, jobs, scan_status, hardware_info, and job_settings. BOTH generally fell back to API and returned useful values.

## Interpretation

Where log-only fails:

- LOG mode is not sufficient as a general passive state reader on this real-scope run. It returned no jobs during read-only resolution, returned no selected_job in the probe's passive selected-job reads, skipped XY because `get_xy` returned None, and did not exercise objective switching.
- This does not mean log `CurrentBlock` is untrusted for selected-job
  confirmation. `docs/SELECTED_JOB_LOG_READER_FIX_20260605.md` established
  `CurrentBlock/Name` in `MatrixScreener.log` as the applied selected-job state
  on this hardware, while API selected-job readback can remain stale for 60 s+.
  Today's `Overview` and `HiRes` log-poll records match that same signature.

Where api-only fails or lags:

- API mode was fast and reliable for most settings, XY, Z, objective, and acquisition.
- API selected-job confirmation failed for `Overview` and `HiRes`: each attempt
  spent about 15 s across three confirmation attempts and still read back
  `AF Job`. This is the expected stale-API selected-job failure documented on
  2026-06-05.
- Sequential mode transitions involving `Line` were also intermittently unconfirmed after about 15 s.

Where both helps:

- BOTH recovered useful read-only state when LOG was missing values by falling back to API.
- BOTH preserved the successful API behavior for XY, Z, objective, and acquisition.
- BOTH does not solve selected-job switching when passive log fails closed and
  the route falls back to stale API selected-job readback. Selected-job
  confirmation still needs the explicit log-confirm path.

Change-wait reliability:

- XY change_wait is reliable enough in this run for the tested movements: 10/10 XY changes were confirmed by API, with maximum readback delta about `0.0022 um`.
- selected_job change_wait found 4 post-command log `CurrentBlock` changes that
  matched the requested target. That is useful evidence and aligns with the
  2026-06-05 fix. However, change_wait intentionally detects "state changed",
  not "the command is fully confirmed"; workflow gating should use
  `select_job` with `--select-job-confirm-source log` / the log confirmation
  profile, not the default API-confirmed command result.

## Bottom-Line Recommendation

For real-scope workflows, use API or BOTH for general passive state reads and
motion/acquisition confirmation. For selected-job confirmation on this LAS X
version, use the log `CurrentBlock` confirmation path from
`docs/SELECTED_JOB_LOG_READER_FIX_20260605.md`; do not require API selected-job
agreement, because API is the known-stale source for this datum.

The missing decisive experiment from this run is:

```powershell
& 'C:\ProgramData\MinicondaZMB\envs\lasxapi_extended\python.exe' `
  'Z:\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\driver\vendor\leica\navigator_expert\tests\hardware\validate_hardware.py' `
  --yes --allow-xy --allow-z --allow-objective --allow-acquire `
  --state-reader-mode log `
  --select-job-confirm-source log
```

The expectation, based on the 2026-06-05 live verification and today's
`CurrentBlock` records, is that `Overview` and `HiRes` should log-confirm quickly
even while immediate API readback remains stale.

XY, Z, objective switching, and acquisition on `AF Job` were operational in API/BOTH modes and restored successfully in this run.

## Open Questions And Calibration Needs

- Re-run the full validator with `--select-job-confirm-source log`; today's
  validator runs did not exercise the selected-job fix configuration.
- Watch the LAS X UI during one `HiRes`/`Overview` switch, or acquire one image
  after a log-confirmed switch and verify which job's settings were used.
- Why did LOG mode not provide enough XY state for the validator round trip and not emit objective switch/restore records?
- Sequential mode `Line` readback was unconfirmed in multiple modes; verify whether this is a reader lag, a LAS X state constraint, or an actual failed setting write.
- XY jitter/min_delta is not a limiting issue for these tested moves: observed target deltas were at most about `0.0022 um`. Smaller-step testing would still be useful before reducing XY tolerances or using very small min-delta thresholds.

## Log-Confirm Recheck

Date/time: 2026-06-11 19:21-19:22 Europe/Berlin. This was run on the real Leica STELLARIS scope after confirming the sample/scope was safe for XY, Z, objective changes, and acquisition.

Exact command:

```powershell
& 'C:\ProgramData\MinicondaZMB\envs\lasxapi_extended\python.exe' `
  'Z:\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\driver\vendor\leica\navigator_expert\tests\hardware\validate_hardware.py' `
  --yes --allow-xy --allow-z --allow-objective --allow-acquire `
  --state-reader-mode log `
  --select-job-confirm-source log `
  --output 'Z:\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\driver\vendor\leica\navigator_expert\tests\hardware\validate_hardware_20260611_real_scope_log_confirm.jsonl'
```

JSONL output:

`Z:\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\driver\vendor\leica\navigator_expert\tests\hardware\validate_hardware_20260611_real_scope_log_confirm.jsonl`

Summary counts:

- PASS 81
- WARN 2
- FAIL 1
- SKIP 1
- Exit code 1, caused by the remaining log-mode startup/read-only job resolver failure.

Selected-job log-confirm results:

- `Overview`: PASS. `select_job` completed with log confirmation in `0.444 s` driver time (`0.625 s` validator elapsed). The explicit validator log poll matched `Overview` in `0.172 s`, `attempts=1`, with `log_event_delta=0.183 s`.
- `HiRes`: PASS. `select_job` completed with log confirmation in `0.434 s` driver time (`0.610 s` validator elapsed). The explicit validator log poll matched `HiRes` in `0.171 s`, `attempts=1`. The record reports `log_event_delta=-0.623 s`, while still marking the poll as matched; this is consistent with the command's own log-confirm path having already observed the event before the validator's extra poll timestamp.
- `AF Job`: PASS. `select_job` completed in `3.837 s` driver time (`4.032 s` validator elapsed), with `att=2` and `conf=2`; the console noted one log-backed timeout before the successful confirmation. The explicit validator log poll matched `AF Job` in `0.156 s`, `attempts=1`, with `log_event_delta=0.181 s`.
- Restore/no-op behavior: PASS. The final restore reported `'AF Job' already selected` and completed in `0.171 s` validator elapsed (`0.164 s` driver total).
- API readback still disagreed for the non-original jobs: after log-confirmed `Overview`, immediate API read returned `AF Job`; after log-confirmed `HiRes`, immediate API read returned `AF Job`. Those are recorded as WARN, not FAIL.

Remaining failures and warnings:

- FAIL: `job: resolve -- no jobs returned with --state-reader-mode log`. This is the same log-mode read-only/startup job-list freshness issue noted earlier; the validator then used API control input for the job-switch experiment.
- WARN: `job selection: API lag after log-confirmed Overview -- log confirmed 'Overview'; immediate API read returned 'AF Job'`.
- WARN: `job selection: API lag after log-confirmed HiRes -- log confirmed 'HiRes'; immediate API read returned 'AF Job'`.
- SKIP: `xy: round-trip -- get_xy returned None`. LOG mode still did not provide a usable XY start value for the validator round trip.

XY/Z/objective/acquire outcomes:

- XY: skipped because log `get_xy` returned None. No XY move was performed in this recheck, so XY restore was not applicable.
- Z: PASS. Moved galvo Z from `-0.0 um` to `2.0 um`, readback passed within `1.0 um`, and restored to `-0.0 um`.
- Objective: only `objective: read hardware` and `objective: read start` were recorded as PASS. No objective switch was performed, so objective restore was not applicable in this log-mode run.
- Acquire: PASS. Acquired `AF Job`; total driver time was about `14.081 s`.
- Settings restores all recorded PASS, including sequential mode restoring to `Frame`.

Interpretation:

The 2026-06-05 selected-job log-confirm fix reproduced on the real scope on 2026-06-11 when the validator was run with `--select-job-confirm-source log`. `Overview`, `HiRes`, and `AF Job` all log-confirmed, while immediate API selected-job readback remained stale at `AF Job` for `Overview` and `HiRes`. This explains why the earlier 2026-06-11 LOG run looked failed: it was still using API selected-job confirmation for the command path.

Recommendation:

For this LAS X version (`1.0.108.0`), selected-job confirmation should default to the log `CurrentBlock` path rather than API readback. The validator should also make `--state-reader-mode log` imply `--select-job-confirm-source log`, or at least warn loudly when log reader mode is paired with API selected-job confirmation. API/BOTH remain better choices for general passive reads and XY validation because LOG mode still has gaps for read-only job resolution and XY start state.

# Selected-Job + Log-Reader Fix — Handoff

Date: 2026-06-05
Branch: `defaults/native-autosave-log`
Commits: `0e183db` (driver fix), `c832463` (docs)
Backup of the original (broken) exploration: branch `codex-explore-backup`

## TL;DR

On this LAS X version (`1.0.108.0`) the **CAM API selected-job readback is
persistently stale**. The fix makes the driver read selected-job state and the
full job list from the LAS X **logs** instead, and confirms job switches against
the log. Live-verified: log-confirmed job switching is ~0.17 s/switch vs a 15 s
timeout-then-fail in API mode.

## The core finding (the non-obvious fact)

- After a job switch, `CurrentBlock/Name` in `MatrixScreener.log` reflects the
  applied job in ~0.13–0.19 s.
- The CAM API `get_jobs().IsSelected` / selected-job readback **never converged**
  to the new job within a 60 s poll — it kept returning the previous job
  (`Overview`).
- So for *selected job* on this hardware, the **log is authoritative and fast;
  the API readback is wrong/stale**. This inverts the usual "API is truth" rule.
- The job list and selected-job state are **separate log streams** with
  different freshness from the per-job settings stream — do not couple them.

## Three independent LAS X log signals

| Signal | Source | Notes |
|---|---|---|
| Job **list** | `GetMatrixCollectionPatternInfo` (`lcsCommand.log`) | Full ordered summary: name/id/autofocus/scan. Authoritative list. |
| Selected **job** | `CurrentBlock/Name` + `CurrentBlock/BlockID` (`MatrixScreener.log`) | Applied state. **Beats** `SetCurrentSelectedElementID` (which is only *requested intent*). |
| Per-job **settings** | `ATL_GetBlockApiInfoAsJsonString` (`lcsCommand.log`) | On-demand: only logged for jobs whose settings were queried, so partial. |

Log files:
`C:\ProgramData\Leica Microsystems\LAS X\lcsCommand.log`
`C:\ProgramData\Leica Microsystems\LAS X\MatrixScreener.log`

## What the fix does (committed in `0e183db`)

- `state_readers/log_reader.py`
  - Parse `GetMatrixCollectionPatternInfo` → complete job list.
  - Parse `CurrentBlock/*` → applied selection.
  - Selection precedence: fresh `CurrentBlock` first (state beats intent);
    `SetCurrentSelectedElementID` element-index kept as a **guarded fallback**,
    trusted only on a complete, unambiguous, numeric-id cluster (fail closed).
  - `get_selected_job` prefers `CurrentBlock`, falls back to get_jobs-derived.
- `state_readers/router.py` + `core/profiles.py`
  - Route `get_selected_job` independently of `get_jobs` (new
    `selected_job_mode` / `selected_job_log_max_age_s` / `selected_job_timeout_s`)
    so selected-job freshness is no longer gated on a fresh job-list dump.
- `core/commands.py` `select_job`
  - One reader family per decision (no API/log mixing):
    - log-confirm: log pre-check (a no-op re-select emits no new event, so the
      early-exit must come from log state) + log confirmation; the API readback
      is used only to enumerate jobs for cluster priming and to *annotate* a
      disagreement, never to gate the command.
    - api-confirm: API pre-check + API confirmation throughout.
- `state_readers/log_wait.py`
  - Confirm from a fresh post-command `CurrentBlock` event; element/cluster path
    as fallback.
- `tests/hardware/validate_readers_side_by_side.py`
  - Pin `mode="api"` on the API column so it truly compares API vs log.

## Verification data (2026-06-05)

Env: `smart_lasx_runtime`. CAM Api Server listening on `127.0.0.1:8896`
(`NavigatorExpert`), client name `PythonClient`.

### Off-microscope
- `413` driver tests pass (`tests/unit` + `tests/hardware/test_validate_hardware.py`).
  - Before the fix the restored exploration had **7 failing** tests.
- Remaining broad-suite failures are **env-only** and unrelated:
  `test_polish.py`/`test_visualize.py` need `IPython`/`matplotlib`,
  `test_acquisition` OME validation needs `lxml`/`xmlschema`.

### Read-only validators
```
API mode (--state-reader-mode api):        pass=9  fail=0
Default profile (log), idle scope:         pass=7  skip=1   (SKIP job:resolve -- no jobs)
Explicit log mode, idle scope:             pass=7  fail=1   (FAIL job:resolve -- no jobs)
```
The idle-scope "no jobs" is the **age-gate policy** (see open item), not a parser
bug.

### Side-by-side (API vs log, log freshened by the API reads)
```
parity 8/10
  get_jobs (names)   api=[AF Job,HiRes,Overview]  log=[AF Job,HiRes,Overview]   MATCH
  get_selected_job   api=[Overview]               log=[Overview]                MATCH
  get_xy / scan_status / hardware_info / get_fov / read_zwide_um                MATCH
  settings[AF Job], settings[HiRes]              api=True log=False   (on-demand ATL, expected)
```

### Full write run — the live before/after
```
API mode  --yes --state-reader-mode api --select-job-confirm-source api
  FAIL job selection: select job 'AF Job' (UNCONFIRMED, 15.2s timeout)
  FAIL confirmed AF Job -- expected='AF Job' actual='Overview'   (API stuck on Overview)
  FAIL job selection: select job 'HiRes' (UNCONFIRMED, 15.1s timeout)
  FAIL confirmed HiRes  -- expected='HiRes'  actual='Overview'
  pass=65 warn=1 fail=4   (stale restore was a no-op -> left scope on HiRes)

LOG mode  --yes --state-reader-mode log --select-job-confirm-source log
  PASS log poll confirmed AF Job  (187ms)
  WARN API lag -- log confirmed 'AF Job'; immediate API read returned 'Overview'
  PASS log poll confirmed HiRes   (172ms)
  WARN API lag -- log confirmed 'HiRes'; immediate API read returned 'Overview'
  PASS log poll confirmed Overview(172ms)  -> restored to Overview correctly
  pass=72 warn=2 fail=1   (the 1 fail = startup "no jobs" idle-scope passive read)
```
Each switch: **~0.17 s log-confirmed vs 15 s API timeout**. Log mode restores the
original job correctly; API mode leaves it drifted.

## OPEN ITEM — age-gate policy (a decision, not a bug)

Profile gates in `core/profiles.py` `LOG_READER`:
```
xy_log_max_age_s          = 1.0
scan_status_log_max_age_s = 0.5
jobs_log_max_age_s        = 2.0
job_settings_log_max_age_s= 2.0
hardware_info_log_max_age_s= 2.0
```
On a fully idle scope these reject the (minutes-old) logs, so passive
`get_jobs(log)` returns nothing until something primes the log — this is the
`job: resolve -- no jobs` line. The job-switch path is unaffected (each switch
writes a fresh `CurrentBlock`). Decide later: keep strict freshness, or let the
slow-changing job list tolerate a longer window (split policy per signal). Do
NOT blanket-inflate all gates (would accept stale XY/scan/settings).

## How to re-verify next time

```powershell
$py = "C:\ProgramData\MinicondaZMB\envs\smart_lasx_runtime\python.exe"
cd Z:\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy

# unit gate
& $py -m pytest driver/vendor/leica/navigator_expert/tests/unit `
  driver/vendor/leica/navigator_expert/tests/hardware/test_validate_hardware.py -q

# preconditions: LAS X up, CAM Api Server listening on 127.0.0.1:8896 (PythonClient)
Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -eq 8896 }

# read-only API control
& $py driver/vendor/leica/navigator_expert/tests/hardware/validate_hardware.py `
  --yes --read-only --state-reader-mode api

# API vs log parity (freshens the log via API reads)
& $py driver/vendor/leica/navigator_expert/tests/hardware/validate_readers_side_by_side.py --read-only

# live job-switch via log confirmation (writes: switches + restores job)
& $py driver/vendor/leica/navigator_expert/tests/hardware/validate_hardware.py `
  --yes --state-reader-mode log --select-job-confirm-source log
```

Notes:
- `--yes` does job-selection + reversible setting writes; stage motion /
  objective / acquire stay behind `--allow-xy` / `--allow-z` / `--allow-objective`
  / `--allow-acquire`.
- The env `smart_lasx_pf_only_fresh` named in the original test plan does not
  exist on this machine; use `smart_lasx_runtime` (built per
  `docs/MINIMAL_LASX_PYTHON_ENV.md`; has pythonnet + the image/OME deps).

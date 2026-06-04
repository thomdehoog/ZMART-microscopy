# API vs Log — Full Reader Comparison

Date: 2026-06-05
Branch: `defaults/native-autosave-log`
Scope state: **idle** (no acquisition running), LAS X `1.0.108.0`, `api_delay_ms=250`
Env: `smart_lasx_runtime`, CAM Api Server `127.0.0.1:8896` (`PythonClient`)

Every passive reader called in both `mode="api"` and `mode="log"` with the
production profile age gates in effect. For each reader the API read runs first
(which would freshen the log if it issued the same logged command), then the log
read. Latencies are single-call wall time.

## Reader-by-reader

| Reader / field | API value | LOG value (gated) | Match | API ms | LOG ms |
|---|---|---|:--:|--:|--:|
| `get_xy` (um) | (55138, 37912) | None | N | 30 | 347 |
| `get_jobs` (names) | AF Job,HiRes,Overview | [] | N | 12 | 318 |
| `get_selected_job` | Overview | None | N | 13 | 321 |
| `get_scan_status` | eScanIdle | None | N | 3 | 335 |
| `get_hardware_info`.Microscope.name | DMI8 | None | N | 13 | 318 |
| `get_fov[Overview]` (um) | (465.0, 465.0) | None | N | 17 | 319 |
| `read_zwide_um[Overview]` | 1712.97 | \<RuntimeError\> | N | 13 | 326 |
| `get_job_settings[Overview]` (read) | ok | ok | Y | 17 | 333 |
| &nbsp;&nbsp;.zoom.current | 1.2499992052719082 | 1.2499992052719082 | Y | | |
| &nbsp;&nbsp;.scanSpeed.value | 400 | 400 | Y | | |
| &nbsp;&nbsp;.format | 512 x 512 | 512 x 512 | Y | | |
| &nbsp;&nbsp;.scanMode | xyz | xyz | Y | | |
| &nbsp;&nbsp;.objective.name | HC PL APO CS2 20x/0.75 DRY | HC PL APO CS2 20x/0.75 DRY | Y | | |
| &nbsp;&nbsp;.as0.pinholeAiry.value | 1.0 | 1.0 | Y | | |
| &nbsp;&nbsp;.as0.frameAverage | 1 | 1 | Y | | |

## What this is showing (it is NOT a parser failure)

This is the **age-gate policy on an idle scope** (the open item), captured across
all readers:

- **API** is the live source: every reader works, fast (3-30 ms).
- **LOG (production-gated)** returns `None`/`[]` for the volatile readers because
  that log data is older than the 0.5-2 s gates **and the API read doesn't
  refresh it** - the API readers mostly issue different CAM calls than the log
  records.
- **The one parity row is the tell:** `get_job_settings` matches on every field,
  because reading settings via API issues the *same*
  `ATL_GetBlockApiInfoAsJsonString` command the log parses, so it **self-freshens**
  the log within the 2 s gate. The others do not self-freshen, so they gate out.

## The latency dimension

- API single reads: **~3-30 ms**. Log single reads: **~320 ms**, because each one
  re-parses the whole multi-MB log file. For *passive* reads, log is the slower
  one.
- The flip is **confirmation-after-a-write** (e.g. a job switch): there, the log
  reflects the new state in ~0.2 s while the API readback stays stale for 15 s+.
  That is why log wins for *job-switch confirmation* (the committed fix) but is
  slower/empty for idle passive reads.

## Summary of the API-vs-Log difference

| Dimension | API | Log |
|---|---|---|
| Idle passive reads (value) | all correct | mostly `None` (gated-out as stale) |
| Idle passive reads (latency) | ~3-30 ms | ~320 ms (full-file parse) |
| Self-freshened reads (settings) | correct | matches API |
| Selected-job after a switch | stale 15 s+ (wrong) | fresh ~0.2 s (correct) |
| When log is fresh (active / just-written) | correct | matches API (side-by-side parity 8/10) |

Net: API is the reliable always-on source but is **stale for selected-job**; log
is empty for idle passive reads (the age-gate policy) but is the **fast, correct**
source the instant something writes to it. That is exactly why the fix uses log
for job-switch confirmation and keeps API for everything that must work cold.

## Reproduce

Pin the CAM Api Server first (`127.0.0.1:8896`). The probe used for the table is
a scratch script (not in the repo); the equivalent canonical comparison is:

```powershell
$py = "C:\ProgramData\MinicondaZMB\envs\smart_lasx_runtime\python.exe"
cd Z:\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy

# value parity, contract-field level (uses an ungated snapshot for the log column,
# so it shows the parser's capability when the log is fresh)
& $py driver/vendor/leica/navigator_expert/tests/hardware/validate_readers_side_by_side.py --read-only
```

Note: the routed (gated) `mode="log"` reads above return `None` on an idle scope
because of the freshness gates; the side-by-side log column uses an un-gated
snapshot, so it shows parity when the log is fresh. Both views are in
`SESSION_SUMMARY_20260605.md` and `SELECTED_JOB_LOG_READER_FIX_20260605.md`.

## Event-driven vs passive: why polling can't beat data freshness

Hardware test: `tests/hardware/move_xy_pattern_api_vs_log.py` moves the stage
around a 5000 um square for two laps (move -> confirm -> move -> confirm) and
reads the position back in api and log mode at each stop.

Both / api readback (8 moves):
- API: 8/8 exact (+/-0 um), ~12 ms each.
- LOG: 5-6/8 returned the exact position; the rest `None`. Never wrong.

Log-only readback, polling for a fresh value:
- When fresh, log lands on the FIRST poll (`tries=1`, ~330 ms), exact position.
- When the line has aged past the 1.0 s `xy` gate, polling does NOT recover it:
  with `--log-poll-s 8` the failing stop re-parsed the log **21 times over 8.0 s
  and still returned `None`**.

### The rule

The log reader is **passive**: a poll only re-parses the file, it does not issue
any command, so it cannot make a fresh `GetStageHwPosition` line appear. The only
fresh XY line comes from the move's own confirmation (an API read). Once that line
ages past the gate and nothing re-queries position, no amount of polling helps -
each iteration finds the same too-old line.

Outcome is therefore **binary**: a read is either fresh-immediately (`tries=1`) or
it polls to timeout and returns `None`. Nothing lands "after 3 s of polling",
because no fresh event arrives mid-poll on a settled stage.

| | Fresh log lines during the poll? | Longer poll helps? |
|---|---|---|
| Job-switch confirmation | yes - the command emits a new `CurrentBlock` event | **yes** |
| Passive read (settled stage) | no - nothing re-queries the datum | **no** |

### Practical guidance per datum

- **Position / passive state (XY, scan status, hardware info):** use **API** - it
  actively queries, always fresh, ~12 ms. Log is only an opportunistic echo
  (correct when fresh, `None` otherwise, ~330 ms; not made reliable by polling).
- **Selected job after a switch:** use **log** confirmation - the switch writes a
  fresh `CurrentBlock` event, so polling lands on it (and API is stale here).

To get log-XY to return a value you must read before the gate expires (smaller
pause), re-trigger the query (== just use API), or loosen the gate (risky for a
fast-moving value). Do NOT "fix" it with a longer poll - the wall is data
freshness, not poll duration.

Test usage:

```powershell
$py = "C:\ProgramData\MinicondaZMB\envs\smart_lasx_runtime\python.exe"
& $py driver/vendor/leica/navigator_expert/tests/hardware/move_xy_pattern_api_vs_log.py `
  --delta-um 5000 --laps 2 --pause-s 0.8 --readback both
# log-only with a long poll window (demonstrates polling can't beat freshness):
& $py driver/vendor/leica/navigator_expert/tests/hardware/move_xy_pattern_api_vs_log.py `
  --readback log --log-poll-s 8
```

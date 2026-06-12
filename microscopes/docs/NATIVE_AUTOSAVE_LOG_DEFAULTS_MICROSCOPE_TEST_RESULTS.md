# Native AutoSave + Log Defaults Microscope Test Results

Branch: `defaults/native-autosave-log`
Date: 2026-06-04
Test plan: `docs/NATIVE_AUTOSAVE_LOG_DEFAULTS_MICROSCOPE_TEST_PLAN.md`

## Environment Note

- The env named in the plan (`smart_lasx_pf_only_fresh`) does **not** exist on
  this machine.
- Available envs under `C:\ProgramData\MinicondaZMB\envs`:
  `env_a, env_b, env_c, lasxapi, lasxapi_extended, lasxapi_extended1,
  python_zmb, zmb_cellpose_v3, zmb_napari_empanada, zmb_pyscreengui`
- Default `python` resolves to `lasxapi_extended`.
- **Decision:** running validators with `lasxapi_extended` for now.
- Open question: was the intended PF-only env renamed to `lasxapi_extended1`?

## Test 1: API-mode control run

Command:

```powershell
& "C:\ProgramData\MinicondaZMB\envs\lasxapi_extended\python.exe" `
  driver/vendor/leica/navigator_expert/tests/hardware/validate_hardware.py `
  --yes `
  --state-reader-mode api `
  --output C:\Users\t.de\AppData\Local\Temp\native_log_defaults_api_control.jsonl
```

Result: **FAIL at connection step** (did not reach validation).

```text
Connect raised (is LAS X running?):
  System.IO.IOException: The operation is not allowed on non-connected sockets.
FAIL | client: connect -- could not establish client
pass=0 warn=0 fail=1 skip=0
```

Interpretation:
- This is Precondition #1 (LAS X running + CAM API connects) not being met.
- Nothing moved on the scope; it never got past connecting.
- The socket error is a "LAS X not accepting connections" symptom, not an
  env/DLL problem.

## Connection Diagnosis (root cause)

Investigated why the connect failed. Findings:

1. **LAS X is fully running.** Processes confirmed up since ~22:00:
   `LMSApplication`, `NavigatorExpert`, `LMSDataContainerServerV2`,
   `LMSInformationService`, `LMSIOManager`, `LMSUserDataService`, and others.
   So "is LAS X running?" is not the problem.

2. **The Python connector loaded and reached the server-side connect.** The
   error is a .NET `System.IO.IOException` thrown *inside* the Leica connect
   path (`CreateClientSideSSlStreamAsync` -> "operation is not allowed on
   non-connected sockets"). That means the CAM connector DLLs in
   `lasxapi_extended` work; the TCP socket simply never established. **This is
   not an env/DLL problem.**

3. **No CAM API port was listening.** At failure time the only LMS listening
   ports were:
   - `127.0.0.1:8892` (LMSDataContainerServerV2)
   - `127.0.0.1:50000` (LMSIoTCoreService)

   No Matrix Screener / CAM client port was accepting connections.

4. **The CAM Api Server is configured but not started.** The LAS X "Api Server"
   panel shows:
   - Server credentials: name `Cam Server`, IP `127.0.0.1`, **Port `8896`**
   - Registered client: **`PythonClient`** (present)
   - Server certificate thumbprint `C0A9D22ABE687584E3BC3FF12A29238CD29CCF1B`,
     expiry `2026-11-25`
   - Repeated `netstat` checks show **8896 is NOT listening**, so the server
     socket is not bound even though it is configured.

5. **Client name matches.** The validator connects as `PythonClient` (default in
   `core/session.py:60` and `validate_hardware.py:1062`), which is exactly the
   registered client. Registration is correct.

### Root cause

The CAM **Api Server in LAS X is not started/bound on `127.0.0.1:8896`**.
Everything else (port config, `PythonClient` registration, certificate, Python
env, connector DLLs) is correct.

### Does a new env help? No

The current env already loads the connector and reaches the server handshake;
the failure is that nothing is listening to connect to. A new/cloned env will
not change this. Also note: there is **no `environment.yml`/`requirements.txt`
in the repo**, so `smart_lasx_pf_only_fresh` cannot be reproduced exactly -
only cloned from an existing env.

### Fix / next steps before retry

1. In the LAS X "Api Server" panel, **start / enable the Api Server** so it binds
   `127.0.0.1:8896`. (`PythonClient` is already registered; the `NewClient`
   being typed is not needed.)
2. Confirm it is listening:
   ```powershell
   Get-NetTCPConnection -State Listen |
     Where-Object { $_.LocalPort -eq 8896 }
   ```
3. Re-run Test 1.

## Tests 2-7

Not yet run (blocked on Test 1 connection / CAM Api Server not started).

## Retry: API read-only after Api Server started

After the failed run, `127.0.0.1:8896` was checked again and was listening,
owned by `NavigatorExpert`.

Command:

```powershell
& "C:\ProgramData\MinicondaZMB\envs\lasxapi_extended\python.exe" `
  driver/vendor/leica/navigator_expert/tests/hardware/validate_hardware.py `
  --yes `
  --read-only `
  --state-reader-mode api `
  --output C:\Users\t.de\AppData\Local\Temp\native_log_defaults_api_readonly_retry.jsonl
```

Result: **PASS**.

```text
client | LasxApi (LAS X simulator or microscope) |
  runtime=C:\Program Files\Leica Microsystems CMS GmbH\LAS X\AddIns\NavigatorExpert |
  version=1.0.108.0 |
  api_delay_ms=250
PASS | ping
PASS | get_scan_status
PASS | get_jobs
PASS | get_hardware_info
PASS | get_xy
PASS | job: resolved
PASS | settings: read
DONE | __summary__ -- pass=9 warn=0 fail=0 skip=0
```

Interpretation:
- The original failure was a LAS X CAM Api Server startup/binding issue, not a
  Program Files runtime, pythonnet, profile delay, or driver-default issue.
- Once the Api Server was listening on `127.0.0.1:8896`, the driver connected
  and read state successfully.
- The remaining Tests 2-7 still need to be run from the plan.

## Minimal Env Built: `smart_lasx_runtime`

Built the recommended microscope env from `docs/MINIMAL_LASX_PYTHON_ENV.md`
(covers connection, hardware validation, native AutoSave save, and API-vs-log
comparison in one env). No Leica DLLs are copied in; the driver loads the CAM
runtime from Program Files at runtime.

Create + install:

```powershell
conda create -n smart_lasx_runtime python=3.12 pip -y
& "C:\ProgramData\MinicondaZMB\envs\smart_lasx_runtime\python.exe" -m pip install `
  pythonnet numpy tifffile imagecodecs ome-types pytest
```

Resulting versions (Python 3.12.13):
- `pythonnet` 3.1.0 (+ `clr_loader` 0.3.1, `cffi` 2.0.0) -- the .NET bridge
- `numpy` 2.4.6, `tifffile` 2026.6.1, `imagecodecs` 2026.5.10 -- image I/O
- `ome-types` 0.6.3 -- OME metadata comparison
- `pytest` 9.0.3 -- tests

Import check:

```text
clr import: OK
pythonnet 3.1.0
clr_loader 0.3.1
```

Env path: `C:\ProgramData\MinicondaZMB\envs\smart_lasx_runtime\python.exe`

### How the driver auto-connects

`connect_python_client()` (`core/session.py:60`) requires no host/port/cert in
the script:
1. `load_lasx_api_runtime()` auto-loads the CAM runtime from Program Files.
2. `client.Connect("PythonClient")` connects over `127.0.0.1:8896` as the
   registered client.
3. Sets the profile API delay (250 ms) and pings to verify.

The only precondition is that the LAS X Api Server is listening on `8896`.

## End-to-End Smoke Test With `smart_lasx_runtime`

Confirmed `8896` listening (owned by `NavigatorExpert`), then ran the read-only
validator with the new env.

Command:

```powershell
& "C:\ProgramData\MinicondaZMB\envs\smart_lasx_runtime\python.exe" `
  driver/vendor/leica/navigator_expert/tests/hardware/validate_hardware.py `
  --yes `
  --read-only `
  --state-reader-mode api
```

Result: **PASS**.

```text
client | LasxApi | runtime=C:\Program Files\...\AddIns\NavigatorExpert |
  version=1.0.108.0 | api_delay_ms=250
PASS | stage config: load (31ms)
PASS | stage limits: apply
PASS | ping
PASS | get_scan_status
PASS | get_jobs (47ms)
PASS | get_hardware_info (15ms)
PASS | get_xy (32ms)
PASS | job: resolved
PASS | settings: read (15ms)
DONE | __summary__ -- pass=9 warn=0 fail=0 skip=0
```

Interpretation:
- The freshly built minimal env connects and reads live scope state with no
  manual configuration. The driver auto-connect works end to end.
- `smart_lasx_runtime` is now the env to use for the remaining tests.

## Current Status

- CAM Api Server: listening on `127.0.0.1:8896` (NavigatorExpert) âœ“
- Env `smart_lasx_runtime`: built, pythonnet + clr verified âœ“
- Auto-connect: proven against live scope (read-only pass=9) âœ“

## Test 4: API-vs-Log Side-by-Side (read-only) â€” KEY FINDING

Env: `smart_lasx_runtime`. Ran the read-only comparison twice (identical both
times):

```powershell
& "C:\ProgramData\MinicondaZMB\envs\smart_lasx_runtime\python.exe" `
  driver/vendor/leica/navigator_expert/tests/hardware/validate_readers_side_by_side.py `
  --read-only
```

Output:

```text
=== READ-ONLY PARITY (current state) ===
  OK  get_xy                  API HANG (92ms) -> log delivered (55138,37912)um log_age=114s
  XX  get_jobs (names)        api=[] log=['HiRes']
  OK  get_selected_job        api=[] log=[]
  XX  get_scan_status         api=None log='eScanIdle' log_age=538s
  XX  get_hardware_info       (blank)
  XX  settings[HiRes]         api=False log=True (log_age=114s)
SUMMARY: parity 2/6  API timeouts/hangs=1
```

At face value this looks like "the API is broken," which contradicts the
read-only API run above (pass=9). It is not. Root cause below.

### Root cause of the side-by-side result

1. The harness calls the production readers (`drv.get_xy`, `drv.get_jobs`, ...)
   for its "API" column with **no `mode=` argument**, so they use the profile
   default. On this branch the passive defaults are **`log`** (see plan section
   "Passive state-reader defaults now use the log reader").
2. `router._route_read` (`state_readers/router.py:124`) has **no API fallback in
   pure `log` mode** â€” `mode == "log"` returns `None` if the log read is not
   trusted (stale / empty). There is fallback only in `mode == "both"`.
3. Result: the harness's "API column" is actually an **age-gated log read**,
   while its "log column" is a direct `log_reader` call on an **un-gated**
   snapshot. So it is comparing gated-log vs ungated-log, mislabeled as API vs
   log. The harness predates the default flip to `log`.

**Harness defect on this branch:** to genuinely compare API vs log,
`validate_readers_side_by_side.py` must pin `mode="api"` on the first column.
As written it does not, so its API column is invalid on this branch.

### Direct mode probe (the real signal)

Probed each reader explicitly against the live, idle scope:

```text
get_jobs(mode='api')  -> ['AF Job', 'HiRes', 'Overview']
get_jobs(mode='log')  -> []
get_jobs(mode=None)   -> []        # default == log
get_xy(mode='api')    -> (55138, 37912)
get_xy(mode='log')    -> None
get_xy(mode=None)     -> None      # default == log
```

Findings:
- **API readers work perfectly** (full job list, real XY).
- **Log readers return empty/None** for `get_xy` and `get_jobs` on this idle
  scope. Default mode == log, so the driver's default passive reads return
  nothing here.
- Even where the harness snapshot did parse a job, the **log was partial**
  (`['HiRes']` only) vs the API's full `['AF Job', 'HiRes', 'Overview']`, and
  the log data was stale (`log_age` 114s for xy, 538s â‰ˆ 9 min for scan_status).
  LAS X is idle and not re-dumping its native log, so age-gated log reads reject
  it.

## Test 2 (read-only, default profile = log)

Ran `validate_hardware` with **no** `--state-reader-mode`, so it uses the branch
log defaults:

```powershell
& "C:\ProgramData\MinicondaZMB\envs\smart_lasx_runtime\python.exe" `
  driver/vendor/leica/navigator_expert/tests/hardware/validate_hardware.py `
  --yes --read-only `
  --output C:\Users\t.de\AppData\Local\Temp\native_log_defaults_profile_readonly.jsonl
```

Output:

```text
client | LasxApi | runtime=...\NavigatorExpert | version=1.0.108.0 | api_delay_ms=250
PASS | stage config: load (31ms)
PASS | stage limits: apply
PASS | ping
PASS | get_scan_status (109ms)
PASS | get_jobs (94ms)
PASS | get_hardware_info (94ms)
PASS | get_xy (94ms)
SKIP | job: resolve -- no jobs returned
DONE | __summary__ -- pass=7 warn=0 fail=0 skip=1
```

Interpretation (important):
- `validate_hardware` **does not crash** in default (log) mode â€” it reports
  `pass=7 fail=0 skip=1`. So "does validate_hardware work?" -> yes, it runs.
- BUT the pass is on **empty data**: `get_jobs` passed yet returned no jobs, so
  `job: resolve` was **SKIP -- no jobs returned**. The validator's read-only
  checks count "call returned without error" as PASS; they do not assert the
  passive value is non-empty. Uniform ~94-109 ms latencies are the log-read
  path, not the fast API path (API was 15-47 ms).
- So in default mode the passive log readers deliver **nothing** on this idle
  scope, and the validator masks it as a pass.

### API mode vs default(log) mode, same scope, minutes apart

| reader            | API mode (pinned)              | default (log) mode      |
|-------------------|--------------------------------|-------------------------|
| get_xy            | (55138, 37912)                 | None                    |
| get_jobs          | AF Job, HiRes, Overview        | [] (job resolve SKIP)   |
| validate summary  | pass=9 fail=0 skip=0           | pass=7 fail=0 skip=1    |

## Verdict So Far

- The branch's premise â€” log defaults are good enough for passive reads â€” does
  **not** hold on this live, idle microscope. Log passive reads (`get_xy`,
  `get_jobs`) return empty/None or partial+stale; the API reads are complete.
- This matches the plan's Stop Rule: "default profile validation fails on
  passive log reads." It does not hard-fail the validator, but it silently
  returns empty passive state, which is arguably worse than a clean fail.
- The likely cause is that LAS X is **idle and not re-dumping its native log**,
  so the log is stale/partial and the age gates reject it. Worth re-checking
  during an active acquisition when the log is being written.

## Root-Cause Investigation: Why Log Readers Return Empty

Question raised: have the log readers broken because LAS X changed the log
format in a new version? **Answer: no.** The format is intact; the emptiness is
staleness + an idle scope, plus one harness field assumption.

### Log paths and age gates (from `core/profiles.py`)

```text
lcs_log_path             = C:\ProgramData\Leica Microsystems\LAS X\lcsCommand.log
msgbox_log_path          = C:\ProgramData\Leica Microsystems\LAS X\MatrixScreener.log
current_window_s         = 180.0
xy_log_max_age_s         = 1.0     # XY must be < 1 s old
scan_status_log_max_age_s= 0.5     # scan status < 0.5 s old
jobs_log_max_age_s       = 2.0
job_settings_log_max_age_s = 2.0
hardware_info_log_max_age_s = 2.0
```

The gates assume LAS X is continuously dumping these values (true during active
polling/acquisition). On an idle scope they are far too tight.

### Log files exist but froze when LAS X went idle

```text
lcsCommand.log     1,713,016 bytes  modified 23:24:20  (185 s ago at check time)
MatrixScreener.log 9,975,488 bytes  modified 23:24:20  (185 s ago)
Socket.log         still live (23:27)  <- LAS X is up, just not dumping STATE
```

### All parser markers still match the current format

Grepped the live logs; every marker the parser depends on is present and parses:

```text
GetStageHwPosition   '<Result HwStagePosX="0.055137..." HwStagePosY="0.037912..." Unit="m"/>'   (matches _RE_XY)
ATL_GetBlockApiInfoAsJsonString '<Result Error="">{...}'   (parses; jobName/id/imageSize present)
GetConfocalHardwareInfoAsJson   '<Result Error="">{...}'   (parses)
SetCurrentSelectedElementID" ElementID="2"                 (matches _RE_SEL)
AcquisitionState = <n>   (1806 hits in MatrixScreener.log; parses to eScanIdle)
```

So the log FORMAT has not changed across the LAS X version. The parser works.

### The actual mechanism

The state log lines are written **as a side effect of CAM API commands**:
- XY line timestamp `23:22:42` == the `get_xy` API probe.
- ATL job + hw blocks timestamp `23:18:58` == the side-by-side run.

When nothing drives the API, nothing fresh is logged. Newest entries are minutes
old, the 0.5-2 s age gates reject them, and `log` mode has no API fallback ->
`None`/empty. Job blocks are also **partial**: only 2 ATL dumps occurred this
session (so `get_jobs` returns a subset of the API's full list).

### Double-check: hardware JSON shape is OK

Rechecked the hardware-info JSON after the first diagnosis. Correction: this
system's hardware JSON **does** include a top-level `"Microscope"` key
(`"name": "DMI8"`), so the hardware-info row did **not** fail because of a LAS X
version/shape mismatch.

The row failed for the same reason as the other side-by-side rows: the harness's
supposed "API" side calls `drv.get_hardware_info(client)` without `mode="api"`,
so on this branch it uses the default age-gated `log` route and returns `None`
when the hardware-info log line is stale. The direct un-gated log parser still
parses the full hardware JSON, including `Microscope`.

Second live mode probe:

```text
profile modes: xy=log, jobs=log, hardware_info=log, scan_status=log
age gates: xy=1.0s, jobs=2.0s, hardware_info=2.0s, scan_status=0.5s

log ages:
  xy=697s, scan_status=1346s, hardware_info=922s, selected=38s,
  jobs[HiRes]=922s

raw log parser with no age gate:
  xy=(55137.56, 37912.29) um
  jobs=['HiRes']
  scan=eScanIdle
  hardware_info has Microscope=True

routed readers:
  mode='api': jobs=['AF Job', 'Overview', 'HiRes']; xy=(55137.56, 37912.29) um; status=eScanIdle
  mode='log': jobs=None/[]; xy=None; status=None
  mode=None : jobs=None/[]; xy=None; status=None
```

### Conclusion

- Log reader code + log format: **fine** on this LAS X version.
- Empty/stale results are caused by an **idle scope** (state logs frozen, data
  older than the sub-2 s gates) and a **partial** in-session job dump.
- Valid log-parity testing requires LAS X to be **actively acquiring/polling**
  so the logs are fresh. Re-run Test 4 during an acquisition.

## Latest Read-Only Rerun After Harness Fix

Date/time: 2026-06-04 23:39-23:41

Env: `smart_lasx_runtime`

Confirmed `127.0.0.1:8896` was listening, owned by `NavigatorExpert`.

### Validator control: API mode

```powershell
& "C:\ProgramData\MinicondaZMB\envs\smart_lasx_runtime\python.exe" `
  driver/vendor/leica/navigator_expert/tests/hardware/validate_hardware.py `
  --yes --read-only --state-reader-mode api `
  --output C:\Users\t.de\AppData\Local\Temp\native_log_defaults_api_readonly_latest.jsonl
```

Result:

```text
pass=9 warn=0 fail=0 skip=0
get_jobs=16ms, get_hardware_info=15ms, get_xy=16ms
```

Interpretation: API readers are healthy and return the full live state.

### Validator: default profile

```powershell
& "C:\ProgramData\MinicondaZMB\envs\smart_lasx_runtime\python.exe" `
  driver/vendor/leica/navigator_expert/tests/hardware/validate_hardware.py `
  --yes --read-only `
  --output C:\Users\t.de\AppData\Local\Temp\native_log_defaults_profile_readonly_latest.jsonl
```

Result:

```text
pass=7 warn=0 fail=0 skip=1
SKIP | job: resolve -- no jobs returned
```

Interpretation: default profile still uses log mode and still reports no jobs.
The validator counts the empty passive reads as pass, then skips job resolution.

### Validator: explicit log mode

```powershell
& "C:\ProgramData\MinicondaZMB\envs\smart_lasx_runtime\python.exe" `
  driver/vendor/leica/navigator_expert/tests/hardware/validate_hardware.py `
  --yes --read-only --state-reader-mode log `
  --output C:\Users\t.de\AppData\Local\Temp\native_log_defaults_log_readonly_latest.jsonl
```

Result:

```text
pass=7 warn=0 fail=1 skip=0
FAIL | job: resolve -- no jobs returned with --state-reader-mode log
```

Interpretation: explicit log mode fails the validator because the routed log
reader cannot provide a job list.

### Side-by-side harness correction

Patched `validate_readers_side_by_side.py` so the API side pins
`mode="api"` for production reader calls. Before this fix the harness's "API"
column used the branch default, which is log mode.

Syntax/diff checks:

```text
python -m py_compile validate_readers_side_by_side.py  -> OK
git diff --check                                      -> OK
```

Corrected read-only side-by-side result:

```text
SUMMARY: parity 6/8  API timeouts/hangs=0

OK  get_xy
XX  get_jobs (names)          api=['AF Job', 'HiRes', 'Overview'] log=['Overview']
XX  get_selected_job          api=['Overview'] log=[]
OK  get_scan_status
OK  get_hardware_info
OK  settings[Overview]
OK  get_fov[Overview]
OK  read_zwide_um[Overview]
```

Interpretation: the API-vs-log comparison now shows the real state:

- API is not hanging and returns complete state.
- Log parser works for the one current dumped job (`Overview`) and matches
  settings/FOV/z-wide for that job.
- Log parity fails for job enumeration and selected-job mapping because the log
  contains only a partial job dump and stale selection data.

### Direct probe after rerun

```text
raw no-age log jobs: ['Overview']
raw no-age selected: None

mode='api':
  jobs=['AF Job', 'Overview', 'HiRes']
  selected='Overview'
  xy=(55137.56, 37912.29) um

mode='log':
  jobs=None/[]
  selected=None
  xy=None

mode='both':
  jobs=['AF Job', 'Overview', 'HiRes']
  selected='Overview'
  xy=(55137.56, 37912.29) um
```

Interpretation: `both` mode is the robust default candidate because it rescues
through API when log data is stale or partial. Pure `log` is not sufficient for
default passive reads on this microscope in the current idle/partial-log state.

## Open Items / Recommendations

1. **Side-by-side harness fix: done locally.** The first column now pins
   `mode="api"` so it actually compares API vs log on this branch.
2. **Decide on log-default safety:** a passive log read that returns
   empty/None on an idle scope means downstream code sees "no jobs / no XY".
   Confirm callers treat that as "unknown" and fall back to API, not as a real
   empty state. Consider defaulting passive reads to `both` (log with API
   rescue) instead of pure `log`.
3. **Re-test during active acquisition:** verify whether log freshness/parity
   improves when LAS X is actively dumping its log, before judging the log
   backend complete.
4. Still to run from the plan: Test 1 full (writes), Test 3 (explicit
   `--state-reader-mode log`), Test 4 reversible-write / job-switch, Test 5
   native AutoSave save smoke, Test 6 preflight, Test 7 NE override.

## Follow-up: More Robust Log Parsing

Question raised: maybe this microscope writes different logs and the parser
needs to be better. **Yes.** The previous parser was too narrow for job
enumeration on this machine.

### What was different

The old `log_reader.get_jobs()` inferred the job list from
`ATL_GetBlockApiInfoAsJsonString` dumps. On this LAS X session those ATL dumps
are **per-job settings** and are only written for jobs whose settings were
queried. That explains the partial list:

```text
ATL settings blocks seen in lcsCommand.log:
  HiRes
  Overview
```

But the same log also contains a better source:

```text
GetMatrixCollectionPatternInfo '<Result ...>
  BlockId=4 BlockName=AF Job
  BlockId=6 BlockName=Overview
  BlockId=8 BlockName=HiRes
</Result>'
```

`MatrixScreener.log` also carries selected/current block state:

```text
CurrentBlock/Name = Overview
CurrentBlock/BlockID = 6
```

### Code change

Updated `state_readers/log_reader.py` to:

- Parse `GetMatrixCollectionPatternInfo` XML from `lcsCommand.log`.
- Use that as the preferred full job-list source.
- Keep `ATL_GetBlockApiInfoAsJsonString` as the detailed job-settings source.
- Parse `CurrentBlock/Name` and `CurrentBlock/BlockID` from
  `MatrixScreener.log`.
- Mark `IsSelected` from either `SetCurrentSelectedElementID` or current-block
  name/ID when the mapping is unambiguous.
- Preserve previous fail-closed behavior for partial ATL clusters.

Updated `state_readers/router.py` so diagnostics for `get_jobs()` include the
new full job-list age (`job_list`).

Added unit coverage in `test_log_reader.py` for:

- XML matrix job summaries.
- Full job list plus selected-job mapping.
- Age-gated refusal of stale matrix summaries.
- Current-block selected-job mapping.

### Test results after parser update

Offline:

```text
python -m pytest driver/vendor/leica/navigator_expert/tests/unit/test_log_reader.py -q
26 passed

python -m pytest \
  driver/vendor/leica/navigator_expert/tests/unit/test_state_readers.py \
  driver/vendor/leica/navigator_expert/tests/unit/test_log_reader.py -q
38 passed

py_compile log_reader.py router.py validate_readers_side_by_side.py
OK

git diff --check
OK
```

Live raw log probe after parser update:

```text
matrix jobs, no age gate:
  [('AF Job', 4, False), ('Overview', 6, True), ('HiRes', 8, False)]

current block:
  Overview / 6

ATL settings blocks:
  HiRes, Overview
```

Corrected side-by-side read-only result after parser update:

```text
SUMMARY: parity 7/10  API timeouts/hangs=0

OK  get_xy
OK  get_jobs (names)          api=['AF Job', 'HiRes', 'Overview']
                              log=['AF Job', 'HiRes', 'Overview']
OK  get_selected_job          api=['Overview'] log=['Overview']
OK  get_scan_status
OK  get_hardware_info
XX  settings[AF Job]          api=True log=False
XX  settings[HiRes]           api=True log=False
XX  settings[Overview]        one z-galvo field differed
OK  get_fov[Overview]
OK  read_zwide_um[Overview]
```

Interpretation:

- The log parser now handles this machine's full job-list format correctly.
- The remaining log parity gap is detailed job settings, not job enumeration.
  LAS X only logs detailed settings for jobs queried through the API, and those
  settings can still be absent/stale.

### Validator result after parser update

Default/profile mode and explicit `log` mode still fail to resolve jobs under
the current profile because the routed readers enforce very tight age gates:

```text
jobs_log_max_age_s = 2.0
job_settings_log_max_age_s = 2.0
xy_log_max_age_s = 1.0
scan_status_log_max_age_s = 0.5
```

Observed:

```text
default profile: pass=7 warn=0 fail=0 skip=1
  SKIP | job: resolve -- no jobs returned

explicit log: pass=7 warn=0 fail=1 skip=0
  FAIL | job: resolve -- no jobs returned with --state-reader-mode log

explicit both: pass=9 warn=0 fail=0 skip=0

temporary pure-log profile with 3600 s age gates:
  pass=9 warn=0 fail=0 skip=0
```

Conclusion:

- Parser robustness is improved and job-list parity is fixed.
- Pure `log` defaults are still not robust with sub-2-second age gates on an
  idle microscope.
- `both` is useful as a diagnostic control, but it is still experimental and
  should not be treated as the production default without a separate decision.
- Pure log can pass if the age policy is relaxed, but blindly widening all age
  gates can accept stale scan status / XY / settings. A safer non-experimental
  direction is to split the policies:
  - full job-list summaries can probably tolerate a longer passive age;
  - scan status and XY should stay fresh or remain API-backed;
  - detailed job settings need a clear stale-data policy because LAS X only
    logs them for jobs whose settings were queried.

## Latest API vs Log Hardware Validator Rerun

Date/time: 2026-06-04 23:58

All runs were read-only.

API mode:

```text
validate_hardware.py --yes --read-only --state-reader-mode api
pass=9 warn=0 fail=0 skip=0
```

Explicit log mode with the current branch age gates:

```text
validate_hardware.py --yes --read-only --state-reader-mode log
pass=7 warn=0 fail=1 skip=0
FAIL | job: resolve -- no jobs returned with --state-reader-mode log
```

Direct parser probe from the same log state:

```text
jobs no_age = [('AF Job', False), ('Overview', True), ('HiRes', False)]
jobs age_2  = None
xy age_1    = None
hardware age_2 = False

ages:
  xy=34s
  job_list=1201s
  hardware_info=34s
  selected/current_block=1494s
  scan_status=2802s
```

Pure log with a temporary 3600 s age policy:

```text
validate_hardware.py --yes --read-only
profile override: all passive modes=log, all log max ages=3600s
pass=9 warn=0 fail=0 skip=0
```

Interpretation:

- API mode is healthy.
- The improved parser can extract the full job list and selected job.
- Current explicit log mode still fails because the freshness policy is too
  strict for an idle microscope, not because the parser misses the job list.
- A non-experimental next step is a more nuanced pure-log age policy, not
  defaulting to experimental `both`.

## Retry After Midnight

Date/time: 2026-06-05 00:00-00:01

All runs were read-only. `127.0.0.1:8896` was listening, owned by
`NavigatorExpert`.

API mode:

```text
validate_hardware.py --yes --read-only --state-reader-mode api
pass=9 warn=0 fail=0 skip=0
```

Explicit log mode with current branch age gates:

```text
validate_hardware.py --yes --read-only --state-reader-mode log
pass=7 warn=0 fail=1 skip=0
FAIL | job: resolve -- no jobs returned with --state-reader-mode log
```

Direct parser probe:

```text
jobs no_age = [('AF Job', False), ('Overview', True), ('HiRes', False)]
jobs age_2  = None
selected no_age = Overview
selected age_2  = None
xy age_1 = None
hardware age_2 = False
scan age_0_5 = Unknown

ages:
  xy=29s
  job_list=1366s
  hardware_info=29s
  selected/current_block=59s
  scan_status=2967s
```

Temporary pure-log profile with 3600 s age gates:

```text
pass=9 warn=0 fail=0 skip=0
```

Interpretation unchanged:

- API mode is healthy.
- The improved parser sees the full job list and selected job.
- Explicit log mode fails only because the current freshness gates reject the
  values before `job: resolve`.
- Pure log can validate when the age policy is relaxed, so the next fix should
  be an explicit pure-log freshness policy per datum.

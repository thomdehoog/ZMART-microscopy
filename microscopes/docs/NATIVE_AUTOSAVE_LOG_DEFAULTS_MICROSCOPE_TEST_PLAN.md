# Native AutoSave + Log Defaults Microscope Test Plan

Branch: `defaults/native-autosave-log`

Base context:
- This branch starts from the PF-only LAS X runtime branch.
- Leica CAM API DLLs are no longer in the repo or the Python env.
- The driver loads the CAM API runtime from:
  `C:\Program Files\Leica Microsystems CMS GmbH\LAS X\AddIns\NavigatorExpert`
- `profiles.LASX_API.delay_ms` remains `250`.

## What Changed On This Branch

1. Default save exporter is now native AutoSave:
   - `navigator_expert.acquisition.save.save(..., exporter=...)` defaults to
     `lasx_native_autosave`.
   - Target-acquisition `Config.save_exporter` defaults to
     `lasx_native_autosave`.
   - `navigator_expert` remains available as an explicit override.

2. Passive state-reader defaults now use the log reader:
   - `xy_mode = "log"`
   - `job_settings_mode = "log"`
   - `jobs_mode = "log"`
   - `hardware_info_mode = "log"`
   - `scan_status_mode = "log"`

3. Safety-critical reads still pin API:
   - command prechecks
   - command early exits
   - command-parameterizing reads
   - confirmations and post-write readbacks
   - calibration geometry
   - canonical OME physical metadata

The log reader default is only for passive/cold state reads. A log value must
not decide whether a command fires or what metadata/calibration is persisted.

## Already Run Off The Microscope

Focused tests:

```powershell
python -m pytest `
  driver/vendor/leica/navigator_expert/tests/unit/test_state_readers.py `
  driver/vendor/leica/navigator_expert/tests/unit/test_acquisition.py `
  driver/vendor/leica/navigator_expert/tests/unit/test_native_autosave.py `
  workflows/vendor/leica/navigator_expert/target_acquisition/tests/test_preflight.py `
  --tb=short -q
```

Result:

```text
73 passed
```

Broad driver/workflow tests:

```powershell
python -m pytest `
  driver/vendor/leica/navigator_expert/tests/unit `
  workflows/vendor/leica/navigator_expert/target_acquisition/tests `
  --tb=short -q
```

Result:

```text
641 passed, 8 warnings, 56 subtests passed
```

## Microscope Preconditions

Before testing native AutoSave default:

1. LAS X is running and the CAM API connects.
2. Native AutoSave is enabled in LAS X.
3. The native AutoSave base folder exists, for example:
   `C:\Users\t.de\lasx_probes\test`
4. It is OK if Navigator Expert export is disabled; this branch is meant to
   work through native AutoSave by default.
5. Do not delete native AutoSave project/cache files mid-run. Cleanup remains
   operator/LAS X managed.

Expected SMART output root for native AutoSave default:

```text
C:\Users\t.de\lasx_probes\smart
```

assuming the native AutoSave base folder is:

```text
C:\Users\t.de\lasx_probes\test
```

Manual `smart_output_root` still wins if configured.

## Test 1: Confirm Runtime Still Loads From Program Files

Run:

```powershell
C:\ProgramData\MinicondaZMB\envs\smart_lasx_pf_only_fresh\python.exe `
  driver/vendor/leica/navigator_expert/tests/hardware/validate_hardware.py `
  --yes `
  --state-reader-mode api `
  --output C:\Users\t.de\AppData\Local\Temp\native_log_defaults_api_control.jsonl
```

Expected:

```text
runtime=C:\Program Files\Leica Microsystems CMS GmbH\LAS X\AddIns\NavigatorExpert
version=1.0.108.0
api_delay_ms=250
pass=66 warn=0 fail=0 skip=5
```

Purpose:
- API-mode control run.
- Confirms the PF-only runtime still works before testing log defaults.

## Test 2: Validate Default Profile With Log Readers

Run without `--state-reader-mode`, so it uses the branch defaults:

```powershell
C:\ProgramData\MinicondaZMB\envs\smart_lasx_pf_only_fresh\python.exe `
  driver/vendor/leica/navigator_expert/tests/hardware/validate_hardware.py `
  --yes `
  --output C:\Users\t.de\AppData\Local\Temp\native_log_defaults_profile.jsonl
```

Expected ideal result:

```text
pass=66 warn=0 fail=0 skip=5
```

If this fails early on passive reads such as `get_jobs`, `get_hardware_info`,
or `get_scan_status`, keep the JSONL and console output. That means the log
default is not yet complete enough for that passive reader on the real system.
The safety-critical command paths should still be protected by API pins.

## Test 3: Explicit Log-Mode Validator Run

Run:

```powershell
C:\ProgramData\MinicondaZMB\envs\smart_lasx_pf_only_fresh\python.exe `
  driver/vendor/leica/navigator_expert/tests/hardware/validate_hardware.py `
  --yes `
  --state-reader-mode log `
  --output C:\Users\t.de\AppData\Local\Temp\native_log_defaults_log_explicit.jsonl
```

Expected:
- Ideally matches Test 2.
- If it fails, note the first failing passive reader and reason.

Purpose:
- Makes it explicit that log-only passive reads can or cannot support the full
  validator.
- This separates "profile default issue" from "log backend completeness issue."

## Test 4: API-vs-Log Reader Comparison

Run the side-by-side reader validator. This compares API and log values for
the same live microscope state instead of only running separate API/log
validator passes.

Read-only comparison first:

```powershell
C:\ProgramData\MinicondaZMB\envs\smart_lasx_pf_only_fresh\python.exe `
  driver/vendor/leica/navigator_expert/tests/hardware/validate_readers_side_by_side.py `
  --read-only
```

Optional reversible-write comparison:

```powershell
C:\ProgramData\MinicondaZMB\envs\smart_lasx_pf_only_fresh\python.exe `
  driver/vendor/leica/navigator_expert/tests/hardware/validate_readers_side_by_side.py `
  --yes
```

Optional job-switch comparison, only if the objective dialog / job switch is
safe to exercise:

```powershell
C:\ProgramData\MinicondaZMB\envs\smart_lasx_pf_only_fresh\python.exe `
  driver/vendor/leica/navigator_expert/tests/hardware/validate_readers_side_by_side.py `
  --yes `
  --allow-job-switch
```

Expected:
- API and log agree for the passive readers that are now log defaults.
- If they differ, record which reader diverged and whether the log value was
  absent, stale, partial, or different.
- A missing/partial log value is useful evidence; do not patch around it during
  this test.

Purpose:
- Proves log parity per passive reader, not just that the full validator can
  still pass.
- Identifies which log default, if any, is not ready for production on the real
  microscope.

## Test 5: Native AutoSave Default Save Smoke

This is the most important default-exporter test.

Setup:
- Native AutoSave enabled.
- Navigator Expert export may be disabled.
- Use a job that produces a known native AutoSave OME-TIFF.

Run a minimal acquire/save through the public API from a Python prompt or
small scratch script:

```python
import sys
from pathlib import Path

repo = Path(r"Z:\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy")
sys.path.insert(0, str(repo / "driver" / "vendor" / "leica"))

import navigator_expert as drv
from shared.output_layout import Naming, run_hash

client = drv.connect_python_client()
job = (drv.get_selected_job(client, mode="api") or {})["Name"]

acq = drv.acquire(client, job)
naming = Naming(acquisition_type="native-default-smoke", hash6=run_hash(), p=0)
out = Path(r"C:\Users\t.de\lasx_probes\smart") / "native_default_smoke"

saved = drv.save(client, acq, out, naming)
print("images", len(saved.image_paths))
print("xml", len(saved.xml_paths))
print("output", out)
```

Expected:
- `drv.save(...)` uses `lasx_native_autosave` without passing `exporter=...`.
- At least one canonical `.ome.tiff` is written.
- At least one companion `.ome.xml` is written.
- `summary.json` records `source_exporter = "lasx_native_autosave"`.
- Output is under the native SMART root, not the Navigator Expert media path,
  unless `out` is manually set as above.

## Test 6: Target-Acquisition Preflight Default

Use the normal target-acquisition notebook/config path and do not set
`save_exporter`.

Expected:
- `Config.save_exporter` is `lasx_native_autosave`.
- Preflight derives SMART output beside the native AutoSave base folder:
  `<native base parent>\smart`.
- Preflight fails early if native AutoSave is disabled.

If preflight fails because native AutoSave is disabled, that is correct behavior
for this branch.

## Test 7: Manual Navigator Expert Override Still Works

Only run this if Navigator Expert export is enabled.

Set:

```python
cfg.save_exporter = "navigator_expert"
```

Expected:
- SMART output root returns to `<Navigator MediaPath>\smart`.
- Save uses the Navigator Expert collector.

Purpose:
- Confirms Navigator Expert remains available as an explicit fallback.

## What To Report Back

Please report:

1. Test 1 summary line.
2. Test 2 summary line and first failure, if any.
3. Test 3 summary line and first failure, if any.
4. Test 4 side-by-side summary:
   - read-only result
   - reversible-write result, if run
   - job-switch result, if run
   - any API/log divergence by reader
5. For Test 5:
   - job name
   - output path
   - image count
   - XML count
   - `summary.json` `source_exporter`
6. Whether Navigator Expert export was on or off during native AutoSave tests.
7. Whether native AutoSave base folder was:
   `C:\Users\t.de\lasx_probes\test`

## Stop Rules

Stop and keep logs if:

- native AutoSave collector cannot find the newly acquired OME-TIFF
- default profile validation fails on passive log reads
- `summary.json` does not say `lasx_native_autosave`
- output appears under the Navigator Expert media path when no manual output root
  was requested

Do not debug by deleting native AutoSave project/cache files mid-run.

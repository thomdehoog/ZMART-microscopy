# Hardware validation run report

Every change this run attempted on the instrument is listed below, including failed attempts and restore/cleanup steps (see the *Mutates scope* column). Changes carry their success+CONFIRMED / success+UNCONFIRMED / FAILED result and attempt counts in the *Result* column.

## Run metadata

- **Validator**: `validate_readers_side_by_side`
- **Arguments**: `--yes --report-dir=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report`
- **Backend**: live LAS X (simulator or scope)
- **Date**: 2026-07-06
- **Started / finished**: 11:17:29 / 11:17:34 (5.2s)
- **Host**: ZMB-LASX-PC (Windows-10-10.0.26200-SP0)
- **Python**: 3.11.15
- **Driver commit**: unknown on unknown
- **Driver log**: `\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\driver_log_20260706-111729.log` (full log-line capture)

## Summary

| Phase | Actions attempted | Passed | Warned | Failed | Skipped | Confirmed | Unconfirmed |
|---|---:|---:|---:|---:|---:|---:|---:|
| read-only parity | 8 | 7 | 0 | 1 | 0 | 0 | 0 |
| routed reader modes | 30 | 22 | 0 | 2 | 6 | 0 | 0 |
| live changes (reversible) | 8 | 8 | 0 | 0 | 0 | 8 | 0 |
| **total** | **46** | **37** | **0** | **3** | **6** | **8** | **0** |

## Timing overview

### Per phase

| Phase | Timed actions | Min | Median | Max |
|---|---:|---:|---:|---:|
| read-only parity | 2 | 0.018s | 0.018s | 0.018s |
| routed reader modes | 18 | 0.001s | 0.046s | 0.054s |
| live changes (reversible) | 8 | 0.016s | 0.035s | 0.078s |

### Per reader mode (routed read latency)

| Mode | Reads | Min | Median | Max | Median reading age |
|---|---:|---:|---:|---:|---:|
| api | 6 | 0.001s | 0.012s | 0.015s | 0.000s |
| log | 6 | 0.045s | 0.046s | 0.048s | 0.499s |
| hybrid | 6 | 0.049s | 0.051s | 0.054s | 0.094s |

### Slowest actions

| Duration | Phase | Action | Status |
|---:|---|---|---|
| 0.078s | live changes (reversible) | change[pinhole_airy] -> 1.2 | PASS |
| 0.055s | live changes (reversible) | change[image_format] -> 1024 x 1024 | PASS |
| 0.054s | routed reader modes | read[xy] mode=hybrid | PASS |
| 0.053s | live changes (reversible) | change[zoom] -> 5.0 | PASS |
| 0.051s | routed reader modes | read[selected_job] mode=hybrid | PASS |
| 0.051s | live changes (reversible) | change[scan_speed] -> 600 | PASS |
| 0.051s | routed reader modes | read[hardware_info] mode=hybrid | PASS |
| 0.051s | routed reader modes | read[job_settings] mode=hybrid | PASS |
| 0.049s | routed reader modes | read[jobs] mode=hybrid | PASS |
| 0.049s | routed reader modes | read[scan_status] mode=hybrid | PASS |

### Unconfirmed / failed changes

None -- every attempted change reported success and confirmed.

## Chronological detail (every attempted action)

| # | Time | Phase | Status | Result | Mutates scope | Action attempted | Args / target | Expected | Observed | Duration |
|---:|---|---|---|---|---|---|---|---|---|---:|
| 1 | 11:17:29.898 | read-only parity | PASS |  |  | get_xy |  |  | api=18ms log_age=2s | 0.018s |
| 2 | 11:17:29.916 | read-only parity | FAIL |  |  | get_jobs (names) |  |  | api=['AF Job', 'HiRes', 'Overview'] log=['Overview'] | 0.018s |
| 3 | 11:17:29.916 | read-only parity | PASS |  |  | get_selected_job |  |  | api=['Overview'] log=['Overview'] | 0.000s |
| 4 | 11:17:29.916 | read-only parity | PASS |  |  | get_scan_status (idle-sense) |  |  | api='eScanIdle' log='eScanIdle' log_age=257461s | 0.000s |
| 5 | 11:17:29.934 | read-only parity | PASS |  |  | get_hardware_info (Microscope.name) |  |  |  | 0.000s |
| 6 | 11:17:29.950 | read-only parity | PASS |  |  | settings[Overview] (70 fields) |  |  | log_age=2s | 0.000s |
| 7 | 11:17:29.965 | read-only parity | PASS |  |  | get_fov[Overview] |  |  | api=(0.00116, 0.00116) log=(0.00116, 0.00116) | 0.000s |
| 8 | 11:17:29.981 | read-only parity | PASS |  |  | read_zwide_um[Overview] |  |  | api=-7200.0 log=-7200.0 | 0.000s |
| 9 | 11:17:29.993 | routed reader modes | PASS |  |  | read[xy] mode=api |  |  | value=(0.0,0.0)um source=api age=0.00s latency=12ms | 0.012s |
| 10 | 11:17:30.027 | routed reader modes | SKIP |  |  | read[xy] mode=log |  |  | no trusted log value (stale/absent log stream; router fails closed) | 0.048s |
| 11 | 11:17:30.095 | routed reader modes | PASS |  |  | read[xy] mode=hybrid |  |  | value=(0.0,0.0)um source=api age=0.00s latency=54ms | 0.054s |
| 12 | 11:17:30.095 | routed reader modes | SKIP |  |  | agree[xy] api vs log |  |  | insufficient values to cross-check | 0.000s |
| 13 | 11:17:30.095 | routed reader modes | PASS |  |  | agree[xy] api vs hybrid |  |  | delta=(0.00,0.00)um tol=1.0um | 0.000s |
| 14 | 11:17:30.110 | routed reader modes | PASS |  |  | read[jobs] mode=api |  |  | value=['AF Job', 'HiRes', 'Overview'] source=api age=0.00s latency=15ms | 0.015s |
| 15 | 11:17:30.158 | routed reader modes | PASS |  |  | read[jobs] mode=log |  |  | value=['Overview'] source=log age=0.14s latency=48ms | 0.048s |
| 16 | 11:17:30.205 | routed reader modes | PASS |  |  | read[jobs] mode=hybrid |  |  | value=['Overview'] source=log age=0.19s latency=49ms | 0.049s |
| 17 | 11:17:30.205 | routed reader modes | FAIL |  |  | agree[jobs] api vs log |  |  | ['AF Job', 'HiRes', 'Overview'] vs ['Overview'] | 0.000s |
| 18 | 11:17:30.205 | routed reader modes | FAIL |  |  | agree[jobs] api vs hybrid |  |  | ['AF Job', 'HiRes', 'Overview'] vs ['Overview'] | 0.000s |
| 19 | 11:17:30.220 | routed reader modes | PASS |  |  | read[selected_job] mode=api |  |  | value='Overview' source=api age=0.00s latency=12ms | 0.012s |
| 20 | 11:17:30.264 | routed reader modes | SKIP |  |  | read[selected_job] mode=log |  |  | no trusted log value (stale/absent log stream; router fails closed) | 0.045s |
| 21 | 11:17:30.317 | routed reader modes | PASS |  |  | read[selected_job] mode=hybrid |  |  | value='Overview' source=api age=0.00s latency=51ms | 0.051s |
| 22 | 11:17:30.317 | routed reader modes | SKIP |  |  | agree[selected_job] api vs log |  |  | insufficient values to cross-check | 0.000s |
| 23 | 11:17:30.317 | routed reader modes | PASS |  |  | agree[selected_job] api vs hybrid |  |  | 'Overview' vs 'Overview' | 0.000s |
| 24 | 11:17:30.317 | routed reader modes | PASS |  |  | read[scan_status] mode=api |  |  | value='eScanIdle' source=api age=0.00s latency=1ms | 0.001s |
| 25 | 11:17:30.359 | routed reader modes | SKIP |  |  | read[scan_status] mode=log |  |  | no trusted log value (stale/absent log stream; router fails closed) | 0.045s |
| 26 | 11:17:30.411 | routed reader modes | PASS |  |  | read[scan_status] mode=hybrid |  |  | value='eScanIdle' source=api age=0.00s latency=49ms | 0.049s |
| 27 | 11:17:30.411 | routed reader modes | SKIP |  |  | agree[scan_status] api vs log |  |  | insufficient values to cross-check | 0.000s |
| 28 | 11:17:30.411 | routed reader modes | PASS |  |  | agree[scan_status] api vs hybrid |  |  | 'eScanIdle' vs 'eScanIdle' (idle-sense) | 0.000s |
| 29 | 11:17:30.424 | routed reader modes | PASS |  |  | read[hardware_info] mode=api |  |  | value=Microscope='DM Manual-6' source=api age=0.00s latency=12ms | 0.012s |
| 30 | 11:17:30.469 | routed reader modes | PASS |  |  | read[hardware_info] mode=log |  |  | value=Microscope='DM Manual-6' source=log age=0.50s latency=46ms | 0.046s |
| 31 | 11:17:30.521 | routed reader modes | PASS |  |  | read[hardware_info] mode=hybrid |  |  | value=Microscope='DM Manual-6' source=log age=0.55s latency=51ms | 0.051s |
| 32 | 11:17:30.521 | routed reader modes | PASS |  |  | agree[hardware_info] api vs log |  |  | 'DM Manual-6' vs 'DM Manual-6' | 0.000s |
| 33 | 11:17:30.521 | routed reader modes | PASS |  |  | agree[hardware_info] api vs hybrid |  |  | 'DM Manual-6' vs 'DM Manual-6' | 0.000s |
| 34 | 11:17:30.535 | routed reader modes | PASS |  |  | read[job_settings] mode=api |  |  | value=70 contract fields source=api age=0.00s latency=14ms | 0.014s |
| 35 | 11:17:30.580 | routed reader modes | PASS |  |  | read[job_settings] mode=log |  |  | value=70 contract fields source=log age=0.57s latency=46ms | 0.046s |
| 36 | 11:17:30.632 | routed reader modes | PASS |  |  | read[job_settings] mode=hybrid |  |  | value=70 contract fields source=log age=0.61s latency=51ms | 0.051s |
| 37 | 11:17:30.632 | routed reader modes | PASS |  |  | agree[job_settings] api vs log |  |  | all contract fields agree | 0.000s |
| 38 | 11:17:30.632 | routed reader modes | PASS |  |  | agree[job_settings] api vs hybrid |  |  | all contract fields agree | 0.000s |
| 39 | 11:17:31.183 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | change[zoom] -> 5.0 | job='Overview' target=5.0 (was 1.0) | 5.0 | set=31ms api=22ms log=491ms earlier=api | 0.053s |
| 40 | 11:17:31.200 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | restore[zoom] -> 1.0 | job='Overview' restore_to=1.0 | 1.0 | restore=16ms | 0.016s |
| 41 | 11:17:32.187 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | change[scan_speed] -> 600 | job='Overview' target=600 (was 400) | 600 | set=27ms api=25ms log=943ms earlier=api | 0.051s |
| 42 | 11:17:32.204 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | restore[scan_speed] -> 400 | job='Overview' restore_to=400 | 400 | restore=16ms | 0.016s |
| 43 | 11:17:33.277 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | change[image_format] -> 1024 x 1024 | job='Overview' target='1024 x 1024' (was '512 x 512') | 1024 x 1024 | set=31ms api=24ms log=938ms earlier=api | 0.055s |
| 44 | 11:17:33.295 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | restore[image_format] -> 512 x 512 | job='Overview' restore_to='512 x 512' | 512 x 512 | restore=19ms | 0.019s |
| 45 | 11:17:34.376 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | change[pinhole_airy] -> 1.2 | job='Overview' target=1.2 (was 1.0) | 1.2 | set=28ms api=50ms log=949ms earlier=api | 0.078s |
| 46 | 11:17:34.392 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | restore[pinhole_airy] -> 1.0 | job='Overview' restore_to=1.0 | 1.0 | restore=17ms | 0.017s |

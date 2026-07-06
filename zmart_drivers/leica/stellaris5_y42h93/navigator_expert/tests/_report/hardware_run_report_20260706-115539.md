# Hardware validation run report

Every change this run attempted on the instrument is listed below, including failed attempts and restore/cleanup steps (see the *Mutates scope* column). Changes carry their success+CONFIRMED / success+UNCONFIRMED / FAILED result and attempt counts in the *Result* column.

## Run metadata

- **Validator**: `validate_readers_side_by_side`
- **Arguments**: `--yes --report-dir=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report`
- **Backend**: live LAS X (simulator or scope)
- **Date**: 2026-07-06
- **Started / finished**: 11:55:39 / 11:55:44 (5.0s)
- **Host**: ZMB-LASX-PC (Windows-10-10.0.26200-SP0)
- **Python**: 3.11.15
- **Driver commit**: unknown on unknown
- **Driver log**: `\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\driver_log_20260706-115539.log` (full log-line capture)

## Summary

| Phase | Actions attempted | Passed | Warned | Failed | Skipped | Confirmed | Unconfirmed |
|---|---:|---:|---:|---:|---:|---:|---:|
| read-only parity | 8 | 7 | 0 | 1 | 0 | 0 | 0 |
| routed reader modes | 30 | 20 | 0 | 0 | 10 | 0 | 0 |
| live changes (reversible) | 8 | 8 | 0 | 0 | 0 | 8 | 0 |
| **total** | **46** | **35** | **0** | **1** | **10** | **8** | **0** |

## Timing overview

### Per phase

| Phase | Timed actions | Min | Median | Max |
|---|---:|---:|---:|---:|
| read-only parity | 2 | 0.017s | 0.017s | 0.017s |
| routed reader modes | 18 | 0.000s | 0.066s | 0.075s |
| live changes (reversible) | 8 | 0.015s | 0.040s | 0.068s |

### Per reader mode (routed read latency)

| Mode | Reads | Min | Median | Max | Median reading age |
|---|---:|---:|---:|---:|---:|
| api | 6 | 0.001s | 0.013s | 0.017s | 0.000s |
| log | 6 | 0.000s | 0.067s | 0.070s | 0.102s |
| hybrid | 6 | 0.013s | 0.072s | 0.075s | 0.000s |

### Slowest actions

| Duration | Phase | Action | Status |
|---:|---|---|---|
| 0.075s | routed reader modes | read[selected_job] mode=hybrid | PASS |
| 0.074s | routed reader modes | read[scan_status] mode=hybrid | PASS |
| 0.073s | routed reader modes | read[job_settings] mode=hybrid | PASS |
| 0.071s | routed reader modes | read[hardware_info] mode=hybrid | PASS |
| 0.070s | routed reader modes | read[scan_status] mode=log | SKIP |
| 0.069s | routed reader modes | read[xy] mode=hybrid | PASS |
| 0.068s | live changes (reversible) | change[zoom] -> 5.0 | PASS |
| 0.067s | routed reader modes | read[selected_job] mode=log | SKIP |
| 0.067s | routed reader modes | read[job_settings] mode=log | SKIP |
| 0.066s | routed reader modes | read[xy] mode=log | PASS |

### Unconfirmed / failed changes

None -- every attempted change reported success and confirmed.

## Chronological detail (every attempted action)

| # | Time | Phase | Status | Result | Mutates scope | Action attempted | Args / target | Expected | Observed | Duration |
|---:|---|---|---|---|---|---|---|---|---|---:|
| 1 | 11:55:40.687 | read-only parity | PASS |  |  | get_xy |  |  | api=17ms log_age=2s | 0.017s |
| 2 | 11:55:40.704 | read-only parity | FAIL |  |  | get_jobs (names) |  |  | api=['AF Job', 'HiRes', 'Overview'] log=['Overview'] | 0.017s |
| 3 | 11:55:40.704 | read-only parity | PASS |  |  | get_selected_job |  |  | api=['Overview'] log=['Overview'] | 0.000s |
| 4 | 11:55:40.707 | read-only parity | PASS |  |  | get_scan_status (idle-sense) |  |  | api='eScanIdle' log='eScanIdle' log_age=1976s | 0.000s |
| 5 | 11:55:40.719 | read-only parity | PASS |  |  | get_hardware_info (Microscope.name) |  |  |  | 0.000s |
| 6 | 11:55:40.736 | read-only parity | PASS |  |  | settings[Overview] (70 fields) |  |  | log_age=2s | 0.000s |
| 7 | 11:55:40.749 | read-only parity | PASS |  |  | get_fov[Overview] |  |  | api=(0.00058125, 0.00058125) log=(0.00058125, 0.00058125) | 0.000s |
| 8 | 11:55:40.765 | read-only parity | PASS |  |  | read_zwide_um[Overview] |  |  | api=-7200.0 log=-7200.0 | 0.000s |
| 9 | 11:55:40.777 | routed reader modes | PASS |  |  | read[xy] mode=api |  |  | value=(64220.0,41180.0)um source=api age=0.00s latency=12ms | 0.012s |
| 10 | 11:55:40.843 | routed reader modes | PASS |  |  | read[xy] mode=log |  |  | value=(64220.0,41180.0)um source=log age=0.10s latency=66ms | 0.066s |
| 11 | 11:55:40.913 | routed reader modes | PASS |  |  | read[xy] mode=hybrid |  |  | value=(64220.0,41180.0)um source=log age=0.17s latency=69ms | 0.069s |
| 12 | 11:55:40.913 | routed reader modes | PASS |  |  | agree[xy] api vs log |  |  | delta=(0.00,0.00)um tol=1.0um | 0.000s |
| 13 | 11:55:40.913 | routed reader modes | PASS |  |  | agree[xy] api vs hybrid |  |  | delta=(0.00,0.00)um tol=1.0um | 0.000s |
| 14 | 11:55:40.926 | routed reader modes | PASS |  |  | read[jobs] mode=api |  |  | value=['AF Job', 'HiRes', 'Overview'] source=api age=0.00s latency=13ms | 0.013s |
| 15 | 11:55:40.926 | routed reader modes | SKIP |  |  | read[jobs] mode=log |  |  | no trusted log value (stale/absent log stream; router fails closed) err=UnsupportedSource("datum 'jobs' has no log leg") | 0.000s |
| 16 | 11:55:40.939 | routed reader modes | PASS |  |  | read[jobs] mode=hybrid |  |  | value=['AF Job', 'HiRes', 'Overview'] source=api age=0.00s latency=13ms | 0.013s |
| 17 | 11:55:40.939 | routed reader modes | SKIP |  |  | agree[jobs] api vs log |  |  | insufficient values to cross-check | 0.000s |
| 18 | 11:55:40.939 | routed reader modes | PASS |  |  | agree[jobs] api vs hybrid |  |  | ['AF Job', 'HiRes', 'Overview'] vs ['AF Job', 'HiRes', 'Overview'] | 0.000s |
| 19 | 11:55:40.951 | routed reader modes | PASS |  |  | read[selected_job] mode=api |  |  | value='Overview' source=api age=0.00s latency=12ms | 0.012s |
| 20 | 11:55:41.018 | routed reader modes | SKIP |  |  | read[selected_job] mode=log |  |  | no trusted log value (stale/absent log stream; router fails closed) | 0.067s |
| 21 | 11:55:41.094 | routed reader modes | PASS |  |  | read[selected_job] mode=hybrid |  |  | value='Overview' source=api age=0.00s latency=75ms | 0.075s |
| 22 | 11:55:41.094 | routed reader modes | SKIP |  |  | agree[selected_job] api vs log |  |  | insufficient values to cross-check | 0.000s |
| 23 | 11:55:41.094 | routed reader modes | PASS |  |  | agree[selected_job] api vs hybrid |  |  | 'Overview' vs 'Overview' | 0.000s |
| 24 | 11:55:41.095 | routed reader modes | PASS |  |  | read[scan_status] mode=api |  |  | value='eScanIdle' source=api age=0.00s latency=1ms | 0.001s |
| 25 | 11:55:41.165 | routed reader modes | SKIP |  |  | read[scan_status] mode=log |  |  | no trusted log value (stale/absent log stream; router fails closed) | 0.070s |
| 26 | 11:55:41.239 | routed reader modes | PASS |  |  | read[scan_status] mode=hybrid |  |  | value='eScanIdle' source=api age=0.00s latency=74ms | 0.074s |
| 27 | 11:55:41.239 | routed reader modes | SKIP |  |  | agree[scan_status] api vs log |  |  | insufficient values to cross-check | 0.000s |
| 28 | 11:55:41.239 | routed reader modes | PASS |  |  | agree[scan_status] api vs hybrid |  |  | 'eScanIdle' vs 'eScanIdle' (idle-sense) | 0.000s |
| 29 | 11:55:41.252 | routed reader modes | PASS |  |  | read[hardware_info] mode=api |  |  | value=Microscope='DM Manual-6' source=api age=0.00s latency=13ms | 0.013s |
| 30 | 11:55:41.318 | routed reader modes | SKIP |  |  | read[hardware_info] mode=log |  |  | no trusted log value (stale/absent log stream; router fails closed) | 0.066s |
| 31 | 11:55:41.390 | routed reader modes | PASS |  |  | read[hardware_info] mode=hybrid |  |  | value=Microscope='DM Manual-6' source=api age=0.00s latency=71ms | 0.071s |
| 32 | 11:55:41.390 | routed reader modes | SKIP |  |  | agree[hardware_info] api vs log |  |  | insufficient values to cross-check | 0.000s |
| 33 | 11:55:41.390 | routed reader modes | PASS |  |  | agree[hardware_info] api vs hybrid |  |  | 'DM Manual-6' vs 'DM Manual-6' | 0.000s |
| 34 | 11:55:41.406 | routed reader modes | PASS |  |  | read[job_settings] mode=api |  |  | value=70 contract fields source=api age=0.00s latency=17ms | 0.017s |
| 35 | 11:55:41.473 | routed reader modes | SKIP |  |  | read[job_settings] mode=log |  |  | no trusted log value (stale/absent log stream; router fails closed) | 0.067s |
| 36 | 11:55:41.547 | routed reader modes | PASS |  |  | read[job_settings] mode=hybrid |  |  | value=70 contract fields source=api age=0.00s latency=73ms | 0.073s |
| 37 | 11:55:41.547 | routed reader modes | SKIP |  |  | agree[job_settings] api vs log |  |  | insufficient values to cross-check | 0.000s |
| 38 | 11:55:41.547 | routed reader modes | PASS |  |  | agree[job_settings] api vs hybrid |  |  | all contract fields agree | 0.000s |
| 39 | 11:55:41.860 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | change[zoom] -> 5.0 | job='Overview' target=5.0 (was 2.0) | 5.0 | set=23ms api=44ms log=236ms earlier=api | 0.068s |
| 40 | 11:55:41.875 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | restore[zoom] -> 2.0 | job='Overview' restore_to=2.0 | 2.0 | restore=15ms | 0.015s |
| 41 | 11:55:42.840 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | change[scan_speed] -> 600 | job='Overview' target=600 (was 400) | 600 | set=20ms api=43ms log=919ms earlier=api | 0.063s |
| 42 | 11:55:42.857 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | restore[scan_speed] -> 400 | job='Overview' restore_to=400 | 400 | restore=17ms | 0.017s |
| 43 | 11:55:43.797 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | change[image_format] -> 1024 x 1024 | job='Overview' target='1024 x 1024' (was '512 x 512') | 1024 x 1024 | set=14ms api=49ms log=912ms earlier=api | 0.063s |
| 44 | 11:55:43.814 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | restore[image_format] -> 512 x 512 | job='Overview' restore_to='512 x 512' | 512 x 512 | restore=18ms | 0.018s |
| 45 | 11:55:44.910 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | change[pinhole_airy] -> 1.2 | job='Overview' target=1.2 (was 1.0) | 1.2 | set=20ms api=42ms log=1062ms earlier=api | 0.062s |
| 46 | 11:55:44.929 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | restore[pinhole_airy] -> 1.0 | job='Overview' restore_to=1.0 | 1.0 | restore=18ms | 0.018s |

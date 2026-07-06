# Hardware validation run report

Every change this run attempted on the instrument is listed below, including failed attempts and restore/cleanup steps (see the *Mutates scope* column). Changes carry their success+CONFIRMED / success+UNCONFIRMED / FAILED result and attempt counts in the *Result* column.

## Run metadata

- **Validator**: `validate_readers_side_by_side`
- **Arguments**: `--yes --report-dir=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report`
- **Backend**: live LAS X (simulator or scope)
- **Date**: 2026-07-06
- **Started / finished**: 13:26:09 / 13:26:15 (5.6s)
- **Host**: ZMB-LASX-PC (Windows-10-10.0.26200-SP0)
- **Python**: 3.11.15
- **Driver commit**: unknown on unknown
- **Driver log**: `\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\driver_log_20260706-132609.log` (full log-line capture)

## Summary

| Phase | Actions attempted | Passed | Warned | Failed | Skipped | Confirmed | Unconfirmed |
|---|---:|---:|---:|---:|---:|---:|---:|
| read-only parity | 8 | 7 | 0 | 0 | 1 | 0 | 0 |
| routed reader modes | 30 | 22 | 0 | 0 | 8 | 0 | 0 |
| live changes (reversible) | 8 | 8 | 0 | 0 | 0 | 8 | 0 |
| **total** | **46** | **37** | **0** | **0** | **9** | **8** | **0** |

## Timing overview

### Per phase

| Phase | Timed actions | Min | Median | Max |
|---|---:|---:|---:|---:|
| read-only parity | 2 | 0.019s | 0.019s | 0.020s |
| routed reader modes | 18 | 0.000s | 0.062s | 0.075s |
| live changes (reversible) | 8 | 0.016s | 0.045s | 0.066s |

### Per reader mode (routed read latency)

| Mode | Reads | Min | Median | Max | Median reading age |
|---|---:|---:|---:|---:|---:|
| api | 6 | 0.001s | 0.012s | 0.014s | 0.000s |
| log | 6 | 0.000s | 0.063s | 0.064s | 0.560s |
| hybrid | 6 | 0.013s | 0.065s | 0.075s | 0.000s |

### Slowest actions

| Duration | Phase | Action | Status |
|---:|---|---|---|
| 0.075s | routed reader modes | read[hardware_info] mode=hybrid | PASS |
| 0.066s | live changes (reversible) | change[zoom] -> 5.0 | PASS |
| 0.066s | routed reader modes | read[scan_status] mode=hybrid | PASS |
| 0.066s | routed reader modes | read[selected_job] mode=hybrid | PASS |
| 0.065s | routed reader modes | read[job_settings] mode=hybrid | PASS |
| 0.065s | routed reader modes | read[xy] mode=hybrid | PASS |
| 0.064s | routed reader modes | read[selected_job] mode=log | SKIP |
| 0.063s | routed reader modes | read[hardware_info] mode=log | PASS |
| 0.063s | routed reader modes | read[xy] mode=log | SKIP |
| 0.063s | routed reader modes | read[job_settings] mode=log | PASS |

### Unconfirmed / failed changes

None -- every attempted change reported success and confirmed.

## Chronological detail (every attempted action)

| # | Time | Phase | Status | Result | Mutates scope | Action attempted | Args / target | Expected | Observed | Duration |
|---:|---|---|---|---|---|---|---|---|---|---:|
| 1 | 13:26:10.449 | read-only parity | PASS |  |  | get_xy |  |  | api=19ms log_age=2s | 0.019s |
| 2 | 13:26:10.469 | read-only parity | SKIP |  |  | get_jobs (names) |  |  | no authoritative log leg for this datum (API-only); api=['AF Job', 'HiRes', 'Overview'] log=['Overview'] | 0.020s |
| 3 | 13:26:10.469 | read-only parity | PASS |  |  | get_selected_job |  |  | api='Overview' log='Overview' | 0.000s |
| 4 | 13:26:10.471 | read-only parity | PASS |  |  | get_scan_status (idle-sense) |  |  | api='eScanIdle' log='eScanIdle' log_age=7405s | 0.000s |
| 5 | 13:26:10.485 | read-only parity | PASS |  |  | get_hardware_info (Microscope.name) |  |  |  | 0.000s |
| 6 | 13:26:10.501 | read-only parity | PASS |  |  | settings[Overview] (70 fields) |  |  | log_age=2s | 0.000s |
| 7 | 13:26:10.518 | read-only parity | PASS |  |  | get_fov[Overview] |  |  | api=(0.00058125, 0.00058125) log=(0.00058125, 0.00058125) | 0.000s |
| 8 | 13:26:10.531 | read-only parity | PASS |  |  | read_zwide_um[Overview] |  |  | api=0.0 log=0.0 | 0.000s |
| 9 | 13:26:10.543 | routed reader modes | PASS |  |  | read[xy] mode=api |  |  | value=(64220.0,41180.0)um source=api age=0.00s latency=12ms | 0.012s |
| 10 | 13:26:10.605 | routed reader modes | SKIP |  |  | read[xy] mode=log |  |  | no trusted log value (stale/absent log stream; router fails closed) | 0.063s |
| 11 | 13:26:10.656 | routed reader modes | PASS |  |  | read[xy] mode=hybrid |  |  | value=(64220.0,41180.0)um source=api age=0.00s latency=65ms | 0.065s |
| 12 | 13:26:10.656 | routed reader modes | SKIP |  |  | agree[xy] api vs log |  |  | insufficient values to cross-check | 0.000s |
| 13 | 13:26:10.656 | routed reader modes | PASS |  |  | agree[xy] api vs hybrid |  |  | delta=(0.00,0.00)um tol=1.0um | 0.000s |
| 14 | 13:26:10.683 | routed reader modes | PASS |  |  | read[jobs] mode=api |  |  | value=['AF Job', 'HiRes', 'Overview'] source=api age=0.00s latency=12ms | 0.012s |
| 15 | 13:26:10.683 | routed reader modes | SKIP |  |  | read[jobs] mode=log |  |  | no trusted log value (stale/absent log stream; router fails closed) err=UnsupportedSource("datum 'jobs' has no log leg") | 0.000s |
| 16 | 13:26:10.696 | routed reader modes | PASS |  |  | read[jobs] mode=hybrid |  |  | value=['AF Job', 'HiRes', 'Overview'] source=api age=0.00s latency=13ms | 0.013s |
| 17 | 13:26:10.696 | routed reader modes | SKIP |  |  | agree[jobs] api vs log |  |  | insufficient values to cross-check | 0.000s |
| 18 | 13:26:10.696 | routed reader modes | PASS |  |  | agree[jobs] api vs hybrid |  |  | ['AF Job', 'HiRes', 'Overview'] vs ['AF Job', 'HiRes', 'Overview'] | 0.000s |
| 19 | 13:26:10.709 | routed reader modes | PASS |  |  | read[selected_job] mode=api |  |  | value='Overview' source=api age=0.00s latency=12ms | 0.012s |
| 20 | 13:26:10.773 | routed reader modes | SKIP |  |  | read[selected_job] mode=log |  |  | no trusted log value (stale/absent log stream; router fails closed) | 0.064s |
| 21 | 13:26:10.839 | routed reader modes | PASS |  |  | read[selected_job] mode=hybrid |  |  | value='Overview' source=api age=0.00s latency=66ms | 0.066s |
| 22 | 13:26:10.839 | routed reader modes | SKIP |  |  | agree[selected_job] api vs log |  |  | insufficient values to cross-check | 0.000s |
| 23 | 13:26:10.839 | routed reader modes | PASS |  |  | agree[selected_job] api vs hybrid |  |  | 'Overview' vs 'Overview' | 0.000s |
| 24 | 13:26:10.839 | routed reader modes | PASS |  |  | read[scan_status] mode=api |  |  | value='eScanIdle' source=api age=0.00s latency=1ms | 0.001s |
| 25 | 13:26:10.900 | routed reader modes | SKIP |  |  | read[scan_status] mode=log |  |  | no trusted log value (stale/absent log stream; router fails closed) | 0.062s |
| 26 | 13:26:10.968 | routed reader modes | PASS |  |  | read[scan_status] mode=hybrid |  |  | value='eScanIdle' source=api age=0.00s latency=66ms | 0.066s |
| 27 | 13:26:10.968 | routed reader modes | SKIP |  |  | agree[scan_status] api vs log |  |  | insufficient values to cross-check | 0.000s |
| 28 | 13:26:10.968 | routed reader modes | PASS |  |  | agree[scan_status] api vs hybrid |  |  | 'eScanIdle' vs 'eScanIdle' (idle-sense) | 0.000s |
| 29 | 13:26:10.981 | routed reader modes | PASS |  |  | read[hardware_info] mode=api |  |  | value=Microscope='DM Manual-6' source=api age=0.00s latency=13ms | 0.013s |
| 30 | 13:26:11.044 | routed reader modes | PASS |  |  | read[hardware_info] mode=log |  |  | value=Microscope='DM Manual-6' source=log age=0.51s latency=63ms | 0.063s |
| 31 | 13:26:11.120 | routed reader modes | PASS |  |  | read[hardware_info] mode=hybrid |  |  | value=Microscope='DM Manual-6' source=log age=0.57s latency=75ms | 0.075s |
| 32 | 13:26:11.120 | routed reader modes | PASS |  |  | agree[hardware_info] api vs log |  |  | 'DM Manual-6' vs 'DM Manual-6' | 0.000s |
| 33 | 13:26:11.120 | routed reader modes | PASS |  |  | agree[hardware_info] api vs hybrid |  |  | 'DM Manual-6' vs 'DM Manual-6' | 0.000s |
| 34 | 13:26:11.134 | routed reader modes | PASS |  |  | read[job_settings] mode=api |  |  | value=70 contract fields source=api age=0.00s latency=14ms | 0.014s |
| 35 | 13:26:11.194 | routed reader modes | PASS |  |  | read[job_settings] mode=log |  |  | value=70 contract fields source=log age=0.61s latency=63ms | 0.063s |
| 36 | 13:26:11.262 | routed reader modes | PASS |  |  | read[job_settings] mode=hybrid |  |  | value=70 contract fields source=log age=0.67s latency=65ms | 0.065s |
| 37 | 13:26:11.262 | routed reader modes | PASS |  |  | agree[job_settings] api vs log |  |  | all contract fields agree | 0.000s |
| 38 | 13:26:11.262 | routed reader modes | PASS |  |  | agree[job_settings] api vs hybrid |  |  | all contract fields agree | 0.000s |
| 39 | 13:26:12.115 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | change[zoom] -> 5.0 | job='Overview' target=5.0 (was 2.0) | 5.0 | set=25ms api=42ms log=724ms earlier=api | 0.066s |
| 40 | 13:26:12.131 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | restore[zoom] -> 2.0 | job='Overview' restore_to=2.0 | 2.0 | restore=16ms | 0.016s |
| 41 | 13:26:13.095 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | change[scan_speed] -> 600 | job='Overview' target=600 (was 400) | 600 | set=19ms api=42ms log=885ms earlier=api | 0.061s |
| 42 | 13:26:13.123 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | restore[scan_speed] -> 400 | job='Overview' restore_to=400 | 400 | restore=30ms | 0.030s |
| 43 | 13:26:14.062 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | change[image_format] -> 1024 x 1024 | job='Overview' target='1024 x 1024' (was '512 x 512') | 1024 x 1024 | set=21ms api=41ms log=889ms earlier=api | 0.062s |
| 44 | 13:26:14.079 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | restore[image_format] -> 512 x 512 | job='Overview' restore_to='512 x 512' | 512 x 512 | restore=17ms | 0.017s |
| 45 | 13:26:15.207 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | change[pinhole_airy] -> 1.2 | job='Overview' target=1.2 (was 1.0) | 1.2 | set=21ms api=40ms log=1042ms earlier=api | 0.061s |
| 46 | 13:26:15.224 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | restore[pinhole_airy] -> 1.0 | job='Overview' restore_to=1.0 | 1.0 | restore=17ms | 0.017s |

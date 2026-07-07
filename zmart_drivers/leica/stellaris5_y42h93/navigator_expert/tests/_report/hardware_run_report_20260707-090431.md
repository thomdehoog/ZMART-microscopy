# Hardware validation run report

Every change this run attempted on the instrument is listed below, including failed attempts and restore/cleanup steps (see the *Mutates scope* column). Changes carry their success+CONFIRMED / success+UNCONFIRMED / FAILED result and attempt counts in the *Result* column.

## Run metadata

- **Validator**: `validate_readers_side_by_side`
- **Arguments**: `--yes --report-dir=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report`
- **Backend**: live LAS X (simulator or scope)
- **Date**: 2026-07-07
- **Started / finished**: 09:04:31 / 09:04:38 (7.4s)
- **Host**: ZMB-LASX-PC (Windows-10-10.0.26200-SP0)
- **Python**: 3.11.15
- **Driver commit**: unknown on unknown
- **Driver log**: `\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\driver_log_20260707-090431.log` (full log-line capture)

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
| read-only parity | 2 | 0.017s | 0.018s | 0.018s |
| routed reader modes | 18 | 0.000s | 0.061s | 0.065s |
| live changes (reversible) | 8 | 0.016s | 0.062s | 2.043s |

### Per reader mode (routed read latency)

| Mode | Reads | Min | Median | Max | Median reading age |
|---|---:|---:|---:|---:|---:|
| api | 6 | 0.001s | 0.012s | 0.014s | 0.000s |
| log | 6 | 0.000s | 0.062s | 0.062s | 0.549s |
| hybrid | 6 | 0.012s | 0.065s | 0.065s | 0.000s |

### Slowest actions

| Duration | Phase | Action | Status |
|---:|---|---|---|
| 2.043s | live changes (reversible) | restore[zoom] -> 2.0 | PASS |
| 0.065s | live changes (reversible) | change[image_format] -> 1024 x 1024 | PASS |
| 0.065s | routed reader modes | read[hardware_info] mode=hybrid | PASS |
| 0.065s | routed reader modes | read[selected_job] mode=hybrid | PASS |
| 0.065s | routed reader modes | read[job_settings] mode=hybrid | PASS |
| 0.065s | routed reader modes | read[scan_status] mode=hybrid | PASS |
| 0.065s | routed reader modes | read[xy] mode=hybrid | PASS |
| 0.064s | live changes (reversible) | change[zoom] -> 5.0 | PASS |
| 0.063s | live changes (reversible) | change[scan_speed] -> 600 | PASS |
| 0.062s | routed reader modes | read[selected_job] mode=log | SKIP |

### Unconfirmed / failed changes

None -- every attempted change reported success and confirmed.

## Chronological detail (every attempted action)

| # | Time | Phase | Status | Result | Mutates scope | Action attempted | Args / target | Expected | Observed | Duration |
|---:|---|---|---|---|---|---|---|---|---|---:|
| 1 | 09:04:32.100 | read-only parity | PASS |  |  | get_xy |  |  | api=17ms log_age=2s | 0.017s |
| 2 | 09:04:32.118 | read-only parity | SKIP |  |  | get_jobs (names) |  |  | no authoritative log leg for this datum (API-only); api=['AF Job', 'HiRes', 'Overview'] log=['Overview'] | 0.018s |
| 3 | 09:04:32.118 | read-only parity | PASS |  |  | get_selected_job |  |  | api='Overview' log='Overview' | 0.000s |
| 4 | 09:04:32.120 | read-only parity | PASS |  |  | get_scan_status (idle-sense) |  |  | api='eScanIdle' log='eScanIdle' log_age=65525s | 0.000s |
| 5 | 09:04:32.144 | read-only parity | PASS |  |  | get_hardware_info (Microscope.name) |  |  |  | 0.000s |
| 6 | 09:04:32.159 | read-only parity | PASS |  |  | settings[Overview] (70 fields) |  |  | log_age=2s | 0.000s |
| 7 | 09:04:32.173 | read-only parity | PASS |  |  | get_fov[Overview] |  |  | api=(0.00058125, 0.00058125) log=(0.00058125, 0.00058125) | 0.000s |
| 8 | 09:04:32.187 | read-only parity | PASS |  |  | read_zwide_um[Overview] |  |  | api=0.0 log=0.0 | 0.000s |
| 9 | 09:04:32.199 | routed reader modes | PASS |  |  | read[xy] mode=api |  |  | value=(64220.0,41180.0)um source=api age=0.00s latency=12ms | 0.012s |
| 10 | 09:04:32.260 | routed reader modes | SKIP |  |  | read[xy] mode=log |  |  | no trusted log value (stale/absent log stream; router fails closed) | 0.062s |
| 11 | 09:04:32.325 | routed reader modes | PASS |  |  | read[xy] mode=hybrid |  |  | value=(64220.0,41180.0)um source=api age=0.00s latency=65ms | 0.065s |
| 12 | 09:04:32.325 | routed reader modes | SKIP |  |  | agree[xy] api vs log |  |  | insufficient values to cross-check | 0.000s |
| 13 | 09:04:32.325 | routed reader modes | PASS |  |  | agree[xy] api vs hybrid |  |  | delta=(0.00,0.00)um tol=1.0um | 0.000s |
| 14 | 09:04:32.337 | routed reader modes | PASS |  |  | read[jobs] mode=api |  |  | value=['AF Job', 'HiRes', 'Overview'] source=api age=0.00s latency=12ms | 0.012s |
| 15 | 09:04:32.337 | routed reader modes | SKIP |  |  | read[jobs] mode=log |  |  | no trusted log value (stale/absent log stream; router fails closed) err=UnsupportedSource("datum 'jobs' has no log leg") | 0.000s |
| 16 | 09:04:32.349 | routed reader modes | PASS |  |  | read[jobs] mode=hybrid |  |  | value=['AF Job', 'HiRes', 'Overview'] source=api age=0.00s latency=12ms | 0.012s |
| 17 | 09:04:32.349 | routed reader modes | SKIP |  |  | agree[jobs] api vs log |  |  | insufficient values to cross-check | 0.000s |
| 18 | 09:04:32.349 | routed reader modes | PASS |  |  | agree[jobs] api vs hybrid |  |  | ['AF Job', 'HiRes', 'Overview'] vs ['AF Job', 'HiRes', 'Overview'] | 0.000s |
| 19 | 09:04:32.361 | routed reader modes | PASS |  |  | read[selected_job] mode=api |  |  | value='Overview' source=api age=0.00s latency=12ms | 0.012s |
| 20 | 09:04:32.423 | routed reader modes | SKIP |  |  | read[selected_job] mode=log |  |  | no trusted log value (stale/absent log stream; router fails closed) | 0.062s |
| 21 | 09:04:32.488 | routed reader modes | PASS |  |  | read[selected_job] mode=hybrid |  |  | value='Overview' source=api age=0.00s latency=65ms | 0.065s |
| 22 | 09:04:32.488 | routed reader modes | SKIP |  |  | agree[selected_job] api vs log |  |  | insufficient values to cross-check | 0.000s |
| 23 | 09:04:32.488 | routed reader modes | PASS |  |  | agree[selected_job] api vs hybrid |  |  | 'Overview' vs 'Overview' | 0.000s |
| 24 | 09:04:32.489 | routed reader modes | PASS |  |  | read[scan_status] mode=api |  |  | value='eScanIdle' source=api age=0.00s latency=1ms | 0.001s |
| 25 | 09:04:32.551 | routed reader modes | SKIP |  |  | read[scan_status] mode=log |  |  | no trusted log value (stale/absent log stream; router fails closed) | 0.062s |
| 26 | 09:04:32.616 | routed reader modes | PASS |  |  | read[scan_status] mode=hybrid |  |  | value='eScanIdle' source=api age=0.00s latency=65ms | 0.065s |
| 27 | 09:04:32.616 | routed reader modes | SKIP |  |  | agree[scan_status] api vs log |  |  | insufficient values to cross-check | 0.000s |
| 28 | 09:04:32.616 | routed reader modes | PASS |  |  | agree[scan_status] api vs hybrid |  |  | 'eScanIdle' vs 'eScanIdle' (idle-sense) | 0.000s |
| 29 | 09:04:32.629 | routed reader modes | PASS |  |  | read[hardware_info] mode=api |  |  | value=Microscope='DM Manual-6' source=api age=0.00s latency=13ms | 0.013s |
| 30 | 09:04:32.690 | routed reader modes | PASS |  |  | read[hardware_info] mode=log |  |  | value=Microscope='DM Manual-6' source=log age=0.50s latency=61ms | 0.061s |
| 31 | 09:04:32.755 | routed reader modes | PASS |  |  | read[hardware_info] mode=hybrid |  |  | value=Microscope='DM Manual-6' source=log age=0.57s latency=65ms | 0.065s |
| 32 | 09:04:32.755 | routed reader modes | PASS |  |  | agree[hardware_info] api vs log |  |  | 'DM Manual-6' vs 'DM Manual-6' | 0.000s |
| 33 | 09:04:32.755 | routed reader modes | PASS |  |  | agree[hardware_info] api vs hybrid |  |  | 'DM Manual-6' vs 'DM Manual-6' | 0.000s |
| 34 | 09:04:32.769 | routed reader modes | PASS |  |  | read[job_settings] mode=api |  |  | value=70 contract fields source=api age=0.00s latency=14ms | 0.014s |
| 35 | 09:04:32.831 | routed reader modes | PASS |  |  | read[job_settings] mode=log |  |  | value=70 contract fields source=log age=0.59s latency=62ms | 0.062s |
| 36 | 09:04:32.896 | routed reader modes | PASS |  |  | read[job_settings] mode=hybrid |  |  | value=70 contract fields source=log age=0.66s latency=65ms | 0.065s |
| 37 | 09:04:32.896 | routed reader modes | PASS |  |  | agree[job_settings] api vs log |  |  | all contract fields agree | 0.000s |
| 38 | 09:04:32.896 | routed reader modes | PASS |  |  | agree[job_settings] api vs hybrid |  |  | all contract fields agree | 0.000s |
| 39 | 09:04:33.751 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | change[zoom] -> 5.0 | job='Overview' target=5.0 (was 2.0) | 5.0 | set=22ms api=41ms log=725ms earlier=api | 0.064s |
| 40 | 09:04:35.794 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | restore[zoom] -> 2.0 | job='Overview' restore_to=2.0 | 2.0 | restore=2043ms | 2.043s |
| 41 | 09:04:36.758 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | change[scan_speed] -> 600 | job='Overview' target=600 (was 400) | 600 | set=22ms api=41ms log=885ms earlier=api | 0.063s |
| 42 | 09:04:36.779 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | restore[scan_speed] -> 400 | job='Overview' restore_to=400 | 400 | restore=20ms | 0.020s |
| 43 | 09:04:37.757 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | change[image_format] -> 1024 x 1024 | job='Overview' target='1024 x 1024' (was '512 x 512') | 1024 x 1024 | set=21ms api=44ms log=888ms earlier=api | 0.065s |
| 44 | 09:04:37.774 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | restore[image_format] -> 512 x 512 | job='Overview' restore_to='512 x 512' | 512 x 512 | restore=16ms | 0.016s |
| 45 | 09:04:38.733 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | change[pinhole_airy] -> 1.2 | job='Overview' target=1.2 (was 1.0) | 1.2 | set=18ms api=42ms log=882ms earlier=api | 0.060s |
| 46 | 09:04:38.750 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | restore[pinhole_airy] -> 1.0 | job='Overview' restore_to=1.0 | 1.0 | restore=16ms | 0.016s |

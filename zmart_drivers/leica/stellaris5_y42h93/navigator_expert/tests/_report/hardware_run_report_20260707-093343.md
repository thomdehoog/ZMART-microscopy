# Hardware validation run report

Every change this run attempted on the instrument is listed below, including failed attempts and restore/cleanup steps (see the *Mutates scope* column). Changes carry their success+CONFIRMED / success+UNCONFIRMED / FAILED result and attempt counts in the *Result* column.

## Run metadata

- **Validator**: `validate_readers_side_by_side`
- **Arguments**: `--yes --report-dir=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report`
- **Backend**: live LAS X (simulator or scope)
- **Date**: 2026-07-07
- **Started / finished**: 09:33:43 / 09:33:50 (6.9s)
- **Host**: ZMB-Y42H93-STI8 (Windows-10-10.0.26100-SP0)
- **Python**: 3.11.15
- **Driver commit**: aecf1a2 on claude/smart-drivers-code-review-ky4phc (working tree has local changes)
- **Driver log**: `\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\driver_log_20260707-093343.log` (full log-line capture)

## Summary

| Phase | Actions attempted | Passed | Warned | Failed | Skipped | Confirmed | Unconfirmed |
|---|---:|---:|---:|---:|---:|---:|---:|
| read-only parity | 14 | 13 | 0 | 0 | 1 | 0 | 0 |
| routed reader modes | 30 | 22 | 0 | 0 | 8 | 0 | 0 |
| live changes (reversible) | 8 | 8 | 0 | 0 | 0 | 8 | 0 |
| **total** | **52** | **43** | **0** | **0** | **9** | **8** | **0** |

## Timing overview

### Per phase

| Phase | Timed actions | Min | Median | Max |
|---|---:|---:|---:|---:|
| read-only parity | 2 | 0.020s | 0.022s | 0.025s |
| routed reader modes | 18 | 0.000s | 0.135s | 0.158s |
| live changes (reversible) | 8 | 0.021s | 0.093s | 0.274s |

### Per reader mode (routed read latency)

| Mode | Reads | Min | Median | Max | Median reading age |
|---|---:|---:|---:|---:|---:|
| api | 6 | 0.001s | 0.013s | 0.014s | 0.000s |
| log | 6 | 0.000s | 0.139s | 0.144s | 1.161s |
| hybrid | 6 | 0.013s | 0.137s | 0.158s | 0.000s |

### Slowest actions

| Duration | Phase | Action | Status |
|---:|---|---|---|
| 0.274s | live changes (reversible) | change[zoom] -> 5.0 | PASS |
| 0.210s | live changes (reversible) | restore[zoom] -> 1.0 | PASS |
| 0.158s | routed reader modes | read[xy] mode=hybrid | PASS |
| 0.144s | routed reader modes | read[job_settings] mode=log | PASS |
| 0.142s | routed reader modes | read[scan_status] mode=log | SKIP |
| 0.141s | routed reader modes | read[xy] mode=log | SKIP |
| 0.138s | routed reader modes | read[job_settings] mode=hybrid | PASS |
| 0.137s | routed reader modes | read[scan_status] mode=hybrid | PASS |
| 0.137s | routed reader modes | read[hardware_info] mode=log | PASS |
| 0.137s | routed reader modes | read[selected_job] mode=hybrid | PASS |

### Unconfirmed / failed changes

None -- every attempted change reported success and confirmed.

## Chronological detail (every attempted action)

| # | Time | Phase | Status | Result | Mutates scope | Action attempted | Args / target | Expected | Observed | Duration |
|---:|---|---|---|---|---|---|---|---|---|---:|
| 1 | 09:33:44.567 | read-only parity | PASS |  |  | get_xy |  |  | api=20ms log_age=2s | 0.020s |
| 2 | 09:33:44.592 | read-only parity | SKIP |  |  | get_jobs (names) |  |  | no authoritative log leg for this datum (API-only); api=['AF Job', 'HiRes', 'Overview'] log=['AF Job', 'HiRes', 'Overview'] | 0.025s |
| 3 | 09:33:44.592 | read-only parity | PASS |  |  | get_selected_job |  |  | api='HiRes' log='HiRes' | 0.000s |
| 4 | 09:33:44.596 | read-only parity | PASS |  |  | get_scan_status (idle-sense) |  |  | api='eScanIdle' log='eScanIdle' log_age=473671s | 0.000s |
| 5 | 09:33:44.609 | read-only parity | PASS |  |  | get_hardware_info (Microscope.name) |  |  |  | 0.000s |
| 6 | 09:33:44.626 | read-only parity | PASS |  |  | settings[AF Job] (36 fields) |  |  | log_age=154s | 0.000s |
| 7 | 09:33:44.641 | read-only parity | PASS |  |  | get_fov[AF Job] |  |  | api=(0.00116, 0.00116) log=(0.00116, 0.00116) | 0.000s |
| 8 | 09:33:44.656 | read-only parity | PASS |  |  | read_zwide_um[AF Job] |  |  | api=0.0 log=0.0 | 0.000s |
| 9 | 09:33:44.670 | read-only parity | PASS |  |  | settings[HiRes] (42 fields) |  |  | log_age=2s | 0.000s |
| 10 | 09:33:44.684 | read-only parity | PASS |  |  | get_fov[HiRes] |  |  | api=(0.00116, 0.00116) log=(0.00116, 0.00116) | 0.000s |
| 11 | 09:33:44.698 | read-only parity | PASS |  |  | read_zwide_um[HiRes] |  |  | api=0.0 log=0.0 | 0.000s |
| 12 | 09:33:44.712 | read-only parity | PASS |  |  | settings[Overview] (42 fields) |  |  | log_age=154s | 0.000s |
| 13 | 09:33:44.726 | read-only parity | PASS |  |  | get_fov[Overview] |  |  | api=(0.00116, 0.00116) log=(0.00116, 0.00116) | 0.000s |
| 14 | 09:33:44.743 | read-only parity | PASS |  |  | read_zwide_um[Overview] |  |  | api=0.0 log=0.0 | 0.000s |
| 15 | 09:33:44.757 | routed reader modes | PASS |  |  | read[xy] mode=api |  |  | value=(63500.0,41500.0)um source=api age=0.00s latency=13ms | 0.013s |
| 16 | 09:33:44.898 | routed reader modes | SKIP |  |  | read[xy] mode=log |  |  | no trusted log value (stale/absent log stream; router fails closed) | 0.141s |
| 17 | 09:33:45.056 | routed reader modes | PASS |  |  | read[xy] mode=hybrid |  |  | value=(63500.0,41500.0)um source=api age=0.00s latency=158ms | 0.158s |
| 18 | 09:33:45.056 | routed reader modes | SKIP |  |  | agree[xy] api vs log |  |  | insufficient values to cross-check | 0.000s |
| 19 | 09:33:45.056 | routed reader modes | PASS |  |  | agree[xy] api vs hybrid |  |  | delta=(0.00,0.00)um tol=1.0um | 0.000s |
| 20 | 09:33:45.069 | routed reader modes | PASS |  |  | read[jobs] mode=api |  |  | value=['AF Job', 'HiRes', 'Overview'] source=api age=0.00s latency=13ms | 0.013s |
| 21 | 09:33:45.069 | routed reader modes | SKIP |  |  | read[jobs] mode=log |  |  | no trusted log value (stale/absent log stream; router fails closed) err=UnsupportedSource("datum 'jobs' has no log leg") | 0.000s |
| 22 | 09:33:45.082 | routed reader modes | PASS |  |  | read[jobs] mode=hybrid |  |  | value=['AF Job', 'HiRes', 'Overview'] source=api age=0.00s latency=13ms | 0.013s |
| 23 | 09:33:45.082 | routed reader modes | SKIP |  |  | agree[jobs] api vs log |  |  | insufficient values to cross-check | 0.000s |
| 24 | 09:33:45.082 | routed reader modes | PASS |  |  | agree[jobs] api vs hybrid |  |  | ['AF Job', 'HiRes', 'Overview'] vs ['AF Job', 'HiRes', 'Overview'] | 0.000s |
| 25 | 09:33:45.096 | routed reader modes | PASS |  |  | read[selected_job] mode=api |  |  | value='HiRes' source=api age=0.00s latency=13ms | 0.013s |
| 26 | 09:33:45.231 | routed reader modes | SKIP |  |  | read[selected_job] mode=log |  |  | no trusted log value (stale/absent log stream; router fails closed) | 0.135s |
| 27 | 09:33:45.368 | routed reader modes | PASS |  |  | read[selected_job] mode=hybrid |  |  | value='HiRes' source=api age=0.00s latency=137ms | 0.137s |
| 28 | 09:33:45.368 | routed reader modes | SKIP |  |  | agree[selected_job] api vs log |  |  | insufficient values to cross-check | 0.000s |
| 29 | 09:33:45.368 | routed reader modes | PASS |  |  | agree[selected_job] api vs hybrid |  |  | 'HiRes' vs 'HiRes' | 0.000s |
| 30 | 09:33:45.369 | routed reader modes | PASS |  |  | read[scan_status] mode=api |  |  | value='eScanIdle' source=api age=0.00s latency=1ms | 0.001s |
| 31 | 09:33:45.511 | routed reader modes | SKIP |  |  | read[scan_status] mode=log |  |  | no trusted log value (stale/absent log stream; router fails closed) | 0.142s |
| 32 | 09:33:45.648 | routed reader modes | PASS |  |  | read[scan_status] mode=hybrid |  |  | value='eScanIdle' source=api age=0.00s latency=137ms | 0.137s |
| 33 | 09:33:45.648 | routed reader modes | SKIP |  |  | agree[scan_status] api vs log |  |  | insufficient values to cross-check | 0.000s |
| 34 | 09:33:45.648 | routed reader modes | PASS |  |  | agree[scan_status] api vs hybrid |  |  | 'eScanIdle' vs 'eScanIdle' (idle-sense) | 0.000s |
| 35 | 09:33:45.661 | routed reader modes | PASS |  |  | read[hardware_info] mode=api |  |  | value=Microscope='DMI8' source=api age=0.00s latency=13ms | 0.013s |
| 36 | 09:33:45.798 | routed reader modes | PASS |  |  | read[hardware_info] mode=log |  |  | value=Microscope='DMI8' source=log age=1.06s latency=137ms | 0.137s |
| 37 | 09:33:45.932 | routed reader modes | PASS |  |  | read[hardware_info] mode=hybrid |  |  | value=Microscope='DMI8' source=log age=1.20s latency=134ms | 0.134s |
| 38 | 09:33:45.932 | routed reader modes | PASS |  |  | agree[hardware_info] api vs log |  |  | 'DMI8' vs 'DMI8' | 0.000s |
| 39 | 09:33:45.932 | routed reader modes | PASS |  |  | agree[hardware_info] api vs hybrid |  |  | 'DMI8' vs 'DMI8' | 0.000s |
| 40 | 09:33:45.946 | routed reader modes | PASS |  |  | read[job_settings] mode=api |  |  | value=42 contract fields source=api age=0.00s latency=14ms | 0.014s |
| 41 | 09:33:46.090 | routed reader modes | PASS |  |  | read[job_settings] mode=log |  |  | value=42 contract fields source=log age=1.26s latency=144ms | 0.144s |
| 42 | 09:33:46.229 | routed reader modes | PASS |  |  | read[job_settings] mode=hybrid |  |  | value=42 contract fields source=log age=1.40s latency=138ms | 0.138s |
| 43 | 09:33:46.229 | routed reader modes | PASS |  |  | agree[job_settings] api vs log |  |  | all contract fields agree | 0.000s |
| 44 | 09:33:46.229 | routed reader modes | PASS |  |  | agree[job_settings] api vs hybrid |  |  | all contract fields agree | 0.000s |
| 45 | 09:33:47.358 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | change[zoom] -> 5.0 | job='HiRes' target=5.0 (was 1.0) | 5.0 | set=234ms api=40ms log=845ms earlier=api | 0.274s |
| 46 | 09:33:47.568 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | restore[zoom] -> 1.0 | job='HiRes' restore_to=1.0 | 1.0 | restore=210ms | 0.210s |
| 47 | 09:33:48.538 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | change[scan_speed] -> 600 | job='HiRes' target=600 (was 400) | 600 | set=49ms api=68ms log=825ms earlier=api | 0.117s |
| 48 | 09:33:48.591 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | restore[scan_speed] -> 400 | job='HiRes' restore_to=400 | 400 | restore=53ms | 0.053s |
| 49 | 09:33:49.557 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | change[image_format] -> 1024 x 1024 | job='HiRes' target='1024 x 1024' (was '512 x 512') | 1024 x 1024 | set=35ms api=70ms log=836ms earlier=api | 0.105s |
| 50 | 09:33:49.579 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | restore[image_format] -> 512 x 512 | job='HiRes' restore_to='512 x 512' | 512 x 512 | restore=21ms | 0.021s |
| 51 | 09:33:50.433 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | change[pinhole_airy] -> 1.2 | job='HiRes' target=1.2 (was 1.0) | 1.2 | set=31ms api=52ms log=809ms earlier=api | 0.082s |
| 52 | 09:33:50.455 | live changes (reversible) | PASS | success+CONFIRMED att=1 conf=1 | YES | restore[pinhole_airy] -> 1.0 | job='HiRes' restore_to=1.0 | 1.0 | restore=22ms | 0.022s |

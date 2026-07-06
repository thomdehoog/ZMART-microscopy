# Hardware validation run report

Every change this run attempted on the instrument is listed below, including failed attempts and restore/cleanup steps (see the *Mutates scope* column). Changes carry their success+CONFIRMED / success+UNCONFIRMED / FAILED result and attempt counts in the *Result* column.

## Run metadata

- **Validator**: `validate_readers_side_by_side`
- **Arguments**: `--yes --report-dir=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report`
- **Backend**: live LAS X (simulator or scope)
- **Date**: 2026-07-06
- **Started / finished**: 11:16:14 / 11:16:15 (1.4s)
- **Host**: ZMB-LASX-PC (Windows-10-10.0.26200-SP0)
- **Python**: 3.11.15
- **Driver commit**: unknown on unknown
- **Driver log**: `\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\driver_log_20260706-111614.log` (full log-line capture)

## Summary

| Phase | Actions attempted | Passed | Warned | Failed | Skipped | Confirmed | Unconfirmed |
|---|---:|---:|---:|---:|---:|---:|---:|
| setup | 1 | 0 | 0 | 1 | 0 | 0 | 0 |
| read-only parity | 8 | 7 | 0 | 1 | 0 | 0 | 0 |
| routed reader modes | 30 | 22 | 0 | 2 | 6 | 0 | 0 |
| **total** | **39** | **29** | **0** | **4** | **6** | **0** | **0** |

## Timing overview

### Per phase

| Phase | Timed actions | Min | Median | Max |
|---|---:|---:|---:|---:|
| read-only parity | 2 | 0.017s | 0.019s | 0.020s |
| routed reader modes | 18 | 0.001s | 0.042s | 0.049s |

### Per reader mode (routed read latency)

| Mode | Reads | Min | Median | Max | Median reading age |
|---|---:|---:|---:|---:|---:|
| api | 6 | 0.001s | 0.012s | 0.014s | 0.000s |
| log | 6 | 0.042s | 0.042s | 0.043s | 0.508s |
| hybrid | 6 | 0.044s | 0.044s | 0.049s | 0.249s |

### Slowest actions

| Duration | Phase | Action | Status |
|---:|---|---|---|
| 0.049s | routed reader modes | read[xy] mode=hybrid | PASS |
| 0.045s | routed reader modes | read[hardware_info] mode=hybrid | PASS |
| 0.045s | routed reader modes | read[scan_status] mode=hybrid | PASS |
| 0.044s | routed reader modes | read[job_settings] mode=hybrid | PASS |
| 0.044s | routed reader modes | read[selected_job] mode=hybrid | PASS |
| 0.044s | routed reader modes | read[jobs] mode=hybrid | PASS |
| 0.043s | routed reader modes | read[job_settings] mode=log | PASS |
| 0.042s | routed reader modes | read[scan_status] mode=log | SKIP |
| 0.042s | routed reader modes | read[hardware_info] mode=log | PASS |
| 0.042s | routed reader modes | read[xy] mode=log | SKIP |

### Unconfirmed / failed changes

None -- every attempted change reported success and confirmed.

## Chronological detail (every attempted action)

| # | Time | Phase | Status | Result | Mutates scope | Action attempted | Args / target | Expected | Observed | Duration |
|---:|---|---|---|---|---|---|---|---|---|---:|
| 1 | 11:16:14.835 | setup | FAIL |  |  | limits handshake |  |  | limits handshake failed: no machine-local limits.json for the physical stage envelope: tried C:\ProgramData\zmart-microscopy\leica\stellaris5_y42h93\navigator_expert (newest snapshot under C:\ProgramData\zmart-microscopy\leica\stellaris5_y… | 0.000s |
| 2 | 11:16:14.911 | read-only parity | PASS |  |  | get_xy |  |  | api=17ms log_age=2s | 0.017s |
| 3 | 11:16:14.931 | read-only parity | FAIL |  |  | get_jobs (names) |  |  | api=['AF Job', 'HiRes', 'Overview'] log=['Overview'] | 0.020s |
| 4 | 11:16:14.931 | read-only parity | PASS |  |  | get_selected_job |  |  | api=['Overview'] log=['Overview'] | 0.000s |
| 5 | 11:16:14.931 | read-only parity | PASS |  |  | get_scan_status (idle-sense) |  |  | api='eScanIdle' log='eScanIdle' log_age=257386s | 0.000s |
| 6 | 11:16:14.945 | read-only parity | PASS |  |  | get_hardware_info (Microscope.name) |  |  |  | 0.000s |
| 7 | 11:16:14.962 | read-only parity | PASS |  |  | settings[Overview] (70 fields) |  |  | log_age=2s | 0.000s |
| 8 | 11:16:14.974 | read-only parity | PASS |  |  | get_fov[Overview] |  |  | api=(0.00116, 0.00116) log=(0.00116, 0.00116) | 0.000s |
| 9 | 11:16:14.991 | read-only parity | PASS |  |  | read_zwide_um[Overview] |  |  | api=-7200.0 log=-7200.0 | 0.000s |
| 10 | 11:16:15.004 | routed reader modes | PASS |  |  | read[xy] mode=api |  |  | value=(0.0,0.0)um source=api age=0.00s latency=12ms | 0.012s |
| 11 | 11:16:15.041 | routed reader modes | SKIP |  |  | read[xy] mode=log |  |  | no trusted log value (stale/absent log stream; router fails closed) | 0.042s |
| 12 | 11:16:15.095 | routed reader modes | PASS |  |  | read[xy] mode=hybrid |  |  | value=(0.0,0.0)um source=api age=0.00s latency=49ms | 0.049s |
| 13 | 11:16:15.095 | routed reader modes | SKIP |  |  | agree[xy] api vs log |  |  | insufficient values to cross-check | 0.000s |
| 14 | 11:16:15.095 | routed reader modes | PASS |  |  | agree[xy] api vs hybrid |  |  | delta=(0.00,0.00)um tol=1.0um | 0.000s |
| 15 | 11:16:15.107 | routed reader modes | PASS |  |  | read[jobs] mode=api |  |  | value=['AF Job', 'HiRes', 'Overview'] source=api age=0.00s latency=12ms | 0.012s |
| 16 | 11:16:15.136 | routed reader modes | PASS |  |  | read[jobs] mode=log |  |  | value=['Overview'] source=log age=1.90s latency=42ms | 0.042s |
| 17 | 11:16:15.188 | routed reader modes | PASS |  |  | read[jobs] mode=hybrid |  |  | value=['Overview'] source=log age=1.93s latency=44ms | 0.044s |
| 18 | 11:16:15.188 | routed reader modes | FAIL |  |  | agree[jobs] api vs log |  |  | ['AF Job', 'HiRes', 'Overview'] vs ['Overview'] | 0.000s |
| 19 | 11:16:15.188 | routed reader modes | FAIL |  |  | agree[jobs] api vs hybrid |  |  | ['AF Job', 'HiRes', 'Overview'] vs ['Overview'] | 0.000s |
| 20 | 11:16:15.205 | routed reader modes | PASS |  |  | read[selected_job] mode=api |  |  | value='Overview' source=api age=0.00s latency=12ms | 0.012s |
| 21 | 11:16:15.246 | routed reader modes | SKIP |  |  | read[selected_job] mode=log |  |  | no trusted log value (stale/absent log stream; router fails closed) | 0.042s |
| 22 | 11:16:15.283 | routed reader modes | PASS |  |  | read[selected_job] mode=hybrid |  |  | value='Overview' source=api age=0.00s latency=44ms | 0.044s |
| 23 | 11:16:15.283 | routed reader modes | SKIP |  |  | agree[selected_job] api vs log |  |  | insufficient values to cross-check | 0.000s |
| 24 | 11:16:15.283 | routed reader modes | PASS |  |  | agree[selected_job] api vs hybrid |  |  | 'Overview' vs 'Overview' | 0.000s |
| 25 | 11:16:15.283 | routed reader modes | PASS |  |  | read[scan_status] mode=api |  |  | value='eScanIdle' source=api age=0.00s latency=1ms | 0.001s |
| 26 | 11:16:15.325 | routed reader modes | SKIP |  |  | read[scan_status] mode=log |  |  | no trusted log value (stale/absent log stream; router fails closed) | 0.042s |
| 27 | 11:16:15.377 | routed reader modes | PASS |  |  | read[scan_status] mode=hybrid |  |  | value='eScanIdle' source=api age=0.00s latency=45ms | 0.045s |
| 28 | 11:16:15.377 | routed reader modes | SKIP |  |  | agree[scan_status] api vs log |  |  | insufficient values to cross-check | 0.000s |
| 29 | 11:16:15.377 | routed reader modes | PASS |  |  | agree[scan_status] api vs hybrid |  |  | 'eScanIdle' vs 'eScanIdle' (idle-sense) | 0.000s |
| 30 | 11:16:15.391 | routed reader modes | PASS |  |  | read[hardware_info] mode=api |  |  | value=Microscope='DM Manual-6' source=api age=0.00s latency=12ms | 0.012s |
| 31 | 11:16:15.433 | routed reader modes | PASS |  |  | read[hardware_info] mode=log |  |  | value=Microscope='DM Manual-6' source=log age=0.46s latency=42ms | 0.042s |
| 32 | 11:16:15.478 | routed reader modes | PASS |  |  | read[hardware_info] mode=hybrid |  |  | value=Microscope='DM Manual-6' source=log age=0.50s latency=45ms | 0.045s |
| 33 | 11:16:15.478 | routed reader modes | PASS |  |  | agree[hardware_info] api vs log |  |  | 'DM Manual-6' vs 'DM Manual-6' | 0.000s |
| 34 | 11:16:15.478 | routed reader modes | PASS |  |  | agree[hardware_info] api vs hybrid |  |  | 'DM Manual-6' vs 'DM Manual-6' | 0.000s |
| 35 | 11:16:15.492 | routed reader modes | PASS |  |  | read[job_settings] mode=api |  |  | value=70 contract fields source=api age=0.00s latency=14ms | 0.014s |
| 36 | 11:16:15.521 | routed reader modes | PASS |  |  | read[job_settings] mode=log |  |  | value=70 contract fields source=log age=0.51s latency=43ms | 0.043s |
| 37 | 11:16:15.574 | routed reader modes | PASS |  |  | read[job_settings] mode=hybrid |  |  | value=70 contract fields source=log age=0.55s latency=44ms | 0.044s |
| 38 | 11:16:15.574 | routed reader modes | PASS |  |  | agree[job_settings] api vs log |  |  | all contract fields agree | 0.000s |
| 39 | 11:16:15.574 | routed reader modes | PASS |  |  | agree[job_settings] api vs hybrid |  |  | all contract fields agree | 0.000s |

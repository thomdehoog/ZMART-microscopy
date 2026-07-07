# Hardware validation run report

Every change this run attempted on the instrument is listed below, including failed attempts and restore/cleanup steps (see the *Mutates scope* column). Changes carry their success+CONFIRMED / success+UNCONFIRMED / FAILED result and attempt counts in the *Result* column.

## Run metadata

- **Validator**: `validate_readers_side_by_side`
- **Arguments**: `--read-only --report-dir=tests\_report`
- **Backend**: live LAS X (simulator or scope)
- **Date**: 2026-07-07
- **Started / finished**: 09:30:12 / 09:30:15 (2.8s)
- **Host**: ZMB-Y42H93-STI8 (Windows-10-10.0.26100-SP0)
- **Python**: 3.11.15
- **Driver commit**: aecf1a2 on claude/smart-drivers-code-review-ky4phc (working tree has local changes)
- **Driver log**: `tests\_report\driver_log_20260707-093012.log` (full log-line capture)

## Summary

| Phase | Actions attempted | Passed | Warned | Failed | Skipped | Confirmed | Unconfirmed |
|---|---:|---:|---:|---:|---:|---:|---:|
| read-only parity | 14 | 13 | 0 | 0 | 1 | 0 | 0 |
| routed reader modes | 30 | 22 | 0 | 0 | 8 | 0 | 0 |
| **total** | **44** | **35** | **0** | **0** | **9** | **0** | **0** |

## Timing overview

### Per phase

| Phase | Timed actions | Min | Median | Max |
|---|---:|---:|---:|---:|
| read-only parity | 2 | 0.020s | 0.024s | 0.027s |
| routed reader modes | 18 | 0.000s | 0.150s | 0.169s |

### Per reader mode (routed read latency)

| Mode | Reads | Min | Median | Max | Median reading age |
|---|---:|---:|---:|---:|---:|
| api | 6 | 0.001s | 0.013s | 0.015s | 0.000s |
| log | 6 | 0.000s | 0.154s | 0.169s | 1.260s |
| hybrid | 6 | 0.013s | 0.153s | 0.155s | 0.082s |

### Slowest actions

| Duration | Phase | Action | Status |
|---:|---|---|---|
| 0.169s | routed reader modes | read[scan_status] mode=log | SKIP |
| 0.156s | routed reader modes | read[hardware_info] mode=log | PASS |
| 0.155s | routed reader modes | read[xy] mode=hybrid | PASS |
| 0.155s | routed reader modes | read[hardware_info] mode=hybrid | PASS |
| 0.154s | routed reader modes | read[xy] mode=log | SKIP |
| 0.154s | routed reader modes | read[job_settings] mode=hybrid | PASS |
| 0.153s | routed reader modes | read[job_settings] mode=log | PASS |
| 0.153s | routed reader modes | read[selected_job] mode=log | SKIP |
| 0.152s | routed reader modes | read[selected_job] mode=hybrid | PASS |
| 0.148s | routed reader modes | read[scan_status] mode=hybrid | PASS |

### Unconfirmed / failed changes

None -- every attempted change reported success and confirmed.

## Chronological detail (every attempted action)

| # | Time | Phase | Status | Result | Mutates scope | Action attempted | Args / target | Expected | Observed | Duration |
|---:|---|---|---|---|---|---|---|---|---|---:|
| 1 | 09:30:13.695 | read-only parity | PASS |  |  | get_xy |  |  | api=20ms log_age=33s | 0.020s |
| 2 | 09:30:13.722 | read-only parity | SKIP |  |  | get_jobs (names) |  |  | no authoritative log leg for this datum (API-only); api=['AF Job', 'HiRes', 'Overview'] log=['AF Job', 'HiRes', 'Overview'] | 0.027s |
| 3 | 09:30:13.722 | read-only parity | PASS |  |  | get_selected_job |  |  | api='HiRes' log='HiRes' | 0.000s |
| 4 | 09:30:13.726 | read-only parity | PASS |  |  | get_scan_status (idle-sense) |  |  | api='eScanIdle' log='eScanIdle' log_age=473460s | 0.000s |
| 5 | 09:30:13.739 | read-only parity | PASS |  |  | get_hardware_info (Microscope.name) |  |  |  | 0.000s |
| 6 | 09:30:13.756 | read-only parity | PASS |  |  | settings[AF Job] (36 fields) |  |  | log_age=33s | 0.000s |
| 7 | 09:30:13.769 | read-only parity | PASS |  |  | get_fov[AF Job] |  |  | api=(0.00116, 0.00116) log=(0.00116, 0.00116) | 0.000s |
| 8 | 09:30:13.784 | read-only parity | PASS |  |  | read_zwide_um[AF Job] |  |  | api=0.0 log=0.0 | 0.000s |
| 9 | 09:30:13.798 | read-only parity | PASS |  |  | settings[HiRes] (42 fields) |  |  | log_age=31s | 0.000s |
| 10 | 09:30:13.813 | read-only parity | PASS |  |  | get_fov[HiRes] |  |  | api=(0.00116, 0.00116) log=(0.00116, 0.00116) | 0.000s |
| 11 | 09:30:13.827 | read-only parity | PASS |  |  | read_zwide_um[HiRes] |  |  | api=0.0 log=0.0 | 0.000s |
| 12 | 09:30:13.844 | read-only parity | PASS |  |  | settings[Overview] (42 fields) |  |  | log_age=33s | 0.000s |
| 13 | 09:30:13.858 | read-only parity | PASS |  |  | get_fov[Overview] |  |  | api=(0.00116, 0.00116) log=(0.00116, 0.00116) | 0.000s |
| 14 | 09:30:13.873 | read-only parity | PASS |  |  | read_zwide_um[Overview] |  |  | api=0.0 log=0.0 | 0.000s |
| 15 | 09:30:13.886 | routed reader modes | PASS |  |  | read[xy] mode=api |  |  | value=(63500.0,41500.0)um source=api age=0.00s latency=12ms | 0.012s |
| 16 | 09:30:14.039 | routed reader modes | SKIP |  |  | read[xy] mode=log |  |  | no trusted log value (stale/absent log stream; router fails closed) | 0.154s |
| 17 | 09:30:14.195 | routed reader modes | PASS |  |  | read[xy] mode=hybrid |  |  | value=(63500.0,41500.0)um source=log age=0.16s latency=155ms | 0.155s |
| 18 | 09:30:14.195 | routed reader modes | SKIP |  |  | agree[xy] api vs log |  |  | insufficient values to cross-check | 0.000s |
| 19 | 09:30:14.195 | routed reader modes | PASS |  |  | agree[xy] api vs hybrid |  |  | delta=(0.00,0.00)um tol=1.0um | 0.000s |
| 20 | 09:30:14.208 | routed reader modes | PASS |  |  | read[jobs] mode=api |  |  | value=['AF Job', 'HiRes', 'Overview'] source=api age=0.00s latency=13ms | 0.013s |
| 21 | 09:30:14.208 | routed reader modes | SKIP |  |  | read[jobs] mode=log |  |  | no trusted log value (stale/absent log stream; router fails closed) err=UnsupportedSource("datum 'jobs' has no log leg") | 0.000s |
| 22 | 09:30:14.221 | routed reader modes | PASS |  |  | read[jobs] mode=hybrid |  |  | value=['AF Job', 'HiRes', 'Overview'] source=api age=0.00s latency=13ms | 0.013s |
| 23 | 09:30:14.221 | routed reader modes | SKIP |  |  | agree[jobs] api vs log |  |  | insufficient values to cross-check | 0.000s |
| 24 | 09:30:14.221 | routed reader modes | PASS |  |  | agree[jobs] api vs hybrid |  |  | ['AF Job', 'HiRes', 'Overview'] vs ['AF Job', 'HiRes', 'Overview'] | 0.000s |
| 25 | 09:30:14.234 | routed reader modes | PASS |  |  | read[selected_job] mode=api |  |  | value='HiRes' source=api age=0.00s latency=12ms | 0.012s |
| 26 | 09:30:14.386 | routed reader modes | SKIP |  |  | read[selected_job] mode=log |  |  | no trusted log value (stale/absent log stream; router fails closed) | 0.153s |
| 27 | 09:30:14.538 | routed reader modes | PASS |  |  | read[selected_job] mode=hybrid |  |  | value='HiRes' source=api age=0.00s latency=152ms | 0.152s |
| 28 | 09:30:14.538 | routed reader modes | SKIP |  |  | agree[selected_job] api vs log |  |  | insufficient values to cross-check | 0.000s |
| 29 | 09:30:14.538 | routed reader modes | PASS |  |  | agree[selected_job] api vs hybrid |  |  | 'HiRes' vs 'HiRes' | 0.000s |
| 30 | 09:30:14.539 | routed reader modes | PASS |  |  | read[scan_status] mode=api |  |  | value='eScanIdle' source=api age=0.00s latency=1ms | 0.001s |
| 31 | 09:30:14.707 | routed reader modes | SKIP |  |  | read[scan_status] mode=log |  |  | no trusted log value (stale/absent log stream; router fails closed) | 0.169s |
| 32 | 09:30:14.856 | routed reader modes | PASS |  |  | read[scan_status] mode=hybrid |  |  | value='eScanIdle' source=api age=0.00s latency=148ms | 0.148s |
| 33 | 09:30:14.856 | routed reader modes | SKIP |  |  | agree[scan_status] api vs log |  |  | insufficient values to cross-check | 0.000s |
| 34 | 09:30:14.856 | routed reader modes | PASS |  |  | agree[scan_status] api vs hybrid |  |  | 'eScanIdle' vs 'eScanIdle' (idle-sense) | 0.000s |
| 35 | 09:30:14.870 | routed reader modes | PASS |  |  | read[hardware_info] mode=api |  |  | value=Microscope='DMI8' source=api age=0.00s latency=13ms | 0.013s |
| 36 | 09:30:15.026 | routed reader modes | PASS |  |  | read[hardware_info] mode=log |  |  | value=Microscope='DMI8' source=log age=1.14s latency=156ms | 0.156s |
| 37 | 09:30:15.181 | routed reader modes | PASS |  |  | read[hardware_info] mode=hybrid |  |  | value=Microscope='DMI8' source=log age=0.17s latency=155ms | 0.155s |
| 38 | 09:30:15.181 | routed reader modes | PASS |  |  | agree[hardware_info] api vs log |  |  | 'DMI8' vs 'DMI8' | 0.000s |
| 39 | 09:30:15.181 | routed reader modes | PASS |  |  | agree[hardware_info] api vs hybrid |  |  | 'DMI8' vs 'DMI8' | 0.000s |
| 40 | 09:30:15.196 | routed reader modes | PASS |  |  | read[job_settings] mode=api |  |  | value=42 contract fields source=api age=0.00s latency=15ms | 0.015s |
| 41 | 09:30:15.349 | routed reader modes | PASS |  |  | read[job_settings] mode=log |  |  | value=42 contract fields source=log age=1.38s latency=153ms | 0.153s |
| 42 | 09:30:15.503 | routed reader modes | PASS |  |  | read[job_settings] mode=hybrid |  |  | value=42 contract fields source=log age=1.53s latency=154ms | 0.154s |
| 43 | 09:30:15.503 | routed reader modes | PASS |  |  | agree[job_settings] api vs log |  |  | all contract fields agree | 0.000s |
| 44 | 09:30:15.504 | routed reader modes | PASS |  |  | agree[job_settings] api vs hybrid |  |  | all contract fields agree | 0.000s |

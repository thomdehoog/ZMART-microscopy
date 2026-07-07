# Hardware validation run report

Every change this run attempted on the instrument is listed below, including failed attempts and restore/cleanup steps (see the *Mutates scope* column). Changes carry their success+CONFIRMED / success+UNCONFIRMED / FAILED result and attempt counts in the *Result* column.

## Run metadata

- **Validator**: `validate_readers_side_by_side`
- **Arguments**: `--read-only --report-dir=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report`
- **Backend**: live LAS X (simulator or scope)
- **Date**: 2026-07-07
- **Started / finished**: 09:28:41 / 09:28:44 (2.9s)
- **Host**: ZMB-Y42H93-STI8 (Windows-10-10.0.26100-SP0)
- **Python**: 3.11.15
- **Driver commit**: aecf1a2 on claude/smart-drivers-code-review-ky4phc (working tree has local changes)
- **Driver log**: `\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\driver_log_20260707-092841.log` (full log-line capture)

## Summary

| Phase | Actions attempted | Passed | Warned | Failed | Skipped | Confirmed | Unconfirmed |
|---|---:|---:|---:|---:|---:|---:|---:|
| read-only parity | 10 | 7 | 0 | 2 | 1 | 0 | 0 |
| routed reader modes | 30 | 22 | 0 | 0 | 8 | 0 | 0 |
| **total** | **40** | **29** | **0** | **2** | **9** | **0** | **0** |

## Timing overview

### Per phase

| Phase | Timed actions | Min | Median | Max |
|---|---:|---:|---:|---:|
| read-only parity | 2 | 0.019s | 0.020s | 0.020s |
| routed reader modes | 18 | 0.000s | 0.161s | 0.174s |

### Per reader mode (routed read latency)

| Mode | Reads | Min | Median | Max | Median reading age |
|---|---:|---:|---:|---:|---:|
| api | 6 | 0.001s | 0.013s | 0.014s | 0.000s |
| log | 6 | 0.000s | 0.164s | 0.168s | 1.282s |
| hybrid | 6 | 0.012s | 0.163s | 0.174s | 0.000s |

### Slowest actions

| Duration | Phase | Action | Status |
|---:|---|---|---|
| 0.174s | routed reader modes | read[scan_status] mode=hybrid | PASS |
| 0.168s | routed reader modes | read[hardware_info] mode=log | PASS |
| 0.167s | routed reader modes | read[scan_status] mode=log | SKIP |
| 0.167s | routed reader modes | read[job_settings] mode=log | PASS |
| 0.165s | routed reader modes | read[hardware_info] mode=hybrid | PASS |
| 0.164s | routed reader modes | read[job_settings] mode=hybrid | PASS |
| 0.162s | routed reader modes | read[xy] mode=hybrid | PASS |
| 0.161s | routed reader modes | read[selected_job] mode=hybrid | PASS |
| 0.161s | routed reader modes | read[xy] mode=log | SKIP |
| 0.160s | routed reader modes | read[selected_job] mode=log | SKIP |

### Unconfirmed / failed changes

None -- every attempted change reported success and confirmed.

## Chronological detail (every attempted action)

| # | Time | Phase | Status | Result | Mutates scope | Action attempted | Args / target | Expected | Observed | Duration |
|---:|---|---|---|---|---|---|---|---|---|---:|
| 1 | 09:28:42.589 | read-only parity | PASS |  |  | get_xy |  |  | api=20ms log_age=3s | 0.020s |
| 2 | 09:28:42.609 | read-only parity | SKIP |  |  | get_jobs (names) |  |  | no authoritative log leg for this datum (API-only); api=['AF Job', 'HiRes', 'Overview'] log=['AF Job', 'HiRes', 'Overview'] | 0.019s |
| 3 | 09:28:42.609 | read-only parity | PASS |  |  | get_selected_job |  |  | api='HiRes' log='HiRes' | 0.000s |
| 4 | 09:28:42.612 | read-only parity | PASS |  |  | get_scan_status (idle-sense) |  |  | api='eScanIdle' log='eScanIdle' log_age=473369s | 0.000s |
| 5 | 09:28:42.625 | read-only parity | PASS |  |  | get_hardware_info (Microscope.name) |  |  |  | 0.000s |
| 6 | 09:28:42.643 | read-only parity | FAIL |  |  | settings[AF Job] |  |  | api=True log=False | 0.000s |
| 7 | 09:28:42.658 | read-only parity | PASS |  |  | settings[HiRes] (42 fields) |  |  | log_age=2s | 0.000s |
| 8 | 09:28:42.672 | read-only parity | PASS |  |  | get_fov[HiRes] |  |  | api=(0.00116, 0.00116) log=(0.00116, 0.00116) | 0.000s |
| 9 | 09:28:42.686 | read-only parity | PASS |  |  | read_zwide_um[HiRes] |  |  | api=0.0 log=0.0 | 0.000s |
| 10 | 09:28:42.700 | read-only parity | FAIL |  |  | settings[Overview] |  |  | api=True log=False | 0.000s |
| 11 | 09:28:42.714 | routed reader modes | PASS |  |  | read[xy] mode=api |  |  | value=(63500.0,41500.0)um source=api age=0.00s latency=13ms | 0.013s |
| 12 | 09:28:42.875 | routed reader modes | SKIP |  |  | read[xy] mode=log |  |  | no trusted log value (stale/absent log stream; router fails closed) | 0.161s |
| 13 | 09:28:43.037 | routed reader modes | PASS |  |  | read[xy] mode=hybrid |  |  | value=(63500.0,41500.0)um source=api age=0.00s latency=162ms | 0.162s |
| 14 | 09:28:43.037 | routed reader modes | SKIP |  |  | agree[xy] api vs log |  |  | insufficient values to cross-check | 0.000s |
| 15 | 09:28:43.037 | routed reader modes | PASS |  |  | agree[xy] api vs hybrid |  |  | delta=(0.00,0.00)um tol=1.0um | 0.000s |
| 16 | 09:28:43.050 | routed reader modes | PASS |  |  | read[jobs] mode=api |  |  | value=['AF Job', 'HiRes', 'Overview'] source=api age=0.00s latency=13ms | 0.013s |
| 17 | 09:28:43.050 | routed reader modes | SKIP |  |  | read[jobs] mode=log |  |  | no trusted log value (stale/absent log stream; router fails closed) err=UnsupportedSource("datum 'jobs' has no log leg") | 0.000s |
| 18 | 09:28:43.063 | routed reader modes | PASS |  |  | read[jobs] mode=hybrid |  |  | value=['AF Job', 'HiRes', 'Overview'] source=api age=0.00s latency=12ms | 0.012s |
| 19 | 09:28:43.063 | routed reader modes | SKIP |  |  | agree[jobs] api vs log |  |  | insufficient values to cross-check | 0.000s |
| 20 | 09:28:43.063 | routed reader modes | PASS |  |  | agree[jobs] api vs hybrid |  |  | ['AF Job', 'HiRes', 'Overview'] vs ['AF Job', 'HiRes', 'Overview'] | 0.000s |
| 21 | 09:28:43.076 | routed reader modes | PASS |  |  | read[selected_job] mode=api |  |  | value='HiRes' source=api age=0.00s latency=13ms | 0.013s |
| 22 | 09:28:43.236 | routed reader modes | SKIP |  |  | read[selected_job] mode=log |  |  | no trusted log value (stale/absent log stream; router fails closed) | 0.160s |
| 23 | 09:28:43.397 | routed reader modes | PASS |  |  | read[selected_job] mode=hybrid |  |  | value='HiRes' source=api age=0.00s latency=161ms | 0.161s |
| 24 | 09:28:43.397 | routed reader modes | SKIP |  |  | agree[selected_job] api vs log |  |  | insufficient values to cross-check | 0.000s |
| 25 | 09:28:43.397 | routed reader modes | PASS |  |  | agree[selected_job] api vs hybrid |  |  | 'HiRes' vs 'HiRes' | 0.000s |
| 26 | 09:28:43.398 | routed reader modes | PASS |  |  | read[scan_status] mode=api |  |  | value='eScanIdle' source=api age=0.00s latency=1ms | 0.001s |
| 27 | 09:28:43.566 | routed reader modes | SKIP |  |  | read[scan_status] mode=log |  |  | no trusted log value (stale/absent log stream; router fails closed) | 0.167s |
| 28 | 09:28:43.740 | routed reader modes | PASS |  |  | read[scan_status] mode=hybrid |  |  | value='eScanIdle' source=api age=0.00s latency=174ms | 0.174s |
| 29 | 09:28:43.740 | routed reader modes | SKIP |  |  | agree[scan_status] api vs log |  |  | insufficient values to cross-check | 0.000s |
| 30 | 09:28:43.740 | routed reader modes | PASS |  |  | agree[scan_status] api vs hybrid |  |  | 'eScanIdle' vs 'eScanIdle' (idle-sense) | 0.000s |
| 31 | 09:28:43.753 | routed reader modes | PASS |  |  | read[hardware_info] mode=api |  |  | value=Microscope='DMI8' source=api age=0.00s latency=13ms | 0.013s |
| 32 | 09:28:43.921 | routed reader modes | PASS |  |  | read[hardware_info] mode=log |  |  | value=Microscope='DMI8' source=log age=1.14s latency=168ms | 0.168s |
| 33 | 09:28:44.086 | routed reader modes | PASS |  |  | read[hardware_info] mode=hybrid |  |  | value=Microscope='DMI8' source=log age=1.31s latency=165ms | 0.165s |
| 34 | 09:28:44.086 | routed reader modes | PASS |  |  | agree[hardware_info] api vs log |  |  | 'DMI8' vs 'DMI8' | 0.000s |
| 35 | 09:28:44.086 | routed reader modes | PASS |  |  | agree[hardware_info] api vs hybrid |  |  | 'DMI8' vs 'DMI8' | 0.000s |
| 36 | 09:28:44.101 | routed reader modes | PASS |  |  | read[job_settings] mode=api |  |  | value=42 contract fields source=api age=0.00s latency=14ms | 0.014s |
| 37 | 09:28:44.267 | routed reader modes | PASS |  |  | read[job_settings] mode=log |  |  | value=42 contract fields source=log age=1.43s latency=167ms | 0.167s |
| 38 | 09:28:44.432 | routed reader modes | PASS |  |  | read[job_settings] mode=hybrid |  |  | value=42 contract fields source=log age=0.18s latency=164ms | 0.164s |
| 39 | 09:28:44.432 | routed reader modes | PASS |  |  | agree[job_settings] api vs log |  |  | all contract fields agree | 0.000s |
| 40 | 09:28:44.433 | routed reader modes | PASS |  |  | agree[job_settings] api vs hybrid |  |  | all contract fields agree | 0.000s |

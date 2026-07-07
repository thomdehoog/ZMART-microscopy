# Hardware validation run report

Every change this run attempted on the instrument is listed below, including failed attempts and restore/cleanup steps (see the *Mutates scope* column). Changes carry their success+CONFIRMED / success+UNCONFIRMED / FAILED result and attempt counts in the *Result* column.

## Run metadata

- **Validator**: `validate_hardware`
- **Arguments**: `--read-only --allow-missing-lasx --state-reader-mode log --output=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\hardware_validate_log.jsonl --report-dir=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report`
- **Backend**: live LAS X (simulator or scope)
- **Date**: 2026-07-07
- **Started / finished**: 09:31:13 / 09:31:14 (1.1s)
- **Host**: ZMB-Y42H93-STI8 (Windows-10-10.0.26100-SP0)
- **Python**: 3.11.15
- **Driver commit**: aecf1a2 on claude/smart-drivers-code-review-ky4phc (working tree has local changes)
- **Driver log**: `\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\driver_log_20260707-093113.log` (full log-line capture)

## Summary

| Phase | Actions attempted | Passed | Warned | Failed | Skipped | Confirmed | Unconfirmed |
|---|---:|---:|---:|---:|---:|---:|---:|
| setup | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| read-only | 6 | 5 | 0 | 0 | 1 | 0 | 0 |
| **total** | **7** | **6** | **0** | **0** | **1** | **0** | **0** |

## Timing overview

### Per phase

| Phase | Timed actions | Min | Median | Max |
|---|---:|---:|---:|---:|
| read-only | 3 | 0.125s | 0.140s | 0.157s |

### Slowest actions

| Duration | Phase | Action | Status |
|---:|---|---|---|
| 0.157s | read-only | get_scan_status | PASS |
| 0.140s | read-only | get_hardware_info | PASS |
| 0.125s | read-only | get_xy | PASS |

### Unconfirmed / failed changes

None -- every attempted change reported success and confirmed.

## Chronological detail (every attempted action)

| # | Time | Phase | Status | Result | Mutates scope | Action attempted | Args / target | Expected | Observed | Duration |
|---:|---|---|---|---|---|---|---|---|---|---:|
| 1 | 09:31:14.346 | setup | PASS |  |  | limits: connect handshake | limits_path='<machine-local snapshot>' |  |  | 0.000s |
| 2 | 09:31:14.350 | read-only | PASS |  |  | ping |  |  |  | 0.000s |
| 3 | 09:31:14.506 | read-only | PASS |  |  | get_scan_status |  |  |  | 0.157s |
| 4 | 09:31:14.508 | read-only | PASS |  |  | get_jobs |  |  |  | 0.000s |
| 5 | 09:31:14.645 | read-only | PASS |  |  | get_hardware_info |  |  |  | 0.140s |
| 6 | 09:31:14.779 | read-only | PASS |  |  | get_xy |  |  |  | 0.125s |
| 7 | 09:31:14.781 | read-only | SKIP |  |  | job: resolve |  |  | job list is API-only (no log leg); enumerating via API | 0.000s |

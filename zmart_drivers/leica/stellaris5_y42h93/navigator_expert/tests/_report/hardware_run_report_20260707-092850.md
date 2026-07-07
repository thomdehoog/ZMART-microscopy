# Hardware validation run report

Every change this run attempted on the instrument is listed below, including failed attempts and restore/cleanup steps (see the *Mutates scope* column). Changes carry their success+CONFIRMED / success+UNCONFIRMED / FAILED result and attempt counts in the *Result* column.

## Run metadata

- **Validator**: `validate_hardware`
- **Arguments**: `--read-only --allow-missing-lasx --state-reader-mode log --output=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\hardware_validate_log.jsonl --report-dir=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report`
- **Backend**: live LAS X (simulator or scope)
- **Date**: 2026-07-07
- **Started / finished**: 09:28:50 / 09:28:51 (1.2s)
- **Host**: ZMB-Y42H93-STI8 (Windows-10-10.0.26100-SP0)
- **Python**: 3.11.15
- **Driver commit**: aecf1a2 on claude/smart-drivers-code-review-ky4phc (working tree has local changes)
- **Driver log**: `\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\driver_log_20260707-092850.log` (full log-line capture)

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
| read-only | 3 | 0.141s | 0.156s | 0.172s |

### Slowest actions

| Duration | Phase | Action | Status |
|---:|---|---|---|
| 0.172s | read-only | get_scan_status | PASS |
| 0.156s | read-only | get_xy | PASS |
| 0.141s | read-only | get_hardware_info | PASS |

### Unconfirmed / failed changes

None -- every attempted change reported success and confirmed.

## Chronological detail (every attempted action)

| # | Time | Phase | Status | Result | Mutates scope | Action attempted | Args / target | Expected | Observed | Duration |
|---:|---|---|---|---|---|---|---|---|---|---:|
| 1 | 09:28:50.843 | setup | PASS |  |  | limits: connect handshake | limits_path='<machine-local snapshot>' |  |  | 0.000s |
| 2 | 09:28:50.847 | read-only | PASS |  |  | ping |  |  |  | 0.000s |
| 3 | 09:28:51.013 | read-only | PASS |  |  | get_scan_status |  |  |  | 0.172s |
| 4 | 09:28:51.015 | read-only | PASS |  |  | get_jobs |  |  |  | 0.000s |
| 5 | 09:28:51.168 | read-only | PASS |  |  | get_hardware_info |  |  |  | 0.141s |
| 6 | 09:28:51.325 | read-only | PASS |  |  | get_xy |  |  |  | 0.156s |
| 7 | 09:28:51.326 | read-only | SKIP |  |  | job: resolve |  |  | job list is API-only (no log leg); enumerating via API | 0.000s |

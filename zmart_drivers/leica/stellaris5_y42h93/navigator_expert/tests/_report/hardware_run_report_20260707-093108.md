# Hardware validation run report

Every change this run attempted on the instrument is listed below, including failed attempts and restore/cleanup steps (see the *Mutates scope* column). Changes carry their success+CONFIRMED / success+UNCONFIRMED / FAILED result and attempt counts in the *Result* column.

## Run metadata

- **Validator**: `validate_zmart_adapter`
- **Arguments**: `--read-only --allow-missing-lasx --output=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\zmart_adapter_validate.jsonl --report-dir=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report`
- **Backend**: live LAS X (simulator or scope)
- **Date**: 2026-07-07
- **Started / finished**: 09:31:08 / 09:31:10 (1.9s)
- **Host**: ZMB-Y42H93-STI8 (Windows-10-10.0.26100-SP0)
- **Python**: 3.11.15
- **Driver commit**: aecf1a2 on claude/smart-drivers-code-review-ky4phc (working tree has local changes)
- **Driver log**: `\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\driver_log_20260707-093108.log` (full log-line capture)

## Summary

| Phase | Actions attempted | Passed | Warned | Failed | Skipped | Confirmed | Unconfirmed |
|---|---:|---:|---:|---:|---:|---:|---:|
| read-only | 17 | 17 | 0 | 0 | 0 | 0 | 0 |
| **total** | **17** | **17** | **0** | **0** | **0** | **0** | **0** |

## Timing overview

### Per phase

| Phase | Timed actions | Min | Median | Max |
|---|---:|---:|---:|---:|
| read-only | 4 | 0.015s | 0.054s | 0.750s |

### Slowest actions

| Duration | Phase | Action | Status |
|---:|---|---|---|
| 0.750s | read-only | get_context | PASS |
| 0.062s | read-only | get_xyz | PASS |
| 0.047s | read-only | get_state | PASS |
| 0.015s | read-only | get_acquisition_options | PASS |

### Unconfirmed / failed changes

None -- every attempted change reported success and confirmed.

## Chronological detail (every attempted action)

| # | Time | Phase | Status | Result | Mutates scope | Action attempted | Args / target | Expected | Observed | Duration |
|---:|---|---|---|---|---|---|---|---|---|---:|
| 1 | 09:31:09.760 | read-only | PASS |  |  | get_instruments |  |  |  | 0.000s |
| 2 | 09:31:09.761 | read-only | PASS |  |  | registry: leica adapter registered |  |  | expected=True actual=True | 0.000s |
| 3 | 09:31:09.762 | read-only | PASS |  |  | get_actuators |  |  |  | 0.000s |
| 4 | 09:31:09.763 | read-only | PASS |  |  | actuators: expected menu |  |  | expected={'x': ['motoric'], 'y': ['motoric'], 'z': ['z-wide', 'z-galvo']} actual={'x': ['motoric'], 'y': ['motoric'], 'z': ['z-wide', 'z-galvo']} | 0.000s |
| 5 | 09:31:09.831 | read-only | PASS |  |  | get_xyz |  |  |  | 0.062s |
| 6 | 09:31:09.832 | read-only | PASS |  |  | get_xyz: x unit is um |  |  | expected='um' actual='um' | 0.000s |
| 7 | 09:31:09.833 | read-only | PASS |  |  | get_xyz: y unit is um |  |  | expected='um' actual='um' | 0.000s |
| 8 | 09:31:09.834 | read-only | PASS |  |  | get_xyz: z unit is um |  |  | expected='um' actual='um' | 0.000s |
| 9 | 09:31:09.836 | read-only | PASS |  |  | get_xyz: hardware block complete |  |  | expected=True actual=True | 0.000s |
| 10 | 09:31:09.837 | read-only | PASS |  |  | get_xyz: objective has a name |  |  | expected=True actual=True | 0.000s |
| 11 | 09:31:09.877 | read-only | PASS |  |  | get_state |  |  |  | 0.047s |
| 12 | 09:31:09.912 | read-only | PASS |  |  | get_acquisition_options |  |  |  | 0.015s |
| 13 | 09:31:09.913 | read-only | PASS |  |  | get_state: changeable job is in the job list |  |  | expected=True actual=True | 0.000s |
| 14 | 09:31:09.914 | read-only | PASS |  |  | get_state: observed carries an identity |  |  | expected=True actual=True | 0.000s |
| 15 | 09:31:09.916 | read-only | PASS |  |  | get_acquisition_options: active exporter is offered |  |  | expected=True actual=True | 0.000s |
| 16 | 09:31:10.657 | read-only | PASS |  |  | get_context |  |  |  | 0.750s |
| 17 | 09:31:10.659 | read-only | PASS |  |  | get_context: has session_hash6 |  |  | expected=True actual=True | 0.000s |

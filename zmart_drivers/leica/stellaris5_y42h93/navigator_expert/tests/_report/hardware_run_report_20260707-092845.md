# Hardware validation run report

Every change this run attempted on the instrument is listed below, including failed attempts and restore/cleanup steps (see the *Mutates scope* column). Changes carry their success+CONFIRMED / success+UNCONFIRMED / FAILED result and attempt counts in the *Result* column.

## Run metadata

- **Validator**: `validate_zmart_adapter`
- **Arguments**: `--read-only --allow-missing-lasx --output=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\zmart_adapter_validate.jsonl --report-dir=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report`
- **Backend**: live LAS X (simulator or scope)
- **Date**: 2026-07-07
- **Started / finished**: 09:28:45 / 09:28:47 (1.9s)
- **Host**: ZMB-Y42H93-STI8 (Windows-10-10.0.26100-SP0)
- **Python**: 3.11.15
- **Driver commit**: aecf1a2 on claude/smart-drivers-code-review-ky4phc (working tree has local changes)
- **Driver log**: `\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\driver_log_20260707-092845.log` (full log-line capture)

## Summary

| Phase | Actions attempted | Passed | Warned | Failed | Skipped | Confirmed | Unconfirmed |
|---|---:|---:|---:|---:|---:|---:|---:|
| read-only | 17 | 17 | 0 | 0 | 0 | 0 | 0 |
| **total** | **17** | **17** | **0** | **0** | **0** | **0** | **0** |

## Timing overview

### Per phase

| Phase | Timed actions | Min | Median | Max |
|---|---:|---:|---:|---:|
| read-only | 3 | 0.031s | 0.063s | 0.844s |

### Slowest actions

| Duration | Phase | Action | Status |
|---:|---|---|---|
| 0.844s | read-only | get_context | PASS |
| 0.063s | read-only | get_xyz | PASS |
| 0.031s | read-only | get_state | PASS |

### Unconfirmed / failed changes

None -- every attempted change reported success and confirmed.

## Chronological detail (every attempted action)

| # | Time | Phase | Status | Result | Mutates scope | Action attempted | Args / target | Expected | Observed | Duration |
|---:|---|---|---|---|---|---|---|---|---|---:|
| 1 | 09:28:46.392 | read-only | PASS |  |  | get_instruments |  |  |  | 0.000s |
| 2 | 09:28:46.393 | read-only | PASS |  |  | registry: leica adapter registered |  |  | expected=True actual=True | 0.000s |
| 3 | 09:28:46.394 | read-only | PASS |  |  | get_actuators |  |  |  | 0.000s |
| 4 | 09:28:46.395 | read-only | PASS |  |  | actuators: expected menu |  |  | expected={'x': ['motoric'], 'y': ['motoric'], 'z': ['z-wide', 'z-galvo']} actual={'x': ['motoric'], 'y': ['motoric'], 'z': ['z-wide', 'z-galvo']} | 0.000s |
| 5 | 09:28:46.452 | read-only | PASS |  |  | get_xyz |  |  |  | 0.063s |
| 6 | 09:28:46.453 | read-only | PASS |  |  | get_xyz: x unit is um |  |  | expected='um' actual='um' | 0.000s |
| 7 | 09:28:46.455 | read-only | PASS |  |  | get_xyz: y unit is um |  |  | expected='um' actual='um' | 0.000s |
| 8 | 09:28:46.456 | read-only | PASS |  |  | get_xyz: z unit is um |  |  | expected='um' actual='um' | 0.000s |
| 9 | 09:28:46.457 | read-only | PASS |  |  | get_xyz: hardware block complete |  |  | expected=True actual=True | 0.000s |
| 10 | 09:28:46.458 | read-only | PASS |  |  | get_xyz: objective has a name |  |  | expected=True actual=True | 0.000s |
| 11 | 09:28:46.497 | read-only | PASS |  |  | get_state |  |  |  | 0.031s |
| 12 | 09:28:46.512 | read-only | PASS |  |  | get_acquisition_options |  |  |  | 0.000s |
| 13 | 09:28:46.513 | read-only | PASS |  |  | get_state: changeable job is in the job list |  |  | expected=True actual=True | 0.000s |
| 14 | 09:28:46.514 | read-only | PASS |  |  | get_state: observed carries an identity |  |  | expected=True actual=True | 0.000s |
| 15 | 09:28:46.515 | read-only | PASS |  |  | get_acquisition_options: active exporter is offered |  |  | expected=True actual=True | 0.000s |
| 16 | 09:28:47.359 | read-only | PASS |  |  | get_context |  |  |  | 0.844s |
| 17 | 09:28:47.360 | read-only | PASS |  |  | get_context: has session_hash6 |  |  | expected=True actual=True | 0.000s |

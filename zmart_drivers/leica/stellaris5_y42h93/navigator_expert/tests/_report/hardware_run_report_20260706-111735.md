# Hardware validation run report

Every change this run attempted on the instrument is listed below, including failed attempts and restore/cleanup steps (see the *Mutates scope* column). Changes carry their success+CONFIRMED / success+UNCONFIRMED / FAILED result and attempt counts in the *Result* column.

## Run metadata

- **Validator**: `validate_zmart_adapter`
- **Arguments**: `--yes --allow-move --allow-state --allow-missing-lasx --output=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\zmart_adapter_validate.jsonl --report-dir=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report`
- **Backend**: live LAS X (simulator or scope)
- **Date**: 2026-07-06
- **Started / finished**: 11:17:35 / 11:17:39 (4.4s)
- **Host**: ZMB-LASX-PC (Windows-10-10.0.26200-SP0)
- **Python**: 3.11.15
- **Driver commit**: unknown on unknown
- **Driver log**: `\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\driver_log_20260706-111735.log` (full log-line capture)

## Summary

| Phase | Actions attempted | Passed | Warned | Failed | Skipped | Confirmed | Unconfirmed |
|---|---:|---:|---:|---:|---:|---:|---:|
| read-only | 19 | 19 | 0 | 0 | 0 | 0 | 0 |
| move (set_origin + set_xyz) | 16 | 8 | 0 | 7 | 1 | 0 | 0 |
| state (capture / switch / restore) | 7 | 7 | 0 | 0 | 0 | 0 | 0 |
| setup | 2 | 0 | 0 | 0 | 2 | 0 | 0 |
| **total** | **44** | **34** | **0** | **7** | **3** | **0** | **0** |

## Timing overview

### Per phase

| Phase | Timed actions | Min | Median | Max |
|---|---:|---:|---:|---:|
| read-only | 4 | 0.015s | 0.055s | 0.641s |
| move (set_origin + set_xyz) | 7 | 0.031s | 0.047s | 0.047s |
| state (capture / switch / restore) | 5 | 0.047s | 0.203s | 1.000s |

### Slowest actions

| Duration | Phase | Action | Status |
|---:|---|---|---|
| 1.000s | state (capture / switch / restore) | set_state: switch job | PASS |
| 0.985s | state (capture / switch / restore) | set_state: restore | PASS |
| 0.641s | read-only | get_context | PASS |
| 0.203s | state (capture / switch / restore) | get_state: after restore (settled) | PASS |
| 0.125s | state (capture / switch / restore) | get_state: after switch (settled) | PASS |
| 0.063s | read-only | get_xyz | PASS |
| 0.047s | read-only | get_state | PASS |
| 0.047s | move (set_origin + set_xyz) | set_origin | PASS |
| 0.047s | move (set_origin + set_xyz) | get_xyz after set_origin | PASS |
| 0.047s | move (set_origin + set_xyz) | get_xyz after XY | PASS |

### Unconfirmed / failed changes

| Phase | Action | Result | Attempts | Duration | Observed |
|---|---|---|---|---:|---|
| move (set_origin + set_xyz) | set_xyz: XY move | FAILED |  | 0.031s | RuntimeError: move_xy refused: set_xyz: x_um=25.0 outside [1000.0, 130000.0] (constraint 'stage.x'; limits: C:\ProgramData\zmart-microscopy\leica\stellaris5_y4… |
| move (set_origin + set_xyz) | set_xyz: z-galvo move | FAILED |  | 0.047s | RuntimeError: move_xy refused: set_xyz: x_um=25.0 outside [1000.0, 130000.0] (constraint 'stage.x'; limits: C:\ProgramData\zmart-microscopy\leica\stellaris5_y4… |
| move (set_origin + set_xyz) | move: restore XY + focus (frame 0,0,0) | FAILED |  | 0.047s | RuntimeError: move_xy refused: set_xyz: x_um=0.0 outside [1000.0, 130000.0] (constraint 'stage.x'; limits: C:\ProgramData\zmart-microscopy\leica\stellaris5_y42… |

## Chronological detail (every attempted action)

| # | Time | Phase | Status | Result | Mutates scope | Action attempted | Args / target | Expected | Observed | Duration |
|---:|---|---|---|---|---|---|---|---|---|---:|
| 1 | 11:17:36.033 | read-only | PASS |  |  | get_instruments |  |  |  | 0.000s |
| 2 | 11:17:36.033 | read-only | PASS |  |  | registry: leica adapter registered |  |  | expected=True actual=True | 0.000s |
| 3 | 11:17:36.035 | read-only | PASS |  |  | get_actuators |  |  |  | 0.000s |
| 4 | 11:17:36.037 | read-only | PASS |  |  | actuators: expected menu |  |  | expected={'x': ['motoric'], 'y': ['motoric'], 'z': ['z-wide', 'z-galvo']} actual={'x': ['motoric'], 'y': ['motoric'], 'z': ['z-wide', 'z-galvo']} | 0.000s |
| 5 | 11:17:36.096 | read-only | PASS |  |  | get_xyz |  |  |  | 0.063s |
| 6 | 11:17:36.096 | read-only | PASS |  |  | get_xyz: x unit is um |  |  | expected='um' actual='um' | 0.000s |
| 7 | 11:17:36.096 | read-only | PASS |  |  | get_xyz: y unit is um |  |  | expected='um' actual='um' | 0.000s |
| 8 | 11:17:36.100 | read-only | PASS |  |  | get_xyz: z unit is um |  |  | expected='um' actual='um' | 0.000s |
| 9 | 11:17:36.100 | read-only | PASS |  |  | get_xyz: hardware block complete |  |  | expected=True actual=True | 0.000s |
| 10 | 11:17:36.100 | read-only | PASS |  |  | get_xyz: frame x == hardware x_um |  |  | expected=0.0 actual=0.0 tol=0.05 | 0.000s |
| 11 | 11:17:36.100 | read-only | PASS |  |  | get_xyz: frame z == z_wide + z_galvo |  |  | expected=-7200.0 actual=-7200.0 tol=0.05 | 0.000s |
| 12 | 11:17:36.100 | read-only | PASS |  |  | get_xyz: objective has a name |  |  | expected=True actual=True | 0.000s |
| 13 | 11:17:36.144 | read-only | PASS |  |  | get_state |  |  |  | 0.047s |
| 14 | 11:17:36.157 | read-only | PASS |  |  | get_acquisition_options |  |  |  | 0.015s |
| 15 | 11:17:36.157 | read-only | PASS |  |  | get_state: changeable job is in the job list |  |  | expected=True actual=True | 0.000s |
| 16 | 11:17:36.157 | read-only | PASS |  |  | get_state: observed carries an identity |  |  | expected=True actual=True | 0.000s |
| 17 | 11:17:36.157 | read-only | PASS |  |  | get_acquisition_options: active exporter is offered |  |  | expected=True actual=True | 0.000s |
| 18 | 11:17:36.800 | read-only | PASS |  |  | get_context |  |  |  | 0.641s |
| 19 | 11:17:36.800 | read-only | PASS |  |  | get_context: has session_hash6 |  |  | expected=True actual=True | 0.000s |
| 20 | 11:17:36.881 | move (set_origin + set_xyz) | PASS |  | YES | set_origin |  |  |  | 0.047s |
| 21 | 11:17:36.923 | move (set_origin + set_xyz) | PASS |  |  | get_xyz after set_origin |  |  |  | 0.047s |
| 22 | 11:17:36.923 | move (set_origin + set_xyz) | PASS |  |  | origin: frame x -> 0 |  |  | expected=0.0 actual=0.0 tol=20.0 | 0.000s |
| 23 | 11:17:36.923 | move (set_origin + set_xyz) | PASS |  |  | origin: frame y -> 0 |  |  | expected=0.0 actual=0.0 tol=20.0 | 0.000s |
| 24 | 11:17:36.923 | move (set_origin + set_xyz) | PASS |  |  | origin: frame z -> 0 |  |  | expected=0.0 actual=0.0 tol=1.0 | 0.000s |
| 25 | 11:17:36.968 | move (set_origin + set_xyz) | FAIL | FAILED | YES | set_xyz: XY move | to_frame=(25.0, 25.0, 0.0) z_actuator='z-galvo' |  | RuntimeError: move_xy refused: set_xyz: x_um=25.0 outside [1000.0, 130000.0] (constraint 'stage.x'; limits: C:\ProgramData\zmart-microscopy\leica\stellaris5_y42h93\navigator_expert\2026-07-06T09-17-14-792088Z\limits.json, source=defaults) | 0.031s |
| 26 | 11:17:37.009 | move (set_origin + set_xyz) | PASS |  |  | get_xyz after XY |  |  |  | 0.047s |
| 27 | 11:17:37.009 | move (set_origin + set_xyz) | FAIL |  |  | xy: frame x |  |  | expected=25.0 actual=0.0 tol=20.0 | 0.000s |
| 28 | 11:17:37.009 | move (set_origin + set_xyz) | FAIL |  |  | xy: frame y |  |  | expected=25.0 actual=0.0 tol=20.0 | 0.000s |
| 29 | 11:17:37.049 | move (set_origin + set_xyz) | FAIL | FAILED | YES | set_xyz: z-galvo move | to_frame=(25.0, 25.0, 2.0) z_actuator='z-galvo' |  | RuntimeError: move_xy refused: set_xyz: x_um=25.0 outside [1000.0, 130000.0] (constraint 'stage.x'; limits: C:\ProgramData\zmart-microscopy\leica\stellaris5_y42h93\navigator_expert\2026-07-06T09-17-14-792088Z\limits.json, source=defaults) | 0.047s |
| 30 | 11:17:37.090 | move (set_origin + set_xyz) | PASS |  |  | get_xyz after z-galvo |  |  |  | 0.031s |
| 31 | 11:17:37.090 | move (set_origin + set_xyz) | FAIL |  |  | zgalvo: frame z |  |  | expected=2.0 actual=0.0 tol=1.0 | 0.000s |
| 32 | 11:17:37.090 | move (set_origin + set_xyz) | FAIL |  |  | zgalvo: drive moved by delta (sign check) |  |  | expected=2.0 actual=0.0 tol=1.0 | 0.000s |
| 33 | 11:17:37.090 | move (set_origin + set_xyz) | PASS |  |  | zgalvo: z-wide drive unchanged |  |  | expected=-7200.0 actual=-7200.0 tol=1.0 | 0.000s |
| 34 | 11:17:37.090 | move (set_origin + set_xyz) | SKIP |  |  | zwide: drive leg |  |  | z-wide baseline -7200.0 / target -7197.0 outside envelope [0.0, 25000.0] (simulator artifact; validates on a scope) | 0.000s |
| 35 | 11:17:37.132 | move (set_origin + set_xyz) | FAIL | FAILED | YES | move: restore XY + focus (frame 0,0,0) | x_um=0.0 y_um=0.0 z_wide_um=-7200.0 z_galvo_um=-0.0 job='Overview' |  | RuntimeError: move_xy refused: set_xyz: x_um=0.0 outside [1000.0, 130000.0] (constraint 'stage.x'; limits: C:\ProgramData\zmart-microscopy\leica\stellaris5_y42h93\navigator_expert\2026-07-06T09-17-14-792088Z\limits.json, source=defaults) | 0.047s |
| 36 | 11:17:37.175 | state (capture / switch / restore) | PASS |  |  | get_state: capture |  |  |  | 0.047s |
| 37 | 11:17:38.200 | state (capture / switch / restore) | PASS |  | YES | set_state: switch job | to='HiRes' from='Overview' | to='HiRes' |  | 1.000s |
| 38 | 11:17:38.321 | state (capture / switch / restore) | PASS |  |  | get_state: after switch (settled) |  |  |  | 0.125s |
| 39 | 11:17:38.323 | state (capture / switch / restore) | PASS |  |  | state: switched |  |  | expected='HiRes' actual='HiRes' | 0.000s |
| 40 | 11:17:39.308 | state (capture / switch / restore) | PASS |  | YES | set_state: restore | restore_to='Overview' | restore_to='Overview' |  | 0.985s |
| 41 | 11:17:39.505 | state (capture / switch / restore) | PASS |  |  | get_state: after restore (settled) |  |  |  | 0.203s |
| 42 | 11:17:39.507 | state (capture / switch / restore) | PASS |  |  | state: restored |  |  | expected='Overview' actual='Overview' | 0.000s |
| 43 | 11:17:39.507 | setup | SKIP |  |  | phase: autofocus |  |  | use --allow-autofocus to enable | 0.000s |
| 44 | 11:17:39.509 | setup | SKIP |  |  | phase: acquire |  |  | use --allow-acquire to enable | 0.000s |

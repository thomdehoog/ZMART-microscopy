# Hardware validation run report

Every change this run attempted on the instrument is listed below, including failed attempts and restore/cleanup steps (see the *Mutates scope* column). Changes carry their success+CONFIRMED / success+UNCONFIRMED / FAILED result and attempt counts in the *Result* column.

## Run metadata

- **Validator**: `validate_zmart_adapter`
- **Arguments**: `--yes --allow-move --allow-state --allow-missing-lasx --output=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\zmart_adapter_validate.jsonl --report-dir=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report`
- **Backend**: live LAS X (simulator or scope)
- **Date**: 2026-07-06
- **Started / finished**: 14:00:42 / 14:00:52 (10.1s)
- **Host**: ZMB-LASX-PC (Windows-10-10.0.26200-SP0)
- **Python**: 3.11.15
- **Driver commit**: unknown on unknown
- **Driver log**: `\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\driver_log_20260706-140042.log` (full log-line capture)

## Summary

| Phase | Actions attempted | Passed | Warned | Failed | Skipped | Confirmed | Unconfirmed |
|---|---:|---:|---:|---:|---:|---:|---:|
| read-only | 17 | 17 | 0 | 0 | 0 | 0 | 0 |
| move (set_origin + set_xyz) | 21 | 21 | 0 | 0 | 0 | 0 | 0 |
| state (capture / switch / restore) | 7 | 7 | 0 | 0 | 0 | 0 | 0 |
| setup | 2 | 0 | 0 | 0 | 2 | 0 | 0 |
| **total** | **47** | **45** | **0** | **0** | **2** | **0** | **0** |

## Timing overview

### Per phase

| Phase | Timed actions | Min | Median | Max |
|---|---:|---:|---:|---:|
| read-only | 4 | 0.016s | 0.047s | 0.531s |
| move (set_origin + set_xyz) | 10 | 0.015s | 0.047s | 0.297s |
| state (capture / switch / restore) | 5 | 0.047s | 0.906s | 5.234s |

### Slowest actions

| Duration | Phase | Action | Status |
|---:|---|---|---|
| 5.234s | state (capture / switch / restore) | get_state: after restore (settled) | PASS |
| 0.937s | state (capture / switch / restore) | set_state: switch job | PASS |
| 0.906s | state (capture / switch / restore) | set_state: restore | PASS |
| 0.531s | read-only | get_context | PASS |
| 0.297s | move (set_origin + set_xyz) | move: restore XY + focus (frame 0,0,0) | PASS |
| 0.219s | move (set_origin + set_xyz) | set_xyz: XY move | PASS |
| 0.188s | move (set_origin + set_xyz) | set_xyz: z-wide move | PASS |
| 0.188s | state (capture / switch / restore) | get_state: after switch (settled) | PASS |
| 0.187s | move (set_origin + set_xyz) | set_xyz: z-galvo move | PASS |
| 0.047s | read-only | get_xyz | PASS |

### Unconfirmed / failed changes

None -- every attempted change reported success and confirmed.

## Chronological detail (every attempted action)

| # | Time | Phase | Status | Result | Mutates scope | Action attempted | Args / target | Expected | Observed | Duration |
|---:|---|---|---|---|---|---|---|---|---|---:|
| 1 | 14:00:43.324 | read-only | PASS |  |  | get_instruments |  |  |  | 0.000s |
| 2 | 14:00:43.324 | read-only | PASS |  |  | registry: leica adapter registered |  |  | expected=True actual=True | 0.000s |
| 3 | 14:00:43.324 | read-only | PASS |  |  | get_actuators |  |  |  | 0.000s |
| 4 | 14:00:43.324 | read-only | PASS |  |  | actuators: expected menu |  |  | expected={'x': ['motoric'], 'y': ['motoric'], 'z': ['z-wide', 'z-galvo']} actual={'x': ['motoric'], 'y': ['motoric'], 'z': ['z-wide', 'z-galvo']} | 0.000s |
| 5 | 14:00:43.379 | read-only | PASS |  |  | get_xyz |  |  |  | 0.047s |
| 6 | 14:00:43.379 | read-only | PASS |  |  | get_xyz: x unit is um |  |  | expected='um' actual='um' | 0.000s |
| 7 | 14:00:43.379 | read-only | PASS |  |  | get_xyz: y unit is um |  |  | expected='um' actual='um' | 0.000s |
| 8 | 14:00:43.379 | read-only | PASS |  |  | get_xyz: z unit is um |  |  | expected='um' actual='um' | 0.000s |
| 9 | 14:00:43.379 | read-only | PASS |  |  | get_xyz: hardware block complete |  |  | expected=True actual=True | 0.000s |
| 10 | 14:00:43.379 | read-only | PASS |  |  | get_xyz: objective has a name |  |  | expected=True actual=True | 0.000s |
| 11 | 14:00:43.423 | read-only | PASS |  |  | get_state |  |  |  | 0.047s |
| 12 | 14:00:43.437 | read-only | PASS |  |  | get_acquisition_options |  |  |  | 0.016s |
| 13 | 14:00:43.437 | read-only | PASS |  |  | get_state: changeable job is in the job list |  |  | expected=True actual=True | 0.000s |
| 14 | 14:00:43.437 | read-only | PASS |  |  | get_state: observed carries an identity |  |  | expected=True actual=True | 0.000s |
| 15 | 14:00:43.437 | read-only | PASS |  |  | get_acquisition_options: active exporter is offered |  |  | expected=True actual=True | 0.000s |
| 16 | 14:00:43.974 | read-only | PASS |  |  | get_context |  |  |  | 0.531s |
| 17 | 14:00:43.977 | read-only | PASS |  |  | get_context: has session_hash6 |  |  | expected=True actual=True | 0.000s |
| 18 | 14:00:44.058 | move (set_origin + set_xyz) | PASS |  | YES | set_origin |  |  |  | 0.047s |
| 19 | 14:00:44.098 | move (set_origin + set_xyz) | PASS |  |  | get_xyz after set_origin |  |  |  | 0.031s |
| 20 | 14:00:44.098 | move (set_origin + set_xyz) | PASS |  |  | origin: frame x -> 0 |  |  | expected=0.0 actual=0.0 tol=20.0 | 0.000s |
| 21 | 14:00:44.098 | move (set_origin + set_xyz) | PASS |  |  | origin: frame y -> 0 |  |  | expected=0.0 actual=0.0 tol=20.0 | 0.000s |
| 22 | 14:00:44.098 | move (set_origin + set_xyz) | PASS |  |  | origin: frame z -> 0 |  |  | expected=0.0 actual=0.0 tol=1.0 | 0.000s |
| 23 | 14:00:44.307 | move (set_origin + set_xyz) | PASS |  | YES | set_xyz: XY move | to_frame=(25.0, 25.0, 0.0) z_actuator='z-galvo' |  |  | 0.219s |
| 24 | 14:00:44.347 | move (set_origin + set_xyz) | PASS |  |  | get_xyz after XY |  |  |  | 0.031s |
| 25 | 14:00:44.347 | move (set_origin + set_xyz) | PASS |  |  | xy: frame x |  |  | expected=25.0 actual=20.000000000007276 tol=20.0 | 0.000s |
| 26 | 14:00:44.347 | move (set_origin + set_xyz) | PASS |  |  | xy: frame y |  |  | expected=25.0 actual=20.0 tol=20.0 | 0.000s |
| 27 | 14:00:44.537 | move (set_origin + set_xyz) | PASS |  | YES | set_xyz: z-galvo move | to_frame=(25.0, 25.0, 2.0) z_actuator='z-galvo' |  |  | 0.187s |
| 28 | 14:00:44.577 | move (set_origin + set_xyz) | PASS |  |  | get_xyz after z-galvo |  |  |  | 0.047s |
| 29 | 14:00:44.577 | move (set_origin + set_xyz) | PASS |  |  | zgalvo: frame z |  |  | expected=2.0 actual=2.0 tol=1.0 | 0.000s |
| 30 | 14:00:44.577 | move (set_origin + set_xyz) | PASS |  |  | zgalvo: drive moved by delta (sign check) |  |  | expected=2.0 actual=2.0 tol=1.0 | 0.000s |
| 31 | 14:00:44.577 | move (set_origin + set_xyz) | PASS |  |  | zgalvo: z-wide drive unchanged |  |  | expected=0.0 actual=0.0 tol=1.0 | 0.000s |
| 32 | 14:00:44.769 | move (set_origin + set_xyz) | PASS |  | YES | set_xyz: z-wide move | to_frame=(25.0, 25.0, 5.0) z_actuator='z-wide' |  |  | 0.188s |
| 33 | 14:00:44.809 | move (set_origin + set_xyz) | PASS |  |  | get_xyz after z-wide |  |  |  | 0.047s |
| 34 | 14:00:44.809 | move (set_origin + set_xyz) | PASS |  |  | zwide: frame z is additive (z-wide + z-galvo) |  |  | expected=5.0 actual=5.0 tol=1.0 | 0.000s |
| 35 | 14:00:44.809 | move (set_origin + set_xyz) | PASS |  |  | zwide: drive moved by delta |  |  | expected=3.0 actual=3.0 tol=1.0 | 0.000s |
| 36 | 14:00:44.809 | move (set_origin + set_xyz) | PASS |  |  | zwide: z-galvo drive unchanged |  |  | expected=2.0 actual=2.0 tol=1.0 | 0.000s |
| 37 | 14:00:44.833 | move (set_origin + set_xyz) | PASS |  | YES | move: restore z-wide | z_wide_um=0.0 |  |  | 0.015s |
| 38 | 14:00:45.127 | move (set_origin + set_xyz) | PASS |  | YES | move: restore XY + focus (frame 0,0,0) | x_um=64220.0 y_um=41180.0 z_wide_um=0.0 z_galvo_um=-0.5 job='Overview' |  |  | 0.297s |
| 39 | 14:00:45.168 | state (capture / switch / restore) | PASS |  |  | get_state: capture |  |  |  | 0.047s |
| 40 | 14:00:46.117 | state (capture / switch / restore) | PASS |  | YES | set_state: switch job | to='HiRes' from='Overview' | to='HiRes' |  | 0.937s |
| 41 | 14:00:46.317 | state (capture / switch / restore) | PASS |  |  | get_state: after switch (settled) |  |  |  | 0.188s |
| 42 | 14:00:46.317 | state (capture / switch / restore) | PASS |  |  | state: switched |  |  | expected='HiRes' actual='HiRes' | 0.000s |
| 43 | 14:00:47.216 | state (capture / switch / restore) | PASS |  | YES | set_state: restore | restore_to='Overview' | restore_to='Overview' |  | 0.906s |
| 44 | 14:00:52.449 | state (capture / switch / restore) | PASS |  |  | get_state: after restore (settled) |  |  |  | 5.234s |
| 45 | 14:00:52.449 | state (capture / switch / restore) | PASS |  |  | state: restored |  |  | expected='Overview' actual='Overview' | 0.000s |
| 46 | 14:00:52.453 | setup | SKIP |  |  | phase: autofocus |  |  | use --allow-autofocus to enable | 0.000s |
| 47 | 14:00:52.453 | setup | SKIP |  |  | phase: acquire |  |  | use --allow-acquire to enable | 0.000s |

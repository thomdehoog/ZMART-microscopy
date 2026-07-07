# Hardware validation run report

Every change this run attempted on the instrument is listed below, including failed attempts and restore/cleanup steps (see the *Mutates scope* column). Changes carry their success+CONFIRMED / success+UNCONFIRMED / FAILED result and attempt counts in the *Result* column.

## Run metadata

- **Validator**: `validate_zmart_adapter`
- **Arguments**: `--yes --allow-move --allow-state --allow-missing-lasx --output=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\zmart_adapter_validate.jsonl --report-dir=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report`
- **Backend**: live LAS X (simulator or scope)
- **Date**: 2026-07-07
- **Started / finished**: 09:04:39 / 09:04:44 (4.9s)
- **Host**: ZMB-LASX-PC (Windows-10-10.0.26200-SP0)
- **Python**: 3.11.15
- **Driver commit**: unknown on unknown
- **Driver log**: `\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\driver_log_20260707-090439.log` (full log-line capture)

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
| read-only | 4 | 0.016s | 0.046s | 0.531s |
| move (set_origin + set_xyz) | 10 | 0.016s | 0.047s | 0.203s |
| state (capture / switch / restore) | 5 | 0.031s | 0.093s | 1.063s |

### Slowest actions

| Duration | Phase | Action | Status |
|---:|---|---|---|
| 1.063s | state (capture / switch / restore) | set_state: switch job | PASS |
| 1.016s | state (capture / switch / restore) | set_state: restore | PASS |
| 0.531s | read-only | get_context | PASS |
| 0.203s | move (set_origin + set_xyz) | set_xyz: XY move | PASS |
| 0.203s | move (set_origin + set_xyz) | set_xyz: z-wide move | PASS |
| 0.187s | move (set_origin + set_xyz) | move: restore XY + focus (frame 0,0,0) | PASS |
| 0.172s | move (set_origin + set_xyz) | set_xyz: z-galvo move | PASS |
| 0.093s | state (capture / switch / restore) | get_state: after switch (settled) | PASS |
| 0.047s | move (set_origin + set_xyz) | get_xyz after z-wide | PASS |
| 0.047s | read-only | get_xyz | PASS |

### Unconfirmed / failed changes

None -- every attempted change reported success and confirmed.

## Chronological detail (every attempted action)

| # | Time | Phase | Status | Result | Mutates scope | Action attempted | Args / target | Expected | Observed | Duration |
|---:|---|---|---|---|---|---|---|---|---|---:|
| 1 | 09:04:40.405 | read-only | PASS |  |  | get_instruments |  |  |  | 0.000s |
| 2 | 09:04:40.406 | read-only | PASS |  |  | registry: leica adapter registered |  |  | expected=True actual=True | 0.000s |
| 3 | 09:04:40.406 | read-only | PASS |  |  | get_actuators |  |  |  | 0.000s |
| 4 | 09:04:40.407 | read-only | PASS |  |  | actuators: expected menu |  |  | expected={'x': ['motoric'], 'y': ['motoric'], 'z': ['z-wide', 'z-galvo']} actual={'x': ['motoric'], 'y': ['motoric'], 'z': ['z-wide', 'z-galvo']} | 0.000s |
| 5 | 09:04:40.465 | read-only | PASS |  |  | get_xyz |  |  |  | 0.047s |
| 6 | 09:04:40.466 | read-only | PASS |  |  | get_xyz: x unit is um |  |  | expected='um' actual='um' | 0.000s |
| 7 | 09:04:40.467 | read-only | PASS |  |  | get_xyz: y unit is um |  |  | expected='um' actual='um' | 0.000s |
| 8 | 09:04:40.468 | read-only | PASS |  |  | get_xyz: z unit is um |  |  | expected='um' actual='um' | 0.000s |
| 9 | 09:04:40.469 | read-only | PASS |  |  | get_xyz: hardware block complete |  |  | expected=True actual=True | 0.000s |
| 10 | 09:04:40.470 | read-only | PASS |  |  | get_xyz: objective has a name |  |  | expected=True actual=True | 0.000s |
| 11 | 09:04:40.522 | read-only | PASS |  |  | get_state |  |  |  | 0.046s |
| 12 | 09:04:40.537 | read-only | PASS |  |  | get_acquisition_options |  |  |  | 0.016s |
| 13 | 09:04:40.538 | read-only | PASS |  |  | get_state: changeable job is in the job list |  |  | expected=True actual=True | 0.000s |
| 14 | 09:04:40.539 | read-only | PASS |  |  | get_state: observed carries an identity |  |  | expected=True actual=True | 0.000s |
| 15 | 09:04:40.540 | read-only | PASS |  |  | get_acquisition_options: active exporter is offered |  |  | expected=True actual=True | 0.000s |
| 16 | 09:04:41.066 | read-only | PASS |  |  | get_context |  |  |  | 0.531s |
| 17 | 09:04:41.067 | read-only | PASS |  |  | get_context: has session_hash6 |  |  | expected=True actual=True | 0.000s |
| 18 | 09:04:41.146 | move (set_origin + set_xyz) | PASS |  | YES | set_origin |  |  |  | 0.046s |
| 19 | 09:04:41.188 | move (set_origin + set_xyz) | PASS |  |  | get_xyz after set_origin |  |  |  | 0.047s |
| 20 | 09:04:41.189 | move (set_origin + set_xyz) | PASS |  |  | origin: frame x -> 0 |  |  | expected=0.0 actual=0.0 tol=20.0 | 0.000s |
| 21 | 09:04:41.190 | move (set_origin + set_xyz) | PASS |  |  | origin: frame y -> 0 |  |  | expected=0.0 actual=0.0 tol=20.0 | 0.000s |
| 22 | 09:04:41.191 | move (set_origin + set_xyz) | PASS |  |  | origin: frame z -> 0 |  |  | expected=0.0 actual=0.0 tol=1.0 | 0.000s |
| 23 | 09:04:41.397 | move (set_origin + set_xyz) | PASS |  | YES | set_xyz: XY move | to_frame=(25.0, 25.0, 0.0) z_actuator='z-galvo' |  |  | 0.203s |
| 24 | 09:04:41.435 | move (set_origin + set_xyz) | PASS |  |  | get_xyz after XY |  |  |  | 0.032s |
| 25 | 09:04:41.436 | move (set_origin + set_xyz) | PASS |  |  | xy: frame x |  |  | expected=25.0 actual=20.000000000007276 tol=20.0 | 0.000s |
| 26 | 09:04:41.437 | move (set_origin + set_xyz) | PASS |  |  | xy: frame y |  |  | expected=25.0 actual=20.0 tol=20.0 | 0.000s |
| 27 | 09:04:41.624 | move (set_origin + set_xyz) | PASS |  | YES | set_xyz: z-galvo move | to_frame=(25.0, 25.0, 2.0) z_actuator='z-galvo' |  |  | 0.172s |
| 28 | 09:04:41.664 | move (set_origin + set_xyz) | PASS |  |  | get_xyz after z-galvo |  |  |  | 0.031s |
| 29 | 09:04:41.665 | move (set_origin + set_xyz) | PASS |  |  | zgalvo: frame z |  |  | expected=2.0 actual=2.0 tol=1.0 | 0.000s |
| 30 | 09:04:41.665 | move (set_origin + set_xyz) | PASS |  |  | zgalvo: drive moved by delta (sign check) |  |  | expected=2.0 actual=2.0 tol=1.0 | 0.000s |
| 31 | 09:04:41.666 | move (set_origin + set_xyz) | PASS |  |  | zgalvo: z-wide drive unchanged |  |  | expected=0.0 actual=0.0 tol=1.0 | 0.000s |
| 32 | 09:04:41.871 | move (set_origin + set_xyz) | PASS |  | YES | set_xyz: z-wide move | to_frame=(25.0, 25.0, 5.0) z_actuator='z-wide' |  |  | 0.203s |
| 33 | 09:04:41.909 | move (set_origin + set_xyz) | PASS |  |  | get_xyz after z-wide |  |  |  | 0.047s |
| 34 | 09:04:41.910 | move (set_origin + set_xyz) | PASS |  |  | zwide: frame z is additive (z-wide + z-galvo) |  |  | expected=5.0 actual=5.0 tol=1.0 | 0.000s |
| 35 | 09:04:41.911 | move (set_origin + set_xyz) | PASS |  |  | zwide: drive moved by delta |  |  | expected=3.0 actual=3.0 tol=1.0 | 0.000s |
| 36 | 09:04:41.912 | move (set_origin + set_xyz) | PASS |  |  | zwide: z-galvo drive unchanged |  |  | expected=2.0 actual=2.0 tol=1.0 | 0.000s |
| 37 | 09:04:41.929 | move (set_origin + set_xyz) | PASS |  | YES | move: restore z-wide | z_wide_um=0.0 |  |  | 0.016s |
| 38 | 09:04:42.116 | move (set_origin + set_xyz) | PASS |  | YES | move: restore XY + focus (frame 0,0,0) | x_um=64220.0 y_um=41180.0 z_wide_um=0.0 z_galvo_um=-0.5 job='Overview' |  |  | 0.187s |
| 39 | 09:04:42.155 | state (capture / switch / restore) | PASS |  |  | get_state: capture |  |  |  | 0.031s |
| 40 | 09:04:43.218 | state (capture / switch / restore) | PASS |  | YES | set_state: switch job | to='HiRes' from='Overview' | to='HiRes' |  | 1.063s |
| 41 | 09:04:43.324 | state (capture / switch / restore) | PASS |  |  | get_state: after switch (settled) |  |  |  | 0.093s |
| 42 | 09:04:43.325 | state (capture / switch / restore) | PASS |  |  | state: switched |  |  | expected='HiRes' actual='HiRes' | 0.000s |
| 43 | 09:04:44.335 | state (capture / switch / restore) | PASS |  | YES | set_state: restore | restore_to='Overview' | restore_to='Overview' |  | 1.016s |
| 44 | 09:04:44.374 | state (capture / switch / restore) | PASS |  |  | get_state: after restore (settled) |  |  |  | 0.031s |
| 45 | 09:04:44.375 | state (capture / switch / restore) | PASS |  |  | state: restored |  |  | expected='Overview' actual='Overview' | 0.000s |
| 46 | 09:04:44.376 | setup | SKIP |  |  | phase: autofocus |  |  | use --allow-autofocus to enable | 0.000s |
| 47 | 09:04:44.377 | setup | SKIP |  |  | phase: acquire |  |  | use --allow-acquire to enable | 0.000s |

# Hardware validation run report

Every change this run attempted on the instrument is listed below, including failed attempts and restore/cleanup steps (see the *Mutates scope* column). Changes carry their success+CONFIRMED / success+UNCONFIRMED / FAILED result and attempt counts in the *Result* column.

## Run metadata

- **Validator**: `validate_zmart_adapter`
- **Arguments**: `--yes --allow-move --allow-state --allow-missing-lasx --output=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\zmart_adapter_validate.jsonl --report-dir=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report`
- **Backend**: live LAS X (simulator or scope)
- **Date**: 2026-07-06
- **Started / finished**: 13:26:15 / 13:26:21 (5.1s)
- **Host**: ZMB-LASX-PC (Windows-10-10.0.26200-SP0)
- **Python**: 3.11.15
- **Driver commit**: unknown on unknown
- **Driver log**: `\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\driver_log_20260706-132615.log` (full log-line capture)

## Summary

| Phase | Actions attempted | Passed | Warned | Failed | Skipped | Confirmed | Unconfirmed |
|---|---:|---:|---:|---:|---:|---:|---:|
| read-only | 19 | 17 | 0 | 2 | 0 | 0 | 0 |
| move (set_origin + set_xyz) | 21 | 21 | 0 | 0 | 0 | 0 | 0 |
| state (capture / switch / restore) | 7 | 7 | 0 | 0 | 0 | 0 | 0 |
| setup | 2 | 0 | 0 | 0 | 2 | 0 | 0 |
| **total** | **49** | **45** | **0** | **2** | **2** | **0** | **0** |

## Timing overview

### Per phase

| Phase | Timed actions | Min | Median | Max |
|---|---:|---:|---:|---:|
| read-only | 4 | 0.016s | 0.047s | 0.547s |
| move (set_origin + set_xyz) | 10 | 0.031s | 0.055s | 0.203s |
| state (capture / switch / restore) | 5 | 0.031s | 0.140s | 1.078s |

### Slowest actions

| Duration | Phase | Action | Status |
|---:|---|---|---|
| 1.078s | state (capture / switch / restore) | set_state: restore | PASS |
| 1.063s | state (capture / switch / restore) | set_state: switch job | PASS |
| 0.547s | read-only | get_context | PASS |
| 0.203s | move (set_origin + set_xyz) | set_xyz: XY move | PASS |
| 0.188s | move (set_origin + set_xyz) | set_xyz: z-galvo move | PASS |
| 0.187s | move (set_origin + set_xyz) | set_xyz: z-wide move | PASS |
| 0.187s | move (set_origin + set_xyz) | move: restore XY + focus (frame 0,0,0) | PASS |
| 0.140s | state (capture / switch / restore) | get_state: after switch (settled) | PASS |
| 0.094s | state (capture / switch / restore) | get_state: after restore (settled) | PASS |
| 0.062s | move (set_origin + set_xyz) | get_xyz after XY | PASS |

### Unconfirmed / failed changes

None -- every attempted change reported success and confirmed.

## Chronological detail (every attempted action)

| # | Time | Phase | Status | Result | Mutates scope | Action attempted | Args / target | Expected | Observed | Duration |
|---:|---|---|---|---|---|---|---|---|---|---:|
| 1 | 13:26:16.962 | read-only | PASS |  |  | get_instruments |  |  |  | 0.000s |
| 2 | 13:26:16.962 | read-only | PASS |  |  | registry: leica adapter registered |  |  | expected=True actual=True | 0.000s |
| 3 | 13:26:16.962 | read-only | PASS |  |  | get_actuators |  |  |  | 0.000s |
| 4 | 13:26:16.962 | read-only | PASS |  |  | actuators: expected menu |  |  | expected={'x': ['motoric'], 'y': ['motoric'], 'z': ['z-wide', 'z-galvo']} actual={'x': ['motoric'], 'y': ['motoric'], 'z': ['z-wide', 'z-galvo']} | 0.000s |
| 5 | 13:26:17.012 | read-only | PASS |  |  | get_xyz |  |  |  | 0.047s |
| 6 | 13:26:17.012 | read-only | PASS |  |  | get_xyz: x unit is um |  |  | expected='um' actual='um' | 0.000s |
| 7 | 13:26:17.012 | read-only | PASS |  |  | get_xyz: y unit is um |  |  | expected='um' actual='um' | 0.000s |
| 8 | 13:26:17.012 | read-only | PASS |  |  | get_xyz: z unit is um |  |  | expected='um' actual='um' | 0.000s |
| 9 | 13:26:17.012 | read-only | PASS |  |  | get_xyz: hardware block complete |  |  | expected=True actual=True | 0.000s |
| 10 | 13:26:17.012 | read-only | FAIL |  |  | get_xyz: frame x == hardware x_um |  |  | expected=64220.0 actual=0.0 tol=0.05 | 0.000s |
| 11 | 13:26:17.012 | read-only | FAIL |  |  | get_xyz: frame z == z_wide + z_galvo |  |  | expected=-0.5 actual=0.0 tol=0.05 | 0.000s |
| 12 | 13:26:17.012 | read-only | PASS |  |  | get_xyz: objective has a name |  |  | expected=True actual=True | 0.000s |
| 13 | 13:26:17.062 | read-only | PASS |  |  | get_state |  |  |  | 0.047s |
| 14 | 13:26:17.076 | read-only | PASS |  |  | get_acquisition_options |  |  |  | 0.016s |
| 15 | 13:26:17.076 | read-only | PASS |  |  | get_state: changeable job is in the job list |  |  | expected=True actual=True | 0.000s |
| 16 | 13:26:17.076 | read-only | PASS |  |  | get_state: observed carries an identity |  |  | expected=True actual=True | 0.000s |
| 17 | 13:26:17.076 | read-only | PASS |  |  | get_acquisition_options: active exporter is offered |  |  | expected=True actual=True | 0.000s |
| 18 | 13:26:17.618 | read-only | PASS |  |  | get_context |  |  |  | 0.547s |
| 19 | 13:26:17.618 | read-only | PASS |  |  | get_context: has session_hash6 |  |  | expected=True actual=True | 0.000s |
| 20 | 13:26:17.704 | move (set_origin + set_xyz) | PASS |  | YES | set_origin |  |  |  | 0.047s |
| 21 | 13:26:17.746 | move (set_origin + set_xyz) | PASS |  |  | get_xyz after set_origin |  |  |  | 0.047s |
| 22 | 13:26:17.746 | move (set_origin + set_xyz) | PASS |  |  | origin: frame x -> 0 |  |  | expected=0.0 actual=0.0 tol=20.0 | 0.000s |
| 23 | 13:26:17.746 | move (set_origin + set_xyz) | PASS |  |  | origin: frame y -> 0 |  |  | expected=0.0 actual=0.0 tol=20.0 | 0.000s |
| 24 | 13:26:17.746 | move (set_origin + set_xyz) | PASS |  |  | origin: frame z -> 0 |  |  | expected=0.0 actual=0.0 tol=1.0 | 0.000s |
| 25 | 13:26:17.957 | move (set_origin + set_xyz) | PASS |  | YES | set_xyz: XY move | to_frame=(25.0, 25.0, 0.0) z_actuator='z-galvo' |  |  | 0.203s |
| 26 | 13:26:18.008 | move (set_origin + set_xyz) | PASS |  |  | get_xyz after XY |  |  |  | 0.062s |
| 27 | 13:26:18.008 | move (set_origin + set_xyz) | PASS |  |  | xy: frame x |  |  | expected=25.0 actual=20.000000000007276 tol=20.0 | 0.000s |
| 28 | 13:26:18.008 | move (set_origin + set_xyz) | PASS |  |  | xy: frame y |  |  | expected=25.0 actual=20.0 tol=20.0 | 0.000s |
| 29 | 13:26:18.202 | move (set_origin + set_xyz) | PASS |  | YES | set_xyz: z-galvo move | to_frame=(25.0, 25.0, 2.0) z_actuator='z-galvo' |  |  | 0.188s |
| 30 | 13:26:18.242 | move (set_origin + set_xyz) | PASS |  |  | get_xyz after z-galvo |  |  |  | 0.047s |
| 31 | 13:26:18.242 | move (set_origin + set_xyz) | PASS |  |  | zgalvo: frame z |  |  | expected=2.0 actual=2.0 tol=1.0 | 0.000s |
| 32 | 13:26:18.242 | move (set_origin + set_xyz) | PASS |  |  | zgalvo: drive moved by delta (sign check) |  |  | expected=2.0 actual=2.0 tol=1.0 | 0.000s |
| 33 | 13:26:18.242 | move (set_origin + set_xyz) | PASS |  |  | zgalvo: z-wide drive unchanged |  |  | expected=0.0 actual=0.0 tol=1.0 | 0.000s |
| 34 | 13:26:18.431 | move (set_origin + set_xyz) | PASS |  | YES | set_xyz: z-wide move | to_frame=(25.0, 25.0, 5.0) z_actuator='z-wide' |  |  | 0.187s |
| 35 | 13:26:18.471 | move (set_origin + set_xyz) | PASS |  |  | get_xyz after z-wide |  |  |  | 0.031s |
| 36 | 13:26:18.471 | move (set_origin + set_xyz) | PASS |  |  | zwide: frame z is additive (z-wide + z-galvo) |  |  | expected=5.0 actual=5.0 tol=1.0 | 0.000s |
| 37 | 13:26:18.471 | move (set_origin + set_xyz) | PASS |  |  | zwide: drive moved by delta |  |  | expected=3.0 actual=3.0 tol=1.0 | 0.000s |
| 38 | 13:26:18.471 | move (set_origin + set_xyz) | PASS |  |  | zwide: z-galvo drive unchanged |  |  | expected=2.0 actual=2.0 tol=1.0 | 0.000s |
| 39 | 13:26:18.491 | move (set_origin + set_xyz) | PASS |  | YES | move: restore z-wide | z_wide_um=0.0 |  |  | 0.032s |
| 40 | 13:26:18.681 | move (set_origin + set_xyz) | PASS |  | YES | move: restore XY + focus (frame 0,0,0) | x_um=64220.0 y_um=41180.0 z_wide_um=0.0 z_galvo_um=-0.5 job='Overview' |  |  | 0.187s |
| 41 | 13:26:18.720 | state (capture / switch / restore) | PASS |  |  | get_state: capture |  |  |  | 0.031s |
| 42 | 13:26:19.797 | state (capture / switch / restore) | PASS |  | YES | set_state: switch job | to='HiRes' from='Overview' | to='HiRes' |  | 1.063s |
| 43 | 13:26:19.929 | state (capture / switch / restore) | PASS |  |  | get_state: after switch (settled) |  |  |  | 0.140s |
| 44 | 13:26:19.929 | state (capture / switch / restore) | PASS |  |  | state: switched |  |  | expected='HiRes' actual='HiRes' | 0.000s |
| 45 | 13:26:21.015 | state (capture / switch / restore) | PASS |  | YES | set_state: restore | restore_to='Overview' | restore_to='Overview' |  | 1.078s |
| 46 | 13:26:21.108 | state (capture / switch / restore) | PASS |  |  | get_state: after restore (settled) |  |  |  | 0.094s |
| 47 | 13:26:21.108 | state (capture / switch / restore) | PASS |  |  | state: restored |  |  | expected='Overview' actual='Overview' | 0.000s |
| 48 | 13:26:21.108 | setup | SKIP |  |  | phase: autofocus |  |  | use --allow-autofocus to enable | 0.000s |
| 49 | 13:26:21.108 | setup | SKIP |  |  | phase: acquire |  |  | use --allow-acquire to enable | 0.000s |

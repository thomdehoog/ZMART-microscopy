# Hardware validation run report

Every change this run attempted on the instrument is listed below, including failed attempts and restore/cleanup steps (see the *Mutates scope* column). Changes carry their success+CONFIRMED / success+UNCONFIRMED / FAILED result and attempt counts in the *Result* column.

## Run metadata

- **Validator**: `validate_zmart_adapter`
- **Arguments**: `--yes --allow-move --allow-state --allow-missing-lasx --output=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\zmart_adapter_validate.jsonl --report-dir=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report`
- **Backend**: live LAS X (simulator or scope)
- **Date**: 2026-07-06
- **Started / finished**: 11:59:29 / 11:59:33 (4.7s)
- **Host**: ZMB-LASX-PC (Windows-10-10.0.26200-SP0)
- **Python**: 3.11.15
- **Driver commit**: unknown on unknown
- **Driver log**: `\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\driver_log_20260706-115929.log` (full log-line capture)

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
| read-only | 3 | 0.031s | 0.062s | 0.515s |
| move (set_origin + set_xyz) | 10 | 0.016s | 0.039s | 0.203s |
| state (capture / switch / restore) | 5 | 0.031s | 0.110s | 0.922s |

### Slowest actions

| Duration | Phase | Action | Status |
|---:|---|---|---|
| 0.922s | state (capture / switch / restore) | set_state: switch job | PASS |
| 0.906s | state (capture / switch / restore) | set_state: restore | PASS |
| 0.515s | read-only | get_context | PASS |
| 0.203s | move (set_origin + set_xyz) | set_xyz: XY move | PASS |
| 0.188s | move (set_origin + set_xyz) | set_xyz: z-galvo move | PASS |
| 0.187s | move (set_origin + set_xyz) | set_xyz: z-wide move | PASS |
| 0.187s | move (set_origin + set_xyz) | move: restore XY + focus (frame 0,0,0) | PASS |
| 0.110s | state (capture / switch / restore) | get_state: after restore (settled) | PASS |
| 0.078s | state (capture / switch / restore) | get_state: after switch (settled) | PASS |
| 0.062s | read-only | get_xyz | PASS |

### Unconfirmed / failed changes

None -- every attempted change reported success and confirmed.

## Chronological detail (every attempted action)

| # | Time | Phase | Status | Result | Mutates scope | Action attempted | Args / target | Expected | Observed | Duration |
|---:|---|---|---|---|---|---|---|---|---|---:|
| 1 | 11:59:30.196 | read-only | PASS |  |  | get_instruments |  |  |  | 0.000s |
| 2 | 11:59:30.197 | read-only | PASS |  |  | registry: leica adapter registered |  |  | expected=True actual=True | 0.000s |
| 3 | 11:59:30.198 | read-only | PASS |  |  | get_actuators |  |  |  | 0.000s |
| 4 | 11:59:30.199 | read-only | PASS |  |  | actuators: expected menu |  |  | expected={'x': ['motoric'], 'y': ['motoric'], 'z': ['z-wide', 'z-galvo']} actual={'x': ['motoric'], 'y': ['motoric'], 'z': ['z-wide', 'z-galvo']} | 0.000s |
| 5 | 11:59:30.256 | read-only | PASS |  |  | get_xyz |  |  |  | 0.062s |
| 6 | 11:59:30.257 | read-only | PASS |  |  | get_xyz: x unit is um |  |  | expected='um' actual='um' | 0.000s |
| 7 | 11:59:30.257 | read-only | PASS |  |  | get_xyz: y unit is um |  |  | expected='um' actual='um' | 0.000s |
| 8 | 11:59:30.258 | read-only | PASS |  |  | get_xyz: z unit is um |  |  | expected='um' actual='um' | 0.000s |
| 9 | 11:59:30.259 | read-only | PASS |  |  | get_xyz: hardware block complete |  |  | expected=True actual=True | 0.000s |
| 10 | 11:59:30.260 | read-only | FAIL |  |  | get_xyz: frame x == hardware x_um |  |  | expected=64220.0 actual=0.0 tol=0.05 | 0.000s |
| 11 | 11:59:30.261 | read-only | FAIL |  |  | get_xyz: frame z == z_wide + z_galvo |  |  | expected=-0.5 actual=7199.5 tol=0.05 | 0.000s |
| 12 | 11:59:30.262 | read-only | PASS |  |  | get_xyz: objective has a name |  |  | expected=True actual=True | 0.000s |
| 13 | 11:59:30.300 | read-only | PASS |  |  | get_state |  |  |  | 0.031s |
| 14 | 11:59:30.313 | read-only | PASS |  |  | get_acquisition_options |  |  |  | 0.000s |
| 15 | 11:59:30.314 | read-only | PASS |  |  | get_state: changeable job is in the job list |  |  | expected=True actual=True | 0.000s |
| 16 | 11:59:30.315 | read-only | PASS |  |  | get_state: observed carries an identity |  |  | expected=True actual=True | 0.000s |
| 17 | 11:59:30.316 | read-only | PASS |  |  | get_acquisition_options: active exporter is offered |  |  | expected=True actual=True | 0.000s |
| 18 | 11:59:30.846 | read-only | PASS |  |  | get_context |  |  |  | 0.515s |
| 19 | 11:59:30.847 | read-only | PASS |  |  | get_context: has session_hash6 |  |  | expected=True actual=True | 0.000s |
| 20 | 11:59:30.929 | move (set_origin + set_xyz) | PASS |  | YES | set_origin |  |  |  | 0.047s |
| 21 | 11:59:30.969 | move (set_origin + set_xyz) | PASS |  |  | get_xyz after set_origin |  |  |  | 0.031s |
| 22 | 11:59:30.970 | move (set_origin + set_xyz) | PASS |  |  | origin: frame x -> 0 |  |  | expected=0.0 actual=0.0 tol=20.0 | 0.000s |
| 23 | 11:59:30.971 | move (set_origin + set_xyz) | PASS |  |  | origin: frame y -> 0 |  |  | expected=0.0 actual=0.0 tol=20.0 | 0.000s |
| 24 | 11:59:30.972 | move (set_origin + set_xyz) | PASS |  |  | origin: frame z -> 0 |  |  | expected=0.0 actual=0.0 tol=1.0 | 0.000s |
| 25 | 11:59:31.176 | move (set_origin + set_xyz) | PASS |  | YES | set_xyz: XY move | to_frame=(25.0, 25.0, 0.0) z_actuator='z-galvo' |  |  | 0.203s |
| 26 | 11:59:31.219 | move (set_origin + set_xyz) | PASS |  |  | get_xyz after XY |  |  |  | 0.031s |
| 27 | 11:59:31.220 | move (set_origin + set_xyz) | PASS |  |  | xy: frame x |  |  | expected=25.0 actual=20.000000000007276 tol=20.0 | 0.000s |
| 28 | 11:59:31.221 | move (set_origin + set_xyz) | PASS |  |  | xy: frame y |  |  | expected=25.0 actual=20.0 tol=20.0 | 0.000s |
| 29 | 11:59:31.402 | move (set_origin + set_xyz) | PASS |  | YES | set_xyz: z-galvo move | to_frame=(25.0, 25.0, 2.0) z_actuator='z-galvo' |  |  | 0.188s |
| 30 | 11:59:31.440 | move (set_origin + set_xyz) | PASS |  |  | get_xyz after z-galvo |  |  |  | 0.031s |
| 31 | 11:59:31.441 | move (set_origin + set_xyz) | PASS |  |  | zgalvo: frame z |  |  | expected=2.0 actual=2.0 tol=1.0 | 0.000s |
| 32 | 11:59:31.442 | move (set_origin + set_xyz) | PASS |  |  | zgalvo: drive moved by delta (sign check) |  |  | expected=2.0 actual=2.0 tol=1.0 | 0.000s |
| 33 | 11:59:31.443 | move (set_origin + set_xyz) | PASS |  |  | zgalvo: z-wide drive unchanged |  |  | expected=0.0 actual=0.0 tol=1.0 | 0.000s |
| 34 | 11:59:31.643 | move (set_origin + set_xyz) | PASS |  | YES | set_xyz: z-wide move | to_frame=(25.0, 25.0, 5.0) z_actuator='z-wide' |  |  | 0.187s |
| 35 | 11:59:31.680 | move (set_origin + set_xyz) | PASS |  |  | get_xyz after z-wide |  |  |  | 0.031s |
| 36 | 11:59:31.681 | move (set_origin + set_xyz) | PASS |  |  | zwide: frame z is additive (z-wide + z-galvo) |  |  | expected=5.0 actual=5.0 tol=1.0 | 0.000s |
| 37 | 11:59:31.682 | move (set_origin + set_xyz) | PASS |  |  | zwide: drive moved by delta |  |  | expected=3.0 actual=3.0 tol=1.0 | 0.000s |
| 38 | 11:59:31.683 | move (set_origin + set_xyz) | PASS |  |  | zwide: z-galvo drive unchanged |  |  | expected=2.0 actual=2.0 tol=1.0 | 0.000s |
| 39 | 11:59:31.698 | move (set_origin + set_xyz) | PASS |  | YES | move: restore z-wide | z_wide_um=0.0 |  |  | 0.016s |
| 40 | 11:59:31.884 | move (set_origin + set_xyz) | PASS |  | YES | move: restore XY + focus (frame 0,0,0) | x_um=64220.0 y_um=41180.0 z_wide_um=0.0 z_galvo_um=-0.5 job='Overview' |  |  | 0.187s |
| 41 | 11:59:31.921 | state (capture / switch / restore) | PASS |  |  | get_state: capture |  |  |  | 0.031s |
| 42 | 11:59:32.848 | state (capture / switch / restore) | PASS |  | YES | set_state: switch job | to='HiRes' from='Overview' | to='HiRes' |  | 0.922s |
| 43 | 11:59:32.934 | state (capture / switch / restore) | PASS |  |  | get_state: after switch (settled) |  |  |  | 0.078s |
| 44 | 11:59:32.935 | state (capture / switch / restore) | PASS |  |  | state: switched |  |  | expected='HiRes' actual='HiRes' | 0.000s |
| 45 | 11:59:33.839 | state (capture / switch / restore) | PASS |  | YES | set_state: restore | restore_to='Overview' | restore_to='Overview' |  | 0.906s |
| 46 | 11:59:33.945 | state (capture / switch / restore) | PASS |  |  | get_state: after restore (settled) |  |  |  | 0.110s |
| 47 | 11:59:33.946 | state (capture / switch / restore) | PASS |  |  | state: restored |  |  | expected='Overview' actual='Overview' | 0.000s |
| 48 | 11:59:33.947 | setup | SKIP |  |  | phase: autofocus |  |  | use --allow-autofocus to enable | 0.000s |
| 49 | 11:59:33.948 | setup | SKIP |  |  | phase: acquire |  |  | use --allow-acquire to enable | 0.000s |

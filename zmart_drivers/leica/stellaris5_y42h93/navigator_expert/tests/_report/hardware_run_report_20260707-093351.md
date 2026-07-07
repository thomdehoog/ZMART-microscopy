# Hardware validation run report

Every change this run attempted on the instrument is listed below, including failed attempts and restore/cleanup steps (see the *Mutates scope* column). Changes carry their success+CONFIRMED / success+UNCONFIRMED / FAILED result and attempt counts in the *Result* column.

## Run metadata

- **Validator**: `validate_zmart_adapter`
- **Arguments**: `--yes --allow-move --allow-state --allow-missing-lasx --output=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\zmart_adapter_validate.jsonl --report-dir=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report`
- **Backend**: live LAS X (simulator or scope)
- **Date**: 2026-07-07
- **Started / finished**: 09:33:51 / 09:33:56 (4.7s)
- **Host**: ZMB-Y42H93-STI8 (Windows-10-10.0.26100-SP0)
- **Python**: 3.11.15
- **Driver commit**: aecf1a2 on claude/smart-drivers-code-review-ky4phc (working tree has local changes)
- **Driver log**: `\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\driver_log_20260707-093351.log` (full log-line capture)

## Summary

| Phase | Actions attempted | Passed | Warned | Failed | Skipped | Confirmed | Unconfirmed |
|---|---:|---:|---:|---:|---:|---:|---:|
| read-only | 17 | 17 | 0 | 0 | 0 | 0 | 0 |
| move (set_origin + set_xyz) | 21 | 21 | 0 | 0 | 0 | 0 | 0 |
| state (capture / switch / restore) | 7 | 6 | 0 | 1 | 0 | 0 | 0 |
| setup | 2 | 0 | 0 | 0 | 2 | 0 | 0 |
| **total** | **47** | **44** | **0** | **1** | **2** | **0** | **0** |

## Timing overview

### Per phase

| Phase | Timed actions | Min | Median | Max |
|---|---:|---:|---:|---:|
| read-only | 4 | 0.016s | 0.054s | 0.734s |
| move (set_origin + set_xyz) | 10 | 0.031s | 0.078s | 0.500s |
| state (capture / switch / restore) | 5 | 0.031s | 0.031s | 0.609s |

### Slowest actions

| Duration | Phase | Action | Status |
|---:|---|---|---|
| 0.734s | read-only | get_context | PASS |
| 0.609s | state (capture / switch / restore) | set_state: switch job | PASS |
| 0.500s | move (set_origin + set_xyz) | set_xyz: z-wide move | PASS |
| 0.437s | move (set_origin + set_xyz) | set_xyz: XY move | PASS |
| 0.390s | move (set_origin + set_xyz) | move: restore XY + focus (frame 0,0,0) | PASS |
| 0.360s | move (set_origin + set_xyz) | set_xyz: z-galvo move | PASS |
| 0.110s | move (set_origin + set_xyz) | move: restore z-wide | PASS |
| 0.062s | read-only | get_xyz | PASS |
| 0.047s | read-only | get_state | PASS |
| 0.047s | move (set_origin + set_xyz) | get_xyz after set_origin | PASS |

### Unconfirmed / failed changes

None -- every attempted change reported success and confirmed.

## Chronological detail (every attempted action)

| # | Time | Phase | Status | Result | Mutates scope | Action attempted | Args / target | Expected | Observed | Duration |
|---:|---|---|---|---|---|---|---|---|---|---:|
| 1 | 09:33:52.374 | read-only | PASS |  |  | get_instruments |  |  |  | 0.000s |
| 2 | 09:33:52.376 | read-only | PASS |  |  | registry: leica adapter registered |  |  | expected=True actual=True | 0.000s |
| 3 | 09:33:52.377 | read-only | PASS |  |  | get_actuators |  |  |  | 0.000s |
| 4 | 09:33:52.378 | read-only | PASS |  |  | actuators: expected menu |  |  | expected={'x': ['motoric'], 'y': ['motoric'], 'z': ['z-wide', 'z-galvo']} actual={'x': ['motoric'], 'y': ['motoric'], 'z': ['z-wide', 'z-galvo']} | 0.000s |
| 5 | 09:33:52.443 | read-only | PASS |  |  | get_xyz |  |  |  | 0.062s |
| 6 | 09:33:52.445 | read-only | PASS |  |  | get_xyz: x unit is um |  |  | expected='um' actual='um' | 0.000s |
| 7 | 09:33:52.446 | read-only | PASS |  |  | get_xyz: y unit is um |  |  | expected='um' actual='um' | 0.000s |
| 8 | 09:33:52.447 | read-only | PASS |  |  | get_xyz: z unit is um |  |  | expected='um' actual='um' | 0.000s |
| 9 | 09:33:52.448 | read-only | PASS |  |  | get_xyz: hardware block complete |  |  | expected=True actual=True | 0.000s |
| 10 | 09:33:52.449 | read-only | PASS |  |  | get_xyz: objective has a name |  |  | expected=True actual=True | 0.000s |
| 11 | 09:33:52.488 | read-only | PASS |  |  | get_state |  |  |  | 0.047s |
| 12 | 09:33:52.503 | read-only | PASS |  |  | get_acquisition_options |  |  |  | 0.016s |
| 13 | 09:33:52.504 | read-only | PASS |  |  | get_state: changeable job is in the job list |  |  | expected=True actual=True | 0.000s |
| 14 | 09:33:52.506 | read-only | PASS |  |  | get_state: observed carries an identity |  |  | expected=True actual=True | 0.000s |
| 15 | 09:33:52.507 | read-only | PASS |  |  | get_acquisition_options: active exporter is offered |  |  | expected=True actual=True | 0.000s |
| 16 | 09:33:53.242 | read-only | PASS |  |  | get_context |  |  |  | 0.734s |
| 17 | 09:33:53.243 | read-only | PASS |  |  | get_context: has session_hash6 |  |  | expected=True actual=True | 0.000s |
| 18 | 09:33:53.325 | move (set_origin + set_xyz) | PASS |  | YES | set_origin |  |  |  | 0.031s |
| 19 | 09:33:53.367 | move (set_origin + set_xyz) | PASS |  |  | get_xyz after set_origin |  |  |  | 0.047s |
| 20 | 09:33:53.369 | move (set_origin + set_xyz) | PASS |  |  | origin: frame x -> 0 |  |  | expected=0.0 actual=0.0 tol=20.0 | 0.000s |
| 21 | 09:33:53.370 | move (set_origin + set_xyz) | PASS |  |  | origin: frame y -> 0 |  |  | expected=0.0 actual=0.0 tol=20.0 | 0.000s |
| 22 | 09:33:53.371 | move (set_origin + set_xyz) | PASS |  |  | origin: frame z -> 0 |  |  | expected=0.0 actual=0.0 tol=1.0 | 0.000s |
| 23 | 09:33:53.803 | move (set_origin + set_xyz) | PASS |  | YES | set_xyz: XY move | to_frame=(25.0, 25.0, 0.0) z_actuator='z-galvo' |  |  | 0.437s |
| 24 | 09:33:53.844 | move (set_origin + set_xyz) | PASS |  |  | get_xyz after XY |  |  |  | 0.047s |
| 25 | 09:33:53.845 | move (set_origin + set_xyz) | PASS |  |  | xy: frame x |  |  | expected=25.0 actual=25.0 tol=20.0 | 0.000s |
| 26 | 09:33:53.846 | move (set_origin + set_xyz) | PASS |  |  | xy: frame y |  |  | expected=25.0 actual=25.000000000007276 tol=20.0 | 0.000s |
| 27 | 09:33:54.214 | move (set_origin + set_xyz) | PASS |  | YES | set_xyz: z-galvo move | to_frame=(25.0, 25.0, 2.0) z_actuator='z-galvo' |  |  | 0.360s |
| 28 | 09:33:54.255 | move (set_origin + set_xyz) | PASS |  |  | get_xyz after z-galvo |  |  |  | 0.047s |
| 29 | 09:33:54.256 | move (set_origin + set_xyz) | PASS |  |  | zgalvo: frame z |  |  | expected=2.0 actual=2.0 tol=1.0 | 0.000s |
| 30 | 09:33:54.258 | move (set_origin + set_xyz) | PASS |  |  | zgalvo: drive moved by delta (sign check) |  |  | expected=2.0 actual=2.0 tol=1.0 | 0.000s |
| 31 | 09:33:54.259 | move (set_origin + set_xyz) | PASS |  |  | zgalvo: z-wide drive unchanged |  |  | expected=0.0 actual=0.0 tol=1.0 | 0.000s |
| 32 | 09:33:54.754 | move (set_origin + set_xyz) | PASS |  | YES | set_xyz: z-wide move | to_frame=(25.0, 25.0, 5.0) z_actuator='z-wide' |  |  | 0.500s |
| 33 | 09:33:54.793 | move (set_origin + set_xyz) | PASS |  |  | get_xyz after z-wide |  |  |  | 0.031s |
| 34 | 09:33:54.795 | move (set_origin + set_xyz) | PASS |  |  | zwide: frame z is additive (z-wide + z-galvo) |  |  | expected=5.0 actual=5.0 tol=1.0 | 0.000s |
| 35 | 09:33:54.796 | move (set_origin + set_xyz) | PASS |  |  | zwide: drive moved by delta |  |  | expected=3.0 actual=3.0 tol=1.0 | 0.000s |
| 36 | 09:33:54.797 | move (set_origin + set_xyz) | PASS |  |  | zwide: z-galvo drive unchanged |  |  | expected=2.0 actual=2.0 tol=1.0 | 0.000s |
| 37 | 09:33:54.911 | move (set_origin + set_xyz) | PASS |  | YES | move: restore z-wide | z_wide_um=0.0 |  |  | 0.110s |
| 38 | 09:33:55.310 | move (set_origin + set_xyz) | PASS |  | YES | move: restore XY + focus (frame 0,0,0) | x_um=63500.0 y_um=41499.99999999999 z_wide_um=0.0 z_galvo_um=-0.0 job='HiRes' |  |  | 0.390s |
| 39 | 09:33:55.350 | state (capture / switch / restore) | PASS |  |  | get_state: capture |  |  |  | 0.031s |
| 40 | 09:33:55.972 | state (capture / switch / restore) | PASS |  | YES | set_state: switch job | to='Overview' from='HiRes' | to='Overview' |  | 0.609s |
| 41 | 09:33:56.027 | state (capture / switch / restore) | PASS |  |  | get_state: after switch (settled) |  |  |  | 0.047s |
| 42 | 09:33:56.029 | state (capture / switch / restore) | FAIL |  |  | state: switched |  |  | expected='Overview' actual='HiRes' | 0.000s |
| 43 | 09:33:56.064 | state (capture / switch / restore) | PASS |  | YES | set_state: restore | restore_to='HiRes' | restore_to='HiRes' |  | 0.031s |
| 44 | 09:33:56.104 | state (capture / switch / restore) | PASS |  |  | get_state: after restore (settled) |  |  |  | 0.031s |
| 45 | 09:33:56.106 | state (capture / switch / restore) | PASS |  |  | state: restored |  |  | expected='HiRes' actual='HiRes' | 0.000s |
| 46 | 09:33:56.107 | setup | SKIP |  |  | phase: autofocus |  |  | use --allow-autofocus to enable | 0.000s |
| 47 | 09:33:56.108 | setup | SKIP |  |  | phase: acquire |  |  | use --allow-acquire to enable | 0.000s |

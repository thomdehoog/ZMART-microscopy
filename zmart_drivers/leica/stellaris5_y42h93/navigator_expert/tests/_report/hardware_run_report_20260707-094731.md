# Hardware validation run report

Every change this run attempted on the instrument is listed below, including failed attempts and restore/cleanup steps (see the *Mutates scope* column). Changes carry their success+CONFIRMED / success+UNCONFIRMED / FAILED result and attempt counts in the *Result* column.

## Run metadata

- **Validator**: `validate_zmart_adapter`
- **Arguments**: `--yes --allow-move --allow-state --allow-acquire --allow-missing-lasx --exporter lasx_native_autosave --output=tests\_report\zmart_adapter_acquire_native.jsonl --report-dir=tests\_report`
- **Backend**: live LAS X (simulator or scope)
- **Date**: 2026-07-07
- **Started / finished**: 09:47:31 / 09:47:45 (13.2s)
- **Host**: ZMB-Y42H93-STI8 (Windows-10-10.0.26100-SP0)
- **Python**: 3.11.15
- **Driver commit**: aecf1a2 on claude/smart-drivers-code-review-ky4phc (working tree has local changes)
- **Driver log**: `tests\_report\driver_log_20260707-094731.log` (full log-line capture)

## Summary

| Phase | Actions attempted | Passed | Warned | Failed | Skipped | Confirmed | Unconfirmed |
|---|---:|---:|---:|---:|---:|---:|---:|
| read-only | 17 | 17 | 0 | 0 | 0 | 0 | 0 |
| move (set_origin + set_xyz) | 21 | 21 | 0 | 0 | 0 | 0 | 0 |
| state (capture / switch / restore) | 7 | 6 | 0 | 1 | 0 | 0 | 0 |
| setup | 1 | 0 | 0 | 0 | 1 | 0 | 0 |
| acquire (capture + save) | 5 | 5 | 0 | 0 | 0 | 0 | 0 |
| **total** | **51** | **49** | **0** | **1** | **1** | **0** | **0** |

## Timing overview

### Per phase

| Phase | Timed actions | Min | Median | Max |
|---|---:|---:|---:|---:|
| read-only | 4 | 0.016s | 0.039s | 0.640s |
| move (set_origin + set_xyz) | 10 | 0.031s | 0.086s | 0.469s |
| state (capture / switch / restore) | 5 | 0.031s | 0.032s | 1.047s |
| acquire (capture + save) | 1 | 7.797s | 7.797s | 7.797s |

### Slowest actions

| Duration | Phase | Action | Status |
|---:|---|---|---|
| 7.797s | acquire (capture + save) | acquire: capture + save | PASS |
| 1.047s | state (capture / switch / restore) | set_state: switch job | PASS |
| 0.640s | read-only | get_context | PASS |
| 0.469s | move (set_origin + set_xyz) | set_xyz: z-wide move | PASS |
| 0.406s | move (set_origin + set_xyz) | move: restore XY + focus (frame 0,0,0) | PASS |
| 0.391s | move (set_origin + set_xyz) | set_xyz: XY move | PASS |
| 0.375s | move (set_origin + set_xyz) | set_xyz: z-galvo move | PASS |
| 0.125s | move (set_origin + set_xyz) | move: restore z-wide | PASS |
| 0.078s | state (capture / switch / restore) | get_state: after switch (settled) | PASS |
| 0.047s | read-only | get_xyz | PASS |

### Unconfirmed / failed changes

None -- every attempted change reported success and confirmed.

## Chronological detail (every attempted action)

| # | Time | Phase | Status | Result | Mutates scope | Action attempted | Args / target | Expected | Observed | Duration |
|---:|---|---|---|---|---|---|---|---|---|---:|
| 1 | 09:47:33.182 | read-only | PASS |  |  | get_instruments |  |  |  | 0.000s |
| 2 | 09:47:33.183 | read-only | PASS |  |  | registry: leica adapter registered |  |  | expected=True actual=True | 0.000s |
| 3 | 09:47:33.184 | read-only | PASS |  |  | get_actuators |  |  |  | 0.000s |
| 4 | 09:47:33.185 | read-only | PASS |  |  | actuators: expected menu |  |  | expected={'x': ['motoric'], 'y': ['motoric'], 'z': ['z-wide', 'z-galvo']} actual={'x': ['motoric'], 'y': ['motoric'], 'z': ['z-wide', 'z-galvo']} | 0.000s |
| 5 | 09:47:33.238 | read-only | PASS |  |  | get_xyz |  |  |  | 0.047s |
| 6 | 09:47:33.238 | read-only | PASS |  |  | get_xyz: x unit is um |  |  | expected='um' actual='um' | 0.000s |
| 7 | 09:47:33.239 | read-only | PASS |  |  | get_xyz: y unit is um |  |  | expected='um' actual='um' | 0.000s |
| 8 | 09:47:33.240 | read-only | PASS |  |  | get_xyz: z unit is um |  |  | expected='um' actual='um' | 0.000s |
| 9 | 09:47:33.240 | read-only | PASS |  |  | get_xyz: hardware block complete |  |  | expected=True actual=True | 0.000s |
| 10 | 09:47:33.241 | read-only | PASS |  |  | get_xyz: objective has a name |  |  | expected=True actual=True | 0.000s |
| 11 | 09:47:33.281 | read-only | PASS |  |  | get_state |  |  |  | 0.031s |
| 12 | 09:47:33.295 | read-only | PASS |  |  | get_acquisition_options |  |  |  | 0.016s |
| 13 | 09:47:33.295 | read-only | PASS |  |  | get_state: changeable job is in the job list |  |  | expected=True actual=True | 0.000s |
| 14 | 09:47:33.296 | read-only | PASS |  |  | get_state: observed carries an identity |  |  | expected=True actual=True | 0.000s |
| 15 | 09:47:33.297 | read-only | PASS |  |  | get_acquisition_options: active exporter is offered |  |  | expected=True actual=True | 0.000s |
| 16 | 09:47:33.940 | read-only | PASS |  |  | get_context |  |  |  | 0.640s |
| 17 | 09:47:33.941 | read-only | PASS |  |  | get_context: has session_hash6 |  |  | expected=True actual=True | 0.000s |
| 18 | 09:47:34.021 | move (set_origin + set_xyz) | PASS |  | YES | set_origin |  |  |  | 0.032s |
| 19 | 09:47:34.060 | move (set_origin + set_xyz) | PASS |  |  | get_xyz after set_origin |  |  |  | 0.031s |
| 20 | 09:47:34.061 | move (set_origin + set_xyz) | PASS |  |  | origin: frame x -> 0 |  |  | expected=0.0 actual=0.0 tol=20.0 | 0.000s |
| 21 | 09:47:34.061 | move (set_origin + set_xyz) | PASS |  |  | origin: frame y -> 0 |  |  | expected=0.0 actual=0.0 tol=20.0 | 0.000s |
| 22 | 09:47:34.062 | move (set_origin + set_xyz) | PASS |  |  | origin: frame z -> 0 |  |  | expected=0.0 actual=0.0 tol=1.0 | 0.000s |
| 23 | 09:47:34.448 | move (set_origin + set_xyz) | PASS |  | YES | set_xyz: XY move | to_frame=(25.0, 25.0, 0.0) z_actuator='z-galvo' |  |  | 0.391s |
| 24 | 09:47:34.488 | move (set_origin + set_xyz) | PASS |  |  | get_xyz after XY |  |  |  | 0.031s |
| 25 | 09:47:34.488 | move (set_origin + set_xyz) | PASS |  |  | xy: frame x |  |  | expected=25.0 actual=25.0 tol=20.0 | 0.000s |
| 26 | 09:47:34.489 | move (set_origin + set_xyz) | PASS |  |  | xy: frame y |  |  | expected=25.0 actual=25.000000000007276 tol=20.0 | 0.000s |
| 27 | 09:47:34.857 | move (set_origin + set_xyz) | PASS |  | YES | set_xyz: z-galvo move | to_frame=(25.0, 25.0, 2.0) z_actuator='z-galvo' |  |  | 0.375s |
| 28 | 09:47:34.906 | move (set_origin + set_xyz) | PASS |  |  | get_xyz after z-galvo |  |  |  | 0.047s |
| 29 | 09:47:34.907 | move (set_origin + set_xyz) | PASS |  |  | zgalvo: frame z |  |  | expected=2.0 actual=2.0 tol=1.0 | 0.000s |
| 30 | 09:47:34.907 | move (set_origin + set_xyz) | PASS |  |  | zgalvo: drive moved by delta (sign check) |  |  | expected=2.0 actual=2.0 tol=1.0 | 0.000s |
| 31 | 09:47:34.908 | move (set_origin + set_xyz) | PASS |  |  | zgalvo: z-wide drive unchanged |  |  | expected=0.0 actual=0.0 tol=1.0 | 0.000s |
| 32 | 09:47:35.369 | move (set_origin + set_xyz) | PASS |  | YES | set_xyz: z-wide move | to_frame=(25.0, 25.0, 5.0) z_actuator='z-wide' |  |  | 0.469s |
| 33 | 09:47:35.408 | move (set_origin + set_xyz) | PASS |  |  | get_xyz after z-wide |  |  |  | 0.031s |
| 34 | 09:47:35.409 | move (set_origin + set_xyz) | PASS |  |  | zwide: frame z is additive (z-wide + z-galvo) |  |  | expected=5.0 actual=5.0 tol=1.0 | 0.000s |
| 35 | 09:47:35.409 | move (set_origin + set_xyz) | PASS |  |  | zwide: drive moved by delta |  |  | expected=3.0 actual=3.0 tol=1.0 | 0.000s |
| 36 | 09:47:35.410 | move (set_origin + set_xyz) | PASS |  |  | zwide: z-galvo drive unchanged |  |  | expected=2.0 actual=2.0 tol=1.0 | 0.000s |
| 37 | 09:47:35.522 | move (set_origin + set_xyz) | PASS |  | YES | move: restore z-wide | z_wide_um=0.0 |  |  | 0.125s |
| 38 | 09:47:35.933 | move (set_origin + set_xyz) | PASS |  | YES | move: restore XY + focus (frame 0,0,0) | x_um=63500.0 y_um=41499.99999999999 z_wide_um=0.0 z_galvo_um=0.0 job='Overview' |  |  | 0.406s |
| 39 | 09:47:35.972 | state (capture / switch / restore) | PASS |  |  | get_state: capture |  |  |  | 0.032s |
| 40 | 09:47:37.034 | state (capture / switch / restore) | PASS |  | YES | set_state: switch job | to='HiRes' from='Overview' | to='HiRes' |  | 1.047s |
| 41 | 09:47:37.101 | state (capture / switch / restore) | PASS |  |  | get_state: after switch (settled) |  |  |  | 0.078s |
| 42 | 09:47:37.102 | state (capture / switch / restore) | FAIL |  |  | state: switched |  |  | expected='HiRes' actual='Overview' | 0.000s |
| 43 | 09:47:37.133 | state (capture / switch / restore) | PASS |  | YES | set_state: restore | restore_to='Overview' | restore_to='Overview' |  | 0.032s |
| 44 | 09:47:37.172 | state (capture / switch / restore) | PASS |  |  | get_state: after restore (settled) |  |  |  | 0.031s |
| 45 | 09:47:37.173 | state (capture / switch / restore) | PASS |  |  | state: restored |  |  | expected='Overview' actual='Overview' | 0.000s |
| 46 | 09:47:37.174 | setup | SKIP |  |  | phase: autofocus |  |  | use --allow-autofocus to enable | 0.000s |
| 47 | 09:47:44.998 | acquire (capture + save) | PASS |  | YES | acquire: capture + save | exporter='lasx_native_autosave' backlash_correction=True |  |  | 7.797s |
| 48 | 09:47:44.999 | acquire (capture + save) | PASS |  |  | acquire: at least one image |  |  | expected=True actual=True | 0.000s |
| 49 | 09:47:45.000 | acquire (capture + save) | PASS |  |  | acquire: at least one xml |  |  | expected=True actual=True | 0.000s |
| 50 | 09:47:45.001 | acquire (capture + save) | PASS |  |  | acquire: image files exist and are non-empty |  |  | expected=True actual=True | 0.000s |
| 51 | 09:47:45.002 | acquire (capture + save) | PASS |  |  | acquire: backlash_correction ran |  |  | expected='backlash-corrected' actual='backlash-corrected' | 0.000s |

# Hardware validation run report

Every change this run attempted on the instrument is listed below, including failed attempts and restore/cleanup steps (see the *Mutates scope* column). Changes carry their success+CONFIRMED / success+UNCONFIRMED / FAILED result and attempt counts in the *Result* column.

## Run metadata

- **Validator**: `validate_zmart_adapter`
- **Arguments**: `--yes --allow-move --allow-state --allow-acquire --allow-missing-lasx --exporter navigator_expert --output=tests\_report\zmart_adapter_acquire_retry.jsonl --report-dir=tests\_report`
- **Backend**: live LAS X (simulator or scope)
- **Date**: 2026-07-07
- **Started / finished**: 09:39:37 / 09:40:20 (43.8s)
- **Host**: ZMB-Y42H93-STI8 (Windows-10-10.0.26100-SP0)
- **Python**: 3.11.15
- **Driver commit**: aecf1a2 on claude/smart-drivers-code-review-ky4phc (working tree has local changes)
- **Driver log**: `tests\_report\driver_log_20260707-093937.log` (full log-line capture)

## Summary

| Phase | Actions attempted | Passed | Warned | Failed | Skipped | Confirmed | Unconfirmed |
|---|---:|---:|---:|---:|---:|---:|---:|
| read-only | 17 | 17 | 0 | 0 | 0 | 0 | 0 |
| move (set_origin + set_xyz) | 21 | 21 | 0 | 0 | 0 | 0 | 0 |
| state (capture / switch / restore) | 7 | 6 | 0 | 1 | 0 | 0 | 0 |
| setup | 1 | 0 | 0 | 0 | 1 | 0 | 0 |
| acquire (capture + save) | 1 | 0 | 0 | 1 | 0 | 0 | 0 |
| **total** | **47** | **44** | **0** | **2** | **1** | **0** | **0** |

## Timing overview

### Per phase

| Phase | Timed actions | Min | Median | Max |
|---|---:|---:|---:|---:|
| read-only | 4 | 0.015s | 0.055s | 0.532s |
| move (set_origin + set_xyz) | 10 | 0.015s | 0.047s | 0.406s |
| state (capture / switch / restore) | 5 | 0.016s | 0.032s | 13.719s |
| acquire (capture + save) | 1 | 26.313s | 26.313s | 26.313s |

### Slowest actions

| Duration | Phase | Action | Status |
|---:|---|---|---|
| 26.313s | acquire (capture + save) | acquire: capture + save | FAIL |
| 13.719s | state (capture / switch / restore) | set_state: switch job | PASS |
| 0.532s | read-only | get_context | PASS |
| 0.406s | move (set_origin + set_xyz) | set_xyz: z-wide move | PASS |
| 0.406s | move (set_origin + set_xyz) | move: restore XY + focus (frame 0,0,0) | PASS |
| 0.390s | move (set_origin + set_xyz) | set_xyz: XY move | PASS |
| 0.375s | move (set_origin + set_xyz) | set_xyz: z-galvo move | PASS |
| 0.063s | read-only | get_xyz | PASS |
| 0.047s | read-only | get_state | PASS |
| 0.047s | move (set_origin + set_xyz) | set_origin | PASS |

### Unconfirmed / failed changes

| Phase | Action | Result | Attempts | Duration | Observed |
|---|---|---|---|---:|---|
| acquire (capture + save) | acquire: capture + save | FAILED |  | 26.313s | RuntimeError: No Navigator Expert OME-TIFF files found after acquisition (scanned Z:\zmbstaff\10374\Raw_Data\Data for ELMI) |

## Chronological detail (every attempted action)

| # | Time | Phase | Status | Result | Mutates scope | Action attempted | Args / target | Expected | Observed | Duration |
|---:|---|---|---|---|---|---|---|---|---|---:|
| 1 | 09:39:38.182 | read-only | PASS |  |  | get_instruments |  |  |  | 0.000s |
| 2 | 09:39:38.183 | read-only | PASS |  |  | registry: leica adapter registered |  |  | expected=True actual=True | 0.000s |
| 3 | 09:39:38.183 | read-only | PASS |  |  | get_actuators |  |  |  | 0.000s |
| 4 | 09:39:38.184 | read-only | PASS |  |  | actuators: expected menu |  |  | expected={'x': ['motoric'], 'y': ['motoric'], 'z': ['z-wide', 'z-galvo']} actual={'x': ['motoric'], 'y': ['motoric'], 'z': ['z-wide', 'z-galvo']} | 0.000s |
| 5 | 09:39:38.238 | read-only | PASS |  |  | get_xyz |  |  |  | 0.063s |
| 6 | 09:39:38.239 | read-only | PASS |  |  | get_xyz: x unit is um |  |  | expected='um' actual='um' | 0.000s |
| 7 | 09:39:38.239 | read-only | PASS |  |  | get_xyz: y unit is um |  |  | expected='um' actual='um' | 0.000s |
| 8 | 09:39:38.240 | read-only | PASS |  |  | get_xyz: z unit is um |  |  | expected='um' actual='um' | 0.000s |
| 9 | 09:39:38.241 | read-only | PASS |  |  | get_xyz: hardware block complete |  |  | expected=True actual=True | 0.000s |
| 10 | 09:39:38.241 | read-only | PASS |  |  | get_xyz: objective has a name |  |  | expected=True actual=True | 0.000s |
| 11 | 09:39:38.284 | read-only | PASS |  |  | get_state |  |  |  | 0.047s |
| 12 | 09:39:38.298 | read-only | PASS |  |  | get_acquisition_options |  |  |  | 0.015s |
| 13 | 09:39:38.298 | read-only | PASS |  |  | get_state: changeable job is in the job list |  |  | expected=True actual=True | 0.000s |
| 14 | 09:39:38.299 | read-only | PASS |  |  | get_state: observed carries an identity |  |  | expected=True actual=True | 0.000s |
| 15 | 09:39:38.300 | read-only | PASS |  |  | get_acquisition_options: active exporter is offered |  |  | expected=True actual=True | 0.000s |
| 16 | 09:39:38.832 | read-only | PASS |  |  | get_context |  |  |  | 0.532s |
| 17 | 09:39:38.834 | read-only | PASS |  |  | get_context: has session_hash6 |  |  | expected=True actual=True | 0.000s |
| 18 | 09:39:38.918 | move (set_origin + set_xyz) | PASS |  | YES | set_origin |  |  |  | 0.047s |
| 19 | 09:39:38.959 | move (set_origin + set_xyz) | PASS |  |  | get_xyz after set_origin |  |  |  | 0.047s |
| 20 | 09:39:38.960 | move (set_origin + set_xyz) | PASS |  |  | origin: frame x -> 0 |  |  | expected=0.0 actual=0.0 tol=20.0 | 0.000s |
| 21 | 09:39:38.961 | move (set_origin + set_xyz) | PASS |  |  | origin: frame y -> 0 |  |  | expected=0.0 actual=0.0 tol=20.0 | 0.000s |
| 22 | 09:39:38.962 | move (set_origin + set_xyz) | PASS |  |  | origin: frame z -> 0 |  |  | expected=0.0 actual=0.0 tol=1.0 | 0.000s |
| 23 | 09:39:39.353 | move (set_origin + set_xyz) | PASS |  | YES | set_xyz: XY move | to_frame=(25.0, 25.0, 0.0) z_actuator='z-galvo' |  |  | 0.390s |
| 24 | 09:39:39.395 | move (set_origin + set_xyz) | PASS |  |  | get_xyz after XY |  |  |  | 0.047s |
| 25 | 09:39:39.396 | move (set_origin + set_xyz) | PASS |  |  | xy: frame x |  |  | expected=25.0 actual=25.0 tol=20.0 | 0.000s |
| 26 | 09:39:39.396 | move (set_origin + set_xyz) | PASS |  |  | xy: frame y |  |  | expected=25.0 actual=25.000000000007276 tol=20.0 | 0.000s |
| 27 | 09:39:39.771 | move (set_origin + set_xyz) | PASS |  | YES | set_xyz: z-galvo move | to_frame=(25.0, 25.0, 2.0) z_actuator='z-galvo' |  |  | 0.375s |
| 28 | 09:39:39.821 | move (set_origin + set_xyz) | PASS |  |  | get_xyz after z-galvo |  |  |  | 0.047s |
| 29 | 09:39:39.822 | move (set_origin + set_xyz) | PASS |  |  | zgalvo: frame z |  |  | expected=2.0 actual=2.0 tol=1.0 | 0.000s |
| 30 | 09:39:39.822 | move (set_origin + set_xyz) | PASS |  |  | zgalvo: drive moved by delta (sign check) |  |  | expected=2.0 actual=2.0 tol=1.0 | 0.000s |
| 31 | 09:39:39.823 | move (set_origin + set_xyz) | PASS |  |  | zgalvo: z-wide drive unchanged |  |  | expected=0.0 actual=0.0 tol=1.0 | 0.000s |
| 32 | 09:39:40.220 | move (set_origin + set_xyz) | PASS |  | YES | set_xyz: z-wide move | to_frame=(25.0, 25.0, 5.0) z_actuator='z-wide' |  |  | 0.406s |
| 33 | 09:39:40.259 | move (set_origin + set_xyz) | PASS |  |  | get_xyz after z-wide |  |  |  | 0.032s |
| 34 | 09:39:40.260 | move (set_origin + set_xyz) | PASS |  |  | zwide: frame z is additive (z-wide + z-galvo) |  |  | expected=5.0 actual=5.0 tol=1.0 | 0.000s |
| 35 | 09:39:40.260 | move (set_origin + set_xyz) | PASS |  |  | zwide: drive moved by delta |  |  | expected=3.0 actual=3.0 tol=1.0 | 0.000s |
| 36 | 09:39:40.261 | move (set_origin + set_xyz) | PASS |  |  | zwide: z-galvo drive unchanged |  |  | expected=2.0 actual=2.0 tol=1.0 | 0.000s |
| 37 | 09:39:40.279 | move (set_origin + set_xyz) | PASS |  | YES | move: restore z-wide | z_wide_um=0.0 |  |  | 0.015s |
| 38 | 09:39:40.673 | move (set_origin + set_xyz) | PASS |  | YES | move: restore XY + focus (frame 0,0,0) | x_um=63500.0 y_um=41499.99999999999 z_wide_um=0.0 z_galvo_um=0.0 job='HiRes' |  |  | 0.406s |
| 39 | 09:39:40.711 | state (capture / switch / restore) | PASS |  |  | get_state: capture |  |  |  | 0.032s |
| 40 | 09:39:54.449 | state (capture / switch / restore) | PASS |  | YES | set_state: switch job | to='Overview' from='HiRes' | to='Overview' |  | 13.719s |
| 41 | 09:39:54.489 | state (capture / switch / restore) | PASS |  |  | get_state: after switch (settled) |  |  |  | 0.047s |
| 42 | 09:39:54.490 | state (capture / switch / restore) | FAIL |  |  | state: switched |  |  | expected='Overview' actual='HiRes' | 0.000s |
| 43 | 09:39:54.503 | state (capture / switch / restore) | PASS |  | YES | set_state: restore | restore_to='HiRes' | restore_to='HiRes' |  | 0.016s |
| 44 | 09:39:54.543 | state (capture / switch / restore) | PASS |  |  | get_state: after restore (settled) |  |  |  | 0.031s |
| 45 | 09:39:54.543 | state (capture / switch / restore) | PASS |  |  | state: restored |  |  | expected='HiRes' actual='HiRes' | 0.000s |
| 46 | 09:39:54.544 | setup | SKIP |  |  | phase: autofocus |  |  | use --allow-autofocus to enable | 0.000s |
| 47 | 09:40:20.870 | acquire (capture + save) | FAIL | FAILED | YES | acquire: capture + save | exporter='navigator_expert' backlash_correction=True |  | RuntimeError: No Navigator Expert OME-TIFF files found after acquisition (scanned Z:\zmbstaff\10374\Raw_Data\Data for ELMI) | 26.313s |

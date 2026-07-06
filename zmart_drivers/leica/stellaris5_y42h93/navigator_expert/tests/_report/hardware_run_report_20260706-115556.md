# Hardware validation run report

Every change this run attempted on the instrument is listed below, including failed attempts and restore/cleanup steps (see the *Mutates scope* column). Changes carry their success+CONFIRMED / success+UNCONFIRMED / FAILED result and attempt counts in the *Result* column.

## Run metadata

- **Validator**: `validate_hardware`
- **Arguments**: `--yes --allow-xy --allow-z --allow-missing-lasx --state-reader-mode log --output=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\hardware_validate_log.jsonl --report-dir=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report`
- **Backend**: live LAS X (simulator or scope)
- **Date**: 2026-07-06
- **Started / finished**: 11:55:56 / 11:56:01 (5.0s)
- **Host**: ZMB-LASX-PC (Windows-10-10.0.26200-SP0)
- **Python**: 3.11.15
- **Driver commit**: unknown on unknown
- **Driver log**: `\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\driver_log_20260706-115556.log` (full log-line capture)

## Summary

| Phase | Actions attempted | Passed | Warned | Failed | Skipped | Confirmed | Unconfirmed |
|---|---:|---:|---:|---:|---:|---:|---:|
| setup | 3 | 1 | 0 | 0 | 2 | 0 | 0 |
| read-only | 9 | 8 | 0 | 1 | 0 | 0 | 0 |
| job selection round-trip | 14 | 13 | 0 | 0 | 1 | 3 | 0 |
| settings round-trip | 47 | 46 | 0 | 0 | 1 | 33 | 0 |
| xy 10-position pattern | 42 | 42 | 0 | 0 | 0 | 11 | 0 |
| z-galvo round-trip | 5 | 5 | 0 | 0 | 0 | 2 | 0 |
| **total** | **120** | **115** | **0** | **1** | **4** | **49** | **0** |

## Timing overview

### Per phase

| Phase | Timed actions | Min | Median | Max |
|---|---:|---:|---:|---:|
| read-only | 5 | 0.031s | 0.047s | 0.063s |
| job selection round-trip | 9 | 0.031s | 0.062s | 0.766s |
| settings round-trip | 32 | 0.015s | 0.016s | 0.125s |
| xy 10-position pattern | 16 | 0.015s | 0.016s | 0.031s |
| z-galvo round-trip | 4 | 0.015s | 0.023s | 0.063s |

### Slowest actions

| Duration | Phase | Action | Status |
|---:|---|---|---|
| 0.766s | job selection round-trip | job selection: select job | PASS |
| 0.766s | job selection round-trip | job selection: select job | PASS |
| 0.610s | job selection round-trip | job selection: select job | PASS |
| 0.125s | settings round-trip | sequential_mode: write alternate | PASS |
| 0.063s | read-only | get_scan_status | PASS |
| 0.063s | read-only | get_xy | PASS |
| 0.063s | z-galvo round-trip | z: read start | PASS |
| 0.062s | job selection round-trip | job selection: log poll confirmed Overview | PASS |
| 0.062s | job selection round-trip | job selection: log poll confirmed AF Job | PASS |
| 0.047s | read-only | get_hardware_info | PASS |

### Unconfirmed / failed changes

None -- every attempted change reported success and confirmed.

## Chronological detail (every attempted action)

| # | Time | Phase | Status | Result | Mutates scope | Action attempted | Args / target | Expected | Observed | Duration |
|---:|---|---|---|---|---|---|---|---|---|---:|
| 1 | 11:55:57.372 | setup | PASS |  |  | limits: connect handshake | limits_path='<machine-local snapshot>' |  |  | 0.000s |
| 2 | 11:55:57.374 | read-only | PASS |  |  | ping |  |  |  | 0.000s |
| 3 | 11:55:57.447 | read-only | PASS |  |  | get_scan_status |  |  |  | 0.063s |
| 4 | 11:55:57.448 | read-only | PASS |  |  | get_jobs |  |  |  | 0.000s |
| 5 | 11:55:57.508 | read-only | PASS |  |  | get_hardware_info |  |  |  | 0.047s |
| 6 | 11:55:57.568 | read-only | PASS |  |  | get_xy |  |  |  | 0.063s |
| 7 | 11:55:57.569 | read-only | FAIL |  |  | job: resolve |  |  | no jobs returned with --state-reader-mode log | 0.000s |
| 8 | 11:55:57.589 | read-only | PASS |  |  | job: resolve api control for log experiment | purpose='drive log selected-job poll' |  |  | 0.031s |
| 9 | 11:55:57.590 | read-only | PASS |  |  | job: resolved | job='Overview' |  |  | 0.000s |
| 10 | 11:55:57.651 | read-only | PASS |  |  | settings: read | job='Overview' |  |  | 0.047s |
| 11 | 11:55:57.663 | job selection round-trip | PASS |  |  | job selection: read jobs | mode='api' |  |  | 0.000s |
| 12 | 11:55:58.319 | job selection round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | job selection: select job | index=0 count=3 job='AF Job' job_order=['AF Job', 'HiRes', 'Overview'] |  | SelectJob 'AF Job'; [total=0.550s, att=1, conf=1, m=async] | 0.610s |
| 13 | 11:55:58.382 | job selection round-trip | PASS |  |  | job selection: log poll confirmed AF Job | index=0 count=3 job='AF Job' job_order=['AF Job', 'HiRes', 'Overview'] log_poll={'success': True, 'value': 'AF Job', 'matched_at': 1783331758.208, 'attempts': … |  | matched; last_reason=matched; value='AF Job'; log_event_delta=0.501s; api_select_elapsed=0.550s; attempts=1 | 0.062s |
| 14 | 11:55:58.407 | job selection round-trip | PASS |  |  | job selection: read selected job | index=0 count=3 job='AF Job' job_order=['AF Job', 'HiRes', 'Overview'] |  |  | 0.031s |
| 15 | 11:55:58.409 | job selection round-trip | PASS |  |  | job selection: confirmed AF Job |  |  | expected='AF Job' actual='AF Job' | 0.000s |
| 16 | 11:55:59.181 | job selection round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | job selection: select job | index=1 count=3 job='HiRes' job_order=['AF Job', 'HiRes', 'Overview'] |  | SelectJob 'HiRes'; [total=0.709s, att=1, conf=1, m=async] | 0.766s |
| 17 | 11:55:59.243 | job selection round-trip | PASS |  |  | job selection: log poll confirmed HiRes | index=1 count=3 job='HiRes' job_order=['AF Job', 'HiRes', 'Overview'] log_poll={'success': True, 'value': 'HiRes', 'matched_at': 1783331759.133, 'attempts': 1,… |  | matched; last_reason=matched; value='HiRes'; log_event_delta=0.724s; api_select_elapsed=0.709s; attempts=1 | 0.046s |
| 18 | 11:55:59.278 | job selection round-trip | PASS |  |  | job selection: read selected job | index=1 count=3 job='HiRes' job_order=['AF Job', 'HiRes', 'Overview'] |  |  | 0.047s |
| 19 | 11:55:59.279 | job selection round-trip | PASS |  |  | job selection: confirmed HiRes |  |  | expected='HiRes' actual='HiRes' | 0.000s |
| 20 | 11:56:00.056 | job selection round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | job selection: select job | index=2 count=3 job='Overview' job_order=['AF Job', 'HiRes', 'Overview'] |  | SelectJob 'Overview'; [total=0.713s, att=1, conf=1, m=async] | 0.766s |
| 21 | 11:56:00.118 | job selection round-trip | PASS |  |  | job selection: log poll confirmed Overview | index=2 count=3 job='Overview' job_order=['AF Job', 'HiRes', 'Overview'] log_poll={'success': True, 'value': 'Overview', 'matched_at': 1783331760.001, 'attempt… |  | matched; last_reason=matched; value='Overview'; log_event_delta=0.721s; api_select_elapsed=0.713s; attempts=1 | 0.062s |
| 22 | 11:56:00.143 | job selection round-trip | PASS |  |  | job selection: read selected job | index=2 count=3 job='Overview' job_order=['AF Job', 'HiRes', 'Overview'] |  |  | 0.032s |
| 23 | 11:56:00.144 | job selection round-trip | PASS |  |  | job selection: confirmed Overview |  |  | expected='Overview' actual='Overview' | 0.000s |
| 24 | 11:56:00.145 | job selection round-trip | SKIP |  |  | job selection: restore |  |  | 'Overview' already confirmed by round-trip | 0.000s |
| 25 | 11:56:00.193 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | zoom: write current | job='Overview' current=2.0 target=5.0 | target=5.0 | Zoom -> 2.0; [total=0.030s, att=1, conf=1, m=async] | 0.032s |
| 26 | 11:56:00.212 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | zoom: write alternate | job='Overview' current=2.0 target=5.0 | target=5.0 | Zoom -> 5.0; [total=0.018s, att=1, conf=1, m=async] | 0.015s |
| 27 | 11:56:00.241 | settings round-trip | PASS |  |  | zoom: readback |  |  | expected=5.0 actual=5.0000127156898895 tol=0.1 | 0.000s |
| 28 | 11:56:00.265 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | zoom: restore | job='Overview' restore_to=2.0 | restore_to=2.0 | Zoom -> 2.0; [total=0.023s, att=1, conf=1, m=async] | 0.032s |
| 29 | 11:56:00.322 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_speed: write current | job='Overview' current=400 target=600 | target=600 | ScanSpeed -> 400; [total=0.021s, att=1, conf=1, m=async] | 0.016s |
| 30 | 11:56:00.339 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_speed: write alternate | job='Overview' current=400 target=600 | target=600 | ScanSpeed -> 600; [total=0.015s, att=1, conf=1, m=async] | 0.016s |
| 31 | 11:56:00.353 | settings round-trip | PASS |  |  | scan_speed: readback |  |  | expected=600 actual=600 | 0.000s |
| 32 | 11:56:00.369 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_speed: restore | job='Overview' restore_to=400 | restore_to=400 | ScanSpeed -> 400; [total=0.015s, att=1, conf=1, m=async] | 0.000s |
| 33 | 11:56:00.402 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_resonant: write current | job='Overview' current=False target=True | target=True | Resonant -> False; [total=0.018s, att=1, conf=1, m=async] | 0.031s |
| 34 | 11:56:00.421 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_resonant: write alternate | job='Overview' current=False target=True | target=True | Resonant -> True; [total=0.018s, att=1, conf=1, m=async] | 0.016s |
| 35 | 11:56:00.435 | settings round-trip | PASS |  |  | scan_resonant: readback |  |  | expected=True actual=True | 0.000s |
| 36 | 11:56:00.451 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_resonant: restore | job='Overview' restore_to=False | restore_to=False | Resonant -> False; [total=0.015s, att=1, conf=1, m=async] | 0.015s |
| 37 | 11:56:00.466 | settings round-trip | PASS |  |  | scan_mode: read current | job='Overview' |  |  | 0.016s |
| 38 | 11:56:00.467 | settings round-trip | PASS |  |  | scan_mode: is xyz |  |  | expected='xyz' actual='xyz' | 0.000s |
| 39 | 11:56:00.509 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | sequential_mode: write current | job='Overview' current='Line' target='Frame' | target='Frame' | SequentialMode -> Line; [total=0.027s, att=1, conf=1, m=async] | 0.016s |
| 40 | 11:56:00.649 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | sequential_mode: write alternate | job='Overview' current='Line' target='Frame' | target='Frame' | SequentialMode -> Frame; [total=0.139s, att=1, conf=1, m=async] | 0.125s |
| 41 | 11:56:00.664 | settings round-trip | PASS |  |  | sequential_mode: readback |  |  | expected='Frame' actual='Frame' | 0.000s |
| 42 | 11:56:00.682 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | sequential_mode: restore | job='Overview' restore_to='Line' | restore_to='Line' | SequentialMode -> Line; [total=0.017s, att=1, conf=1, m=async] | 0.032s |
| 43 | 11:56:00.720 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_field_rotation: write current | job='Overview' current=0.0 target=5.0 | target=5.0 | Rotation -> 0.0; [total=0.024s, att=1, conf=1, m=async] | 0.031s |
| 44 | 11:56:00.737 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_field_rotation: write alternate | job='Overview' current=0.0 target=5.0 | target=5.0 | Rotation -> 5.0; [total=0.015s, att=1, conf=1, m=async] | 0.015s |
| 45 | 11:56:00.751 | settings round-trip | PASS |  |  | scan_field_rotation: readback |  |  | expected=5.0 actual=5.0 tol=0.5 | 0.000s |
| 46 | 11:56:00.767 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_field_rotation: restore | job='Overview' restore_to=0.0 | restore_to=0.0 | Rotation -> 0.0; [total=0.015s, att=1, conf=1, m=async] | 0.016s |
| 47 | 11:56:00.807 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | image_format: write current | job='Overview' current='512 x 512' target='1024 x 1024' | target='1024 x 1024' | Format -> 512 x 512; [total=0.026s, att=1, conf=1, m=async] | 0.032s |
| 48 | 11:56:00.825 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | image_format: write alternate | job='Overview' current='512 x 512' target='1024 x 1024' | target='1024 x 1024' | Format -> 1024 x 1024; [total=0.016s, att=1, conf=1, m=async] | 0.015s |
| 49 | 11:56:00.840 | settings round-trip | PASS |  |  | image_format: readback |  |  | expected='1024 x 1024' actual='1024 x 1024' | 0.000s |
| 50 | 11:56:00.859 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | image_format: restore | job='Overview' restore_to='512 x 512' | restore_to='512 x 512' | Format -> 512 x 512; [total=0.018s, att=1, conf=1, m=async] | 0.015s |
| 51 | 11:56:00.891 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_accumulation: write current | job='Overview' current=1 target=2 | target=2 | Setting[0].FrameAccumulation -> 1; [total=0.018s, att=1, conf=1, m=async] | 0.016s |
| 52 | 11:56:00.909 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_accumulation: write alternate | job='Overview' current=1 target=2 | target=2 | Setting[0].FrameAccumulation -> 2; [total=0.016s, att=1, conf=1, m=async] | 0.015s |
| 53 | 11:56:00.923 | settings round-trip | PASS |  |  | frame_accumulation: readback |  |  | expected=2 actual=2 | 0.000s |
| 54 | 11:56:00.956 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_accumulation: restore | job='Overview' restore_to=1 | restore_to=1 | Setting[0].FrameAccumulation -> 1; [total=0.032s, att=1, conf=1, m=async] | 0.031s |
| 55 | 11:56:00.989 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_average: write current | job='Overview' current=1 target=2 | target=2 | Setting[0].FrameAverage -> 1; [total=0.018s, att=1, conf=1, m=async] | 0.015s |
| 56 | 11:56:01.010 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_average: write alternate | job='Overview' current=1 target=2 | target=2 | Setting[0].FrameAverage -> 2; [total=0.018s, att=1, conf=1, m=async] | 0.016s |
| 57 | 11:56:01.023 | settings round-trip | PASS |  |  | frame_average: readback |  |  | expected=2 actual=2 | 0.000s |
| 58 | 11:56:01.040 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_average: restore | job='Overview' restore_to=1 | restore_to=1 | Setting[0].FrameAverage -> 1; [total=0.015s, att=1, conf=1, m=async] | 0.015s |
| 59 | 11:56:01.072 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_accumulation: write current | job='Overview' current=1 target=2 | target=2 | Setting[0].LineAccumulation -> 1; [total=0.018s, att=1, conf=1, m=async] | 0.031s |
| 60 | 11:56:01.089 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_accumulation: write alternate | job='Overview' current=1 target=2 | target=2 | Setting[0].LineAccumulation -> 2; [total=0.015s, att=1, conf=1, m=async] | 0.000s |
| 61 | 11:56:01.102 | settings round-trip | PASS |  |  | line_accumulation: readback |  |  | expected=2 actual=2 | 0.000s |
| 62 | 11:56:01.120 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_accumulation: restore | job='Overview' restore_to=1 | restore_to=1 | Setting[0].LineAccumulation -> 1; [total=0.016s, att=1, conf=1, m=async] | 0.031s |
| 63 | 11:56:01.158 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_average: write current | job='Overview' current=1 target=2 | target=2 | Setting[0].LineAverage -> 1; [total=0.020s, att=1, conf=1, m=async] | 0.015s |
| 64 | 11:56:01.174 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_average: write alternate | job='Overview' current=1 target=2 | target=2 | Setting[0].LineAverage -> 2; [total=0.015s, att=1, conf=1, m=async] | 0.016s |
| 65 | 11:56:01.188 | settings round-trip | PASS |  |  | line_average: readback |  |  | expected=2 actual=2 | 0.000s |
| 66 | 11:56:01.207 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_average: restore | job='Overview' restore_to=1 | restore_to=1 | Setting[0].LineAverage -> 1; [total=0.017s, att=1, conf=1, m=async] | 0.015s |
| 67 | 11:56:01.241 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | pinhole_airy: write current | job='Overview' current=1.0 target=1.2 | target=1.2 | Setting[0].PinholeAiry -> 1.0; [total=0.019s, att=1, conf=1, m=async] | 0.015s |
| 68 | 11:56:01.258 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | pinhole_airy: write alternate | job='Overview' current=1.0 target=1.2 | target=1.2 | Setting[0].PinholeAiry -> 1.2; [total=0.015s, att=1, conf=1, m=async] | 0.016s |
| 69 | 11:56:01.274 | settings round-trip | PASS |  |  | pinhole_airy: readback |  |  | expected=1.2 actual=1.2 tol=0.05 | 0.000s |
| 70 | 11:56:01.290 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | pinhole_airy: restore | job='Overview' restore_to=1.0 | restore_to=1.0 | Setting[0].PinholeAiry -> 1.0; [total=0.015s, att=1, conf=1, m=async] | 0.015s |
| 71 | 11:56:01.304 | settings round-trip | SKIP |  |  | detector_gain: round-trip |  |  | HyD 2 exposes no writable gain range; not mutating gain | 0.000s |
| 72 | 11:56:01.318 | xy 10-position pattern | PASS |  |  | xy: read start | mode='api' purpose='stage-safety-anchor' |  |  | 0.016s |
| 73 | 11:56:01.343 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 01 | index=1 count=10 from=(64220.0, 41180.0) to=(64245.0, 41180.0) radius_um=25.0 | to=(64245.0, 41180.0) | MoveXY -> (64245.0, 41180.0) um; [total=0.023s, att=1, conf=1, m=async] | 0.031s |
| 74 | 11:56:01.356 | xy 10-position pattern | PASS |  |  | xy: read 01 | index=1 count=10 from=(64220.0, 41180.0) to=(64245.0, 41180.0) radius_um=25.0 | to=(64245.0, 41180.0) |  | 0.015s |
| 75 | 11:56:01.357 | xy 10-position pattern | PASS |  |  | xy: x readback 01 |  |  | expected=64245.0 actual=64240.00000000001 tol=20.0 | 0.000s |
| 76 | 11:56:01.358 | xy 10-position pattern | PASS |  |  | xy: y readback 01 |  |  | expected=41180.0 actual=41180.0 tol=20.0 | 0.000s |
| 77 | 11:56:01.372 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 02 | index=2 count=10 from=(64220.0, 41180.0) to=(64240.225, 41194.695) radius_um=25.0 | to=(64240.225, 41194.695) | MoveXY -> (64240.225, 41194.695) um; [total=0.013s, att=1, conf=1, m=async] | 0.016s |
| 78 | 11:56:01.385 | xy 10-position pattern | PASS |  |  | xy: read 02 | index=2 count=10 from=(64220.0, 41180.0) to=(64240.225, 41194.695) radius_um=25.0 | to=(64240.225, 41194.695) |  | 0.016s |
| 79 | 11:56:01.386 | xy 10-position pattern | PASS |  |  | xy: x readback 02 |  |  | expected=64240.225 actual=64240.00000000001 tol=20.0 | 0.000s |
| 80 | 11:56:01.387 | xy 10-position pattern | PASS |  |  | xy: y readback 02 |  |  | expected=41194.695 actual=41180.0 tol=20.0 | 0.000s |
| 81 | 11:56:01.402 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 03 | index=3 count=10 from=(64220.0, 41180.0) to=(64227.725, 41203.776) radius_um=25.0 | to=(64227.725, 41203.776) | MoveXY -> (64227.725, 41203.776) um; [total=0.013s, att=1, conf=1, m=async] | 0.015s |
| 82 | 11:56:01.414 | xy 10-position pattern | PASS |  |  | xy: read 03 | index=3 count=10 from=(64220.0, 41180.0) to=(64227.725, 41203.776) radius_um=25.0 | to=(64227.725, 41203.776) |  | 0.000s |
| 83 | 11:56:01.415 | xy 10-position pattern | PASS |  |  | xy: x readback 03 |  |  | expected=64227.725 actual=64220.0 tol=20.0 | 0.000s |
| 84 | 11:56:01.415 | xy 10-position pattern | PASS |  |  | xy: y readback 03 |  |  | expected=41203.776 actual=41200.0 tol=20.0 | 0.000s |
| 85 | 11:56:01.430 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 04 | index=4 count=10 from=(64220.0, 41180.0) to=(64212.275, 41203.776) radius_um=25.0 | to=(64212.275, 41203.776) | MoveXY -> (64212.275, 41203.776) um; [total=0.013s, att=1, conf=1, m=async] | 0.000s |
| 86 | 11:56:01.443 | xy 10-position pattern | PASS |  |  | xy: read 04 | index=4 count=10 from=(64220.0, 41180.0) to=(64212.275, 41203.776) radius_um=25.0 | to=(64212.275, 41203.776) |  | 0.016s |
| 87 | 11:56:01.444 | xy 10-position pattern | PASS |  |  | xy: x readback 04 |  |  | expected=64212.275 actual=64199.99999999999 tol=20.0 | 0.000s |
| 88 | 11:56:01.445 | xy 10-position pattern | PASS |  |  | xy: y readback 04 |  |  | expected=41203.776 actual=41200.0 tol=20.0 | 0.000s |
| 89 | 11:56:01.460 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 05 | index=5 count=10 from=(64220.0, 41180.0) to=(64199.775, 41194.695) radius_um=25.0 | to=(64199.775, 41194.695) | MoveXY -> (64199.775, 41194.695) um; [total=0.014s, att=1, conf=1, m=async] | 0.015s |
| 90 | 11:56:01.474 | xy 10-position pattern | PASS |  |  | xy: read 05 | index=5 count=10 from=(64220.0, 41180.0) to=(64199.775, 41194.695) radius_um=25.0 | to=(64199.775, 41194.695) |  | 0.016s |
| 91 | 11:56:01.474 | xy 10-position pattern | PASS |  |  | xy: x readback 05 |  |  | expected=64199.775 actual=64180.0 tol=20.0 | 0.000s |
| 92 | 11:56:01.475 | xy 10-position pattern | PASS |  |  | xy: y readback 05 |  |  | expected=41194.695 actual=41180.0 tol=20.0 | 0.000s |
| 93 | 11:56:01.491 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 06 | index=6 count=10 from=(64220.0, 41180.0) to=(64195.0, 41180.0) radius_um=25.0 | to=(64195.0, 41180.0) | MoveXY -> (64195.0, 41180.0) um; [total=0.015s, att=1, conf=1, m=async] | 0.015s |
| 94 | 11:56:01.505 | xy 10-position pattern | PASS |  |  | xy: read 06 | index=6 count=10 from=(64220.0, 41180.0) to=(64195.0, 41180.0) radius_um=25.0 | to=(64195.0, 41180.0) |  | 0.016s |
| 95 | 11:56:01.505 | xy 10-position pattern | PASS |  |  | xy: x readback 06 |  |  | expected=64195.0 actual=64180.0 tol=20.0 | 0.000s |
| 96 | 11:56:01.506 | xy 10-position pattern | PASS |  |  | xy: y readback 06 |  |  | expected=41180.0 actual=41180.0 tol=20.0 | 0.000s |
| 97 | 11:56:01.511 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 07 | index=7 count=10 from=(64220.0, 41180.0) to=(64199.775, 41165.305) radius_um=25.0 | to=(64199.775, 41165.305) | MoveXY -> (64199.775, 41165.305) um; [total=0.004s, att=1, conf=1, m=async] | 0.016s |
| 98 | 11:56:01.525 | xy 10-position pattern | PASS |  |  | xy: read 07 | index=7 count=10 from=(64220.0, 41180.0) to=(64199.775, 41165.305) radius_um=25.0 | to=(64199.775, 41165.305) |  | 0.000s |
| 99 | 11:56:01.526 | xy 10-position pattern | PASS |  |  | xy: x readback 07 |  |  | expected=64199.775 actual=64180.0 tol=20.0 | 0.000s |
| 100 | 11:56:01.527 | xy 10-position pattern | PASS |  |  | xy: y readback 07 |  |  | expected=41165.305 actual=41160.0 tol=20.0 | 0.000s |
| 101 | 11:56:01.541 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 08 | index=8 count=10 from=(64220.0, 41180.0) to=(64212.275, 41156.224) radius_um=25.0 | to=(64212.275, 41156.224) | MoveXY -> (64212.275, 41156.224) um; [total=0.013s, att=1, conf=1, m=async] | 0.000s |
| 102 | 11:56:01.554 | xy 10-position pattern | PASS |  |  | xy: read 08 | index=8 count=10 from=(64220.0, 41180.0) to=(64212.275, 41156.224) radius_um=25.0 | to=(64212.275, 41156.224) |  | 0.000s |
| 103 | 11:56:01.555 | xy 10-position pattern | PASS |  |  | xy: x readback 08 |  |  | expected=64212.275 actual=64199.99999999999 tol=20.0 | 0.000s |
| 104 | 11:56:01.556 | xy 10-position pattern | PASS |  |  | xy: y readback 08 |  |  | expected=41156.224 actual=41140.0 tol=20.0 | 0.000s |
| 105 | 11:56:01.570 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 09 | index=9 count=10 from=(64220.0, 41180.0) to=(64227.725, 41156.224) radius_um=25.0 | to=(64227.725, 41156.224) | MoveXY -> (64227.725, 41156.224) um; [total=0.013s, att=1, conf=1, m=async] | 0.000s |
| 106 | 11:56:01.584 | xy 10-position pattern | PASS |  |  | xy: read 09 | index=9 count=10 from=(64220.0, 41180.0) to=(64227.725, 41156.224) radius_um=25.0 | to=(64227.725, 41156.224) |  | 0.015s |
| 107 | 11:56:01.585 | xy 10-position pattern | PASS |  |  | xy: x readback 09 |  |  | expected=64227.725 actual=64220.0 tol=20.0 | 0.000s |
| 108 | 11:56:01.586 | xy 10-position pattern | PASS |  |  | xy: y readback 09 |  |  | expected=41156.224 actual=41140.0 tol=20.0 | 0.000s |
| 109 | 11:56:01.600 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 10 | index=10 count=10 from=(64220.0, 41180.0) to=(64240.225, 41165.305) radius_um=25.0 | to=(64240.225, 41165.305) | MoveXY -> (64240.225, 41165.305) um; [total=0.014s, att=1, conf=1, m=async] | 0.016s |
| 110 | 11:56:01.614 | xy 10-position pattern | PASS |  |  | xy: read 10 | index=10 count=10 from=(64220.0, 41180.0) to=(64240.225, 41165.305) radius_um=25.0 | to=(64240.225, 41165.305) |  | 0.015s |
| 111 | 11:56:01.615 | xy 10-position pattern | PASS |  |  | xy: x readback 10 |  |  | expected=64240.225 actual=64240.00000000001 tol=20.0 | 0.000s |
| 112 | 11:56:01.616 | xy 10-position pattern | PASS |  |  | xy: y readback 10 |  |  | expected=41165.305 actual=41160.0 tol=20.0 | 0.000s |
| 113 | 11:56:01.631 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: restore | restore_to=(64220.0, 41180.0) positions=10 | restore_to=(64220.0, 41180.0) | MoveXY -> (64220.0, 41180.0) um; [total=0.013s, att=1, conf=1, m=async] | 0.016s |
| 114 | 11:56:01.693 | z-galvo round-trip | PASS |  |  | z: read start | job='Overview' |  |  | 0.063s |
| 115 | 11:56:01.714 | z-galvo round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | z: move alternate | job='Overview' from=0.0 to=2.0 | to=2.0 | Z -> 2.0 um (galvo); [total=0.019s, att=1, conf=1, m=async] | 0.031s |
| 116 | 11:56:01.729 | z-galvo round-trip | PASS |  |  | z: read alternate | job='Overview' |  |  | 0.015s |
| 117 | 11:56:01.730 | z-galvo round-trip | PASS |  |  | z: readback |  |  | expected=2.0 actual=2.0 tol=1.0 | 0.000s |
| 118 | 11:56:01.750 | z-galvo round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | z: restore | restore_to=0.0 | restore_to=0.0 | Z -> 0.0 um (galvo); [total=0.019s, att=1, conf=1, m=async] | 0.016s |
| 119 | 11:56:01.751 | setup | SKIP |  |  | phase: objective |  |  | use --allow-objective to enable | 0.000s |
| 120 | 11:56:01.752 | setup | SKIP |  |  | phase: acquire |  |  | use --allow-acquire to enable | 0.000s |

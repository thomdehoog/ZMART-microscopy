# Hardware validation run report

Every change this run attempted on the instrument is listed below, including failed attempts and restore/cleanup steps (see the *Mutates scope* column). Changes carry their success+CONFIRMED / success+UNCONFIRMED / FAILED result and attempt counts in the *Result* column.

## Run metadata

- **Validator**: `validate_hardware`
- **Arguments**: `--yes --allow-xy --allow-z --allow-missing-lasx --state-reader-mode api --output=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\hardware_validate_api.jsonl --report-dir=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report`
- **Backend**: live LAS X (simulator or scope)
- **Date**: 2026-07-06
- **Started / finished**: 11:55:51 / 11:55:55 (4.6s)
- **Host**: ZMB-LASX-PC (Windows-10-10.0.26200-SP0)
- **Python**: 3.11.15
- **Driver commit**: unknown on unknown
- **Driver log**: `\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\driver_log_20260706-115551.log` (full log-line capture)

## Summary

| Phase | Actions attempted | Passed | Warned | Failed | Skipped | Confirmed | Unconfirmed |
|---|---:|---:|---:|---:|---:|---:|---:|
| setup | 3 | 1 | 0 | 0 | 2 | 0 | 0 |
| read-only | 7 | 7 | 0 | 0 | 0 | 0 | 0 |
| job selection round-trip | 11 | 10 | 0 | 0 | 1 | 3 | 0 |
| settings round-trip | 47 | 46 | 0 | 0 | 1 | 33 | 0 |
| xy 10-position pattern | 42 | 42 | 0 | 0 | 0 | 11 | 0 |
| z-galvo round-trip | 5 | 5 | 0 | 0 | 0 | 2 | 0 |
| **total** | **115** | **111** | **0** | **0** | **4** | **49** | **0** |

## Timing overview

### Per phase

| Phase | Timed actions | Min | Median | Max |
|---|---:|---:|---:|---:|
| read-only | 4 | 0.015s | 0.016s | 0.031s |
| job selection round-trip | 7 | 0.015s | 0.032s | 0.828s |
| settings round-trip | 33 | 0.015s | 0.016s | 0.140s |
| xy 10-position pattern | 16 | 0.015s | 0.016s | 0.032s |
| z-galvo round-trip | 4 | 0.015s | 0.016s | 0.031s |

### Slowest actions

| Duration | Phase | Action | Status |
|---:|---|---|---|
| 0.828s | job selection round-trip | job selection: select job | PASS |
| 0.828s | job selection round-trip | job selection: select job | PASS |
| 0.562s | job selection round-trip | job selection: select job | PASS |
| 0.140s | settings round-trip | sequential_mode: write alternate | PASS |
| 0.032s | job selection round-trip | job selection: read selected job | PASS |
| 0.032s | settings round-trip | zoom: write current | PASS |
| 0.032s | settings round-trip | line_accumulation: write current | PASS |
| 0.032s | xy 10-position pattern | xy: move 02 | PASS |
| 0.031s | read-only | get_jobs | PASS |
| 0.031s | settings round-trip | sequential_mode: restore | PASS |

### Unconfirmed / failed changes

None -- every attempted change reported success and confirmed.

## Chronological detail (every attempted action)

| # | Time | Phase | Status | Result | Mutates scope | Action attempted | Args / target | Expected | Observed | Duration |
|---:|---|---|---|---|---|---|---|---|---|---:|
| 1 | 11:55:51.827 | setup | PASS |  |  | limits: connect handshake | limits_path='<machine-local snapshot>' |  |  | 0.000s |
| 2 | 11:55:51.830 | read-only | PASS |  |  | ping |  |  |  | 0.000s |
| 3 | 11:55:51.835 | read-only | PASS |  |  | get_scan_status |  |  |  | 0.000s |
| 4 | 11:55:51.867 | read-only | PASS |  |  | get_jobs |  |  |  | 0.031s |
| 5 | 11:55:51.882 | read-only | PASS |  |  | get_hardware_info |  |  |  | 0.016s |
| 6 | 11:55:51.895 | read-only | PASS |  |  | get_xy |  |  |  | 0.016s |
| 7 | 11:55:51.896 | read-only | PASS |  |  | job: resolved | job='Overview' |  |  | 0.000s |
| 8 | 11:55:51.913 | read-only | PASS |  |  | settings: read | job='Overview' |  |  | 0.015s |
| 9 | 11:55:51.927 | job selection round-trip | PASS |  |  | job selection: read jobs | mode='profile' |  |  | 0.016s |
| 10 | 11:55:52.527 | job selection round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | job selection: select job | index=0 count=3 job='AF Job' job_order=['AF Job', 'HiRes', 'Overview'] |  | SelectJob 'AF Job'; [total=0.545s, att=1, conf=1, m=async] | 0.562s |
| 11 | 11:55:52.563 | job selection round-trip | PASS |  |  | job selection: read selected job | index=0 count=3 job='AF Job' job_order=['AF Job', 'HiRes', 'Overview'] |  |  | 0.032s |
| 12 | 11:55:52.564 | job selection round-trip | PASS |  |  | job selection: confirmed AF Job |  |  | expected='AF Job' actual='AF Job' | 0.000s |
| 13 | 11:55:53.391 | job selection round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | job selection: select job | index=1 count=3 job='HiRes' job_order=['AF Job', 'HiRes', 'Overview'] |  | SelectJob 'HiRes'; [total=0.814s, att=1, conf=1, m=async] | 0.828s |
| 14 | 11:55:53.405 | job selection round-trip | PASS |  |  | job selection: read selected job | index=1 count=3 job='HiRes' job_order=['AF Job', 'HiRes', 'Overview'] |  |  | 0.015s |
| 15 | 11:55:53.406 | job selection round-trip | PASS |  |  | job selection: confirmed HiRes |  |  | expected='HiRes' actual='HiRes' | 0.000s |
| 16 | 11:55:54.237 | job selection round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | job selection: select job | index=2 count=3 job='Overview' job_order=['AF Job', 'HiRes', 'Overview'] |  | SelectJob 'Overview'; [total=0.818s, att=1, conf=1, m=async] | 0.828s |
| 17 | 11:55:54.251 | job selection round-trip | PASS |  |  | job selection: read selected job | index=2 count=3 job='Overview' job_order=['AF Job', 'HiRes', 'Overview'] |  |  | 0.016s |
| 18 | 11:55:54.252 | job selection round-trip | PASS |  |  | job selection: confirmed Overview |  |  | expected='Overview' actual='Overview' | 0.000s |
| 19 | 11:55:54.253 | job selection round-trip | SKIP |  |  | job selection: restore |  |  | 'Overview' already confirmed by round-trip | 0.000s |
| 20 | 11:55:54.310 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | zoom: write current | job='Overview' current=2.0 target=5.0 | target=5.0 | Zoom -> 2.0; [total=0.022s, att=1, conf=1, m=async] | 0.032s |
| 21 | 11:55:54.329 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | zoom: write alternate | job='Overview' current=2.0 target=5.0 | target=5.0 | Zoom -> 5.0; [total=0.017s, att=1, conf=1, m=async] | 0.015s |
| 22 | 11:55:54.343 | settings round-trip | PASS |  |  | zoom: readback |  |  | expected=5.0 actual=5.0000127156898895 tol=0.1 | 0.000s |
| 23 | 11:55:54.370 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | zoom: restore | job='Overview' restore_to=2.0 | restore_to=2.0 | Zoom -> 2.0; [total=0.026s, att=1, conf=1, m=async] | 0.031s |
| 24 | 11:55:54.415 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_speed: write current | job='Overview' current=400 target=600 | target=600 | ScanSpeed -> 400; [total=0.020s, att=1, conf=1, m=async] | 0.015s |
| 25 | 11:55:54.430 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_speed: write alternate | job='Overview' current=400 target=600 | target=600 | ScanSpeed -> 600; [total=0.014s, att=1, conf=1, m=async] | 0.000s |
| 26 | 11:55:54.446 | settings round-trip | PASS |  |  | scan_speed: readback |  |  | expected=600 actual=600 | 0.000s |
| 27 | 11:55:54.462 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_speed: restore | job='Overview' restore_to=400 | restore_to=400 | ScanSpeed -> 400; [total=0.015s, att=1, conf=1, m=async] | 0.015s |
| 28 | 11:55:54.498 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_resonant: write current | job='Overview' current=False target=True | target=True | Resonant -> False; [total=0.022s, att=1, conf=1, m=async] | 0.031s |
| 29 | 11:55:54.515 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_resonant: write alternate | job='Overview' current=False target=True | target=True | Resonant -> True; [total=0.015s, att=1, conf=1, m=async] | 0.016s |
| 30 | 11:55:54.528 | settings round-trip | PASS |  |  | scan_resonant: readback |  |  | expected=True actual=True | 0.000s |
| 31 | 11:55:54.545 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_resonant: restore | job='Overview' restore_to=False | restore_to=False | Resonant -> False; [total=0.015s, att=1, conf=1, m=async] | 0.016s |
| 32 | 11:55:54.559 | settings round-trip | PASS |  |  | scan_mode: read current | job='Overview' |  |  | 0.016s |
| 33 | 11:55:54.560 | settings round-trip | PASS |  |  | scan_mode: is xyz |  |  | expected='xyz' actual='xyz' | 0.000s |
| 34 | 11:55:54.597 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | sequential_mode: write current | job='Overview' current='Line' target='Frame' | target='Frame' | SequentialMode -> Line; [total=0.021s, att=1, conf=1, m=async] | 0.016s |
| 35 | 11:55:54.739 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | sequential_mode: write alternate | job='Overview' current='Line' target='Frame' | target='Frame' | SequentialMode -> Frame; [total=0.141s, att=1, conf=1, m=async] | 0.140s |
| 36 | 11:55:54.756 | settings round-trip | PASS |  |  | sequential_mode: readback |  |  | expected='Frame' actual='Frame' | 0.000s |
| 37 | 11:55:54.782 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | sequential_mode: restore | job='Overview' restore_to='Line' | restore_to='Line' | SequentialMode -> Line; [total=0.025s, att=1, conf=1, m=async] | 0.031s |
| 38 | 11:55:54.819 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_field_rotation: write current | job='Overview' current=0.0 target=5.0 | target=5.0 | Rotation -> 0.0; [total=0.017s, att=1, conf=1, m=async] | 0.016s |
| 39 | 11:55:54.839 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_field_rotation: write alternate | job='Overview' current=0.0 target=5.0 | target=5.0 | Rotation -> 5.0; [total=0.019s, att=1, conf=1, m=async] | 0.031s |
| 40 | 11:55:54.854 | settings round-trip | PASS |  |  | scan_field_rotation: readback |  |  | expected=5.0 actual=5.0 tol=0.5 | 0.000s |
| 41 | 11:55:54.870 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_field_rotation: restore | job='Overview' restore_to=0.0 | restore_to=0.0 | Rotation -> 0.0; [total=0.015s, att=1, conf=1, m=async] | 0.016s |
| 42 | 11:55:54.920 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | image_format: write current | job='Overview' current='512 x 512' target='1024 x 1024' | target='1024 x 1024' | Format -> 512 x 512; [total=0.020s, att=1, conf=1, m=async] | 0.031s |
| 43 | 11:55:54.936 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | image_format: write alternate | job='Overview' current='512 x 512' target='1024 x 1024' | target='1024 x 1024' | Format -> 1024 x 1024; [total=0.016s, att=1, conf=1, m=async] | 0.016s |
| 44 | 11:55:54.951 | settings round-trip | PASS |  |  | image_format: readback |  |  | expected='1024 x 1024' actual='1024 x 1024' | 0.000s |
| 45 | 11:55:54.967 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | image_format: restore | job='Overview' restore_to='512 x 512' | restore_to='512 x 512' | Format -> 512 x 512; [total=0.015s, att=1, conf=1, m=async] | 0.016s |
| 46 | 11:55:55.001 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_accumulation: write current | job='Overview' current=1 target=2 | target=2 | Setting[0].FrameAccumulation -> 1; [total=0.019s, att=1, conf=1, m=async] | 0.016s |
| 47 | 11:55:55.018 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_accumulation: write alternate | job='Overview' current=1 target=2 | target=2 | Setting[0].FrameAccumulation -> 2; [total=0.015s, att=1, conf=1, m=async] | 0.016s |
| 48 | 11:55:55.037 | settings round-trip | PASS |  |  | frame_accumulation: readback |  |  | expected=2 actual=2 | 0.000s |
| 49 | 11:55:55.054 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_accumulation: restore | job='Overview' restore_to=1 | restore_to=1 | Setting[0].FrameAccumulation -> 1; [total=0.015s, att=1, conf=1, m=async] | 0.016s |
| 50 | 11:55:55.102 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_average: write current | job='Overview' current=1 target=2 | target=2 | Setting[0].FrameAverage -> 1; [total=0.034s, att=1, conf=1, m=async] | 0.031s |
| 51 | 11:55:55.118 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_average: write alternate | job='Overview' current=1 target=2 | target=2 | Setting[0].FrameAverage -> 2; [total=0.015s, att=1, conf=1, m=async] | 0.015s |
| 52 | 11:55:55.133 | settings round-trip | PASS |  |  | frame_average: readback |  |  | expected=2 actual=2 | 0.000s |
| 53 | 11:55:55.150 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_average: restore | job='Overview' restore_to=1 | restore_to=1 | Setting[0].FrameAverage -> 1; [total=0.016s, att=1, conf=1, m=async] | 0.016s |
| 54 | 11:55:55.183 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_accumulation: write current | job='Overview' current=1 target=2 | target=2 | Setting[0].LineAccumulation -> 1; [total=0.018s, att=1, conf=1, m=async] | 0.032s |
| 55 | 11:55:55.199 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_accumulation: write alternate | job='Overview' current=1 target=2 | target=2 | Setting[0].LineAccumulation -> 2; [total=0.015s, att=1, conf=1, m=async] | 0.015s |
| 56 | 11:55:55.214 | settings round-trip | PASS |  |  | line_accumulation: readback |  |  | expected=2 actual=2 | 0.000s |
| 57 | 11:55:55.236 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_accumulation: restore | job='Overview' restore_to=1 | restore_to=1 | Setting[0].LineAccumulation -> 1; [total=0.021s, att=1, conf=1, m=async] | 0.015s |
| 58 | 11:55:55.270 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_average: write current | job='Overview' current=1 target=2 | target=2 | Setting[0].LineAverage -> 1; [total=0.018s, att=1, conf=1, m=async] | 0.016s |
| 59 | 11:55:55.285 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_average: write alternate | job='Overview' current=1 target=2 | target=2 | Setting[0].LineAverage -> 2; [total=0.015s, att=1, conf=1, m=async] | 0.015s |
| 60 | 11:55:55.310 | settings round-trip | PASS |  |  | line_average: readback |  |  | expected=2 actual=2 | 0.000s |
| 61 | 11:55:55.327 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_average: restore | job='Overview' restore_to=1 | restore_to=1 | Setting[0].LineAverage -> 1; [total=0.016s, att=1, conf=1, m=async] | 0.015s |
| 62 | 11:55:55.364 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | pinhole_airy: write current | job='Overview' current=1.0 target=1.2 | target=1.2 | Setting[0].PinholeAiry -> 1.0; [total=0.021s, att=1, conf=1, m=async] | 0.015s |
| 63 | 11:55:55.379 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | pinhole_airy: write alternate | job='Overview' current=1.0 target=1.2 | target=1.2 | Setting[0].PinholeAiry -> 1.2; [total=0.014s, att=1, conf=1, m=async] | 0.016s |
| 64 | 11:55:55.394 | settings round-trip | PASS |  |  | pinhole_airy: readback |  |  | expected=1.2 actual=1.2 tol=0.05 | 0.000s |
| 65 | 11:55:55.410 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | pinhole_airy: restore | job='Overview' restore_to=1.0 | restore_to=1.0 | Setting[0].PinholeAiry -> 1.0; [total=0.015s, att=1, conf=1, m=async] | 0.015s |
| 66 | 11:55:55.425 | settings round-trip | SKIP |  |  | detector_gain: round-trip |  |  | HyD 2 exposes no writable gain range; not mutating gain | 0.000s |
| 67 | 11:55:55.439 | xy 10-position pattern | PASS |  |  | xy: read start | mode='api' purpose='stage-safety-anchor' |  |  | 0.016s |
| 68 | 11:55:55.464 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 01 | index=1 count=10 from=(64220.0, 41180.0) to=(64245.0, 41180.0) radius_um=25.0 | to=(64245.0, 41180.0) | MoveXY -> (64245.0, 41180.0) um; [total=0.023s, att=1, conf=1, m=async] | 0.031s |
| 69 | 11:55:55.477 | xy 10-position pattern | PASS |  |  | xy: read 01 | index=1 count=10 from=(64220.0, 41180.0) to=(64245.0, 41180.0) radius_um=25.0 | to=(64245.0, 41180.0) |  | 0.000s |
| 70 | 11:55:55.478 | xy 10-position pattern | PASS |  |  | xy: x readback 01 |  |  | expected=64245.0 actual=64240.00000000001 tol=20.0 | 0.000s |
| 71 | 11:55:55.480 | xy 10-position pattern | PASS |  |  | xy: y readback 01 |  |  | expected=41180.0 actual=41180.0 tol=20.0 | 0.000s |
| 72 | 11:55:55.513 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 02 | index=2 count=10 from=(64220.0, 41180.0) to=(64240.225, 41194.695) radius_um=25.0 | to=(64240.225, 41194.695) | MoveXY -> (64240.225, 41194.695) um; [total=0.032s, att=1, conf=1, m=async] | 0.032s |
| 73 | 11:55:55.527 | xy 10-position pattern | PASS |  |  | xy: read 02 | index=2 count=10 from=(64220.0, 41180.0) to=(64240.225, 41194.695) radius_um=25.0 | to=(64240.225, 41194.695) |  | 0.015s |
| 74 | 11:55:55.528 | xy 10-position pattern | PASS |  |  | xy: x readback 02 |  |  | expected=64240.225 actual=64240.00000000001 tol=20.0 | 0.000s |
| 75 | 11:55:55.529 | xy 10-position pattern | PASS |  |  | xy: y readback 02 |  |  | expected=41194.695 actual=41180.0 tol=20.0 | 0.000s |
| 76 | 11:55:55.544 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 03 | index=3 count=10 from=(64220.0, 41180.0) to=(64227.725, 41203.776) radius_um=25.0 | to=(64227.725, 41203.776) | MoveXY -> (64227.725, 41203.776) um; [total=0.014s, att=1, conf=1, m=async] | 0.016s |
| 77 | 11:55:55.557 | xy 10-position pattern | PASS |  |  | xy: read 03 | index=3 count=10 from=(64220.0, 41180.0) to=(64227.725, 41203.776) radius_um=25.0 | to=(64227.725, 41203.776) |  | 0.016s |
| 78 | 11:55:55.558 | xy 10-position pattern | PASS |  |  | xy: x readback 03 |  |  | expected=64227.725 actual=64220.0 tol=20.0 | 0.000s |
| 79 | 11:55:55.559 | xy 10-position pattern | PASS |  |  | xy: y readback 03 |  |  | expected=41203.776 actual=41200.0 tol=20.0 | 0.000s |
| 80 | 11:55:55.573 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 04 | index=4 count=10 from=(64220.0, 41180.0) to=(64212.275, 41203.776) radius_um=25.0 | to=(64212.275, 41203.776) | MoveXY -> (64212.275, 41203.776) um; [total=0.013s, att=1, conf=1, m=async] | 0.015s |
| 81 | 11:55:55.587 | xy 10-position pattern | PASS |  |  | xy: read 04 | index=4 count=10 from=(64220.0, 41180.0) to=(64212.275, 41203.776) radius_um=25.0 | to=(64212.275, 41203.776) |  | 0.000s |
| 82 | 11:55:55.588 | xy 10-position pattern | PASS |  |  | xy: x readback 04 |  |  | expected=64212.275 actual=64199.99999999999 tol=20.0 | 0.000s |
| 83 | 11:55:55.589 | xy 10-position pattern | PASS |  |  | xy: y readback 04 |  |  | expected=41203.776 actual=41200.0 tol=20.0 | 0.000s |
| 84 | 11:55:55.606 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 05 | index=5 count=10 from=(64220.0, 41180.0) to=(64199.775, 41194.695) radius_um=25.0 | to=(64199.775, 41194.695) | MoveXY -> (64199.775, 41194.695) um; [total=0.013s, att=1, conf=1, m=async] | 0.000s |
| 85 | 11:55:55.623 | xy 10-position pattern | PASS |  |  | xy: read 05 | index=5 count=10 from=(64220.0, 41180.0) to=(64199.775, 41194.695) radius_um=25.0 | to=(64199.775, 41194.695) |  | 0.016s |
| 86 | 11:55:55.624 | xy 10-position pattern | PASS |  |  | xy: x readback 05 |  |  | expected=64199.775 actual=64180.0 tol=20.0 | 0.000s |
| 87 | 11:55:55.625 | xy 10-position pattern | PASS |  |  | xy: y readback 05 |  |  | expected=41194.695 actual=41180.0 tol=20.0 | 0.000s |
| 88 | 11:55:55.640 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 06 | index=6 count=10 from=(64220.0, 41180.0) to=(64195.0, 41180.0) radius_um=25.0 | to=(64195.0, 41180.0) | MoveXY -> (64195.0, 41180.0) um; [total=0.013s, att=1, conf=1, m=async] | 0.016s |
| 89 | 11:55:55.653 | xy 10-position pattern | PASS |  |  | xy: read 06 | index=6 count=10 from=(64220.0, 41180.0) to=(64195.0, 41180.0) radius_um=25.0 | to=(64195.0, 41180.0) |  | 0.015s |
| 90 | 11:55:55.654 | xy 10-position pattern | PASS |  |  | xy: x readback 06 |  |  | expected=64195.0 actual=64180.0 tol=20.0 | 0.000s |
| 91 | 11:55:55.655 | xy 10-position pattern | PASS |  |  | xy: y readback 06 |  |  | expected=41180.0 actual=41180.0 tol=20.0 | 0.000s |
| 92 | 11:55:55.671 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 07 | index=7 count=10 from=(64220.0, 41180.0) to=(64199.775, 41165.305) radius_um=25.0 | to=(64199.775, 41165.305) | MoveXY -> (64199.775, 41165.305) um; [total=0.014s, att=1, conf=1, m=async] | 0.016s |
| 93 | 11:55:55.683 | xy 10-position pattern | PASS |  |  | xy: read 07 | index=7 count=10 from=(64220.0, 41180.0) to=(64199.775, 41165.305) radius_um=25.0 | to=(64199.775, 41165.305) |  | 0.016s |
| 94 | 11:55:55.684 | xy 10-position pattern | PASS |  |  | xy: x readback 07 |  |  | expected=64199.775 actual=64180.0 tol=20.0 | 0.000s |
| 95 | 11:55:55.685 | xy 10-position pattern | PASS |  |  | xy: y readback 07 |  |  | expected=41165.305 actual=41160.0 tol=20.0 | 0.000s |
| 96 | 11:55:55.700 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 08 | index=8 count=10 from=(64220.0, 41180.0) to=(64212.275, 41156.224) radius_um=25.0 | to=(64212.275, 41156.224) | MoveXY -> (64212.275, 41156.224) um; [total=0.014s, att=1, conf=1, m=async] | 0.015s |
| 97 | 11:55:55.713 | xy 10-position pattern | PASS |  |  | xy: read 08 | index=8 count=10 from=(64220.0, 41180.0) to=(64212.275, 41156.224) radius_um=25.0 | to=(64212.275, 41156.224) |  | 0.016s |
| 98 | 11:55:55.714 | xy 10-position pattern | PASS |  |  | xy: x readback 08 |  |  | expected=64212.275 actual=64199.99999999999 tol=20.0 | 0.000s |
| 99 | 11:55:55.715 | xy 10-position pattern | PASS |  |  | xy: y readback 08 |  |  | expected=41156.224 actual=41140.0 tol=20.0 | 0.000s |
| 100 | 11:55:55.729 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 09 | index=9 count=10 from=(64220.0, 41180.0) to=(64227.725, 41156.224) radius_um=25.0 | to=(64227.725, 41156.224) | MoveXY -> (64227.725, 41156.224) um; [total=0.013s, att=1, conf=1, m=async] | 0.015s |
| 101 | 11:55:55.743 | xy 10-position pattern | PASS |  |  | xy: read 09 | index=9 count=10 from=(64220.0, 41180.0) to=(64227.725, 41156.224) radius_um=25.0 | to=(64227.725, 41156.224) |  | 0.000s |
| 102 | 11:55:55.744 | xy 10-position pattern | PASS |  |  | xy: x readback 09 |  |  | expected=64227.725 actual=64220.0 tol=20.0 | 0.000s |
| 103 | 11:55:55.745 | xy 10-position pattern | PASS |  |  | xy: y readback 09 |  |  | expected=41156.224 actual=41140.0 tol=20.0 | 0.000s |
| 104 | 11:55:55.759 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 10 | index=10 count=10 from=(64220.0, 41180.0) to=(64240.225, 41165.305) radius_um=25.0 | to=(64240.225, 41165.305) | MoveXY -> (64240.225, 41165.305) um; [total=0.014s, att=1, conf=1, m=async] | 0.000s |
| 105 | 11:55:55.772 | xy 10-position pattern | PASS |  |  | xy: read 10 | index=10 count=10 from=(64220.0, 41180.0) to=(64240.225, 41165.305) radius_um=25.0 | to=(64240.225, 41165.305) |  | 0.000s |
| 106 | 11:55:55.773 | xy 10-position pattern | PASS |  |  | xy: x readback 10 |  |  | expected=64240.225 actual=64240.00000000001 tol=20.0 | 0.000s |
| 107 | 11:55:55.774 | xy 10-position pattern | PASS |  |  | xy: y readback 10 |  |  | expected=41165.305 actual=41160.0 tol=20.0 | 0.000s |
| 108 | 11:55:55.788 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: restore | restore_to=(64220.0, 41180.0) positions=10 | restore_to=(64220.0, 41180.0) | MoveXY -> (64220.0, 41180.0) um; [total=0.014s, att=1, conf=1, m=async] | 0.015s |
| 109 | 11:55:55.803 | z-galvo round-trip | PASS |  |  | z: read start | job='Overview' |  |  | 0.016s |
| 110 | 11:55:55.826 | z-galvo round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | z: move alternate | job='Overview' from=0.0 to=2.0 | to=2.0 | Z -> 2.0 um (galvo); [total=0.020s, att=1, conf=1, m=async] | 0.031s |
| 111 | 11:55:55.840 | z-galvo round-trip | PASS |  |  | z: read alternate | job='Overview' |  |  | 0.016s |
| 112 | 11:55:55.841 | z-galvo round-trip | PASS |  |  | z: readback |  |  | expected=2.0 actual=2.0 tol=1.0 | 0.000s |
| 113 | 11:55:55.857 | z-galvo round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | z: restore | restore_to=0.0 | restore_to=0.0 | Z -> 0.0 um (galvo); [total=0.015s, att=1, conf=1, m=async] | 0.015s |
| 114 | 11:55:55.858 | setup | SKIP |  |  | phase: objective |  |  | use --allow-objective to enable | 0.000s |
| 115 | 11:55:55.859 | setup | SKIP |  |  | phase: acquire |  |  | use --allow-acquire to enable | 0.000s |

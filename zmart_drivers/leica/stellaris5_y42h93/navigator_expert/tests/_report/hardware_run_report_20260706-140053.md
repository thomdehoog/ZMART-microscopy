# Hardware validation run report

Every change this run attempted on the instrument is listed below, including failed attempts and restore/cleanup steps (see the *Mutates scope* column). Changes carry their success+CONFIRMED / success+UNCONFIRMED / FAILED result and attempt counts in the *Result* column.

## Run metadata

- **Validator**: `validate_hardware`
- **Arguments**: `--yes --allow-xy --allow-z --allow-missing-lasx --state-reader-mode api --output=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\hardware_validate_api.jsonl --report-dir=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report`
- **Backend**: live LAS X (simulator or scope)
- **Date**: 2026-07-06
- **Started / finished**: 14:00:53 / 14:01:00 (7.0s)
- **Host**: ZMB-LASX-PC (Windows-10-10.0.26200-SP0)
- **Python**: 3.11.15
- **Driver commit**: unknown on unknown
- **Driver log**: `\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\driver_log_20260706-140053.log` (full log-line capture)

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
| read-only | 3 | 0.015s | 0.031s | 0.032s |
| job selection round-trip | 6 | 0.016s | 0.406s | 0.922s |
| settings round-trip | 34 | 0.015s | 0.016s | 2.031s |
| xy 10-position pattern | 21 | 0.015s | 0.016s | 0.016s |
| z-galvo round-trip | 4 | 0.015s | 0.016s | 0.032s |

### Slowest actions

| Duration | Phase | Action | Status |
|---:|---|---|---|
| 2.031s | settings round-trip | zoom: write current | PASS |
| 0.922s | job selection round-trip | job selection: select job | PASS |
| 0.844s | job selection round-trip | job selection: select job | PASS |
| 0.765s | job selection round-trip | job selection: select job | PASS |
| 0.156s | settings round-trip | sequential_mode: write alternate | PASS |
| 0.094s | settings round-trip | image_format: write current | PASS |
| 0.046s | job selection round-trip | job selection: read selected job | PASS |
| 0.032s | read-only | settings: read | PASS |
| 0.032s | job selection round-trip | job selection: read selected job | PASS |
| 0.032s | settings round-trip | sequential_mode: restore | PASS |

### Unconfirmed / failed changes

None -- every attempted change reported success and confirmed.

## Chronological detail (every attempted action)

| # | Time | Phase | Status | Result | Mutates scope | Action attempted | Args / target | Expected | Observed | Duration |
|---:|---|---|---|---|---|---|---|---|---|---:|
| 1 | 14:00:53.977 | setup | PASS |  |  | limits: connect handshake | limits_path='<machine-local snapshot>' |  |  | 0.000s |
| 2 | 14:00:53.977 | read-only | PASS |  |  | ping |  |  |  | 0.000s |
| 3 | 14:00:53.977 | read-only | PASS |  |  | get_scan_status |  |  |  | 0.000s |
| 4 | 14:00:54.009 | read-only | PASS |  |  | get_jobs |  |  |  | 0.031s |
| 5 | 14:00:54.023 | read-only | PASS |  |  | get_hardware_info |  |  |  | 0.015s |
| 6 | 14:00:54.037 | read-only | PASS |  |  | get_xy |  |  |  | 0.000s |
| 7 | 14:00:54.037 | read-only | PASS |  |  | job: resolved | job='Overview' |  |  | 0.000s |
| 8 | 14:00:54.055 | read-only | PASS |  |  | settings: read | job='Overview' |  |  | 0.032s |
| 9 | 14:00:54.068 | job selection round-trip | PASS |  |  | job selection: read jobs | mode='profile' |  |  | 0.000s |
| 10 | 14:00:54.876 | job selection round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | job selection: select job | index=0 count=3 job='AF Job' job_order=['AF Job', 'HiRes', 'Overview'] |  | SelectJob 'AF Job'; [total=0.752s, att=1, conf=1, m=async] | 0.765s |
| 11 | 14:00:54.891 | job selection round-trip | PASS |  |  | job selection: read selected job | index=0 count=3 job='AF Job' job_order=['AF Job', 'HiRes', 'Overview'] |  |  | 0.016s |
| 12 | 14:00:54.891 | job selection round-trip | PASS |  |  | job selection: confirmed AF Job |  |  | expected='AF Job' actual='AF Job' | 0.000s |
| 13 | 14:00:55.732 | job selection round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | job selection: select job | index=1 count=3 job='HiRes' job_order=['AF Job', 'HiRes', 'Overview'] |  | SelectJob 'HiRes'; [total=0.807s, att=1, conf=1, m=async] | 0.844s |
| 14 | 14:00:55.787 | job selection round-trip | PASS |  |  | job selection: read selected job | index=1 count=3 job='HiRes' job_order=['AF Job', 'HiRes', 'Overview'] |  |  | 0.046s |
| 15 | 14:00:55.787 | job selection round-trip | PASS |  |  | job selection: confirmed HiRes |  |  | expected='HiRes' actual='HiRes' | 0.000s |
| 16 | 14:00:56.705 | job selection round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | job selection: select job | index=2 count=3 job='Overview' job_order=['AF Job', 'HiRes', 'Overview'] |  | SelectJob 'Overview'; [total=0.905s, att=1, conf=1, m=async] | 0.922s |
| 17 | 14:00:56.730 | job selection round-trip | PASS |  |  | job selection: read selected job | index=2 count=3 job='Overview' job_order=['AF Job', 'HiRes', 'Overview'] |  |  | 0.032s |
| 18 | 14:00:56.730 | job selection round-trip | PASS |  |  | job selection: confirmed Overview |  |  | expected='Overview' actual='Overview' | 0.000s |
| 19 | 14:00:56.733 | job selection round-trip | SKIP |  |  | job selection: restore |  |  | 'Overview' already confirmed by round-trip | 0.000s |
| 20 | 14:00:58.832 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | zoom: write current | job='Overview' current=2.0 target=5.0 | target=5.0 | Zoom -> 2.0; [total=2.041s, att=1, conf=1, m=async] | 2.031s |
| 21 | 14:00:58.848 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | zoom: write alternate | job='Overview' current=2.0 target=5.0 | target=5.0 | Zoom -> 5.0; [total=0.015s, att=1, conf=1, m=async] | 0.016s |
| 22 | 14:00:58.864 | settings round-trip | PASS |  |  | zoom: readback |  |  | expected=5.0 actual=5.0000127156898895 tol=0.1 | 0.000s |
| 23 | 14:00:58.881 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | zoom: restore | job='Overview' restore_to=2.0 | restore_to=2.0 | Zoom -> 2.0; [total=0.016s, att=1, conf=1, m=async] | 0.015s |
| 24 | 14:00:58.915 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_speed: write current | job='Overview' current=400 target=600 | target=600 | ScanSpeed -> 400; [total=0.018s, att=1, conf=1, m=async] | 0.015s |
| 25 | 14:00:58.931 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_speed: write alternate | job='Overview' current=400 target=600 | target=600 | ScanSpeed -> 600; [total=0.015s, att=1, conf=1, m=async] | 0.016s |
| 26 | 14:00:58.944 | settings round-trip | PASS |  |  | scan_speed: readback |  |  | expected=600 actual=600 | 0.000s |
| 27 | 14:00:58.961 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_speed: restore | job='Overview' restore_to=400 | restore_to=400 | ScanSpeed -> 400; [total=0.015s, att=1, conf=1, m=async] | 0.015s |
| 28 | 14:00:59.005 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_resonant: write current | job='Overview' current=False target=True | target=True | Resonant -> False; [total=0.031s, att=1, conf=1, m=async] | 0.031s |
| 29 | 14:00:59.022 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_resonant: write alternate | job='Overview' current=False target=True | target=True | Resonant -> True; [total=0.015s, att=1, conf=1, m=async] | 0.016s |
| 30 | 14:00:59.041 | settings round-trip | PASS |  |  | scan_resonant: readback |  |  | expected=True actual=True | 0.000s |
| 31 | 14:00:59.057 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_resonant: restore | job='Overview' restore_to=False | restore_to=False | Resonant -> False; [total=0.016s, att=1, conf=1, m=async] | 0.016s |
| 32 | 14:00:59.073 | settings round-trip | PASS |  |  | scan_mode: read current | job='Overview' |  |  | 0.015s |
| 33 | 14:00:59.073 | settings round-trip | PASS |  |  | scan_mode: is xyz |  |  | expected='xyz' actual='xyz' | 0.000s |
| 34 | 14:00:59.107 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | sequential_mode: write current | job='Overview' current='Line' target='Frame' | target='Frame' | SequentialMode -> Line; [total=0.020s, att=1, conf=1, m=async] | 0.016s |
| 35 | 14:00:59.264 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | sequential_mode: write alternate | job='Overview' current='Line' target='Frame' | target='Frame' | SequentialMode -> Frame; [total=0.153s, att=1, conf=1, m=async] | 0.156s |
| 36 | 14:00:59.287 | settings round-trip | PASS |  |  | sequential_mode: readback |  |  | expected='Frame' actual='Frame' | 0.000s |
| 37 | 14:00:59.318 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | sequential_mode: restore | job='Overview' restore_to='Line' | restore_to='Line' | SequentialMode -> Line; [total=0.028s, att=1, conf=1, m=async] | 0.032s |
| 38 | 14:00:59.359 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_field_rotation: write current | job='Overview' current=5.0 target=0.0 | target=0.0 | Rotation -> 5.0; [total=0.029s, att=1, conf=1, m=async] | 0.032s |
| 39 | 14:00:59.376 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_field_rotation: write alternate | job='Overview' current=5.0 target=0.0 | target=0.0 | Rotation -> 0.0; [total=0.015s, att=1, conf=1, m=async] | 0.015s |
| 40 | 14:00:59.392 | settings round-trip | PASS |  |  | scan_field_rotation: readback |  |  | expected=0.0 actual=0.0 tol=0.5 | 0.000s |
| 41 | 14:00:59.408 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_field_rotation: restore | job='Overview' restore_to=5.0 | restore_to=5.0 | Rotation -> 5.0; [total=0.016s, att=1, conf=1, m=async] | 0.015s |
| 42 | 14:00:59.509 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | image_format: write current | job='Overview' current='512 x 512' target='1024 x 1024' | target='1024 x 1024' | Format -> 512 x 512; [total=0.086s, att=1, conf=1, m=async] | 0.094s |
| 43 | 14:00:59.527 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | image_format: write alternate | job='Overview' current='512 x 512' target='1024 x 1024' | target='1024 x 1024' | Format -> 1024 x 1024; [total=0.016s, att=1, conf=1, m=async] | 0.015s |
| 44 | 14:00:59.551 | settings round-trip | PASS |  |  | image_format: readback |  |  | expected='1024 x 1024' actual='1024 x 1024' | 0.000s |
| 45 | 14:00:59.567 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | image_format: restore | job='Overview' restore_to='512 x 512' | restore_to='512 x 512' | Format -> 512 x 512; [total=0.015s, att=1, conf=1, m=async] | 0.016s |
| 46 | 14:00:59.614 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_accumulation: write current | job='Overview' current=1 target=2 | target=2 | Setting[0].FrameAccumulation -> 1; [total=0.022s, att=1, conf=1, m=async] | 0.016s |
| 47 | 14:00:59.631 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_accumulation: write alternate | job='Overview' current=1 target=2 | target=2 | Setting[0].FrameAccumulation -> 2; [total=0.016s, att=1, conf=1, m=async] | 0.015s |
| 48 | 14:00:59.646 | settings round-trip | PASS |  |  | frame_accumulation: readback |  |  | expected=2 actual=2 | 0.000s |
| 49 | 14:00:59.661 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_accumulation: restore | job='Overview' restore_to=1 | restore_to=1 | Setting[0].FrameAccumulation -> 1; [total=0.016s, att=1, conf=1, m=async] | 0.015s |
| 50 | 14:00:59.704 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_average: write current | job='Overview' current=1 target=2 | target=2 | Setting[0].FrameAverage -> 1; [total=0.028s, att=1, conf=1, m=async] | 0.031s |
| 51 | 14:00:59.720 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_average: write alternate | job='Overview' current=1 target=2 | target=2 | Setting[0].FrameAverage -> 2; [total=0.015s, att=1, conf=1, m=async] | 0.016s |
| 52 | 14:00:59.736 | settings round-trip | PASS |  |  | frame_average: readback |  |  | expected=2 actual=2 | 0.000s |
| 53 | 14:00:59.754 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_average: restore | job='Overview' restore_to=1 | restore_to=1 | Setting[0].FrameAverage -> 1; [total=0.018s, att=1, conf=1, m=async] | 0.015s |
| 54 | 14:00:59.787 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_accumulation: write current | job='Overview' current=1 target=2 | target=2 | Setting[0].LineAccumulation -> 1; [total=0.018s, att=1, conf=1, m=async] | 0.015s |
| 55 | 14:00:59.806 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_accumulation: write alternate | job='Overview' current=1 target=2 | target=2 | Setting[0].LineAccumulation -> 2; [total=0.016s, att=1, conf=1, m=async] | 0.032s |
| 56 | 14:00:59.819 | settings round-trip | PASS |  |  | line_accumulation: readback |  |  | expected=2 actual=2 | 0.000s |
| 57 | 14:00:59.836 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_accumulation: restore | job='Overview' restore_to=1 | restore_to=1 | Setting[0].LineAccumulation -> 1; [total=0.016s, att=1, conf=1, m=async] | 0.031s |
| 58 | 14:00:59.875 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_average: write current | job='Overview' current=1 target=2 | target=2 | Setting[0].LineAverage -> 1; [total=0.019s, att=1, conf=1, m=async] | 0.015s |
| 59 | 14:00:59.889 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_average: write alternate | job='Overview' current=1 target=2 | target=2 | Setting[0].LineAverage -> 2; [total=0.015s, att=1, conf=1, m=async] | 0.016s |
| 60 | 14:00:59.904 | settings round-trip | PASS |  |  | line_average: readback |  |  | expected=2 actual=2 | 0.000s |
| 61 | 14:00:59.926 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_average: restore | job='Overview' restore_to=1 | restore_to=1 | Setting[0].LineAverage -> 1; [total=0.020s, att=1, conf=1, m=async] | 0.016s |
| 62 | 14:00:59.959 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | pinhole_airy: write current | job='Overview' current=1.0 target=1.2 | target=1.2 | Setting[0].PinholeAiry -> 1.0; [total=0.018s, att=1, conf=1, m=async] | 0.015s |
| 63 | 14:00:59.975 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | pinhole_airy: write alternate | job='Overview' current=1.0 target=1.2 | target=1.2 | Setting[0].PinholeAiry -> 1.2; [total=0.015s, att=1, conf=1, m=async] | 0.016s |
| 64 | 14:00:59.992 | settings round-trip | PASS |  |  | pinhole_airy: readback |  |  | expected=1.2 actual=1.2 tol=0.05 | 0.000s |
| 65 | 14:01:00.009 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | pinhole_airy: restore | job='Overview' restore_to=1.0 | restore_to=1.0 | Setting[0].PinholeAiry -> 1.0; [total=0.018s, att=1, conf=1, m=async] | 0.016s |
| 66 | 14:01:00.024 | settings round-trip | SKIP |  |  | detector_gain: round-trip |  |  | HyD 2 exposes no writable gain range; not mutating gain | 0.000s |
| 67 | 14:01:00.039 | xy 10-position pattern | PASS |  |  | xy: read start | mode='api' purpose='stage-safety-anchor' |  |  | 0.000s |
| 68 | 14:01:00.063 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 01 | index=1 count=10 from=(64220.0, 41180.0) to=(64245.0, 41180.0) radius_um=25.0 | to=(64245.0, 41180.0) | MoveXY -> (64245.0, 41180.0) um; [total=0.023s, att=1, conf=1, m=async] | 0.016s |
| 69 | 14:01:00.082 | xy 10-position pattern | PASS |  |  | xy: read 01 | index=1 count=10 from=(64220.0, 41180.0) to=(64245.0, 41180.0) radius_um=25.0 | to=(64245.0, 41180.0) |  | 0.015s |
| 70 | 14:01:00.082 | xy 10-position pattern | PASS |  |  | xy: x readback 01 |  |  | expected=64245.0 actual=64240.00000000001 tol=20.0 | 0.000s |
| 71 | 14:01:00.082 | xy 10-position pattern | PASS |  |  | xy: y readback 01 |  |  | expected=41180.0 actual=41180.0 tol=20.0 | 0.000s |
| 72 | 14:01:00.099 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 02 | index=2 count=10 from=(64220.0, 41180.0) to=(64240.225, 41194.695) radius_um=25.0 | to=(64240.225, 41194.695) | MoveXY -> (64240.225, 41194.695) um; [total=0.015s, att=1, conf=1, m=async] | 0.016s |
| 73 | 14:01:00.112 | xy 10-position pattern | PASS |  |  | xy: read 02 | index=2 count=10 from=(64220.0, 41180.0) to=(64240.225, 41194.695) radius_um=25.0 | to=(64240.225, 41194.695) |  | 0.016s |
| 74 | 14:01:00.112 | xy 10-position pattern | PASS |  |  | xy: x readback 02 |  |  | expected=64240.225 actual=64240.00000000001 tol=20.0 | 0.000s |
| 75 | 14:01:00.112 | xy 10-position pattern | PASS |  |  | xy: y readback 02 |  |  | expected=41194.695 actual=41180.0 tol=20.0 | 0.000s |
| 76 | 14:01:00.130 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 03 | index=3 count=10 from=(64220.0, 41180.0) to=(64227.725, 41203.776) radius_um=25.0 | to=(64227.725, 41203.776) | MoveXY -> (64227.725, 41203.776) um; [total=0.014s, att=1, conf=1, m=async] | 0.015s |
| 77 | 14:01:00.142 | xy 10-position pattern | PASS |  |  | xy: read 03 | index=3 count=10 from=(64220.0, 41180.0) to=(64227.725, 41203.776) radius_um=25.0 | to=(64227.725, 41203.776) |  | 0.016s |
| 78 | 14:01:00.142 | xy 10-position pattern | PASS |  |  | xy: x readback 03 |  |  | expected=64227.725 actual=64220.0 tol=20.0 | 0.000s |
| 79 | 14:01:00.142 | xy 10-position pattern | PASS |  |  | xy: y readback 03 |  |  | expected=41203.776 actual=41200.0 tol=20.0 | 0.000s |
| 80 | 14:01:00.157 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 04 | index=4 count=10 from=(64220.0, 41180.0) to=(64212.275, 41203.776) radius_um=25.0 | to=(64212.275, 41203.776) | MoveXY -> (64212.275, 41203.776) um; [total=0.013s, att=1, conf=1, m=async] | 0.015s |
| 81 | 14:01:00.171 | xy 10-position pattern | PASS |  |  | xy: read 04 | index=4 count=10 from=(64220.0, 41180.0) to=(64212.275, 41203.776) radius_um=25.0 | to=(64212.275, 41203.776) |  | 0.016s |
| 82 | 14:01:00.171 | xy 10-position pattern | PASS |  |  | xy: x readback 04 |  |  | expected=64212.275 actual=64199.99999999999 tol=20.0 | 0.000s |
| 83 | 14:01:00.171 | xy 10-position pattern | PASS |  |  | xy: y readback 04 |  |  | expected=41203.776 actual=41200.0 tol=20.0 | 0.000s |
| 84 | 14:01:00.187 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 05 | index=5 count=10 from=(64220.0, 41180.0) to=(64199.775, 41194.695) radius_um=25.0 | to=(64199.775, 41194.695) | MoveXY -> (64199.775, 41194.695) um; [total=0.014s, att=1, conf=1, m=async] | 0.016s |
| 85 | 14:01:00.202 | xy 10-position pattern | PASS |  |  | xy: read 05 | index=5 count=10 from=(64220.0, 41180.0) to=(64199.775, 41194.695) radius_um=25.0 | to=(64199.775, 41194.695) |  | 0.015s |
| 86 | 14:01:00.203 | xy 10-position pattern | PASS |  |  | xy: x readback 05 |  |  | expected=64199.775 actual=64180.0 tol=20.0 | 0.000s |
| 87 | 14:01:00.204 | xy 10-position pattern | PASS |  |  | xy: y readback 05 |  |  | expected=41194.695 actual=41180.0 tol=20.0 | 0.000s |
| 88 | 14:01:00.221 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 06 | index=6 count=10 from=(64220.0, 41180.0) to=(64195.0, 41180.0) radius_um=25.0 | to=(64195.0, 41180.0) | MoveXY -> (64195.0, 41180.0) um; [total=0.018s, att=1, conf=1, m=async] | 0.016s |
| 89 | 14:01:00.234 | xy 10-position pattern | PASS |  |  | xy: read 06 | index=6 count=10 from=(64220.0, 41180.0) to=(64195.0, 41180.0) radius_um=25.0 | to=(64195.0, 41180.0) |  | 0.016s |
| 90 | 14:01:00.236 | xy 10-position pattern | PASS |  |  | xy: x readback 06 |  |  | expected=64195.0 actual=64180.0 tol=20.0 | 0.000s |
| 91 | 14:01:00.236 | xy 10-position pattern | PASS |  |  | xy: y readback 06 |  |  | expected=41180.0 actual=41180.0 tol=20.0 | 0.000s |
| 92 | 14:01:00.253 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 07 | index=7 count=10 from=(64220.0, 41180.0) to=(64199.775, 41165.305) radius_um=25.0 | to=(64199.775, 41165.305) | MoveXY -> (64199.775, 41165.305) um; [total=0.014s, att=1, conf=1, m=async] | 0.015s |
| 93 | 14:01:00.264 | xy 10-position pattern | PASS |  |  | xy: read 07 | index=7 count=10 from=(64220.0, 41180.0) to=(64199.775, 41165.305) radius_um=25.0 | to=(64199.775, 41165.305) |  | 0.016s |
| 94 | 14:01:00.264 | xy 10-position pattern | PASS |  |  | xy: x readback 07 |  |  | expected=64199.775 actual=64180.0 tol=20.0 | 0.000s |
| 95 | 14:01:00.264 | xy 10-position pattern | PASS |  |  | xy: y readback 07 |  |  | expected=41165.305 actual=41160.0 tol=20.0 | 0.000s |
| 96 | 14:01:00.280 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 08 | index=8 count=10 from=(64220.0, 41180.0) to=(64212.275, 41156.224) radius_um=25.0 | to=(64212.275, 41156.224) | MoveXY -> (64212.275, 41156.224) um; [total=0.014s, att=1, conf=1, m=async] | 0.015s |
| 97 | 14:01:00.294 | xy 10-position pattern | PASS |  |  | xy: read 08 | index=8 count=10 from=(64220.0, 41180.0) to=(64212.275, 41156.224) radius_um=25.0 | to=(64212.275, 41156.224) |  | 0.016s |
| 98 | 14:01:00.294 | xy 10-position pattern | PASS |  |  | xy: x readback 08 |  |  | expected=64212.275 actual=64199.99999999999 tol=20.0 | 0.000s |
| 99 | 14:01:00.294 | xy 10-position pattern | PASS |  |  | xy: y readback 08 |  |  | expected=41156.224 actual=41140.0 tol=20.0 | 0.000s |
| 100 | 14:01:00.311 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 09 | index=9 count=10 from=(64220.0, 41180.0) to=(64227.725, 41156.224) radius_um=25.0 | to=(64227.725, 41156.224) | MoveXY -> (64227.725, 41156.224) um; [total=0.014s, att=1, conf=1, m=async] | 0.016s |
| 101 | 14:01:00.326 | xy 10-position pattern | PASS |  |  | xy: read 09 | index=9 count=10 from=(64220.0, 41180.0) to=(64227.725, 41156.224) radius_um=25.0 | to=(64227.725, 41156.224) |  | 0.015s |
| 102 | 14:01:00.327 | xy 10-position pattern | PASS |  |  | xy: x readback 09 |  |  | expected=64227.725 actual=64220.0 tol=20.0 | 0.000s |
| 103 | 14:01:00.328 | xy 10-position pattern | PASS |  |  | xy: y readback 09 |  |  | expected=41156.224 actual=41140.0 tol=20.0 | 0.000s |
| 104 | 14:01:00.346 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 10 | index=10 count=10 from=(64220.0, 41180.0) to=(64240.225, 41165.305) radius_um=25.0 | to=(64240.225, 41165.305) | MoveXY -> (64240.225, 41165.305) um; [total=0.018s, att=1, conf=1, m=async] | 0.016s |
| 105 | 14:01:00.361 | xy 10-position pattern | PASS |  |  | xy: read 10 | index=10 count=10 from=(64220.0, 41180.0) to=(64240.225, 41165.305) radius_um=25.0 | to=(64240.225, 41165.305) |  | 0.016s |
| 106 | 14:01:00.362 | xy 10-position pattern | PASS |  |  | xy: x readback 10 |  |  | expected=64240.225 actual=64240.00000000001 tol=20.0 | 0.000s |
| 107 | 14:01:00.363 | xy 10-position pattern | PASS |  |  | xy: y readback 10 |  |  | expected=41165.305 actual=41160.0 tol=20.0 | 0.000s |
| 108 | 14:01:00.375 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: restore | restore_to=(64220.0, 41180.0) positions=10 | restore_to=(64220.0, 41180.0) | MoveXY -> (64220.0, 41180.0) um; [total=0.013s, att=1, conf=1, m=async] | 0.015s |
| 109 | 14:01:00.390 | z-galvo round-trip | PASS |  |  | z: read start | job='Overview' |  |  | 0.016s |
| 110 | 14:01:00.413 | z-galvo round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | z: move alternate | job='Overview' from=-0.5 to=1.5 | to=1.5 | Z -> 1.5 um (galvo); [total=0.019s, att=1, conf=1, m=async] | 0.015s |
| 111 | 14:01:00.430 | z-galvo round-trip | PASS |  |  | z: read alternate | job='Overview' |  |  | 0.032s |
| 112 | 14:01:00.430 | z-galvo round-trip | PASS |  |  | z: readback |  |  | expected=1.5 actual=1.5 tol=1.0 | 0.000s |
| 113 | 14:01:00.448 | z-galvo round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | z: restore | restore_to=-0.5 | restore_to=-0.5 | Z -> -0.5 um (galvo); [total=0.016s, att=1, conf=1, m=async] | 0.015s |
| 114 | 14:01:00.448 | setup | SKIP |  |  | phase: objective |  |  | use --allow-objective to enable | 0.000s |
| 115 | 14:01:00.448 | setup | SKIP |  |  | phase: acquire |  |  | use --allow-acquire to enable | 0.000s |

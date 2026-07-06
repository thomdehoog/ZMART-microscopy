# Hardware validation run report

Every change this run attempted on the instrument is listed below, including failed attempts and restore/cleanup steps (see the *Mutates scope* column). Changes carry their success+CONFIRMED / success+UNCONFIRMED / FAILED result and attempt counts in the *Result* column.

## Run metadata

- **Validator**: `validate_hardware`
- **Arguments**: `--yes --allow-xy --allow-z --allow-missing-lasx --state-reader-mode log --output=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\hardware_validate_log.jsonl --report-dir=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report`
- **Backend**: live LAS X (simulator or scope)
- **Date**: 2026-07-06
- **Started / finished**: 14:18:44 / 14:18:49 (5.3s)
- **Host**: ZMB-LASX-PC (Windows-10-10.0.26200-SP0)
- **Python**: 3.11.15
- **Driver commit**: unknown on unknown
- **Driver log**: `\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\driver_log_20260706-141844.log` (full log-line capture)

## Summary

| Phase | Actions attempted | Passed | Warned | Failed | Skipped | Confirmed | Unconfirmed |
|---|---:|---:|---:|---:|---:|---:|---:|
| setup | 3 | 1 | 0 | 0 | 2 | 0 | 0 |
| read-only | 9 | 8 | 0 | 0 | 1 | 0 | 0 |
| job selection round-trip | 14 | 13 | 0 | 0 | 1 | 3 | 0 |
| settings round-trip | 47 | 46 | 0 | 0 | 1 | 33 | 0 |
| xy 10-position pattern | 42 | 42 | 0 | 0 | 0 | 11 | 0 |
| z-galvo round-trip | 5 | 5 | 0 | 0 | 0 | 2 | 0 |
| **total** | **120** | **115** | **0** | **0** | **5** | **49** | **0** |

## Timing overview

### Per phase

| Phase | Timed actions | Min | Median | Max |
|---|---:|---:|---:|---:|
| read-only | 5 | 0.032s | 0.062s | 0.063s |
| job selection round-trip | 10 | 0.016s | 0.071s | 0.781s |
| settings round-trip | 34 | 0.015s | 0.016s | 0.141s |
| xy 10-position pattern | 21 | 0.015s | 0.016s | 0.032s |
| z-galvo round-trip | 4 | 0.015s | 0.024s | 0.062s |

### Slowest actions

| Duration | Phase | Action | Status |
|---:|---|---|---|
| 0.781s | job selection round-trip | job selection: select job | PASS |
| 0.781s | job selection round-trip | job selection: select job | PASS |
| 0.625s | job selection round-trip | job selection: select job | PASS |
| 0.157s | job selection round-trip | job selection: read selected job | PASS |
| 0.141s | settings round-trip | sequential_mode: write alternate | PASS |
| 0.078s | job selection round-trip | job selection: read selected job | PASS |
| 0.063s | read-only | get_hardware_info | PASS |
| 0.063s | job selection round-trip | job selection: log poll confirmed HiRes | PASS |
| 0.062s | read-only | get_scan_status | PASS |
| 0.062s | job selection round-trip | job selection: log poll confirmed Overview | PASS |

### Unconfirmed / failed changes

None -- every attempted change reported success and confirmed.

## Chronological detail (every attempted action)

| # | Time | Phase | Status | Result | Mutates scope | Action attempted | Args / target | Expected | Observed | Duration |
|---:|---|---|---|---|---|---|---|---|---|---:|
| 1 | 14:18:45.124 | setup | PASS |  |  | limits: connect handshake | limits_path='<machine-local snapshot>' |  |  | 0.000s |
| 2 | 14:18:45.124 | read-only | PASS |  |  | ping |  |  |  | 0.000s |
| 3 | 14:18:45.188 | read-only | PASS |  |  | get_scan_status |  |  |  | 0.062s |
| 4 | 14:18:45.204 | read-only | PASS |  |  | get_jobs |  |  |  | 0.000s |
| 5 | 14:18:45.260 | read-only | PASS |  |  | get_hardware_info |  |  |  | 0.063s |
| 6 | 14:18:45.316 | read-only | PASS |  |  | get_xy |  |  |  | 0.046s |
| 7 | 14:18:45.316 | read-only | SKIP |  |  | job: resolve |  |  | job list is API-only (no log leg); enumerating via API | 0.000s |
| 8 | 14:18:45.347 | read-only | PASS |  |  | job: resolve api control for log experiment | purpose='drive log selected-job poll' |  |  | 0.032s |
| 9 | 14:18:45.347 | read-only | PASS |  |  | job: resolved | job='Overview' |  |  | 0.000s |
| 10 | 14:18:45.412 | read-only | PASS |  |  | settings: read | job='Overview' |  |  | 0.062s |
| 11 | 14:18:45.426 | job selection round-trip | PASS |  |  | job selection: read jobs | mode='api' |  |  | 0.016s |
| 12 | 14:18:46.093 | job selection round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | job selection: select job | index=0 count=3 job='AF Job' job_order=['AF Job', 'HiRes', 'Overview'] |  | SelectJob 'AF Job'; [total=0.560s, att=1, conf=1, m=async] | 0.625s |
| 13 | 14:18:46.156 | job selection round-trip | PASS |  |  | job selection: log poll confirmed AF Job | index=0 count=3 job='AF Job' job_order=['AF Job', 'HiRes', 'Overview'] log_poll={'success': True, 'value': 'AF Job', 'matched_at': 1783340325.958, 'attempts': … |  | matched; last_reason=matched; value='AF Job'; log_event_delta=0.486s; api_select_elapsed=0.560s; attempts=1 | 0.062s |
| 14 | 14:18:46.172 | job selection round-trip | PASS |  |  | job selection: read selected job | index=0 count=3 job='AF Job' job_order=['AF Job', 'HiRes', 'Overview'] |  |  | 0.016s |
| 15 | 14:18:46.172 | job selection round-trip | PASS |  |  | job selection: confirmed AF Job |  |  | expected='AF Job' actual='AF Job' | 0.000s |
| 16 | 14:18:46.951 | job selection round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | job selection: select job | index=1 count=3 job='HiRes' job_order=['AF Job', 'HiRes', 'Overview'] |  | SelectJob 'HiRes'; [total=0.716s, att=1, conf=1, m=async] | 0.781s |
| 17 | 14:18:47.014 | job selection round-trip | PASS |  |  | job selection: log poll confirmed HiRes | index=1 count=3 job='HiRes' job_order=['AF Job', 'HiRes', 'Overview'] log_poll={'success': True, 'value': 'HiRes', 'matched_at': 1783340326.914, 'attempts': 1,… |  | matched; last_reason=matched; value='HiRes'; log_event_delta=0.742s; api_select_elapsed=0.716s; attempts=1 | 0.063s |
| 18 | 14:18:47.100 | job selection round-trip | PASS |  |  | job selection: read selected job | index=1 count=3 job='HiRes' job_order=['AF Job', 'HiRes', 'Overview'] |  |  | 0.078s |
| 19 | 14:18:47.100 | job selection round-trip | PASS |  |  | job selection: confirmed HiRes |  |  | expected='HiRes' actual='HiRes' | 0.000s |
| 20 | 14:18:47.878 | job selection round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | job selection: select job | index=2 count=3 job='Overview' job_order=['AF Job', 'HiRes', 'Overview'] |  | SelectJob 'Overview'; [total=0.714s, att=1, conf=1, m=async] | 0.781s |
| 21 | 14:18:47.940 | job selection round-trip | PASS |  |  | job selection: log poll confirmed Overview | index=2 count=3 job='Overview' job_order=['AF Job', 'HiRes', 'Overview'] log_poll={'success': True, 'value': 'Overview', 'matched_at': 1783340327.819, 'attempt… |  | matched; last_reason=matched; value='Overview'; log_event_delta=0.719s; api_select_elapsed=0.714s; attempts=1 | 0.062s |
| 22 | 14:18:48.099 | job selection round-trip | PASS |  |  | job selection: read selected job | index=2 count=3 job='Overview' job_order=['AF Job', 'HiRes', 'Overview'] |  |  | 0.157s |
| 23 | 14:18:48.099 | job selection round-trip | PASS |  |  | job selection: confirmed Overview |  |  | expected='Overview' actual='Overview' | 0.000s |
| 24 | 14:18:48.099 | job selection round-trip | SKIP |  |  | job selection: restore |  |  | 'Overview' already confirmed by round-trip | 0.000s |
| 25 | 14:18:48.145 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | zoom: write current | job='Overview' current=2.0 target=5.0 | target=5.0 | Zoom -> 2.0; [total=0.019s, att=1, conf=1, m=async] | 0.016s |
| 26 | 14:18:48.169 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | zoom: write alternate | job='Overview' current=2.0 target=5.0 | target=5.0 | Zoom -> 5.0; [total=0.020s, att=1, conf=1, m=async] | 0.031s |
| 27 | 14:18:48.182 | settings round-trip | PASS |  |  | zoom: readback |  |  | expected=5.0 actual=5.0000127156898895 tol=0.1 | 0.000s |
| 28 | 14:18:48.206 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | zoom: restore | job='Overview' restore_to=2.0 | restore_to=2.0 | Zoom -> 2.0; [total=0.022s, att=1, conf=1, m=async] | 0.016s |
| 29 | 14:18:48.248 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_speed: write current | job='Overview' current=400 target=600 | target=600 | ScanSpeed -> 400; [total=0.022s, att=1, conf=1, m=async] | 0.031s |
| 30 | 14:18:48.265 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_speed: write alternate | job='Overview' current=400 target=600 | target=600 | ScanSpeed -> 600; [total=0.016s, att=1, conf=1, m=async] | 0.016s |
| 31 | 14:18:48.282 | settings round-trip | PASS |  |  | scan_speed: readback |  |  | expected=600 actual=600 | 0.000s |
| 32 | 14:18:48.311 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_speed: restore | job='Overview' restore_to=400 | restore_to=400 | ScanSpeed -> 400; [total=0.028s, att=1, conf=1, m=async] | 0.031s |
| 33 | 14:18:48.347 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_resonant: write current | job='Overview' current=False target=True | target=True | Resonant -> False; [total=0.022s, att=1, conf=1, m=async] | 0.016s |
| 34 | 14:18:48.366 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_resonant: write alternate | job='Overview' current=False target=True | target=True | Resonant -> True; [total=0.016s, att=1, conf=1, m=async] | 0.015s |
| 35 | 14:18:48.382 | settings round-trip | PASS |  |  | scan_resonant: readback |  |  | expected=True actual=True | 0.000s |
| 36 | 14:18:48.408 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_resonant: restore | job='Overview' restore_to=False | restore_to=False | Resonant -> False; [total=0.025s, att=1, conf=1, m=async] | 0.031s |
| 37 | 14:18:48.433 | settings round-trip | PASS |  |  | scan_mode: read current | job='Overview' |  |  | 0.031s |
| 38 | 14:18:48.433 | settings round-trip | PASS |  |  | scan_mode: is xyz |  |  | expected='xyz' actual='xyz' | 0.000s |
| 39 | 14:18:48.481 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | sequential_mode: write current | job='Overview' current='Line' target='Frame' | target='Frame' | SequentialMode -> Line; [total=0.023s, att=1, conf=1, m=async] | 0.031s |
| 40 | 14:18:48.634 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | sequential_mode: write alternate | job='Overview' current='Line' target='Frame' | target='Frame' | SequentialMode -> Frame; [total=0.150s, att=1, conf=1, m=async] | 0.141s |
| 41 | 14:18:48.659 | settings round-trip | PASS |  |  | sequential_mode: readback |  |  | expected='Frame' actual='Frame' | 0.000s |
| 42 | 14:18:48.675 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | sequential_mode: restore | job='Overview' restore_to='Line' | restore_to='Line' | SequentialMode -> Line; [total=0.016s, att=1, conf=1, m=async] | 0.016s |
| 43 | 14:18:48.724 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_field_rotation: write current | job='Overview' current=5.0 target=0.0 | target=0.0 | Rotation -> 5.0; [total=0.034s, att=1, conf=1, m=async] | 0.032s |
| 44 | 14:18:48.742 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_field_rotation: write alternate | job='Overview' current=5.0 target=0.0 | target=0.0 | Rotation -> 0.0; [total=0.016s, att=1, conf=1, m=async] | 0.015s |
| 45 | 14:18:48.756 | settings round-trip | PASS |  |  | scan_field_rotation: readback |  |  | expected=0.0 actual=0.0 tol=0.5 | 0.000s |
| 46 | 14:18:48.773 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_field_rotation: restore | job='Overview' restore_to=5.0 | restore_to=5.0 | Rotation -> 5.0; [total=0.016s, att=1, conf=1, m=async] | 0.016s |
| 47 | 14:18:48.815 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | image_format: write current | job='Overview' current='512 x 512' target='1024 x 1024' | target='1024 x 1024' | Format -> 512 x 512; [total=0.020s, att=1, conf=1, m=async] | 0.015s |
| 48 | 14:18:48.830 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | image_format: write alternate | job='Overview' current='512 x 512' target='1024 x 1024' | target='1024 x 1024' | Format -> 1024 x 1024; [total=0.016s, att=1, conf=1, m=async] | 0.016s |
| 49 | 14:18:48.846 | settings round-trip | PASS |  |  | image_format: readback |  |  | expected='1024 x 1024' actual='1024 x 1024' | 0.000s |
| 50 | 14:18:48.863 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | image_format: restore | job='Overview' restore_to='512 x 512' | restore_to='512 x 512' | Format -> 512 x 512; [total=0.015s, att=1, conf=1, m=async] | 0.015s |
| 51 | 14:18:48.895 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_accumulation: write current | job='Overview' current=1 target=2 | target=2 | Setting[0].FrameAccumulation -> 1; [total=0.019s, att=1, conf=1, m=async] | 0.016s |
| 52 | 14:18:48.918 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_accumulation: write alternate | job='Overview' current=1 target=2 | target=2 | Setting[0].FrameAccumulation -> 2; [total=0.020s, att=1, conf=1, m=async] | 0.031s |
| 53 | 14:18:48.933 | settings round-trip | PASS |  |  | frame_accumulation: readback |  |  | expected=2 actual=2 | 0.000s |
| 54 | 14:18:48.950 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_accumulation: restore | job='Overview' restore_to=1 | restore_to=1 | Setting[0].FrameAccumulation -> 1; [total=0.016s, att=1, conf=1, m=async] | 0.016s |
| 55 | 14:18:48.981 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_average: write current | job='Overview' current=1 target=2 | target=2 | Setting[0].FrameAverage -> 1; [total=0.018s, att=1, conf=1, m=async] | 0.015s |
| 56 | 14:18:48.997 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_average: write alternate | job='Overview' current=1 target=2 | target=2 | Setting[0].FrameAverage -> 2; [total=0.015s, att=1, conf=1, m=async] | 0.016s |
| 57 | 14:18:49.014 | settings round-trip | PASS |  |  | frame_average: readback |  |  | expected=2 actual=2 | 0.000s |
| 58 | 14:18:49.040 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_average: restore | job='Overview' restore_to=1 | restore_to=1 | Setting[0].FrameAverage -> 1; [total=0.026s, att=1, conf=1, m=async] | 0.015s |
| 59 | 14:18:49.074 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_accumulation: write current | job='Overview' current=1 target=2 | target=2 | Setting[0].LineAccumulation -> 1; [total=0.018s, att=1, conf=1, m=async] | 0.031s |
| 60 | 14:18:49.091 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_accumulation: write alternate | job='Overview' current=1 target=2 | target=2 | Setting[0].LineAccumulation -> 2; [total=0.016s, att=1, conf=1, m=async] | 0.016s |
| 61 | 14:18:49.106 | settings round-trip | PASS |  |  | line_accumulation: readback |  |  | expected=2 actual=2 | 0.000s |
| 62 | 14:18:49.128 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_accumulation: restore | job='Overview' restore_to=1 | restore_to=1 | Setting[0].LineAccumulation -> 1; [total=0.021s, att=1, conf=1, m=async] | 0.016s |
| 63 | 14:18:49.161 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_average: write current | job='Overview' current=1 target=2 | target=2 | Setting[0].LineAverage -> 1; [total=0.018s, att=1, conf=1, m=async] | 0.015s |
| 64 | 14:18:49.176 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_average: write alternate | job='Overview' current=1 target=2 | target=2 | Setting[0].LineAverage -> 2; [total=0.015s, att=1, conf=1, m=async] | 0.016s |
| 65 | 14:18:49.193 | settings round-trip | PASS |  |  | line_average: readback |  |  | expected=2 actual=2 | 0.000s |
| 66 | 14:18:49.212 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_average: restore | job='Overview' restore_to=1 | restore_to=1 | Setting[0].LineAverage -> 1; [total=0.020s, att=1, conf=1, m=async] | 0.016s |
| 67 | 14:18:49.251 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | pinhole_airy: write current | job='Overview' current=1.0 target=1.2 | target=1.2 | Setting[0].PinholeAiry -> 1.0; [total=0.024s, att=1, conf=1, m=async] | 0.031s |
| 68 | 14:18:49.268 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | pinhole_airy: write alternate | job='Overview' current=1.0 target=1.2 | target=1.2 | Setting[0].PinholeAiry -> 1.2; [total=0.016s, att=1, conf=1, m=async] | 0.016s |
| 69 | 14:18:49.284 | settings round-trip | PASS |  |  | pinhole_airy: readback |  |  | expected=1.2 actual=1.2 tol=0.05 | 0.000s |
| 70 | 14:18:49.298 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | pinhole_airy: restore | job='Overview' restore_to=1.0 | restore_to=1.0 | Setting[0].PinholeAiry -> 1.0; [total=0.016s, att=1, conf=1, m=async] | 0.016s |
| 71 | 14:18:49.314 | settings round-trip | SKIP |  |  | detector_gain: round-trip |  |  | HyD 2 exposes no writable gain range; not mutating gain | 0.000s |
| 72 | 14:18:49.329 | xy 10-position pattern | PASS |  |  | xy: read start | mode='api' purpose='stage-safety-anchor' |  |  | 0.016s |
| 73 | 14:18:49.354 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 01 | index=1 count=10 from=(64220.0, 41180.0) to=(64245.0, 41180.0) radius_um=25.0 | to=(64245.0, 41180.0) | MoveXY -> (64245.0, 41180.0) um; [total=0.023s, att=1, conf=1, m=async] | 0.031s |
| 74 | 14:18:49.367 | xy 10-position pattern | PASS |  |  | xy: read 01 | index=1 count=10 from=(64220.0, 41180.0) to=(64245.0, 41180.0) radius_um=25.0 | to=(64245.0, 41180.0) |  | 0.000s |
| 75 | 14:18:49.367 | xy 10-position pattern | PASS |  |  | xy: x readback 01 |  |  | expected=64245.0 actual=64240.00000000001 tol=20.0 | 0.000s |
| 76 | 14:18:49.367 | xy 10-position pattern | PASS |  |  | xy: y readback 01 |  |  | expected=41180.0 actual=41180.0 tol=20.0 | 0.000s |
| 77 | 14:18:49.384 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 02 | index=2 count=10 from=(64220.0, 41180.0) to=(64240.225, 41194.695) radius_um=25.0 | to=(64240.225, 41194.695) | MoveXY -> (64240.225, 41194.695) um; [total=0.014s, att=1, conf=1, m=async] | 0.016s |
| 78 | 14:18:49.398 | xy 10-position pattern | PASS |  |  | xy: read 02 | index=2 count=10 from=(64220.0, 41180.0) to=(64240.225, 41194.695) radius_um=25.0 | to=(64240.225, 41194.695) |  | 0.016s |
| 79 | 14:18:49.398 | xy 10-position pattern | PASS |  |  | xy: x readback 02 |  |  | expected=64240.225 actual=64240.00000000001 tol=20.0 | 0.000s |
| 80 | 14:18:49.398 | xy 10-position pattern | PASS |  |  | xy: y readback 02 |  |  | expected=41194.695 actual=41180.0 tol=20.0 | 0.000s |
| 81 | 14:18:49.415 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 03 | index=3 count=10 from=(64220.0, 41180.0) to=(64227.725, 41203.776) radius_um=25.0 | to=(64227.725, 41203.776) | MoveXY -> (64227.725, 41203.776) um; [total=0.015s, att=1, conf=1, m=async] | 0.015s |
| 82 | 14:18:49.430 | xy 10-position pattern | PASS |  |  | xy: read 03 | index=3 count=10 from=(64220.0, 41180.0) to=(64227.725, 41203.776) radius_um=25.0 | to=(64227.725, 41203.776) |  | 0.016s |
| 83 | 14:18:49.430 | xy 10-position pattern | PASS |  |  | xy: x readback 03 |  |  | expected=64227.725 actual=64220.0 tol=20.0 | 0.000s |
| 84 | 14:18:49.430 | xy 10-position pattern | PASS |  |  | xy: y readback 03 |  |  | expected=41203.776 actual=41200.0 tol=20.0 | 0.000s |
| 85 | 14:18:49.446 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 04 | index=4 count=10 from=(64220.0, 41180.0) to=(64212.275, 41203.776) radius_um=25.0 | to=(64212.275, 41203.776) | MoveXY -> (64212.275, 41203.776) um; [total=0.013s, att=1, conf=1, m=async] | 0.015s |
| 86 | 14:18:49.464 | xy 10-position pattern | PASS |  |  | xy: read 04 | index=4 count=10 from=(64220.0, 41180.0) to=(64212.275, 41203.776) radius_um=25.0 | to=(64212.275, 41203.776) |  | 0.032s |
| 87 | 14:18:49.464 | xy 10-position pattern | PASS |  |  | xy: x readback 04 |  |  | expected=64212.275 actual=64199.99999999999 tol=20.0 | 0.000s |
| 88 | 14:18:49.464 | xy 10-position pattern | PASS |  |  | xy: y readback 04 |  |  | expected=41203.776 actual=41200.0 tol=20.0 | 0.000s |
| 89 | 14:18:49.482 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 05 | index=5 count=10 from=(64220.0, 41180.0) to=(64199.775, 41194.695) radius_um=25.0 | to=(64199.775, 41194.695) | MoveXY -> (64199.775, 41194.695) um; [total=0.015s, att=1, conf=1, m=async] | 0.015s |
| 90 | 14:18:49.495 | xy 10-position pattern | PASS |  |  | xy: read 05 | index=5 count=10 from=(64220.0, 41180.0) to=(64199.775, 41194.695) radius_um=25.0 | to=(64199.775, 41194.695) |  | 0.016s |
| 91 | 14:18:49.495 | xy 10-position pattern | PASS |  |  | xy: x readback 05 |  |  | expected=64199.775 actual=64180.0 tol=20.0 | 0.000s |
| 92 | 14:18:49.495 | xy 10-position pattern | PASS |  |  | xy: y readback 05 |  |  | expected=41194.695 actual=41180.0 tol=20.0 | 0.000s |
| 93 | 14:18:49.515 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 06 | index=6 count=10 from=(64220.0, 41180.0) to=(64195.0, 41180.0) radius_um=25.0 | to=(64195.0, 41180.0) | MoveXY -> (64195.0, 41180.0) um; [total=0.016s, att=1, conf=1, m=async] | 0.016s |
| 94 | 14:18:49.527 | xy 10-position pattern | PASS |  |  | xy: read 06 | index=6 count=10 from=(64220.0, 41180.0) to=(64195.0, 41180.0) radius_um=25.0 | to=(64195.0, 41180.0) |  | 0.015s |
| 95 | 14:18:49.527 | xy 10-position pattern | PASS |  |  | xy: x readback 06 |  |  | expected=64195.0 actual=64180.0 tol=20.0 | 0.000s |
| 96 | 14:18:49.527 | xy 10-position pattern | PASS |  |  | xy: y readback 06 |  |  | expected=41180.0 actual=41180.0 tol=20.0 | 0.000s |
| 97 | 14:18:49.543 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 07 | index=7 count=10 from=(64220.0, 41180.0) to=(64199.775, 41165.305) radius_um=25.0 | to=(64199.775, 41165.305) | MoveXY -> (64199.775, 41165.305) um; [total=0.015s, att=1, conf=1, m=async] | 0.016s |
| 98 | 14:18:49.558 | xy 10-position pattern | PASS |  |  | xy: read 07 | index=7 count=10 from=(64220.0, 41180.0) to=(64199.775, 41165.305) radius_um=25.0 | to=(64199.775, 41165.305) |  | 0.015s |
| 99 | 14:18:49.558 | xy 10-position pattern | PASS |  |  | xy: x readback 07 |  |  | expected=64199.775 actual=64180.0 tol=20.0 | 0.000s |
| 100 | 14:18:49.558 | xy 10-position pattern | PASS |  |  | xy: y readback 07 |  |  | expected=41165.305 actual=41160.0 tol=20.0 | 0.000s |
| 101 | 14:18:49.585 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 08 | index=8 count=10 from=(64220.0, 41180.0) to=(64212.275, 41156.224) radius_um=25.0 | to=(64212.275, 41156.224) | MoveXY -> (64212.275, 41156.224) um; [total=0.025s, att=1, conf=1, m=async] | 0.016s |
| 102 | 14:18:49.599 | xy 10-position pattern | PASS |  |  | xy: read 08 | index=8 count=10 from=(64220.0, 41180.0) to=(64212.275, 41156.224) radius_um=25.0 | to=(64212.275, 41156.224) |  | 0.016s |
| 103 | 14:18:49.599 | xy 10-position pattern | PASS |  |  | xy: x readback 08 |  |  | expected=64212.275 actual=64199.99999999999 tol=20.0 | 0.000s |
| 104 | 14:18:49.599 | xy 10-position pattern | PASS |  |  | xy: y readback 08 |  |  | expected=41156.224 actual=41140.0 tol=20.0 | 0.000s |
| 105 | 14:18:49.615 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 09 | index=9 count=10 from=(64220.0, 41180.0) to=(64227.725, 41156.224) radius_um=25.0 | to=(64227.725, 41156.224) | MoveXY -> (64227.725, 41156.224) um; [total=0.014s, att=1, conf=1, m=async] | 0.015s |
| 106 | 14:18:49.629 | xy 10-position pattern | PASS |  |  | xy: read 09 | index=9 count=10 from=(64220.0, 41180.0) to=(64227.725, 41156.224) radius_um=25.0 | to=(64227.725, 41156.224) |  | 0.016s |
| 107 | 14:18:49.629 | xy 10-position pattern | PASS |  |  | xy: x readback 09 |  |  | expected=64227.725 actual=64220.0 tol=20.0 | 0.000s |
| 108 | 14:18:49.629 | xy 10-position pattern | PASS |  |  | xy: y readback 09 |  |  | expected=41156.224 actual=41140.0 tol=20.0 | 0.000s |
| 109 | 14:18:49.645 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 10 | index=10 count=10 from=(64220.0, 41180.0) to=(64240.225, 41165.305) radius_um=25.0 | to=(64240.225, 41165.305) | MoveXY -> (64240.225, 41165.305) um; [total=0.014s, att=1, conf=1, m=async] | 0.016s |
| 110 | 14:18:49.659 | xy 10-position pattern | PASS |  |  | xy: read 10 | index=10 count=10 from=(64220.0, 41180.0) to=(64240.225, 41165.305) radius_um=25.0 | to=(64240.225, 41165.305) |  | 0.015s |
| 111 | 14:18:49.661 | xy 10-position pattern | PASS |  |  | xy: x readback 10 |  |  | expected=64240.225 actual=64240.00000000001 tol=20.0 | 0.000s |
| 112 | 14:18:49.661 | xy 10-position pattern | PASS |  |  | xy: y readback 10 |  |  | expected=41165.305 actual=41160.0 tol=20.0 | 0.000s |
| 113 | 14:18:49.675 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: restore | restore_to=(64220.0, 41180.0) positions=10 | restore_to=(64220.0, 41180.0) | MoveXY -> (64220.0, 41180.0) um; [total=0.014s, att=1, conf=1, m=async] | 0.016s |
| 114 | 14:18:49.736 | z-galvo round-trip | PASS |  |  | z: read start | job='Overview' |  |  | 0.062s |
| 115 | 14:18:49.769 | z-galvo round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | z: move alternate | job='Overview' from=-0.5 to=1.5 | to=1.5 | Z -> 1.5 um (galvo); [total=0.028s, att=1, conf=1, m=async] | 0.032s |
| 116 | 14:18:49.785 | z-galvo round-trip | PASS |  |  | z: read alternate | job='Overview' |  |  | 0.015s |
| 117 | 14:18:49.785 | z-galvo round-trip | PASS |  |  | z: readback |  |  | expected=1.5 actual=1.5 tol=1.0 | 0.000s |
| 118 | 14:18:49.805 | z-galvo round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | z: restore | restore_to=-0.5 | restore_to=-0.5 | Z -> -0.5 um (galvo); [total=0.016s, att=1, conf=1, m=async] | 0.016s |
| 119 | 14:18:49.806 | setup | SKIP |  |  | phase: objective |  |  | use --allow-objective to enable | 0.000s |
| 120 | 14:18:49.807 | setup | SKIP |  |  | phase: acquire |  |  | use --allow-acquire to enable | 0.000s |

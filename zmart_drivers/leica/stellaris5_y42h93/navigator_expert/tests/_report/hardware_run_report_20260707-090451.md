# Hardware validation run report

Every change this run attempted on the instrument is listed below, including failed attempts and restore/cleanup steps (see the *Mutates scope* column). Changes carry their success+CONFIRMED / success+UNCONFIRMED / FAILED result and attempt counts in the *Result* column.

## Run metadata

- **Validator**: `validate_hardware`
- **Arguments**: `--yes --allow-xy --allow-z --allow-missing-lasx --state-reader-mode log --output=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\hardware_validate_log.jsonl --report-dir=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report`
- **Backend**: live LAS X (simulator or scope)
- **Date**: 2026-07-07
- **Started / finished**: 09:04:51 / 09:04:56 (5.3s)
- **Host**: ZMB-LASX-PC (Windows-10-10.0.26200-SP0)
- **Python**: 3.11.15
- **Driver commit**: unknown on unknown
- **Driver log**: `\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\driver_log_20260707-090451.log` (full log-line capture)

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
| read-only | 5 | 0.015s | 0.063s | 0.079s |
| job selection round-trip | 10 | 0.015s | 0.078s | 0.782s |
| settings round-trip | 34 | 0.015s | 0.016s | 0.157s |
| xy 10-position pattern | 18 | 0.015s | 0.016s | 0.031s |
| z-galvo round-trip | 4 | 0.015s | 0.016s | 0.062s |

### Slowest actions

| Duration | Phase | Action | Status |
|---:|---|---|---|
| 0.782s | job selection round-trip | job selection: select job | PASS |
| 0.781s | job selection round-trip | job selection: select job | PASS |
| 0.610s | job selection round-trip | job selection: select job | PASS |
| 0.157s | settings round-trip | sequential_mode: write alternate | PASS |
| 0.156s | job selection round-trip | job selection: read selected job | PASS |
| 0.093s | job selection round-trip | job selection: read selected job | PASS |
| 0.079s | read-only | get_scan_status | PASS |
| 0.063s | read-only | get_xy | PASS |
| 0.063s | read-only | settings: read | PASS |
| 0.063s | job selection round-trip | job selection: log poll confirmed HiRes | PASS |

### Unconfirmed / failed changes

None -- every attempted change reported success and confirmed.

## Chronological detail (every attempted action)

| # | Time | Phase | Status | Result | Mutates scope | Action attempted | Args / target | Expected | Observed | Duration |
|---:|---|---|---|---|---|---|---|---|---|---:|
| 1 | 09:04:51.894 | setup | PASS |  |  | limits: connect handshake | limits_path='<machine-local snapshot>' |  |  | 0.000s |
| 2 | 09:04:51.897 | read-only | PASS |  |  | ping |  |  |  | 0.000s |
| 3 | 09:04:51.970 | read-only | PASS |  |  | get_scan_status |  |  |  | 0.079s |
| 4 | 09:04:51.971 | read-only | PASS |  |  | get_jobs |  |  |  | 0.000s |
| 5 | 09:04:52.033 | read-only | PASS |  |  | get_hardware_info |  |  |  | 0.062s |
| 6 | 09:04:52.095 | read-only | PASS |  |  | get_xy |  |  |  | 0.063s |
| 7 | 09:04:52.096 | read-only | SKIP |  |  | job: resolve |  |  | job list is API-only (no log leg); enumerating via API | 0.000s |
| 8 | 09:04:52.114 | read-only | PASS |  |  | job: resolve api control for log experiment | purpose='drive log selected-job poll' |  |  | 0.015s |
| 9 | 09:04:52.115 | read-only | PASS |  |  | job: resolved | job='Overview' |  |  | 0.000s |
| 10 | 09:04:52.178 | read-only | PASS |  |  | settings: read | job='Overview' |  |  | 0.063s |
| 11 | 09:04:52.193 | job selection round-trip | PASS |  |  | job selection: read jobs | mode='api' |  |  | 0.015s |
| 12 | 09:04:52.857 | job selection round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | job selection: select job | index=0 count=3 job='AF Job' job_order=['AF Job', 'HiRes', 'Overview'] |  | SelectJob 'AF Job'; [total=0.556s, att=1, conf=1, m=async] | 0.610s |
| 13 | 09:04:52.922 | job selection round-trip | PASS |  |  | job selection: log poll confirmed AF Job | index=0 count=3 job='AF Job' job_order=['AF Job', 'HiRes', 'Overview'] log_poll={'success': True, 'value': 'AF Job', 'matched_at': 1783407892.719, 'attempts': … |  | matched; last_reason=matched; value='AF Job'; log_event_delta=0.482s; api_select_elapsed=0.556s; attempts=1 | 0.062s |
| 14 | 09:04:52.958 | job selection round-trip | PASS |  |  | job selection: read selected job | index=0 count=3 job='AF Job' job_order=['AF Job', 'HiRes', 'Overview'] |  |  | 0.031s |
| 15 | 09:04:52.959 | job selection round-trip | PASS |  |  | job selection: confirmed AF Job |  |  | expected='AF Job' actual='AF Job' | 0.000s |
| 16 | 09:04:53.745 | job selection round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | job selection: select job | index=1 count=3 job='HiRes' job_order=['AF Job', 'HiRes', 'Overview'] |  | SelectJob 'HiRes'; [total=0.723s, att=1, conf=1, m=async] | 0.781s |
| 17 | 09:04:53.809 | job selection round-trip | PASS |  |  | job selection: log poll confirmed HiRes | index=1 count=3 job='HiRes' job_order=['AF Job', 'HiRes', 'Overview'] log_poll={'success': True, 'value': 'HiRes', 'matched_at': 1783407893.714, 'attempts': 1,… |  | matched; last_reason=matched; value='HiRes'; log_event_delta=0.754s; api_select_elapsed=0.723s; attempts=1 | 0.063s |
| 18 | 09:04:53.896 | job selection round-trip | PASS |  |  | job selection: read selected job | index=1 count=3 job='HiRes' job_order=['AF Job', 'HiRes', 'Overview'] |  |  | 0.093s |
| 19 | 09:04:53.897 | job selection round-trip | PASS |  |  | job selection: confirmed HiRes |  |  | expected='HiRes' actual='HiRes' | 0.000s |
| 20 | 09:04:54.683 | job selection round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | job selection: select job | index=2 count=3 job='Overview' job_order=['AF Job', 'HiRes', 'Overview'] |  | SelectJob 'Overview'; [total=0.723s, att=1, conf=1, m=async] | 0.782s |
| 21 | 09:04:54.747 | job selection round-trip | PASS |  |  | job selection: log poll confirmed Overview | index=2 count=3 job='Overview' job_order=['AF Job', 'HiRes', 'Overview'] log_poll={'success': True, 'value': 'Overview', 'matched_at': 1783407894.654, 'attempt… |  | matched; last_reason=matched; value='Overview'; log_event_delta=0.757s; api_select_elapsed=0.723s; attempts=1 | 0.062s |
| 22 | 09:04:54.896 | job selection round-trip | PASS |  |  | job selection: read selected job | index=2 count=3 job='Overview' job_order=['AF Job', 'HiRes', 'Overview'] |  |  | 0.156s |
| 23 | 09:04:54.897 | job selection round-trip | PASS |  |  | job selection: confirmed Overview |  |  | expected='Overview' actual='Overview' | 0.000s |
| 24 | 09:04:54.898 | job selection round-trip | SKIP |  |  | job selection: restore |  |  | 'Overview' already confirmed by round-trip | 0.000s |
| 25 | 09:04:54.938 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | zoom: write current | job='Overview' current=2.0 target=5.0 | target=5.0 | Zoom -> 2.0; [total=0.021s, att=1, conf=1, m=async] | 0.031s |
| 26 | 09:04:54.975 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | zoom: write alternate | job='Overview' current=2.0 target=5.0 | target=5.0 | Zoom -> 5.0; [total=0.036s, att=1, conf=1, m=async] | 0.032s |
| 27 | 09:04:55.034 | settings round-trip | PASS |  |  | zoom: readback |  |  | expected=5.0 actual=5.0000127156898895 tol=0.1 | 0.000s |
| 28 | 09:04:55.051 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | zoom: restore | job='Overview' restore_to=2.0 | restore_to=2.0 | Zoom -> 2.0; [total=0.015s, att=1, conf=1, m=async] | 0.016s |
| 29 | 09:04:55.086 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_speed: write current | job='Overview' current=400 target=600 | target=600 | ScanSpeed -> 400; [total=0.018s, att=1, conf=1, m=async] | 0.016s |
| 30 | 09:04:55.101 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_speed: write alternate | job='Overview' current=400 target=600 | target=600 | ScanSpeed -> 600; [total=0.015s, att=1, conf=1, m=async] | 0.016s |
| 31 | 09:04:55.114 | settings round-trip | PASS |  |  | scan_speed: readback |  |  | expected=600 actual=600 | 0.000s |
| 32 | 09:04:55.152 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_speed: restore | job='Overview' restore_to=400 | restore_to=400 | ScanSpeed -> 400; [total=0.036s, att=1, conf=1, m=async] | 0.031s |
| 33 | 09:04:55.199 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_resonant: write current | job='Overview' current=False target=True | target=True | Resonant -> False; [total=0.022s, att=1, conf=1, m=async] | 0.015s |
| 34 | 09:04:55.216 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_resonant: write alternate | job='Overview' current=False target=True | target=True | Resonant -> True; [total=0.016s, att=1, conf=1, m=async] | 0.016s |
| 35 | 09:04:55.230 | settings round-trip | PASS |  |  | scan_resonant: readback |  |  | expected=True actual=True | 0.000s |
| 36 | 09:04:55.257 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_resonant: restore | job='Overview' restore_to=False | restore_to=False | Resonant -> False; [total=0.025s, att=1, conf=1, m=async] | 0.031s |
| 37 | 09:04:55.281 | settings round-trip | PASS |  |  | scan_mode: read current | job='Overview' |  |  | 0.015s |
| 38 | 09:04:55.282 | settings round-trip | PASS |  |  | scan_mode: is xyz |  |  | expected='xyz' actual='xyz' | 0.000s |
| 39 | 09:04:55.320 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | sequential_mode: write current | job='Overview' current='Line' target='Frame' | target='Frame' | SequentialMode -> Line; [total=0.023s, att=1, conf=1, m=async] | 0.031s |
| 40 | 09:04:55.483 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | sequential_mode: write alternate | job='Overview' current='Line' target='Frame' | target='Frame' | SequentialMode -> Frame; [total=0.162s, att=1, conf=1, m=async] | 0.157s |
| 41 | 09:04:55.508 | settings round-trip | PASS |  |  | sequential_mode: readback |  |  | expected='Frame' actual='Frame' | 0.000s |
| 42 | 09:04:55.526 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | sequential_mode: restore | job='Overview' restore_to='Line' | restore_to='Line' | SequentialMode -> Line; [total=0.018s, att=1, conf=1, m=async] | 0.015s |
| 43 | 09:04:55.576 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_field_rotation: write current | job='Overview' current=5.0 target=0.0 | target=0.0 | Rotation -> 5.0; [total=0.035s, att=1, conf=1, m=async] | 0.031s |
| 44 | 09:04:55.599 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_field_rotation: write alternate | job='Overview' current=5.0 target=0.0 | target=0.0 | Rotation -> 0.0; [total=0.023s, att=1, conf=1, m=async] | 0.032s |
| 45 | 09:04:55.614 | settings round-trip | PASS |  |  | scan_field_rotation: readback |  |  | expected=0.0 actual=0.0 tol=0.5 | 0.000s |
| 46 | 09:04:55.633 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_field_rotation: restore | job='Overview' restore_to=5.0 | restore_to=5.0 | Rotation -> 5.0; [total=0.018s, att=1, conf=1, m=async] | 0.016s |
| 47 | 09:04:55.672 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | image_format: write current | job='Overview' current='512 x 512' target='1024 x 1024' | target='1024 x 1024' | Format -> 512 x 512; [total=0.024s, att=1, conf=1, m=async] | 0.016s |
| 48 | 09:04:55.690 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | image_format: write alternate | job='Overview' current='512 x 512' target='1024 x 1024' | target='1024 x 1024' | Format -> 1024 x 1024; [total=0.017s, att=1, conf=1, m=async] | 0.015s |
| 49 | 09:04:55.707 | settings round-trip | PASS |  |  | image_format: readback |  |  | expected='1024 x 1024' actual='1024 x 1024' | 0.000s |
| 50 | 09:04:55.733 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | image_format: restore | job='Overview' restore_to='512 x 512' | restore_to='512 x 512' | Format -> 512 x 512; [total=0.025s, att=1, conf=1, m=async] | 0.016s |
| 51 | 09:04:55.771 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_accumulation: write current | job='Overview' current=1 target=2 | target=2 | Setting[0].FrameAccumulation -> 1; [total=0.023s, att=1, conf=1, m=async] | 0.031s |
| 52 | 09:04:55.786 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_accumulation: write alternate | job='Overview' current=1 target=2 | target=2 | Setting[0].FrameAccumulation -> 2; [total=0.015s, att=1, conf=1, m=async] | 0.016s |
| 53 | 09:04:55.801 | settings round-trip | PASS |  |  | frame_accumulation: readback |  |  | expected=2 actual=2 | 0.000s |
| 54 | 09:04:55.828 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_accumulation: restore | job='Overview' restore_to=1 | restore_to=1 | Setting[0].FrameAccumulation -> 1; [total=0.026s, att=1, conf=1, m=async] | 0.015s |
| 55 | 09:04:55.871 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_average: write current | job='Overview' current=1 target=2 | target=2 | Setting[0].FrameAverage -> 1; [total=0.017s, att=1, conf=1, m=async] | 0.015s |
| 56 | 09:04:55.889 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_average: write alternate | job='Overview' current=1 target=2 | target=2 | Setting[0].FrameAverage -> 2; [total=0.018s, att=1, conf=1, m=async] | 0.016s |
| 57 | 09:04:55.904 | settings round-trip | PASS |  |  | frame_average: readback |  |  | expected=2 actual=2 | 0.000s |
| 58 | 09:04:55.924 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_average: restore | job='Overview' restore_to=1 | restore_to=1 | Setting[0].FrameAverage -> 1; [total=0.019s, att=1, conf=1, m=async] | 0.032s |
| 59 | 09:04:55.966 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_accumulation: write current | job='Overview' current=1 target=2 | target=2 | Setting[0].LineAccumulation -> 1; [total=0.028s, att=1, conf=1, m=async] | 0.016s |
| 60 | 09:04:55.997 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_accumulation: write alternate | job='Overview' current=1 target=2 | target=2 | Setting[0].LineAccumulation -> 2; [total=0.030s, att=1, conf=1, m=async] | 0.031s |
| 61 | 09:04:56.012 | settings round-trip | PASS |  |  | line_accumulation: readback |  |  | expected=2 actual=2 | 0.000s |
| 62 | 09:04:56.039 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_accumulation: restore | job='Overview' restore_to=1 | restore_to=1 | Setting[0].LineAccumulation -> 1; [total=0.026s, att=1, conf=1, m=async] | 0.031s |
| 63 | 09:04:56.081 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_average: write current | job='Overview' current=1 target=2 | target=2 | Setting[0].LineAverage -> 1; [total=0.017s, att=1, conf=1, m=async] | 0.016s |
| 64 | 09:04:56.097 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_average: write alternate | job='Overview' current=1 target=2 | target=2 | Setting[0].LineAverage -> 2; [total=0.015s, att=1, conf=1, m=async] | 0.016s |
| 65 | 09:04:56.110 | settings round-trip | PASS |  |  | line_average: readback |  |  | expected=2 actual=2 | 0.000s |
| 66 | 09:04:56.132 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_average: restore | job='Overview' restore_to=1 | restore_to=1 | Setting[0].LineAverage -> 1; [total=0.020s, att=1, conf=1, m=async] | 0.016s |
| 67 | 09:04:56.167 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | pinhole_airy: write current | job='Overview' current=1.0 target=1.2 | target=1.2 | Setting[0].PinholeAiry -> 1.0; [total=0.019s, att=1, conf=1, m=async] | 0.016s |
| 68 | 09:04:56.182 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | pinhole_airy: write alternate | job='Overview' current=1.0 target=1.2 | target=1.2 | Setting[0].PinholeAiry -> 1.2; [total=0.014s, att=1, conf=1, m=async] | 0.016s |
| 69 | 09:04:56.197 | settings round-trip | PASS |  |  | pinhole_airy: readback |  |  | expected=1.2 actual=1.2 tol=0.05 | 0.000s |
| 70 | 09:04:56.213 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | pinhole_airy: restore | job='Overview' restore_to=1.0 | restore_to=1.0 | Setting[0].PinholeAiry -> 1.0; [total=0.015s, att=1, conf=1, m=async] | 0.016s |
| 71 | 09:04:56.229 | settings round-trip | SKIP |  |  | detector_gain: round-trip |  |  | HyD 2 exposes no writable gain range; not mutating gain | 0.000s |
| 72 | 09:04:56.242 | xy 10-position pattern | PASS |  |  | xy: read start | mode='api' purpose='stage-safety-anchor' |  |  | 0.015s |
| 73 | 09:04:56.268 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 01 | index=1 count=10 from=(64220.0, 41180.0) to=(64245.0, 41180.0) radius_um=25.0 | to=(64245.0, 41180.0) | MoveXY -> (64245.0, 41180.0) um; [total=0.023s, att=1, conf=1, m=async] | 0.031s |
| 74 | 09:04:56.281 | xy 10-position pattern | PASS |  |  | xy: read 01 | index=1 count=10 from=(64220.0, 41180.0) to=(64245.0, 41180.0) radius_um=25.0 | to=(64245.0, 41180.0) |  | 0.000s |
| 75 | 09:04:56.282 | xy 10-position pattern | PASS |  |  | xy: x readback 01 |  |  | expected=64245.0 actual=64240.00000000001 tol=20.0 | 0.000s |
| 76 | 09:04:56.283 | xy 10-position pattern | PASS |  |  | xy: y readback 01 |  |  | expected=41180.0 actual=41180.0 tol=20.0 | 0.000s |
| 77 | 09:04:56.298 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 02 | index=2 count=10 from=(64220.0, 41180.0) to=(64240.225, 41194.695) radius_um=25.0 | to=(64240.225, 41194.695) | MoveXY -> (64240.225, 41194.695) um; [total=0.013s, att=1, conf=1, m=async] | 0.016s |
| 78 | 09:04:56.310 | xy 10-position pattern | PASS |  |  | xy: read 02 | index=2 count=10 from=(64220.0, 41180.0) to=(64240.225, 41194.695) radius_um=25.0 | to=(64240.225, 41194.695) |  | 0.000s |
| 79 | 09:04:56.311 | xy 10-position pattern | PASS |  |  | xy: x readback 02 |  |  | expected=64240.225 actual=64240.00000000001 tol=20.0 | 0.000s |
| 80 | 09:04:56.312 | xy 10-position pattern | PASS |  |  | xy: y readback 02 |  |  | expected=41194.695 actual=41180.0 tol=20.0 | 0.000s |
| 81 | 09:04:56.327 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 03 | index=3 count=10 from=(64220.0, 41180.0) to=(64227.725, 41203.776) radius_um=25.0 | to=(64227.725, 41203.776) | MoveXY -> (64227.725, 41203.776) um; [total=0.013s, att=1, conf=1, m=async] | 0.000s |
| 82 | 09:04:56.340 | xy 10-position pattern | PASS |  |  | xy: read 03 | index=3 count=10 from=(64220.0, 41180.0) to=(64227.725, 41203.776) radius_um=25.0 | to=(64227.725, 41203.776) |  | 0.016s |
| 83 | 09:04:56.341 | xy 10-position pattern | PASS |  |  | xy: x readback 03 |  |  | expected=64227.725 actual=64220.0 tol=20.0 | 0.000s |
| 84 | 09:04:56.342 | xy 10-position pattern | PASS |  |  | xy: y readback 03 |  |  | expected=41203.776 actual=41200.0 tol=20.0 | 0.000s |
| 85 | 09:04:56.357 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 04 | index=4 count=10 from=(64220.0, 41180.0) to=(64212.275, 41203.776) radius_um=25.0 | to=(64212.275, 41203.776) | MoveXY -> (64212.275, 41203.776) um; [total=0.014s, att=1, conf=1, m=async] | 0.016s |
| 86 | 09:04:56.370 | xy 10-position pattern | PASS |  |  | xy: read 04 | index=4 count=10 from=(64220.0, 41180.0) to=(64212.275, 41203.776) radius_um=25.0 | to=(64212.275, 41203.776) |  | 0.015s |
| 87 | 09:04:56.371 | xy 10-position pattern | PASS |  |  | xy: x readback 04 |  |  | expected=64212.275 actual=64199.99999999999 tol=20.0 | 0.000s |
| 88 | 09:04:56.372 | xy 10-position pattern | PASS |  |  | xy: y readback 04 |  |  | expected=41203.776 actual=41200.0 tol=20.0 | 0.000s |
| 89 | 09:04:56.386 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 05 | index=5 count=10 from=(64220.0, 41180.0) to=(64199.775, 41194.695) radius_um=25.0 | to=(64199.775, 41194.695) | MoveXY -> (64199.775, 41194.695) um; [total=0.013s, att=1, conf=1, m=async] | 0.016s |
| 90 | 09:04:56.400 | xy 10-position pattern | PASS |  |  | xy: read 05 | index=5 count=10 from=(64220.0, 41180.0) to=(64199.775, 41194.695) radius_um=25.0 | to=(64199.775, 41194.695) |  | 0.015s |
| 91 | 09:04:56.401 | xy 10-position pattern | PASS |  |  | xy: x readback 05 |  |  | expected=64199.775 actual=64180.0 tol=20.0 | 0.000s |
| 92 | 09:04:56.402 | xy 10-position pattern | PASS |  |  | xy: y readback 05 |  |  | expected=41194.695 actual=41180.0 tol=20.0 | 0.000s |
| 93 | 09:04:56.416 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 06 | index=6 count=10 from=(64220.0, 41180.0) to=(64195.0, 41180.0) radius_um=25.0 | to=(64195.0, 41180.0) | MoveXY -> (64195.0, 41180.0) um; [total=0.013s, att=1, conf=1, m=async] | 0.016s |
| 94 | 09:04:56.429 | xy 10-position pattern | PASS |  |  | xy: read 06 | index=6 count=10 from=(64220.0, 41180.0) to=(64195.0, 41180.0) radius_um=25.0 | to=(64195.0, 41180.0) |  | 0.016s |
| 95 | 09:04:56.430 | xy 10-position pattern | PASS |  |  | xy: x readback 06 |  |  | expected=64195.0 actual=64180.0 tol=20.0 | 0.000s |
| 96 | 09:04:56.430 | xy 10-position pattern | PASS |  |  | xy: y readback 06 |  |  | expected=41180.0 actual=41180.0 tol=20.0 | 0.000s |
| 97 | 09:04:56.435 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 07 | index=7 count=10 from=(64220.0, 41180.0) to=(64199.775, 41165.305) radius_um=25.0 | to=(64199.775, 41165.305) | MoveXY -> (64199.775, 41165.305) um; [total=0.003s, att=1, conf=1, m=async] | 0.000s |
| 98 | 09:04:56.448 | xy 10-position pattern | PASS |  |  | xy: read 07 | index=7 count=10 from=(64220.0, 41180.0) to=(64199.775, 41165.305) radius_um=25.0 | to=(64199.775, 41165.305) |  | 0.015s |
| 99 | 09:04:56.449 | xy 10-position pattern | PASS |  |  | xy: x readback 07 |  |  | expected=64199.775 actual=64180.0 tol=20.0 | 0.000s |
| 100 | 09:04:56.450 | xy 10-position pattern | PASS |  |  | xy: y readback 07 |  |  | expected=41165.305 actual=41160.0 tol=20.0 | 0.000s |
| 101 | 09:04:56.464 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 08 | index=8 count=10 from=(64220.0, 41180.0) to=(64212.275, 41156.224) radius_um=25.0 | to=(64212.275, 41156.224) | MoveXY -> (64212.275, 41156.224) um; [total=0.013s, att=1, conf=1, m=async] | 0.016s |
| 102 | 09:04:56.476 | xy 10-position pattern | PASS |  |  | xy: read 08 | index=8 count=10 from=(64220.0, 41180.0) to=(64212.275, 41156.224) radius_um=25.0 | to=(64212.275, 41156.224) |  | 0.016s |
| 103 | 09:04:56.477 | xy 10-position pattern | PASS |  |  | xy: x readback 08 |  |  | expected=64212.275 actual=64199.99999999999 tol=20.0 | 0.000s |
| 104 | 09:04:56.478 | xy 10-position pattern | PASS |  |  | xy: y readback 08 |  |  | expected=41156.224 actual=41140.0 tol=20.0 | 0.000s |
| 105 | 09:04:56.492 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 09 | index=9 count=10 from=(64220.0, 41180.0) to=(64227.725, 41156.224) radius_um=25.0 | to=(64227.725, 41156.224) | MoveXY -> (64227.725, 41156.224) um; [total=0.013s, att=1, conf=1, m=async] | 0.015s |
| 106 | 09:04:56.504 | xy 10-position pattern | PASS |  |  | xy: read 09 | index=9 count=10 from=(64220.0, 41180.0) to=(64227.725, 41156.224) radius_um=25.0 | to=(64227.725, 41156.224) |  | 0.016s |
| 107 | 09:04:56.505 | xy 10-position pattern | PASS |  |  | xy: x readback 09 |  |  | expected=64227.725 actual=64220.0 tol=20.0 | 0.000s |
| 108 | 09:04:56.506 | xy 10-position pattern | PASS |  |  | xy: y readback 09 |  |  | expected=41156.224 actual=41140.0 tol=20.0 | 0.000s |
| 109 | 09:04:56.521 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 10 | index=10 count=10 from=(64220.0, 41180.0) to=(64240.225, 41165.305) radius_um=25.0 | to=(64240.225, 41165.305) | MoveXY -> (64240.225, 41165.305) um; [total=0.014s, att=1, conf=1, m=async] | 0.015s |
| 110 | 09:04:56.534 | xy 10-position pattern | PASS |  |  | xy: read 10 | index=10 count=10 from=(64220.0, 41180.0) to=(64240.225, 41165.305) radius_um=25.0 | to=(64240.225, 41165.305) |  | 0.016s |
| 111 | 09:04:56.535 | xy 10-position pattern | PASS |  |  | xy: x readback 10 |  |  | expected=64240.225 actual=64240.00000000001 tol=20.0 | 0.000s |
| 112 | 09:04:56.536 | xy 10-position pattern | PASS |  |  | xy: y readback 10 |  |  | expected=41165.305 actual=41160.0 tol=20.0 | 0.000s |
| 113 | 09:04:56.550 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: restore | restore_to=(64220.0, 41180.0) positions=10 | restore_to=(64220.0, 41180.0) | MoveXY -> (64220.0, 41180.0) um; [total=0.013s, att=1, conf=1, m=async] | 0.016s |
| 114 | 09:04:56.614 | z-galvo round-trip | PASS |  |  | z: read start | job='Overview' |  |  | 0.062s |
| 115 | 09:04:56.637 | z-galvo round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | z: move alternate | job='Overview' from=-0.5 to=1.5 | to=1.5 | Z -> 1.5 um (galvo); [total=0.020s, att=1, conf=1, m=async] | 0.016s |
| 116 | 09:04:56.651 | z-galvo round-trip | PASS |  |  | z: read alternate | job='Overview' |  |  | 0.015s |
| 117 | 09:04:56.652 | z-galvo round-trip | PASS |  |  | z: readback |  |  | expected=1.5 actual=1.5 tol=1.0 | 0.000s |
| 118 | 09:04:56.667 | z-galvo round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | z: restore | restore_to=-0.5 | restore_to=-0.5 | Z -> -0.5 um (galvo); [total=0.015s, att=1, conf=1, m=async] | 0.016s |
| 119 | 09:04:56.668 | setup | SKIP |  |  | phase: objective |  |  | use --allow-objective to enable | 0.000s |
| 120 | 09:04:56.669 | setup | SKIP |  |  | phase: acquire |  |  | use --allow-acquire to enable | 0.000s |

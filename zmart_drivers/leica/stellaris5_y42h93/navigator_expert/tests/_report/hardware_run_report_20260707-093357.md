# Hardware validation run report

Every change this run attempted on the instrument is listed below, including failed attempts and restore/cleanup steps (see the *Mutates scope* column). Changes carry their success+CONFIRMED / success+UNCONFIRMED / FAILED result and attempt counts in the *Result* column.

## Run metadata

- **Validator**: `validate_hardware`
- **Arguments**: `--yes --allow-xy --allow-z --allow-missing-lasx --state-reader-mode api --output=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\hardware_validate_api.jsonl --report-dir=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report`
- **Backend**: live LAS X (simulator or scope)
- **Date**: 2026-07-07
- **Started / finished**: 09:33:57 / 09:34:46 (49.0s)
- **Host**: ZMB-Y42H93-STI8 (Windows-10-10.0.26100-SP0)
- **Python**: 3.11.15
- **Driver commit**: aecf1a2 on claude/smart-drivers-code-review-ky4phc (working tree has local changes)
- **Driver log**: `\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\driver_log_20260707-093357.log` (full log-line capture)

## Summary

| Phase | Actions attempted | Passed | Warned | Failed | Skipped | Confirmed | Unconfirmed |
|---|---:|---:|---:|---:|---:|---:|---:|
| setup | 3 | 1 | 0 | 0 | 2 | 0 | 0 |
| read-only | 7 | 7 | 0 | 0 | 0 | 0 | 0 |
| job selection round-trip | 11 | 6 | 2 | 2 | 1 | 1 | 2 |
| settings round-trip | 50 | 49 | 1 | 0 | 0 | 35 | 1 |
| xy 10-position pattern | 42 | 42 | 0 | 0 | 0 | 11 | 0 |
| z-galvo round-trip | 5 | 5 | 0 | 0 | 0 | 2 | 0 |
| **total** | **118** | **110** | **3** | **2** | **3** | **49** | **3** |

## Timing overview

### Per phase

| Phase | Timed actions | Min | Median | Max |
|---|---:|---:|---:|---:|
| read-only | 4 | 0.015s | 0.016s | 0.016s |
| job selection round-trip | 7 | 0.015s | 0.016s | 15.109s |
| settings round-trip | 36 | 0.015s | 0.016s | 9.094s |
| xy 10-position pattern | 20 | 0.015s | 0.078s | 0.110s |
| z-galvo round-trip | 4 | 0.016s | 0.024s | 0.031s |

### Slowest actions

| Duration | Phase | Action | Status |
|---:|---|---|---|
| 15.109s | job selection round-trip | job selection: select job | WARN |
| 15.109s | job selection round-trip | job selection: select job | WARN |
| 9.094s | settings round-trip | sequential_mode: restore | WARN |
| 2.062s | settings round-trip | detector_gain: write current | PASS |
| 2.047s | settings round-trip | line_accumulation: write current | PASS |
| 2.047s | settings round-trip | line_average: write alternate | PASS |
| 0.312s | settings round-trip | sequential_mode: write alternate | PASS |
| 0.110s | xy 10-position pattern | xy: move 05 | PASS |
| 0.110s | xy 10-position pattern | xy: move 06 | PASS |
| 0.109s | xy 10-position pattern | xy: move 09 | PASS |

### Unconfirmed / failed changes

| Phase | Action | Result | Attempts | Duration | Observed |
|---|---|---|---|---:|---|
| job selection round-trip | job selection: select job | success+UNCONFIRMED | att=3 conf=3 | 15.109s | SelectJob 'AF Job' (readback unconfirmed); [total=15.093s, att=3, conf=3, m=async] |
| job selection round-trip | job selection: select job | success+UNCONFIRMED | att=3 conf=3 | 15.109s | SelectJob 'Overview' (readback unconfirmed); [total=15.086s, att=3, conf=3, m=async] |
| settings round-trip | sequential_mode: restore | success+UNCONFIRMED | att=3 conf=3 | 9.094s | SequentialMode -> Line (readback unconfirmed); [total=9.094s, att=3, conf=3, m=async] |

## Chronological detail (every attempted action)

| # | Time | Phase | Status | Result | Mutates scope | Action attempted | Args / target | Expected | Observed | Duration |
|---:|---|---|---|---|---|---|---|---|---|---:|
| 1 | 09:33:57.817 | setup | PASS |  |  | limits: connect handshake | limits_path='<machine-local snapshot>' |  |  | 0.000s |
| 2 | 09:33:57.821 | read-only | PASS |  |  | ping |  |  |  | 0.000s |
| 3 | 09:33:57.827 | read-only | PASS |  |  | get_scan_status |  |  |  | 0.016s |
| 4 | 09:33:57.858 | read-only | PASS |  |  | get_jobs |  |  |  | 0.015s |
| 5 | 09:33:57.873 | read-only | PASS |  |  | get_hardware_info |  |  |  | 0.000s |
| 6 | 09:33:57.888 | read-only | PASS |  |  | get_xy |  |  |  | 0.016s |
| 7 | 09:33:57.890 | read-only | PASS |  |  | job: resolved | job='HiRes' |  |  | 0.000s |
| 8 | 09:33:57.908 | read-only | PASS |  |  | settings: read | job='HiRes' |  |  | 0.016s |
| 9 | 09:33:57.923 | job selection round-trip | PASS |  |  | job selection: read jobs | mode='profile' |  |  | 0.015s |
| 10 | 09:34:13.075 | job selection round-trip | WARN | success+UNCONFIRMED att=3 conf=3 | YES | job selection: select job | index=0 count=3 job='AF Job' job_order=['AF Job', 'Overview', 'HiRes'] |  | SelectJob 'AF Job' (readback unconfirmed); [total=15.093s, att=3, conf=3, m=async] | 15.109s |
| 11 | 09:34:13.089 | job selection round-trip | PASS |  |  | job selection: read selected job | index=0 count=3 job='AF Job' job_order=['AF Job', 'Overview', 'HiRes'] |  |  | 0.016s |
| 12 | 09:34:13.090 | job selection round-trip | FAIL |  |  | job selection: confirmed AF Job |  |  | expected='AF Job' actual='HiRes' | 0.000s |
| 13 | 09:34:28.193 | job selection round-trip | WARN | success+UNCONFIRMED att=3 conf=3 | YES | job selection: select job | index=1 count=3 job='Overview' job_order=['AF Job', 'Overview', 'HiRes'] |  | SelectJob 'Overview' (readback unconfirmed); [total=15.086s, att=3, conf=3, m=async] | 15.109s |
| 14 | 09:34:28.208 | job selection round-trip | PASS |  |  | job selection: read selected job | index=1 count=3 job='Overview' job_order=['AF Job', 'Overview', 'HiRes'] |  |  | 0.016s |
| 15 | 09:34:28.209 | job selection round-trip | FAIL |  |  | job selection: confirmed Overview |  |  | expected='Overview' actual='HiRes' | 0.000s |
| 16 | 09:34:28.223 | job selection round-trip | PASS | success+CONFIRMED att=0 conf=0 | YES | job selection: select job | index=2 count=3 job='HiRes' job_order=['AF Job', 'Overview', 'HiRes'] |  | 'HiRes' already selected; [total=0.012s, att=0, conf=0, m=async] | 0.015s |
| 17 | 09:34:28.236 | job selection round-trip | PASS |  |  | job selection: read selected job | index=2 count=3 job='HiRes' job_order=['AF Job', 'Overview', 'HiRes'] |  |  | 0.016s |
| 18 | 09:34:28.237 | job selection round-trip | PASS |  |  | job selection: confirmed HiRes |  |  | expected='HiRes' actual='HiRes' | 0.000s |
| 19 | 09:34:28.238 | job selection round-trip | SKIP |  |  | job selection: restore |  |  | 'HiRes' already confirmed by round-trip | 0.000s |
| 20 | 09:34:28.275 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | zoom: write current | job='HiRes' current=1.0 target=5.0 | target=5.0 | Zoom -> 1.0; [total=0.021s, att=1, conf=1, m=async] | 0.015s |
| 21 | 09:34:28.293 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | zoom: write alternate | job='HiRes' current=1.0 target=5.0 | target=5.0 | Zoom -> 5.0; [total=0.017s, att=1, conf=1, m=async] | 0.016s |
| 22 | 09:34:28.308 | settings round-trip | PASS |  |  | zoom: readback |  |  | expected=5.0 actual=5.0000127156898895 tol=0.1 | 0.000s |
| 23 | 09:34:28.326 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | zoom: restore | job='HiRes' restore_to=1.0 | restore_to=1.0 | Zoom -> 1.0; [total=0.016s, att=1, conf=1, m=async] | 0.016s |
| 24 | 09:34:28.365 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_speed: write current | job='HiRes' current=400 target=600 | target=600 | ScanSpeed -> 400; [total=0.019s, att=1, conf=1, m=async] | 0.016s |
| 25 | 09:34:28.383 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_speed: write alternate | job='HiRes' current=400 target=600 | target=600 | ScanSpeed -> 600; [total=0.016s, att=1, conf=1, m=async] | 0.016s |
| 26 | 09:34:28.398 | settings round-trip | PASS |  |  | scan_speed: readback |  |  | expected=600 actual=600 | 0.000s |
| 27 | 09:34:28.419 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_speed: restore | job='HiRes' restore_to=400 | restore_to=400 | ScanSpeed -> 400; [total=0.020s, att=1, conf=1, m=async] | 0.016s |
| 28 | 09:34:28.462 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_resonant: write current | job='HiRes' current=False target=True | target=True | Resonant -> False; [total=0.027s, att=1, conf=1, m=async] | 0.032s |
| 29 | 09:34:28.486 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_resonant: write alternate | job='HiRes' current=False target=True | target=True | Resonant -> True; [total=0.022s, att=1, conf=1, m=async] | 0.031s |
| 30 | 09:34:28.502 | settings round-trip | PASS |  |  | scan_resonant: readback |  |  | expected=True actual=True | 0.000s |
| 31 | 09:34:28.519 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_resonant: restore | job='HiRes' restore_to=False | restore_to=False | Resonant -> False; [total=0.016s, att=1, conf=1, m=async] | 0.015s |
| 32 | 09:34:28.534 | settings round-trip | PASS |  |  | scan_mode: read current | job='HiRes' |  |  | 0.016s |
| 33 | 09:34:28.535 | settings round-trip | PASS |  |  | scan_mode: is xyz |  |  | expected='xyz' actual='xyz' | 0.000s |
| 34 | 09:34:28.581 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | sequential_mode: write current | job='HiRes' current='Line' target='Frame' | target='Frame' | SequentialMode -> Line; [total=0.030s, att=1, conf=1, m=async] | 0.032s |
| 35 | 09:34:28.903 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | sequential_mode: write alternate | job='HiRes' current='Line' target='Frame' | target='Frame' | SequentialMode -> Frame; [total=0.320s, att=1, conf=1, m=async] | 0.312s |
| 36 | 09:34:28.918 | settings round-trip | PASS |  |  | sequential_mode: readback |  |  | expected='Frame' actual='Frame' | 0.000s |
| 37 | 09:34:38.016 | settings round-trip | WARN | success+UNCONFIRMED att=3 conf=3 | YES | sequential_mode: restore | job='HiRes' restore_to='Line' | restore_to='Line' | SequentialMode -> Line (readback unconfirmed); [total=9.094s, att=3, conf=3, m=async] | 9.094s |
| 38 | 09:34:38.059 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_field_rotation: write current | job='HiRes' current=0.0 target=5.0 | target=5.0 | Rotation -> 0.0; [total=0.026s, att=1, conf=1, m=async] | 0.015s |
| 39 | 09:34:38.078 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_field_rotation: write alternate | job='HiRes' current=0.0 target=5.0 | target=5.0 | Rotation -> 5.0; [total=0.017s, att=1, conf=1, m=async] | 0.032s |
| 40 | 09:34:38.096 | settings round-trip | PASS |  |  | scan_field_rotation: readback |  |  | expected=5.0 actual=5.0 tol=0.5 | 0.000s |
| 41 | 09:34:38.115 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_field_rotation: restore | job='HiRes' restore_to=0.0 | restore_to=0.0 | Rotation -> 0.0; [total=0.017s, att=1, conf=1, m=async] | 0.016s |
| 42 | 09:34:38.152 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | image_format: write current | job='HiRes' current='512 x 512' target='1024 x 1024' | target='1024 x 1024' | Format -> 512 x 512; [total=0.021s, att=1, conf=1, m=async] | 0.015s |
| 43 | 09:34:38.170 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | image_format: write alternate | job='HiRes' current='512 x 512' target='1024 x 1024' | target='1024 x 1024' | Format -> 1024 x 1024; [total=0.017s, att=1, conf=1, m=async] | 0.016s |
| 44 | 09:34:38.186 | settings round-trip | PASS |  |  | image_format: readback |  |  | expected='1024 x 1024' actual='1024 x 1024' | 0.000s |
| 45 | 09:34:38.204 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | image_format: restore | job='HiRes' restore_to='512 x 512' | restore_to='512 x 512' | Format -> 512 x 512; [total=0.016s, att=1, conf=1, m=async] | 0.016s |
| 46 | 09:34:38.245 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_accumulation: write current | job='HiRes' current=1 target=2 | target=2 | Setting[0].FrameAccumulation -> 1; [total=0.027s, att=1, conf=1, m=async] | 0.016s |
| 47 | 09:34:38.264 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_accumulation: write alternate | job='HiRes' current=1 target=2 | target=2 | Setting[0].FrameAccumulation -> 2; [total=0.017s, att=1, conf=1, m=async] | 0.016s |
| 48 | 09:34:38.279 | settings round-trip | PASS |  |  | frame_accumulation: readback |  |  | expected=2 actual=2 | 0.000s |
| 49 | 09:34:38.302 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_accumulation: restore | job='HiRes' restore_to=1 | restore_to=1 | Setting[0].FrameAccumulation -> 1; [total=0.020s, att=1, conf=1, m=async] | 0.015s |
| 50 | 09:34:38.339 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_average: write current | job='HiRes' current=1 target=2 | target=2 | Setting[0].FrameAverage -> 1; [total=0.021s, att=1, conf=1, m=async] | 0.016s |
| 51 | 09:34:38.360 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_average: write alternate | job='HiRes' current=1 target=2 | target=2 | Setting[0].FrameAverage -> 2; [total=0.020s, att=1, conf=1, m=async] | 0.031s |
| 52 | 09:34:38.375 | settings round-trip | PASS |  |  | frame_average: readback |  |  | expected=2 actual=2 | 0.000s |
| 53 | 09:34:38.393 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_average: restore | job='HiRes' restore_to=1 | restore_to=1 | Setting[0].FrameAverage -> 1; [total=0.017s, att=1, conf=1, m=async] | 0.015s |
| 54 | 09:34:40.459 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_accumulation: write current | job='HiRes' current=1 target=2 | target=2 | Setting[0].LineAccumulation -> 1; [total=2.050s, att=1, conf=1, m=async] | 2.047s |
| 55 | 09:34:40.479 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_accumulation: write alternate | job='HiRes' current=1 target=2 | target=2 | Setting[0].LineAccumulation -> 2; [total=0.018s, att=1, conf=1, m=async] | 0.015s |
| 56 | 09:34:40.494 | settings round-trip | PASS |  |  | line_accumulation: readback |  |  | expected=2 actual=2 | 0.000s |
| 57 | 09:34:40.513 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_accumulation: restore | job='HiRes' restore_to=1 | restore_to=1 | Setting[0].LineAccumulation -> 1; [total=0.017s, att=1, conf=1, m=async] | 0.016s |
| 58 | 09:34:40.560 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_average: write current | job='HiRes' current=1 target=2 | target=2 | Setting[0].LineAverage -> 1; [total=0.027s, att=1, conf=1, m=async] | 0.015s |
| 59 | 09:34:42.603 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_average: write alternate | job='HiRes' current=1 target=2 | target=2 | Setting[0].LineAverage -> 2; [total=2.042s, att=1, conf=1, m=async] | 2.047s |
| 60 | 09:34:42.619 | settings round-trip | PASS |  |  | line_average: readback |  |  | expected=2 actual=2 | 0.000s |
| 61 | 09:34:42.638 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_average: restore | job='HiRes' restore_to=1 | restore_to=1 | Setting[0].LineAverage -> 1; [total=0.017s, att=1, conf=1, m=async] | 0.016s |
| 62 | 09:34:42.673 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | pinhole_airy: write current | job='HiRes' current=1.0 target=1.2 | target=1.2 | Setting[0].PinholeAiry -> 1.0; [total=0.020s, att=1, conf=1, m=async] | 0.031s |
| 63 | 09:34:42.685 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | pinhole_airy: write alternate | job='HiRes' current=1.0 target=1.2 | target=1.2 | Setting[0].PinholeAiry -> 1.2; [total=0.010s, att=1, conf=1, m=async] | 0.000s |
| 64 | 09:34:42.701 | settings round-trip | PASS |  |  | pinhole_airy: readback |  |  | expected=1.2 actual=1.2 tol=0.05 | 0.000s |
| 65 | 09:34:42.718 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | pinhole_airy: restore | job='HiRes' restore_to=1.0 | restore_to=1.0 | Setting[0].PinholeAiry -> 1.0; [total=0.016s, att=1, conf=1, m=async] | 0.031s |
| 66 | 09:34:44.797 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | detector_gain: write current | job='HiRes' current=2.5 target=3.5 | target=3.5 | Setting[0].Detector[40;1].Gain -> 2.5; [total=2.050s, att=1, conf=1, m=async] | 2.062s |
| 67 | 09:34:44.815 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | detector_gain: write alternate | job='HiRes' current=2.5 target=3.5 | target=3.5 | Setting[0].Detector[40;1].Gain -> 3.5; [total=0.016s, att=1, conf=1, m=async] | 0.016s |
| 68 | 09:34:44.834 | settings round-trip | PASS |  |  | detector_gain: readback |  |  | expected=3.5 actual=3.5 tol=0.1 | 0.000s |
| 69 | 09:34:44.851 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | detector_gain: restore | job='HiRes' restore_to=2.5 | restore_to=2.5 | Setting[0].Detector[40;1].Gain -> 2.5; [total=0.016s, att=1, conf=1, m=async] | 0.015s |
| 70 | 09:34:44.865 | xy 10-position pattern | PASS |  |  | xy: read start | mode='api' purpose='stage-safety-anchor' |  |  | 0.016s |
| 71 | 09:34:44.947 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 01 | index=1 count=10 from=(63500.0, 41499.99999999999) to=(63525.0, 41500.0) radius_um=25.0 | to=(63525.0, 41500.0) | MoveXY -> (63525.0, 41500.0) um; [total=0.079s, att=1, conf=1, m=async] | 0.078s |
| 72 | 09:34:44.962 | xy 10-position pattern | PASS |  |  | xy: read 01 | index=1 count=10 from=(63500.0, 41499.99999999999) to=(63525.0, 41500.0) radius_um=25.0 | to=(63525.0, 41500.0) |  | 0.016s |
| 73 | 09:34:44.963 | xy 10-position pattern | PASS |  |  | xy: x readback 01 |  |  | expected=63525.0 actual=63525.0 tol=20.0 | 0.000s |
| 74 | 09:34:44.964 | xy 10-position pattern | PASS |  |  | xy: y readback 01 |  |  | expected=41500.0 actual=41499.99999999999 tol=20.0 | 0.000s |
| 75 | 09:34:45.071 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 02 | index=2 count=10 from=(63500.0, 41499.99999999999) to=(63520.225, 41514.695) radius_um=25.0 | to=(63520.225, 41514.695) | MoveXY -> (63520.225, 41514.695) um; [total=0.106s, att=1, conf=1, m=async] | 0.109s |
| 76 | 09:34:45.086 | xy 10-position pattern | PASS |  |  | xy: read 02 | index=2 count=10 from=(63500.0, 41499.99999999999) to=(63520.225, 41514.695) radius_um=25.0 | to=(63520.225, 41514.695) |  | 0.016s |
| 77 | 09:34:45.088 | xy 10-position pattern | PASS |  |  | xy: x readback 02 |  |  | expected=63520.225 actual=63520.22460937499 tol=20.0 | 0.000s |
| 78 | 09:34:45.089 | xy 10-position pattern | PASS |  |  | xy: y readback 02 |  |  | expected=41514.695 actual=41514.69238281249 tol=20.0 | 0.000s |
| 79 | 09:34:45.167 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 03 | index=3 count=10 from=(63500.0, 41499.99999999999) to=(63507.725, 41523.776) radius_um=25.0 | to=(63507.725, 41523.776) | MoveXY -> (63507.725, 41523.776) um; [total=0.076s, att=1, conf=1, m=async] | 0.078s |
| 80 | 09:34:45.181 | xy 10-position pattern | PASS |  |  | xy: read 03 | index=3 count=10 from=(63500.0, 41499.99999999999) to=(63507.725, 41523.776) radius_um=25.0 | to=(63507.725, 41523.776) |  | 0.015s |
| 81 | 09:34:45.182 | xy 10-position pattern | PASS |  |  | xy: x readback 03 |  |  | expected=63507.725 actual=63507.724609375 tol=20.0 | 0.000s |
| 82 | 09:34:45.183 | xy 10-position pattern | PASS |  |  | xy: y readback 03 |  |  | expected=41523.776 actual=41523.7744140625 tol=20.0 | 0.000s |
| 83 | 09:34:45.261 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 04 | index=4 count=10 from=(63500.0, 41499.99999999999) to=(63492.275, 41523.776) radius_um=25.0 | to=(63492.275, 41523.776) | MoveXY -> (63492.275, 41523.776) um; [total=0.076s, att=1, conf=1, m=async] | 0.079s |
| 84 | 09:34:45.275 | xy 10-position pattern | PASS |  |  | xy: read 04 | index=4 count=10 from=(63500.0, 41499.99999999999) to=(63492.275, 41523.776) radius_um=25.0 | to=(63492.275, 41523.776) |  | 0.015s |
| 85 | 09:34:45.276 | xy 10-position pattern | PASS |  |  | xy: x readback 04 |  |  | expected=63492.275 actual=63492.27539062499 tol=20.0 | 0.000s |
| 86 | 09:34:45.277 | xy 10-position pattern | PASS |  |  | xy: y readback 04 |  |  | expected=41523.776 actual=41523.7744140625 tol=20.0 | 0.000s |
| 87 | 09:34:45.387 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 05 | index=5 count=10 from=(63500.0, 41499.99999999999) to=(63479.775, 41514.695) radius_um=25.0 | to=(63479.775, 41514.695) | MoveXY -> (63479.775, 41514.695) um; [total=0.108s, att=1, conf=1, m=async] | 0.110s |
| 88 | 09:34:45.401 | xy 10-position pattern | PASS |  |  | xy: read 05 | index=5 count=10 from=(63500.0, 41499.99999999999) to=(63479.775, 41514.695) radius_um=25.0 | to=(63479.775, 41514.695) |  | 0.015s |
| 89 | 09:34:45.403 | xy 10-position pattern | PASS |  |  | xy: x readback 05 |  |  | expected=63479.775 actual=63479.77539062499 tol=20.0 | 0.000s |
| 90 | 09:34:45.404 | xy 10-position pattern | PASS |  |  | xy: y readback 05 |  |  | expected=41514.695 actual=41514.69238281249 tol=20.0 | 0.000s |
| 91 | 09:34:45.514 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 06 | index=6 count=10 from=(63500.0, 41499.99999999999) to=(63475.0, 41500.0) radius_um=25.0 | to=(63475.0, 41500.0) | MoveXY -> (63475.0, 41500.0) um; [total=0.108s, att=1, conf=1, m=async] | 0.110s |
| 92 | 09:34:45.528 | xy 10-position pattern | PASS |  |  | xy: read 06 | index=6 count=10 from=(63500.0, 41499.99999999999) to=(63475.0, 41500.0) radius_um=25.0 | to=(63475.0, 41500.0) |  | 0.000s |
| 93 | 09:34:45.530 | xy 10-position pattern | PASS |  |  | xy: x readback 06 |  |  | expected=63475.0 actual=63475.00000000001 tol=20.0 | 0.000s |
| 94 | 09:34:45.531 | xy 10-position pattern | PASS |  |  | xy: y readback 06 |  |  | expected=41500.0 actual=41499.99999999999 tol=20.0 | 0.000s |
| 95 | 09:34:45.609 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 07 | index=7 count=10 from=(63500.0, 41499.99999999999) to=(63479.775, 41485.305) radius_um=25.0 | to=(63479.775, 41485.305) | MoveXY -> (63479.775, 41485.305) um; [total=0.078s, att=1, conf=1, m=async] | 0.078s |
| 96 | 09:34:45.623 | xy 10-position pattern | PASS |  |  | xy: read 07 | index=7 count=10 from=(63500.0, 41499.99999999999) to=(63479.775, 41485.305) radius_um=25.0 | to=(63479.775, 41485.305) |  | 0.000s |
| 97 | 09:34:45.625 | xy 10-position pattern | PASS |  |  | xy: x readback 07 |  |  | expected=63479.775 actual=63479.77539062499 tol=20.0 | 0.000s |
| 98 | 09:34:45.626 | xy 10-position pattern | PASS |  |  | xy: y readback 07 |  |  | expected=41485.305 actual=41485.302734375 tol=20.0 | 0.000s |
| 99 | 09:34:45.726 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 08 | index=8 count=10 from=(63500.0, 41499.99999999999) to=(63492.275, 41476.224) radius_um=25.0 | to=(63492.275, 41476.224) | MoveXY -> (63492.275, 41476.224) um; [total=0.098s, att=1, conf=1, m=async] | 0.093s |
| 100 | 09:34:45.741 | xy 10-position pattern | PASS |  |  | xy: read 08 | index=8 count=10 from=(63500.0, 41499.99999999999) to=(63492.275, 41476.224) radius_um=25.0 | to=(63492.275, 41476.224) |  | 0.016s |
| 101 | 09:34:45.742 | xy 10-position pattern | PASS |  |  | xy: x readback 08 |  |  | expected=63492.275 actual=63492.27539062499 tol=20.0 | 0.000s |
| 102 | 09:34:45.743 | xy 10-position pattern | PASS |  |  | xy: y readback 08 |  |  | expected=41476.224 actual=41476.2255859375 tol=20.0 | 0.000s |
| 103 | 09:34:45.852 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 09 | index=9 count=10 from=(63500.0, 41499.99999999999) to=(63507.725, 41476.224) radius_um=25.0 | to=(63507.725, 41476.224) | MoveXY -> (63507.725, 41476.224) um; [total=0.108s, att=1, conf=1, m=async] | 0.109s |
| 104 | 09:34:45.867 | xy 10-position pattern | PASS |  |  | xy: read 09 | index=9 count=10 from=(63500.0, 41499.99999999999) to=(63507.725, 41476.224) radius_um=25.0 | to=(63507.725, 41476.224) |  | 0.016s |
| 105 | 09:34:45.868 | xy 10-position pattern | PASS |  |  | xy: x readback 09 |  |  | expected=63507.725 actual=63507.724609375 tol=20.0 | 0.000s |
| 106 | 09:34:45.869 | xy 10-position pattern | PASS |  |  | xy: y readback 09 |  |  | expected=41476.224 actual=41476.2255859375 tol=20.0 | 0.000s |
| 107 | 09:34:45.947 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 10 | index=10 count=10 from=(63500.0, 41499.99999999999) to=(63520.225, 41485.305) radius_um=25.0 | to=(63520.225, 41485.305) | MoveXY -> (63520.225, 41485.305) um; [total=0.077s, att=1, conf=1, m=async] | 0.078s |
| 108 | 09:34:45.961 | xy 10-position pattern | PASS |  |  | xy: read 10 | index=10 count=10 from=(63500.0, 41499.99999999999) to=(63520.225, 41485.305) radius_um=25.0 | to=(63520.225, 41485.305) |  | 0.016s |
| 109 | 09:34:45.963 | xy 10-position pattern | PASS |  |  | xy: x readback 10 |  |  | expected=63520.225 actual=63520.22460937499 tol=20.0 | 0.000s |
| 110 | 09:34:45.964 | xy 10-position pattern | PASS |  |  | xy: y readback 10 |  |  | expected=41485.305 actual=41485.302734375 tol=20.0 | 0.000s |
| 111 | 09:34:46.074 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: restore | restore_to=(63500.0, 41499.99999999999) positions=10 | restore_to=(63500.0, 41499.99999999999) | MoveXY -> (63500.0, 41499.99999999999) um; [total=0.108s, att=1, conf=1, m=async] | 0.109s |
| 112 | 09:34:46.089 | z-galvo round-trip | PASS |  |  | z: read start | job='HiRes' |  |  | 0.016s |
| 113 | 09:34:46.114 | z-galvo round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | z: move alternate | job='HiRes' from=0.0 to=2.0 | to=2.0 | Z -> 2.0 um (galvo); [total=0.022s, att=1, conf=1, m=async] | 0.031s |
| 114 | 09:34:46.130 | z-galvo round-trip | PASS |  |  | z: read alternate | job='HiRes' |  |  | 0.016s |
| 115 | 09:34:46.131 | z-galvo round-trip | PASS |  |  | z: readback |  |  | expected=2.0 actual=2.0 tol=1.0 | 0.000s |
| 116 | 09:34:46.159 | z-galvo round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | z: restore | restore_to=0.0 | restore_to=0.0 | Z -> 0.0 um (galvo); [total=0.026s, att=1, conf=1, m=async] | 0.031s |
| 117 | 09:34:46.160 | setup | SKIP |  |  | phase: objective |  |  | use --allow-objective to enable | 0.000s |
| 118 | 09:34:46.161 | setup | SKIP |  |  | phase: acquire |  |  | use --allow-acquire to enable | 0.000s |

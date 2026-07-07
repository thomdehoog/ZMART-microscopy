# Hardware validation run report

Every change this run attempted on the instrument is listed below, including failed attempts and restore/cleanup steps (see the *Mutates scope* column). Changes carry their success+CONFIRMED / success+UNCONFIRMED / FAILED result and attempt counts in the *Result* column.

## Run metadata

- **Validator**: `validate_hardware`
- **Arguments**: `--yes --allow-xy --allow-z --allow-missing-lasx --state-reader-mode hybrid --output=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\hardware_validate_hybrid.jsonl --report-dir=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report`
- **Backend**: live LAS X (simulator or scope)
- **Date**: 2026-07-07
- **Started / finished**: 09:35:02 / 09:35:20 (18.0s)
- **Host**: ZMB-Y42H93-STI8 (Windows-10-10.0.26100-SP0)
- **Python**: 3.11.15
- **Driver commit**: aecf1a2 on claude/smart-drivers-code-review-ky4phc (working tree has local changes)
- **Driver log**: `\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\driver_log_20260707-093502.log` (full log-line capture)

## Summary

| Phase | Actions attempted | Passed | Warned | Failed | Skipped | Confirmed | Unconfirmed |
|---|---:|---:|---:|---:|---:|---:|---:|
| setup | 3 | 1 | 0 | 0 | 2 | 0 | 0 |
| read-only | 7 | 7 | 0 | 0 | 0 | 0 | 0 |
| job selection round-trip | 11 | 8 | 2 | 0 | 1 | 3 | 0 |
| settings round-trip | 50 | 50 | 0 | 0 | 0 | 36 | 0 |
| xy 10-position pattern | 42 | 42 | 0 | 0 | 0 | 11 | 0 |
| z-galvo round-trip | 5 | 5 | 0 | 0 | 0 | 2 | 0 |
| **total** | **118** | **113** | **2** | **0** | **3** | **52** | **0** |

## Timing overview

### Per phase

| Phase | Timed actions | Min | Median | Max |
|---|---:|---:|---:|---:|
| read-only | 5 | 0.031s | 0.078s | 0.078s |
| job selection round-trip | 7 | 0.015s | 0.141s | 4.719s |
| settings round-trip | 37 | 0.015s | 0.031s | 2.047s |
| xy 10-position pattern | 19 | 0.015s | 0.078s | 0.125s |
| z-galvo round-trip | 4 | 0.015s | 0.023s | 0.079s |

### Slowest actions

| Duration | Phase | Action | Status |
|---:|---|---|---|
| 4.719s | job selection round-trip | job selection: select job | PASS |
| 2.047s | settings round-trip | image_format: write current | PASS |
| 1.828s | job selection round-trip | job selection: select job | PASS |
| 1.750s | settings round-trip | scan_resonant: restore | PASS |
| 1.656s | settings round-trip | scan_resonant: write alternate | PASS |
| 1.156s | job selection round-trip | job selection: select job | PASS |
| 0.234s | settings round-trip | scan_field_rotation: write alternate | PASS |
| 0.234s | settings round-trip | scan_field_rotation: write current | PASS |
| 0.203s | settings round-trip | scan_field_rotation: restore | PASS |
| 0.141s | job selection round-trip | job selection: read selected job | PASS |

### Unconfirmed / failed changes

None -- every attempted change reported success and confirmed.

## Chronological detail (every attempted action)

| # | Time | Phase | Status | Result | Mutates scope | Action attempted | Args / target | Expected | Observed | Duration |
|---:|---|---|---|---|---|---|---|---|---|---:|
| 1 | 09:35:03.128 | setup | PASS |  |  | limits: connect handshake | limits_path='<machine-local snapshot>' |  |  | 0.000s |
| 2 | 09:35:03.132 | read-only | PASS |  |  | ping |  |  |  | 0.000s |
| 3 | 09:35:03.214 | read-only | PASS |  |  | get_scan_status |  |  |  | 0.078s |
| 4 | 09:35:03.242 | read-only | PASS |  |  | get_jobs |  |  |  | 0.031s |
| 5 | 09:35:03.314 | read-only | PASS |  |  | get_hardware_info |  |  |  | 0.078s |
| 6 | 09:35:03.385 | read-only | PASS |  |  | get_xy |  |  |  | 0.063s |
| 7 | 09:35:03.387 | read-only | PASS |  |  | job: resolved | job='HiRes' |  |  | 0.000s |
| 8 | 09:35:03.455 | read-only | PASS |  |  | settings: read | job='HiRes' |  |  | 0.078s |
| 9 | 09:35:03.470 | job selection round-trip | PASS |  |  | job selection: read jobs | mode='api' |  |  | 0.015s |
| 10 | 09:35:08.252 | job selection round-trip | PASS | success+CONFIRMED att=2 conf=2 | YES | job selection: select job | index=0 count=3 job='AF Job' job_order=['AF Job', 'Overview', 'HiRes'] |  | SelectJob 'AF Job'; [total=4.651s, att=2, conf=2, m=async] | 4.719s |
| 11 | 09:35:08.276 | job selection round-trip | PASS |  |  | job selection: read selected job | index=0 count=3 job='AF Job' job_order=['AF Job', 'Overview', 'HiRes'] |  |  | 0.015s |
| 12 | 09:35:08.277 | job selection round-trip | WARN |  |  | job selection: API lag after log-confirmed AF Job | index=0 count=3 job='AF Job' job_order=['AF Job', 'Overview', 'HiRes'] expected='AF Job' api_selected='HiRes' confirmation_evidence='log' | expected='AF Job' | log confirmed 'AF Job'; immediate API read returned 'HiRes' | 0.000s |
| 13 | 09:35:10.110 | job selection round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | job selection: select job | index=1 count=3 job='Overview' job_order=['AF Job', 'Overview', 'HiRes'] |  | SelectJob 'Overview'; [total=1.764s, att=1, conf=1, m=async] | 1.828s |
| 14 | 09:35:10.253 | job selection round-trip | PASS |  |  | job selection: read selected job | index=1 count=3 job='Overview' job_order=['AF Job', 'Overview', 'HiRes'] |  |  | 0.141s |
| 15 | 09:35:10.254 | job selection round-trip | WARN |  |  | job selection: API lag after log-confirmed Overview | index=1 count=3 job='Overview' job_order=['AF Job', 'Overview', 'HiRes'] expected='Overview' api_selected='HiRes' confirmation_evidence='log' | expected='Overview' | log confirmed 'Overview'; immediate API read returned 'HiRes' | 0.000s |
| 16 | 09:35:11.412 | job selection round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | job selection: select job | index=2 count=3 job='HiRes' job_order=['AF Job', 'Overview', 'HiRes'] |  | SelectJob 'HiRes'; [total=1.079s, att=1, conf=1, m=async] | 1.156s |
| 17 | 09:35:11.442 | job selection round-trip | PASS |  |  | job selection: read selected job | index=2 count=3 job='HiRes' job_order=['AF Job', 'Overview', 'HiRes'] |  |  | 0.031s |
| 18 | 09:35:11.443 | job selection round-trip | PASS |  |  | job selection: confirmed HiRes |  |  | expected='HiRes' actual='HiRes' | 0.000s |
| 19 | 09:35:11.444 | job selection round-trip | SKIP |  |  | job selection: restore |  |  | 'HiRes' already confirmed by round-trip | 0.000s |
| 20 | 09:35:11.509 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | zoom: write current | job='HiRes' current=1.2499992052719082 target=5.0 | target=5.0 | Zoom -> 1.2499992052719082; [total=0.032s, att=1, conf=1, m=async] | 0.032s |
| 21 | 09:35:11.560 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | zoom: write alternate | job='HiRes' current=1.2499992052719082 target=5.0 | target=5.0 | Zoom -> 5.0; [total=0.048s, att=1, conf=1, m=async] | 0.046s |
| 22 | 09:35:11.585 | settings round-trip | PASS |  |  | zoom: readback |  |  | expected=5.0 actual=5.0000127156898895 tol=0.1 | 0.000s |
| 23 | 09:35:11.629 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | zoom: restore | job='HiRes' restore_to=1.2499992052719082 | restore_to=1.2499992052719082 | Zoom -> 1.2499992052719082; [total=0.042s, att=1, conf=1, m=async] | 0.047s |
| 24 | 09:35:11.717 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_speed: write current | job='HiRes' current=400 target=600 | target=600 | ScanSpeed -> 400; [total=0.056s, att=1, conf=1, m=async] | 0.047s |
| 25 | 09:35:11.782 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_speed: write alternate | job='HiRes' current=400 target=600 | target=600 | ScanSpeed -> 600; [total=0.064s, att=1, conf=1, m=async] | 0.063s |
| 26 | 09:35:11.814 | settings round-trip | PASS |  |  | scan_speed: readback |  |  | expected=600 actual=600 | 0.000s |
| 27 | 09:35:11.853 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_speed: restore | job='HiRes' restore_to=400 | restore_to=400 | ScanSpeed -> 400; [total=0.037s, att=1, conf=1, m=async] | 0.031s |
| 28 | 09:35:11.904 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_resonant: write current | job='HiRes' current=False target=True | target=True | Resonant -> False; [total=0.035s, att=1, conf=1, m=async] | 0.031s |
| 29 | 09:35:13.568 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_resonant: write alternate | job='HiRes' current=False target=True | target=True | Resonant -> True; [total=1.662s, att=1, conf=1, m=async] | 1.656s |
| 30 | 09:35:13.594 | settings round-trip | PASS |  |  | scan_resonant: readback |  |  | expected=True actual=True | 0.000s |
| 31 | 09:35:15.350 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_resonant: restore | job='HiRes' restore_to=False | restore_to=False | Resonant -> False; [total=1.753s, att=1, conf=1, m=async] | 1.750s |
| 32 | 09:35:15.365 | settings round-trip | PASS |  |  | scan_mode: read current | job='HiRes' |  |  | 0.016s |
| 33 | 09:35:15.366 | settings round-trip | PASS |  |  | scan_mode: is xyz |  |  | expected='xyz' actual='xyz' | 0.000s |
| 34 | 09:35:15.416 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | sequential_mode: write current | job='HiRes' current='Frame' target='Line' | target='Line' | SequentialMode -> Frame; [total=0.023s, att=1, conf=1, m=async] | 0.016s |
| 35 | 09:35:15.475 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | sequential_mode: write alternate | job='HiRes' current='Frame' target='Line' | target='Line' | SequentialMode -> Line; [total=0.058s, att=1, conf=1, m=async] | 0.062s |
| 36 | 09:35:15.490 | settings round-trip | PASS |  |  | sequential_mode: readback |  |  | expected='Line' actual='Line' | 0.000s |
| 37 | 09:35:15.577 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | sequential_mode: restore | job='HiRes' restore_to='Frame' | restore_to='Frame' | SequentialMode -> Frame; [total=0.084s, att=1, conf=1, m=async] | 0.078s |
| 38 | 09:35:15.820 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_field_rotation: write current | job='HiRes' current=0.0 target=5.0 | target=5.0 | Rotation -> 0.0; [total=0.228s, att=1, conf=1, m=async] | 0.234s |
| 39 | 09:35:16.047 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_field_rotation: write alternate | job='HiRes' current=0.0 target=5.0 | target=5.0 | Rotation -> 5.0; [total=0.225s, att=1, conf=1, m=async] | 0.234s |
| 40 | 09:35:16.063 | settings round-trip | PASS |  |  | scan_field_rotation: readback |  |  | expected=5.0 actual=5.0 tol=0.5 | 0.000s |
| 41 | 09:35:16.277 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_field_rotation: restore | job='HiRes' restore_to=0.0 | restore_to=0.0 | Rotation -> 0.0; [total=0.213s, att=1, conf=1, m=async] | 0.203s |
| 42 | 09:35:18.348 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | image_format: write current | job='HiRes' current='512 x 512' target='1024 x 1024' | target='1024 x 1024' | Format -> 512 x 512; [total=2.041s, att=1, conf=1, m=async] | 2.047s |
| 43 | 09:35:18.367 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | image_format: write alternate | job='HiRes' current='512 x 512' target='1024 x 1024' | target='1024 x 1024' | Format -> 1024 x 1024; [total=0.016s, att=1, conf=1, m=async] | 0.016s |
| 44 | 09:35:18.381 | settings round-trip | PASS |  |  | image_format: readback |  |  | expected='1024 x 1024' actual='1024 x 1024' | 0.000s |
| 45 | 09:35:18.400 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | image_format: restore | job='HiRes' restore_to='512 x 512' | restore_to='512 x 512' | Format -> 512 x 512; [total=0.017s, att=1, conf=1, m=async] | 0.015s |
| 46 | 09:35:18.448 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_accumulation: write current | job='HiRes' current=1 target=2 | target=2 | Setting[0].FrameAccumulation -> 1; [total=0.022s, att=1, conf=1, m=async] | 0.016s |
| 47 | 09:35:18.466 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_accumulation: write alternate | job='HiRes' current=1 target=2 | target=2 | Setting[0].FrameAccumulation -> 2; [total=0.017s, att=1, conf=1, m=async] | 0.016s |
| 48 | 09:35:18.482 | settings round-trip | PASS |  |  | frame_accumulation: readback |  |  | expected=2 actual=2 | 0.000s |
| 49 | 09:35:18.500 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_accumulation: restore | job='HiRes' restore_to=1 | restore_to=1 | Setting[0].FrameAccumulation -> 1; [total=0.017s, att=1, conf=1, m=async] | 0.032s |
| 50 | 09:35:18.543 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_average: write current | job='HiRes' current=1 target=2 | target=2 | Setting[0].FrameAverage -> 1; [total=0.021s, att=1, conf=1, m=async] | 0.016s |
| 51 | 09:35:18.561 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_average: write alternate | job='HiRes' current=1 target=2 | target=2 | Setting[0].FrameAverage -> 2; [total=0.017s, att=1, conf=1, m=async] | 0.015s |
| 52 | 09:35:18.580 | settings round-trip | PASS |  |  | frame_average: readback |  |  | expected=2 actual=2 | 0.000s |
| 53 | 09:35:18.598 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_average: restore | job='HiRes' restore_to=1 | restore_to=1 | Setting[0].FrameAverage -> 1; [total=0.016s, att=1, conf=1, m=async] | 0.015s |
| 54 | 09:35:18.634 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_accumulation: write current | job='HiRes' current=1 target=2 | target=2 | Setting[0].LineAccumulation -> 1; [total=0.020s, att=1, conf=1, m=async] | 0.016s |
| 55 | 09:35:18.652 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_accumulation: write alternate | job='HiRes' current=1 target=2 | target=2 | Setting[0].LineAccumulation -> 2; [total=0.016s, att=1, conf=1, m=async] | 0.015s |
| 56 | 09:35:18.667 | settings round-trip | PASS |  |  | line_accumulation: readback |  |  | expected=2 actual=2 | 0.000s |
| 57 | 09:35:18.695 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_accumulation: restore | job='HiRes' restore_to=1 | restore_to=1 | Setting[0].LineAccumulation -> 1; [total=0.027s, att=1, conf=1, m=async] | 0.031s |
| 58 | 09:35:18.731 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_average: write current | job='HiRes' current=1 target=2 | target=2 | Setting[0].LineAverage -> 1; [total=0.020s, att=1, conf=1, m=async] | 0.015s |
| 59 | 09:35:18.754 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_average: write alternate | job='HiRes' current=1 target=2 | target=2 | Setting[0].LineAverage -> 2; [total=0.021s, att=1, conf=1, m=async] | 0.032s |
| 60 | 09:35:18.769 | settings round-trip | PASS |  |  | line_average: readback |  |  | expected=2 actual=2 | 0.000s |
| 61 | 09:35:18.787 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_average: restore | job='HiRes' restore_to=1 | restore_to=1 | Setting[0].LineAverage -> 1; [total=0.017s, att=1, conf=1, m=async] | 0.016s |
| 62 | 09:35:18.829 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | pinhole_airy: write current | job='HiRes' current=1.0 target=1.2 | target=1.2 | Setting[0].PinholeAiry -> 1.0; [total=0.022s, att=1, conf=1, m=async] | 0.032s |
| 63 | 09:35:18.846 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | pinhole_airy: write alternate | job='HiRes' current=1.0 target=1.2 | target=1.2 | Setting[0].PinholeAiry -> 1.2; [total=0.016s, att=1, conf=1, m=async] | 0.015s |
| 64 | 09:35:18.867 | settings round-trip | PASS |  |  | pinhole_airy: readback |  |  | expected=1.2 actual=1.2 tol=0.05 | 0.000s |
| 65 | 09:35:18.936 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | pinhole_airy: restore | job='HiRes' restore_to=1.0 | restore_to=1.0 | Setting[0].PinholeAiry -> 1.0; [total=0.068s, att=1, conf=1, m=async] | 0.078s |
| 66 | 09:35:18.989 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | detector_gain: write current | job='HiRes' current=2.5 target=3.5 | target=3.5 | Setting[0].Detector[40;1].Gain -> 2.5; [total=0.024s, att=1, conf=1, m=async] | 0.031s |
| 67 | 09:35:19.007 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | detector_gain: write alternate | job='HiRes' current=2.5 target=3.5 | target=3.5 | Setting[0].Detector[40;1].Gain -> 3.5; [total=0.016s, att=1, conf=1, m=async] | 0.016s |
| 68 | 09:35:19.023 | settings round-trip | PASS |  |  | detector_gain: readback |  |  | expected=3.5 actual=3.5 tol=0.1 | 0.000s |
| 69 | 09:35:19.045 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | detector_gain: restore | job='HiRes' restore_to=2.5 | restore_to=2.5 | Setting[0].Detector[40;1].Gain -> 2.5; [total=0.021s, att=1, conf=1, m=async] | 0.016s |
| 70 | 09:35:19.059 | xy 10-position pattern | PASS |  |  | xy: read start | mode='api' purpose='stage-safety-anchor' |  |  | 0.000s |
| 71 | 09:35:19.171 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 01 | index=1 count=10 from=(63500.0, 41499.99999999999) to=(63525.0, 41500.0) radius_um=25.0 | to=(63525.0, 41500.0) | MoveXY -> (63525.0, 41500.0) um; [total=0.109s, att=1, conf=1, m=async] | 0.125s |
| 72 | 09:35:19.195 | xy 10-position pattern | PASS |  |  | xy: read 01 | index=1 count=10 from=(63500.0, 41499.99999999999) to=(63525.0, 41500.0) radius_um=25.0 | to=(63525.0, 41500.0) |  | 0.016s |
| 73 | 09:35:19.197 | xy 10-position pattern | PASS |  |  | xy: x readback 01 |  |  | expected=63525.0 actual=63525.0 tol=20.0 | 0.000s |
| 74 | 09:35:19.199 | xy 10-position pattern | PASS |  |  | xy: y readback 01 |  |  | expected=41500.0 actual=41499.99999999999 tol=20.0 | 0.000s |
| 75 | 09:35:19.308 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 02 | index=2 count=10 from=(63500.0, 41499.99999999999) to=(63520.225, 41514.695) radius_um=25.0 | to=(63520.225, 41514.695) | MoveXY -> (63520.225, 41514.695) um; [total=0.108s, att=1, conf=1, m=async] | 0.109s |
| 76 | 09:35:19.322 | xy 10-position pattern | PASS |  |  | xy: read 02 | index=2 count=10 from=(63500.0, 41499.99999999999) to=(63520.225, 41514.695) radius_um=25.0 | to=(63520.225, 41514.695) |  | 0.016s |
| 77 | 09:35:19.323 | xy 10-position pattern | PASS |  |  | xy: x readback 02 |  |  | expected=63520.225 actual=63520.22460937499 tol=20.0 | 0.000s |
| 78 | 09:35:19.325 | xy 10-position pattern | PASS |  |  | xy: y readback 02 |  |  | expected=41514.695 actual=41514.69238281249 tol=20.0 | 0.000s |
| 79 | 09:35:19.435 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 03 | index=3 count=10 from=(63500.0, 41499.99999999999) to=(63507.725, 41523.776) radius_um=25.0 | to=(63507.725, 41523.776) | MoveXY -> (63507.725, 41523.776) um; [total=0.109s, att=1, conf=1, m=async] | 0.109s |
| 80 | 09:35:19.449 | xy 10-position pattern | PASS |  |  | xy: read 03 | index=3 count=10 from=(63500.0, 41499.99999999999) to=(63507.725, 41523.776) radius_um=25.0 | to=(63507.725, 41523.776) |  | 0.016s |
| 81 | 09:35:19.450 | xy 10-position pattern | PASS |  |  | xy: x readback 03 |  |  | expected=63507.725 actual=63507.724609375 tol=20.0 | 0.000s |
| 82 | 09:35:19.452 | xy 10-position pattern | PASS |  |  | xy: y readback 03 |  |  | expected=41523.776 actual=41523.7744140625 tol=20.0 | 0.000s |
| 83 | 09:35:19.530 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 04 | index=4 count=10 from=(63500.0, 41499.99999999999) to=(63492.275, 41523.776) radius_um=25.0 | to=(63492.275, 41523.776) | MoveXY -> (63492.275, 41523.776) um; [total=0.076s, att=1, conf=1, m=async] | 0.078s |
| 84 | 09:35:19.544 | xy 10-position pattern | PASS |  |  | xy: read 04 | index=4 count=10 from=(63500.0, 41499.99999999999) to=(63492.275, 41523.776) radius_um=25.0 | to=(63492.275, 41523.776) |  | 0.000s |
| 85 | 09:35:19.546 | xy 10-position pattern | PASS |  |  | xy: x readback 04 |  |  | expected=63492.275 actual=63492.27539062499 tol=20.0 | 0.000s |
| 86 | 09:35:19.546 | xy 10-position pattern | PASS |  |  | xy: y readback 04 |  |  | expected=41523.776 actual=41523.7744140625 tol=20.0 | 0.000s |
| 87 | 09:35:19.657 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 05 | index=5 count=10 from=(63500.0, 41499.99999999999) to=(63479.775, 41514.695) radius_um=25.0 | to=(63479.775, 41514.695) | MoveXY -> (63479.775, 41514.695) um; [total=0.108s, att=1, conf=1, m=async] | 0.110s |
| 88 | 09:35:19.670 | xy 10-position pattern | PASS |  |  | xy: read 05 | index=5 count=10 from=(63500.0, 41499.99999999999) to=(63479.775, 41514.695) radius_um=25.0 | to=(63479.775, 41514.695) |  | 0.000s |
| 89 | 09:35:19.672 | xy 10-position pattern | PASS |  |  | xy: x readback 05 |  |  | expected=63479.775 actual=63479.77539062499 tol=20.0 | 0.000s |
| 90 | 09:35:19.673 | xy 10-position pattern | PASS |  |  | xy: y readback 05 |  |  | expected=41514.695 actual=41514.69238281249 tol=20.0 | 0.000s |
| 91 | 09:35:19.750 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 06 | index=6 count=10 from=(63500.0, 41499.99999999999) to=(63475.0, 41500.0) radius_um=25.0 | to=(63475.0, 41500.0) | MoveXY -> (63475.0, 41500.0) um; [total=0.075s, att=1, conf=1, m=async] | 0.079s |
| 92 | 09:35:19.768 | xy 10-position pattern | PASS |  |  | xy: read 06 | index=6 count=10 from=(63500.0, 41499.99999999999) to=(63475.0, 41500.0) radius_um=25.0 | to=(63475.0, 41500.0) |  | 0.015s |
| 93 | 09:35:19.770 | xy 10-position pattern | PASS |  |  | xy: x readback 06 |  |  | expected=63475.0 actual=63475.00000000001 tol=20.0 | 0.000s |
| 94 | 09:35:19.771 | xy 10-position pattern | PASS |  |  | xy: y readback 06 |  |  | expected=41500.0 actual=41499.99999999999 tol=20.0 | 0.000s |
| 95 | 09:35:19.871 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 07 | index=7 count=10 from=(63500.0, 41499.99999999999) to=(63479.775, 41485.305) radius_um=25.0 | to=(63479.775, 41485.305) | MoveXY -> (63479.775, 41485.305) um; [total=0.098s, att=1, conf=1, m=async] | 0.094s |
| 96 | 09:35:19.885 | xy 10-position pattern | PASS |  |  | xy: read 07 | index=7 count=10 from=(63500.0, 41499.99999999999) to=(63479.775, 41485.305) radius_um=25.0 | to=(63479.775, 41485.305) |  | 0.016s |
| 97 | 09:35:19.886 | xy 10-position pattern | PASS |  |  | xy: x readback 07 |  |  | expected=63479.775 actual=63479.77539062499 tol=20.0 | 0.000s |
| 98 | 09:35:19.887 | xy 10-position pattern | PASS |  |  | xy: y readback 07 |  |  | expected=41485.305 actual=41485.302734375 tol=20.0 | 0.000s |
| 99 | 09:35:19.996 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 08 | index=8 count=10 from=(63500.0, 41499.99999999999) to=(63492.275, 41476.224) radius_um=25.0 | to=(63492.275, 41476.224) | MoveXY -> (63492.275, 41476.224) um; [total=0.107s, att=1, conf=1, m=async] | 0.109s |
| 100 | 09:35:20.010 | xy 10-position pattern | PASS |  |  | xy: read 08 | index=8 count=10 from=(63500.0, 41499.99999999999) to=(63492.275, 41476.224) radius_um=25.0 | to=(63492.275, 41476.224) |  | 0.016s |
| 101 | 09:35:20.011 | xy 10-position pattern | PASS |  |  | xy: x readback 08 |  |  | expected=63492.275 actual=63492.27539062499 tol=20.0 | 0.000s |
| 102 | 09:35:20.013 | xy 10-position pattern | PASS |  |  | xy: y readback 08 |  |  | expected=41476.224 actual=41476.2255859375 tol=20.0 | 0.000s |
| 103 | 09:35:20.089 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 09 | index=9 count=10 from=(63500.0, 41499.99999999999) to=(63507.725, 41476.224) radius_um=25.0 | to=(63507.725, 41476.224) | MoveXY -> (63507.725, 41476.224) um; [total=0.075s, att=1, conf=1, m=async] | 0.078s |
| 104 | 09:35:20.103 | xy 10-position pattern | PASS |  |  | xy: read 09 | index=9 count=10 from=(63500.0, 41499.99999999999) to=(63507.725, 41476.224) radius_um=25.0 | to=(63507.725, 41476.224) |  | 0.015s |
| 105 | 09:35:20.104 | xy 10-position pattern | PASS |  |  | xy: x readback 09 |  |  | expected=63507.725 actual=63507.724609375 tol=20.0 | 0.000s |
| 106 | 09:35:20.106 | xy 10-position pattern | PASS |  |  | xy: y readback 09 |  |  | expected=41476.224 actual=41476.2255859375 tol=20.0 | 0.000s |
| 107 | 09:35:20.214 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 10 | index=10 count=10 from=(63500.0, 41499.99999999999) to=(63520.225, 41485.305) radius_um=25.0 | to=(63520.225, 41485.305) | MoveXY -> (63520.225, 41485.305) um; [total=0.107s, att=1, conf=1, m=async] | 0.110s |
| 108 | 09:35:20.228 | xy 10-position pattern | PASS |  |  | xy: read 10 | index=10 count=10 from=(63500.0, 41499.99999999999) to=(63520.225, 41485.305) radius_um=25.0 | to=(63520.225, 41485.305) |  | 0.015s |
| 109 | 09:35:20.229 | xy 10-position pattern | PASS |  |  | xy: x readback 10 |  |  | expected=63520.225 actual=63520.22460937499 tol=20.0 | 0.000s |
| 110 | 09:35:20.230 | xy 10-position pattern | PASS |  |  | xy: y readback 10 |  |  | expected=41485.305 actual=41485.302734375 tol=20.0 | 0.000s |
| 111 | 09:35:20.309 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: restore | restore_to=(63500.0, 41499.99999999999) positions=10 | restore_to=(63500.0, 41499.99999999999) | MoveXY -> (63500.0, 41499.99999999999) um; [total=0.076s, att=1, conf=1, m=async] | 0.078s |
| 112 | 09:35:20.384 | z-galvo round-trip | PASS |  |  | z: read start | job='HiRes' |  |  | 0.079s |
| 113 | 09:35:20.409 | z-galvo round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | z: move alternate | job='HiRes' from=0.0 to=2.0 | to=2.0 | Z -> 2.0 um (galvo); [total=0.022s, att=1, conf=1, m=async] | 0.031s |
| 114 | 09:35:20.424 | z-galvo round-trip | PASS |  |  | z: read alternate | job='HiRes' |  |  | 0.015s |
| 115 | 09:35:20.426 | z-galvo round-trip | PASS |  |  | z: readback |  |  | expected=2.0 actual=2.0 tol=1.0 | 0.000s |
| 116 | 09:35:20.445 | z-galvo round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | z: restore | restore_to=0.0 | restore_to=0.0 | Z -> 0.0 um (galvo); [total=0.017s, att=1, conf=1, m=async] | 0.016s |
| 117 | 09:35:20.446 | setup | SKIP |  |  | phase: objective |  |  | use --allow-objective to enable | 0.000s |
| 118 | 09:35:20.448 | setup | SKIP |  |  | phase: acquire |  |  | use --allow-acquire to enable | 0.000s |

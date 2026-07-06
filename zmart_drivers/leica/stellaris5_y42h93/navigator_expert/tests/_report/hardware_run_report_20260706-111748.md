# Hardware validation run report

Every change this run attempted on the instrument is listed below, including failed attempts and restore/cleanup steps (see the *Mutates scope* column). Changes carry their success+CONFIRMED / success+UNCONFIRMED / FAILED result and attempt counts in the *Result* column.

## Run metadata

- **Validator**: `validate_hardware`
- **Arguments**: `--yes --allow-xy --allow-z --allow-missing-lasx --state-reader-mode log --output=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\hardware_validate_log.jsonl --report-dir=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report`
- **Backend**: live LAS X (simulator or scope)
- **Date**: 2026-07-06
- **Started / finished**: 11:17:48 / 11:17:53 (5.5s)
- **Host**: ZMB-LASX-PC (Windows-10-10.0.26200-SP0)
- **Python**: 3.11.15
- **Driver commit**: unknown on unknown
- **Driver log**: `\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\driver_log_20260706-111748.log` (full log-line capture)

## Summary

| Phase | Actions attempted | Passed | Warned | Failed | Skipped | Confirmed | Unconfirmed |
|---|---:|---:|---:|---:|---:|---:|---:|
| setup | 3 | 1 | 0 | 0 | 2 | 0 | 0 |
| read-only | 7 | 7 | 0 | 0 | 0 | 0 | 0 |
| job selection round-trip | 14 | 13 | 0 | 0 | 1 | 3 | 0 |
| settings round-trip | 47 | 46 | 0 | 0 | 1 | 33 | 0 |
| xy 10-position pattern | 2 | 1 | 0 | 1 | 0 | 0 | 0 |
| z-galvo round-trip | 5 | 5 | 0 | 0 | 0 | 2 | 0 |
| **total** | **78** | **73** | **0** | **1** | **4** | **38** | **0** |

## Timing overview

### Per phase

| Phase | Timed actions | Min | Median | Max |
|---|---:|---:|---:|---:|
| read-only | 5 | 0.047s | 0.062s | 0.063s |
| job selection round-trip | 10 | 0.031s | 0.047s | 1.047s |
| settings round-trip | 34 | 0.015s | 0.016s | 0.141s |
| xy 10-position pattern | 1 | 0.015s | 0.015s | 0.015s |
| z-galvo round-trip | 4 | 0.015s | 0.016s | 0.063s |

### Slowest actions

| Duration | Phase | Action | Status |
|---:|---|---|---|
| 1.047s | job selection round-trip | job selection: select job | PASS |
| 0.875s | job selection round-trip | job selection: select job | PASS |
| 0.734s | job selection round-trip | job selection: select job | PASS |
| 0.156s | job selection round-trip | job selection: read selected job | PASS |
| 0.141s | settings round-trip | sequential_mode: write alternate | PASS |
| 0.063s | read-only | get_xy | PASS |
| 0.063s | z-galvo round-trip | z: read start | PASS |
| 0.062s | read-only | get_scan_status | PASS |
| 0.062s | read-only | get_hardware_info | PASS |
| 0.047s | settings round-trip | zoom: write current | PASS |

### Unconfirmed / failed changes

None -- every attempted change reported success and confirmed.

## Chronological detail (every attempted action)

| # | Time | Phase | Status | Result | Mutates scope | Action attempted | Args / target | Expected | Observed | Duration |
|---:|---|---|---|---|---|---|---|---|---|---:|
| 1 | 11:17:48.638 | setup | PASS |  |  | limits: connect handshake | limits_path='<machine-local snapshot>' |  |  | 0.000s |
| 2 | 11:17:48.638 | read-only | PASS |  |  | ping |  |  |  | 0.000s |
| 3 | 11:17:48.718 | read-only | PASS |  |  | get_scan_status |  |  |  | 0.062s |
| 4 | 11:17:48.765 | read-only | PASS |  |  | get_jobs |  |  |  | 0.047s |
| 5 | 11:17:48.828 | read-only | PASS |  |  | get_hardware_info |  |  |  | 0.062s |
| 6 | 11:17:48.876 | read-only | PASS |  |  | get_xy |  |  |  | 0.063s |
| 7 | 11:17:48.876 | read-only | PASS |  |  | job: resolved | job='Overview' |  |  | 0.000s |
| 8 | 11:17:48.923 | read-only | PASS |  |  | settings: read | job='Overview' |  |  | 0.047s |
| 9 | 11:17:48.964 | job selection round-trip | PASS |  |  | job selection: read jobs | mode='api' |  |  | 0.031s |
| 10 | 11:17:49.744 | job selection round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | job selection: select job | index=0 count=3 job='AF Job' job_order=['AF Job', 'HiRes', 'Overview'] |  | SelectJob 'AF Job'; [total=0.682s, att=1, conf=1, m=async] | 0.734s |
| 11 | 11:17:49.796 | job selection round-trip | PASS |  |  | job selection: log poll confirmed AF Job | index=0 count=3 job='AF Job' job_order=['AF Job', 'HiRes', 'Overview'] log_poll={'success': True, 'value': 'AF Job', 'matched_at': 1783329469.621, 'attempts': … |  | matched; last_reason=matched; value='AF Job'; log_event_delta=0.610s; api_select_elapsed=0.682s; attempts=1 | 0.047s |
| 12 | 11:17:49.825 | job selection round-trip | PASS |  |  | job selection: read selected job | index=0 count=3 job='AF Job' job_order=['AF Job', 'HiRes', 'Overview'] |  |  | 0.031s |
| 13 | 11:17:49.825 | job selection round-trip | PASS |  |  | job selection: confirmed AF Job |  |  | expected='AF Job' actual='AF Job' | 0.000s |
| 14 | 11:17:50.868 | job selection round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | job selection: select job | index=1 count=3 job='HiRes' job_order=['AF Job', 'HiRes', 'Overview'] |  | SelectJob 'HiRes'; [total=0.991s, att=1, conf=1, m=async] | 1.047s |
| 15 | 11:17:50.922 | job selection round-trip | PASS |  |  | job selection: log poll confirmed HiRes | index=1 count=3 job='HiRes' job_order=['AF Job', 'HiRes', 'Overview'] log_poll={'success': True, 'value': 'HiRes', 'matched_at': 1783329470.719, 'attempts': 1,… |  | matched; last_reason=matched; value='HiRes'; log_event_delta=0.894s; api_select_elapsed=0.991s; attempts=1 | 0.047s |
| 16 | 11:17:50.940 | job selection round-trip | PASS |  |  | job selection: read selected job | index=1 count=3 job='HiRes' job_order=['AF Job', 'HiRes', 'Overview'] |  |  | 0.031s |
| 17 | 11:17:50.940 | job selection round-trip | PASS |  |  | job selection: confirmed HiRes |  |  | expected='HiRes' actual='HiRes' | 0.000s |
| 18 | 11:17:51.829 | job selection round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | job selection: select job | index=2 count=3 job='Overview' job_order=['AF Job', 'HiRes', 'Overview'] |  | SelectJob 'Overview'; [total=0.833s, att=1, conf=1, m=async] | 0.875s |
| 19 | 11:17:51.885 | job selection round-trip | PASS |  |  | job selection: log poll confirmed Overview | index=2 count=3 job='Overview' job_order=['AF Job', 'HiRes', 'Overview'] log_poll={'success': True, 'value': 'Overview', 'matched_at': 1783329471.803, 'attempt… |  | matched; last_reason=matched; value='Overview'; log_event_delta=0.862s; api_select_elapsed=0.833s; attempts=1 | 0.031s |
| 20 | 11:17:52.043 | job selection round-trip | PASS |  |  | job selection: read selected job | index=2 count=3 job='Overview' job_order=['AF Job', 'HiRes', 'Overview'] |  |  | 0.156s |
| 21 | 11:17:52.043 | job selection round-trip | PASS |  |  | job selection: confirmed Overview |  |  | expected='Overview' actual='Overview' | 0.000s |
| 22 | 11:17:52.043 | job selection round-trip | SKIP |  |  | job selection: restore |  |  | 'Overview' already confirmed by round-trip | 0.000s |
| 23 | 11:17:52.106 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | zoom: write current | job='Overview' current=2.0 target=5.0 | target=5.0 | Zoom -> 2.0; [total=0.047s, att=1, conf=1, m=async] | 0.047s |
| 24 | 11:17:52.144 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | zoom: write alternate | job='Overview' current=2.0 target=5.0 | target=5.0 | Zoom -> 5.0; [total=0.036s, att=1, conf=1, m=async] | 0.047s |
| 25 | 11:17:52.160 | settings round-trip | PASS |  |  | zoom: readback |  |  | expected=5.0 actual=5.0000127156898895 tol=0.1 | 0.000s |
| 26 | 11:17:52.178 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | zoom: restore | job='Overview' restore_to=2.0 | restore_to=2.0 | Zoom -> 2.0; [total=0.016s, att=1, conf=1, m=async] | 0.016s |
| 27 | 11:17:52.210 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_speed: write current | job='Overview' current=400 target=600 | target=600 | ScanSpeed -> 400; [total=0.019s, att=1, conf=1, m=async] | 0.016s |
| 28 | 11:17:52.228 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_speed: write alternate | job='Overview' current=400 target=600 | target=600 | ScanSpeed -> 600; [total=0.016s, att=1, conf=1, m=async] | 0.016s |
| 29 | 11:17:52.252 | settings round-trip | PASS |  |  | scan_speed: readback |  |  | expected=600 actual=600 | 0.000s |
| 30 | 11:17:52.273 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_speed: restore | job='Overview' restore_to=400 | restore_to=400 | ScanSpeed -> 400; [total=0.020s, att=1, conf=1, m=async] | 0.016s |
| 31 | 11:17:52.320 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_resonant: write current | job='Overview' current=False target=True | target=True | Resonant -> False; [total=0.022s, att=1, conf=1, m=async] | 0.015s |
| 32 | 11:17:52.338 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_resonant: write alternate | job='Overview' current=False target=True | target=True | Resonant -> True; [total=0.016s, att=1, conf=1, m=async] | 0.016s |
| 33 | 11:17:52.363 | settings round-trip | PASS |  |  | scan_resonant: readback |  |  | expected=True actual=True | 0.000s |
| 34 | 11:17:52.380 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_resonant: restore | job='Overview' restore_to=False | restore_to=False | Resonant -> False; [total=0.015s, att=1, conf=1, m=async] | 0.016s |
| 35 | 11:17:52.395 | settings round-trip | PASS |  |  | scan_mode: read current | job='Overview' |  |  | 0.016s |
| 36 | 11:17:52.396 | settings round-trip | PASS |  |  | scan_mode: is xyz |  |  | expected='xyz' actual='xyz' | 0.000s |
| 37 | 11:17:52.444 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | sequential_mode: write current | job='Overview' current='Line' target='Frame' | target='Frame' | SequentialMode -> Line; [total=0.025s, att=1, conf=1, m=async] | 0.031s |
| 38 | 11:17:52.587 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | sequential_mode: write alternate | job='Overview' current='Line' target='Frame' | target='Frame' | SequentialMode -> Frame; [total=0.140s, att=1, conf=1, m=async] | 0.141s |
| 39 | 11:17:52.615 | settings round-trip | PASS |  |  | sequential_mode: readback |  |  | expected='Frame' actual='Frame' | 0.000s |
| 40 | 11:17:52.630 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | sequential_mode: restore | job='Overview' restore_to='Line' | restore_to='Line' | SequentialMode -> Line; [total=0.015s, att=1, conf=1, m=async] | 0.016s |
| 41 | 11:17:52.683 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_field_rotation: write current | job='Overview' current=0.0 target=5.0 | target=5.0 | Rotation -> 0.0; [total=0.028s, att=1, conf=1, m=async] | 0.031s |
| 42 | 11:17:52.711 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_field_rotation: write alternate | job='Overview' current=0.0 target=5.0 | target=5.0 | Rotation -> 5.0; [total=0.025s, att=1, conf=1, m=async] | 0.031s |
| 43 | 11:17:52.727 | settings round-trip | PASS |  |  | scan_field_rotation: readback |  |  | expected=5.0 actual=5.0 tol=0.5 | 0.000s |
| 44 | 11:17:52.742 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_field_rotation: restore | job='Overview' restore_to=0.0 | restore_to=0.0 | Rotation -> 0.0; [total=0.015s, att=1, conf=1, m=async] | 0.015s |
| 45 | 11:17:52.780 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | image_format: write current | job='Overview' current='512 x 512' target='1024 x 1024' | target='1024 x 1024' | Format -> 512 x 512; [total=0.020s, att=1, conf=1, m=async] | 0.016s |
| 46 | 11:17:52.822 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | image_format: write alternate | job='Overview' current='512 x 512' target='1024 x 1024' | target='1024 x 1024' | Format -> 1024 x 1024; [total=0.041s, att=1, conf=1, m=async] | 0.046s |
| 47 | 11:17:52.835 | settings round-trip | PASS |  |  | image_format: readback |  |  | expected='1024 x 1024' actual='1024 x 1024' | 0.000s |
| 48 | 11:17:52.852 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | image_format: restore | job='Overview' restore_to='512 x 512' | restore_to='512 x 512' | Format -> 512 x 512; [total=0.015s, att=1, conf=1, m=async] | 0.016s |
| 49 | 11:17:52.894 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_accumulation: write current | job='Overview' current=1 target=2 | target=2 | Setting[0].FrameAccumulation -> 1; [total=0.019s, att=1, conf=1, m=async] | 0.016s |
| 50 | 11:17:52.911 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_accumulation: write alternate | job='Overview' current=1 target=2 | target=2 | Setting[0].FrameAccumulation -> 2; [total=0.014s, att=1, conf=1, m=async] | 0.015s |
| 51 | 11:17:52.927 | settings round-trip | PASS |  |  | frame_accumulation: readback |  |  | expected=2 actual=2 | 0.000s |
| 52 | 11:17:52.941 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_accumulation: restore | job='Overview' restore_to=1 | restore_to=1 | Setting[0].FrameAccumulation -> 1; [total=0.015s, att=1, conf=1, m=async] | 0.015s |
| 53 | 11:17:52.995 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_average: write current | job='Overview' current=1 target=2 | target=2 | Setting[0].FrameAverage -> 1; [total=0.029s, att=1, conf=1, m=async] | 0.031s |
| 54 | 11:17:53.017 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_average: write alternate | job='Overview' current=1 target=2 | target=2 | Setting[0].FrameAverage -> 2; [total=0.021s, att=1, conf=1, m=async] | 0.032s |
| 55 | 11:17:53.035 | settings round-trip | PASS |  |  | frame_average: readback |  |  | expected=2 actual=2 | 0.000s |
| 56 | 11:17:53.063 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_average: restore | job='Overview' restore_to=1 | restore_to=1 | Setting[0].FrameAverage -> 1; [total=0.027s, att=1, conf=1, m=async] | 0.016s |
| 57 | 11:17:53.096 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_accumulation: write current | job='Overview' current=1 target=2 | target=2 | Setting[0].LineAccumulation -> 1; [total=0.019s, att=1, conf=1, m=async] | 0.032s |
| 58 | 11:17:53.121 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_accumulation: write alternate | job='Overview' current=1 target=2 | target=2 | Setting[0].LineAccumulation -> 2; [total=0.022s, att=1, conf=1, m=async] | 0.015s |
| 59 | 11:17:53.135 | settings round-trip | PASS |  |  | line_accumulation: readback |  |  | expected=2 actual=2 | 0.000s |
| 60 | 11:17:53.151 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_accumulation: restore | job='Overview' restore_to=1 | restore_to=1 | Setting[0].LineAccumulation -> 1; [total=0.015s, att=1, conf=1, m=async] | 0.016s |
| 61 | 11:17:53.185 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_average: write current | job='Overview' current=1 target=2 | target=2 | Setting[0].LineAverage -> 1; [total=0.018s, att=1, conf=1, m=async] | 0.016s |
| 62 | 11:17:53.206 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_average: write alternate | job='Overview' current=1 target=2 | target=2 | Setting[0].LineAverage -> 2; [total=0.020s, att=1, conf=1, m=async] | 0.031s |
| 63 | 11:17:53.220 | settings round-trip | PASS |  |  | line_average: readback |  |  | expected=2 actual=2 | 0.000s |
| 64 | 11:17:53.238 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_average: restore | job='Overview' restore_to=1 | restore_to=1 | Setting[0].LineAverage -> 1; [total=0.015s, att=1, conf=1, m=async] | 0.015s |
| 65 | 11:17:53.272 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | pinhole_airy: write current | job='Overview' current=1.0 target=1.2 | target=1.2 | Setting[0].PinholeAiry -> 1.0; [total=0.020s, att=1, conf=1, m=async] | 0.016s |
| 66 | 11:17:53.294 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | pinhole_airy: write alternate | job='Overview' current=1.0 target=1.2 | target=1.2 | Setting[0].PinholeAiry -> 1.2; [total=0.021s, att=1, conf=1, m=async] | 0.015s |
| 67 | 11:17:53.310 | settings round-trip | PASS |  |  | pinhole_airy: readback |  |  | expected=1.2 actual=1.2 tol=0.05 | 0.000s |
| 68 | 11:17:53.343 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | pinhole_airy: restore | job='Overview' restore_to=1.0 | restore_to=1.0 | Setting[0].PinholeAiry -> 1.0; [total=0.030s, att=1, conf=1, m=async] | 0.031s |
| 69 | 11:17:53.397 | settings round-trip | SKIP |  |  | detector_gain: round-trip |  |  | HyD 2 exposes no writable gain range; not mutating gain | 0.000s |
| 70 | 11:17:53.412 | xy 10-position pattern | PASS |  |  | xy: read start | mode='api' purpose='stage-safety-anchor' |  |  | 0.015s |
| 71 | 11:17:53.412 | xy 10-position pattern | FAIL |  |  | xy: pattern | position=(0.0, 0.0) limits={'x_min': 1000.0, 'x_max': 130000.0, 'y_min': 1000.0, 'y_max': 100000.0, 'z_galvo_min': -200.0, 'z_galvo_max': 200.0, 'z_wide_min': … |  | starting position outside limits: X=0.0 outside calibrated limits [1000.0, 130000.0]. Configure LAS X simulator/hardware inside the calibrated envelope, or omit --allow-xy. | 0.000s |
| 72 | 11:17:53.474 | z-galvo round-trip | PASS |  |  | z: read start | job='Overview' |  |  | 0.063s |
| 73 | 11:17:53.500 | z-galvo round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | z: move alternate | job='Overview' from=0.0 to=2.0 | to=2.0 | Z -> 2.0 um (galvo); [total=0.021s, att=1, conf=1, m=async] | 0.015s |
| 74 | 11:17:53.513 | z-galvo round-trip | PASS |  |  | z: read alternate | job='Overview' |  |  | 0.016s |
| 75 | 11:17:53.515 | z-galvo round-trip | PASS |  |  | z: readback |  |  | expected=2.0 actual=2.0 tol=1.0 | 0.000s |
| 76 | 11:17:53.531 | z-galvo round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | z: restore | restore_to=0.0 | restore_to=0.0 | Z -> 0.0 um (galvo); [total=0.015s, att=1, conf=1, m=async] | 0.016s |
| 77 | 11:17:53.531 | setup | SKIP |  |  | phase: objective |  |  | use --allow-objective to enable | 0.000s |
| 78 | 11:17:53.533 | setup | SKIP |  |  | phase: acquire |  |  | use --allow-acquire to enable | 0.000s |

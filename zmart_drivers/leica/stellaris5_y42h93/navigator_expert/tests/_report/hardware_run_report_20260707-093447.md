# Hardware validation run report

Every change this run attempted on the instrument is listed below, including failed attempts and restore/cleanup steps (see the *Mutates scope* column). Changes carry their success+CONFIRMED / success+UNCONFIRMED / FAILED result and attempt counts in the *Result* column.

## Run metadata

- **Validator**: `validate_hardware`
- **Arguments**: `--yes --allow-xy --allow-z --allow-missing-lasx --state-reader-mode log --output=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\hardware_validate_log.jsonl --report-dir=\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report`
- **Backend**: live LAS X (simulator or scope)
- **Date**: 2026-07-07
- **Started / finished**: 09:34:47 / 09:35:01 (13.8s)
- **Host**: ZMB-Y42H93-STI8 (Windows-10-10.0.26100-SP0)
- **Python**: 3.11.15
- **Driver commit**: aecf1a2 on claude/smart-drivers-code-review-ky4phc (working tree has local changes)
- **Driver log**: `\\zmbstaff.core.uzh.ch\zmbstaff\10374\Protocols_Notes\thom\notes\repositories\smart-microscopy\zmart_drivers\leica\stellaris5_y42h93\navigator_expert\tests\_report\driver_log_20260707-093447.log` (full log-line capture)

## Summary

| Phase | Actions attempted | Passed | Warned | Failed | Skipped | Confirmed | Unconfirmed |
|---|---:|---:|---:|---:|---:|---:|---:|
| setup | 3 | 1 | 0 | 0 | 2 | 0 | 0 |
| read-only | 9 | 8 | 0 | 0 | 1 | 0 | 0 |
| job selection round-trip | 14 | 11 | 2 | 0 | 1 | 3 | 0 |
| settings round-trip | 50 | 50 | 0 | 0 | 0 | 36 | 0 |
| xy 10-position pattern | 42 | 42 | 0 | 0 | 0 | 11 | 0 |
| z-galvo round-trip | 5 | 5 | 0 | 0 | 0 | 2 | 0 |
| **total** | **123** | **117** | **2** | **0** | **4** | **52** | **0** |

## Timing overview

### Per phase

| Phase | Timed actions | Min | Median | Max |
|---|---:|---:|---:|---:|
| read-only | 5 | 0.032s | 0.062s | 0.078s |
| job selection round-trip | 9 | 0.016s | 0.047s | 2.343s |
| settings round-trip | 37 | 0.015s | 0.031s | 1.813s |
| xy 10-position pattern | 18 | 0.015s | 0.070s | 0.125s |
| z-galvo round-trip | 3 | 0.016s | 0.016s | 0.062s |

### Slowest actions

| Duration | Phase | Action | Status |
|---:|---|---|---|
| 2.343s | job selection round-trip | job selection: select job | PASS |
| 1.859s | job selection round-trip | job selection: select job | PASS |
| 1.813s | settings round-trip | scan_resonant: write alternate | PASS |
| 1.750s | settings round-trip | scan_resonant: restore | PASS |
| 1.063s | job selection round-trip | job selection: select job | PASS |
| 0.235s | settings round-trip | scan_field_rotation: write current | PASS |
| 0.235s | settings round-trip | scan_field_rotation: restore | PASS |
| 0.219s | settings round-trip | scan_field_rotation: write alternate | PASS |
| 0.125s | xy 10-position pattern | xy: move 02 | PASS |
| 0.110s | settings round-trip | sequential_mode: restore | PASS |

### Unconfirmed / failed changes

None -- every attempted change reported success and confirmed.

## Chronological detail (every attempted action)

| # | Time | Phase | Status | Result | Mutates scope | Action attempted | Args / target | Expected | Observed | Duration |
|---:|---|---|---|---|---|---|---|---|---|---:|
| 1 | 09:34:48.100 | setup | PASS |  |  | limits: connect handshake | limits_path='<machine-local snapshot>' |  |  | 0.000s |
| 2 | 09:34:48.107 | read-only | PASS |  |  | ping |  |  |  | 0.000s |
| 3 | 09:34:48.177 | read-only | PASS |  |  | get_scan_status |  |  |  | 0.078s |
| 4 | 09:34:48.179 | read-only | PASS |  |  | get_jobs |  |  |  | 0.000s |
| 5 | 09:34:48.239 | read-only | PASS |  |  | get_hardware_info |  |  |  | 0.063s |
| 6 | 09:34:48.299 | read-only | PASS |  |  | get_xy |  |  |  | 0.062s |
| 7 | 09:34:48.300 | read-only | SKIP |  |  | job: resolve |  |  | job list is API-only (no log leg); enumerating via API | 0.000s |
| 8 | 09:34:48.330 | read-only | PASS |  |  | job: resolve api control for log experiment | purpose='drive log selected-job poll' |  |  | 0.032s |
| 9 | 09:34:48.332 | read-only | PASS |  |  | job: resolved | job='HiRes' |  |  | 0.000s |
| 10 | 09:34:48.391 | read-only | PASS |  |  | settings: read | job='HiRes' |  |  | 0.062s |
| 11 | 09:34:48.406 | job selection round-trip | PASS |  |  | job selection: read jobs | mode='api' |  |  | 0.016s |
| 12 | 09:34:50.810 | job selection round-trip | PASS | success+CONFIRMED att=2 conf=2 | YES | job selection: select job | index=0 count=3 job='AF Job' job_order=['AF Job', 'Overview', 'HiRes'] |  | SelectJob 'AF Job'; [total=2.296s, att=2, conf=2, m=async] | 2.343s |
| 13 | 09:34:50.873 | job selection round-trip | PASS |  |  | job selection: log poll confirmed AF Job | index=0 count=3 job='AF Job' job_order=['AF Job', 'Overview', 'HiRes'] log_poll={'success': True, 'value': 'AF Job', 'matched_at': 1783409690.63, 'attempts': 1… |  | matched; last_reason=matched; value='AF Job'; log_event_delta=2.177s; api_select_elapsed=2.296s; attempts=1 | 0.047s |
| 14 | 09:34:50.935 | job selection round-trip | PASS |  |  | job selection: read selected job | index=0 count=3 job='AF Job' job_order=['AF Job', 'Overview', 'HiRes'] |  |  | 0.046s |
| 15 | 09:34:50.937 | job selection round-trip | WARN |  |  | job selection: API lag after log-confirmed AF Job | index=0 count=3 job='AF Job' job_order=['AF Job', 'Overview', 'HiRes'] expected='AF Job' api_selected='HiRes' confirmation_evidence='log' | expected='AF Job' | log confirmed 'AF Job'; immediate API read returned 'HiRes' | 0.000s |
| 16 | 09:34:52.813 | job selection round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | job selection: select job | index=1 count=3 job='Overview' job_order=['AF Job', 'Overview', 'HiRes'] |  | SelectJob 'Overview'; [total=1.810s, att=1, conf=1, m=async] | 1.859s |
| 17 | 09:34:52.873 | job selection round-trip | PASS |  |  | job selection: log poll confirmed Overview | index=1 count=3 job='Overview' job_order=['AF Job', 'Overview', 'HiRes'] log_poll={'success': True, 'value': 'Overview', 'matched_at': 1783409692.62, 'attempts… |  | matched; last_reason=matched; value='Overview'; log_event_delta=1.682s; api_select_elapsed=1.810s; attempts=1 | 0.047s |
| 18 | 09:34:52.929 | job selection round-trip | PASS |  |  | job selection: read selected job | index=1 count=3 job='Overview' job_order=['AF Job', 'Overview', 'HiRes'] |  |  | 0.046s |
| 19 | 09:34:52.931 | job selection round-trip | WARN |  |  | job selection: API lag after log-confirmed Overview | index=1 count=3 job='Overview' job_order=['AF Job', 'Overview', 'HiRes'] expected='Overview' api_selected='HiRes' confirmation_evidence='log' | expected='Overview' | log confirmed 'Overview'; immediate API read returned 'HiRes' | 0.000s |
| 20 | 09:34:54.000 | job selection round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | job selection: select job | index=2 count=3 job='HiRes' job_order=['AF Job', 'Overview', 'HiRes'] |  | SelectJob 'HiRes'; [total=1.008s, att=1, conf=1, m=async] | 1.063s |
| 21 | 09:34:54.062 | job selection round-trip | PASS |  |  | job selection: log poll confirmed HiRes | index=2 count=3 job='HiRes' job_order=['AF Job', 'Overview', 'HiRes'] log_poll={'success': True, 'value': 'HiRes', 'matched_at': 1783409693.889, 'attempts': 1,… |  | matched; last_reason=matched; value='HiRes'; log_event_delta=0.957s; api_select_elapsed=1.008s; attempts=1 | 0.046s |
| 22 | 09:34:54.076 | job selection round-trip | PASS |  |  | job selection: read selected job | index=2 count=3 job='HiRes' job_order=['AF Job', 'Overview', 'HiRes'] |  |  | 0.000s |
| 23 | 09:34:54.077 | job selection round-trip | PASS |  |  | job selection: confirmed HiRes |  |  | expected='HiRes' actual='HiRes' | 0.000s |
| 24 | 09:34:54.079 | job selection round-trip | SKIP |  |  | job selection: restore |  |  | 'HiRes' already confirmed by round-trip | 0.000s |
| 25 | 09:34:54.125 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | zoom: write current | job='HiRes' current=1.2499992052719082 target=5.0 | target=5.0 | Zoom -> 1.2499992052719082; [total=0.021s, att=1, conf=1, m=async] | 0.032s |
| 26 | 09:34:54.163 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | zoom: write alternate | job='HiRes' current=1.2499992052719082 target=5.0 | target=5.0 | Zoom -> 5.0; [total=0.037s, att=1, conf=1, m=async] | 0.031s |
| 27 | 09:34:54.188 | settings round-trip | PASS |  |  | zoom: readback |  |  | expected=5.0 actual=5.0000127156898895 tol=0.1 | 0.000s |
| 28 | 09:34:54.229 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | zoom: restore | job='HiRes' restore_to=1.2499992052719082 | restore_to=1.2499992052719082 | Zoom -> 1.2499992052719082; [total=0.038s, att=1, conf=1, m=async] | 0.031s |
| 29 | 09:34:54.285 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_speed: write current | job='HiRes' current=400 target=600 | target=600 | ScanSpeed -> 400; [total=0.040s, att=1, conf=1, m=async] | 0.047s |
| 30 | 09:34:54.323 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_speed: write alternate | job='HiRes' current=400 target=600 | target=600 | ScanSpeed -> 600; [total=0.037s, att=1, conf=1, m=async] | 0.031s |
| 31 | 09:34:54.349 | settings round-trip | PASS |  |  | scan_speed: readback |  |  | expected=600 actual=600 | 0.000s |
| 32 | 09:34:54.399 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_speed: restore | job='HiRes' restore_to=400 | restore_to=400 | ScanSpeed -> 400; [total=0.048s, att=1, conf=1, m=async] | 0.047s |
| 33 | 09:34:54.434 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_resonant: write current | job='HiRes' current=False target=True | target=True | Resonant -> False; [total=0.019s, att=1, conf=1, m=async] | 0.015s |
| 34 | 09:34:56.235 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_resonant: write alternate | job='HiRes' current=False target=True | target=True | Resonant -> True; [total=1.799s, att=1, conf=1, m=async] | 1.813s |
| 35 | 09:34:56.269 | settings round-trip | PASS |  |  | scan_resonant: readback |  |  | expected=True actual=True | 0.000s |
| 36 | 09:34:58.022 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_resonant: restore | job='HiRes' restore_to=False | restore_to=False | Resonant -> False; [total=1.752s, att=1, conf=1, m=async] | 1.750s |
| 37 | 09:34:58.038 | settings round-trip | PASS |  |  | scan_mode: read current | job='HiRes' |  |  | 0.016s |
| 38 | 09:34:58.039 | settings round-trip | PASS |  |  | scan_mode: is xyz |  |  | expected='xyz' actual='xyz' | 0.000s |
| 39 | 09:34:58.087 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | sequential_mode: write current | job='HiRes' current='Frame' target='Line' | target='Line' | SequentialMode -> Frame; [total=0.021s, att=1, conf=1, m=async] | 0.016s |
| 40 | 09:34:58.158 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | sequential_mode: write alternate | job='HiRes' current='Frame' target='Line' | target='Line' | SequentialMode -> Line; [total=0.069s, att=1, conf=1, m=async] | 0.078s |
| 41 | 09:34:58.184 | settings round-trip | PASS |  |  | sequential_mode: readback |  |  | expected='Line' actual='Line' | 0.000s |
| 42 | 09:34:58.286 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | sequential_mode: restore | job='HiRes' restore_to='Frame' | restore_to='Frame' | SequentialMode -> Frame; [total=0.100s, att=1, conf=1, m=async] | 0.110s |
| 43 | 09:34:58.539 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_field_rotation: write current | job='HiRes' current=0.0 target=5.0 | target=5.0 | Rotation -> 0.0; [total=0.226s, att=1, conf=1, m=async] | 0.235s |
| 44 | 09:34:58.763 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_field_rotation: write alternate | job='HiRes' current=0.0 target=5.0 | target=5.0 | Rotation -> 5.0; [total=0.223s, att=1, conf=1, m=async] | 0.219s |
| 45 | 09:34:58.779 | settings round-trip | PASS |  |  | scan_field_rotation: readback |  |  | expected=5.0 actual=5.0 tol=0.5 | 0.000s |
| 46 | 09:34:59.013 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | scan_field_rotation: restore | job='HiRes' restore_to=0.0 | restore_to=0.0 | Rotation -> 0.0; [total=0.234s, att=1, conf=1, m=async] | 0.235s |
| 47 | 09:34:59.052 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | image_format: write current | job='HiRes' current='512 x 512' target='1024 x 1024' | target='1024 x 1024' | Format -> 512 x 512; [total=0.022s, att=1, conf=1, m=async] | 0.031s |
| 48 | 09:34:59.070 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | image_format: write alternate | job='HiRes' current='512 x 512' target='1024 x 1024' | target='1024 x 1024' | Format -> 1024 x 1024; [total=0.017s, att=1, conf=1, m=async] | 0.016s |
| 49 | 09:34:59.087 | settings round-trip | PASS |  |  | image_format: readback |  |  | expected='1024 x 1024' actual='1024 x 1024' | 0.000s |
| 50 | 09:34:59.105 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | image_format: restore | job='HiRes' restore_to='512 x 512' | restore_to='512 x 512' | Format -> 512 x 512; [total=0.016s, att=1, conf=1, m=async] | 0.015s |
| 51 | 09:34:59.148 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_accumulation: write current | job='HiRes' current=1 target=2 | target=2 | Setting[0].FrameAccumulation -> 1; [total=0.027s, att=1, conf=1, m=async] | 0.031s |
| 52 | 09:34:59.167 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_accumulation: write alternate | job='HiRes' current=1 target=2 | target=2 | Setting[0].FrameAccumulation -> 2; [total=0.018s, att=1, conf=1, m=async] | 0.016s |
| 53 | 09:34:59.182 | settings round-trip | PASS |  |  | frame_accumulation: readback |  |  | expected=2 actual=2 | 0.000s |
| 54 | 09:34:59.211 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_accumulation: restore | job='HiRes' restore_to=1 | restore_to=1 | Setting[0].FrameAccumulation -> 1; [total=0.027s, att=1, conf=1, m=async] | 0.032s |
| 55 | 09:34:59.247 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_average: write current | job='HiRes' current=1 target=2 | target=2 | Setting[0].FrameAverage -> 1; [total=0.020s, att=1, conf=1, m=async] | 0.016s |
| 56 | 09:34:59.276 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_average: write alternate | job='HiRes' current=1 target=2 | target=2 | Setting[0].FrameAverage -> 2; [total=0.027s, att=1, conf=1, m=async] | 0.031s |
| 57 | 09:34:59.291 | settings round-trip | PASS |  |  | frame_average: readback |  |  | expected=2 actual=2 | 0.000s |
| 58 | 09:34:59.312 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | frame_average: restore | job='HiRes' restore_to=1 | restore_to=1 | Setting[0].FrameAverage -> 1; [total=0.019s, att=1, conf=1, m=async] | 0.015s |
| 59 | 09:34:59.356 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_accumulation: write current | job='HiRes' current=1 target=2 | target=2 | Setting[0].LineAccumulation -> 1; [total=0.017s, att=1, conf=1, m=async] | 0.015s |
| 60 | 09:34:59.377 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_accumulation: write alternate | job='HiRes' current=1 target=2 | target=2 | Setting[0].LineAccumulation -> 2; [total=0.019s, att=1, conf=1, m=async] | 0.032s |
| 61 | 09:34:59.406 | settings round-trip | PASS |  |  | line_accumulation: readback |  |  | expected=2 actual=2 | 0.000s |
| 62 | 09:34:59.426 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_accumulation: restore | job='HiRes' restore_to=1 | restore_to=1 | Setting[0].LineAccumulation -> 1; [total=0.019s, att=1, conf=1, m=async] | 0.015s |
| 63 | 09:34:59.469 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_average: write current | job='HiRes' current=1 target=2 | target=2 | Setting[0].LineAverage -> 1; [total=0.024s, att=1, conf=1, m=async] | 0.031s |
| 64 | 09:34:59.488 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_average: write alternate | job='HiRes' current=1 target=2 | target=2 | Setting[0].LineAverage -> 2; [total=0.017s, att=1, conf=1, m=async] | 0.016s |
| 65 | 09:34:59.503 | settings round-trip | PASS |  |  | line_average: readback |  |  | expected=2 actual=2 | 0.000s |
| 66 | 09:34:59.521 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | line_average: restore | job='HiRes' restore_to=1 | restore_to=1 | Setting[0].LineAverage -> 1; [total=0.016s, att=1, conf=1, m=async] | 0.015s |
| 67 | 09:34:59.561 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | pinhole_airy: write current | job='HiRes' current=1.0 target=1.2 | target=1.2 | Setting[0].PinholeAiry -> 1.0; [total=0.020s, att=1, conf=1, m=async] | 0.031s |
| 68 | 09:34:59.580 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | pinhole_airy: write alternate | job='HiRes' current=1.0 target=1.2 | target=1.2 | Setting[0].PinholeAiry -> 1.2; [total=0.017s, att=1, conf=1, m=async] | 0.016s |
| 69 | 09:34:59.600 | settings round-trip | PASS |  |  | pinhole_airy: readback |  |  | expected=1.2 actual=1.2 tol=0.05 | 0.000s |
| 70 | 09:34:59.660 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | pinhole_airy: restore | job='HiRes' restore_to=1.0 | restore_to=1.0 | Setting[0].PinholeAiry -> 1.0; [total=0.058s, att=1, conf=1, m=async] | 0.063s |
| 71 | 09:34:59.708 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | detector_gain: write current | job='HiRes' current=2.5 target=3.5 | target=3.5 | Setting[0].Detector[40;1].Gain -> 2.5; [total=0.020s, att=1, conf=1, m=async] | 0.016s |
| 72 | 09:34:59.726 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | detector_gain: write alternate | job='HiRes' current=2.5 target=3.5 | target=3.5 | Setting[0].Detector[40;1].Gain -> 3.5; [total=0.016s, att=1, conf=1, m=async] | 0.015s |
| 73 | 09:34:59.741 | settings round-trip | PASS |  |  | detector_gain: readback |  |  | expected=3.5 actual=3.5 tol=0.1 | 0.000s |
| 74 | 09:34:59.763 | settings round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | detector_gain: restore | job='HiRes' restore_to=2.5 | restore_to=2.5 | Setting[0].Detector[40;1].Gain -> 2.5; [total=0.020s, att=1, conf=1, m=async] | 0.016s |
| 75 | 09:34:59.777 | xy 10-position pattern | PASS |  |  | xy: read start | mode='api' purpose='stage-safety-anchor' |  |  | 0.015s |
| 76 | 09:34:59.889 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 01 | index=1 count=10 from=(63500.0, 41499.99999999999) to=(63525.0, 41500.0) radius_um=25.0 | to=(63525.0, 41500.0) | MoveXY -> (63525.0, 41500.0) um; [total=0.108s, att=1, conf=1, m=async] | 0.110s |
| 77 | 09:34:59.903 | xy 10-position pattern | PASS |  |  | xy: read 01 | index=1 count=10 from=(63500.0, 41499.99999999999) to=(63525.0, 41500.0) radius_um=25.0 | to=(63525.0, 41500.0) |  | 0.000s |
| 78 | 09:34:59.904 | xy 10-position pattern | PASS |  |  | xy: x readback 01 |  |  | expected=63525.0 actual=63525.0 tol=20.0 | 0.000s |
| 79 | 09:34:59.906 | xy 10-position pattern | PASS |  |  | xy: y readback 01 |  |  | expected=41500.0 actual=41499.99999999999 tol=20.0 | 0.000s |
| 80 | 09:35:00.035 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 02 | index=2 count=10 from=(63500.0, 41499.99999999999) to=(63520.225, 41514.695) radius_um=25.0 | to=(63520.225, 41514.695) | MoveXY -> (63520.225, 41514.695) um; [total=0.129s, att=1, conf=1, m=async] | 0.125s |
| 81 | 09:35:00.050 | xy 10-position pattern | PASS |  |  | xy: read 02 | index=2 count=10 from=(63500.0, 41499.99999999999) to=(63520.225, 41514.695) radius_um=25.0 | to=(63520.225, 41514.695) |  | 0.015s |
| 82 | 09:35:00.051 | xy 10-position pattern | PASS |  |  | xy: x readback 02 |  |  | expected=63520.225 actual=63520.22460937499 tol=20.0 | 0.000s |
| 83 | 09:35:00.053 | xy 10-position pattern | PASS |  |  | xy: y readback 02 |  |  | expected=41514.695 actual=41514.69238281249 tol=20.0 | 0.000s |
| 84 | 09:35:00.162 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 03 | index=3 count=10 from=(63500.0, 41499.99999999999) to=(63507.725, 41523.776) radius_um=25.0 | to=(63507.725, 41523.776) | MoveXY -> (63507.725, 41523.776) um; [total=0.107s, att=1, conf=1, m=async] | 0.110s |
| 85 | 09:35:00.176 | xy 10-position pattern | PASS |  |  | xy: read 03 | index=3 count=10 from=(63500.0, 41499.99999999999) to=(63507.725, 41523.776) radius_um=25.0 | to=(63507.725, 41523.776) |  | 0.015s |
| 86 | 09:35:00.177 | xy 10-position pattern | PASS |  |  | xy: x readback 03 |  |  | expected=63507.725 actual=63507.724609375 tol=20.0 | 0.000s |
| 87 | 09:35:00.178 | xy 10-position pattern | PASS |  |  | xy: y readback 03 |  |  | expected=41523.776 actual=41523.7744140625 tol=20.0 | 0.000s |
| 88 | 09:35:00.245 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 04 | index=4 count=10 from=(63500.0, 41499.99999999999) to=(63492.275, 41523.776) radius_um=25.0 | to=(63492.275, 41523.776) | MoveXY -> (63492.275, 41523.776) um; [total=0.065s, att=1, conf=1, m=async] | 0.063s |
| 89 | 09:35:00.259 | xy 10-position pattern | PASS |  |  | xy: read 04 | index=4 count=10 from=(63500.0, 41499.99999999999) to=(63492.275, 41523.776) radius_um=25.0 | to=(63492.275, 41523.776) |  | 0.016s |
| 90 | 09:35:00.261 | xy 10-position pattern | PASS |  |  | xy: x readback 04 |  |  | expected=63492.275 actual=63492.27539062499 tol=20.0 | 0.000s |
| 91 | 09:35:00.262 | xy 10-position pattern | PASS |  |  | xy: y readback 04 |  |  | expected=41523.776 actual=41523.7744140625 tol=20.0 | 0.000s |
| 92 | 09:35:00.371 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 05 | index=5 count=10 from=(63500.0, 41499.99999999999) to=(63479.775, 41514.695) radius_um=25.0 | to=(63479.775, 41514.695) | MoveXY -> (63479.775, 41514.695) um; [total=0.108s, att=1, conf=1, m=async] | 0.109s |
| 93 | 09:35:00.385 | xy 10-position pattern | PASS |  |  | xy: read 05 | index=5 count=10 from=(63500.0, 41499.99999999999) to=(63479.775, 41514.695) radius_um=25.0 | to=(63479.775, 41514.695) |  | 0.016s |
| 94 | 09:35:00.387 | xy 10-position pattern | PASS |  |  | xy: x readback 05 |  |  | expected=63479.775 actual=63479.77539062499 tol=20.0 | 0.000s |
| 95 | 09:35:00.388 | xy 10-position pattern | PASS |  |  | xy: y readback 05 |  |  | expected=41514.695 actual=41514.69238281249 tol=20.0 | 0.000s |
| 96 | 09:35:00.467 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 06 | index=6 count=10 from=(63500.0, 41499.99999999999) to=(63475.0, 41500.0) radius_um=25.0 | to=(63475.0, 41500.0) | MoveXY -> (63475.0, 41500.0) um; [total=0.078s, att=1, conf=1, m=async] | 0.063s |
| 97 | 09:35:00.481 | xy 10-position pattern | PASS |  |  | xy: read 06 | index=6 count=10 from=(63500.0, 41499.99999999999) to=(63475.0, 41500.0) radius_um=25.0 | to=(63475.0, 41500.0) |  | 0.000s |
| 98 | 09:35:00.482 | xy 10-position pattern | PASS |  |  | xy: x readback 06 |  |  | expected=63475.0 actual=63475.00000000001 tol=20.0 | 0.000s |
| 99 | 09:35:00.484 | xy 10-position pattern | PASS |  |  | xy: y readback 06 |  |  | expected=41500.0 actual=41499.99999999999 tol=20.0 | 0.000s |
| 100 | 09:35:00.592 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 07 | index=7 count=10 from=(63500.0, 41499.99999999999) to=(63479.775, 41485.305) radius_um=25.0 | to=(63479.775, 41485.305) | MoveXY -> (63479.775, 41485.305) um; [total=0.107s, att=1, conf=1, m=async] | 0.094s |
| 101 | 09:35:00.606 | xy 10-position pattern | PASS |  |  | xy: read 07 | index=7 count=10 from=(63500.0, 41499.99999999999) to=(63479.775, 41485.305) radius_um=25.0 | to=(63479.775, 41485.305) |  | 0.000s |
| 102 | 09:35:00.607 | xy 10-position pattern | PASS |  |  | xy: x readback 07 |  |  | expected=63479.775 actual=63479.77539062499 tol=20.0 | 0.000s |
| 103 | 09:35:00.609 | xy 10-position pattern | PASS |  |  | xy: y readback 07 |  |  | expected=41485.305 actual=41485.302734375 tol=20.0 | 0.000s |
| 104 | 09:35:00.688 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 08 | index=8 count=10 from=(63500.0, 41499.99999999999) to=(63492.275, 41476.224) radius_um=25.0 | to=(63492.275, 41476.224) | MoveXY -> (63492.275, 41476.224) um; [total=0.077s, att=1, conf=1, m=async] | 0.078s |
| 105 | 09:35:00.702 | xy 10-position pattern | PASS |  |  | xy: read 08 | index=8 count=10 from=(63500.0, 41499.99999999999) to=(63492.275, 41476.224) radius_um=25.0 | to=(63492.275, 41476.224) |  | 0.000s |
| 106 | 09:35:00.703 | xy 10-position pattern | PASS |  |  | xy: x readback 08 |  |  | expected=63492.275 actual=63492.27539062499 tol=20.0 | 0.000s |
| 107 | 09:35:00.705 | xy 10-position pattern | PASS |  |  | xy: y readback 08 |  |  | expected=41476.224 actual=41476.2255859375 tol=20.0 | 0.000s |
| 108 | 09:35:00.814 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 09 | index=9 count=10 from=(63500.0, 41499.99999999999) to=(63507.725, 41476.224) radius_um=25.0 | to=(63507.725, 41476.224) | MoveXY -> (63507.725, 41476.224) um; [total=0.108s, att=1, conf=1, m=async] | 0.109s |
| 109 | 09:35:00.829 | xy 10-position pattern | PASS |  |  | xy: read 09 | index=9 count=10 from=(63500.0, 41499.99999999999) to=(63507.725, 41476.224) radius_um=25.0 | to=(63507.725, 41476.224) |  | 0.016s |
| 110 | 09:35:00.835 | xy 10-position pattern | PASS |  |  | xy: x readback 09 |  |  | expected=63507.725 actual=63507.724609375 tol=20.0 | 0.000s |
| 111 | 09:35:00.838 | xy 10-position pattern | PASS |  |  | xy: y readback 09 |  |  | expected=41476.224 actual=41476.2255859375 tol=20.0 | 0.000s |
| 112 | 09:35:00.950 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: move 10 | index=10 count=10 from=(63500.0, 41499.99999999999) to=(63520.225, 41485.305) radius_um=25.0 | to=(63520.225, 41485.305) | MoveXY -> (63520.225, 41485.305) um; [total=0.111s, att=1, conf=1, m=async] | 0.109s |
| 113 | 09:35:00.964 | xy 10-position pattern | PASS |  |  | xy: read 10 | index=10 count=10 from=(63500.0, 41499.99999999999) to=(63520.225, 41485.305) radius_um=25.0 | to=(63520.225, 41485.305) |  | 0.016s |
| 114 | 09:35:00.966 | xy 10-position pattern | PASS |  |  | xy: x readback 10 |  |  | expected=63520.225 actual=63520.22460937499 tol=20.0 | 0.000s |
| 115 | 09:35:00.967 | xy 10-position pattern | PASS |  |  | xy: y readback 10 |  |  | expected=41485.305 actual=41485.302734375 tol=20.0 | 0.000s |
| 116 | 09:35:01.076 | xy 10-position pattern | PASS | success+CONFIRMED att=1 conf=1 | YES | xy: restore | restore_to=(63500.0, 41499.99999999999) positions=10 | restore_to=(63500.0, 41499.99999999999) | MoveXY -> (63500.0, 41499.99999999999) um; [total=0.108s, att=1, conf=1, m=async] | 0.094s |
| 117 | 09:35:01.143 | z-galvo round-trip | PASS |  |  | z: read start | job='HiRes' |  |  | 0.062s |
| 118 | 09:35:01.170 | z-galvo round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | z: move alternate | job='HiRes' from=0.0 to=2.0 | to=2.0 | Z -> 2.0 um (galvo); [total=0.022s, att=1, conf=1, m=async] | 0.016s |
| 119 | 09:35:01.186 | z-galvo round-trip | PASS |  |  | z: read alternate | job='HiRes' |  |  | 0.000s |
| 120 | 09:35:01.187 | z-galvo round-trip | PASS |  |  | z: readback |  |  | expected=2.0 actual=2.0 tol=1.0 | 0.000s |
| 121 | 09:35:01.206 | z-galvo round-trip | PASS | success+CONFIRMED att=1 conf=1 | YES | z: restore | restore_to=0.0 | restore_to=0.0 | Z -> 0.0 um (galvo); [total=0.017s, att=1, conf=1, m=async] | 0.016s |
| 122 | 09:35:01.207 | setup | SKIP |  |  | phase: objective |  |  | use --allow-objective to enable | 0.000s |
| 123 | 09:35:01.208 | setup | SKIP |  |  | phase: acquire |  |  | use --allow-acquire to enable | 0.000s |

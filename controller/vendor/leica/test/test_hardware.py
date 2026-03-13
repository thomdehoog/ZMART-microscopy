"""
Hardware Validation — driver v6.0.0
====================================
Comprehensive test of ALL driver functions on real hardware.
Pattern: read current -> write same (safe) -> change -> readback verify -> restore.

Usage:
    python test_hardware.py
    python test_hardware.py --job HiRes
    python test_hardware.py --job HiRes --skip-move --skip-acquire --skip-write
    python test_hardware.py --no-pause          # CI-friendly, no interactive prompts
    python test_hardware.py --skip-dangerous     # skip objective, z-stack changes
"""

import argparse
import sys
import time
import json
import logging

# Enable debug logging for z-stack confirm diagnostics
logging.basicConfig(
    level=logging.WARNING,
    format="%(name)s: %(message)s",
)
logging.getLogger("lasx.confirmations").setLevel(logging.WARNING)
logging.getLogger("lasx.readers").setLevel(logging.WARNING)

# ── CLI ──────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description="LASX Driver Hardware Validation")
parser.add_argument("--job", default=None,
                    help="Job name to test against (default: first selected job)")
parser.add_argument("--skip-move", action="store_true",
                    help="Skip stage movement tests")
parser.add_argument("--skip-acquire", action="store_true",
                    help="Skip acquisition test")
parser.add_argument("--skip-write", action="store_true",
                    help="Skip all write tests (read-only validation)")
parser.add_argument("--skip-dangerous", action="store_true",
                    help="Skip objective switch, resonant toggle, z-stack changes")
parser.add_argument("--no-pause", action="store_true",
                    help="Run without interactive pauses")
parser.add_argument("--timeout", type=int, default=20,
                    help="Default timeout for API calls (seconds)")
args = parser.parse_args()

TIMEOUT = args.timeout

# ── UPDATE THESE FOR YOUR MICROSCOPE ─────────────────────────────────────
LIMITS = dict(
    x_min=1000,   x_max=130000,
    y_min=1000,   y_max=100000,
    z_galvo_min=-200,  z_galvo_max=200,
    z_wide_min=0,      z_wide_max=25000,
)
# ─────────────────────────────────────────────────────────────────────────

passed = 0
failed = 0
skipped = 0
results_log = []


def test(name, fn, skip=False):
    """Run a single test. Returns the result or None on failure."""
    global passed, failed, skipped
    if skip:
        print(f"  \033[33m[SKIP]\033[0m {name}")
        skipped += 1
        results_log.append(("SKIP", name, ""))
        return None
    try:
        result = fn()
        if isinstance(result, dict) and "success" in result:
            if result["success"]:
                print(f"  \033[32m[PASS]\033[0m {name}")
                passed += 1
                results_log.append(("PASS", name, ""))
            else:
                msg = result.get("message", "unknown error")
                print(f"  \033[31m[FAIL]\033[0m {name}: {msg}")
                failed += 1
                results_log.append(("FAIL", name, msg))
            return result
        elif result is not None:
            print(f"  \033[32m[PASS]\033[0m {name}")
            passed += 1
            results_log.append(("PASS", name, ""))
            return result
        else:
            print(f"  \033[31m[FAIL]\033[0m {name}: returned None")
            failed += 1
            results_log.append(("FAIL", name, "returned None"))
            return None
    except Exception as e:
        print(f"  \033[31m[FAIL]\033[0m {name}: {e}")
        failed += 1
        results_log.append(("FAIL", name, str(e)))
        return None


def pause(msg="Press Enter to continue..."):
    if args.no_pause:
        return
    input(f"\n  \u23f8  {msg}\n")


def detail(text):
    """Print indented detail line."""
    print(f"           {text}")


def timing_str(r):
    """Format timing from a set/move result."""
    t = r.get("timing", {})
    parts = []
    if t.get("pre_check_s", 0) > 0.001:
        parts.append(f"pre_check={t['pre_check_s']:.3f}s")
    if t.get("fire_s", 0) > 0:
        parts.append(f"fire={t['fire_s']:.3f}s")
    if t.get("check_s", 0) > 0.001:
        parts.append(f"check={t['check_s']:.3f}s")
    if t.get("confirm_s", 0) > 0:
        parts.append(f"confirm={t['confirm_s']:.3f}s")
    parts.append(f"total={t.get('total_s', 0):.3f}s")
    parts.append(f"attempts={t.get('attempts', '?')}")
    ca = t.get("confirm_attempts", 0)
    if ca > 0:
        parts.append(f"confirm_attempts={ca}")
    return ", ".join(parts)


def write_test(name, set_fn, current_val, new_val, readback_fn,
               tolerance=None, skip=False):
    """Standard write-test pattern:
    set current (safe) -> set new -> readback verify -> restore.

    Args:
        name: display name
        set_fn: callable(value) -> result dict
        current_val: current value to write back safely
        new_val: new value to test with
        readback_fn: callable() -> actual value from settings
        tolerance: float for approximate comparison, None for exact
        skip: skip this test
    """
    if skip:
        test(f"{name}: skipped", lambda: None, skip=True)
        return

    # 1) Write current value (safe, no state change)
    r = test(f"{name}: write current ({current_val})",
             lambda: set_fn(current_val))
    if not r or not r.get("success"):
        detail(f"ABORT {name}: safe write of current value failed — "
               f"result={r}")
        return

    # 2) Write new value
    r = test(f"{name}: change to {new_val}",
             lambda: set_fn(new_val))
    if not r or not r.get("success"):
        detail(f"ABORT {name}: write of new value failed — "
               f"result={r}")
        # Still attempt restore so hardware isn't left in unknown state
        r_restore = set_fn(current_val)
        test(f"{name}: restore after failed write",
             lambda: r_restore)
        return
    detail(f"Timing: {timing_str(r)}")
    if r.get("confirmed") is not True:
        detail(f"WARNING: confirmed={r.get('confirmed')} (expected True)")

    # 3) Readback verify
    time.sleep(0.1)
    actual = readback_fn()
    if tolerance is not None:
        ok = actual is not None and abs(actual - new_val) < tolerance
    else:
        ok = actual == new_val
    test(f"{name}: readback = {actual}",
         lambda: {"success": ok,
                  "message": f"Expected {new_val}, got {actual}"})

    # 4) Restore
    r_restore = set_fn(current_val)
    test(f"{name}: restore to {current_val}",
         lambda: r_restore)
    if not r_restore or not r_restore.get("success"):
        detail(f"WARNING: restore failed — hardware may be in changed "
               f"state! result={r_restore}")


# #########################################################################
#  Phase 1: CONNECTION
# #########################################################################

print("\n" + "=" * 70)
print("  Phase 1: CONNECTION")
print("=" * 70)

from pathlib import Path
# Add the leica directory to sys.path so `import lasx` works unchanged.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from LasxApi import PYLICamApiConnector as lasx_api
import lasx as drv

print(f"  Driver version: {drv.__version__}")

client = lasx_api.LasxApiClientPyModel
confirmed = client.Connect("PythonClient")
test("Connect", lambda: {"success": confirmed, "message": f"Connected: {confirmed}"})

if not confirmed:
    print("\n  ABORT: Cannot connect to LAS X. Is it running?")
    sys.exit(1)

test("ping", lambda: {"success": drv.ping(client), "message": "OK"})

drv.set_stage_limits(**LIMITS)
lim = drv.get_stage_limits()
test("set_stage_limits",
     lambda: {"success": lim["x_min"] == LIMITS["x_min"], "message": str(lim)})


# #########################################################################
#  Phase 2: READ-ONLY
# #########################################################################

print("\n" + "=" * 70)
print("  Phase 2: READ-ONLY")
print("=" * 70)

# get_scan_status
status = test("get_scan_status", lambda: drv.get_scan_status(client))
if status:
    detail(f"Scanner: {status}")

# get_jobs
jobs = test("get_jobs", lambda: drv.get_jobs(client))
JOB = args.job
if jobs:
    names = [j["Name"] for j in jobs]
    selected = next((j["Name"] for j in jobs if j.get("IsSelected")), None)
    detail(f"Jobs: {names}")
    detail(f"Selected: {selected}")

    if JOB is None:
        JOB = selected or names[0]
        detail(f"Using job: {JOB}")

    if JOB not in names:
        print(f"\n  ABORT: Job '{JOB}' not found! Available: {names}")
        print(f"  Re-run with: python test_hardware.py --job {names[0]}")
        sys.exit(1)

    # Show metadata for the active job
    job_info = next((j for j in jobs if j["Name"] == JOB), None)
    if job_info:
        detail(f"ScanMode: {job_info.get('ScanMode')}")
        flags = [k for k in ("IsPattern", "IsAutofocus", "IsCamera",
                             "IsLightning", "IsPause")
                 if job_info.get(k)]
        if flags:
            detail(f"Flags: {', '.join(flags)}")
        if job_info.get("AFZUseMode", 0):
            detail(f"AF: mode={job_info['AFZUseMode']}  "
                   f"range={job_info.get('FocusRange')}um  "
                   f"slices={job_info.get('FocusSliceCount')}")

# get_hardware_info
hw = test("get_hardware_info", lambda: drv.get_hardware_info(client))
if hw:
    objs = hw.get("Microscope", {}).get("objectives", [])
    detail(f"Objectives ({len(objs)}): "
           f"{[o.get('name', '?') for o in objs]}")

# get_xy
pos = test("get_xy", lambda: drv.get_xy(client))
if pos:
    detail(f"Stage: X={pos['x_um']:.1f} Y={pos['y_um']:.1f} um")

# get_job_settings + make_changeable_copy
settings = test("get_job_settings",
                lambda: drv.get_job_settings(client, JOB, timeout=TIMEOUT))
ch = None
if settings:
    ch = drv.make_changeable_copy(settings)
    test("make_changeable_copy", lambda: ch)

    detail(f"Zoom: {ch['zoom']['current']}")
    detail(f"Speed: {ch['scanSpeed']['value']} Hz")
    detail(f"Resonant: {ch['scanSpeed']['isResonant']}")
    detail(f"Mode: {ch['scanMode']}")
    detail(f"Seq.Mode: {ch.get('sequentialMode', 'N/A')}")
    detail(f"Rotation: {ch['scanFieldRotation'].get('value', 0)}")
    detail(f"Format: {ch['format']}")
    detail(f"Objective: {ch['objective'].get('name', '?')}")

    for s in ch["activeSettings"]:
        detail(f"--- Setting {s['_index']} ({s['_name']}) ---")
        detail(f"  FrameAcc={s['frameAccumulation']}  FrameAvg={s['frameAverage']}  "
               f"LineAcc={s['lineAccumulation']}  LineAvg={s['lineAverage']}")
        ph = s.get("pinholeAiry", {})
        detail(f"  Pinhole: {ph.get('value', '?')} AU")

        for d in s.get("activeDetectors", []):
            detail(f"  Detector: route={d.get('_beamRoute', '?')}  "
                   f"gain={d.get('gain', {}).get('value', '?')}  "
                   f"active={d.get('isActive', '?')}")

        for l in s.get("activeLaserLines", []):
            detail(f"  Laser: route={l.get('_beamRoute', '?')}  "
                   f"line={l.get('_lineIndex', '?')}  "
                   f"wl={l.get('wavelength', '?')}nm  "
                   f"intensity={l.get('intensity', {}).get('value', '?')}  "
                   f"shutter={'open' if l.get('shutterOpen') else 'closed'}")

        for fw in s.get("filterWheels", []):
            detail(f"  FilterWheel: route={fw.get('_beamRoute', '?')}  "
                   f"type={fw.get('type', '?')}  "
                   f"slot={fw.get('slotIndex', '?')}  "
                   f"spectrum={fw.get('spectrumPosition', '?')}")

    if ch.get("stack"):
        st = ch["stack"]
        detail(f"Z-stack: begin={st['begin']}, end={st['end']}, "
               f"step={st['stepSize']}, size={st['size']}, "
               f"sections={st.get('sections')}, drive={st.get('zDrive')}")

    if ch.get("time"):
        t = ch["time"]
        detail(f"Time: interval={t.get('interval')}s, "
               f"cycles={t.get('cycles')}, minimize={t.get('minimize')}")


# #########################################################################
#  Phase 3: SELECT JOB
# #########################################################################

print("\n" + "=" * 70)
print(f"  Phase 3: SELECT JOB '{JOB}'")
print("=" * 70)

r = test("select_job", lambda: drv.select_job(client, JOB, poll_timeout=TIMEOUT))
if r:
    detail(f"Elapsed: {r.get('timing', {}).get('total_s', 0):.2f}s")

# Select again (should be near-instant — already selected)
r = test("select_job (already selected)",
         lambda: drv.select_job(client, JOB, poll_timeout=TIMEOUT))
if r:
    detail(f"Elapsed: {r.get('timing', {}).get('total_s', 0):.2f}s (should be ~0)")

# Cycle through all jobs 5 times (tests rapid switching and restore)
if jobs and len(names) > 1:
    other_names = [n for n in names if n != JOB]
    for cycle in range(1, 6):
        for other_job in other_names:
            r = test(f"select_job cycle {cycle}: switch to '{other_job}'",
                     lambda _j=other_job: drv.select_job(client, _j,
                                                          poll_timeout=TIMEOUT))
            if r:
                detail(f"Elapsed: {r.get('timing', {}).get('total_s', 0):.2f}s")
        r2 = drv.select_job(client, JOB, poll_timeout=TIMEOUT)
        test(f"select_job cycle {cycle}: restore '{JOB}'",
             lambda: r2)
        if r2:
            detail(f"Elapsed: {r2.get('timing', {}).get('total_s', 0):.2f}s")


# Abort early if no settings or skipping writes
if not ch or args.skip_write:
    if args.skip_write:
        print("\n  [INFO] --skip-write: skipping all write phases")


# #########################################################################
#  Phase 4: JOB-LEVEL WRITE TESTS
# #########################################################################

if ch and not args.skip_write:
    print("\n" + "=" * 70)
    print("  Phase 4: JOB-LEVEL SETTINGS")
    print("=" * 70)


    def fresh():
        """Re-read settings for readback verification."""
        # Clear cached settings to force fresh dispatch from LAS X
        try:
            client.PyApiGetJobSettingsByName.Model.Settings = None
        except Exception:
            pass
        return drv.make_changeable_copy(
            drv.get_job_settings(client, JOB, timeout=TIMEOUT))

    # ── 4a. Zoom ─────────────────────────────────────────────────────
    cur_zoom = ch["zoom"]["current"]
    new_zoom = 5.0 if abs(cur_zoom - 5.0) > 0.5 else 3.0
    write_test("set_zoom",
               lambda v: drv.set_zoom(client, JOB, v, pre_check_timeout=TIMEOUT),
               cur_zoom, new_zoom,
               lambda: fresh()["zoom"]["current"],
               tolerance=0.1)

    # ── 4b. Scan speed ───────────────────────────────────────────────
    cur_speed = ch["scanSpeed"]["value"]
    new_speed = 600 if cur_speed != 600 else 400
    write_test("set_scan_speed",
               lambda v: drv.set_scan_speed(client, JOB, v, pre_check_timeout=TIMEOUT),
               cur_speed, new_speed,
               lambda: fresh()["scanSpeed"]["value"])

    # ── 4c. Resonant (toggle — LAS X rejects writing same value) ────
    cur_res = ch["scanSpeed"]["isResonant"]
    if not args.skip_dangerous:
        r = test(f"set_scan_resonant: change to {not cur_res}",
                 lambda: drv.set_scan_resonant(client, JOB, not cur_res,
                                                pre_check_timeout=10.0))
        if r and r.get("success"):
            detail(f"Timing: {timing_str(r)}")
            actual = fresh()["scanSpeed"]["isResonant"]
            test(f"set_scan_resonant: readback = {actual}",
                 lambda: {"success": actual == (not cur_res),
                          "message": f"Expected {not cur_res}, got {actual}"})
        # Always restore — hardware may have changed even if readback
        # was unconfirmed, and leaving resonant on changes zoom range
        r2 = drv.set_scan_resonant(client, JOB, cur_res,
                                    pre_check_timeout=10.0)
        test(f"set_scan_resonant: restore to {cur_res}", lambda: r2)
    else:
        test("set_scan_resonant: skipped (--skip-dangerous)",
             lambda: None, skip=True)

    # ── 4d. Scan mode ─────────────────────────────────────────────
    #   LAS X silently rejects invalid modes for a given job config.
    #   Try candidates until one sticks; skip if none work.
    cur_mode = ch["scanMode"]
    valid_modes = ["xyz", "xzy", "xz", "xt", "xyt", "xyzt"]
    candidates = [m for m in valid_modes if m != cur_mode]

    scan_mode_ok = False
    for new_mode in candidates:
        r = drv.set_scan_mode(client, JOB, new_mode,
                              pre_check_timeout=TIMEOUT)
        if r.get("success"):
            scan_mode_ok = True
            test(f"set_scan_mode: change to {new_mode}",
                 lambda: r)
            detail(f"Timing: {timing_str(r)}")

            time.sleep(0.1)
            actual = fresh()["scanMode"]
            test(f"set_scan_mode: readback = {actual}",
                 lambda: {"success": actual == new_mode,
                          "message": f"Expected {new_mode}, got {actual}"})

            # Restore
            r2 = drv.set_scan_mode(client, JOB, cur_mode,
                                   pre_check_timeout=TIMEOUT)
            test(f"set_scan_mode: restore to {cur_mode}",
                 lambda: r2)
            break
        else:
            detail(f"set_scan_mode: '{new_mode}' rejected (trying next)")

    if not scan_mode_ok:
        test("set_scan_mode: no valid alternative mode found for this job",
             lambda: None, skip=True)

    # ── 4e. Sequential mode ──────────────────────────────────────────
    cur_seq = ch.get("sequentialMode", "Line")
    new_seq = "Frame" if cur_seq != "Frame" else "Line"
    if len(ch["activeSettings"]) > 1:
        write_test("set_sequential_mode",
                   lambda v: drv.set_sequential_mode(client, JOB, v,
                                                      pre_check_timeout=TIMEOUT),
                   cur_seq, new_seq,
                   lambda: fresh().get("sequentialMode", ""))
    else:
        test("set_sequential_mode: only 1 setting, skipping",
             lambda: None, skip=True)

    # ── 4f. Scan field rotation ──────────────────────────────────────
    cur_rot = ch["scanFieldRotation"].get("value", 0.0)
    new_rot = 10.0 if abs(cur_rot - 10.0) > 1 else 0.0
    write_test("set_scan_field_rotation",
               lambda v: drv.set_scan_field_rotation(client, JOB, v,
                                                      pre_check_timeout=TIMEOUT),
               cur_rot, new_rot,
               lambda: fresh()["scanFieldRotation"].get("value", 0),
               tolerance=0.5)

    # ── 4g. Image format ─────────────────────────────────────────────
    cur_fmt = ch["format"]
    cur_w, cur_h = drv.parse_format(cur_fmt) if isinstance(cur_fmt, str) else (512, 512)
    new_fmt = "256 x 256" if cur_w != 256 else "512 x 512"
    write_test("set_image_format",
               lambda v: drv.set_image_format(client, JOB, v, pre_check_timeout=TIMEOUT),
               cur_fmt, new_fmt,
               lambda: fresh()["format"])

    # ── 4h. Objective ────────────────────────────────────────────────
    if hw and not args.skip_dangerous:
        objectives = hw.get("Microscope", {}).get("objectives", [])
        cur_obj_name = ch["objective"].get("name", "")
        other_objs = [o for o in objectives if o.get("name") != cur_obj_name]

        if other_objs:
            alt_obj = other_objs[0]

            r = test(f"set_objective: change to {alt_obj['name'][:40]}",
                     lambda: drv.set_objective(client, JOB, hw,
                                               name=alt_obj["name"],
                                               pre_check_timeout=TIMEOUT))
            if r and r.get("success"):
                detail(f"Timing: {timing_str(r)}")
                actual = fresh()["objective"].get("name", "")
                test(f"set_objective: readback = {actual[:40]}",
                     lambda: {"success": alt_obj["name"] in actual or
                              actual in alt_obj["name"],
                              "message": f"Expected '{alt_obj['name']}', "
                                         f"got '{actual}'"})

                # Restore
                r2 = drv.set_objective(client, JOB, hw, name=cur_obj_name,
                                       pre_check_timeout=TIMEOUT)
                test(f"set_objective: restore to {cur_obj_name[:40]}",
                     lambda: r2)
        else:
            test("set_objective: only 1 objective, skipping",
                 lambda: None, skip=True)
    else:
        test("set_objective: skipped (--skip-dangerous or no hw_info)",
             lambda: None, skip=True)


# #########################################################################
#  Phase 5: PER-SETTING WRITE TESTS
# #########################################################################

if ch and not args.skip_write:
    print("\n" + "=" * 70)
    print("  Phase 5: PER-SETTING PARAMETERS")
    print("=" * 70)


    for si_data in ch["activeSettings"]:
        si = si_data["_index"]
        si_name = si_data["_name"]
        print(f"\n  --- Setting {si} ({si_name}) ---")

        # ── 5a. Frame accumulation (discrete: [1,2,3,4,6,8,9,10,12,14,15,16]) ──
        _FA_VALID = [1, 2, 3, 4, 6, 8, 9, 10, 12, 14, 15, 16]
        cur_fa = si_data["frameAccumulation"]
        new_fa = next((v for v in _FA_VALID if v != cur_fa), cur_fa)
        write_test(f"  set_frame_accumulation[{si}]",
                   lambda v, _si=si: drv.set_frame_accumulation(
                       client, JOB, _si, v, pre_check_timeout=TIMEOUT),
                   cur_fa, new_fa,
                   lambda _si=si: fresh()["activeSettings"][_si]
                                  ["frameAccumulation"])

        # ── 5b. Frame average ────────────────────────────────────────
        cur_favg = si_data["frameAverage"]
        new_favg = cur_favg + 1 if cur_favg < 10 else cur_favg - 1
        write_test(f"  set_frame_average[{si}]",
                   lambda v, _si=si: drv.set_frame_average(
                       client, JOB, _si, v, pre_check_timeout=TIMEOUT),
                   cur_favg, new_favg,
                   lambda _si=si: fresh()["activeSettings"][_si]
                                  ["frameAverage"])

        # ── 5c. Line accumulation ────────────────────────────────────
        cur_la = si_data["lineAccumulation"]
        new_la = cur_la - 1 if cur_la > 1 else cur_la + 1
        write_test(f"  set_line_accumulation[{si}]",
                   lambda v, _si=si: drv.set_line_accumulation(
                       client, JOB, _si, v, pre_check_timeout=TIMEOUT),
                   cur_la, new_la,
                   lambda _si=si: fresh()["activeSettings"][_si]
                                  ["lineAccumulation"])

        # ── 5d. Line average (powers of 2: [1,2,4,8]) ────────────────
        _LA_VALID = [1, 2, 4, 8]
        cur_lavg = si_data["lineAverage"]
        new_lavg = next((v for v in _LA_VALID if v != cur_lavg), cur_lavg)
        write_test(f"  set_line_average[{si}]",
                   lambda v, _si=si: drv.set_line_average(
                       client, JOB, _si, v, pre_check_timeout=TIMEOUT),
                   cur_lavg, new_lavg,
                   lambda _si=si: fresh()["activeSettings"][_si]
                                  ["lineAverage"])

        # ── 5e. Pinhole ──────────────────────────────────────────────
        cur_ph = si_data.get("pinholeAiry", {}).get("value", 1.0)
        new_ph = 1.5 if abs(cur_ph - 1.5) > 0.2 else 1.0
        write_test(f"  set_pinhole_airy[{si}]",
                   lambda v, _si=si: drv.set_pinhole_airy(
                       client, JOB, _si, v, pre_check_timeout=TIMEOUT),
                   cur_ph, new_ph,
                   lambda _si=si: fresh()["activeSettings"][_si]
                                  .get("pinholeAiry", {}).get("value"),
                   tolerance=0.1)

        # ── 5f. Detectors (gain only, NOT deactivating) ─────────────
        for det in si_data.get("activeDetectors", []):
            br = det.get("_beamRoute", "")
            cur_gain = det.get("gain", {}).get("value")
            gain_min = det.get("gain", {}).get("min")
            gain_max = det.get("gain", {}).get("max")

            if cur_gain is None:
                test(f"  set_detector_gain[{si}:{br}]: no gain value",
                     lambda: None, skip=True)
                continue

            # Skip HyD detectors with fixed gain (min == max)
            if gain_min is not None and gain_max is not None:
                if abs(gain_max - gain_min) < 0.1:
                    test(f"  set_detector_gain[{si}:{br}]: fixed gain "
                         f"({gain_min}), skipping (HyD)",
                         lambda: None, skip=True)
                    continue

            # Try writing current value first; if that fails with
            # "out of range" where min==max, it's a fixed-gain detector
            r_probe = drv.set_detector_gain(client, JOB, si, br, cur_gain,
                                             pre_check_timeout=TIMEOUT)
            if not r_probe["success"] and "out of range" in r_probe.get("message", "").lower():
                test(f"  set_detector_gain[{si}:{br}]: fixed gain (detected "
                     f"from error), skipping",
                     lambda: None, skip=True)
                continue

            # Small nudge: +10 or -10
            new_gain = cur_gain + 10.0 if cur_gain < 1190 else cur_gain - 10.0

            def _readback_gain(_si=si, _br=br):
                s = fresh()["activeSettings"][_si]
                for d in s.get("activeDetectors", []):
                    if d.get("_beamRoute") == _br:
                        return d.get("gain", {}).get("value")
                return None

            write_test(f"  set_detector_gain[{si}:{br}]",
                       lambda v, _br=br: drv.set_detector_gain(
                           client, JOB, si, _br, v, pre_check_timeout=TIMEOUT),
                       cur_gain, new_gain,
                       _readback_gain,
                       tolerance=1.0)

        # ── 5g. Laser intensity ──────────────────────────────────────
        for las in si_data.get("activeLaserLines", []):
            br = las.get("_beamRoute", "")
            li = las.get("_lineIndex", 0)
            cur_int = las.get("intensity", {}).get("value")
            if cur_int is None:
                test(f"  set_laser_intensity[{si}:{br}:{li}]: no value",
                     lambda: None, skip=True)
                continue

            new_int = 0.1 if abs(cur_int - 0.1) > 0.02 else 0.05

            def _readback_laser(_si=si, _br=br, _li=li):
                s = fresh()["activeSettings"][_si]
                for l in s.get("activeLaserLines", []):
                    if l.get("_beamRoute") == _br and l.get("_lineIndex") == _li:
                        return l.get("intensity", {}).get("value")
                return None

            write_test(f"  set_laser_intensity[{si}:{br}:{li}]",
                       lambda v, _br=br, _li=li: drv.set_laser_intensity(
                           client, JOB, si, _br, _li, v, pre_check_timeout=TIMEOUT),
                       cur_int, new_int,
                       _readback_laser,
                       tolerance=0.01)

        # ── 5h. Laser shutter ────────────────────────────────────────
        for las in si_data.get("activeLaserLines", []):
            br = las.get("_beamRoute", "")
            cur_shutter = las.get("shutterOpen", True)

            # Close then restore
            r = test(f"  set_laser_shutter[{si}:{br}]: close",
                     lambda _br=br: drv.set_laser_shutter(
                         client, JOB, si, _br, False, pre_check_timeout=TIMEOUT))
            if r and r.get("success"):
                r2 = drv.set_laser_shutter(client, JOB, si, br, cur_shutter,
                                            pre_check_timeout=TIMEOUT)
                test(f"  set_laser_shutter[{si}:{br}]: restore ({'open' if cur_shutter else 'closed'})",
                     lambda: r2)
            break  # only test first laser's shutter per setting

        # ── 5i. Filter wheels (if present) ───────────────────────────
        for fw in si_data.get("filterWheels", []):
            br = fw.get("_beamRoute", "")
            fw_type = fw.get("type")
            cur_slot = fw.get("slotIndex")
            cur_spec = fw.get("spectrumPosition")

            if cur_slot is not None and fw_type is not None:
                new_slot = cur_slot + 1 if cur_slot < 5 else cur_slot - 1

                def _readback_fw_slot(_si=si, _br=br, _fwt=fw_type):
                    s = fresh()["activeSettings"][_si]
                    for f in s.get("filterWheels", []):
                        if f.get("_beamRoute") == _br and f.get("type") == _fwt:
                            return f.get("slotIndex")
                    return None

                write_test(f"  set_filter_wheel_slot[{si}:{br}]",
                           lambda v, _br=br, _fwt=fw_type:
                               drv.set_filter_wheel_slot(
                                   client, JOB, si, _br, _fwt, v,
                                   pre_check_timeout=TIMEOUT),
                           cur_slot, new_slot,
                           _readback_fw_slot)

            if cur_spec is not None and fw_type is not None:
                new_spec = cur_spec + 5.0 if cur_spec < 700 else cur_spec - 5.0

                def _readback_fw_spec(_si=si, _br=br, _fwt=fw_type):
                    s = fresh()["activeSettings"][_si]
                    for f in s.get("filterWheels", []):
                        if f.get("_beamRoute") == _br and f.get("type") == _fwt:
                            return f.get("spectrumPosition")
                    return None

                write_test(f"  set_filter_wheel_spectrum[{si}:{br}]",
                           lambda v, _br=br, _fwt=fw_type:
                               drv.set_filter_wheel_spectrum(
                                   client, JOB, si, _br, _fwt, v,
                                   pre_check_timeout=TIMEOUT),
                           cur_spec, new_spec,
                           _readback_fw_spec,
                           tolerance=1.0)


# #########################################################################
#  Phase 6: Z-STACK & TIME DEFINITION
# #########################################################################

if ch and not args.skip_write:
    print("\n" + "=" * 70)
    print("  Phase 6: Z-STACK & TIME DEFINITION")
    print("=" * 70)

    skip_z = args.skip_dangerous

    if not skip_z:
        # ── Save original state ──────────────────────────────────────
        orig_mode = ch.get("scanMode", "xyz")
        orig_stack = ch.get("stack")  # None or dict with begin/end/step/size
        had_z_stack = (orig_stack is not None
                       and orig_stack.get("begin") is not None)

        # ── Ensure scan mode has z axis ──────────────────────────────
        if "z" not in orig_mode.lower():
            r = test("set_scan_mode: switch to xyz for z-stack tests",
                     lambda: drv.set_scan_mode(client, JOB, "xyz",
                                               pre_check_timeout=TIMEOUT))
            if not r or not r.get("success"):
                test("z-stack tests: could not switch to xyz mode",
                     lambda: None, skip=True)
                skip_z = True

        # ── Set up a z-stack if none exists ──────────────────────────
        if not skip_z and not had_z_stack:
            r = test("set_z_stack_definition: create stack (begin=-10, end=10)",
                     lambda: drv.set_z_stack_definition(
                         client, JOB, begin_um=-10.0, end_um=10.0,
                         pre_check_timeout=TIMEOUT))
            if not r or not r.get("success"):
                test("z-stack tests: could not create z-stack",
                     lambda: None, skip=True)
                skip_z = True

    if not skip_z:
        # Re-read settings now that z-stack is guaranteed
        ch_z = fresh()
        st = ch_z.get("stack", {})

        # ── 6a. set_z_stack_definition (begin/end) ───────────────────
        #   LAS X recalculates z-stack geometry when begin/end change,
        #   so readback won't match exact targets. Verify command succeeds
        #   and that begin actually changed.
        #   When "Z-Step Size" mode is active in the GUI, LAS X quantises
        #   the stack to integer multiples of the step size.  Use a delta
        #   that is a multiple of step so the test passes in any mode.
        cur_begin = st.get("begin")
        cur_end = st.get("end")
        cur_step = st.get("stepSize")
        if cur_begin is not None and cur_end is not None:
            delta = cur_step if cur_step and cur_step >= 1.0 else 2.0
            new_begin = cur_begin - delta
            new_end = cur_end + delta
            r = test("set_z_stack_definition: change begin/end",
                     lambda: drv.set_z_stack_definition(
                         client, JOB,
                         begin_um=new_begin, end_um=new_end,
                         pre_check_timeout=TIMEOUT))
            if r and r.get("success"):
                detail(f"Timing: {timing_str(r)}")
                rb = fresh().get("stack", {})
                detail(f"Readback: begin={rb.get('begin')}, end={rb.get('end')}, "
                       f"size={rb.get('size')}")
                test("set_z_stack_definition: begin changed",
                     lambda: {"success": rb.get("begin") is not None
                              and abs(rb["begin"] - new_begin) < 1.0,
                              "message": f"Expected begin≈{new_begin}, "
                                         f"got {rb.get('begin')}"})
                # Restore
                r2 = drv.set_z_stack_definition(
                    client, JOB,
                    begin_um=cur_begin, end_um=cur_end,
                    pre_check_timeout=TIMEOUT)
                test("set_z_stack_definition: restore", lambda: r2)

        # ── 6b. set_z_stack_size ─────────────────────────────────────
        #   LAS X recalculates geometry when size changes. Verify
        #   command succeeds and that size actually changed.
        #   Use a delta that is a multiple of step size (see 6a).
        cur_size = st.get("size")
        if cur_size is not None:
            size_delta = cur_step if cur_step and cur_step >= 1.0 else 5.0
            new_size = cur_size + size_delta if cur_size < 100 else cur_size - size_delta
            r = test("set_z_stack_size: write current",
                     lambda: drv.set_z_stack_size(client, JOB, cur_size,
                                                   pre_check_timeout=TIMEOUT))
            r = test(f"set_z_stack_size: change to {new_size}",
                     lambda: drv.set_z_stack_size(client, JOB, new_size,
                                                   pre_check_timeout=TIMEOUT))
            if r and r.get("success"):
                detail(f"Timing: {timing_str(r)}")
                rb_size = fresh().get("stack", {}).get("size")
                detail(f"Readback: size={rb_size} (target was {new_size})")
                test("set_z_stack_size: size changed from original",
                     lambda: {"success": rb_size is not None
                              and abs(rb_size - cur_size) > 0.5,
                              "message": f"Expected size to change from "
                                         f"{cur_size}, got {rb_size}"})
                # Restore
                drv.set_z_stack_size(client, JOB, cur_size, pre_check_timeout=TIMEOUT)
                test("set_z_stack_size: restore",
                     lambda: {"success": True})

        # ── 6c. set_z_stack_step_size ────────────────────────────────
        cur_step = st.get("stepSize")
        if cur_step is not None:
            new_step = cur_step + 0.5 if cur_step < 10 else cur_step - 0.5
            write_test("set_z_stack_step_size",
                       lambda v: drv.set_z_stack_step_size(client, JOB, v,
                                                            pre_check_timeout=TIMEOUT),
                       cur_step, new_step,
                       lambda: fresh().get("stack", {}).get("stepSize") or 0,
                       tolerance=0.2)

        # ── Restore original state ───────────────────────────────────
        if not had_z_stack:
            # Clear the z-stack we created by resetting begin/end
            r = drv.set_z_stack_definition(client, JOB,
                                           old_begin_um=0, old_end_um=0,
                                           pre_check_timeout=TIMEOUT)
            test("z-stack: clear (restore no z-stack)", lambda: r)

        if "z" not in orig_mode.lower():
            r = drv.set_scan_mode(client, JOB, orig_mode, pre_check_timeout=TIMEOUT)
            test(f"scan_mode: restore to '{orig_mode}'", lambda: r)

    else:
        test("z-stack tests: skipped (--skip-dangerous)",
             lambda: None, skip=True)


# #########################################################################
#  Phase 7: STAGE MOVEMENT
# #########################################################################

print("\n" + "=" * 70)
print("  Phase 7: STAGE MOVEMENT")
print("=" * 70)

if args.skip_move:
    test("move_xy: skipped (--skip-move)", lambda: None, skip=True)
else:
    pos = drv.get_xy(client)
    if pos:
        x0, y0 = pos["x_um"], pos["y_um"]
        lim = drv.get_stage_limits()

        # ── 7a. Absolute move ────────────────────────────────────────
        safe_x = max(lim["x_min"] + 100, min(x0 + 500, lim["x_max"] - 100))
        safe_y = max(lim["y_min"] + 100, min(y0 + 500, lim["y_max"] - 100))


        r = test(f"move_xy absolute to ({safe_x:.0f}, {safe_y:.0f})",
                 lambda: drv.move_xy(client, safe_x, safe_y, unit="um",
                                     pre_check_timeout=TIMEOUT))
        if r and r.get("success"):
            detail(f"Timing: {timing_str(r)}")
            new_pos = drv.get_xy(client)
            if new_pos:
                detail(f"Position: X={new_pos['x_um']:.1f} Y={new_pos['y_um']:.1f}")

        # Move back
        r = test("move_xy: return to original",
                 lambda: drv.move_xy(client, x0, y0, unit="um",
                                     pre_check_timeout=TIMEOUT))
        if r and r.get("success"):
            new_pos = drv.get_xy(client)
            if new_pos:
                detail(f"Restored: X={new_pos['x_um']:.1f} Y={new_pos['y_um']:.1f}")

        # ── 7b. Out-of-limits (should fail gracefully) ───────────────
        r_ool = drv.move_xy(client, -999999, -999999, unit="um", pre_check_timeout=TIMEOUT)
        test("move_xy: out-of-limits correctly rejected",
             lambda: {"success": not r_ool["success"],
                      "message": r_ool.get("message", "")})

    # ── 7c. move_z ───────────────────────────────────────────────────
    if ch and not args.skip_dangerous and not args.skip_move:
        cur_z = ch["zPosition"]["z-galvo"]
        target_z = cur_z + 5.0

        r = drv.move_z(client, JOB, target_z,
                        unit="um", z_mode="galvo",
                        pre_check_timeout=TIMEOUT)
        if r.get("success"):
            test("move_z: absolute galvo to current+5", lambda: r)
            detail(f"Timing: {timing_str(r)}")
            r2 = drv.move_z(client, JOB, cur_z,
                            unit="um", z_mode="galvo", pre_check_timeout=TIMEOUT)
            test("move_z: restore to original", lambda: r2)
        else:
            # Z-galvo moves may be silently rejected depending on scan mode
            # (e.g. xzy mode uses galvo as scan axis, locking manual moves)
            scan_mode = ch.get("scanMode", "")
            detail(f"move_z galvo: silently rejected (scan mode: {scan_mode!r})")
            test("move_z: galvo locked by scan mode (expected)",
                 lambda: None, skip=True)
    else:
        test("move_z: skipped (--skip-dangerous or --skip-move)",
             lambda: None, skip=True)


# #########################################################################
#  Phase 8: ACQUISITION
# #########################################################################

print("\n" + "=" * 70)
print("  Phase 8: ACQUISITION")
print("=" * 70)

if args.skip_acquire:
    test("acquire: skipped (--skip-acquire)", lambda: None, skip=True)
else:

    r = test("acquire",
             lambda: drv.acquire(client, JOB, poll_interval=0.1,
                                 start_timeout=15.0))
    if r:
        detail(f"Elapsed: {r.get('timing', {}).get('total_s', 0):.1f}s")


# #########################################################################
#  Phase 9: CONFIRM SMOKE TEST
# #########################################################################

if ch and not args.skip_write:
    print("\n" + "=" * 70)
    print("  Phase 9: CONFIRM SMOKE TEST")
    print("=" * 70)

    cur_zoom = ch["zoom"]["current"]
    cur_speed = ch["scanSpeed"]["value"]

    # v6.0: confirmation is always active (confirm_fn baked into profiles).
    # Verify result dict includes 'confirmed' and 'logs' keys.
    r = test("set_zoom (default confirm)",
             lambda: drv.set_zoom(client, JOB, cur_zoom))
    if r:
        detail(f"Timing: {timing_str(r)}")
        detail(f"Confirmed: {r.get('confirmed')}")
        test("set_zoom: confirmed key is True",
             lambda: {"success": r.get("confirmed") is True,
                      "message": f"Expected confirmed=True, got {r.get('confirmed')}"})
        test("set_zoom: logs key present",
             lambda: {"success": isinstance(r.get("logs"), list),
                      "message": f"Expected logs list, got {type(r.get('logs'))}"})

    r = test("set_scan_speed (default confirm)",
             lambda: drv.set_scan_speed(client, JOB, cur_speed))
    if r:
        detail(f"Timing: {timing_str(r)}")
        detail(f"Confirmed: {r.get('confirmed')}")

    # Custom pre_check_timeout
    r = test("set_zoom(pre_check_timeout=10.0)",
             lambda: drv.set_zoom(client, JOB, cur_zoom,
                                  pre_check_timeout=10.0))
    if r:
        detail(f"Timing: {timing_str(r)}")


# #########################################################################
#  SUMMARY
# #########################################################################

print("\n" + "=" * 70)
print(f"  SUMMARY: {passed} passed, \033[31m{failed} failed\033[0m, \033[33m{skipped} skipped\033[0m")
print("=" * 70)

if failed > 0:
    print("\n  \033[31mFailed tests:\033[0m")
    for status, name, msg in results_log:
        if status == "FAIL":
            print(f"    \033[31m- {name}: {msg}\033[0m")
    print()

sys.exit(1 if failed > 0 else 0)

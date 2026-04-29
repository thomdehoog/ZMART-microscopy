"""
Stress Test — Random Setting Barrage
======================================
Fires all available set_* commands in random order with random valid
values. Designed to surface race conditions, state corruption, and
timing issues under rapid unstructured load.

Usage:
    python test_stress.py                          # default: 50 rounds x 3 cycles
    python test_stress.py --rounds 100 --cycles 5
    python test_stress.py --job HiRes --skip-move --skip-objective
    python test_stress.py --seed 12345             # replay a specific run
"""

import argparse
import sys
import time
import random
import traceback

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

parser = argparse.ArgumentParser(description="Stress Test — Random Setting Barrage")
parser.add_argument("--job", default=None)
parser.add_argument("--rounds", type=int, default=50,
                    help="Number of random commands to fire per cycle (default: 50)")
parser.add_argument("--cycles", type=int, default=3,
                    help="Number of cycles to run (default: 3)")
parser.add_argument("--skip-move", action="store_true",
                    help="Skip stage and z movement commands")
parser.add_argument("--skip-objective", action="store_true",
                    help="Skip objective switching")
parser.add_argument("--skip-acquire", action="store_true",
                    help="Skip acquisition commands")
parser.add_argument("--seed", type=int, default=None,
                    help="RNG seed for reproducibility (default: random)")
args = parser.parse_args()

if args.seed is None:
    args.seed = random.randint(0, 2**31 - 1)
random.seed(args.seed)

# ── Connect ──────────────────────────────────────────────────────────────

from LasxApi import PYLICamApiConnector as lasx_api
import navigator_expert.driver as drv

client = lasx_api.LasxApiClientPyModel
assert client.Connect("PythonClient"), "Cannot connect to LAS X"

drv.set_stage_limits(
    x_min=1000, x_max=130000,
    y_min=1000, y_max=100000,
    z_galvo_min=-200, z_galvo_max=200,
    z_wide_min=0, z_wide_max=25000,
)

# ── Resolve job and read baseline ────────────────────────────────────────

jobs = drv.get_jobs(client)
names = [j["Name"] for j in jobs]
JOB = args.job or next((j["Name"] for j in jobs if j.get("IsSelected")), names[0])
assert JOB in names, f"Job '{JOB}' not found. Available: {names}"

drv.select_job(client, JOB)

hw = drv.get_hardware_info(client)
settings = drv.get_job_settings(client, JOB)
orig = drv.make_changeable_copy(settings)

print(f"Job: {JOB}")
print(f"Objectives: {[o['name'].strip() for o in hw['Microscope']['objectives']]}")
print(f"Rounds: {args.rounds} x {args.cycles} cycles = {args.rounds * args.cycles}")
print(f"Seed: {args.seed}")
print()

# ── Save originals for restore ───────────────────────────────────────────

ORIG_ZOOM = orig["zoom"]["current"]
ORIG_SPEED = orig["scanSpeed"]["value"]
ORIG_RESONANT = orig["scanSpeed"]["isResonant"]
ORIG_MODE = orig["scanMode"]
ORIG_ROTATION = orig["scanFieldRotation"].get("value", 0.0)
ORIG_FORMAT = orig["format"]
ORIG_OBJ = orig["objective"].get("name", "")

si = orig["activeSettings"][0]
ORIG_FA = si["frameAccumulation"]
ORIG_FAVG = si["frameAverage"]
ORIG_LA = si["lineAccumulation"]
ORIG_LAVG = si["lineAverage"]
ORIG_DETECTORS = {}
for d in si.get("activeDetectors", []):
    br = d.get("_beamRoute", "")
    gain = d.get("gain", {}).get("value")
    gain_min = d.get("gain", {}).get("min")
    gain_max = d.get("gain", {}).get("max")
    if gain is not None and (gain_min is None or gain_max is None or
                              abs(gain_max - gain_min) > 0.1):
        ORIG_DETECTORS[br] = gain

ORIG_LASERS = {}
for l in si.get("activeLaserLines", []):
    br = l.get("_beamRoute", "")
    li = l.get("_lineIndex", 0)
    intensity = l.get("intensity", {}).get("value")
    if intensity is not None:
        ORIG_LASERS[(br, li)] = intensity

pos = drv.get_xy(client)
ORIG_X, ORIG_Y = pos["x_um"], pos["y_um"]

objectives = hw.get("Microscope", {}).get("objectives", [])
obj_names = [o["name"] for o in objectives if o.get("objectiveNumber", 0) != 0]

# ── Define command pool ──────────────────────────────────────────────────

# Valid zoom/speed pairs — LAS X silently adjusts zoom at high speeds.
# Table generated from test_zoom_speed_combos.py.
ZOOM_MAX_SPEED = {
    5.0: 1400,  7.0: 1600,  10.0: 1800,
    15.0: 1800,  20.0: 2000,  30.0: 2000,  48.0: 2000,
}
ZOOMS = list(ZOOM_MAX_SPEED.keys())
SPEEDS = [400, 600, 800, 1000, 1200, 1400, 1600, 1800, 2000]
FORMATS = ["128 x 128", "256 x 256", "512 x 512", "1024 x 1024"]
MODES = ["xyz"]
FA_VALID = [1, 2, 3, 4, 6, 8]
LAVG_VALID = [1, 2, 4, 8]
ROTATIONS = [0.0, 5.0, 10.0, 15.0, 30.0, 45.0, 90.0]


def make_commands():
    """Build the pool of (name, callable) pairs."""
    cmds = []

    # Job-level settings — zoom and speed are set together to avoid
    # invalid combos (LAS X silently adjusts zoom at high speeds).
    def _set_zoom_speed():
        zoom = random.choice(ZOOMS)
        max_spd = ZOOM_MAX_SPEED[zoom]
        speed = random.choice([s for s in SPEEDS if s <= max_spd])
        # Drop speed to minimum first so LAS X accepts any zoom change
        rs = drv.set_scan_speed(client, JOB, min(SPEEDS))
        if not rs.get("success"):
            return rs
        rz = drv.set_zoom(client, JOB, zoom)
        if not rz.get("success"):
            return rz
        return drv.set_scan_speed(client, JOB, speed)
    cmds.append(("zoom_speed", _set_zoom_speed))
    cmds.append(("mode", lambda: drv.set_scan_mode(
        client, JOB, random.choice(MODES))))
    cmds.append(("format", lambda: drv.set_image_format(
        client, JOB, random.choice(FORMATS))))
    cmds.append(("rotation", lambda: drv.set_scan_field_rotation(
        client, JOB, random.choice(ROTATIONS))))

    # Per-setting (setting index 0)
    cmds.append(("frame_acc", lambda: drv.set_frame_accumulation(
        client, JOB, 0, random.choice(FA_VALID))))
    cmds.append(("frame_avg", lambda: drv.set_frame_average(
        client, JOB, 0, random.randint(1, 4))))
    cmds.append(("line_acc", lambda: drv.set_line_accumulation(
        client, JOB, 0, random.randint(1, 4))))
    cmds.append(("line_avg", lambda: drv.set_line_average(
        client, JOB, 0, random.choice(LAVG_VALID))))
    # Pinhole — removed: valid AU range is objective-dependent
    # Detectors — skipped (gain readback unreliable during laser stabilization)
    # for br in ORIG_DETECTORS:
    #     cmds.append((f"gain[{br}]", lambda _br=br: drv.set_detector_gain(
    #         client, JOB, 0, _br, random.uniform(1.0, 50.0))))

    # Lasers
    for (br, li) in ORIG_LASERS:
        cmds.append((f"laser[{br}:{li}]", lambda _br=br, _li=li:
            drv.set_laser_intensity(
                client, JOB, 0, _br, _li, random.uniform(0.01, 0.2))))

    # Objective
    if not args.skip_objective and len(obj_names) > 1:
        cmds.append(("objective", lambda: drv.set_objective(
            client, JOB, hw, name=random.choice(obj_names))))

    # Acquire
    if not args.skip_acquire:
        cmds.append(("acquire", lambda: drv.acquire(client, JOB)))

    # Stage movement
    if not args.skip_move:
        cmds.append(("move_xy", lambda: drv.move_xy(
            client,
            random.randint(32322, 93979),
            random.randint(31176, 51986),
            unit="um")))
        cmds.append(("move_z", lambda: drv.move_z(
            client, JOB, random.uniform(-10.0, 10.0),
            unit="um", z_mode="galvo")))

    return cmds


commands = make_commands()
print(f"Command pool: {len(commands)} commands")
print(f"  {', '.join(name for name, _ in commands)}")
print()

# ── Run stress test ──────────────────────────────────────────────────────

results = []  # (round, name, success, elapsed, message)
t_start = time.perf_counter()
total_rounds = args.rounds * args.cycles
round_num = 0

for cycle in range(1, args.cycles + 1):
    if args.cycles > 1:
        print(f"  -- Cycle {cycle}/{args.cycles} --")
    for i in range(1, args.rounds + 1):
        round_num += 1
        name, fn = random.choice(commands)
        t0 = time.perf_counter()
        try:
            r = fn()
            elapsed = time.perf_counter() - t0
            ok = r.get("success", False) if isinstance(r, dict) else bool(r)
            msg = "" if ok else r.get("message", "unknown")[:80] if isinstance(r, dict) else ""
            confirmed = r.get("confirmed", None) if isinstance(r, dict) else None
        except Exception as e:
            elapsed = time.perf_counter() - t0
            ok = False
            msg = f"EXCEPTION: {e}"
            confirmed = None

        status = "\033[32mOK\033[0m" if ok else "\033[31mFAIL\033[0m"
        conf_tag = ""
        if confirmed is False:
            conf_tag = " \033[33m[UNCONFIRMED]\033[0m"
        # Show timing breakdown for slow commands (>3s)
        timing_tag = ""
        if isinstance(r, dict) and elapsed > 3.0:
            t = r.get("timing", {})
            parts = []
            for k in ("pre_check_s", "setup_s", "fire_s", "check_s", "confirm_s"):
                v = t.get(k)
                if v is not None and v > 0.01:
                    parts.append(f"{k.replace('_s','')}={v:.1f}s")
            if parts:
                timing_tag = f"  [{', '.join(parts)}]"
        print(f"  [{round_num:4d}/{total_rounds}] {status} {name:20s} {elapsed:.3f}s{conf_tag}"
              f"{timing_tag}{'  ' + msg if msg else ''}")

        results.append((round_num, name, ok, elapsed, msg, confirmed))

t_total = time.perf_counter() - t_start

# ── Restore ──────────────────────────────────────────────────────────────

print(f"\n{'='*60}")
print("  RESTORING ORIGINAL SETTINGS")
print(f"{'='*60}")

restore_errors = []

def safe_restore(label, fn):
    try:
        r = fn()
        ok = r.get("success", False) if isinstance(r, dict) else bool(r)
        if ok:
            print(f"  \033[32mOK\033[0m  {label}")
        else:
            print(f"  \033[31mFAIL\033[0m  {label}: {r.get('message', '')[:60]}")
            restore_errors.append(label)
    except Exception as e:
        print(f"  \033[31mFAIL\033[0m  {label}: {e}")
        restore_errors.append(label)

# Restore in a sensible order: objective first (slow), then settings
if not args.skip_objective:
    safe_restore("objective", lambda: drv.set_objective(
        client, JOB, hw, name=ORIG_OBJ))

safe_restore("scan_mode", lambda: drv.set_scan_mode(client, JOB, ORIG_MODE))
safe_restore("zoom", lambda: drv.set_zoom(client, JOB, ORIG_ZOOM))
safe_restore("speed", lambda: drv.set_scan_speed(client, JOB, ORIG_SPEED))
safe_restore("rotation", lambda: drv.set_scan_field_rotation(client, JOB, ORIG_ROTATION))
safe_restore("format", lambda: drv.set_image_format(client, JOB, ORIG_FORMAT))
safe_restore("frame_acc", lambda: drv.set_frame_accumulation(client, JOB, 0, ORIG_FA))
safe_restore("frame_avg", lambda: drv.set_frame_average(client, JOB, 0, ORIG_FAVG))
safe_restore("line_acc", lambda: drv.set_line_accumulation(client, JOB, 0, ORIG_LA))
safe_restore("line_avg", lambda: drv.set_line_average(client, JOB, 0, ORIG_LAVG))
# for br, gain in ORIG_DETECTORS.items():
#     safe_restore(f"gain[{br}]", lambda _br=br, _g=gain:
#         drv.set_detector_gain(client, JOB, 0, _br, _g))

for (br, li), intensity in ORIG_LASERS.items():
    safe_restore(f"laser[{br}:{li}]", lambda _br=br, _li=li, _v=intensity:
        drv.set_laser_intensity(client, JOB, 0, _br, _li, _v))

if not args.skip_move:
    safe_restore("move_xy", lambda: drv.move_xy(
        client, ORIG_X, ORIG_Y, unit="um"))

# ── Summary ──────────────────────────────────────────────────────────────

passed = sum(1 for _, _, ok, _, _, _ in results if ok)
failed = sum(1 for _, _, ok, _, _, _ in results if not ok)
unconfirmed = sum(1 for _, _, _, _, _, c in results if c is False)
times = [e for _, _, ok, e, _, _ in results if ok]

print(f"\n{'='*60}")
print(f"  STRESS TEST SUMMARY")
print(f"{'='*60}")
print(f"  Rounds:       {total_rounds} ({args.rounds} x {args.cycles})")
print(f"  Passed:       \033[32m{passed}\033[0m")
print(f"  Failed:       \033[31m{failed}\033[0m")
print(f"  Unconfirmed:  \033[33m{unconfirmed}\033[0m")
print(f"  Total time:   {t_total:.1f}s")
if times:
    print(f"  Per-command:  min={min(times):.3f}s  max={max(times):.3f}s  "
          f"avg={sum(times)/len(times):.3f}s")

# Per-command breakdown
print(f"\n  Per-command breakdown:")
cmd_names = sorted(set(n for _, n, _, _, _, _ in results))
for cn in cmd_names:
    cmd_results = [(ok, e, c) for _, n, ok, e, _, c in results if n == cn]
    n_ok = sum(1 for ok, _, _ in cmd_results if ok)
    n_fail = sum(1 for ok, _, _ in cmd_results if not ok)
    n_unc = sum(1 for _, _, c in cmd_results if c is False)
    cmd_times = [e for ok, e, _ in cmd_results if ok]
    avg_t = sum(cmd_times) / len(cmd_times) if cmd_times else 0
    max_t = max(cmd_times) if cmd_times else 0
    status_parts = [f"\033[32m{n_ok} ok\033[0m"]
    if n_fail:
        status_parts.append(f"\033[31m{n_fail} fail\033[0m")
    if n_unc:
        status_parts.append(f"\033[33m{n_unc} unc\033[0m")
    print(f"    {cn:20s}  {', '.join(status_parts):40s}  "
          f"avg={avg_t:.3f}s  max={max_t:.3f}s  n={len(cmd_results)}")

if failed > 0:
    print(f"\n  \033[31mFailures:\033[0m")
    for i, name, ok, elapsed, msg, _ in results:
        if not ok:
            print(f"    [{i}] {name}: {msg}")

if restore_errors:
    print(f"\n  \033[31mRestore errors: {restore_errors}\033[0m")

print(f"{'='*60}")
sys.exit(1 if failed > 0 else 0)

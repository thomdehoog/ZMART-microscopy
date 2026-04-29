"""
Test Objective Switching
========================
Cycles through all available objectives on the turret, verifying that
each switch is confirmed by readback. Optionally cycles multiple times
to catch intermittent failures.

Usage:
    python test_objective.py
    python test_objective.py --cycles 3
    python test_objective.py --job HiRes --cycles 5
"""

import argparse
import sys
import time

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

parser = argparse.ArgumentParser(description="Test Objective Switching")
parser.add_argument("--job", default=None)
parser.add_argument("--cycles", type=int, default=1,
                    help="Number of full cycles through all objectives (default: 1)")
args = parser.parse_args()

# ── Connect ──────────────────────────────────────────────────────────────

from LasxApi import PYLICamApiConnector as lasx_api
import navigator_expert.driver as drv

client = lasx_api.LasxApiClientPyModel
assert client.Connect("PythonClient"), "Cannot connect to LAS X"

# ── Resolve job ──────────────────────────────────────────────────────────

jobs = drv.get_jobs(client)
names = [j["Name"] for j in jobs]
JOB = args.job or next((j["Name"] for j in jobs if j.get("IsSelected")), names[0])
assert JOB in names, f"Job '{JOB}' not found. Available: {names}"

drv.select_job(client, JOB)

hw = drv.get_hardware_info(client)
settings = drv.get_job_settings(client, JOB)
orig = drv.make_changeable_copy(settings)
ORIG_OBJ = orig["objective"].get("name", "").strip()

objectives = hw.get("Microscope", {}).get("objectives", [])
obj_names = [o["name"].strip() for o in objectives]

print(f"Job: {JOB}")
print(f"Original objective: {ORIG_OBJ}")
print(f"Available objectives ({len(obj_names)}):")
for o in objectives:
    name = o["name"].strip()
    slot = o.get("slotIndex", "?")
    mag = o.get("magnification", "?")
    print(f"  slot {slot}: {name} ({mag}x)")
print(f"Cycles: {args.cycles}")
print()

# ── Run test ─────────────────────────────────────────────────────────────

results = []  # (cycle, name, success, elapsed, message)
total = args.cycles * len(obj_names)
count = 0

for cycle in range(1, args.cycles + 1):
    for obj_name in obj_names:
        count += 1
        t0 = time.perf_counter()
        try:
            r = drv.set_objective(client, JOB, hw, name=obj_name)
            elapsed = time.perf_counter() - t0
            ok = r.get("success", False)
            confirmed = r.get("confirmed", None)
            msg = "" if ok else r.get("message", "unknown")[:80]
        except Exception as e:
            elapsed = time.perf_counter() - t0
            ok = False
            confirmed = None
            msg = f"EXCEPTION: {e}"

        status = "\033[32mOK\033[0m" if ok else "\033[31mFAIL\033[0m"
        conf_tag = ""
        if confirmed is False:
            conf_tag = " \033[33m[UNCONFIRMED]\033[0m"

        print(f"  [{count:3d}/{total}] {status} {obj_name:45s} {elapsed:.3f}s{conf_tag}"
              f"{'  ' + msg if msg else ''}")

        results.append((cycle, obj_name, ok, elapsed, msg))

# ── Restore ──────────────────────────────────────────────────────────────

print(f"\n{'='*60}")
print("  RESTORING ORIGINAL OBJECTIVE")
print(f"{'='*60}")

try:
    r = drv.set_objective(client, JOB, hw, name=ORIG_OBJ)
    ok = r.get("success", False)
    if ok:
        print(f"  \033[32mOK\033[0m  {ORIG_OBJ}")
    else:
        print(f"  \033[31mFAIL\033[0m  {ORIG_OBJ}: {r.get('message', '')[:60]}")
except Exception as e:
    print(f"  \033[31mFAIL\033[0m  {ORIG_OBJ}: {e}")

# ── Summary ──────────────────────────────────────────────────────────────

passed = sum(1 for _, _, ok, _, _ in results if ok)
failed = sum(1 for _, _, ok, _, _ in results if not ok)
times = [e for _, _, ok, e, _ in results if ok]

print(f"\n{'='*60}")
print(f"  OBJECTIVE TEST SUMMARY")
print(f"{'='*60}")
print(f"  Total:   {len(results)}")
print(f"  Passed:  \033[32m{passed}\033[0m")
print(f"  Failed:  \033[31m{failed}\033[0m")
if times:
    print(f"  Timing:  min={min(times):.3f}s  max={max(times):.3f}s  "
          f"avg={sum(times)/len(times):.3f}s")

# Per-objective breakdown
print(f"\n  Per-objective breakdown:")
for obj_name in obj_names:
    obj_results = [(ok, e) for _, n, ok, e, _ in results if n == obj_name]
    n_ok = sum(1 for ok, _ in obj_results if ok)
    n_fail = sum(1 for ok, _ in obj_results if not ok)
    obj_times = [e for ok, e in obj_results if ok]
    avg_t = sum(obj_times) / len(obj_times) if obj_times else 0
    max_t = max(obj_times) if obj_times else 0
    status = f"\033[32m{n_ok} ok\033[0m"
    if n_fail:
        status += f", \033[31m{n_fail} fail\033[0m"
    print(f"    {obj_name:45s}  {status:40s}  avg={avg_t:.3f}s  max={max_t:.3f}s")

if failed > 0:
    print(f"\n  \033[31mFailures:\033[0m")
    for cycle, name, ok, elapsed, msg in results:
        if not ok:
            print(f"    [cycle {cycle}] {name}: {msg}")

print(f"{'='*60}")
sys.exit(1 if failed > 0 else 0)

"""
Integration Test: Alignment Coordinate Translation
====================================================
Verifies that objective switching + coordinate translation produces
consistent positions on real hardware.

Tests:
  1. Switch objectives, read XY, verify motor_delta matches calibration.
  2. Translate a position from ref to target, move there, verify readback.
  3. Round-trip: ref -> target -> ref, verify position is preserved.

Usage:
    python test_alignment_integration.py
    python test_alignment_integration.py --alignment path/to/alignment_results.json
    python test_alignment_integration.py --job MyJob --tolerance 5
"""

import argparse
import os
import sys
import time

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

parser = argparse.ArgumentParser(description="Alignment Integration Test")
parser.add_argument("--job", default=None)
parser.add_argument("--alignment", default=None,
                    help="Path to alignment_results.json "
                         "(default: latest in config/alignment/)")
parser.add_argument("--tolerance", type=float, default=5.0,
                    help="Position tolerance in um (default: 5.0)")
args = parser.parse_args()

# ── Import ──────────────────────────────────────────────────────────────

from LasxApi import PYLICamApiConnector as lasx_api
import lasx as drv
from lasx.alignment import load_alignment, translate_xy, translate_z
from lasx.prechecks import check_idle

# ── Connect ─────────────────────────────────────────────────────────────

client = lasx_api.LasxApiClientPyModel
assert client.Connect("PythonClient"), "Cannot connect to LAS X"
assert drv.ping(client), "Ping failed"

jobs = drv.get_jobs(client)
names = [j["Name"] for j in jobs]
JOB = args.job or next((j["Name"] for j in jobs if j.get("IsSelected")), names[0])
assert JOB in names, f"Job '{JOB}' not found. Available: {names}"

drv.select_job(client, JOB)
time.sleep(1)

hw = drv.get_hardware_info(client)
assert hw, "Cannot read hardware info"

# ── Load alignment ──────────────────────────────────────────────────────

if args.alignment:
    al_path = args.alignment
else:
    al_dir = os.path.join(
        str(Path(__file__).resolve().parent.parent), "config", "alignment")
    runs = sorted(os.listdir(al_dir)) if os.path.isdir(al_dir) else []
    runs = [r for r in runs if os.path.isfile(
        os.path.join(al_dir, r, "alignment_results.json"))]
    assert runs, f"No alignment runs found in {al_dir}"
    al_path = os.path.join(al_dir, runs[-1], "alignment_results.json")

al = load_alignment(al_path)
print(f"Alignment: {al_path}")
print(f"  Reference: slot {al['ref_slot']} ({al['ref_objective']})")
for slot, off in al["offsets"].items():
    tx, ty = off["total_xy_um"]
    print(f"  Slot {slot} ({off['label']}): total=({tx:+.1f}, {ty:+.1f}) um, "
          f"dz={off['image_z_um']:+.1f} um")

# ── Resolve calibrated objectives in hardware ───────────────────────────

all_slots = [al["ref_slot"]] + list(al["offsets"].keys())
objs_by_slot = {}
for o in hw.get("Microscope", {}).get("objectives", []):
    if o.get("objectiveNumber", 0) != 0:
        objs_by_slot[o["slotIndex"]] = o

for s in all_slots:
    assert s in objs_by_slot, (
        f"Calibrated slot {s} not found in hardware. "
        f"Available: {list(objs_by_slot.keys())}")

# ── Save original state ────────────────────────────────────────────────

settings = drv.get_job_settings(client, JOB)
orig_slot = settings["objective"]["slotIndex"]
orig_pos = drv.get_xy(client)
print(f"\nOriginal: slot {orig_slot}, "
      f"pos=({orig_pos['x_um']:.1f}, {orig_pos['y_um']:.1f}) um")

# ── Test helpers ────────────────────────────────────────────────────────

results = []
TOL = args.tolerance


def check(name, ok, msg=""):
    status = "PASS" if ok else "FAIL"
    results.append((name, ok, msg))
    tag = "\033[32mPASS\033[0m" if ok else "\033[31mFAIL\033[0m"
    print(f"  [{tag}] {name}" + (f"  ({msg})" if msg else ""))


def switch_to(slot):
    """Switch objective and wait for idle."""
    r = drv.set_objective(client, JOB, hw, slot_index=slot)
    assert r["success"], f"set_objective slot {slot} failed: {r['message']}"
    time.sleep(2)
    drv.select_job(client, JOB)
    time.sleep(1)


# ── Test 1: Motor delta matches calibration ─────────────────────────────

print(f"\n{'='*60}")
print("  TEST 1: Motor delta matches calibration")
print(f"{'='*60}")

ref_slot = al["ref_slot"]
switch_to(ref_slot)
ref_pos = drv.get_xy(client)
print(f"  Reference position: ({ref_pos['x_um']:.3f}, {ref_pos['y_um']:.3f}) um")

for tgt_slot, off in al["offsets"].items():
    switch_to(tgt_slot)
    tgt_pos = drv.get_xy(client)

    measured_dx = tgt_pos["x_um"] - ref_pos["x_um"]
    measured_dy = tgt_pos["y_um"] - ref_pos["y_um"]
    expected_mx, expected_my = off["motor_xy_um"]

    err_x = abs(measured_dx - expected_mx)
    err_y = abs(measured_dy - expected_my)

    check(
        f"motor_delta slot {ref_slot}->{tgt_slot}",
        err_x < TOL and err_y < TOL,
        f"measured=({measured_dx:+.1f}, {measured_dy:+.1f}), "
        f"expected=({expected_mx:+.1f}, {expected_my:+.1f}), "
        f"err=({err_x:.1f}, {err_y:.1f}) um"
    )

    # Switch back to ref for next iteration
    switch_to(ref_slot)

# ── Test 2: Translate + move lands at correct position ──────────────────

print(f"\n{'='*60}")
print("  TEST 2: Translate + move accuracy")
print(f"{'='*60}")

switch_to(ref_slot)
ref_pos = drv.get_xy(client)
ref_x, ref_y = ref_pos["x_um"], ref_pos["y_um"]
print(f"  Reference position: ({ref_x:.3f}, {ref_y:.3f}) um")

for tgt_slot in al["offsets"]:
    # Translate ref position to target space
    tgt_x, tgt_y = translate_xy(ref_x, ref_y, ref_slot, tgt_slot, al)
    print(f"  Translated to slot {tgt_slot}: ({tgt_x:.3f}, {tgt_y:.3f}) um")

    # Switch and move
    switch_to(tgt_slot)
    drv.move_xy(client, tgt_x, tgt_y)
    time.sleep(1)

    # Read back
    actual = drv.get_xy(client)
    err_x = abs(actual["x_um"] - tgt_x)
    err_y = abs(actual["y_um"] - tgt_y)

    check(
        f"translate+move slot {ref_slot}->{tgt_slot}",
        err_x < TOL and err_y < TOL,
        f"target=({tgt_x:.1f}, {tgt_y:.1f}), "
        f"actual=({actual['x_um']:.1f}, {actual['y_um']:.1f}), "
        f"err=({err_x:.1f}, {err_y:.1f}) um"
    )

    switch_to(ref_slot)

# ── Test 3: Round-trip translation ──────────────────────────────────────

print(f"\n{'='*60}")
print("  TEST 3: Round-trip ref -> target -> ref")
print(f"{'='*60}")

switch_to(ref_slot)
start_pos = drv.get_xy(client)
start_x, start_y = start_pos["x_um"], start_pos["y_um"]
print(f"  Start: ({start_x:.3f}, {start_y:.3f}) um")

for tgt_slot in al["offsets"]:
    # Ref -> target
    tgt_x, tgt_y = translate_xy(start_x, start_y, ref_slot, tgt_slot, al)
    switch_to(tgt_slot)
    drv.move_xy(client, tgt_x, tgt_y)
    time.sleep(1)

    # Target -> ref
    back_x, back_y = translate_xy(tgt_x, tgt_y, tgt_slot, ref_slot, al)
    switch_to(ref_slot)
    drv.move_xy(client, back_x, back_y)
    time.sleep(1)

    end_pos = drv.get_xy(client)
    err_x = abs(end_pos["x_um"] - start_x)
    err_y = abs(end_pos["y_um"] - start_y)

    check(
        f"round-trip via slot {tgt_slot}",
        err_x < TOL and err_y < TOL,
        f"start=({start_x:.1f}, {start_y:.1f}), "
        f"end=({end_pos['x_um']:.1f}, {end_pos['y_um']:.1f}), "
        f"err=({err_x:.1f}, {err_y:.1f}) um"
    )

# ── Restore ─────────────────────────────────────────────────────────────

print(f"\n{'='*60}")
print("  RESTORING ORIGINAL STATE")
print(f"{'='*60}")

switch_to(orig_slot)
drv.move_xy(client, orig_pos["x_um"], orig_pos["y_um"])
time.sleep(1)
final = drv.get_xy(client)
err = ((final["x_um"] - orig_pos["x_um"])**2 +
       (final["y_um"] - orig_pos["y_um"])**2)**0.5
print(f"  Restored to slot {orig_slot}, "
      f"pos=({final['x_um']:.1f}, {final['y_um']:.1f}) um, "
      f"err={err:.1f} um")

# ── Summary ─────────────────────────────────────────────────────────────

passed = sum(1 for _, ok, _ in results if ok)
failed = sum(1 for _, ok, _ in results if not ok)

print(f"\n{'='*60}")
print(f"  ALIGNMENT TEST SUMMARY")
print(f"{'='*60}")
print(f"  Total:   {len(results)}")
print(f"  Passed:  \033[32m{passed}\033[0m")
print(f"  Failed:  \033[31m{failed}\033[0m")
print(f"  Tolerance: {TOL} um")

if failed:
    print(f"\n  \033[31mFailures:\033[0m")
    for name, ok, msg in results:
        if not ok:
            print(f"    {name}: {msg}")

print(f"{'='*60}")
sys.exit(1 if failed > 0 else 0)

"""
Parcentric Offset Measurement
===============================
Measures the parcentric offset of each objective relative to the 10x
by switching objectives and reading stage XY positions.

The 10x is the reference (0, 0). All offsets are deterministic and
reproducible (std=0 over 10 switches).

Usage:
    python test_parcentric_offset.py
    python test_parcentric_offset.py --reference 20
    python test_parcentric_offset.py --repeats 5
"""

import argparse
import json
import os
import sys
import time
import logging

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

parser = argparse.ArgumentParser(description="Parcentric Offset Measurement")
parser.add_argument("--reference", type=float, default=10,
                    help="Reference objective magnification (default: 10)")
parser.add_argument("--repeats", type=int, default=1,
                    help="Number of measurement repeats (default: 1)")
parser.add_argument("--output", default=None,
                    help="Output JSON path (default: Desktop/parcentric_offsets.json)")
args = parser.parse_args()

# ── Import ──────────────────────────────────────────────────────────────

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from LasxApi import PYLICamApiConnector as lasx_api
import navigator_expert.driver as drv

# ── Connect ─────────────────────────────────────────────────────────────

client = lasx_api.LasxApiClientPyModel
confirmed = client.Connect("PythonClient")
if not confirmed:
    print("  ABORT: Cannot connect to LAS X.")
    sys.exit(1)

if not drv.ping(client):
    print("  ABORT: ping failed")
    sys.exit(1)

job = drv.get_selected_job(client).get("Name")
hw = drv.get_hardware_info(client)

objs = [o for o in hw.get("Microscope", {}).get("objectives", [])
        if o.get("objectiveNumber", 0) != 0]

ref_obj = None
other_objs = []
for o in objs:
    if o.get("magnification") == args.reference:
        if ref_obj is None:
            ref_obj = o
    else:
        other_objs.append(o)

if ref_obj is None:
    print(f"  ABORT: no objective with magnification {args.reference}x found")
    sys.exit(1)

ref_name = ref_obj.get("name", "").strip()

# ── Measure ─────────────────────────────────────────────────────────────

print(f"\n{'=' * 70}")
print(f"  Parcentric Offset Measurement — reference: {ref_name}")
print(f"  Job: {job}, Repeats: {args.repeats}")
print(f"{'=' * 70}\n")

results = {}

for repeat in range(args.repeats):
    if args.repeats > 1:
        print(f"  --- Repeat {repeat + 1}/{args.repeats} ---")

    # Go to reference objective
    drv.set_objective(client, job, hw, name=ref_name)
    time.sleep(3)
    ref_pos = drv.get_xy(client)
    rx, ry = ref_pos["x_um"], ref_pos["y_um"]

    if repeat == 0:
        print(f"  {'Objective':<45}  {'dX (um)':>10}  {'dY (um)':>10}")
        print(f"  {'-'*45}  {'-'*10}  {'-'*10}")
        print(f"  {ref_name + ' (reference)':<45}  {0:>+10.2f}  {0:>+10.2f}")

    # Switch to each other objective
    for obj in other_objs:
        name = obj.get("name", "").strip()
        drv.set_objective(client, job, hw, name=name)
        time.sleep(3)
        pos = drv.get_xy(client)
        dx = pos["x_um"] - rx
        dy = pos["y_um"] - ry

        if name not in results:
            results[name] = {"dx": [], "dy": [], "magnification": obj.get("magnification")}
        results[name]["dx"].append(dx)
        results[name]["dy"].append(dy)

        if repeat == 0:
            print(f"  {name:<45}  {dx:>+10.2f}  {dy:>+10.2f}")

# ── Summary ─────────────────────────────────────────────────────────────

output = {
    "reference": ref_name,
    "reference_magnification": args.reference,
    "repeats": args.repeats,
    "offsets": {},
}

if args.repeats > 1:
    import statistics
    print(f"\n  {'Objective':<45}  {'dX mean':>10}  {'dY mean':>10}  {'dX std':>8}  {'dY std':>8}")
    print(f"  {'-'*45}  {'-'*10}  {'-'*10}  {'-'*8}  {'-'*8}")

for name, data in results.items():
    dx_mean = sum(data["dx"]) / len(data["dx"])
    dy_mean = sum(data["dy"]) / len(data["dy"])
    output["offsets"][name] = {
        "dx_um": round(dx_mean, 2),
        "dy_um": round(dy_mean, 2),
        "magnification": data["magnification"],
    }
    if args.repeats > 1:
        import statistics
        dx_std = statistics.stdev(data["dx"]) if len(data["dx"]) > 1 else 0
        dy_std = statistics.stdev(data["dy"]) if len(data["dy"]) > 1 else 0
        print(f"  {name:<45}  {dx_mean:>+10.2f}  {dy_mean:>+10.2f}  {dx_std:>8.2f}  {dy_std:>8.2f}")

# ── Save ────────────────────────────────────────────────────────────────

out_path = args.output or os.path.join(os.path.expanduser("~"), "Desktop", "parcentric_offsets.json")
with open(out_path, "w") as f:
    json.dump(output, f, indent=2)

print(f"\n  Saved to: {out_path}")
print(f"{'=' * 70}")

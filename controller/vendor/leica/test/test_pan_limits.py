"""
Pan Limit Discovery
====================
Automated script to discover the maximum pan range at different zoom levels.

Two modes:
  --no-refresh  (default) Set pan to a test value, save/load, read back.
                LAS X may or may not clip depending on zoom.
  --refresh     Same but also triggers refresh_display (AcquireSingleImage
                + StopScan with shutters closed) after loading. This forces
                the hardware to clip the pan value on every zoom level.

Usage:
    python test_pan_limits.py
    python test_pan_limits.py --refresh
    python test_pan_limits.py --job "AF Job" --pan 0.01
"""

import argparse
import sys
import os
import time

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from LasxApi import PYLICamApiConnector as lasx_api
import lasx as drv
from lasx.scanning_templates import (
    TEMPLATE_XML, apply_lrp_change, find_scanning_templates_dir,
    save_experiment,
)
from lasx.scanning_template_editors_scan import lrp_set_pan, lrp_set_zoom
import xml.etree.ElementTree as ET

parser = argparse.ArgumentParser(description="Pan Limit Discovery")
parser.add_argument("--job", default="HiRes",
                    help="Job name (default: HiRes)")
parser.add_argument("--pan", type=float, default=0.01,
                    help="Pan value to test (default: 0.01)")
parser.add_argument("--refresh", action="store_true",
                    help="Trigger refresh_display to force hardware clipping")
parser.add_argument("--zooms", type=float, nargs="+",
                    default=[1, 2, 4, 8, 10, 15, 20, 30, 40, 48],
                    help="Zoom levels to test")
args = parser.parse_args()

# ── Connect ──────────────────────────────────────────────────────────────

client = lasx_api.LasxApiClientPyModel
confirmed = client.Connect("PythonClient")
print(f"  Connected: {confirmed}")
if not confirmed:
    print("  ABORT: Cannot connect to LAS X. Is it running?")
    sys.exit(1)

if not drv.ping(client):
    print("  ABORT: ping failed")
    sys.exit(1)

print(f"  Driver version: {drv.__version__}")

job = args.job
tdir = find_scanning_templates_dir()
lrp_path = os.path.join(tdir, TEMPLATE_XML.replace(".xml", ".lrp"))


def read_pan_zoom(lrp, job_name):
    """Read PanFirstDim, PanSecondDim, Zoom from the LRP."""
    root = ET.parse(lrp).getroot()
    for seq in root.iter("LDM_Block_Sequential"):
        if seq.get("BlockName") == job_name:
            master = seq.find(
                ".//LDM_Block_Sequential_Master/ATLConfocalSettingDefinition"
            )
            if master is not None:
                return {
                    "zoom": float(master.get("Zoom", 1)),
                    "pan_x": float(master.get("PanFirstDim", 0)),
                    "pan_y": float(master.get("PanSecondDim", 0)),
                }
    return None


# ── Run ──────────────────────────────────────────────────────────────────

mode = "WITH refresh_display" if args.refresh else "WITHOUT refresh_display"
print(f"\n{'=' * 65}")
print(f"  Pan Limit Discovery — job '{job}' — {mode}")
print(f"  Test pan value: {args.pan}")
print(f"{'=' * 65}")
print(f"  {'Zoom':>6}  {'Set':>8}  {'Pan X after':>14}  {'Pan Y after':>14}  "
      f"{'Clipped?':>8}")
print(f"  {'-' * 56}")

results = []

for z in args.zooms:
    def edit_fn(p, _z=z, _pv=args.pan):
        lrp_set_zoom(p, _z, job)
        lrp_set_pan(p, _pv, _pv, job)

    r = apply_lrp_change(client, TEMPLATE_XML, edit_fn,
                         confirm_delays=(1, 2, 4))
    if not r or not r["success"]:
        print(f"  {z:>6}  {args.pan:>8}  {'FAILED':>14}")
        continue

    if args.refresh:
        drv.refresh_display(client, job)
        time.sleep(0.3)
        # Save again to capture clipped values
        for _ in range(3):
            sr = save_experiment(client, TEMPLATE_XML, tdir, timeout=3.0)
            if sr:
                break
            time.sleep(0.3)

    vals = read_pan_zoom(lrp_path, job)
    if vals:
        clipped = "YES" if abs(vals["pan_x"]) < abs(args.pan) - 1e-9 else "no"
        results.append(vals)
        print(f"  {z:>6}  {args.pan:>8}  {vals['pan_x']:>14.10f}  "
              f"{vals['pan_y']:>14.10f}  {clipped:>8}")

# ── Summary ──────────────────────────────────────────────────────────────

if results:
    clipped_vals = [r["pan_x"] for r in results
                    if abs(r["pan_x"]) < abs(args.pan) - 1e-9]
    unclipped = [r for r in results
                 if abs(r["pan_x"]) >= abs(args.pan) - 1e-9]

    print(f"\n  {'=' * 56}")
    if clipped_vals:
        unique = set(f"{v:.8f}" for v in clipped_vals)
        if len(unique) == 1:
            print(f"  Clipped values are CONSTANT: +/-{clipped_vals[0]:.10f}")
        else:
            print(f"  Clipped values VARY:")
            for r in results:
                if abs(r["pan_x"]) < abs(args.pan) - 1e-9:
                    print(f"    Zoom {r['zoom']:>5.1f}: "
                          f"+/-{r['pan_x']:.10f}")
    if unclipped:
        print(f"  {len(unclipped)} zoom level(s) did NOT clip "
              f"(pan={args.pan} accepted as-is)")

# ── Reset ────────────────────────────────────────────────────────────────

def reset(p):
    lrp_set_zoom(p, 10, job)
    lrp_set_pan(p, 0, 0, job)

apply_lrp_change(client, TEMPLATE_XML, reset, confirm_delays=(1, 2, 4))

print(f"\n  Reset to zoom=10, pan=(0,0)")
print(f"{'=' * 65}")

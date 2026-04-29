"""
Test all zoom x speed combinations on real hardware.
======================================================
For each zoom level, sets zoom then sweeps all speeds.
After each speed change, reads back BOTH zoom and speed
to detect silent adjustments by LAS X.

Restores original settings when done.

Usage:
    python test_zoom_speed_combos.py
    python test_zoom_speed_combos.py --mock
    python test_zoom_speed_combos.py --job Overview
"""

import argparse
import sys
import time
import json
import logging

logging.basicConfig(level=logging.WARNING, format="%(name)s: %(message)s")

parser = argparse.ArgumentParser(description="Zoom x Speed combination test")
parser.add_argument("--mock", action="store_true")
parser.add_argument("--job", default=None)
parser.add_argument("--timeout", type=float, default=10.0)
args = parser.parse_args()

from pathlib import Path
# Add the leica directory to sys.path so `import lasx` works unchanged.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lasx as drv

if args.mock:
    from mock_lasx_api import MockLasxClient
    client = MockLasxClient(latency=0.0)
    print("Using MOCK client")
else:
    try:
        from LasxApi import PYLICamApiConnector as lasx_api
        client = lasx_api.LasxApiClientPyModel
        if not client.Connect("PythonClient"):
            print("ERROR: Cannot connect to LAS X")
            sys.exit(1)
        print("Connected to LAS X")
    except ImportError:
        print("ERROR: LasxApi not available. Use --mock for offline testing.")
        sys.exit(1)

# Resolve job
jobs = drv.get_jobs(client)
if not jobs:
    print("ERROR: No jobs found")
    sys.exit(1)
if args.job:
    JOB = args.job
else:
    JOB = next((j["Name"] for j in jobs if j.get("IsSelected")), jobs[0]["Name"])

print(f"Job: {JOB}")

# Save originals
ch = drv.make_changeable_copy(drv.get_job_settings(client, JOB))
orig_zoom = ch["zoom"]["current"]
orig_speed = ch["scanSpeed"]["value"]
print(f"Original: zoom={orig_zoom}, speed={orig_speed}")

TIMEOUT = args.timeout


def read_settings():
    client.PyApiGetJobSettingsByName.Model.Settings = None
    raw = drv.get_job_settings(client, JOB, timeout=5)
    if raw is None:
        return None, None
    ch = drv.make_changeable_copy(raw)
    return ch.get("zoom", {}).get("current"), ch.get("scanSpeed", {}).get("value")


def read_echo_error():
    echo = client.PyApiCommandEcho.Model
    if echo.HasError:
        return str(echo.Error)
    return None


# Test ranges
ZOOMS = [0.75, 1.0, 1.5, 2.0, 3.0, 5.0, 7.0, 10.0,
         15.0, 20.0, 30.0, 40.0, 48.0]

SPEEDS = [10, 50, 100, 200, 400, 600, 800, 1000,
          1200, 1400, 1600, 1800, 2000, 2400, 2600]

total = len(ZOOMS) * len(SPEEDS)
print(f"\nTesting {len(ZOOMS)} zooms x {len(SPEEDS)} speeds = {total} combos\n")

# Grid storage: grid[zoom][speed] = status string
grid = {}
details = []  # list of (zoom, speed, status, info)

count = 0
for zoom in ZOOMS:
    grid[zoom] = {}

    for speed in SPEEDS:
        count += 1
        sys.stdout.write(f"\r  [{count}/{total}] zoom={zoom}, speed={speed}   ")
        sys.stdout.flush()

        # Reset to a known-good baseline before each combo
        # Set a safe zoom first, then target zoom, then speed
        drv.set_zoom(client, JOB, 20.0, pre_check_timeout=TIMEOUT)
        drv.set_scan_speed(client, JOB, 400, pre_check_timeout=TIMEOUT)

        # Now set the target zoom
        rz = drv.set_zoom(client, JOB, zoom, pre_check_timeout=TIMEOUT)
        zoom_err = None
        if not rz.get("success"):
            zoom_err = read_echo_error()
            if not zoom_err:
                zoom_err = rz.get("message", "zoom failed")
            grid[zoom][speed] = "Z_ERR"
            details.append((zoom, speed, "Z_ERR", zoom_err))
            continue

        # Set the target speed
        rs = drv.set_scan_speed(client, JOB, speed, pre_check_timeout=TIMEOUT)
        speed_err = None
        if not rs.get("success"):
            speed_err = read_echo_error()
            if not speed_err:
                speed_err = rs.get("message", "speed failed")
            grid[zoom][speed] = "S_ERR"
            details.append((zoom, speed, "S_ERR", speed_err))
            continue

        # Read back actual values
        actual_zoom, actual_speed = read_settings()

        if actual_zoom is None:
            grid[zoom][speed] = "READ?"
            details.append((zoom, speed, "READ?", "readback failed"))
            continue

        zoom_ok = abs(actual_zoom - zoom) < 0.2
        speed_ok = (actual_speed == speed)

        if zoom_ok and speed_ok:
            grid[zoom][speed] = "OK"
        elif not zoom_ok and speed_ok:
            grid[zoom][speed] = f"z={actual_zoom:.1f}"
            details.append((zoom, speed, "ZOOM_ADJ",
                            f"requested zoom={zoom}, got {actual_zoom:.4f}"))
        elif zoom_ok and not speed_ok:
            grid[zoom][speed] = f"s={actual_speed}"
            details.append((zoom, speed, "SPEED_ADJ",
                            f"requested speed={speed}, got {actual_speed}"))
        else:
            grid[zoom][speed] = "BOTH"
            details.append((zoom, speed, "BOTH_ADJ",
                            f"zoom: {zoom}->{actual_zoom:.4f}, "
                            f"speed: {speed}->{actual_speed}"))

print(f"\r{'':80}")  # clear progress line


# ---- Print result grid ----

print("=" * 100)
print("RESULT GRID")
print("OK = both confirmed  |  z=N = zoom silently adjusted to N  |  "
      "Z_ERR/S_ERR = rejected")
print("=" * 100)

# Header
header = f"{'zoom':>6}"
for s in SPEEDS:
    header += f" {s:>6}"
print(header)
print("-" * len(header))

for z in ZOOMS:
    row = f"{z:>6.2f}"
    for s in SPEEDS:
        cell = grid[z].get(s, "--")
        row += f" {cell:>6}"
    print(row)


# ---- Adjustment details ----

adjustments = [d for d in details if d[2] in ("ZOOM_ADJ", "SPEED_ADJ", "BOTH_ADJ")]
errors = [d for d in details if d[2] in ("Z_ERR", "S_ERR")]

if adjustments:
    print(f"\nSILENT ADJUSTMENTS ({len(adjustments)}):")
    for z, s, status, info in adjustments:
        print(f"  zoom={z:>5}, speed={s:>5}: {info}")

if errors:
    print(f"\nREJECTED ({len(errors)}):")
    for z, s, status, info in errors:
        print(f"  zoom={z:>5}, speed={s:>5}: [{status}] {info}")


# ---- Summary ----

ok_count = sum(1 for z in ZOOMS for s in SPEEDS if grid[z].get(s) == "OK")
adj_count = len(adjustments)
err_count = len(errors)

print(f"\n{'=' * 100}")
print(f"SUMMARY: {ok_count} OK, {adj_count} silently adjusted, "
      f"{err_count} rejected  (total {total})")
print(f"{'=' * 100}")


# ---- Restore ----

print(f"\nRestoring zoom={orig_zoom}, speed={orig_speed}...")
try:
    drv.set_zoom(client, JOB, orig_zoom, pre_check_timeout=TIMEOUT)
    drv.set_scan_speed(client, JOB, orig_speed, pre_check_timeout=TIMEOUT)
    print("Restored.")
except Exception as e:
    print(f"Restore failed: {e}")

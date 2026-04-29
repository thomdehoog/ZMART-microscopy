"""
Square Spiral Acquisition Test
===============================
Acquires an NxN square spiral of touching tiles at the current stage position.
Uses the live tile size from the API so tiles connect regardless of zoom.

Usage:
    python test_square_spiral.py              # default 3x3
    python test_square_spiral.py --size 5     # 5x5 = 25 tiles
    python test_square_spiral.py --size 7     # 7x7 = 49 tiles
"""

import argparse
import sys
import time
from pathlib import Path

parser = argparse.ArgumentParser(description="Square Spiral Acquisition Test")
parser.add_argument("--size", type=int, default=3,
                    help="Grid size NxN (default: 3)")
args = parser.parse_args()

N = args.size

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from LasxApi import PYLICamApiConnector as lasx_api
import navigator_expert.driver as drv
from navigator_expert.driver.scanning_template_parsers import _get_tile_sizes_from_api

# ── Connect ──────────────────────────────────────────────────────────────

client = lasx_api.LasxApiClientPyModel
if not client.Connect("PythonClient"):
    print("Cannot connect to LAS X.")
    sys.exit(1)
print("Connected to LAS X")

pos = drv.get_xy(client)
home_x = pos["x_um"]
home_y = pos["y_um"]
print(f"Home: ({home_x:.0f}, {home_y:.0f}) um")

tile_sizes = _get_tile_sizes_from_api(client, ["HiRes"])
fov = tile_sizes["HiRes"]
print(f"Tile size: {fov} um")

# ── Square spiral generator ──────────────────────────────────────────────

def square_spiral(n):
    """Generate n x n square spiral grid coordinates from center outward."""
    positions = []
    x, y = 0, 0
    positions.append((x, y))
    directions = [(1, 0), (0, 1), (-1, 0), (0, -1)]
    steps = 1
    d = 0
    while len(positions) < n * n:
        for _ in range(2):
            dx, dy = directions[d % 4]
            for _ in range(steps):
                if len(positions) >= n * n:
                    break
                x += dx
                y += dy
                positions.append((x, y))
            d += 1
        steps += 1
    return positions

# ── Acquisition helpers ──────────────────────────────────────────────────

move_api = client.PyApiMoveHardwareXY
unit_val = type(move_api.Model.Units).eMicrons
mode_val = type(move_api.Model.MoveXyMode).eMoveXY
acq_api = client.PyApiAcquireSingleImage

SETTLE = 0.5

def wait_scan(timeout=10.0):
    """Wait for scan to start (not idle), then wait for it to finish (idle).

    Requires observing a non-idle status before accepting idle as
    completion — prevents mistaking 'not yet started' for 'finished'.

    Returns (start_time, total_time) in seconds.
    """
    t0 = time.perf_counter()
    saw_scanning = False
    while time.perf_counter() - t0 < timeout:
        status = str(client.PyApiStatus.Model.ScanStatus)
        if "Idle" not in status:
            if not saw_scanning:
                start_t = time.perf_counter() - t0
            saw_scanning = True
        elif saw_scanning:
            return start_t, time.perf_counter() - t0
        time.sleep(0.01)
    return time.perf_counter() - t0, time.perf_counter() - t0

# ── Run spiral ───────────────────────────────────────────────────────────

grid = square_spiral(N)
total = len(grid)
print(f"\nRunning {N}x{N} square spiral ({total} positions, step={fov} um)\n")
print(f"  {'#':>4}  {'position':>22}  {'move':>7}  {'scan_start':>11}  {'scan':>7}  {'total':>7}")
print(f"  {'':->4}  {'':->22}  {'':->7}  {'':->11}  {'':->7}  {'':->7}")

move_times = []
scan_times = []

total_start = time.perf_counter()
for i, (gx, gy) in enumerate(grid):
    tx = home_x + gx * fov
    ty = home_y + gy * fov
    t0 = time.perf_counter()

    m = move_api.Model
    m.RelativePosition = False
    m.XPosition = tx
    m.YPosition = ty
    m.MoveXyMode = mode_val
    m.Units = unit_val
    move_api.UpdateAsync()
    time.sleep(SETTLE)
    move_t = time.perf_counter() - t0

    acq_api.UpdateAwaitReceipt(2)
    scan_start_t, scan_t = wait_scan()

    t1 = time.perf_counter()
    move_times.append(move_t)
    scan_times.append(scan_t)
    print(f"  {i+1:>{4}}/{total}  ({tx:8.2f}, {ty:8.2f})  {move_t:6.3f}s  {scan_start_t:10.3f}s  {scan_t:6.3f}s  {t1-t0:6.3f}s")

elapsed = time.perf_counter() - total_start
print(f"\n  Total:      {elapsed:.1f}s")
print(f"  Per tile:   {elapsed/total:.2f}s")
print(f"  Avg move:   {sum(move_times)/len(move_times):.3f}s")
print(f"  Avg scan:   {sum(scan_times)/len(scan_times):.3f}s")

# ── Return home ──────────────────────────────────────────────────────────

m = move_api.Model
m.XPosition = home_x
m.YPosition = home_y
move_api.UpdateAsync()
print(f"Returning home ({home_x:.0f}, {home_y:.0f})")

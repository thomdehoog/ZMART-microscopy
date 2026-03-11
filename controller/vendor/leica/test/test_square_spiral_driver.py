"""
Square Spiral Acquisition Test (driver version)
=================================================
Same as test_square_spiral.py but uses the driver's move_xy and acquire
commands with full confirmation, retries, and safety checks.

Usage:
    python test_square_spiral_driver.py              # default 3x3
    python test_square_spiral_driver.py --size 5     # 5x5 = 25 tiles
    python test_square_spiral_driver.py --size 7     # 7x7 = 49 tiles
"""

import argparse
import sys
import time
from pathlib import Path

parser = argparse.ArgumentParser(
    description="Square Spiral Acquisition Test (driver)")
parser.add_argument("--size", type=int, default=3,
                    help="Grid size NxN (default: 3)")
args = parser.parse_args()

N = args.size

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from LasxApi import PYLICamApiConnector as lasx_api
import lasx as drv
from lasx.scanning_template_parsers import _get_tile_sizes_from_api

# ── Connect ──────────────────────────────────────────────────────────────

client = lasx_api.LasxApiClientPyModel
if not client.Connect("PythonClient"):
    print("Cannot connect to LAS X.")
    sys.exit(1)
print("Connected to LAS X")

drv.set_stage_limits(
    x_min=0, x_max=130000,
    y_min=0, y_max=100000,
    z_galvo_min=-200, z_galvo_max=200,
    z_wide_min=0, z_wide_max=25000,
)

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

# ── Run spiral ───────────────────────────────────────────────────────────

grid = square_spiral(N)
total = len(grid)
print(f"\nRunning {N}x{N} square spiral ({total} positions, step={fov} um)\n")
print(f"  {'#':>4}  {'position':>22}  {'move':>7}  {'acq':>7}  {'total':>7}")
print(f"  {'':->4}  {'':->22}  {'':->7}  {'':->7}  {'':->7}")

move_times = []
acq_times = []

total_start = time.perf_counter()
for i, (gx, gy) in enumerate(grid):
    tx = home_x + gx * fov
    ty = home_y + gy * fov
    t0 = time.perf_counter()

    r_move = drv.move_xy(client, tx, ty)
    move_t = time.perf_counter() - t0

    t_acq = time.perf_counter()
    r_acq = drv.acquire(client, "HiRes")
    acq_t = time.perf_counter() - t_acq

    t1 = time.perf_counter()
    move_times.append(move_t)
    acq_times.append(acq_t)
    print(f"  {i+1:>{4}}/{total}  ({tx:8.2f}, {ty:8.2f})  {move_t:6.3f}s  {acq_t:6.3f}s  {t1-t0:6.3f}s")

elapsed = time.perf_counter() - total_start
print(f"\n  Total:      {elapsed:.1f}s")
print(f"  Per tile:   {elapsed/total:.2f}s")
print(f"  Avg move:   {sum(move_times)/len(move_times):.3f}s")
print(f"  Avg acq:    {sum(acq_times)/len(acq_times):.3f}s")

# ── Return home ──────────────────────────────────────────────────────────

drv.move_xy(client, home_x, home_y)
print(f"Returned home ({home_x:.0f}, {home_y:.0f})")

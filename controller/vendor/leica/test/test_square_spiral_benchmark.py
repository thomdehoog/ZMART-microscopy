"""
Square Spiral Benchmark
========================
Benchmarks NxN square spiral acquisition using three methods:
raw API calls, driver acquire, and driver acquire_single_image.
Prints a side-by-side comparison.

Usage:
    python test_square_spiral_benchmark.py              # default 3x3
    python test_square_spiral_benchmark.py --size 5     # 5x5 = 25 tiles
"""

import argparse
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.WARNING, format="%(name)s: %(message)s")

parser = argparse.ArgumentParser(description="Square Spiral Benchmark")
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
    x_min=29126, x_max=130000,
    y_min=31370, y_max=100000,
    z_galvo_min=-200, z_galvo_max=200,
    z_wide_min=0, z_wide_max=25000,
)

drv.select_job(client, "HiRes")
print("Selected job: HiRes")

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


grid = square_spiral(N)
total = len(grid)

# Offset the three spirals so they don't overlap in LAS X.
# Raw API: left, Driver acquire: center, Driver single image: right.
spiral_offset = (N + 1) * fov
positions_raw = [(home_x - spiral_offset + gx * fov, home_y + gy * fov)
                 for gx, gy in grid]
positions_drv = [(home_x + gx * fov, home_y + gy * fov)
                 for gx, gy in grid]
positions_single = [(home_x + spiral_offset + gx * fov, home_y + gy * fov)
                    for gx, gy in grid]


# ── Raw API benchmark ────────────────────────────────────────────────────

def run_raw():
    move_api = client.PyApiMoveHardwareXY
    unit_val = type(move_api.Model.Units).eMicrons
    mode_val = type(move_api.Model.MoveXyMode).eMoveXY
    acq_api = client.PyApiAcquireSingleImage
    def wait_scan(timeout=10.0):
        """Poll scan status — require saw_scanning before accepting idle."""
        t0 = time.perf_counter()
        saw_scanning = False
        while time.perf_counter() - t0 < timeout:
            status = str(client.PyApiStatus.Model.ScanStatus)
            if "Idle" not in status:
                saw_scanning = True
            elif saw_scanning:
                return time.perf_counter() - t0
            time.sleep(0.01)
        return time.perf_counter() - t0

    move_times = []
    acq_times = []
    tile_times = []

    total_start = time.perf_counter()
    for i, (tx, ty) in enumerate(positions_raw):
        t0 = time.perf_counter()

        m = move_api.Model
        m.RelativePosition = False
        m.XPosition = tx
        m.YPosition = ty
        m.MoveXyMode = mode_val
        m.Units = unit_val
        move_api.UpdateAsync()
        move_t = time.perf_counter() - t0

        acq_api.UpdateAwaitReceipt(2)
        scan_t = wait_scan()

        t1 = time.perf_counter()
        move_times.append(move_t)
        acq_times.append(scan_t)
        tile_times.append(t1 - t0)
        print(f"    {i+1:>{3}}/{total}  ({tx:8.2f}, {ty:8.2f})  move={move_t:.3f}s  acq={scan_t:.3f}s  total={t1-t0:.3f}s")

    elapsed = time.perf_counter() - total_start

    # Return home (use driver to ensure move completes before next benchmark)
    drv.move_xy(client, home_x, home_y)

    return {
        "elapsed": elapsed,
        "move_times": move_times,
        "acq_times": acq_times,
        "tile_times": tile_times,
    }


# ── Driver benchmark ─────────────────────────────────────────────────────

def run_driver():
    move_times = []
    acq_times = []
    tile_times = []

    total_start = time.perf_counter()
    for i, (tx, ty) in enumerate(positions_drv):
        t0 = time.perf_counter()

        drv.move_xy(client, tx, ty)
        move_t = time.perf_counter() - t0

        t_acq = time.perf_counter()
        drv.acquire(client, "HiRes")
        acq_t = time.perf_counter() - t_acq

        t1 = time.perf_counter()
        move_times.append(move_t)
        acq_times.append(acq_t)
        tile_times.append(t1 - t0)
        print(f"    {i+1:>{3}}/{total}  ({tx:8.2f}, {ty:8.2f})  move={move_t:.3f}s  acq={acq_t:.3f}s  total={t1-t0:.3f}s")

    elapsed = time.perf_counter() - total_start

    drv.move_xy(client, home_x, home_y)

    return {
        "elapsed": elapsed,
        "move_times": move_times,
        "acq_times": acq_times,
        "tile_times": tile_times,
    }


# ── Driver single image benchmark ─────────────────────────────────────────

def run_single_image():
    move_times = []
    acq_times = []
    tile_times = []

    total_start = time.perf_counter()
    for i, (tx, ty) in enumerate(positions_single):
        t0 = time.perf_counter()

        drv.move_xy(client, tx, ty)
        move_t = time.perf_counter() - t0

        t_acq = time.perf_counter()
        drv.acquire_single_image(client)
        acq_t = time.perf_counter() - t_acq

        t1 = time.perf_counter()
        move_times.append(move_t)
        acq_times.append(acq_t)
        tile_times.append(t1 - t0)
        print(f"    {i+1:>{3}}/{total}  ({tx:8.2f}, {ty:8.2f})  move={move_t:.3f}s  acq={acq_t:.3f}s  total={t1-t0:.3f}s")

    elapsed = time.perf_counter() - total_start

    drv.move_xy(client, home_x, home_y)

    return {
        "elapsed": elapsed,
        "move_times": move_times,
        "acq_times": acq_times,
        "tile_times": tile_times,
    }


# ── Run benchmarks ───────────────────────────────────────────────────────

def wait_idle(timeout=5.0):
    """Wait for scanner to be idle before starting next benchmark."""
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        if "Idle" in str(client.PyApiStatus.Model.ScanStatus):
            return
        time.sleep(0.05)

print(f"\n  Running RAW API...")
raw = run_raw()

wait_idle()

print(f"  Running DRIVER (acquire)...")
driver = run_driver()

wait_idle()

print(f"  Running DRIVER (acquire_single_image)...")
single = run_single_image()

# ── Side-by-side results ─────────────────────────────────────────────────

def avg(lst):
    return sum(lst) / len(lst)

print(f"\n{'='*120}")
print(f"  {N}x{N} SPIRAL ({total} tiles) — RAW API vs DRIVER (acquire) vs DRIVER (single_image)")
print(f"{'='*120}\n")

h1, h2, h3 = "RAW API", "DRV acquire", "DRV single_img"
print(f"  {'#':>3}  {'move':>7} {'acq':>7} {'total':>7}  |  {'move':>7} {'acq':>7} {'total':>7}  |  {'move':>7} {'acq':>7} {'total':>7}")
print(f"  {'':>3}  {h1:^21}  |  {h2:^21}  |  {h3:^21}")
print(f"  {'':->3}  {'':->7} {'':->7} {'':->7}  |  {'':->7} {'':->7} {'':->7}  |  {'':->7} {'':->7} {'':->7}")

for i in range(total):
    rm, ra, rt = raw["move_times"][i], raw["acq_times"][i], raw["tile_times"][i]
    dm, da, dt = driver["move_times"][i], driver["acq_times"][i], driver["tile_times"][i]
    sm, sa, st = single["move_times"][i], single["acq_times"][i], single["tile_times"][i]
    print(f"  {i+1:>3}  {rm:6.3f}s {ra:6.3f}s {rt:6.3f}s  |  {dm:6.3f}s {da:6.3f}s {dt:6.3f}s  |  {sm:6.3f}s {sa:6.3f}s {st:6.3f}s")

print(f"  {'':->3}  {'':->7} {'':->7} {'':->7}  |  {'':->7} {'':->7} {'':->7}  |  {'':->7} {'':->7} {'':->7}")

rm_avg, ra_avg, rt_avg = avg(raw["move_times"]), avg(raw["acq_times"]), avg(raw["tile_times"])
dm_avg, da_avg, dt_avg = avg(driver["move_times"]), avg(driver["acq_times"]), avg(driver["tile_times"])
sm_avg, sa_avg, st_avg = avg(single["move_times"]), avg(single["acq_times"]), avg(single["tile_times"])
print(f"  {'avg':>3}  {rm_avg:6.3f}s {ra_avg:6.3f}s {rt_avg:6.3f}s  |  {dm_avg:6.3f}s {da_avg:6.3f}s {dt_avg:6.3f}s  |  {sm_avg:6.3f}s {sa_avg:6.3f}s {st_avg:6.3f}s")

print(f"\n  Total:  Raw {raw['elapsed']:.1f}s  |  Driver {driver['elapsed']:.1f}s  |  Single {single['elapsed']:.1f}s")
print()

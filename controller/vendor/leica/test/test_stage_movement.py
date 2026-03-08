"""
Stage Movement Test
====================
Moves the stage in observable patterns so you can watch it.
Starts from current position, returns to start when done.

Usage:
    python test_stage_movement.py
    python test_stage_movement.py --pattern square
    python test_stage_movement.py --pattern star
    python test_stage_movement.py --pattern spiral
    python test_stage_movement.py --pattern grid
    python test_stage_movement.py --pattern all
    python test_stage_movement.py --step 2000        # larger moves (um)
    python test_stage_movement.py --pause 1.0         # wait between moves (s)
"""

import argparse
import sys
import time
import math

# ── CLI ──────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description="Stage Movement Test")
parser.add_argument("--pattern", default="all",
                    choices=["square", "star", "spiral", "grid", "zigzag", "all"],
                    help="Movement pattern to run (default: all)")
parser.add_argument("--step", type=float, default=1000,
                    help="Step size in microns (default: 1000)")
parser.add_argument("--pause", type=float, default=0.5,
                    help="Pause between moves in seconds (default: 0.5)")
args = parser.parse_args()

STEP = args.step
PAUSE = args.pause

# ── Connect ──────────────────────────────────────────────────────────────

from pathlib import Path
# Add the leica directory to sys.path so `import lasx` works unchanged.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from LasxApi import PYLICamApiConnector as lasx_api
import lasx as drv

print(f"\n  Driver version: {drv.__version__}")
print(f"  Step size: {STEP:.0f} um")
print(f"  Pause: {PAUSE:.1f}s\n")

client = lasx_api.LasxApiClientPyModel
confirmed = client.Connect("PythonClient")
if not confirmed:
    print("  ABORT: Cannot connect to LAS X.")
    sys.exit(1)
print("  Connected to LAS X\n")

drv.set_stage_limits(
    x_min=0, x_max=130000,
    y_min=0, y_max=100000,
    z_galvo_min=-200, z_galvo_max=200,
    z_wide_min=0, z_wide_max=25000,
)

# ── Helpers ──────────────────────────────────────────────────────────────

# Read current position
pos = drv.get_xy(client)
if not pos:
    print("  ABORT: Cannot read stage position.")
    sys.exit(1)

HOME_X = pos["x_um"]
HOME_Y = pos["y_um"]
print(f"  Home position: X={HOME_X:.1f}  Y={HOME_Y:.1f} um")

lim = drv.get_stage_limits()
print(f"  Stage limits: X=[{lim['x_min']}, {lim['x_max']}] "
      f"Y=[{lim['y_min']}, {lim['y_max']}]")
print()

move_count = 0
total_distance = 0.0
last_x, last_y = HOME_X, HOME_Y


def move(x, y, label=""):
    """Move to absolute position (um), print result."""
    global move_count, total_distance, last_x, last_y

    dist = math.sqrt((x - last_x)**2 + (y - last_y)**2)
    t0 = time.perf_counter()
    r = drv.move_xy(client, x, y, unit="um")
    elapsed = time.perf_counter() - t0

    move_count += 1
    status = "OK" if r["success"] else "FAIL"

    pos = r.get("position") or {}
    actual_x = pos.get("x_um", x)
    actual_y = pos.get("y_um", y)

    tag = f" ({label})" if label else ""
    print(f"  [{move_count:3d}] {status}  -> ({x:8.0f}, {y:8.0f}){tag}"
          f"  actual=({actual_x:8.0f}, {actual_y:8.0f})"
          f"  dist={dist:7.0f}um  {elapsed:.3f}s")

    if not r["success"]:
        print(f"        ERROR: {r['message']}")

    total_distance += dist
    last_x, last_y = actual_x, actual_y
    time.sleep(PAUSE)
    return r["success"]


def go_home(label="return home"):
    """Return to starting position."""
    move(HOME_X, HOME_Y, label)


def check_limits(points):
    """Verify all points are within stage limits before moving."""
    lim = drv.get_stage_limits()
    for x, y in points:
        if x < lim["x_min"] or x > lim["x_max"]:
            return False
        if y < lim["y_min"] or y > lim["y_max"]:
            return False
    return True


# ── Patterns ─────────────────────────────────────────────────────────────

def pattern_square():
    """Move in a square: right → up → left → down → home."""
    print("\n" + "=" * 60)
    print("  PATTERN: Square")
    print("=" * 60)

    s = STEP
    points = [
        (HOME_X + s, HOME_Y,     "right"),
        (HOME_X + s, HOME_Y + s, "up-right"),
        (HOME_X,     HOME_Y + s, "up-left"),
        (HOME_X,     HOME_Y,     "back to start"),
    ]

    coords = [(x, y) for x, y, _ in points]
    if not check_limits(coords):
        print("  SKIP: square pattern exceeds stage limits")
        return

    for x, y, label in points:
        move(x, y, label)


def pattern_star():
    """Move in a 5-point star, returning to center between each point."""
    print("\n" + "=" * 60)
    print("  PATTERN: Star (5 points, return to center)")
    print("=" * 60)

    s = STEP
    cx, cy = HOME_X, HOME_Y

    # 5 points of a star, evenly spaced at 72° intervals
    angles = [90, 162, 234, 306, 378]  # degrees, starting from top
    points = []
    for a in angles:
        rad = math.radians(a)
        px = cx + s * math.cos(rad)
        py = cy + s * math.sin(rad)
        points.append((px, py))

    all_pts = []
    for px, py in points:
        all_pts.append((px, py))
        all_pts.append((cx, cy))

    if not check_limits(all_pts):
        print("  SKIP: star pattern exceeds stage limits")
        return

    for i, (px, py) in enumerate(points):
        move(px, py, f"point {i+1}")
        move(cx, cy, "center")


def pattern_spiral():
    """Move in an outward spiral (8 points, increasing radius)."""
    print("\n" + "=" * 60)
    print("  PATTERN: Spiral (outward)")
    print("=" * 60)

    cx, cy = HOME_X, HOME_Y
    n_points = 12
    max_radius = STEP * 1.5

    points = []
    for i in range(n_points):
        angle = i * (360 / n_points) * 2  # 2 full rotations
        radius = max_radius * (i + 1) / n_points
        rad = math.radians(angle)
        px = cx + radius * math.cos(rad)
        py = cy + radius * math.sin(rad)
        points.append((px, py, f"r={radius:.0f}um"))

    coords = [(x, y) for x, y, _ in points]
    if not check_limits(coords):
        print("  SKIP: spiral pattern exceeds stage limits")
        return

    for x, y, label in points:
        move(x, y, label)

    go_home()


def pattern_grid():
    """Move in a 3x3 grid scan pattern (raster)."""
    print("\n" + "=" * 60)
    print("  PATTERN: Grid (3x3 raster)")
    print("=" * 60)

    s = STEP
    cx, cy = HOME_X, HOME_Y

    # 3x3 grid centered on home, raster scan (snake pattern)
    offsets = [-s, 0, s]
    points = []
    for row_i, dy in enumerate(offsets):
        cols = offsets if row_i % 2 == 0 else list(reversed(offsets))
        for dx in cols:
            points.append((cx + dx, cy + dy,
                           f"({dx/s:+.0f},{dy/s:+.0f})"))

    coords = [(x, y) for x, y, _ in points]
    if not check_limits(coords):
        print("  SKIP: grid pattern exceeds stage limits")
        return

    for x, y, label in points:
        move(x, y, label)

    go_home()


def pattern_zigzag():
    """Zigzag across the field — fast lateral moves."""
    print("\n" + "=" * 60)
    print("  PATTERN: Zigzag")
    print("=" * 60)

    s = STEP
    cx, cy = HOME_X, HOME_Y
    n_zags = 6

    points = []
    for i in range(n_zags):
        x_off = s if (i % 2 == 0) else -s
        y_off = s * i / 2
        points.append((cx + x_off, cy + y_off, f"zag {i+1}"))

    coords = [(x, y) for x, y, _ in points]
    if not check_limits(coords):
        print("  SKIP: zigzag pattern exceeds stage limits")
        return

    for x, y, label in points:
        move(x, y, label)

    go_home()


# ── Run ──────────────────────────────────────────────────────────────────

patterns = {
    "square": pattern_square,
    "star": pattern_star,
    "spiral": pattern_spiral,
    "grid": pattern_grid,
    "zigzag": pattern_zigzag,
}

t_start = time.perf_counter()

if args.pattern == "all":
    for name, fn in patterns.items():
        fn()
        go_home(f"home after {name}")
else:
    patterns[args.pattern]()
    go_home()

t_total = time.perf_counter() - t_start

# ── Summary ──────────────────────────────────────────────────────────────

# Verify we're back home
pos = drv.get_xy(client)
if pos:
    dx = abs(pos["x_um"] - HOME_X)
    dy = abs(pos["y_um"] - HOME_Y)
    home_ok = dx < 20 and dy < 20
else:
    home_ok = False

print("\n" + "=" * 60)
print(f"  DONE")
print(f"  Moves:          {move_count}")
print(f"  Total distance:  {total_distance/1000:.1f} mm")
print(f"  Total time:      {t_total:.1f}s")
print(f"  Avg per move:    {t_total/max(move_count,1):.3f}s")
print(f"  Back at home:    {'YES' if home_ok else 'NO'}")
if pos:
    print(f"  Final position:  X={pos['x_um']:.1f}  Y={pos['y_um']:.1f} um")
print("=" * 60)

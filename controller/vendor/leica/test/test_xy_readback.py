"""Test whether PyApiGetXY.Model updates automatically after a move,
without re-firing the GetXY command each time.

Compares three readback methods:
  1. Full get_xy() — fires GetXY command each call (slow, reliable)
  2. Direct model read — just reads PyApiGetXY.Model.XPosition/YPosition
  3. Fire GetXY once, then poll the model repeatedly
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from LasxApi import PYLICamApiConnector as lasx_api
import lasx as drv
from lasx.utils import RECEIPT_TIMEOUT

client = lasx_api.LasxApiClientPyModel
if not client.Connect("PythonClient"):
    print("Cannot connect to LAS X.")
    sys.exit(1)

drv.set_stage_limits(
    x_min=29126, x_max=130000,
    y_min=31370, y_max=100000,
    z_galvo_min=-200, z_galvo_max=200,
    z_wide_min=0, z_wide_max=25000,
)

# Get current position as baseline
pos = drv.get_xy(client)
home_x, home_y = pos["x_um"], pos["y_um"]
print(f"Home: ({home_x:.0f}, {home_y:.0f}) um\n")

# Target: offset by 500 um
target_x = home_x + 500
target_y = home_y + 500


def read_model_direct():
    """Read XY from the model without firing any command."""
    x = client.PyApiGetXY.Model.XPosition
    y = client.PyApiGetXY.Model.YPosition
    return x * 1e6, y * 1e6


def fire_getxy_once():
    """Fire GetXY command once (no retry)."""
    client.PyApiCommand.Model.Command = ""
    client.PyApiCommand.Model.Command = "GetXY"
    client.PyApiCommand.UpdateAwaitReceipt(RECEIPT_TIMEOUT)
    time.sleep(0.05)


def read_job_settings_xy():
    """Read xyStage from all job settings."""
    jobs = drv.get_jobs(client)
    results = {}
    for job in jobs:
        name = job["Name"]
        settings = drv.get_job_settings(client, name)
        if settings:
            xy = settings.get("xyStage", {})
            results[name] = (xy.get("posX", "N/A"), xy.get("posY", "N/A"))
        else:
            results[name] = ("N/A", "N/A")
    return results


def print_all_sources(label):
    """Print XY from all three sources."""
    print(f"\n--- {label} ---")
    x, y = read_model_direct()
    print(f"  PyApiGetXY model:  ({x:.2f}, {y:.2f}) um")
    pos = drv.get_xy(client)
    print(f"  Full get_xy():     ({pos['x_um']:.2f}, {pos['y_um']:.2f}) um")
    job_xy = read_job_settings_xy()
    for name, (px, py) in job_xy.items():
        print(f"  Job '{name}':  posX={px}  posY={py}")


# ── Before move ─────────────────────────────────────────────────────────
print_all_sources("Before move")

# ── Move with raw API ───────────────────────────────────────────────────
print(f"\n=== Moving to ({target_x:.0f}, {target_y:.0f}) with raw UpdateAsync ===")
api = client.PyApiMoveHardwareXY
m = api.Model
m.RelativePosition = False
m.XPosition = target_x
m.YPosition = target_y
m.MoveXyMode = type(m.MoveXyMode).eMoveXY
m.Units = type(m.Units).eMicrons
api.UpdateAsync()
time.sleep(1)

# ── After move, before GetXY ────────────────────────────────────────────
print_all_sources("After move (no GetXY fired)")

# ── Fire GetXY once ─────────────────────────────────────────────────────
print("\n=== Firing GetXY once ===")
fire_getxy_once()
print_all_sources("After firing GetXY once")

# ── Re-select active job to force settings refresh ──────────────────────
selected = drv.get_selected_job(client)
if selected:
    job_name = selected["Name"]
    print(f"\n=== Re-selecting active job '{job_name}' to force refresh ===")
    drv.select_job(client, job_name)
    print_all_sources(f"After re-selecting '{job_name}'")

# ── Move back ───────────────────────────────────────────────────────────
print(f"\n=== Moving back to home ({home_x:.0f}, {home_y:.0f}) ===")
m.XPosition = home_x
m.YPosition = home_y
api.UpdateAsync()
time.sleep(1)

print_all_sources("After move back (no GetXY fired)")

print("\n=== Firing GetXY once ===")
fire_getxy_once()
print_all_sources("After firing GetXY once")

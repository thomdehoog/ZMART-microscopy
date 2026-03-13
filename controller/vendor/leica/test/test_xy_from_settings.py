"""Check if xyStage in job settings is consistent across jobs and matches get_xy."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from LasxApi import PYLICamApiConnector as lasx_api
import lasx as drv

client = lasx_api.LasxApiClientPyModel
if not client.Connect("PythonClient"):
    print("Cannot connect to LAS X.")
    sys.exit(1)

# Get XY from dedicated command
pos = drv.get_xy(client)
print(f"get_xy:  x={pos['x_um']:.2f} um  y={pos['y_um']:.2f} um")
print()

# Get all jobs and their xyStage
jobs = drv.get_jobs(client)
print(f"Jobs: {[j['Name'] for j in jobs]}")
print()

for job in jobs:
    name = job["Name"]
    settings = drv.get_job_settings(client, name)
    if settings is None:
        print(f"  {name}: settings=None")
        continue
    xy = settings.get("xyStage", {})
    print(f"  {name}: posX={xy.get('posX', 'N/A')}  posY={xy.get('posY', 'N/A')}")

# Move stage
print("\n--- Moving stage to (60000, 45000) ---")
drv.set_stage_limits(
    x_min=29126, x_max=130000,
    y_min=31370, y_max=100000,
    z_galvo_min=-200, z_galvo_max=200,
    z_wide_min=0, z_wide_max=25000,
)
drv.move_xy(client, 60000, 45000)

pos2 = drv.get_xy(client)
print(f"get_xy after move: x={pos2['x_um']:.2f} um  y={pos2['y_um']:.2f} um")
print()

# Re-check job settings
print("Job settings after move:")
jobs2 = drv.get_jobs(client)
for job in jobs2:
    name = job["Name"]
    settings = drv.get_job_settings(client, name)
    if settings is None:
        print(f"  {name}: settings=None")
        continue
    xy = settings.get("xyStage", {})
    print(f"  {name}: posX={xy.get('posX', 'N/A')}  posY={xy.get('posY', 'N/A')}")

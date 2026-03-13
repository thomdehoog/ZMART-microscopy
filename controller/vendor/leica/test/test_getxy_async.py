"""Test GetXY async with NaN flush — show the transition from NaN to real value."""
import sys
import time
import math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from LasxApi import PYLICamApiConnector as lasx_api
import lasx as drv

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

pos = drv.get_xy(client)
home_x, home_y = pos["x_um"], pos["y_um"]
print(f"Home: ({home_x:.0f}, {home_y:.0f}) um")

# Move somewhere
target_x = home_x + 500
target_y = home_y + 500
api = client.PyApiMoveHardwareXY
m = api.Model
m.RelativePosition = False
m.XPosition = target_x
m.YPosition = target_y
m.MoveXyMode = type(m.MoveXyMode).eMoveXY
m.Units = type(m.Units).eMicrons
api.UpdateAsync()
time.sleep(0.5)

print(f"Target: ({target_x:.0f}, {target_y:.0f}) um\n")

# Flush to NaN
client.PyApiGetXY.Model.XPosition = float('nan')
client.PyApiGetXY.Model.YPosition = float('nan')

# Fire GetXY async
client.PyApiCommand.Model.Command = ""
client.PyApiCommand.Model.Command = "GetXY"
client.PyApiCommand.UpdateAsync()

# Poll as fast as possible — no sleep, count NaN reads
t0 = time.perf_counter()
nan_count = 0
for i in range(100000):
    x_raw = client.PyApiGetXY.Model.XPosition
    y_raw = client.PyApiGetXY.Model.YPosition
    elapsed = time.perf_counter() - t0
    x_nan = math.isnan(x_raw)
    y_nan = math.isnan(y_raw)

    if x_nan or y_nan:
        nan_count += 1
        if nan_count <= 20:  # print first 20 NaN reads
            print(f"  {elapsed*1000:6.1f}ms:  NaN  (read #{i+1})")
    else:
        x_um = x_raw * 1e6
        y_um = y_raw * 1e6
        if nan_count > 20:
            print(f"  ... ({nan_count - 20} more NaN reads) ...")
        print(f"  {elapsed*1000:6.1f}ms:  ({x_um:.2f}, {y_um:.2f}) um  <-- FRESH DATA (after {nan_count} NaN reads)")
        break

# Move back
m.XPosition = home_x
m.YPosition = home_y
api.UpdateAsync()

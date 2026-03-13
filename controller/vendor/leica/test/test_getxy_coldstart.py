"""Test get_xy cold start timing — how long after connect before GetXY responds?"""
import sys
import time
import math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from LasxApi import PYLICamApiConnector as lasx_api

client = lasx_api.LasxApiClientPyModel
if not client.Connect("PythonClient"):
    print("Cannot connect to LAS X.")
    sys.exit(1)

t_connect = time.perf_counter()
print("Connected to LAS X\n")

# Immediately try GetXY with NaN flush — time each attempt
for attempt in range(1, 51):
    client.PyApiGetXY.Model.XPosition = float('nan')
    client.PyApiGetXY.Model.YPosition = float('nan')

    client.PyApiCommand.Model.Command = ""
    client.PyApiCommand.Model.Command = "GetXY"
    client.PyApiCommand.UpdateAsync()

    t0 = time.perf_counter()
    result = None
    for i in range(10000):
        x = client.PyApiGetXY.Model.XPosition
        y = client.PyApiGetXY.Model.YPosition
        if not (math.isnan(x) or math.isnan(y)):
            elapsed = (time.perf_counter() - t0) * 1000
            since_connect = (time.perf_counter() - t_connect) * 1000
            x_um, y_um = x * 1e6, y * 1e6
            print(f"  attempt {attempt:>2}: {elapsed:7.1f}ms  (since connect: {since_connect:7.1f}ms)  -> ({x_um:.2f}, {y_um:.2f}) um")
            result = True
            break
        time.sleep(0.1)

    if not result:
        elapsed = (time.perf_counter() - t0) * 1000
        since_connect = (time.perf_counter() - t_connect) * 1000
        print(f"  attempt {attempt:>2}: TIMEOUT after {elapsed:.0f}ms  (since connect: {since_connect:.0f}ms)")

print("\nDone.")

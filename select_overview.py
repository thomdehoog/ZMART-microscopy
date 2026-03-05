"""Select the Overview job in LAS X."""
import sys
from LasxApi import PYLICamApiConnector as lasx_api
import driver as drv

client = lasx_api.LasxApiClientPyModel
if not client.Connect("PythonClient"):
    print("ERROR: Cannot connect to LAS X")
    sys.exit(1)

r = drv.select_job(client, "Overview")
print(f"select_job('Overview'): confirmed={r.get('confirmed')}, elapsed={r['timing']['total_s']:.2f}s")

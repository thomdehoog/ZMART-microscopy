"""Call each reader once to see the flush → populated debug output."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from LasxApi import PYLICamApiConnector as lasx_api
import lasx as drv

client = lasx_api.LasxApiClientPyModel
if not client.Connect("PythonClient"):
    print("Cannot connect to LAS X.")
    sys.exit(1)

print("— get_xy —")
drv.get_xy(client)

print("— get_job_settings —")
drv.get_job_settings(client, "HiRes")

print("— get_hardware_info —")
drv.get_hardware_info(client)

print("— get_jobs —")
drv.get_jobs(client)

print("\nDone.")

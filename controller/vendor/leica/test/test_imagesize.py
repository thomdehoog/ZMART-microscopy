"""Print raw imageSize from job settings."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from LasxApi import PYLICamApiConnector as lasx_api
import lasx as drv

client = lasx_api.LasxApiClientPyModel
if not client.Connect("PythonClient"):
    print("Cannot connect to LAS X.")
    sys.exit(1)

for job in drv.get_jobs(client):
    name = job["Name"]
    settings = drv.get_job_settings(client, name)
    if settings:
        raw = settings.get("imageSize", "N/A")
        print(f"  {name}: imageSize = '{raw}'")

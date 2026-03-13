"""Acquire a single HiRes image at the current stage position."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "controller" / "vendor" / "leica"))

from LasxApi import PYLICamApiConnector as lasx_api
import lasx as drv

# Connect
client = lasx_api.LasxApiClientPyModel
if not client.Connect("PythonClient"):
    print("Cannot connect to LAS X.")
    sys.exit(1)
print("Connected to LAS X")

# Acquire
result = drv.acquire(client, "HiRes")
print(f"Done — acquired in {result['timing']['total_s']:.1f}s")

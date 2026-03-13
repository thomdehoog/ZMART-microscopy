"""Test get_jobs polling timing at different intervals."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from LasxApi import PYLICamApiConnector as lasx_api

client = lasx_api.LasxApiClientPyModel
if not client.Connect("PythonClient"):
    print("Cannot connect to LAS X.")
    sys.exit(1)
print("Connected to LAS X\n")

for interval in [0.01, 0.02, 0.05, 0.1]:
    print(f"--- poll_interval={interval}s ---")
    for attempt in range(1, 51):
        try:
            client.PyApiGetJobsInformation.Model.Jobs = None
        except Exception:
            pass

        client.PyApiCommand.Model.Command = ""
        client.PyApiCommand.Model.Command = "GetJobsInformation"
        client.PyApiCommand.UpdateAsync()

        t0 = time.perf_counter()
        result = None
        for i in range(1000):
            raw = client.PyApiGetJobsInformation.Model.Jobs
            if raw is not None:
                elapsed = (time.perf_counter() - t0) * 1000
                data = json.loads(raw) if isinstance(raw, str) else raw
                names = [j.get("Name", "?") for j in data]
                print(f"  attempt {attempt}: {elapsed:7.1f}ms  -> {names}")
                result = True
                break
            time.sleep(interval)

        if not result:
            elapsed = (time.perf_counter() - t0) * 1000
            print(f"  attempt {attempt}: TIMEOUT after {elapsed:.0f}ms")
    print()

print("Done.")

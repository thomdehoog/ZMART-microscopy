"""Test all readers at 0.01s polling — 50 attempts each."""
import json
import math
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

INTERVAL = 0.01
ATTEMPTS = 50


# ── get_xy ──────────────────────────────────────────────────────────────

print(f"=== get_xy (poll={INTERVAL}s) ===")
for attempt in range(1, ATTEMPTS + 1):
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
            print(f"  {attempt:>3}: {elapsed:7.1f}ms  -> ({x*1e6:.2f}, {y*1e6:.2f}) um")
            result = True
            break
        time.sleep(INTERVAL)
    if not result:
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"  {attempt:>3}: TIMEOUT after {elapsed:.0f}ms")


# ── get_job_settings ────────────────────────────────────────────────────

print(f"\n=== get_job_settings (poll={INTERVAL}s) ===")
for attempt in range(1, ATTEMPTS + 1):
    client.PyApiGetJobSettingsByName.Model.JobName = "HiRes"
    client.PyApiGetJobSettingsByName.Model.Settings = None
    client.PyApiCommand.Model.Command = ""
    client.PyApiCommand.Model.Command = "GetJobSettingsByName"
    client.PyApiCommand.UpdateAsync()

    t0 = time.perf_counter()
    result = None
    for i in range(10000):
        raw = client.PyApiGetJobSettingsByName.Model.Settings
        if raw is not None:
            elapsed = (time.perf_counter() - t0) * 1000
            data = json.loads(raw) if isinstance(raw, str) else raw
            preview = str(data)[:60]
            print(f"  {attempt:>3}: {elapsed:7.1f}ms  -> {preview}...")
            result = True
            break
        time.sleep(INTERVAL)
    if not result:
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"  {attempt:>3}: TIMEOUT after {elapsed:.0f}ms")


# ── get_hardware_info ───────────────────────────────────────────────────

print(f"\n=== get_hardware_info (poll={INTERVAL}s) ===")
for attempt in range(1, ATTEMPTS + 1):
    try:
        client.PyApiGetConfocalHardwareInfo.Model.HWInfo = None
    except Exception:
        pass
    client.PyApiCommand.Model.Command = ""
    client.PyApiCommand.Model.Command = "GetConfocalHardwareInfo"
    client.PyApiCommand.UpdateAsync()

    t0 = time.perf_counter()
    result = None
    for i in range(10000):
        raw = client.PyApiGetConfocalHardwareInfo.Model.HWInfo
        if raw is not None:
            elapsed = (time.perf_counter() - t0) * 1000
            data = json.loads(raw) if isinstance(raw, str) else raw
            preview = str(data)[:60]
            print(f"  {attempt:>3}: {elapsed:7.1f}ms  -> {preview}...")
            result = True
            break
        time.sleep(INTERVAL)
    if not result:
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"  {attempt:>3}: TIMEOUT after {elapsed:.0f}ms")


# ── get_jobs ────────────────────────────────────────────────────────────

print(f"\n=== get_jobs (poll={INTERVAL}s) ===")
for attempt in range(1, ATTEMPTS + 1):
    try:
        client.PyApiGetJobsInformation.Model.Jobs = None
    except Exception:
        pass
    client.PyApiCommand.Model.Command = ""
    client.PyApiCommand.Model.Command = "GetJobsInformation"
    client.PyApiCommand.UpdateAsync()

    t0 = time.perf_counter()
    result = None
    for i in range(10000):
        raw = client.PyApiGetJobsInformation.Model.Jobs
        if raw is not None:
            elapsed = (time.perf_counter() - t0) * 1000
            data = json.loads(raw) if isinstance(raw, str) else raw
            names = [j.get("Name", "?") for j in data]
            print(f"  {attempt:>3}: {elapsed:7.1f}ms  -> {names}")
            result = True
            break
        time.sleep(INTERVAL)
    if not result:
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"  {attempt:>3}: TIMEOUT after {elapsed:.0f}ms")

print("\nDone.")

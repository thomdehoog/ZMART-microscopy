"""
Diagnostic: set_scan_mode confirmation
========================================
Prints ScanMode from BOTH sources (job settings + jobs information)
before and after SetScanModeByJobName, to identify value format
mismatches and timing issues.

Usage:
    python diag_scan_mode.py
    python diag_scan_mode.py --job HiRes
"""

import argparse
import json
import time
import logging

logging.basicConfig(level=logging.WARNING, format="%(name)s: %(message)s")

parser = argparse.ArgumentParser()
parser.add_argument("--job", default=None)
args = parser.parse_args()

from LasxApi import PYLICamApiConnector as lasx_api
from lasx import readers as _readers
from lasx.settings import make_changeable_copy

client = lasx_api.LasxApiClientPyModel
confirmed = client.Connect("PythonClient")
print(f"Connected: {confirmed}")
if not confirmed:
    raise SystemExit("Cannot connect to LAS X")


# --- Discover job ---
jobs = _readers.get_jobs(client)
if not jobs:
    raise SystemExit("No jobs found")

JOB = args.job
if JOB is None:
    sel = next((j for j in jobs if j.get("IsSelected")), None)
    JOB = sel["Name"] if sel else jobs[0]["Name"]
print(f"Using job: {JOB}\n")


def read_both_sources():
    """Read scan mode from job settings AND jobs information."""
    # Source 1: GetJobsInformation (jobs list)
    t0 = time.perf_counter()
    all_jobs = _readers.get_jobs(client)
    dt_jobs = time.perf_counter() - t0
    job_info = next((j for j in all_jobs if j.get("Name") == JOB), None) if all_jobs else None

    # Source 2: GetJobSettingsByName
    t0 = time.perf_counter()
    settings_raw = _readers.get_job_settings(client, JOB, timeout=5)
    dt_settings = time.perf_counter() - t0

    return {
        "jobs_info": job_info,
        "jobs_info_keys": sorted(job_info.keys()) if job_info else None,
        "jobs_info_scan_mode": job_info.get("ScanMode") if job_info else None,
        "jobs_info_time": dt_jobs,
        "settings_raw_keys": sorted(settings_raw.keys()) if settings_raw else None,
        "settings_raw_scan_mode": settings_raw.get("scanMode") if settings_raw else None,
        "settings_raw_ScanMode": settings_raw.get("ScanMode") if settings_raw else None,
        "settings_time": dt_settings,
    }


def print_sources(label, data):
    print(f"  --- {label} ---")
    print(f"  GetJobsInformation:")
    print(f"    Keys: {data['jobs_info_keys']}")
    print(f"    ScanMode: {data['jobs_info_scan_mode']!r}  (type={type(data['jobs_info_scan_mode']).__name__})")
    print(f"    Time: {data['jobs_info_time']:.3f}s")
    print(f"  GetJobSettings:")
    print(f"    Keys: {data['settings_raw_keys']}")
    print(f"    scanMode: {data['settings_raw_scan_mode']!r}  (type={type(data['settings_raw_scan_mode']).__name__})")
    print(f"    ScanMode: {data['settings_raw_ScanMode']!r}  (type={type(data['settings_raw_ScanMode']).__name__})")
    print(f"    Time: {data['settings_time']:.3f}s")
    print()


# --- Read BEFORE ---
print("=" * 60)
print("  BEFORE SetScanModeByJobName")
print("=" * 60)
before = read_both_sources()
print_sources("Before", before)

# Determine current mode and pick a different one
cur_mode_from_settings = before["settings_raw_scan_mode"]
cur_mode_from_jobs = before["jobs_info_scan_mode"]
print(f"  Current mode (settings): {cur_mode_from_settings!r}")
print(f"  Current mode (jobs):     {cur_mode_from_jobs!r}")

# Use the jobs info value as reference (it's what the confirm function reads)
cur_mode = cur_mode_from_jobs or cur_mode_from_settings or "xyz"
valid_modes = ["xyz", "xzy", "xz", "xt", "xyt", "xyzt"]
new_mode = next((m for m in valid_modes if m != cur_mode), None)
if new_mode is None:
    # Try case-insensitive
    new_mode = next((m for m in valid_modes if m.lower() != str(cur_mode).lower()), None)
if new_mode is None:
    raise SystemExit(f"Cannot find alternative mode (current: {cur_mode})")
print(f"  Will set mode to: {new_mode!r}")
print()


# --- FIRE SetScanModeByJobName ---
print("=" * 60)
print(f"  FIRE: SetScanModeByJobName('{JOB}', '{new_mode}')")
print("=" * 60)

api_obj = client.PyApiSetScanModeByJobName
api_obj.Model.JobName = JOB
api_obj.Model.ScanModeValue = new_mode
client.PyApiCommandEcho.Model.HasError = False
t0 = time.perf_counter()
receipt = api_obj.UpdateAwaitReceipt(2)
dt_fire = time.perf_counter() - t0
has_error = client.PyApiCommandEcho.Model.HasError
error_msg = client.PyApiCommandEcho.Model.Error if has_error else ""
print(f"  Receipt: {receipt}  Time: {dt_fire:.3f}s")
print(f"  Error: {has_error}  Message: {error_msg!r}")
print()


# --- Read AFTER (immediate) ---
print("=" * 60)
print("  AFTER SetScanModeByJobName (immediate)")
print("=" * 60)
after_0 = read_both_sources()
print_sources("After (0ms delay)", after_0)

# --- Read AFTER (100ms delay) ---
time.sleep(0.1)
after_100 = read_both_sources()
print_sources("After (100ms delay)", after_100)

# --- Read AFTER (500ms delay) ---
time.sleep(0.4)
after_500 = read_both_sources()
print_sources("After (500ms delay)", after_500)


# --- Comparison ---
print("=" * 60)
print("  COMPARISON")
print("=" * 60)
print(f"  Target:          {new_mode!r}")
print(f"  Jobs (0ms):      {after_0['jobs_info_scan_mode']!r}  match={after_0['jobs_info_scan_mode'] == new_mode}")
print(f"  Jobs (100ms):    {after_100['jobs_info_scan_mode']!r}  match={after_100['jobs_info_scan_mode'] == new_mode}")
print(f"  Jobs (500ms):    {after_500['jobs_info_scan_mode']!r}  match={after_500['jobs_info_scan_mode'] == new_mode}")
print(f"  Settings (0ms):  {after_0['settings_raw_scan_mode']!r}  match={after_0['settings_raw_scan_mode'] == new_mode}")
print(f"  Settings (100ms):{after_100['settings_raw_scan_mode']!r}  match={after_100['settings_raw_scan_mode'] == new_mode}")
print(f"  Settings (500ms):{after_500['settings_raw_scan_mode']!r}  match={after_500['settings_raw_scan_mode'] == new_mode}")
print()

# Case-insensitive
for label, val in [("Jobs 0ms", after_0['jobs_info_scan_mode']),
                   ("Jobs 500ms", after_500['jobs_info_scan_mode']),
                   ("Settings 0ms", after_0['settings_raw_scan_mode']),
                   ("Settings 500ms", after_500['settings_raw_scan_mode'])]:
    if val is not None:
        ci_match = str(val).lower() == new_mode.lower()
        print(f"  {label:20s} case-insensitive match: {ci_match}  (val={val!r})")
print()


# --- RESTORE ---
print("=" * 60)
print(f"  RESTORE: SetScanModeByJobName('{JOB}', '{cur_mode}')")
print("=" * 60)
api_obj.Model.JobName = JOB
api_obj.Model.ScanModeValue = cur_mode
receipt = api_obj.UpdateAwaitReceipt(2)
print(f"  Receipt: {receipt}")
time.sleep(0.2)
restored = read_both_sources()
print(f"  Restored mode (jobs): {restored['jobs_info_scan_mode']!r}")
print(f"  Restored mode (settings): {restored['settings_raw_scan_mode']!r}")
print()
print("Done.")

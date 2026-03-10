"""
LRP API Readback Test
======================
Toggle LineAverage in the LRP for a specific job and verify via
the API that the change is actually applied by LAS X.

Usage:
    python test_lrp_api_readback.py
    python test_lrp_api_readback.py --job "AF Job" --cycles 5
"""

import argparse
import sys
import time
import logging
import xml.etree.ElementTree as ET

logging.basicConfig(
    level=logging.INFO,
    format="%(name)s: %(message)s",
)

parser = argparse.ArgumentParser(description="LRP API Readback Test")
parser.add_argument("--job", default="AF Job",
                    help="Job name to test (default: AF Job)")
parser.add_argument("--cycles", type=int, default=3,
                    help="Number of toggle cycles (default: 3)")
parser.add_argument("--no-strip", action="store_true",
                    help="Skip stripping, work on full template")
args = parser.parse_args()

# -- Import ------------------------------------------------------------------

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from LasxApi import PYLICamApiConnector as lasx_api
import lasx as drv
from lasx.scanning_templates import (
    TEMPLATE_XML, STRIPPED_XML, get_template_state,
    find_scanning_templates_dir, load_experiment, save_experiment,
    apply_lrp_change,
)

print(f"  Driver version: {drv.__version__}")

# -- Connect -----------------------------------------------------------------

client = lasx_api.LasxApiClientPyModel
confirmed = client.Connect("PythonClient")
print(f"  Connected: {confirmed}")
if not confirmed:
    print("  ABORT: Cannot connect to LAS X. Is it running?")
    sys.exit(1)

if not drv.ping(client):
    print("  ABORT: ping failed")
    sys.exit(1)


# -- LRP edit function -------------------------------------------------------

def set_line_average(lrp_path, value, job_name):
    """Set LineAverage on all ATLConfocalSettingDefinition in a job."""
    lrp_path = Path(lrp_path)
    tree = ET.parse(lrp_path)
    root = tree.getroot()

    block = None
    for b in root.findall(".//LDM_Block_Sequence_Block"):
        seq = b.find(".//LDM_Block_Sequential")
        if seq is not None and seq.get("BlockName") == job_name:
            block = b
            break

    if block is None:
        print(f"  ERROR: job '{job_name}' not found in LRP")
        return 0

    count = 0
    for el in block.findall(".//ATLConfocalSettingDefinition"):
        old = el.get("LineAverage")
        el.set("LineAverage", str(value))
        if old != str(value):
            count += 1

    tree.write(lrp_path, encoding="utf-8", xml_declaration=True)
    return count


def read_lrp_line_average(lrp_path, job_name):
    """Read LineAverage values from the LRP file for a job.

    Returns a dict mapping element location to its LineAverage value,
    e.g. {"Master": "1", "Sequential": "1", "AutoFocus": "1"}.
    """
    root = ET.parse(lrp_path).getroot()
    values = {}
    for b in root.findall(".//LDM_Block_Sequence_Block"):
        seq = b.find(".//LDM_Block_Sequential")
        if seq is not None and seq.get("BlockName") == job_name:
            master = b.find(".//LDM_Block_Sequential_Master/ATLConfocalSettingDefinition")
            if master is not None:
                values["Master"] = master.get("LineAverage")
            seq_list = b.find(".//LDM_Block_Sequential_List/ATLConfocalSettingDefinition")
            if seq_list is not None:
                values["Sequential"] = seq_list.get("LineAverage")
            af = b.find(".//Block_Sequential_AutoFocus//ATLConfocalSettingDefinition")
            if af is not None:
                values["AutoFocus"] = af.get("LineAverage")
            break
    return values


def verify_line_average(lrp_path, value, job_name):
    """Verify LineAverage in the LRP file for a job."""
    values = read_lrp_line_average(lrp_path, job_name)
    return bool(values) and all(v == str(value) for v in values.values())


def read_api_line_average(client, job_name, max_retries=5):
    """Read lineAverage from the API for a job (cache-cleared)."""
    for attempt in range(1, max_retries + 1):
        client.PyApiGetJobSettingsByName.Model.Settings = None
        drv.select_job(client, job_name)
        r = drv.get_job_settings(client, job_name)
        if r is not None:
            return r["activeSettings"][0]["lineAverage"]
        print(f"    API read failed (attempt {attempt}), retrying...")
        time.sleep(2)
    print("    API read failed after all retries")
    return None


# -- Determine initial state -------------------------------------------------

state = get_template_state()
print(f"  Template state: {state}")

if state == "fresh":
    print("  No _PythonInspect files found -- saving current experiment...")
    templates_dir = find_scanning_templates_dir()
    if templates_dir is None:
        print("  ABORT: Cannot find ScanningTemplates directory")
        sys.exit(1)
    r = save_experiment(client, TEMPLATE_XML, templates_dir, timeout=120)
    if r is None:
        print("  ABORT: Initial save failed")
        sys.exit(1)
    print("  Saved. State is now 'unstripped'.")
    state = "unstripped"

# -- Strip if needed ----------------------------------------------------------

if args.no_strip:
    active_xml = TEMPLATE_XML
    print("  Skipping strip -- working on full template.")
else:
    if state == "unstripped":
        print("\n  Stripping template...")
        r = drv.strip_template(client)
        if r is None:
            print("  ABORT: strip_template failed")
            sys.exit(1)
        print(f"  Stripped.")
    elif state == "stripped":
        print("  Already stripped.")
    active_xml = STRIPPED_XML

# -- Read initial value -------------------------------------------------------

initial_api = read_api_line_average(client, args.job)
print(f"\n  Initial LineAverage (API) for '{args.job}': {initial_api}")

passed = 0
failed = 0

# -- Toggle cycles -----------------------------------------------------------

values = [2, 1]  # alternate between these
if initial_api == 2:
    values = [1, 2]

print(f"\n{'=' * 60}")
print(f"  Running {args.cycles} toggle cycle(s) on '{args.job}'")
print(f"  Toggle values: {values[0]} <-> {values[1]}")
print(f"{'=' * 60}")

templates_dir = find_scanning_templates_dir()
lrp_path = Path(templates_dir) / active_xml.replace(".xml", ".lrp")

for cycle in range(1, args.cycles + 1):
    for target in values:
        desc = f"Cycle {cycle}/{args.cycles} -- LineAverage -> {target}"
        print(f"\n  [{desc}]")

        # Step 1: Edit LRP + load + save + verify
        print(f"    Writing LineAverage={target} to LRP...")
        t0 = time.perf_counter()
        r = apply_lrp_change(
            client, active_xml,
            set_line_average, target, args.job,
            verify_fn=lambda p, v=target, j=args.job: verify_line_average(p, v, j),
        )
        elapsed = time.perf_counter() - t0

        if not (r and r["success"]):
            print(f"  \033[31m[FAIL]\033[0m {desc} -- apply_lrp_change failed ({elapsed:.1f}s)")
            failed += 1
            continue

        # Step 2: Read back from API
        api_val = read_api_line_average(client, args.job)

        print(f"    API:       LineAverage={api_val}")
        print(f"    Expected:  {target}")
        print(f"    Attempts:  {r['attempts']} ({elapsed:.1f}s)")

        api_ok = api_val == target

        if api_ok:
            print(f"  \033[32m[PASS]\033[0m {desc} -- API confirmed")
            passed += 1
        else:
            print(f"  \033[31m[FAIL]\033[0m {desc} -- API mismatch")
            failed += 1

# -- Restore ------------------------------------------------------------------

if not args.no_strip:
    print(f"\n{'=' * 60}")
    print("  Restoring template...")
    r = drv.restore_template(client)
    if r is None:
        print("  \033[31m[FAIL]\033[0m restore_template failed")
        failed += 1
    else:
        print(f"  \033[32m[PASS]\033[0m Restored ({r['attempts']} attempt(s), "
              f"{r['total_s']:.1f}s)")
        passed += 1

# -- Verify final state -------------------------------------------------------

final_api = read_api_line_average(client, args.job)
print(f"  Final LineAverage (API): {final_api} (was {initial_api} at start)")

# -- Summary ------------------------------------------------------------------

total = passed + failed
print(f"\n{'=' * 60}")
print(f"  Results: {passed}/{total} passed, {failed} failed")
print(f"{'=' * 60}")
sys.exit(1 if failed else 0)

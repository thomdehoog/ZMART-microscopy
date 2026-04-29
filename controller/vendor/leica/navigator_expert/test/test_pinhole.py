"""
Pinhole LRP Readback Test
===========================
Toggle pinhole (Airy units) via LRP file editing and verify the change
using both parse_lrp/diff_lrp and API readback (get_job_settings).

Uses the save -> edit LRP -> load workflow. After each edit, parses the
LRP before and after to confirm only PinholeAiry attributes changed.

Usage:
    python test_pinhole.py
    python test_pinhole.py --job HiRes --cycles 5
    python test_pinhole.py --values 0.5 1.0 1.5
"""

import argparse
import copy
import sys
import time
import logging
import xml.etree.ElementTree as ET

logging.basicConfig(
    level=logging.INFO,
    format="%(name)s: %(message)s",
)

parser = argparse.ArgumentParser(description="Pinhole LRP Readback Test")
parser.add_argument("--job", default="AF Job",
                    help="Job name (default: AF Job)")
parser.add_argument("--cycles", type=int, default=3,
                    help="Number of toggle cycles (default: 3)")
parser.add_argument("--values", type=float, nargs="+", default=None,
                    help="Pinhole values to cycle through in AU (default: auto)")
parser.add_argument("--no-strip", action="store_true",
                    help="Skip stripping, work on full template")
args = parser.parse_args()

# -- Import ------------------------------------------------------------------

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from LasxApi import PYLICamApiConnector as lasx_api
import navigator_expert.driver as drv
from navigator_expert.driver.scanning_templates import (
    TEMPLATE_XML, STRIPPED_XML, get_template_state,
    find_scanning_templates_dir, save_experiment,
    apply_lrp_change,
)
from navigator_expert.driver.scanning_template_parsers import parse_lrp, diff_lrp

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

def set_pinhole_airy_lrp(lrp_path, value, job_name):
    """Set PinholeAiry on all ATLConfocalSettingDefinition in a job."""
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
        old = el.get("PinholeAiry")
        el.set("PinholeAiry", str(value))
        if old != str(value):
            count += 1

    tree.write(lrp_path, encoding="utf-8", xml_declaration=True)
    return count


def verify_pinhole_lrp(lrp_path, value, job_name, tolerance=0.1):
    """Verify PinholeAiry in the parsed LRP for a job (with tolerance).

    LAS X adjusts PinholeAiry when saving (e.g. 1.0 -> 0.99996859...),
    so we use float tolerance instead of exact string comparison.
    """
    parsed = parse_lrp(lrp_path)
    job = parsed["jobs"].get(job_name, {})
    for section in ("Master", "Sequential", "AutoFocus"):
        s = job.get(section, {})
        attrs = s.get("attrs", {})
        if "PinholeAiry" in attrs:
            try:
                if abs(float(attrs["PinholeAiry"]) - value) > tolerance:
                    return False
            except (ValueError, TypeError):
                return False
    return True


def read_api_pinhole(client, job_name, setting_index=0, max_retries=5):
    """Read pinholeAiry from the API for a job (cache-cleared)."""
    for attempt in range(1, max_retries + 1):
        client.PyApiGetJobSettingsByName.Model.Settings = None
        drv.select_job(client, job_name)
        r = drv.get_job_settings(client, job_name)
        if r is not None:
            return r["activeSettings"][setting_index] \
                    .get("pinholeAiry", {}).get("value")
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
        print("  Stripped.")
    elif state == "stripped":
        print("  Already stripped.")
    active_xml = STRIPPED_XML

# -- Read initial value -------------------------------------------------------

templates_dir = find_scanning_templates_dir()
lrp_path = Path(templates_dir) / active_xml.replace(".xml", ".lrp")

initial_api = read_api_pinhole(client, args.job)
initial_parsed = parse_lrp(lrp_path)
initial_lrp = initial_parsed["jobs"].get(args.job, {}) \
    .get("Master", {}).get("attrs", {}).get("PinholeAiry", "?")

print(f"\n  Initial PinholeAiry for '{args.job}':")
print(f"    API: {initial_api} AU")
print(f"    LRP: {initial_lrp}")

passed = 0
failed = 0

# -- Determine test values ---------------------------------------------------

if args.values:
    values = args.values
else:
    if initial_api is not None and abs(initial_api - 1.0) > 0.2:
        values = [1.0, initial_api]
    else:
        values = [1.5, 1.0]

# -- Toggle cycles -----------------------------------------------------------

print(f"\n{'=' * 60}")
print(f"  Running {args.cycles} toggle cycle(s) on '{args.job}'")
print(f"  Toggle values: {' <-> '.join(str(v) for v in values)}")
print(f"{'=' * 60}")

for cycle in range(1, args.cycles + 1):
    for target in values:
        desc = f"Cycle {cycle}/{args.cycles} -- PinholeAiry -> {target}"
        print(f"\n  [{desc}]")

        # Snapshot LRP before edit
        before = parse_lrp(lrp_path)

        # Step 1: Edit LRP + load + save + verify via parser
        print(f"    Writing PinholeAiry={target} to LRP...")
        t0 = time.perf_counter()
        r = apply_lrp_change(
            client, active_xml,
            set_pinhole_airy_lrp, target, args.job,
            verify_fn=lambda p, v=target, j=args.job:
                verify_pinhole_lrp(p, v, j),
        )
        elapsed = time.perf_counter() - t0

        if not (r and r["success"]):
            print(f"  \033[31m[FAIL]\033[0m {desc} -- "
                  f"apply_lrp_change failed ({elapsed:.1f}s)")
            failed += 1
            continue

        # Step 2: Diff LRP before/after — PinholeAiry should change;
        # ZPosition, Pinhole (physical), Detectors, AutofocusConfig are
        # expected side effects of changing the optical pinhole size.
        EXPECTED_SIDE_EFFECTS = {
            "ZPosition", "Pinhole", "Gain", "OptimalStepSize",
            "_DetectionReferenceLine", "_AdditionalZPositions",
        }
        after = parse_lrp(lrp_path)
        diffs = diff_lrp(before, after)
        pinhole_diffs = [d for d in diffs if "PinholeAiry" in d["path"]]
        other_diffs = [d for d in diffs
                       if "PinholeAiry" not in d["path"]
                       and not any(k in d["path"]
                                   for k in EXPECTED_SIDE_EFFECTS)]

        lrp_ok = len(pinhole_diffs) > 0 and len(other_diffs) == 0
        if pinhole_diffs:
            for d in pinhole_diffs:
                print(f"    LRP diff: {d['path']}: {d['a']} -> {d['b']}")
        if other_diffs:
            print(f"    UNEXPECTED diffs ({len(other_diffs)}):")
            for d in other_diffs[:5]:
                print(f"      {d['path']}: {d['a']} -> {d['b']}")

        # Step 3: Read back from API
        api_val = read_api_pinhole(client, args.job)
        api_ok = api_val is not None and abs(api_val - target) < 0.05

        print(f"    API:       PinholeAiry={api_val}")
        print(f"    Expected:  {target}")
        print(f"    Attempts:  {r['attempts']} ({elapsed:.1f}s)")

        if lrp_ok and api_ok:
            print(f"  \033[32m[PASS]\033[0m {desc} -- LRP + API confirmed")
            passed += 1
        elif api_ok and not lrp_ok:
            print(f"  \033[33m[WARN]\033[0m {desc} -- API ok, LRP has "
                  f"unexpected diffs")
            failed += 1
        else:
            print(f"  \033[31m[FAIL]\033[0m {desc} -- "
                  f"LRP={'ok' if lrp_ok else 'fail'} "
                  f"API={'ok' if api_ok else 'fail'}")
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

final_api = read_api_pinhole(client, args.job)
print(f"  Final PinholeAiry (API): {final_api} AU (was {initial_api} at start)")

# -- Summary ------------------------------------------------------------------

total = passed + failed
print(f"\n{'=' * 60}")
print(f"  Results: {passed}/{total} passed, {failed} failed")
print(f"{'=' * 60}")
sys.exit(1 if failed else 0)

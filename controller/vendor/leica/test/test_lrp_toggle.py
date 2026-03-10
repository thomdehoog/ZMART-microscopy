"""
LRP System-Optimized Toggle Test
=================================
Toggle the system-optimized Z-stack step size on and off via the
strip -> edit LRP -> restore workflow.

Usage:
    python test_lrp_toggle.py
    python test_lrp_toggle.py --cycles 3
    python test_lrp_toggle.py --retry-interval 2.0
"""

import argparse
import sys
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(name)s: %(message)s",
)

parser = argparse.ArgumentParser(description="LRP System-Optimized Toggle Test")
parser.add_argument("--cycles", type=int, default=2,
                    help="Number of on/off toggle cycles (default: 2)")
parser.add_argument("--job", default="HiRes",
                    help="Job name to toggle (default: HiRes)")
args = parser.parse_args()

# ── Import ──────────────────────────────────────────────────────────────

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from LasxApi import PYLICamApiConnector as lasx_api
import lasx as drv
from lasx.template_operations import (
    TEMPLATE_XML, STRIPPED_XML, get_template_state,
)
from lasx.template_parser import (
    apply_lrp_change, set_system_optimized_step_size,
    verify_system_optimized_step_size,
)

print(f"  Driver version: {drv.__version__}")

# ── Connect ─────────────────────────────────────────────────────────────

client = lasx_api.LasxApiClientPyModel
confirmed = client.Connect("PythonClient")
print(f"  Connected: {confirmed}")
if not confirmed:
    print("  ABORT: Cannot connect to LAS X. Is it running?")
    sys.exit(1)

if not drv.ping(client):
    print("  ABORT: ping failed")
    sys.exit(1)

# ── Determine initial state ────────────────────────────────────────────

state = get_template_state()
print(f"  Template state: {state}")

if state == "fresh":
    print("  No _PythonInspect files found -- saving current experiment...")
    templates_dir = drv.find_scanning_templates_dir()
    if templates_dir is None:
        print("  ABORT: Cannot find ScanningTemplates directory")
        sys.exit(1)
    r = drv.save_experiment(client, TEMPLATE_XML, templates_dir)
    if r is None:
        print("  ABORT: Initial save failed")
        sys.exit(1)
    print("  Saved. State is now 'unstripped'.")
    state = "unstripped"

# ── Strip if needed ────────────────────────────────────────────────────

if state == "unstripped":
    print("\n  Stripping template...")
    r = drv.strip_template(client)
    if r is None:
        print("  ABORT: strip_template failed")
        sys.exit(1)
    print(f"  Stripped. [{r['original_fields']} fields, "
          f"{r['original_items']} items, {r['original_focus']} focus]")
elif state == "stripped":
    print("  Already stripped, continuing.")

# ── Toggle cycles ──────────────────────────────────────────────────────

print(f"\n{'=' * 60}")
print(f"  Running {args.cycles} toggle cycle(s) on job '{args.job}'")
print(f"{'=' * 60}")

passed = 0
failed = 0

for cycle in range(1, args.cycles + 1):
    for enabled in (True, False):
        label = "ON" if enabled else "OFF"
        desc = f"Cycle {cycle}/{args.cycles} -- System Optimized -> {label}"
        print(f"\n  [{desc}]")

        t0 = time.perf_counter()
        r = apply_lrp_change(
            client, STRIPPED_XML,
            set_system_optimized_step_size, enabled, args.job,
            verify_fn=lambda p, e=enabled, j=args.job: verify_system_optimized_step_size(p, e, j),
        )
        elapsed = time.perf_counter() - t0

        if r and r["success"]:
            print(f"  \033[32m[PASS]\033[0m {desc} "
                  f"({r['attempts']} attempt(s), {elapsed:.1f}s)")
            passed += 1
        else:
            print(f"  \033[31m[FAIL]\033[0m {desc} ({elapsed:.1f}s)")
            failed += 1

# ── Restore ─────────────────────────────────────────────────────────────

print(f"\n{'=' * 60}")
print("  Restoring template...")
r = drv.restore_template(client)
if r is None:
    print("  \033[31m[FAIL]\033[0m restore_template failed")
    failed += 1
else:
    print(f"  \033[32m[PASS]\033[0m Restored [{r['fields']} fields, "
          f"{r['items']} items, {r['focus']} focus] "
          f"({r['attempts']} attempt(s), {r['total_s']:.1f}s)")
    passed += 1

# ── Summary ─────────────────────────────────────────────────────────────

total = passed + failed
print(f"\n{'=' * 60}")
print(f"  Results: {passed}/{total} passed, {failed} failed")
print(f"{'=' * 60}")
sys.exit(1 if failed else 0)

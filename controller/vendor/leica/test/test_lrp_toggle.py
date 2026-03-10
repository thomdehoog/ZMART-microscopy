"""
LRP Stack Calculation Mode Toggle Test
========================================
Cycle through Z-stack calculation modes via the
save -> edit LRP -> load workflow on the _PythonInspect template.

Modes: 0 = Constant steps, 1 = Constant step size,
       2 = System optimized step size

Usage:
    python test_lrp_toggle.py
    python test_lrp_toggle.py --cycles 3
    python test_lrp_toggle.py --job "AF Job"
    python test_lrp_toggle.py --modes 0 2
"""

import argparse
import sys
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(name)s: %(message)s",
)

parser = argparse.ArgumentParser(description="LRP Stack Calculation Mode Toggle Test")
parser.add_argument("--cycles", type=int, default=2,
                    help="Number of toggle cycles (default: 2)")
parser.add_argument("--job", default="AF Job",
                    help="Job name to toggle (default: AF Job)")
parser.add_argument("--modes", type=int, nargs="+", default=[0, 1, 2],
                    help="Modes to cycle through (default: 0 1 2)")
args = parser.parse_args()

# ── Import ──────────────────────────────────────────────────────────────

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from LasxApi import PYLICamApiConnector as lasx_api
import lasx as drv
from lasx.template_operations import TEMPLATE_XML
from lasx.template_parser import (
    STACK_MODES,
    apply_lrp_change, set_stack_calculation_mode,
    verify_stack_calculation_mode,
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

# ── Toggle cycles ──────────────────────────────────────────────────────

for m in args.modes:
    if m not in STACK_MODES:
        print(f"  ABORT: invalid mode {m} (expected 0, 1, or 2)")
        sys.exit(1)

print(f"\n{'=' * 60}")
print(f"  Running {args.cycles} cycle(s) on job '{args.job}'")
print(f"  Modes: {' -> '.join(STACK_MODES[m] for m in args.modes)}")
print(f"  Using {TEMPLATE_XML}")
print(f"{'=' * 60}")

passed = 0
failed = 0

for cycle in range(1, args.cycles + 1):
    for mode in args.modes:
        desc = f"Cycle {cycle}/{args.cycles} -- mode {mode} ({STACK_MODES[mode]})"
        print(f"\n  [{desc}]")

        t0 = time.perf_counter()
        r = apply_lrp_change(
            client, TEMPLATE_XML,
            set_stack_calculation_mode, mode, args.job,
            verify_fn=lambda p, m=mode, j=args.job: verify_stack_calculation_mode(p, m, j),
            active_job=args.job,
        )
        elapsed = time.perf_counter() - t0

        if r and r["success"]:
            print(f"  \033[32m[PASS]\033[0m {desc} "
                  f"({r['attempts']} attempt(s), {elapsed:.1f}s)")
            passed += 1
        else:
            print(f"  \033[31m[FAIL]\033[0m {desc} ({elapsed:.1f}s)")
            failed += 1

# ── Summary ─────────────────────────────────────────────────────────────

total = passed + failed
print(f"\n{'=' * 60}")
print(f"  Results: {passed}/{total} passed, {failed} failed")
print(f"{'=' * 60}")
sys.exit(1 if failed else 0)

"""
Pan & ROI Live Integration Test
=================================
Test galvo pan and ROI editing via the
save -> edit LRP -> load workflow on the _PythonInspect template.

Usage:
    python test_pan_roi.py
    python test_pan_roi.py --job "AF Job"
"""

import argparse
import sys
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(name)s: %(message)s",
)

parser = argparse.ArgumentParser(description="Pan & ROI Live Integration Test")
parser.add_argument("--job", default="AF Job",
                    help="Job name to test (default: AF Job)")
args = parser.parse_args()

# ── Import ──────────────────────────────────────────────────────────────

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from LasxApi import PYLICamApiConnector as lasx_api
import lasx as drv
from lasx.scanning_templates import TEMPLATE_XML, apply_lrp_change
from lasx.scanning_template_editors_scan import (
    lrp_set_pan, lrp_verify_pan,
)
from lasx.scanning_template_editors_roi import (
    lrp_enable_roi_scan, lrp_verify_roi_scan,
    lrp_clear_rois, lrp_add_roi,
    lrp_verify_roi_count,
    make_rectangle,
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

# ── Test helpers ────────────────────────────────────────────────────────

passed = 0
failed = 0


def run_test(desc, edit_fn, verify_fn):
    """Run a single test: apply_lrp_change + verify."""
    global passed, failed
    print(f"\n  [{desc}]")
    t0 = time.perf_counter()
    r = apply_lrp_change(
        client, TEMPLATE_XML,
        edit_fn,
        verify_fn=verify_fn,
    )
    elapsed = time.perf_counter() - t0
    if r and r["success"]:
        print(f"  \033[32m[PASS]\033[0m {desc} "
              f"({r['attempts']} attempt(s), {elapsed:.1f}s)")
        passed += 1
    else:
        print(f"  \033[31m[FAIL]\033[0m {desc} ({elapsed:.1f}s)")
        failed += 1


# ── Pan tests ───────────────────────────────────────────────────────────

print(f"\n{'=' * 60}")
print(f"  Pan Tests — job '{args.job}'")
print(f"  Using {TEMPLATE_XML}")
print(f"{'=' * 60}")

# Set pan to (0.25, -0.1)
run_test(
    "Set pan to (0.25, -0.1)",
    lambda p: lrp_set_pan(p, 0.25, -0.1, args.job),
    lambda p: lrp_verify_pan(p, 0.25, -0.1, args.job),
)

# Reset pan to (0, 0)
run_test(
    "Reset pan to (0, 0)",
    lambda p: lrp_set_pan(p, 0, 0, args.job),
    lambda p: lrp_verify_pan(p, 0, 0, args.job),
)

# ── ROI tests ───────────────────────────────────────────────────────────

print(f"\n{'=' * 60}")
print(f"  ROI Tests — job '{args.job}'")
print(f"{'=' * 60}")

# Clear ROIs
run_test(
    "Clear all ROIs",
    lambda p: lrp_clear_rois(p, args.job),
    lambda p: lrp_verify_roi_count(p, 0, args.job),
)

# Add a rectangle ROI
def _add_rect_roi(p):
    verts = make_rectangle(0.5, 0.5)
    lrp_add_roi(p, args.job, "8", verts)

run_test(
    "Add rectangle ROI",
    _add_rect_roi,
    lambda p: lrp_verify_roi_count(p, 1, args.job),
)

# Enable ROI scan
run_test(
    "Enable ROI scan",
    lambda p: lrp_enable_roi_scan(p, True, args.job),
    lambda p: lrp_verify_roi_scan(p, True, args.job),
)

# Disable ROI scan + clear
def _disable_and_clear(p):
    lrp_enable_roi_scan(p, False, args.job)
    lrp_clear_rois(p, args.job)

def _verify_disabled_and_clear(p):
    return (lrp_verify_roi_scan(p, False, args.job) and
            lrp_verify_roi_count(p, 0, args.job))

run_test(
    "Disable ROI scan + clear ROIs",
    _disable_and_clear,
    _verify_disabled_and_clear,
)

# ── Summary ─────────────────────────────────────────────────────────────

total = passed + failed
print(f"\n{'=' * 60}")
print(f"  Results: {passed}/{total} passed, {failed} failed")
print(f"{'=' * 60}")
sys.exit(1 if failed else 0)

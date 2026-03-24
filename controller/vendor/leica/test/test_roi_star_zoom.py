"""
ROI Star + Zoom Integration Test
===================================
Add stars at different sizes relative to the FOV and change zoom levels
to verify the ROI overlay updates correctly.

Usage:
    python test_roi_star_zoom.py
    python test_roi_star_zoom.py --job "AF Job"
    python test_roi_star_zoom.py --zooms 4 10 20 40
"""

import argparse
import sys
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(name)s: %(message)s",
)

parser = argparse.ArgumentParser(
    description="ROI Star + Zoom Integration Test")
parser.add_argument("--job", default="HiRes",
                    help="Job name to test (default: HiRes)")
parser.add_argument("--zooms", type=float, nargs="+",
                    default=[4, 10, 20, 40],
                    help="Zoom levels to cycle through")
parser.add_argument("--pause", type=float, default=2.0,
                    help="Seconds to pause between steps (default: 2.0)")
args = parser.parse_args()

# ── Import ───────────────────────────────────────────────────────────────

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from LasxApi import PYLICamApiConnector as lasx_api
import lasx as drv
from lasx.scanning_templates import TEMPLATE_XML, apply_lrp_change
from lasx.scanning_template_editors_scan import lrp_set_zoom, lrp_verify_zoom
from lasx.scanning_template_editors_roi import (
    lrp_enable_roi_scan, lrp_verify_roi_scan,
    lrp_clear_rois, lrp_add_roi,
    lrp_verify_roi_count,
    make_star, um,
)

print(f"  Driver version: {drv.__version__}")

# ── Connect ──────────────────────────────────────────────────────────────

client = lasx_api.LasxApiClientPyModel
confirmed = client.Connect("PythonClient")
print(f"  Connected: {confirmed}")
if not confirmed:
    print("  ABORT: Cannot connect to LAS X. Is it running?")
    sys.exit(1)

if not drv.ping(client):
    print("  ABORT: ping failed")
    sys.exit(1)

job = args.job

# ── Test helpers ─────────────────────────────────────────────────────────

passed = 0
failed = 0


def run_test(desc, edit_fn, verify_fn=None):
    """Run a single test: apply_lrp_change + optional verify."""
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


# ── Test 1: Add FOV-relative star at current zoom ───────────────────────

print(f"\n{'=' * 60}")
print(f"  ROI Star + Zoom Test — job '{job}'")
print(f"  Zooms: {args.zooms}")
print(f"{'=' * 60}")

# Clear existing ROIs and enable ROI scan
def _setup(p):
    lrp_clear_rois(p, job)
    lrp_enable_roi_scan(p, True, job)

run_test("Clear ROIs + enable ROI scan", _setup,
         lambda p: lrp_verify_roi_scan(p, True, job))

# ── Test 2: At each zoom level, add a star sized to FOV ─────────────────

for z in args.zooms:
    # Set zoom
    run_test(
        f"Set zoom to {z}",
        lambda p, _z=z: lrp_set_zoom(p, _z, job),
        lambda p, _z=z: lrp_verify_zoom(p, _z, job),
    )

    # Query FOV at this zoom
    fov = drv.get_fov(client, job)
    if fov:
        fov_um = fov[0] * 1e6
        print(f"  FOV at zoom {z}: {fov_um:.1f} um")
    else:
        fov_um = 1160.0 / z  # rough estimate
        print(f"  FOV query failed, estimating: {fov_um:.1f} um")

    # Add star at 30% of FOV
    outer_r = fov[0] * 0.3 if fov else um(fov_um * 0.3)
    inner_r = outer_r * 0.4

    def _add_star(p, _or=outer_r, _ir=inner_r):
        lrp_clear_rois(p, job)
        verts = make_star(outer_radius=_or, inner_radius=_ir)
        lrp_add_roi(p, job, "8", verts)

    run_test(
        f"Add star (30% FOV = {outer_r*1e6:.1f} um outer) at zoom {z}",
        _add_star,
        lambda p: lrp_verify_roi_count(p, 1, job),
    )

    print(f"  -- Pausing {args.pause}s (check LAS X) --")
    time.sleep(args.pause)

# ── Test 3: Zoom sweep with same star ────────────────────────────────────

print(f"\n{'=' * 60}")
print(f"  Zoom sweep with fixed star (5 um outer)")
print(f"{'=' * 60}")

# Add a fixed-size star
def _add_fixed_star(p):
    lrp_clear_rois(p, job)
    verts = make_star(outer_radius=um(5), inner_radius=um(2))
    lrp_add_roi(p, job, "8", verts)

run_test("Add fixed star (5 um outer, 2 um inner)", _add_fixed_star,
         lambda p: lrp_verify_roi_count(p, 1, job))
time.sleep(args.pause)

# Zoom up and down
zoom_sweep = sorted(args.zooms) + sorted(args.zooms, reverse=True)
for z in zoom_sweep:
    run_test(
        f"Zoom to {z} (fixed star)",
        lambda p, _z=z: lrp_set_zoom(p, _z, job),
        lambda p, _z=z: lrp_verify_zoom(p, _z, job),
    )
    print(f"  -- Pausing {args.pause}s --")
    time.sleep(args.pause)

# ── Cleanup ──────────────────────────────────────────────────────────────

print(f"\n{'=' * 60}")
print(f"  Cleanup")
print(f"{'=' * 60}")

def _cleanup(p):
    lrp_enable_roi_scan(p, False, job)
    lrp_clear_rois(p, job)
    lrp_set_zoom(p, 10, job)

run_test("Disable ROI scan + clear + reset zoom",
         _cleanup,
         lambda p: (lrp_verify_roi_scan(p, False, job) and
                    lrp_verify_roi_count(p, 0, job)))

# ── Summary ──────────────────────────────────────────────────────────────

total = passed + failed
print(f"\n{'=' * 60}")
print(f"  Results: {passed}/{total} passed, {failed} failed")
print(f"{'=' * 60}")
sys.exit(1 if failed else 0)

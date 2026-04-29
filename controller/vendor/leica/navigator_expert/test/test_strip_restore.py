"""
Strip / Restore Integration Test (requires live LAS X).
========================================================
Runs strip → restore cycles and verifies object counts are preserved.

Usage:
    python test_strip_restore.py
    python test_strip_restore.py --cycles 10
"""

import argparse
import sys
import time

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from LasxApi import PYLICamApiConnector as lasx_api
import navigator_expert.driver as drv
from navigator_expert.driver.scanning_templates import (
    TEMPLATE_XML, find_scanning_templates_dir,
    get_template_state, _count_objects,
)

parser = argparse.ArgumentParser()
parser.add_argument("--cycles", type=int, default=3)
args = parser.parse_args()

# ── Connect ─────────────────────────────────────────────────────────────

client = lasx_api.LasxApiClientPyModel
assert client.Connect("PythonClient"), "Cannot connect to LAS X"
assert drv.ping(client), "Ping failed"

td = find_scanning_templates_dir()
assert td is not None, "Cannot find ScanningTemplates directory"

xml = Path(td) / TEMPLATE_XML
rgn = xml.with_suffix(".rgn")

# ── Pre-flight ──────────────────────────────────────────────────────────

state = get_template_state(td)
if state == "stripped":
    print("Already stripped — restoring first...")
    r = drv.restore_template(client)
    assert r is not None, "Pre-restore failed"

if state == "fresh":
    print("No template files — saving current experiment...")
    r = drv.save_experiment(client, TEMPLATE_XML, td, timeout=120)
    assert r is not None, "Initial save failed"

f0, i0, fp0 = _count_objects(xml, rgn)
print(f"Baseline: {f0} fields, {i0} items, {fp0} focus")
print(f"Running {args.cycles} cycle(s)\n")

# ── Cycles ──────────────────────────────────────────────────────────────

passed = 0

for c in range(1, args.cycles + 1):
    t0 = time.perf_counter()

    r = drv.strip_template(client)
    t_strip = time.perf_counter() - t0
    assert r is not None, f"Cycle {c}: strip failed"

    t1 = time.perf_counter()
    r = drv.restore_template(client)
    t_restore = time.perf_counter() - t1
    assert r is not None, f"Cycle {c}: restore failed"

    ok = r["fields"] >= f0 and r["items"] >= i0
    status = "PASS" if ok else "FAIL"
    print(f"  {c}/{args.cycles}: {status}  strip={t_strip:.1f}s  "
          f"restore={t_restore:.1f}s  "
          f"[{r['fields']}/{r['items']}, {r['attempts']} attempt(s)]")
    assert ok, (f"Cycle {c}: count mismatch — "
                f"expected >={f0}/{i0}, got {r['fields']}/{r['items']}")
    passed += 1

print(f"\n{passed}/{args.cycles} passed.")

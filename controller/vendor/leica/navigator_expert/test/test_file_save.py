"""
Test file save reliability
===========================
Acquire single images on the Overview job and check that LAS X
actually writes the files to disk.  Repeats N times to surface
intermittent save failures.

Usage:
    python test_file_save.py
    python test_file_save.py --repeats 20 --job Overview
"""

import argparse
import sys
import time
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
log = logging.getLogger(__name__)

parser = argparse.ArgumentParser(description="Test LAS X file save reliability")
parser.add_argument("--repeats", type=int, default=1,
                    help="Number of acquire cycles (default: 1)")
parser.add_argument("--job", default="Overview",
                    help="LAS X job name (default: Overview)")
parser.add_argument("--stability-timeout", type=float, default=30,
                    help="Max seconds to wait for file stability (default: 30)")
args = parser.parse_args()

# ── Imports ──────────────────────────────────────────────────────────────

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from LasxApi import PYLICamApiConnector as lasx_api
import navigator_expert.driver as drv
from navigator_expert.driver.readers import get_lasx_settings
from navigator_expert.driver.prechecks import check_idle
from navigator_expert.driver.file_confirmation import (
    read_relative_path, detect_new_files, wait_all_stable,
)

# ── Connect ──────────────────────────────────────────────────────────────

client = lasx_api.LasxApiClientPyModel
confirmed = client.Connect("PythonClient")
if not confirmed:
    print("ABORT: Cannot connect to LAS X.")
    sys.exit(1)
assert drv.ping(client), "ping failed"

drv.select_job(client, args.job)
time.sleep(1)
current = drv.get_selected_job(client).get("Name", "")
if current != args.job:
    print(f"ABORT: Expected '{args.job}', got '{current}'.")
    sys.exit(1)

media = get_lasx_settings()["export"]["media_path"]
print(f"Job: {args.job}")
print(f"Media: {media}")
print(f"Repeats: {args.repeats}")
print()

# ── Run ──────────────────────────────────────────────────────────────────

results = []

for i in range(1, args.repeats + 1):
    print(f"--- Acquire {i}/{args.repeats} ---")

    # Pre-check
    idle = check_idle(client, timeout=15)
    if not idle["success"]:
        print(f"  WARNING: scanner not idle before acquire")

    baseline = read_relative_path(client)
    t0 = time.time()

    # Acquire
    r = drv.acquire(client, args.job)
    elapsed_acquire = time.time() - t0

    if not r or not r.get("success"):
        print(f"  FAIL: acquire returned {r}")
        results.append({"i": i, "ok": False, "stage": "acquire", "detail": str(r)})
        continue

    print(f"  Acquired in {elapsed_acquire:.1f}s")

    # Detect files
    det = detect_new_files(client, baseline, media, acquire_start=t0)

    if not det["success"]:
        print(f"  FAIL: detect_new_files — {det.get('error')}")
        results.append({"i": i, "ok": False, "stage": "detect", "detail": det.get("error")})
        continue

    n_img = len(det["image_files"])
    n_xml = len(det["xml_files"])
    method = det["method"]
    print(f"  Detected {n_img} image + {n_xml} XML (method={method})")

    # Wait for stability
    all_files = det["image_files"] + det["xml_files"]
    stable = wait_all_stable(all_files, timeout=args.stability_timeout)

    if not stable["success"]:
        print(f"  FAIL: files not stable — {stable.get('error')}")
        for u in stable.get("unstable", []):
            print(f"    unstable: {u}")
        results.append({"i": i, "ok": False, "stage": "stability",
                        "detail": stable.get("error"),
                        "n_img": n_img, "method": method})
        continue

    # Basic size check
    sizes = []
    for f in det["image_files"]:
        sz = Path(f).stat().st_size
        sizes.append(sz)
        if sz < 1024:
            print(f"  WARNING: {Path(f).name} is only {sz} bytes")

    elapsed_total = time.time() - t0
    print(f"  OK: {n_img} files, sizes {min(sizes)}-{max(sizes)} bytes, "
          f"total {elapsed_total:.1f}s")

    results.append({
        "i": i, "ok": True,
        "n_img": n_img, "n_xml": n_xml,
        "method": method,
        "sizes": sizes,
        "acquire_s": elapsed_acquire,
        "total_s": elapsed_total,
    })

# ── Summary ──────────────────────────────────────────────────────────────

print()
print(f"{'=' * 40}")
print(f"  Results: {args.repeats} attempts")
print(f"{'=' * 40}")

ok = [r for r in results if r["ok"]]
fail = [r for r in results if not r["ok"]]

print(f"  Pass: {len(ok)}/{len(results)}")
if fail:
    print(f"  Fail: {len(fail)}")
    for f in fail:
        print(f"    #{f['i']}: {f['stage']} — {f.get('detail', '?')}")

if ok:
    times = [r["total_s"] for r in ok]
    print(f"  Total time: {min(times):.1f}–{max(times):.1f}s "
          f"(mean {sum(times)/len(times):.1f}s)")
    methods = set(r["method"] for r in ok)
    print(f"  Detection methods used: {', '.join(methods)}")

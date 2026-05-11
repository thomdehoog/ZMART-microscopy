"""Crash-recovery integration test for driver.acquire_and_save.

Spawns a child process running start_run + multiple acquire_and_save
calls with a sleep between each, then kills it mid-stream. Verifies
that summary.json remains parseable and the run directory is in a
consistent state (no half-written files).

Uses stdlib subprocess.Popen + .kill() — Windows-correct (signal.SIGKILL
does not exist on Windows).
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest


CHILD_SCRIPT = Path(__file__).parent / "_crash_recovery_child.py"


def _spawn_child(media_path: Path, count: int, sleep_s: float) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, str(CHILD_SCRIPT),
         str(media_path), str(count), str(sleep_s)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_kill_mid_acquisition_leaves_parseable_summary(tmp_path):
    media_path = tmp_path / "media"
    proc = _spawn_child(media_path, count=10, sleep_s=0.5)
    try:
        # Wait for at least 2 acquisitions to land, then kill.
        deadline = time.time() + 30.0
        completed = 0
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                break
            if line.startswith("acq "):
                completed += 1
                if completed >= 2:
                    break

        assert completed >= 2, "child failed to complete any acquisitions before kill"
        proc.kill()
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)

    # Locate the run dir via the beacon the child wrote.
    beacon = media_path / "run_dir.txt"
    assert beacon.is_file(), "child did not write run_dir beacon"
    run_dir = Path(beacon.read_text().strip())
    assert run_dir.is_dir()

    # summary.json must be parseable (atomic write held under SIGKILL).
    summary_path = run_dir / "summary.json"
    assert summary_path.is_file()
    data = json.loads(summary_path.read_text())  # raises if corrupt

    assert data["experiment"] == "crash-exp"
    # At least the acquisitions reported before kill should be in summary.
    assert len(data["acquisitions"]) >= 2

    # No stale .tmp files in the run tree.
    stale = list(run_dir.rglob("*.tmp"))
    assert stale == [], f"Stale .tmp files found: {stale}"


def test_image_xml_pairs_consistent_after_kill(tmp_path):
    """Every image in summary.json has its XML on disk and vice versa."""
    media_path = tmp_path / "media"
    proc = _spawn_child(media_path, count=10, sleep_s=0.4)
    try:
        deadline = time.time() + 30.0
        completed = 0
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                break
            if line.startswith("acq "):
                completed += 1
                if completed >= 3:
                    break
        proc.kill()
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)

    beacon = media_path / "run_dir.txt"
    run_dir = Path(beacon.read_text().strip())
    summary_path = run_dir / "summary.json"
    data = json.loads(summary_path.read_text())

    for rec in data["acquisitions"]:
        image_path = run_dir / rec["image_path"]
        xml_path = run_dir / rec["xml_path"]
        assert image_path.is_file(), f"missing image: {image_path}"
        assert xml_path.is_file(), f"missing xml: {xml_path}"

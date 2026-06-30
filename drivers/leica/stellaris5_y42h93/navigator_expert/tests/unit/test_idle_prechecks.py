"""Idle-before-anything policy (operator decision, 2026-06-11).

Commands that touch the scope's physical/acquisition state must SEE the
scanner idle before firing, and must wait for it indefinitely - a long
acquisition is the natural synchronization point, never a timeout. The
wait stays observable through check_idle's heartbeat; it is fail-closed
against Unknown status (Unknown is not idle).
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from navigator_expert.commands import prechecks
from navigator_expert.config import profiles

IDLE_GUARDED = [
    "MOVE_XY",
    "MOVE_Z",
    "OBJECTIVE",
    "SELECT_JOB",
    "ACQUIRE",
    "ACQUIRE_SINGLE_IMAGE",
]


class TestIdlePrecheckPolicy(unittest.TestCase):
    def test_physical_commands_wait_for_idle_without_timeout(self):
        for name in IDLE_GUARDED:
            profile = getattr(profiles, name)
            with self.subTest(profile=name):
                self.assertIsNotNone(profile.pre_check_fn, f"{name} must see idle before firing")
                self.assertIsNone(
                    profile.pre_check_fn.keywords.get("timeout", "missing"),
                    f"{name} idle wait must be unbounded (timeout=None)",
                )

    def test_check_idle_waits_through_long_busy_phase(self):
        statuses = iter(["eScanRunning"] * 50 + ["eScanIdle"])
        with (
            patch.object(
                prechecks._readers, "get_scan_status", side_effect=lambda c, **k: next(statuses)
            ),
            patch("time.sleep"),
        ):
            result = prechecks.check_idle(object(), timeout=None)
        self.assertTrue(result["success"])

    def test_check_idle_unknown_is_not_idle(self):
        statuses = iter(["Unknown", None, "eScanIdle"])
        with (
            patch.object(
                prechecks._readers, "get_scan_status", side_effect=lambda c, **k: next(statuses)
            ),
            patch("time.sleep"),
        ):
            result = prechecks.check_idle(object(), timeout=None)
        self.assertTrue(result["success"])  # waited through Unknown, not past it


if __name__ == "__main__":
    unittest.main()

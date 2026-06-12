"""Unit tests for log-backed polling helpers."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from navigator_expert.runtime import profiles
from navigator_expert.state_readers import log_reader
from navigator_expert.state_readers.log_wait import wait_for_selected_job_log


def _job(block_id, name):
    return {
        "id": block_id,
        "jobName": name,
        "imageSize": "1.0 mm x 1.0 mm",
    }


def _snapshot(
    *,
    now,
    selected=None,
    selected_ts=None,
    jobs=(),
    current_block_name=None,
    current_block_id=None,
    current_block_ts=None,
):
    snap = log_reader.Snapshot(now=now)
    snap.selected_element = selected
    snap.selected_ts = selected_ts
    snap.current_block_name = current_block_name
    snap.current_block_id = current_block_id
    snap.current_block_ts = current_block_ts
    for block_id, name, ts in jobs:
        snap.atl_by_block[str(block_id)] = (_job(block_id, name), ts)
    return snap


class TestLogWait(unittest.TestCase):
    def setUp(self):
        self._state_profile = profiles.STATE_READERS

    def tearDown(self):
        profiles.STATE_READERS = self._state_profile

    def test_selected_job_poll_succeeds_immediately(self):
        snap = _snapshot(
            now=102.0,
            selected=2,
            selected_ts=101.0,
            jobs=[(1, "AF Job", 101.0), (2, "Overview", 101.0)],
        )

        result = wait_for_selected_job_log(
            "Overview",
            command_started_at=100.0,
            timeout_s=0.0,
            parse_fn=lambda: snap,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.value, "Overview")
        self.assertEqual(result.reason, "matched")
        self.assertEqual(result.attempts, 1)

    def test_selected_job_poll_breaks_when_later_snapshot_matches(self):
        snapshots = iter([
            _snapshot(now=101.0, jobs=[(1, "Overview", 101.0)]),
            _snapshot(
                now=102.0,
                selected=1,
                selected_ts=101.5,
                jobs=[(1, "Overview", 101.5)],
            ),
        ])
        clock = [0.0]
        sleeps = []

        def sleep(dt):
            sleeps.append(dt)
            clock[0] += dt

        result = wait_for_selected_job_log(
            "Overview",
            command_started_at=100.0,
            timeout_s=1.0,
            poll_interval_s=0.1,
            parse_fn=lambda: next(snapshots),
            sleep_fn=sleep,
            monotonic_fn=lambda: clock[0],
        )

        self.assertTrue(result.success)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(len(sleeps), 1)

    def test_selected_job_poll_rejects_pre_command_selection(self):
        snap = _snapshot(
            now=102.0,
            selected=1,
            selected_ts=99.0,
            jobs=[(1, "Overview", 99.0)],
        )

        result = wait_for_selected_job_log(
            "Overview",
            command_started_at=100.0,
            timeout_s=0.0,
            parse_fn=lambda: snap,
        )

        self.assertFalse(result.success)
        self.assertEqual(result.reason, "timeout")
        self.assertEqual(result.diagnostics["last_reason"], "selected_before_command")

    def test_selected_job_poll_reports_partial_cluster(self):
        snap = _snapshot(
            now=3705.0,
            selected=1,
            selected_ts=3701.0,
            jobs=[
                (1, "AF Job", 0.0),
                (2, "Overview", 3701.0),
                (3, "HiRes", 0.0),
            ],
        )

        result = wait_for_selected_job_log(
            "Overview",
            command_started_at=3700.0,
            timeout_s=0.0,
            max_age_s=60.0,
            parse_fn=lambda: snap,
        )

        self.assertFalse(result.success)
        self.assertEqual(result.diagnostics["last_reason"], "partial_job_cluster")
        self.assertTrue(result.diagnostics["selected_after_command"])

    def test_selected_job_poll_accepts_fresh_current_block_without_job_cluster(self):
        snap = _snapshot(
            now=3705.0,
            current_block_name="Overview",
            current_block_id=6,
            current_block_ts=3701.0,
            jobs=[
                (1, "AF Job", 0.0),
                (2, "Overview", 0.0),
                (3, "HiRes", 0.0),
            ],
        )

        result = wait_for_selected_job_log(
            "Overview",
            command_started_at=3700.0,
            timeout_s=0.0,
            max_age_s=60.0,
            parse_fn=lambda: snap,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.value, "Overview")
        self.assertEqual(result.matched_at, 3701.0)
        self.assertEqual(result.diagnostics["current_block_name"], "Overview")

    def test_selected_job_poll_uses_profile_defaults(self):
        profiles.STATE_READERS = profiles.StateReaderProfile(
            selected_job_log_poll_timeout_s=0.0,
            selected_job_log_poll_interval_s=0.25,
        )
        snap = _snapshot(
            now=102.0,
            selected=1,
            selected_ts=101.0,
            jobs=[(1, "Overview", 101.0)],
        )

        result = wait_for_selected_job_log(
            "Overview",
            command_started_at=100.0,
            parse_fn=lambda: snap,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.diagnostics["poll_interval_s"], 0.25)


if __name__ == "__main__":
    unittest.main()

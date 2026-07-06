"""
Unit tests for readers.api_reader (offline, no driver, no hardware).
=====================================================================
Exercises the flush-fire-poll retry/accept skeleton (`_flush_fire_poll`)
directly, plus the four public readers built on it (get_xy, get_jobs,
get_hardware_info, get_job_settings), using small hand-built fakes -- no
real CAM client, no threads, no wall-clock races. Every test scripts
exactly what a poll loop sees on each read via a property, so the
scenario is deterministic regardless of real timing.

This is the LC-09 hazard from the review, made concrete: LAS X delivers
read results by writing into a shared model with no request/response
correlation, so a delayed response to an *earlier* fire can still land
during a *later* fire's poll window. `get_job_settings` has a validate
hook that catches this (its payload carries `jobName`, a natural
correlating field, echoing the request); `get_xy`/`get_jobs`/
`get_hardware_info` do not (their payloads carry nothing that says which
fire they answer), so they accept a stale response as if it were fresh.

    python -m pytest test_api_reader.py
"""

import json
import math
import unittest
from types import SimpleNamespace

from navigator_expert.readers import api_reader as A


def _client(**extra):
    """A fake CAM client with the PyApiCommand dispatch channel
    _flush_fire_poll touches directly, plus whichever reader-specific
    channel(s) a test needs."""
    return SimpleNamespace(
        PyApiCommand=SimpleNamespace(
            Model=SimpleNamespace(Command=""),
            UpdateAwaitReceipt=lambda timeout: True,
        ),
        **extra,
    )


class TestFlushFirePollCore(unittest.TestCase):
    """The shared retry/accept skeleton, exercised directly with scripted
    flush/read callables -- no reader-shaped client needed for these two."""

    def test_without_a_validate_hook_a_stale_response_is_silently_accepted(self):
        """Reproduces the hazard for get_xy/get_jobs/get_hardware_info's
        shape: no validate hook means a straggler from an earlier, timed-out
        fire is indistinguishable from a genuinely fresh answer."""
        attempt = {"n": 0}

        def flush(client):
            attempt["n"] += 1

        def read(client):
            if attempt["n"] == 1:
                return None  # attempt 1 times out: nothing ever arrives
            return "stale-answer-from-fire-1"  # attempt 2's first read

        value = A._flush_fire_poll(
            _client(),
            command="Whatever",
            flush=flush,
            read=read,
            validate=None,
            timeout=0.02,
            poll_interval=0.001,
            max_retries=2,
        )
        self.assertEqual(value, "stale-answer-from-fire-1")

    def test_with_a_validate_hook_a_stale_response_is_rejected_and_the_fresh_one_is_accepted(self):
        """The same race, but with a correlating validate hook (mirrors
        get_job_settings' jobName check) -- proves the mechanism works when
        a correlating field exists to check against."""
        attempt = {"n": 0}
        reads_this_attempt = {"n": 0}

        def flush(client):
            attempt["n"] += 1
            reads_this_attempt["n"] = 0

        def read(client):
            if attempt["n"] == 1:
                return None
            reads_this_attempt["n"] += 1
            # First read of attempt 2 is fire 1's late, tagged answer;
            # the second is fire 2's genuine one.
            return {"fired_in_attempt": 1 if reads_this_attempt["n"] == 1 else 2}

        def validate(value, attempt_no):
            return A._ACCEPT if value["fired_in_attempt"] == attempt_no else A._STALE

        value = A._flush_fire_poll(
            _client(),
            command="Whatever",
            flush=flush,
            read=read,
            validate=validate,
            timeout=0.05,
            poll_interval=0.001,
            max_retries=2,
        )
        self.assertEqual(value, {"fired_in_attempt": 2})


class TestGetHardwareInfo(unittest.TestCase):
    def test_returns_parsed_json_on_success(self):
        payload = {"Microscope": {"name": "DM Manual-6"}, "LightSources": []}

        class _Model:
            @property
            def HWInfo(self):
                return json.dumps(payload)

            @HWInfo.setter
            def HWInfo(self, value):
                pass  # flush()'s sentinel reset; ignored, a fresh answer is always ready

        client = _client(PyApiGetConfocalHardwareInfo=SimpleNamespace(Model=_Model()))
        result = A.get_hardware_info(client, timeout=0.05, poll_interval=0.001, max_retries=1)
        self.assertEqual(result, payload)

    def test_has_no_correlating_field_so_a_stale_response_is_silently_accepted(self):
        stale_payload = {"Microscope": {"name": "STALE-FROM-AN-EARLIER-FIRE"}}

        class _Model:
            def __init__(self):
                self.resets = 0

            @property
            def HWInfo(self):
                return None if self.resets <= 1 else json.dumps(stale_payload)

            @HWInfo.setter
            def HWInfo(self, value):
                if value is None:  # flush()'s sentinel reset marks a new attempt
                    self.resets += 1

        client = _client(PyApiGetConfocalHardwareInfo=SimpleNamespace(Model=_Model()))
        result = A.get_hardware_info(client, timeout=0.02, poll_interval=0.001, max_retries=2)
        self.assertEqual(result, stale_payload)  # accepted -- nothing marks it as stale


class TestGetXY(unittest.TestCase):
    def test_returns_parsed_position_on_success(self):
        class _Model:
            @property
            def XPosition(self):
                return 0.00005  # 50 um, in meters

            @XPosition.setter
            def XPosition(self, value):
                pass

            @property
            def YPosition(self):
                return 0.00003  # 30 um

            @YPosition.setter
            def YPosition(self, value):
                pass

        client = _client(PyApiGetXY=SimpleNamespace(Model=_Model()))
        result = A.get_xy(client, timeout=0.05, poll_interval=0.001, max_retries=1)
        self.assertAlmostEqual(result["x_um"], 50.0)
        self.assertAlmostEqual(result["y_um"], 30.0)

    def test_has_no_correlating_field_so_a_stale_response_is_silently_accepted(self):
        """Concretely, this is the correct_backlash hazard (LC-09): its
        A -> B -> A move revisits the same coordinate, so a stale reading
        from the *first* visit to A can satisfy a check meant to confirm
        the *second* -- the values are identical, and get_xy has nothing to
        tell the two apart."""
        stale_x_um, stale_y_um = 100.0, 200.0

        class _Model:
            def __init__(self):
                self.resets = 0

            @property
            def XPosition(self):
                return float("nan") if self.resets <= 1 else stale_x_um / 1e6

            @XPosition.setter
            def XPosition(self, value):
                if isinstance(value, float) and math.isnan(value):
                    self.resets += 1

            @property
            def YPosition(self):
                return float("nan") if self.resets <= 1 else stale_y_um / 1e6

            @YPosition.setter
            def YPosition(self, value):
                pass  # attempt already counted by the XPosition reset in the same flush()

        client = _client(PyApiGetXY=SimpleNamespace(Model=_Model()))
        result = A.get_xy(client, timeout=0.02, poll_interval=0.001, max_retries=2)
        self.assertAlmostEqual(result["x_um"], stale_x_um)
        self.assertAlmostEqual(result["y_um"], stale_y_um)


class TestGetJobs(unittest.TestCase):
    def test_returns_parsed_list_on_success(self):
        jobs = [{"Name": "Overview", "IsSelected": True}, {"Name": "HiRes", "IsSelected": False}]

        class _Model:
            @property
            def Jobs(self):
                return json.dumps(jobs)

            @Jobs.setter
            def Jobs(self, value):
                pass

        client = _client(PyApiGetJobsInformation=SimpleNamespace(Model=_Model()))
        result = A.get_jobs(client, timeout=0.05, poll_interval=0.001, max_retries=1)
        self.assertEqual(result, jobs)

    def test_has_no_correlating_field_so_a_stale_response_is_silently_accepted(self):
        stale_jobs = [{"Name": "STALE-FROM-AN-EARLIER-FIRE", "IsSelected": True}]

        class _Model:
            def __init__(self):
                self.resets = 0

            @property
            def Jobs(self):
                return None if self.resets <= 1 else json.dumps(stale_jobs)

            @Jobs.setter
            def Jobs(self, value):
                if value is None:
                    self.resets += 1

        client = _client(PyApiGetJobsInformation=SimpleNamespace(Model=_Model()))
        result = A.get_jobs(client, timeout=0.02, poll_interval=0.001, max_retries=2)
        self.assertEqual(result, stale_jobs)


class TestGetJobSettingsCorrelationGuard(unittest.TestCase):
    """The one reader with a real correlating field: the response carries
    jobName, so its validate hook can tell a straggler from an earlier fire
    apart from the answer to the job actually being asked about now."""

    def test_rejects_a_stale_response_for_a_different_job_and_returns_the_fresh_one(self):
        stale = json.dumps({"jobName": "OLD_JOB", "imageSize": "100.0 um x 100.0 um"})
        fresh = json.dumps({"jobName": "NEW_JOB", "imageSize": "200.0 um x 200.0 um"})

        class _Model:
            def __init__(self):
                self.JobName = ""
                self.reads = 0

            @property
            def Settings(self):
                self.reads += 1
                return stale if self.reads == 1 else fresh

            @Settings.setter
            def Settings(self, value):
                pass

        client = _client(
            PyApiGetJobSettingsByName=SimpleNamespace(
                Model=_Model(), UpdateAwaitReceipt=lambda timeout: True
            )
        )
        result = A.get_job_settings(
            client, "NEW_JOB", timeout=0.05, poll_interval=0.001, max_retries=1
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["jobName"], "NEW_JOB")

    def test_all_responses_stale_falls_closed_to_none_not_a_wrong_value(self):
        stale = json.dumps({"jobName": "OLD_JOB"})

        class _Model:
            def __init__(self):
                self.JobName = ""

            @property
            def Settings(self):
                return stale

            @Settings.setter
            def Settings(self, value):
                pass

        client = _client(
            PyApiGetJobSettingsByName=SimpleNamespace(
                Model=_Model(), UpdateAwaitReceipt=lambda timeout: True
            )
        )
        result = A.get_job_settings(
            client, "NEW_JOB", timeout=0.02, poll_interval=0.001, max_retries=1
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()

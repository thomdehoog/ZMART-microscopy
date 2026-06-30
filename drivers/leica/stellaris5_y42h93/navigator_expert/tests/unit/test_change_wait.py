"""Unit tests for the alternating API/log change-wait reader.

Contract under test (see ``readers/change_wait.py``):

- ``read_change_baseline`` captures one pre-command reading per source; the API leg
  is bounded so a hung CAM call cannot block baseline capture forever.
- ``wait_for_change`` alternates API and log reads until one source observes
  a value that differs from ITS OWN baseline; cross-source comparison never
  signals a change (it only feeds the ``sources_agree`` report).
- The API leg runs through the in-flight-capped worker thread, so a hung API
  read degrades the wait to log-only instead of freezing the loop.
- None / NaN / empty / "Unknown" values are never accepted as a change.
- A log value only counts when its log timestamp is newer than the baseline.
- On timeout the result is ``unconfirmed`` - never a guessed value.
- Tolerance against an optional target is REPORTED, not enforced.
- All default tunables come from ``profiles.STATE_READERS`` (no hardcoding).
"""

import dataclasses
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from navigator_expert.config import profiles
from navigator_expert.readers import capabilities, change_wait, router


def _snapshot(now, *, block=None, block_ts=None, xy=None, xy_ts=None):
    return SimpleNamespace(
        now=now,
        current_block_name=block,
        current_block_ts=block_ts,
        current_block_id=None,
        selected_element=None,
        selected_ts=None,
        xy=xy,
        xy_ts=xy_ts,
    )


def _fast_profile(**overrides):
    values = dict(
        change_wait_timeout_s=0.5,
        change_wait_loop_interval_s=0.01,
        change_wait_api_retry_interval_s=0.02,
        change_wait_baseline_api_timeout_s=0.2,
    )
    values.update(overrides)
    return profiles.StateReaderProfile(**values)


class ChangeWaitTestCase(unittest.TestCase):
    def setUp(self):
        self._state_profile = profiles.STATE_READERS
        profiles.STATE_READERS = _fast_profile()
        self.client = object()
        self.addCleanup(self._restore_profile)

    def _restore_profile(self):
        profiles.STATE_READERS = self._state_profile


class TestProfileDefaults(unittest.TestCase):
    def test_change_wait_params_exist_with_documented_defaults(self):
        profile = profiles.StateReaderProfile()
        self.assertEqual(profile.change_wait_timeout_s, 10.0)
        self.assertEqual(profile.change_wait_loop_interval_s, 0.1)
        self.assertEqual(profile.change_wait_api_retry_interval_s, 0.25)
        self.assertEqual(profile.change_wait_xy_min_delta_um, 0.5)
        self.assertEqual(profile.change_wait_baseline_api_timeout_s, 2.0)


class TestReadBaseline(ChangeWaitTestCase):
    def test_captures_both_sources(self):
        api_value = {"x_um": 100.0, "y_um": 200.0}
        log_value = {"x_um": 100.0, "y_um": 200.0}
        snapshot = _snapshot(1000.0, xy_ts=999.5)
        with (
            patch.object(capabilities.api_reader, "get_xy", return_value=api_value),
            patch.object(change_wait.log_reader, "get_xy", return_value=log_value),
        ):
            baseline = change_wait.read_change_baseline(
                self.client, "xy", parse_fn=lambda: snapshot
            )
        self.assertEqual(baseline.datum, "xy")
        self.assertEqual(baseline.api.value, api_value)
        self.assertEqual(baseline.log.value, log_value)
        self.assertAlmostEqual(baseline.log.observed_at, 999.5)
        self.assertLessEqual(baseline.taken_at, time.time())

    def test_hung_api_is_bounded_and_reported(self):
        release = threading.Event()
        self.addCleanup(release.set)

        def hung_api(_client):
            release.wait(5.0)
            return {"x_um": 1.0, "y_um": 2.0}

        snapshot = _snapshot(1000.0)
        with (
            patch.object(capabilities.api_reader, "get_xy", side_effect=hung_api),
            patch.object(change_wait.log_reader, "get_xy", return_value={"x_um": 3.0, "y_um": 4.0}),
            patch.object(change_wait.log_reader, "ages", return_value={"xy": 0.1}),
        ):
            started = time.monotonic()
            baseline = change_wait.read_change_baseline(
                self.client, "xy", parse_fn=lambda: snapshot
            )
            elapsed = time.monotonic() - started
        self.assertIsNone(baseline.api)
        self.assertEqual(baseline.diagnostics["api_reason"], "api_timeout")
        self.assertIsNotNone(baseline.log)
        self.assertLess(elapsed, 2.0)

    def test_unknown_datum_rejected(self):
        with self.assertRaises(ValueError):
            change_wait.read_change_baseline(self.client, "nonsense")


class TestWaitForChangeSelectedJob(ChangeWaitTestCase):
    def test_log_change_wins_and_conflict_with_stale_api_is_reported(self):
        baseline_ts = time.time() - 5.0
        with patch.object(
            capabilities.api_reader, "get_selected_job", return_value={"Name": "Overview"}
        ):
            baseline = change_wait.read_change_baseline(
                self.client,
                "selected_job",
                parse_fn=lambda: _snapshot(time.time(), block="Overview", block_ts=baseline_ts),
            )

        calls = {"n": 0}

        def parse_fn():
            calls["n"] += 1
            now = time.time()
            if calls["n"] < 3:
                return _snapshot(now, block="Overview", block_ts=baseline_ts)
            return _snapshot(now, block="HiRes", block_ts=now)

        with patch.object(
            capabilities.api_reader, "get_selected_job", return_value={"Name": "Overview"}
        ):
            result = change_wait.wait_for_change(
                self.client, "selected_job", baseline, target="HiRes", parse_fn=parse_fn
            )

        self.assertTrue(result.success)
        self.assertEqual(result.outcome, "changed")
        self.assertEqual(result.source, "log")
        self.assertEqual(result.value["Name"], "HiRes")
        self.assertEqual(result.reason, "changed")
        self.assertTrue(result.matches_target)
        self.assertIsNone(result.within_tolerance)
        self.assertGreaterEqual(result.log_attempts, 3)
        self.assertGreaterEqual(result.api_attempts, 1)
        # the API still reported the pre-switch job: that is a conflict and
        # it must be visible, not buried.
        self.assertFalse(result.sources_agree)
        self.assertEqual(result.diagnostics["last_valid"]["api"]["key"], "Overview")

    def test_stale_log_line_cannot_signal_change(self):
        stale_ts = time.time() - 60.0
        baseline = change_wait.ChangeBaseline(
            datum="selected_job",
            taken_at=time.time(),
            api=None,
            log=router.Reading(
                value={"Name": "Overview"}, source="log", observed_at=stale_ts, age_s=60.0
            ),
            diagnostics={},
        )

        # a DIFFERENT job name, but on a log line OLDER than the baseline:
        # state leaked from a previous run must never confirm.
        def parse_fn():
            return _snapshot(time.time(), block="HiRes", block_ts=stale_ts - 10.0)

        with patch.object(capabilities.api_reader, "get_selected_job", return_value=None):
            result = change_wait.wait_for_change(
                self.client, "selected_job", baseline, parse_fn=parse_fn
            )
        self.assertFalse(result.success)
        self.assertEqual(result.outcome, "unconfirmed")
        self.assertEqual(result.reason, "timeout")
        self.assertEqual(
            result.diagnostics["last_reasons"]["log"],
            "observed_before_log_boundary",
        )

    def test_command_started_at_rejects_log_event_between_baseline_and_fire(self):
        baseline_time = time.time()
        command_started_at = baseline_time + 0.5
        between_time = baseline_time + 0.2
        baseline = change_wait.ChangeBaseline(
            datum="selected_job",
            taken_at=baseline_time,
            api=None,
            log=router.Reading(
                value={"Name": "Overview"}, source="log", observed_at=baseline_time - 0.1, age_s=0.1
            ),
            diagnostics={},
        )

        with patch.object(capabilities.api_reader, "get_selected_job", return_value=None):
            result = change_wait.wait_for_change(
                self.client,
                "selected_job",
                baseline,
                command_started_at=command_started_at,
                parse_fn=lambda: _snapshot(time.time(), block="HiRes", block_ts=between_time),
            )

        self.assertFalse(result.success)
        self.assertEqual(
            result.diagnostics["last_reasons"]["log"],
            "observed_before_log_boundary",
        )
        self.assertEqual(
            result.diagnostics["baseline"]["log_boundary"],
            command_started_at,
        )

    def test_early_command_started_at_cannot_weaken_log_boundary(self):
        baseline_time = time.time()
        command_started_at = baseline_time - 0.5
        after_command_before_baseline = baseline_time - 0.2
        baseline = change_wait.ChangeBaseline(
            datum="selected_job",
            taken_at=baseline_time,
            api=None,
            log=router.Reading(
                value={"Name": "Overview"}, source="log", observed_at=baseline_time - 1.0, age_s=1.0
            ),
            diagnostics={},
        )

        with patch.object(capabilities.api_reader, "get_selected_job", return_value=None):
            result = change_wait.wait_for_change(
                self.client,
                "selected_job",
                baseline,
                command_started_at=command_started_at,
                parse_fn=lambda: _snapshot(
                    time.time(),
                    block="HiRes",
                    block_ts=after_command_before_baseline,
                ),
            )

        self.assertFalse(result.success)
        self.assertEqual(
            result.diagnostics["last_reasons"]["log"],
            "observed_before_log_boundary",
        )
        self.assertEqual(
            result.diagnostics["baseline"]["log_boundary"],
            baseline_time,
        )

    def test_sources_agree_ignores_stale_log_observation(self):
        baseline_time = time.time()
        baseline = change_wait.ChangeBaseline(
            datum="selected_job",
            taken_at=baseline_time,
            api=router.Reading(
                value={"Name": "Overview"}, source="api", observed_at=baseline_time, age_s=0.0
            ),
            log=router.Reading(
                value={"Name": "Overview"}, source="log", observed_at=baseline_time - 1.0, age_s=1.0
            ),
            diagnostics={},
        )

        def api_selected(_client):
            time.sleep(0.03)
            return {"Name": "HiRes"}

        def parse_fn():
            return _snapshot(
                time.time(),
                block="HiRes",
                block_ts=baseline_time - 0.5,
            )

        with patch.object(capabilities.api_reader, "get_selected_job", side_effect=api_selected):
            result = change_wait.wait_for_change(
                self.client, "selected_job", baseline, target="HiRes", parse_fn=parse_fn
            )

        self.assertTrue(result.success)
        self.assertEqual(result.source, "api")
        self.assertIsNone(result.sources_agree)
        self.assertEqual(
            result.diagnostics["last_reasons"]["log"],
            "observed_before_log_boundary",
        )

    def test_cross_source_disagreement_alone_never_confirms(self):
        baseline_time = time.time()
        baseline = change_wait.ChangeBaseline(
            datum="selected_job",
            taken_at=baseline_time,
            api=router.Reading(
                value={"Name": "Overview"}, source="api", observed_at=baseline_time, age_s=0.0
            ),
            log=router.Reading(
                value={"Name": "HiRes"}, source="log", observed_at=baseline_time + 0.01, age_s=0.0
            ),
            diagnostics={},
        )

        with patch.object(
            capabilities.api_reader, "get_selected_job", return_value={"Name": "Overview"}
        ):
            result = change_wait.wait_for_change(
                self.client,
                "selected_job",
                baseline,
                parse_fn=lambda: _snapshot(
                    time.time(), block="HiRes", block_ts=baseline_time + 0.02
                ),
            )

        self.assertFalse(result.success)
        self.assertEqual(result.outcome, "unconfirmed")
        self.assertEqual(result.diagnostics["last_reasons"]["api"], "unchanged")
        self.assertEqual(result.diagnostics["last_reasons"]["log"], "unchanged")

    def test_unknown_and_empty_selected_jobs_never_confirm(self):
        readings = iter(
            [
                {"Name": "Unknown"},
                {"Name": ""},
                {"Name": "Overview"},
            ]
        )

        def api_selected(_client):
            try:
                return next(readings)
            except StopIteration:
                return {"Name": "Overview"}

        baseline = change_wait.ChangeBaseline(
            datum="selected_job",
            taken_at=time.time(),
            api=router.Reading(
                value={"Name": "Overview"}, source="api", observed_at=time.time(), age_s=0.0
            ),
            log=None,
            diagnostics={},
        )

        with patch.object(capabilities.api_reader, "get_selected_job", side_effect=api_selected):
            result = change_wait.wait_for_change(
                self.client, "selected_job", baseline, parse_fn=lambda: _snapshot(time.time())
            )

        self.assertFalse(result.success)
        self.assertEqual(result.outcome, "unconfirmed")

    def test_api_lag_then_converge_is_known_limitation(self):
        baseline_time = time.time()
        # API baseline is stale from a previous A->B command. If it converges
        # to B while we are waiting for a later B->C command, the API leg has
        # no event timestamp that lets this reader distinguish old convergence
        # from the current command's effect.
        baseline = change_wait.ChangeBaseline(
            datum="selected_job",
            taken_at=baseline_time,
            api=router.Reading(
                value={"Name": "A"}, source="api", observed_at=baseline_time, age_s=0.0
            ),
            log=router.Reading(
                value={"Name": "B"}, source="log", observed_at=baseline_time - 0.1, age_s=0.1
            ),
            diagnostics={},
        )

        def api_selected(_client):
            time.sleep(0.03)
            return {"Name": "B"}

        with patch.object(capabilities.api_reader, "get_selected_job", side_effect=api_selected):
            result = change_wait.wait_for_change(
                self.client,
                "selected_job",
                baseline,
                target="C",
                parse_fn=lambda: _snapshot(time.time(), block="B", block_ts=baseline_time + 0.01),
            )

        self.assertTrue(result.success)
        self.assertEqual(result.source, "api")
        self.assertFalse(result.matches_target)
        self.assertTrue(result.sources_agree)

    def test_wrong_baseline_datum_is_rejected_immediately(self):
        baseline = change_wait.ChangeBaseline(
            datum="xy", taken_at=time.time(), api=None, log=None, diagnostics={}
        )
        with self.assertRaises(ValueError):
            change_wait.wait_for_change(
                self.client, "selected_job", baseline, parse_fn=lambda: _snapshot(time.time())
            )

    def test_malformed_target_is_rejected_before_reads(self):
        baseline = change_wait.ChangeBaseline(
            datum="xy",
            taken_at=time.time(),
            api=router.Reading(
                value={"x_um": 1.0, "y_um": 2.0}, source="api", observed_at=time.time(), age_s=0.0
            ),
            log=None,
            diagnostics={},
        )
        with patch.object(capabilities.api_reader, "get_xy") as api:
            with self.assertRaises(ValueError):
                change_wait.wait_for_change(
                    self.client,
                    "xy",
                    baseline,
                    target=("not-a-number", 2.0),
                    parse_fn=lambda: _snapshot(time.time()),
                )
        api.assert_not_called()


class TestWaitForChangeXY(ChangeWaitTestCase):
    def _baseline(self, x=100.0, y=200.0):
        return change_wait.ChangeBaseline(
            datum="xy",
            taken_at=time.time(),
            api=router.Reading(
                value={"x_um": x, "y_um": y}, source="api", observed_at=time.time(), age_s=0.0
            ),
            log=None,
            diagnostics={},
        )

    def test_api_change_wins_when_log_is_silent(self):
        moved = {"x_um": 150.0, "y_um": 200.0}
        with (
            patch.object(capabilities.api_reader, "get_xy", return_value=moved),
            patch.object(change_wait.log_reader, "get_xy", return_value=None),
            patch.object(change_wait.log_reader, "ages", return_value={"xy": None}),
        ):
            result = change_wait.wait_for_change(
                self.client,
                "xy",
                self._baseline(),
                target=(150.0, 200.0),
                tolerance=1.0,
                parse_fn=lambda: _snapshot(time.time()),
            )
        self.assertTrue(result.success)
        self.assertEqual(result.source, "api")
        self.assertEqual(result.value, moved)
        self.assertTrue(result.within_tolerance)
        self.assertEqual(result.target_delta, 0.0)

    def test_tolerance_is_reported_not_enforced(self):
        moved = {"x_um": 150.0, "y_um": 200.0}
        with (
            patch.object(capabilities.api_reader, "get_xy", return_value=moved),
            patch.object(change_wait.log_reader, "get_xy", return_value=None),
            patch.object(change_wait.log_reader, "ages", return_value={"xy": None}),
        ):
            result = change_wait.wait_for_change(
                self.client,
                "xy",
                self._baseline(),
                target=(500.0, 500.0),
                tolerance=1.0,
                parse_fn=lambda: _snapshot(time.time()),
            )
        self.assertTrue(result.success)  # change accepted anyway
        self.assertFalse(result.within_tolerance)  # ... but honestly reported
        self.assertAlmostEqual(result.target_delta, 350.0)

    def test_log_xy_change_can_win(self):
        baseline_time = time.time()
        baseline = change_wait.ChangeBaseline(
            datum="xy",
            taken_at=baseline_time,
            api=None,
            log=router.Reading(
                value={"x_um": 100.0, "y_um": 200.0},
                source="log",
                observed_at=baseline_time - 0.1,
                age_s=0.1,
            ),
            diagnostics={},
        )
        moved = {"x_um": 102.0, "y_um": 200.0}

        with (
            patch.object(capabilities.api_reader, "get_xy", return_value=None),
            patch.object(change_wait.log_reader, "get_xy", return_value=moved),
        ):
            result = change_wait.wait_for_change(
                self.client,
                "xy",
                baseline,
                target=(102.0, 200.0),
                tolerance=0.2,
                parse_fn=lambda: _snapshot(time.time(), xy_ts=baseline_time + 0.1),
            )

        self.assertTrue(result.success)
        self.assertEqual(result.source, "log")
        self.assertEqual(result.value, moved)
        self.assertTrue(result.within_tolerance)

    def test_none_nan_and_unchanged_values_never_confirm(self):
        readings = iter(
            [
                None,
                {"x_um": float("nan"), "y_um": 200.0},
                {"x_um": 100.0, "y_um": 200.0},  # same as baseline
            ]
        )

        def api_xy(_client):
            try:
                return next(readings)
            except StopIteration:
                return {"x_um": 100.0, "y_um": 200.0}

        with (
            patch.object(capabilities.api_reader, "get_xy", side_effect=api_xy),
            patch.object(change_wait.log_reader, "get_xy", return_value=None),
            patch.object(change_wait.log_reader, "ages", return_value={"xy": None}),
        ):
            result = change_wait.wait_for_change(
                self.client, "xy", self._baseline(), parse_fn=lambda: _snapshot(time.time())
            )
        self.assertFalse(result.success)
        self.assertEqual(result.outcome, "unconfirmed")

    def test_min_delta_filters_jitter(self):
        profiles.STATE_READERS = _fast_profile(change_wait_xy_min_delta_um=0.5)
        jitter = {"x_um": 100.2, "y_um": 200.0}  # within min_delta
        with (
            patch.object(capabilities.api_reader, "get_xy", return_value=jitter),
            patch.object(change_wait.log_reader, "get_xy", return_value=None),
            patch.object(change_wait.log_reader, "ages", return_value={"xy": None}),
        ):
            result = change_wait.wait_for_change(
                self.client, "xy", self._baseline(), parse_fn=lambda: _snapshot(time.time())
            )
        self.assertFalse(result.success)

    def test_api_without_baseline_cannot_confirm(self):
        baseline = change_wait.ChangeBaseline(
            datum="xy", taken_at=time.time(), api=None, log=None, diagnostics={}
        )
        with (
            patch.object(
                capabilities.api_reader, "get_xy", return_value={"x_um": 999.0, "y_um": 999.0}
            ),
            patch.object(change_wait.log_reader, "get_xy", return_value=None),
            patch.object(change_wait.log_reader, "ages", return_value={"xy": None}),
        ):
            result = change_wait.wait_for_change(
                self.client, "xy", baseline, parse_fn=lambda: _snapshot(time.time())
            )
        self.assertFalse(result.success)
        self.assertEqual(result.diagnostics["last_reasons"]["api"], "no_baseline")


class TestHangImmunity(ChangeWaitTestCase):
    def test_hung_api_does_not_block_the_log_leg(self):
        release = threading.Event()
        self.addCleanup(release.set)

        def hung_api(_client):
            release.wait(10.0)
            return {"Name": "Overview"}

        baseline_ts = time.time() - 5.0
        baseline = change_wait.ChangeBaseline(
            datum="selected_job",
            taken_at=time.time(),
            api=None,
            log=router.Reading(
                value={"Name": "Overview"}, source="log", observed_at=baseline_ts, age_s=5.0
            ),
            diagnostics={},
        )
        calls = {"n": 0}

        def parse_fn():
            calls["n"] += 1
            now = time.time()
            if calls["n"] < 3:
                return _snapshot(now, block="Overview", block_ts=baseline_ts)
            return _snapshot(now, block="HiRes", block_ts=now)

        with patch.object(capabilities.api_reader, "get_selected_job", side_effect=hung_api):
            started = time.monotonic()
            result = change_wait.wait_for_change(
                self.client, "selected_job", baseline, parse_fn=parse_fn
            )
            elapsed = time.monotonic() - started

        self.assertTrue(result.success)
        self.assertEqual(result.source, "log")
        self.assertLess(elapsed, 0.5)  # log won long before any timeout
        self.assertTrue(result.diagnostics["api_pending_at_exit"])

    def test_api_leg_skipped_while_in_flight_cap_is_held(self):
        api_key = router._client_api_key(self.client)
        self.assertTrue(router._claim_api_read(api_key))
        self.addCleanup(router._release_api_read, api_key)

        baseline = change_wait.ChangeBaseline(
            datum="xy",
            taken_at=time.time(),
            api=router.Reading(
                value={"x_um": 1.0, "y_um": 2.0}, source="api", observed_at=time.time(), age_s=0.0
            ),
            log=None,
            diagnostics={},
        )
        with (
            patch.object(
                capabilities.api_reader, "get_xy", return_value={"x_um": 9.0, "y_um": 9.0}
            ) as api,
            patch.object(change_wait.log_reader, "get_xy", return_value=None),
            patch.object(change_wait.log_reader, "ages", return_value={"xy": None}),
        ):
            result = change_wait.wait_for_change(
                self.client, "xy", baseline, parse_fn=lambda: _snapshot(time.time())
            )
        self.assertFalse(result.success)
        self.assertEqual(result.api_attempts, 0)
        self.assertGreater(result.diagnostics["api_skips"], 0)
        api.assert_not_called()


class TestTimeoutAndReporting(ChangeWaitTestCase):
    def test_unconfirmed_after_profile_timeout(self):
        profiles.STATE_READERS = _fast_profile(change_wait_timeout_s=0.15)
        baseline = change_wait.ChangeBaseline(
            datum="xy",
            taken_at=time.time(),
            api=router.Reading(
                value={"x_um": 1.0, "y_um": 2.0}, source="api", observed_at=time.time(), age_s=0.0
            ),
            log=None,
            diagnostics={},
        )
        with (
            patch.object(
                capabilities.api_reader, "get_xy", return_value={"x_um": 1.0, "y_um": 2.0}
            ),
            patch.object(change_wait.log_reader, "get_xy", return_value=None),
            patch.object(change_wait.log_reader, "ages", return_value={"xy": None}),
        ):
            started = time.monotonic()
            result = change_wait.wait_for_change(
                self.client, "xy", baseline, parse_fn=lambda: _snapshot(time.time())
            )
            elapsed = time.monotonic() - started

        self.assertFalse(result.success)
        self.assertEqual(result.outcome, "unconfirmed")
        self.assertEqual(result.reason, "timeout")
        self.assertGreaterEqual(elapsed, 0.15)
        self.assertLess(elapsed, 1.0)
        # debugging surface: params, baselines, per-source last state, trace
        diag = result.diagnostics
        self.assertEqual(diag["params"]["timeout_s"], 0.15)
        self.assertIn("baseline", diag)
        self.assertIn("last_reasons", diag)
        self.assertGreater(len(diag["trace"]), 0)
        first = diag["trace"][0]
        for field in ("t_s", "source", "valid", "changed"):
            self.assertIn(field, first)

    def test_result_is_a_frozen_dataclass_with_elapsed(self):
        baseline = change_wait.ChangeBaseline(
            datum="xy", taken_at=time.time(), api=None, log=None, diagnostics={}
        )
        with (
            patch.object(capabilities.api_reader, "get_xy", return_value=None),
            patch.object(change_wait.log_reader, "get_xy", return_value=None),
            patch.object(change_wait.log_reader, "ages", return_value={"xy": None}),
        ):
            result = change_wait.wait_for_change(
                self.client, "xy", baseline, parse_fn=lambda: _snapshot(time.time())
            )
        self.assertGreater(result.elapsed_s, 0.0)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.success = True


if __name__ == "__main__":
    unittest.main()

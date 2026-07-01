"""Selected-job confirmation legs and the hybrid race (TDD).

The FIRST test below is the real-scope A->B->A restore hazard: the CAM API
selected-job readback can be persistently stale, so an API that already read
the target BEFORE the command is not a transition witness - it must never
confirm in hybrid mode, no matter how fast it answers. The log leg confirms
only on a post-command ``CurrentBlock`` event (``log_wait``).

Source policy lives in ONE place: ``select_job_confirm_legs``. ``api`` keeps
today's exact semantics (no admissibility gate - the API poll is the only
evidence), ``log`` keeps the measured log-confirm path, ``hybrid`` races both
with the admissibility gate on the api leg.
"""

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from navigator_expert import readers as readers
from navigator_expert.commands import confirm_select_job, confirmations
from navigator_expert.config import profiles
from navigator_expert.readers import log_wait


def _poll_result(success, value=None, reason="matched"):
    return log_wait.LogPollResult(
        success=success,
        value=value,
        matched_at=101.0 if success else None,
        elapsed_s=0.02,
        attempts=1,
        reason=reason,
        diagnostics={"last_reason": reason},
    )


class SelectJobCase(unittest.TestCase):
    def setUp(self):
        self._profile = profiles.STATE_READERS
        self.addCleanup(self._restore)

    def _restore(self):
        profiles.STATE_READERS = self._profile

    def _use(self, **kwargs):
        profiles.STATE_READERS = profiles.StateReaderProfile(**kwargs)


class TestHybridAdmissibility(SelectJobCase):
    def test_stale_api_equals_target_cannot_confirm(self):
        """A->B->A restore: api pre-command already read the target, the log
        produces no post-command event -> hybrid must NOT confirm."""
        self._use(
            selected_job_confirm_source="hybrid",
            selected_job_hybrid_budget_s=1.0,
            selected_job_log_confirm_timeout_s=0.05,
        )
        api_leg, log_leg, budget = confirm_select_job.select_job_confirm_legs(
            "AF Job",
            command_started_at=100.0,
            timeout=0.5,
            api_baseline_name="AF Job",
        )
        stale_jobs = [{"Name": "AF Job", "IsSelected": True}]
        with (
            patch.object(readers, "get_jobs", return_value=stale_jobs) as api_jobs,
            patch.object(
                confirm_select_job.log_wait,
                "wait_for_selected_job_log",
                return_value=_poll_result(False, reason="timeout"),
            ),
        ):
            api_outcome = api_leg(None)
            race = confirmations.race_confirmations(
                api_leg=lambda: api_leg(None),
                log_leg=log_leg,
                label="SelectJob 'AF Job'",
                budget_s=budget,
            )
            result = race()

        self.assertFalse(api_outcome["success"])
        self.assertEqual(api_outcome["reason"], "inadmissible_no_transition")
        api_jobs.assert_not_called()  # an inadmissible leg never polls
        self.assertFalse(result["success"])

    def test_missing_api_baseline_cannot_confirm_in_hybrid(self):
        """Hybrid API evidence must prove a transition. If the pre-command
        API baseline was unavailable, an API readback equal to the target is
        not admissible evidence."""
        self._use(
            selected_job_confirm_source="hybrid",
            selected_job_hybrid_budget_s=1.0,
            selected_job_log_confirm_timeout_s=0.05,
        )
        api_leg, log_leg, budget = confirm_select_job.select_job_confirm_legs(
            "AF Job",
            command_started_at=100.0,
            timeout=0.5,
            api_baseline_name=None,
        )
        stale_jobs = [{"Name": "AF Job", "IsSelected": True}]
        with (
            patch.object(readers, "get_jobs", return_value=stale_jobs) as api_jobs,
            patch.object(
                confirm_select_job.log_wait,
                "wait_for_selected_job_log",
                return_value=_poll_result(False, reason="timeout"),
            ),
        ):
            api_outcome = api_leg(None)
            race = confirmations.race_confirmations(
                api_leg=lambda: api_leg(None),
                log_leg=log_leg,
                label="SelectJob 'AF Job'",
                budget_s=budget,
            )
            result = race()

        self.assertFalse(api_outcome["success"])
        self.assertEqual(api_outcome["reason"], "inadmissible_no_baseline")
        api_jobs.assert_not_called()
        self.assertFalse(result["success"])

    def test_log_wins_while_api_stale(self):
        self._use(
            selected_job_confirm_source="hybrid",
            selected_job_hybrid_budget_s=2.0,
            selected_job_log_confirm_timeout_s=1.0,
        )
        api_leg, log_leg, budget = confirm_select_job.select_job_confirm_legs(
            "HiRes",
            command_started_at=100.0,
            timeout=0.3,
            poll_interval=0.01,
            api_baseline_name="AF Job",
        )
        stale_jobs = [{"Name": "AF Job", "IsSelected": True}]
        with (
            patch.object(readers, "get_jobs", return_value=stale_jobs),
            patch.object(
                confirm_select_job.log_wait,
                "wait_for_selected_job_log",
                return_value=_poll_result(True, value="HiRes"),
            ),
        ):
            race = confirmations.race_confirmations(
                api_leg=lambda: api_leg(None),
                log_leg=log_leg,
                label="SelectJob 'HiRes'",
                budget_s=budget,
            )
            result = race()
            # The race returns as soon as the log wins; keep the fake API
            # installed until the stale API leg finishes its bounded timeout.
            time.sleep(0.35)

        self.assertTrue(result["success"])
        messages = [entry["msg"] for entry in result["logs"]]
        self.assertTrue(any("confirmed by log leg" in m for m in messages))

    def test_api_wins_while_log_silent(self):
        self._use(
            selected_job_confirm_source="hybrid",
            selected_job_hybrid_budget_s=2.0,
            selected_job_log_confirm_timeout_s=0.05,
        )
        api_leg, log_leg, budget = confirm_select_job.select_job_confirm_legs(
            "HiRes",
            command_started_at=100.0,
            timeout=1.0,
            poll_interval=0.01,
            api_baseline_name="Overview",
        )
        switched = [{"Name": "HiRes", "IsSelected": True}]
        with (
            patch.object(readers, "get_jobs", return_value=switched),
            patch.object(
                confirm_select_job.log_wait,
                "wait_for_selected_job_log",
                return_value=_poll_result(False, reason="timeout"),
            ),
        ):
            race = confirmations.race_confirmations(
                api_leg=lambda: api_leg(None),
                log_leg=log_leg,
                label="SelectJob 'HiRes'",
                budget_s=budget,
            )
            result = race()

        self.assertTrue(result["success"])
        messages = [entry["msg"] for entry in result["logs"]]
        self.assertTrue(any("confirmed by api leg" in m for m in messages))


class TestDefaultPolicy(unittest.TestCase):
    def test_selected_job_confirmation_defaults_to_hybrid(self):
        """The api confirm is measured-wrong on the real scope and log-only
        is insufficient on the simulator; hybrid is the one default that
        fits both without environment detection (validated 2026-06-11)."""
        profile = profiles.StateReaderProfile()
        self.assertEqual(profile.selected_job_confirm_source, "hybrid")
        self.assertEqual(profile.selected_job_hybrid_budget_s, 6.0)


class TestLegsBuilder(SelectJobCase):
    def test_api_source_has_no_admissibility_gate(self):
        """Pure api mode keeps today's exact semantics: the API poll is the
        only evidence, even when the pre-command baseline equals the target
        (re-assert / write-current shape)."""
        self._use(selected_job_confirm_source="api")
        api_leg, log_leg, budget = confirm_select_job.select_job_confirm_legs(
            "AF Job",
            command_started_at=100.0,
            timeout=0.5,
            poll_interval=0.01,
            api_baseline_name="AF Job",
        )
        self.assertIsNone(log_leg)
        self.assertIsNone(budget)
        jobs = [{"Name": "AF Job", "IsSelected": True}]
        with patch.object(readers, "get_jobs", return_value=jobs):
            outcome = api_leg(None)
        self.assertTrue(outcome["success"])

    def test_log_source_builds_log_leg_only(self):
        self._use(
            selected_job_confirm_source="log",
            selected_job_log_confirm_timeout_s=0.25,
        )
        api_leg, log_leg, budget = confirm_select_job.select_job_confirm_legs(
            "HiRes", command_started_at=100.0
        )
        self.assertIsNone(api_leg)
        self.assertIsNone(budget)
        with (
            patch.object(
                confirm_select_job.log_wait,
                "wait_for_selected_job_log",
                return_value=_poll_result(True, value="HiRes"),
            ),
            patch.object(readers, "get_jobs") as api_jobs,
        ):
            outcome = log_leg()
        self.assertTrue(outcome["success"])
        self.assertEqual(outcome["source"], "log")
        api_jobs.assert_not_called()

    def test_log_leg_fails_closed_when_log_misses(self):
        self._use(
            selected_job_confirm_source="log",
            selected_job_log_confirm_timeout_s=0.25,
        )
        _, log_leg, _ = confirm_select_job.select_job_confirm_legs("HiRes", command_started_at=100.0)
        with patch.object(
            confirm_select_job.log_wait,
            "wait_for_selected_job_log",
            return_value=_poll_result(False, reason="timeout"),
        ):
            outcome = log_leg()
        self.assertFalse(outcome["success"])
        self.assertEqual(outcome["source"], "log")

    def test_hybrid_builds_both_legs_with_profile_budget(self):
        self._use(
            selected_job_confirm_source="hybrid",
            selected_job_hybrid_budget_s=4.5,
        )
        # Pass the confirm ceiling the wrapper binds in production
        # (SELECT_JOB.poll_timeout). Budget < ceiling, so it is not capped -
        # this exercises the profile-budget branch of min(budget, ceiling),
        # while test_hybrid_budget_is_capped_by_confirm_timeout covers the other.
        api_leg, log_leg, budget = confirm_select_job.select_job_confirm_legs(
            "HiRes", command_started_at=100.0, api_baseline_name="Overview", timeout=5.0
        )
        self.assertIsNotNone(api_leg)
        self.assertIsNotNone(log_leg)
        self.assertEqual(budget, 4.5)

    def test_hybrid_budget_is_capped_by_confirm_timeout(self):
        self._use(
            selected_job_confirm_source="hybrid",
            selected_job_hybrid_budget_s=6.0,
        )
        api_leg, log_leg, budget = confirm_select_job.select_job_confirm_legs(
            "HiRes",
            command_started_at=100.0,
            api_baseline_name="Overview",
            timeout=5.0,
        )
        self.assertIsNotNone(api_leg)
        self.assertIsNotNone(log_leg)
        self.assertEqual(budget, 5.0)

    def test_unknown_source_raises_before_firing(self):
        self._use(selected_job_confirm_source="nonsense")
        with self.assertRaises(ValueError):
            confirm_select_job.select_job_confirm_legs("HiRes", command_started_at=100.0)

    def test_refires_reuse_the_original_command_timestamp(self):
        self._use(
            selected_job_confirm_source="log",
            selected_job_log_confirm_timeout_s=0.25,
        )
        _, log_leg, _ = confirm_select_job.select_job_confirm_legs("HiRes", command_started_at=123.456)
        with patch.object(
            confirm_select_job.log_wait,
            "wait_for_selected_job_log",
            return_value=_poll_result(False, reason="timeout"),
        ) as poll:
            log_leg()
            log_leg()  # second dispatcher confirm attempt
        anchors = [call.kwargs["command_started_at"] for call in poll.call_args_list]
        self.assertEqual(anchors, [123.456, 123.456])


class TestPrepareSelectJob(SelectJobCase):
    def test_api_source_noop_proof_from_api(self):
        self._use(selected_job_confirm_source="api")
        jobs = [{"Name": "AF Job", "IsSelected": True}]
        with patch.object(readers, "get_jobs", return_value=jobs):
            noop, context = confirm_select_job.prepare_select_job(None, "AF Job")
        self.assertIsNotNone(noop)
        self.assertTrue(noop["success"])
        self.assertTrue(noop["confirmed"])
        self.assertEqual(context["api_baseline_name"], "AF Job")

    def test_hybrid_api_already_target_is_not_noop_proof(self):
        """The no-op edge: log stale/silent + api already reads target ->
        FIRE (and possibly time out later). Stale API must never suppress a
        real command, and the baseline records the inadmissibility."""
        self._use(selected_job_confirm_source="hybrid")
        jobs = [{"Name": "AF Job", "IsSelected": True}]
        with (
            patch.object(confirm_select_job, "_selected_job_name_from_log", return_value=None),
            patch.object(
                confirm_select_job, "_selected_job_api_baseline", return_value=("AF Job", jobs, "ok")
            ),
        ):
            noop, context = confirm_select_job.prepare_select_job(None, "AF Job")
        self.assertIsNone(noop)  # fires despite api==target
        self.assertEqual(context["api_baseline_name"], "AF Job")

    def test_hybrid_noop_proof_comes_from_log_state(self):
        self._use(selected_job_confirm_source="hybrid")
        jobs = [{"Name": "Overview", "IsSelected": True}]
        with (
            patch.object(readers, "get_jobs", return_value=jobs),
            patch.object(confirm_select_job, "_selected_job_name_from_log", return_value="AF Job"),
        ):
            noop, _ = confirm_select_job.prepare_select_job(None, "AF Job")
        self.assertIsNotNone(noop)
        self.assertTrue(noop["confirmed"])

    def test_log_source_keeps_log_state_noop(self):
        self._use(selected_job_confirm_source="log")
        jobs = [{"Name": "Overview", "IsSelected": True}]
        with (
            patch.object(readers, "get_jobs", return_value=jobs),
            patch.object(confirm_select_job, "_selected_job_name_from_log", return_value="AF Job"),
        ):
            noop, _ = confirm_select_job.prepare_select_job(None, "AF Job")
        self.assertIsNotNone(noop)

    def test_log_source_does_not_touch_api_when_log_has_no_noop(self):
        self._use(selected_job_confirm_source="log")
        with (
            patch.object(confirm_select_job, "_selected_job_name_from_log", return_value=None),
            patch.object(readers, "get_jobs") as api_jobs,
            patch.object(readers, "get_job_settings") as api_settings,
        ):
            noop, context = confirm_select_job.prepare_select_job(None, "AF Job")

        self.assertIsNone(noop)
        self.assertEqual(context["api_baseline_reason"], "not_attempted")
        api_jobs.assert_not_called()
        api_settings.assert_not_called()


if __name__ == "__main__":
    unittest.main()

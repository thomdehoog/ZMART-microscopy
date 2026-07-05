"""Unit tests for the confirmation race wrapper.

Contract under test (``commands/confirmations.race_confirmations``):

- Single-leg confirmations pass through UNCHANGED - the wrapper returns the
  leg itself, so existing command behavior is bit-identical (the dispatch
  contract ``() -> {"success": bool, "logs": [...]}`` is preserved).
- With two legs, the race returns when the first leg confirms; the loser is
  abandoned (the CAM read is non-cancellable, so abandonment - not
  cancellation - is the only honest option).
- Disagreement (one leg confirmed while the other had already failed) is
  reported as a warning log entry, never hidden.
- ``budget_s`` is mandatory for a dual-leg race and bounds it even when a
  leg hangs; budget exhaustion is fail-closed (``success=False``).
- The api leg respects the in-flight cap: if another API read is in flight
  on this client, the api leg is skipped (log-only race), not overlapped.
"""

import threading
import time
import unittest

from navigator_expert.commands import confirmations
from navigator_expert.readers import router


def _ok(msg="ok"):
    return {"success": True, "logs": [{"level": "info", "msg": msg}]}


def _fail(msg="fail"):
    return {"success": False, "logs": [{"level": "info", "msg": msg}]}


class TestSingleLegIdentity(unittest.TestCase):
    def test_api_only_returns_the_leg_unchanged(self):
        def leg():
            return _ok()

        self.assertIs(confirmations.race_confirmations(api_leg=leg), leg)

    def test_log_only_returns_the_leg_unchanged(self):
        def leg():
            return _ok()

        self.assertIs(confirmations.race_confirmations(log_leg=leg), leg)

    def test_no_legs_returns_none(self):
        self.assertIsNone(confirmations.race_confirmations())


class TestDualLegRace(unittest.TestCase):
    def test_dual_leg_requires_budget(self):
        with self.assertRaises(ValueError):
            confirmations.race_confirmations(api_leg=lambda: _ok(), log_leg=lambda: _ok())

    def test_log_wins_while_api_leg_blocked(self):
        release = threading.Event()
        self.addCleanup(release.set)

        def hung_api():
            release.wait(5.0)
            return _ok("api late")

        race = confirmations.race_confirmations(
            api_leg=hung_api,
            log_leg=lambda: _ok("log confirmed"),
            label="TestCmd",
            budget_s=3.0,
        )
        started = time.monotonic()
        result = race()
        elapsed = time.monotonic() - started

        self.assertTrue(result["success"])
        self.assertLess(elapsed, 1.0)
        messages = [entry["msg"] for entry in result["logs"]]
        self.assertTrue(any("confirmed by log leg" in m for m in messages))
        self.assertTrue(any("api leg still pending" in m for m in messages))

    def test_api_wins_and_log_disagreement_is_reported(self):
        log_done = threading.Event()

        def failing_log():
            try:
                return _fail("log saw nothing")
            finally:
                log_done.set()

        race = confirmations.race_confirmations(
            api_leg=lambda: (log_done.wait(2.0), _ok("api readback"))[1],
            log_leg=failing_log,
            label="TestCmd",
            budget_s=3.0,
        )
        result = race()
        self.assertTrue(result["success"])
        warnings = [entry["msg"] for entry in result["logs"] if entry["level"] == "warning"]
        self.assertTrue(any("log leg had not confirmed" in m for m in warnings))

    def test_both_fail_is_fail_closed_with_both_logs(self):
        race = confirmations.race_confirmations(
            api_leg=lambda: _fail("api no match"),
            log_leg=lambda: _fail("log no event"),
            label="TestCmd",
            budget_s=2.0,
        )
        result = race()
        self.assertFalse(result["success"])
        messages = [entry["msg"] for entry in result["logs"]]
        self.assertIn("api no match", messages)
        self.assertIn("log no event", messages)
        self.assertTrue(any("no confirmation leg" in m for m in messages))

    def test_budget_bounds_hung_legs(self):
        release = threading.Event()
        self.addCleanup(release.set)

        def hung():
            release.wait(10.0)
            return _ok()

        race = confirmations.race_confirmations(
            api_leg=hung,
            log_leg=hung,
            label="TestCmd",
            budget_s=0.3,
        )
        started = time.monotonic()
        result = race()
        elapsed = time.monotonic() - started

        self.assertFalse(result["success"])
        self.assertGreaterEqual(elapsed, 0.3)
        self.assertLess(elapsed, 2.0)
        messages = [entry["msg"] for entry in result["logs"]]
        self.assertTrue(any("budget" in m for m in messages))

    def test_leg_exception_is_a_failed_leg_not_a_crash(self):
        def broken_api():
            raise RuntimeError("CAM exploded")

        race = confirmations.race_confirmations(
            api_leg=broken_api,
            log_leg=lambda: _ok("log confirmed"),
            label="TestCmd",
            budget_s=2.0,
        )
        result = race()
        self.assertTrue(result["success"])

    def test_api_leg_skipped_while_cap_held(self):
        api_key = ("race-test-key",)
        self.assertTrue(router._claim_api_read(api_key))
        self.addCleanup(router._release_api_read, api_key)

        api_calls = []

        def api_leg():
            api_calls.append(1)
            return _ok("api confirmed")

        race = confirmations.race_confirmations(
            api_leg=api_leg,
            log_leg=lambda: _fail("log no event"),
            label="TestCmd",
            budget_s=1.0,
            api_key=api_key,
        )
        result = race()
        self.assertFalse(result["success"])
        self.assertEqual(api_calls, [])
        messages = [entry["msg"] for entry in result["logs"]]
        self.assertTrue(any("api read in flight" in m for m in messages))


if __name__ == "__main__":
    unittest.main()

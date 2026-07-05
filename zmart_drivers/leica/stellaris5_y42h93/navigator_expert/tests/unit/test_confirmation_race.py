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
- The race takes NO in-flight claim of its own (CF-01): the api leg's
  routed reads reach the client and claim the cap per raw CAM read, so
  single-flight is preserved against genuinely concurrent readers while
  the leg's own reads are never starved, and an expired race leaves no
  claim residue that could blank the next attempt's api leg (CF-05).
"""

import threading
import time
import unittest
from unittest.mock import patch

from navigator_expert import readers
from navigator_expert.commands import confirmations
from navigator_expert.config import profiles
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


class TestApiLegRoutedReads(unittest.TestCase):
    """CF-01/CF-05 contracts: the race takes no in-flight claim, so an api
    leg's routed reads reach the client while the race runs; the per-read
    cap still protects against genuinely concurrent readers; and an
    expired race leaves no claim residue blocking the next attempt."""

    def setUp(self):
        self._profile = profiles.STATE_READERS
        profiles.STATE_READERS = profiles.StateReaderProfile(jobs_timeout_s=0.5)
        self.addCleanup(self._restore)

    def _restore(self):
        profiles.STATE_READERS = self._profile

    @staticmethod
    def _make_api_leg(client, poll_window_s=1.5):
        """A poll loop of routed ``mode="api"`` reads, shaped like the real
        select_job api leg (each read claims the in-flight cap per raw
        CAM call inside the router)."""

        def api_leg():
            deadline = time.monotonic() + poll_window_s
            while time.monotonic() < deadline:
                jobs = readers.get_jobs(client, mode="api")
                for j in jobs or []:
                    if j.get("Name") == "HiRes" and j.get("IsSelected"):
                        return _ok("api readback")
                time.sleep(0.01)
            return _fail("api no match")

        return api_leg

    def _wait_claim_clear(self, api_key, timeout=2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with router._API_IN_FLIGHT_LOCK:
                if api_key not in router._API_IN_FLIGHT:
                    return
            time.sleep(0.01)

    def test_api_leg_routed_read_reaches_client_and_wins(self):
        """CF-01 regression at the race level: a routed ``mode="api"`` read
        performed inside the race must reach the raw CAM reader, and the
        api leg must be able to win when the log has no evidence."""
        client = object()
        raw_calls = []

        def raw_get_jobs(c, **kwargs):
            raw_calls.append(c)
            return [{"Name": "HiRes", "IsSelected": True}]

        with patch.object(router.api_reader, "get_jobs", side_effect=raw_get_jobs):
            race = confirmations.race_confirmations(
                api_leg=self._make_api_leg(client),
                log_leg=lambda: _fail("log no event"),
                label="TestCmd",
                budget_s=2.0,
            )
            result = race()

        self.assertTrue(result["success"])
        self.assertEqual(raw_calls, [client])
        messages = [entry["msg"] for entry in result["logs"]]
        self.assertTrue(any("confirmed by api leg" in m for m in messages))

    def test_concurrent_external_read_still_capped(self):
        """The protection the claim exists for: while another context holds
        this client's in-flight claim, the leg's routed reads must NOT
        reach the raw reader — and once the external read finishes, the
        leg proceeds instead of having been skipped for the whole race."""
        client = object()
        api_key = router._client_api_key(client)
        self.assertTrue(router._claim_api_read(api_key))
        self.addCleanup(router._release_api_read, api_key)

        raw_calls = []

        def raw_get_jobs(c, **kwargs):
            raw_calls.append(c)
            return [{"Name": "HiRes", "IsSelected": True}]

        raw_calls_while_held = []

        def release_later():
            time.sleep(0.2)
            raw_calls_while_held.extend(raw_calls)
            router._release_api_read(api_key)

        with patch.object(router.api_reader, "get_jobs", side_effect=raw_get_jobs):
            threading.Thread(target=release_later, daemon=True).start()
            race = confirmations.race_confirmations(
                api_leg=self._make_api_leg(client),
                log_leg=lambda: _fail("log no event"),
                label="TestCmd",
                budget_s=2.0,
            )
            result = race()

        self.assertEqual(raw_calls_while_held, [])  # capped while externally held
        self.assertTrue(result["success"])  # ...but the leg was deferred, not blanked
        self.assertEqual(raw_calls, [client])

    def test_expired_race_leaves_no_claim_blocking_the_next_attempt(self):
        """CF-05: a race that expires while its api leg is stuck in a slow
        raw CAM read must leave no in-flight claim once that read returns;
        the next attempt's api leg reads and confirms normally."""
        client = object()
        api_key = router._client_api_key(client)
        release = threading.Event()
        self.addCleanup(release.set)
        raw_calls = []

        def raw_get_jobs(c, **kwargs):
            raw_calls.append(c)
            if len(raw_calls) == 1:
                release.wait(5.0)  # the slow CAM read the first race abandons
            return [{"Name": "HiRes", "IsSelected": True}]

        with patch.object(router.api_reader, "get_jobs", side_effect=raw_get_jobs):
            first = confirmations.race_confirmations(
                api_leg=self._make_api_leg(client),
                log_leg=lambda: _fail("log no event"),
                label="TestCmd",
                budget_s=0.2,
            )
            self.assertFalse(first()["success"])  # expires while the read hangs

            release.set()  # the hung CAM read finally returns
            self._wait_claim_clear(api_key)
            with router._API_IN_FLIGHT_LOCK:
                self.assertNotIn(api_key, router._API_IN_FLIGHT)

            second = confirmations.race_confirmations(
                api_leg=self._make_api_leg(client),
                log_leg=lambda: _fail("log no event"),
                label="TestCmd",
                budget_s=2.0,
            )
            result = second()

        self.assertTrue(result["success"])
        messages = [entry["msg"] for entry in result["logs"]]
        self.assertTrue(any("confirmed by api leg" in m for m in messages))


if __name__ == "__main__":
    unittest.main()

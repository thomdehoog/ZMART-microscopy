"""
Tests for echo polling after UpdateAwaitReceipt.
=================================================
Option B fix: after UpdateAwaitReceipt returns (transport ACK), poll the
echo model waiting for it to settle. This catches errors that LAS X
populates asynchronously after the transport ACK.

The new function under test:
    ``_await_echo_result(client, timeout, poll_interval) -> bool``

Located in ``lasx.core``. Returns True if the echo settled, False on
timeout.

Settlement condition: ``Result != 0 (NotDefined)`` **OR** ``HasError is
True``.  Both must be checked because LAS X may set HasError without
changing Result from NotDefined — observed in error_discovery_v4 probe
D02 where UpdateSync returned True but the echo had HasError=True with
Result potentially still at 0.

These tests simulate the real-world race condition where the echo is
populated *after* UpdateAwaitReceipt returns, by using a threading.Timer
to set echo fields with a configurable delay.
"""

import time
import threading
import unittest
from unittest.mock import MagicMock, patch

import lasx.core
import lasx.errors


# =============================================================================
# Helpers
# =============================================================================

def make_echo(has_error=False, error="", result_code=1):
    """Create a mock PyApiCommandEcho.Model with given state."""
    echo = MagicMock()
    echo.HasError = has_error
    echo.Error = error
    echo.Result = result_code
    return echo


def make_client(echo=None, scan_status="eScanIdle"):
    """Create a mock LAS X client."""
    client = MagicMock()
    if echo is None:
        echo = make_echo()
    client.PyApiCommandEcho.Model = echo
    status_obj = MagicMock()
    status_obj.__str__ = MagicMock(return_value=scan_status)
    client.PyApiStatus.Model.ScanStatus = status_obj
    return client


def make_api_obj():
    """Create a mock API object."""
    api_obj = MagicMock()
    api_obj.Model = MagicMock()
    api_obj.UpdateAwaitReceipt = MagicMock(return_value=True)
    return api_obj


def _idle_pre_check():
    return {"success": True, "logs": []}


class DelayedEcho:
    """Simulates LAS X populating the echo model after a delay.

    After ``delay`` seconds, sets echo fields to the given values.
    This mimics the real race condition: UpdateAwaitReceipt returns
    immediately, but LAS X needs time to process and populate the echo.
    """

    def __init__(self, echo, delay, has_error=False, error="",
                 result_code=1):
        self.echo = echo
        self.delay = delay
        self.has_error = has_error
        self.error = error
        self.result_code = result_code
        self._timer = None

    def start(self):
        """Begin the delayed echo population."""
        self._timer = threading.Timer(self.delay, self._populate)
        self._timer.daemon = True
        self._timer.start()
        return self

    def _populate(self):
        self.echo.Result = self.result_code
        self.echo.HasError = self.has_error
        self.echo.Error = self.error

    def cancel(self):
        if self._timer:
            self._timer.cancel()


# =============================================================================
# 1. _await_echo_result — direct tests
# =============================================================================

class TestAwaitEchoResult(unittest.TestCase):
    """Test the echo polling function in isolation."""

    def test_echo_already_settled_success(self):
        """If Result is already != 0 (e.g. Success=1), return immediately."""
        echo = make_echo(result_code=1)  # Success
        client = make_client(echo)

        t0 = time.perf_counter()
        settled = lasx.core._await_echo_result(client, timeout=0.5,
                                               poll_interval=0.01)
        elapsed = time.perf_counter() - t0

        self.assertTrue(settled)
        self.assertLess(elapsed, 0.05, "Should return immediately, not poll")

    def test_echo_already_settled_failure(self):
        """If Result is already Failure (2), return immediately."""
        echo = make_echo(has_error=True, error="out of range",
                         result_code=2)
        client = make_client(echo)

        settled = lasx.core._await_echo_result(client, timeout=0.5,
                                               poll_interval=0.01)
        self.assertTrue(settled)

    def test_echo_settles_after_delay(self):
        """Echo starts at NotDefined (0), settles to Success after 50ms."""
        echo = make_echo(result_code=0)  # NotDefined — cleared state
        client = make_client(echo)

        delayed = DelayedEcho(echo, delay=0.05, result_code=1).start()
        try:
            t0 = time.perf_counter()
            settled = lasx.core._await_echo_result(client, timeout=0.5,
                                                   poll_interval=0.01)
            elapsed = time.perf_counter() - t0

            self.assertTrue(settled)
            self.assertGreaterEqual(elapsed, 0.04,
                                    "Should wait for echo to settle")
            self.assertLess(elapsed, 0.2,
                            "Should not wait full timeout")
        finally:
            delayed.cancel()

    def test_echo_settles_to_error(self):
        """Echo starts at NotDefined (0), settles to Failure after 30ms."""
        echo = make_echo(result_code=0)
        client = make_client(echo)

        delayed = DelayedEcho(echo, delay=0.03, has_error=True,
                              error="zoom out of range",
                              result_code=2).start()
        try:
            settled = lasx.core._await_echo_result(client, timeout=0.5,
                                                   poll_interval=0.01)
            self.assertTrue(settled)
            # Verify the error fields are now readable
            self.assertTrue(echo.HasError)
            self.assertEqual(echo.Error, "zoom out of range")
            self.assertEqual(echo.Result, 2)
        finally:
            delayed.cancel()

    def test_timeout_when_echo_never_settles(self):
        """Echo stays at NotDefined (0) — should timeout and return False."""
        echo = make_echo(result_code=0)
        client = make_client(echo)

        t0 = time.perf_counter()
        settled = lasx.core._await_echo_result(client, timeout=0.1,
                                               poll_interval=0.01)
        elapsed = time.perf_counter() - t0

        self.assertFalse(settled)
        self.assertGreaterEqual(elapsed, 0.09,
                                "Should wait for full timeout")
        self.assertLess(elapsed, 0.3,
                        "Should not overshoot timeout significantly")

    def test_poll_interval_respected(self):
        """Verify that polling doesn't spin faster than poll_interval."""
        echo = make_echo(result_code=0)
        client = make_client(echo)

        # Track how many times Result is read
        read_count = [0]
        original_result = 0

        def counting_result():
            read_count[0] += 1
            return original_result

        type(echo).Result = property(lambda self: counting_result())

        lasx.core._await_echo_result(client, timeout=0.1,
                                     poll_interval=0.02)

        # With 100ms timeout and 20ms interval, expect ~5-6 polls
        self.assertLessEqual(read_count[0], 10,
                             "Too many polls — interval not respected")
        self.assertGreaterEqual(read_count[0], 3,
                                "Too few polls — should poll multiple times")

    def test_not_defined_result_code_is_zero(self):
        """Confirm that result_code=0 with HasError=False is unsettled."""
        echo = make_echo(result_code=0, has_error=False)
        client = make_client(echo)

        # Should timeout: Result=0 AND HasError=False → not settled
        settled = lasx.core._await_echo_result(client, timeout=0.05,
                                               poll_interval=0.01)
        self.assertFalse(settled)

    def test_not_implemented_result_settles(self):
        """Result code 3 (NotImplemented) should count as settled."""
        echo = make_echo(result_code=0)
        client = make_client(echo)

        delayed = DelayedEcho(echo, delay=0.02, result_code=3).start()
        try:
            settled = lasx.core._await_echo_result(client, timeout=0.5,
                                                   poll_interval=0.01)
            self.assertTrue(settled)
        finally:
            delayed.cancel()

    def test_has_error_without_result_change_settles(self):
        """HasError=True with Result still at 0 should count as settled.

        Inspired by error_discovery_v4 probe D02: UpdateSync returned True
        but echo had HasError=True. We cannot assume Result changes from
        NotDefined (0) for every error — HasError alone must be sufficient
        to detect settlement.
        """
        echo = make_echo(result_code=0, has_error=False)
        client = make_client(echo)

        # After 30ms, LAS X sets HasError but leaves Result at 0
        def set_has_error_only():
            echo.HasError = True
            echo.Error = "CamCommandSetZoomByJobName invalid block identifier"
            # Result stays at 0 (NotDefined) — not changed by LAS X

        timer = threading.Timer(0.03, set_has_error_only)
        timer.daemon = True
        timer.start()

        try:
            t0 = time.perf_counter()
            settled = lasx.core._await_echo_result(client, timeout=0.5,
                                                   poll_interval=0.01)
            elapsed = time.perf_counter() - t0

            self.assertTrue(settled,
                            "HasError=True should settle even if Result=0")
            self.assertGreaterEqual(elapsed, 0.02)
            self.assertLess(elapsed, 0.2)
        finally:
            timer.cancel()

    def test_has_error_already_set_returns_immediately(self):
        """If HasError is already True at poll start, return immediately."""
        echo = make_echo(result_code=0, has_error=True,
                         error="some stale error")
        client = make_client(echo)

        t0 = time.perf_counter()
        settled = lasx.core._await_echo_result(client, timeout=0.5,
                                               poll_interval=0.01)
        elapsed = time.perf_counter() - t0

        self.assertTrue(settled)
        self.assertLess(elapsed, 0.05, "Should return immediately")


# =============================================================================
# 2. Integration with _fire_block — delayed errors now detected
# =============================================================================

class TestFireBlockWithEchoPoll(unittest.TestCase):
    """Verify that _fire_block catches errors that arrive late."""

    def _make_delayed_error_client(self, delay, error_msg, result_code=2):
        """Create a client where the echo error appears after a delay.

        Simulates: UpdateAwaitReceipt returns (transport ACK), then LAS X
        populates the echo after `delay` seconds.
        """
        echo = make_echo(result_code=0)  # Starts cleared (NotDefined)
        client = make_client(echo)

        # When fire clears the echo, reset to NotDefined
        def clear_echo(*args, **kwargs):
            echo.HasError = False
            echo.Error = ""
            echo.Result = 0

        # Patch the echo attribute setters to track clearing
        # (The real code sets these directly on the echo model)

        return client, echo, delay, error_msg, result_code

    def test_delayed_permanent_error_caught(self):
        """Error arriving 30ms after receipt should be caught by poll."""
        echo = make_echo(result_code=0)
        client = make_client(echo)
        api_obj = make_api_obj()

        # Simulate: after fire, echo stays at 0 for 30ms then shows error
        fire_called = [False]
        original_fire = lasx.core._fire_with_receipt

        def mock_fire(api_obj_arg, **kwargs):
            fire_called[0] = True
            # Start delayed error population
            DelayedEcho(echo, delay=0.03, has_error=True,
                        error="out of range", result_code=2).start()
            return True

        with patch.object(lasx.core, '_fire_with_receipt', side_effect=mock_fire):
            r = lasx.core._fire_block(
                client, api_obj, "Zoom -> 999",
                setup_fn=lambda m: None,
                pre_check_fn=_idle_pre_check,
                max_retries=0,
            )

        self.assertTrue(fire_called[0])
        self.assertFalse(r["success"],
                         "Delayed permanent error should be caught")
        self.assertIn("out of range", r["message"])

    def test_delayed_transient_error_retried(self):
        """Transient error arriving late should trigger retry."""
        echo = make_echo(result_code=0)
        client = make_client(echo)
        api_obj = make_api_obj()

        call_count = [0]

        def mock_fire(api_obj_arg, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: delayed transient error
                DelayedEcho(echo, delay=0.02, has_error=True,
                            error="block is being scanned",
                            result_code=2).start()
            else:
                # Second call: immediate success
                echo.HasError = False
                echo.Error = ""
                echo.Result = 1
            return True

        with patch.object(lasx.core, '_fire_with_receipt', side_effect=mock_fire):
            r = lasx.core._fire_block(
                client, api_obj, "Zoom -> 5",
                setup_fn=lambda m: None,
                pre_check_fn=_idle_pre_check,
                max_retries=2,
            )

        self.assertTrue(r["success"])
        self.assertEqual(r["attempts"], 2,
                         "Should have retried after transient error")

    def test_immediate_success_still_fast(self):
        """When echo settles immediately to Success, no unnecessary delay."""
        echo = make_echo(result_code=0)
        client = make_client(echo)
        api_obj = make_api_obj()

        def mock_fire(api_obj_arg, **kwargs):
            # Simulate: echo populated immediately (fast command)
            echo.Result = 1
            echo.HasError = False
            echo.Error = ""
            return True

        with patch.object(lasx.core, '_fire_with_receipt', side_effect=mock_fire):
            t0 = time.perf_counter()
            r = lasx.core._fire_block(
                client, api_obj, "Fast command",
                setup_fn=lambda m: None,
                pre_check_fn=_idle_pre_check,
                max_retries=0,
            )
            elapsed = time.perf_counter() - t0

        self.assertTrue(r["success"])
        self.assertLess(elapsed, 0.1,
                        "Immediate success should not add polling delay")

    def test_has_error_only_no_result_change_caught(self):
        """D02 scenario: HasError=True but Result stays at 0 (NotDefined).

        From error_discovery_v4 probe D02: firing with a stale model
        caused UpdateSync to return True, but the echo had HasError=True
        without necessarily changing Result. The poll must detect this
        via HasError, not just Result.
        """
        echo = make_echo(result_code=0)
        client = make_client(echo)
        api_obj = make_api_obj()

        def mock_fire(api_obj_arg, **kwargs):
            # LAS X sets HasError after 20ms but leaves Result at 0
            def set_error():
                echo.HasError = True
                echo.Error = "CamCommandSetZoomByJobName invalid block identifier"
                # Result stays at 0 — NOT changed

            timer = threading.Timer(0.02, set_error)
            timer.daemon = True
            timer.start()
            return True

        with patch.object(lasx.core, '_fire_with_receipt', side_effect=mock_fire):
            r = lasx.core._fire_block(
                client, api_obj, "Zoom stale model",
                setup_fn=lambda m: None,
                pre_check_fn=_idle_pre_check,
                max_retries=0,
            )

        self.assertFalse(r["success"],
                         "HasError=True with Result=0 should still be caught")
        self.assertIn("invalid block identifier", r["message"])

    def test_timeout_proceeds_without_error(self):
        """When echo never settles (stays NotDefined), proceed as success.

        The confirm step will catch any actual failures via readback.
        """
        echo = make_echo(result_code=0)
        client = make_client(echo)
        api_obj = make_api_obj()

        def mock_fire(api_obj_arg, **kwargs):
            # Echo stays at NotDefined — never populated
            return True

        with patch.object(lasx.core, '_fire_with_receipt', side_effect=mock_fire):
            r = lasx.core._fire_block(
                client, api_obj, "Slow command",
                setup_fn=lambda m: None,
                pre_check_fn=_idle_pre_check,
                max_retries=0,
            )

        # NotDefined (0) with no error → _check_api_error returns None → success
        # This is the current behavior preserved: if echo never populates,
        # we proceed and let the confirm step catch it via readback.
        self.assertTrue(r["success"])


# =============================================================================
# 3. Integration with confirm_and_fire — end-to-end
# =============================================================================

class TestConfirmAndFireWithEchoPoll(unittest.TestCase):
    """End-to-end: delayed errors detected before reaching confirm step."""

    def test_delayed_error_prevents_confirm(self):
        """Permanent error caught by poll should fail before confirm runs."""
        echo = make_echo(result_code=0)
        client = make_client(echo)
        api_obj = make_api_obj()
        confirm_fn = MagicMock(return_value={"success": True, "logs": []})

        def mock_fire(api_obj_arg, **kwargs):
            DelayedEcho(echo, delay=0.02, has_error=True,
                        error="out of range", result_code=2).start()
            return True

        with patch.object(lasx.core, '_fire_with_receipt', side_effect=mock_fire):
            r = lasx.core.confirm_and_fire(
                client, api_obj, "Zoom -> 999",
                setup_fn=lambda m: None,
                pre_check_fn=_idle_pre_check,
                confirm_fn=confirm_fn,
                max_retries=0,
                max_confirm_attempts=1,
            )

        self.assertFalse(r["success"])
        self.assertIn("out of range", r["message"])
        confirm_fn.assert_not_called()

    def test_delayed_success_reaches_confirm(self):
        """When echo settles to Success, confirm step runs normally."""
        echo = make_echo(result_code=0)
        client = make_client(echo)
        api_obj = make_api_obj()
        confirm_fn = MagicMock(return_value={"success": True, "logs": []})

        def mock_fire(api_obj_arg, **kwargs):
            DelayedEcho(echo, delay=0.02, result_code=1).start()
            return True

        with patch.object(lasx.core, '_fire_with_receipt', side_effect=mock_fire):
            r = lasx.core.confirm_and_fire(
                client, api_obj, "Zoom -> 5",
                setup_fn=lambda m: None,
                pre_check_fn=_idle_pre_check,
                confirm_fn=confirm_fn,
                max_retries=0,
                max_confirm_attempts=1,
            )

        self.assertTrue(r["success"])
        confirm_fn.assert_called_once()

    def test_warning_after_delay_treated_as_success(self):
        """Delayed warning (HasError with 'warning') should pass through."""
        echo = make_echo(result_code=0)
        client = make_client(echo)
        api_obj = make_api_obj()
        confirm_fn = MagicMock(return_value={"success": True, "logs": []})

        def mock_fire(api_obj_arg, **kwargs):
            DelayedEcho(echo, delay=0.02, has_error=True,
                        error="Warning: pinhole adjusted",
                        result_code=1).start()
            return True

        with patch.object(lasx.core, '_fire_with_receipt', side_effect=mock_fire):
            r = lasx.core.confirm_and_fire(
                client, api_obj, "SetPinhole",
                setup_fn=lambda m: None,
                pre_check_fn=_idle_pre_check,
                confirm_fn=confirm_fn,
                max_retries=0,
                max_confirm_attempts=1,
            )

        self.assertTrue(r["success"])
        confirm_fn.assert_called_once()


# =============================================================================
# 4. Timing instrumentation
# =============================================================================

class TestEchoPollTiming(unittest.TestCase):
    """Verify that echo poll time is captured in timing dict."""

    def test_poll_time_included_in_fire_timing(self):
        """The echo poll wait should be visible in fire_s or check_s."""
        echo = make_echo(result_code=0)
        client = make_client(echo)
        api_obj = make_api_obj()

        def mock_fire(api_obj_arg, **kwargs):
            DelayedEcho(echo, delay=0.05, result_code=1).start()
            return True

        with patch.object(lasx.core, '_fire_with_receipt', side_effect=mock_fire):
            r = lasx.core._fire_block(
                client, api_obj, "Test",
                setup_fn=lambda m: None,
                pre_check_fn=_idle_pre_check,
                max_retries=0,
            )

        self.assertTrue(r["success"])
        timing = r["timing"]
        # The poll time should appear somewhere — either fire_s or check_s
        # depends on implementation. Total should reflect the wait.
        total = timing["fire_s"] + timing["check_s"]
        self.assertGreaterEqual(total, 0.04,
                                "Timing should reflect echo poll wait")


# =============================================================================
# 5. Edge cases
# =============================================================================

class TestEchoPollEdgeCases(unittest.TestCase):

    def test_echo_result_read_exception_handled(self):
        """If reading echo.Result AND echo.HasError both raise, timeout."""
        echo = MagicMock()
        type(echo).Result = property(lambda self: (_ for _ in ()).throw(
            Exception("COM error")))
        type(echo).HasError = property(lambda self: (_ for _ in ()).throw(
            Exception("COM error")))
        echo.Error = ""
        client = make_client(echo)

        # Should timeout gracefully, not crash
        settled = lasx.core._await_echo_result(client, timeout=0.05,
                                               poll_interval=0.01)
        self.assertFalse(settled)

    def test_result_exception_but_has_error_readable(self):
        """If echo.Result raises but HasError is readable and True, settle."""
        echo = MagicMock()
        type(echo).Result = property(lambda self: (_ for _ in ()).throw(
            Exception("COM error")))
        echo.HasError = True
        echo.Error = "some error"
        client = make_client(echo)

        settled = lasx.core._await_echo_result(client, timeout=0.5,
                                               poll_interval=0.01)
        self.assertTrue(settled, "HasError=True should settle even if Result unreadable")

    def test_zero_timeout_returns_immediately(self):
        """Timeout=0 should check once and return."""
        echo = make_echo(result_code=0)
        client = make_client(echo)

        t0 = time.perf_counter()
        settled = lasx.core._await_echo_result(client, timeout=0,
                                               poll_interval=0.01)
        elapsed = time.perf_counter() - t0

        self.assertFalse(settled)
        self.assertLess(elapsed, 0.05)

    def test_echo_clears_before_poll_starts(self):
        """Verify the poll sees the cleared state (Result=0), not stale data.

        The fire step in _fire_block clears echo before calling
        _fire_with_receipt. The poll should see this cleared state.
        """
        echo = make_echo(result_code=1)  # Start with "stale" success
        client = make_client(echo)
        api_obj = make_api_obj()

        def mock_fire(api_obj_arg, **kwargs):
            # After fire, echo has been cleared to 0 by _fire_block
            # Then LAS X sets an error after 30ms
            DelayedEcho(echo, delay=0.03, has_error=True,
                        error="out of range", result_code=2).start()
            return True

        # Verify that _fire_block clears echo before fire, so the poll
        # doesn't immediately see the stale result_code=1
        with patch.object(lasx.core, '_fire_with_receipt', side_effect=mock_fire):
            r = lasx.core._fire_block(
                client, api_obj, "Test",
                setup_fn=lambda m: None,
                pre_check_fn=_idle_pre_check,
                max_retries=0,
            )

        # The fire_block clears Result to 0 at line 172, so the poll
        # should wait and then see the delayed error
        self.assertFalse(r["success"])
        self.assertIn("out of range", r["message"])


# =============================================================================
# 6. Mock behavioral test — proves the current bug exists
# =============================================================================

class TestCurrentBugDemonstration(unittest.TestCase):
    """Demonstrate the race condition that Option B fixes.

    These tests use the CURRENT code path (before the fix) to show that
    errors arriving after UpdateAwaitReceipt are missed.

    After implementing _await_echo_result, these tests should be updated:
    the ones marked 'bug' should start passing, proving the fix works.
    """

    def test_baseline_synchronous_error_detected(self):
        """Baseline: when the handler sets error synchronously during fire,
        the error IS detected (no race condition).

        This simulates a mock-like scenario where the handler runs inside
        UpdateAwaitReceipt and populates the echo before returning.
        """
        echo = make_echo(result_code=0)
        client = make_client(echo)
        api_obj = make_api_obj()

        def mock_fire(api_obj_arg, **kwargs):
            # Handler runs synchronously — sets error during fire
            echo.HasError = True
            echo.Error = "out of range"
            echo.Result = 2
            return True

        with patch.object(lasx.core, '_fire_with_receipt',
                          side_effect=mock_fire):
            r = lasx.core._fire_block(
                client, api_obj, "Zoom -> 999",
                setup_fn=lambda m: None,
                pre_check_fn=_idle_pre_check,
                max_retries=0,
            )

        self.assertFalse(r["success"],
                         "Synchronous errors should always be caught")

    def test_d02_stale_model_has_error_without_result(self):
        """Reproduce D02 from error_discovery_v4: fire with stale model.

        D02 showed: UpdateSync returned True, echo had HasError=True with
        error "CamCommandSetZoomByJobName invalid block identifier", but
        the probe was classified as SUCCESS_BUT_ERROR — meaning the
        command "succeeded" from the dispatch perspective but the echo
        error channel flagged an issue.

        With the poll fix, this should be detected as a failure.
        """
        echo = make_echo(result_code=0)
        client = make_client(echo)
        api_obj = make_api_obj()

        def mock_fire(api_obj_arg, **kwargs):
            # Simulate D02: echo populated with HasError after delay
            # Result may or may not change — test the HasError-only path
            def populate():
                echo.HasError = True
                echo.Error = ("CamCommandSetZoomByJobName "
                              "invalid block identifier")
                # Result stays at 0 — mimics D02 behavior

            timer = threading.Timer(0.02, populate)
            timer.daemon = True
            timer.start()
            return True

        with patch.object(lasx.core, '_fire_with_receipt',
                          side_effect=mock_fire):
            r = lasx.core._fire_block(
                client, api_obj, "D02 repro",
                setup_fn=lambda m: None,
                pre_check_fn=_idle_pre_check,
                max_retries=0,
            )

        self.assertFalse(r["success"])
        self.assertIn("invalid block identifier", r["message"])

    def test_bug_cleared_echo_looks_like_success(self):
        """BUG: echo cleared to NotDefined (0) with no error → false success.

        This is the race condition: _fire_block clears echo, fires via
        UpdateAwaitReceipt, then immediately checks. The echo is still
        in cleared state, so _check_api_error returns None (success).

        After the fix, this test should still pass because NotDefined
        with no error IS treated as success — the poll just gives LAS X
        more time to populate the echo before checking.
        """
        echo = make_echo(result_code=0, has_error=False, error="")
        client = make_client(echo)

        result = lasx.errors._check_api_error(client)
        self.assertIsNone(result,
                          "NotDefined (0) with no error → success (by design)")


if __name__ == "__main__":
    unittest.main()

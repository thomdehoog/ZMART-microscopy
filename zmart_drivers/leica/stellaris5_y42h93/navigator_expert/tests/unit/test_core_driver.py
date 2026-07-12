"""
Unit tests for the Navigator Expert driver core.
================================================
Offline mock-based tests - no hardware required.

Uses unittest.mock to simulate the LAS X API client and verify the
driver's internal logic: error classification, fire/retry flow,
confirmation polling, timing instrumentation, and set function wiring.

The tests exercise the current dispatch backbone, command profiles,
confirmation polling, and timing/result envelope contracts.

Usage::

    python test_unit.py            # run all
    python test_unit.py -v         # verbose
    python -m pytest test_unit.py  # via pytest
"""

import inspect
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, patch

import navigator_expert as drv
from navigator_expert import readers as readers
from navigator_expert.commands import (
    commands,
    confirm_select_job,
    confirmations,
    dispatch,
    errors,
    prechecks,
)
from navigator_expert.commands import errors as drv_errors
from navigator_expert.commands.confirmations import _readback
from navigator_expert.config import profiles
from navigator_expert.connection import session
from navigator_expert.motion import limits as drv_limits
from navigator_expert.utils import _safe_float

# =============================================================================
# Helpers - mock factory
# =============================================================================


def make_echo(has_error=False, error="", result_code=1):
    """Create a mock PyApiCommandEcho.Model with given state."""
    echo = MagicMock()
    echo.HasError = has_error
    echo.Error = error
    echo.Result = result_code
    return echo


def make_client(echo=None, scan_status="eScanIdle"):
    """Create a mock LAS X client with a permissive function-limits gate.

    The commands-layer gate fails closed for a never-handshaken client, so
    the factory installs a permissive in-memory state — these tests are
    about command mechanics, not limits (test_limits_adversarial.py owns
    those). Tests that need the fail-closed behavior use a fresh object.
    """
    from limits_fixtures import install_permissive_limits

    client = MagicMock()
    if echo is None:
        echo = make_echo()
    client.PyApiCommandEcho.Model = echo
    status_obj = MagicMock()
    status_obj.__str__ = MagicMock(return_value=scan_status)
    client.PyApiStatus.Model.ScanStatus = status_obj
    install_permissive_limits(client)
    return client


def make_api_obj():
    """Create a mock API object."""
    api_obj = MagicMock()
    api_obj.Model = MagicMock()
    api_obj.UpdateAsync = MagicMock()
    api_obj.UpdateAwaitReceipt = MagicMock(return_value=True)
    api_obj.UpdateSync = MagicMock(return_value=True)
    return api_obj


def _idle_pre_check():
    """Trivial pre-check that always succeeds (scanner idle)."""
    return {"success": True, "logs": []}


class TestLasxApiSessionProfile(unittest.TestCase):
    def test_configure_lasx_api_delay_uses_profile_value(self):
        class FakeLasxApi:
            class PyApiClient:
                DelayInMilliseconds = 0

        profile = profiles.LasxApiProfile(delay_ms=123)
        with patch.object(profiles, "LASX_API", profile):
            applied = session.configure_lasx_api_delay(FakeLasxApi)

        self.assertEqual(applied, 123)
        self.assertEqual(FakeLasxApi.PyApiClient.DelayInMilliseconds, 123)

    def test_configure_lasx_api_delay_accepts_explicit_override(self):
        class FakeLasxApi:
            class PyApiClient:
                DelayInMilliseconds = 0

        applied = session.configure_lasx_api_delay(FakeLasxApi, delay_ms=0)

        self.assertEqual(applied, 0)
        self.assertEqual(FakeLasxApi.PyApiClient.DelayInMilliseconds, 0)

    def test_configure_lasx_api_delay_supports_connector_module_shape(self):
        class FakeConnector:
            class LasxApiClientPyModel:
                class PyApiClient:
                    DelayInMilliseconds = 0

        applied = session.configure_lasx_api_delay(FakeConnector, delay_ms=250)

        self.assertEqual(applied, 250)
        self.assertEqual(
            FakeConnector.LasxApiClientPyModel.PyApiClient.DelayInMilliseconds,
            250,
        )

    def test_configure_lasx_api_delay_fails_when_property_missing(self):
        class FakeLasxApi:
            pass

        with self.assertRaisesRegex(RuntimeError, "PyApiClient"):
            session.configure_lasx_api_delay(FakeLasxApi, delay_ms=250)


def _make_v6_timing(**kw):
    """Helper to build a driver timing dict."""
    d = {
        "pre_check_s": 0,
        "setup_s": 0,
        "fire_s": 0,
        "check_s": 0,
        "confirm_s": 0,
        "total_s": 0,
        "attempts": 1,
        "confirm_attempts": 0,
        "method": "async",
    }
    d.update(kw)
    return d


def _make_v6_result(success=True, msg="OK", **extra):
    """Helper to build a driver result dict."""
    r = {
        "success": success,
        "confirmed": True if success else None,
        "message": msg,
        "timing": _make_v6_timing(),
        "logs": [],
    }
    r.update(extra)
    return r


# =============================================================================
# 1. _check_api_error
# =============================================================================


class TestCheckApiError(unittest.TestCase):
    def test_success_result_1(self):
        client = make_client(make_echo(has_error=False, result_code=1))
        self.assertIsNone(drv_errors._check_api_error(client))

    def test_not_defined_no_error(self):
        client = make_client(make_echo(has_error=False, result_code=0))
        self.assertIsNone(drv_errors._check_api_error(client))

    def test_warning_treated_as_success(self):
        client = make_client(
            make_echo(has_error=True, error="Warning on command: pinhole adjusted", result_code=1)
        )
        self.assertIsNone(drv_errors._check_api_error(client))

    def test_warning_case_insensitive(self):
        client = make_client(
            make_echo(has_error=True, error="WARNING: value clamped", result_code=2)
        )
        self.assertIsNone(drv_errors._check_api_error(client))

    def test_error_result_failure(self):
        client = make_client(make_echo(has_error=True, error="Zoom out of range", result_code=2))
        err = drv_errors._check_api_error(client)
        self.assertIsNotNone(err)
        self.assertEqual(err["error"], "Zoom out of range")
        self.assertEqual(err["result"], "Failure")
        self.assertEqual(err["result_code"], 2)

    def test_not_implemented(self):
        client = make_client(make_echo(has_error=False, error="", result_code=3))
        err = drv_errors._check_api_error(client)
        self.assertIsNotNone(err)
        self.assertEqual(err["result"], "NotImplemented")
        self.assertIn("not implemented", err["error"].lower())

    def test_not_implemented_with_message(self):
        client = make_client(make_echo(has_error=True, error="Custom not impl msg", result_code=3))
        err = drv_errors._check_api_error(client)
        self.assertEqual(err["error"], "Custom not impl msg")

    def test_has_error_no_warning(self):
        client = make_client(make_echo(has_error=True, error="Something broke", result_code=1))
        err = drv_errors._check_api_error(client)
        self.assertIsNotNone(err)
        self.assertEqual(err["error"], "Something broke")

    def test_result_enum_exception(self):
        echo = MagicMock()
        echo.HasError = True
        echo.Error = "Some error"
        type(echo).Result = PropertyMock(side_effect=Exception("COM error"))
        client = MagicMock()
        client.PyApiCommandEcho.Model = echo
        err = drv_errors._check_api_error(client)
        self.assertIsNotNone(err)
        self.assertEqual(err["result"], "Unknown")


# =============================================================================
# 2. _default_error_check adapter
# =============================================================================


class TestDefaultErrorCheck(unittest.TestCase):
    def test_success_shape(self):
        client = make_client(make_echo(has_error=False, result_code=1))
        result = drv_errors._default_error_check(client)
        self.assertTrue(result["success"])
        self.assertIsNone(result["error"])
        self.assertIsNone(result["transient"])
        self.assertIsInstance(result["logs"], list)

    def test_permanent_error_shape(self):
        client = make_client(make_echo(has_error=True, error="out of range", result_code=2))
        result = drv_errors._default_error_check(client)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "out of range")
        self.assertFalse(result["transient"])
        self.assertGreater(len(result["logs"]), 0)

    def test_transient_error_shape(self):
        client = make_client(
            make_echo(has_error=True, error="block is being scanned", result_code=2)
        )
        result = drv_errors._default_error_check(client)
        self.assertFalse(result["success"])
        self.assertTrue(result["transient"])


# =============================================================================
# 3. confirm_and_fire - core flow
# =============================================================================


class TestConfirmAndFire(unittest.TestCase):
    def test_success(self):
        client = make_client()
        api_obj = make_api_obj()
        with patch.object(errors, "_check_api_error", return_value=None):
            r = dispatch.confirm_and_fire(
                client,
                api_obj,
                "Test",
                setup_fn=lambda m: setattr(m, "X", 1),
                max_retries=0,
                pre_check_fn=_idle_pre_check,
            )
        self.assertTrue(r["success"])
        self.assertEqual(r["message"], "Test")
        self.assertIn("logs", r)
        api_obj.UpdateAwaitReceipt.assert_called_once()

    def test_timing_dict_structure(self):
        client = make_client()
        api_obj = make_api_obj()
        with patch.object(errors, "_check_api_error", return_value=None):
            r = dispatch.confirm_and_fire(
                client, api_obj, "Test", max_retries=0, pre_check_fn=_idle_pre_check
            )
        t = r["timing"]
        for key in (
            "pre_check_s",
            "setup_s",
            "fire_s",
            "check_s",
            "confirm_s",
            "total_s",
            "attempts",
            "confirm_attempts",
            "method",
        ):
            self.assertIn(key, t, f"Missing timing key: {key}")
        self.assertEqual(t["method"], "async")
        self.assertEqual(t["attempts"], 1)
        self.assertEqual(t["confirm_attempts"], 0)

    def test_permanent_error_no_retry(self):
        client = make_client()
        api_obj = make_api_obj()
        perm_error = {"error": "out of range", "result": "Failure", "result_code": 2}
        with patch.object(errors, "_check_api_error", return_value=perm_error):
            r = dispatch.confirm_and_fire(
                client,
                api_obj,
                "Zoom -> 999",
                max_retries=5,
                pre_check_fn=_idle_pre_check,
                error_check_fn=lambda: errors._default_error_check(client),
            )
        self.assertFalse(r["success"])
        self.assertIn("out of range", r["message"])
        self.assertEqual(r["timing"]["attempts"], 1)

    def test_transient_error_retries(self):
        client = make_client()
        api_obj = make_api_obj()
        trans_error = {"error": "block is being scanned", "result": "Failure", "result_code": 2}
        with patch.object(errors, "_check_api_error", return_value=trans_error):
            r = dispatch.confirm_and_fire(
                client,
                api_obj,
                "Zoom -> 5",
                max_retries=2,
                pre_check_fn=_idle_pre_check,
                error_check_fn=lambda: errors._default_error_check(client),
            )
        self.assertFalse(r["success"])
        self.assertIn("being scanned", r["message"])
        self.assertEqual(r["timing"]["attempts"], 3)

    def test_transient_then_success(self):
        client = make_client()
        api_obj = make_api_obj()
        trans_error = {"error": "block is being scanned", "result": "Failure", "result_code": 2}
        call_count = [0]

        def mock_check(c):
            call_count[0] += 1
            return trans_error if call_count[0] == 1 else None

        with patch.object(errors, "_check_api_error", side_effect=mock_check):
            r = dispatch.confirm_and_fire(
                client,
                api_obj,
                "Zoom -> 5",
                max_retries=3,
                pre_check_fn=_idle_pre_check,
                error_check_fn=lambda: errors._default_error_check(client),
            )
        self.assertTrue(r["success"])
        self.assertEqual(r["timing"]["attempts"], 2)

    def test_no_retry_on_zero(self):
        client = make_client()
        api_obj = make_api_obj()
        trans_error = {"error": "busy", "result": "Failure", "result_code": 2}
        with patch.object(errors, "_check_api_error", return_value=trans_error):
            r = dispatch.confirm_and_fire(
                client,
                api_obj,
                "Test",
                max_retries=0,
                pre_check_fn=_idle_pre_check,
                error_check_fn=lambda: errors._default_error_check(client),
            )
        self.assertFalse(r["success"])
        self.assertEqual(r["timing"]["attempts"], 1)

    def test_setup_fn_called_every_attempt(self):
        client = make_client()
        api_obj = make_api_obj()
        setup_calls = []

        def setup(m):
            setup_calls.append(1)

        trans_error = {"error": "busy", "result": "Failure", "result_code": 2}
        call_count = [0]

        def mock_check(c):
            call_count[0] += 1
            return trans_error if call_count[0] <= 2 else None

        with patch.object(errors, "_check_api_error", side_effect=mock_check):
            dispatch.confirm_and_fire(
                client,
                api_obj,
                "Test",
                setup_fn=setup,
                max_retries=3,
                pre_check_fn=_idle_pre_check,
                error_check_fn=lambda: errors._default_error_check(client),
            )
        self.assertEqual(len(setup_calls), 3)

    def test_setup_fn_exception(self):
        client = make_client()
        api_obj = make_api_obj()

        def bad_setup(m):
            raise ValueError("bad value")

        r = dispatch.confirm_and_fire(
            client, api_obj, "Test", setup_fn=bad_setup, max_retries=0, pre_check_fn=_idle_pre_check
        )
        self.assertFalse(r["success"])
        self.assertIn("Setup exception", r["message"])

    def test_no_setup_fn(self):
        client = make_client()
        api_obj = make_api_obj()
        with patch.object(errors, "_check_api_error", return_value=None):
            r = dispatch.confirm_and_fire(
                client, api_obj, "Test", setup_fn=None, max_retries=0, pre_check_fn=_idle_pre_check
            )
        self.assertTrue(r["success"])

    def test_pre_check_failure_stops(self):
        """A pre_check_fn that returns failure stops the pipeline."""
        client = make_client()
        api_obj = make_api_obj()

        def failing_pre_check():
            return {"success": False, "logs": []}

        r = dispatch.confirm_and_fire(
            client, api_obj, "Test", max_retries=0, pre_check_fn=failing_pre_check
        )
        self.assertFalse(r["success"])
        self.assertIn("Pre-check failed", r["message"])

    def test_confirmed_key_present(self):
        client = make_client()
        api_obj = make_api_obj()
        with patch.object(errors, "_check_api_error", return_value=None):
            r = dispatch.confirm_and_fire(
                client, api_obj, "Test", max_retries=0, pre_check_fn=_idle_pre_check
            )
        self.assertIn("confirmed", r)
        self.assertIsNone(r["confirmed"])


# =============================================================================
# 3b. Retry backoff - escalating and fixed delays
# =============================================================================


class TestTransientRetry(unittest.TestCase):
    """Transient retries are immediate, and profile policy flows through _dispatch.

    The fire-block tests call _fire_block directly (not confirm_and_fire) to
    avoid echo poll sleeps. The error_check_fn is injected directly,
    bypassing _await_echo_result entirely.
    """

    def test_transient_retries_are_immediate(self):
        """The fire block never sleeps between transient error retries."""
        client = make_client()
        api_obj = make_api_obj()
        sleep_calls = []

        with (
            patch(
                "navigator_expert.commands.dispatch.time.sleep",
                # patching dispatch.time.sleep rebinds the STDLIB time.sleep;
                # leftover daemon threads (confirmation-race legs from earlier
                # tests) also call it, so record main-thread sleeps only
                side_effect=lambda s: (
                    sleep_calls.append(s)
                    if threading.current_thread() is threading.main_thread()
                    else None
                ),
            ),
            patch.object(dispatch, "_fire_with_receipt", return_value=True),
            patch.object(dispatch, "_await_echo_result", return_value=True),
        ):
            r = dispatch._fire_block(
                client,
                api_obj,
                "Test",
                error_check_fn=lambda: {
                    "success": False,
                    "transient": True,
                    "error": "block is being scanned",
                    "logs": [],
                },
                max_retries=3,
                pre_check_fn=_idle_pre_check,
            )

        self.assertFalse(r["success"])
        self.assertEqual(r["attempts"], 4)
        self.assertEqual(sleep_calls, [])

    def test_profile_confirmation_policy_passed_through_dispatch(self):
        """_dispatch passes the profile's readback retry policy."""
        client = make_client()
        api_obj = make_api_obj()

        from navigator_expert.config.profiles import CommandProfile

        profile = CommandProfile(
            refire_on_unconfirmed=False,
        )

        with patch.object(
            commands,
            "confirm_and_fire",
            return_value={
                "success": True,
                "confirmed": None,
                "message": "ok",
                "timing": {},
                "logs": [],
            },
        ) as mock_caf:
            commands._dispatch(client, api_obj, "Test", profile, setup_fn=lambda m: None)

        _, kwargs = mock_caf.call_args
        self.assertFalse(kwargs["refire_on_unconfirmed"])

    def test_default_setting_and_acquire_profiles_encode_retry_policy(self):
        """Uniform posture; acquisition is the one command that never re-sends."""
        # Settings inherit the uniform posture: 3 poll windows, re-fire,
        # unconfirmed-not-fail, the shared poll window.
        self.assertEqual(profiles.ZOOM.max_confirm_attempts, 3)
        self.assertEqual(profiles.ZOOM.confirm_poll_s, profiles.CONFIRM_POLL_S)
        self.assertTrue(profiles.ZOOM.refire_on_unconfirmed)
        self.assertTrue(profiles.ZOOM.success_on_unconfirmed)

        # OBJECTIVE and MOVE_Z used to deviate (single attempt / hard-fail);
        # they now match the uniform posture.
        self.assertEqual(profiles.OBJECTIVE.max_confirm_attempts, 3)
        self.assertEqual(profiles.OBJECTIVE.confirm_poll_s, profiles.CONFIRM_POLL_S)
        self.assertTrue(profiles.OBJECTIVE.success_on_unconfirmed)
        self.assertEqual(profiles.MOVE_Z.max_confirm_attempts, 3)
        self.assertTrue(profiles.MOVE_Z.success_on_unconfirmed)
        self.assertTrue(profiles.MOVE_XY.refire_on_unconfirmed)

        # ACQUIRE is the sole deviation: never re-sends on EITHER axis, but
        # still returns unconfirmed rather than hard-failing.
        self.assertEqual(profiles.ACQUIRE.max_retries, 0)
        self.assertEqual(profiles.ACQUIRE.max_confirm_attempts, 1)
        self.assertFalse(profiles.ACQUIRE.refire_on_unconfirmed)
        self.assertTrue(profiles.ACQUIRE.success_on_unconfirmed)
        self.assertEqual(profiles.ACQUIRE.start_timeout, 15.0)

        signature = inspect.signature(confirmations.confirm_acquire)
        self.assertEqual(
            signature.parameters["start_timeout"].default,
            profiles.ACQUIRE.start_timeout,
        )
        self.assertEqual(
            signature.parameters["heartbeat_interval"].default,
            profiles.ACQUIRE.heartbeat_interval,
        )
        self.assertEqual(
            signature.parameters["poll_interval"].default,
            profiles.ACQUIRE.poll_interval,
        )

        # select_job is the uniform 3x3, not an outlier: no bespoke poll_timeout;
        # the per-attempt window is the shared confirm_poll_s (CONFIRM_POLL_S),
        # over max_confirm_attempts attempts, re-fire between.
        self.assertIsNone(profiles.SELECT_JOB.poll_timeout)
        self.assertEqual(profiles.SELECT_JOB.confirm_poll_s, profiles.CONFIRM_POLL_S)
        self.assertEqual(profiles.SELECT_JOB.max_confirm_attempts, 3)


class TestCommandProfileGuard(unittest.TestCase):
    """__post_init__ rejects field combinations the dispatcher cannot honour."""

    def test_async_requires_no_error_check(self):
        # Async fire blanks the echo, so a live echo-based error check would
        # report a meaningless success.
        with self.assertRaises(ValueError):
            profiles.CommandProfile(fire_async=True)  # error_check_fn defaults live

    def test_async_with_null_error_check_is_allowed(self):
        p = profiles.CommandProfile(fire_async=True, error_check_fn=None)
        self.assertTrue(p.fire_async)
        self.assertIsNone(p.error_check_fn)

    def test_single_confirm_attempt_forbids_refire(self):
        # One window has no 'next attempt' for a re-fire to precede.
        with self.assertRaises(ValueError):
            profiles.CommandProfile(max_confirm_attempts=1)  # refire defaults True

    def test_single_confirm_attempt_without_refire_is_allowed(self):
        p = profiles.CommandProfile(max_confirm_attempts=1, refire_on_unconfirmed=False)
        self.assertEqual(p.max_confirm_attempts, 1)
        self.assertFalse(p.refire_on_unconfirmed)

    def test_every_shipped_profile_is_coherent(self):
        # Importing profiles constructs every module-level profile; the guard
        # must reject none of them. Assert they are all built and typed.
        shipped = [
            profiles.ZOOM,
            profiles.OBJECTIVE,
            profiles.MOVE_XY,
            profiles.MOVE_Z,
            profiles.ACQUIRE,
            profiles.SELECT_JOB,
        ]
        for p in shipped:
            self.assertIsInstance(p, profiles.CommandProfile)


# =============================================================================
# 4. Confirmation via confirm_and_fire
# =============================================================================


class TestConfirmation(unittest.TestCase):
    def test_confirm_fn_immediate(self):
        client = make_client()
        api_obj = make_api_obj()
        confirm_fn = MagicMock(return_value={"success": True, "logs": []})
        with patch.object(errors, "_check_api_error", return_value=None):
            r = dispatch.confirm_and_fire(
                client,
                api_obj,
                "Test",
                confirm_fn=confirm_fn,
                max_retries=0,
                pre_check_fn=_idle_pre_check,
            )
        self.assertTrue(r["success"])
        self.assertTrue(r["confirmed"])
        confirm_fn.assert_called()

    def test_no_confirm_fn_skips(self):
        client = make_client()
        api_obj = make_api_obj()
        with patch.object(errors, "_check_api_error", return_value=None):
            r = dispatch.confirm_and_fire(
                client,
                api_obj,
                "Test",
                confirm_fn=None,
                max_retries=0,
                pre_check_fn=_idle_pre_check,
            )
        self.assertTrue(r["success"])
        self.assertIsNone(r["confirmed"])
        self.assertEqual(r["timing"]["confirm_s"], 0.0)

    def test_confirm_always_fails(self):
        """When confirm_fn always returns failure, result is unconfirmed."""
        client = make_client()
        api_obj = make_api_obj()
        confirm_fn = MagicMock(return_value={"success": False, "logs": []})
        with patch.object(errors, "_check_api_error", return_value=None):
            r = dispatch.confirm_and_fire(
                client,
                api_obj,
                "Zoom -> 5",
                confirm_fn=confirm_fn,
                max_retries=0,
                max_confirm_attempts=1,
                pre_check_fn=_idle_pre_check,
            )
        self.assertFalse(r["success"])
        self.assertFalse(r["confirmed"])
        self.assertIn("unconfirmed", r["message"])

    def test_unconfirmed_command_reports_post_command_dialog(self):
        client = make_client()
        api_obj = make_api_obj()
        confirm_fn = MagicMock(return_value={"success": False, "logs": []})
        snapshot = MagicMock(
            pending_dialog="Please turn turret manually",
            pending_dialog_ts=time.time() + 10.0,
        )

        with (
            patch.object(errors, "_check_api_error", return_value=None),
            patch.object(dispatch._log_reader, "parse_msgbox_log", return_value=snapshot),
        ):
            r = dispatch.confirm_and_fire(
                client,
                api_obj,
                "Objective -> slot 1",
                confirm_fn=confirm_fn,
                max_retries=0,
                max_confirm_attempts=1,
                pre_check_fn=_idle_pre_check,
            )

        self.assertFalse(r["confirmed"])
        self.assertIn("LAS X dialog appears open", r["message"])
        self.assertTrue(any("LAS X dialog appears open" in entry["msg"] for entry in r["logs"]))

    def test_unconfirmed_command_ignores_pre_command_dialog(self):
        client = make_client()
        api_obj = make_api_obj()
        confirm_fn = MagicMock(return_value={"success": False, "logs": []})
        snapshot = MagicMock(
            pending_dialog="Old dialog",
            pending_dialog_ts=0.0,
        )

        with (
            patch.object(errors, "_check_api_error", return_value=None),
            patch.object(dispatch._log_reader, "parse_msgbox_log", return_value=snapshot),
        ):
            r = dispatch.confirm_and_fire(
                client,
                api_obj,
                "Objective -> slot 1",
                confirm_fn=confirm_fn,
                max_retries=0,
                max_confirm_attempts=1,
                pre_check_fn=_idle_pre_check,
            )

        self.assertFalse(r["confirmed"])
        self.assertFalse(any("LAS X dialog appears open" in entry["msg"] for entry in r["logs"]))

    def test_confirm_succeeds_on_retry(self):
        """Confirm fails first, correction re-fires, then confirm succeeds."""
        client = make_client()
        api_obj = make_api_obj()
        call_count = [0]

        def delayed_confirm():
            call_count[0] += 1
            return {"success": call_count[0] >= 2, "logs": []}

        with patch.object(errors, "_check_api_error", return_value=None):
            r = dispatch.confirm_and_fire(
                client,
                api_obj,
                "Test",
                confirm_fn=delayed_confirm,
                max_retries=0,
                max_confirm_attempts=3,
                pre_check_fn=_idle_pre_check,
            )
        self.assertTrue(r["success"])

    def test_readback_retry_does_not_refire_when_policy_says_so(self):
        """A stale Leica readback can retry confirmation without re-firing."""
        client = make_client()
        api_obj = make_api_obj()
        fire_result = {
            "success": True,
            "logs": [],
            "attempts": 1,
            "timing": {
                "pre_check_s": 0.0,
                "setup_s": 0.0,
                "fire_s": 0.0,
                "check_s": 0.0,
            },
        }
        confirm_fn = MagicMock(
            side_effect=[
                {"success": False, "logs": []},
                {"success": False, "logs": []},
                {"success": True, "logs": []},
            ]
        )

        with patch.object(dispatch, "_fire_block", return_value=fire_result) as fire:
            r = dispatch.confirm_and_fire(
                client,
                api_obj,
                "Set Zoom",
                setup_fn=lambda m: None,
                confirm_fn=confirm_fn,
                max_confirm_attempts=3,
                refire_on_unconfirmed=False,
            )

        self.assertTrue(r["success"])
        self.assertTrue(r["confirmed"])
        self.assertEqual(fire.call_count, 1)
        self.assertEqual(confirm_fn.call_count, 3)

    def test_unconfirmed_readback_can_be_non_fatal_without_refire(self):
        """Settings may be applied even when Leica's state readback is stale."""
        client = make_client()
        api_obj = make_api_obj()
        fire_result = {
            "success": True,
            "logs": [],
            "attempts": 1,
            "timing": {
                "pre_check_s": 0.0,
                "setup_s": 0.0,
                "fire_s": 0.0,
                "check_s": 0.0,
            },
        }
        confirm_fn = MagicMock(return_value={"success": False, "logs": []})

        with patch.object(dispatch, "_fire_block", return_value=fire_result) as fire:
            r = dispatch.confirm_and_fire(
                client,
                api_obj,
                "Set Zoom",
                setup_fn=lambda m: None,
                confirm_fn=confirm_fn,
                max_confirm_attempts=3,
                refire_on_unconfirmed=False,
                success_on_unconfirmed=True,
            )

        self.assertTrue(r["success"])
        self.assertFalse(r["confirmed"])
        self.assertEqual(fire.call_count, 1)
        self.assertIn("readback unconfirmed", r["message"])
        self.assertTrue(any("command was sent successfully" in item["msg"] for item in r["logs"]))

    def test_unconfirmed_setting_refire_is_non_fatal(self):
        """Settings may re-fire and still continue when readback disagrees."""
        client = make_client()
        api_obj = make_api_obj()
        fire_result = {
            "success": True,
            "logs": [],
            "attempts": 1,
            "timing": {
                "pre_check_s": 0.0,
                "setup_s": 0.0,
                "fire_s": 0.0,
                "check_s": 0.0,
            },
        }
        confirm_fn = MagicMock(
            return_value={
                "success": False,
                "logs": [],
                "actual": 4.0,
            }
        )

        with patch.object(dispatch, "_fire_block", return_value=fire_result) as fire:
            r = dispatch.confirm_and_fire(
                client,
                api_obj,
                "Set Zoom",
                setup_fn=lambda m: None,
                confirm_fn=confirm_fn,
                max_confirm_attempts=3,
                refire_on_unconfirmed=True,
                success_on_unconfirmed=True,
            )

        self.assertTrue(r["success"])
        self.assertFalse(r["confirmed"])
        self.assertEqual(fire.call_count, 3)
        self.assertEqual(confirm_fn.call_count, 3)
        self.assertTrue(
            any("last_confirmation={'actual': 4.0}" in item["msg"] for item in r["logs"])
        )

    def test_confirm_fn_exception_handled(self):
        """Exceptions in confirm_fn are caught and treated as failure."""
        client = make_client()
        api_obj = make_api_obj()
        call_count = [0]

        def flaky_confirm():
            call_count[0] += 1
            if call_count[0] < 2:
                raise RuntimeError("COM error")
            return {"success": True, "logs": []}

        with patch.object(errors, "_check_api_error", return_value=None):
            r = dispatch.confirm_and_fire(
                client,
                api_obj,
                "Test",
                confirm_fn=flaky_confirm,
                max_retries=0,
                max_confirm_attempts=3,
                pre_check_fn=_idle_pre_check,
            )
        self.assertTrue(r["success"])


# =============================================================================
# 6. Error classification
# =============================================================================


class TestErrorClassification(unittest.TestCase):
    def test_transient_patterns(self):
        for msg in [
            "block is being scanned",
            "cannot be set while scanning",
            "Hardware busy",
            "Resource locked",
            "Connection timeout",
            "Request timed out",
        ]:
            with self.subTest(msg=msg):
                self.assertTrue(drv_errors._is_transient_error(msg))

    def test_permanent_patterns(self):
        for msg in [
            "parameter out of range",
            "value is invalid",
            "invalid block identifier",
            "detector not found",
            "Command not defined",
            "has been adjusted",
            "not implemented",
        ]:
            with self.subTest(msg=msg):
                self.assertFalse(drv_errors._is_transient_error(msg))

    def test_permanent_wins_over_transient(self):
        self.assertFalse(drv_errors._is_transient_error("timeout not found"))
        self.assertFalse(drv_errors._is_transient_error("locked out of range"))

    def test_unknown_is_permanent(self):
        self.assertFalse(drv_errors._is_transient_error("something unexpected"))

    def test_empty_string(self):
        self.assertFalse(drv_errors._is_transient_error(""))

    def test_case_insensitive(self):
        self.assertTrue(drv_errors._is_transient_error("BEING SCANNED"))
        self.assertFalse(drv_errors._is_transient_error("OUT OF RANGE"))


# =============================================================================
# 7. Confirm functions
# =============================================================================


def _fw_settings(fw_type="emission", beam_route="BR1", filter_index=0, spectrum_position=525):
    """Build a job-settings readback carrying one filter wheel entry."""
    return {
        "activeSettings": [
            {
                "filterWheels": [
                    {
                        "_beamRoute": beam_route,
                        "type": fw_type,
                        "filterIndex": filter_index,
                        "spectrumPosition": spectrum_position,
                    }
                ],
            }
        ],
    }


class TestConfirmFunctions(unittest.TestCase):
    """Table-driven checks of the readback confirm functions.

    Each row runs one confirm function against a mocked readback (the dict
    ``_readback`` would return) and asserts whether the confirmation should
    succeed. Rows preserve the exact arguments of the individual tests they
    replaced, including the shortened poll windows on the cases that must
    time out unconfirmed.
    """

    def _mock_readback(self, changeable_dict):
        return patch.object(confirmations, "_readback", return_value=changeable_dict)

    # Rows: (case label, confirm function name, positional args after client,
    #        keyword args, mocked readback, expected success).
    CONFIRM_CASES = [
        # -- zoom (tolerance 0.1 default) --
        ("zoom exact", "_confirm_zoom", ("J", 5.0), {}, {"zoom": {"current": 5.0}}, True),
        ("zoom within tol", "_confirm_zoom", ("J", 5.0), {}, {"zoom": {"current": 5.05}}, True),
        ("zoom mismatch", "_confirm_zoom", ("J", 5.0), {}, {"zoom": {"current": 3.0}}, False),
        ("zoom none readback", "_confirm_zoom", ("J", 5.0), {}, None, False),
        # -- scan speed / resonant / mode / sequential (exact match) --
        (
            "scan speed match",
            "_confirm_scan_speed",
            ("J", 600),
            {},
            {"scanSpeed": {"value": 600}},
            True,
        ),
        (
            "scan speed mismatch",
            "_confirm_scan_speed",
            ("J", 600),
            {},
            {"scanSpeed": {"value": 400}},
            False,
        ),
        (
            "scan resonant match",
            "_confirm_scan_resonant",
            ("J", True),
            {},
            {"scanSpeed": {"isResonant": True}},
            True,
        ),
        (
            "scan resonant mismatch",
            "_confirm_scan_resonant",
            ("J", False),
            {},
            {"scanSpeed": {"isResonant": True}},
            False,
        ),
        ("scan mode match", "_confirm_scan_mode", ("J", "xyz"), {}, {"scanMode": "xyz"}, True),
        ("scan mode mismatch", "_confirm_scan_mode", ("J", "xy"), {}, {"scanMode": "xyz"}, False),
        (
            "sequential mode match",
            "_confirm_sequential_mode",
            ("J", "Frame"),
            {},
            {"sequentialMode": "Frame"},
            True,
        ),
        # -- rotation (tolerance 0.5 default) --
        (
            "rotation within tol",
            "_confirm_scan_field_rotation",
            ("J", 45.0),
            {},
            {"scanFieldRotation": {"value": 45.3}},
            True,
        ),
        (
            "rotation outside tol",
            "_confirm_scan_field_rotation",
            ("J", 45.0),
            {},
            {"scanFieldRotation": {"value": 46.0}},
            False,
        ),
        # -- image format ("W x H" string target) --
        (
            "image format match",
            "_confirm_image_format",
            ("J", 1024, 1024),
            {},
            {"format": "1024 x 1024"},
            True,
        ),
        (
            "image format mismatch",
            "_confirm_image_format",
            ("J", 512, 512),
            {},
            {"format": "1024 x 1024"},
            False,
        ),
        # -- pinhole (tolerance 0.05 default) --
        (
            "pinhole within tol",
            "_confirm_pinhole_airy",
            ("J", 0, 1.0),
            {},
            {"activeSettings": [{"pinholeAiry": {"value": 1.02}}]},
            True,
        ),
        (
            "pinhole outside tol",
            "_confirm_pinhole_airy",
            ("J", 0, 1.0),
            {},
            {"activeSettings": [{"pinholeAiry": {"value": 0.5}}]},
            False,
        ),
        # -- accumulation / average (exact match) --
        (
            "frame accumulation match",
            "_confirm_frame_accumulation",
            ("J", 0, 4),
            {},
            {"activeSettings": [{"frameAccumulation": 4}]},
            True,
        ),
        (
            "frame accumulation mismatch",
            "_confirm_frame_accumulation",
            ("J", 0, 2),
            {},
            {"activeSettings": [{"frameAccumulation": 4}]},
            False,
        ),
        (
            "frame average match",
            "_confirm_frame_average",
            ("J", 0, 2),
            {},
            {"activeSettings": [{"frameAverage": 2}]},
            True,
        ),
        (
            "line accumulation match",
            "_confirm_line_accumulation",
            ("J", 0, 3),
            {},
            {"activeSettings": [{"lineAccumulation": 3}]},
            True,
        ),
        (
            "line average match",
            "_confirm_line_average",
            ("J", 0, 8),
            {},
            {"activeSettings": [{"lineAverage": 8}]},
            True,
        ),
        # -- move_z (galvo / zwide drives, tolerance 1.0 default) --
        (
            "move_z galvo arrived",
            "confirm_move_z",
            (),
            dict(job_name="J", z_mode="galvo", target_um=50.0, poll_window=1),
            {"zPosition": {"z-galvo": 50.0}},
            True,
        ),
        (
            "move_z galvo short",
            "confirm_move_z",
            (),
            dict(job_name="J", z_mode="galvo", target_um=50.0, poll_window=0.1),
            {"zPosition": {"z-galvo": 10.0}},
            False,
        ),
        (
            "move_z zwide arrived",
            "confirm_move_z",
            (),
            dict(job_name="J", z_mode="zwide", target_um=100.0, poll_window=1),
            {"zPosition": {"z-wide": 100.0}},
            True,
        ),
        (
            "move_z within tol",
            "confirm_move_z",
            (),
            dict(job_name="J", z_mode="galvo", target_um=50.0, tolerance=1.0, poll_window=1),
            {"zPosition": {"z-galvo": 50.5}},
            True,
        ),
        (
            "move_z none readback",
            "confirm_move_z",
            (),
            dict(job_name="J", z_mode="galvo", target_um=50.0, poll_window=0.1),
            None,
            False,
        ),
        # -- z-stack step size (tolerance 0.5 default) --
        (
            "z-step exact",
            "_confirm_z_stack_step_size",
            ("J",),
            dict(target=2.0, poll_window=1),
            {"stack": {"stepSize": 2.0}},
            True,
        ),
        (
            "z-step mismatch",
            "_confirm_z_stack_step_size",
            ("J",),
            dict(target=2.0, poll_window=0.1),
            {"stack": {"stepSize": 5.0}},
            False,
        ),
        (
            "z-step within tol",
            "_confirm_z_stack_step_size",
            ("J",),
            dict(target=2.0, tolerance=0.5, poll_window=1),
            {"stack": {"stepSize": 2.3}},
            True,
        ),
        # -- z-stack size (direct or step-quantised match) --
        (
            "z-size exact",
            "_confirm_z_stack_size",
            ("J",),
            dict(target_um=10.0, poll_window=1),
            {"stack": {"size": 10.0, "stepSize": 2.0}},
            True,
        ),
        (
            "z-size mismatch",
            "_confirm_z_stack_size",
            ("J",),
            dict(target_um=10.0, poll_window=0.1),
            {"stack": {"size": 20.0, "stepSize": 2.0}},
            False,
        ),
        # Target 9.5 with step 2.0: quantised candidates are 8.0 (n=4) and
        # 10.0 (n=5); actual 10.0 matches via the quantised path.
        (
            "z-size quantised",
            "_confirm_z_stack_size",
            ("J",),
            dict(target_um=9.5, poll_window=1),
            {"stack": {"size": 10.0, "stepSize": 2.0}},
            True,
        ),
        # -- z-stack definition (begin/end, optional sides, quantisation) --
        (
            "z-def exact",
            "_confirm_z_stack_definition",
            ("J",),
            dict(begin_um=-5.0, end_um=5.0, poll_window=1),
            {"stack": {"begin": -5.0, "end": 5.0, "stepSize": 1.0}},
            True,
        ),
        (
            "z-def mismatch",
            "_confirm_z_stack_definition",
            ("J",),
            dict(begin_um=-10.0, end_um=10.0, poll_window=0.1),
            {"stack": {"begin": -5.0, "end": 5.0, "stepSize": 1.0}},
            False,
        ),
        (
            "z-def begin only",
            "_confirm_z_stack_definition",
            ("J",),
            dict(begin_um=-5.0, end_um=None, poll_window=1),
            {"stack": {"begin": -5.0, "end": 5.0, "stepSize": 1.0}},
            True,
        ),
        # begin=-5, end=5, step=3 -> raw size 10, centre 0. Quantised n=3 gives
        # size 9 -> (-4.5, 4.5); n=4 gives size 12 -> (-6, 6). Actual (-4.5,
        # 4.5) matches the first candidate.
        (
            "z-def quantised",
            "_confirm_z_stack_definition",
            ("J",),
            dict(begin_um=-5.0, end_um=5.0, poll_window=1),
            {"stack": {"begin": -4.5, "end": 4.5, "stepSize": 3.0}},
            True,
        ),
        # -- filter wheel slot / spectrum --
        (
            "fw slot match",
            "_confirm_filter_wheel_slot",
            ("J",),
            dict(si=0, beam_route="BR1", fw_type="emission", target=2, poll_window=1),
            _fw_settings(filter_index=2),
            True,
        ),
        (
            "fw slot mismatch",
            "_confirm_filter_wheel_slot",
            ("J",),
            dict(si=0, beam_route="BR1", fw_type="emission", target=2, poll_window=0.1),
            _fw_settings(filter_index=0),
            False,
        ),
        (
            "fw slot wrong beam route",
            "_confirm_filter_wheel_slot",
            ("J",),
            dict(si=0, beam_route="BR1", fw_type="emission", target=2, poll_window=0.1),
            _fw_settings(beam_route="BR2", filter_index=2),
            False,
        ),
        (
            "fw spectrum match",
            "_confirm_filter_wheel_spectrum",
            ("J",),
            dict(si=0, beam_route="BR1", fw_type="emission", target=525, poll_window=1),
            _fw_settings(spectrum_position=525),
            True,
        ),
        (
            "fw spectrum mismatch",
            "_confirm_filter_wheel_spectrum",
            ("J",),
            dict(si=0, beam_route="BR1", fw_type="emission", target=525, poll_window=0.1),
            _fw_settings(spectrum_position=600),
            False,
        ),
        (
            "fw spectrum within tol",
            "_confirm_filter_wheel_spectrum",
            ("J",),
            dict(
                si=0, beam_route="BR1", fw_type="emission", target=525, tolerance=1, poll_window=1
            ),
            _fw_settings(spectrum_position=525.5),
            True,
        ),
    ]

    def test_confirm_functions_against_mocked_readback(self):
        for label, fn_name, args, kwargs, readback, expected in self.CONFIRM_CASES:
            fn = getattr(confirmations, fn_name)
            with self.subTest(label):
                with self._mock_readback(readback):
                    result = fn(None, *args, **kwargs)
                self.assertEqual(result["success"], expected)

    def test_setting_confirm_pins_api_even_when_profile_is_both(self):
        prior = profiles.STATE_READERS
        profiles.STATE_READERS = profiles.StateReaderProfile(job_settings_mode="hybrid")
        calls = []

        def fake_get_job_settings(client, job_name, **kwargs):
            calls.append(kwargs)
            return readers.Reading(
                value={
                    "zoom": {"current": 1.0},
                    "scanSpeed": {"value": 400, "isResonant": True},
                    "activeSettings": [{}],
                },
                source="api",
                observed_at=time.time() + 1.0,
                age_s=0.0,
            )

        try:
            with patch.object(
                confirmations._readers,
                "get_job_settings",
                side_effect=fake_get_job_settings,
            ):
                result = confirmations._confirm_scan_resonant(
                    object(), "J", True, poll_window=0.01, poll_interval=0.001
                )
        finally:
            profiles.STATE_READERS = prior

        self.assertTrue(result["success"])
        self.assertEqual(calls[0]["mode"], "api")
        self.assertTrue(calls[0]["diagnostics"])

    def test_confirm_move_xy(self):
        with patch.object(
            readers, "get_xy", return_value={"x_um": 50000, "y_um": 50000, "x_m": 0.05, "y_m": 0.05}
        ):
            self.assertTrue(
                confirmations.confirm_move_xy(
                    None, target_x_um=50000, target_y_um=50000, poll_window=1
                )["success"]
            )
            self.assertFalse(
                confirmations.confirm_move_xy(
                    None, target_x_um=50000, target_y_um=99999, poll_window=0.2
                )["success"]
            )

    def test_confirm_returns_dict_shape(self):
        """All confirm functions return {"success": bool, "logs": [...]}."""
        with self._mock_readback({"zoom": {"current": 5.0}}):
            result = confirmations._confirm_zoom(None, "J", 5.0)
        self.assertIn("success", result)
        self.assertIn("logs", result)
        self.assertIsInstance(result["logs"], list)


# =============================================================================
# 8. Set function wiring
# =============================================================================


class TestSetFunctionWiring(unittest.TestCase):
    def _resonant_no_change_client(self):
        class Echo:
            Result = 2
            HasError = True
            Error = (
                "CamCommandSetScannerToResonantByJobName: "
                "the desired state does not differ from the current state"
            )
            Description = ""
            ErrorDescription = ""
            Message = ""
            ErrorMessage = ""
            Warning = ""
            Info = ""
            Details = ""

        client = MagicMock()
        client.PyApiCommandEcho.Model = Echo()
        return client

    def _run_set(self, set_fn, *args, **kwargs):
        """Run a set function with confirm_and_fire mocked.

        If the first positional arg is None, substitute make_client()
        so that API object attribute lookups (client.PyApiXxx) succeed.
        Returns (captured_info, result).  captured_info includes:
          - description, kwargs, model  (as before)
          - api_obj: the API object the set function resolved
          - client:  the mock client used (for identity checks)
        """
        args = list(args)
        if args and args[0] is None:
            args[0] = make_client()
        captured = {"client": args[0]}

        def mock_fire(client, api_obj, description, **kw):
            captured["description"] = description
            captured["api_obj"] = api_obj
            captured["kwargs"] = kw
            model = MagicMock()
            if kw.get("setup_fn"):
                kw["setup_fn"](model)
            captured["model"] = model
            return _make_v6_result(msg=description)

        with patch.object(commands, "confirm_and_fire", side_effect=mock_fire):
            r = set_fn(*args, **kwargs)
        return captured, r

    # Rows: (case label, set function name, positional args after client,
    #        client API-object attribute, {model attribute: expected value}).
    # Float expectations use assertAlmostEqual because some setters convert
    # micrometers to meters before writing the model.
    SET_MODEL_CASES = [
        (
            "set_zoom",
            "set_zoom",
            ("HiRes", 5.0),
            "PyApiSetZoomByJobName",
            {"JobName": "HiRes", "ZoomValue": 5.0},
        ),
        (
            "set_scan_speed",
            "set_scan_speed",
            ("HiRes", 600),
            "PyApiSetScanSpeedByJobName",
            {"ScanSpeed": 600},
        ),
        (
            "set_scan_resonant",
            "set_scan_resonant",
            ("HiRes", True),
            "PyApiSetScannerToResonantByJobName",
            {"EnableResonant": True},
        ),
        (
            "set_scan_mode",
            "set_scan_mode",
            ("HiRes", "xyz"),
            "PyApiSetScanModeByJobName",
            {"ScanModeValue": "xyz"},
        ),
        (
            "set_scan_field_rotation",
            "set_scan_field_rotation",
            ("HiRes", 45.0),
            "PyApiSetScanFieldRotationByJobName",
            {"Rotation": 45.0},
        ),
        (
            "set_image_format string",
            "set_image_format",
            ("HiRes", "1024 x 1024"),
            "PyApiSetImageSizeByJobName",
            {"ImageWidth": 1024, "ImageHeight": 1024},
        ),
        (
            "set_image_format tuple",
            "set_image_format",
            ("HiRes", (512, 768)),
            "PyApiSetImageSizeByJobName",
            {"ImageWidth": 512, "ImageHeight": 768},
        ),
        (
            "set_frame_accumulation",
            "set_frame_accumulation",
            ("HiRes", 0, 4),
            "PyApiSetFrameAccumulationByJobName",
            {"SettingIndex": 0, "FrameAccumulation": 4},
        ),
        (
            "set_frame_average",
            "set_frame_average",
            ("HiRes", 0, 2),
            "PyApiSetFrameAverageByJobName",
            {"FrameAverage": 2},
        ),
        (
            "set_pinhole_airy",
            "set_pinhole_airy",
            ("HiRes", 0, 1.5),
            "PyApiSetPinholeAUByJobName",
            {"PinholeAiry": 1.5},
        ),
        (
            "set_detector_gain",
            "set_detector_gain",
            ("HiRes", 0, "BR1", 750),
            "PyApiSetDetectorGainByJobName",
            {"BeamRoute": "BR1", "GainValue": 750},
        ),
        (
            "set_laser_intensity",
            "set_laser_intensity",
            ("HiRes", 0, "BR1", 0, 0.5),
            "PyApiSetLaserIntensityByJobName",
            {"IntensityValue": 0.5, "LaserLineIndex": 0},
        ),
        (
            "set_laser_shutter",
            "set_laser_shutter",
            ("HiRes", 0, "BR1", True),
            "PyApiSetLaserShutterByJobName",
            {"Activate": True},
        ),
        (
            "set_z_stack_step_size",
            "set_z_stack_step_size",
            ("HiRes", 2.0),
            "PyApiCommandSetZStackStepSizeByJobName",
            {"StackStepSize": 2.0e-6},
        ),
        (
            "set_z_stack_size",
            "set_z_stack_size",
            ("HiRes", 10.0),
            "PyApiSetZStackSizeByJobName",
            {"StackSize": 10.0e-6},
        ),
        (
            "set_filter_wheel_slot",
            "set_filter_wheel_slot",
            ("J", 0, "BR1", "emission", 2),
            "PyApiSetFilterWheelSlotByJobName",
            {"JobName": "J", "SettingIndex": 0, "BeamRoute": "BR1", "SlotIndex": 2},
        ),
        (
            "set_filter_wheel_spectrum",
            "set_filter_wheel_spectrum",
            ("J", 0, "BR1", "emission", 525),
            "PyApiSetFilterWheelSpectrumPositionByJobName",
            {"JobName": "J", "SettingIndex": 0, "BeamRoute": "BR1", "FilterSpectrumPosition": 525},
        ),
    ]

    def test_set_functions_write_the_documented_model_fields(self):
        """Each set function resolves its API object and writes its model fields."""
        for label, fn_name, args, api_attr, fields in self.SET_MODEL_CASES:
            with self.subTest(label):
                info, _ = self._run_set(getattr(drv, fn_name), None, *args)
                self.assertIs(info["api_obj"], getattr(info["client"], api_attr))
                for attr, expected in fields.items():
                    actual = getattr(info["model"], attr)
                    if isinstance(expected, float):
                        self.assertAlmostEqual(actual, expected, places=10)
                    else:
                        self.assertEqual(actual, expected)

    def test_scan_resonant_no_change_error_accepted_when_readback_matches(self):

        client = self._resonant_no_change_client()
        with patch.object(
            commands,
            "_confirm_scan_resonant",
            return_value={"success": True, "logs": []},
        ) as confirm:
            result = commands._scan_resonant_error_check(
                client, job_name="HiRes", target=False, timeout=0.1
            )

        self.assertTrue(result["success"])
        self.assertIsNone(result["error"])
        confirm.assert_called_once_with(client, "HiRes", False, poll_window=0.1)

    def test_scan_resonant_no_change_error_fails_when_readback_disagrees(self):
        client = self._resonant_no_change_client()
        with patch.object(
            commands,
            "_confirm_scan_resonant",
            return_value={"success": False, "logs": []},
        ):
            result = commands._scan_resonant_error_check(
                client, job_name="HiRes", target=False, timeout=0.1
            )

        self.assertFalse(result["success"])
        self.assertIn("desired state does not differ", result["error"])

    def test_set_zoom_provides_confirm_fn(self):
        info, _ = self._run_set(drv.set_zoom, None, "HiRes", 5.0)
        self.assertIs(info["api_obj"], info["client"].PyApiSetZoomByJobName)
        self.assertIsNotNone(info["kwargs"].get("confirm_fn"))

    # â”€â”€ move_z wiring â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _run_move_z(self, *args, **kwargs):
        """Like _run_set but also mocks _check_z_limits."""
        with patch.object(commands, "_check_z_limits"):
            return self._run_set(drv.move_z, *args, **kwargs)

    def test_move_z_galvo_model(self):
        info, _ = self._run_move_z(None, "J", 50.0, unit="um", z_mode="galvo")
        self.assertIs(info["api_obj"], info["client"].PyApiMoveZByJobName)
        self.assertEqual(info["model"].JobName, "J")
        self.assertEqual(info["model"].ZPosition, 50.0)
        self.assertFalse(info["model"].RelativePosition)

    def test_move_z_unit_mm(self):
        info, _ = self._run_move_z(None, "J", 0.05, unit="mm", z_mode="galvo")
        self.assertIs(info["api_obj"], info["client"].PyApiMoveZByJobName)
        # ZPosition is stored in the user-supplied unit (not converted)
        self.assertEqual(info["model"].ZPosition, 0.05)

    def test_move_z_unit_m(self):
        info, _ = self._run_move_z(None, "J", 50.0e-6, unit="m", z_mode="galvo")
        self.assertIs(info["api_obj"], info["client"].PyApiMoveZByJobName)
        self.assertEqual(info["model"].ZPosition, 50.0e-6)

    def test_move_z_zwide_mode(self):
        info, _ = self._run_move_z(None, "J", 100.0, unit="um", z_mode="zwide")
        self.assertIs(info["api_obj"], info["client"].PyApiMoveZByJobName)

    def test_move_z_invalid_mode(self):
        r = drv.move_z(make_client(), "J", 50.0, z_mode="invalid")
        self.assertFalse(r["success"])
        self.assertIn("Unknown z_mode", r["message"])

    def test_move_z_provides_confirm_fn(self):
        info, _ = self._run_move_z(None, "J", 50.0)
        self.assertIsNotNone(info["kwargs"].get("confirm_fn"))

    def test_move_z_limit_check_failure(self):
        """When _check_z_limits raises, move_z returns failure without dispatch."""
        r = drv.move_z(make_client(), "J", 99999.0, z_mode="galvo")
        self.assertFalse(r["success"])

    # â”€â”€ set_z_stack_definition wiring â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def test_set_z_stack_definition_begin_end(self):
        info, _ = self._run_set(drv.set_z_stack_definition, None, "J", begin_um=-5.0, end_um=5.0)
        self.assertIs(info["api_obj"], info["client"].PyApiSetZStackDefinitionByJobName)
        self.assertEqual(info["model"].JobName, "J")
        self.assertEqual(info["model"].SetBegin, 1)
        self.assertEqual(info["model"].SetEnd, 1)
        self.assertAlmostEqual(info["model"].BeginValue, -5.0e-6, places=12)
        self.assertAlmostEqual(info["model"].EndValue, 5.0e-6, places=12)

    def test_set_z_stack_definition_begin_only(self):
        info, _ = self._run_set(drv.set_z_stack_definition, None, "J", begin_um=10.0)
        self.assertEqual(info["model"].SetBegin, 1)
        self.assertEqual(info["model"].SetEnd, 2)  # ignore

    def test_set_z_stack_definition_end_only(self):
        info, _ = self._run_set(drv.set_z_stack_definition, None, "J", end_um=10.0)
        self.assertEqual(info["model"].SetBegin, 2)  # ignore
        self.assertEqual(info["model"].SetEnd, 1)

    def test_set_z_stack_definition_reset_begin(self):
        info, _ = self._run_set(drv.set_z_stack_definition, None, "J", old_begin_um=-3.0)
        self.assertEqual(info["model"].SetBegin, 0)  # reset

    def test_set_z_stack_definition_zero_begin(self):
        """begin_um=0.0 is a valid z-position - must not be treated as None."""
        info, _ = self._run_set(drv.set_z_stack_definition, None, "J", begin_um=0.0, end_um=10.0)
        self.assertEqual(info["model"].SetBegin, 1)
        self.assertAlmostEqual(info["model"].BeginValue, 0.0, places=12)

    def test_set_z_stack_definition_provides_confirm_fn(self):
        info, _ = self._run_set(drv.set_z_stack_definition, None, "J", begin_um=-5.0, end_um=5.0)
        self.assertIsNotNone(info["kwargs"].get("confirm_fn"))

    # â”€â”€ filter wheel wiring â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def test_set_filter_wheel_slot_provides_confirm_fn(self):
        info, _ = self._run_set(drv.set_filter_wheel_slot, None, "J", 0, "BR1", "emission", 2)
        self.assertIsNotNone(info["kwargs"].get("confirm_fn"))

    def test_set_filter_wheel_spectrum_provides_confirm_fn(self):
        info, _ = self._run_set(drv.set_filter_wheel_spectrum, None, "J", 0, "BR1", "emission", 525)
        self.assertIsNotNone(info["kwargs"].get("confirm_fn"))


# =============================================================================
# 9. Set function defaults
# =============================================================================


class TestSetFunctionDefaults(unittest.TestCase):
    def _get_kwargs(self, fn):
        captured = {}

        def mock_fire(client, api_obj, desc, **kw):
            captured.update(kw)
            return _make_v6_result(msg=desc)

        with patch.object(commands, "confirm_and_fire", side_effect=mock_fire):
            fn(make_client(), "J")
        return captured

    def test_zoom_defaults(self):
        d = self._get_kwargs(lambda c, j: drv.set_zoom(c, j, 5.0))
        self.assertEqual(d["max_retries"], 3)
        self.assertIsNotNone(d["confirm_fn"])

    def test_scan_speed_defaults(self):
        d = self._get_kwargs(lambda c, j: drv.set_scan_speed(c, j, 600))
        self.assertEqual(d["max_retries"], 3)
        self.assertIsNotNone(d["confirm_fn"])


# =============================================================================
# 10-14. Unchanged tests (make_changeable_copy, limits, format, etc.)
# =============================================================================


class TestMakeChangeableCopy(unittest.TestCase):
    def _settings(self, **overrides):
        s = {
            "zoom": {"current": 5.0},
            "scanSpeed": {"value": 600, "isResonant": False},
            "scanMode": "xyz",
            "sequentialMode": "Frame",
            "scanFieldRotation": {"value": 0.0},
            "format": "512 x 512",
            "objective": {"name": "HC PL APO 63x", "magnification": 63},
            "activeSettings": [
                {
                    "index": 0,
                    "name": "Setting 1",
                    "frameAccumulation": 1,
                    "frameAverage": 1,
                    "lineAccumulation": 1,
                    "lineAverage": 1,
                    "pinholeAiry": {"value": 1.0},
                    "activeDetectors": [
                        {"beamRoute": "BR1", "name": "HyD S1", "gain": {"value": 100}}
                    ],
                    "activeLaserLines": [
                        {
                            "beamRoute": "BR1",
                            "lineIndex": 0,
                            "wavelength": 488,
                            "laser": {"name": "OPSL 488"},
                            "intensity": {"value": 0.1},
                            "shutterOpen": True,
                        }
                    ],
                }
            ],
        }
        s.update(overrides)
        return s

    def test_none_returns_none(self):
        self.assertIsNone(drv.make_changeable_copy(None))

    def test_basic_fields(self):
        ch = drv.make_changeable_copy(self._settings())
        self.assertEqual(ch["zoom"]["current"], 5.0)
        self.assertEqual(ch["scanSpeed"]["value"], 600)

    def test_objective(self):
        ch = drv.make_changeable_copy(self._settings())
        self.assertEqual(ch["objective"]["name"], "HC PL APO 63x")

    def test_active_settings(self):
        ch = drv.make_changeable_copy(self._settings())
        self.assertEqual(ch["activeSettings"][0]["activeDetectors"][0]["_beamRoute"], "BR1")

    def test_laser_lines(self):
        ch = drv.make_changeable_copy(self._settings())
        self.assertEqual(ch["activeSettings"][0]["activeLaserLines"][0]["_beamRoute"], "BR1")

    def test_stack_with_z(self):
        ch = drv.make_changeable_copy(
            self._settings(stack={"begin": -5.0, "end": 5.0, "stepSize": 1.0})
        )
        self.assertAlmostEqual(ch["stack"]["size"], 10.0)

    def test_no_stack_no_z(self):
        ch = drv.make_changeable_copy(self._settings(scanMode="xy"))
        self.assertNotIn("stack", ch)

    def test_multiple_settings(self):
        settings = self._settings()
        settings["activeSettings"].append(
            {
                "index": 1,
                "name": "Setting 2",
                "frameAccumulation": 2,
                "frameAverage": 4,
                "lineAccumulation": 1,
                "lineAverage": 1,
                "pinholeAiry": {"value": 0.5},
                "activeDetectors": [],
                "activeLaserLines": [],
            }
        )
        ch = drv.make_changeable_copy(settings)
        self.assertEqual(len(ch["activeSettings"]), 2)


class TestStageLimits(unittest.TestCase):
    def setUp(self):
        drv.set_stage_limits(
            x_min=0,
            x_max=130000,
            y_min=0,
            y_max=100000,
            z_galvo_min=-200,
            z_galvo_max=200,
            z_wide_min=0,
            z_wide_max=25000,
        )

    def test_valid_xy(self):
        drv_limits._check_xy_limits(50000, 50000)

    def test_x_below_min(self):
        with self.assertRaises(RuntimeError):
            drv_limits._check_xy_limits(-1, 50000)

    def test_x_above_max(self):
        with self.assertRaises(RuntimeError):
            drv_limits._check_xy_limits(130001, 50000)

    def test_y_below_min(self):
        with self.assertRaises(RuntimeError):
            drv_limits._check_xy_limits(50000, -1)

    def test_y_above_max(self):
        with self.assertRaises(RuntimeError):
            drv_limits._check_xy_limits(50000, 100001)

    def test_z_galvo_valid(self):
        drv_limits._check_z_limits(0, "galvo")

    def test_z_galvo_below(self):
        with self.assertRaises(RuntimeError):
            drv_limits._check_z_limits(-201, "galvo")

    def test_z_galvo_above(self):
        with self.assertRaises(RuntimeError):
            drv_limits._check_z_limits(201, "galvo")

    def test_z_wide_above(self):
        with self.assertRaises(RuntimeError):
            drv_limits._check_z_limits(25001, "zwide")

    def test_z_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            drv_limits._check_z_limits(100, "unknown")

    def test_unconfigured_raises(self):
        old = dict(drv_limits._stage_limits)
        drv_limits._stage_limits["x_min"] = None
        try:
            with self.assertRaises(RuntimeError):
                drv_limits._check_xy_limits(0, 0)
        finally:
            drv_limits._stage_limits.update(old)


class TestFormatParsing(unittest.TestCase):
    def test_parse_standard(self):
        self.assertEqual(drv.parse_format("512 x 512"), (512, 512))

    def test_parse_rectangular(self):
        self.assertEqual(drv.parse_format("1024 x 768"), (1024, 768))

    def test_roundtrip(self):
        self.assertEqual(drv.parse_format("2048 x 2048"), (2048, 2048))

    def test_parse_bad_input(self):
        with self.assertRaises(ValueError):
            drv.parse_format("banana")


class TestSafeFloat(unittest.TestCase):
    def test_int(self):
        self.assertEqual(_safe_float(5), 5.0)

    def test_string(self):
        self.assertEqual(_safe_float("3.14"), 3.14)

    def test_none_default(self):
        self.assertEqual(_safe_float(None, -1), -1)

    def test_bad_string_default(self):
        self.assertEqual(_safe_float("abc", 0), 0)

    def test_none_no_default(self):
        self.assertIsNone(_safe_float(None))


class TestSequentialModeGuard(unittest.TestCase):
    def test_empty_string(self):
        r = drv.set_sequential_mode(None, "J", "")
        self.assertFalse(r["success"])

    def test_whitespace(self):
        self.assertFalse(drv.set_sequential_mode(None, "J", "   ")["success"])

    def test_non_string(self):
        self.assertFalse(drv.set_sequential_mode(None, "J", 123)["success"])

    def test_none(self):
        self.assertFalse(drv.set_sequential_mode(None, "J", None)["success"])


class TestReadback(unittest.TestCase):
    def test_success(self):
        settings = {
            "zoom": {"current": 5.0},
            "scanSpeed": {"value": 600, "isResonant": False},
            "scanMode": "xyz",
            "sequentialMode": "Frame",
            "scanFieldRotation": {"value": 0.0},
            "format": "512 x 512",
            "objective": {"name": "Obj", "magnification": 63},
            "activeSettings": [],
        }
        with patch.object(readers, "get_job_settings", return_value=settings):
            ch = _readback(None, "HiRes")
        self.assertIsNotNone(ch)
        self.assertEqual(ch["zoom"]["current"], 5.0)

    def test_failure(self):
        with patch.object(readers, "get_job_settings", return_value=None):
            self.assertIsNone(_readback(None, "HiRes"))


# =============================================================================
# 17. check_idle (replaces pre_check_timeout tests)
# =============================================================================


class TestCheckIdle(unittest.TestCase):
    def test_idle_returns_immediately(self):
        with patch.object(readers, "get_scan_status", return_value="eScanIdle"):
            result = prechecks.check_idle(None, timeout=5.0)
        self.assertTrue(result["success"])
        self.assertIsInstance(result["logs"], list)

    def test_check_idle_pins_api_mode(self):
        prior = profiles.STATE_READERS
        calls = []

        def mock_status(client, **kwargs):
            calls.append(kwargs)
            return "eScanIdle"

        profiles.STATE_READERS = profiles.StateReaderProfile(scan_status_mode="hybrid")
        try:
            with patch.object(readers, "get_scan_status", side_effect=mock_status):
                result = prechecks.check_idle(None, timeout=5.0)
        finally:
            profiles.STATE_READERS = prior

        self.assertTrue(result["success"])
        self.assertEqual(calls[0]["mode"], "api")

    def test_check_idle_treats_none_as_not_idle(self):
        values = [None, "eScanIdle"]

        def mock_status(client, **_kwargs):
            return values.pop(0)

        with patch.object(readers, "get_scan_status", side_effect=mock_status), patch("time.sleep"):
            result = prechecks.check_idle(None, timeout=None)

        self.assertTrue(result["success"])

    def test_timeout_returns_failure(self):
        with (
            patch.object(readers, "get_scan_status", return_value="eScanRunning"),
            patch("time.sleep"),
        ):
            result = prechecks.check_idle(None, timeout=0.01)
        self.assertFalse(result["success"])
        self.assertTrue(any("timeout" in e["msg"].lower() for e in result["logs"]))

    def test_none_timeout_waits_until_idle(self):
        call_count = [0]

        def mock_status(client, **_kwargs):
            call_count[0] += 1
            return "eScanIdle" if call_count[0] > 3 else "eScanRunning"

        with patch.object(readers, "get_scan_status", side_effect=mock_status), patch("time.sleep"):
            result = prechecks.check_idle(None, timeout=None)
        self.assertTrue(result["success"])


# =============================================================================
# 18. Command envelope consistency
# =============================================================================


class TestMoveXYConsistency(unittest.TestCase):
    def test_move_xy_has_full_timing(self):
        client = make_client()
        drv.set_stage_limits(
            x_min=0,
            x_max=130000,
            y_min=0,
            y_max=100000,
            z_galvo_min=-200,
            z_galvo_max=200,
            z_wide_min=0,
            z_wide_max=25000,
        )
        with (
            patch.object(readers, "get_scan_status", return_value="eScanIdle"),
            patch.object(errors, "_check_api_error", return_value=None),
            patch.object(
                readers,
                "get_xy",
                return_value={"x_um": 50000, "y_um": 50000, "x_m": 0.05, "y_m": 0.05},
            ),
            patch.object(
                confirmations, "confirm_move_xy", return_value={"success": True, "logs": []}
            ),
        ):
            r = drv.move_xy(client, 50000, 50000, unit="um")
        self.assertTrue(r["success"])
        for key in (
            "pre_check_s",
            "setup_s",
            "fire_s",
            "check_s",
            "confirm_s",
            "total_s",
            "attempts",
            "confirm_attempts",
            "method",
        ):
            self.assertIn(key, r["timing"])
        self.assertIn("position", r)

    def test_move_xy_no_confirm_bool(self):
        import inspect

        params = list(inspect.signature(drv.move_xy).parameters.keys())
        self.assertNotIn("confirm", params)
        self.assertIn("max_retries", params)
        self.assertIn("tolerance", params)


class TestGetStageLimits(unittest.TestCase):
    def test_returns_copy(self):
        drv.set_stage_limits(
            x_min=1,
            x_max=2,
            y_min=3,
            y_max=4,
            z_galvo_min=5,
            z_galvo_max=6,
            z_wide_min=7,
            z_wide_max=8,
        )
        limits = drv.get_stage_limits()
        self.assertEqual(limits["x_min"], 1)
        limits["x_min"] = 9999
        self.assertEqual(drv.get_stage_limits()["x_min"], 1)


class TestPing(unittest.TestCase):
    def test_ping_success(self):
        self.assertTrue(drv.ping(make_client()))

    def test_ping_failure(self):
        client = MagicMock()
        client.PyApiPing.UpdateAwaitReceipt.side_effect = Exception("COM error")
        type(client.PyApiStatus.Model).ScanStatus = PropertyMock(side_effect=Exception("COM error"))
        self.assertFalse(drv.ping(client))


class TestSchemaValidation(unittest.TestCase):
    def test_missing_zoom_raises(self):
        with self.assertRaises(ValueError) as ctx:
            drv.make_changeable_copy(
                {"scanSpeed": {"value": 600, "isResonant": False}, "activeSettings": []}
            )
        self.assertIn("zoom", str(ctx.exception))

    def test_missing_active_settings_raises(self):
        with self.assertRaises(ValueError) as ctx:
            drv.make_changeable_copy({"zoom": {"current": 5.0}, "scanSpeed": {"value": 600}})
        self.assertIn("activeSettings", str(ctx.exception))

    def test_valid_settings_pass(self):
        self.assertIsNotNone(
            drv.make_changeable_copy(
                {
                    "zoom": {"current": 5.0},
                    "scanSpeed": {"value": 600, "isResonant": False},
                    "activeSettings": [],
                }
            )
        )


class TestUnclassifiedErrorLogging(unittest.TestCase):
    def test_unknown_error_logs_warning(self):
        with self.assertLogs(drv.log, level="WARNING") as cm:
            result = drv_errors._is_transient_error("totally unexpected error xyz")
        self.assertFalse(result)
        self.assertTrue(any("Unclassified" in msg for msg in cm.output))

    def test_known_patterns_no_warning(self):
        self.assertTrue(drv_errors._is_transient_error("block is being scanned"))
        self.assertFalse(drv_errors._is_transient_error("out of range"))


# =============================================================================
# 19. confirm_acquire and confirm_select_job
# =============================================================================


class TestDispatchCheckExceptions(unittest.TestCase):
    """pre_check_fn / error_check_fn exceptions become structured failures."""

    def test_raising_pre_check_returns_failure_dict(self):
        result = dispatch._fire_block(
            None,
            SimpleNamespace(Model=SimpleNamespace()),
            "TestCmd",
            setup_fn=None,
            pre_check_fn=lambda: (_ for _ in ()).throw(RuntimeError("com fault")),
            error_check_fn=None,
        )
        self.assertFalse(result["success"])
        self.assertTrue(any("Pre-check raised" in e["msg"] for e in result["logs"]))

    def test_raising_error_check_is_transient_failure_not_exception(self):
        api_obj = SimpleNamespace(
            Model=SimpleNamespace(),
            UpdateAsync=lambda: None,
        )
        fake_client = SimpleNamespace(
            PyApiCommandEcho=SimpleNamespace(Model=SimpleNamespace(Result=0, HasError=False))
        )
        result = dispatch._fire_block(
            fake_client,
            api_obj,
            "TestCmd",
            setup_fn=None,
            pre_check_fn=None,
            error_check_fn=lambda: (_ for _ in ()).throw(RuntimeError("echo read fault")),
            fire_async=True,
            max_retries=0,
        )
        self.assertFalse(result["success"])
        self.assertTrue(any("Error check raised" in e["msg"] for e in result["logs"]))


class TestUnitValidation(unittest.TestCase):
    def test_move_xy_unknown_unit_returns_failure_dict(self):
        result = drv.move_xy(None, 1.0, 2.0, unit="nm")
        self.assertFalse(result["success"])
        self.assertIn("unknown unit", result["message"])

    def test_move_z_unknown_unit_returns_failure_dict(self):
        result = drv.move_z(None, "Job", 1.0, unit="nm")
        self.assertFalse(result["success"])
        self.assertIn("unknown unit", result["message"])

    def test_set_objective_requires_exactly_one_selector(self):
        client = make_client()  # gate-permissive; the selector validation is under test
        result = drv.set_objective(client, "Job", {}, slot_index=1, name="HC PL APO 63x")
        self.assertFalse(result["success"])
        self.assertIn("exactly one", result["message"])
        result = drv.set_objective(client, "Job", {})
        self.assertFalse(result["success"])


class TestQuantisedCandidatesDirection(unittest.TestCase):
    def test_descending_stack_candidates_keep_direction(self):
        # begin=10, end=-10: candidates must stay descending.
        candidates = confirmations._quantised_candidates(0.0, -20.0, 3.0)
        for begin, end in candidates:
            self.assertGreater(begin, end)
        sizes = sorted(abs(e - b) for b, e in candidates)
        self.assertAlmostEqual(sizes[0], 18.0)
        self.assertAlmostEqual(sizes[-1], 21.0)

    def test_ascending_stack_unchanged(self):
        candidates = confirmations._quantised_candidates(0.0, 20.0, 3.0)
        for begin, end in candidates:
            self.assertLess(begin, end)


class TestConfirmAcquire(unittest.TestCase):
    def test_idle_without_scanning_returns_failure(self):
        """Always idle, never saw scanning -> failure (start_timeout)."""
        with (
            patch.object(readers, "get_scan_status", return_value="eScanIdle"),
            patch.object(confirmations, "_check_api_error", return_value=None),
            patch("time.sleep"),
        ):
            result = confirmations.confirm_acquire(
                None, start_timeout=0.0, timeout=1.0, poll_interval=0.001
            )
        self.assertFalse(result["success"])

    def test_scanning_then_idle(self):
        """Non-idle then idle -> success (saw scanning)."""
        call_count = [0]

        def mock_status(client, **_kwargs):
            call_count[0] += 1
            return "eScanStarted" if call_count[0] <= 2 else "eScanIdle"

        with patch.object(readers, "get_scan_status", side_effect=mock_status), patch("time.sleep"):
            result = confirmations.confirm_acquire(None, timeout=5.0, poll_interval=0.001)
        self.assertTrue(result["success"])

    def test_failed_status_read_is_not_evidence_of_scanning(self):
        """A failed read (None) then idle forever -> failure, not success.

        A transient read error must not set saw_scanning: that would skip
        the start timeout and let two idle reads confirm an acquisition
        that never ran.
        """
        call_count = [0]

        def mock_status(client, **_kwargs):
            call_count[0] += 1
            return None if call_count[0] == 1 else "eScanIdle"

        with (
            patch.object(readers, "get_scan_status", side_effect=mock_status),
            patch.object(confirmations, "_check_api_error", return_value=None),
            patch("time.sleep"),
        ):
            result = confirmations.confirm_acquire(
                None, start_timeout=0.0, timeout=1.0, poll_interval=0.001
            )
        self.assertFalse(result["success"])

    def test_unknown_status_is_not_evidence_of_scanning(self):
        """The API reader's 'Unknown' failure sentinel behaves like None."""
        call_count = [0]

        def mock_status(client, **_kwargs):
            call_count[0] += 1
            return "Unknown" if call_count[0] == 1 else "eScanIdle"

        with (
            patch.object(readers, "get_scan_status", side_effect=mock_status),
            patch.object(confirmations, "_check_api_error", return_value=None),
            patch("time.sleep"),
        ):
            result = confirmations.confirm_acquire(
                None, start_timeout=0.0, timeout=1.0, poll_interval=0.001
            )
        self.assertFalse(result["success"])

    def test_unknown_read_breaks_idle_streak_but_not_saw_scanning(self):
        """Scanning, then a failed read between idles -> still succeeds."""
        statuses = iter(["eScanStarted", "Unknown", "eScanIdle", "eScanIdle", "eScanIdle"])

        def mock_status(client, **_kwargs):
            return next(statuses, "eScanIdle")

        with patch.object(readers, "get_scan_status", side_effect=mock_status), patch("time.sleep"):
            result = confirmations.confirm_acquire(None, timeout=5.0, poll_interval=0.001)
        self.assertTrue(result["success"])


class TestConfirmSelectJob(unittest.TestCase):
    def test_selected_after_settle(self):
        """Job is selected on first poll -> success."""
        jobs = [{"Name": "HiRes", "IsSelected": True}]
        with patch.object(readers, "get_jobs", return_value=jobs), patch("time.sleep"):
            result = confirm_select_job.confirm_select_job(
                None, job_name="HiRes", timeout=1.0, poll_interval=0.001
            )
        self.assertTrue(result["success"])

    def test_timeout_returns_failure(self):
        """Job never becomes selected -> failure."""
        jobs = [{"Name": "Other", "IsSelected": True}]
        with patch.object(readers, "get_jobs", return_value=jobs), patch("time.sleep"):
            result = confirm_select_job.confirm_select_job(
                None, job_name="HiRes", timeout=0.01, poll_interval=0.001
            )
        self.assertFalse(result["success"])

    def test_api_confirm_leg_never_touches_log_wait(self):
        jobs = [{"Name": "HiRes", "IsSelected": True}]
        with (
            patch.object(confirm_select_job.log_wait, "wait_for_selected_job_log") as log_wait_mock,
            patch.object(readers, "get_jobs", return_value=jobs),
            patch("time.sleep"),
        ):
            result = confirm_select_job.confirm_select_job(
                None, job_name="HiRes", timeout=1.0, poll_interval=0.001, command_started_at=100.0
            )

        self.assertTrue(result["success"])
        log_wait_mock.assert_not_called()

    # Log-source and hybrid confirmation behavior is covered by
    # tests/unit/test_select_job_confirm.py against the one policy point
    # (confirm_select_job.select_job_confirm_legs).

    def test_select_job_early_exit_pins_api_mode(self):
        client = make_client()
        client.PyApiSelectJobByName = make_api_obj()
        profile = profiles.StateReaderProfile(
            selected_job_confirm_source="api",
        )
        calls = []

        def fake_get_jobs(client, **kwargs):
            calls.append(kwargs)
            # A stale log would claim Overview is selected. The API says it is
            # not, so select_job must dispatch instead of early-exiting.
            if kwargs.get("mode") != "api":
                return [{"Name": "Overview", "IsSelected": True}]
            return [
                {"Name": "AF Job", "IsSelected": True},
                {"Name": "Overview", "IsSelected": False},
            ]

        dispatched = {"success": True, "confirmed": True, "message": "sent"}
        with (
            patch.object(profiles, "STATE_READERS", profile),
            patch.object(readers, "get_jobs", side_effect=fake_get_jobs),
            patch.object(commands, "_dispatch", return_value=dispatched) as dispatch_mock,
        ):
            result = commands.select_job(client, "Overview")

        self.assertEqual(result, dispatched)
        self.assertEqual(calls[0]["mode"], "api")
        dispatch_mock.assert_called_once()

    def test_select_job_log_confirmation_does_not_api_early_exit(self):
        client = make_client()
        client.PyApiSelectJobByName = make_api_obj()
        profile = profiles.StateReaderProfile(
            selected_job_confirm_source="log",
        )
        dispatched = {"success": True, "confirmed": True, "message": "sent"}
        with (
            patch.object(profiles, "STATE_READERS", profile),
            patch.object(confirm_select_job, "_selected_job_name_from_log", return_value=None),
            patch.object(readers, "get_jobs") as get_jobs,
            patch.object(commands, "_dispatch", return_value=dispatched) as dispatch_mock,
        ):
            result = commands.select_job(client, "Overview")

        self.assertEqual(result, dispatched)
        get_jobs.assert_not_called()
        dispatch_mock.assert_called_once()

    def test_select_job_primes_log_cluster_when_profile_enables_it(self):
        client = make_client()
        client.PyApiSelectJobByName = make_api_obj()
        profile = profiles.StateReaderProfile(
            selected_job_confirm_source="log",
            selected_job_log_prime_cluster=True,
        )
        jobs = [
            {"Name": "AF Job", "IsSelected": True},
            {"Name": "Overview", "IsSelected": False},
            {"Name": "HiRes", "IsSelected": False},
        ]
        bounded_calls = []

        def fake_api_jobs(client, profile):
            return jobs, "ok"

        def fake_bounded(client, fn, *, timeout_s):
            bounded_calls.append(timeout_s)
            return {"jobName": f"job-{len(bounded_calls)}"}, "ok"

        dispatched = {"success": True, "confirmed": True, "message": "sent"}
        with (
            patch.object(profiles, "STATE_READERS", profile),
            patch.object(confirm_select_job, "_selected_job_name_from_log", return_value=None),
            patch.object(confirm_select_job, "_selected_job_api_jobs", side_effect=fake_api_jobs),
            patch.object(confirm_select_job, "_bounded_api_read", side_effect=fake_bounded),
            patch.object(commands, "_dispatch", return_value=dispatched) as dispatch_mock,
        ):
            result = commands.select_job(client, "Overview")

        self.assertEqual(result, dispatched)
        self.assertEqual(
            bounded_calls,
            [
                profile.job_settings_timeout_s,
                profile.job_settings_timeout_s,
                profile.job_settings_timeout_s,
            ],
        )
        self.assertIsNone(dispatch_mock.call_args.kwargs["confirm_fn"])
        log_leg = dispatch_mock.call_args.kwargs["log_confirm_fn"]
        self.assertIsNotNone(log_leg)
        self.assertIsInstance(log_leg.args[1], float)


class TestHybridSelectJobApiLegEndToEnd(unittest.TestCase):
    """CF-01 regression: the hybrid race's api leg must actually reach the
    CAM client through the routed readers while the race is running.

    Wires ``commands.select_job`` through the real dispatch backbone and
    the real reader router — only the raw CAM reader and the log poll are
    faked. Before the fix, the race held the client's in-flight claim for
    the api leg's entire duration, so the leg's own routed ``get_jobs``
    reads were refused for their full timeout: the raw reader was never
    called inside the race and hybrid select_job was log-only in practice.
    """

    def test_api_leg_confirms_when_log_has_no_evidence(self):
        from navigator_expert.readers import log_wait

        client = make_client()
        api_obj = make_api_obj()
        client.PyApiSelectJobByName = api_obj
        fired = threading.Event()

        def fire(receipt_timeout):
            # Simulate LAS X processing: echo settles, job switches.
            client.PyApiCommandEcho.Model.Result = 1
            fired.set()
            return True

        api_obj.UpdateAwaitReceipt = MagicMock(side_effect=fire)

        raw_reads_after_fire = []

        def raw_get_jobs(c, **kwargs):
            if fired.is_set():
                raw_reads_after_fire.append(1)
                return [
                    {"Name": "Overview", "IsSelected": False},
                    {"Name": "HiRes", "IsSelected": True},
                ]
            return [
                {"Name": "Overview", "IsSelected": True},
                {"Name": "HiRes", "IsSelected": False},
            ]

        silent_log = log_wait.LogPollResult(
            success=False,
            value=None,
            matched_at=None,
            elapsed_s=0.05,
            attempts=1,
            reason="timeout",
            diagnostics={"last_reason": "timeout"},
        )
        profile = profiles.StateReaderProfile(
            selected_job_confirm_source="hybrid",
            selected_job_log_confirm_timeout_s=0.05,
            jobs_timeout_s=0.5,
        )
        with (
            patch.object(profiles, "STATE_READERS", profile),
            patch.object(readers.router.api_reader, "get_jobs", side_effect=raw_get_jobs),
            patch.object(confirm_select_job, "_selected_job_name_from_log", return_value=None),
            patch.object(
                confirm_select_job.log_wait,
                "wait_for_selected_job_log",
                return_value=silent_log,
            ),
        ):
            result = commands.select_job(client, "HiRes", poll_timeout=1.0)

        self.assertTrue(result["success"])
        self.assertTrue(
            result.get("confirmed"),
            "hybrid select_job did not confirm although the API could "
            "witness the transition (api leg starved inside the race?)",
        )
        self.assertGreater(
            len(raw_reads_after_fire),
            0,
            "the api leg's routed reads never reached the raw CAM reader",
        )
        messages = [entry["msg"] for entry in result["logs"]]
        self.assertTrue(any("confirmed by api leg" in m for m in messages))


class TestCommandReaderSafety(unittest.TestCase):
    def test_move_galvo_to_pixel_routes_selected_job_and_pins_metadata_to_api(self):
        client = make_client()
        calls = {"selected": [], "settings": [], "base_fov": []}

        def fake_get_selected_job(client, **kwargs):
            calls["selected"].append(kwargs)
            return {"Name": "Overview"}

        def fake_get_job_settings(client, job_name, **kwargs):
            calls["settings"].append((job_name, kwargs))
            return {"settings": "raw"}

        def fake_get_base_fov(client, job_name, **kwargs):
            calls["base_fov"].append((job_name, kwargs))
            return (0.000512, 0.000512)

        def fake_apply_lrp_change(client, template_xml, edit_fn):
            return {"success": True}

        with (
            patch.object(readers, "get_selected_job", side_effect=fake_get_selected_job),
            patch.object(readers, "get_job_settings", side_effect=fake_get_job_settings),
            patch.object(readers, "get_base_fov", side_effect=fake_get_base_fov),
            patch(
                "navigator_expert.utils.parse_tile_geometry",
                return_value={"pixel_w_um": 1.0, "pixels_x": 512},
            ),
            patch(
                "navigator_expert.experimental.lrp_edits.roi.galvo_pan_for_pixel",
                return_value=(0.0, 0.0),
            ),
            patch(
                "navigator_expert.scanfields.transaction.apply_lrp_change",
                side_effect=fake_apply_lrp_change,
            ),
        ):
            result = commands.move_galvo_to_pixel(client, 10, 20)

        self.assertTrue(result["success"])
        self.assertNotIn("mode", calls["selected"][0])
        self.assertEqual(calls["settings"][0][1]["mode"], "api")
        self.assertEqual(calls["base_fov"][0][1]["mode"], "api")


# =============================================================================
# 20. _make_log_entry
# =============================================================================


class TestMakeLogEntry(unittest.TestCase):
    def test_shape(self):
        entry = drv._make_log_entry("info", "test message")
        self.assertIn("ts", entry)
        self.assertEqual(entry["level"], "info")
        self.assertEqual(entry["msg"], "test message")
        self.assertIsInstance(entry["ts"], float)


if __name__ == "__main__":
    unittest.main()

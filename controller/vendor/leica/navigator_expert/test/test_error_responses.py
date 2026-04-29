"""
Comprehensive error response tests from error_discovery_v4 data.
================================================================
Replays every error message captured by error_discovery_v4 (run on real
STELLARIS hardware with driver v2.0.0 + UpdateSync) through the v6
driver's error detection and classification pipeline.

Tests verify:
1. ``_check_api_error`` correctly detects each error from the echo model
2. ``_is_transient_error`` correctly classifies each error
3. ``_default_error_check`` returns correct structured result
4. ``_fire_block`` with echo poll catches delayed versions of each error

Error messages sourced from:
    error_discovery_final_20260224_144448.json (60 probes, driver v2.0.0)
"""

import time
import threading
import unittest
from unittest.mock import MagicMock, patch

import lasx.core
import lasx.errors


# =============================================================================
# Error catalog from discovery data
# =============================================================================
# Each entry: (echo_error_msg, result_code, has_error, expected_transient,
#              expected_detection, description)
#
# expected_detection:
#   "error"   — _check_api_error should return an error dict
#   "warning" — _check_api_error should return None (warning = success)
#   "success" — _check_api_error should return None

# -- Permanent errors: "out of range" pattern --
OUT_OF_RANGE_ERRORS = [
    ("CAM Command >> CamCommandSetZoomByJobName >> Error on command "
     "The zoom parameter (0.000) is out of range. Value has to be "
     "between 0.750 and 48.000",
     2, True, False, "error", "R01: Zoom=0"),

    ("CAM Command >> CamCommandSetZoomByJobName >> Error on command "
     "The zoom parameter (-5.000) is out of range. Value has to be "
     "between 0.750 and 48.000",
     2, True, False, "error", "R02: Zoom=-5"),

    ("CAM Command >> CamCommandSetZoomByJobName >> Error on command "
     "The zoom parameter (999.000) is out of range. Value has to be "
     "between 0.750 and 48.000",
     2, True, False, "error", "R03: Zoom=999"),

    ("CAM Command >> CamCommandSetZoomByJobName >> Error on command "
     "The zoom parameter (0.001) is out of range. Value has to be "
     "between 0.750 and 48.000",
     2, True, False, "error", "R04: Zoom=0.001"),

    ("CamCommandSetScanSpeedByJobName: The speed parameter (0) is out "
     "of range. Value for this setting has to be between 1 and 2600",
     2, True, False, "error", "R05: Speed=0"),

    ("CamCommandSetScanSpeedByJobName: The speed parameter (-100) is "
     "out of range. Value for this setting has to be between 1 and 2600",
     2, True, False, "error", "R06: Speed=-100"),

    ("CamCommandSetScanSpeedByJobName: The speed parameter (99999) is "
     "out of range. Value for this setting has to be between 1 and 2600",
     2, True, False, "error", "R07: Speed=99999"),

    ("CamCommandSetScanFieldRotationByJobName: The scan field rotation "
     "parameter (999.0) is out of range. Value has to be between "
     "-100.0 and 100.0",
     2, True, False, "error", "R09: Rotation=999"),

    ("CamCommandSetScanFieldRotationByJobName: The scan field rotation "
     "parameter (-999.0) is out of range. Value has to be between "
     "-100.0 and 100.0",
     2, True, False, "error", "R10: Rotation=-999"),

    ("CAM Command >> CamCommandSetDetectorGainByJobName >> Error on "
     "command The gain parameter (-1.000) is out of range. Value has "
     "to be between 2.500 and 2.500",
     2, True, False, "error", "R14: Gain=-1"),

    ("CAM Command >> CamCommandSetDetectorGainByJobName >> Error on "
     "command The gain parameter (99999.000) is out of range. Value "
     "has to be between 2.500 and 2.500",
     2, True, False, "error", "R15: Gain=99999"),

    ("CAM Command >> CamCommandSetLaserIntensityByJobName >> Error on "
     "command The intensity parameter (-0.5000) is out of range. Value "
     "has to be between 0.0 and 1.0",
     2, True, False, "error", "R16: Laser=-0.5"),

    ("CAM Command >> CamCommandSetLaserIntensityByJobName >> Error on "
     "command The intensity parameter (5.0000) is out of range. Value "
     "has to be between 0.0 and 1.0",
     2, True, False, "error", "R17: Laser=5.0"),
]

# -- Permanent errors: "is invalid" pattern --
IS_INVALID_ERRORS = [
    ("CAM Command >> CamCommandSetFrameAccumulationByJobName >> Error "
     "on command The frame accumulation parameter (0) is invalid. "
     "Value must be an element from the following list: "
     "[1, 2, 3, 4, 6, 8, 9, 10, 12, 14, 15, 16]",
     2, True, False, "error", "R19: FrameAcc=0"),

    ("CAM Command >> CamCommandSetFrameAccumulationByJobName >> Error "
     "on command The frame accumulation parameter (99999) is invalid. "
     "Value must be an element from the following list: "
     "[1, 2, 3, 4, 6, 8, 9, 10, 12, 14, 15, 16]",
     2, True, False, "error", "R24: FrameAcc=99999"),

    ("CamCommandSetFrameAverageByJobName: The frame average parameter "
     "(99999) is invalid. Value must be an element from the following "
     "list: [1, 2, 3, 4, 6, 8, 10, 12, 14, 16, 20, 25, 30, 40, 50, 64]",
     2, True, False, "error", "R21: FrameAvg=99999"),

    ("CamCommandSetLineAccumulationByJobName: The line accumulation "
     "parameter (99999) is invalid. Value must be an element from the "
     "following list: [1, 2, 3, 4, 6, 8, 9, 10, 12, 14, 15, 16]",
     2, True, False, "error", "R25: LineAcc=99999"),

    ("CamCommandSetLineAverageByJobName: The line average parameter "
     "(99999) is invalid. Value must be an element from the following "
     "list: [1, 2, 4, 8",
     2, True, False, "error", "R23: LineAvg=99999 (truncated)"),
]

# -- Permanent errors: "invalid block identifier" pattern --
INVALID_BLOCK_ERRORS = [
    ("CamCommandSetZoomByJobName invalid block identifier",
     2, True, False, "error", "F01: Zoom on fake job"),

    ("CamCommandSetScanSpeedByJobName invalid block identifier",
     2, True, False, "error", "F02: Speed on fake job"),

    ("CamCommandSetPinholeAUByJobName invalid block identifier",
     2, True, False, "error", "F03: Pinhole on fake job"),

    ("[CommandEcho] CamCommandSetZoomByJobName invalid block identifier",
     2, True, False, "error", "D01: SetZoom empty job"),
]

# -- Permanent errors: invalid reference patterns --
INVALID_REF_ERRORS = [
    ("CAM Command >> CamCommandSetDetectorGainByJobName >> Error on "
     "command Invalid detector beamRoute",
     2, True, False, "error", "F07: Detector gain fake BR"),

    ("CAM Command >> CamCommandSetDetectorActiveByJobName >> Error on "
     "command Invalid detector beam route: . ",
     2, True, False, "error", "F08: Detector activate fake BR"),

    ("CAM Command >> CamCommandSetLaserIntensityByJobName >> Error on "
     "command Invalid light source beamRoute",
     2, True, False, "error", "F09: Laser intensity fake BR"),

    ("CAM Command >> CamCommandSetLaserShutterByJobName >> Error on "
     "command invalid light source beamroute: ",
     2, True, False, "error", "F10: Laser shutter fake BR"),

    ("CAM Command >> CamCommandAddOrRemoveLaserLineByJobName >> Error "
     "on command The line index parameter (99) is out of range. Value "
     "has to be between 0 and 0",
     2, True, False, "error", "F11: Add laser idx=99"),

    ("CamCommandSetFrameAverageByJobName: invalid setting index",
     2, True, False, "error", "F06: FrameAvg setting_index=99"),
]

# -- Permanent errors: "not defined" pattern --
NOT_DEFINED_ERRORS = [
    ("CamCommand Parameter TotallyFakeCommand is not defined.",
     2, True, False, "error", "D03: Fake command"),

    ("CamCommand Parameter  is not defined.",
     2, True, False, "error", "D04: Empty command"),
]

# -- Permanent errors: other --
OTHER_PERMANENT_ERRORS = [
    ("CamCommandSetTimeDefinitionByJobName: Cannot set time definition "
     "for scan mode xyz",
     2, True, False, "error", "B14: Time def on xyz mode"),
]

# -- Warning errors: "has been adjusted" (treated as success) --
WARNING_ERRORS = [
    ("CAM Command >> SetPinholeAUByJobName >> Warning on command "
     "The requested pinhole airy (0.000) has been adjusted to 0.251",
     1, True, True, "warning", "R11: Pinhole=0"),

    ("CAM Command >> SetPinholeAUByJobName >> Warning on command "
     "The requested pinhole airy (-1.000) has been adjusted to 0.251",
     1, True, True, "warning", "R12: Pinhole=-1"),

    ("CAM Command >> SetPinholeAUByJobName >> Warning on command "
     "The requested pinhole airy (999.000) has been adjusted to 2.512",
     1, True, True, "warning", "R13: Pinhole=999"),
]

# -- Transient errors: "being scanned" pattern --
TRANSIENT_ERRORS = [
    ("CAM Command >> CamCommandSetObjectiveSlotByJobName >> Error on "
     "command The objective cannot be set while the block is being scanned",
     2, True, True, "error", "H04: Objective during scan"),

    ("CamCommandSetScanSpeedByJobName: The scan speed cannot be set "
     "while the block is being scanned",
     2, True, True, "error", "H02: Speed during scan"),
]

# All errors combined for parametric tests
ALL_ERRORS = (OUT_OF_RANGE_ERRORS + IS_INVALID_ERRORS +
              INVALID_BLOCK_ERRORS + INVALID_REF_ERRORS +
              NOT_DEFINED_ERRORS + OTHER_PERMANENT_ERRORS +
              WARNING_ERRORS + TRANSIENT_ERRORS)

ALL_REAL_ERRORS = (OUT_OF_RANGE_ERRORS + IS_INVALID_ERRORS +
                   INVALID_BLOCK_ERRORS + INVALID_REF_ERRORS +
                   NOT_DEFINED_ERRORS + OTHER_PERMANENT_ERRORS +
                   TRANSIENT_ERRORS)

ALL_PERMANENT = (OUT_OF_RANGE_ERRORS + IS_INVALID_ERRORS +
                 INVALID_BLOCK_ERRORS + INVALID_REF_ERRORS +
                 NOT_DEFINED_ERRORS + OTHER_PERMANENT_ERRORS)


# =============================================================================
# Helpers
# =============================================================================

def make_echo(has_error=False, error="", result_code=1):
    echo = MagicMock()
    echo.HasError = has_error
    echo.Error = error
    echo.Result = result_code
    return echo


def make_client(echo=None):
    client = MagicMock()
    if echo is None:
        echo = make_echo()
    client.PyApiCommandEcho.Model = echo
    return client


def make_api_obj():
    api_obj = MagicMock()
    api_obj.Model = MagicMock()
    api_obj.UpdateAwaitReceipt = MagicMock(return_value=True)
    return api_obj


def _idle_pre_check():
    return {"success": True, "logs": []}


# =============================================================================
# 1. _check_api_error — detection with real error messages
# =============================================================================

class TestCheckApiErrorDiscovery(unittest.TestCase):
    """Verify _check_api_error detects every error from the discovery data."""

    def test_all_real_errors_detected(self):
        """Every non-warning error should be detected by _check_api_error."""
        for msg, result_code, has_error, _, expected, desc in ALL_REAL_ERRORS:
            with self.subTest(desc=desc):
                echo = make_echo(has_error=has_error, error=msg,
                                 result_code=result_code)
                client = make_client(echo)

                err = lasx.errors._check_api_error(client)
                self.assertIsNotNone(err,
                    f"Error not detected: {desc}\n  msg: {msg[:80]}")
                self.assertEqual(err["error"], msg)

    def test_all_warnings_accepted(self):
        """Warning messages (HasError + 'warning' in msg) → success."""
        for msg, result_code, has_error, _, expected, desc in WARNING_ERRORS:
            with self.subTest(desc=desc):
                echo = make_echo(has_error=has_error, error=msg,
                                 result_code=result_code)
                client = make_client(echo)

                err = lasx.errors._check_api_error(client)
                self.assertIsNone(err,
                    f"Warning should be accepted: {desc}\n  msg: {msg[:80]}")

    def test_out_of_range_errors(self):
        """All 'out of range' errors detected with correct error string."""
        for msg, result_code, has_error, _, _, desc in OUT_OF_RANGE_ERRORS:
            with self.subTest(desc=desc):
                echo = make_echo(has_error=has_error, error=msg,
                                 result_code=result_code)
                client = make_client(echo)
                err = lasx.errors._check_api_error(client)
                self.assertIsNotNone(err)
                self.assertIn("out of range", err["error"].lower())

    def test_invalid_block_identifier_errors(self):
        """All 'invalid block identifier' errors detected."""
        for msg, result_code, has_error, _, _, desc in INVALID_BLOCK_ERRORS:
            with self.subTest(desc=desc):
                echo = make_echo(has_error=has_error, error=msg,
                                 result_code=result_code)
                client = make_client(echo)
                err = lasx.errors._check_api_error(client)
                self.assertIsNotNone(err)
                self.assertIn("invalid block identifier",
                              err["error"].lower())


# =============================================================================
# 2. _is_transient_error — classification with real error messages
# =============================================================================

class TestErrorClassificationDiscovery(unittest.TestCase):
    """Verify _is_transient_error classifies every discovery error correctly."""

    def test_all_permanent_errors_classified(self):
        """Every permanent error should be classified as non-transient."""
        for msg, _, _, expected_transient, _, desc in ALL_PERMANENT:
            with self.subTest(desc=desc):
                result = lasx.errors._is_transient_error(msg)
                self.assertFalse(result,
                    f"Should be permanent: {desc}\n  msg: {msg[:80]}")

    def test_all_transient_errors_classified(self):
        """Every transient error should be classified as transient."""
        for msg, _, _, expected_transient, _, desc in TRANSIENT_ERRORS:
            with self.subTest(desc=desc):
                result = lasx.errors._is_transient_error(msg)
                self.assertTrue(result,
                    f"Should be transient: {desc}\n  msg: {msg[:80]}")

    def test_warning_messages_classification(self):
        """Warning messages classified as permanent (has 'has been adjusted').

        Note: warnings are permanent in classification but the driver
        treats them as success via _check_api_error's warning check.
        """
        for msg, _, _, _, _, desc in WARNING_ERRORS:
            with self.subTest(desc=desc):
                result = lasx.errors._is_transient_error(msg)
                self.assertFalse(result,
                    f"Warnings should be classified as permanent: {desc}")


# =============================================================================
# 3. _default_error_check — structured result with real errors
# =============================================================================

class TestDefaultErrorCheckDiscovery(unittest.TestCase):
    """Verify _default_error_check returns correct shape for each error."""

    def test_permanent_error_shape(self):
        """Permanent errors: success=False, transient=False."""
        for msg, result_code, has_error, _, _, desc in ALL_PERMANENT:
            with self.subTest(desc=desc):
                echo = make_echo(has_error=has_error, error=msg,
                                 result_code=result_code)
                client = make_client(echo)
                result = lasx.errors._default_error_check(client)

                self.assertFalse(result["success"], f"Should fail: {desc}")
                self.assertFalse(result["transient"],
                    f"Should be permanent: {desc}")
                self.assertEqual(result["error"], msg)

    def test_transient_error_shape(self):
        """Transient errors: success=False, transient=True."""
        for msg, result_code, has_error, _, _, desc in TRANSIENT_ERRORS:
            with self.subTest(desc=desc):
                echo = make_echo(has_error=has_error, error=msg,
                                 result_code=result_code)
                client = make_client(echo)
                result = lasx.errors._default_error_check(client)

                self.assertFalse(result["success"], f"Should fail: {desc}")
                self.assertTrue(result["transient"],
                    f"Should be transient: {desc}")

    def test_warning_success_shape(self):
        """Warnings: success=True (treated as accepted)."""
        for msg, result_code, has_error, _, _, desc in WARNING_ERRORS:
            with self.subTest(desc=desc):
                echo = make_echo(has_error=has_error, error=msg,
                                 result_code=result_code)
                client = make_client(echo)
                result = lasx.errors._default_error_check(client)

                self.assertTrue(result["success"],
                    f"Warning should be success: {desc}")


# =============================================================================
# 4. Delayed error detection through _fire_block with echo poll
# =============================================================================

class TestDelayedErrorDetection(unittest.TestCase):
    """Verify _fire_block + echo poll catches delayed real errors."""

    def _run_delayed_fire(self, msg, result_code, has_error, delay=0.03,
                          max_retries=0):
        """Fire with a delayed echo population and return the result."""
        echo = make_echo(result_code=0)
        client = make_client(echo)
        api_obj = make_api_obj()

        def mock_fire(api_obj_arg, **kwargs):
            def populate():
                echo.HasError = has_error
                echo.Error = msg
                echo.Result = result_code

            timer = threading.Timer(delay, populate)
            timer.daemon = True
            timer.start()
            return True

        with patch.object(lasx.core, '_fire_with_receipt',
                          side_effect=mock_fire):
            return lasx.core._fire_block(
                client, api_obj, "Test",
                setup_fn=lambda m: None,
                pre_check_fn=_idle_pre_check,
                max_retries=max_retries,
            )

    def test_delayed_permanent_errors_caught(self):
        """All permanent errors arriving after 30ms delay are caught."""
        for msg, result_code, has_error, _, _, desc in ALL_PERMANENT:
            with self.subTest(desc=desc):
                r = self._run_delayed_fire(msg, result_code, has_error)
                self.assertFalse(r["success"],
                    f"Delayed permanent error not caught: {desc}")
                self.assertIn("API Error", r["message"])

    def test_delayed_transient_errors_caught(self):
        """Transient errors arriving after delay are caught (no retry)."""
        for msg, result_code, has_error, _, _, desc in TRANSIENT_ERRORS:
            with self.subTest(desc=desc):
                r = self._run_delayed_fire(msg, result_code, has_error,
                                           max_retries=0)
                self.assertFalse(r["success"],
                    f"Delayed transient error not caught: {desc}")

    def test_delayed_transient_errors_retried(self):
        """Transient errors arriving after delay trigger retry."""
        for msg, result_code, has_error, _, _, desc in TRANSIENT_ERRORS:
            with self.subTest(desc=desc):
                echo = make_echo(result_code=0)
                client = make_client(echo)
                api_obj = make_api_obj()
                call_count = [0]

                def mock_fire(api_obj_arg, **kwargs):
                    call_count[0] += 1
                    if call_count[0] == 1:
                        # First: delayed transient error
                        def populate():
                            echo.HasError = has_error
                            echo.Error = msg
                            echo.Result = result_code

                        timer = threading.Timer(0.02, populate)
                        timer.daemon = True
                        timer.start()
                    else:
                        # Second: immediate success
                        echo.HasError = False
                        echo.Error = ""
                        echo.Result = 1
                    return True

                with patch.object(lasx.core, '_fire_with_receipt',
                                  side_effect=mock_fire):
                    r = lasx.core._fire_block(
                        client, api_obj, "Test",
                        setup_fn=lambda m: None,
                        pre_check_fn=_idle_pre_check,
                        max_retries=2,
                    )

                self.assertTrue(r["success"],
                    f"Should succeed after retry: {desc}")
                self.assertEqual(r["attempts"], 2,
                    f"Should have retried: {desc}")

    def test_delayed_warnings_pass_through(self):
        """Warning messages arriving after delay are treated as success."""
        for msg, result_code, has_error, _, _, desc in WARNING_ERRORS:
            with self.subTest(desc=desc):
                r = self._run_delayed_fire(msg, result_code, has_error)
                self.assertTrue(r["success"],
                    f"Warning should pass: {desc}")


# =============================================================================
# 5. Error message format coverage
# =============================================================================

class TestErrorMessageFormats(unittest.TestCase):
    """Verify all 4 LAS X error message formats are handled."""

    def test_format_a_cam_command_arrows(self):
        """Format A: 'CAM Command >> CmdName >> Error on command msg'"""
        msg = ("CAM Command >> CamCommandSetZoomByJobName >> Error on "
               "command The zoom parameter (0.000) is out of range. "
               "Value has to be between 0.750 and 48.000")
        echo = make_echo(has_error=True, error=msg, result_code=2)
        client = make_client(echo)
        err = lasx.errors._check_api_error(client)
        self.assertIsNotNone(err)
        self.assertFalse(lasx.errors._is_transient_error(msg))

    def test_format_b_colon_delimited(self):
        """Format B: 'CmdName: msg'"""
        msg = ("CamCommandSetScanSpeedByJobName: The speed parameter "
               "(0) is out of range. Value for this setting has to be "
               "between 1 and 2600")
        echo = make_echo(has_error=True, error=msg, result_code=2)
        client = make_client(echo)
        err = lasx.errors._check_api_error(client)
        self.assertIsNotNone(err)
        self.assertFalse(lasx.errors._is_transient_error(msg))

    def test_format_c_no_delimiter(self):
        """Format C: 'CmdName msg' (no delimiter)"""
        msg = "CamCommandSetZoomByJobName invalid block identifier"
        echo = make_echo(has_error=True, error=msg, result_code=2)
        client = make_client(echo)
        err = lasx.errors._check_api_error(client)
        self.assertIsNotNone(err)
        self.assertFalse(lasx.errors._is_transient_error(msg))

    def test_format_d_bracket_prefix(self):
        """Format D: '[CommandEcho] CamCommand Parameter X not defined.'"""
        msg = ("[CommandEcho] CamCommand Parameter TotallyFakeCommand "
               "is not defined.")
        echo = make_echo(has_error=True, error=msg, result_code=2)
        client = make_client(echo)
        err = lasx.errors._check_api_error(client)
        self.assertIsNotNone(err)
        self.assertFalse(lasx.errors._is_transient_error(msg))

    def test_format_warning_cam_command(self):
        """Warning format: 'CAM Command >> CmdName >> Warning on command msg'"""
        msg = ("CAM Command >> SetPinholeAUByJobName >> Warning on "
               "command The requested pinhole airy (0.000) has been "
               "adjusted to 0.251")
        echo = make_echo(has_error=True, error=msg, result_code=1)
        client = make_client(echo)
        err = lasx.errors._check_api_error(client)
        self.assertIsNone(err, "Warnings should be treated as success")


# =============================================================================
# 6. Pattern coverage — every classification pattern hit
# =============================================================================

class TestPatternCoverage(unittest.TestCase):
    """Verify each pattern in _PERMANENT_PATTERNS and _TRANSIENT_PATTERNS
    is hit by at least one real error message from the discovery data."""

    def test_permanent_pattern_out_of_range(self):
        for msg, _, _, _, _, _ in OUT_OF_RANGE_ERRORS:
            self.assertIn("out of range", msg.lower())
            self.assertFalse(lasx.errors._is_transient_error(msg))

    def test_permanent_pattern_is_invalid(self):
        for msg, _, _, _, _, _ in IS_INVALID_ERRORS:
            self.assertIn("is invalid", msg.lower())
            self.assertFalse(lasx.errors._is_transient_error(msg))

    def test_permanent_pattern_invalid_block_identifier(self):
        for msg, _, _, _, _, _ in INVALID_BLOCK_ERRORS:
            self.assertIn("invalid block identifier", msg.lower())
            self.assertFalse(lasx.errors._is_transient_error(msg))

    def test_permanent_pattern_invalid_detector(self):
        msgs = [
            "CAM Command >> CamCommandSetDetectorGainByJobName >> "
            "Error on command Invalid detector beamRoute",
            "CAM Command >> CamCommandSetDetectorActiveByJobName >> "
            "Error on command Invalid detector beam route: . ",
        ]
        for msg in msgs:
            self.assertIn("invalid detector", msg.lower())
            self.assertFalse(lasx.errors._is_transient_error(msg))

    def test_permanent_pattern_invalid_light_source(self):
        msgs = [
            "CAM Command >> CamCommandSetLaserIntensityByJobName >> "
            "Error on command Invalid light source beamRoute",
            "CAM Command >> CamCommandSetLaserShutterByJobName >> "
            "Error on command invalid light source beamroute: ",
        ]
        for msg in msgs:
            self.assertIn("invalid light source", msg.lower())
            self.assertFalse(lasx.errors._is_transient_error(msg))

    def test_permanent_pattern_not_defined(self):
        for msg, _, _, _, _, _ in NOT_DEFINED_ERRORS:
            self.assertIn("not defined", msg.lower())
            self.assertFalse(lasx.errors._is_transient_error(msg))

    def test_permanent_pattern_has_been_adjusted(self):
        for msg, _, _, _, _, _ in WARNING_ERRORS:
            self.assertIn("has been adjusted", msg.lower())
            # Note: classified as permanent, but treated as warning/success
            self.assertFalse(lasx.errors._is_transient_error(msg))

    def test_transient_pattern_being_scanned(self):
        for msg, _, _, _, _, _ in TRANSIENT_ERRORS:
            self.assertIn("being scanned", msg.lower())
            self.assertTrue(lasx.errors._is_transient_error(msg))

    def test_transient_pattern_cannot_be_set_while(self):
        msg = ("CamCommandSetScanSpeedByJobName: The scan speed cannot "
               "be set while the block is being scanned")
        self.assertIn("cannot be set while", msg.lower())
        self.assertTrue(lasx.errors._is_transient_error(msg))


# =============================================================================
# 7. D02 scenario — HasError without Result change
# =============================================================================

class TestD02Scenario(unittest.TestCase):
    """Probe D02: UpdateSync returned True but echo had HasError=True.

    This tests the case where LAS X sets HasError without necessarily
    changing Result from NotDefined (0). The echo poll must detect
    settlement via HasError, not just Result.
    """

    def test_has_error_only_detected_by_check(self):
        """_check_api_error detects HasError=True even with Result=0."""
        echo = make_echo(result_code=0, has_error=True,
                         error="CamCommandSetZoomByJobName "
                               "invalid block identifier")
        client = make_client(echo)

        # Result=0 but HasError=True → _check_api_error uses the
        # "Can't read Result enum" fallback path or NotDefined path
        # Either way, HasError=True should be caught
        err = lasx.errors._check_api_error(client)
        # With Result=0 (NotDefined) and HasError=False: returns None
        # With Result=0 (NotDefined) and HasError=True: should return error
        # Looking at _check_api_error: result_code=0 is not 3, not 2,
        # and echo.HasError is True → hits the "HasError without warning" branch
        self.assertIsNotNone(err,
            "HasError=True with Result=0 should be detected")

    def test_has_error_only_delayed_caught_by_poll(self):
        """Delayed HasError (Result stays 0) caught by fire block."""
        echo = make_echo(result_code=0)
        client = make_client(echo)
        api_obj = make_api_obj()

        def mock_fire(api_obj_arg, **kwargs):
            def populate():
                echo.HasError = True
                echo.Error = ("CamCommandSetZoomByJobName "
                              "invalid block identifier")
                # Result stays at 0

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

        self.assertFalse(r["success"],
                         "HasError-only delayed error should be caught")


if __name__ == "__main__":
    unittest.main()

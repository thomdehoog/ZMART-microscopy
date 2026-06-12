"""
Error classification and API error checking.
=============================================
Two responsibilities, both related to post-fire error handling:

1. **Classification** — ``_is_transient_error`` decides whether an error
   message from LAS X is transient (retry-worthy) or permanent (fail
   immediately). Pattern lists are checked in priority order: permanent
   patterns first, then transient patterns, unknown defaults to permanent.

2. **Detection** — ``_check_api_error`` reads the ``PyApiCommandEcho``
   model after a command fire and returns raw error information.
   ``_default_error_check`` wraps this into the structured result dict
   that the fire block expects from any ``error_check_fn``.

Import restrictions: only runtime utilities and stdlib. Nothing from commands,
profiles, prechecks, or confirmations.
"""

import logging

from .utils import _make_log_entry

log = logging.getLogger(__name__)


# =============================================================================
# Error classification
# =============================================================================

_PERMANENT_PATTERNS = [
    "out of range",
    "is invalid",
    "invalid block identifier",
    "invalid detector",
    "invalid light source",
    "not defined",
    "not found",
    "has been adjusted",
    "not implemented",
]

_TRANSIENT_PATTERNS = [
    "being scanned",
    "cannot be set while",
    "block is being",
    "busy",
    "locked",
    "timeout",
    "timed out",
]


def _is_transient_error(msg):
    """Classify an error message as transient or permanent.

    Args:
        msg: Error message string from LAS X.

    Returns:
        True if transient (retry-worthy), False if permanent.
        Permanent patterns are checked first and take priority.
    """
    if not msg:
        return False
    lower = msg.lower()
    # Permanent patterns checked first — they take priority
    for pat in _PERMANENT_PATTERNS:
        if pat in lower:
            return False
    for pat in _TRANSIENT_PATTERNS:
        if pat in lower:
            return True
    # Unknown errors → treated as permanent (safe default)
    log.warning("Unclassified error (treated as permanent): %s", msg)
    return False


# =============================================================================
# Error checking — raw API echo inspection
# =============================================================================

_RESULT_MAP = {0: "NotDefined", 1: "Success", 2: "Failure", 3: "NotImplemented"}


def _read_echo_details(echo):
    """Read additional diagnostic attributes from the echo model.

    LAS X may populate these with context about silent rejections or
    parameter adjustments. Returns a dict of non-empty attribute values.
    """
    details = {}
    for attr in (
        "Description",
        "ErrorDescription",
        "Message",
        "ErrorMessage",
        "Warning",
        "Info",
        "Details",
    ):
        try:
            val = getattr(echo, attr, None)
            if val is not None and val != "":
                details[attr] = str(val)
        except Exception:
            pass
    return details


def _check_api_error(client):
    """Check PyApiCommandEcho for errors after a fire.

    Reads the echo model and interprets the Result enum and HasError flag.
    Warnings (HasError with "warning" in the message) are treated as
    success — LAS X uses these for non-fatal parameter adjustments.
    Additional echo attributes are captured for diagnostics.

    Args:
        client: The connected LAS X API client.

    Returns:
        None on success, or {"error": str, "result": str, "result_code": int,
        "details": dict} on failure.
    """
    echo = client.PyApiCommandEcho.Model
    details = _read_echo_details(echo)

    try:
        result_code = int(echo.Result)
    except Exception:
        # Can't read Result enum
        if echo.HasError:
            error_msg = echo.Error if echo.Error else "(no message)"
            return {"error": error_msg, "result": "Unknown", "result_code": -1, "details": details}
        return None

    result_str = _RESULT_MAP.get(result_code, "Unknown")
    error_msg = echo.Error if echo.Error else ""

    # NotImplemented → always error
    if result_code == 3:
        if not error_msg:
            error_msg = "Command not implemented on this hardware"
        return {
            "error": error_msg,
            "result": result_str,
            "result_code": result_code,
            "details": details,
        }

    # HasError with "warning" → success (non-fatal adjustment)
    if echo.HasError and "warning" in error_msg.lower():
        if details:
            log.debug("Warning accepted with details: %s", details)
        return None

    # HasError without warning → error
    if echo.HasError:
        if not error_msg:
            error_msg = "(HasError set, no message)"
        return {
            "error": error_msg,
            "result": result_str,
            "result_code": result_code,
            "details": details,
        }

    # Failure result code without HasError
    if result_code == 2:
        return {
            "error": error_msg or "Unknown failure",
            "result": result_str,
            "result_code": result_code,
            "details": details,
        }

    # Success or NotDefined with no error
    if details:
        log.debug("Echo details on success: %s", details)
    return None


# =============================================================================
# Default error_check_fn — structured adapter for the fire block
# =============================================================================


def _default_error_check(client):
    """Check for API errors and return a structured result dict.

    This is the default ``error_check_fn`` used by the fire block. It
    wraps ``_check_api_error`` and ``_is_transient_error`` into the
    standard error-check return shape. The fire block reads
    ``result["success"]`` to decide whether the command succeeded, and
    ``result["transient"]`` to decide whether a retry is warranted.

    99% of commands use this default. Only override when a command needs
    custom error interpretation (e.g. treating a specific permanent error
    as acceptable).

    Args:
        client: The connected LAS X API client.

    Returns:
        {
            "success": True,
            "error": None,
            "transient": None,
            "logs": [...]
        }
        on success, or:
        {
            "success": False,
            "error": str,
            "transient": bool,
            "logs": [...]
        }
        on failure.
    """
    logs = []
    err = _check_api_error(client)

    if err is None:
        return {"success": True, "error": None, "transient": None, "logs": logs}

    error_msg = err.get("error", "")
    details = err.get("details", {})
    transient = _is_transient_error(error_msg)
    level = "warning" if transient else "error"

    log_msg = f"API error: {error_msg}"
    if details:
        log_msg += f" | details: {details}"
    logs.append(_make_log_entry(level, log_msg))

    return {
        "success": False,
        "error": error_msg,
        "transient": transient,
        "logs": logs,
    }

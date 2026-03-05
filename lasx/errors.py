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

Import restrictions: only ``util`` and stdlib. Nothing from ``core``,
``commands``, ``profiles``, ``checks``, or ``confirm``.
"""

import logging

from .util import _make_log_entry

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


def _check_api_error(client):
    """Check PyApiCommandEcho for errors after a fire.

    Reads the echo model and interprets the Result enum and HasError flag.
    Warnings (HasError with "warning" in the message) are treated as
    success — LAS X uses these for non-fatal parameter adjustments.

    Args:
        client: The connected LAS X API client.

    Returns:
        None on success, or {"error": str, "result": str, "result_code": int}
        on failure.
    """
    echo = client.PyApiCommandEcho.Model

    try:
        result_code = int(echo.Result)
    except Exception:
        # Can't read Result enum
        if echo.HasError:
            return {"error": echo.Error, "result": "Unknown", "result_code": -1}
        return None

    result_str = _RESULT_MAP.get(result_code, "Unknown")
    error_msg = echo.Error if echo.Error else ""

    # NotImplemented → always error
    if result_code == 3:
        if not error_msg:
            error_msg = "Command not implemented on this hardware"
        return {"error": error_msg, "result": result_str, "result_code": result_code}

    # HasError with "warning" → success (non-fatal adjustment)
    if echo.HasError and "warning" in error_msg.lower():
        return None

    # HasError without warning → error
    if echo.HasError:
        return {"error": error_msg, "result": result_str, "result_code": result_code}

    # Failure result code without HasError
    if result_code == 2:
        return {"error": error_msg or "Unknown failure",
                "result": result_str, "result_code": result_code}

    # Success or NotDefined with no error
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
    transient = _is_transient_error(error_msg)
    level = "warning" if transient else "error"
    logs.append(_make_log_entry(level, f"API error: {error_msg}"))

    return {
        "success": False,
        "error": error_msg,
        "transient": transient,
        "logs": logs,
    }

"""
Utility functions.
==================
Shared low-level helpers with no domain knowledge: safe type conversion,
unit conversion (the driver speaks micrometers publicly; ZEN API speaks SI
meters on the wire), timing-envelope construction, and structured log entries.

Every function here is a pure utility -- no imports from other driver modules,
no knowledge of ZEN API, gRPC, or hardware.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import time

# ---------------------------------------------------------------------------
# Configurable timeouts (seconds). Import and override to tune per instrument.
# ---------------------------------------------------------------------------
CONFIRM_POLL_S = 3.0  # Per-attempt readback poll window (NOT a timeout): poll the
# readback for this long, then re-fire and poll again up to max_confirm_attempts;
# exhaustion returns unconfirmed, never a hard fail.
CALL_TIMEOUT = 30.0  # Default per-RPC deadline (a true timeout: expiry is a
# transient transport failure, retried by the fire block).

# ---------------------------------------------------------------------------
# Unit conversion. Public API is micrometers; ZEN API request/response is meters.
# Conversion happens ONLY at the request builder and the reader parser.
# ---------------------------------------------------------------------------
M_PER_UM = 1e-6
_UNIT_TO_UM = {"um": 1.0, "µm": 1.0, "μm": 1.0, "mm": 1000.0, "m": 1e6}


def to_um(value: float, unit: str = "um") -> float:
    """Convert a length in the given unit ('um'|'mm'|'m') to micrometers."""
    try:
        return float(value) * _UNIT_TO_UM[unit]
    except KeyError as exc:
        raise ValueError(f"Unknown unit '{unit}'. Use: 'um', 'mm', or 'm'") from exc


def um_to_m(um: float) -> float:
    """Micrometers -> meters (the on-the-wire unit)."""
    return float(um) * M_PER_UM


def m_to_um(m: float) -> float:
    """Meters (on the wire) -> micrometers (public unit)."""
    return float(m) * 1e6


def _safe_float(val, default=None):
    """Convert val to float. Returns default on failure or None input."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


# =============================================================================
# Structured log entries
# =============================================================================


def _make_log_entry(level: str, msg: str) -> dict:
    """Build a timestamped log entry dict.

    Every pluggable function in the pipeline accumulates these in its ``logs``
    list; the backbone collects them into one ordered trace so the caller has
    full visibility into what happened.

    Args:
        level: One of "debug", "info", "warning", "error".
        msg: Human-readable log message.

    Returns:
        {"ts": float, "level": str, "msg": str}
    """
    return {"ts": time.time(), "level": level, "msg": msg}


# =============================================================================
# Timing envelope
# =============================================================================


def _make_timing(
    pre_check_s: float = 0.0,
    fire_s: float = 0.0,
    confirm_s: float = 0.0,
    total_s: float = 0.0,
    attempts: int = 1,
    confirm_attempts: int = 0,
    method: str = "async",
) -> dict:
    """Build a timing dict for command result envelopes.

    Args:
        pre_check_s: Time spent in the pre-fire check.
        fire_s: Time in the fire leg (the awaited RPC).
        confirm_s: Time spent in confirm_fn.
        total_s: Wall-clock time for the whole operation.
        attempts: Number of fire-block attempts (1 + retries).
        confirm_attempts: Number of confirm-wrapper attempts.
        method: Transport method label ("async").

    Returns:
        Timing dict with all keys above.
    """
    return {
        "pre_check_s": pre_check_s,
        "fire_s": fire_s,
        "confirm_s": confirm_s,
        "total_s": total_s,
        "attempts": attempts,
        "confirm_attempts": confirm_attempts,
        "method": method,
    }

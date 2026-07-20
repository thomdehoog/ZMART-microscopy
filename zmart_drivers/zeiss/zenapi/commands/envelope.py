"""
The command result envelope.
============================
Every command in this driver returns the same envelope shape: success flag,
confirmation state, message, data, timing, and an ordered log trace. This
module builds those pieces. It is a leaf -- no imports from other driver
modules -- so the dispatch backbone, the confirmations, and the command
wrappers can all share it without creating import cycles.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import time


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

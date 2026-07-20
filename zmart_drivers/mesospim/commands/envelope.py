"""
The command result envelope.
============================
Every command in this driver returns the same envelope shape: success flag,
confirmation state, message, data, timing, and an ordered log trace. This
module builds those pieces. It is a leaf -- no imports from other driver
modules -- so the dispatch backbone, the movement wrappers, and the
state-setting wrappers can all share it without creating import cycles.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import time


def _make_log_entry(level: str, msg: str) -> dict:
    """Build a timestamped structured log entry.

    Every command result carries a ``logs`` list of these so callers get an
    ordered trace of what happened. ``level`` is one of
    ``debug|info|warning|error``.
    """
    return {"ts": time.time(), "level": level, "msg": msg}


def _make_timing(
    *,
    pre_check_s: float = 0.0,
    fire_s: float = 0.0,
    confirm_s: float = 0.0,
    total_s: float = 0.0,
    attempts: int = 1,
    confirm_attempts: int = 0,
) -> dict:
    """Build a timing dict for command result envelopes."""
    return {
        "pre_check_s": pre_check_s,
        "fire_s": fire_s,
        "confirm_s": confirm_s,
        "total_s": total_s,
        "attempts": attempts,
        "confirm_attempts": confirm_attempts,
    }


def _fail(label: str, message: str) -> dict:
    """A pre-fire failure envelope (validation / limits): no request was sent.

    Shared by the movement wrappers (:mod:`mesospim.commands.movement`) and the
    state-setting wrappers (:mod:`mesospim.commands.commands`).
    """
    return {
        "success": False,
        "confirmed": None,
        "message": f"{label}: {message}",
        "data": {},
        "timing": _make_timing(total_s=0.0, attempts=0),
        "logs": [_make_log_entry("error", f"{label}: {message}")],
    }

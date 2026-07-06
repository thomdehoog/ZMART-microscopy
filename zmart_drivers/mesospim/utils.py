"""
Utility functions.
==================
Shared low-level helpers with no domain knowledge: safe float conversion,
timing-envelope construction, and structured log entries. Every function here is
a pure utility -- no imports from other driver modules, no knowledge of mesoSPIM,
sockets, or the wire protocol.

Unit convention: the mesoSPIM driver speaks **micrometers** for the linear axes
(x, y, z, focus) and **degrees** for the rotation axis (theta), on both the
public API and the wire. The server is responsible for any conversion to
mesoSPIM's internal units.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import time

# The five mesoSPIM axes. Linear axes are micrometers; theta is degrees.
LINEAR_AXES = ("x", "y", "z", "f")
ROTARY_AXES = ("theta",)
AXES = LINEAR_AXES + ROTARY_AXES


def _safe_float(val, default=None):
    """Convert val to float. Returns default on failure or None input."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _make_log_entry(level: str, msg: str) -> dict:
    """Build a timestamped log entry (``level`` is ``debug|info|warning|error``)."""
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

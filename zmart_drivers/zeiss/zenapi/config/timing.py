"""
Configurable timeouts (seconds).
================================
Import and override to tune per instrument.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

CONFIRM_POLL_S = 3.0  # Per-attempt readback poll window (NOT a timeout): poll the
# readback for this long, then re-fire and poll again up to max_confirm_attempts;
# exhaustion returns unconfirmed, never a hard fail.
CALL_TIMEOUT = 30.0  # Default per-RPC deadline (a true timeout: expiry is a
# transient transport failure, retried by the fire block).

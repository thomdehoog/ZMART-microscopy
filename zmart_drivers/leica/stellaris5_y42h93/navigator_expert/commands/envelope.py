"""The shape every command result shares: timing and log entries.

A leaf module (stdlib only) so every commands-layer module — including the
ones below ``dispatch`` in the layering — can build result envelopes
without import cycles.
"""

import time


def _make_log_entry(level, msg):
    """Build a timestamped log entry dict.

    Every pluggable function in the pipeline accumulates these entries in
    its ``logs`` list. The backbone collects them into a single ordered
    trace so the caller has full visibility into what happened.

    Args:
        level: One of "debug", "info", "warning", "error".
        msg: Human-readable log message.

    Returns:
        {"ts": float, "level": str, "msg": str}
    """
    return {"ts": time.time(), "level": level, "msg": msg}


def _make_timing(
    pre_check_s=0.0,
    setup_s=0.0,
    fire_s=0.0,
    check_s=0.0,
    confirm_s=0.0,
    total_s=0.0,
    attempts=1,
    confirm_attempts=0,
    method="async",
):
    """Build a timing dict for command result envelopes.

    Args:
        pre_check_s: Time spent in pre-fire check (e.g. idle wait).
        setup_s: Time writing parameters to the model.
        fire_s: Time for UpdateAwaitReceipt transport.
        check_s: Time for API error check.
        confirm_s: Time spent in confirm_fn.
        total_s: Wall-clock time for the entire operation.
        attempts: Number of fire-block attempts (1 + retries).
        confirm_attempts: Number of confirm-wrapper attempts.
        method: 'sync' or 'async'.

    Returns:
        Timing dict with all keys above.
    """
    return {
        "pre_check_s": pre_check_s,
        "setup_s": setup_s,
        "fire_s": fire_s,
        "check_s": check_s,
        "confirm_s": confirm_s,
        "total_s": total_s,
        "attempts": attempts,
        "confirm_attempts": confirm_attempts,
        "method": method,
    }

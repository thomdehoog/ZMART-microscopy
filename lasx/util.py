"""
Utility functions.
==================
Shared low-level helpers with no domain knowledge. Used across the driver
for format parsing, safe type conversion, timing envelope construction,
and structured log entry creation.

Every function here is a pure utility — no imports from other driver
modules, no knowledge of LAS X, microscopes, or API objects.
"""

import time


def _safe_float(val, default=None):
    """Convert val to float. Returns default on failure or None input."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _hw_get(d, key, default=None):
    """Safe dict/object getter for hardware info navigation."""
    try:
        if isinstance(d, dict):
            return d.get(key, default)
        return getattr(d, key, default)
    except Exception:
        return default


def parse_format(format_str):
    """Parse '512 x 512' → (512, 512)."""
    parts = format_str.split("x")
    if len(parts) != 2:
        raise ValueError(f"Cannot parse format: '{format_str}'")
    return int(parts[0].strip()), int(parts[1].strip())


def format_to_str(width, height):
    """Convert (512, 512) → '512 x 512'."""
    return f"{width} x {height}"


# =============================================================================
# Structured log entries
# =============================================================================

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


# =============================================================================
# Timing envelope
# =============================================================================

def _make_timing(pre_check_s=0.0, setup_s=0.0, fire_s=0.0, check_s=0.0,
                 confirm_s=0.0, total_s=0.0, attempts=1,
                 confirm_attempts=0, method="sync"):
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

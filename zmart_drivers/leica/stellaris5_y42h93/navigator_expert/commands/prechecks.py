"""
Pre-flight check functions.
============================
Functions that run before a command fires to ensure preconditions are met.
Each function owns its own polling loop internally — the backbone never
sleeps or polls. It calls the function once and gets back a result dict.

Currently contains only ``check_idle`` (wait for scanner idle). Future
pre-flight checks (e.g. wait for temperature stability, wait for stage
settled) follow the same contract: ``callable(client) → result dict``.
Extra parameters are pre-bound with ``partial`` at profile definition
time; the command function binds ``client`` via lambda.

Import restrictions: only runtime utilities, readers, and stdlib. Nothing
from command wrappers, profiles, or confirmations.
"""

import logging
import time

from .. import readers as _readers
from .envelope import _make_log_entry

log = logging.getLogger(__name__)


def check_idle(client, *, timeout, heartbeat=30.0):
    """Poll until the scanner is idle, or until timeout is exceeded.

    Logs a heartbeat message at regular intervals so long-running waits
    are visible in the logs. All polling logic is internal — the caller
    sees only a result dict with "success" and "logs".

    Args:
        client: The connected LAS X API client.
        timeout: Maximum seconds to wait before returning failure.
            None means wait indefinitely (no timeout).
        heartbeat: Interval in seconds between log messages during
            the wait. Keeps operators informed that the system is
            alive during long idle waits.

    Returns:
        {"success": True, "logs": [...]} if scanner became idle.
        {"success": False, "logs": [...]} if timeout was exceeded.
    """
    logs = []
    t0 = time.perf_counter()
    last_heartbeat = t0

    while True:
        # Idle is a command-safety precondition, not a passive status display.
        # Pin API so log/hybrid profile modes cannot let a stale log value gate a
        # command. Unknown/None is treated as not idle.
        status = _readers.get_scan_status(client, mode="api") or "Unknown"

        if "Idle" in status:
            return {"success": True, "logs": logs}

        now = time.perf_counter()
        elapsed = now - t0

        # Heartbeat logging during long waits
        if now - last_heartbeat > heartbeat:
            msg = f"Waiting for idle: {status} ({elapsed:.0f}s elapsed)"
            log.info(msg)
            logs.append(_make_log_entry("info", msg))
            last_heartbeat = now

        # Hard timeout
        if timeout is not None and elapsed > timeout:
            msg = f"Pre-check timeout after {timeout:.1f}s (status: {status})"
            log.warning(msg)
            logs.append(_make_log_entry("warning", msg))
            return {"success": False, "logs": logs}

        time.sleep(0.05)

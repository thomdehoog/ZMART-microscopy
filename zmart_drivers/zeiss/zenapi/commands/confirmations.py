"""
Readback confirmations.
=======================
Zero-arg-after-binding confirmation functions the dispatch backbone calls to
verify a command took effect. Each polls a reader (or, for acquisition,
consumes the native status stream) and returns ``{"success": bool, "logs": [...]}``.

Because ZEN ``move_to`` awaits to completion, the readback confirmations are
cheap insurance rather than the primary completion signal; ``confirm_acquire``
is the real one -- it consumes ``register_on_status_changed`` (a strict upgrade
over log-tailing).

Readers are imported lazily inside the functions to keep the import graph
acyclic (``profiles`` -> ``confirmations`` -> ``readers`` -> ``profiles``).

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import logging
import time

from ..readers.reading import _reading_value_after
from ..utils import CONFIRM_POLL_S, _make_log_entry

log = logging.getLogger(__name__)


def confirm_move_xy(
    client, *, target_x_um, target_y_um, tolerance=1.0, poll_window=None, poll_interval=0.1
):
    """Poll ``get_xy`` until |readback - target| < tolerance (µm) on both axes."""
    from .. import readers as _readers

    poll_window = CONFIRM_POLL_S if poll_window is None else poll_window
    logs = []
    observed_after = time.time()
    deadline = time.perf_counter() + poll_window
    last = None
    while time.perf_counter() < deadline:
        pos = _reading_value_after(_readers.get_xy(client, diagnostics=True), observed_after)
        if pos is not None:
            last = pos
            if (
                abs(pos["x_um"] - target_x_um) < tolerance
                and abs(pos["y_um"] - target_y_um) < tolerance
            ):
                return {"success": True, "logs": logs, "last_position": last}
        time.sleep(poll_interval)
    msg = f"MoveXY unconfirmed — target=({target_x_um:.2f}, {target_y_um:.2f}) µm, last={last}"
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs, "last_position": last}


def confirm_move_z(client, *, target_um, tolerance=0.5, poll_window=None, poll_interval=0.1):
    """Poll ``get_z`` until |readback - target| < tolerance (µm)."""
    from .. import readers as _readers

    poll_window = CONFIRM_POLL_S if poll_window is None else poll_window
    logs = []
    observed_after = time.time()
    deadline = time.perf_counter() + poll_window
    last = None
    while time.perf_counter() < deadline:
        z = _reading_value_after(_readers.get_z(client, diagnostics=True), observed_after)
        if z is not None:
            last = z
            if abs(z - target_um) < tolerance:
                return {"success": True, "logs": logs, "last_z_um": last}
        time.sleep(poll_interval)
    msg = f"MoveZ unconfirmed — target={target_um:.2f} µm, last={last}"
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs, "last_z_um": last}


def confirm_objective(client, *, target_index, poll_window=None, poll_interval=0.1):
    """Poll ``get_objective`` until the turret index matches the target."""
    from .. import readers as _readers

    poll_window = CONFIRM_POLL_S if poll_window is None else poll_window
    logs = []
    observed_after = time.time()
    deadline = time.perf_counter() + poll_window
    last = None
    while time.perf_counter() < deadline:
        obj = _reading_value_after(_readers.get_objective(client, diagnostics=True), observed_after)
        if obj is not None:
            last = obj.get("index")
            if last == target_index:
                return {"success": True, "logs": logs, "index": last}
        time.sleep(poll_interval)
    msg = f"Objective unconfirmed — target index={target_index}, last={last}"
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs, "index": last}


def confirm_acquire(
    client,
    *,
    experiment_id,
    start_timeout=15.0,
    heartbeat_interval=30.0,
    timeout=None,
    poll_interval=0.1,
):
    """Consume the experiment status stream until the acquisition completes.

    Phase 1: within ``start_timeout``, see running go True.
    Phase 2: consume progress until running goes back to False (terminal) or the
             stream ends -> success. If running is never seen -> failure (the
             acquire profile does not re-fire).

    NOTE (bench-verify): the stream is opened here, i.e. just after the fire. If
    the server does not replay current status on subscribe and ``run_experiment``
    returns only on completion, the "register before fire" ordering must move
    into the wrapper. See the driver README "Risks".
    """
    from ..readers.api_reader import status_to_dict

    logs = []
    saw_running = False
    t_start = time.perf_counter()
    last_hb = t_start
    last_status = None
    item_timeout = timeout if timeout is not None else max(start_timeout, 600.0)

    factory = lambda: client.experiment.register_on_status_changed(  # noqa: E731
        client.messages.status_subscribe(experiment_id)
    )
    try:
        for item in client.stream(factory, item_timeout=item_timeout):
            last_status = status_to_dict(item)
            running = last_status["is_experiment_running"] or last_status["is_acquisition_running"]
            elapsed = time.perf_counter() - t_start

            if running:
                saw_running = True
            elif saw_running:
                # running -> not running: acquisition finished
                return {"success": True, "logs": logs, "last_status": last_status}

            if not saw_running and elapsed > start_timeout:
                msg = f"Acquisition not started after {start_timeout:.0f}s"
                log.warning(msg)
                logs.append(_make_log_entry("warning", msg))
                return {"success": False, "logs": logs, "last_status": last_status}

            now = time.perf_counter()
            if now - last_hb > heartbeat_interval:
                msg = f"Acquiring: {last_status}, {elapsed:.0f}s elapsed"
                log.info(msg)
                logs.append(_make_log_entry("info", msg))
                last_hb = now
    except TimeoutError:
        msg = f"Acquisition status stream stalled (> {item_timeout:.0f}s between updates)"
        log.warning(msg)
        logs.append(_make_log_entry("warning", msg))
        return {"success": False, "logs": logs, "last_status": last_status}

    # Stream ended.
    if saw_running:
        return {"success": True, "logs": logs, "last_status": last_status}
    msg = "Acquisition status stream ended without the experiment ever running"
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs, "last_status": last_status}

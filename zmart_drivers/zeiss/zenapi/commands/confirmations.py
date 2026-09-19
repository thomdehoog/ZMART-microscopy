"""
Readback confirmations.
=======================
Zero-arg-after-binding confirmation functions the dispatch backbone calls to
verify a command took effect. Each polls a reader (or, for acquisition,
consumes the native status stream) and returns ``{"success": bool, "logs": [...]}``.

ZEN's move and run calls only return once the action is done, so every
confirmation here is cheap insurance rather than the primary completion
signal: a readback that proves the microscope is where (or in the state) we
asked for.

Readers are imported lazily inside the functions to keep the import graph
acyclic (``profiles`` -> ``confirmations`` -> ``readers`` -> ``profiles``).

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import logging
import time

from ..config.timing import CONFIRM_POLL_S
from ..readers.reading import _reading_value_after
from .envelope import _make_log_entry

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
    poll_window=None,
    poll_interval=0.2,
    start_timeout=None,
    heartbeat_interval=None,
    timeout=None,
    sink=None,
):
    """Check with ``GetStatus`` that the acquisition is over.

    ``RunSnap`` and ``RunExperiment`` only return once ZEN has finished (or
    failed, or was stopped), so by the time this runs the answer should be
    "not running" straight away. The readback is kept as insurance: it polls
    ZEN's status for at most ``poll_window`` seconds and succeeds as soon as
    both running flags are off. The final status (image counts, elapsed time)
    is returned as ``last_status`` so the caller can record it.

    ``sink`` is an optional dict; the last status read is stored under
    ``sink["last_status"]`` so the command wrapper can attach it to its
    result. ``start_timeout``, ``heartbeat_interval`` and ``timeout`` are
    accepted for profile compatibility and are not needed with the blocking
    run calls.
    """
    from ..readers.api_reader import get_status

    poll_window = CONFIRM_POLL_S if poll_window is None else poll_window
    logs = []
    deadline = time.perf_counter() + poll_window
    last_status = None
    while True:
        try:
            last_status = get_status(client, experiment_id)
        except Exception as exc:  # noqa: BLE001 - a failed readback is "unconfirmed"
            msg = f"Acquisition status readback failed: {exc}"
            log.warning(msg)
            logs.append(_make_log_entry("warning", msg))
            return {"success": False, "logs": logs, "last_status": None}
        if sink is not None:
            sink["last_status"] = last_status
        running = last_status["is_experiment_running"] or last_status["is_acquisition_running"]
        if not running:
            return {"success": True, "logs": logs, "last_status": last_status}
        if time.perf_counter() >= deadline:
            break
        time.sleep(poll_interval)
    msg = f"Acquisition still reported as running after {poll_window:.0f}s: {last_status}"
    log.warning(msg)
    logs.append(_make_log_entry("warning", msg))
    return {"success": False, "logs": logs, "last_status": last_status}

"""
Core dispatch engine.
=====================
The command backbone every write routes through. Two layers, mirroring the
Leica/ZEN drivers but sized for a text-socket transport:

    Fire block   -- send the request; retry only on *transient* transport
                    failures (dropped link / timeout) up to ``max_retries``. A
                    server NAK (``ok=false``) is a permanent rejection, not
                    retried.
    Confirm wrap -- run ``confirm_fn`` to verify the fire landed; optionally
                    re-fire and re-confirm up to ``max_confirm_attempts``.

The backbone is dumb: it owns order, retry ceilings, and timing, and calls
zero-/one-arg callables. It knows nothing about axes, lasers, or acquisitions.

Result envelope (every command returns this shape)::

    {
      "success": bool,       # did the command achieve its effect?
      "confirmed": bool|None,# did a readback verify it? None = not confirmed-checked
      "message": str,        # human-readable outcome
      "data": dict,          # command-specific payload (server reply data, position, ...)
      "timing": {...},       # from utils._make_timing
      "logs": [{ts, level, msg}, ...],
    }

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import logging
import socket
import time
from collections.abc import Callable
from typing import Any

from ..connection.client import MesospimError
from ..protocol import Reply
from ..utils import _make_log_entry, _make_timing

log = logging.getLogger(__name__)

# Transport-level failures worth a retry (the fire never reached the server, or
# the server did not answer in time). A NAK is NOT here -- it is a decision.
_TRANSIENT = (ConnectionError, TimeoutError, socket.timeout)


def _result(
    *,
    success: bool,
    confirmed: bool | None,
    message: str,
    data: dict | None,
    logs: list,
    timing: dict,
) -> dict:
    return {
        "success": success,
        "confirmed": confirmed,
        "message": message,
        "data": data or {},
        "timing": timing,
        "logs": logs,
    }


def confirm_and_fire(
    client,
    label: str,
    profile,
    fire_fn: Callable[[], Reply],
    *,
    confirm_fn: Callable[..., dict] | None = None,
) -> dict:
    """Fire ``fire_fn`` (with transient retry), then confirm via ``confirm_fn``.

    Args:
        client: the connected :class:`MesospimClient`.
        label: human-readable command label for logs/messages.
        profile: a :class:`config.profiles.CommandProfile`.
        fire_fn: zero-arg callable that sends the request and returns a
            :class:`Reply`. Must be safe to call again (re-fire on unconfirmed).
        confirm_fn: ``callable(client, observed_after) -> {"confirmed": bool, ...}``
            or None to skip confirmation.

    Returns:
        The standard result envelope.
    """
    logs: list = []
    t0 = time.perf_counter()

    # -- fire block (transient retry) ----------------------------------------
    reply: Reply | None = None
    attempts = 0
    fire_start = time.perf_counter()
    while True:
        attempts += 1
        try:
            reply = fire_fn()
        except _TRANSIENT as exc:
            if attempts <= profile.max_retries:
                logs.append(_make_log_entry("warning", f"{label}: transient error, retry: {exc}"))
                time.sleep(min(0.25 * attempts, 1.0))
                continue
            logs.append(_make_log_entry("error", f"{label}: transport failed: {exc}"))
            return _result(
                success=False,
                confirmed=None,
                message=f"{label}: transport failed after {attempts} attempts: {exc}",
                data=None,
                logs=logs,
                timing=_make_timing(
                    fire_s=time.perf_counter() - fire_start,
                    total_s=time.perf_counter() - t0,
                    attempts=attempts,
                ),
            )
        except MesospimError as exc:
            # try_request would not raise; a raising fire_fn used request().
            logs.append(_make_log_entry("error", f"{label}: rejected: {exc}"))
            return _result(
                success=False,
                confirmed=None,
                message=f"{label}: {exc}",
                data=None,
                logs=logs,
                timing=_make_timing(total_s=time.perf_counter() - t0, attempts=attempts),
            )
        except Exception as exc:  # noqa: BLE001 - never break the envelope contract
            # e.g. a ProtocolError on a garbled reply line: fail the command
            # rather than let a raw exception escape confirm_and_fire.
            logs.append(_make_log_entry("error", f"{label}: unexpected error: {exc}"))
            return _result(
                success=False,
                confirmed=None,
                message=f"{label}: unexpected error: {exc}",
                data=None,
                logs=logs,
                timing=_make_timing(total_s=time.perf_counter() - t0, attempts=attempts),
            )
        break

    assert reply is not None
    if not reply.ok:
        logs.append(_make_log_entry("error", f"{label}: NAK: {reply.error}"))
        return _result(
            success=False,
            confirmed=None,
            message=f"{label}: server rejected: {reply.error or '(no message)'}",
            data=dict(reply.data),
            logs=logs,
            timing=_make_timing(
                fire_s=time.perf_counter() - fire_start,
                total_s=time.perf_counter() - t0,
                attempts=attempts,
            ),
        )

    fire_s = time.perf_counter() - fire_start
    # perf_counter instant the command landed. The confirm freshness gate rejects
    # any readback observed *before* this, so a stale pre-command read can never
    # confirm the fire. Must match Reading.observed_at's clock (perf_counter):
    # wall clock and time.monotonic() are both ~16 ms coarse on Windows, so a
    # stale read could share the fire's timestamp and wrongly confirm; wall clock
    # can also step backward. Captured once, before the first confirm read.
    command_fired_at = time.perf_counter()

    # -- no confirmation requested -------------------------------------------
    if confirm_fn is None:
        return _result(
            success=True,
            confirmed=None,
            message=f"{label}: ok",
            data=dict(reply.data),
            logs=logs,
            timing=_make_timing(
                fire_s=fire_s, total_s=time.perf_counter() - t0, attempts=attempts
            ),
        )

    # -- confirm wrapper ------------------------------------------------------
    confirm_start = time.perf_counter()
    confirm_attempts = 0
    last: dict[str, Any] = {}
    for attempt in range(1, profile.max_confirm_attempts + 1):
        confirm_attempts = attempt
        try:
            last = confirm_fn(client, observed_after=command_fired_at)
        except Exception as exc:  # noqa: BLE001 - a reader failure is not fatal
            logs.append(_make_log_entry("warning", f"{label}: confirm read failed: {exc}"))
            last = {"confirmed": False, "error": str(exc)}
        if last.get("confirmed"):
            logs.append(_make_log_entry("info", f"{label}: confirmed"))
            return _result(
                success=True,
                confirmed=True,
                message=f"{label}: confirmed",
                data={**reply.data, **{k: v for k, v in last.items() if k != "confirmed"}},
                logs=logs,
                timing=_make_timing(
                    fire_s=fire_s,
                    confirm_s=time.perf_counter() - confirm_start,
                    total_s=time.perf_counter() - t0,
                    attempts=attempts,
                    confirm_attempts=confirm_attempts,
                ),
            )
        if profile.refire_on_unconfirmed and attempt < profile.max_confirm_attempts:
            logs.append(_make_log_entry("info", f"{label}: unconfirmed, re-firing"))
            try:
                fire_fn()
            except _TRANSIENT as exc:
                logs.append(_make_log_entry("warning", f"{label}: re-fire transient: {exc}"))
            except Exception as exc:  # noqa: BLE001 - a re-fire failure must not crash
                # A NAK (or any error) on re-fire is not fatal: log it and let the
                # confirm loop fall through to the exhausted branch so the caller
                # still gets the standard envelope, never a raised exception.
                logs.append(_make_log_entry("warning", f"{label}: re-fire failed: {exc}"))

    # -- confirmation exhausted ----------------------------------------------
    timing = _make_timing(
        fire_s=fire_s,
        confirm_s=time.perf_counter() - confirm_start,
        total_s=time.perf_counter() - t0,
        attempts=attempts,
        confirm_attempts=confirm_attempts,
    )
    detail = f" (last readback: {last!r})" if last else ""
    if profile.success_on_unconfirmed:
        logs.append(_make_log_entry("warning", f"{label}: unconfirmed but accepted{detail}"))
        return _result(
            success=True,
            confirmed=False,
            message=f"{label}: fired, not confirmed{detail}",
            data={**reply.data, **{k: v for k, v in last.items() if k != "confirmed"}},
            logs=logs,
            timing=timing,
        )
    logs.append(_make_log_entry("error", f"{label}: not confirmed{detail}"))
    return _result(
        success=False,
        confirmed=False,
        message=f"{label}: not confirmed{detail}",
        data=dict(reply.data),
        logs=logs,
        timing=timing,
    )

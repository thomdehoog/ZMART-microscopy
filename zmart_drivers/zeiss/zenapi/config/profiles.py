"""
Per-command profiles + connection/reader settings.
===================================================
Every command has a ``CommandProfile`` -- its complete recipe of confirm
function and retry/confirm tuning in one place. Tuning a command means editing
its profile; nothing else changes. This keeps machine-sensitive numbers out of
the command wrappers (which accept explicit overrides only for tests).

ZEN differences from the Leica ``CommandProfile``: no ``receipt_timeout`` /
``skip_echo`` / ``fire_async`` (there is no echo model or transport branch --
a command is one awaited RPC); a ``call_timeout`` is added for the gRPC
per-call deadline. The ``max_confirm_attempts==1 => refire_on_unconfirmed=False``
guard is kept.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

from dataclasses import dataclass

from ..utils import CALL_TIMEOUT, CONFIRM_POLL_S

# NOTE: the confirm_* functions are imported LOWER DOWN (just before the profile
# instances), not here. Importing them triggers ``readers`` -> ``api_reader`` ->
# ``profiles.READERS``; deferring the import until after ``READERS`` and
# ``CommandProfile`` are defined breaks that cycle.


@dataclass(frozen=True)
class ZenApiProfile:
    """Connection-level ZEN API settings (gateway, TLS, deadlines).

    Values resolve at ``connect()`` from a ``config.ini`` and/or explicit
    overrides; these are the fallbacks and the timing knobs.
    """

    config_path: str | None = "config.ini"
    host: str | None = None
    port: int | None = None
    cert_file: str | None = None
    control_token: str | None = None
    token_path: str | None = None
    connect_timeout_s: float = 10.0
    default_call_timeout_s: float = CALL_TIMEOUT


ZEN_API = ZenApiProfile()


@dataclass(frozen=True)
class ReaderProfile:
    """Per-read deadlines. ZEN reads are all api (gRPC); no log/hybrid modes."""

    read_timeout_s: float = 10.0
    status_item_timeout_s: float = 60.0


READERS = ReaderProfile()


@dataclass(frozen=True)
class CommandProfile:
    """Complete recipe for one command's backbone behaviour.

    Attributes:
        confirm_fn: readback/stream confirmation ``callable(client, ...) -> result``.
            Declarative only -- commands bind the target via ``partial`` at call time.
        max_retries: transient-error retries inside the fire block.
        max_confirm_attempts: confirm-wrapper re-attempt ceiling.
        refire_on_unconfirmed: re-send the command before the next confirm attempt?
        confirm_poll_s: per-attempt readback poll window (NOT a timeout).
        confirm_tolerance: numeric tolerance (µm) for target readbacks.
        poll_interval / poll_timeout / start_timeout / heartbeat_interval:
            long-running (acquisition) confirmation knobs.
        retry_backoff / retry_escalate: transient-retry backoff policy.
        call_timeout: per-RPC gRPC deadline (seconds); None = wait indefinitely
            (used for long acquisitions where the status stream is the gate).
        success_on_unconfirmed: exhausted confirmation returns success (default)
            with confirmed=False; only a transport/RPC error hard-fails.
    """

    confirm_fn: callable = None
    max_retries: int = 3
    max_confirm_attempts: int = 3
    refire_on_unconfirmed: bool = True
    confirm_poll_s: float = CONFIRM_POLL_S
    confirm_tolerance: float = None
    poll_interval: float = None
    poll_timeout: float = None
    start_timeout: float = None
    heartbeat_interval: float = None
    retry_backoff: float = None
    retry_escalate: bool = False
    call_timeout: float | None = CALL_TIMEOUT
    success_on_unconfirmed: bool = True

    def __post_init__(self):
        # A single confirm window has no 'next attempt' to re-fire before, so a
        # requested re-fire could never run. Forbid the incoherent combination.
        if self.max_confirm_attempts == 1 and self.refire_on_unconfirmed:
            raise ValueError("max_confirm_attempts==1 requires refire_on_unconfirmed=False")


# Deferred import (see NOTE at the top): READERS + CommandProfile now exist, so
# the readers -> api_reader -> profiles.READERS re-entry during this import resolves.
from ..commands.confirmations import (  # noqa: E402
    confirm_acquire,
    confirm_move_xy,
    confirm_move_z,
    confirm_objective,
)

# =============================================================================
# Device moves. ZEN move_to awaits to completion, so a single confirm window
# (readback insurance) with no re-fire is the right posture -- not the Leica
# 3-window re-fire loop, which existed because LAS X could accept-then-drift.
# pre_check idle-wait is intentionally absent: ZEN serializes hardware access
# server-side, and a bare-instrument idle stream is not available in this API.
# =============================================================================

STAGE_MOVE = CommandProfile(
    confirm_fn=confirm_move_xy,
    confirm_tolerance=1.0,
    max_confirm_attempts=1,
    refire_on_unconfirmed=False,
    call_timeout=60.0,
)

FOCUS_MOVE = CommandProfile(
    confirm_fn=confirm_move_z,
    confirm_tolerance=0.5,
    max_confirm_attempts=1,
    refire_on_unconfirmed=False,
    call_timeout=60.0,
)

OBJECTIVE = CommandProfile(
    confirm_fn=confirm_objective,
    max_confirm_attempts=1,
    refire_on_unconfirmed=False,
    call_timeout=60.0,
)


# =============================================================================
# Acquisition. Copies the Leica ACQUIRE posture: never re-send (a re-fire starts
# a second acquisition), unconfirmed is not a hard fail (save()'s file check is
# the real data gate). call_timeout=None: the fire RPC may run as long as the
# acquisition; the status stream is the completion gate.
# =============================================================================

SNAP = CommandProfile(
    confirm_fn=confirm_acquire,
    max_retries=0,
    max_confirm_attempts=1,
    refire_on_unconfirmed=False,
    poll_interval=0.1,
    start_timeout=15.0,
    heartbeat_interval=30.0,
    call_timeout=None,
)

RUN_EXPERIMENT = CommandProfile(
    confirm_fn=confirm_acquire,
    max_retries=0,
    max_confirm_attempts=1,
    refire_on_unconfirmed=False,
    poll_interval=0.1,
    start_timeout=30.0,
    heartbeat_interval=30.0,
    call_timeout=None,
)

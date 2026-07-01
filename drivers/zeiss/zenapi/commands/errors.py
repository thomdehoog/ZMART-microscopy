"""
Error classification for ZEN API (gRPC).
=========================================
ZEN API commands raise ``grpclib.GRPCError`` (or a transport error) rather than
writing an echo string like LAS X. So classification keys off the gRPC **status
code**, not message-text patterns: transient codes are retry-worthy, everything
else (and any unknown/unclassifiable failure) is permanent.

``classify_grpc_error`` turns a caught exception into the ``{"transient","error"}``
shape the fire block understands. It is the ZEN analog of the Leica driver's
``_is_transient_error`` + ``_default_error_check``.

Import restrictions: only runtime utilities and stdlib. Nothing from commands,
profiles, prechecks, or confirmations.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# gRPC status codes that are worth retrying (the call may succeed if repeated).
# Names are matched case-insensitively against the exception's status, so this
# works whether grpclib exposes an enum member (``Status.UNAVAILABLE``), an int,
# or a plain string -- see ``_status_name``.
_TRANSIENT = frozenset(
    {"UNAVAILABLE", "DEADLINE_EXCEEDED", "ABORTED", "RESOURCE_EXHAUSTED", "CANCELLED"}
)

# Everything below is permanent; retrying cannot help. Listed for documentation
# and log clarity -- classification treats "not transient" as permanent, so an
# unknown/unclassifiable code is permanent by default (the safe choice).
_PERMANENT = frozenset(
    {
        "INVALID_ARGUMENT",
        "NOT_FOUND",
        "FAILED_PRECONDITION",
        "PERMISSION_DENIED",
        "UNAUTHENTICATED",
        "UNIMPLEMENTED",
        "OUT_OF_RANGE",
        "ALREADY_EXISTS",
        "INTERNAL",
        "DATA_LOSS",
        "UNKNOWN",
    }
)


def _status_name(exc) -> str | None:
    """Best-effort extraction of a gRPC status name from an exception.

    Handles grpclib's ``GRPCError`` (``exc.status`` is a ``grpclib.const.Status``
    enum whose ``.name`` is e.g. ``"UNAVAILABLE"``), plain ints, and strings.
    Returns an upper-case name, or None if no status is present (e.g. a plain
    ``TimeoutError`` from the bridge, which the caller maps to a transient).
    """
    status = getattr(exc, "status", None)
    if status is None:
        return None
    name = getattr(status, "name", None)
    if isinstance(name, str):
        return name.upper()
    if isinstance(status, str):
        return status.upper()
    return str(status).upper()


def classify_grpc_error(exc: BaseException) -> dict:
    """Classify a caught RPC exception into ``{"transient", "error"}``.

    - A bridge/deadline ``TimeoutError`` (no gRPC status) is **transient**: the
      server may simply have been slow; a retry is warranted.
    - A gRPC status in ``_TRANSIENT`` is transient.
    - Everything else -- including unknown/unclassifiable codes -- is permanent.

    Args:
        exc: The exception raised by ``ZenClient.submit`` / a stub call.

    Returns:
        {"transient": bool, "error": str}
    """
    if isinstance(exc, TimeoutError):
        return {"transient": True, "error": f"RPC timed out: {exc}"}

    name = _status_name(exc)
    message = getattr(exc, "message", None) or str(exc)
    detail = f"{name}: {message}" if name else message

    if name is None:
        # Transport-level failure with no status -- treat as transient (the
        # connection may recover), mirroring the Leica timeout posture.
        log.warning("RPC transport error (treated as transient): %s", detail)
        return {"transient": True, "error": f"transport error: {detail}"}

    if name in _TRANSIENT:
        return {"transient": True, "error": detail}

    if name not in _PERMANENT:
        log.warning("Unclassified gRPC status (treated as permanent): %s", detail)
    return {"transient": False, "error": detail}

"""
Wire protocol between the ZMART driver and the bridge inside NIS-Elements.
=======================================================================
The driver (our Python) and the bridge (Python running inside NIS-Elements)
talk over a local TCP socket. Every message is **one JSON object on one line**,
so it is easy to read in a log and easy to parse on both sides.

A request looks like::

    {"id": 7, "op": "get_position", "args": {}}

and its reply is either a success::

    {"id": 7, "ok": true, "result": {"x": 100.0, "y": -20.0, "z": 500.0}}

or a failure::

    {"id": 7, "ok": false, "kind": "RuntimeError", "error": "StgMove: DR_NOTINITIALIZED (-7)"}

``kind`` tells the driver which Python exception to raise again on its side:
``ValueError`` for a mistake in the request (unknown operation, bad argument),
``RuntimeError`` when the microscope itself refused or failed. That mirrors the
error contract of the ZMART controller.

This module has no sockets in it; it only builds and reads messages, so it can
be tested completely offline and is shared by both halves. It must stay
standard-library only, because the bridge runs in the Python that ships with
NIS-Elements.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import json
from typing import Any

ENCODING = "utf-8"
LINE_END = "\n"

# Bump when a request or reply changes shape in a way old peers cannot read.
PROTOCOL_VERSION = 1

# The exception kinds a reply may carry. Anything else is treated as RuntimeError.
ERROR_KINDS = {"ValueError": ValueError, "RuntimeError": RuntimeError}


class ProtocolError(ValueError):
    """A line arrived that is not a well-formed request or reply."""


def encode_request(request_id: int, op: str, args: dict[str, Any] | None = None) -> str:
    """Build one request line (with its trailing newline)."""
    if not isinstance(op, str) or not op:
        raise ProtocolError("op must be a non-empty string")
    payload = {"id": int(request_id), "op": op, "args": dict(args or {})}
    return json.dumps(payload) + LINE_END


def encode_reply(request_id: int | None, result: Any) -> str:
    """Build one success reply line."""
    return json.dumps({"id": request_id, "ok": True, "result": result}, default=str) + LINE_END


def encode_error(request_id: int | None, exc: BaseException) -> str:
    """Build one failure reply line from an exception.

    The exception's class name becomes ``kind`` when it is one the driver knows
    how to re-raise; every other exception is reported as a RuntimeError, because
    from the driver's point of view the instrument side failed.
    """
    kind = type(exc).__name__ if type(exc).__name__ in ERROR_KINDS else "RuntimeError"
    text = f"{type(exc).__name__}: {exc}" if kind != type(exc).__name__ else str(exc)
    return json.dumps({"id": request_id, "ok": False, "kind": kind, "error": text}) + LINE_END


def decode_request(line: str) -> tuple[int | None, str, dict[str, Any]]:
    """Read one request line; returns ``(id, op, args)``.

    Raises :class:`ProtocolError` when the line is not a request we understand,
    so the bridge can answer with a clean error instead of crashing.
    """
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"request is not valid JSON: {exc}") from None
    if not isinstance(payload, dict):
        raise ProtocolError("request must be a JSON object")
    op = payload.get("op")
    if not isinstance(op, str) or not op:
        raise ProtocolError("request has no 'op'")
    args = payload.get("args") or {}
    if not isinstance(args, dict):
        raise ProtocolError("'args' must be a JSON object")
    request_id = payload.get("id")
    return (request_id if isinstance(request_id, int) else None), op, args


def decode_reply(line: str) -> tuple[int | None, Any]:
    """Read one reply line; returns ``(id, result)`` or raises the carried error.

    A failure reply is turned back into the exception kind the bridge reported
    (``ValueError`` or ``RuntimeError``) with the bridge's message, so driver code
    can simply ``try/except`` around a request.
    """
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"reply is not valid JSON: {exc}") from None
    if not isinstance(payload, dict) or "ok" not in payload:
        raise ProtocolError("reply must be a JSON object with an 'ok' field")
    request_id = payload.get("id")
    if payload["ok"]:
        return request_id, payload.get("result")
    exc_type = ERROR_KINDS.get(payload.get("kind"), RuntimeError)
    raise exc_type(payload.get("error") or "bridge reported an error without a message")

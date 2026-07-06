"""
Restricted remote-scripting transport + structured-result envelope.
===================================================================
The mesoSPIM driver talks to mesoSPIM-control through its **Remote Scripting**
server (an upstream contribution under ``pull_request/``) run in **restricted
mode**: the wire carries a *named call* -- data, not code -- and the server
dispatches it against a fixed allowlist (:mod:`mesospim.connection.command_api`).
The client never sends Python; the server never ``exec``s client input.

This module is the pure, socket-free core of that transport:

1. **Framing** -- length-prefixed, both directions::

       message = b"<decimal-byte-count>\\n" + <payload bytes>

   This is the framing the Remote Scripting PR speaks (see
   ``pull_request/PROTOCOL.md``).

2. **A named call.** The request payload is one JSON object,
   ``{"call": <name>, "args": {...}}`` (:func:`encode_call` /
   :func:`decode_call`). The reply is one line, ``__ZMART_OK__<json>``
   (:func:`encode_reply`), which :func:`parse_result` reads back. On any
   server-side error the reply is the traceback text (no marker line); finding no
   ``__ZMART_OK__`` line, :func:`parse_result` returns that whole text as the
   error. So failures still surface without a success payload.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

ENCODING = "utf-8"

# Bumped only if the framing or call/reply contract changes.
PROTOCOL_VERSION = 1

# Result marker. A distinctive prefix on one line; the JSON result follows on the
# same line (so a single regex `^__ZMART_OK__(.*)$` extracts it).
OK_MARKER = "__ZMART_OK__"


class ProtocolError(ValueError):
    """A frame or result payload could not be parsed."""


@dataclass(frozen=True)
class Reply:
    """A parsed structured result.

    ``ok`` reports success; ``data`` carries the payload of a successful reply
    and ``error`` the message of a failed one. ``id`` is unused by the
    remote-scripting transport (kept for API compatibility with callers).
    """

    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    id: int | None = None


# -- framing ------------------------------------------------------------------


def frame(payload: str | bytes) -> bytes:
    """Length-prefix ``payload`` for the wire: ``b"<len>\\n" + payload``."""
    if isinstance(payload, str):
        payload = payload.encode(ENCODING)
    return str(len(payload)).encode("ascii") + b"\n" + payload


# -- named-call codec ---------------------------------------------------------


def encode_call(cmd: str, args: dict | None = None) -> str:
    """Serialise one request: ``{"call": cmd, "args": {...}}`` -- data, not code."""
    return json.dumps({"call": cmd, "args": dict(args or {})})


def decode_call(payload: str) -> tuple[str, dict]:
    """Parse a request payload into ``(call, args)``; raise on a malformed object."""
    obj = _loads(payload)
    if not isinstance(obj, dict) or not isinstance(obj.get("call"), str):
        raise ProtocolError("expected a {'call': <name>, 'args': {...}} object")
    args = obj.get("args") or {}
    if not isinstance(args, dict):
        raise ProtocolError("'args' must be an object")
    return obj["call"], args


def encode_reply(result: dict) -> str:
    """Serialise a successful result the way the server sends it: the OK line."""
    return OK_MARKER + json.dumps(result)


def parse_result(console: str) -> Reply:
    """Turn the server's reply text into a :class:`Reply`.

    Scans for the last ``__ZMART_OK__`` line. If there is none (the handler
    raised, an unknown call, or an auth/plumbing failure), the whole reply text
    -- the traceback the server sent -- is returned as the error.
    """
    for line in reversed(console.splitlines()):
        if line.startswith(OK_MARKER):
            data = _loads(line[len(OK_MARKER):])
            if not isinstance(data, dict):
                raise ProtocolError(f"result must be an object, got {type(data).__name__}")
            return Reply(ok=True, data=data)
    text = console.strip()
    return Reply(ok=False, error=text or "no result marker in server reply")


def _loads(payload: str):
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"could not decode result payload: {exc}") from exc

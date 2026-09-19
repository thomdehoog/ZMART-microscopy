"""
The wire contract of mesoSPIM Remote Control.
=============================================
The mesoSPIM driver talks to mesoSPIM-control through its **Remote Control**
TCP server (mesoSPIM-control pull request #106). The server understands a
fixed list of named calls -- ``get_position``, ``move_absolute``,
``acquire_start`` and so on -- and never runs code a client sends. This module
is the pure, socket-free half of that conversation: how a call is written on
the wire and how a reply is read back. The socket itself lives in
:mod:`mesospim.connection.client`.

**Framing.** Every message, in both directions, is a byte count, a newline,
and then that many bytes of UTF-8 text::

    message = b"<decimal-byte-count>\\n" + <payload bytes>

**Calls.** One JSON object with exactly one member: the call's name, and an
object of its arguments::

    {"move_absolute": {"targets": {"x": 100.0}}}

**Replies.** A successful reply is the marker ``__MESOSPIM_OK__`` followed by
a JSON object. A refused call is plain text that starts with ``error: [code]``,
where the code is one of ``validation`` (the request was wrong, nothing
started), ``busy`` (another change is still running), ``unknown_command`` and
``execution`` (the microscope side failed). :func:`parse_reply` turns either
form into a :class:`Reply` so the rest of the driver never looks at the text.

**Operations.** A call that changes something is *accepted* before the work
starts. The reply then carries an ``operation`` record (an id and a status),
and the client polls ``get_progress`` until that operation is ``completed`` or
``failed``. :mod:`mesospim.connection.client` does that polling; the helpers
at the bottom of this module read the operation record out of a reply.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

ENCODING = "utf-8"

# The protocol version ``hello`` reports. Bumped only when the framing or the
# call/reply contract of the Remote Control server changes.
PROTOCOL_VERSION = 1

# The marker a successful reply starts with, exactly as the server writes it.
OK_MARKER = "__MESOSPIM_OK__"

# The largest frame the server accepts or sends (one mebibyte), and the
# longest byte-count header it will read. Mirrors the server so a bad frame
# is refused on this side before it is ever sent.
MAX_FRAME_BYTES = 1 << 20
MAX_FRAME_HEADER_BYTES = 16

# The statuses an operation record can carry. Only the first two mean "still
# running"; the client keeps polling while it sees one of them.
PROCESSING = "processing"
STOPPING = "stopping"
COMPLETED = "completed"
FAILED = "failed"
IDLE = "idle"
ACTIVE_STATUSES = (PROCESSING, STOPPING)
TERMINAL_STATUSES = (COMPLETED, FAILED)

_ERROR_RE = re.compile(r"^error:\s*\[(?P<code>[a-z_]+)\]\s*(?P<message>.*)$", re.DOTALL)


class ProtocolError(ValueError):
    """A frame or a reply could not be understood."""


@dataclass(frozen=True)
class Reply:
    """What the server answered to one call.

    ``ok`` says whether the call was accepted. ``data`` is the JSON object of a
    successful reply (for a read, the data itself; for a change, the accepted
    operation record, and once it has finished, the operation's result merged in
    by the client). ``error`` is the message of a refused call and ``code`` its
    machine-readable reason (``validation``, ``busy``, ``unknown_command`` or
    ``execution``), so a caller can decide whether to retry without reading the
    text. ``id`` is unused by this transport and kept for older callers.
    """

    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    code: str | None = None
    id: int | None = None


# -- framing ------------------------------------------------------------------


def frame(payload: str | bytes) -> bytes:
    """Put ``payload`` in a frame for the wire: ``b"<len>\\n" + payload``.

    Raises :class:`ProtocolError` when the payload is larger than the server
    would accept, so an oversized call fails here instead of being cut off.
    """
    if isinstance(payload, str):
        payload = payload.encode(ENCODING)
    if len(payload) > MAX_FRAME_BYTES:
        raise ProtocolError(f"payload exceeds {MAX_FRAME_BYTES} bytes")
    return str(len(payload)).encode("ascii") + b"\n" + payload


def frame_length(head: bytes) -> int:
    """The number of payload bytes a frame header promises.

    The header must be plain decimal digits, like the server's own reader
    demands; anything else is a framing error and the connection is not to be
    trusted any further.
    """
    if not head or len(head) > MAX_FRAME_HEADER_BYTES or not head.isdigit():
        raise ProtocolError(f"expected a decimal byte count, got {head!r}")
    length = int(head)
    if length > MAX_FRAME_BYTES:
        raise ProtocolError(f"frame exceeds {MAX_FRAME_BYTES} bytes")
    return length


# -- calls and replies ---------------------------------------------------------


def encode_call(name: str, args: dict[str, Any] | None = None) -> str:
    """Write one call as the JSON text the server expects: ``{name: args}``.

    The server rejects JSON that is not strict (a ``NaN`` or an ``Infinity``),
    so those are refused here too, before anything is sent.
    """
    if not isinstance(name, str) or not name:
        raise ProtocolError("a call needs a name")
    args = dict(args or {})
    try:
        return json.dumps({name: args}, allow_nan=False)
    except ValueError as exc:
        raise ProtocolError(f"call {name!r} has a value JSON cannot carry: {exc}") from exc


def parse_reply(text: str) -> Reply:
    """Read a reply frame into a :class:`Reply`.

    A successful reply starts with :data:`OK_MARKER` and carries a JSON object.
    A refused call starts with ``error: [code]``. Anything else is a
    :class:`ProtocolError`: the server is not speaking Remote Control, or the
    connection is out of step.
    """
    if text.startswith(OK_MARKER):
        body = text[len(OK_MARKER) :]
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ProtocolError(f"could not decode the reply's JSON: {exc}") from exc
        if not isinstance(data, dict):
            data = {"result": data}
        return Reply(ok=True, data=data)
    match = _ERROR_RE.match(text.strip())
    if match:
        return Reply(ok=False, error=match.group("message").strip(), code=match.group("code"))
    raise ProtocolError(f"unexpected reply from the server: {text[:200]!r}")


# -- operation records -----------------------------------------------------------


def operation_of(data: dict[str, Any] | None) -> dict[str, Any] | None:
    """The operation record inside a reply, or None when the reply has none.

    A read returns its data directly and has no operation; an accepted change
    carries one under ``operation``; ``get_progress`` reports the latest one
    under the same key.
    """
    if not isinstance(data, dict):
        return None
    operation = data.get("operation")
    return dict(operation) if isinstance(operation, dict) else None


def is_active(operation: dict[str, Any] | None) -> bool:
    """True while the operation is still running (``processing`` or ``stopping``)."""
    return bool(operation) and operation.get("status") in ACTIVE_STATUSES

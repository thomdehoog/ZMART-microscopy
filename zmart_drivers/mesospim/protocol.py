"""
mesoSPIM command-server wire protocol (pure encode/parse).
==========================================================
mesoSPIM-control has no external control API of its own (see the driver
`README.md`). ZMART reaches it through a small **resident command-server
script**, loaded via mesoSPIM's Script Window, which opens a localhost TCP
socket and translates text requests into mesoSPIM ``Core`` signals and state
reads. This module is the pure, socket-free core of the protocol the client and
that server both speak -- encode/parse only.

Why **JSON lines** rather than the Evident/Nikon ``VERB= args`` framing: the
mesoSPIM control surface is fundamentally *dict-shaped*. The Core is driven by
``sig_state_request(dict)`` / ``sig_move_absolute(dict)`` / ``sig_move_relative(
dict)`` and an ``Acquisition`` is itself a dict of ~20 fields. A JSON object per
line maps onto that one-to-one, keeps nested payloads (an acquisition list, a
config block) honest, and stays trivially parseable. One request object and one
reply object per newline-terminated line; UTF-8; ``\n`` terminated.

Request  : ``{"cmd": <str>, "args": {<...>}, "id": <int|null>}``
Reply    : ``{"ok": true,  "data": {<...>}, "id": <int|null>}``
           ``{"ok": false, "error": <str>, "id": <int|null>}``

The command vocabulary (``cmd`` values and their ``args``) is specified in
``server/PROTOCOL.md``; this module is agnostic to it -- it only frames lines.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

TERMINATOR = "\n"
ENCODING = "utf-8"


class ProtocolError(ValueError):
    """A line could not be parsed as a protocol request or reply."""


@dataclass(frozen=True)
class Request:
    """A parsed request line."""

    cmd: str
    args: dict[str, Any] = field(default_factory=dict)
    id: int | None = None


@dataclass(frozen=True)
class Reply:
    """A parsed reply line.

    ``ok`` reports success; ``data`` carries the payload of a successful reply
    and ``error`` the message of a failed one (the other is always empty).
    """

    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    id: int | None = None


# -- encode -------------------------------------------------------------------


def encode_request(cmd: str, *, args: dict[str, Any] | None = None, id: int | None = None) -> str:
    """Build a request line (without the terminator)."""
    if not isinstance(cmd, str) or not cmd:
        raise ProtocolError(f"cmd must be a non-empty string, got {cmd!r}")
    return json.dumps({"cmd": cmd, "args": args or {}, "id": id}, separators=(",", ":"))


def encode_ok(data: dict[str, Any] | None = None, *, id: int | None = None) -> str:
    """Build a success reply line ``{"ok": true, "data": ...}``."""
    return json.dumps({"ok": True, "data": data or {}, "id": id}, separators=(",", ":"))


def encode_error(message: str, *, id: int | None = None) -> str:
    """Build a failure reply line ``{"ok": false, "error": ...}``."""
    return json.dumps({"ok": False, "error": str(message), "id": id}, separators=(",", ":"))


def frame(line: str) -> bytes:
    """Add the newline terminator and encode to bytes for the wire."""
    return (line + TERMINATOR).encode(ENCODING)


# -- parse --------------------------------------------------------------------


def _loads(line: str) -> dict[str, Any]:
    stripped = line.strip()
    if not stripped:
        raise ProtocolError("empty line")
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise ProtocolError(f"expected a JSON object, got {type(obj).__name__}")
    return obj


def parse_request(line: str) -> Request:
    """Parse one line into a :class:`Request`. Raises :class:`ProtocolError`."""
    obj = _loads(line)
    cmd = obj.get("cmd")
    if not isinstance(cmd, str) or not cmd:
        raise ProtocolError(f"request missing 'cmd': {obj!r}")
    args = obj.get("args", {}) or {}
    if not isinstance(args, dict):
        raise ProtocolError(f"request 'args' must be an object, got {type(args).__name__}")
    return Request(cmd=cmd, args=args, id=obj.get("id"))


def parse_reply(line: str) -> Reply:
    """Parse one line into a :class:`Reply`. Raises :class:`ProtocolError`."""
    obj = _loads(line)
    if "ok" not in obj:
        raise ProtocolError(f"reply missing 'ok': {obj!r}")
    ok = bool(obj["ok"])
    data = obj.get("data", {}) or {}
    if not isinstance(data, dict):
        raise ProtocolError(f"reply 'data' must be an object, got {type(data).__name__}")
    return Reply(ok=ok, data=data, error=str(obj.get("error", "")), id=obj.get("id"))

"""Messages between the client and the bridge: one JSON object per line.

Request:  {"id": 7, "op": "get_position", "args": {}, "timeout": 30.0}
Success:  {"id": 7, "ok": true, "result": {"x": 100.0, "y": -20.0, "z": 500.0}}
Failure:  {"id": 7, "ok": false, "kind": "RuntimeError", "error": "StgMove: DR_NOTINITIALIZED (-7)"}

``timeout`` is how long the client waits; the bridge drops a request that has
not started by then, so a request the client gave up on never runs later.
``kind`` is ValueError for a bad request and RuntimeError when NIS refused or
failed; the client raises the same type. Standard library only, because the
bridge imports this file inside NIS-Elements.
"""

from __future__ import annotations

import json
from typing import Any

PROTOCOL_VERSION = 2
DEFAULT_HOST = "127.0.0.1"  # the bridge only ever listens on this computer
DEFAULT_PORT = 54470
DEFAULT_TIMEOUT_S = 30.0

_ERRORS = {"ValueError": ValueError, "RuntimeError": RuntimeError}


class ProtocolError(ValueError):
    """A line that is not a well-formed request or reply."""


def encode_request(request_id: int, op: str, args: dict[str, Any], timeout: float) -> str:
    return json.dumps({"id": request_id, "op": op, "args": args, "timeout": timeout}) + "\n"


def decode_request(line: str) -> tuple[int | None, str, dict[str, Any], float]:
    try:
        msg = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"request is not valid JSON: {exc}") from None
    if not isinstance(msg, dict) or not isinstance(msg.get("op"), str):
        raise ProtocolError("request must be a JSON object with an 'op' string")
    args = msg.get("args") or {}
    if not isinstance(args, dict):
        raise ProtocolError("'args' must be a JSON object")
    request_id = msg.get("id")
    timeout = msg.get("timeout")
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        timeout = DEFAULT_TIMEOUT_S
    return (request_id if isinstance(request_id, int) else None), msg["op"], args, float(timeout)


def encode_reply(request_id: int | None, result: Any) -> str:
    return json.dumps({"id": request_id, "ok": True, "result": result}, default=str) + "\n"


def encode_error(request_id: int | None, exc: BaseException) -> str:
    name = type(exc).__name__
    kind = name if name in _ERRORS else "RuntimeError"
    text = str(exc) if kind == name else f"{name}: {exc}"
    return json.dumps({"id": request_id, "ok": False, "kind": kind, "error": text}) + "\n"


def decode_reply(line: str) -> tuple[int | None, Any]:
    """Return ``(id, result)``, or raise the error the bridge reported."""
    try:
        msg = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"reply is not valid JSON: {exc}") from None
    if not isinstance(msg, dict) or "ok" not in msg:
        raise ProtocolError("reply must be a JSON object with an 'ok' field")
    if msg["ok"]:
        return msg.get("id"), msg.get("result")
    raise _ERRORS.get(msg.get("kind"), RuntimeError)(msg.get("error") or "bridge error")

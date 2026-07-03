"""
Remote-scripting transport + structured-result envelope.
========================================================
The mesoSPIM driver talks to mesoSPIM-control through its **Remote Scripting**
server (an upstream contribution under ``pull_request/``):
a tiny, generic bridge that runs a Python script in the live ``mesoSPIM_Core``
context and returns whatever the script prints. There is **no command vocabulary
on the wire** -- the driver injects a script, mesoSPIM runs it (``self`` == Core),
and the console output comes back.

This module is the pure, socket-free core of that transport:

1. **Framing** -- length-prefixed, both directions::

       message = b"<decimal-byte-count>\\n" + <payload bytes>

   This is the framing the Remote Scripting PR speaks (see
   ``pull_request/PROTOCOL.md``). It suits arbitrary script text (which contains
   newlines) where a line-delimited framing would not.

2. **A structured result over an unstructured channel.** The reply is raw
   console text and may interleave output from other threads (loggers, the demo
   thread), exactly as mesoSPIM's Script Window console does. So every command
   the driver injects is wrapped in :func:`wrap_script`, which:

     - emits its result as ``<nonce>`` + base64(JSON) + ``<nonce-end>`` -- a
       **per-call nonce** so no other output can be mistaken for ours, and
       **base64** so the payload can never contain the delimiter; and
     - catches any exception and emits a structured ``{"ok": false, "error":
       <traceback>}`` instead, so a failing script comes back as a clean NAK, not
       a client-side parse crash.

   :func:`parse_result` extracts that block from the console text and returns a
   :class:`Reply`. If no block is present (e.g. a syntax error before the harness
   ran, which mesoSPIM prints as a bare traceback), the whole console text is
   returned as the error.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from typing import Any

ENCODING = "utf-8"

# Bumped only if the framing or harness contract changes.
PROTOCOL_VERSION = 1


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


# -- structured result harness ------------------------------------------------

_MARKER_PREFIX = "<<<ZMART-RESULT:"
_MARKER_SUFFIX = ":ZMART-END>>>"


def _markers(nonce: str) -> tuple[str, str]:
    return f"{_MARKER_PREFIX}{nonce}|", f"|{nonce}{_MARKER_SUFFIX}"


def wrap_script(body: str, nonce: str) -> str:
    """Wrap a command ``body`` in the emit/try-except harness.

    ``body`` is Python that runs in the Core context (``self`` == Core) and must
    assign the result to a name ``_result``. ``nonce`` must be unique per call.
    The returned script prints exactly one delimited base64(JSON) block.

    Scope note (critical): mesoSPIM runs an injected script with ``exec(script)``
    **inside** ``mesoSPIM_Core.execute_script`` -- a method, so ``globals() is not
    locals()``. In that frame any nested function, lambda or comprehension in
    ``body`` resolves its free names via the *module* globals, not the script's own
    assignments, and raises ``NameError`` (e.g. a ``lambda`` that reads ``_pos``, or
    a dict comprehension). So we do NOT inline ``body`` at that top level; we
    ``exec`` it in a dedicated namespace dict where ``globals is locals`` (normal
    module scoping), with ``self`` injected. The emit code stays flat at the outer
    top level, where reading the module-local ``_z*`` imports is fine.
    """
    start, end = _markers(nonce)
    return (
        "import json as _zjson, base64 as _zb64, traceback as _ztb\n"
        "_zns = {'self': self}\n"
        "try:\n"
        f"    exec(compile({body!r}, '<zmart-cmd>', 'exec'), _zns)\n"
        "    _zres = {'ok': True, 'data': _zns.get('_result')}\n"
        "except Exception:\n"
        "    _zres = {'ok': False, 'error': _ztb.format_exc()}\n"
        f"print({start!r} + _zb64.b64encode(_zjson.dumps(_zres).encode('utf-8')).decode('ascii') + {end!r})\n"
    )


def parse_result(console: str, nonce: str) -> Reply:
    """Extract the delimited base64(JSON) result block from console text.

    Returns a :class:`Reply`. If the block is absent, the whole console text is
    returned as an error (this is how a pre-harness failure -- a syntax error, an
    import error, an auth/plumbing issue -- surfaces).
    """
    start, end = _markers(nonce)
    match = re.search(re.escape(start) + "(.*?)" + re.escape(end), console, re.DOTALL)
    if not match:
        text = console.strip()
        return Reply(ok=False, error=text or "no result marker in server reply")
    try:
        payload = base64.b64decode(match.group(1)).decode("utf-8")
        obj = json.loads(payload)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"could not decode result payload: {exc}") from exc
    if not isinstance(obj, dict) or "ok" not in obj:
        raise ProtocolError(f"malformed result object: {obj!r}")
    ok = bool(obj["ok"])
    data = obj.get("data", {}) or {}
    if not isinstance(data, dict):
        raise ProtocolError(f"result 'data' must be an object, got {type(data).__name__}")
    return Reply(ok=ok, data=data, error=str(obj.get("error", "")))

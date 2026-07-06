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

2. **A simple, readable result line.** Every command is wrapped in
   :func:`wrap_script`, which runs the body and prints one line -- either
   ``__ZMART_OK__<json>`` (the result dict) or ``__ZMART_ERR__<json-string>``
   (a traceback) if it raised. That keeps the injected script plain enough to
   read, tweak, and ``regex`` by hand in mesoSPIM's Script Window, while still
   giving the client a structured ``{ok, data, error}`` back. :func:`parse_result`
   scans the console for the last such line (so it wins over any earlier stray
   output) and returns a :class:`Reply`; if there is none (a syntax/import error
   before the harness ran), the whole console text becomes the error.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

ENCODING = "utf-8"

# Bumped only if the framing or harness contract changes.
PROTOCOL_VERSION = 1

# Result markers. A distinctive prefix on one line; the JSON follows on the same
# line (so a single regex `^__ZMART_(OK|ERR)__(.*)$` extracts it).
OK_MARKER = "__ZMART_OK__"
ERR_MARKER = "__ZMART_ERR__"


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


def wrap_script(body: str) -> str:
    """Wrap a command ``body`` in a minimal print-the-result harness.

    ``body`` is Python that runs in the Core context (``self`` == Core) and must
    assign the result to a local named ``_result`` (a JSON-serialisable dict).
    The returned script prints one marker line -- ``__ZMART_OK__<json>`` on
    success, or ``__ZMART_ERR__<json>`` (a traceback) if the body raised.
    """
    indented = "\n".join("    " + line for line in body.splitlines()) or "    pass"
    return (
        "import json, traceback\n"
        "try:\n"
        f"{indented}\n"
        f"    print({OK_MARKER!r} + json.dumps(_result))\n"
        "except Exception:\n"
        f"    print({ERR_MARKER!r} + json.dumps(traceback.format_exc()))\n"
    )


def parse_result(console: str) -> Reply:
    """Turn the script's console output into a :class:`Reply`.

    Scans for the last ``__ZMART_OK__`` / ``__ZMART_ERR__`` line. If neither is
    present (a pre-harness failure -- syntax/import error, an auth/plumbing
    issue), the whole console text is returned as the error.
    """
    for line in reversed(console.splitlines()):
        if line.startswith(OK_MARKER):
            data = _loads(line[len(OK_MARKER):])
            if not isinstance(data, dict):
                raise ProtocolError(f"result must be an object, got {type(data).__name__}")
            return Reply(ok=True, data=data)
        if line.startswith(ERR_MARKER):
            return Reply(ok=False, error=str(_loads(line[len(ERR_MARKER):])))
    text = console.strip()
    return Reply(ok=False, error=text or "no result marker in server reply")


def _loads(payload: str):
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"could not decode result payload: {exc}") from exc

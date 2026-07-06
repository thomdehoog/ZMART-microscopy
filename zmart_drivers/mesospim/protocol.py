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

2. **A minimal result line.** Every command is wrapped by :func:`wrap_script`
   into a *flat* script (no ``try/except``, no indentation) that runs the body
   and prints one line, ``__ZMART_OK__<json>``. That keeps the injected script as
   short and plain as possible -- easy to read, tweak, and ``regex`` by hand in
   mesoSPIM's Script Window. On any error the body just raises: mesoSPIM's own
   ``Core.execute_script`` prints the traceback to the console, and
   :func:`parse_result` -- finding no ``__ZMART_OK__`` line -- returns that whole
   console text as the error. So failures still surface without the harness
   carrying its own try/except.

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


# -- structured result harness ------------------------------------------------


def wrap_script(body: str) -> str:
    """Wrap a command ``body`` into a minimal, flat print-the-result script.

    ``body`` is Python that runs in the Core context (``self`` == Core) and must
    assign the result to a local named ``_result`` (a JSON-serialisable dict).
    The returned script is flat -- no ``try/except``, no indentation -- and just
    prints ``__ZMART_OK__<json>``. If the body raises, mesoSPIM's
    ``Core.execute_script`` prints the traceback and :func:`parse_result` (finding
    no ``__ZMART_OK__`` line) returns it as the error.
    """
    return f"import json\n{body}\nprint({OK_MARKER!r} + json.dumps(_result))\n"


def parse_result(console: str) -> Reply:
    """Turn the script's console output into a :class:`Reply`.

    Scans for the last ``__ZMART_OK__`` line. If there is none (the body raised,
    or a syntax/auth/plumbing failure), the whole console text -- the traceback
    mesoSPIM printed -- is returned as the error.
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

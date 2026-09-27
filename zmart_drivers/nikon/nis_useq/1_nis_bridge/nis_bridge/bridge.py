"""The bridge inside NIS-Elements: what ``start_bridge.mac`` calls.

``start`` opens the server, ``pump`` runs queued requests on the NIS main
thread (the macro loop calls it), and ``stop`` closes the server. The pieces:

* ``nis_dll.py``: the raw NIS functions, one wrapper each;
* ``readers.py``: the read-only requests, one method each;
* ``commands.py``: the requests that change something, one method each;
* ``dispatch.py``: the server, the queue and the timeouts;
* ``profile.py``: every timing constant;
* ``protocol.py``: the message format the client shares.

Rules that keep it safe: only the requests in ``dispatch.OPS`` can be called,
no macro text is executed, and every NIS call runs on the NIS main thread,
one at a time. Standard library only (NIS 6.10 bundles Python 3.12 with numpy
and nothing else).

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB), University of Zurich
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
Date: 2026-09-27
License: MIT
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import time
from typing import Any

from .dispatch import BRIDGE_VERSION, serve
from .nis_dll import NisDll
from .settings import HOST, LOG_FILE, PORT, PUMP_WAIT_S, STALE_SERVER_S

log = logging.getLogger("nis_bridge")

# The running server is kept in __main__ so that it survives the module reload
# the macro does to pick up code changes.
_running: dict[str, Any] = sys.modules["__main__"].__dict__.setdefault("_nis_bridge", {})
STOP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bridge.stop")


def start(port: int = PORT) -> str:
    """Start listening (called once by the macro before its pump loop)."""
    old = _running.get("server")
    if old is not None:
        if not old.stop_requested and time.monotonic() - old.last_pump < STALE_SERVER_S:
            return f"bridge already running on port {port}"
        stop()  # left over from an earlier macro run: free its port
    if os.path.exists(STOP_FILE):
        os.remove(STOP_FILE)
    log_path = os.path.join(tempfile.gettempdir(), LOG_FILE)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.handlers[:] = [handler]
    log.setLevel(logging.INFO)
    try:
        _running["server"] = serve(NisDll(), HOST, port)
    except OSError as exc:
        log.error("could not start: %s", exc)
        return f"bridge failed to start on port {port}: {exc}"
    log.info("bridge %s listening on port %s", BRIDGE_VERSION, port)
    return f"bridge {BRIDGE_VERSION} listening on {HOST}:{port}; log: {log_path}"


def pump(wait_s: float = PUMP_WAIT_S) -> None:
    """Run queued requests on the NIS main thread (called by the macro loop)."""
    server = _running.get("server")
    if server is None:
        return
    server.pump(wait_s)
    if server.stop_requested and not os.path.exists(STOP_FILE):
        open(STOP_FILE, "w").close()  # ends the macro loop


def stop() -> str:
    """Close the server (called by the macro after its loop ends)."""
    if os.path.exists(STOP_FILE):
        os.remove(STOP_FILE)
    server = _running.pop("server", None)
    if server is None:
        return "bridge is not running"
    server.shutdown()
    server.server_close()
    log.info("bridge stopped")
    for handler in log.handlers[:]:
        log.removeHandler(handler)
        handler.close()
    return "bridge stopped"

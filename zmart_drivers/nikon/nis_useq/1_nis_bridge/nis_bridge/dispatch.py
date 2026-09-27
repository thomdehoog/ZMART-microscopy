"""The server: socket threads queue requests, the NIS main thread runs them.

Every NIS call must run on the NIS main thread (``Capture`` from any other
thread crashes NIS-Elements). So the socket threads only queue requests, and
the macro loop runs them one at a time by calling ``BridgeServer.pump``. A
request the client has stopped waiting for is never run late.

Standard library only: this runs inside NIS-Elements.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB), University of Zurich
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
Date: 2026-09-27
License: MIT
"""

from __future__ import annotations

import logging
import queue
import socketserver
import threading
import time
from typing import Any

from .commands import COMMANDS, Commands
from .protocol import PROTOCOL_VERSION, ProtocolError, decode_request, encode_error, encode_reply
from .readers import READS, Readers
from .settings import HOST, PORT, SERVE_POLL_S

log = logging.getLogger("nis_bridge")

BRIDGE_VERSION = "0.2.0"  # of this server, reported by ping; not the package version
SERVER = ("ping", "shutdown")  # the requests about the bridge itself, answered here
OPS = SERVER + READS + COMMANDS  # every request a client may send


class _Job:
    def __init__(self, op: str, args: dict) -> None:
        self.op, self.args = op, args
        self.lock = threading.Lock()  # decides between "started" and "cancelled"
        self.started = self.cancelled = False
        self.done = threading.Event()
        self.result: Any = None
        self.error: BaseException | None = None


class BridgeServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = False  # never let a second bridge share the port on Windows
    daemon_threads = True

    def __init__(self, address: tuple[str, int], api: Any) -> None:
        super().__init__(address, _Handler)
        self.readers = Readers(api)
        commands = Commands(api, self.readers)
        # what answers each request: a method of the readers, the commands, or this server
        self.ops = {
            "ping": self._ping,
            "shutdown": self._request_shutdown,
            **{op: getattr(self.readers, op) for op in READS},
            **{op: getattr(commands, op) for op in COMMANDS},
        }
        self.jobs: queue.Queue[_Job] = queue.Queue()
        self.stop_requested = False
        self.last_pump = 0.0

    def _ping(self, args: dict) -> dict:
        """Who answers: the bridge and protocol versions, and NIS's own version."""
        return {
            "bridge": BRIDGE_VERSION,
            "protocol": PROTOCOL_VERSION,
            "nis": self.readers.get_version({}),
        }

    def _request_shutdown(self, args: dict) -> dict:
        """Ask the macro loop to end; the server closes when it does."""
        self.stop_requested = True
        return {"stopping": True}

    def pump(self, wait_s: float = 0.0) -> int:
        """Run queued requests on the calling thread; wait up to ``wait_s`` for the first."""
        self.last_pump = time.monotonic()
        ran = 0
        while True:
            try:
                job = (
                    self.jobs.get(timeout=wait_s)
                    if (wait_s and not ran)
                    else self.jobs.get_nowait()
                )
            except queue.Empty:
                return ran
            with job.lock:
                if job.cancelled:  # the client stopped waiting; never run it late
                    continue
                job.started = True
            try:
                job.result = self.ops[job.op](job.args)
            except BaseException as exc:
                log.exception("op %s failed", job.op)
                job.error = exc
            job.done.set()
            ran += 1

    def handle_line(self, line: str) -> str:
        """Queue one request, wait for the main thread to run it, return the reply line."""
        request_id = None
        try:
            request_id, op, args, timeout = decode_request(line)
            if op not in OPS:
                raise ValueError(f"unknown op {op!r}; known: {', '.join(OPS)}")
            job = _Job(op, args)
            self.jobs.put(job)
            if not job.done.wait(timeout):
                with job.lock:
                    job.cancelled = not job.started
                if job.cancelled:
                    raise RuntimeError(
                        f"{op!r} did not start within {timeout:g} s: "
                        "is start_bridge.mac still running in NIS-Elements?"
                    )
                raise RuntimeError(f"{op!r} is still running in NIS after {timeout:g} s")
            if job.error is not None:
                raise job.error
            return encode_reply(request_id, job.result)
        except ProtocolError as exc:
            return encode_error(request_id, ValueError(str(exc)))
        except BaseException as exc:
            return encode_error(request_id, exc)


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        server: BridgeServer = self.server  # type: ignore[assignment]
        while raw := self.rfile.readline():
            line = raw.decode("utf-8", errors="replace").strip()
            if line:
                self.wfile.write(server.handle_line(line).encode("utf-8"))
                self.wfile.flush()


def serve(api: Any, host: str = HOST, port: int = PORT) -> BridgeServer:
    """Listen in a background thread. The caller must call ``server.pump()`` regularly."""
    server = BridgeServer((host, port), api)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": SERVE_POLL_S}, daemon=True
    )
    thread.start()
    return server

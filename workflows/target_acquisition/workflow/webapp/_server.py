"""A small local web server for the run page — Python stdlib only.

Nothing heavy on purpose: :mod:`http.server` from the standard library
carries the page, the widget modules, the live event stream, and the
image bytes. There is no framework, no build step, and nothing fetched
from the internet — the same offline promise the notebooks make.

It binds to 127.0.0.1 by default: this page drives a real microscope, so
it should only ever be reachable from the microscope PC itself unless you
very deliberately decide otherwise.
"""

from __future__ import annotations

import json
import queue
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from ._flow import RunFlow
from ._host import WidgetHub, _jsonable
from ._page import page_html


class _Handler(BaseHTTPRequestHandler):
    # Set by make_server(): the one hub/flow pair every request talks to.
    hub: WidgetHub
    flow: RunFlow

    # Quiet: one log line per request is notebook-kernel noise, not signal.
    def log_message(self, _format: str, *_args: Any) -> None:
        pass

    # -- small helpers ---------------------------------------------------------

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, default=_jsonable).encode("utf-8")
        self._send(status, body, "application/json")

    def _read_json(self) -> Any:
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= 4 * 1024 * 1024:
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None

    # -- GET ---------------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 -- http.server's naming
        path = self.path.split("?", 1)[0]
        if path == "/" or path == "/index.html":
            self._send(200, page_html().encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/state":
            self._send_json(
                {"widgets": self.hub.state_snapshot(), "flow": self.flow.flow_snapshot()}
            )
            return
        if path.startswith("/esm/") and path.endswith(".mjs"):
            widget = self.hub.widget(path[len("/esm/") : -len(".mjs")])
            if widget is None:
                self._send(404, b"no such widget", "text/plain")
                return
            self._send(200, widget._esm.encode("utf-8"), "text/javascript; charset=utf-8")
            return
        if path.startswith("/buffer/"):
            data = self.hub.buffer(path[len("/buffer/") :])
            if data is None:
                self._send(404, b"buffer expired", "text/plain")
                return
            self._send(200, data, "application/octet-stream")
            return
        if path == "/events":
            self._serve_events()
            return
        self._send(404, b"not found", "text/plain")

    def _serve_events(self) -> None:
        """One server-sent-events stream: everything Python wants a tab to know."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        client = self.hub.add_client()
        try:
            while True:
                try:
                    payload = client.get(timeout=15.0)
                except queue.Empty:
                    # A comment line keeps the connection provably alive and
                    # lets a closed tab surface as a write error promptly.
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                    continue
                self.wfile.write(b"data: " + payload.encode("utf-8") + b"\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # the tab went away — normal
        finally:
            self.hub.remove_client(client)

    # -- POST ----------------------------------------------------------------------

    def do_POST(self) -> None:  # noqa: N802 -- http.server's naming
        body = self._read_json()
        if not isinstance(body, dict):
            self._send_json({"ok": False, "error": "malformed request"}, status=400)
            return
        if self.path == "/action":
            ok = self.flow.run_step(str(body.get("step")))
            self._send_json({"ok": ok}, status=200 if ok else 404)
            return
        if self.path == "/msg":
            ok = self.hub.dispatch_message(str(body.get("widget")), body.get("content"))
            self._send_json({"ok": ok}, status=200 if ok else 404)
            return
        if self.path == "/trait":
            ok = self.hub.dispatch_trait_changes(str(body.get("widget")), body.get("changes"))
            self._send_json({"ok": ok}, status=200 if ok else 404)
            return
        self._send_json({"ok": False, "error": "not found"}, status=404)


def make_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    demo: bool = False,
    analysis_repo: Any = None,
    vendor: str = "leica",
    demo_root: Any = None,
    af_job: str | None = None,
) -> tuple[ThreadingHTTPServer, WidgetHub, RunFlow]:
    """Build the hub, the flow, and a ready-to-run HTTP server."""
    hub = WidgetHub()
    flow = RunFlow(
        hub,
        demo=demo,
        analysis_repo=analysis_repo,
        vendor=vendor,
        demo_root=demo_root,
        af_job=af_job,
    )
    handler = type("BoundHandler", (_Handler,), {"hub": hub, "flow": flow})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server, hub, flow

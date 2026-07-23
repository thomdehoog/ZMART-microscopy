"""The small web server behind the visualization studio.

Its whole job is to hand two kinds of thing to the browser on a single local
address:

1. the built viewer web page (the ``frontend/dist`` folder), and
2. the image volume as OME-Zarr (a folder of many small files under ``/data``),

plus a couple of tiny JSON endpoints under ``/api`` for talking back to Python
(for the spike, just one: an echo of a "go to this box" command, standing in
for a future "move the stage there").

We use Python's built-in threading HTTP server rather than a web framework.
The task is serving static files and answering two short questions, which the
standard library does well; avoiding a framework keeps the whole tool
installable from conda with nothing exotic, and keeps it light. The viewer asks
for many little image chunks at once, so the server is threaded — each request
is handled on its own thread and they do not queue behind one another.

Everything is bound to localhost (this machine only). Later, when this server
also relays commands to real microscope hardware, that same localhost-only
posture is what keeps it from being reachable across the network.
"""

from __future__ import annotations

import json
import functools
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Where the two kinds of content live on disk. Both are resolved to absolute
# paths so the server behaves the same regardless of the working directory it
# was started from.
_HERE = Path(__file__).resolve().parent
_FRONTEND_DIST = (_HERE.parent / "frontend" / "dist").resolve()
_DEMO_STORE = (_HERE / "demo_store").resolve()


class _Handler(SimpleHTTPRequestHandler):
    """Serve the built page, the image data, and the small JSON endpoints.

    Requests under ``/data`` are image chunks and come from the demo store;
    requests under ``/api`` are JSON commands answered here; everything else is
    a file from the built viewer page (with a fallback to ``index.html`` so the
    single-page app loads however it is addressed).
    """

    # Keep connections alive between requests. The viewer fetches hundreds of
    # small chunks; without this each one would open a fresh connection.
    protocol_version = "HTTP/1.1"

    # Directory the base class serves from; set per-instance in __init__.
    def __init__(self, *args, data_dir: Path, site_dir: Path, **kwargs):
        self._data_dir = data_dir
        self._site_dir = site_dir
        super().__init__(*args, directory=str(site_dir), **kwargs)

    def handle_one_request(self) -> None:
        """Serve one request, ignoring the client hanging up early.

        The viewer constantly cancels chunk requests it no longer needs (you
        panned away before they arrived). That shows up here as a dropped
        connection; it is normal, not an error, so we swallow it quietly
        instead of printing a scary traceback to the operator's console.
        """
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True

    # -- routing ---------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 (name fixed by base class)
        if self.path.startswith("/data/"):
            self._serve_from_data()
            return
        if self.path.startswith("/api/"):
            self._serve_api_get()
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if self.path.startswith("/api/"):
            self._serve_api_post()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    # -- image data ------------------------------------------------------

    def _serve_from_data(self) -> None:
        """Serve one file from the OME-Zarr store under ``/data``.

        The browser requests image chunks by path, e.g.
        ``/data/demo.zarr/0/0.24.0.0`` (the numbers are the chunk's position;
        the volume's metadata tells the viewer to join them with dots). We
        translate that to a file inside the demo store, refusing any path that
        tries to climb out of it.
        """
        rel = self.path[len("/data/") :].split("?", 1)[0].split("#", 1)[0]
        target = (self._data_dir / rel).resolve()
        if self._data_dir not in target.parents and target != self._data_dir:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not target.is_file():
            # A missing chunk is normal in zarr (it means "all background
            # here"), so answer 404 quietly rather than as an error.
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._send_file(target)

    def _send_file(self, target: Path) -> None:
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        # The demo volume never changes during a session, so let the browser
        # cache chunks it has already fetched.
        self.send_header("Cache-Control", "max-age=3600")
        self.end_headers()
        self.wfile.write(data)

    # -- JSON endpoints --------------------------------------------------

    def _serve_api_get(self) -> None:
        if self.path.rstrip("/") == "/api/health":
            self._send_json({"ok": True})
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def _serve_api_post(self) -> None:
        """Handle the one control command the spike understands.

        ``POST /api/goto`` receives the corner coordinates of a box the operator
        placed in the viewer and, for now, simply echoes them back. This proves
        the path a real "move the microscope to this region" command will travel
        — from a click in the browser, to Python, and (eventually) on to the
        hardware — without any hardware attached.
        """
        if self.path.rstrip("/") != "/api/goto":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self.send_error(HTTPStatus.BAD_REQUEST)
            return
        # A real driver call would go here. For the spike we acknowledge.
        self._send_json({"received": payload, "action": "goto (demo: no hardware)"})

    def _send_json(self, obj: dict) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # Quieten the default per-request logging so the console stays readable.
    def log_message(self, *args) -> None:  # noqa: D401
        pass


def make_server(
    port: int = 8848,
    *,
    data_dir: Path = _DEMO_STORE,
    site_dir: Path = _FRONTEND_DIST,
) -> ThreadingHTTPServer:
    """Create (but do not start) the viewer's web server.

    Bound to localhost only. Call ``serve_forever`` on the returned server to
    run it, or use :func:`serve`.
    """
    handler = functools.partial(_Handler, data_dir=data_dir, site_dir=site_dir)
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


def serve(port: int = 8848) -> None:
    """Run the server until interrupted. The viewer page will be at ``/``."""
    server = make_server(port)
    print(f"ZMART Viz Studio serving on http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Serve the visualization studio.")
    parser.add_argument("--port", type=int, default=8848)
    args = parser.parse_args()
    serve(args.port)

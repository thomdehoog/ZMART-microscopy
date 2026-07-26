"""The small web server behind the visualization studio.

Its whole job is to hand two kinds of thing to the browser on a single local
address:

1. the built viewer web page (the ``frontend/dist`` folder), and
2. the image volume as OME-Zarr (a folder of many small files under ``/data``),

plus a couple of tiny JSON endpoints under ``/api``: what to open, and the
targets the operator has drawn.

This server deliberately does **not** talk to the microscope. The studio is a
viewer: it shows images and lets you mark places in them. Acting on those marks —
driving the stage, starting an acquisition — belongs to the control application,
which reads the targets from the file saved beside the image data. Keeping the
two apart means the viewer can be opened on any data, anywhere, by anyone, with
no possibility of it moving an instrument.

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

import functools
import json
import math
import os
import tempfile
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Where the two kinds of content live on disk. Both are resolved to absolute
# paths so the server behaves the same regardless of the working directory it
# was started from.
_HERE = Path(__file__).resolve().parent
_FRONTEND_DIST = (_HERE.parent / "frontend" / "dist").resolve()
_DEMO_STORE = (_HERE / "demo_store").resolve()
_ANNOTATIONS_FILE = "zmart-annotations.json"
_EMPTY_ANNOTATIONS = {"version": 1, "annotations": []}


def _validate_annotations(payload: object) -> dict:
    """Return a small, safe annotation document or raise ValueError."""
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("expected annotation document version 1")
    items = payload.get("annotations")
    if not isinstance(items, list) or len(items) > 10_000:
        raise ValueError("annotations must be a list of at most 10000 items")
    clean = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("each annotation must be an object")
        annotation_id = item.get("id")
        kind = item.get("type")
        if not isinstance(annotation_id, str) or not annotation_id or annotation_id in seen:
            raise ValueError("annotation ids must be unique non-empty strings")
        if kind not in {"point", "axis_aligned_bounding_box"}:
            raise ValueError("unsupported annotation type")
        coordinate_keys = ("point",) if kind == "point" else ("pointA", "pointB")
        result = {"id": annotation_id, "type": kind}
        for key in coordinate_keys:
            value = item.get(key)
            if (
                not isinstance(value, list)
                or not 1 <= len(value) <= 8
                or any(
                    isinstance(x, bool)
                    or not isinstance(x, (int, float))
                    or not math.isfinite(x)
                    for x in value
                )
            ):
                raise ValueError(f"{key} must contain finite coordinates")
            result[key] = [float(x) for x in value]
        description = item.get("description", "")
        if not isinstance(description, str) or len(description) > 1000:
            raise ValueError("description must be a string of at most 1000 characters")
        result["description"] = description
        clean.append(result)
        seen.add(annotation_id)
    return {"version": 1, "annotations": clean}


class _Handler(SimpleHTTPRequestHandler):
    """Serve the built page, the image data, and the small JSON endpoints.

    Requests under ``/data`` are image chunks and come from the demo store;
    requests under ``/api`` are JSON commands answered here; everything else is
    a file from the built viewer page. The app is loaded at ``/`` (which serves
    ``index.html``); there is no deep-link fallback because the app never needs
    one.
    """

    # Keep connections alive between requests. The viewer fetches hundreds of
    # small chunks; without this each one would open a fresh connection.
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, data_dir: Path, site_dir: Path, config: dict, **kwargs):
        self._data_dir = data_dir  # the OME-Zarr store, served under /data
        self._site_dir = site_dir  # the built page, served as the base directory
        self._config = config  # what the page should open, answered at /api/config
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
        if self.path.rstrip("/") == "/api/config":
            self._serve_config()
            return
        if self.path.rstrip("/") == "/api/annotations":
            path = self._data_dir / _ANNOTATIONS_FILE
            try:
                payload = _validate_annotations(json.loads(path.read_text("utf-8")))
            except FileNotFoundError:
                payload = _EMPTY_ANNOTATIONS
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                self._send_json({"error": "invalid annotation sidecar"}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            self._send_json(payload)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def _serve_config(self) -> None:
        """Tell the page which store to open and how to display it.

        The page asks rather than assumes, so that pointing the viewer at a real
        acquisition is a server-side decision (a ``--data`` argument) and needs
        no rebuild of the frontend.
        """
        self._send_json(self._config)

    def _serve_api_post(self) -> None:
        """Save the targets the operator has drawn.

        This is the only thing the viewer sends back, and it goes to a file, not
        to an instrument. The document is written to a temporary file and then
        moved into place in a single step, so a save interrupted half-way leaves
        the previous targets intact rather than a truncated file.
        """
        if self.path.rstrip("/") != "/api/annotations":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self.send_error(HTTPStatus.BAD_REQUEST)
            return
        try:
            document = _validate_annotations(payload)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        path = self._data_dir / _ANNOTATIONS_FILE
        try:
            fd, temporary = tempfile.mkstemp(
                prefix=f".{_ANNOTATIONS_FILE}.", suffix=".tmp", dir=self._data_dir
            )
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(document, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except OSError:
            try:
                os.unlink(temporary)
            except (OSError, UnboundLocalError):
                pass
            self._send_json({"error": "could not save annotations"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self._send_json(document)

    def _send_json(self, obj: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
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
    store: str | list[str] = "demo.zarr",
    window: tuple[float, float] | None = None,
    depth_samples: int = 256,
    chrome: bool = False,
) -> ThreadingHTTPServer:
    """Create (but do not start) the viewer's web server.

    Bound to localhost only. Call ``serve_forever`` on the returned server to
    run it, or use :func:`serve`.

    Both directories are resolved here, and that is load-bearing rather than
    tidiness: the traversal check in the handler resolves each request target,
    so a caller-supplied directory that is *not* already resolved can never
    contain it and every file is refused. A mapped network drive is the case
    that bites — ``Z:\\...`` resolves to ``\\\\server\\share\\...``, which
    shares no prefix with what the caller passed.
    """
    from contrast import display_window, intensity_histogram
    from stores import channel_color, layer_names

    data_dir = Path(data_dir).resolve()
    names = [store] if isinstance(store, str) else list(store)
    labels = layer_names(names)
    layers = []
    for name, label in zip(names, labels, strict=True):
        # Both windows travel with the layer so switching between the plane and
        # the volume is instant: the client already has what each mode needs
        # and never goes back to the server for it.
        flat = window if window is not None else display_window(data_dir / name)
        volume = (
            window
            if window is not None
            else display_window(data_dir / name, volumetric=True)
        )
        color = channel_color(name) if len(names) > 1 else None
        layers.append(
            {
                "name": label,
                "source": f"/data/{name}/|zarr2:",
                "window": {"low": flat[0], "high": flat[1]},
                "volumeWindow": {"low": volume[0], "high": volume[1]},
                "color": list(color) if color else None,
                "histogram": intensity_histogram(data_dir / name),
            }
        )
    config = {"layers": layers, "depthSamples": depth_samples, "chrome": chrome}
    handler = functools.partial(
        _Handler,
        data_dir=data_dir,
        site_dir=Path(site_dir).resolve(),
        config=config,
    )
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

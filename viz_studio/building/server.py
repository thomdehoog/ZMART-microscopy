"""A web server that answers for a picture it does not hold.

Every piece it serves is built the moment it is asked for, out of the tiles the
transfer really contains. The description is written from the arrangement; the
pieces are built by :class:`composer.Composer`.

It keeps a note of what it was asked for, split by resolution. That is how the
question "which copy did the engine actually choose to draw?" gets an answer from
the traffic rather than from an impression of how blurry the window looks — a
distinction the earlier measurements in this repo learned the hard way, having
reached four confident conclusions from photographs and had all four turn out
wrong.

The browser is served from a different port, so every answer carries the header
saying a page from elsewhere may read it. Without it the requests are made,
refused by the browser, and the window stays black with the reason only in a
console nobody is looking at.
"""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from composer import Composer

# What the built picture is called in the address. Anything else asked for is
# answered with a plain "nothing here".
STORE = "built.ome.zarr"


def serve(composer: Composer, port: int = 0):
    """Start the server; hand back it, its address, and its record of work."""
    ledger = {
        "pieces": {level: 0 for level in range(composer.mosaic.levels)},
        "work_ms": {level: [] for level in range(composer.mosaic.levels)},
        "descriptions": 0,
        "refused": [],
        "first_asked": None,
    }
    guard = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            """Quiet. What was asked for is kept in the ledger instead."""

        def _send(self, body: bytes, kind: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):
            asked = self.path.split("?")[0].strip("/")
            if ledger["first_asked"] is None:
                ledger["first_asked"] = time.perf_counter()
            if not asked.startswith(STORE):
                return self._missing(asked)
            inside = asked[len(STORE):].strip("/")

            if inside == "zarr.json":
                ledger["descriptions"] += 1
                return self._send(composer.group_json(), "application/json")

            parts = inside.split("/")
            if len(parts) == 2 and parts[1] == "zarr.json" and parts[0].isdigit():
                level = int(parts[0])
                if not 0 <= level < composer.mosaic.levels:
                    return self._missing(asked)
                ledger["descriptions"] += 1
                return self._send(composer.array_json(level), "application/json")

            # A piece is named by its resolution, then "c", then one number per
            # axis: depth, height, width. Three, because a transfer has three axes.
            if len(parts) == 5 and parts[1] == "c" and parts[0].isdigit():
                level = int(parts[0])
                if not 0 <= level < composer.mosaic.levels:
                    return self._missing(asked)
                if not all(one.isdigit() for one in parts[2:]):
                    return self._missing(asked)
                plane, row, column = (int(one) for one in parts[2:])
                deep, down, across = composer.grid(level)
                if not (0 <= plane < deep and 0 <= row < down
                        and 0 <= column < across):
                    return self._missing(asked)
                began = time.perf_counter()
                body = composer.bytes_for(level, plane, row, column)
                spent = (time.perf_counter() - began) * 1000
                with guard:
                    ledger["work_ms"][level].append(spent)
                    ledger["pieces"][level] += 1
                return self._send(body, "application/octet-stream")

            return self._missing(asked)

        def _missing(self, asked: str) -> None:
            """Say plainly there is nothing here, and remember having been asked.

            404 rather than anything politer, and that is deliberate. The drawing
            engine treats 403, 404 and a failed connection as "this piece is
            absent" and fills the ground from the fill value without complaint. A
            204, which reads as the more courteous answer, is taken instead as a
            successful reply with an empty body and fails to decode — the polite
            answer is the broken one.
            """
            with guard:
                ledger["refused"].append(asked)
            body = b"nothing here"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}", ledger

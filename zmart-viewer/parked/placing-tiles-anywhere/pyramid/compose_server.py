"""A little web server that answers for one picture it does not actually hold.

Everything it serves is made the moment it is asked for. The description is
written out of the geometry, and each piece of the picture — at whichever of the
four sizes was asked for — is assembled from whichever positions reach into it.
Nothing on disk is ever the picture; the positions are, and they sit wherever the
stage put them.

The ledger it keeps is split by size, because the whole question here is what the
smaller copies cost. When the viewer is zoomed out and asks only for eighth-size
pieces, that shows up as work charged to level 3 and none to level 0, which is how
we can tell from the server alone which size the engine chose to draw.

The browser is on a different port from this one, so every answer carries the
header that says a page from elsewhere is allowed to read it. Without it the
requests are made, refused by the browser, and the window stays black with the
reason only in the console.
"""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import geometry as g
from compose import Composer

STORE = "pyramid.ome.zarr"


def serve(positions_folder: Path, places, port: int = 0, composer=None):
    """Start the server and hand back it, its address, and its record of work.

    ``composer`` lets a caller hand in something other than the plain one — the
    diagnostic in ``which_level_is_drawn.py`` hands in a composer that marks each
    size differently, so that a photograph says which size reached the screen.
    """
    composer = composer or Composer(positions_folder, places)
    guard = threading.Lock()
    ledger = {
        "pieces": {level: 0 for level in range(g.LEVELS)},
        # Two timings per piece, because they answer different questions. The
        # first is the work itself; the second includes the wait while other
        # requests the browser made at the same moment are served ahead of it,
        # which is what an operator actually waits through.
        "work_ms": {level: [] for level in range(g.LEVELS)},
        "compose_ms": {level: [] for level in range(g.LEVELS)},
        "first_asked": None,
        "descriptions": 0,
        "refused": [],
        # Every piece asked for, in the order it was asked for. The order is the
        # evidence for which size the engine actually chose to draw: it fetches the
        # whole pyramid of this small picture either way, so counting what arrived
        # says nothing, but what it reached for *first* says a great deal.
        "order": [],
    }

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
                if not 0 <= level < g.LEVELS:
                    return self._missing(asked)
                ledger["descriptions"] += 1
                return self._send(composer.array_json(level), "application/json")

            # A piece is named by its size, then "c", then one number per axis:
            # t, c, z, y, x. Five numbers because the picture has five axes.
            if len(parts) == 7 and parts[1] == "c" and parts[0].isdigit():
                level = int(parts[0])
                t, colour, plane, row, column = parts[2:]
                if not (row.isdigit() and column.isdigit()):
                    return self._missing(asked)
                if not 0 <= level < g.LEVELS:
                    return self._missing(asked)
                cy, cx = int(row), int(column)
                down, across = composer.grid(level)
                if (t, colour, plane) != ("0", "0", "0") or \
                        not (0 <= cy < down and 0 <= cx < across):
                    return self._missing(asked)
                started = time.perf_counter()
                with guard:
                    working = time.perf_counter()
                    body = composer.bytes_for(level, cy, cx)
                    finished = time.perf_counter()
                ledger["work_ms"][level].append((finished - working) * 1000)
                ledger["compose_ms"][level].append(
                    (time.perf_counter() - started) * 1000)
                ledger["order"].append((started, finished, level, cy, cx))
                ledger["pieces"][level] += 1
                return self._send(body, "application/octet-stream")

            return self._missing(asked)

        def _missing(self, asked: str) -> None:
            """Say plainly that there is nothing here, and remember being asked.

            A picture that is made rather than stored can be asked for things it was
            never going to have, and a request nobody expected is the first sign
            that the browser wants something different from what is being offered.
            So each one is kept.
            """
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
    address = f"http://127.0.0.1:{server.server_address[1]}"
    return server, address, ledger

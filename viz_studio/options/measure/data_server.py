"""The little server every option is measured against.

It does the three things the viewer's own server does — hand over the built
page, hand over the images, answer a couple of short questions — and adds two
that only a measurement needs.

**It can be made slow on purpose.** The store will live either on the
acquisition machine's own disk or on a network share, and both have to be
acceptable. A share is not slower because the data is bigger; it is slower
because every request costs a round trip, and a redraw is made of hundreds of
small ones. So this server can be told to wait a fixed number of milliseconds
before answering anything under ``/data``. The wait can be changed while a page
is open, which is what lets a measurement stall a viewer in the middle of a drag
and watch what happens to the interface.

**It keeps a note of every request it answered** — when it started, when it
finished, what was asked for, and whether the answer was "here it is" or "there
is nothing here". That note is the ground truth for the timing measurements: how
many requests a redraw really costs, how many the browser was willing to have in
flight at once, and therefore how many rounds of waiting a delay is multiplied
by. It matters that this is counted here rather than asked of the engine,
because an engine's own account of what it fetched is exactly the kind of
self-report this project has learned not to trust.

Everything is bound to this machine only.

This began as ``viz_studio/sandwich/probe_server.py``, which is not on this
branch but on ``claude/sandwich-probe``, commit ``1277e30``. It is kept close to
it on purpose, so that a number measured then and a number measured now are
comparable.
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_VIZ_ROOT = Path(__file__).resolve().parents[2]
for extra in (str(_VIZ_ROOT / "backend"), str(_VIZ_ROOT.parent)):
    if extra not in sys.path:
        sys.path.insert(0, extra)

from stores import normalise_units  # noqa: E402

# "bytes=0-99", "bytes=500-" or "bytes=-64" — the same three shapes the viewer's
# own server honours, and for the same reason: a sharded store is read by asking
# for parts of a file.
_RANGE_HEADER = re.compile(r"^bytes=(\d*)-(\d*)$")

# The small files that describe a store rather than holding picture. They are
# never delayed and never counted as image traffic: on a real share they would be
# read once and kept, and counting them would flatter or spoil the figures
# depending which way you looked at it.
_DESCRIBING_FILES = (".zattrs", ".zarray", ".zgroup", "zarr.json")


class Ledger:
    """Every request this server answered, with the times either side of it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.entries: list[dict] = []
        self.delay_ms: float = 0.0

    def note(self, path: str, started: float, finished: float, found: bool) -> None:
        with self._lock:
            self.entries.append(
                {"path": path, "started": started, "finished": finished, "found": found}
            )

    def clear(self) -> None:
        with self._lock:
            self.entries = []

    def summary(self) -> dict:
        """What the note adds up to.

        ``rounds`` is the honest version of the arithmetic everybody does in
        their head. A browser will hold only so many conversations with one
        address at a time, so a redraw of several hundred pieces goes out in
        rounds, and on a share every round costs a round trip. Rather than
        dividing the count by the limit and hoping, this counts the rounds from
        the times themselves: each request is put in the first lane that was free
        when it started, and the longest lane is how deep the traffic went.
        """
        with self._lock:
            entries = sorted(self.entries, key=lambda e: e["started"])
        if not entries:
            return {
                "requests": 0, "found": 0, "missing": 0, "at_once": 0,
                "seconds": 0.0, "rounds": 0, "delay_ms": self.delay_ms,
            }
        moments = [(e["started"], 1) for e in entries] + [
            (e["finished"], -1) for e in entries
        ]
        moments.sort()
        running = at_once = 0
        for _, step in moments:
            running += step
            at_once = max(at_once, running)
        lanes: list[float] = []
        depth: list[int] = []
        for entry in entries:
            for index, free_from in enumerate(lanes):
                if entry["started"] >= free_from:
                    lanes[index] = entry["finished"]
                    depth[index] += 1
                    break
            else:
                lanes.append(entry["finished"])
                depth.append(1)
        return {
            "requests": len(entries),
            "found": sum(1 for e in entries if e["found"]),
            "missing": sum(1 for e in entries if not e["found"]),
            "at_once": at_once,
            "seconds": entries[-1]["finished"] - entries[0]["started"],
            "rounds": max(depth) if depth else 0,
            "delay_ms": self.delay_ms,
        }


def voxel_size_um(image: Path) -> dict:
    """How large one voxel is, in micrometres, read out of the image itself.

    The coverage record counts in voxels, because that is what the writer knows,
    and everything above the options' interface counts in micrometres. So the two
    have to be joined somewhere, and the image's own description is the right
    place to take the number from: it is the same description the drawing engine
    reads, so the operator's drawing and the picture cannot end up scaled
    differently from one another.
    """
    described = json.loads((image / ".zattrs").read_text())
    multiscales = described["multiscales"][0]
    names = [axis["name"] for axis in multiscales["axes"]]
    units = [axis.get("unit", "") for axis in multiscales["axes"]]
    scale = None
    for step in multiscales["datasets"][0]["coordinateTransformations"]:
        if step["type"] == "scale":
            scale = step["scale"]
    found = {}
    for name, unit, size in zip(names, units, scale or []):
        # Both spellings occur in the wild. The writer here spells it out in
        # full; the engine insists on the short form.
        if unit in ("micrometer", "um", "µm"):
            found[name] = float(size)
    return found


def make_measurement_server(
    *, port: int, site_dir: Path, data_dir: Path, ledger: Ledger
) -> ThreadingHTTPServer:
    """Serve the harness page at ``/`` and the run's images under ``/data``."""
    site_dir = Path(site_dir).resolve()
    data_dir = Path(data_dir).resolve()

    class _Handler(SimpleHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        wbufsize = 64 * 1024
        disable_nagle_algorithm = True

        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(site_dir), **kwargs)

        def handle_one_request(self) -> None:
            # An engine cancels requests it no longer needs whenever the view
            # moves, which arrives here as a dropped connection. Ordinary, not an
            # error.
            try:
                super().handle_one_request()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                self.close_connection = True

        def log_message(self, *args) -> None:
            pass

        def do_GET(self) -> None:  # noqa: N802
            if self.path.startswith("/data/"):
                self._serve_data()
            elif self.path.startswith("/api/"):
                self._serve_api()
            else:
                super().do_GET()

        def do_HEAD(self) -> None:  # noqa: N802
            # A sharded store asks how long a file is before reading part of it,
            # and it asks with a HEAD. Every reply below knows not to write a
            # body for one, which matters because this server keeps connections
            # open between requests.
            if self.path.startswith("/data/") or self.path.startswith("/api/"):
                self.do_GET()
            else:
                super().do_HEAD()

        def do_POST(self) -> None:  # noqa: N802
            if not self.path.startswith("/api/"):
                self._send_empty(HTTPStatus.NOT_FOUND)
                return
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                payload = {}
            route = self.path.rstrip("/")
            if route == "/api/delay":
                ledger.delay_ms = float(payload.get("ms", 0))
                self._send_json({"delay_ms": ledger.delay_ms})
            elif route == "/api/ledger/clear":
                ledger.clear()
                self._send_json({"cleared": True})
            else:
                self._send_empty(HTTPStatus.NOT_FOUND)

        def _serve_api(self) -> None:
            route = self.path.split("?")[0].rstrip("/")
            if route == "/api/ledger":
                self._send_json(ledger.summary())
            elif route == "/api/coverage":
                self._send_json(self._coverage())
            else:
                self._send_empty(HTTPStatus.NOT_FOUND)

        def _coverage(self) -> dict:
            """Where the run actually imaged, read from the record beside the data.

            This is what lets the page cut its holes in the right places instead
            of covering the whole window. The image itself cannot say — a piece
            nobody has written reads back as zeros exactly like a piece of
            genuinely dark specimen — so the record the writer kept as the run
            went is the only source for it.
            """
            from urllib.parse import parse_qs, urlparse

            from zmart_storage import imaged_regions

            asked = parse_qs(urlparse(self.path).query).get("image", [None])[0]
            where = data_dir / f"{asked}.ome.zarr" if asked else data_dir
            found = imaged_regions(where)
            answer = {
                "recorded": found.recorded,
                "regions": [region.as_written() for region in found.regions],
                "bounds": found.bounds.as_written() if found.bounds else None,
                "tiles": len(found.tiles),
            }
            if asked and (where / ".zattrs").exists():
                answer["voxel_size_um"] = voxel_size_um(where)
            return answer

        def _serve_data(self) -> None:
            started = time.perf_counter()
            rel = self.path[len("/data/"):].split("?", 1)[0].split("#", 1)[0]
            target = (data_dir / rel).resolve()
            if not str(target).startswith(str(data_dir)):
                self._send_empty(HTTPStatus.FORBIDDEN)
                return
            describing = target.name in _DESCRIBING_FILES
            if not describing and ledger.delay_ms > 0:
                time.sleep(ledger.delay_ms / 1000.0)
            found = target.is_file()
            if not found:
                # A piece nobody has imaged is the ordinary case on a sparse run
                # rather than an error, so it is answered plainly and the
                # connection is left open. Answering through the standard
                # library's error page would close it, and on this shape of data
                # that is most of them.
                self._send_empty(HTTPStatus.NOT_FOUND)
            else:
                self._send_file(target, describing)
            if not describing:
                ledger.note(rel, started, time.perf_counter(), found)

        def _send_file(self, target: Path, describing: bool) -> None:
            # A description is read whole because it is small, and because it is
            # repaired on the way out: this writer spells its units the everyday
            # way ("micrometer") and the engine refuses anything but "um".
            data = normalise_units(target.read_bytes()) if describing else None
            total = len(data) if data is not None else target.stat().st_size
            try:
                wanted = self._wanted_range(total)
            except ValueError:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{total}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            start, length = wanted if wanted else (0, total)
            if data is None:
                with target.open("rb") as handle:
                    handle.seek(start)
                    body = handle.read(length)
            else:
                body = data[start:start + length]
            self.send_response(
                HTTPStatus.PARTIAL_CONTENT if wanted else HTTPStatus.OK
            )
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Accept-Ranges", "bytes")
            if wanted:
                self.send_header(
                    "Content-Range", f"bytes {start}-{start + len(body) - 1}/{total}"
                )
            # Nothing may be kept. These measurements write into a store while a
            # page is looking at it, so a copy held in the browser would answer
            # from a moment ago and the measurement would be of the wrong thing.
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _wanted_range(self, total: int):
            asked = self.headers.get("Range")
            if not asked:
                return None
            found = _RANGE_HEADER.match(asked.strip())
            if not found:
                return None
            first, last = found.group(1), found.group(2)
            if not first:
                length = int(last or 0)
                if length == 0:
                    raise ValueError("an empty suffix range cannot be satisfied")
                start = max(0, total - length)
                return start, total - start
            start = int(first)
            if start >= total:
                raise ValueError("range starts past the end of the file")
            end = min(int(last) if last else total - 1, total - 1)
            return start, end - start + 1

        def _send_empty(self, status: HTTPStatus) -> None:
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _send_json(self, obj: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

    class _Server(ThreadingHTTPServer):
        # An engine opens several connections at once. The standard library lets
        # only five wait to be accepted, and anything beyond that is dropped and
        # retried a second later — which would show up in these measurements as
        # latency that was really our own server's doing.
        request_queue_size = 128
        daemon_threads = True

    return _Server(("127.0.0.1", port), _Handler)

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
import hashlib
import json
import math
import os
import queue
import re
import sys
import tempfile
import threading
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# These are the viewer's own modules, and none of them pulls in anything heavy
# when imported -- numpy and zarr are only reached for inside the functions that
# actually read pixels. So they are imported here in the ordinary way rather than
# inside the function that uses them, which keeps import errors surfacing at
# startup instead of on the first request an operator makes.
import announcements as announcements_mod
import linking
from announcements import Announcements, FolderWatcher, ManifestWatcher

# The other way a picture can exist without being written: built when asked for,
# rather than pointed at. Its folder sits beside the viewer's own modules rather
# than among them, so its path is added here -- and the import is guarded, because
# a checkout without it should still serve every ordinary image.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "building"))
try:
    import served as building
except ImportError:  # pragma: no cover - a checkout without the building module
    building = None
from contrast import coarsest_level_is_written, intensity_histogram, measure
from library import Library
from live_config import LiveRegistry, capture_live_state, live_rows
from stores import (
    DESCRIPTION_FILES,
    axis_names,
    channel_color,
    channel_of,
    channels,
    forget,
    label_images,
    layer_names,
    normalise_units,
    written_timepoints,
    zarr_scheme,
)

from zmart_live.gateway import answer_from_a_live_run

# Where the two kinds of content live on disk. Both are resolved to absolute
# paths so the server behaves the same regardless of the working directory it
# was started from.
_HERE = Path(__file__).resolve().parent
_FRONTEND_DIST = (_HERE.parent / "frontend" / "dist").resolve()
_DEMO_STORE = (_HERE / "demo_store").resolve()
_ANNOTATIONS_FILE = "zmart-annotations.json"
_EMPTY_ANNOTATIONS = {"version": 1, "annotations": []}
# "bytes=0-99", "bytes=500-" or "bytes=-64": a start and end, an open end, or a
# suffix. Only single ranges are honoured, which is all the engine ever asks for.
_RANGE_HEADER = re.compile(r"^bytes=(\d*)-(\d*)$")


# -- checking what the page sends back ------------------------------------------
#
# The operator's marked places arrive from the page as text, and they are written
# straight into a file beside somebody's data. So they are looked over first: the
# right shape, a sane number of them, and real coordinates. Anything else is
# refused with a reason rather than saved and puzzled over later.


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


# -- what the panel calls each open acquisition ---------------------------------


def group_labels(datasets) -> dict[int, str]:
    """What to call each open dataset in the panel.

    Normally a dataset is called what the load called it — "overview",
    "targetscan" — because only one run is open and there is nothing to confuse
    it with. But the viewer is meant to be opened on a second run alongside the
    first: last week's experiment for comparison, or a colleague's data. Both
    runs may be called "overview", and two headings reading the same thing would
    leave the operator with no way to tell which is which.

    So a name shared by more than one open dataset is qualified by the folder it
    came from. Nothing changes in the ordinary single-run case.
    """
    shared: dict[str, int] = {}
    for dataset in datasets:
        shared[dataset.name] = shared.get(dataset.name, 0) + 1
    return {
        dataset.number: (
            dataset.name if shared[dataset.name] == 1 else f"{dataset.root.name} · {dataset.name}"
        )
        for dataset in datasets
    }


# -- answering one request ------------------------------------------------------
#
# Everything below belongs to a single request. The class is long because the
# viewer asks for several quite different things down one address — the page, the
# image, and a handful of short questions in JSON — and its own sections say which
# is which.


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

    # Build each reply in memory and send it as one piece. The standard library
    # writes unbuffered by default, which sends every header line as its own
    # little network packet — barely noticeable for one request, and a real cost
    # when opening an acquisition of two hundred tiles, where the viewer asks
    # well over a thousand small questions before it can draw anything.
    wbufsize = 64 * 1024
    # Do not wait to see whether more data is coming before sending what we have.
    # That waiting is worth it on a real network; on this machine talking to
    # itself it only adds delay to every single answer.
    disable_nagle_algorithm = True

    def __init__(
        self,
        *args,
        data_dir: Path,
        site_dir: Path,
        config: dict,
        library=None,
        browse=None,
        live: bool = True,
        announcements=None,
        live_state=None,
        forget_measurements=None,
        **kwargs,
    ):
        self._data_dir = data_dir  # where drawn targets are saved
        self._library = library  # which folders may be read from, and what is in them
        self._browse = browse  # opens a native folder chooser, when one is available
        self._site_dir = site_dir  # the built page, served as the base directory
        self._live = live  # is the data still being written? decides what may be kept
        # How open pages are told that something has changed. See announcements.py.
        self._announcements = announcements or announcements_mod.Announcements()
        # A cheap authoritative answer used for conditional catch-up after a
        # missed SSE hint.  It returns ``(document, etag)`` and touches no image.
        self._live_state = live_state
        # Asked afresh on each /api/config request rather than held as a fixed
        # answer, so a store written after the viewer opened can still appear.
        self._config = config
        # Told when stores are closed, so the measurements taken from their pixels
        # can be dropped along with everything else remembered about them. It is a
        # function passed in because the measurements are kept beside the thing that
        # builds the answer, not here. Absent in the few tests that construct a
        # handler on their own, so it is allowed to be missing.
        self._forget_measurements = forget_measurements or (lambda closed: None)
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
        self._send_empty(HTTPStatus.NOT_FOUND)

    def do_HEAD(self) -> None:  # noqa: N802
        """Answer "does this exist, and how big is it?" — headers only, no body.

        Without this, a HEAD for a piece of image would fall through to the
        machinery that serves the page's own files and be looked for in the wrong
        place entirely, so an existing piece would be reported missing.

        The routing below is shared with GET, and every reply it produces knows
        not to write a body when the request was a HEAD. That distinction is not
        pedantry: this server keeps connections alive, so a body sent where none
        was asked for is read as the beginning of the *next* reply and everything
        after it on that connection is nonsense.

        A sharded store is what makes this matter. To read the last few bytes of a
        shard the engine first asks how long the shard is, and it asks with a HEAD.
        """
        if self.path.startswith("/data/") or self.path.startswith("/api/"):
            self.do_GET()
            return
        super().do_HEAD()

    def _wanted_range(self, total: int) -> tuple[int, int] | None:
        """The byte range asked for as ``(start, length)``, or ``None`` for all of it.

        Sharded zarr is why this exists. A shard holds many chunks in one file;
        the engine reads the shard's index, then asks for one chunk out of the
        middle by byte offset. A server that ignored that and returned the whole
        shard would hand back megabytes for every few kilobytes wanted — and the
        engine, which expects a partial answer, would not use it anyway.

        Returns ``None`` when there is no range to honour, and raises
        ``ValueError`` when one was asked for that cannot be satisfied.
        """
        asked = self.headers.get("Range")
        if not asked:
            return None
        found = _RANGE_HEADER.match(asked.strip())
        if not found:
            # A range we do not understand is not an error: answering with the
            # whole file is always a correct response to a Range request.
            return None
        first, last = found.group(1), found.group(2)
        if not first:
            # "the last N bytes" -- how the index at the end of a shard is read.
            length = int(last or 0)
            if length == 0:
                raise ValueError("an empty suffix range cannot be satisfied")
            start = max(0, total - length)
            return start, total - start
        start = int(first)
        if start >= total:
            raise ValueError(f"range starts at {start}, past the end at {total}")
        end = int(last) if last else total - 1
        end = min(end, total - 1)
        return start, end - start + 1

    # -- image data ------------------------------------------------------

    def _serve_from_data(self) -> None:
        """Serve one file from an open OME-Zarr store under ``/data``.

        The browser asks for image chunks by path, for example
        ``/data/0/demo.zarr/0/0.24.0.0``: the first number says which opened
        folder, then the store inside it, then the chunk's position (the volume's
        metadata tells the viewer to join those with dots).

        Which folders may be read from is the library's decision, and a request
        that does not land inside one of them is refused rather than corrected.
        """
        rel = self.path[len("/data/") :].split("?", 1)[0].split("#", 1)[0]
        target = self._library.resolve(rel)
        if target is None:
            self._send_empty(HTTPStatus.FORBIDDEN)
            return

        # A live run writes pixels before it atomically publishes them.  Static
        # file existence is therefore not permission to serve.  This gate also
        # resolves a seamless view chunk straight to the encoded bytes in its
        # canonical position, including an inner chunk held inside a shard.
        live = answer_from_a_live_run(target)
        if live is not None:
            if not live.allowed:
                self._send_empty(HTTPStatus.NOT_FOUND)
                return
            if live.serving is not None:
                number = rel.partition("/")[0]
                root = self._library.resolve(f"{number}/.")
                source = live.serving.path.resolve()
                if root is None or (source != root and root not in source.parents):
                    self._send_empty(HTTPStatus.FORBIDDEN)
                    return
                if not source.is_file():
                    self._send_empty(HTTPStatus.NOT_FOUND)
                    return
                self._send_file(
                    source,
                    begins_at=live.serving.offset,
                    how_many=live.serving.length,
                )
                return
        if not target.is_file():
            if live is not None:
                # The live gateway already classified this as a materialized
                # piece.  If that file has disappeared, do not let the older
                # generic pointer mechanism answer with some other bytes and
                # hide the damage behind a plausible image.
                self._send_empty(HTTPStatus.NOT_FOUND)
                return
            # Before deciding there is nothing here: some pictures are never
            # written down at all. An acquisition can be shown as one image whose
            # full-size picture is a list of pointers into the tiles that already
            # exist, so a piece of it lives in a file somewhere else, byte for
            # byte. See linking.py. Nothing is assembled and no pixel is touched --
            # the file that already holds those exact bytes is handed over as it is.
            elsewhere = self._pointed_at(rel)
            if elsewhere is not None:
                target, begins_at, how_many = elsewhere
                self._send_file(target, begins_at=begins_at, how_many=how_many)
                return
            # And some pictures are not written down *or* pointed at. A transfer
            # from another microscope has tiles that land nowhere near a whole
            # file, so no piece of it can be handed over as it is; the piece is
            # built out of whichever tiles cover that ground and served as bytes
            # that never existed until now. See viz_studio/building/served.py.
            made = self._built(rel)
            if made is not None:
                self._send_bytes(made)
                return
            # A piece that was never imaged is the *ordinary* case, not an error:
            # most of a live acquisition has not been written yet, and the engine
            # asks about those regions constantly.
            #
            # It matters that this is answered plainly rather than through the
            # standard library's error reply, which closes the connection and
            # sends a page of HTML explaining itself. Closing would mean every
            # probe of unimaged ground costs a new connection and a new thread —
            # which, on a sparse acquisition, is most of them.
            self._send_empty(HTTPStatus.NOT_FOUND)
            return
        self._send_file(target)

    def _pointed_at(self, rel: str) -> tuple[Path, int, int | None] | None:
        """The file that really holds this piece, when the picture was never written.

        ``rel`` is what came after ``/data/``: the opened folder's number, then the
        image, then the piece inside it. A view built by
        :mod:`zmart_storage.linked` keeps a small list saying which piece of it is
        which piece of which tile, and this turns one into the other.

        The answer comes back from that list as a path *relative to the opened
        folder* and is then resolved by the library, exactly as the original request
        was. That is deliberate: a pointer is therefore held to the same rule as
        everything else — it can only reach inside a folder somebody opened — and
        there is no second guard here that could come to disagree with the first.

        ``None`` means this is not a pointed-at piece, which is the answer for every
        ordinary image and costs one look at whether a file exists.
        """
        number, _, rest = rel.partition("/")
        image, _, inside = rest.partition("/")
        if not inside:
            return None
        store = self._library.resolve(f"{number}/{image}")
        if store is None:
            return None
        found = linking.the_bytes_behind(store, inside)
        if found is None:
            return None
        where = self._library.resolve(f"{number}/{found.path}")
        if where is None:
            return None
        return where, found.offset, found.length

    def _built(self, rel: str) -> bytes | None:
        """This piece, built now, when the picture it belongs to holds no pixels.

        ``rel`` is what came after ``/data/``: the opened folder's number, then the
        image, then the piece inside it. A picture declared by
        ``viz_studio/building/declare.py`` records which transfer it was built from,
        and the tiles of that transfer are read to make the piece.

        ``None`` means this is not a built picture — the answer for every ordinary
        image, and for a pointed-at one — which costs one look at the store's own
        description the first time and nothing afterwards.

        Note that the tiles read here are **not** resolved by the library, unlike a
        pointed-at piece, because a transfer normally sits on a different disk from
        anything the operator opened. ``served.py`` says more about why that is a
        decision rather than an oversight.
        """
        if building is None:
            return None
        number, _, rest = rel.partition("/")
        image, _, inside = rest.partition("/")
        if not inside:
            return None
        store = self._library.resolve(f"{number}/{image}")
        if store is None:
            return None
        return building.the_bytes_behind(store, inside)

    def _send_bytes(self, body: bytes) -> None:
        """Answer with bytes that are not a file and never were.

        Kept apart from :meth:`_send_file` deliberately. That one is about a file —
        its size on disk, ranges out of the middle of it, the repairs a description
        may need on the way out. None of that applies to a piece that was made a
        moment ago and is already exactly what was asked for.
        """
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        if self._live:
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_empty(self, status: HTTPStatus) -> None:
        """Answer with a bare status, keeping the connection open for the next ask."""
        self.send_response(status)
        self.send_header("Content-Length", "0")
        if self._live:
            self.send_header("Cache-Control", "no-store")
        self.end_headers()

    # An OME-Zarr describes itself in small files named like this: what the axes
    # are, how big each copy of the image is, and how the pieces are named. The
    # viewer reads one of them per copy per store before it can draw anything, so
    # an acquisition of two hundred tiles means over a thousand of these before a
    # single pixel appears. They are the same every time — the shape of a store
    # only changes if it is resized, which the storage layout deliberately avoids —
    # so they are worth remembering rather than re-reading, and worth letting the
    # browser keep rather than asking for again.
    # Shared with ``contrast``, which asks the same question of a folder for a
    # different reason. See ``DESCRIPTION_FILES`` in ``stores`` for why there is
    # one list rather than one per module.
    _DESCRIBING_FILES = DESCRIPTION_FILES
    # Remembered by path *and* by when the file was last written. Keying on the
    # path alone would be faster still and quietly wrong: a store whose
    # description is rewritten during a run — a timelapse being given more room,
    # say — would go on being described by what it used to be for the rest of the
    # session, and the viewer would look at the wrong shape of data without
    # anything appearing to be amiss.
    _described: dict[str, tuple[int, bytes]] = {}
    _described_lock = threading.Lock()

    @classmethod
    def forget_described(cls, store: Path) -> None:
        """Let go of the description files remembered for one closed store.

        These are small, but there are several per store per copy of the image, so a
        session that opens one large folder after another accumulates them by the
        thousand. Closing an acquisition should hand that memory back rather than
        keeping it until the viewer is quit.
        """
        inside = str(store) + os.sep
        with cls._described_lock:
            for key in [key for key in cls._described if key.startswith(inside)]:
                del cls._described[key]

    def _send_file(
        self, target: Path, *, begins_at: int = 0, how_many: int | None = None
    ) -> None:
        """Answer with a file, or with one stretch of bytes out of the middle of it.

        ``begins_at`` and ``how_many`` say which part of the file is the thing being
        asked for. Left alone they mean all of it, which is the ordinary case: a
        piece of a zarr image is a file of its own. A pointed-at view supplies them
        when a piece lives *inside* a larger file — as it does in a sharded store —
        so that the answer is that piece and not the file around it.

        Everything after this treats that stretch as though it were the whole file,
        which matters: a browser asking for a range of a piece means a range of the
        *piece*, so its request is measured from ``begins_at`` rather than from the
        beginning of the file.
        """
        describing = target.name in self._DESCRIBING_FILES
        # A description is read whole because it is small and because it may have
        # been repaired on the way out, so what is on disk is not what is served.
        # Image data is not: a range of a shard is read out of the file directly
        # rather than pulling the whole thing into memory to slice it.
        data = self._read(target) if describing else None
        on_disk = len(data) if data is not None else target.stat().st_size
        total = (
            max(0, on_disk - begins_at) if how_many is None
            else max(0, min(how_many, on_disk - begins_at))
        )
        try:
            wanted = self._wanted_range(total)
        except ValueError:
            self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            self.send_header("Content-Range", f"bytes */{total}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if wanted is None:
            start, length = 0, total
        else:
            start, length = wanted
        if data is None:
            with target.open("rb") as handle:
                handle.seek(begins_at + start)
                body = handle.read(length)
        else:
            body = data[begins_at + start : begins_at + start + length]
        self.send_response(HTTPStatus.PARTIAL_CONTENT if wanted else HTTPStatus.OK)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        # Says a range may be asked for at all. Without it a well-behaved client
        # will not try, and a sharded store would be fetched a whole shard at a time.
        self.send_header("Accept-Ranges", "bytes")
        if wanted:
            self.send_header("Content-Range", f"bytes {start}-{start + len(body) - 1}/{total}")
        self.send_header("Cache-Control", self._how_long_to_keep(describing))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _how_long_to_keep(self, describing: bool) -> str:
        """How long the browser may keep a copy of what we are about to send.

        Letting the browser keep things is the difference between panning back
        over a region costing nothing and fetching it all again, and on a finished
        folder of a few hundred tiles it is a large difference. But *keeping* and
        *changing* are exactly the wrong pair, so what may be kept depends on
        whether the data is still being written.

        **A run in progress keeps nothing.** This is the important half. While the
        instrument is writing, we cannot promise that what is on disk now is what
        will be there in a minute: a piece may be rewritten, a plane filled in, a
        timelapse extended. If the browser were holding its own copy it would go
        on showing the old one, and — this is the part that hurts — there would be
        nothing on screen to say so. The operator would be looking at a stale
        picture of a live experiment and making decisions on it. A round trip to a
        server on the same machine is a very cheap price for not doing that.

        **Finished data may be kept for a year.** Nothing is writing, so nothing
        can change, and there is no reason to ask twice. ``immutable`` goes
        further and tells the browser not even to check — no request at all, not
        even a quick "is my copy still good?". This is what makes opening
        yesterday's run and moving around in it feel instant.

        The small files that describe a store are never kept, in either mode. They
        are the one thing that changes as an image grows: a timelapse gaining a
        frame rewrites its shape. A stale copy of one — even for a few seconds —
        leaves the engine believing the old length, so a frame that exists on disk
        simply is not there, with nothing to explain why. Not keeping them costs a
        round trip rather than a read, since the server answers them from memory
        against each file's modification time.
        """
        if describing or self._live:
            # "no-store" rather than "no-cache": no-cache still lets the browser
            # keep a copy and ask whether it is current, which is fine for the
            # small descriptions but not for image during a run -- there we would
            # rather it simply did not hold one.
            return "no-cache" if describing else "no-store"
        return "max-age=31536000, immutable"

    def _read(self, target: Path) -> bytes:
        """The file's contents, remembering the small ones that describe a store."""
        if target.name not in self._DESCRIBING_FILES:
            return target.read_bytes()
        key = str(target)
        written = target.stat().st_mtime_ns
        with self._described_lock:
            remembered = self._described.get(key)
        if remembered is not None and remembered[0] == written:
            return remembered[1]
        # Repaired before it is remembered, so the cost is paid once per store
        # rather than on every request. See ``normalise_units``: a store whose axis
        # units are spelled the everyday way is refused outright by the engine, and
        # this is the one place the description passes through.
        data = normalise_units(target.read_bytes())
        with self._described_lock:
            self._described[key] = (written, data)
        return data

    # -- JSON endpoints --------------------------------------------------

    def _serve_api_get(self) -> None:
        if self.path.rstrip("/") == "/api/health":
            self._send_json({"ok": True})
            return
        if self.path.rstrip("/") == "/api/events":
            self._serve_events()
            return
        if self.path.rstrip("/") == "/api/config":
            self._serve_config()
            return
        if self.path.rstrip("/") == "/api/live-state":
            self._serve_live_state()
            return
        if self.path.rstrip("/") == "/api/annotations":
            path = self._data_dir / _ANNOTATIONS_FILE
            try:
                payload = _validate_annotations(json.loads(path.read_text("utf-8")))
            except FileNotFoundError:
                payload = _EMPTY_ANNOTATIONS
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                # Named plainly rather than as "the sidecar", which is our word for
                # it and means nothing to somebody reading it for the first time.
                self._send_json(
                    {
                        "error": (
                            "the file of marked places beside the images "
                            f"({_ANNOTATIONS_FILE}) could not be read, so none of "
                            "them are shown. It is still there and has not been "
                            "changed."
                        )
                    },
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self._send_json(payload)
            return
        self._send_empty(HTTPStatus.NOT_FOUND)

    def _serve_events(self) -> None:
        """Hold a connection open and write a line whenever something changes.

        This is how an open page finds out that a new acquisition has appeared or
        a timelapse has gained a frame. The page opens this once and leaves it
        open; the server writes to it when there is something to say and says
        nothing the rest of the time. The alternative it replaces — the page
        asking every seven hundred milliseconds for the life of the window — cost
        a question and an answer several times a second, for ever, to be told
        "nothing" almost every time.

        The format is the browser's own ``EventSource``: a few lines of text per
        message, with a blank line between them. No library is involved on either
        side.

        Two details are load-bearing. There is no ``Content-Length``, because the
        length is not known — the reply ends when the connection does. And nothing
        may keep a copy of this, since a recording of the announcements would be
        worse than useless when replayed.

        The thread serving this belongs to the page until the page goes away. That
        is only discovered by trying to write, which is what the quiet heartbeat in
        ``announcements.py`` is for.
        """
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        # This reply is terminated by closing the connection, so it cannot be one
        # of several on a kept-alive connection.
        self.send_header("Connection", "close")
        self.close_connection = True
        self.end_headers()

        waiting = self._announcements.listen()
        try:
            # Say hello straight away. This gets the headers out of any buffer
            # between here and the page, so the browser reports the connection as
            # open rather than sitting in "connecting" until the first real event.
            self.wfile.write(b": listening\n\n")
            self.wfile.flush()
            while True:
                try:
                    message = waiting.get(timeout=announcements_mod.QUIET_HEARTBEAT_S)
                except queue.Empty:
                    message = announcements_mod.HEARTBEAT
                if message is None:
                    return  # the server is shutting down
                self.wfile.write(message)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            # The page was closed or navigated away. Ordinary, not an error.
            pass
        finally:
            self._announcements.stop_listening(waiting)

    def _serve_announcement(self, payload: object) -> None:
        """Accept the legacy optional hint used by generic live folders.

        Manifest-governed ZMART runs never need this endpoint: their watcher
        observes the atomic committed marker and announces only after rereading
        that authoritative state.  Keeping the endpoint preserves generic live
        folder and explicit in-place-write behaviour without making a microscope
        responsible for controlling the viewer.

        The body is almost never read for content, and that is on purpose. What a
        page does on hearing this is ask for the current state of things, which is
        read from disk — so the disk stays the one description of the world that has
        to be right. Anything sent here would only be a second description to keep in
        step. Callers are welcome to send something readable for the sake of anyone
        watching the traffic.

        There is exactly one thing read from the body, and it is read because a
        generic folder cannot say it. Send ``{"wrote_image_in_place": true}`` when
        what was written went *into* a store the viewer may already have open — a
        tile landing in its place inside one large OME-Zarr — rather than into a
        new store of its own.
        Nothing about any description changes in that case: same store, same name, same
        size. The viewer would go on showing the emptiness it settled on earlier and
        would never look again, so it has to be told. Leave it out for the ordinary
        layout of one store per position, where the new store speaks for itself.

        Answers with how many pages were told, which is worth knowing: a script
        that announces a position and is told nobody was listening has learnt that
        the viewer is not open.
        """
        in_place = bool(
            isinstance(payload, dict) and payload.get("wrote_image_in_place")
        )
        # What the disk looks like as this announcement is made. The folder watcher
        # compares it with what it sees a moment later, so that the write the
        # microscope has just told us about is not announced a second time when the
        # watcher notices the same thing. See announcements.already_told_about.
        covering = None
        try:
            if self._library is not None:
                covering = self._library.revision()
        except Exception:
            # Reading the folder is only an optimisation here. Failing to read it
            # means the watcher may repeat this announcement, which is wasteful and
            # harmless -- never a reason to refuse the announcement itself.
            covering = None
        self._send_json(
            {
                "told": self._announcements.say_something_changed(
                    image_written_in_place=in_place, covering=covering
                )
            }
        )

    def _serve_config(self) -> None:
        """Tell the page which stores to open and how to display them.

        The page asks rather than assumes, so that pointing the viewer at a real
        acquisition is a server-side decision (a ``--data`` argument) and needs
        no rebuild of the frontend.

        The answer is worked out fresh each time it is asked for. During a
        smart-microscopy run the folder is still being written to, and a new
        acquisition may well appear after the viewer was opened; an answer
        prepared once at startup could never mention it. Measuring a store's
        brightness and histogram means reading pixels, so those measurements are
        remembered per store and only made once — what gets redone on each
        request is the cheap part, which is looking to see what is now there.
        """
        self._send_json(self._config())

    def _serve_live_state(self) -> None:
        """Return bounded committed revisions, conditionally when unchanged."""
        if self._live_state is None:
            self._send_empty(HTTPStatus.NOT_FOUND)
            return
        document, etag = self._live_state()
        if self.headers.get("If-None-Match") == etag:
            self.send_response(HTTPStatus.NOT_MODIFIED)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._send_json(
            document,
            headers={"ETag": etag, "Cache-Control": "no-store"},
        )

    def _serve_api_post(self) -> None:
        """Handle the things the viewer asks Python to do.

        Saving drawn targets, and changing which images are open: choosing a
        folder, opening one, and closing one again. None of it touches a
        microscope — the studio is a viewer.
        """
        route = self.path.rstrip("/")
        if route not in {
            "/api/browse",
            "/api/stores/open",
            "/api/stores/close",
            "/api/annotations",
            "/api/announce",
        }:
            self._send_empty(HTTPStatus.NOT_FOUND)
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send_json({"error": "that was not readable JSON"}, HTTPStatus.BAD_REQUEST)
            return
        if route == "/api/browse":
            self._serve_browse()
        elif route == "/api/stores/open":
            self._serve_open(payload)
        elif route == "/api/stores/close":
            self._serve_close(payload)
        elif route == "/api/announce":
            self._serve_announcement(payload)
        else:
            self._save_annotations(payload)

    def _serve_browse(self) -> None:
        """Ask the operating system to show a folder chooser, and say what was picked.

        A page in a browser cannot be given a path on the machine — for good
        reason — so the chooser has to be opened by Python, which is running the
        window. In the desktop window that works; in a plain browser tab there is
        nothing to open, and the answer says so plainly so the interface can fall
        back to asking for a typed path instead of failing mysteriously.
        """
        if self._browse is None:
            self._send_json(
                {
                    "error": "no folder chooser is available here",
                    "reason": "The chooser is opened by the desktop window. In a "
                    "browser tab, type or paste the folder's path instead.",
                },
                HTTPStatus.NOT_IMPLEMENTED,
            )
            return
        try:
            chosen = self._browse()
        except Exception as exc:  # noqa: BLE001 -- reported, never swallowed
            # Answered in the same shape as "there is no chooser here" above, and
            # for the same reason: the page reads ``reason`` and asks for a typed
            # path instead, so a chooser that will not open costs the operator a
            # little typing rather than the ability to open their data at all.
            # Without a ``reason`` the page has nothing to fall back to and the
            # failure passes in silence, which is the one outcome this viewer is
            # not allowed to produce.
            #
            # The reason the machine gave is kept, because it is often the useful
            # part, but it is never the whole message: on its own it is a line of
            # Python and tells an operator nothing they can act on.
            self._send_json(
                {
                    "error": f"the folder chooser could not be opened: {exc}",
                    "reason": (
                        f"The window for choosing a folder could not be opened ({exc}). "
                        "Nothing has changed and whatever was already on screen is "
                        "still there. Type or paste the folder's path instead."
                    ),
                },
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return
        # Nothing chosen is a perfectly ordinary outcome: the operator changed
        # their mind and pressed cancel.
        self._send_json({"path": chosen} if chosen else {"cancelled": True})

    def _serve_open(self, payload: object) -> None:
        """Open a folder of images and answer with the viewer's new contents."""
        path = payload.get("path") if isinstance(payload, dict) else None
        if not isinstance(path, str) or not path.strip():
            self._send_json({"error": "a folder path is needed"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            self._library.open(path.strip())
        except FileNotFoundError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
            return
        except (ValueError, OSError) as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json(self._config())

    def _serve_close(self, payload: object) -> None:
        """Close an acquisition type, and answer with what is left."""
        group = payload.get("group") if isinstance(payload, dict) else None
        if not isinstance(group, str) or not group:
            self._send_json({"error": "which acquisition to close is needed"}, HTTPStatus.BAD_REQUEST)
            return
        # The panel closes by the heading it shows, which with two runs open names
        # the folder as well as the dataset. Working back from the heading to the
        # dataset it belongs to is what keeps "close the overview I was comparing
        # against" from also closing the overview being worked on.
        datasets = self._library.datasets()
        named = group_labels(datasets)
        by_number = {dataset.number: dataset for dataset in datasets}
        chosen = [number for number, label in named.items() if label == group]
        closed = []
        if chosen:
            for number in chosen:
                closed += self._library.close_group(by_number[number].name, folder=number)
        else:
            closed += self._library.close_group(group)
        # Give the memory back. An operator who closes an acquisition has said they
        # are finished with it, and the viewer should take them at their word: what
        # was remembered about those stores is dropped here rather than kept for the
        # rest of the session. Nothing is lost by it — if the same folder is opened
        # again, the small files describing it are simply read again.
        for _, root, name in closed:
            forget(root / name)
            linking.forget(root / name)
            self.forget_described(root / name)
        self._forget_measurements(closed)
        self._send_json(self._config())

    def _save_annotations(self, payload: object) -> None:
        """Save the targets the operator has drawn.

        This is the only thing the viewer sends back, and it goes to a file, not
        to an instrument. The document is written to a temporary file and then
        moved into place in a single step, so a save interrupted half-way leaves
        the previous targets intact rather than a truncated file.
        """
        try:
            document = _validate_annotations(payload)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        path = self._data_dir / _ANNOTATIONS_FILE
        temporary = None
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
        except OSError as why:
            # The half-written file is cleared away so a failed save does not
            # leave litter beside the operator's data.
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
            # This message is shown in the panel, right under the list of places
            # the operator has marked, so it is written for them rather than for
            # us. It names the file, gives the reason the operating system gave,
            # and says what has and has not been lost — because the useful thing
            # to know at that moment is whether the marks are still on screen and
            # whether the earlier ones are still on disk. Both are: nothing has
            # been overwritten, and the marks are safe until the page is closed.
            self._send_json(
                {
                    "error": (
                        f"could not write {path} ({why.strerror or why}). The places "
                        "you have marked are still on screen and whatever was saved "
                        "before is untouched, but nothing new has reached the disk. "
                        "This is usually a folder that cannot be written to, or a "
                        "drive that has filled up or gone away."
                    )
                },
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return
        self._send_json(document)

    def _send_json(
        self,
        obj: dict,
        status: HTTPStatus = HTTPStatus.OK,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    # Quieten the default per-request logging so the console stays readable.
    def log_message(self, *args) -> None:  # noqa: D401
        pass


# -- putting a server together --------------------------------------------------
#
# One call builds the whole thing: what is open, who is watching the disk, the
# brightness measured for each store, and the description of the scene the panel
# reads. They are gathered here rather than in a class of their own because they
# share one piece of state — the measurements — and because a request handler is
# built fresh for every request and so can hold nothing.
#
# It is the largest thing in this file by some way, and it is on the list to be
# broken up; `NEXT_STEPS.md` says what that would take.


def make_server(
    port: int = 8848,
    *,
    data_dir: Path = _DEMO_STORE,
    site_dir: Path = _FRONTEND_DIST,
    store: str | list[str] = "demo.zarr",
    loads: list[dict] | None = None,
    window: tuple[float, float] | None = None,
    depth_samples: int = 256,
    chrome: bool = False,
    browse=None,
    live: bool = True,
    allow_open: bool = True,
    allow_selection: bool = False,
    panel_side: str = "right",
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

    ``store`` names the images to open inside ``data_dir``, and they become one
    dataset — one acquisition, however many tiles and channels it was written as.

    ``loads`` opens several datasets instead, one per entry, each a dict with an
    optional ``path`` (defaulting to ``data_dir``), ``stores`` (the names to open,
    or all of them), and ``name`` (what the panel calls it). Two entries reading
    the same folder need names, or they arrive as two datasets called the same
    thing. Use this to put a finished run beside the one being worked on.

    ``allow_open`` decides whether the page offers the operator a way to choose
    folders for themselves.

    It is on by default, because someone opening the viewer on its own — to look
    at yesterday's run, or at a colleague's data — needs some way to say which
    folder. During a smart-microscopy experiment it should be off. There the
    workflow decides what is worth looking at, and a "load data" button would
    invite someone to add an image the experiment knows nothing about, sitting on
    screen beside the images the experiment chose, with nothing to tell them apart.

    Switching it off hides that part of the panel and nothing else. Images can
    still be put on screen from outside the page, and that is how a workflow does
    it: either by naming them here when the viewer is started, or by asking
    ``POST /api/stores/open`` as the run goes on. Those routes stay open on
    purpose, so that what is shown is decided by the experiment rather than by
    whoever happens to be watching it.

    ``live`` says whether the data is still being written.

    A smart-microscopy run writes as it goes: acquisitions appear, timelapses gain
    frames, and the viewer has to keep looking so that what is on screen follows
    what the instrument is doing. That is live mode, and it is the default.

    Static mode is for data that is finished — yesterday's run, a colleague's
    folder, anything being read rather than made. Nothing about it can change, so
    the viewer stops asking: no looking in the folder for new acquisitions, no
    counting frames again, and the page stops its several-times-a-second question
    about whether anything has moved. On a folder of several hundred acquisitions
    that asking is the largest thing the server does, and in static mode the honest
    answer is that it is all wasted work.

    The mode also decides whether the browser may keep its own copy of the image.
    Finished data may be kept and re-read without asking, which is what makes
    moving around an old run feel instant. A run in progress is kept by nobody:
    while the instrument is still writing, a copy held in the browser could go on
    showing an old version of a region with nothing on screen to say so, and
    looking at a stale picture of a live experiment is exactly the situation this
    viewer exists to avoid. See ``_how_long_to_keep``.

    Getting this wrong is not dangerous, only disappointing in one direction and
    slightly slow in the other: a live run opened as static will not notice new
    data until it is reopened, and finished data opened as live is re-fetched more
    often than it needs to be.

    ``panel_side`` puts the bar of controls on the ``"right"`` or the ``"left"``.
    Which side is better depends on the room: at a microscope the screen is often
    beside the instrument and one edge is easier to reach than the other. It folds
    away towards whichever edge it is on.

    ``allow_selection`` decides whether the panel offers the selection list at all
    — the places marked on the image, whether drawn by hand or found by the
    workflow. It is off unless asked for, because marking places is not what most
    viewing is: someone looking through yesterday's run wants the image and nothing
    else on screen. A workflow that cares about targets switches it on.
    """
    data_dir = Path(data_dir).resolve()
    names = [store] if isinstance(store, str) else list(store)
    library = Library()
    # The folder the viewer was started on is the run being worked on, so it is
    # watched: an acquisition written while it is open appears on its own.
    #
    # One load is one dataset, so opening more than one acquisition at a time means
    # loading more than once -- which is why this takes a list. Without it the thing
    # that starts the viewer could only ever show a single acquisition, and "open
    # last week's run beside this one" would be impossible to express at startup.
    wanted = loads if loads is not None else [{"stores": names}]
    for spec in wanted:
        library.open(
            Path(spec.get("path", data_dir)),
            names=spec.get("stores"),
            # Whether to keep looking in this folder once it has been opened.
            #
            # A load that named particular stores is not watched, because naming
            # them is how somebody says "this much and no more", and looking in the
            # folder again would quietly add what they left out. The one exception
            # is the single load the viewer was started on: that folder is the run
            # being worked on, and a position or an acquisition written into it
            # while the viewer is open is the whole point of watching at all.
            #
            # This restriction used to be justified here by a hazard that no longer
            # exists — two datasets open on one folder each taking the other's
            # images on the next look, and a store the operator had closed being
            # rediscovered moments later by its neighbour. Neither can happen now: a
            # watched folder is looked in once however many datasets are open on it,
            # a store that appears is given to exactly one of them according to what
            # it says it is, and anything the operator closed is remembered as
            # closed. See ``_look_again`` and ``_place`` in library.py.
            watch=live and (len(wanted) == 1 or spec.get("stores") is None),
            name=spec.get("name"),
        )

    # How open pages are told that something has changed.  A recognized ZMART
    # run is governed only by its atomic publication marker; ordinary folders
    # retain the generic directory watcher.
    told = Announcements()
    live_registry = LiveRegistry(library)
    live_registry.refresh()
    watchers = []
    if live:
        # Both providers are dynamic: the existing open/close API may add or
        # remove a manifest run after the server has begun serving.
        watchers.append(
            FolderWatcher(
                library,
                told,
                excluding=live_registry.dataset_numbers,
            )
        )
        watchers.append(ManifestWatcher(live_registry.trackers, told))

    def captured_live_state():
        bindings, governed = live_registry.refresh()
        document, snapshots = capture_live_state(bindings)
        settled = json.dumps(document, sort_keys=True, separators=(",", ":"))
        etag = '"' + hashlib.sha256(settled.encode("utf-8")).hexdigest() + '"'
        return bindings, governed, document, snapshots, etag

    def live_state_now() -> tuple[dict, str]:
        """Bounded truth and its conditional-request identity."""
        _bindings, _governed, document, _snapshots, etag = captured_live_state()
        return document, etag

    # Measuring a store's display window and histogram means reading pixels, so
    # each store is measured once and the answer kept. The list of stores is
    # re-read on every request (see _serve_config); only this expensive part is
    # remembered.
    #
    # Note that build_config only ever asks this of the one store that decides
    # how a row is shown, not of every position on the row -- so on a large run
    # there are a handful of entries here rather than tens of thousands.
    measured: dict[str, dict] = {}
    # The measurements above that were taken before the run had finished writing,
    # and so are worth taking again once it has. They are kept and used in the
    # meantime -- they are honest readings of the pixels that existed at the time,
    # and far better than making the operator wait -- but they are not the final
    # answer, because they were measured from a larger copy of the image that
    # covers less of the specimen at once, or from no picture at all.
    provisional: set[str] = set()
    # Measuring a store means reading pixels. Two requests arriving together --
    # the page loading while the refresh poll fires, or a second window opening --
    # would otherwise both do that work for the same store.
    measuring = threading.Lock()

    def forget_measurements(closed) -> None:
        """Drop the measurements taken from stores that have just been closed.

        Deliberately without waiting for ``measuring`` above. That lock is held for
        as long as it takes to read a store's pixels, and closing an acquisition
        should never sit waiting on that — the panel would appear to freeze. The
        cost of not waiting is that a measurement already under way for a store
        being closed can finish and put its answer back, leaving one entry behind.
        That is a few hundred bytes, once, and the next close of the same
        acquisition clears it.
        """
        for number, _, name in closed:
            # A store holding several channels leaves one entry per channel, under
            # keys ending in the channel's number, so every entry belonging to this
            # store goes rather than only the one with the bare name.
            stem = f"{number}/{name}"
            for key in [k for k in measured if k == stem or k.startswith(f"{stem}/c")]:
                measured.pop(key, None)
                provisional.discard(key)

    def describe(
        root_number: int, root: Path, name: str, label: str, coloured: bool,
        channel: int | None = None,
    ) -> dict:
        # The channel belongs in the key. A store holding several channels is
        # measured once per channel, because one window covering all of them
        # leaves a faint channel with its whole useful range in the bottom
        # hundredth of its slider -- and sharing one entry between them is
        # precisely how that used to happen.
        key = f"{root_number}/{name}" if channel is None else f"{root_number}/{name}/c{channel}"
        remembered = measured.get(key)
        if remembered is not None and (
            key not in provisional
            # Taken before the run had finished writing. The numbers are good
            # enough to show, so they are used again unless the store has since
            # gained the whole-field copy that would make them final. Asked
            # before the lock below is taken, and by looking at a folder rather
            # than at any picture, so the ordinary case of "still writing,
            # nothing new" costs a directory listing and no waiting at all.
            or not _worth_measuring_again(root / name)
        ):
            return {**remembered, "name": label}
        with measuring:
            remembered = measured.get(key)
            if remembered is not None and key not in provisional:
                return {**remembered, "name": label}
            return _measure(key, root_number, root, name, label, coloured, channel)

    def _worth_measuring_again(store: Path) -> bool:
        """Has the store gained the whole-field copy it was missing?

        Cheap on purpose: it looks at a folder rather than reading any picture,
        so asking it on every answer costs nothing. Only when it says yes is the
        expensive measurement done a second time.
        """
        try:
            return coarsest_level_is_written(store)
        except OSError:
            return False

    def _the_window_this_channel_asked_for(store, channel):
        """The brightness this channel's run asked for, or ``None`` if it said none.

        Read from the store's own description, which costs one small file and no
        image data at all — worth knowing, because everything else in
        :func:`_measure` is expensive by comparison.
        """
        try:
            described = channels(store)
        except Exception:
            return None
        at = 0 if channel is None else int(channel)
        if at >= len(described):
            return None
        return described[at].get("window")

    def _measure(key, root_number, root, name, label, coloured, channel=None) -> dict:
        """Read one store's pixels and work out how it should first be shown.

        This is the expensive part of answering "what is open" — everything else
        only reads the small files that describe a store, while this reads image
        data. It is therefore done once per store and channel, and the answer
        kept, which is what the ``measured`` record above is for.

        Both windows are worked out here and travel together, so switching between
        the plane and the volume is instant: the page already holds what each view
        needs and never comes back to ask.
        """
        if window is not None:
            # A window given on the command line is used for both views rather than
            # measured. The histogram is still measured, because it is what the
            # panel draws and what the Auto button restores -- so this reads pixels
            # once, not three times.
            found = {
                "window": window,
                "volumeWindow": window,
                "histogram": intensity_histogram(root / name, channel=channel),
                # A window the operator asked for on the command line is their
                # decision and does not improve by being measured again, but the
                # histogram beside it is still read from the picture, so it is
                # worth revisiting on the same terms as any other.
                "settled": coarsest_level_is_written(root / name),
            }
        else:
            found = measure(root / name, channel=channel)
        flat, volume = found["window"], found["volumeWindow"]

        # What the run itself asked this channel to be shown between, if it said.
        # It is preferred over the measurement, and there are two reasons.
        #
        # The plain one is that the run knows better. The window in the store is
        # what the microscopist chose at the instrument, and reading it back means
        # an acquisition opens looking the way they left it.
        #
        # The other is that for some pictures there is nothing to measure. A
        # picture assembled by pointing at positions holds no voxels of its own --
        # every piece of it is answered by handing over a position's file -- so
        # reading its pixels finds only the empty value. That produces a window
        # covering the whole range of the data type, which draws the specimen at a
        # few per cent of its brightness: the picture is there, and looks like a
        # black screen. Measured at fourteen out of two hundred and fifty-five.
        asked_for = _the_window_this_channel_asked_for(root / name, channel)
        if asked_for is not None:
            flat = volume = (asked_for["low"], asked_for["high"])
        color = channel_color(name) if coloured else None
        described = {
            # A row may be drawn from more than one store: several positions of the
            # same acquisition type, each carrying its own place on the stage. The
            # engine takes a list and places them itself, so a row that happens to
            # come from one store is simply a list of one.
            "sources": [f"/data/{root_number}/{name}/|{zarr_scheme(root / name)}:"],
            "window": {"low": flat[0], "high": flat[1]},
            "volumeWindow": {"low": volume[0], "high": volume[1]},
            "color": list(color) if color else None,
            "histogram": found["histogram"],
        }
        # A store can be met before any of its image has been written -- the viewer
        # is built to notice one the instant its description lands, which is the
        # earliest possible moment. Measuring then gives a window covering the whole
        # range of the data type (the layer draws black) or a window one count wide
        # (it draws saturated white), and either would be remembered for the rest of
        # the session. So a measurement with nothing behind it is used once and not
        # kept, and the next look measures again.
        #
        # The same care is needed for a measurement that *did* see pixels but not
        # all of them. During a run the whole-field copy of the image is the last
        # thing written, so an early measurement is taken from a larger copy that
        # covers less of the specimen. That reading is honest and is shown, but it
        # is marked as one to take again -- cheaply, by looking at a folder rather
        # than reading pixels -- once the run has finished writing.
        if found["histogram"] is not None:
            measured[key] = described
            if found.get("settled"):
                provisional.discard(key)
            else:
                provisional.add(key)
        return {**described, "name": label}

    # The answer to "what is open", kept against the revision it was built for.
    #
    # The viewer asks whether anything has changed several times a second, and during
    # a run the answer moves whenever a frame is written -- which is constantly. Each
    # move made the page ask this expensive question again, and rebuilding it reads
    # every store's description and counts every timelapse's frames: measured at 50
    # milliseconds for four hundred acquisitions and over a second for five thousand,
    # at which point the server never finishes one answer before the next is asked.
    #
    # So the built answer is kept, and rebuilt only when the revision has actually
    # moved since it was made. During a timelapse that still means a rebuild per
    # frame, which is the honest cost of noticing new frames -- but a page reloading,
    # a second window, or several polls arriving together now share one.
    last_built: dict = {"revision": None, "config": None}
    building = threading.Lock()

    def config_now() -> dict:
        (
            live_bindings,
            live_numbers,
            live_document,
            live_snapshots,
            live_etag,
        ) = captured_live_state()
        revision = (
            library.revision(excluding=live_numbers),
            live_etag,
        )
        if last_built["revision"] == revision:
            return last_built["config"]
        with building:
            # Asked again with the lock held: while waiting, another thread may have
            # built exactly what this one was about to build.
            if last_built["revision"] == revision:
                return last_built["config"]
            built = build_config(
                live_document,
                live_bindings,
                live_snapshots,
                live_numbers,
            )
            last_built["revision"] = revision
            last_built["config"] = built
            return built

    def build_config(
        live_document: dict,
        live_bindings,
        live_snapshots,
        live_numbers: frozenset[int],
    ) -> dict:
        """Describe every row the layer panel should show, and its group.

        A row is one channel of one acquisition type. Which stores contribute to a
        row depends on how the data was written, and both shapes occur:

        - A store holding several channels inside it (the ``c`` axis of a
          ``t,c,z,y,x`` image) becomes one row per channel, each naming the channel
          and the colour from the store's own description.
        - A store holding a single channel — the shape a mesoSPIM transfer writes,
          one file per tile and channel — becomes one row, named and coloured the
          way it always was.

        Both then carry the acquisition type they belong to, so the panel can show
        them gathered under it rather than as a flat list.
        """
        entries = library.entries()
        present = [name for _, _, name in entries]
        labels = layer_names(present)
        # What each dataset is called in the panel. With one run open this is
        # simply its own name; with two, each is qualified by the folder it came
        # from so they can be told apart -- see ``group_labels``.
        groups_named = group_labels(library.datasets())
        # One row per acquisition type and channel. Several *positions* of the same
        # acquisition and channel are not separate rows: they are one picture of one
        # specimen, taken in pieces, so they become one row that reads from all of
        # them. The engine takes the list and places each piece using the stage
        # position recorded inside it.
        #
        # This is worth doing for more than tidiness. Asking the engine for one
        # layer with two hundred sources is far less work than two hundred layers,
        # each needing its own setup and its own shader compiled.
        merged: dict[tuple, dict] = {}
        for (root_number, root, name), label in zip(entries, labels, strict=True):
            if root_number in live_numbers:
                continue
            group = groups_named[root_number]
            store_path = root / name
            # Where this store is read from. It follows from the store's name, so
            # working it out costs nothing -- no pixel is touched. That matters
            # here: a row is drawn from every position of its acquisition type,
            # and all but the first of them need only this address. Judging a
            # store's brightness, by contrast, means reading its image data, so
            # it is left until we know a row actually needs it (see below).
            address = f"/data/{root_number}/{name}/|{zarr_scheme(store_path)}:"
            if "c" in axis_names(store_path):
                found = [
                    (index, channel["name"], channel["color"])
                    for index, channel in enumerate(channels(store_path))
                ]
            else:
                # The channel lives in the file's name rather than inside it. Group
                # by the wavelength so the same channel of different tiles merges,
                # falling back to the label where there is no wavelength to read.
                wavelength = channel_of(name)
                colour = channel_color(name) if len(present) > 1 else None
                found = [(None, f"Ch{wavelength}" if wavelength else label, colour)]

            frames = written_timepoints(store_path)
            for index, channel_name, color in found:
                # The folder is part of what makes a row a row. Without it, two
                # runs open side by side would each contribute their "overview" to
                # the *same* row, and one experiment would be drawn on top of the
                # other with nothing to say it had happened.
                key = (root_number, index, channel_name)
                row = merged.get(key)
                if row is None:
                    # The first position of a row decides how the whole row is
                    # shown, so this is the only store on the row whose pixels
                    # have to be read. Every later position adds its address to
                    # the list below and nothing else.
                    #
                    # This is worth knowing, because the alternative is expensive
                    # in a way that is easy to miss. Measuring every position and
                    # then merging looks harmless -- the merge simply keeps the
                    # first answer -- but it reads the image data of every store
                    # in the run to produce a number that is immediately thrown
                    # away. On a folder of a thousand positions that was a
                    # thousand measurements to fill in one row. It is the reason
                    # a large finished folder took the best part of an hour to
                    # open; see NEXT_STEPS.md for the figures.
                    # Measured for this channel and no other. Where the store keeps
                    # its channels in separate files, ``index`` is None and the
                    # whole store already is the one channel.
                    base = describe(
                        root_number, root, name, label,
                        coloured=len(present) > 1, channel=index,
                    )
                    merged[key] = {
                        **base,
                        # A list of this row's own, so that extending it below
                        # cannot reach back into anything shared. `base` carries
                        # a list of addresses too, belonging to the remembered
                        # measurement of this store; growing *that* by accident
                        # would add a little to the remembered copy on every
                        # answer, so the row is given its own from the start.
                        "sources": [address],
                        "name": channel_name,
                        "group": group,
                        "channelIndex": index,
                        # How many frames exist so far, so the time slider stops
                        # there rather than running out over frames not yet imaged.
                        "frames": frames,
                        # The same count again, but kept per store rather than for
                        # the row as a whole, in the same order as ``sources``.
                        #
                        # The row's figure above is the highest across its positions,
                        # which is what the slider needs. It is no use at all for the
                        # other question the viewer has to answer -- *which* position
                        # gained a frame -- because one position advancing moves the
                        # row's figure and says nothing about which one moved. The
                        # viewer would then have to go back to every store on the row
                        # and ask, and at a thousand positions that was measured at
                        # six thousand small requests and eighteen seconds for a
                        # single frame landing. See NEXT_STEPS.md for the figures.
                        #
                        # Keeping the counts separately costs nothing to produce: it
                        # is the same number, already worked out for each store just
                        # above, that used to be thrown away in the merge.
                        "frameCounts": [frames],
                        "color": list(color) if color else None,
                    }
                else:
                    # Another position of the same picture: add where to read it,
                    # and how far along that position is, in step with each other.
                    # Extended in place. Building a new list each time made
                    # adding one position cost more the more were already
                    # there -- measured at seven seconds for a single row of
                    # forty thousand, on every answer.
                    row["sources"].append(address)
                    row["frameCounts"].append(frames)
                    # Positions of one acquisition are imaged together, but one may
                    # be a frame ahead of another at the moment of looking. The
                    # slider follows the one furthest along.
                    if frames and (row.get("frames") or 0) < frames:
                        row["frames"] = frames

            # Segmentation masks saved beside the image become rows of their own,
            # of a different kind: the engine draws a mask by giving every object
            # its own colour, which is not something a picture layer can do.
            for mask in label_images(store_path):
                key = (root_number, "mask", mask)
                row = merged.get(key)
                source = f"/data/{root_number}/{name}/labels/{mask}/|{zarr_scheme(store_path / 'labels' / mask)}:"
                if row is None:
                    merged[key] = {
                        "name": mask,
                        "group": group,
                        "kind": "segmentation",
                        "channelIndex": None,
                        "color": None,
                        "window": None,
                        "volumeWindow": None,
                        "histogram": None,
                        "sources": [source],
                        "frames": frames,
                        # Kept in step with ``sources`` for the same reason as the
                        # picture rows above: a mask sits inside the store it belongs
                        # to, so it advances as that store does.
                        "frameCounts": [frames],
                    }
                else:
                    row["sources"].append(source)
                    row["frameCounts"].append(frames)
        rows = [{"kind": "image", **row} for row in merged.values()]
        for binding in live_bindings:
            rows.extend(
                live_rows(
                    binding,
                    chosen_window=window,
                    group=groups_named[binding.dataset_number],
                    snapshot=live_snapshots[binding.dataset_number],
                )
            )
        # Group order follows first appearance, which follows the sorted store
        # names, so the panel does not reshuffle itself between runs.
        groups = list(dict.fromkeys(row["group"] for row in rows))
        return {
            "layers": rows,
            "groups": groups,
            "depthSamples": depth_samples,
            "chrome": chrome,
            # Whether the operator may choose folders themselves. See the note on
            # ``allow_open`` in make_server: during a run the workflow decides what
            # is shown, and offering a "load data" button would invite someone to
            # add something the experiment knows nothing about.
            "canOpen": allow_open,
            # Whether the selection list is offered. See ``allow_selection``.
            "canSelect": allow_selection,
            # Which edge the bar of controls sits on. See ``panel_side``.
            "panelSide": "left" if str(panel_side).lower() == "left" else "right",
            # Whether the page should keep asking if anything has changed. See
            # ``live`` above: on finished data there is nothing to notice.
            "live": live,
            # Kept beside the complete row description so the browser can reject
            # regressions before asking Neuroglancer to touch a source. Ordinary
            # folders retain their existing response shape.
            **({"liveState": live_document} if live_bindings else {}),
        }

    class _Server(ThreadingHTTPServer):
        # The engine opens several connections at once and asks for pieces in
        # parallel. The standard library lets only five wait to be accepted, and
        # anything beyond that is dropped and retried a second later.
        request_queue_size = 128
        daemon_threads = True

        def serve_forever(self, *args, **kwargs):
            # The disk is watched only while the server is actually running, and
            # only for data that is still being written -- see FolderWatcher.
            for watcher in watchers:
                watcher.start()
            super().serve_forever(*args, **kwargs)

        def shutdown(self):
            # Let the listeners go before stopping, or each would sit through its
            # own quiet heartbeat before noticing the server had gone.
            told.close()
            for watcher in watchers:
                watcher.stop()
            super().shutdown()

    handler = functools.partial(
        _Handler,
        data_dir=data_dir,
        site_dir=Path(site_dir).resolve(),
        config=config_now,
        library=library,
        browse=browse,
        live=live,
        announcements=told,
        live_state=live_state_now,
        forget_measurements=forget_measurements,
    )
    try:
        return _Server(("127.0.0.1", port), handler)
    except OSError as why:
        # Almost always "that door is already in use" -- a viewer already open, or
        # some other program on this machine holding the same number. Left as it
        # came, this reached the operator as a bare OSError with a number in it and
        # no suggestion of what to do, and on a lab PC where something else owns
        # 8848 the viewer simply could not be started at all.
        told.close()
        raise OSError(
            f"the viewer could not start on port {port}: {why}\n\n"
            "That usually means something else on this machine is already using "
            f"it — most often another copy of this viewer. Either close that one, "
            "or start this one on a different port:\n\n"
            "    python run_demo.py --port 8849\n\n"
            "Any number between 1024 and 65535 that nothing else is using will do, "
            "and --port 0 lets the machine choose a free one for you and prints "
            "which it picked."
        ) from why


# -- running it -----------------------------------------------------------------


def serve(port: int = 8848) -> None:
    """Run the server until interrupted. The viewer page will be at ``/``."""
    server = make_server(port)
    # Asked of the server rather than taken from the number passed in. They are
    # the same for an ordinary port, and quite different for port 0 -- which means
    # "any free one" and would otherwise be printed as the useless
    # http://127.0.0.1:0.
    print(f"ZMART Viz Studio serving on http://127.0.0.1:{server.server_address[1]}")
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

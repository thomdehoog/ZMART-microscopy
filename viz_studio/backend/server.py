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
import queue
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
from announcements import Announcements, FolderWatcher
from contrast import intensity_histogram, measure
from library import Library
from stores import (
    axis_names,
    channel_color,
    channel_of,
    channels,
    label_images,
    layer_names,
    split_name,
    written_timepoints,
)

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


def group_labels(entries: list[tuple[int, Path, str]]) -> dict[tuple[int, str], str]:
    """What to call each acquisition type in the panel, per open folder.

    Normally an acquisition type is simply called what it is — "overview",
    "targetscan" — because only one run is open and there is nothing to confuse
    it with. But the viewer is meant to be opened on a second run alongside the
    first: last week's experiment for comparison, or a colleague's data. Both
    runs will have an "overview", and two headings reading "overview" would leave
    the operator with no way to tell which is which — and, worse, the two would be
    drawn into the same layer and silently overlaid on top of one another.

    So when the same acquisition type is found in more than one open folder, each
    one is named after the folder it came from. Nothing changes in the ordinary
    single-run case.
    """
    where: dict[str, set[tuple[int, str]]] = {}
    for number, root, name in entries:
        kind, _ = split_name(name)
        where.setdefault(kind, set()).add((number, root.name))
    labels: dict[tuple[int, str], str] = {}
    for kind, folders in where.items():
        for number, folder in folders:
            labels[(number, kind)] = kind if len(folders) == 1 else f"{folder} · {kind}"
    return labels


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
        **kwargs,
    ):
        self._data_dir = data_dir  # where drawn targets are saved
        self._library = library  # which folders may be read from, and what is in them
        self._browse = browse  # opens a native folder chooser, when one is available
        self._site_dir = site_dir  # the built page, served as the base directory
        self._live = live  # is the data still being written? decides what may be kept
        # How open pages are told that something has changed. See announcements.py.
        self._announcements = announcements or announcements_mod.Announcements()
        # Asked afresh on each /api/config request rather than held as a fixed
        # answer, so a store written after the viewer opened can still appear.
        self._config = config
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
        """Answer a "does this exist?" question the same way as a full request.

        Without this, a HEAD for a piece of image would fall through to the
        machinery that serves the page's own files and be looked for in the wrong
        place entirely — so an existing piece would be reported missing. Nothing
        in the viewer asks this today; it is here so that nothing quietly gets a
        wrong answer if something ever does.
        """
        if self.path.startswith("/data/") or self.path.startswith("/api/"):
            self.do_GET()
            return
        super().do_HEAD()

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
        if not target.is_file():
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

    def _send_empty(self, status: HTTPStatus) -> None:
        """Answer with a bare status, keeping the connection open for the next ask."""
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    # An OME-Zarr describes itself in small files named like this: what the axes
    # are, how big each resolution level is, and how the pieces are named. The
    # viewer reads one of them per level per store before it can draw anything, so
    # an acquisition of two hundred tiles means over a thousand of these before a
    # single pixel appears. They are the same every time — the shape of a store
    # only changes if it is resized, which the storage layout deliberately avoids —
    # so they are worth remembering rather than re-reading, and worth letting the
    # browser keep rather than asking for again.
    _DESCRIBING_FILES = (".zattrs", ".zarray", ".zgroup", "zarr.json")
    # Remembered by path *and* by when the file was last written. Keying on the
    # path alone would be faster still and quietly wrong: a store whose
    # description is rewritten during a run — a timelapse being given more room,
    # say — would go on being described by what it used to be for the rest of the
    # session, and the viewer would look at the wrong shape of data without
    # anything appearing to be amiss.
    _described: dict[str, tuple[int, bytes]] = {}
    _described_lock = threading.Lock()

    def _send_file(self, target: Path) -> None:
        describing = target.name in self._DESCRIBING_FILES
        data = self._read(target)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", self._how_long_to_keep(describing))
        self.end_headers()
        self.wfile.write(data)

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
        data = target.read_bytes()
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
        """Take an announcement from whatever is driving the microscope.

        The application running the experiment knows things the viewer can only
        guess at: it asked for the acquisition and it waited for the write to
        finish. This is where it says so, and every open page is told to look
        again.

        The body is not read for content, and that is on purpose. What a page does
        on hearing this is ask for the current state of things, which is read from
        disk — so the disk stays the one description of the world that has to be
        right. Anything sent here would only be a second description to keep in
        step. Callers are welcome to send something readable for the sake of
        anyone watching the traffic.

        Answers with how many pages were told, which is worth knowing: a script
        that announces a position and is told nobody was listening has learnt that
        the viewer is not open.
        """
        del payload  # see above: the announcement itself is the whole message
        self._send_json({"told": self._announcements.say_something_changed()})

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
            self._send_json({"error": f"the folder chooser failed: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
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
        # the folder as well as the acquisition type. Working back from the heading
        # to the folder it belongs to is what keeps "close the overview I was
        # comparing against" from also closing the overview being worked on.
        named = group_labels(self._library.entries())
        chosen = [where for where, label in named.items() if label == group]
        if chosen:
            for number, kind in chosen:
                self._library.close_group(kind, folder=number)
        else:
            self._library.close_group(group)
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
        except OSError:
            # The half-written file is cleared away so a failed save does not
            # leave litter beside the operator's data.
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
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
    library.open(data_dir, names=names, watch=live)

    # How open pages are told that something has changed, and the two things that
    # do the telling. See announcements.py for why there are two.
    told = Announcements()
    watcher = FolderWatcher(library, told) if live else None

    # Measuring a store's display window and histogram means reading pixels, so
    # each store is measured once and the answer kept. The list of stores is
    # re-read on every request (see _serve_config); only this expensive part is
    # remembered.
    measured: dict[str, dict] = {}
    # Measuring a store means reading pixels. Two requests arriving together --
    # the page loading while the refresh poll fires, or a second window opening --
    # would otherwise both do that work for the same store.
    measuring = threading.Lock()

    def describe(root_number: int, root: Path, name: str, label: str, coloured: bool) -> dict:
        key = f"{root_number}/{name}"
        if key in measured:
            return {**measured[key], "name": label}
        with measuring:
            if key in measured:
                return {**measured[key], "name": label}
            return _measure(key, root_number, root, name, label, coloured)

    def _measure(key, root_number, root, name, label, coloured) -> dict:
        """Read one store's pixels and work out how it should first be shown.

        This is the expensive part of answering "what is open" — everything else
        only reads the small files that describe a store, while this reads image
        data. It is therefore done once per store and the answer kept, which is
        what the ``measured`` record above is for.

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
                "histogram": intensity_histogram(root / name),
            }
        else:
            found = measure(root / name)
        flat, volume = found["window"], found["volumeWindow"]
        color = channel_color(name) if coloured else None
        described = {
            # A row may be drawn from more than one store: several positions of the
            # same acquisition type, each carrying its own place on the stage. The
            # engine takes a list and places them itself, so a row that happens to
            # come from one store is simply a list of one.
            "sources": [f"/data/{root_number}/{name}/|zarr2:"],
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
        if found["histogram"] is not None:
            measured[key] = described
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
        revision = library.revision()
        if last_built["revision"] == revision:
            return last_built["config"]
        with building:
            # Asked again with the lock held: while waiting, another thread may have
            # built exactly what this one was about to build.
            if last_built["revision"] == revision:
                return last_built["config"]
            built = build_config()
            last_built["revision"] = revision
            last_built["config"] = built
            return built

    def build_config() -> dict:
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
        # What each acquisition type is called in the panel. With one run open this
        # is simply its own name; with two, each is named after the folder it came
        # from so they can be told apart -- see ``group_labels``.
        groups_named = group_labels(entries)
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
            kind, _ = split_name(name)
            group = groups_named[(root_number, kind)]
            store_path = root / name
            base = describe(root_number, root, name, label, coloured=len(present) > 1)
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
                found = [(None, f"Ch{wavelength}" if wavelength else label, base.get("color"))]

            frames = written_timepoints(store_path)
            for index, channel_name, color in found:
                # The folder is part of what makes a row a row. Without it, two
                # runs open side by side would each contribute their "overview" to
                # the *same* row, and one experiment would be drawn on top of the
                # other with nothing to say it had happened.
                key = (root_number, kind, index, channel_name)
                row = merged.get(key)
                if row is None:
                    merged[key] = {
                        **base,
                        # A list of this row's own. `base` comes from the remembered
                        # measurement of one store, and its list of addresses belongs
                        # to that memory -- extending it below would grow the
                        # remembered copy too, a little more on every answer.
                        "sources": list(base["sources"]),
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
                        "frameCounts": [frames] * len(base["sources"]),
                        "color": list(color) if color else None,
                    }
                else:
                    # Another position of the same picture: add where to read it,
                    # and how far along that position is, in step with each other.
                    # Extended in place. Building a new list each time made
                    # adding one position cost more the more were already
                    # there -- measured at seven seconds for a single row of
                    # forty thousand, on every answer.
                    row["sources"].extend(base["sources"])
                    row["frameCounts"].extend([frames] * len(base["sources"]))
                    # Positions of one acquisition are imaged together, but one may
                    # be a frame ahead of another at the moment of looking. The
                    # slider follows the one furthest along.
                    if frames and (row.get("frames") or 0) < frames:
                        row["frames"] = frames

            # Segmentation masks saved beside the image become rows of their own,
            # of a different kind: the engine draws a mask by giving every object
            # its own colour, which is not something a picture layer can do.
            for mask in label_images(store_path):
                key = (root_number, kind, "mask", mask)
                row = merged.get(key)
                source = f"/data/{root_number}/{name}/labels/{mask}/|zarr2:"
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
            if watcher is not None:
                watcher.start()
            super().serve_forever(*args, **kwargs)

        def shutdown(self):
            # Let the listeners go before stopping, or each would sit through its
            # own quiet heartbeat before noticing the server had gone.
            told.close()
            if watcher is not None:
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
    )
    return _Server(("127.0.0.1", port), handler)


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

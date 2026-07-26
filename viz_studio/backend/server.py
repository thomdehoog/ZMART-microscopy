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
import threading
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# These are the viewer's own modules, and none of them pulls in anything heavy
# when imported -- numpy and zarr are only reached for inside the functions that
# actually read pixels. So they are imported here in the ordinary way rather than
# inside the function that uses them, which keeps import errors surfacing at
# startup instead of on the first request an operator makes.
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
        **kwargs,
    ):
        self._data_dir = data_dir  # where drawn targets are saved
        self._library = library  # which folders may be read from, and what is in them
        self._browse = browse  # opens a native folder chooser, when one is available
        self._site_dir = site_dir  # the built page, served as the base directory
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
        data = self._read(target)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        # Let the browser keep what it has already fetched, both the small files
        # describing a store and the pieces of image themselves.
        #
        # For the descriptions this is the single biggest saving when opening a
        # tiled acquisition: the viewer reads one per resolution level per store
        # before it can draw anything, so two hundred tiles means over a thousand
        # of them before a single pixel appears.
        #
        # For the image it matters at scale: a piece is written once and never
        # rewritten — each acquisition writes its own store and nothing is resized
        # — so a piece that exists will not change under us, and panning back over
        # somewhere you have already been should cost nothing. A piece not yet
        # written answers "nothing here", and *that* answer is not kept, so data
        # arriving later is still found when you next go looking.
        #
        # This does assume the writer puts a piece in place complete, rather than
        # letting a half-written one be read. `DATA_LAYOUT.md` asks for that, and
        # it is the same discipline that keeps a reader from seeing a torn image
        # during a live run.
        self.send_header("Cache-Control", "max-age=3600")
        self.end_headers()
        self.wfile.write(data)

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
        if self.path.rstrip("/") == "/api/revision":
            # Deliberately tiny: the viewer asks this often, and asks the expensive
            # question only when the answer here has changed.
            self._send_json({"revision": self._library.revision()})
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
    watch: bool = True,
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
    library.open(data_dir, names=names, watch=watch)

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
            # An operator-supplied window overrides measurement for both views,
            # so there is no need to read any pixels at all.
            found = {
                "window": window,
                "volumeWindow": window,
                "histogram": intensity_histogram(root / name),
            }
        else:
            found = measure(root / name)
        flat, volume = found["window"], found["volumeWindow"]
        color = channel_color(name) if coloured else None
        measured[key] = {
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
        return {**measured[key], "name": label}

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
                        "name": channel_name,
                        "group": group,
                        "channelIndex": index,
                        "color": list(color) if color else None,
                        # How many frames exist so far, so the time slider stops
                        # there rather than running out over frames not yet imaged.
                        "frames": frames,
                    }
                else:
                    # Another position of the same picture: add where to read it.
                    row["sources"] = [*row["sources"], *base["sources"]]
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
                    }
                else:
                    row["sources"] = [*row["sources"], source]
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
        }

    class _Server(ThreadingHTTPServer):
        # The engine opens several connections at once and asks for pieces in
        # parallel. The standard library lets only five wait to be accepted, and
        # anything beyond that is dropped and retried a second later.
        request_queue_size = 128
        daemon_threads = True

    handler = functools.partial(
        _Handler,
        data_dir=data_dir,
        site_dir=Path(site_dir).resolve(),
        config=build_config,
        library=library,
        browse=browse,
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

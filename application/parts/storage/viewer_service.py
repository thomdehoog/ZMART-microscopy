"""The ZMART viewer's server, run beside the bridge and pointed at the run.

The viewer (github.com/thomdehoog/ZMART-viewer) is the party that knows how to
serve OME-Zarr to a drawing engine: it links a folder of position stores into
one picture without copying a voxel, watches the folder as a run writes into
it, and answers the pieces of the picture over HTTP. This module runs that
server in-process, on a port of the machine's choosing, and keeps the small
amount of state the operator page asks about: whether it is up, where it is,
and which acquisition folders it has open.

The viewer is an optional guest. A machine without the ``zmart_viewer``
package installed simply has no picture server — the JPEG engine still draws —
and every question here answers with the sentence saying so rather than a
stack trace.

Two small liberties are taken with the guest, both worth naming:

- **Its answers are given to another origin.** The operator page is served by
  the dev server or the bridge, not by the viewer, so the browser will not let
  the page read the viewer's bytes unless the viewer says they may be read.
  The viewer does not say so itself (it serves its own page, same-origin), so
  its handler is wrapped here to add the one header. Both servers answer only
  on 127.0.0.1, so this opens nothing to anybody who could not already read
  the disk.
- **Sources are opened lazily**, on the first landed capture of each
  acquisition type, because the folder does not exist before that and the
  viewer refuses to open what is not there.

Author: Thom de Hoog (ZMB, University of Zurich).
License: MIT
"""

from __future__ import annotations

import json
import re
import threading
import urllib.request
from pathlib import Path

#: The service's whole state: one viewer per bridge process, like the run.
_viewer: dict = {
    "server": None, "thread": None, "port": None, "error": None,
    # viewer heading (the acquisition type, read off the store names) -> the
    # engine-ready sources: [{"url": ..., "name": ...}], each a whole address.
    "sources": {},
    # positions folder -> how many stores it held when it was linked. The
    # count matters, not just membership: a folder opened at ONE store was
    # opened as that store, and a folder opened at several links exactly the
    # stores that were there at the time — so what the viewer serves stops
    # matching the disk the moment another position lands, and the folder has
    # to be opened again over everything now there.
    "opened": {},
    # positions folder -> the acquisition type it holds, so a relink knows
    # which headings to close.
    "kind": {},
    # positions folder -> when it was last linked, so a run that lands a
    # position every half-second is not relinked every half-second.
    "linked_at": {},
}
_the_turn = threading.Lock()

#: How long a linked picture may stand before a grown folder is linked again.
#:
#: Every relink closes the acquisition and opens it afresh, and the viewer
#: numbers what it serves in the order it was opened — so a relink changes the
#: address. That is the whole reason this waits. Relinking on every landing
#: renumbered the source several times a second, and the page, which reads the
#: addresses and then opens them, was always one or two numbers behind: every
#: open it attempted had already been closed, and the answer was 403. Nothing
#: ever reached the screen, and nothing said why.
#:
#: Five seconds is a compromise between two real wants. An operator watching a
#: scan wants the picture to grow while they watch; the page wants an address
#: that is still alive by the time it has opened it. The relink happens as the
#: page asks what there is to draw (see :func:`status`), so the address it is
#: handed is always the freshest there has ever been.
A_PICTURE_MAY_STAND_FOR = 5.0


def start(run_folder: Path | str) -> None:
    """Bring the viewer up beside the run, or record why it cannot come up.

    Never raises: connecting to the microscope must not fail over the
    picture server, so a viewer that cannot start becomes a sentence in
    :func:`status` instead.
    """
    with _the_turn:
        if _viewer["server"] is not None:
            return
        _viewer["error"] = None
        try:
            from zmart_viewer import server as viewer_server

            made = viewer_server.make_server(
                port=0,
                data_dir=str(run_folder),
                live=True,
                allow_open=True,
                panel_side="left",
            )
            _allow_the_page_to_read(made)
            thread = threading.Thread(target=made.serve_forever, daemon=True)
            thread.start()
            _viewer.update(server=made, thread=thread, port=made.server_address[1])
        except Exception as why:  # noqa: BLE001 -- optional guest, sentence not stack
            _viewer["error"] = f"the viewer server did not start: {why}"


def stop() -> None:
    """The session is over, and the viewer with it."""
    with _the_turn:
        server = _viewer["server"]
        _viewer.update(
            server=None, thread=None, port=None,
            sources={}, opened={}, kind={}, linked_at={},
        )
        if server is not None:
            try:
                server.shutdown()
            except Exception:  # noqa: BLE001 -- already going away
                pass


def status() -> dict:
    """What the operator page asks: is the viewer up, and what does it hold.

    Any acquisition whose folder has grown is linked again first, so the
    addresses handed back are the freshest that have ever been served. That
    matters more than it sounds: a relink closes the old address, so an
    address given out and relinked a moment later is one the page can no
    longer open. Linking here — as the page asks — makes the gap as small as
    it can be.
    """
    _link_again_what_has_grown()
    with _the_turn:
        port = _viewer["port"]
        return {
            "running": port is not None,
            "url": f"http://127.0.0.1:{port}" if port is not None else None,
            "sources": {kind: list(held) for kind, held in _viewer["sources"].items()},
            "error": _viewer["error"],
        }


def a_position_landed(acquisition_type: str, positions_folder: Path | str) -> None:
    """A capture's position store has been written: make sure the viewer shows it.

    The first position of an acquisition type opens its folder as a source of
    its own. Later ones only ring the doorbell and note that the folder has
    grown; the linking itself waits until the page next asks what there is to
    draw, which is where the address it is given is freshest. Never raises —
    a viewer that cannot hear costs the live picture, not the scan.
    """
    folder = str(positions_folder)
    with _the_turn:
        port = _viewer["port"]
        if port is None:
            return
        _viewer["kind"][folder] = acquisition_type
        first_time = folder not in _viewer["opened"]
    try:
        if first_time:
            _link(port, folder, acquisition_type, closing=False)
        _ask(port, "/api/announce", {})
    except Exception as why:  # noqa: BLE001 -- the picture lags, the scan goes on
        with _the_turn:
            _viewer["error"] = f"the viewer was not told about {acquisition_type}: {why}"


def _link_again_what_has_grown() -> None:
    """Open afresh every acquisition whose folder holds more than it links.

    Rate-limited by :data:`A_PICTURE_MAY_STAND_FOR`, because each relink
    changes the address the acquisition is served at and an address that
    changes faster than the page can open it is an address nobody can draw.
    """
    import time

    with _the_turn:
        port = _viewer["port"]
        if port is None:
            return
        standing = list(_viewer["opened"].items())
        kinds = dict(_viewer["kind"])
        linked_at = dict(_viewer["linked_at"])

    now = time.monotonic()
    for folder, linked in standing:
        if now - linked_at.get(folder, 0.0) < A_PICTURE_MAY_STAND_FOR:
            continue
        try:
            on_disk = len(list(Path(folder).glob("*.ome.zarr")))
        except OSError:
            continue
        if on_disk <= linked:
            continue
        try:
            _link(port, folder, kinds.get(folder, "picture"), closing=True)
        except Exception as why:  # noqa: BLE001 -- the picture lags, the run goes on
            with _the_turn:
                _viewer["error"] = f"the picture of {folder} was not linked again: {why}"


def _link(port: int, folder: str, acquisition_type: str, *, closing: bool) -> None:
    """Open a positions folder, and remember what was linked and when.

    ``closing`` says whether this acquisition is already open and must be let
    go of first. Both of its names are closed, because the viewer knows the
    two shapes of an acquisition by different names: a folder opened at one
    store goes by the acquisition type, and a linked scene by its scene-store
    name. Closing only the first left every scene standing, so each relink
    added the same picture again — a growing pile of duplicates, every one of
    them an address that had already been superseded.
    """
    import time

    if closing:
        for name in (acquisition_type, f"{acquisition_type}.zmartview.zarr"):
            _ask(port, "/api/stores/close", {"group": name})
    on_disk = len(list(Path(folder).glob("*.ome.zarr")))
    answered = _ask(port, "/api/stores/open", {"path": folder})
    with _the_turn:
        _viewer["opened"][folder] = on_disk
        _viewer["linked_at"][folder] = time.monotonic()
        _viewer["sources"] = _the_sources_in(answered, port)


def _the_sources_in(config: dict, port: int) -> dict[str, list[dict]]:
    """Every drawable source the viewer's config names, grouped by heading.

    The config describes one row per channel, rows of one acquisition sharing
    a ``group`` (the acquisition type, read off the store names) and their
    store addresses in ``sources``; an engine wants each *store* once and
    reads the channels out of the store's own description. The viewer speaks
    page-relative addresses because its own page lives on its own origin; the
    operator page does not, so the host goes back on here — an engine handed
    an address with no host builds a layer that waits for ever (contract §3).
    """
    grouped: dict[str, dict[str, dict]] = {}
    for row in config.get("layers") or []:
        if row.get("kind") != "image":
            continue
        group = str(row.get("group") or "picture")
        # The viewer decorates a label when names collide: a session prefix
        # ("session-abc · focussing.zmartview.zarr") and a copy number
        # ("… (2)"). Both are the viewer's own bookkeeping, not the
        # acquisition's name, so they come off before the store suffix does —
        # a suffix at the end of a decorated label would otherwise survive
        # the stripping and stand as a heading of its own.
        group = group.rsplit(" · ", 1)[-1]
        group = re.sub(r" \(\d+\)$", "", group)
        for suffix in (".zmartview.zarr", ".ome.zarr", ".zarr"):
            group = group.removesuffix(suffix)
        for address in row.get("sources") or []:
            whole = (
                f"http://127.0.0.1:{port}{address}"
                if str(address).startswith("/") else str(address)
            )
            grouped.setdefault(group, {}).setdefault(whole, {"url": whole, "name": group})
    return {
        group: _only_the_newest_of(held.values()) for group, held in grouped.items()
    }


def _only_the_newest_of(held) -> list[dict]:
    """One address per acquisition: the most recently opened generation.

    This is the fix for the fault that kept an acquired overview off the
    operator's canvas, and it is worth writing down because nothing on screen
    could have shown it.

    Every time a growing folder is linked again, the viewer opens it afresh
    and numbers what it serves in the order it was opened — so one acquisition
    ends up served at several addresses, one per generation. Their headings
    differ only by the viewer's own decoration ("… (2)"), which is stripped
    just above, so all the generations fall under one heading; and the first
    one seen was kept, which is the *oldest*. The page was therefore handed a
    superseded picture. Its description still read correctly, so the layer
    built, reported no error, and sat at the right place on the canvas — and
    every piece of picture the engine then asked for came back "not found",
    because only the newest generation can still build its pieces. An
    acquisition that is present, correct, and completely invisible.

    The viewer numbers its datasets upwards, so the newest is the one with the
    highest number in its address. Where an address carries no number at all
    (a store named directly rather than served by the viewer) the order it
    arrived in stands.
    """
    def numbered(source: dict) -> int:
        found = re.search(r"/data/(\d+)/", source["url"])
        return int(found.group(1)) if found else -1

    sources = list(held)
    if len(sources) <= 1:
        return sources
    newest = max(sources, key=numbered)
    return [newest]


def _ask(port: int, route: str, payload: dict) -> dict:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{route}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as answer:
        return json.loads(answer.read() or b"{}")


def _allow_the_page_to_read(server) -> None:
    """Add the one CORS header to every answer the viewer gives.

    Done by wrapping the handler class's ``end_headers`` rather than by
    changing the viewer, so the vendored guest stays exactly what was tested.
    Candidate to offer upstream as an ``allow_origin=`` argument.
    """
    import functools

    handler = server.RequestHandlerClass
    while isinstance(handler, functools.partial):
        handler = handler.func
    if getattr(handler, "_zmart_cors_added", False):
        return
    plain = handler.end_headers

    def end_headers(self):  # noqa: ANN001 -- http.server's own shape
        self.send_header("Access-Control-Allow-Origin", "*")
        plain(self)

    def do_OPTIONS(self):  # noqa: N802, ANN001 -- http.server's own naming
        # The browser's preflight for a cross-origin POST (the page asking
        # /api/measure for a histogram). Answered here because the viewer
        # never needed to hear one: its own page lives on its own origin.
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    handler.end_headers = end_headers
    handler.do_OPTIONS = do_OPTIONS
    handler._zmart_cors_added = True

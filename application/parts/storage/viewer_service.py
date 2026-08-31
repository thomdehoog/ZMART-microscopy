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
import threading
import urllib.request
from pathlib import Path

#: The service's whole state: one viewer per bridge process, like the run.
_viewer: dict = {
    "server": None, "thread": None, "port": None, "error": None,
    # viewer heading (the acquisition type, read off the store names) -> the
    # engine-ready sources: [{"url": ..., "name": ...}], each a whole address.
    "sources": {},
    # the positions folders already opened as sources, so a landed capture
    # only rings the doorbell after the first of its kind.
    "opened": set(),
}
_the_turn = threading.Lock()


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
        _viewer.update(server=None, thread=None, port=None, sources={}, opened=set())
        if server is not None:
            try:
                server.shutdown()
            except Exception:  # noqa: BLE001 -- already going away
                pass


def status() -> dict:
    """What the operator page asks: is the viewer up, and what does it hold."""
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
    its own; every later one only rings the doorbell, and the viewer re-reads
    what is on disk. Never raises — a viewer that cannot hear costs the live
    picture, not the scan.
    """
    folder = str(positions_folder)
    with _the_turn:
        port = _viewer["port"]
        if port is None:
            return
        fresh = folder not in _viewer["opened"]
    try:
        if fresh:
            answered = _ask(port, "/api/stores/open", {"path": folder})
            with _the_turn:
                _viewer["opened"].add(folder)
                _viewer["sources"] = _the_sources_in(answered, port)
        _ask(port, "/api/announce", {})
    except Exception as why:  # noqa: BLE001 -- the picture lags, the scan goes on
        with _the_turn:
            _viewer["error"] = f"the viewer was not told about {acquisition_type}: {why}"


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
        for suffix in (".zmartview.zarr", ".ome.zarr", ".zarr"):
            group = group.removesuffix(suffix)
        for address in row.get("sources") or []:
            whole = (
                f"http://127.0.0.1:{port}{address}"
                if str(address).startswith("/") else str(address)
            )
            grouped.setdefault(group, {}).setdefault(whole, {"url": whole, "name": group})
    return {group: list(held.values()) for group, held in grouped.items()}


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

    handler.end_headers = end_headers
    handler._zmart_cors_added = True

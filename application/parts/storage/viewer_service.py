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
from importlib.metadata import version
from pathlib import Path

#: The operator asks for the live scene every 1.5 seconds.  A read must finish
#: before the next question or a stalled Viewer creates an ever-growing queue of
#: bridge requests while the microscope is meant to keep scanning.
VIEWER_POLL_TIMEOUT_S = 1.0

#: The operator integration is verified against this separate Smart Viewer
#: release.  An editable checkout is intentionally allowed, but an old copy of
#: the viewer living inside this repository is not: those sources are historical
#: reference material and do not own the runtime boundary.
SMART_VIEWER_VERSION = "0.2.0"
_MICROSCOPY_ROOT = Path(__file__).resolve().parents[3]

#: The service's whole state: one viewer per bridge process, like the run.
_viewer: dict = {
    "server": None,
    "thread": None,
    "port": None,
    "error": None,
    # viewer heading (the acquisition type, read off the store names) -> the
    # engine-ready sources: [{"url": ..., "name": ...}], each a whole address.
    "sources": {},
    # The same answer at Smart Viewer's real boundary: one logical acquisition
    # per group, whose channel rows each retain every spatial source.  Nine
    # fields by three channels is therefore one acquisition with three rows,
    # not nine acquisitions (and never twenty-seven controls).
    "acquisitions": [],
    # Positions folders already handed to Smart Viewer. Viewer 0.2 watches an
    # opened folder itself and adds later stores to the same dataset number,
    # so each folder is opened exactly once for the life of this service.
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
            viewer_server = _smart_viewer_server()

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


def viewer_provenance() -> dict[str, str]:
    """Identify and validate the Smart Viewer package that owns the server.

    Microscopy once carried a copied backend under ``viz_studio``.  It remains
    useful as historical design evidence, but accepting it at runtime would make
    imports depend on the current working directory.  The supported boundary is
    the separately installed ``zmart-viewer`` distribution at the version whose
    API and browser behavior this integration proves.
    """
    import zmart_viewer

    installed_version = version("zmart-viewer")
    package_path = Path(zmart_viewer.__file__).resolve()
    _validate_viewer_provenance(installed_version, package_path)
    return {"version": installed_version, "path": str(package_path)}


def _smart_viewer_server():
    """Return the validated external server module, never a copied backend."""
    viewer_provenance()
    from zmart_viewer import server

    return server


def _validate_viewer_provenance(installed_version: str, package_path: Path) -> None:
    """Reject an unproved release or anything imported from this repository."""
    resolved = package_path.resolve()
    if resolved.is_relative_to(_MICROSCOPY_ROOT):
        raise RuntimeError(
            "Smart Viewer must be installed from its separate ZMART-viewer checkout; "
            f"refusing the in-repository path {resolved}"
        )
    if installed_version != SMART_VIEWER_VERSION:
        raise RuntimeError(
            f"Smart Viewer {SMART_VIEWER_VERSION} is required; found {installed_version} "
            f"at {resolved}"
        )


def stop() -> None:
    """The session is over, and the viewer with it."""
    with _the_turn:
        server = _viewer["server"]
        _viewer.update(
            server=None,
            thread=None,
            port=None,
            sources={},
            acquisitions=[],
            opened=set(),
        )
        if server is not None:
            try:
                server.shutdown()
            except Exception:  # noqa: BLE001 -- already going away
                pass


def status() -> dict:
    """What the operator page asks: is the viewer up, and what does it hold.

    Smart Viewer watches folders that were opened while a run is growing. Its
    config therefore changes from one source to two, three, and so on without
    the folder being reopened. Read that config on every operator poll instead
    of freezing the answer returned by the first ``/api/stores/open`` call.
    """
    with _the_turn:
        port = _viewer["port"]

    if port is not None:
        try:
            current = _read(port, "/api/config")
        except Exception as why:  # noqa: BLE001 -- the scan must carry on
            with _the_turn:
                _viewer["error"] = f"the viewer's current picture could not be read: {why}"
        else:
            with _the_turn:
                # A stop/start may have replaced the server while the request
                # was in flight. Never publish one server's addresses as
                # another server's state.
                if _viewer["port"] == port:
                    _viewer["sources"] = _the_sources_in(current, port)
                    _viewer["acquisitions"] = _the_acquisitions_in(current, port)
                    _viewer["error"] = None

    with _the_turn:
        port = _viewer["port"]
        return {
            "running": port is not None,
            "url": f"http://127.0.0.1:{port}" if port is not None else None,
            "sources": {kind: list(held) for kind, held in _viewer["sources"].items()},
            "acquisitions": list(_viewer["acquisitions"]),
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
        first_time = folder not in _viewer["opened"]
    try:
        if first_time:
            answered = _ask(port, "/api/stores/open", {"path": folder})
            with _the_turn:
                _viewer["opened"].add(folder)
                _viewer["sources"] = _the_sources_in(answered, port)
                _viewer["acquisitions"] = _the_acquisitions_in(answered, port)
        # A rerun may replace chunks inside the same named store.  Smart Viewer
        # deliberately distinguishes that case: this wire word tells its live
        # readers that stable URLs may now contain new bytes.
        _ask(port, "/api/announce", {"wrote_image_in_place": True})
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
        # Session and copy decorations belong to the Viewer's library, not to
        # the acquisition heading the operator should see.
        group = group.rsplit(" · ", 1)[-1]
        group = re.sub(r" \(\d+\)$", "", group)
        for suffix in (".zmartview.zarr", ".ome.zarr", ".zarr"):
            group = group.removesuffix(suffix)
        for address in row.get("sources") or []:
            whole = (
                f"http://127.0.0.1:{port}{address}"
                if str(address).startswith("/")
                else str(address)
            )
            grouped.setdefault(group, {}).setdefault(whole, {"url": whole, "name": group})
    return {group: _only_the_newest_generation_of(held.values()) for group, held in grouped.items()}


def _the_acquisitions_in(config: dict, port: int) -> list[dict]:
    """Translate Smart Viewer's layer rows without destroying their shape.

    Smart Viewer 0.2 merges all position stores belonging to one channel into
    one layer row whose ``sources`` list carries the spatial pieces.  The
    operator's engine calls the containing group an acquisition and its panel
    calls each layer a channel, so this is a naming adapter only: every row and
    every source stays where the Viewer put it.

    The former adapter flattened ``sources`` first.  A 3-by-3, three-channel
    overview consequently became nine acquisitions and twenty-seven controls.
    That was not Smart Viewer behaviour and also prevented Neuroglancer from
    opening the nine tiles as one placed layer.
    """
    scene = _the_scene_in(config, port)
    grouped: dict[str, dict] = {}
    for layer in scene["layers"]:
        if layer.get("kind") != "image":
            continue
        group = layer["group"]
        sources = list(layer.get("sources") or [])
        if not sources:
            continue
        acquisition = grouped.setdefault(
            group,
            {"name": group, "url": sources[0], "channels": []},
        )
        acquisition["channels"].append(
            {
                "name": str(layer.get("name") or f"channel {len(acquisition['channels'])}"),
                "colour": layer.get("color"),
                "window": layer.get("window"),
                "histogram": layer.get("histogram"),
                "channelIndex": layer.get("channelIndex"),
                "localPosition": layer.get("localPosition"),
                "visible": layer.get("active") is not False,
                "sources": sources,
            }
        )
    return list(grouped.values())


def _the_scene_in(config: dict, port: int) -> dict:
    """Smart Viewer's current layer rows, with whole operator-page addresses.

    Reopening an older integration can leave two Viewer dataset generations
    carrying the same cleaned group label.  Keep the newest dataset exactly as
    before, but do it *inside each row* so all fields of that generation remain
    together as the Viewer's multi-source layer.
    """

    def whole(address: object) -> str:
        text = str(address)
        return f"http://127.0.0.1:{port}{text}" if text.startswith("/") else text

    def group_of(row: dict) -> str:
        group = str(row.get("group") or "picture")
        group = group.rsplit(" · ", 1)[-1]
        group = re.sub(r" \(\d+\)$", "", group)
        for suffix in (".zmartview.zarr", ".ome.zarr", ".zarr"):
            group = group.removesuffix(suffix)
        return group

    candidates = []
    newest: dict[str, int] = {}
    for original in config.get("layers") or []:
        if not isinstance(original, dict):
            continue
        row = dict(original)
        row["group"] = group_of(row)
        row["sources"] = [whole(source) for source in row.get("sources") or []]
        candidates.append(row)
        for source in row["sources"]:
            found = re.search(r"/data/(\d+)/", source)
            number = int(found.group(1)) if found else -1
            newest[row["group"]] = max(newest.get(row["group"], -1), number)

    layers = []
    for row in candidates:
        wanted = newest.get(row["group"], -1)
        row["sources"] = [
            source
            for source in row["sources"]
            if (int(found.group(1)) if (found := re.search(r"/data/(\d+)/", source)) else -1)
            == wanted
        ]
        if row["sources"]:
            layers.append(row)
    return {
        **{key: value for key, value in config.items() if key not in {"layers", "groups"}},
        "layers": layers,
        "groups": list(dict.fromkeys(row["group"] for row in layers)),
    }


def _only_the_newest_generation_of(held) -> list[dict]:
    """Keep every store in the newest Viewer dataset under a heading.

    Viewer 0.2 gives every store in one watched acquisition the same
    ``/data/N/`` dataset number. All of those stores are tiles of the picture
    and must reach the canvas. If an older integration has nevertheless left
    more than one generation open under the same heading, only the highest
    dataset number is still current.
    """

    def numbered(source: dict) -> int:
        found = re.search(r"/data/(\d+)/", source["url"])
        return int(found.group(1)) if found else -1

    sources = list(held)
    if len(sources) <= 1:
        return sources
    newest = max(numbered(source) for source in sources)
    return [source for source in sources if numbered(source) == newest]


def _ask(port: int, route: str, payload: dict) -> dict:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{route}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as answer:
        return json.loads(answer.read() or b"{}")


def _read(port: int, route: str) -> dict:
    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}{route}", timeout=VIEWER_POLL_TIMEOUT_S
    ) as answer:
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

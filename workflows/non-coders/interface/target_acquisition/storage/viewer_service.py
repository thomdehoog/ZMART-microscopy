"""The ZMART viewer's server, run beside the bridge and pointed at the run.

The viewer (github.com/ZMB-UZH/ZMART-viewer) is the party that knows how to
serve OME-Zarr to a drawing engine, optionally bake a coarse overview, and
answer image chunks directly over HTTP. This module runs that
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

Which viewer is accepted
------------------------

The ZMART-viewer package, installed on its own (``pip install zmart-viewer``
from its repository), in a version this interface was tested with: 0.5.0rc4
and later releases up to, not including, 0.6. Only the viewer's
public names are used (``zmart_viewer.make_server`` and
``zmart_viewer.views.publishing``), which its own package promises to keep
stable between versions.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
from importlib.metadata import version
from pathlib import Path
from urllib.parse import unquote

#: Only the background publisher waits for the viewer; acquisition and status
#: requests never perform viewer I/O.
VIEWER_REQUEST_TIMEOUT_S = 30.0
_metadata_reads = threading.Lock()

#: The viewer versions this interface is tested with: 0.5.0rc10 and later,
#: up to but not including 0.6. From 0.5.0rc2 the viewer itself names the
#: operator's page as allowed to read it, and refuses pages from elsewhere;
#: from 0.5.0rc3 its engine no longer takes the viewer window's own settings,
#: and it ships the shader programs and neuroglancer edits this page is built
#: with; from 0.5.0rc4 it reads the projections a driver already made
#: (views "projections_given") instead of making its own; from 0.5.0rc6 it
#: reads every translation as the centre of the first voxel, as the
#: interface writes it, and a run's canvas by its edges; from 0.5.0rc7 it
#: ships the drawing primitives this page draws through; from 0.5.0rc8
#: a store fed in later keeps its own depth; and from 0.5.0rc9 a piece
#: asked for right after a publication is never answered from the one
#: before; and from 0.5.0rc10 a projection of flat tiles at different
#: heights (a focus map's) shows them all. An older viewer would leave the page unable to read it, to be
#: built, or to show a driver's projections, would draw the picture half
#: a voxel from where it was taken, or would leave pieces of an earlier
#: publication on the canvas for good, or would show one flat tile of
#: many, so it is refused, as are the 0.5.0
#: development builds that came before its public names settled.
VIEWER_VERSIONS = ">=0.5.0rc10,<0.6"

#: The service's whole state: one viewer per bridge process, like the run.
_viewer: dict = {
    "server": None,
    "thread": None,
    "port": None,
    "error": None,
    # viewer heading (the acquisition type, read off the store names) -> the
    # engine-ready sources: [{"url": ..., "name": ...}], each a whole address.
    "sources": {},
    # The same answer at the ZMART viewer's real boundary: one logical acquisition
    # per group, whose channel rows each retain every spatial source.  Nine
    # fields by three channels is therefore one acquisition with three rows,
    # not nine acquisitions (and never twenty-seven controls).
    "acquisitions": [],
    # Positions folders already handed to the ZMART viewer. Viewer 0.2 watches an
    # opened folder itself and adds later stores to the same dataset number,
    # so each folder is opened exactly once for the life of this service.
    "opened": set(),
    "source_versions": {},
    "source_order": {},
    "published_versions": {},
    "publication_failures": {},
    "pending": set(),
    "publishing": set(),
    "wake": None,
}
_the_turn = threading.Lock()


def start(run_folder: Path | str, *, bake: bool = False, canvas: dict | None = None) -> None:
    """Bring the viewer up beside the run, or record why it cannot come up.

    Never raises: connecting to the microscope must not fail over the
    picture server, so a viewer that cannot start becomes a sentence in
    :func:`status` instead.

    ``canvas`` is the area pictures are laid out on, ``{"x_um", "y_um",
    "z_um"}`` as ``[min, max]``: the canvas get_xyz reports per axis, so a
    picture taken anywhere the stage can go lands inside it.
    """
    with _the_turn:
        if _viewer["server"] is not None:
            return
        _viewer["error"] = None
        try:
            make_server = _the_viewers_make_server()

            made = make_server(
                port=0,
                data_dir=str(run_folder),
                live=True,
                allow_open=True,
                canvas=canvas, transparent_background=True,
            )
            thread = threading.Thread(target=made.serve_forever, daemon=True)
            thread.start()
            wake = threading.Event()
            _viewer.update(server=made, thread=thread, port=made.server_address[1], wake=wake,
                           bake=bake, folder_types={})
            _viewer["canvas"] = canvas
            _viewer["run_folder"] = str(Path(run_folder).resolve())
            threading.Thread(target=_publish_changes, args=(wake,), daemon=True).start()
            threading.Thread(target=_watch_metadata, args=(wake,), daemon=True).start()
        except Exception as why:  # noqa: BLE001 -- optional guest, sentence not stack
            _viewer["error"] = f"the viewer server did not start: {why}"


def viewer_provenance() -> dict[str, str]:
    """Which viewer is installed, and where: checked against the versions accepted.

    Raises ``RuntimeError`` with a sentence saying what to install when the
    viewer is missing or of a version this interface was not tested with.
    """
    try:
        import zmart_viewer
    except ImportError:
        raise RuntimeError(
            "the ZMART viewer is not installed; install zmart-viewer "
            f"({VIEWER_VERSIONS}) to see the run as it is acquired"
        ) from None
    installed_version = version("zmart-viewer")
    _accept_the_version(installed_version)
    return {"version": installed_version, "path": str(Path(zmart_viewer.__file__).resolve())}


def _accept_the_version(installed_version: str) -> None:
    """Refuse a viewer outside :data:`VIEWER_VERSIONS`, saying which was found."""
    from packaging.specifiers import SpecifierSet  # noqa: PLC0415

    if not SpecifierSet(VIEWER_VERSIONS, prereleases=True).contains(installed_version):
        raise RuntimeError(
            f"the ZMART viewer {installed_version} is installed, and this interface "
            f"needs zmart-viewer {VIEWER_VERSIONS}"
        )


def _the_viewers_make_server():
    """The installed viewer's ``make_server``, once its version is accepted.

    The rendering contract is checked too: the viewer publishes each
    acquisition the way this interface draws it (positions relative in z),
    and says so with ``ACQUISITION_RENDERING_VERSION``.
    """
    viewer_provenance()
    from zmart_viewer import make_server  # noqa: PLC0415
    from zmart_viewer.views import publishing  # noqa: PLC0415

    if getattr(publishing, "ACQUISITION_RENDERING_VERSION", None) != 1:
        raise RuntimeError(
            "the installed ZMART viewer publishes acquisitions in a way this "
            "interface does not draw (ACQUISITION_RENDERING_VERSION is not 1)"
        )
    return make_server


def stop() -> None:
    """The session is over, and the viewer with it."""
    with _the_turn:
        server = _viewer["server"]
        if _viewer["wake"] is not None:
            _viewer["wake"].set()
        _viewer.update(
            server=None,
            thread=None,
            port=None,
            error=None,
            sources={},
            acquisitions=[],
            opened=set(),
            source_versions={},
            source_order={},
            projections_in={},
            published_versions={},
            publishing=set(),
            publication_failures={},
            pending=set(),
            wake=None,
            bake=False,
            folder_types={},
        )
        if server is not None:
            try:
                server.shutdown()
                # shutdown() only stops answering; this lets the port go.
                server.server_close()
            except Exception:  # noqa: BLE001 -- already going away
                pass


def status() -> dict:
    """Return the latest published picture without waiting for viewer I/O."""
    with _the_turn:
        port = _viewer["port"]
        errors = [f"{kind}: {failure['error']}"
                  for kind, failure in _viewer.get("publication_failures", {}).items()]
        if _viewer["error"]:
            errors.append(_viewer["error"])
        publications = {}
        busy = _viewer.get("pending", set()) | _viewer.get("publishing", set())
        busy_kinds = {_viewer.get("folder_types", {}).get(folder) for folder in busy}
        for kind, order in _viewer["source_order"].items():
            published = _viewer.get("published_versions", {}).get(kind, {})
            failure = _viewer.get("publication_failures", {}).get(kind, {})
            count = sum(published.get(name) == _viewer["source_versions"][(kind, name)]
                        for name in order)
            publications[kind] = {
                "acquired": len(order), "published": count,
                "state": ("blocked" if failure.get("blocked") else
                          "retrying" if failure else
                          "ready" if count == len(order) and kind not in busy_kinds else "preparing"),
                "error": failure.get("error"),
            }
        return {
            "running": port is not None,
            "url": f"http://127.0.0.1:{port}" if port is not None else None,
            "sources": {kind: list(held) for kind, held in _viewer["sources"].items()},
            "acquisitions": [dict(acquisition) for acquisition in _viewer["acquisitions"]],
            "error": "; ".join(errors) or None,
            "publications": publications,
        }


def a_position_landed(
    acquisition_type: str, positions_folder: Path | str, *, store: Path | str,
    projections_in: Path | str | None = None,
) -> None:
    """Record a completed write; publication must never hold up acquisition.

    *projections_in* is where this kind's projections already lie, made by
    the microscope's driver under each store's own name (or, for flat
    captures, their own folder): the viewer then reads them and makes none.
    """
    with _the_turn:
        if projections_in is not None:
            _viewer.setdefault("projections_in", {}).setdefault(acquisition_type, str(projections_in))
        if _viewer["port"] is None:
            return
        versions = _viewer["source_versions"]
        key = (acquisition_type, Path(store).name)
        previous = versions.get(key, 0)
        versions[key] = previous + 1
        order = _viewer["source_order"].setdefault(acquisition_type, [])
        if key[1] in order:
            order.remove(key[1])
        order.append(key[1])
        _viewer.setdefault("folder_types", {})[str(positions_folder)] = acquisition_type
        _queue_publication(str(positions_folder))


def raise_position(acquisition_type: str, positions_folder: Path, store: Path) -> None:
    """Change overlap order without rewriting or re-versioning original pixels."""
    with _the_turn:
        order = _viewer["source_order"].get(acquisition_type, [])
        if store.name in order:
            order.remove(store.name)
            order.append(store.name)
            _queue_publication(str(positions_folder))


def stores_were_retired(acquisition_type: str, positions_folder: Path | str) -> None:
    """Queue a new snapshot after a shorter rerun removes position stores."""
    folder = str(positions_folder)
    with _the_turn:
        if folder in _viewer["opened"] or any(
            kind == acquisition_type for kind, _ in _viewer["source_versions"]
        ):
            _viewer.setdefault("folder_types", {})[folder] = acquisition_type
            _queue_publication(folder)


def forget_stores(acquisition_type: str, keeping: set[str]) -> None:
    """Stop showing this kind's stores, except those named in *keeping*, without touching them.

    A store a driver saved is the capture itself and is never deleted; a
    rerun of the scan leaves it on disk and only stops handing it to the
    viewer, the way a deleted store of the interface's own drops out.
    """
    with _the_turn:
        versions = _viewer["source_versions"]
        gone = [key for key in versions if key[0] == acquisition_type and key[1] not in keeping]
        for key in gone:
            del versions[key]
        order = _viewer["source_order"].get(acquisition_type)
        if order is not None:
            order[:] = [name for name in order if name in keeping]
        if gone:
            for folder, kind in _viewer.get("folder_types", {}).items():
                if kind == acquisition_type:
                    _queue_publication(folder)


def _queue_publication(folder: str) -> None:
    # Called with the turn held. Coalesce by folder, not by frame.
    _viewer["pending"].add(folder)
    _viewer["wake"].set()


def _publish_changes(wake: threading.Event) -> None:
    retry = False
    while True:
        wake.wait(timeout=1.5 if retry else None)
        with _the_turn:
            if _viewer["wake"] is not wake:
                return
            wake.clear()
            pending = set(_viewer["pending"])
            _viewer["pending"].clear()
            _viewer.setdefault("publishing", set()).update(pending)
        retry = bool(pending) and not _publish_once(wake, pending)


def _publish_once(wake: threading.Event, pending: set[str]) -> bool:
    with _the_turn:
        if _viewer["wake"] is not wake:
            return True
        port = _viewer["port"]
        opened = set(_viewer["opened"])
        bake = _viewer.get("bake", False)
        versions = dict(_viewer["source_versions"])
        folder_types = dict(_viewer.get("folder_types", {}))
        orders = {kind: list(names) for kind, names in _viewer["source_order"].items()}
        canvas = _viewer["canvas"]
        run_folder = Path(_viewer["run_folder"])
        given = dict(_viewer.get("projections_in", {}))
        _viewer.setdefault("publishing", set()).update(pending)
    retry = set()
    blocked_folders = set()
    for folder in pending:
        kind = folder_types.get(folder)
        try:
            completed = {
                name: revision for (source_kind, name), revision in versions.items()
                if source_kind == kind and (Path(folder) / name).is_dir()
            }
            if not completed and folder not in opened:
                continue
            payload = {"path": folder, "source_revisions": completed, "composition": {
                "regions": "complete",
                "order": [n for n in orders.get(folder_types.get(folder), []) if n in completed],
                "pyramid_reduction": "mean-xy2-crop-f32-rint-int",
            }}
            if folder not in opened:
                _ask(port, "/api/stores/open", {
                    **payload, "bake": bake, "canvas": canvas,
                    "views": {
                        "path": str(run_folder / "view"),
                        "acquisition": kind,
                        "modes": [], "projections": ["max"],
                        **(
                            {"projection_path": given[kind], "projections_given": True}
                            if kind in given
                            else {"projection_path": str(run_folder / kind / "projections")}
                        ),
                    },
                })
                with _the_turn:
                    if _viewer["wake"] is not wake:
                        return True
                    _viewer["opened"].add(folder)
                    opened.add(folder)
            else:
                _ask(port, "/api/announce", {"publications": [payload]})
            with _the_turn:
                if _viewer["wake"] is not wake:
                    return True
                _viewer.setdefault("published_versions", {})[kind] = completed
                _viewer.setdefault("publication_failures", {}).pop(kind, None)
                # Forget retired names only if no newer capture has landed
                # while this snapshot was publishing.
                _viewer["source_order"][kind] = [
                    name for name in _viewer["source_order"].get(kind, [])
                    if name in completed or _viewer["source_versions"].get((kind, name))
                    != versions.get((kind, name))
                ]
        except Exception as why:  # noqa: BLE001 -- independent acquisition failures
            blocked = isinstance(why, PublicationRejected)
            if not blocked:
                retry.add(folder)
            else:
                blocked_folders.add(folder)
            with _the_turn:
                if _viewer["wake"] is not wake:
                    return True
                _viewer.setdefault("publication_failures", {})[kind] = {
                    "error": str(why), "blocked": blocked,
                }
    read_error = _refresh_metadata(wake, include_pending=False)
    if read_error is not None:
        retry.update(set(pending) - blocked_folders)
    with _the_turn:
        if _viewer["wake"] is wake:
            _viewer["error"] = read_error
            _viewer["pending"].update(retry)
            _viewer.setdefault("publishing", set()).difference_update(pending)
    return not retry


def _watch_metadata(wake: threading.Event) -> None:
    """Follow individual committed views while the publication worker is waiting."""
    pause = threading.Event()
    while True:
        with _the_turn:
            if _viewer["wake"] is not wake:
                return
            active = bool(_viewer.get("publishing") or _viewer.get("opened"))
        if active:
            _refresh_metadata(wake)
        pause.wait(0.5)


def _refresh_metadata(wake: threading.Event, *, include_pending=True) -> str | None:
    # Serialize metadata reads, never acquisition/status requests. A delayed
    # earlier response must not replace a newer view revision in the cache.
    with _metadata_reads:
        return _read_metadata(wake, include_pending=include_pending)


def _read_metadata(wake: threading.Event, *, include_pending: bool) -> str | None:
    with _the_turn:
        if _viewer["wake"] is not wake:
            return
        port = _viewer["port"]
        folders = _viewer["opened"] | (_viewer.get("publishing", set()) if include_pending else set())
        headings = {_viewer.get("folder_types", {}).get(folder) for folder in folders}
        opened_headings = {_viewer.get("folder_types", {}).get(folder)
                           for folder in _viewer["opened"]}
    try:
        current = _read(port, "/api/config")
        current = {**current, "layers": [row for row in current.get("layers", [])
                                        if (_the_heading_of(row) in opened_headings
                                            or (row.get("view") and _the_heading_of(row) in headings))]}
        sources = _the_sources_in(current, port)
        acquisitions = _the_acquisitions_in(current, port)
    except Exception as why:
        # Keep the last committed metadata during a transient server failure.
        return f"the viewer's current picture could not be read: {why}"
    with _the_turn:
        if _viewer["wake"] is wake:
            _viewer.update(sources=sources, acquisitions=acquisitions)
    return None


def _still_on_disk(address: str) -> bool:
    """Whether the store an address points at is still in an opened folder.

    A store removed by a shorter rerun stays in the viewer's rows; leaving it
    in the page's list would have the engine ask for pixels that no longer
    exist. Addresses that do not name a store in a folder this service opened
    are left alone. Called with or without the turn held, so it takes no lock
    of its own.
    """
    found = re.search(r"/data/\d+/([^/|]+)", str(address))
    folders = [Path(folder) for folder in _viewer["opened"]]
    if not found or not folders:
        return True
    name = unquote(found.group(1))
    return any((folder / name).is_dir() for folder in folders)


def _the_heading_of(row: dict) -> str:
    """The acquisition an image row belongs to, as the operator sees it named.

    Session and copy decorations belong to the Viewer's library, not to the
    acquisition heading the operator should see.
    """
    if row.get("view"):
        return row["view"]["acquisition"]
    group = str(row.get("group") or "picture")
    group = group.rsplit(" · ", 1)[-1]
    group = re.sub(r" \(\d+\)$", "", group)
    for suffix in (".zmartview.zarr", ".ome.zarr", ".zarr"):
        group = group.removesuffix(suffix)
    return group


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
        group = _the_heading_of(row)
        for address in row.get("sources") or []:
            if not row.get("view") and not _still_on_disk(address):
                continue
            whole = (
                f"http://127.0.0.1:{port}{address}"
                if str(address).startswith("/")
                else str(address)
            )
            grouped.setdefault(group, {}).setdefault(whole, {"url": whole, "name": group})
    return {group: _only_the_newest_generation_of(held.values()) for group, held in grouped.items()}


def _the_acquisitions_in(config: dict, port: int) -> list[dict]:
    """Translate the ZMART viewer's layer rows without destroying their shape.

    The ZMART viewer 0.2 merges all position stores belonging to one channel into
    one layer row whose ``sources`` list carries the spatial pieces.  The
    operator's engine calls the containing group an acquisition and its panel
    calls each layer a channel, so this is a naming adapter only: every row and
    every source stays where the Viewer put it.

    The former adapter flattened ``sources`` first.  A 3-by-3, three-channel
    overview consequently became nine acquisitions and twenty-seven controls.
    That was not how the ZMART viewer behaves, and also prevented Neuroglancer from
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
            {"name": group, "url": sources[0], "channels": [],
             "embeddingUrl": f"http://127.0.0.1:{port}/embedding.js"},
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
                "sourceDepths": layer.get("sourceDepths"),
                "sourceGeometryRevisions": layer.get("sourceGeometryRevisions"),
                **({"view": layer["view"]} if layer.get("view") else {}),
                **({"coverageSources": layer["coverageSources"]} if layer.get("coverageSources") else {}),
                "sourceRevisions": layer.get("sourceRevisions") or [
                    _viewer["source_versions"].get((group, unquote(found.group(1))), 0)
                    if (found := re.search(r"/data/\d+/([^/|]+)", source))
                    else 0
                    for source in sources
                ],
            }
        )
    return list(grouped.values())


def _the_scene_in(config: dict, port: int) -> dict:
    """The ZMART viewer's current layer rows, with whole operator-page addresses.

    Reopening an older integration can leave two Viewer dataset generations
    carrying the same cleaned group label.  Keep the newest dataset exactly as
    before, but do it *inside each row* so all fields of that generation remain
    together as the Viewer's multi-source layer.
    """

    def whole(address: object) -> str:
        text = str(address)
        return f"http://127.0.0.1:{port}{text}" if text.startswith("/") else text

    def group_of(row: dict) -> str:
        return _the_heading_of(row)

    candidates = []
    newest: dict[str, int] = {}
    for original in config.get("layers") or []:
        if not isinstance(original, dict):
            continue
        row = dict(original)
        row["group"] = group_of(row)
        row["sources"] = [
            whole(source) for source in row.get("sources") or []
            if row.get("view") or _still_on_disk(source)
        ]
        if row.get("coverageSources"):
            row["coverageSources"] = [whole(source) for source in row["coverageSources"]]
        candidates.append(row)
        for source in row["sources"]:
            found = re.search(r"/data/(\d+)/", source)
            number = int(found.group(1)) if found else -1
            newest[row["group"]] = max(newest.get(row["group"], -1), number)

    layers = []
    for row in candidates:
        if row.get("view"):
            if row["sources"]:
                layers.append(row)
            continue
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


class PublicationRejected(RuntimeError):
    """Invalid input needs a changed publication, not an idle retry."""


def _ask(port: int, route: str, payload: dict) -> dict:
    """Wait for this publication before the worker submits its coalesced successor.

    A socket timeout does not cancel the server's write. Retrying it while that
    write still runs would queue obsolete snapshots instead of coalescing them.
    Capture and status never wait on this background worker.
    """
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{route}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=None) as answer:
            return json.loads(answer.read() or b"{}")
    except urllib.error.HTTPError as error:
        detail = json.loads(error.read() or b"{}").get("error", str(error))
        failure = PublicationRejected if error.code in {400, 422} else RuntimeError
        raise failure(detail) from error


def _read(port: int, route: str) -> dict:
    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}{route}", timeout=VIEWER_REQUEST_TIMEOUT_S
    ) as answer:
        return json.loads(answer.read() or b"{}")

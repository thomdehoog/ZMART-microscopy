"""Manifest-aware serving for live positions and the one virtual linked view.

The files under a live run are deliberately written before the atomic publication
record moves.  A plain static-file server therefore cannot distinguish a finished
chunk from one that is merely present on disk.  This module is the small boundary
between the viewer server and those files: metadata is always readable, while
pixel requests are attributed to one position and moment and are served only when
the run manifest says that exact unit is published.

For the linked view it also completes the zero-copy route.  A view chunk is
answered by an encoded inner chunk inside a canonical position's shard, using
:mod:`zmart_live.viewroute`; no pixel is decoded or copied.  Where positions
overlap, the route's claims are walked newest first and the newest **published**
claim answers — so a position that is written and routed but not yet committed
neither appears early nor blanks the published ground it is about to take over.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from .identity import load_a_layout_revision, load_the_profile
from .manifest import RunManifest
from .model import (
    AcquisitionProfile,
    SceneLayoutRevision,
    ZmartLiveError,
)
from .viewroute import (
    Placed,
    Serving,
    ViewRoute,
    refuse_a_view_stored_differently,
    route_the_view,
)

__all__ = [
    "LiveResponse",
    "answer_from_a_live_run",
    "forget_live_run",
    "live_run_holding",
]

_BOOKKEEPING = "zmart-live"
_TRUTH = "committed.json"
_LINKS = "links.json"
_LINKS_SCHEMA = "zmart-live-links/3"
_VIEW = Path("views/overview.ome.zarr")
_GENERATION = re.compile(r"^(?P<position>.+)\.generation-(?P<generation>\d+)\.ome\.zarr$")


@dataclass(frozen=True)
class LiveResponse:
    """What the server should do with one pixel request from a live run.

    ``allowed=False`` means answer with ordinary sparse-image absence (HTTP 404).
    ``serving`` names existing encoded canonical bytes for a virtual view chunk.
    When it is ``None`` and the request is allowed, the request itself names a
    canonical position file or ordinary metadata and is served normally. View
    chunk requests never use that path.
    """

    allowed: bool
    serving: Serving | None = None


def _piece_in(path: Path) -> tuple[int, ...] | None:
    """Read a Zarr v3 chunk coordinate from the end of a relative path."""
    parts = path.parts
    at = len(parts) - 1
    numbers: list[int] = []
    while at >= 0 and parts[at].isdigit():
        numbers.insert(0, int(parts[at]))
        at -= 1
    if not numbers or at < 0 or parts[at] != "c":
        return None
    return tuple(numbers)


def _generation_named(
    store_name: str, position_ids: tuple[str, ...] = ()
) -> tuple[str, int] | None:
    # Early runs could legally contain dots and the word ``generation`` before
    # the replacement-store namespace was reserved.  The immutable layout gets
    # first say so that a lone legacy canonical name is not reinterpreted as
    # somebody else's replacement suffix.  New runs refuse such identifiers at
    # construction time because a layout containing both spellings is
    # fundamentally ambiguous on disk.
    for position_id in sorted(position_ids, key=len, reverse=True):
        if store_name == f"{position_id}.ome.zarr":
            return position_id, 0
        prefix = f"{position_id}.generation-"
        ending = ".ome.zarr"
        if store_name.startswith(prefix) and store_name.endswith(ending):
            generation = store_name[len(prefix) : -len(ending)]
            if generation.isdigit():
                return position_id, int(generation)
    found = _GENERATION.fullmatch(store_name)
    if found:
        return found.group("position"), int(found.group("generation"))
    ending = ".ome.zarr"
    if store_name.endswith(ending):
        return store_name[: -len(ending)], 0
    return None


def _inside(path: Path, parent: Path) -> bool:
    resolved = path.resolve()
    root = parent.resolve()
    return resolved == root or root in resolved.parents


class _LiveRun:
    """The cached, fail-closed interpretation of one run folder."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder.resolve()
        self.manifest = RunManifest.open(self.folder)
        self._publication_mark: tuple[int, int, int, int] | None = None
        self._published: frozenset[tuple[str, int, int]] = frozenset()
        self._layout_mark: tuple[int, int, int, int] | None = None
        self._layout: SceneLayoutRevision | None = None
        self._profile: AcquisitionProfile | None = None
        self._links_mark: tuple[int, int, int, int] | None = None
        self._routes: dict[int, ViewRoute] = {}
        self._commit_order: tuple[str, ...] = ()
        self._lock = threading.RLock()

    def _published_units(self) -> frozenset[tuple[str, int, int]]:
        mark = self.manifest.fingerprint()
        with self._lock:
            if mark != self._publication_mark:
                published: set[tuple[str, int, int]] = set()
                arrival_order: list[str] = []
                moments_by_position: dict[str, set[int]] = {}
                replacements_seen: dict[str, int] = {}
                for event in self.manifest.events():
                    if event.position_id not in arrival_order:
                        arrival_order.append(event.position_id)
                    position_id = event.position_id
                    inferred = replacements_seen.get(position_id, 0)
                    if event.event_type == "position_replaced":
                        inferred += 1
                        replacements_seen[position_id] = inferred
                    generation = max(event.position_generation, inferred)
                    moment = 0 if event.timepoint is None else event.timepoint
                    already_visible = moments_by_position.setdefault(position_id, set())
                    if event.event_type == "position_replaced":
                        # Replacement copies the entire immutable position before
                        # changing one moment.  The one atomic replacement commit
                        # therefore advances every moment that was already public
                        # to this generation, while moments never committed remain
                        # withheld even if their fill-value room was copied too.
                        published.update(
                            (position_id, inherited, generation)
                            for inherited in already_visible
                        )
                    already_visible.add(moment)
                    published.add((position_id, moment, generation))
                self._published = frozenset(published)
                self._commit_order = tuple(arrival_order)
                self._publication_mark = mark
            return self._published

    def _positions_in_commit_order(self) -> tuple[str, ...]:
        """Every published position in first-arrival order — the draw order."""
        self._published_units()
        with self._lock:
            return self._commit_order

    def published(self, position_id: str, moment: int, generation: int) -> bool:
        return (position_id, moment, generation) in self._published_units()

    def _geometry(self) -> tuple[SceneLayoutRevision, AcquisitionProfile]:
        pointer = self.folder / _BOOKKEEPING / "layout.json"
        stamp = pointer.stat()
        mark = (
            stamp.st_mtime_ns,
            stamp.st_ctime_ns,
            stamp.st_size,
            getattr(stamp, "st_ino", 0),
        )
        with self._lock:
            if mark != self._layout_mark:
                described = json.loads(pointer.read_text(encoding="utf-8"))
                revision = int(described["revision"])
                layout = load_a_layout_revision(self.folder, revision)
                profile = load_the_profile(self.folder, layout.profile_id)
                self._layout = layout
                self._profile = profile
                self._layout_mark = mark
            assert self._layout is not None and self._profile is not None
            return self._layout, self._profile

    def _routes_now(self) -> dict[int, ViewRoute]:
        link_file = self.folder / _BOOKKEEPING / _LINKS
        stamp = link_file.stat()
        mark = (
            stamp.st_mtime_ns,
            stamp.st_ctime_ns,
            stamp.st_size,
            getattr(stamp, "st_ino", 0),
        )
        with self._lock:
            if mark == self._links_mark:
                return self._routes
            held = json.loads(link_file.read_text(encoding="utf-8"))
            if held.get("schema") != _LINKS_SCHEMA:
                raise ValueError("the live view link map has an unknown schema")
            layout, profile = self._geometry()
            position_ids = tuple(placement.position_id for placement in layout.positions)
            for key, expected in (
                ("run_id", layout.run_id),
                ("profile_id", profile.profile_id),
                ("scene_layout_revision", layout.revision),
            ):
                if held.get(key) != expected:
                    raise ValueError(
                        f"the live view link map names the wrong {key.replace('_', ' ')}"
                    )
            generations = held.get("position_generations") or {}
            if not isinstance(generations, dict):
                raise ValueError("the live view generation map is not a table")
            routes: dict[int, ViewRoute] = {}
            routed_levels: set[int] = set()
            declared_order: tuple[str, ...] | None = None
            for level in held.get("levels", ()):
                level_number = int(level["level"])
                routed_levels.add(level_number)
                entries = tuple(level.get("positions") or ())
                if not entries:
                    continue
                placed = []
                position_ids = [str(entry["position_id"]) for entry in entries]
                if len(position_ids) != len(set(position_ids)) or set(position_ids) != set(
                    generations
                ):
                    raise ValueError(
                        "each routed level must name every declared position exactly once"
                    )
                # The order of the entries is the draw order, so it is validated
                # like any other route fact.  Every level must declare the same
                # order, committed positions must appear exactly as the manifest
                # first committed them, and a position routed ahead of its own
                # commit may only sit at the tail — behind everything published,
                # where a brand-new arrival belongs.
                if declared_order is None:
                    declared_order = tuple(position_ids)
                    committed_order = [
                        position_id
                        for position_id in self._positions_in_commit_order()
                        if position_id in set(position_ids)
                    ]
                    already_committed = set(committed_order)
                    if [
                        position_id
                        for position_id in position_ids
                        if position_id in already_committed
                    ] != committed_order:
                        raise ValueError(
                            "the live view draw order disagrees with the manifest's "
                            "commit order"
                        )
                    first_uncommitted = next(
                        (
                            at
                            for at, position_id in enumerate(position_ids)
                            if position_id not in already_committed
                        ),
                        len(position_ids),
                    )
                    if any(
                        position_id in already_committed
                        for position_id in position_ids[first_uncommitted:]
                    ):
                        raise ValueError(
                            "an uncommitted position is routed ahead of published "
                            "ground in the live view draw order"
                        )
                elif tuple(position_ids) != declared_order:
                    raise ValueError(
                        "the live view levels disagree about the draw order"
                    )
                geometry = profile.level(level_number)
                by_z = geometry.downsampling.get("z", 1)
                by_y = geometry.downsampling.get("y", 1)
                by_x = geometry.downsampling.get("x", 1)
                expected_view_shape = (
                    profile.frame_shape.get("z", 1) // by_z,
                    max(
                        placement.origin["y"] + profile.frame_shape["y"]
                        for placement in layout.positions
                    )
                    // by_y,
                    max(
                        placement.origin["x"] + profile.frame_shape["x"]
                        for placement in layout.positions
                    )
                    // by_x,
                )
                if tuple(level["view_shape"]) != expected_view_shape:
                    raise ValueError("a live view route declares the wrong view shape")
                for entry in entries:
                    position_id = str(entry["position_id"])
                    if position_id not in generations:
                        raise ValueError(
                            "a routed position has no generation in the live link map"
                        )
                    array = (self.folder / entry["array"]).resolve()
                    named = _generation_named(array.parent.name, position_ids)
                    expected_generation = int(generations[position_id])
                    if (
                        not _inside(array, self.folder)
                        or named != (position_id, expected_generation)
                        or array.name != str(level_number)
                    ):
                        raise ValueError(
                            "a live view route does not name its declared canonical "
                            "position generation and pyramid level"
                        )
                    placement = layout.placement(position_id)
                    expected_lands_at = (
                        0,
                        placement.origin["y"] // by_y,
                        placement.origin["x"] // by_x,
                    )
                    expected_size = (
                        profile.frame_shape.get("z", 1) // by_z,
                        profile.frame_shape["y"] // by_y,
                        profile.frame_shape["x"] // by_x,
                    )
                    if (
                        tuple(entry["lands_at"]) != expected_lands_at
                        or tuple(entry["taken_from"]) != (0, 0, 0)
                        or tuple(entry["size"]) != expected_size
                    ):
                        raise ValueError(
                            "a live view route disagrees with the immutable layout"
                        )
                    placed.append(
                        Placed(
                            array=array,
                            lands_at=tuple(entry["lands_at"]),
                            taken_from=tuple(entry["taken_from"]),
                            size=tuple(entry["size"]),
                        )
                    )
                route = route_the_view(
                    placed,
                    view_shape=tuple(level["view_shape"]),
                )
                view_array = self.folder / _VIEW / str(level_number)
                if (view_array / "c").exists():
                    raise ValueError("the linked virtual view contains pixel chunks")
                refuse_a_view_stored_differently(view_array, route)
                routes[level_number] = route
            expected_levels = set(profile.linkable_levels) if generations else set()
            if routed_levels != expected_levels:
                raise ValueError("the live view route has the wrong pyramid levels")
            self._routes = routes
            self._links_mark = mark
            return routes

    def _published_serving(self, route: ViewRoute, piece: tuple[int, ...]) -> LiveResponse:
        """Serve the newest published claim on one piece, or withhold it.

        The claims are walked newest arrival first. A claim whose position and
        moment are not yet published is stepped over rather than served, so the
        ground a written-but-withheld arrival covers keeps showing the last
        published recording instead of blinking out — and never shows the
        withheld one early. The first *published* claim answers; if its chunk
        bytes are absent, the answer is absence, never an older tile's pixels,
        because a published position was read back complete and a gap in it is
        damage to fail closed on.
        """
        layout, _profile = self._geometry()
        position_ids = tuple(placement.position_id for placement in layout.positions)
        moment = piece[0]
        for claim in route.claims_on(piece):
            if not _inside(claim.position, self.folder):
                return LiveResponse(False)
            named = _generation_named(claim.position.parent.name, position_ids)
            if named is None:
                return LiveResponse(False)
            position_id, generation = named
            if not self.published(position_id, moment, generation):
                continue
            serving = claim.serving()
            if serving is None or not _inside(serving.path, self.folder):
                return LiveResponse(False)
            return LiveResponse(True, serving)
        return LiveResponse(False)

    def _view_route(self, relative: Path, piece: tuple[int, ...]) -> LiveResponse | None:
        try:
            inside = relative.relative_to(_VIEW)
        except ValueError:
            return None
        # Accept a numeric multiscale level between the view group and ``c``.
        before_chunk = inside.parts[: inside.parts.index("c")]
        level = int(before_chunk[-1]) if before_chunk and before_chunk[-1].isdigit() else 0
        route = self._routes_now().get(level)
        if route is None or not route.covers(piece):
            return LiveResponse(False)
        return self._published_serving(route, piece)

    def answer(self, target: Path) -> LiveResponse | None:
        """Classify one resolved request target, or leave ordinary data alone."""
        try:
            relative = target.relative_to(self.folder)
        except ValueError:
            return None
        piece = _piece_in(relative)
        if piece is None:
            return None

        parts = relative.parts
        if len(parts) >= 3 and parts[0] == "positions":
            layout, _profile = self._geometry()
            named = _generation_named(
                parts[1],
                tuple(placement.position_id for placement in layout.positions),
            )
            if named is None or not piece:
                return LiveResponse(False)
            position_id, generation = named
            return LiveResponse(self.published(position_id, piece[0], generation))

        return self._view_route(relative, piece)


_known: dict[Path, _LiveRun] = {}
_known_lock = threading.Lock()


def live_run_holding(target: str | Path) -> Path | None:
    """Find the nearest live-run root above a possibly absent target.

    Once the bookkeeping directory exists, loss of ``committed.json`` is damage,
    not a conversion back into an ordinary ungoverned folder. Recognizing the
    directory keeps pixel requests fail-closed while the small marker is restored.
    """
    target = Path(target).resolve()
    for candidate in (target, *target.parents):
        if (candidate / _BOOKKEEPING).is_dir():
            return candidate.resolve()
    return None


def answer_from_a_live_run(target: str | Path) -> LiveResponse | None:
    """Return the manifest decision for a pixel path, failing closed on damage.

    ``None`` means the path is not governed live pixel data (usually metadata or
    an ordinary, static OME-Zarr).  Any failure after a live run is recognised is
    returned as ``allowed=False``: a blank patch is safer than a plausible image
    assembled from state whose publication record could not be interpreted.
    """
    target = Path(target).resolve()
    run_folder = live_run_holding(target)
    if run_folder is None:
        return None
    try:
        with _known_lock:
            run = _known.get(run_folder)
            if run is None:
                run = _known[run_folder] = _LiveRun(run_folder)
        return run.answer(target)
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        json.JSONDecodeError,
        ZmartLiveError,
    ):
        return LiveResponse(False)


def forget_live_run(folder: str | Path) -> None:
    """Drop cached manifest, geometry and routes for a run that was closed."""
    with _known_lock:
        _known.pop(Path(folder).resolve(), None)

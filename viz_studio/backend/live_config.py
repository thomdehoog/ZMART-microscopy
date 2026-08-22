"""Adapt manifest-driven aggregate scenes to the studio's frontend vocabulary.

This module is also where the migration to one live path is finished: the live
source a browser is handed is the run's **governed baked picture**, declared at
``views/live/picture.ome.zarr`` when the run is first bound, not the zero-copy linked
view the scene still compiles. The substitution lives here, in the adapter,
because the two packages must stay one-directional: ``viz_studio`` may import
``building``, while ``zmart_live`` — whose scene compiler names the linked
view — must know nothing about either. The linked view keeps being written per
publish and keeps its gateway route; only what the frontend draws live moves.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from contrast import intensity_histogram
from stores import described_channels, zarr_scheme

# ``zmart_live`` is a package of the checkout rather than of this folder, so it
# is reachable only when the checkout's own root is on the path. Put there here
# because this is the module that needs it, in the same way and for the same
# reason the backend adds the ``building`` folder a few lines below.
#
# Without it the viewer runs under pytest -- which puts the root on the path
# itself -- and nowhere else. `python run_demo.py` from viz_studio, which is
# what the README tells an operator to type, stopped at this import with
# "No module named 'zmart_live'"; so did the launcher, and so did the shipped
# browser check, whose gate has been saying so.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from zmart_live.gateway import live_run_holding  # noqa: E402
from zmart_live.live_state import LiveStateSnapshot, LiveStateTracker
from zmart_live.model import ZmartLiveError
from zmart_live.omezarr import the_channels_described

# The governed-picture declaration comes from the building folder, which sits
# beside the backend rather than among its modules -- the same arrangement, and
# the same guard, as the backend server's own import of ``served``. A checkout
# without it can still show ordinary folders; a governed run then binds with an
# error rather than quietly falling back to the linked view.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "building"))
try:
    from declare import declare_a_governed_picture
except ImportError:  # pragma: no cover - a checkout without the building module
    declare_a_governed_picture = None

LIVE_STATE_SET_SCHEMA = "zmart-live-frontend-state-set/1"

# Where a live run's served picture lives, relative to the run root: inside
# the live view's own folder, beside the linked store and the view's
# metadata -- the picture is part of that one view, exactly as the contract
# draws it.
LIVE_PICTURE = "views/live/picture.ome.zarr"

# How long a failed declaration is remembered before it is tried again. Long
# enough that a refusal does not re-derive the run on every config poll, short
# enough that a transient failure -- endpoint protection holding a fresh file,
# the site's known trouble -- heals without restarting the viewer.
_DECLARE_RETRY_S = 2.0


def the_live_picture_declared(run_root: Path) -> Path:
    """The governed picture this run is served by, declared if needed.

    Every run is declared with the bake, so its cold open reads files and
    every commit patches its own footprint -- the one live path the
    2026-08-13 decision settles on. A run grown along (t, c) bakes one
    file per (moment, channel) frame, kept true per commit exactly as a
    flat run's files are; the last bake refusal retired with
    ``test_a_grown_run_is_baked_per_commit``.

    Declaring can take seconds to minutes at scale, so it happens once, on
    the binding's first creation: a store already declared FROM THIS RUN in
    the shape the run needs today is recognised and left alone. A store
    declared from some other run, or in yesterday's shape (a run that grew
    axes since), is re-declared rather than trusted.
    """
    store = run_root / LIVE_PICTURE
    grown = _the_run_is_grown(run_root)
    if _already_this_runs_picture(store, run_root, grown):
        return store
    if declare_a_governed_picture is None:
        raise RuntimeError(
            f"the live run at {run_root} needs its governed picture declared, "
            "and this checkout has no building module to declare it with."
        )
    began = time.perf_counter()
    made = declare_a_governed_picture(
        run_root / "views" / "live", run_root, name="picture", bake=True
    )
    print(
        f"declared the {'grown, ' if grown else ''}baked live picture "
        f"{made} in {time.perf_counter() - began:.1f} s",
        flush=True,
    )
    return made


def _the_run_is_grown(run_root: Path) -> bool:
    """Whether this run's picture carries the (t, c) axes.

    The sealed profile is the declaration for every run written since the
    time room entered it. Runs sealed BEFORE then declared their room only
    in the arrays, so the first member's array gets a say too -- the same
    whichever-declares-more rule the world frame applies -- or exactly
    those runs would be declared flat and silently truncate every moment
    after the first.
    """
    from zmart_live.gateway import _LiveRun

    profile = _LiveRun(run_root)._geometry()[1]
    if profile.timepoints > 1 or len(profile.channels) > 1:
        return True
    collection = run_root / "data" / "survey.ome.zarr"
    for member in sorted(collection.glob("*/0/zarr.json")):
        try:
            shape = json.loads(member.read_text(encoding="utf-8")).get("shape")
        except (OSError, ValueError):
            continue
        if shape and len(shape) == 5:
            return shape[0] > 1 or shape[1] > 1
    return False


def _already_this_runs_picture(store: Path, run_root: Path,
                               grown: bool) -> bool:
    """Whether the store already is this run's picture, in today's shape.

    The durable mark is ``baked.json`` -- written only by a finished bake,
    flat and grown alike. A grown picture declared in the days it composed
    on request carries no stamp, so it is quietly re-declared with its
    bake the first time it binds. The shape has to match what the run
    needs TODAY as well: a picture declared flat before its run grew axes
    would silently truncate every later moment, so it is re-declared
    instead. Anything unreadable answers ``False`` -- the re-declaration
    overwrites cleanly, which is the fail-closed direction.
    """
    try:
        described = json.loads((store / "zarr.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    ours = (described.get("attributes") or {}).get("zmart") or {}
    governs = ours.get("governed_from")
    if not governs:
        return False
    try:
        if Path(governs).resolve() != run_root.resolve():
            return False
    except OSError:
        return False
    axes = [axis.get("name") for axis in
            ((described.get("attributes") or {}).get("ome") or {})
            .get("multiscales", [{}])[0].get("axes", [])]
    if grown:
        return axes[:2] == ["t", "c"]
    return axes[:1] == ["z"] and (store / "baked.json").is_file()


@dataclass(frozen=True)
class LiveBinding:
    """One manifest run and the library root through which it is served."""

    tracker: LiveStateTracker
    dataset_number: int
    dataset_root: Path
    group: str = ""

    @property
    def run_root(self) -> Path:
        return self.tracker.run_root

    def _source_store(self, relative_url: str) -> Path:
        return (self.run_root / relative_url).resolve()

    def source_url(self, relative_url: str) -> str:
        """A stable browser URL, relative to the opened library root."""
        store = self._source_store(relative_url)
        try:
            inside = store.relative_to(self.dataset_root)
        except ValueError as why:
            raise ValueError(
                f"The compiled live source {store} is outside the opened folder "
                f"{self.dataset_root}. Open the run root or its views folder."
            ) from why
        return f"/data/{self.dataset_number}/{inside.as_posix()}/|{zarr_scheme(store)}:"

    def state_json(self, snapshot: LiveStateSnapshot | None = None) -> dict:
        """The run's frontend state, naming the source actually served.

        The tracker's compiled state names the linked view, because the scene
        compiler in ``zmart_live`` knows nothing of the governed picture. The
        substitution happens here so the state document and the config rows
        agree on the live source's address -- the frontend refuses a source
        whose URL moves between the two.
        """
        answer = (snapshot or self.tracker.snapshot()).to_json()
        for source in answer.get("sources", ()):
            if source.get("role") == "linked":
                source["url"] = LIVE_PICTURE
        answer["dataset"] = self.dataset_number
        return answer


class LiveRegistry:
    """Track manifest-governed datasets as the ordinary library opens/closes.

    Recognition is deliberately based only on the publication marker. A broken
    marker still governs (and therefore excludes) its dataset from generic folder
    inference, but it does not become a binding until strict state can be opened.
    One tracker is shared if the same run is intentionally opened twice.
    """

    def __init__(self, library) -> None:
        self._library = library
        self._lock = threading.RLock()
        self._trackers_by_root: dict[Path, LiveStateTracker] = {}
        self._pictures: dict[Path, Path] = {}
        self._picture_refused: dict[Path, tuple[float, str]] = {}
        self._bindings: tuple[LiveBinding, ...] = ()
        self._dataset_numbers: frozenset[int] = frozenset()
        self._errors: dict[Path, str] = {}

    def refresh(self) -> tuple[tuple[LiveBinding, ...], frozenset[int]]:
        with self._lock:
            datasets = tuple(self._library.datasets())
            governed: set[int] = set()
            bindings: list[LiveBinding] = []
            used_roots: set[Path] = set()
            errors: dict[Path, str] = {}
            for dataset in datasets:
                run_root = live_run_holding(dataset.root)
                if run_root is None:
                    continue
                # A live binding is only made where the live view can actually
                # be served: the run root, or a folder holding the live view.
                # Any OTHER opened folder inside the run -- one specific
                # derived view, a gate's declared picture, a sealed export --
                # is an ordinary dataset: its rows are built from the stores
                # it holds, exactly as if it lay outside the run. Substituting
                # the run's live picture into it is impossible by construction
                # (the picture is not under the opened folder), and declaring
                # one on its behalf would bake a second picture nobody asked
                # for. Its pixel requests still pass the manifest gate, which
                # keys off the files, not off this registry.
                picture = (run_root / LIVE_PICTURE).resolve()
                opened = Path(dataset.root).resolve()
                if not (opened == picture or opened in picture.parents):
                    continue
                governed.add(dataset.number)
                dataset.watch = False
                tracker = self._trackers_by_root.get(run_root)
                if tracker is None:
                    try:
                        tracker = LiveStateTracker(run_root)
                    except (OSError, ValueError, ZmartLiveError) as why:
                        # Never let a recognizable but damaged manifest fall back
                        # to folder scanning. A later refresh retries strict open.
                        errors[run_root] = str(why)
                        continue
                    self._trackers_by_root[run_root] = tracker
                used_roots.add(run_root)
                refused = self._without_a_picture(run_root)
                if refused is not None:
                    # No picture, no binding. Falling back to the linked view
                    # here would be the silent straddle this migration ends;
                    # the run stays governed (and excluded from inference)
                    # while the reason is reported and retried.
                    errors[run_root] = refused
                    continue
                bindings.append(
                    LiveBinding(
                        tracker=tracker,
                        dataset_number=dataset.number,
                        dataset_root=dataset.root,
                    )
                )
            self._trackers_by_root = {
                root: tracker
                for root, tracker in self._trackers_by_root.items()
                if root in used_roots
            }
            self._pictures = {
                root: store
                for root, store in self._pictures.items()
                if root in used_roots
            }
            self._picture_refused = {
                root: held
                for root, held in self._picture_refused.items()
                if root in used_roots
            }
            self._bindings = tuple(bindings)
            self._dataset_numbers = frozenset(governed)
            self._errors = errors
            return self._bindings, self._dataset_numbers

    def _without_a_picture(self, run_root: Path) -> str | None:
        """Why this run has no served picture right now, or ``None`` once it has.

        The declaration is synchronous and happens under the registry lock on
        the binding's first creation -- the operator asked for the run, and
        seconds to minutes of declaring is the honest price stated by the
        migration decision. A failure is remembered briefly and retried, so a
        refusal never re-derives the run on every config poll and a transient
        failure never outlives its cause by more than the pause.
        """
        if run_root in self._pictures:
            return None
        stumbled = self._picture_refused.get(run_root)
        if stumbled is not None:
            if time.monotonic() - stumbled[0] < _DECLARE_RETRY_S:
                return stumbled[1]
            del self._picture_refused[run_root]
        try:
            made = the_live_picture_declared(run_root)
        except Exception as why:  # noqa: BLE001 - reported and retried, never hidden
            self._picture_refused[run_root] = (time.monotonic(), str(why))
            return str(why)
        self._pictures[run_root] = made
        return None

    def bindings(self) -> tuple[LiveBinding, ...]:
        return self.refresh()[0]

    def dataset_numbers(self) -> frozenset[int]:
        return self.refresh()[1]

    def trackers(self) -> tuple[LiveStateTracker, ...]:
        bindings = self.bindings()
        return tuple(dict.fromkeys(binding.tracker for binding in bindings))

    @property
    def errors(self) -> dict[Path, str]:
        with self._lock:
            return dict(self._errors)


def capture_live_state(
    bindings: tuple[LiveBinding, ...],
) -> tuple[dict, dict[int, LiveStateSnapshot]]:
    """Observe and pin one immutable state/scene pair for every binding."""
    snapshots: dict[int, LiveStateSnapshot] = {}
    by_tracker: dict[LiveStateTracker, LiveStateSnapshot] = {}
    for binding in bindings:
        snapshot = by_tracker.get(binding.tracker)
        if snapshot is None:
            binding.tracker.observe()
            snapshot = by_tracker[binding.tracker] = binding.tracker.snapshot()
        snapshots[binding.dataset_number] = snapshot
    return live_state_document(bindings, snapshots=snapshots), snapshots


def live_state_document(
    bindings: tuple[LiveBinding, ...],
    *,
    snapshots: dict[int, LiveStateSnapshot] | None = None,
) -> dict:
    """Current authoritative state for all open manifest-driven runs."""
    if snapshots is None:
        snapshots = {}
        by_tracker: dict[LiveStateTracker, LiveStateSnapshot] = {}
        for binding in bindings:
            snapshot = by_tracker.get(binding.tracker)
            if snapshot is None:
                binding.tracker.observe()
                snapshot = by_tracker[binding.tracker] = binding.tracker.snapshot()
            snapshots[binding.dataset_number] = snapshot
    return {
        "schema": LIVE_STATE_SET_SCHEMA,
        "runs": [
            binding.state_json(snapshots[binding.dataset_number])
            for binding in bindings
        ],
    }


def the_runs_channels(run_root: Path) -> list[dict]:
    """What this run says about its colours: their names, tints and windows.

    A run settles all of that when its profile is sealed, before the first
    position is imaged, and writes the same description into every position
    it saves. The panel reads it from the profile rather than from a store,
    for two reasons. It is there from the run's first moment, before any
    picture exists to read. And the picture built over a run of one colour
    carries no colour axis at all -- there being nothing to tell apart -- so
    a reader that went looking for the description there found nothing, and
    the run's one channel arrived on screen with no tint and no brightness
    window, which is to say invisible (measured 2026-08-22).
    """
    from zmart_live.gateway import _LiveRun

    profile = _LiveRun(run_root)._geometry()[1]
    return described_channels(
        the_channels_described(profile.channels, profile.dtype),
        len(profile.channels),
    )


def _display_for(described: list[dict], store: Path, channel_index: int,
                 chosen_window) -> dict:
    channel = described[channel_index] if channel_index < len(described) else {}
    window = (
        {"low": float(chosen_window[0]), "high": float(chosen_window[1])}
        if chosen_window is not None
        else channel.get("window")
    )
    return {
        "color": list(channel["color"]) if channel.get("color") else None,
        "window": window,
        "volumeWindow": window,
        # A virtual view owns no pixels of its own, but the measurement knows
        # where the real ones live -- it follows the view to a member of the
        # run's data collection (see contrast._the_members_behind). The
        # run-provided display window above stays authoritative either way;
        # the histogram is what the panel draws beside it and what the Auto
        # button offers as an alternative.
        "histogram": intensity_histogram(store, channel=channel_index),
    }


def _the_url_served_for(source) -> str:
    """The run-relative store a compiled source is actually served from.

    The scene compiles the linked view, but the live source the frontend draws
    is the governed baked picture -- the registry refused the binding outright
    if that picture could not be declared, so by the time a row is built the
    substitution is unconditional. Everything else about the source -- its
    identity, role, revision, transform -- stays the compiler's.
    """
    return LIVE_PICTURE if source.role == "linked" else source.url


def live_rows(
    binding: LiveBinding,
    *,
    chosen_window=None,
    group: str | None = None,
    snapshot: LiveStateSnapshot | None = None,
) -> list[dict]:
    """Rows for one compiled scene, bounded by views and channels.

    The row's addresses name the governed picture (see
    :func:`_the_url_served_for`). Its colours and brightness window come from
    the run's own sealed description (see :func:`the_runs_channels`), and the
    histogram beside them is measured from the picture actually served.
    """
    snapshot = snapshot or binding.tracker.snapshot()
    scene = snapshot.scene
    if scene is None:
        return []
    frontend_sources = {
        source.source_id: source for source in snapshot.state.sources
    }
    compiled_sources = {source.source_id: source for source in scene.sources}
    described = the_runs_channels(binding.run_root)
    rows = []
    for layer in scene.layers:
        source_states = [frontend_sources[source_id] for source_id in layer.source_ids]
        sources = [compiled_sources[source_id] for source_id in layer.source_ids]
        urls = [binding.source_url(_the_url_served_for(source)) for source in sources]
        first_store = binding._source_store(_the_url_served_for(sources[0]))
        display = _display_for(described, first_store, layer.channel_index,
                               chosen_window)
        available = [
            {"start": start, "stop": stop}
            for start, stop in source_states[0].committed_time_ranges
        ]
        # Keep the legacy `frames` field useful without allowing a gap to look
        # like a transition from "no image" to "first image". New frontends use
        # committedTimeRanges as the authority. A gapped manifest therefore gets
        # a zero legacy count, which is still an honest contiguous prefix and is
        # non-null so the old first-image cache heuristic cannot fire when the gap
        # is later filled. The authoritative half-open ranges remain unchanged.
        contiguous_frames = (
            available[0]["stop"]
            if len(available) == 1 and available[0]["start"] == 0
            else 0
        )
        rows.append(
            {
                "name": layer.name,
                "group": binding.group if group is None else group,
                "kind": layer.kind,
                "channelIndex": layer.channel_index,
                "localPosition": [layer.channel_index],
                "sources": urls,
                "sourceIds": [
                    f"{binding.dataset_number}/{snapshot.state.run_id}/{source.source_id}"
                    for source in source_states
                ],
                "sourceRevisions": [source.revision for source in source_states],
                "committedTimeRanges": available,
                "frames": contiguous_frames,
                "liveRunId": snapshot.state.run_id,
                **display,
            }
        )
    return rows

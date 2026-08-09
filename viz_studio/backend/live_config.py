"""Adapt manifest-driven aggregate scenes to the studio's frontend vocabulary."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from stores import channels, zarr_scheme

from zmart_live.gateway import live_run_holding
from zmart_live.live_state import LiveStateSnapshot, LiveStateTracker
from zmart_live.model import ZmartLiveError

LIVE_STATE_SET_SCHEMA = "zmart-live-frontend-state-set/1"


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
        answer = (snapshot or self.tracker.snapshot()).to_json()
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
            self._bindings = tuple(bindings)
            self._dataset_numbers = frozenset(governed)
            self._errors = errors
            return self._bindings, self._dataset_numbers

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


def _display_for(store: Path, channel_index: int, chosen_window) -> dict:
    described = channels(store)
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
        # A virtual view owns no pixels to sample directly.  Its run-provided
        # display window is authoritative; an invented histogram would be worse
        # than showing none.
        "histogram": None,
    }


def live_rows(
    binding: LiveBinding,
    *,
    chosen_window=None,
    group: str | None = None,
    snapshot: LiveStateSnapshot | None = None,
) -> list[dict]:
    """Rows for one compiled scene, bounded by views and channels."""
    snapshot = snapshot or binding.tracker.snapshot()
    scene = snapshot.scene
    if scene is None:
        return []
    frontend_sources = {
        source.source_id: source for source in snapshot.state.sources
    }
    compiled_sources = {source.source_id: source for source in scene.sources}
    rows = []
    for layer in scene.layers:
        source_states = [frontend_sources[source_id] for source_id in layer.source_ids]
        sources = [compiled_sources[source_id] for source_id in layer.source_ids]
        urls = [binding.source_url(source.url) for source in sources]
        first_store = binding._source_store(sources[0].url)
        display = _display_for(first_store, layer.channel_index, chosen_window)
        available = [
            {"start": start, "stop": stop}
            for start, stop in source_states[0].committed_time_ranges
        ]
        contiguous_frames = (
            available[0]["stop"]
            if len(available) == 1 and available[0]["start"] == 0
            else None
        )
        local_position = [layer.channel_index]
        if sources[0].local_dimension is not None:
            local_position.insert(0, int(layer.local_position.get(sources[0].local_dimension, 0)))
        rows.append(
            {
                "name": layer.name,
                "group": binding.group if group is None else group,
                "kind": layer.kind,
                "channelIndex": layer.channel_index,
                "localPosition": local_position,
                "sources": urls,
                "sourceIds": [
                    f"{binding.dataset_number}/{snapshot.state.run_id}/{source.source_id}"
                    for source in source_states
                ],
                "sourceRevisions": [source.revision for source in source_states],
                "committedTimeRanges": available,
                # Retained for old frontends.  New ones use the ranges above and
                # therefore do not turn a gap into published time. It is omitted
                # as a high-water answer whenever publication is not contiguous.
                "frames": contiguous_frames,
                "liveRunId": snapshot.state.run_id,
                **display,
            }
        )
    return rows

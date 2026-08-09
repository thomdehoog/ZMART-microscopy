"""Bounded, manifest-derived state for an already-open live viewer.

The acquisition writer publishes large images and tiny truth in two different
places.  This module watches only the tiny truth.  It never scans chunks, view
folders or timestamps to decide what is visible: a complete, strictly validated
``committed.json`` snapshot and the history it covers are the sole inputs.

The result is deliberately small.  A five-position run and a fifty-thousand-
position run both describe the same two aggregate overview sources.  Per-position
history stays behind the server; the browser receives source revisions and compact
half-open ranges of committed timepoints.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .identity import load_a_layout_revision, load_the_profile
from .manifest import CommittedState, RunManifest
from .model import CommitEvent, ZmartLiveError
from .scene import NeuroglancerScene, build_the_scene, compile_for_neuroglancer

__all__ = [
    "FRONTEND_STATE_SCHEMA",
    "FrontendLiveSource",
    "FrontendLiveState",
    "LiveStateSnapshot",
    "LiveStateTracker",
    "compact_time_ranges",
]

FRONTEND_STATE_SCHEMA = "zmart-live-frontend-state/1"


def compact_time_ranges(moments: set[int] | frozenset[int]) -> tuple[tuple[int, int], ...]:
    """Turn committed moments into settled half-open ranges.

    A high-water number would make a gap look published.  Ranges preserve gaps
    explicitly while remaining compact for the normal contiguous case.
    """
    ordered = sorted(set(moments))
    if not ordered:
        return ()
    ranges: list[tuple[int, int]] = []
    start = previous = ordered[0]
    for moment in ordered[1:]:
        if moment == previous + 1:
            previous = moment
            continue
        ranges.append((start, previous + 1))
        start = previous = moment
    ranges.append((start, previous + 1))
    return tuple(ranges)


@dataclass(frozen=True)
class FrontendLiveSource:
    """One stable aggregate source and the committed state it may expose."""

    source_id: str
    role: str
    url: str
    revision: int
    layout_revision: int
    committed_time_ranges: tuple[tuple[int, int], ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "role": self.role,
            "url": self.url,
            "revision": self.revision,
            "layout_revision": self.layout_revision,
            "committed_time_ranges": [
                {"start": start, "stop": stop}
                for start, stop in self.committed_time_ranges
            ],
        }


@dataclass(frozen=True)
class FrontendLiveState:
    """The last complete state a browser is allowed to act on."""

    run_id: str
    revision: int
    layout_revision: int
    sources: tuple[FrontendLiveSource, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": FRONTEND_STATE_SCHEMA,
            "run_id": self.run_id,
            "revision": self.revision,
            "layout_revision": self.layout_revision,
            "sources": [source.to_json() for source in self.sources],
        }


@dataclass(frozen=True)
class LiveStateSnapshot:
    """One internally consistent, immutable tracker observation."""

    state: FrontendLiveState
    scene: NeuroglancerScene | None
    error: str | None = None

    @property
    def freshness(self) -> str:
        return "current" if self.error is None else "degraded"

    def to_json(self) -> dict[str, Any]:
        answer = self.state.to_json()
        answer["freshness"] = self.freshness
        if self.error is not None:
            answer["error"] = self.error
        return answer


class LiveStateTracker:
    """Follow one run's marker and retain its last valid bounded scene.

    ``observe`` is cheap while idle: one ``stat`` of ``committed.json``.  Only a
    changed fingerprint causes the marker and appended history tail to be read.
    Invalid, foreign or regressing state records an error but leaves every last
    good field untouched.
    """

    def __init__(self, run_root: str | Path) -> None:
        self.run_root = Path(run_root).resolve()
        self.manifest = RunManifest.open(self.run_root)
        self._lock = threading.RLock()
        self._fingerprint: tuple[int, int, int, int] | None = None
        self._committed: CommittedState | None = None
        self._state: FrontendLiveState | None = None
        self._scene: NeuroglancerScene | None = None
        self._error: str | None = None
        self._position_revisions: dict[str, int] = {}
        self._layout_revision = 0
        self._moments: dict[tuple[str, str], set[int]] = {}
        self._events: list[CommitEvent] = []
        self.fingerprint_checks = 0
        self.history_events_read = 0
        self.observe(force=True)
        if self._state is None:
            raise ZmartLiveError(
                f"The live frontend state for {self.run_root} could not be "
                f"established safely: {self._error or 'unknown damage'}."
            )

    @property
    def state(self) -> FrontendLiveState:
        """The last state that passed every check."""
        with self._lock:
            assert self._state is not None
            return self._state

    @property
    def scene(self) -> NeuroglancerScene | None:
        """The compiled aggregate scene belonging to :attr:`state`."""
        with self._lock:
            return self._scene

    @property
    def committed(self) -> CommittedState:
        """The strict manifest snapshot belonging to :attr:`state`."""
        with self._lock:
            assert self._committed is not None
            return self._committed

    @property
    def error(self) -> str | None:
        """Why the newest marker was rejected, or ``None`` when current."""
        with self._lock:
            return self._error

    @property
    def revision(self) -> int:
        return self.state.revision

    @property
    def freshness(self) -> str:
        return "current" if self.error is None else "degraded"

    def snapshot(self) -> LiveStateSnapshot:
        """Return state, scene and failure status from one lock acquisition."""
        with self._lock:
            assert self._state is not None
            return LiveStateSnapshot(self._state, self._scene, self._error)

    def to_json(self) -> dict[str, Any]:
        """The last good state plus an explicit freshness report."""
        return self.snapshot().to_json()

    def version_token(self) -> str:
        """A compact conditional-request token for the state now served."""
        return json.dumps(self.to_json(), sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _moment_of(event: CommitEvent) -> int:
        return 0 if event.timepoint is None else event.timepoint

    def _compile(
        self,
        committed: CommittedState,
        moments: dict[tuple[str, str], set[int]],
        events: list[CommitEvent],
    ) -> tuple[FrontendLiveState, NeuroglancerScene | None]:
        if committed.revision == 0:
            return (
                FrontendLiveState(
                    run_id=committed.run_id,
                    revision=0,
                    layout_revision=0,
                ),
                None,
            )

        layout = load_a_layout_revision(self.run_root, committed.layout_revision)
        if layout.run_id != committed.run_id:
            raise ZmartLiveError(
                f"Layout revision {layout.revision} belongs to run {layout.run_id!r}, "
                f"not the published run {committed.run_id!r}."
            )
        profile = load_the_profile(self.run_root, layout.profile_id)
        channels = tuple(profile.channels)
        if not channels:
            matching = [
                event
                for event in events
                if event.acquisition_profile_id == profile.profile_id
            ]
            channels = matching[-1].channels if matching else ()
        scene = build_the_scene(profile, layout, channels=channels)
        compiled = compile_for_neuroglancer(scene, committed)
        available = compact_time_ranges(
            moments.get((layout.acquisition_type, layout.profile_id), set())
        )
        sources = tuple(
            FrontendLiveSource(
                source_id=source.source_id,
                role=source.role,
                url=source.url,
                revision=source.revision,
                layout_revision=source.layout_revision,
                committed_time_ranges=available,
            )
            for source in compiled.sources
        )
        return (
            FrontendLiveState(
                run_id=committed.run_id,
                revision=committed.revision,
                layout_revision=committed.layout_revision,
                sources=sources,
            ),
            compiled,
        )

    def _accept(self, committed: CommittedState) -> bool:
        previous = self._committed
        previous_revision = 0 if previous is None else previous.revision
        if previous is not None and committed.run_id != previous.run_id:
            raise ZmartLiveError(
                f"The publication marker changed from run {previous.run_id!r} to "
                f"foreign run {committed.run_id!r}."
            )
        if committed.revision < previous_revision:
            raise ZmartLiveError(
                f"The publication marker regressed from revision {previous_revision} "
                f"to {committed.revision}."
            )
        if committed.revision == previous_revision and previous is not None:
            if (
                dict(committed.by_store) != dict(previous.by_store)
                or committed.layout_revision != previous.layout_revision
            ):
                raise ZmartLiveError(
                    "The publication marker changed its per-position or layout "
                    "state without advancing the global revision."
                )
            return False

        new_events = self.manifest.events_through(
            committed,
            after=previous_revision,
        )
        expected = list(range(previous_revision + 1, committed.revision + 1))
        if [event.revision for event in new_events] != expected:
            raise ZmartLiveError(
                f"The publication marker advanced to {committed.revision}, but its "
                "covered history tail is incomplete."
            )

        position_revisions = dict(self._position_revisions)
        layout_revision = self._layout_revision
        moments = {key: set(values) for key, values in self._moments.items()}
        for event in new_events:
            if not event.ready:
                raise ZmartLiveError(
                    f"Publication history revision {event.revision} does not record "
                    "all prerequisites as validated."
                )
            if event.run_id != committed.run_id:
                raise ZmartLiveError(
                    f"Publication history revision {event.revision} belongs to "
                    f"foreign run {event.run_id!r}."
                )
            position_revisions[event.position_id] = event.revision
            layout_revision = max(layout_revision, event.scene_layout_revision)
            key = (event.acquisition_type, event.acquisition_profile_id)
            moments.setdefault(key, set()).add(self._moment_of(event))

        if position_revisions != dict(committed.by_store):
            raise ZmartLiveError(
                "The publication marker's per-position revisions do not match "
                "the durable events it claims to publish."
            )
        if layout_revision != committed.layout_revision:
            raise ZmartLiveError(
                f"The publication marker claims layout revision "
                f"{committed.layout_revision}, while its events reach "
                f"{layout_revision}."
            )

        # Include earlier accepted events when locating channel identity for a
        # profile whose sealed record predates the channels field.  Keep that
        # prefix here so a publication reads the manifest's appended tail once.
        all_events = [*self._events, *new_events]
        frontend, scene = self._compile(committed, moments, all_events)

        self._position_revisions = position_revisions
        self._layout_revision = layout_revision
        self._moments = moments
        self._events = all_events
        self._committed = committed
        self._state = frontend
        self._scene = scene
        self.history_events_read += len(new_events)
        return committed.revision > previous_revision

    def observe(self, *, force: bool = False) -> bool:
        """Check the marker, returning whether a higher valid revision won.

        Damage is reported through :attr:`error`; it is not raised after startup
        and never mutates the last good state.
        """
        with self._lock:
            self.fingerprint_checks += 1
            try:
                mark = self.manifest.fingerprint()
            except OSError as why:
                self._error = (
                    f"The publication marker for {self.run_root} cannot currently "
                    f"be inspected: {why}"
                )
                return False
            # A transient read failure may leave the marker fingerprint exactly
            # as it was once the share recovers. Retry while degraded; the cheap
            # one-stat idle path resumes immediately after a strict read succeeds.
            if not force and mark == self._fingerprint and self._error is None:
                return False
            self._fingerprint = mark
            try:
                committed = self.manifest.committed_strict()
                advanced = self._accept(committed)
            except (OSError, ValueError, TypeError, KeyError, ZmartLiveError) as why:
                self._error = str(why)
                return False
            self._error = None
            return advanced

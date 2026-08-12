"""The record that decides what a viewer is allowed to see.

While a microscope is running, files appear on disk continuously — half a
position, three of five colours, a zoomed-out copy that is still being built.
None of that should reach the screen. A picture assembled from a position that
is only partly written is not a slow picture; it is a wrong one, and it looks
exactly like a right one.

So this package keeps a separate record of what is *finished*, and the viewer
reads that record rather than looking at the folder. The rule is short:

    **Data becomes visible only after the complete position, or the complete
    moment, has been committed.**

Files existing means nothing. This record means everything.

How the record is arranged
--------------------------

Two files sit beside the run.

``events.jsonl`` is the active history: one line per publication and append-only
during normal operation. Recovery is the sole exception; it preserves a crash
tail in ``interrupted.json`` before removing those never-published lines. The
history says what was published, when, which storage plan and which layout it
used, and that every prerequisite was checked first.

``committed.json`` is the truth: a single small file naming the highest revision
that is completely safe to read. It is replaced by writing a new one alongside
and renaming it over the old, which the operating system does in one step — so a
reader either sees the whole previous version or the whole new one, and never a
half-written mixture.

Why both? Because a line being present in the history is not proof it was
finished; a program can die halfway through writing one. The rename is the
moment of publication, and nothing before it counts.

The counter is the truth; the announcement is a hurry-up
--------------------------------------------------------

Every publication moves a number, and that number only ever goes up. A viewer
that has drawn revision 7 and sees revision 9 knows it has fallen behind, and
knows it without having to have been listening at the right moment.

The backend may also *tell* the viewer that something changed, over whatever live
connection is already open. That message is a convenience and not the record. If
it arrives, the viewer refreshes at once; if it is lost, the next question the
viewer asks reveals the higher number anyway. A lost message therefore delays a
refresh but can never leave a viewer permanently showing something stale.

Reading it cheaply
------------------

The viewer asks "has anything changed?" many times a second, so answering must
not mean reading the history. :meth:`RunManifest.fingerprint` answers from a
single glance at the small file — no contents read at all — and only when that
glance changes is anything parsed. Even then only the new lines are read, from
where the last read stopped.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from .model import CommitEvent, FrozenMap, ZmartLiveError

__all__ = [
    "CommittedState",
    "PublicationRefused",
    "RunManifest",
    "now_in_words",
]

#: The folder, beside the run's images, that holds our own bookkeeping. It is
#: kept outside the images themselves so that nothing we invented ever turns up
#: inside a picture somebody opens in another program.
BOOKKEEPING = "zmart-live"

_HISTORY = "events.jsonl"
_TRUTH = "committed.json"
_WRITER_LOCK = "publication.lock"
_SCHEMA = "zmart-live-manifest/1"


def now_in_words() -> str:
    """The present moment, written so that a person can read it.

    Times are recorded in UTC with the offset spelled out, because a run started
    in one timezone is frequently analysed in another, and a bare local time
    leaves no way to tell which was meant.
    """
    return datetime.now(UTC).isoformat(timespec="seconds")


class PublicationRefused(ZmartLiveError):
    """A commit was offered before everything it depends on was ready.

    This is deliberately a refusal rather than a warning. The one promise this
    record makes is that anything visible is complete, and a commit written
    before its pyramids, its pointers or its shared zoomed-out pieces had been
    checked would quietly break that promise for every reader afterwards.
    """


@dataclass(frozen=True)
class CommittedState:
    """What is safe to read, as of the last publication.

    ``revision`` is the run-wide counter. ``by_store`` gives the same thing per
    position, which is what lets a viewer refresh only the picture that actually
    changed instead of everything it has open — a distinction that has been
    measured here as the difference between a handful of requests and several
    thousand.
    """

    revision: int = 0
    run_id: str = ""
    by_store: Mapping[str, int] = field(default_factory=FrozenMap)
    layout_revision: int = 0
    updated_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "by_store",
            FrozenMap({str(position): int(number) for position, number in self.by_store.items()}),
        )
        if self.revision < 0 or self.layout_revision < 0:
            raise ZmartLiveError(
                "Publication and layout revisions cannot be negative; got "
                f"{self.revision} and {self.layout_revision}."
            )
        if self.revision and not self.run_id:
            raise ZmartLiveError("Published state has to name the run it belongs to.")
        impossible = {
            position: number
            for position, number in self.by_store.items()
            if not position or number < 0 or number > self.revision
        }
        if impossible:
            raise ZmartLiveError(
                "A per-position counter is empty, negative, or ahead of the whole "
                f"run counter: {impossible}."
            )

    def to_json(self) -> dict:
        """A plain dictionary, for the small file that is renamed into place."""
        return {
            "schema": _SCHEMA,
            "revision": self.revision,
            "run_id": self.run_id,
            "by_store": dict(sorted(self.by_store.items())),
            "layout_revision": self.layout_revision,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_json(cls, value: dict) -> CommittedState:
        """Read back what :meth:`to_json` wrote, refusing a misleading record.

        This is a small file, but it is the most consequential one in the run:
        accepting a plausible-looking record from another schema or one whose
        per-position counters have moved past the run counter would make the
        viewer trust an answer nobody actually published.
        """
        if not isinstance(value, dict) or value.get("schema") != _SCHEMA:
            raise ZmartLiveError(
                f"This publication record is not {_SCHEMA!r}. It may belong to a "
                "different version of ZMART, so its meaning cannot be guessed safely."
            )
        revision = int(value["revision"])
        layout_revision = int(value.get("layout_revision", 0))
        run_id = value["run_id"]
        stores = value.get("by_store", {})
        if not isinstance(run_id, str) or not run_id:
            raise ZmartLiveError("A publication record has to name the run it belongs to.")
        if revision < 0 or layout_revision < 0:
            raise ZmartLiveError(
                "Publication and layout revisions cannot be negative; "
                f"got {revision} and {layout_revision}."
            )
        if not isinstance(stores, dict):
            raise ZmartLiveError("The per-position publication counters are not a table.")
        by_store = {str(key): int(number) for key, number in stores.items()}
        impossible = {
            key: number
            for key, number in by_store.items()
            if not key or number < 0 or number > revision
        }
        if impossible:
            raise ZmartLiveError(
                "A per-position counter is empty, negative, or ahead of the whole "
                f"run counter: {impossible}."
            )
        return cls(
            revision=revision,
            run_id=run_id,
            by_store=by_store,
            layout_revision=layout_revision,
            updated_at=str(value.get("updated_at", "")),
        )


def _push_directory_to_disk(folder: Path) -> None:
    """Make a renamed directory entry durable where the platform permits it.

    Flushing the temporary file protects its contents. On POSIX filesystems the
    containing directory must be flushed as well, or a power cut can forget the
    rename even though the file itself was safe. Windows does not offer Python an
    equivalent operation on a directory handle; ``os.replace`` is still atomic
    there, but power-loss durability remains a property to measure on the target
    filesystem rather than a promise made by this helper.
    """
    if os.name == "nt":  # pragma: no cover - exercised on the Windows target
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(folder, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_and_replace(destination: Path, text: str) -> None:
    """Put new contents in place in one indivisible step.

    Writing straight over a file leaves a window in which a reader sees half of
    the old contents and half of the new. Instead the new contents are written
    beside it under a temporary name, pushed all the way to the disk, and then
    renamed over the top. Renaming is the one filesystem operation that is
    genuinely all-or-nothing, on Windows as well as elsewhere.

    Pushing to the disk first matters more than it looks. Without it the
    operating system may hold the contents in memory while the rename has already
    happened, so a power cut could leave a record that points confidently at data
    which never reached the platter.

    The rename itself is made with a short patience for a reader's hold. These
    small files are replaced on every commit and read constantly by the live
    viewer, and on Windows the reader's open handle makes the replacement fail
    as ``Access is denied`` on ground that is free a moment later — a governed
    run watched live died of exactly this. The pixel path was cured first, in
    :func:`zmart_storage.canvas.written_despite_brief_holds`, and this is the
    same cure in the same place for the metadata.
    """
    from zmart_storage.canvas import written_despite_brief_holds

    destination.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        dir=destination.parent,
        prefix=destination.name + ".",
        suffix=".tmp",
        delete=False,
        encoding="utf-8",
    )
    try:
        with handle as writing:
            writing.write(text)
            writing.flush()
            os.fsync(writing.fileno())
        written_despite_brief_holds(lambda: os.replace(handle.name, destination))
        _push_directory_to_disk(destination.parent)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise


@contextmanager
def _one_writer_at_a_time(path: Path) -> Iterator[None]:
    """Reserve one run's publication record for a single writer.

    Reading remains lock-free. Writers fail immediately when another process is
    publishing, because waiting behind a hung microscope process is less useful
    than a clear refusal that the caller can retry. The operating system releases
    this mark if a process dies, so a crash does not leave a stale lock to remove.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    first_creation = not path.exists()
    handle: BinaryIO = path.open("a+b", buffering=0)
    locked = False
    try:
        if handle.tell() == 0:
            handle.write(b"\0")
            os.fsync(handle.fileno())
            if first_creation:
                _push_directory_to_disk(path.parent)
        handle.seek(0)
        try:
            if os.name == "nt":  # pragma: no cover - exercised on the Windows target
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as why:
            raise PublicationRefused(
                f"Another writer is publishing this run through {path}. Only one "
                "writer may change the publication record at a time, or one can "
                "silently overwrite the other's position counters. Retry after "
                "the other publication finishes."
            ) from why
        locked = True
        yield
    finally:
        if locked:
            if os.name == "nt":  # pragma: no cover - exercised on the Windows target
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


class RunManifest:
    """The bookkeeping for one run: what has been published, and how far along.

    Open one where the run's images live. It creates its own folder beside them
    and keeps two files there, described at the top of this module.

    A writer calls :meth:`publish` when a position or a moment is genuinely
    finished. A viewer calls :meth:`fingerprint` constantly and
    :meth:`committed` only when the fingerprint has moved.
    """

    def __init__(self, folder: Path | str, run_id: str = "") -> None:
        self.folder = Path(folder)
        self.bookkeeping = self.folder / BOOKKEEPING
        self.history = self.bookkeeping / _HISTORY
        self.truth = self.bookkeeping / _TRUTH
        self.writer_lock = self.bookkeeping / _WRITER_LOCK
        self.run_id = run_id
        self._read_to = 0  # bytes of complete history already read
        self._history_lines = 0
        self._history_identity: tuple[int, int] | None = None
        self._history_mtime_ns: int | None = None
        self._events_cache: list[CommitEvent] = []
        self._event_ends: list[int] = []
        self._partial_history = b""

    # -- creating and opening ------------------------------------------------

    @classmethod
    def start(cls, folder: Path | str, run_id: str) -> RunManifest:
        """Begin bookkeeping for a new run, or pick up one already under way.

        Safe to call again on a run that already exists: an interrupted writer
        that comes back should carry on from where the record left off rather
        than start a fresh one, because everything already published is still
        published and readers may be relying on it.
        """
        manifest = cls(folder, run_id)
        manifest.bookkeeping.mkdir(parents=True, exist_ok=True)
        with _one_writer_at_a_time(manifest.writer_lock):
            if not manifest.history.exists():
                with manifest.history.open("xb") as history:
                    history.flush()
                    os.fsync(history.fileno())
                _push_directory_to_disk(manifest.bookkeeping)
            if manifest.truth.exists():
                state = manifest._committed_for_writing(check_identity=False)
                if state.run_id != run_id:
                    raise PublicationRefused(
                        f"This folder already belongs to run {state.run_id!r}, but it "
                        f"was opened as {run_id!r}. Reusing it would mix two runs in "
                        "one publication history. Give the new run its own folder."
                    )
            else:
                if manifest.history.stat().st_size:
                    raise PublicationRefused(
                        f"{manifest.history} already contains publication history, "
                        f"but {manifest.truth} is missing. Starting at revision zero "
                        "would hide or overwrite an earlier run; restore the small "
                        "committed file before continuing."
                    )
                _write_and_replace(
                    manifest.truth,
                    json.dumps(
                        CommittedState(
                            revision=0,
                            run_id=run_id,
                            updated_at=now_in_words(),
                        ).to_json(),
                        indent=2,
                    ),
                )
        return manifest

    @classmethod
    def open(cls, folder: Path | str) -> RunManifest:
        """Read the bookkeeping for a run that already exists."""
        manifest = cls(folder)
        if not manifest.truth.exists():
            raise ZmartLiveError(
                f"There is no publication record under {manifest.bookkeeping}. "
                f"Either this folder does not hold a run written by this version "
                f"of ZMART, or the run was never started properly. Nothing in it "
                f"can be shown safely until there is a record saying what is "
                f"finished."
            )
        try:
            state = CommittedState.from_json(json.loads(manifest.truth.read_text(encoding="utf-8")))
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            AttributeError,
            KeyError,
            TypeError,
            ValueError,
            ZmartLiveError,
        ) as why:
            raise ZmartLiveError(
                f"The publication record at {manifest.truth} is damaged or belongs "
                "to another schema. The run cannot be opened safely until that "
                "small file is restored."
            ) from why
        manifest.run_id = state.run_id
        return manifest

    # -- what a reader asks --------------------------------------------------

    def fingerprint(self) -> tuple[int, int, int, int]:
        """A cheap glance that changes whenever something has been published.

        Deliberately does not open or read the file. This is asked several times
        a second while a run is going, and reading a growing history that often
        would put real work on the path of every frame the viewer draws.
        """
        try:
            stamp = self.truth.stat()
        except FileNotFoundError:
            return (0, 0, 0, 0)
        return (
            stamp.st_mtime_ns,
            stamp.st_ctime_ns,
            stamp.st_size,
            getattr(stamp, "st_ino", 0),
        )

    def committed(self) -> CommittedState:
        """What is safe to read right now.

        Falls back to "nothing published yet" if the small file cannot be read as
        sense. That is the safe direction to fail in: showing nothing is a
        disappointment, whereas showing something half-written is a wrong answer
        that nobody can spot.
        """
        try:
            state = CommittedState.from_json(json.loads(self.truth.read_text(encoding="utf-8")))
            if self.run_id and state.run_id != self.run_id:
                raise ZmartLiveError(
                    f"The publication record changed from run {self.run_id!r} to {state.run_id!r}."
                )
            return state
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            AttributeError,
            KeyError,
            TypeError,
            ValueError,
            ZmartLiveError,
        ):
            return CommittedState(run_id=self.run_id)

    def committed_strict(self) -> CommittedState:
        """Read committed truth without turning damage into revision zero.

        :meth:`committed` deliberately fails towards an empty screen.  That is
        the right answer for a pixel request, but it is not enough information
        for a long-lived observer: an observer that had already accepted
        revision 12 must be able to distinguish a genuinely empty run from a
        temporarily unreadable marker, or it could report a false regression.

        This method makes that distinction explicit.  It returns the same
        validated state as :meth:`committed`, and raises :class:`ZmartLiveError`
        for damaged, foreign or unreadable truth.  It never repairs or rewrites
        anything.
        """
        try:
            state = CommittedState.from_json(
                json.loads(self.truth.read_text(encoding="utf-8"))
            )
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            AttributeError,
            KeyError,
            TypeError,
            ValueError,
            ZmartLiveError,
        ) as why:
            raise ZmartLiveError(
                f"The publication record at {self.truth} cannot be read safely. "
                "The last valid published state must be retained until the small "
                "file is restored."
            ) from why
        if self.run_id and state.run_id != self.run_id:
            raise ZmartLiveError(
                f"This manifest was opened for run {self.run_id!r}, but its "
                f"publication record now belongs to {state.run_id!r}."
            )
        return state

    def _committed_for_writing(
        self,
        *,
        check_identity: bool = True,
    ) -> CommittedState:
        """Read the truth without the viewer's safe empty-screen fallback.

        A reader may fail towards showing nothing. A writer may not: treating a
        damaged record as revision zero and publishing over it would erase the
        only statement of what was already visible.
        """
        try:
            state = CommittedState.from_json(json.loads(self.truth.read_text(encoding="utf-8")))
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            AttributeError,
            KeyError,
            TypeError,
            ValueError,
            ZmartLiveError,
        ) as why:
            raise PublicationRefused(
                f"The publication record at {self.truth} cannot be read safely. "
                "Publishing over it could forget positions that viewers have "
                "already seen, so the writer is stopping instead."
            ) from why
        if check_identity and self.run_id and state.run_id != self.run_id:
            raise PublicationRefused(
                f"This manifest was opened for run {self.run_id!r}, but its record "
                f"belongs to {state.run_id!r}. The two runs must not be mixed."
            )
        return state

    def revision(self) -> int:
        """The run-wide counter. It only ever goes up."""
        return self.committed().revision

    def revision_of(self, position_id: str) -> int:
        """How far along one position is, or zero if it has published nothing.

        This is what lets a viewer refresh a single picture instead of every
        picture it has open.
        """
        return self.committed().by_store.get(position_id, 0)

    # -- reading the history -------------------------------------------------

    def _reset_history_reader(self) -> None:
        """Forget an old cursor after the history was replaced or shortened."""
        self._read_to = 0
        self._history_lines = 0
        self._events_cache = []
        self._event_ends = []
        self._partial_history = b""

    def _read_new_history(self) -> None:
        """Read complete lines added since the previous call, and cache them."""
        if not self.history.exists():
            self._reset_history_reader()
            self._history_identity = None
            self._history_mtime_ns = None
            return
        with self.history.open("rb") as reading:
            stamp = os.fstat(reading.fileno())
            identity = (stamp.st_dev, stamp.st_ino)
            changed_without_growing = (
                self._history_mtime_ns is not None
                and stamp.st_size == self._read_to
                and stamp.st_mtime_ns != self._history_mtime_ns
            )
            if (
                self._history_identity not in (None, identity)
                or stamp.st_size < self._read_to
                or changed_without_growing
            ):
                self._reset_history_reader()
            self._history_identity = identity
            reading.seek(self._read_to)
            unread = reading.read()

        start_at = self._read_to
        consumed = 0
        partial = b""
        complete_lines = 0
        new_events: list[CommitEvent] = []
        new_event_ends: list[int] = []
        for raw_line in unread.splitlines(keepends=True):
            complete = raw_line.endswith((b"\n", b"\r"))
            if not complete:
                partial = unread[consumed:]
                break
            line_number = self._history_lines + complete_lines + 1
            stripped = raw_line.strip()
            if stripped:
                try:
                    record = json.loads(stripped.decode("utf-8"))
                    event = CommitEvent.from_json(record)
                except (
                    UnicodeDecodeError,
                    json.JSONDecodeError,
                    AttributeError,
                    KeyError,
                    TypeError,
                    ValueError,
                    ZmartLiveError,
                ):
                    raise ZmartLiveError(
                        f"The publication history at {self.history} has a damaged "
                        f"entry on line {line_number}. The line ends normally, so "
                        "this is corruption rather than a writer caught mid-sentence."
                    ) from None
                expected = len(self._events_cache) + len(new_events) + 1
                if event.revision != expected:
                    raise ZmartLiveError(
                        f"The publication history at {self.history} jumps from "
                        f"revision {expected - 1} to {event.revision} on line "
                        f"{line_number}. Revisions must appear exactly once and in "
                        "order; accepting this history could hide a lost commit."
                    )
                if self.run_id and event.run_id != self.run_id:
                    raise ZmartLiveError(
                        f"Line {line_number} of {self.history} belongs to run "
                        f"{event.run_id!r}, not {self.run_id!r}. The histories of "
                        "two experiments cannot be combined."
                    )
                new_events.append(event)
            consumed += len(raw_line)
            if stripped:
                new_event_ends.append(start_at + consumed)
            complete_lines += 1

        self._events_cache.extend(new_events)
        self._event_ends.extend(new_event_ends)
        self._history_lines += complete_lines
        self._read_to += consumed
        self._partial_history = partial
        self._history_mtime_ns = stamp.st_mtime_ns

    def events(
        self,
        after: int = 0,
        *,
        published_only: bool = True,
    ) -> list[CommitEvent]:
        """Every publication with a revision above ``after``, oldest first.

        Only reads the part of the history it has not read before, so following a
        long run costs the same per publication whether it is the tenth or the
        ten-thousandth.

        A final line without its newline may be a writer caught in the middle and
        is left for the next call. A malformed line that *does* end normally is
        corruption, even when it is currently last, and is reported.

        By default this returns only events covered by ``committed.json``. A line
        appended just before a writer crashed is history, but it was never a
        publication and must not become a second route around the atomic commit.
        Recovery code may ask for those lines with ``published_only=False``.
        """
        self._read_new_history()
        ceiling = self.revision() if published_only else None
        return [
            event
            for event in self._events_cache
            if event.revision > after and (ceiling is None or event.revision <= ceiling)
        ]

    def events_through(
        self,
        committed: CommittedState,
        after: int = 0,
    ) -> list[CommitEvent]:
        """Published events above ``after`` through one strict state snapshot.

        Reading the marker and then calling :meth:`events` used to read the
        marker a second time through its safe-empty fallback.  A replacement
        between those two reads could pair history with a different ceiling,
        while damage could silently turn that ceiling into zero.  A backend
        watcher instead reads one strict snapshot and hands it here.

        The history cursor is still incremental.  A jump from revision 41 to 44
        reads the appended tail once and returns 42, 43 and 44 together.  A
        marker claiming history that is absent is refused rather than treated
        as an empty tail.
        """
        if self.run_id and committed.run_id != self.run_id:
            raise ZmartLiveError(
                f"This manifest was opened for run {self.run_id!r}, but the "
                f"requested publication snapshot belongs to {committed.run_id!r}."
            )
        self._read_new_history()
        if committed.revision > len(self._events_cache):
            raise ZmartLiveError(
                f"The publication marker claims revision {committed.revision}, "
                f"but the durable history reaches only {len(self._events_cache)}. "
                "The missing publications cannot be inferred from files on disk."
            )
        # Revisions are validated as a contiguous one-based sequence while they
        # enter the cache, so their list indices are the cursor.  Slicing avoids
        # walking a long accepted prefix on every new publication.
        start = max(0, after)
        return list(self._events_cache[start : committed.revision])

    def events_for(
        self,
        position_id: str,
        after: int = 0,
        *,
        published_only: bool = True,
    ) -> list[CommitEvent]:
        """The same, narrowed to one position."""
        return [
            event
            for event in self.events(after, published_only=published_only)
            if event.position_id == position_id
        ]

    # -- what a writer does --------------------------------------------------

    def publish(self, event: CommitEvent) -> CommittedState:
        """Make one finished position or moment visible, all at once.

        Everything the unit depends on must already have been checked — its
        pixels, its zoomed-out copies, the pointers the overview needs, the
        shared zoomed-out pieces it changes, and the layout saying who owns what.
        The event carries the results of those checks, and an event that does not
        claim all of them is refused.

        Returns what is now visible. Until this call returns, nothing about the
        unit is visible to anybody, however complete the files may look.

        """
        if not event.ready:
            missing = [
                name
                for name, done in (
                    ("the zoomed-out copies", event.pyramids_ready),
                    ("the overview's pointers", event.links_ready),
                    ("the linked view's description", event.view_ready),
                    ("the final check over all of it", event.validated),
                )
                if not done
            ]
            raise PublicationRefused(
                f"'{event.position_id}' cannot be published yet: "
                f"{', and '.join(missing)} {'is' if len(missing) == 1 else 'are'} "
                f"not ready. Publishing now would let a viewer draw a picture from "
                f"data that is still being written, which does not look like an "
                f"error on screen — it looks like a result."
            )

        with _one_writer_at_a_time(self.writer_lock):
            state = self._committed_for_writing()
            if event.run_id != state.run_id:
                raise PublicationRefused(
                    f"This commit belongs to run {event.run_id!r}, but this folder "
                    f"belongs to {state.run_id!r}. Publishing it would mix two "
                    "experiments in one history."
                )

            recorded = self.events(published_only=False)
            last_recorded = max((past.revision for past in recorded), default=0)
            if state.revision > last_recorded:
                raise PublicationRefused(
                    f"The small publication record claims revision {state.revision}, "
                    f"but the durable history reaches only {last_recorded}. "
                    "Publishing again would build on a commit whose identity has "
                    "been lost; restore the missing history first."
                )
            if self._partial_history:
                raise PublicationRefused(
                    f"The last line of {self.history} stops mid-sentence, which is "
                    "what a crash during history writing leaves behind. Call "
                    "recover() before publishing again; it preserves the fragment "
                    "in interrupted.json before making the history appendable."
                )
            unannounced = [past for past in recorded if past.revision > state.revision]
            if unannounced:
                raise PublicationRefused(
                    f"The history contains {len(unannounced)} complete record(s) "
                    "that were never atomically published, probably because the "
                    "writer stopped between its two disk writes. Call recover() "
                    "to preserve and quarantine that tail before retrying."
                )
            expected = max(state.revision, last_recorded) + 1
            if event.revision != expected:
                raise PublicationRefused(
                    f"This publication is numbered {event.revision}, but the next "
                    f"safe number is {expected}. The number has to keep going up "
                    "without being reused, including after an interrupted history "
                    "write. Ask next_revision() again and retry the complete unit."
                )

            already_exists = event.position_id in state.by_store
            if event.event_type == "position_committed" and already_exists:
                raise PublicationRefused(
                    f"Position {event.position_id!r} is already published. A new "
                    "moment uses 'timepoint_committed'; replacing its pixels uses "
                    "the explicit 'position_replaced' event."
                )
            if (
                event.event_type in {"timepoint_committed", "position_replaced"}
                and not already_exists
            ):
                raise PublicationRefused(
                    f"{event.event_type!r} refers to {event.position_id!r}, but that "
                    "position has never been published. Publish the position first."
                )
            # Every event kind lands on a moment — a position commit without a
            # timepoint lands on moment zero — so the duplicate check compares
            # moments rather than spellings. Replacements are the one deliberate
            # exception: superseding a moment is 'position_replaced', which is
            # allowed onto a committed moment because that is its entire job.
            if event.event_type == "timepoint_committed":
                moment = event.timepoint
                if any(
                    past.position_id == event.position_id
                    and (0 if past.timepoint is None else past.timepoint) == moment
                    for past in recorded
                ):
                    raise PublicationRefused(
                        f"Timepoint {moment} of {event.position_id!r} already "
                        "has a commit. Reusing it would give one moment two "
                        "histories; replacing its pixels uses the explicit "
                        "'position_replaced' event."
                    )

            line = json.dumps(event.to_json(), sort_keys=True)

            # First the history, pushed all the way to the disk. A line here is not
            # yet a publication; it becomes one only when the small file below is
            # renamed into place.
            with self.history.open("a", encoding="utf-8") as writing:
                writing.write(line + "\n")
                writing.flush()
                os.fsync(writing.fileno())
            history_stamp = self.history.stat()
            self._events_cache.append(event)
            self._event_ends.append(history_stamp.st_size)
            self._read_to = history_stamp.st_size
            self._history_lines += 1
            self._history_identity = (history_stamp.st_dev, history_stamp.st_ino)
            self._history_mtime_ns = history_stamp.st_mtime_ns

            moved_on = dict(state.by_store)
            moved_on[event.position_id] = event.revision
            published = CommittedState(
                revision=event.revision,
                run_id=state.run_id,
                by_store=moved_on,
                layout_revision=max(state.layout_revision, event.scene_layout_revision),
                updated_at=now_in_words(),
            )

            # And now the moment of publication itself: one rename, indivisible.
            _write_and_replace(self.truth, json.dumps(published.to_json(), indent=2))
            return published

    def next_revision(self) -> int:
        """The number the next publication should carry.

        Complete history lines left by a crash are never reused, even though they
        were not published. This is a suggestion rather than a reservation: the
        lock and the check inside :meth:`publish` remain the authority if two
        callers ask at the same moment.
        """
        state = self._committed_for_writing()
        recorded = self.events(published_only=False)
        last_recorded = max((event.revision for event in recorded), default=0)
        if state.revision > last_recorded:
            raise PublicationRefused(
                f"The small publication record claims revision {state.revision}, "
                f"but the durable history reaches only {last_recorded}. Restore "
                "the missing history before asking for another revision."
            )
        if self._partial_history or any(event.revision > state.revision for event in recorded):
            raise PublicationRefused(
                "The previous writer left an unpublished tail in the history. "
                "Call recover() before asking for another revision."
            )
        return (
            max(
                state.revision,
                max((event.revision for event in recorded), default=0),
            )
            + 1
        )

    # -- picking up after a crash -------------------------------------------

    def recover(self) -> CommittedState:
        """Put the record back in order after a writer stopped unexpectedly.

        A writer can die between adding a line to the history and renaming the
        small file. When that happens the history holds one more publication than
        was ever announced — and the safe reading is that it was never published,
        because no reader was ever told about it and the data behind it may well
        be unfinished.

        So this trusts the small file and quarantines any trailing lines it does
        not cover. Their complete contents are preserved in ``interrupted.json``
        before they are removed from the active append-only history, because they
        are evidence of what the writer was doing and cannot remain where a later
        truth revision might accidentally cover them.
        """
        with _one_writer_at_a_time(self.writer_lock):
            state = self._committed_for_writing()
            all_events = self.events(published_only=False)
            last_recorded = max((event.revision for event in all_events), default=0)
            if state.revision > last_recorded:
                raise PublicationRefused(
                    f"The small publication record claims revision {state.revision}, "
                    f"but the durable history reaches only {last_recorded}. There "
                    "is no safe tail to recover; restore the missing published "
                    "history first."
                )
            unannounced = [event for event in all_events if event.revision > state.revision]
            partial = self._partial_history
            if unannounced or partial:
                note = self.bookkeeping / "interrupted.json"
                _write_and_replace(
                    note,
                    json.dumps(
                        {
                            "schema": _SCHEMA,
                            "noticed_at": now_in_words(),
                            "last_published": state.revision,
                            "written_but_never_published": [
                                event.to_json() for event in unannounced
                            ],
                            "unfinished_history_fragment": (
                                partial.decode("utf-8", errors="replace") if partial else ""
                            ),
                            "what_this_means": (
                                "The writer stopped after beginning these records "
                                "but before announcing them. They were never "
                                "visible, so they remain unfinished. The entire "
                                "unpublished tail was preserved here before being "
                                "removed from the active publication history; the "
                                "writer may validate and publish the unit again."
                            ),
                        },
                        indent=2,
                    ),
                )
            if unannounced or partial:
                published_ends = [
                    end
                    for event, end in zip(self._events_cache, self._event_ends, strict=True)
                    if event.revision <= state.revision
                ]
                keep_to = max(published_ends, default=0)
                with self.history.open("r+b") as history:
                    history.truncate(keep_to)
                    history.flush()
                    os.fsync(history.fileno())
                self._reset_history_reader()
                self._history_identity = None
                self._history_mtime_ns = None
                self._read_new_history()
            return state

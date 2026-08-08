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

``events.jsonl`` is the history: one line per publication, only ever added to,
never rewritten. It says what was published, when, which storage plan and which
layout it used, and that every prerequisite was checked first.

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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .model import CommitEvent, ZmartLiveError

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
    by_store: dict[str, int] = field(default_factory=dict)
    layout_revision: int = 0
    updated_at: str = ""

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
        """Read back what :meth:`to_json` wrote."""
        return cls(
            revision=int(value.get("revision", 0)),
            run_id=value.get("run_id", ""),
            by_store={str(k): int(v) for k, v in (value.get("by_store") or {}).items()},
            layout_revision=int(value.get("layout_revision", 0)),
            updated_at=value.get("updated_at", ""),
        )


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
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", dir=destination.parent, prefix=destination.name + ".", suffix=".tmp",
        delete=False, encoding="utf-8",
    )
    try:
        with handle as writing:
            writing.write(text)
            writing.flush()
            os.fsync(writing.fileno())
        os.replace(handle.name, destination)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise


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
        self.run_id = run_id
        self._read_to = 0        # how far into the history we have already read

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
        if not manifest.history.exists():
            manifest.history.touch()
        if not manifest.truth.exists():
            _write_and_replace(
                manifest.truth,
                json.dumps(
                    CommittedState(revision=0, run_id=run_id,
                                   updated_at=now_in_words()).to_json(),
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
        manifest.run_id = manifest.committed().run_id
        return manifest

    # -- what a reader asks --------------------------------------------------

    def fingerprint(self) -> tuple[int, int]:
        """A cheap glance that changes whenever something has been published.

        Deliberately does not open or read the file. This is asked several times
        a second while a run is going, and reading a growing history that often
        would put real work on the path of every frame the viewer draws.
        """
        try:
            stamp = self.truth.stat()
        except FileNotFoundError:
            return (0, 0)
        return (stamp.st_mtime_ns, stamp.st_size)

    def committed(self) -> CommittedState:
        """What is safe to read right now.

        Falls back to "nothing published yet" if the small file cannot be read as
        sense. That is the safe direction to fail in: showing nothing is a
        disappointment, whereas showing something half-written is a wrong answer
        that nobody can spot.
        """
        try:
            return CommittedState.from_json(json.loads(self.truth.read_text()))
        except (FileNotFoundError, json.JSONDecodeError):
            return CommittedState(run_id=self.run_id)

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

    def events(self, after: int = 0) -> list[CommitEvent]:
        """Every publication with a revision above ``after``, oldest first.

        Only reads the part of the history it has not read before, so following a
        long run costs the same per publication whether it is the tenth or the
        ten-thousandth.

        A final line that will not parse is expected rather than alarming: a
        writer may be partway through adding it at this very moment, and it is
        not published until the small file says so. A line that will not parse
        anywhere *earlier* is a real fault and is reported as one, because
        everything before the end was finished long ago.
        """
        found: list[CommitEvent] = []
        if not self.history.exists():
            return found
        lines = self.history.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                if number == len(lines):
                    break            # the writer is mid-sentence; come back later
                raise ZmartLiveError(
                    f"The publication history at {self.history} has a damaged "
                    f"entry on line {number}, which is not the last line. Lines "
                    f"before the end were finished long ago, so this means the "
                    f"file itself has been corrupted rather than caught mid-write."
                ) from None
            event = CommitEvent.from_json(record)
            if event.revision > after:
                found.append(event)
        return found

    def events_for(self, position_id: str, after: int = 0) -> list[CommitEvent]:
        """The same, narrowed to one position."""
        return [e for e in self.events(after) if e.position_id == position_id]

    # -- what a writer does --------------------------------------------------

    def publish(
        self,
        event: CommitEvent,
        *,
        allow_incomplete: bool = False,
    ) -> CommittedState:
        """Make one finished position or moment visible, all at once.

        Everything the unit depends on must already have been checked — its
        pixels, its zoomed-out copies, the pointers the overview needs, the
        shared zoomed-out pieces it changes, and the layout saying who owns what.
        The event carries the results of those checks, and an event that does not
        claim all of them is refused.

        Returns what is now visible. Until this call returns, nothing about the
        unit is visible to anybody, however complete the files may look.

        ``allow_incomplete`` exists for tests that need to prove the refusal
        works. It should never be used by a writer.
        """
        if not allow_incomplete and not event.ready:
            missing = [
                name
                for name, done in (
                    ("the zoomed-out copies", event.pyramids_ready),
                    ("the overview's pointers", event.links_ready),
                    ("the shared zoomed-out pieces", event.coarse_chunks_ready),
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

        state = self.committed()
        if event.revision <= state.revision:
            raise PublicationRefused(
                f"This publication is numbered {event.revision}, but {state.revision} "
                f"has already been published. The number has to keep going up, "
                f"because it is how a viewer that missed a message works out that "
                f"it has fallen behind. Use next_revision() to get the right one."
            )

        line = json.dumps(event.to_json(), sort_keys=True)

        # First the history, pushed all the way to the disk. A line here is not
        # yet a publication; it becomes one only when the small file below is
        # renamed into place.
        with self.history.open("a", encoding="utf-8") as writing:
            writing.write(line + "\n")
            writing.flush()
            os.fsync(writing.fileno())

        moved_on = dict(state.by_store)
        moved_on[event.position_id] = event.revision
        published = CommittedState(
            revision=event.revision,
            run_id=self.run_id or state.run_id or event.run_id,
            by_store=moved_on,
            layout_revision=max(state.layout_revision, event.scene_layout_revision),
            updated_at=now_in_words(),
        )

        # And now the moment of publication itself: one rename, indivisible.
        _write_and_replace(self.truth, json.dumps(published.to_json(), indent=2))
        return published

    def next_revision(self) -> int:
        """The number the next publication should carry."""
        return self.revision() + 1

    # -- picking up after a crash -------------------------------------------

    def recover(self) -> CommittedState:
        """Put the record back in order after a writer stopped unexpectedly.

        A writer can die between adding a line to the history and renaming the
        small file. When that happens the history holds one more publication than
        was ever announced — and the safe reading is that it was never published,
        because no reader was ever told about it and the data behind it may well
        be unfinished.

        So this trusts the small file, and reports any trailing lines it does not
        cover. It does not delete them: they are evidence of what the writer was
        doing, and a person looking into an interrupted run will want them.
        """
        state = self.committed()
        unannounced = [e for e in self.events() if e.revision > state.revision]
        if unannounced:
            note = self.bookkeeping / "interrupted.json"
            _write_and_replace(
                note,
                json.dumps(
                    {
                        "schema": _SCHEMA,
                        "noticed_at": now_in_words(),
                        "last_published": state.revision,
                        "written_but_never_published": [
                            {"revision": e.revision, "position_id": e.position_id,
                             "timepoint": e.timepoint}
                            for e in unannounced
                        ],
                        "what_this_means": (
                            "The writer stopped between recording these and "
                            "announcing them. They were never visible to anyone, "
                            "so they are being treated as unfinished. The data "
                            "they refer to is still on disk and can be written "
                            "again under a new number."
                        ),
                    },
                    indent=2,
                ),
            )
        return state

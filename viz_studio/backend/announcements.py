"""Telling an open page that something has changed, the moment it happens.

A viewer watching a run needs to know when a new acquisition has appeared and
when a timelapse has gained a frame. Until now it found out by asking, several
times a second, whether anything had moved — which works, but it asks constantly
and it can only ever *infer* what happened from the state of the disk. Inferring
has caught us out more than once: most recently a description file that was
filled in rather than created, which left an acquisition invisible for a whole
session.

For a manifest-driven ZMART run, the atomic publication marker is the authority.
The writer does not know or care whether a viewer exists.  A watcher observes
that small marker and nudges open pages only after a higher valid revision has
been read.  Ordinary live folders have no such marker and retain the generic
folder watcher below.

The shape is deliberately small. There is one kind of message — *something
changed* — and a page that receives it asks for the current state of things in
the ordinary way. It would be possible to send the detail instead (which store,
how many frames) and have the page apply it directly, but then two descriptions
of the world would have to be kept in step, and the one on disk is the one that
is true. Sending only the nudge keeps the disk authoritative and makes the
message impossible to get subtly wrong.

Announcements arrive at the rate acquisitions finish — a handful a minute at
most — so nothing here needs to be fast, and when nothing is happening it does no
work at all.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable

log = logging.getLogger("viz_studio.announcements")

# How long a listener waits for something to be said before sending a small sign
# of life instead. Its purpose is not the message but the writing: a page that
# has been closed is only discovered by trying to write to it, and without this a
# server left running overnight would keep a thread for every page ever opened.
QUIET_HEARTBEAT_S = 15.0

# What is sent as that sign of life. A line beginning with a colon is a comment
# in the server-sent-events format: browsers accept it and hand it to nobody, so
# it keeps the connection honest without the page having to know about it.
HEARTBEAT = b": still here\n\n"

# What is sent when something has actually changed. Any message at all means "ask
# again", and naming it makes a recording of the traffic readable to a person, which
# matters when working out why a viewer did or did not notice something.
SOMETHING_CHANGED = b"event: changed\ndata: {}\n\n"

# The same, for the one kind of change the page cannot work out for itself.
#
# Almost everything a run does shows up in what the disk says: a new acquisition
# appears, a timelapse gets longer, a store's description changes. The page hears
# "something changed", reads the disk, and sees for itself -- which is why the message
# above carries no detail, and that is a deliberate choice worth keeping.
#
# There is one exception, and it is not a matter of taste. If a run writes image into a
# store the viewer already has open -- a tile landing in its place inside one large
# OME-Zarr, rather than a new store appearing beside the others -- then nothing about
# any description changes. The store is the same store, the same size, with the same
# name. The drawing engine, meanwhile, remembers every piece of image it has decoded,
# including the pieces it found to be empty, so it goes on showing the emptiness it
# settled on earlier and never asks the disk again. Measured, that is not "slow to
# appear": it is no request at all, ever.
#
# So the writer has to say so, because the writer is the only one who knows. This is not
# a second description of the world to keep in step with the first -- it says nothing
# about what the data is, only that image was written where the viewer has already
# looked. If it is wrong the worst that happens is that the viewer fetches what is on
# screen once more than it needed to.
IMAGE_WRITTEN_IN_PLACE = b'event: changed\ndata: {"imageWrittenInPlace": true}\n\n'


class Announcements:
    """Everyone currently listening, and the way to tell them something changed.

    One of these belongs to the server. Each open page holds one listener; a page
    that goes away takes its listener with it the next time anything is written.
    """

    def __init__(self, when_changed: Callable[[], None] | None = None) -> None:
        self._listeners: set[queue.SimpleQueue] = set()
        self._lock = threading.Lock()
        self._closed = False
        # Server-owned work that must happen even when no page is listening.
        # It is a nudge, not the work itself: the callback must return quickly.
        self._when_changed = when_changed
        # What the disk looked like when the microscope last announced something
        # itself. The folder watcher reads this so that it does not repeat an
        # announcement that has already been made; see :meth:`already_told_about`.
        self._already_told: object | None = None

    def listen(self) -> queue.SimpleQueue:
        """Start listening. Returns the queue to read messages from."""
        waiting: queue.SimpleQueue = queue.SimpleQueue()
        with self._lock:
            if self._closed:
                # The server is shutting down, so hand back something that ends
                # immediately rather than a listener that would wait for ever.
                waiting.put(None)
                return waiting
            self._listeners.add(waiting)
        return waiting

    def stop_listening(self, waiting: queue.SimpleQueue) -> None:
        with self._lock:
            self._listeners.discard(waiting)

    def say_something_changed(
        self, *, image_written_in_place: bool = False, covering: object | None = None,
    ) -> int:
        """Tell every open page to ask again. Returns how many were told.

        The count is worth returning: an acquisition script that announces a
        position and is told nobody was listening has learnt something useful,
        namely that the viewer is not open.

        Pass ``image_written_in_place`` when what was written went *into* a store the
        viewer may already have open, rather than into a new store of its own. That is
        what a run does when it fills in one large OME-Zarr tile by tile. It is off by
        default, because for the ordinary layout — one store per position — it is not
        true and asking for it would make the viewer fetch the current view again for
        nothing. See ``IMAGE_WRITTEN_IN_PLACE`` above for why the viewer cannot work
        this out on its own.

        Pass ``covering`` — what the disk looks like at this moment — when the
        announcement comes from the microscope rather than from the folder
        watcher. It is how the two are kept from saying the same thing twice; see
        :meth:`already_told_about`.
        """
        message = IMAGE_WRITTEN_IN_PLACE if image_written_in_place else SOMETHING_CHANGED
        with self._lock:
            if covering is not None:
                self._already_told = covering
            listeners = list(self._listeners)
        if self._when_changed is not None:
            try:
                self._when_changed()
            except Exception:
                # An auxiliary catch-up must never prevent the announcement
                # from reaching pages; serving remains fail-closed and a later
                # announcement can try the catch-up again.
                log.exception("server-side announcement work failed")
        for waiting in listeners:
            waiting.put(message)
        return len(listeners)

    def already_told_about(self) -> object | None:
        """What the disk looked like when the microscope last announced something.

        The folder watcher compares this with what it sees. If they match, the
        change it has just noticed is the very one the microscope already
        announced, and saying so again would only make every open page ask the
        same expensive question twice.

        That mattered more than a wasted question. Writing one acquisition
        produced both the run's own announcement and, within a second, the watcher
        noticing the same write — so every position cost two full rebuilds of the
        answer, on a question that takes over a second once a folder holds a few
        thousand acquisitions. Worse, the second announcement arrived when nothing
        on disk had moved since the first, which is the signal the viewer uses to
        decide that image has been written into a store it already has open. It
        would then throw away everything it had fetched and fetch it again, once
        per position, for no reason at all.

        Only an announcement made by the microscope records anything here. The
        watcher's own announcements do not, so a folder being filled by software
        that has never heard of this viewer is still watched exactly as before.
        """
        with self._lock:
            return self._already_told

    def close(self) -> None:
        """Let every listener go, so their threads can finish.

        Sending ``None`` rather than simply forgetting them is what makes a
        shutdown prompt: a listener sitting quietly would otherwise wait out its
        heartbeat before noticing anything had happened.
        """
        with self._lock:
            self._closed = True
            listeners = list(self._listeners)
            self._listeners.clear()
        for waiting in listeners:
            waiting.put(None)

    @property
    def listening(self) -> int:
        """How many pages are currently connected. Useful in tests and diagnosis."""
        with self._lock:
            return len(self._listeners)


class FolderWatcher:
    """Watches the open folders and announces when something on disk changes.

    This is the safety net for data that arrives without anyone announcing it. A
    mesoSPIM writes its own OME-Zarr, and an operator may open the viewer on a
    folder being filled by something that has never heard of us — in both cases
    nothing is going to say "this position is ready", and the only way to notice
    is to look.

    It is worth being clear that this is the path only for folders without a
    publication manifest. Looking at the disk can only infer that a write has
    finished, which is why a recognized ZMART run is excluded and observed by
    :class:`ManifestWatcher` instead.

    What has changed is *where* the looking happens. It used to be the page that
    asked, several times a second, for as long as it was open — so two windows
    asked twice as often, and every question travelled over HTTP. Now the server
    looks once on its own behalf, however many pages are watching, and speaks only
    when there is something to say. On finished data it does not run at all.
    """

    def __init__(
        self,
        library,
        announcements: Announcements,
        *,
        every: float = 1.0,
        excluding=frozenset(),
    ) -> None:
        self._library = library
        self._announcements = announcements
        self._every = every
        # Datasets governed by a ZMART publication manifest must not be inferred
        # from directory changes.  Their dedicated watcher below is the only
        # thing allowed to announce them.
        self._excluding = excluding
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._watch, daemon=True, name="zmart-folder-watch")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _watch(self) -> None:
        last = None
        while not self._stop.is_set():
            try:
                now = (
                    self._library.revision(excluding=self._excluding)
                    if callable(self._excluding) or self._excluding
                    else self._library.revision()
                )
            except Exception:
                # A folder that cannot be read this moment -- a share hiccuping --
                # is not a reason to stop watching for the rest of the session.
                now = last
            if last is not None and now != last:
                # Unless the microscope has already said this itself. Both
                # mechanisms see the same write, and announcing it twice made every
                # open page ask the same expensive question twice per position --
                # and, because nothing on disk had moved between the two, the
                # second announcement looked exactly like image being written into
                # a store already open, so the viewer threw away everything it had
                # fetched and fetched it again.
                #
                # Compared by what the disk says rather than by counting
                # announcements, so that a change landing *after* the microscope
                # spoke is still noticed: the disk has moved on from what was
                # announced, the two no longer match, and the watcher says so.
                if now != self._announcements.already_told_about():
                    self._announcements.say_something_changed()
            last = now
            self._stop.wait(self._every)


class ManifestWatcher:
    """Announce only higher, strictly validated manifest revisions.

    Each tracker stats one ``committed.json`` marker while idle.  Its own strict
    state machine retains the last good scene on damage, regression or a foreign
    run identity; those observations are therefore recorded as degraded but are
    never announced.  A jump over several revisions produces one nudge, because
    the browser will fetch current authoritative state rather than replaying
    hints.
    """

    def __init__(
        self,
        trackers,
        announcements: Announcements,
        *,
        every: float = 1.0,
    ) -> None:
        self._trackers = trackers if callable(trackers) else lambda: tuple(trackers)
        self._announcements = announcements
        self._every = every
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        initial = self._trackers()
        self._announced = {tracker: tracker.revision for tracker in initial}

    def check_once(self) -> int:
        """Observe every marker once and return effective announcements made."""
        announced = 0
        trackers = self._trackers()
        alive = set(trackers)
        self._announced = {
            tracker: revision
            for tracker, revision in self._announced.items()
            if tracker in alive
        }
        for tracker in trackers:
            tracker.observe()
            if tracker not in self._announced:
                # A run may have been opened explicitly (whose response already
                # carries it) or may have gained its first marker inside a folder
                # that was already open. One harmless nudge covers both and is
                # required for the latter to reach an already-open browser.
                self._announced[tracker] = tracker.revision
                self._announcements.say_something_changed()
                announced += 1
                continue
            previous = self._announced[tracker]
            # Another request may share this tracker and observe the marker just
            # before this thread.  Publication is still news to every other tab,
            # so compare with what this watcher announced rather than relying on
            # which caller happened to perform the state transition.
            if tracker.error is not None or tracker.revision <= previous:
                continue
            self._announced[tracker] = tracker.revision
            self._announcements.say_something_changed()
            announced += 1
        return announced

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._watch,
            daemon=True,
            name="zmart-manifest-watch",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _watch(self) -> None:
        while not self._stop.is_set():
            self.check_once()
            self._stop.wait(self._every)

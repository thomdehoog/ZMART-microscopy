"""Telling an open page that something has changed, the moment it happens.

A viewer watching a run needs to know when a new acquisition has appeared and
when a timelapse has gained a frame. Until now it found out by asking, several
times a second, whether anything had moved — which works, but it asks constantly
and it can only ever *infer* what happened from the state of the disk. Inferring
has caught us out more than once: most recently a description file that was
filled in rather than created, which left an acquisition invisible for a whole
session.

The application driving the microscope does not have to infer anything. It called
for the acquisition and it waited for the write to finish, so it knows. This
module is the way for it to say so, and the way an open page hears it.

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

import queue
import threading

# How long a listener waits for something to be said before sending a small sign
# of life instead. Its purpose is not the message but the writing: a page that
# has been closed is only discovered by trying to write to it, and without this a
# server left running overnight would keep a thread for every page ever opened.
QUIET_HEARTBEAT_S = 15.0

# What is sent as that sign of life. A line beginning with a colon is a comment
# in the server-sent-events format: browsers accept it and hand it to nobody, so
# it keeps the connection honest without the page having to know about it.
HEARTBEAT = b": still here\n\n"

# What is sent when something has actually changed. The page does not read the
# text -- any message at all means "ask again" -- but naming it makes a recording
# of the traffic readable to a person, which matters when working out why a
# viewer did or did not notice something.
SOMETHING_CHANGED = b"event: changed\ndata: {}\n\n"


class Announcements:
    """Everyone currently listening, and the way to tell them something changed.

    One of these belongs to the server. Each open page holds one listener; a page
    that goes away takes its listener with it the next time anything is written.
    """

    def __init__(self) -> None:
        self._listeners: set[queue.SimpleQueue] = set()
        self._lock = threading.Lock()
        self._closed = False

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

    def say_something_changed(self) -> int:
        """Tell every open page to ask again. Returns how many were told.

        The count is worth returning: an acquisition script that announces a
        position and is told nobody was listening has learnt something useful,
        namely that the viewer is not open.
        """
        with self._lock:
            listeners = list(self._listeners)
        for waiting in listeners:
            waiting.put(SOMETHING_CHANGED)
        return len(listeners)

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

    It is worth being clear that this is the weaker mechanism of the two. Looking
    at the disk can only ever infer that a write has finished, and inference is
    what has caught us out before. An announcement from the application driving
    the microscope is authoritative and should be preferred wherever there is one.

    What has changed is *where* the looking happens. It used to be the page that
    asked, several times a second, for as long as it was open — so two windows
    asked twice as often, and every question travelled over HTTP. Now the server
    looks once on its own behalf, however many pages are watching, and speaks only
    when there is something to say. On finished data it does not run at all.
    """

    def __init__(self, library, announcements: Announcements, *, every: float = 1.0) -> None:
        self._library = library
        self._announcements = announcements
        self._every = every
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
                now = self._library.revision()
            except Exception:
                # A folder that cannot be read this moment -- a share hiccuping --
                # is not a reason to stop watching for the rest of the session.
                now = last
            if last is not None and now != last:
                self._announcements.say_something_changed()
            last = now
            self._stop.wait(self._every)

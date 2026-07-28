"""Which images the viewer currently has open, and where they live on disk.

The viewer starts on whatever folder it was pointed at, but an operator will want
to add to that while working — last week's run for comparison, a second overview,
a colleague's data from a different drive — and to close things again once they
have been looked at. This keeps that list.

It is a separate piece from the web server because two things about it need care
and are easier to see on their own.

The first is **where a file is allowed to come from**. The server hands out image
files by translating a web address into a path on disk, and a viewer that could be
talked into reading any file on the machine would be a poor thing to leave running.
So every folder that has been opened is remembered here, and a request may only
reach inside one of them. A path that tries to climb out is refused rather than
cleverly corrected.

The second is that folders come and go. Each opened folder is given a small number,
and the images inside it are addressed as ``/data/<number>/<store>``. The number is
never reused once a folder is closed, so a chunk request still in flight when the
operator closed something cannot land on whatever was opened next.
"""

from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path

from stores import discover, split_name

# The small files that say "this folder is an image, and here is its shape". A
# store is only recognisable once one of these is readable, so these are the
# files whose changing matters most to anyone watching a run. Both spellings are
# listed because the two versions of the format name them differently, and a
# folder is checked for either.
_DESCRIPTION_FILES = (".zattrs", "zarr.json")


def _described_at(folder: Path) -> str:
    """When this folder's description was last written, as a short mark.

    Used only for noticing change, never for reading anything, so the exact
    number means nothing on its own — all that matters is that it moves when the
    description does. A folder with no description yet answers ``-``, which is
    itself worth knowing: that is an acquisition still being written, and the
    answer changing from ``-`` to a number is the moment it becomes readable.
    """
    for name in _DESCRIPTION_FILES:
        try:
            return str((folder / name).stat().st_mtime_ns)
        except OSError:
            continue
    return "-"


class Library:
    """The folders the viewer has open, and the images found inside them."""

    def __init__(self) -> None:
        self._roots: dict[int, Path] = {}
        self._stores: dict[int, list[str]] = {}
        # Whether to keep looking in a folder for images that appear after it was
        # opened. See the note on ``open``.
        self._watch: dict[int, bool] = {}
        # Counts up forever rather than filling gaps, so a number never refers to
        # two different folders over the life of a session.
        self._next = 0
        # The web server answers many requests at once, each on its own thread, so
        # a folder can be closed at the very moment another request is reading the
        # list. Without this, that request would fail with an error the operator
        # has no way to understand. Everything guarded here is short and reads no
        # image data, so waiting for it costs nothing worth measuring.
        self._lock = threading.RLock()

    # -- opening and closing ---------------------------------------------

    def open(
        self,
        path: str | Path,
        *,
        names: list[str] | None = None,
        watch: bool | None = None,
    ) -> int:
        """Open a folder and return the number it will be addressed by.

        ``path`` may be a single OME-Zarr store or a folder holding several; both
        are handled, so the operator can pick either without having to know which
        they have. Pass ``names`` to open only some of what is there.

        ``watch`` decides whether the folder keeps being looked at. A run writes as
        it goes, so an acquisition can appear long after the viewer was opened, and
        a watched folder picks those up (and lets go of anything that has been
        removed). It is off when a particular selection of images was asked for,
        since re-reading the folder would quietly undo that choice.

        Raises ``FileNotFoundError`` if the path does not exist, and ``ValueError``
        if it holds no OME-Zarr image at all — which is the ordinary mistake of
        picking one folder up from the right one, and deserves a plain answer
        rather than an empty viewer.
        """
        path = Path(path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"there is no folder at {path}")
        if not path.is_dir():
            raise ValueError(f"{path} is a file, not a folder of images")
        parent, found = discover(path)
        chosen = names if names is not None else found
        if not chosen:
            raise ValueError(
                f"no OME-Zarr image was found in {path} — if the images are one "
                "level down, choose the folder that contains them"
            )
        with self._lock:
            number = self._next
            self._next += 1
            self._roots[number] = parent.resolve()
            self._stores[number] = list(chosen)
            self._watch[number] = watch if watch is not None else (names is None)
        return number

    def close(self, number: int) -> bool:
        """Stop serving a folder. Returns whether it was open at all."""
        with self._lock:
            return self._close(number)

    def _close(self, number: int) -> bool:
        """Stop serving a folder, with the lock already held."""
        self._stores.pop(number, None)
        self._watch.pop(number, None)
        return self._roots.pop(number, None) is not None

    def close_group(self, group: str, *, folder: int | None = None) -> list[tuple[int, Path, str]]:
        """Close every image belonging to one acquisition type.

        The panel offers closing by acquisition type rather than by folder,
        because that is the unit an operator thinks in. A folder that has nothing
        left in it afterwards is closed with them.

        ``folder`` narrows this to one open folder. That matters when two runs are
        open side by side: both will have an "overview", and closing the one being
        compared against must not also close the one being worked on.

        Returns the images that were closed, as ``(folder number, folder, store
        name)``. The caller needs that in order to let go of what it remembered
        about them: closing something is supposed to give the memory back, and only
        this knows which images were actually affected.
        """
        closed: list[tuple[int, Path, str]] = []
        with self._lock:
            for number, names in list(self._stores.items()):
                if folder is not None and number != folder:
                    continue
                kept = [name for name in names if split_name(name)[0] != group]
                if kept == names:
                    continue
                root = self._roots[number]
                closed += [(number, root, name) for name in names if name not in kept]
                if kept:
                    self._stores[number] = kept
                    # Stop watching, or the closed images would be found again on
                    # the next look and reappear moments after being dismissed.
                    self._watch[number] = False
                else:
                    self._close(number)
        return closed

    # -- reading -----------------------------------------------------------

    def entries(self) -> list[tuple[int, Path, str]]:
        """Every open image as ``(folder number, folder, store name)``.

        A watched folder is looked at again here, which is what lets an acquisition
        written during a run turn up in the viewer on its own. Images named when the
        folder was opened keep their place at the front, so the order does not
        rearrange itself as new ones arrive; anything that has since been removed
        from disk quietly drops out.
        """
        with self._lock:
            open_now = [(number, self._roots[number], self._stores[number],
                         self._watch.get(number)) for number in sorted(self._stores)]
        out = []
        for number, root, names, watched in open_now:
            if watched:
                # Looking in the folder is the one slow thing here, so it is done
                # without the lock held: a folder on a network share can take a
                # moment to answer, and no other request should wait on that.
                names = self._present(root, names)
                with self._lock:
                    if number in self._stores:
                        self._stores[number] = names
            out.extend((number, root, name) for name in names)
        return out

    def _present(self, root: Path, known: list[str]) -> list[str]:
        """What is in a watched folder now: what was there, plus whatever is new.

        Only additions are taken. An image is never dropped for having gone missing,
        which is deliberate: a folder on a network share can look empty for a moment
        when the share hiccups, and losing half the screen because of that would be
        far worse than briefly listing something whose files have genuinely gone. A
        store that really has been deleted simply stops answering for its pieces,
        and the operator can close it.
        """
        try:
            _, found = discover(root)
        except OSError:
            # A folder that has become unreadable mid-run is not a reason to lose
            # what is already on screen.
            return known
        # Asked of a set rather than of the list. "Is this name already known?" is a
        # question asked once per image found, and answering it by walking the list of
        # images already known costs a little more each time the folder grows -- which,
        # in a folder of tens of thousands of positions, becomes the slowest thing the
        # viewer does: measured at fifteen seconds a look, and it is looked at whenever
        # anything is announced.
        already = set(known)
        return known + [name for name in found if name not in already]

    def revision(self) -> str:
        """A short summary of the open folders that changes when their contents do.

        The viewer needs to know when a new acquisition has appeared, and asking
        the full question — what is here, what channels, how bright — means reading
        every store's description, which is far too heavy to repeat often. So the
        viewer asks this instead. It only looks at *when* things were last touched,
        which the operating system already knows and can answer without reading
        anything, and so it can be asked several times a second even with hundreds
        of acquisitions open. The expensive question is then asked only when the
        answer here has moved.

        The care in what follows is all about one thing: an acquisition is not
        written in an instant. The microscope makes the folder, fills it with
        image, and writes the small description file last — that description is
        what makes the folder recognisable as an image at all. So there is a window,
        which on a real acquisition is seconds or minutes long, in which the folder
        exists and is not yet readable.

        That window is a trap. If this answer moves the moment the folder appears,
        the viewer looks, finds nothing it can read, and settles down again — and
        because nothing about the enclosing folder changes afterwards, it would
        never look a second time. The acquisition would stay invisible for the rest
        of the session, and nothing anywhere would report a problem.

        So the mark taken here is the modification time of *every* folder sitting
        alongside the images, whether or not the viewer has recognised it yet.

        A folder's own time is not enough on its own, and this is the part that
        caught us out. A folder is marked as changed when something is *created*
        inside it or removed from it — not when a file already in it is rewritten.
        Writers routinely create the description file early, empty, and fill it in
        once the image is safely on disk; that filling-in changes the file and
        leaves the folder's own time exactly as it was. The viewer would look once
        during the empty window, see nothing it could read, and never have any
        reason to look again. The acquisition stayed invisible for the rest of the
        session with nothing anywhere reporting a problem — which is precisely the
        trap described above, arriving by a slightly different door.

        So each candidate folder's description file is looked at as well. That is
        one extra glance per folder, asking the operating system something it
        already knows, and it is what makes "the description was rewritten" and
        "the description was created" look the same from here — which is what the
        viewer actually needs to know.
        """
        with self._lock:
            open_now = [(number, self._roots[number], list(self._stores.get(number, ())))
                        for number in sorted(self._roots)]
        marks = []
        for number, root, names in open_now:
            try:
                with os.scandir(root) as listing:
                    beside = sorted(
                        (entry.name, entry.stat().st_mtime_ns, _described_at(Path(entry.path)))
                        for entry in listing
                        if entry.is_dir()
                    )
            except OSError:
                # A folder that cannot be read right now (a share hiccuping) should
                # not read as "everything changed" and trigger a needless rebuild.
                marks.append(f"{number}:?")
                continue
            marks.append(
                f"{number}:"
                + ",".join(f"{name}@{when}/{described}" for name, when, described in beside)
            )
            # An acquisition already open gains frames as the run goes on, and that
            # happens inside it -- so its own folder does not change and the marks
            # above would miss it. The folder holding the full-resolution image is
            # the one that moves when a frame is written, so that gets a look too.
            for name in names:
                try:
                    marks.append(str((root / name / "0").stat().st_mtime_ns))
                except OSError:
                    marks.append("?")
        # What is returned is a short fingerprint of all that rather than the marks
        # themselves. The viewer only ever compares this answer with the previous
        # one, so it does not need to be readable -- and with several hundred
        # acquisitions open the marks run to tens of thousands of characters, which
        # would then be sent across several times a second for no reason at all.
        return hashlib.blake2b("|".join(marks).encode("utf-8"), digest_size=16).hexdigest()

    def is_empty(self) -> bool:
        """Whether nothing at all is open, which the server reports as an empty viewer."""
        with self._lock:
            return not any(self._stores.values())

    def resolve(self, relative: str) -> Path | None:
        """Turn ``<number>/<store>/<chunk…>`` into a file, or ``None`` if not allowed.

        This is the guard. The path is resolved to what it really points at before
        being checked, because that is the only way to catch a request that climbs
        out of the folder with ``..`` or through a symbolic link. A resolved target
        that does not sit inside the folder it claims to be in is refused.
        """
        number, _, rest = relative.partition("/")
        if not number.isdigit() or not rest:
            return None
        with self._lock:
            root = self._roots.get(int(number))
        if root is None:
            return None
        target = (root / rest).resolve()
        if root not in target.parents and target != root:
            return None
        return target

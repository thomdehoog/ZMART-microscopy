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

from dataclasses import dataclass, field

from stores import channel_of, declared_channels, discover, voxel_size

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
            found = (folder / name).stat()
        except OSError:
            continue
        # The size as well as the time, and this is not belt-and-braces. Windows
        # advances a file's timestamp only about every sixteen milliseconds, so a
        # description created empty and filled in a moment later can carry the same
        # time before and after — and that rewrite is precisely the change this
        # exists to notice. The size always moves when an empty description becomes
        # a real one, and the two together cost the same single question of the
        # operating system that the time alone did.
        return f"{found.st_mtime_ns}:{found.st_size}"
    return "-"


def _named_for(path: Path, parent: Path) -> str:
    """What to call the dataset a load produced.

    The folder the operator chose, or — when they pointed straight at a single
    store — that store, with the format's suffixes taken off so the panel shows
    ``overview`` rather than ``overview.ome.zarr``.
    """
    del parent  # kept in the signature: what was chosen is the whole answer here
    for suffix in (".ome.zarr", ".zarr"):
        if path.name.endswith(suffix):
            return path.name[: -len(suffix)]
    return path.name


@dataclass
class Dataset:
    """One load: one acquisition, however many stores it was written as.

    The stores in it are tiles and channels of the same run, which is why they can
    be drawn as one picture — the engine places each by the position recorded
    inside it. What makes them one thing is not their names but what they are: an
    overview and a target scan of the same specimen are different acquisitions
    because they were taken at different magnifications, and that is checked when
    the dataset is opened rather than inferred afterwards.
    """

    number: int
    root: Path
    name: str
    stores: list[str]
    channels: list[str]
    live: bool
    # Whether to keep looking in the folder for stores that appear after it was
    # opened. See the note on ``open``.
    watch: bool = field(default=True)


def _one_acquisition_only(root: Path, names: list[str]) -> None:
    """Refuse a load that spans more than one acquisition, saying what it found.

    A refusal here is deliberate and is the one place the viewer declines to show
    something it was pointed at. It is not the silent absence Decision 5 forbids:
    what is refused is named, with the stores in each acquisition listed, so the
    answer is to open one of them rather than to wonder what happened.
    """
    families: dict[tuple, list[str]] = {}
    for name in names:
        size = voxel_size(root / name)
        if size:
            families.setdefault(size, []).append(name)
    if len(families) > 1:
        described = "\n".join(
            "  voxel " + " x ".join(f"{value:g}" for value in size) + " um: " + ", ".join(found)
            for size, found in sorted(families.items())
        )
        raise ValueError(
            f"{root} holds more than one acquisition — open one of them instead:\n{described}"
        )

    declared: dict[tuple, list[str]] = {}
    for name in names:
        found = declared_channels(root / name)
        if found is not None:
            declared.setdefault(tuple(found), []).append(name)
    if len(declared) > 1:
        described = "\n".join(
            "  channels " + ", ".join(names_of) + ": " + ", ".join(found)
            for names_of, found in sorted(declared.items())
        )
        raise ValueError(
            f"{root} holds stores declaring different channels, so they are not one "
            f"acquisition — open one of them instead:\n{described}"
        )


def _channels_of(root: Path, names: list[str]) -> list[str]:
    """The channels a dataset presents, in the order the panel should show them.

    Where a store names its channels internally that answer is taken whole. Where
    the channel is in the filename instead, each store carries one and the dataset
    presents the union — a tile that has not been imaged in every channel yet is a
    normal state during a run, not a mismatch.
    """
    for name in names:
        found = declared_channels(root / name)
        if found is not None:
            return found
    seen: list[str] = []
    for name in sorted(names):
        wavelength = channel_of(name)
        if wavelength and f"Ch{wavelength}" not in seen:
            seen.append(f"Ch{wavelength}")
    return seen


class Library:
    """The datasets the viewer has open, and where they live on disk."""

    def __init__(self) -> None:
        self._datasets: dict[int, Dataset] = {}
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
        name: str | None = None,
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
        root = parent.resolve()
        _one_acquisition_only(root, list(chosen))
        watched = watch if watch is not None else (names is None)
        with self._lock:
            number = self._next
            self._next += 1
            self._datasets[number] = Dataset(
                number=number,
                root=root,
                name=name or _named_for(path, parent),
                stores=list(chosen),
                channels=_channels_of(root, list(chosen)),
                live=bool(watched),
                watch=bool(watched),
            )
        return number

    def dataset(self, number: int) -> Dataset | None:
        """The dataset a load produced, or ``None`` if it has since been closed."""
        with self._lock:
            return self._datasets.get(number)

    def datasets(self) -> list[Dataset]:
        """Every open dataset, oldest first, which is the order the panel shows."""
        with self._lock:
            return [self._datasets[number] for number in sorted(self._datasets)]

    def close(self, number: int) -> bool:
        """Stop serving a folder. Returns whether it was open at all."""
        with self._lock:
            return self._close(number)

    def _close(self, number: int) -> bool:
        """Stop serving a dataset, with the lock already held."""
        return self._datasets.pop(number, None) is not None

    def close_group(self, group: str, *, folder: int | None = None) -> list[tuple[int, Path, str]]:
        """Close a dataset by the name the panel shows it under.

        A dataset is one acquisition, so closing one is closing all of it — there
        is no longer a sub-group inside a folder to pick out, because the load that
        produced the dataset is what decided its extent.

        ``folder`` narrows this to one open dataset by number. That matters when two
        runs are open side by side: both may be called "overview", and closing the
        one being compared against must not also close the one being worked on.

        Returns the images that were closed, as ``(number, folder, store name)``.
        The caller needs that in order to let go of what it remembered about them:
        closing something is supposed to give the memory back, and only this knows
        which images were actually affected.
        """
        closed: list[tuple[int, Path, str]] = []
        with self._lock:
            for number, dataset in list(self._datasets.items()):
                if folder is not None and number != folder:
                    continue
                if dataset.name != group:
                    continue
                closed += [(number, dataset.root, store) for store in dataset.stores]
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
            open_now = [(dataset.number, dataset.root, list(dataset.stores), dataset.watch)
                        for dataset in self.datasets()]
        out = []
        for number, root, names, watched in open_now:
            if watched:
                # Looking in the folder is the one slow thing here, so it is done
                # without the lock held: a folder on a network share can take a
                # moment to answer, and no other request should wait on that.
                names = self._present(root, names)
                with self._lock:
                    found = self._datasets.get(number)
                    if found is not None:
                        found.stores = names
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
            open_now = [(dataset.number, dataset.root, list(dataset.stores))
                        for dataset in self.datasets()]
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
            return not any(dataset.stores for dataset in self._datasets.values())

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
            found = self._datasets.get(int(number))
        if found is None:
            return None
        root = found.root
        target = (root / rest).resolve()
        if root not in target.parents and target != root:
            return None
        return target

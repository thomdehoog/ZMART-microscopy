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

There is a third thing, which follows from the first two. A folder that is being
watched is looked in again and again while a run writes into it, so what is open
does not only change when the operator says so. Most of what appears is another
position of the acquisition already on screen and simply joins it. But a run also
produces more than one kind of scan — an overview, then a target scan of something
found in it — and those two are not one picture. So each open dataset knows what
kind of acquisition it is, and a store that is not part of it is opened as a dataset
of its own rather than quietly added. :meth:`Library._look_again` explains why that
is the answer here, and why opening such a folder from scratch is refused instead.
"""

from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path

from dataclasses import dataclass, field

from stores import (
    _moments_folder,
    channel_of,
    declared_channels,
    discover,
    voxel_size,
    without_format_suffix,
)

# The small files that say "this folder is an image, and here is its shape". A
# store is only recognisable once one of these is readable, so these are the
# files whose changing matters most to anyone watching a run. Both spellings are
# listed because the two versions of the format name them differently, and a
# folder is checked for either.
#
# Deliberately shorter than ``DESCRIPTION_FILES`` in ``stores``, and not a stale
# copy of it. That list is every file that describes rather than holds picture;
# this one is only the two that make a folder *recognisable as an image*, which
# is the moment a watcher cares about. A ``.zarray`` appearing says an array is
# being built and says nothing about whether the image can be opened yet.
_DESCRIPTION_FILES = (".zattrs", "zarr.json")


# -- noticing that something on disk has changed -------------------------------
#
# A run writes while the viewer is open, so the library has to tell what is new
# from what it has already seen. Everything here is about doing that cheaply: it
# asks the operating system when things were last touched and reads nothing.


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


# -- what to call things, and what makes two stores one acquisition ------------
#
# Two separate questions that are easy to confuse, so they are set out together.
# What a dataset is *called* comes from names, because a name is what an operator
# reads. What *belongs together* never does: that is read from inside the stores,
# because a folder can be renamed by anybody and the magnification cannot.


def _named_for(path: Path, parent: Path) -> str:
    """What to call the dataset a load produced.

    The folder the operator chose, or — when they pointed straight at a single
    store — that store, with the format's suffixes taken off so the panel shows
    ``overview`` rather than ``overview.ome.zarr``.
    """
    del parent  # kept in the signature: what was chosen is the whole answer here
    return without_format_suffix(path.name)


def _acquisition_type_in(store_name: str) -> str:
    """The kind of scan a store's name says it is — ``targetscan``, ``overview``.

    A run names each output after the scan it came from and then the position:
    ``targetscan_cell042``, ``overview_pos001``. So the text in front of the first
    underscore is the kind of scan, and it is what an operator would call it out
    loud. A run that writes one image per kind of scan has no position to strip and
    answers with the whole name, which is the same answer by a shorter road.

    This is used for one thing only: a heading, when the viewer has had to open a
    dataset on its own while a run was being watched. What actually belongs with
    what is read from inside the stores instead (see :func:`_acquisition_of`),
    because a folder's name can be changed by anyone and this one may well not
    follow the convention at all.
    """
    stem = without_format_suffix(store_name)
    front, _, _position = stem.partition("_")
    return front or stem


# What kind of acquisition a store is: how large one of its voxels is, and the
# channels it names inside itself where it names any (``None`` where it holds a
# single channel and so has no list to give). Written down here under one name
# because it appears in several places below, and "a voxel size together with
# perhaps some channel names" is a mouthful to repeat.
Acquisition = tuple[tuple[float, ...], tuple[str, ...] | None]


def _acquisition_of(root: Path, name: str) -> Acquisition:
    """What kind of acquisition one store says it is, read from the store itself.

    Both parts come from inside the store rather than from its name. That is the
    point: a folder can be renamed by anybody, whereas the voxel size is the
    magnification the microscope actually used and cannot be anything else.

    Either part may be missing, and that is not held against the store — see
    :func:`_same_acquisition`, which treats "did not say" as matching anything.
    """
    declared = declared_channels(root / name)
    return voxel_size(root / name), tuple(declared) if declared is not None else None


def _same_acquisition(one: Acquisition | None, other: Acquisition | None) -> bool:
    """Whether two stores can be pieces of the same acquisition.

    They can unless they positively disagree, which is the same generosity
    :func:`_one_acquisition_only` shows a folder being opened. A store that declares
    no voxel size, or that holds one channel and so declares no channel list, has
    said nothing there is anything to disagree with. Only a real difference — two
    magnifications, or two different sets of named channels — makes them two
    acquisitions, because only a real difference means they are not one picture.
    """
    if one is None or other is None:
        return True
    size_here, channels_here = one
    size_there, channels_there = other
    if size_here and size_there and size_here != size_there:
        return False
    if channels_here is not None and channels_there is not None:
        if channels_here != channels_there:
            return False
    return True


def _kind_of_acquisition(root: Path, names: list[str]) -> Acquisition | None:
    """What kind of acquisition a dataset is, from the first of its stores that says.

    One store is enough, because a dataset is one acquisition and that was checked
    when it was opened. Asking all of them would also be slow in a way that matters:
    with tens of thousands of positions open, re-reading every one of them each time
    the folder is looked at is the kind of cost that has made this viewer feel frozen
    before.

    ``None`` means not one of the stores declared anything to go on, which happens
    with a store that carries no voxel size in its description. Nothing is inferred
    from that; the dataset simply has nothing to compare newcomers against.
    """
    for name in names:
        found = _acquisition_of(root, name)
        if found[0] or found[1] is not None:
            return found
    return None


# -- one load, one acquisition -------------------------------------------------


@dataclass
class Dataset:
    """One load: one acquisition, however many stores it was written as.

    The stores in it are tiles and channels of the same run, which is why they can
    be drawn as one picture — the engine places each by the position recorded
    inside it. What makes them one thing is not their names but what they are: an
    overview and a target scan of the same specimen are different acquisitions
    because they were taken at different magnifications, and that is read from the
    stores rather than inferred from anything about them.

    It is checked when the dataset is opened, and again for each store that appears
    afterwards in a folder being watched. A store that turns out to be a different
    acquisition becomes a dataset of its own instead of joining this one; see
    :meth:`Library._look_again`.
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
    # What kind of acquisition this is, as its own stores declare it: the voxel size
    # they were taken at, and the channels they name inside themselves where they
    # name any. It is read once, when the dataset is opened, and it is what a store
    # appearing later is compared against to decide whether it is another piece of
    # this picture or a different acquisition altogether. ``None`` means none of the
    # stores said, in which case nothing can be told apart and nothing is.
    acquisition: Acquisition | None = field(default=None)


def _one_acquisition_only(root: Path, names: list[str]) -> None:
    """Refuse a load that spans more than one acquisition, saying what it found.

    A refusal here is deliberate and is the one place the viewer declines to show
    something it was pointed at. It is not the silent absence Decision 5 forbids:
    what is refused is named, with the stores in each acquisition listed, so the
    answer is to open one of them rather than to wonder what happened.

    This is the answer *at the door*, where somebody is waiting to be told. A second
    acquisition that appears later, in a folder already being watched, is met with
    nobody there to tell — so it is given a dataset of its own instead of being
    refused into silence. :meth:`Library._look_again` sets out why the two moments
    are answered differently, and what they agree on.
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
        # The stores the operator has closed, as (folder, store name). A watched
        # folder is looked in again and again while a run writes into it, so without
        # this an acquisition closed during the run would be found a second later
        # and put straight back on screen: the eye and the close button would look
        # broken, and there would be nothing the operator could do about it.
        #
        # Only the exact stores that were closed are remembered, and that is
        # deliberate. A *new* position, imaged after the operator closed what was
        # there, is data that has just arrived and is shown. Holding it back because
        # something like it was closed earlier would leave the operator looking at
        # part of their specimen with nothing on screen to say so, which is the one
        # failure this viewer exists to avoid.
        self._let_go: set[tuple[Path, str]] = set()

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
            # Asking for something says plainly that it is wanted, so this undoes
            # any earlier closing of it: otherwise a store closed once could never
            # be opened again for the rest of the session.
            self._let_go.difference_update((root, store) for store in chosen)
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
                acquisition=_kind_of_acquisition(root, list(chosen)),
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
        closed = self._datasets.pop(number, None)
        if closed is None:
            return False
        # Remembered, so that a folder still being watched does not find these again
        # a moment later and put them back on screen. See the note in ``__init__``.
        self._let_go.update((closed.root, name) for name in closed.stores)
        return True

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

    # -- what is open now, and what has arrived since ----------------------
    #
    # These belong together because they are one question asked at one moment.
    # A watched folder is looked in again here, so answering "what is open"
    # is also what notices that a run has produced something since the last
    # time anybody asked -- and what decides whether it joins the acquisition
    # on screen or is given a heading of its own.

    def entries(self) -> list[tuple[int, Path, str]]:
        """Every open image as ``(folder number, folder, store name)``.

        A watched folder is looked at again here, which is what lets an acquisition
        written during a run turn up in the viewer on its own. Images named when the
        folder was opened keep their place at the front, so the order does not
        rearrange itself as new ones arrive. Nothing is ever taken away by a look —
        only the operator closes things — for the reason set out in
        :meth:`_look_again`.

        Where a new store goes is decided in :meth:`_look_again`. Most of the time it
        is another position of the acquisition already open and joins it. A store
        that is a *different* acquisition — a target scan landing in the folder an
        overview is being written to — is opened as a dataset of its own, so that it
        arrives with its own heading, its own eye and its own brightness instead of
        disappearing into the row beside it.
        """
        with self._lock:
            # One look per folder rather than one per dataset. Two datasets can be
            # open on the same folder, and looking in it once for each of them would
            # cost twice as much and, worse, let each of them take what belongs to
            # the other.
            watched: list[Path] = []
            for dataset in self.datasets():
                if dataset.watch and dataset.root not in watched:
                    watched.append(dataset.root)
        for root in watched:
            self._look_again(root)
        with self._lock:
            return [
                (dataset.number, dataset.root, name)
                for dataset in self.datasets()
                for name in dataset.stores
            ]

    def _look_again(self, root: Path) -> None:
        """Look in a watched folder and place whatever has appeared in it.

        Nothing is ever dropped for having gone missing, which is deliberate: a
        folder on a network share can look empty for a moment when the share
        hiccups, and losing half the screen because of that would be far worse than
        briefly listing a store whose files have genuinely gone. A store that really
        has been deleted simply stops answering for its pieces, and the operator can
        close it.

        **Where a newcomer goes.** A run writes its positions one after another, and
        each is another piece of the picture already on screen, so it joins the
        dataset it belongs to. But a run also produces more than one kind of scan —
        an overview at five micrometres to a voxel, then a target scan of something
        found in it at a third of one — and those two are not one picture. Merged
        into one row they would share a single set of controls: no heading for the
        target scan, no eye to hide the overview and look at it, one brightness taken
        from whichever arrived first, and closing either one closing both. The
        operator would have no way even to tell that the target scan was open. So a
        store that is not part of any acquisition already open is opened here as a
        dataset of its own.

        **Why this differs from opening such a folder from scratch,** which is
        refused outright by :func:`_one_acquisition_only`. The two agree on the thing
        that matters — two acquisitions are never merged into one row — and differ
        only in what happens next, because the two moments are not alike. At the door
        there is an operator waiting for an answer, so the viewer can decline and say
        "open one of them instead"; and it should, because a folder holding two
        acquisitions is usually a folder chosen one level too high. Half an hour into
        a run there is nobody to answer: the request that would have carried a
        refusal finished long ago, and the page has no way of asking for one
        acquisition out of a folder even if it were told to. Declining there would
        leave the target scan — usually the very thing the run was done for — absent
        from the screen with nothing anywhere saying why. Showing it under its own
        heading is the honest answer, and it is one the operator can see.
        """
        try:
            _, found = discover(root)
        except OSError:
            # A folder that has become unreadable mid-run is not a reason to lose
            # what is already on screen.
            return
        with self._lock:
            spoken_for = self._spoken_for(root)
        unknown = [name for name in found if name not in spoken_for]
        if not unknown:
            return
        # Working out what kind of acquisition a store is means reading its small
        # description file, so it is done without the lock held: a folder on a
        # network share can take a moment to answer, and no other request should wait
        # on that. Only genuinely new stores are read, so for almost every look this
        # costs nothing at all.
        kinds = {name: _acquisition_of(root, name) for name in unknown}
        with self._lock:
            # Asked again with the lock held: several requests can be looking in the
            # same folder at once, and another one may have placed these stores while
            # this one was reading their descriptions.
            spoken_for = self._spoken_for(root)
            for name in unknown:
                if name in spoken_for:
                    continue
                self._place(root, name, kinds[name])
                spoken_for.add(name)

    def _spoken_for(self, root: Path) -> set[str]:
        """The stores in a folder that are already accounted for. With the lock held.

        Either some open dataset holds the store, or the operator has closed it and
        it is not to be brought back on the viewer's own initiative.

        Answered as a set rather than by looking through each dataset's list of
        stores, and that matters more than it looks. "Is this name already known?" is
        asked once per store found in the folder, and answering it by walking a list
        costs a little more each time the folder grows — which, in a folder of tens of
        thousands of positions, becomes the slowest thing the viewer does: measured at
        fifteen seconds a look, on a question asked whenever anything is announced.
        """
        spoken = {name for folder, name in self._let_go if folder == root}
        for dataset in self._datasets.values():
            if dataset.root == root:
                spoken.update(dataset.stores)
        return spoken

    def _place(self, root: Path, name: str, kind: Acquisition) -> None:
        """Put a store that has just appeared where it belongs. With the lock held.

        It joins the oldest watched dataset of this folder that it could be a piece
        of, which during a run is the acquisition being written. Where there is none
        it becomes a dataset of its own — see :meth:`_look_again` for why that, and
        not a refusal, is the answer while a folder is being watched.
        """
        for number in sorted(self._datasets):
            dataset = self._datasets[number]
            if dataset.root != root or not dataset.watch:
                continue
            if _same_acquisition(dataset.acquisition, kind):
                dataset.stores.append(name)
                if dataset.acquisition is None and (kind[0] or kind[1] is not None):
                    # The dataset was opened before any of its stores said what they
                    # were, which happens when a folder is opened the instant its
                    # first store becomes readable. This is the first chance to know.
                    dataset.acquisition = kind
                return
        number = self._next
        self._next += 1
        self._datasets[number] = Dataset(
            number=number,
            root=root,
            name=self._heading_for(root, name, number),
            stores=[name],
            channels=_channels_of(root, [name]),
            # It arrived in a folder that is still being written, so it is treated as
            # live and watched in its own right: its own further positions will land
            # in the same folder and should join it rather than start again.
            live=True,
            watch=True,
            acquisition=kind,
        )

    def _heading_for(self, root: Path, store_name: str, number: int) -> str:
        """What to call a dataset the viewer opened on its own. With the lock held.

        The kind of scan from the store's name — "targetscan" — because that is what
        the operator would call it. It has to differ from every other heading in the
        same folder: two headings reading the same thing leave the operator unable to
        tell which is which, and closing one of them would close both. So where the
        obvious name is taken the store's full name is used, and failing that the
        dataset's own number, which is unique for the life of the session.
        """
        taken = {dataset.name for dataset in self._datasets.values() if dataset.root == root}
        kind = _acquisition_type_in(store_name)
        whole = without_format_suffix(store_name)
        for candidate in (kind, whole, f"{kind} ({number})", f"{whole} ({number})"):
            if candidate not in taken:
                return candidate
        return f"{whole} ({number})"

    # -- noticing a change without reading anything ------------------------

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
            # above would miss it. The folder that gains an entry as each moment is
            # written therefore gets a look too.
            #
            # *Which* folder that is has to be asked rather than assumed, and this
            # is where it went wrong. It used to be taken as the full-size copy's
            # own folder, ``0`` inside the store, which is right for OME-Zarr 0.4.
            # A 0.5 store is built on zarr version 3, which files every piece under
            # a folder called ``c`` inside that one -- so a frame landing changed
            # ``0/c`` and left ``0`` untouched, this answer never moved, and the
            # viewer went on showing the length it read when the page opened. A
            # timelapse watched live simply stopped growing, for the rest of the
            # session, on the format this project is aiming at.
            #
            # It is asked through the same function the frame counting uses, which
            # is the point: the two were taught separately and one of them was
            # missed. Its answer is remembered against the description file's own
            # modification time, so this costs a couple of extra glances at
            # something the operating system already knows and no file reading at
            # all after the first look.
            for name in names:
                try:
                    marks.append(str(_moments_folder(root / name / "0").stat().st_mtime_ns))
                except OSError:
                    marks.append("?")
        # What is returned is a short fingerprint of all that rather than the marks
        # themselves. The viewer only ever compares this answer with the previous
        # one, so it does not need to be readable -- and with several hundred
        # acquisitions open the marks run to tens of thousands of characters, which
        # would then be sent across several times a second for no reason at all.
        return hashlib.blake2b("|".join(marks).encode("utf-8"), digest_size=16).hexdigest()

    # -- the two questions the server asks ---------------------------------

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

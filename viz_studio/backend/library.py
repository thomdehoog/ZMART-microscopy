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

from pathlib import Path

from stores import discover, split_name


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
        number = self._next
        self._next += 1
        self._roots[number] = parent.resolve()
        self._stores[number] = list(chosen)
        self._watch[number] = watch if watch is not None else (names is None)
        return number

    def close(self, number: int) -> bool:
        """Stop serving a folder. Returns whether it was open at all."""
        self._stores.pop(number, None)
        self._watch.pop(number, None)
        return self._roots.pop(number, None) is not None

    def close_group(self, group: str) -> list[int]:
        """Close every image belonging to one acquisition type.

        The panel offers closing by acquisition type rather than by folder,
        because that is the unit an operator thinks in. A folder that has nothing
        left in it afterwards is closed with them.
        """
        emptied = []
        for number, names in list(self._stores.items()):
            kept = [name for name in names if split_name(name)[0] != group]
            if kept == names:
                continue
            if kept:
                self._stores[number] = kept
                # Stop watching, or the closed images would be found again on the
                # next look and reappear moments after being dismissed.
                self._watch[number] = False
            else:
                self.close(number)
                emptied.append(number)
        return emptied

    # -- reading -----------------------------------------------------------

    def entries(self) -> list[tuple[int, Path, str]]:
        """Every open image as ``(folder number, folder, store name)``.

        A watched folder is looked at again here, which is what lets an acquisition
        written during a run turn up in the viewer on its own. Images named when the
        folder was opened keep their place at the front, so the order does not
        rearrange itself as new ones arrive; anything that has since been removed
        from disk quietly drops out.
        """
        out = []
        for number in sorted(self._stores):
            root = self._roots[number]
            names = self._stores[number]
            if self._watch.get(number):
                names = self._present(root, names)
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
        return known + [name for name in found if name not in known]

    def revision(self) -> str:
        """A short summary of the open folders that changes when their contents do.

        The viewer needs to know when a new acquisition has appeared, and asking
        the full question — what is here, what channels, how bright — means reading
        every store's description, which is far too heavy to repeat often. A
        folder's own modification time changes whenever something is added to or
        removed from it, and reading that is a single, very cheap question. So the
        viewer can ask this many times a second and only ask the expensive question
        when the answer has moved.

        It notices new acquisitions, which is exactly what needs noticing. It does
        not notice pieces of image written inside a store that is already open, and
        does not need to: the engine fetches those when you navigate to them.
        """
        marks = []
        for number in sorted(self._roots):
            root = self._roots[number]
            try:
                marks.append(f"{number}:{root.stat().st_mtime_ns}")
            except OSError:
                # A folder that cannot be read right now (a share hiccuping) should
                # not read as "everything changed" and trigger a needless rebuild.
                marks.append(f"{number}:?")
            marks.append(f"n{len(self._stores.get(number, ()))}")
        return "|".join(marks)

    def is_empty(self) -> bool:
        return not any(self._stores.values())

    def primary_root(self) -> Path | None:
        """The first folder opened, which is where drawn targets are saved.

        Targets belong beside the images they refer to. With several folders open
        there is no single obviously-right place, so the one the viewer was started
        on is used — it is the run being worked on, and the others were added to
        look at.
        """
        for number in sorted(self._roots):
            return self._roots[number]
        return None

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
        root = self._roots.get(int(number))
        if root is None:
            return None
        target = (root / rest).resolve()
        if root not in target.parents and target != root:
            return None
        return target

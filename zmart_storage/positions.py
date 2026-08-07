"""Write a run one position at a time, and let the viewer watch it fill in.

This is the smallest arrangement that gives an operator a live picture of a smart
experiment, and it holds only what is strictly necessary to do that.

What a run leaves on disk::

    experiment/
      overview.ome.zarr/      open this in the viewer. One image, and it holds
        zarr.json             no picture of its own beyond the zoomed-out copies.
        0/ 1/ 2/ 3/
      positions/
        overview_pos00000.ome.zarr      one position, exactly as the camera saw it
        overview_pos00001.ome.zarr
      zmart-links/            ours: which piece of the picture is which position
      zmart-coverage/         ours: where the run has actually imaged so far

A smart experiment usually has more than one kind of scan — a wide survey and the
detailed scans it led to — and each gets a run of its own, so ``overview.ome.zarr``
and ``targetscan.ome.zarr`` sit side by side at the top with their positions
together in one ``positions`` folder. They are told apart by the name each
position carries, which it needs anyway to be worth anything on its own; a folder
per kind was tried and only repeated the name one level up.

Three things sit at the top and each is one idea. **The image you open**, which is
a view: it stores no full-size picture at all and instead says which piece of the
picture is which piece of which position. **The positions**, which is where every
voxel really lives, each an ordinary OME-Zarr image that opens on its own in
napari or Fiji or anything else. And **our own two folders**, kept beside the
images rather than inside them so that nothing we invented ever appears inside an
image somebody else might open.

Why not simply give the viewer the positions
--------------------------------------------

Because it cannot hold them. The viewer draws with neuroglancer, which builds
drawing layers for every image it is given, so a run of a few thousand positions
never really opens. Handed one image it does not matter what is underneath: the
drawing rate measured flat from a hundred positions to six thousand four hundred.

And why not copy the positions into one big image, which would also give the
viewer one thing to open? Because that writes every voxel twice — once as the
position and once as the copy — and a run is large enough that the second copy is
a real cost in disk, in time, and in waiting. Nothing here is copied.

Opening a run in napari, Fiji, or anything else
-----------------------------------------------

**Point other software at ``positions``, never at the picture.** This is the one
thing about the arrangement that will surprise somebody, and it is worth reading
before it does.

Each position is an ordinary OME-Zarr image with its own zoomed-out copies and its
own place on the stage recorded inside it. Opening the ``positions`` group, or any
single position in it, gives exactly what you would expect anywhere else. Nothing
about being pointed at changes a position, and no tool needs to know this project
exists to read one.

The **picture** is a different thing and does not travel. It holds no voxels at
all: every piece of it is answered, while the viewer is open, by the viewer's own
server handing over a position's file. Read straight off the disk by anything
else, it is an image full of nothing.

And it fails in the worst way available, which is why this note is here rather
than in a footnote. It does not refuse to open, and it does not warn. It opens
perfectly — the right number of levels, the right size, the right voxel size, the
right channels — and every voxel in it is nought. Someone opening a run this way
sees a black picture and reasonably concludes their acquisition is empty::

    opened with plain zarr        levels    shape        max    mean
    the picture                   0, 1, 2   1024 x 1024      0       0
    one position                  0, 1, 2    512 x 512    3919    2500

That is the price of not copying, and it is worth being clear that it is a price
rather than an oversight. The alternative — writing the whole run a second time
into one image so that any reader could open it — is the thing this arrangement
exists to avoid, and on a real acquisition it is a second copy of a great many
gigabytes.

If a colleague needs one file they can open anywhere, the honest answer today is
to give them the positions, or to write them a stitched image on purpose. There is
no way to have a single openable picture and no second copy at the same time.

What this deliberately does not do
----------------------------------

**Overlapping positions are not handled.** Each position is placed where it says
it is, and if two of them cover the same ground the later one simply wins for the
pieces they share. Deciding that properly — which position supplies a shared piece,
and how to trim the seam — is a real piece of work with a plan of its own in
``viz_studio/PLAN_showing_many_stores_as_one.md``. It is not needed to watch a run
arrive, so it is not here.

**A position has to begin on a whole piece boundary.** A view hands a position's
own file to the browser untouched, so the bytes asked for have to *be* that file.
:func:`Run.write` refuses a position that does not line up rather than drawing it
a little wrong. A stage that drifts by a voxel or two will trip this, and the fix
belongs in the acquisition — see the same plan.
"""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np

import zarr

from .canvas import _IMAGE_SUFFIX, Channel, _declare_one
from .linked import GrowingLinkedView, LinkedView, PlacedTile, start_a_growing_view

# The folder the positions go in, inside the run's own folder, with one folder per
# acquisition type inside that. A smart experiment usually has more than one kind
# of scan — a wide survey and the detailed scans it led to — and they are separate
# pictures at different magnifications, so each keeps its positions apart.
POSITIONS_FOLDER = "positions"


def how_many_copies_a_position_can_keep(
    tile_shape: tuple[int, int, int], piece: int
) -> int:
    """How many zoomed-out copies one position can usefully keep, counting itself.

    This is the number that decides whether the picture the viewer opens has to
    write anything at all, so it is worth understanding rather than tuning.

    A view points at a position's own zoomed-out copies instead of computing its
    own, which it may do because shrinking here keeps every second voxel rather
    than averaging four — so a voxel of a position's smaller copy is a voxel of the
    whole picture's smaller copy, and belongs to that one position and no other.

    Halving stops when a copy would be smaller than one piece, because a piece is
    the smallest thing that can be handed to the browser. A position 2048 voxels
    across kept in pieces of 128 therefore carries five copies — 2048, 1024, 512,
    256, 128 — and a view over such positions writes no picture at any zoom.

    **The catch, and it is the reason a run can end up writing copies anyway.** A
    position has to begin on a multiple of the piece size times the largest shrink,
    or its copy would keep a different set of voxels from the ones the picture
    would have kept — a different picture, not a rounding difference. A position
    the same size as a piece can only ever carry one copy, whatever is asked for.
    """
    across = min(int(tile_shape[1]), int(tile_shape[2]))
    kept = 1
    while across // 2 >= int(piece):
        across //= 2
        kept += 1
    return kept


class _Position:
    """One place on the stage, stored whole, with its own zoomed-out copies.

    An ordinary OME-Zarr image and nothing more. It is written here rather than
    borrowed from :mod:`zmart_storage.cropped` because that module writes a second
    trimmed copy of the whole run beside the positions, which is exactly what this
    arrangement exists to avoid.
    """

    def __init__(self, folder: Path, arrays: list) -> None:
        self.folder = folder
        self._arrays = arrays

    def put(self, picture: np.ndarray, *, frame: int, channel: int) -> None:
        """Store one position, and shrink it into each of its own smaller copies.

        The shrinking keeps **every second voxel** and discards the rest, which has
        to match how the picture's own copies would have been made, voxel for
        voxel. Averaging instead would give a smoother zoomed-out picture and
        quietly break the whole arrangement: a coarse voxel would then be made of
        four fine ones, which near the edge of a position come from its neighbour,
        and no position could supply that piece on its own.
        """
        for level, array in enumerate(self._arrays):
            factor = 2 ** level
            array[frame, channel] = (picture if factor == 1
                                     else picture[:, ::factor, ::factor])


class Run:
    """A run being acquired, writing each position as it arrives.

    Made by :func:`start_a_run`. Hand it a position with :meth:`write` as it comes
    off the camera and close it with :meth:`finish`, or use it in a ``with`` block
    so it is closed even if the acquisition fails::

        with start_a_run(folder, name="overview", room=(1, 8192, 8192),
                         tile_shape=(1, 512, 512), voxel_size_um=(2.0, 0.35, 0.35),
                         channels=[Channel("488", window=(0, 4000))]) as run:
            for picture, where in as_they_arrive():
                run.write(picture, at=where)

    The viewer may be open on the run throughout, and should be — watching the
    picture fill in is the point. It notices the list of pointers changing and
    reads it again, and the list is replaced in a single step so a reader never
    catches it half written.
    """

    def __init__(self, folder: Path, *, name: str,
                 room: tuple[int, int, int], tile_shape: tuple[int, int, int],
                 voxel_size_um: tuple[float, float, float],
                 origin_um: tuple[float, float, float],
                 channels: list[Channel], frames: int, dtype: str, piece: int,
                 levels: int | None, ome_zarr_version: str) -> None:
        self.folder = Path(folder)
        self.name = name
        # The positions sit inside the picture itself, so the whole run is one
        # zarr: one thing to open, to move and to copy, with nothing of ours loose
        # beside it. The folder holding them is made a proper zarr **group**
        # rather than a plain folder, and that is not decoration — an ordinary
        # folder inside an image makes zarr warn whoever opens the run in other
        # software ("Object at positions is not recognized as a component of a
        # Zarr hierarchy"), while a group is simply part of the hierarchy and
        # passes without comment.
        self.positions_folder = (
            self.folder / f"{name}{_IMAGE_SUFFIX}" / POSITIONS_FOLDER)
        self.positions_folder.mkdir(parents=True, exist_ok=True)
        zarr.open_group(str(self.positions_folder), mode="a",
                        zarr_format=3 if ome_zarr_version == "0.5" else 2)

        self._room = tuple(int(n) for n in room)
        self._tile_shape = tuple(int(n) for n in tile_shape)
        self._voxel_size_um = tuple(float(n) for n in voxel_size_um)
        self._origin_um = tuple(float(n) for n in origin_um)
        self._channels = list(channels)
        self._frames = int(frames)
        self._dtype = dtype
        self._piece = int(piece)
        self._levels = levels
        self._ome_zarr_version = ome_zarr_version
        # How many copies each position keeps of itself. This is what lets the
        # picture the viewer opens store nothing at all: it points at these instead
        # of computing its own, so a run holds each voxel once and only once.
        self._position_levels = how_many_copies_a_position_can_keep(
            self._tile_shape, self._piece)  # type: ignore[arg-type]

        # Which position store belongs to each place on the stage, and the array
        # inside it. A place visited again — in another colour, or at a later
        # moment — writes into the image it wrote into the first time, so that
        # everything recorded of one field of view stays together.
        self._written: dict[tuple[int, int, int], object] = {}
        # Which places the view has already been told about. A position imaged
        # again — in another colour, or at a later moment — writes into the same
        # image and must not be added to the view a second time.
        self._told_the_view: set[tuple[int, int, int]] = set()
        # The view is started by the *first* position rather than here, because it
        # has to be told what the positions look like and the honest way to know
        # that is to read one that exists.
        self._view: GrowingLinkedView | None = None
        # One lock over both, because two threads arriving at the same new place in
        # the same breath would otherwise each declare an image for it and one
        # would empty the other's.
        self._lock = threading.Lock()
        self._open = True

    @property
    def path(self) -> Path | None:
        """The image to open in the viewer, or ``None`` before the first position.

        There is nothing to open until something has been imaged: the view is
        declared by the first position, because what it has to say about itself is
        read out of a position rather than guessed.
        """
        return None if self._view is None else self._view.path

    @property
    def positions(self) -> int:
        """How many places on the stage have been imaged so far."""
        return len(self._written)

    def write(self, picture: np.ndarray, *, at: tuple[int, int, int],
              channel: int = 0, frame: int = 0) -> Path:
        """Store one position and put it into the picture the viewer is watching.

        Args:
            picture: what the camera recorded, as ``(z, y, x)``, the size this run
                was declared with.
            at: where this position's low corner sits in the whole picture, in
                voxels, as ``(z, y, x)``. This is the stage position expressed in
                voxels from the run's own corner.
            channel: which colour this is, as a number into the channels the run
                was declared with.
            frame: which moment this is.

        Returns:
            The position's own OME-Zarr folder, which is an ordinary image and can
            be opened on its own.

        Raises:
            ValueError: if the run has been closed, if the picture is not the size
                this run was declared with, or if the position does not begin on a
                whole piece boundary — see the note at the top of this module about
                why that last one matters and where the fix belongs.
        """
        if not self._open:
            raise ValueError(
                "this run has been closed, so no more positions can be added to "
                "it. A run is held open for the length of an acquisition and "
                "closed once at the end."
            )
        picture = np.asarray(picture)
        if tuple(picture.shape) != self._tile_shape:
            raise ValueError(
                f"this position is {tuple(picture.shape)} voxels and the run was "
                f"declared with positions of {self._tile_shape}. Every position "
                "has to be the size the run declared, because the view works out "
                "where each one lands from that size — a different one would be "
                "drawn in the wrong place with nothing on screen to say so."
            )
        where = tuple(int(n) for n in at)

        with self._lock:
            store = self._written.get(where)
            if store is None:
                store = self._declare_the_position(where)
                self._written[where] = store
            store.put(picture, frame=frame, channel=channel)  # type: ignore[attr-defined]
            folder = store.folder  # type: ignore[attr-defined]
            if self._view is None:
                self._view = self._start_the_view(folder)
            # Added once per place, not once per picture. A position imaged again
            # in a second colour or a later moment goes into the same image, and
            # telling the view about it twice would put the same tile in the list
            # of pointers twice over.
            if where not in self._told_the_view:
                self._view.add(PlacedTile(store=folder, lands_at=where))  # type: ignore[arg-type]
                self._told_the_view.add(where)
        return folder

    def finish(self) -> LinkedView:
        """Close the run and hand back the finished view.

        Safe to call more than once; the second call simply describes what is
        already there.
        """
        with self._lock:
            if self._view is None:
                raise ValueError(
                    "this run imaged nothing, so there is no picture to finish. A "
                    "view is declared by the first position, because what it says "
                    "about itself is read out of a position rather than guessed."
                )
            if self._open:
                self._open = False
                return self._view.finish()
            return self._view.finish()

    def __enter__(self) -> Run:
        return self

    def __exit__(self, *_: object) -> None:
        if self._open and self._view is not None:
            self.finish()
        self._open = False

    # -- the two halves of writing a position ------------------------------

    def _declare_the_position(self, where: tuple[int, int, int]) -> _Position:
        """Write the empty image for one place on the stage, at its true corner.

        The corner recorded is where this position really sits, so opening the
        positions folder in napari or Fiji lays them out as the specimen rather
        than piling them all on the origin.
        """
        number = len(self._written)
        depth_max = int(np.iinfo(np.dtype(self._dtype)).max)
        corner_um = tuple(
            self._origin_um[axis] + where[axis] * self._voxel_size_um[axis]
            for axis in range(3)
        )
        arrays = _declare_one(
            self.positions_folder / f"{self.name}_pos{number:05d}.ome.zarr",
            canvas_shape=self._tile_shape,  # type: ignore[arg-type]
            frames=self._frames,
            channels=len(self._channels),
            dtype=self._dtype,
            chunk=self._piece,
            levels=self._position_levels,
            voxel_size_um=self._voxel_size_um,  # type: ignore[arg-type]
            origin_um=corner_um,  # type: ignore[arg-type]
            channel_blocks=[one.described(depth_max) for one in self._channels],
            ome_zarr_version=self._ome_zarr_version,
        )
        return _Position(
            self.positions_folder / f"{self.name}_pos{number:05d}.ome.zarr", arrays)

    def _start_the_view(self, like: Path) -> GrowingLinkedView:
        """Declare the view, once the first position exists to describe it.

        Everything the view says about itself — how large a voxel is, what the
        colours are called, how a piece is stored — is read out of that position,
        so there is nothing to state twice and get different both times.
        """
        view = start_a_growing_view(
            self.folder,
            like=PlacedTile(store=like, lands_at=(0, 0, 0)),
            view_shape=self._room,  # type: ignore[arg-type]
            name=self.name,
            levels=self._levels,
            origin_um=self._origin_um,  # type: ignore[arg-type]
            discard_existing_run=True,
            # The positions are already inside this folder, and declaring an image
            # normally empties the folder it is declared in. Naming them here is
            # what makes the writer step around them — without it, the first
            # position would be deleted by the picture that is meant to show it.
            keeps_its_tiles_in=POSITIONS_FOLDER,
        )
        return view


def start_a_run(
    folder: str | Path,
    *,
    name: str = "overview",
    room: tuple[int, int, int],
    tile_shape: tuple[int, int, int],
    voxel_size_um: tuple[float, float, float],
    channels: list[Channel],
    origin_um: tuple[float, float, float] = (0.0, 0.0, 0.0),
    frames: int = 1,
    dtype: str = "uint16",
    piece: int = 128,
    levels: int | None = None,
    ome_zarr_version: str = "0.5",
) -> Run:
    """Begin a run that writes each position as it arrives and shows it at once.

    Nothing is written here beyond a folder: the picture the viewer opens is
    declared by the first position, because what it has to say about itself is
    read out of a position rather than guessed at.

    Args:
        folder: the run's own folder. Everything the run produces goes inside it,
            so it is the one thing to copy or move afterwards.
        name: what this kind of scan is called — ``overview``, ``targetscan``. The
            operator sees it as the heading in the viewer's panel, and a smart
            experiment holding more than one kind keeps each in its own run.
        room: how large the whole picture may become, as ``(z, y, x)`` in voxels.
            This has to be decided before the run because the viewer may be reading
            the description throughout. Across the specimen, the stage's travel
            range is a good choice: the stage cannot reach outside it, and room
            that holds no position costs practically nothing on disk.
        tile_shape: how large one position is, as ``(z, y, x)`` in voxels.
        voxel_size_um: how large one voxel is, as ``(z, y, x)`` in micrometres.
        channels: the colours this run records. See
            :class:`zmart_storage.canvas.Channel`, and give each one the brightness
            window it should be shown between rather than the camera's whole range.
        origin_um: where the picture's corner sits on the stage, in micrometres.
        frames: how many moments the run will record.
        dtype: the kind of number a voxel holds.
        piece: how large a piece of the picture is, in voxels across y and x. Every
            position has to begin on a multiple of this, because the view hands a
            position's own file to the browser untouched.
        levels: how many progressively smaller copies the picture keeps, counting
            the full-size one. Normally left out, so the size of the picture
            decides — which is what keeps a large run opening quickly.
        ome_zarr_version: which generation of OME-Zarr to write, ``"0.5"`` or
            ``"0.4"``. 0.5 is the default here because it is the current standard;
            choose 0.4 if something that will read the run cannot manage 0.5.

    Returns:
        A :class:`Run`, ready to be handed positions.
    """
    return Run(
        Path(folder),
        name=name,
        room=room,
        tile_shape=tile_shape,
        voxel_size_um=voxel_size_um,
        origin_um=origin_um,
        channels=list(channels),
        frames=frames,
        dtype=dtype,
        piece=piece,
        levels=levels,
        ome_zarr_version=ome_zarr_version,
    )

"""What a transfer from another microscope is, read out of the transfer itself.

A mesoSPIM transfer is a bare container group holding one OME-Zarr image per tile,
each saying where on the stage it was taken from. Nothing in it says how the tiles
fit together, because nothing needs to: every tile carries its own corner in
micrometres, and the arrangement follows from those.

Why this is a module of its own
-------------------------------

:mod:`zmart_storage.linked` builds one picture by **pointing** at the tiles' files,
which is free but demands that the tiles sit on a common grid of whole chunks. A
transfer was arranged by nobody, and typically does not: the Thy1 set steps 4547.06
voxels between rows, which is not a whole number of anything.

So a transfer is shown by **building** instead — laying whichever tiles reach into
a piece of the picture into one array and handing that back. That works at any
offset at all, including a fractional one, and needs nothing rewritten. This module
is the half that works out the arrangement; :mod:`composer` is the half that builds.

The one decision worth arguing about
------------------------------------

A tile lands at a fractional position, and the built picture is a grid of whole
voxels, so a tile has to be **rounded to the nearest voxel** of whichever copy is
being drawn. At full resolution that rounding is 0.06 of a voxel on the Thy1 set,
a hundredth of a micrometre, far below what the objective resolves.

The coarser copies are where this needs stating carefully, because an earlier
version of this note got it wrong. It claimed the rounding was not a loss, since a
copy shrunk eight times cannot express a position more finely than one of its own
voxels. That is true of any *one* copy and it hid the thing that matters: two
copies can disagree with *each other*, and that is what shows on screen, as detail
sliding when you zoom.

So the bound is worth stating outright rather than argued away. **A copy sits
within half of one of its own voxels of where full resolution puts the same
specimen** — see :meth:`Mosaic.lands_at` for how that is held to. The drawing
engine picks the copy whose voxels are about one screen pixel, so this is half a
screen pixel at any zoom, and it does not grow as you zoom out. Where it could
be seen is a seam: two neighbouring tiles may round opposite ways, so their
displacement relative to one another is a whole coarse voxel rather than half.

``check_the_pyramid.py`` measures it, through micrometres rather than through the
code here.

What none of this is is the rounding that breaks pointing. That one rounds to the
nearest whole **chunk**, hundreds of voxels at a time, which is why it is refused
rather than done.
"""

from __future__ import annotations

import json
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import zarr

# The name every OME-Zarr image folder ends in. A transfer holds one per tile, and
# anything else in the container -- a coverage record, a note of somebody's
# annotations -- is not a tile and is skipped.
IMAGE_SUFFIX = ".ome.zarr"

# The key, beside the format's own, under which a tile may say how far it is
# turned. OME-Zarr 0.5 has nowhere to put a rotation, so this is ours; a tile
# without one is not turned.
OURS_IN_THE_DESCRIPTION = "zmart"


@dataclass
class Copy:
    """One resolution of one tile: how large it is, where it sits, and its pixels.

    **The pixels are not opened until something reads them**, and that is the whole
    point of this class rather than holding a :class:`zarr.Array` outright.
    Opening a transfer needs to know where every tile is and how large — the index
    is built from all of them at once — and none of that needs an opened array.
    Measured on Thy1: reading each resolution's description as plain JSON costs
    0.58 ms a tile, and opening them through zarr costs 4.84 ms, so eight times
    the work was being done to learn a shape that was written in a file.

    Attributes:
        held_in: the folder this resolution's picture is stored in.
        shape: how large it is, as ``(z, y, x)`` in voxels.
        chunks: how much of it is kept in one file, as ``(z, y, x)``.
        voxel_um: how large one of its voxels is, as ``(z, y, x)`` in micrometres.
        corner_um: where its first voxel sits on the stage, as ``(z, y, x)``.
    """

    held_in: Path
    shape: tuple[int, int, int]
    chunks: tuple[int, int, int]
    dtype: str
    voxel_um: tuple[float, float, float]
    corner_um: tuple[float, float, float]
    # How much room the store keeps along the axes in front of (z, y, x) --
    # (t, c) for a governed position, empty for a plain three-axis tile. The
    # composer reads a requested (moment, channel) against this room, and
    # the picture's own description grows the axes when there is more than
    # one frame of room (see ``Mosaic.frame_room``).
    outer_shape: tuple[int, ...] = ()
    # Whether one stored block of this copy actually exists on disk, asked with
    # the block's (z, y, x) coordinate. ``None`` -- every transfer's tile --
    # means nobody promised anything: zarr's fill value is the honest answer
    # for an absent chunk. A governed run's committed position sets this,
    # because there the pixels were promised by a commit and an absent chunk
    # is damage to fail closed on, never plausible fill.
    presence: object | None = field(default=None, repr=False, compare=False)
    _opened: zarr.Array | None = field(default=None, repr=False)

    @property
    def array(self) -> zarr.Array:
        """The pixels, opened the first time anything asks for them.

        Not guarded. Two threads racing here both open the array and one of them
        wins, which costs a few milliseconds once and is correct either way — a
        lock held across every read of every tile would cost far more than it
        could ever save.
        """
        if self._opened is None:
            self._opened = zarr.open_array(str(self.held_in), mode="r")
        return self._opened


@dataclass
class Tile:
    """One position of a transfer, with every copy of its picture it keeps."""

    name: str
    store: Path
    copies: list[Copy]
    # How far this tile is turned about its own centre, in radians, anticlockwise
    # in the plane across the specimen. Nought for an ordinary transfer, and that
    # is the case worth keeping fast: a tile that is not turned is copied
    # rectangle by rectangle, exactly, and only a turned one is resampled.
    #
    # OME-Zarr 0.5 defines scale and translation and not rotation, so there is
    # nowhere in the format to put this. It is read from a field of ours beside
    # the format's own, and a transfer that does not carry one is simply not
    # turned -- which is every transfer anybody has actually sent us.
    turned: float = 0.0
    # What this tile's axes mean, kept from the one reading of its description.
    # Comparing tiles needs it, and reading every description a second time to
    # get it cost more than the whole of the rest of opening.
    axes: tuple[str, ...] = ()
    # Which moments of this tile have been PUBLISHED, where a record governs
    # it (a live run's manifest). ``None`` — every transfer and built picture —
    # means no record governs the tile and its files are the honest truth.
    # A governed tile is skipped entirely for a moment this set does not name:
    # the ground serves as absent and the store is never opened, so pixels
    # written but not yet published cannot leak onto anybody's screen.
    moments: frozenset[int] | None = None

    def footprint(self, level: int, at: tuple[int, int, int]
                  ) -> tuple[int, int, int, int]:
        """The box this tile occupies across the specimen once it is turned.

        Returned as ``(top, bottom, left, right)`` in the picture's own voxels at
        this resolution. For a tile that is not turned this is simply where it
        lands and how large it is; for a turned one it is the box around its four
        corners, which is what has to be indexed, since a turned tile reaches into
        pieces its unturned self would not.
        """
        held = self.copies[level].shape
        if not self.turned:
            return at[1], at[1] + held[1], at[2], at[2] + held[2]
        middle = (held[1] / 2, held[2] / 2)
        cos, sin = math.cos(self.turned), math.sin(self.turned)
        corners = []
        for down in (-middle[0], middle[0]):
            for across in (-middle[1], middle[1]):
                corners.append((down * cos - across * sin + middle[0] + at[1],
                                down * sin + across * cos + middle[1] + at[2]))
        return (math.floor(min(one[0] for one in corners)),
                math.ceil(max(one[0] for one in corners)),
                math.floor(min(one[1] for one in corners)),
                math.ceil(max(one[1] for one in corners)))

    @property
    def keeps(self) -> int:
        """How many copies of its picture this tile holds, counting full size."""
        return len(self.copies)


@dataclass
class Mosaic:
    """A whole transfer: its tiles, where each lands, and how large the picture is.

    Everything here is derived from the tiles and nothing is supplied, for the
    reason :mod:`zmart_storage.linked` gives at length: a number stated twice can be
    stated differently the second time, and the picture would be wrong with nothing
    on screen to say so.
    """

    tiles: list[Tile]
    levels: int
    axes: tuple[str, ...]
    dtype: str
    corner_um: tuple[float, float, float] = field(default=(0.0, 0.0, 0.0))
    # Whether the tiles' coarser copies were made by AVERAGING blocks rather
    # than by taking every second voxel. It decides the picture's per-level
    # registration: an averaged coarse voxel's centre sits half a fine voxel
    # along each halved axis, so each level's declared translation must step
    # by (voxel_L - voxel_0) / 2 — where a decimated copy's centre IS a fine
    # voxel's centre and must not be shifted. Declared wrong either way, the
    # levels draw a fixed diagonal apart, and the operator sees any one-frame
    # level substitution as a deterministic top-left twitch. False for
    # transfers (mesoSPIM decimates); a governed run's writer averages and
    # says so.
    averaged: bool = False

    # Where every tile lands, and how large the picture is, worked out once per
    # resolution and kept.
    #
    # This was a method that recomputed from micrometres each time, which read
    # more honestly -- nothing cached, nothing to fall out of step -- and cost far
    # too much to keep. Building one piece asks where the tiles are three times
    # over, and at four thousand tiles that was 89 milliseconds a piece against
    # the 9 the reading itself takes. The arithmetic cannot change while a
    # transfer is open, since it comes from descriptions on disk that are not
    # being written, so working it out once is safe as well as necessary.
    _placed: dict[int, list[tuple[Tile, tuple[int, int, int]]]] = field(
        default_factory=dict, repr=False)
    _shape: dict[int, tuple[int, int, int]] = field(
        default_factory=dict, repr=False)
    _room: tuple[int, int] | None = field(default=None, repr=False)

    @property
    def frame_room(self) -> tuple[int, int]:
        """How many (moments, channels) the tiles' stores keep room for.

        The writer declares this room when it first makes an array — the
        arrays themselves are the durable declaration (see
        ``zmart_live.coordinator``) — so the first tile that carries the
        front axes is the place to read it. ``(1, 1)`` — every plain
        three-axis tile — means a flat picture: one frame, no time or
        colour room, and the picture's own description stays three axes.
        Anything more and the served picture grows the (t, c) axes.

        Remembered after the first ask: the answer is read from immutable
        descriptions, and this is asked on every served piece.
        """
        if self._room is None:
            found = (1, 1)
            for tile in self.tiles:
                for copy in tile.copies:
                    if len(copy.outer_shape) >= 2:
                        found = (int(copy.outer_shape[0]),
                                 int(copy.outer_shape[1]))
                        break
                else:
                    continue
                break
            self._room = found
        return self._room

    def voxel_um(self, level: int) -> tuple[float, float, float]:
        """How large one voxel of the built picture is at this resolution.

        Taken from the tiles rather than worked out by halving, because a transfer
        need not halve every axis at every step. The Thy1 set does not: its voxels
        are 1 micrometre deep against 0.17 across, so it leaves depth alone for
        three levels and only then begins halving it. Halving blindly would place
        every tile at twice its true depth from level three down.
        """
        return self.tiles[0].copies[level].voxel_um

    def lands_at(self, tile: Tile, level: int) -> tuple[int, int, int]:
        """Where a tile's first voxel goes in this copy of the picture, in voxels.

        The nearest whole voxel **of the copy being drawn**, worked out from the
        micrometres the tile itself records. Nothing else: not from another copy,
        and not from full resolution.

        **This was changed to derive the coarse copies from full resolution, and
        that was wrong.** The intent was to stop the copies disagreeing with one
        another. What it did was displace whole tiles: Thy1's middle column of
        tiles sits at 2659 voxels, so a coarse copy asked for ``round(2659 / 2)``
        -- exactly 1329.5, which Python rounds to *even* and gives 1330, where the
        tile really is at 1329.41 and the answer is 1329. Two of six tiles a whole
        voxel out, 31.8% of the picture wrong at one copy and 31.6% at the next,
        and right again further down. It was reported from the viewer as one zoom
        level being broken, which is exactly what it was.

        The lesson is worth keeping. Rounding each copy from micrometres puts every
        tile within **half a voxel of that copy** of where it truly is, which is the
        best any copy can do -- a copy shrunk eight times cannot say where something
        is more finely than one of its own voxels. Two copies can therefore still
        disagree by up to half a voxel each, and that is a floor rather than a
        fault. ``check_the_pyramid.py`` measured that floor, reported it as a
        failure, and this method was changed to satisfy it; chasing an unavoidable
        half voxel bought a real whole one.

        ``math.floor(x + 0.5)`` rather than ``round`` deliberately: the built-in
        rounds a half to the nearest even number, so two tiles half a voxel out go
        opposite ways depending on whether their neighbour's index happens to be
        odd. That is how a whole column of the specimen ends up displaced from the
        column beside it.
        """
        copy = tile.copies[level]
        voxel = self.voxel_um(level)
        return tuple(
            math.floor((copy.corner_um[axis] - self.corner_um[axis]) / voxel[axis]
                       + 0.5)
            for axis in range(3)
        )  # type: ignore[return-value]

    def placements(self, level: int) -> list[tuple[Tile, tuple[int, int, int]]]:
        """Every tile and where it lands at this resolution, worked out once."""
        found = self._placed.get(level)
        if found is None:
            found = [(tile, self.lands_at(tile, level)) for tile in self.tiles]
            self._placed[level] = found
        return found

    def shape(self, level: int) -> tuple[int, int, int]:
        """How large the built picture is at this resolution, in voxels."""
        found = self._shape.get(level)
        if found is None:
            placed = self.placements(level)
            found = tuple(
                max(at[axis] + tile.copies[level].shape[axis]
                    for tile, at in placed)
                for axis in range(3)
            )
            self._shape[level] = found  # type: ignore[assignment]
        return found  # type: ignore[return-value]

    def reaching_into(self, level: int, low: tuple[int, int, int],
                      high: tuple[int, int, int]) -> list[tuple[Tile, tuple[int, int, int]]]:
        """Which tiles cover any part of this box, and where each of them lands.

        This looks at every tile, which is right for a handful and wrong for
        thousands. :class:`composer.Composer` indexes the placements by which
        pieces they fall in and does not come through here; this stays because it
        says plainly what the question is, and is what a caller with no index
        should use.

        Args:
            level: which copy of the picture the box is measured in.
            low: the box's near corner, as ``(z, y, x)`` in that copy's voxels.
            high: the box's far corner, one past the last voxel.

        Returns:
            Each tile that overlaps the box at all, paired with where it lands.
        """
        return [
            (tile, at) for tile, at in self.placements(level)
            if all(max(low[axis], at[axis])
                   < min(high[axis], at[axis] + tile.copies[level].shape[axis])
                   for axis in range(3))
        ]


def _the_description_of(store: Path) -> tuple[dict, str]:
    """What a store says about itself, and which generation of OME-Zarr wrote it."""
    newer = store / "zarr.json"
    if newer.is_file():
        held = json.loads(newer.read_text(encoding="utf-8"))
        attributes = held.get("attributes") or {}
        return (attributes.get("ome") or attributes), "0.5"
    older = store / ".zattrs"
    if older.is_file():
        return json.loads(older.read_text(encoding="utf-8")), "0.4"
    raise ValueError(
        f"{store} does not look like an OME-Zarr image: it holds neither a "
        "zarr.json nor a .zattrs. A picture can only be built over images, so "
        "check this is the folder the transfer wrote rather than the one above it."
    )


def _how_a_resolution_is_stored(held_in: Path) -> tuple[tuple[int, ...],
                                                        tuple[int, ...], str]:
    """How large one resolution is, how it is chunked, and what a voxel holds.

    Read out of the array's own description rather than by opening it through
    zarr, which is the same answer for an eighth of the work. Both generations of
    the format are read, because a transfer may be written in either.
    """
    for name in ("zarr.json", ".zarray"):
        described = held_in / name
        if described.is_file():
            held = json.loads(described.read_text(encoding="utf-8"))
            shape = tuple(int(n) for n in held["shape"])
            if held.get("zarr_format") == 2:
                chunks = tuple(int(n) for n in held["chunks"])
                # Version 2 spells the kind of number the way numpy does --
                # "<u2" -- and the rest of this works in the plain name.
                kind = np.dtype(held["dtype"]).name
            else:
                grid = (held.get("chunk_grid") or {}).get("configuration") or {}
                chunks = tuple(int(n) for n in grid["chunk_shape"])
                kind = str(held["data_type"])
            return shape, chunks, kind
    raise ValueError(
        f"{held_in} holds no array description, so how its picture is stored "
        "cannot be read. That resolution was probably never finished being "
        "written."
    )


def _read_one_tile(store: Path) -> Tile:
    """Every resolution a tile keeps, each with its own voxel size and corner.

    OME-Zarr allows a position to be written beside each resolution or once for the
    image as a whole, and both are read here and added, which is what the format
    asks a reader to do. Only the whole-image one is shared; a reader that added
    every resolution's would move the tile once per copy it keeps.
    """
    described, _ = _the_description_of(store)
    multiscale = (described.get("multiscales") or [{}])[0]
    datasets = multiscale.get("datasets") or []
    axes = tuple(str(axis.get("name", ""))
                 for axis in multiscale.get("axes") or ())
    if not datasets:
        raise ValueError(
            f"{store} says it keeps no copies of its picture, so there is nothing "
            "to build from. That is either not an OME-Zarr image or was never "
            "finished being written."
        )

    shared = [0.0, 0.0, 0.0]
    for transform in multiscale.get("coordinateTransformations") or []:
        if transform.get("type") == "translation":
            moved = [float(n) for n in transform["translation"]]
            shared = [shared[axis] + moved[-3 + axis] for axis in range(3)]

    copies = []
    for dataset in datasets:
        voxel, corner = None, list(shared)
        for transform in dataset.get("coordinateTransformations") or []:
            if transform.get("type") == "scale":
                scale = [float(n) for n in transform["scale"]]
                voxel = (scale[-3], scale[-2], scale[-1])
            if transform.get("type") == "translation":
                moved = [float(n) for n in transform["translation"]]
                corner = [corner[axis] + moved[-3 + axis] for axis in range(3)]
        if voxel is None:
            raise ValueError(
                f"{store} does not say how large a voxel of its {dataset['path']!r} "
                "copy is, so a picture built over it could not be drawn to scale."
            )
        held_in = store / str(dataset["path"])
        shape, chunks, kind = _how_a_resolution_is_stored(held_in)
        # The spatial axes are the LAST three whatever the store keeps in front
        # of them -- a transfer's tile is plain (z, y, x), a governed run's
        # position is (t, c, z, y, x). What sits in front is recorded so a read
        # can hold it fixed; the scale and translation above already take the
        # last three of themselves for the same reason.
        copies.append(Copy(
            held_in=held_in,
            shape=tuple(shape[-3:]),  # type: ignore[arg-type]
            chunks=tuple(chunks[-3:]),  # type: ignore[arg-type]
            dtype=kind,
            voxel_um=voxel,
            corner_um=(corner[0], corner[1], corner[2]),
            outer_shape=tuple(shape[:-3]),
        ))
    ours = described.get(OURS_IN_THE_DESCRIPTION)
    turned = float((ours or {}).get("turned_radians") or 0.0)
    return Tile(name=store.name, store=store, copies=copies, axes=axes,
                turned=turned)


def _refuse_tiles_that_disagree(tiles: list[Tile]) -> str:
    """Stop a transfer whose tiles are not all the same kind of picture.

    **What has to agree here is much less than for a pointed-at view, and it is
    worth saying why.** :mod:`zmart_storage.linked` hands a tile's bytes to the
    viewer untouched, so it has to refuse tiles that differ in *anything* about
    how those bytes are laid out — the compression, the endianness, the chunking.
    Building decodes every tile and encodes the result itself, so all of that may
    differ freely: two tiles compressed differently make one perfectly good
    picture.

    Three things still cannot differ, and each fails silently rather than loudly,
    which is why they are checked at the door:

    - **the kind of number.** The built picture is declared as one type. A tile
      of another is read into it by numpy, which converts rather than complains:
      eight-bit specimen laid into a sixteen-bit picture is a black square, and
      sixteen into eight is wrapped-around noise. Nothing reports either.
    - **how large a voxel is.** Two magnifications are two acquisitions, not two
      tiles of one picture, and every tile's place is worked out by dividing
      micrometres by this. Getting it from the wrong tile puts the rest of the
      run in the wrong place.
    - **what the axes mean.** A tile stored depth-height-width beside one stored
      height-width-depth holds the same bytes for a different picture, and the
      only sign is a specimen that looks strange.

    Returns:
        The kind of number the whole transfer holds, since it has been read here.
    """
    first = tiles[0]
    kind = first.copies[0].dtype

    for tile in tiles[1:]:
        theirs = tile.copies[0].dtype
        if theirs != kind:
            raise ValueError(
                f"{first.store.name} holds {kind} and {tile.store.name} holds "
                f"{theirs}. A built picture is one image and is declared as one "
                "kind of number, so a tile of another would be converted into it "
                "silently — which is a black square or a field of noise, with "
                "nothing anywhere to report it.\n\n"
                "This usually means two acquisitions have been gathered into one "
                "folder. Build a picture over each of them separately."
            )
        for level, (ours, other) in enumerate(zip(first.copies, tile.copies,
                                                  strict=True)):
            if ours.voxel_um != other.voxel_um:
                raise ValueError(
                    f"{first.store.name} was taken with voxels of "
                    f"{ours.voxel_um} micrometres and {tile.store.name} with "
                    f"{other.voxel_um} (copy {level}). Those are two "
                    "magnifications, which makes them two acquisitions rather "
                    "than two tiles of one picture — and every tile's place is "
                    "worked out by dividing micrometres by this, so the rest of "
                    "the run would be drawn in the wrong place."
                )
    return kind


def read_the_transfer(folder: str | Path) -> Mosaic:
    """Open a transfer and work out how its tiles fit together.

    Args:
        folder: the container the transfer wrote — the folder holding one
            ``.ome.zarr`` per tile.

    Returns:
        The :class:`Mosaic`, from which the built picture follows.

    Raises:
        ValueError: if the folder holds no images, or if the tiles disagree about
            how many copies they keep or what their axes mean. Tiles are laid
            beside one another under a single description, so a disagreement there
            would draw one tile as though it were another kind of picture.
    """
    folder = Path(folder)
    stores = sorted(one for one in folder.glob(f"*{IMAGE_SUFFIX}") if one.is_dir())
    if not stores:
        raise ValueError(
            f"{folder} holds no OME-Zarr images, so there is nothing to build a "
            "picture from. A transfer is a container of one image per tile; this "
            "is probably the folder above it, or a single tile rather than the set."
        )

    # Read several tiles at once. Every tile costs a handful of small file reads
    # and almost no arithmetic, so this waits on the disk rather than on the
    # processor -- which is exactly the case threads help with, even in Python.
    # A survey is thousands of tiles and this is the whole of what opening one
    # costs, so it is worth the four lines.
    with ThreadPoolExecutor(max_workers=min(32, (len(stores) + 3) // 4 or 1)) as pool:
        tiles = list(pool.map(_read_one_tile, stores))

    keeps = {tile.keeps for tile in tiles}
    if len(keeps) != 1:
        raise ValueError(
            f"the tiles in {folder} disagree about how many copies of their picture "
            f"they keep — {sorted(keeps)}. The built picture offers the copies every "
            "tile has, so a run written two different ways has to be looked at as "
            "two runs."
        )

    axes = tiles[0].axes
    for tile in tiles[1:]:
        others = tile.axes
        if others != axes:
            raise ValueError(
                f"{tiles[0].store.name} stores its picture as {', '.join(axes)} "
                f"and {tile.store.name} as {', '.join(others)}. The same bytes "
                "read under two different meanings is a specimen that looks "
                "strange for no reason anybody can point at, so this is refused "
                "rather than drawn."
            )
    # Three axes is a plain spatial picture; five is one that also records
    # time and colour, and the built picture then grows those axes too (see
    # ``Mosaic.frame_room``). The mosaic's OWN axes stay the spatial three
    # either way -- the (t, c) room rides on each copy's ``outer_shape`` --
    # because everything spatial in here reasons in (z, y, x).
    if not (len(axes) == 3 or (len(axes) == 5 and tuple(axes[:2]) == ("t", "c"))):
        raise ValueError(
            f"{tiles[0].store} stores its picture as {', '.join(axes)}. This "
            "builds over tiles of three spatial axes — depth, height and "
            "width — optionally behind a (t, c) pair. Anything else has no "
            "agreed meaning to draw."
        )
    # The (t, c) room has to agree too: the picture is declared with ONE
    # room, and a tile keeping more moments than the declaration would have
    # its later moments silently unreachable -- the same wrong-picture class
    # the disagreement refusals below exist for.
    rooms = {tile.copies[0].outer_shape[:2] for tile in tiles}
    if len(rooms) > 1:
        raise ValueError(
            f"the tiles of {folder} keep different (t, c) room: "
            f"{sorted(rooms)}. One picture has one room, so a tile with more "
            "moments or channels than the declaration would quietly lose "
            "them. This is refused rather than drawn half-true."
        )

    kind = _refuse_tiles_that_disagree(tiles)

    corner = tuple(
        min(tile.copies[0].corner_um[axis] for tile in tiles) for axis in range(3)
    )
    return Mosaic(
        tiles=tiles,
        levels=tiles[0].keeps,
        axes=tuple(axes[-3:]),  # type: ignore[arg-type]
        dtype=kind,
        corner_um=corner,  # type: ignore[arg-type]
    )


def the_mosaic_written_down(mosaic: Mosaic) -> dict:
    """The whole geometry of a picture, as one plain description.

    Everything :func:`read_the_transfer` walks the tiles to learn -- where each
    sits, how large, in what chunks, at which magnifications -- written down so
    it never has to be walked again. Declaring a picture keeps this beside the
    picture's own description, and opening then reads one file however many
    positions the transfer holds: a 12,800-position survey cost 8.6 seconds of
    walking on this machine, and its geometry written down is two megabytes.

    The pixels are deliberately not touched by any of this. A copy's array
    still opens on its first read, exactly as before; only the walk to learn
    the geometry is gone.
    """
    return {
        "levels": mosaic.levels,
        "axes": list(mosaic.axes),
        "dtype": mosaic.dtype,
        "corner_um": list(mosaic.corner_um),
        "tiles": [
            {
                "name": tile.name,
                "store": tile.store.as_posix(),
                "turned": tile.turned,
                "axes": list(tile.axes),
                "copies": [
                    {
                        "held_in": copy.held_in.as_posix(),
                        "shape": list(copy.shape),
                        "chunks": list(copy.chunks),
                        "dtype": copy.dtype,
                        "voxel_um": list(copy.voxel_um),
                        "corner_um": list(copy.corner_um),
                        # The room along the store's front axes -- written
                        # only when there is one, so every flat picture's
                        # ledger stays byte-for-byte what it always was.
                        **({"outer_shape": list(copy.outer_shape)}
                           if copy.outer_shape else {}),
                    }
                    for copy in tile.copies
                ],
            }
            for tile in mosaic.tiles
        ],
    }


def read_the_mosaic_as_written(held: dict) -> Mosaic:
    """The mosaic back from its written-down geometry, touching no tile.

    The counterpart of :func:`the_mosaic_written_down`, and the reason opening
    a declared picture is immediate at any size. It trusts what was written the
    way the composer trusts any description on disk: the declaration was
    derived from the tiles by the same code that reads them, and a finished
    transfer does not change, so re-deriving it at every opening bought
    nothing but the wait.
    """
    tiles = [
        Tile(
            name=one["name"],
            store=Path(one["store"]),
            turned=float(one.get("turned", 0.0)),
            axes=tuple(one["axes"]),
            copies=[
                Copy(
                    held_in=Path(copy["held_in"]),
                    shape=tuple(copy["shape"]),
                    chunks=tuple(copy["chunks"]),
                    dtype=copy["dtype"],
                    voxel_um=tuple(copy["voxel_um"]),
                    corner_um=tuple(copy["corner_um"]),
                    outer_shape=tuple(copy.get("outer_shape", ())),
                )
                for copy in one["copies"]
            ],
        )
        for one in held["tiles"]
    ]
    return Mosaic(
        tiles=tiles,
        levels=int(held["levels"]),
        axes=tuple(held["axes"]),
        dtype=held["dtype"],
        corner_um=tuple(held["corner_um"]),
    )

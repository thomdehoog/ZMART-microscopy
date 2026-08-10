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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import zarr

# The name every OME-Zarr image folder ends in. A transfer holds one per tile, and
# anything else in the container -- a coverage record, a note of somebody's
# annotations -- is not a tile and is skipped.
IMAGE_SUFFIX = ".ome.zarr"


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
    voxel_um: tuple[float, float, float]
    corner_um: tuple[float, float, float]
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
        """Where a tile's first voxel goes in the built picture, in whole voxels.

        Full resolution is rounded from the micrometres the tile records. **Every
        coarser copy is then worked out from that**, rather than being rounded from
        the micrometres again on its own.

        The difference is not obvious and it was measured before it was believed.
        Rounding each copy separately lets them disagree with one another: a tile
        at 2658.82 voxels rounds to 2659 at full resolution, and 2658.82 halves to
        1329 while 2659 halves to 1329.5 — so the coarse copy put the specimen half
        one of its own voxels from where the fine copy put it, and each copy did
        that independently, so the disagreement could compound down the pyramid.
        On screen that is detail sliding as you zoom.

        Working the coarse copies out from full resolution does not make the
        rounding go away — 2659 is odd and cannot be halved — but it bounds the
        disagreement at half a voxel *of the copy being drawn*, with nothing
        accumulating. Since the drawing engine picks the copy whose voxels are
        about one screen pixel, that is half a screen pixel at any zoom.

        ``check_the_pyramid.py`` is what measures this, and it goes through
        micrometres rather than through this function, so it can catch this being
        got wrong.
        """
        at_full_resolution = tuple(
            int(round((tile.copies[0].corner_um[axis] - self.corner_um[axis])
                      / self.voxel_um(0)[axis]))
            for axis in range(3)
        )
        if level == 0:
            return at_full_resolution  # type: ignore[return-value]
        # How much smaller this copy is, per axis, read from the voxel sizes rather
        # than assumed to be two. A transfer need not shrink every axis at every
        # step: Thy1 leaves depth alone for three levels, its voxels being a
        # micrometre deep against 0.17 across.
        finest = self.voxel_um(0)
        voxel = self.voxel_um(level)
        return tuple(
            int(round(at_full_resolution[axis] / (voxel[axis] / finest[axis])))
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


def _placed_copies_of(store: Path) -> list[Copy]:
    """Every resolution a tile keeps, each with its own voxel size and corner.

    OME-Zarr allows a position to be written beside each resolution or once for the
    image as a whole, and both are read here and added, which is what the format
    asks a reader to do. Only the whole-image one is shared; a reader that added
    every resolution's would move the tile once per copy it keeps.
    """
    described, _ = _the_description_of(store)
    multiscale = (described.get("multiscales") or [{}])[0]
    datasets = multiscale.get("datasets") or []
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
        shape, chunks, _ = _how_a_resolution_is_stored(held_in)
        copies.append(Copy(
            held_in=held_in,
            shape=(shape[0], shape[1], shape[2]),
            chunks=(chunks[0], chunks[1], chunks[2]),
            voxel_um=voxel,
            corner_um=(corner[0], corner[1], corner[2]),
        ))
    return copies


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
        copies = list(pool.map(_placed_copies_of, stores))
    tiles = [Tile(name=store.name, store=store, copies=held)
             for store, held in zip(stores, copies, strict=True)]

    keeps = {tile.keeps for tile in tiles}
    if len(keeps) != 1:
        raise ValueError(
            f"the tiles in {folder} disagree about how many copies of their picture "
            f"they keep — {sorted(keeps)}. The built picture offers the copies every "
            "tile has, so a run written two different ways has to be looked at as "
            "two runs."
        )

    described, _ = _the_description_of(tiles[0].store)
    multiscale = (described.get("multiscales") or [{}])[0]
    axes = tuple(str(axis.get("name", "")) for axis in multiscale.get("axes") or ())
    if len(axes) != 3:
        raise ValueError(
            f"{tiles[0].store} stores its picture as {', '.join(axes)}. This builds "
            "over transfers of three axes — depth, height and width — which is what "
            "a mesoSPIM transfer writes. A five-axis run of ours is shown by "
            "pointing instead; see zmart_storage.linked."
        )

    corner = tuple(
        min(tile.copies[0].corner_um[axis] for tile in tiles) for axis in range(3)
    )
    return Mosaic(
        tiles=tiles,
        levels=tiles[0].keeps,
        axes=axes,  # type: ignore[arg-type]
        dtype=_how_a_resolution_is_stored(tiles[0].copies[0].held_in)[2],
        corner_um=corner,  # type: ignore[arg-type]
    )

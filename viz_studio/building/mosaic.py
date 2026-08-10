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
being drawn.

That sounds like an approximation and mostly is not one. A copy of the picture
shrunk eight times cannot express a position more finely than one of its own
voxels; rounding to the nearest is not losing accuracy that copy had, it is
declining to invent accuracy it never had. At full resolution the rounding is
0.06 of a voxel on the Thy1 set — a hundredth of a micrometre — which is far below
what the objective resolves.

What it is *not* is the rounding that breaks pointing. That one rounds to the
nearest whole **chunk**, hundreds of voxels at a time, which is why it is refused
rather than done.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import zarr

# The name every OME-Zarr image folder ends in. A transfer holds one per tile, and
# anything else in the container -- a coverage record, a note of somebody's
# annotations -- is not a tile and is skipped.
IMAGE_SUFFIX = ".ome.zarr"


@dataclass(frozen=True)
class Copy:
    """One resolution of one tile: its pixels, how large a voxel is, where it sits.

    Attributes:
        array: the tile's picture at this resolution, opened read-only.
        voxel_um: how large one of its voxels is, as ``(z, y, x)`` in micrometres.
        corner_um: where its first voxel sits on the stage, as ``(z, y, x)``.
    """

    array: zarr.Array
    voxel_um: tuple[float, float, float]
    corner_um: tuple[float, float, float]


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

        Rounded, for the reason set out at the top of this module: a copy cannot
        express a position more finely than one of its own voxels.
        """
        copy = tile.copies[level]
        voxel = self.voxel_um(level)
        return tuple(
            int(round((copy.corner_um[axis] - self.corner_um[axis]) / voxel[axis]))
            for axis in range(3)
        )  # type: ignore[return-value]

    def shape(self, level: int) -> tuple[int, int, int]:
        """How large the built picture is at this resolution, in voxels."""
        return tuple(
            max(self.lands_at(tile, level)[axis] + tile.copies[level].array.shape[axis]
                for tile in self.tiles)
            for axis in range(3)
        )  # type: ignore[return-value]

    def reaching_into(self, level: int, low: tuple[int, int, int],
                      high: tuple[int, int, int]) -> list[tuple[Tile, tuple[int, int, int]]]:
        """Which tiles cover any part of this box, and where each of them lands.

        Args:
            level: which copy of the picture the box is measured in.
            low: the box's near corner, as ``(z, y, x)`` in that copy's voxels.
            high: the box's far corner, one past the last voxel.

        Returns:
            Each tile that overlaps the box at all, paired with where it lands.
        """
        found = []
        for tile in self.tiles:
            at = self.lands_at(tile, level)
            held = tile.copies[level].array.shape
            if all(max(low[axis], at[axis]) < min(high[axis], at[axis] + held[axis])
                   for axis in range(3)):
                found.append((tile, at))
        return found


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
        copies.append(Copy(
            array=zarr.open_array(str(store / str(dataset["path"])), mode="r"),
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

    tiles = [Tile(name=store.name, store=store, copies=_placed_copies_of(store))
             for store in stores]

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
        dtype=str(tiles[0].copies[0].array.dtype),
        corner_um=corner,  # type: ignore[arg-type]
    )

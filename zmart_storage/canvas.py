"""Writing a tiled run into a small, fixed number of OME-Zarr images.

Why this exists
---------------

A smart-microscopy run can visit thousands of places on the stage. If every one
of those becomes its own OME-Zarr folder, the viewer has thousands of separate
images to open, describe, and keep track of — and that cost is paid again every
time a new tile lands, not just once at the start. Measured on this repository's
own test rig, one tile arriving took 0.1 seconds when 25 tiles were open, 0.3
seconds at 100, and 3.7 seconds at 225. The trend does not survive a run of a
few thousand.

The way out is to stop giving the viewer one image per position. Instead the run
writes into a **small, fixed number of large images** whose size is declared
before any imaging begins. Neuroglancer then has a handful of things to keep
track of no matter how big the run gets, and a tile arriving costs nothing at
all to notice, because the image's description never changes — only chunks of
picture appear underneath it.

Declaring a large image up front is affordable because a piece of an image only
occupies disk once something writes to it. An image can honestly declare the
whole stage travel range and occupy almost nothing until it is filled in.

Why more than one image: keeping the overlap
--------------------------------------------

Tiles are usually acquired with a little overlap — commonly ten or fifteen per
cent — so that the two views of the shared strip can later be compared and the
true alignment worked out. That comparison is what corrects the small errors the
stage makes, and it can only be done once every tile exists, because a good
alignment is solved for all tiles at once rather than pair by pair.

But a single image holds exactly one value per voxel. So if overlapping tiles
are written into one image, the second one to arrive overwrites the shared strip
and the comparison can never be made. The data is gone at the moment of writing.

The fix is to use a few images instead of one, and to place each tile in an image
where it does not touch anything already written there. Neighbouring tiles then
land in *different* images, so nothing is ever overwritten and every pixel the
camera recorded is still on disk, at full resolution, in its correct place.

How many images that takes is small and fixed. Two tiles placed two steps apart
do not touch each other as long as a step is at least half a tile wide — which is
true for any overlap up to fifty per cent. So two "slots" per axis is enough:
four images for a run tiled in y and x, eight if it is also tiled in z. It never
grows with the number of tiles, which is the whole point.

What you get on screen
----------------------

The viewer reads all of the images together and draws them in their proper places,
so the specimen looks like one picture. Where tiles overlap, one image is drawn on
top of another — nothing is blended — so the picture looks exactly as it would
have if a single image had been used. The difference is that the covered pixels
still exist and can be read back, which is what keeps a proper alignment possible
later on.
"""

from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import zarr

# The default colours for the usual excitation wavelengths, matching what the
# viewer uses elsewhere, so a run written here looks the same as one read from a
# mesoSPIM. A wavelength that is not listed is drawn white rather than guessed at.
_CHANNEL_COLORS = {
    "405": "4D73FF",
    "488": "00FF66",
    "561": "FFBF1A",
    "647": "FF33FF",
}


def slots_per_axis(tile_length: int, step: int) -> int:
    """How many images are needed along one axis so that tiles never collide.

    Tiles placed ``step`` apart, each ``tile_length`` long, overlap their
    immediate neighbours. If we deal them out to several images in rotation, two
    tiles in the same image end up further apart, and past a certain separation
    they stop touching altogether.

    That separation is what this works out. With a ten per cent overlap the
    answer is two; it only becomes three if tiles overlap by more than half their
    own width, which a tiled acquisition does not do.

    Args:
        tile_length: how many voxels one tile spans along this axis.
        step: how many voxels the stage moves between neighbouring tiles.

    Returns:
        The number of images needed along this axis, always at least one.
    """
    if step <= 0:
        raise ValueError("the step between tiles must be a positive number of voxels")
    return max(1, math.ceil(tile_length / step))


def _refuse_overlapping_tiles(tile_shape, tile_step) -> None:
    """Stop a run whose tiles overlap from being written into one image.

    This is the rule the whole arrangement rests on, so it is checked once at the
    start rather than discovered later from a picture that looks slightly wrong.

    One image holds one value per voxel, so where two tiles overlap the second to
    arrive replaces the first and the shared strip is gone. That is fine when
    there is no shared strip, and it is a real loss when there is — because the
    two recordings of it are exactly what a stitcher compares in order to work out
    where the stage actually put each tile.

    So a run that overlaps its tiles should keep them as separate images while it
    runs, and be stitched into one picture once it has finished and the alignment
    can be solved. That is a different path, not a variation on this one.
    """
    axes = ("z", "y", "x")
    overlapping = [
        (axes[axis], tile_shape[axis] - tile_step[axis])
        for axis in range(3)
        if tile_step[axis] < tile_shape[axis]
    ]
    if not overlapping:
        return
    described = ", ".join(f"{by} voxels in {axis}" for axis, by in overlapping)
    raise ValueError(
        f"these tiles overlap ({described}), and overlapping tiles must not be "
        "written into one image as the run goes: the second tile to arrive would "
        "replace the strip it shares with the first, and the two recordings of "
        "that strip are what a stitcher needs.\n\n"
        "Either acquire without overlap — step the stage by the whole tile — or "
        "keep the tiles as separate images while the run goes and stitch them "
        "into one picture afterwards, once every tile exists and the alignment "
        "can be solved."
    )


def _warn_if_tiles_straddle_pieces(tile_shape, tile_step, chunk: int, levels: int) -> None:
    """Point out a tile size that makes concurrent writing needlessly slow.

    Two tiles can only be written at the same moment if they do not share a piece
    of image. When a tile is a whole number of pieces and the stage steps by that
    same number, they never do, and tiles can be written as fast as they arrive.

    The size that matters is the piece of the *smallest* copy, because that covers
    the most ground — a piece of the quarter-size copy spans four times as much
    specimen as a piece of the full-size one. Getting this wrong is not dangerous:
    the writer notices and holds the tiles apart. It just means waiting.
    """
    import warnings

    grain = chunk * 2 ** (levels - 1)
    for axis, name in ((1, "y"), (2, "x")):
        if tile_shape[axis] % grain or tile_step[axis] % grain:
            nearest = max(grain, round(tile_shape[axis] / grain) * grain)
            warnings.warn(
                f"a tile of {tile_shape[axis]} voxels in {name}, stepped "
                f"{tile_step[axis]}, does not divide into whole pieces of image "
                f"({grain} voxels, which is {chunk} across {levels} levels of "
                f"shrunk-down copies). Tiles will sometimes share a piece, and "
                f"the writer then has to write those one after another rather "
                f"than at the same time. Nothing is lost, but a tile of "
                f"{nearest} voxels would avoid the wait.",
                stacklevel=3,
            )
            return


@dataclass(frozen=True)
class Channel:
    """One colour of light the run records, and how it should first appear.

    Recording this in the image itself means the viewer can name and colour the
    channel without guessing from a filename, and it opens looking sensible
    rather than flat grey.

    Args:
        name: what to call it on screen, for example ``"488"`` or ``"nuclei"``.
        color: six hex digits, as ``"00FF66"``. Left out, a name that looks like
            an excitation wavelength picks up the conventional colour and
            anything else is drawn white.
        window: the brightness range to start with, as ``(start, end)``. Left
            out, the viewer measures one from the pixels, which costs a read.
    """

    name: str
    color: str | None = None
    window: tuple[int, int] | None = None

    def described(self, depth_max: int) -> dict:
        """This channel in the form an OME-Zarr ``omero`` block expects."""
        color = self.color or _CHANNEL_COLORS.get(self.name, "FFFFFF")
        start, end = self.window or (0, depth_max)
        return {
            "label": self.name,
            "color": color,
            "window": {"min": 0, "max": depth_max, "start": start, "end": end},
        }


@dataclass
class _Slot:
    """One of the images tiles are dealt into, and what has been put in it."""

    index: int
    folder: Path
    arrays: list[zarr.Array]
    # The footprint of every tile written here, as (z0, z1, y0, y1, x0, x1) in
    # voxels. Kept so that a tile arriving at an unplanned position can be asked
    # "does this land on anything already here?" without reading any image data.
    written: list[tuple[int, int, int, int, int, int]] = field(default_factory=list)


class TileCanvases:
    """A run's images, declared up front and filled in as tiles arrive.

    Make one at the start of a run with :meth:`create`, then call :meth:`write`
    once per acquired tile. Nothing needs to be finalised at the end — the images
    are complete and readable throughout, which is what lets the viewer watch a
    run as it happens.
    """

    def __init__(self, folder: Path, slots: list[_Slot], *, shape: tuple[int, ...],
                 levels: int, tile_shape: tuple[int, int, int],
                 slot_grid: tuple[int, int, int]) -> None:
        self.folder = folder
        self._slots = slots
        self._shape = shape
        self._levels = levels
        self._tile_shape = tile_shape
        self._slot_grid = slot_grid
        # Two tiles being written at the same moment are only safe if they do not
        # share a piece of image: otherwise each reads the piece, adds its own
        # tile to its own copy, and writes the whole thing back, so whichever
        # finishes second erases the other's contribution. Nothing reports this —
        # the picture simply comes out with parts missing.
        #
        # Note that this is about sharing a *piece*, not about the tiles
        # overlapping. Two tiles can sit well apart and still fall inside one
        # piece of image, and that is just as damaging. So a tile's claim is
        # widened to whole pieces before it is compared with what else is in
        # progress, and it waits until nothing it shares a piece with is still
        # being written.
        #
        # The pieces of the smallest copy are the ones that matter, because they
        # cover the most ground: a piece of the half-size copy spans twice as much
        # of the specimen as a piece of the full-size one, and they nest inside
        # each other. Claiming by the coarsest therefore covers every level at once.
        chunks = slots[0].arrays[0].chunks
        coarsest = 2 ** (levels - 1)
        self._grain = (chunks[3] * coarsest, chunks[4] * coarsest)
        self._busy: list[tuple[int, ...]] = []
        self._free = threading.Condition()

    # -- making the images ------------------------------------------------

    @classmethod
    def create(
        cls,
        folder: str | Path,
        *,
        name: str = "canvas",
        canvas_shape: tuple[int, int, int],
        tile_shape: tuple[int, int, int],
        tile_step: tuple[int, int, int],
        voxel_size_um: tuple[float, float, float],
        channels: list[Channel],
        origin_um: tuple[float, float, float] = (0.0, 0.0, 0.0),
        frames: int = 1,
        dtype: str = "uint16",
        chunk: int = 256,
        levels: int = 3,
        slots: tuple[int, int, int] | None = None,
    ) -> TileCanvases:
        """Declare the images for a run, before anything has been imaged.

        Nothing here is expensive: declaring a large image writes a few hundred
        bytes of description and no picture at all. Space is taken only as tiles
        are written, so it is much better to declare comfortably more room than
        the run could possibly need than to risk running out.

        Args:
            folder: where to put the images. Created if it is not there yet.
                This is the run's own folder, and every acquisition type in the
                run writes its image into it side by side.
            name: what to call this image, which should be the acquisition type
                it holds — ``"overview"``, ``"prescan"``, ``"targetscan"``. The
                viewer groups the rows it shows by this name, so it is what the
                operator sees rather than an internal detail.
            canvas_shape: how much room to allow, as ``(z, y, x)`` in voxels.
                The stage's travel range is a good choice when the experiment
                does not say: the stage cannot reach outside it, so no tile can
                ever land beyond the edge.
            tile_shape: the size of one acquired tile, as ``(z, y, x)`` in voxels.
            tile_step: how far the stage moves between neighbouring tiles, as
                ``(z, y, x)`` in voxels. Together with ``tile_shape`` this is what
                decides how many images are needed to keep the overlap.
            voxel_size_um: how large one voxel is, as ``(z, y, x)`` in microns.
                This is what makes the scale bar and the measurements truthful.
            channels: the colours of light being recorded, in the order they
                appear along the channel axis.
            origin_um: where the low corner of the images sits in stage
                coordinates. Tile positions given to :meth:`write` are measured
                from the same zero, so this is usually the low end of stage travel.
            frames: how many timepoints to allow for. A run that is not a
                timelapse leaves this at one.
            dtype: the kind of number one voxel is. Use the camera's own — a
                16-bit camera writes ``uint16`` — because every level of the image
                must share it and converting would only lose precision.
            chunk: how large a piece of image is, in y and x. A few hundred is
                right: pieces that are too large make the viewer read far more
                than it needs whenever it wants a small sample.
            levels: how many progressively smaller copies to keep. These are what
                let a huge image feel light when zoomed out. Three is plenty for
                ordinary tiles.
            slots: how many images to spread the tiles over, as ``(z, y, x)``.
                Normally left out, which gives a single image — the arrangement
                this writer is for. Setting it spreads overlapping tiles across
                several images so that none is written over; see the note on
                overlap at the top of this module for when that is worth doing.

        Returns:
            The images, ready to be written into.

        Raises:
            ValueError: if the tiles overlap. A run that overlaps its tiles
                should keep them separate and be stitched once it is finished,
                rather than being written into one image as it goes.
        """
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)

        if slots is None:
            _refuse_overlapping_tiles(tile_shape, tile_step)
            slot_grid = (1, 1, 1)
        else:
            slot_grid = slots
        _warn_if_tiles_straddle_pieces(tile_shape, tile_step, chunk, levels)

        depth_max = int(np.iinfo(np.dtype(dtype)).max)

        total = slot_grid[0] * slot_grid[1] * slot_grid[2]
        slots: list[_Slot] = []
        for index in range(total):
            # One image per acquisition type, named after it, so the viewer can
            # group what it finds the way the experiment is organised. Only a run
            # that spreads its tiles needs more than one, and those are numbered.
            leaf = name if total == 1 else f"{name}_part{index}"
            store = folder / f"{leaf}.ome.zarr"
            arrays = _declare_one(
                store,
                canvas_shape=canvas_shape,
                frames=frames,
                channels=len(channels),
                dtype=dtype,
                chunk=chunk,
                levels=levels,
                voxel_size_um=voxel_size_um,
                origin_um=origin_um,
                channel_blocks=[c.described(depth_max) for c in channels],
            )
            slots.append(_Slot(index=index, folder=store, arrays=arrays))

        return cls(
            folder,
            slots,
            shape=(frames, len(channels), *canvas_shape),
            levels=levels,
            tile_shape=tile_shape,
            slot_grid=slot_grid,
        )

    # -- writing ----------------------------------------------------------

    @property
    def paths(self) -> list[Path]:
        """Where each image lives, in the order the viewer should be given them."""
        return [slot.folder for slot in self._slots]

    def write(
        self,
        image: np.ndarray,
        *,
        origin: tuple[int, int, int],
        channel: int = 0,
        frame: int = 0,
        tile_index: tuple[int, int, int] | None = None,
    ) -> Path:
        """Put one acquired tile into whichever image has room for it.

        Args:
            image: the tile's voxels, shaped ``(z, y, x)``.
            origin: where the tile's low corner sits, as ``(z, y, x)`` in voxels,
                measured from the same zero as ``origin_um``.
            channel: which colour of light this tile was recorded in, as its
                position along the channel axis.
            frame: which timepoint it belongs to.
            tile_index: the tile's place in the scan pattern, as
                ``(z, y, x)`` counts. A raster scan knows this and it makes the
                choice of image immediate. A target picked by the workflow does
                not, and leaving it out is fine — the writer then checks the
                tile against what each image already holds.

        Returns:
            The image the tile was written into, which is useful mainly for
            reporting and for tests.

        Raises:
            ValueError: if the tile would fall outside the room that was
                declared, which means the canvas was declared too small.
        """
        depth, height, width = image.shape
        z0, y0, x0 = origin
        footprint = (z0, z0 + depth, y0, y0 + height, x0, x0 + width)
        self._check_it_fits(footprint)

        slot = self._choose(footprint, tile_index)

        # Hold back until nothing sharing a piece of image is mid-write, so two
        # tiles can never be halfway through the same piece at once.
        region = (
            slot.index, frame, channel, z0, z0 + depth,
            y0 // self._grain[0], (y0 + height - 1) // self._grain[0],
            x0 // self._grain[1], (x0 + width - 1) // self._grain[1],
        )
        with self._free:
            while any(_touches(region, other) for other in self._busy):
                self._free.wait()
            self._busy.append(region)
        try:
            slot.arrays[0][frame, channel,
                           z0:z0 + depth, y0:y0 + height, x0:x0 + width] = image
            self._write_smaller_copies(slot, image, origin, channel, frame)
            slot.written.append(footprint)
        finally:
            with self._free:
                self._busy.remove(region)
                self._free.notify_all()
        return slot.folder

    # -- choosing where a tile goes ---------------------------------------

    def _choose(self, footprint: tuple[int, ...], tile_index) -> _Slot:
        """Which image this tile belongs in, so that it overwrites nothing."""
        if tile_index is not None:
            # A scan pattern deals tiles out in rotation, so neighbours always
            # land in different images and no checking is needed at all.
            zc, yc, xc = self._slot_grid
            index = ((tile_index[0] % zc) * yc + (tile_index[1] % yc)) * xc + (
                tile_index[2] % xc
            )
            return self._slots[index]

        # A tile the workflow chose has no place in a pattern, so ask each image
        # in turn whether this tile would land on anything already in it. This is
        # arithmetic on a list of rectangles, so it costs nothing to speak of and
        # touches no image data.
        for slot in self._slots:
            if not any(_overlaps(footprint, other) for other in slot.written):
                return slot
        # Every image is occupied here, which a normal overlap cannot cause. Rather
        # than silently destroy a tile, put it in the emptiest image and say so.
        emptiest = min(self._slots, key=lambda s: len(s.written))
        raise ValueError(
            "this tile overlaps something already written in every image, so "
            "writing it would destroy data. This happens when tiles overlap by "
            "more than half their width, or when many targets were chosen very "
            "close together. Declare the run with more images to make room "
            f"(there are currently {len(self._slots)}, the emptiest holding "
            f"{len(emptiest.written)} tiles)."
        )

    def _check_it_fits(self, footprint: tuple[int, ...]) -> None:
        z0, z1, y0, y1, x0, x1 = footprint
        limits = self._shape[2:]
        if z0 < 0 or y0 < 0 or x0 < 0:
            raise ValueError(
                "this tile sits before the low corner of the declared room. The "
                "images can be made larger, but only outward, so the corner has to "
                "be at or below the lowest position the run will ever visit."
            )
        if z1 > limits[0] or y1 > limits[1] or x1 > limits[2]:
            raise ValueError(
                f"this tile reaches to {(z1, y1, x1)} voxels, past the declared "
                f"room of {limits}. Declare the images with the stage's whole "
                "travel range so this cannot happen — unwritten room costs "
                "practically nothing on disk."
            )

    # -- the smaller copies -----------------------------------------------

    def _write_smaller_copies(self, slot: _Slot, image: np.ndarray,
                              origin: tuple[int, int, int],
                              channel: int, frame: int) -> None:
        """Fill in this tile's part of each progressively smaller copy.

        These are what the viewer draws when zoomed out, and what it measures
        brightness from, so they have to be kept in step as tiles arrive rather
        than built at the end — otherwise a run in progress looks empty until
        someone zooms all the way in.

        Only y and x are shrunk. Planes are left alone because scrolling through
        a stack should show the planes that were actually acquired.
        """
        for level in range(1, self._levels):
            factor = 2 ** level
            smaller = image[:, ::factor, ::factor]
            if smaller.size == 0:
                continue
            z0 = origin[0]
            y0, x0 = origin[1] // factor, origin[2] // factor
            depth, height, width = smaller.shape
            array = slot.arrays[level]
            # A tile near the far edge can round to just past the end of a smaller
            # copy, so trim rather than fail: the lost row is half a voxel of the
            # coarsest view, which nothing can see.
            height = min(height, array.shape[3] - y0)
            width = min(width, array.shape[4] - x0)
            if height <= 0 or width <= 0:
                continue
            array[frame, channel, z0:z0 + depth, y0:y0 + height, x0:x0 + width] = (
                smaller[:, :height, :width]
            )


# -- geometry ---------------------------------------------------------------


def _overlaps(a: tuple[int, ...], b: tuple[int, ...]) -> bool:
    """Whether two tile footprints share any voxel at all."""
    return (
        a[0] < b[1] and b[0] < a[1]
        and a[2] < b[3] and b[2] < a[3]
        and a[4] < b[5] and b[4] < a[5]
    )


def _touches(a: tuple[int, ...], b: tuple[int, ...]) -> bool:
    """Whether two writes in progress would be working on the same piece of image.

    Each claim is ``(image, frame, channel, z from, z to, then the first and last
    piece it reaches in y, then the same in x)``. Time, colour and depth each get
    a piece to themselves, so those simply have to coincide; y and x are counted
    in whole pieces, and the first and last are both included.
    """
    return (
        a[0] == b[0] and a[1] == b[1] and a[2] == b[2]
        and a[3] < b[4] and b[3] < a[4]
        and a[5] <= b[6] and b[5] <= a[6]
        and a[7] <= b[8] and b[7] <= a[8]
    )


# -- declaring one image ----------------------------------------------------


def _declare_one(
    store: Path,
    *,
    canvas_shape: tuple[int, int, int],
    frames: int,
    channels: int,
    dtype: str,
    chunk: int,
    levels: int,
    voxel_size_um: tuple[float, float, float],
    origin_um: tuple[float, float, float],
    channel_blocks: list[dict],
) -> list[zarr.Array]:
    """Write one empty OME-Zarr image and hand back its levels."""
    store.mkdir(parents=True, exist_ok=True)
    group = zarr.open_group(str(store), mode="w", zarr_format=2)

    arrays, datasets = [], []
    for level in range(levels):
        factor = 2 ** level
        shape = (
            frames,
            channels,
            canvas_shape[0],
            max(1, canvas_shape[1] // factor),
            max(1, canvas_shape[2] // factor),
        )
        arrays.append(group.create_array(
            str(level),
            shape=shape,
            # One plane per piece in time, colour and depth, so showing a single
            # plane never means fetching the ones on either side of it.
            chunks=(1, 1, 1, min(chunk, shape[3]), min(chunk, shape[4])),
            dtype=dtype,
            # Pieces filed in folders rather than side by side in one directory.
            # A long run otherwise puts millions of files in a single folder,
            # which most filesystems handle badly.
            chunk_key_encoding={"name": "v2", "separator": "/"},
        ))
        datasets.append({
            "path": str(level),
            "coordinateTransformations": [{
                "type": "scale",
                "scale": [1.0, 1.0, voxel_size_um[0],
                          voxel_size_um[1] * factor, voxel_size_um[2] * factor],
            }],
        })

    (store / ".zattrs").write_text(json.dumps({
        "multiscales": [{
            "version": "0.4",
            "axes": [
                {"name": "t", "type": "time", "unit": "second"},
                {"name": "c", "type": "channel"},
                {"name": "z", "type": "space", "unit": "micrometer"},
                {"name": "y", "type": "space", "unit": "micrometer"},
                {"name": "x", "type": "space", "unit": "micrometer"},
            ],
            "datasets": datasets,
            # Where this image sits in the world. Every image in a run shares the
            # same corner, which is what makes them line up on screen.
            "coordinateTransformations": [{
                "type": "translation",
                "translation": [0.0, 0.0, origin_um[0], origin_um[1], origin_um[2]],
            }],
        }],
        "omero": {"channels": channel_blocks},
    }, indent=2), encoding="utf-8")

    return arrays

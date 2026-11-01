"""Declaring one OME-Zarr image, ready to be filled with one position's pixels.

Brought from ZMART-microscopy's ``zmart_storage`` writer (``canvas.py`` and
``positions.py``), with only what the interface calls: :class:`Channel`,
:func:`declare_image` and :func:`how_many_copies_a_position_can_keep`.

What an image declared here looks like
--------------------------------------

Five axes, always in this order: time, channel, depth, and the two directions
across the specimen (``t, c, z, y, x``). A full-size level and a few smaller
copies of it, each half as wide and half as tall as the one before, made by
keeping every second voxel rather than averaging, and each saying how large its
voxels are and where the centre of its first voxel sits on the stage. Every
piece of the image is one plane of one channel at one moment, so showing a
plane never means fetching its neighbours. Nothing is written into the image here: declaring it
costs a few hundred bytes of description and no picture at all.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import zarr

# Every image this module writes is a folder whose name ends this way, which is
# the usual convention for an OME-Zarr image and is what the viewer looks for.
_IMAGE_SUFFIX = ".ome.zarr"

# What the five dimensions of every image here are called, in the order they are
# stored. OME-Zarr 0.5 states that the names on each level of the image "MUST
# match the names in the axes metadata" of the group, so they are written down
# once and used in both places.
_AXIS_NAMES = ("t", "c", "z", "y", "x")


# The default colours for the usual excitation wavelengths, matching what the
# viewer uses elsewhere, so a run written here looks the same as one read from a
# mesoSPIM. A wavelength that is not listed is drawn white rather than guessed at.
_CHANNEL_COLORS = {
    "405": "4D73FF",
    "488": "00FF66",
    "561": "FFBF1A",
    "647": "FF33FF",
}


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
        """This channel in the form an OME-Zarr ``omero`` block expects.

        The ``min`` and ``max`` written here are the range of numbers the camera
        can produce at all — nought to 65535 for a 16-bit camera — which is a
        plain fact about the data and always worth recording.

        The ``start`` and ``end`` are a different thing: they are the brightness
        range the image should first be *displayed* with.

        These used to be left out when a run did not ask for a window, on the
        reasoning that a viewer would then measure a good one from the pixels.
        That reasoning was sound but the file it produced was not: **a describing
        block with an incomplete window is refused outright.** Checked against
        ngio, a block naming a channel without ``start`` and ``end`` fails to
        open, while the same image with no describing block at all opens
        perfectly well. So the choice was never "a measured window or a declared
        one" — it was "a complete window or no channel names and colours at all",
        and names and colours are worth having.

        So a window is always written now. When the run did not ask for one, the
        camera's whole range is declared, because that is the honest thing to say
        when nothing is known. Be aware of what that looks like: a real
        acquisition sits in the bottom few per cent of a camera's range — a few
        hundred counts of background with the signal not far above — so an image
        opened on the whole range looks almost black until somebody drags the
        contrast slider. **A run that knows roughly how bright its images are
        should pass a window**, and its acquisitions will open looking like
        something.
        """
        color = self.color or _CHANNEL_COLORS.get(self.name, "FFFFFF")
        window = {"min": 0, "max": depth_max}
        window["start"], window["end"] = self.window or (0, depth_max)
        return {
            "label": self.name,
            "color": color,
            "window": window,
        }


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
    256, 128 — and a view over such positions writes nothing at all at those five
    zooms. **Anything coarser than the last of them is a different matter**: it has
    no copy to point at, so it is written from the positions' pixels. Which zooms a
    picture has is decided by how wide the run is, not by the position, so a wide
    enough run always writes its coarse end however many copies a position keeps.
    That is the only thing a run writes twice, it is small, and the note at the top
    of this module gives the measurement.

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


def declare_image(
    store: Path,
    *,
    canvas_shape: tuple[int, int, int],
    frames: int,
    channels: int,
    dtype: str,
    chunk: int,
    levels: int,
    voxel_size_um: tuple[float, float, float],
    first_voxel_um: tuple[float, float, float],
    channel_blocks: list[dict],
    ome_zarr_version: str = "0.4",
) -> list[zarr.Array]:
    """Write one empty OME-Zarr image and hand back its levels.

    ``first_voxel_um`` is where the centre of the full-size image's first
    voxel sits on the stage, as ``(z, y, x)`` in microns; each smaller copy
    is placed by the centre of its own first voxel from it.

    Every run gets a time axis, whether or not it is a timelapse. That was not
    always so. The viewer used to pick which axes to put on screen from the first
    few an image declared, so an extra axis was enough to make it choose wrongly
    and draw the specimen as a thin band; a run of one moment therefore left the
    axis out to avoid it. The viewer now chooses the axes that measure distance,
    whatever else an image has, so the workaround is gone and every run can declare
    the same five axes. A run of a single moment simply gets no time slider,
    because one moment is nothing to offer a choice between.
    """
    store.mkdir(parents=True, exist_ok=True)
    # Which generation of the format to write. The two differ in more than a number:
    # 0.4 is built on zarr version 2 and keeps a store's description in a separate
    # ``.zattrs`` file beside the image, while 0.5 is built on zarr version 3, which
    # keeps it inside ``zarr.json`` under an ``ome`` key and files the pieces of the
    # image under a folder called ``c``. Everything else here -- the axes, the
    # ordering, the sizes, the way a tile is written -- is the same for
    # both, so a run written either way behaves identically once it is open.
    newer = ome_zarr_version == "0.5"
    # ``mode="w"`` empties the folder before declaring, which is what a fresh
    # image wants: nothing an earlier attempt left behind is carried into it.
    group = zarr.open_group(str(store), mode="w", zarr_format=3 if newer else 2)

    # A time axis is always declared, and is given its full length here rather than
    # being lengthened as the run goes. This is the same arrangement as the room in
    # space: declare comfortably more than the run could need, and fill it in. A
    # moment nothing has been written to occupies no space on disk, so a generous
    # length costs only the number written in this description.
    #
    # What makes it safe is that the viewer shows only the moments that were
    # actually imaged: it counts what has been written and stops the time slider
    # there, so an operator is never offered a frame that does not exist. Without
    # that counting this arrangement would be a trap, because the engine remembers
    # "there is nothing here" for a frame looked at too early and does not look
    # again.
    axes = [
        {"name": _AXIS_NAMES[0], "type": "time", "unit": "second"},
        {"name": _AXIS_NAMES[1], "type": "channel"},
        {"name": _AXIS_NAMES[2], "type": "space", "unit": "micrometer"},
        {"name": _AXIS_NAMES[3], "type": "space", "unit": "micrometer"},
        {"name": _AXIS_NAMES[4], "type": "space", "unit": "micrometer"},
    ]

    arrays, datasets = _make_the_copies(
        group,
        canvas_shape=canvas_shape,
        frames=frames,
        channels=channels,
        dtype=dtype,
        chunk=chunk,
        levels=levels,
        voxel_size_um=voxel_size_um,
        first_voxel_um=first_voxel_um,
        newer=newer,
    )

    # Where the image sits on the stage is written beside each resolution, in
    # ``_make_the_copies``, rather than once for the image as a whole. OME-Zarr
    # allows both places, and the reason for choosing the first is recorded there.
    multiscale = {
        # What this picture is called. The specification asks for it, and it is
        # what a reader shows in its own panel when it has nothing better.
        "name": store.name[:-len(_IMAGE_SUFFIX)] if store.name.endswith(
            _IMAGE_SUFFIX) else store.name,
        "axes": axes,
        # How the smaller copies were made, which the specification asks every
        # image to say and which matters more here than in most projects.
        #
        # They are made by **keeping every second voxel and discarding the rest**,
        # not by averaging groups of them. Saying so is not a formality. A reader
        # deserves to know that a zoomed-out picture is a sample of the specimen
        # rather than a smoothed version of it — bright specks survive at every
        # zoom instead of fading, and a faint object between two kept rows can
        # disappear when you zoom out.
        #
        # It is also the fact this project's whole arrangement rests on. Because
        # each coarse voxel comes from exactly one fine voxel, a voxel of a
        # position's own smaller copy is a voxel of the whole picture's smaller
        # copy, so a view can point at the positions' zoomed-out copies instead of
        # computing and storing a second set. Averaging would mix voxels across
        # the join between two positions, and no position would own its result.
        # The shrinking itself is done where the pixels are written, in
        # ``examples/target_acquisition/storage/zarr_positions.py``.
        "type": "nearest",
        "metadata": {
            "description": (
                "Every second voxel kept along y and x at each level; nothing is "
                "averaged, so each coarse voxel is one original voxel."
            ),
            "method": "slice",
        },
        "datasets": datasets,
    }

    _write_the_description(store, group, multiscale, channel_blocks, newer=newer)
    return arrays


def _make_the_copies(
    group, *,
    canvas_shape: tuple[int, int, int],
    frames: int,
    channels: int,
    dtype: str,
    chunk: int,
    levels: int,
    voxel_size_um: tuple[float, float, float],
    first_voxel_um: tuple[float, float, float],
    newer: bool,
) -> tuple[list[zarr.Array], list[dict]]:
    """Make the full-size image and each progressively smaller copy of it.

    The copies are what the viewer draws when it is zoomed out. Each one is half
    the width and half the height of the one before it, and every one of them
    keeps the full depth of the stack, because scrolling through a stack should
    show the planes that were really acquired.

    Nothing is written into them here. Declaring an image of this size costs a
    few hundred bytes of description and no picture at all, which is what makes
    it reasonable to declare the stage's whole travel range up front.

    Args:
        group: the zarr group the copies are made in, which is one image.
        canvas_shape: how much room the run declared, as ``(z, y, x)`` in voxels.
        frames: how many moments to allow room for.
        channels: how many colours of light the run records.
        dtype: the kind of number one voxel is, such as ``"uint16"``.
        chunk: how large one piece of image is, in y and x.
        levels: how many copies to make, counting the full-size one.
        voxel_size_um: how large one voxel is, as ``(z, y, x)`` in microns.
        first_voxel_um: where the centre of the full-size copy's first voxel
            sits on the stage, as ``(z, y, x)`` in microns. Each smaller copy
            is placed by the centre of its own first voxel.
        newer: ``True`` when writing OME-Zarr 0.5, which files the pieces of an
            image its own way, ``False`` for 0.4.
    Returns:
        The copies themselves, largest first, and the block of description that
        names each one and says how much ground its voxels cover.
    """
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
            chunks=(1, 1, 1, min(chunk, shape[-2]), min(chunk, shape[-1])),
            dtype=dtype,
            # What each dimension of this array is called. OME-Zarr 0.5 requires
            # it -- the specification says the names "MUST be included in the
            # zarr.json of the Zarr array of a multiscale level and MUST match
            # the names in the axes metadata" -- and it is genuinely useful: it
            # is what lets a reader open one level on its own and still know
            # which dimension is depth and which is time, without having to go
            # up to the group description to find out.
            #
            # The older generation has nowhere to put it. In 0.4 the array
            # description is a fixed set of fields with no room for names, so the
            # axes in the group description are the only statement of them, and
            # asking for names here would simply be dropped.
            **({"dimension_names": _AXIS_NAMES} if newer else {}),
            # Pieces filed in folders rather than side by side in one directory.
            # A long run otherwise puts millions of files in a single folder,
            # which most filesystems handle badly.
            #
            # Version 3 already does this of its own accord -- it files every piece
            # under a folder called ``c`` and separates the rest with slashes -- so
            # it is left to its own naming and only version 2 has to be asked.
            # Asking version 3 for the version 2 naming would work, but it would
            # produce a store that looks like neither generation and would be a
            # small surprise to anything else reading it.
            **({} if newer else {"chunk_key_encoding": {"name": "v2", "separator": "/"}}),
        ))
        datasets.append({
            "path": str(level),
            # How large this copy's voxels are, and where the image begins on the
            # stage. Both are written here, beside the copy they describe.
            #
            # OME-Zarr offers two places to say where an image sits: beside each
            # resolution, as here, or once beside the block that lists them all.
            # A reader is meant to apply the second to the result of the first, so
            # a writer must pick one and only one -- saying it in both places
            # places the image twice as far out as it really is.
            #
            # This writer says it here, because this is the place the format makes
            # compulsory: every resolution must carry a transformation, while the
            # block-level one is optional. Tools that read only the compulsory
            # place are therefore common, and a picture written only in the
            # optional place arrives at the stage's zero for all of them, with
            # every acquisition of a run stacked on top of the others. That is
            # what used to happen to our images in the wider Python ecosystem.
            #
            # The number is the **centre** of the copy's first voxel, as the
            # format says (OME-NGFF RFC-5: the centre of a voxel is the origin of
            # the coordinates). A coarse voxel covers the 2 x 2 fine ones in its
            # place, so its centre is the middle of theirs: each copy
            # begins half of its own voxel less half a full-size voxel further
            # along y and x, and every copy covers the same ground. Depth is not
            # shrunk, so it stays where the full-size copy has it.
            "coordinateTransformations": [
                {
                    "type": "scale",
                    # Only the height and the width of a voxel double from one copy
                    # to the next. Its depth stays as it was, because no plane is
                    # ever dropped.
                    "scale": [1.0, 1.0, voxel_size_um[0],
                              voxel_size_um[1] * factor, voxel_size_um[2] * factor],
                },
                {
                    "type": "translation",
                    "translation": [
                        0.0, 0.0, first_voxel_um[0],
                        first_voxel_um[1] + 0.5 * (factor - 1) * voxel_size_um[1],
                        first_voxel_um[2] + 0.5 * (factor - 1) * voxel_size_um[2],
                    ],
                },
            ],
        })
    return arrays, datasets


def _write_the_description(
    store: Path, group, multiscale: dict, channel_blocks: list[dict], *, newer: bool
) -> None:
    """Record what this image is, in the place the chosen generation keeps it.

    This is the one part of writing an image that the two generations of OME-Zarr
    genuinely disagree about, so it is kept here on its own rather than left in
    the middle of building the arrays. Everything the description *says* is the
    same either way; only where it is written down differs.

    Args:
        store: the image folder, which version 0.4 writes a file beside.
        group: the zarr group the arrays were made in, which version 0.5 keeps
            its description inside.
        multiscale: the block describing the axes, the progressively smaller
            copies and where the image sits in the world.
        channel_blocks: one block per colour of light, saying how it should first
            appear on screen.
        newer: ``True`` for version 0.5, ``False`` for 0.4.
    """
    if newer:
        # In 0.5 the description lives inside the store's own ``zarr.json``, under an
        # ``ome`` key, and the version is stated once for the whole block rather than
        # on each multiscale. Written through zarr's own attributes rather than by
        # replacing the file, because that file also holds what zarr needs in order
        # to recognise the store at all -- writing over it by hand would leave an
        # image nothing could open.
        group.attrs.update({
            "ome": {
                "version": "0.5",
                "multiscales": [multiscale],
                "omero": {"channels": channel_blocks},
            }
        })
    else:
        # In 0.4 it is a file of its own beside the image, and each multiscale
        # carries the version itself.
        (store / ".zattrs").write_text(json.dumps({
            "multiscales": [{"version": "0.4", **multiscale}],
            "omero": {"channels": channel_blocks},
        }, indent=2), encoding="utf-8")

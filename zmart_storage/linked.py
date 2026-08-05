"""Showing a whole run as one picture without copying a single pixel of it.

Why this exists
---------------

:mod:`zmart_storage.cropped` hands the viewer one picture by **writing the run a
second time**: every tile goes into the archive whole, and a trimmed copy of it
goes into a canvas. That works, it is measured, and at the sizes this project has
reached so far the extra disk is an easy price.

At five terabytes it stops being a price and becomes a refusal. A run that size
cannot be copied in order to be looked at — there is not the disk, and the copying
itself would take long enough to change how the instrument is used.

This module is the other way of getting one picture. Nothing at full resolution is
copied. The view is a **list of pointers** into the tiles that already exist, and
the viewer is told those pointers describe a single, ordinary image.

The one idea it rests on
------------------------

A zarr image is stored as a grid of equal pieces, one file each. If a piece of the
*view* happens to be exactly a piece of one *tile*, byte for byte, then answering a
request for it is not assembling anything — it is handing over a file that already
exists on disk. No arithmetic is done on the pixels at all.

That is what this module arranges, and it is arithmetic rather than cleverness.
Two conditions have to hold, and both are checked here rather than assumed:

- **Where a tile lands in the view is a whole number of pieces**, so that the
  tile's own grid of pieces and the view's line up instead of being half a piece
  out;
- **the part of the tile the view shows is a whole number of pieces too**, so that
  the first piece the view asks for is a whole piece of the tile rather than a
  window straddling two.

Run with tiles that butt up against one another — the stage stepping by a whole
tile — both conditions hold for free, because the part shown is the whole tile and
tiles land a whole tile apart. A run whose tiles overlap can satisfy them as well,
but only if the pieces are small enough to divide the trim; see the table in
``viz_studio/LINKING_INSTEAD_OF_COPYING.md``, which works that through.

The limit to know about before using this
-----------------------------------------

A tile has to land on a piece boundary *exactly*. A stage asked to step 1792 voxels
steps 1792 give or take a couple, which is a fine result for the microscope and a
fatal one here: two voxels out is as fatal as half a piece out, because the bytes
wanted are then spread across two of the tile's files and no single file can be
handed over. Nothing that can be written in the description gets round this — zarr
describes an image as one regular grid, so a view can keep a tile's true position
or hand over its files untouched, but not both.

What this module does about it today is **refuse**, with a message saying what to
change. That is honest and it is safer than drawing a tile slightly out of place
with nothing on screen to say so, but it does mean this opens the exact grids the
tests build and not yet a run off a real stage.
``viz_studio/LINKING_INSTEAD_OF_COPYING.md`` describes the arrangement that fixes
it — giving each piece of the view to whichever tile covers it best, so the seam
lands on a piece boundary near the midline instead of exactly on it.

What still has to be written, and why
-------------------------------------

**The zoomed-out copies.** A viewer that is zoomed out draws a smaller copy of the
picture, and shrinking makes numbers that exist nowhere on disk — a voxel of the
half-size copy stands for several voxels of the full-size one, and where a tile
meets its neighbour those come from two different tiles. No existing file holds
that answer, so it cannot be pointed at and is written out here, once, exactly the
way :class:`zmart_storage.canvas.TileCanvases` writes it.

Those copies come to **about a quarter** of the full-size picture, and that is the
whole of the disk this arrangement uses. Each copy is half as wide and half as
tall as the one above, so it holds a quarter as many voxels; adding a quarter and a
sixteenth and a sixty-fourth and so on comes to a third, and a real run stops
before the sum runs out, which measures at around 26%. Copying the run instead
costs about eighty per cent more disk, so this is a large saving — but it is a
quarter, not the tenth an earlier draft of this docstring claimed.

**The description.** The viewer asks what the image is before it asks for any of
it: its axes, its size, how large a voxel is, where it sits on the stage, what
copies it has. None of that exists anywhere until this module works it out, and
almost all of it is read back out of the tiles themselves rather than being
supplied again — a view that had to be told the voxel size could be told the wrong
one, and nothing about the picture would say so.

**The list of pointers**, which is written beside the picture as a small file
called ``zmart-links.json``. It says, for each tile, which pieces of the view that
tile supplies and which of its own pieces they are. The viewer's server reads it;
see ``viz_studio/backend/linking.py``, which is the other half of this and is where
the file's shape is written down for the reader.

What is refused, and why it is refused loudly
---------------------------------------------

Bytes are handed over untouched, so the view's description has to agree with what
the tiles really contain — the kind of number a voxel is, what it is compressed
with, what an unwritten piece means, and which generation of zarr wrote it. A
disagreement there does not produce an error; it produces a picture of noise, or a
picture that is silently wrong. So every tile's storage description is compared
with every other's and with the view's own, exactly, and anything that does not
match is refused before a single pointer is written.

What this does not do
---------------------

It does not stitch, blend, or move anything by a fraction of a voxel — all of those
change pixels, and a pointer cannot change a pixel. And it does not follow a run as
it happens: the view is built from the tiles that exist when it is built.

Tiles that bundle their pieces
------------------------------

OME-Zarr 0.5 allows an image to keep many pieces inside one file, with a small index
saying where each of them begins. That is *sharding*, and it exists because a large
run otherwise leaves millions of small files behind, which most filesystems and most
backup software handle badly.

A view can be built over such tiles, and nothing about the idea changes — what gets
handed over is simply the bundle rather than a single piece. The viewer's engine
reads the bundle's index itself and asks for one piece out of the middle by byte
offset, which the server answers as an ordinary range of a file.

Two things follow that are worth knowing before choosing a bundle size. The view is
declared with the tiles' own bundling, because a view stored differently from its
tiles is a picture of noise. And **the bundle becomes the unit everything is
measured in**: a tile has to begin on a whole bundle boundary rather than merely a
whole piece boundary, and the smallest strip that can be trimmed off a tile where it
overlaps its neighbour is a whole bundle. Bundles that are too large therefore make
the placement harder to satisfy, not easier.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import zarr

from .canvas import Channel, TileCanvases, copies_for_a_canvas

# The small file, written inside the view's own folder, that says which piece of
# the view is which piece of which tile. The viewer's server reads it by this name;
# the shape of what is in it is described in ``viz_studio/backend/linking.py``, and
# the two have to be changed together.
LINKS_FILE = "zmart-links.json"

# Which shape of that file this is. A reader that meets a number it does not know
# should refuse rather than guess, because guessing wrongly would draw somebody
# else's tile in the wrong place with nothing on screen to say so.
#
# Version 2 added ``held_as`` to each tile, saying how one of its pieces is stored.
# Every tile written here says ``"file"`` — a piece of an ordinary zarr image is a
# file of its own — but saying it out loud is what lets a store that keeps many
# pieces inside one larger file be described later without the readers changing.
LINKS_VERSION = 2


# -- one tile, and where it appears in the view --------------------------------


@dataclass(frozen=True)
class PlacedTile:
    """One acquired tile, which part of it the view shows, and where it goes.

    Every number here is in voxels, given as ``(z, y, x)``.

    Attributes:
        store: the tile's own OME-Zarr folder, as written by an ordinary
            acquisition. It is read but never changed.
        lands_at: where the shown part's low corner sits in the view.
        taken_from: where the shown part begins inside the tile. Nought on every
            axis for a tile shown whole, which is the usual case; a run whose tiles
            overlap uses this to skip the strip its neighbour is showing.
        size: how much of the tile the view shows. Left out, the whole tile is
            shown, which is read from the tile itself so it cannot be got wrong.
    """

    store: Path
    lands_at: tuple[int, int, int]
    taken_from: tuple[int, int, int] = (0, 0, 0)
    size: tuple[int, int, int] | None = None


@dataclass(frozen=True)
class LinkedView:
    """A view that has been built: where it is, how large, and what it cost.

    Attributes:
        path: the view's own OME-Zarr folder. This is what the viewer is opened on.
        links: the small file of pointers inside it.
        shape: how large the picture is, as ``(z, y, x)`` in voxels.
        frames: how many moments it holds.
        channels: how many colours of light it holds.
        levels: how many progressively smaller copies it keeps, counting the
            full-size one — of which only the full-size one is pointed at rather
            than written.
        tiles: how many tiles the view points into.
        pointers: how many pieces of the view are answered by pointing at a tile.
            Nothing was written for any of them.
    """

    path: Path
    links: Path
    shape: tuple[int, int, int]
    frames: int
    channels: int
    levels: int
    tiles: int
    pointers: int


# -- reading what the tiles are, and refusing a set that disagrees -------------


@dataclass(frozen=True)
class _HowTheTilesAreStored:
    """Everything about the tiles that the view has to copy exactly to be readable."""

    ome_zarr_version: str
    described: dict          # the level's own storage description, minus its shape
    dtype: str
    chunk: tuple[int, int]   # how large one handed-over file is, across y and x
    # When the tiles bundle many pieces into one file -- sharding, which OME-Zarr
    # 0.5 allows -- this is how large one piece inside a bundle is. ``None`` when
    # each piece is a file of its own, which is the ordinary case.
    inside_a_bundle: tuple[int, int] | None
    shape: tuple[int, int, int]
    frames: int
    channels: int
    voxel_size_um: tuple[float, float, float]
    channel_blocks: list[dict]
    separator: str
    prefix: str
    axes: tuple[str, ...]    # what each axis of the picture means, in order


def _description_of(store: Path) -> tuple[dict, str]:
    """What a store says about itself, and which generation of OME-Zarr wrote it.

    The two generations keep the same information in different places: 0.4 writes
    a ``.zattrs`` file beside the image, and 0.5 keeps it inside ``zarr.json``
    under an ``ome`` key. Both are read here so that a view can be built over
    either.
    """
    newer = store / "zarr.json"
    if newer.is_file():
        held = json.loads(newer.read_text(encoding="utf-8"))
        attributes = held.get("attributes") or {}
        return attributes.get("ome") or attributes, "0.5"
    older = store / ".zattrs"
    if older.is_file():
        return json.loads(older.read_text(encoding="utf-8")), "0.4"
    raise ValueError(
        f"{store} does not look like an OME-Zarr image: neither a .zattrs file "
        "nor a zarr.json was found in it. A view can only be built over images, "
        "so check that this is the folder the acquisition wrote rather than the "
        "folder above it."
    )


def _storage_description_of(level: Path) -> dict:
    """How one copy of an image is stored: its pieces, its numbers, its compression.

    This is the part that has to agree exactly between the tiles and the view,
    because the view hands a tile's bytes over untouched. It is read as it was
    written down rather than through zarr, so that everything about it is compared
    — including the parts neither this module nor zarr has any opinion about.
    """
    for name in ("zarr.json", ".zarray"):
        held = level / name
        if held.is_file():
            return json.loads(held.read_text(encoding="utf-8"))
    raise ValueError(
        f"{level} holds no array description, so how its picture is stored cannot "
        "be read. That copy of the image was probably never declared."
    )


def _how_the_pieces_are_named(described: dict) -> tuple[str, str]:
    """What goes between the numbers of a piece's name, and what goes in front.

    A piece of a zarr image is filed under a name built from its position. Version 2
    joins the numbers with whatever separator the store declares; version 3 usually
    puts a ``c`` in front of them as well. Both spellings are read here, because the
    view has to ask for a tile's pieces by the names that tile actually used.

    This mirrors ``_read_array_description`` in the viewer's ``stores.py``, which
    asks the same question for a different reason.
    """
    if described.get("zarr_format") == 2:
        return str(described.get("dimension_separator") or "."), ""
    encoding = described.get("chunk_key_encoding") or {}
    configured = encoding.get("configuration") or {}
    separator = str(configured.get("separator") or "/")
    prefix = "" if encoding.get("name") == "v2" else "c"
    return separator, prefix


def _shape_of(described: dict) -> tuple[int, ...]:
    return tuple(int(n) for n in described["shape"])


def _chunk_of(described: dict) -> tuple[int, ...]:
    """How much picture one **handed-over file** holds.

    For an ordinary image that is one piece. For a *sharded* one — an image that
    bundles many pieces into a single file, which OME-Zarr 0.5 allows — it is the
    whole bundle, because the bundle is what exists as a file and therefore what a
    view can hand over. Zarr writes the bundle's size in the same place an ordinary
    image writes its piece size, so this needs no special case; what the bundle is
    made of is read by :func:`_pieces_inside_a_bundle` instead.
    """
    if described.get("zarr_format") == 2:
        return tuple(int(n) for n in described["chunks"])
    grid = (described.get("chunk_grid") or {}).get("configuration") or {}
    return tuple(int(n) for n in grid["chunk_shape"])


def _pieces_inside_a_bundle(described: dict) -> tuple[int, ...] | None:
    """How large one piece inside a bundle is, or ``None`` if there are no bundles.

    A sharded image keeps many pieces in one file and an index saying where each of
    them begins. The viewer's engine reads that index and asks for one piece out of
    the middle by byte offset, which the server answers — so a view over such tiles
    still hands over files untouched, it just hands over a bundle rather than a
    single piece.

    What this is needed for is *declaring* the view. The view has to be stored
    exactly as its tiles are, bundles and all, or its description and their bytes
    would disagree and the picture would come out as noise.
    """
    for codec in described.get("codecs") or []:
        if str(codec.get("name", "")).lower() == "sharding_indexed":
            inside = (codec.get("configuration") or {}).get("chunk_shape")
            if inside:
                return tuple(int(n) for n in inside)
    return None


def _what_the_tiles_are(tiles: list[PlacedTile]) -> _HowTheTilesAreStored:
    """Read the tiles, and refuse a set of them that does not agree with itself.

    Everything the view has to declare is read from the tiles here — how a voxel is
    stored, how large a piece is, how many colours and moments there are, how large
    a voxel is on the stage, what the colours are called. Asking the tiles rather
    than the caller is deliberate: a number supplied twice can be supplied
    differently the second time, and the picture would be wrong with nothing to say
    so.

    Raises:
        ValueError: if the tiles were not all written the same way. Bytes are
            passed through untouched, so a difference in how any one of them is
            stored would be handed to the viewer as though it were not there.
    """
    if not tiles:
        raise ValueError(
            "a view has to be built over at least one tile, and none were given. "
            "This usually means the run being pointed at has not written anything "
            "yet, or that the folder searched for tiles was the wrong one."
        )

    agreed: _HowTheTilesAreStored | None = None
    for placed in tiles:
        attributes, version = _description_of(placed.store)
        multiscale = (attributes.get("multiscales") or [{}])[0]
        datasets = multiscale.get("datasets") or []
        if len(datasets) != 1:
            raise ValueError(
                f"{placed.store} keeps {len(datasets)} copies of its picture, and a "
                "view can only be built over tiles that keep one. A tile is a single "
                "field of view, so there is nothing to zoom out from and the copies "
                "would only be work paid on every tile — the writer in "
                "zmart_storage.cropped therefore makes exactly one."
            )
        level = placed.store / str(datasets[0]["path"])
        described = _storage_description_of(level)
        shape = _shape_of(described)
        chunk = _chunk_of(described)
        inside = _pieces_inside_a_bundle(described)
        separator, prefix = _how_the_pieces_are_named(described)
        if len(shape) != 5:
            raise ValueError(
                f"{placed.store} has {len(shape)} axes and a view is built over "
                "tiles of five — a moment, a colour, and the three of space. That "
                "is what every acquisition this project writes declares."
            )
        if any(n != 1 for n in chunk[:3]):
            raise ValueError(
                f"{placed.store} keeps more than one moment, colour or plane in a "
                f"single piece of storage (one piece spans {chunk[:3]} of them). A "
                "view points at whole pieces, so a piece holding several planes "
                "could not be placed as one thing."
            )
        this_one = _HowTheTilesAreStored(
            ome_zarr_version=version,
            described={key: value for key, value in described.items() if key != "shape"},
            dtype=str(described.get("dtype") or described.get("data_type")),
            chunk=(chunk[-2], chunk[-1]),
            inside_a_bundle=(inside[-2], inside[-1]) if inside else None,
            shape=(shape[2], shape[3], shape[4]),
            frames=shape[0],
            channels=shape[1],
            voxel_size_um=_voxel_size_in(multiscale),
            channel_blocks=list((attributes.get("omero") or {}).get("channels") or []),
            separator=separator,
            prefix=prefix,
            axes=_axes_in(multiscale),
        )
        if agreed is None:
            agreed = this_one
            continue
        _refuse_tiles_stored_differently(tiles[0].store, placed.store, agreed, this_one)
    return agreed  # type: ignore[return-value]


def _refuse_tiles_stored_differently(
    first: Path, other: Path,
    agreed: _HowTheTilesAreStored, found: _HowTheTilesAreStored,
) -> None:
    """Stop a view whose tiles were not all written the same way.

    This is the check that matters most, and it is worth saying why. A view hands a
    tile's bytes to the viewer untouched, under a description it wrote itself. If
    the description says the numbers are sixteen bits and the bytes are eight, or
    says one kind of compression and the bytes are another, nothing anywhere reports
    an error — the viewer simply draws whatever those bytes happen to decode to.
    That is the worst way for anything to fail, so it is refused here instead.
    """
    if found.ome_zarr_version != agreed.ome_zarr_version:
        raise ValueError(
            f"{first} is OME-Zarr {agreed.ome_zarr_version} and {other} is "
            f"{found.ome_zarr_version}. A view is one image, and an image is written "
            "in one generation of the format, so tiles from both cannot be shown "
            "together. Build a view over each generation separately."
        )
    if found.described != agreed.described:
        differing = sorted(
            key for key in set(found.described) | set(agreed.described)
            if found.described.get(key) != agreed.described.get(key)
        )
        raise ValueError(
            f"{first} and {other} do not store their picture the same way — they "
            f"differ in {', '.join(differing)}. A view hands a tile's bytes to the "
            "viewer exactly as they are on disk, under one description that has to "
            "be true of all of them, so tiles compressed differently, or holding a "
            "different kind of number, or cut into different-sized pieces, cannot be "
            "shown as one picture.\n\n"
            "This normally means two acquisitions have been gathered up together. "
            "Build a view over each of them on its own."
        )
    if (found.frames, found.channels) != (agreed.frames, agreed.channels):
        raise ValueError(
            f"{first} holds {agreed.frames} moments and {agreed.channels} colours "
            f"while {other} holds {found.frames} and {found.channels}. A view keeps "
            "the moments and colours of its tiles as they are, so they all have to "
            "agree about how many there are."
        )
    if found.axes != agreed.axes:
        raise ValueError(
            f"{first} stores its picture as {', '.join(agreed.axes)} and {other} as "
            f"{', '.join(found.axes)}. A view hands both sets of bytes over under one "
            "description, so an axis that means a colour in one tile and a plane in "
            "the other would be read as the wrong thing without anything reporting "
            "it. Build a view over tiles that agree about what their axes mean."
        )
    if found.voxel_size_um != agreed.voxel_size_um:
        raise ValueError(
            f"{first} was taken with voxels of {agreed.voxel_size_um} micrometres "
            f"and {other} with {found.voxel_size_um}. Those are two different "
            "magnifications, which makes them two acquisitions rather than two "
            "tiles of one picture."
        )


def _axes_in(multiscale: dict) -> tuple[str, ...]:
    """What each axis of a tile's picture means, in the order they are stored.

    Named separately from everything else because of where it is written down. The
    rest of how a picture is stored -- its numbers, its compression, how large its
    pieces are -- lives in the array's own description, which this module compares
    whole and so cannot miss anything in. What the axes *mean* lives elsewhere, in
    the image's description, and would otherwise go unchecked.

    That would matter. A tile whose axes run colour, depth, height, width and one
    whose axes run depth, height, width can hold bytes that are the same length and
    pass every other check there is. Handed over together under one description,
    the same bytes are read as a different picture: a colour becomes a plane, and
    the specimen looks strange for no reason anybody can point at.
    """
    return tuple(str(axis.get("name", "")) for axis in multiscale.get("axes") or ())


def _voxel_size_in(multiscale: dict) -> tuple[float, float, float]:
    """How large one voxel is, read from a store's own description, as ``(z, y, x)``."""
    for dataset in multiscale.get("datasets") or []:
        for transform in dataset.get("coordinateTransformations") or []:
            if transform.get("type") == "scale":
                scale = [float(n) for n in transform["scale"]]
                return (scale[-3], scale[-2], scale[-1])
    raise ValueError(
        "this tile does not say how large one of its voxels is, so a view over it "
        "could not be drawn to scale. Every image this project writes says so; a "
        "store that does not is usually one that was copied without its description."
    )


def _where_the_view_begins(
    tiles: list[PlacedTile], voxel_size_um: tuple[float, float, float]
) -> tuple[float, float, float]:
    """Where the view's first voxel sits on the stage, in micrometres.

    Worked out from the tiles rather than asked for, and then checked against every
    one of them. Each tile records the place on the stage its own first voxel came
    from, and each says where it lands in the view — so each of them, on its own, is
    enough to say where the view's corner must be. Every tile agreeing is a strong
    check that the placements handed in are the real ones: if a tile is placed a row
    out, the corner it implies differs from the rest and it is refused here rather
    than drawn in the wrong place.
    """
    corners = []
    for placed in tiles:
        attributes, _ = _description_of(placed.store)
        multiscale = (attributes.get("multiscales") or [{}])[0]
        at = [0.0, 0.0, 0.0]
        for transform in multiscale.get("coordinateTransformations") or []:
            if transform.get("type") == "translation":
                moved = [float(n) for n in transform["translation"]]
                at = [at[axis] + moved[-3 + axis] for axis in range(3)]
        for dataset in multiscale.get("datasets") or []:
            for transform in dataset.get("coordinateTransformations") or []:
                if transform.get("type") == "translation":
                    moved = [float(n) for n in transform["translation"]]
                    at = [at[axis] + moved[-3 + axis] for axis in range(3)]
        corners.append(tuple(
            at[axis]
            + (placed.taken_from[axis] - placed.lands_at[axis]) * voxel_size_um[axis]
            for axis in range(3)
        ))
    first = corners[0]
    for placed, corner in zip(tiles, corners, strict=True):
        if any(abs(corner[axis] - first[axis]) > 1e-6 for axis in range(3)):
            raise ValueError(
                f"{placed.store} does not agree with {tiles[0].store} about where "
                "the view's low corner is: one puts it at "
                f"{tuple(round(n, 3) for n in corner)} micrometres on the stage and "
                f"the other at {tuple(round(n, 3) for n in first)}.\n\n"
                "Each tile records where it was taken from, and each has been told "
                "where it lands in the view, so each of them says where the view "
                "must begin. Two of them disagreeing means a tile has been placed "
                "somewhere other than where it was acquired, and the picture would "
                "be drawn with that tile in the wrong place."
            )
    return first  # type: ignore[return-value]


# -- the rule that makes pointing possible -------------------------------------


def _refuse_a_placement_that_does_not_land_on_whole_pieces(
    tiles: list[PlacedTile], stored: _HowTheTilesAreStored,
    shown: list[tuple[int, int, int]],
) -> None:
    """Stop a view whose pointers would not be whole files of a tile.

    This is the whole mechanism stated as a rule. A piece of the view can be handed
    over from a tile only if the two grids line up, which means a tile has to land on
    a boundary of whatever the tile keeps in one file, and the part of it being shown
    has to start and finish on one too. Where that does not hold, answering a request
    would mean cutting pixels out of one file and pasting them into another — which
    is exactly the copying this module exists to avoid, so it is refused rather than
    done slowly.

    **What counts as the unit depends on how the tiles were written.** Ordinarily it
    is a piece. But a tile may *bundle* many pieces into one file — sharding, which
    OME-Zarr 0.5 allows — and then the bundle is what exists as a file, so the bundle
    is what has to line up. That is worth saying plainly in the message, because it
    is the opposite of what an operator expects: choosing a larger bundle to keep the
    file count down makes this rule harder to satisfy, not easier.

    Only ``y`` and ``x`` are looked at. One file holds a single moment, a single
    colour and a single plane, so along those axes there is nothing to line up.
    """
    bundled = stored.inside_a_bundle is not None
    awkward = []
    for placed, size in zip(tiles, shown, strict=True):
        for axis, name in ((1, "y"), (2, "x")):
            piece = stored.chunk[axis - 1]
            for what, value in (
                ("lands at", placed.lands_at[axis]),
                ("is taken from", placed.taken_from[axis]),
                ("shows", size[axis]),
            ):
                if value % piece:
                    awkward.append((placed, name, what, value, piece))
    if not awkward:
        return
    placed, name, what, value, piece = awkward[0]

    if bundled:
        inside = stored.inside_a_bundle[name == "x"]  # type: ignore[index]
        raise ValueError(
            f"{placed.store} {what} {value} voxels in {name}, and the tiles bundle "
            f"their picture into files {piece} voxels across — each bundle holding "
            f"pieces of {inside} — so that is {value / piece:.2f} bundles rather "
            "than a whole number of them.\n\n"
            "A view shows part of a tile by handing over a file that already exists, "
            "and where pieces are bundled it is the **bundle** that is the file. So "
            "it is the bundle that has to line up, not the piece inside it. Part of "
            "a bundle out, answering would mean opening one file, taking pixels out "
            "of it and writing them into another — which is the copying this whole "
            "arrangement exists to avoid.\n\n"
            "This is the part that catches people out, so it is worth stating: a "
            "larger bundle makes this harder to satisfy, not easier. Bundling exists "
            "to keep a long run from leaving millions of small files behind, and the "
            "right size is the smallest that does that.\n\n"
            f"Two things put it right, and either will do. Acquire with bundles that "
            f"divide {value} — {inside} would do here if the pieces are left as they "
            "are, since a bundle has only to hold a whole number of pieces. Or place "
            "the tiles on a grid of whole bundles, which for a run whose tiles butt "
            "up happens on its own."
        )

    raise ValueError(
        f"{placed.store} {what} {value} voxels in {name}, and the tiles keep their "
        f"picture in pieces {piece} voxels across, so that is "
        f"{value / piece:.2f} pieces rather than a whole number of them.\n\n"
        "A view shows a piece of a tile by handing over the file that piece is "
        "already in, which it can only do when the view's pieces and the tile's line "
        "up exactly. Half a piece out, answering would mean cutting pixels out of "
        "one file and pasting them into another — which is the copying this whole "
        "arrangement exists to avoid.\n\n"
        f"Two things put it right, and either will do. Acquire with pieces that "
        f"divide {value} — the tiles are written with whatever piece size the "
        "acquisition asks for. Or place the tiles on a grid of whole pieces, which "
        "for a run whose tiles butt up happens on its own."
    )


# -- building the view ---------------------------------------------------------


def link_the_tiles(
    folder: str | Path,
    *,
    tiles: list[PlacedTile],
    name: str = "linked",
    view_shape: tuple[int, int, int] | None = None,
    levels: int | None = None,
    discard_existing_run: bool = False,
) -> LinkedView:
    """Present a folder of tiles to the viewer as one image, copying no full-size pixel.

    Everything the view declares about itself is read out of the tiles — how large a
    voxel is, what the colours are called, how the picture is stored, how many
    moments and colours there are — so there is nothing to state twice and get
    different both times.

    What this writes is small and is listed here so it is not a surprise: the view's
    description, its progressively smaller copies, and the list of pointers. The
    full-size picture is not written at all.

    Args:
        folder: the run's own folder, which is where the view is put. The tiles do
            not have to live in it, but they normally do — beside it, in the folder
            of whole tiles the acquisition wrote.
        tiles: the tiles, with where each of them lands in the view. See
            :class:`PlacedTile`.
        name: what to call the view. The image is named after it, and it is what the
            operator sees as the heading in the viewer's panel.
        view_shape: how large the picture is, as ``(z, y, x)`` in voxels. Left out,
            it is exactly big enough for the tiles given, which is usually right.
            Give it when the run means to declare the stage's whole travel range so
            that tiles arriving later still land inside the picture.
        levels: how many progressively smaller copies to keep, counting the
            full-size one. Normally left out, so that the same reckoning an ordinary
            canvas uses decides it from the size of the picture.
        discard_existing_run: whether to throw away a view already built in this
            folder under this name. The tiles are never touched either way.

    Returns:
        A :class:`LinkedView` saying where the view is and what it points at.

    Raises:
        ValueError: if the tiles were not all written the same way, if any of them
            would land somewhere other than on a whole piece boundary, if two of
            them disagree about where the view's corner is, or for any of the
            reasons :meth:`zmart_storage.canvas.TileCanvases.create` refuses a run.
    """
    folder = Path(folder)
    placed = [
        PlacedTile(Path(one.store), tuple(int(n) for n in one.lands_at),  # type: ignore[arg-type]
                   tuple(int(n) for n in one.taken_from), one.size)  # type: ignore[arg-type]
        for one in tiles
    ]
    stored = _what_the_tiles_are(placed)
    shown = [
        tuple(int(n) for n in (one.size if one.size is not None else stored.shape))
        for one in placed
    ]
    _refuse_a_part_of_a_tile_that_is_not_there(placed, shown, stored.shape)
    _refuse_a_placement_that_does_not_land_on_whole_pieces(placed, stored, shown)  # type: ignore[arg-type]

    reaches = tuple(
        max(one.lands_at[axis] + size[axis] for one, size in zip(placed, shown, strict=True))
        for axis in range(3)
    )
    shape = tuple(int(n) for n in (view_shape if view_shape is not None else reaches))
    _refuse_a_view_too_small_for_its_tiles(shape, reaches)  # type: ignore[arg-type]

    origin_um = _where_the_view_begins(placed, stored.voxel_size_um)
    biggest = tuple(max(size[axis] for size in shown) for axis in range(3))

    # The view is declared as an ordinary canvas, by the same writer an ordinary run
    # uses. That is what keeps a pointed-at view and a written-out one identical
    # everywhere it matters: the same axes, the same number of copies, the same piece
    # sizes, the same record of where the run imaged. The only difference is that
    # nothing is ever put into the full-size copy.
    canvas = TileCanvases.create(
        folder,
        name=name,
        canvas_shape=shape,  # type: ignore[arg-type]
        tile_shape=biggest,  # type: ignore[arg-type]
        tile_step=biggest,  # type: ignore[arg-type]
        voxel_size_um=stored.voxel_size_um,
        channels=_the_colours_the_tiles_record(stored),
        origin_um=origin_um,
        frames=stored.frames,
        dtype=_a_numpy_name_for(stored.dtype),
        # A view stored differently from its tiles is a picture of noise, so where
        # the tiles bundle their pieces the view is declared to bundle them the same
        # way: its pieces are the tiles' pieces, and its bundles are their bundles.
        chunk=(stored.inside_a_bundle or stored.chunk)[0],
        shard=stored.chunk[0] if stored.inside_a_bundle else None,
        levels=levels,
        discard_existing_run=discard_existing_run,
        ome_zarr_version=stored.ome_zarr_version,
    )
    view = canvas.paths[0]
    try:
        _refuse_a_view_stored_differently_from_its_tiles(view, stored)
        _say_where_each_resolution_sits(view, origin_um, stored.ome_zarr_version)
        pointers = _fill_in_the_zoomed_out_copies(canvas, placed, shown)
        links = _write_the_list_of_pointers(view, folder, placed, shown, stored)
    finally:
        canvas.close()

    return LinkedView(
        path=view,
        links=links,
        shape=shape,  # type: ignore[arg-type]
        frames=stored.frames,
        channels=stored.channels,
        levels=levels if levels is not None else copies_for_a_canvas(shape),
        tiles=len(placed),
        pointers=pointers,
    )


def _refuse_a_part_of_a_tile_that_is_not_there(
    tiles: list[PlacedTile], shown: list[tuple[int, int, int]],
    tile_shape: tuple[int, int, int],
) -> None:
    """Stop a view asking a tile for more picture than the tile holds."""
    for placed, size in zip(tiles, shown, strict=True):
        for axis in range(3):
            if placed.taken_from[axis] < 0 or size[axis] < 1:
                raise ValueError(
                    f"{placed.store} is asked for {size[axis]} voxels starting at "
                    f"{placed.taken_from[axis]} on axis {'zyx'[axis]}, which is not "
                    "a part of a tile that could exist."
                )
            if placed.taken_from[axis] + size[axis] > tile_shape[axis]:
                raise ValueError(
                    f"{placed.store} is {tile_shape[axis]} voxels across in "
                    f"{'zyx'[axis]}, and the view asks it for {size[axis]} voxels "
                    f"starting at {placed.taken_from[axis]}, which reaches past the "
                    "end of it. The part shown has to be inside the tile."
                )


def _refuse_a_view_too_small_for_its_tiles(
    shape: tuple[int, int, int], reaches: tuple[int, int, int]
) -> None:
    """Stop a view declared smaller than the tiles it is being built over."""
    if all(shape[axis] >= reaches[axis] for axis in range(3)):
        return
    raise ValueError(
        f"the view was declared {shape} voxels and its tiles reach to {reaches}, so "
        "some of them would sit outside the picture and could not be drawn at all. "
        "Declare at least as much room as the tiles need — room that holds no tile "
        "costs practically nothing, because nothing is written to it."
    )


def _the_colours_the_tiles_record(stored: _HowTheTilesAreStored) -> list[Channel]:
    """The colours of light the tiles record, as the view should declare them.

    Taken from the tiles' own description so that the view opens looking exactly as
    a picture of those tiles should — same names, same colours, same starting
    brightness. A tile that says nothing about its colours leaves the view to name
    them by number, which is what the viewer would fall back to anyway.
    """
    colours = []
    for at in range(stored.channels):
        block = stored.channel_blocks[at] if at < len(stored.channel_blocks) else {}
        window = block.get("window") or {}
        colours.append(Channel(
            name=str(block.get("label") or at),
            color=block.get("color"),
            window=(
                (window["start"], window["end"])
                if "start" in window and "end" in window else None
            ),
        ))
    return colours


def _a_numpy_name_for(dtype: str) -> str:
    """The kind of number a voxel is, spelled the way numpy spells it.

    The two generations of zarr write this differently — ``"<u2"`` in one and
    ``"uint16"`` in the other — and the writer wants numpy's own name, so both are
    put through numpy here rather than being translated by hand.
    """
    return str(np.dtype(dtype).name)


def _refuse_a_view_stored_differently_from_its_tiles(
    view: Path, stored: _HowTheTilesAreStored
) -> None:
    """Stop a view whose full-size copy is not stored exactly as its tiles are.

    Everything about how the view stores its picture was taken from the tiles a
    moment ago, so this should never fail. It is asked anyway, because the cost of
    asking is one small file read and the cost of being wrong is a picture of noise
    that nothing reports. If it ever does fail, something in the canvas writer has
    changed and this is the honest place to find out.
    """
    described = _storage_description_of(view / "0")
    mine = {key: value for key, value in described.items() if key != "shape"}
    if mine == stored.described:
        return
    differing = sorted(
        key for key in set(mine) | set(stored.described)
        if mine.get(key) != stored.described.get(key)
    )
    raise ValueError(
        "the view was declared with a different way of storing its picture than the "
        f"tiles it points at — they differ in {', '.join(differing)}. The view hands "
        "a tile's bytes over exactly as they are, so a difference here would be a "
        "picture of noise rather than of the specimen.\n\n"
        f"The view says {mine} and the tiles say {stored.described}."
    )


def _say_where_each_resolution_sits(
    view: Path, origin_um: tuple[float, float, float], ome_zarr_version: str
) -> None:
    """Write the view's place on the stage beside every one of its copies.

    OME-Zarr allows the position to be written in two places: beside each copy of
    the image, or once for the image as a whole. The format's own examples use the
    first; a good deal of the Python imaging world — anything built on ``ngff-zarr``,
    which includes ``multiview-stitcher`` — reads **only** the first and quietly
    places an image at the origin if it is not there. ``viz_studio/INTEROP.md`` §1
    measures what that costs: every store written the other way is drawn stacked on
    top of every other.

    So the view says it in the per-copy place, and only there. Saying it in both
    would be worse than saying it once, because a reader that composes the two — the
    viewer's own engine does — would move the picture twice.
    """
    at = [0.0, 0.0, float(origin_um[0]), float(origin_um[1]), float(origin_um[2])]
    moved = {"type": "translation", "translation": at}

    def repositioned(multiscale: dict) -> dict:
        rebuilt = dict(multiscale)
        rebuilt["datasets"] = [
            {**dataset, "coordinateTransformations": [
                *(dataset.get("coordinateTransformations") or []), moved,
            ]}
            for dataset in multiscale.get("datasets") or []
        ]
        rebuilt.pop("coordinateTransformations", None)
        return rebuilt

    if ome_zarr_version == "0.5":
        held = view / "zarr.json"
        document = json.loads(held.read_text(encoding="utf-8"))
        block = document["attributes"]["ome"]
        block["multiscales"] = [repositioned(one) for one in block["multiscales"]]
        held.write_text(json.dumps(document, indent=2), encoding="utf-8")
        return
    held = view / ".zattrs"
    document = json.loads(held.read_text(encoding="utf-8"))
    document["multiscales"] = [repositioned(one) for one in document["multiscales"]]
    held.write_text(json.dumps(document, indent=2), encoding="utf-8")


def _fill_in_the_zoomed_out_copies(
    canvas: TileCanvases, tiles: list[PlacedTile], shown: list[tuple[int, int, int]]
) -> int:
    """Write the smaller copies of the picture, and count the pieces that are pointed at.

    The smaller copies are the part that genuinely cannot be pointed at, because
    shrinking makes numbers no file holds. They are written here by the ordinary
    canvas writer, from the tiles' own pixels, so that a pointed-at view and a
    written-out one are the same picture at every zoom rather than only at full
    size.

    Reading each tile back to do it is real work, and it is the honest cost of
    building a view: about a quarter of what writing the whole picture would cost,
    because only the smaller copies come out of it.
    """
    pointed_at = 0
    for placed, size in zip(tiles, shown, strict=True):
        held = zarr.open_group(str(placed.store), mode="r")["0"]
        frames, channels = held.shape[0], held.shape[1]
        low = placed.taken_from
        picture = np.asarray(held[
            :, :,
            low[0]:low[0] + size[0],
            low[1]:low[1] + size[1],
            low[2]:low[2] + size[2],
        ])
        for frame in range(frames):
            for channel in range(channels):
                canvas.only_the_zoomed_out_copies(
                    picture[frame, channel],
                    origin=placed.lands_at,
                    channel=channel,
                    frame=frame,
                )
        pointed_at += frames * channels * size[0]
    return pointed_at


def _write_the_list_of_pointers(
    view: Path, folder: Path, tiles: list[PlacedTile],
    shown: list[tuple[int, int, int]], stored: _HowTheTilesAreStored,
) -> Path:
    """Write down which piece of the view is which piece of which tile.

    Everything in the file is counted in **pieces** rather than voxels, which is
    what keeps the viewer's server free of any arithmetic on pixels: it turns the
    name of a piece it has been asked for into the name of a piece that exists, and
    hands that file over.

    Each tile is written down as where it belongs to the view rather than as one
    entry per piece. A run of ten thousand tiles is then ten thousand short lines
    instead of a hundred thousand, and the server spreads them out into a lookup
    when it first needs one.
    """
    piece_y, piece_x = stored.chunk
    listed = []
    for placed, size in zip(tiles, shown, strict=True):
        listed.append({
            # Where the tile lives, said relative to the folder the view sits in,
            # so that a run can be moved or copied elsewhere and still be readable.
            "store": _said_relative_to(placed.store, folder),
            "at": [placed.lands_at[0], placed.lands_at[1] // piece_y,
                   placed.lands_at[2] // piece_x],
            "size": [size[0], size[1] // piece_y, size[2] // piece_x],
            "from": [placed.taken_from[0], placed.taken_from[1] // piece_y,
                     placed.taken_from[2] // piece_x],
            # How one piece of this tile is stored. A piece of an ordinary zarr
            # image is a file of its own, so asking where a piece is gives back
            # the whole of that file. It is written down rather than assumed
            # because a sharded tile keeps many pieces inside one larger file, and
            # a piece of that is a stretch in the middle of it — which the reader
            # can be taught without every view already written becoming unreadable.
            "held_as": "file",
        })
    held = view / LINKS_FILE
    held.write_text(json.dumps({
        "version": LINKS_VERSION,
        "what": (
            "Which piece of this view's full-size picture is which piece of which "
            "tile. Nothing of the full-size picture is stored here: the viewer's "
            "server reads this and hands over the tile's own file. Positions are "
            "counted in pieces, not voxels."
        ),
        "level": "0",
        "separator": stored.separator,
        "prefix": stored.prefix,
        "tiles": listed,
    }, indent=1), encoding="utf-8")
    return held


def _said_relative_to(store: Path, folder: Path) -> str:
    """Where a tile lives, written down relative to the folder holding the view.

    Kept relative so that a whole run can be copied to another disk, or looked at
    over a share, without every pointer in it becoming wrong. A tile that genuinely
    sits somewhere else entirely keeps its full path, which still works as long as
    it is inside the folder the viewer was opened on.
    """
    try:
        return store.resolve().relative_to(folder.resolve()).as_posix()
    except ValueError:
        return store.resolve().as_posix()

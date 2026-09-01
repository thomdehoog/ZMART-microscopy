"""Keeping the overlap and still handing the viewer one picture.

Why this exists
---------------

Microscopists usually acquire with the tiles deliberately overlapping — ten or
fifteen per cent is common. The overlap is not waste. It is the only evidence
that says where the stage *really* put each tile, as opposed to where it reported
putting it, because the strip two tiles both photographed can afterwards be
compared and the difference measured. A stitcher needs that strip; without it
there is nothing to compare and the seams stay wherever the stage happened to
leave them.

:mod:`zmart_storage.canvas` cannot accept such a run, and it is right not to. It
writes everything into one large image, an image holds a single value per voxel,
and so the second tile of an overlapping pair would quietly replace the strip it
shares with the first. That writer therefore refuses an overlapping acquisition
outright rather than losing a fifth of the acquired data with nothing to show for
it.

But the viewer really does want one image. Measured in this repository, a folder
of a thousand separate positions drew twenty-four frames in five seconds where a
hundred managed three hundred, because the drawing engine builds layers per image
and every one of them takes part in every frame. A run of ten thousand tiles
cannot be a folder of ten thousand images and still be usable.

This module is the way out of that, and the idea is simple enough to state in one
sentence: **write the acquisition twice, once whole and once trimmed.**

What gets written
-----------------

Two things sit side by side in the run's folder, and each has one job::

    run/
      overview.ome.zarr/            the canvas -- one image, trimmed, for the viewer
      overview_tiles/               the archive -- every tile whole, overlap intact
        overview_pos00000.ome.zarr
        overview_pos00001.ome.zarr
        ...
      zmart-coverage/               where the run actually imaged
        overview.ome.zarr/

**The tiles**, exactly as the camera recorded them, one small OME-Zarr per
position. Nothing is trimmed, nothing is averaged, and no voxel is written twice,
so every reading the instrument made is still on disk afterwards. This is the
archive, and it is what a stitcher is given when somebody comes to solve the
alignment properly. It is also ordinary OME-Zarr, so it opens in napari, in Fiji,
and in whatever a colleague happens to use.

**The canvas**, which is one image holding each tile with the overlapping parts
taken off. Where two tiles meet, half the shared strip comes off each of them, so
what goes in covers exactly the ground the stage stepped by. Trimmed that way,
neighbouring tiles butt up against one another and touch nowhere at all — which
means nothing is ever written over, and the existing refusal in
:func:`zmart_storage.canvas._refuse_overlapping_tiles` is satisfied without being
weakened by a single line. That refusal is not worked around here; trimming is
what makes it beside the point.

The viewer opens the canvas and nothing else, so it holds one image however many
tiles the run gathers.

How much comes off, and where
-----------------------------

Nothing about the trimming is chosen or switched on. It is worked out, axis by
axis, from two numbers the acquisition has already had to state::

    overlap on an axis = the tile's size on that axis - the stage's step on it
    what comes off each meeting edge = half of that

Three things follow from putting it that way, and each of them matters.

**A run whose tiles butt up is not a special case.** Its overlap is nought on
every axis, so nothing is trimmed, and what this writer does is exactly what
:class:`zmart_storage.canvas.TileCanvases` does on its own. There is no setting to
get wrong, which is the point: a setting can be wrong for a whole run before
anybody notices, whereas the tile size and the stage's step are facts the run
could not have started without.

**Depth is treated like anything else.** Many runs overlap across the specimen and
not at all in depth, and they get no trimming in depth. A run that also overlaps
its stacks — stepping the stage in ``z`` by less than the depth it images — is
trimmed in depth by the same arithmetic. Neither case needs saying out loud.

**Only edges that face another tile are cut.** A tile at the edge of the raster
has nothing on its far side, so there is nothing to replace what would be cut
there, and trimming it would throw away a strip of real specimen right around the
outside of the run. So an edge is trimmed only where a neighbour is going to
butt up against it, and the picture the canvas holds covers exactly the ground the
run covered — no more and no less. Whether a tile has a neighbour is read from its
place in the scan pattern, which is what ``tile_index`` says, together with how
many tiles the pattern takes, which is what ``tile_grid`` says.

Two rules the arithmetic imposes
--------------------------------

**The overlap has to be an even number of voxels** wherever it is not nought,
because half of an odd number of voxels is not a voxel. An acquisition can choose
its overlap freely, so this costs nothing to satisfy, and a run that breaks it is
refused when it is declared rather than left to lose or duplicate a row.

**A trimmed tile has to be a whole number of pieces of the canvas.** A zarr image
is stored as a grid of equal pieces, and a piece is read, changed and written back
as a unit. If a trimmed tile is not a whole number of them, the boundary between
two neighbouring tiles falls in the middle of a piece, the two tiles share that
piece, and every such piece has to be written by one tile and then re-read and
rewritten by the next. Nothing is lost — the writer notices and takes the tiles in
turn — but a run pays for it on every tile, and the arrangement stops being the
clean one it was meant to be. With 128-voxel tiles and pieces of 96, an overlap of
32 leaves a trimmed tile of 96, which is exactly one piece.

That second rule is asked only where tiles genuinely meet. An axis with no overlap
is trimmed by nothing, so there is nothing this writer has to say about it that
:class:`zmart_storage.canvas.TileCanvases` does not already say on its own; and an
axis the pattern takes only one tile along has no seam at all, so a run of a single
target is never held to it.

There is one small consequence of the two rules together that is worth knowing
about, because it shows up if you look at the canvas's declared corner. The
untrimmed outer edges of the perimeter tiles have to go somewhere, and they cannot
sit at a negative position — so the canvas begins a little before the stage's low
corner, by a whole number of pieces, leaving a blank margin around the run. That
margin is what lets the outer edges have their room while every trimmed tile still
lands exactly on a piece boundary. It is never written to, so it costs nothing on
disk, and the canvas's declared position accounts for it so the picture is still
drawn in its true place.

What this costs, said plainly
-----------------------------

It costs disk. The overlapping part of every tile is stored twice: once whole in
the archive, and once as somebody's trimmed remainder in the canvas. On a run
overlapping by an eighth that is roughly a quarter more space than writing the
tiles alone, and about twice the space of writing only the canvas. Disk is the
cheapest thing in a microscope room and lost photons are the most expensive, so
that is a trade worth making — but it is a real cost and it should be budgeted
for rather than discovered.

It also costs a little time on every tile, because two writes happen instead of
one. The archive write is the cheap half: one small store, no progressively
smaller copies to keep up to date.

And what it does *not* do is stitch. The canvas is a picture assembled from where
the stage said each tile was, with hard joins between the trimmed tiles. If the
stage was slightly off, the join is slightly off, exactly as it would be for a run
acquired without overlap. The difference — the whole point — is that the evidence
needed to correct it is still on disk, in the archive, instead of having been
thrown away at the moment of writing.
"""

from __future__ import annotations

import threading
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .canvas import Channel, TileCanvases, _declare_one
from .coverage import Coverage, imaged_regions

# What the folder of whole tiles is called, sitting beside the canvas in the run's
# folder. The name is deliberately not one the viewer would mistake for an image:
# it is a plain folder holding images rather than an image itself, so a viewer
# looking in the run's folder finds the canvas and walks past this.
_TILES_FOLDER_ENDING = "_tiles"

# Which sides of a tile face another tile, as a low side and a high side for each
# of depth, height and width. A tile with nothing next to it anywhere -- a single
# target the workflow chose for itself -- has this, and so keeps every voxel.
NO_NEIGHBOURS: tuple[tuple[bool, bool], ...] = ((False, False),) * 3


# -- the arithmetic of trimming ------------------------------------------------


def neighbours_of(tile_index, tile_grid) -> tuple[tuple[bool, bool], ...]:
    """Which sides of one tile another tile is going to butt up against.

    This is the question that decides where trimming happens, and it is answered
    from the scan pattern rather than from anything about the picture. An edge with
    a neighbour is trimmed, because the neighbour's own recording of that ground
    takes its place; an edge with nothing beyond it is left alone, because there is
    nothing to take its place and cutting it would simply lose specimen.

    Args:
        tile_index: the tile's place in the scan pattern, as ``(z, y, x)`` counts
            from nought, or ``None`` for a position the workflow chose for itself.
            A position with no place in a pattern has no neighbours by definition —
            nothing is going to butt up against it — so nothing is trimmed off it.
        tile_grid: how many tiles the pattern takes in each direction, as
            ``(z, y, x)``, or ``None`` if the run did not say. Without it the far
            edge of the pattern cannot be recognised, so every high side is treated
            as having a neighbour; :meth:`TilesAndCanvas.create` says so out loud
            when a run is declared that way.

    Returns:
        For each of depth, height and width, whether there is a neighbour on the
        low side and whether there is one on the high side.
    """
    if tile_index is None:
        return NO_NEIGHBOURS
    return tuple(
        (
            int(tile_index[axis]) > 0,
            tile_grid is None or int(tile_index[axis]) < int(tile_grid[axis]) - 1,
        )
        for axis in range(3)
    )


@dataclass(frozen=True)
class Trimming:
    """How much comes off a tile where it meets a neighbour, and what is left.

    Every number here is in voxels, given as ``(z, y, x)``.

    Attributes:
        overlap: how much ground neighbouring tiles both photographed, which is
            simply how far short of a whole tile the stage stepped. Nought on an
            axis the stage does not overlap in, which is usual for depth.
        half: how much comes off one edge where two tiles meet — half the overlap,
            since each of the pair gives up the same amount.
        kept: what a tile with neighbours on both sides is left with, which is
            exactly how far the stage steps. That is what makes trimmed tiles butt
            up rather than overlap. A tile at the edge of the pattern keeps more,
            because its outer edges are not cut.
    """

    overlap: tuple[int, int, int]
    half: tuple[int, int, int]
    kept: tuple[int, int, int]

    @classmethod
    def of(cls, tile_shape, tile_step) -> Trimming:
        """Work out the trimming for a tile of this size stepped this far.

        Args:
            tile_shape: the size of one acquired tile, as ``(z, y, x)`` in voxels.
            tile_step: how far the stage moves between neighbouring tiles, the
                same way. A step smaller than the tile is an overlap; a step at
                least as large as the tile is no overlap at all, and then nothing
                is trimmed on that axis.

        Returns:
            The trimming, from which the kept part of any tile can be cut.

        Raises:
            ValueError: if the stage steps by nothing or by a negative amount on
                some axis, which would leave no tile behind at all; or if the
                overlap on some axis is an odd number of voxels, which cannot be
                shared evenly between the two tiles that meet there.
        """
        shape = tuple(int(n) for n in tile_shape)
        step = tuple(int(n) for n in tile_step)
        if any(n < 1 for n in step):
            raise ValueError(
                f"the stage is said to step by {step} voxels between tiles, and a "
                "step has to be at least one voxel on every axis. A step of nought "
                "would mean the microscope never moved, so every tile would be the "
                "same field of view and the canvas would hold one tile's worth of "
                "picture however long the run went on."
            )
        overlap = tuple(max(0, shape[axis] - step[axis]) for axis in range(3))
        _refuse_an_overlap_that_cannot_be_halved(shape, step, overlap)
        half = tuple(n // 2 for n in overlap)
        kept = tuple(shape[axis] - overlap[axis] for axis in range(3))
        return cls(overlap=overlap, half=half, kept=kept)  # type: ignore[arg-type]

    @property
    def anything_to_trim(self) -> bool:
        """Whether this acquisition overlaps at all."""
        return any(n > 0 for n in self.overlap)

    def cut(self, tile: np.ndarray, neighbours) -> np.ndarray:
        """The part of one tile that belongs to it, given what is around it.

        Args:
            tile: the tile's voxels as the camera recorded them, shaped
                ``(z, y, x)``.
            neighbours: which sides face another tile, as
                :func:`neighbours_of` gives them.

        Returns:
            A view of the part to be kept. It is a view rather than a copy, so
            nothing is duplicated in memory on the way to being written.
        """
        return tile[tuple(
            slice(
                self.half[axis] if neighbours[axis][0] else 0,
                tile.shape[axis] - (self.half[axis] if neighbours[axis][1] else 0),
            )
            for axis in range(3)
        )]

    def lands_at(self, origin, neighbours, shift) -> tuple[int, int, int]:
        """Where the kept part of a tile belongs in the canvas, in canvas voxels.

        Args:
            origin: the tile's low corner on the stage, as ``(z, y, x)`` in voxels.
            neighbours: which sides face another tile.
            shift: how far the canvas begins before the stage's low corner, which
                is the blank margin the outer edges of the perimeter tiles need.

        Returns:
            The corner to write the kept part at.
        """
        return tuple(  # type: ignore[return-value]
            int(origin[axis])
            + (self.half[axis] if neighbours[axis][0] else 0)
            + int(shift[axis])
            for axis in range(3)
        )


def _refuse_an_overlap_that_cannot_be_halved(shape, step, overlap) -> None:
    """Stop a run whose tiles overlap by an odd number of voxels.

    Where two tiles meet, each gives up half the strip they share. An odd overlap
    has no half: one of the two would have to give up a voxel more than the other,
    and whichever way that was settled the picture would be a voxel out of step
    with the stage on one side of every seam. Since an experiment chooses its
    overlap freely, the honest thing is to say so now — while it costs a single
    change to a scan pattern — rather than to pick a side quietly.
    """
    odd = [
        (("z", "y", "x")[axis], overlap[axis])
        for axis in range(3)
        if overlap[axis] % 2
    ]
    if not odd:
        return
    described = ", ".join(f"{by} voxels in {axis}" for axis, by in odd)
    axis, by = odd[0]
    at = ("z", "y", "x").index(axis)
    raise ValueError(
        f"these tiles overlap by an odd number of voxels ({described}), and an odd "
        "overlap cannot be shared evenly between the two tiles that meet in it. "
        "Each of a meeting pair gives up half the strip they share, and half of "
        f"{by} voxels is not a whole voxel.\n\n"
        f"Change the step a little so the overlap comes out even: a tile of "
        f"{shape[at]} voxels in {axis} stepped {step[at]} could be stepped "
        f"{step[at] - 1} or {step[at] + 1} instead, which overlaps by {by + 1} or "
        f"{by - 1}. Nothing about the experiment depends on the odd voxel — the "
        "overlap is there to be compared afterwards, and one voxel either way makes "
        "no difference to that."
    )


def the_piece_the_canvas_will_use(canvas_shape, chunk: int) -> int:
    """How large one piece of the full-size canvas really is, across ``y`` and ``x``.

    Almost always this is simply the piece size that was asked for. The exception is
    a canvas narrower than one piece — a run of a single tile, say — where a piece
    cannot be larger than the whole image and is cut down to fit.

    Asking the question here, once, matters for a reason that is easy to miss. The
    rule about trimmed tiles landing on whole pieces has to be checked against the
    pieces the canvas will genuinely be stored in; and the canvas writer, told a
    piece size larger than the image it is making, quietly uses a smaller one and
    would otherwise warn about a mismatch that only exists in the number it was
    handed. Working the real figure out first means both agree.

    Args:
        canvas_shape: how much room the run declared, as ``(z, y, x)`` in voxels.
        chunk: the piece size that was asked for.

    Returns:
        The piece size the canvas will really use across the specimen, which is
        never larger than the canvas itself.
    """
    return min(int(chunk), int(canvas_shape[1]), int(canvas_shape[2]))


def _refuse_a_trim_that_does_not_land_on_whole_pieces(
    trimming: Trimming, tile_shape, piece: int, tile_grid
) -> None:
    """Stop a run whose trimmed tiles would straddle the pieces of the canvas.

    This is checked once when the run is declared rather than met later as a run
    that is mysteriously slow. The module's opening notes say what it is about; the
    message here says what to do instead.

    Only ``y`` and ``x`` are looked at. The canvas keeps one moment, one colour and
    one plane in each piece, so along the other axes a piece can hold no more than
    one tile and there is nothing to line up.

    Two situations are passed over, both because there is genuinely nothing to line
    up in them. An axis with no overlap is trimmed by nothing, so this writer has no
    more to say about it than :class:`zmart_storage.canvas.TileCanvases` already
    does on its own. And an axis the pattern takes only one tile along has no seam
    on it at all — a run of a single target, most often — so nothing meets anything
    and the tile can sit wherever it lands.

    Raises:
        ValueError: if a trimmed tile is not a whole number of pieces. The message
            names the overlaps nearest to the one asked for that would work, since
            the overlap is the number an experiment can actually choose.
    """
    awkward = [
        (name, axis)
        for axis, name in ((1, "y"), (2, "x"))
        if trimming.half[axis]
        and (tile_grid is None or int(tile_grid[axis]) > 1)
        and trimming.kept[axis] % piece
    ]
    if not awkward:
        return

    name, axis = awkward[0]
    tile = int(tile_shape[axis])
    kept = trimming.kept[axis]
    # The overlaps that would work are the ones leaving a whole number of pieces,
    # so they are named directly rather than left for the reader to work out. An
    # odd one is left out, because an odd overlap is refused for its own reasons.
    workable = sorted(
        tile - whole * piece
        for whole in range(1, tile // piece + 1)
        if 0 <= tile - whole * piece < tile and (tile - whole * piece) % 2 == 0
    )
    suggestion = (
        "There is no overlap that would work with a tile and a piece of these "
        f"sizes, because a tile of {tile} voxels is not itself a whole number of "
        f"{piece}-voxel pieces. Change the piece size instead: any size that "
        f"divides {tile} exactly will do."
        if not workable else
        "Overlaps that would work here, in voxels: "
        + ", ".join(str(n) for n in workable)
        + ". Choosing one of them costs the experiment nothing — the overlap is "
        "there to be compared afterwards, and a few voxels either way makes no "
        "difference to that."
    )
    raise ValueError(
        f"trimming this acquisition would leave a tile of {kept} voxels in {name}, "
        f"and the canvas stores its picture in pieces {piece} voxels across, so a "
        f"trimmed tile is {kept / piece:.2f} pieces rather than a whole number of "
        "them.\n\n"
        "That matters because the boundary between two neighbouring tiles would "
        "then fall in the middle of a piece. A piece is read, changed and written "
        "back as a unit, so both tiles would have to write it and one would have to "
        "wait for the other — on every seam, for the whole run. Nothing would be "
        "lost, but the arrangement would stop being the clean one it is meant to "
        "be, and it is far easier to put right now than to notice later.\n\n"
        f"{suggestion}"
    )


def _the_blank_margin(trimming: Trimming, piece: int) -> tuple[int, int, int]:
    """How far before the stage's low corner the canvas has to begin.

    The tiles at the low edge of the pattern keep their outer edges, so the canvas
    has to have room for them below where the first trimmed tile sits — and a
    position in an image cannot be negative. Across the specimen that room is
    rounded up to a whole number of pieces, which is what keeps every trimmed tile
    landing exactly on a piece boundary; in depth a piece holds a single plane, so
    no rounding is needed and the room is exactly what the outer edge takes.

    A run whose tiles butt up needs no margin at all, and gets none, which is what
    makes it behave exactly as :class:`zmart_storage.canvas.TileCanvases` does.
    """
    across = tuple(
        -(-trimming.half[axis] // piece) * piece for axis in (1, 2)
    )
    return (trimming.half[0], across[0], across[1])


# -- writing the two things ----------------------------------------------------


class TilesAndCanvas:
    """An overlapping run, written twice: every tile whole, and one trimmed canvas.

    Make one at the start of a run with :meth:`create` and call :meth:`write` once
    per acquired tile, exactly as you would with
    :class:`zmart_storage.canvas.TileCanvases`. Each call puts the tile away whole,
    in a small image of its own, and puts its trimmed part into the canvas the
    viewer is watching.

    Nothing has to be finished off at the end. Both the archive and the canvas are
    complete and readable throughout, which is what lets somebody watch the run as
    it happens. :meth:`close` is worth calling when the run is over, mainly so that
    the record of where it imaged is brought fully up to date.

    A run recording more than one acquisition type — an overview and a target scan,
    say — makes one of these per type, and their canvases sit side by side in the
    run's folder with a folder of whole tiles beside each.
    """

    def __init__(
        self,
        folder: Path,
        canvas: TileCanvases,
        *,
        name: str,
        trimming: Trimming,
        shift: tuple[int, int, int],
        tile_shape: tuple[int, int, int],
        tile_grid: tuple[int, int, int] | None,
        voxel_size_um: tuple[float, float, float],
        origin_um: tuple[float, float, float],
        channels: list[Channel],
        frames: int,
        dtype: str,
        ome_zarr_version: str,
    ) -> None:
        self.folder = Path(folder)
        self.name = name
        self.trimming = trimming
        self.shift = shift
        self.tile_shape = tuple(int(n) for n in tile_shape)
        self.tile_grid = tile_grid
        self._canvas = canvas
        self._voxel_size_um = tuple(float(n) for n in voxel_size_um)
        self._origin_um = tuple(float(n) for n in origin_um)
        self._channels = list(channels)
        self._frames = int(frames)
        self._dtype = dtype
        self._ome_zarr_version = ome_zarr_version

        self.tiles_folder = self.folder / f"{name}{_TILES_FOLDER_ENDING}"
        self.tiles_folder.mkdir(parents=True, exist_ok=True)

        # Which whole-tile image belongs to each place on the stage, and the arrays
        # inside it. A position visited again — in another colour, or at a later
        # moment — writes into the image it wrote into the first time, rather than
        # starting a second one, so that everything recorded of one field of view
        # stays together.
        #
        # The lock is here because a run may hand tiles to this writer from several
        # threads at once, and two threads discovering the same new position in the
        # same breath would otherwise each declare an image for it and one would
        # empty the other's.
        self._positions: dict[tuple[int, int, int], _WholeTileImage] = {}
        self._positions_lock = threading.Lock()

    # -- declaring the run ------------------------------------------------

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
        tile_grid: tuple[int, int, int] | None = None,
        origin_um: tuple[float, float, float] = (0.0, 0.0, 0.0),
        frames: int = 1,
        dtype: str = "uint16",
        chunk: int = 256,
        levels: int | None = None,
        discard_existing_run: bool = False,
        ome_zarr_version: str = "0.4",
    ) -> TilesAndCanvas:
        """Declare a run, before anything has been imaged.

        The arguments are the ones :meth:`zmart_storage.canvas.TileCanvases.create`
        takes, and they mean the same things, with one difference that is the whole
        point of this class: ``tile_step`` is allowed to be **smaller** than
        ``tile_shape``. That difference is the overlap, and it is kept.

        Nothing has to be said about whether to trim, or by how much. It is worked
        out from ``tile_shape`` and ``tile_step``, axis by axis — see the module's
        opening notes — so a run whose tiles butt up is trimmed by nothing at all
        and behaves exactly as :class:`TileCanvases` does.

        Args:
            folder: the run's own folder. Created if it is not there yet.
            name: what to call this acquisition type — ``"overview"``,
                ``"prescan"``, ``"targetscan"``. The canvas is named after it and
                so is the folder of whole tiles beside it.
            canvas_shape: how much room to allow the canvas, as ``(z, y, x)`` in
                voxels, measured the way the stage measures. The stage's travel
                range across the specimen is a good choice when the experiment does
                not say, because no tile can land outside it and declaring room that
                is never written costs practically nothing on disk. Give ``z`` the
                depth the run means to image rather than the stage's whole travel in
                depth — the reason is explained at :meth:`TileCanvases.create`, and
                it has caught people out.

                A little more room than this is declared behind the scenes, so that
                the untrimmed outer edges of the tiles at the edge of the pattern
                have somewhere to sit. Nothing has to be allowed for it here.
            tile_shape: the size of one acquired tile, as ``(z, y, x)`` in voxels.
            tile_step: how far the stage moves between neighbouring tiles, the same
                way. Anything smaller than ``tile_shape`` on an axis is an overlap
                there, and the overlap must be an even number of voxels.
            voxel_size_um: how large one voxel is, as ``(z, y, x)`` in microns.
            channels: the colours of light being recorded, in the order they appear
                along the channel axis.
            tile_grid: how many tiles the scan pattern takes in each direction, as
                ``(z, y, x)``. A raster knows this before it begins, and giving it
                is what lets the writer recognise the tiles at the far edge of the
                pattern and leave their outer edges whole.

                Left out, the far edge cannot be recognised, and those outer edges
                are trimmed like any other — which loses a strip half an overlap
                wide from the far side of the picture. The tiles themselves still
                hold it, so nothing is gone from the archive, but the canvas is that
                much smaller than the ground the run covered. A run that overlaps
                and does not say is warned about it here.

                A run of scattered targets has no pattern and needs none: a tile
                written without a ``tile_index`` has no neighbours by definition and
                is never trimmed at all.
            origin_um: where the low corner of the stage travel sits, in microns.
                Tile positions given to :meth:`write` are measured from the same
                zero. The canvas records its own corner, which sits a little before
                this one, so the picture is drawn in its true place without anybody
                having to think about the margin.
            frames: how many moments to allow room for. A timelapse should declare
                comfortably more than it could record; a moment nothing was written
                to occupies no space at all.
            dtype: the kind of number one voxel is. Use the camera's own.
            chunk: how large a piece of the canvas is, across ``y`` and ``x``. This
                is the number the trimming has to line up with — see the rules at
                the top of this module — so it is worth choosing together with the
                overlap rather than separately.
            levels: how many progressively smaller copies of the canvas to keep.
                Normally left out, so that the writer works it out from how much
                room was declared.
            discard_existing_run: whether to throw away a run already imaged into
                this folder. Normally left alone, in which case a folder holding
                acquired pictures is refused rather than emptied.
            ome_zarr_version: which generation of OME-Zarr to write, ``"0.4"`` or
                ``"0.5"``. Both the canvas and the whole tiles are written in it.

        Returns:
            The writer, ready to be given tiles.

        Raises:
            ValueError: if the tiles overlap by an odd number of voxels, if a
                trimmed tile would not be a whole number of pieces of the canvas, or
                for any of the reasons :meth:`TileCanvases.create` refuses a run — a
                folder that already holds an imaged run, another program already
                writing this acquisition type, or a name that is not a plain file
                name.
        """
        folder = Path(folder)
        trimming = Trimming.of(tile_shape, tile_step)
        # How large a piece of the canvas really is, which for a canvas smaller than
        # the piece size asked for is the canvas itself. Worked out before anything
        # else because both the rule below and the margin depend on it.
        piece = the_piece_the_canvas_will_use(canvas_shape, chunk)
        _refuse_a_trim_that_does_not_land_on_whole_pieces(
            trimming, tile_shape, piece, tile_grid
        )

        if trimming.anything_to_trim and tile_grid is None:
            warnings.warn(
                "this acquisition overlaps, and nothing was said about how many "
                "tiles its scan pattern takes, so the writer cannot tell which "
                "tiles sit at the far edge of it. Their outer edges will be trimmed "
                "like any other, which leaves the canvas short of the ground the run "
                f"covered by {trimming.half[1]} voxels in y and {trimming.half[2]} in "
                "x along the far edges. Nothing is lost — every tile is still kept "
                "whole in the folder beside the canvas — but the picture is smaller "
                "than the specimen.\n\n"
                "Pass tile_grid=(z, y, x) with the number of tiles the pattern takes "
                "in each direction, which a raster knows before it starts, and those "
                "edges are kept.",
                stacklevel=2,
            )

        # How far before the stage's low corner the canvas begins, so that the
        # untrimmed outer edges of the tiles at the low edge of the pattern have
        # somewhere to sit. Nought for a run whose tiles butt up.
        margin = _the_blank_margin(trimming, piece)
        shift = tuple(margin[axis] - trimming.half[axis] for axis in range(3))

        # The canvas is declared with room for the margin at the low end and for the
        # untrimmed outer edge at the high end. Room that is never written to costs
        # practically nothing on disk, so this is added quietly rather than being
        # made the caller's problem.
        declared = tuple(
            int(canvas_shape[axis]) + margin[axis] + trimming.half[axis]
            for axis in range(3)
        )

        # Where the canvas's first voxel sits on the stage: a margin before the
        # corner the run was declared with. Saying so here is what makes the canvas
        # line up with the whole tiles beside it, and with anything else drawn in
        # stage coordinates.
        canvas_origin_um = tuple(
            origin_um[axis] - shift[axis] * voxel_size_um[axis] for axis in range(3)
        )

        # The canvas is an ordinary TileCanvases, given trimmed tiles that butt up.
        # Its refusal of overlapping tiles is left exactly as it is: trimming is
        # what makes the run acceptable to it, rather than any weakening of the
        # rule. It is told the trimmed size, because that is the size at which the
        # tiles it receives meet one another.
        canvas = TileCanvases.create(
            folder,
            name=name,
            canvas_shape=declared,  # type: ignore[arg-type]
            tile_shape=trimming.kept,
            tile_step=trimming.kept,
            voxel_size_um=voxel_size_um,
            channels=channels,
            origin_um=canvas_origin_um,  # type: ignore[arg-type]
            frames=frames,
            dtype=dtype,
            chunk=piece,
            levels=levels,
            discard_existing_run=discard_existing_run,
            ome_zarr_version=ome_zarr_version,
        )

        return cls(
            folder,
            canvas,
            name=name,
            trimming=trimming,
            shift=shift,  # type: ignore[arg-type]
            tile_shape=tuple(int(n) for n in tile_shape),  # type: ignore[arg-type]
            tile_grid=None if tile_grid is None else tuple(int(n) for n in tile_grid),  # type: ignore[arg-type]
            voxel_size_um=voxel_size_um,
            origin_um=origin_um,
            channels=list(channels),
            frames=frames,
            dtype=dtype,
            ome_zarr_version=ome_zarr_version,
        )

    # -- what a reader is handed ------------------------------------------

    @property
    def canvas(self) -> TileCanvases:
        """The canvas itself, in case a caller wants to ask it something."""
        return self._canvas

    @property
    def paths(self) -> list[Path]:
        """What to point the viewer at: the canvas, and nothing else.

        A list of one, because that is the shape the viewer is handed a run in. The
        whole tiles are deliberately left out — they are the archive, and opening
        ten thousand of them is the very thing the canvas exists to avoid.
        """
        return self._canvas.paths

    @property
    def canvas_path(self) -> Path:
        """Where the canvas image lives."""
        return self._canvas.paths[0]

    @property
    def tile_paths(self) -> list[Path]:
        """Every whole-tile image written so far, in the order the positions arrived.

        This is the archive: one image per place on the stage, with the overlap
        intact. It is what a stitcher is given, and what somebody opens in napari or
        Fiji to look at a single field of view as the camera saw it.
        """
        with self._positions_lock:
            return [held.folder for held in self._positions.values()]

    def coverage(self) -> Coverage:
        """Which parts of the canvas actually hold picture.

        This reads the record :mod:`zmart_storage.coverage` keeps as the run goes,
        rather than keeping a second one here. There is deliberately only ever one
        such record: two would have to be kept in step with each other, and the day
        they disagreed there would be no way to tell which was right.

        Returns:
            A :class:`zmart_storage.coverage.Coverage`. Its regions are measured in
            the canvas's own voxels, which begin a margin before the stage's low
            corner — see :attr:`shift`.
        """
        return imaged_regions(self.canvas_path)

    # -- writing a tile ---------------------------------------------------

    def write(
        self,
        image: np.ndarray,
        *,
        origin: tuple[int, int, int],
        channel: int = 0,
        frame: int = 0,
        tile_index: tuple[int, int, int] | None = None,
    ) -> Path:
        """Put one acquired tile away whole, and its trimmed part into the canvas.

        Args:
            image: the tile's voxels as the camera recorded them, shaped
                ``(z, y, x)``. It must be the size the run declared, because the
                trimming is worked out from that size and a tile of another size
                would be trimmed by the wrong amount.
            origin: where the tile's low corner sits, as ``(z, y, x)`` in voxels,
                measured from the same zero as ``origin_um``.
            channel: which colour of light this tile was recorded in.
            frame: which moment it belongs to.
            tile_index: the tile's place in the scan pattern, as ``(z, y, x)``
                counts. A raster scan knows this, and here it does more than it does
                for :class:`TileCanvases`: it is what says which sides of this tile
                another tile is going to butt up against, and so which sides are
                trimmed. A target the workflow chose for itself has no place in a
                pattern, and leaving this out is right for one — such a tile has no
                neighbours and is kept whole.

        Returns:
            The whole-tile image this tile was put away in. Useful for reporting,
            and for handing a single field of view to something else.

        Raises:
            ValueError: if the tile is not the size the run declared, or for any of
                the reasons :meth:`TileCanvases.write` refuses a tile — past the
                edge of the declared room, past the last declared moment, or landing
                on ground already imaged in the same moment and colour.
        """
        if tuple(image.shape) != self.tile_shape:
            raise ValueError(
                f"this tile is {tuple(image.shape)} voxels and the run was declared "
                f"with tiles of {self.tile_shape}. The two have to agree, because "
                "how much is trimmed from each side is worked out from the declared "
                "size — a tile of another size would be trimmed by the wrong amount "
                "and would land in the wrong place on the canvas, with nothing about "
                "the picture to say so.\n\n"
                "If the camera really is producing a different size now, declare a "
                "new acquisition type for it rather than mixing two sizes into one "
                "canvas."
            )

        where = tuple(int(n) for n in origin)
        # The archive first. If anything is going to fail, better that it fail
        # before the canvas has been told the tile arrived — the archive is the
        # copy that cannot be reconstructed from anything else.
        whole = self._image_for(where)
        whole.put(image, frame=frame, channel=channel)

        neighbours = neighbours_of(tile_index, self.tile_grid)
        self._canvas.write(
            self.trimming.cut(image, neighbours),
            origin=self.trimming.lands_at(where, neighbours, self.shift),
            channel=channel,
            frame=frame,
            tile_index=tile_index,
        )
        return whole.folder

    def _image_for(self, origin: tuple[int, int, int]) -> _WholeTileImage:
        """The whole-tile image belonging to this place on the stage, made if new.

        Positions are recognised by where they are rather than by any name, so a
        field of view revisited in another colour or at a later moment writes into
        the image it wrote into the first time. Everything recorded of one place
        therefore stays in one image, which is what somebody opening a single tile
        expects to find.
        """
        with self._positions_lock:
            held = self._positions.get(origin)
            if held is not None:
                return held
            number = len(self._positions)
            held = _WholeTileImage.declare(
                self.tiles_folder / f"{self.name}_pos{number:05d}.ome.zarr",
                origin=origin,
                tile_shape=self.tile_shape,
                voxel_size_um=self._voxel_size_um,
                origin_um=self._origin_um,
                channels=self._channels,
                frames=self._frames,
                dtype=self._dtype,
                ome_zarr_version=self._ome_zarr_version,
            )
            self._positions[origin] = held
            return held

    # -- finishing --------------------------------------------------------

    def close(self) -> None:
        """Let the canvas go, and bring the record of the run up to date.

        Worth calling when a run has finished, and harmless otherwise. Neither the
        archive nor the canvas needs it in order to be complete — both are readable
        throughout — so a run cut short still leaves everything it acquired.
        """
        self._canvas.close()

    def __del__(self) -> None:
        # A writer that is simply forgotten about should still give the canvas up,
        # so the next program to want it is not turned away by a claim nobody holds.
        try:
            self.close()
        except Exception:  # pragma: no cover - only reachable at shutdown
            pass


# -- one place on the stage, kept whole ----------------------------------------


class _WholeTileImage:
    """One position's tile, stored whole, with room for every colour and moment.

    A small ordinary OME-Zarr with a single level. There are no progressively
    smaller copies, and that is on purpose: this image is one camera tile across,
    so there is nothing to zoom out from, and the copies would only be work paid on
    every tile for a view nobody opens.
    """

    def __init__(self, folder: Path, array) -> None:
        self.folder = folder
        self._array = array

    @classmethod
    def declare(
        cls,
        folder: Path,
        *,
        origin: tuple[int, int, int],
        tile_shape: tuple[int, int, int],
        voxel_size_um: tuple[float, float, float],
        origin_um: tuple[float, float, float],
        channels: list[Channel],
        frames: int,
        dtype: str,
        ome_zarr_version: str,
    ) -> _WholeTileImage:
        """Write the empty image for one position, at its true place on the stage.

        The corner recorded here is where this tile really sits, so opening the
        archive in napari or Fiji lays the tiles out as the specimen rather than
        piling them on the origin.
        """
        depth_max = int(np.iinfo(np.dtype(dtype)).max)
        where_um = tuple(
            origin_um[axis] + origin[axis] * voxel_size_um[axis] for axis in range(3)
        )
        # Declared through the canvas module's own function rather than a second
        # copy of the same code here, so that a whole tile and a canvas can never
        # come to disagree about how an OME-Zarr image is written.
        arrays = _declare_one(
            folder,
            canvas_shape=tile_shape,
            frames=frames,
            channels=len(channels),
            dtype=dtype,
            # One piece per plane, per colour, per moment. A camera tile is small
            # enough that there is nothing to gain by cutting it up further, and a
            # single piece is the cheapest thing to write and to read back.
            chunk=max(int(tile_shape[1]), int(tile_shape[2])),
            levels=1,
            voxel_size_um=voxel_size_um,
            origin_um=where_um,  # type: ignore[arg-type]
            # A channel that has not chosen a window cannot be described in the
            # OME ``omero`` block, because strict readers refuse a block whose
            # window has no ``start``/``end``. So the whole advisory block is
            # left out, exactly as :class:`TileCanvases` leaves it out, and the
            # viewer measures the pixels instead of being told the camera range.
            channel_blocks=(
                []
                if any(colour.window is None for colour in channels)
                else [colour.described(depth_max) for colour in channels]
            ),
            ome_zarr_version=ome_zarr_version,
        )
        return cls(folder, arrays[0])

    def put(self, image: np.ndarray, *, frame: int, channel: int) -> None:
        """Store one whole tile, in its own moment and colour.

        Nothing is trimmed and nothing is written twice: a moment and a colour
        together name a slot that only this tile can occupy, so every voxel the
        camera recorded is on disk afterwards exactly as it arrived.
        """
        self._array[frame, channel] = image

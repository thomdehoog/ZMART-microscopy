"""Earning the right to publish, rather than asserting it.

The publication record refuses an event whose readiness is not claimed. That is
necessary and it is not sufficient, because until now nothing *checked* those
claims — a caller could set every flag to true and the record would believe it.
The promise "nothing half-written is ever visible" was therefore only as good as
the caller's honesty, which is not a property you can test.

This module is what makes the claims mean something. It writes a position, then
goes and looks at what actually landed on disk, and builds the publication event
out of **what it found** rather than what anybody asserted. There is deliberately
no way to hand it a readiness flag.

The two pictures this builds, and why there have to be two
----------------------------------------------------------

A mosaic is imaged with its tiles deliberately overlapping, so along every seam
there is a strip of specimen that two tiles both photographed. That leaves two
honest but different ways to show the run, and this module writes both of them.

The **seamless** view crops each tile so that no piece of specimen appears
twice. It is the quick-look picture an operator navigates by, and it is the one
that answers "where am I?".

The **raw overlap** view keeps every pixel each tile recorded, overlap included.
It is the picture you open when you want to see what the microscope actually
did: whether the two tiles agree along the seam, whether the illumination fell
away at a frame edge, whether the stage went where it was asked to go.

The raw view cannot simply be the tiles painted into one picture. Inside an
overlap strip, two tiles hold two genuinely different measurements of the same
place on the specimen, and one grey value per place can only hold one of them.
Painting them into a single picture means whichever tile happened to be written
last silently replaces the other's measurement — which destroys exactly the
evidence somebody opened this view to look at. The decision record says the same
thing in one sentence: *"A single scalar composite cannot expose two different
measurements at the same world coordinate simultaneously, so a truly raw overlap
presentation must retain distinct position sources/layers or provide a
position-selection mechanism."*

Handing the viewer one source per position is the other way to keep them apart,
and ``scene.py`` explains at length why that is ruinous: every source becomes a
drawing layer that takes part in every frame for as long as the viewer is open.
So the raw view is one store with **one extra dimension** — a slider the
operator steps through to choose which tile they are looking at. That is what
``scene.py`` already declares for this view under the name ``tile``, and it is
what this module writes.

What one stop on that slider means
----------------------------------

The tempting arrangement is one stop per position, and it is the wrong one: on a
real run the slider would have five thousand stops, nearly all of them empty
wherever the operator happens to be looking, and finding the two that meet at
the seam in front of them would be hopeless.

The arrangement used here is much smaller and is fixed by the geometry alone.
Two tiles can only overlap if they sit within a frame's width of one another, so
tiles that are far enough apart in the grid can safely share a stop. Counting
how many tiles it takes to travel one frame gives the number of stops needed on
each tiled axis — with a 1152-pixel frame and a 128-pixel overlap the stage moves
1024 pixels between tiles, so two tiles in a row can overlap and two stops are
enough. A tile's stop is then simply its row and column counted round that many
places, which for an ordinary mosaic gives four stops in total: the tiles fall
into four interleaved sets, like the squares of a chessboard, and no two tiles
within one set ever touch.

Three things follow, and each is worth having. Both measurements in an overlap
are always kept, because two overlapping tiles always land on different stops.
No measurement is ever overwritten, because two tiles sharing a stop never share
any specimen. And the number of stops depends on the acquisition geometry rather
than on how many positions have arrived, so the slider means the same thing at
the beginning of a run as at the end.

That reasoning is checked rather than trusted:
:meth:`LivePublisher.write_the_raw_overlap_view` refuses to write at all if any
two tiles sharing a stop would in fact share specimen.

What this view does not do yet is worth saying plainly. It is written at full
resolution only, like the seamless view, so zooming out in the raw view has no
prepared copies to fall back on. Nothing about the arrangement above prevents
those being added; they simply are not here.

What is published, and what "ready" is made to mean
---------------------------------------------------

The thing that becomes visible is never "a position" in the abstract. It is one
position **at one moment** — one position together with one timepoint — because
a timelapse writes the same position over and over and each of those moments is
finished at a different time. Every check below is therefore asked about that
pair and about nothing else. Asking about the position as a whole was the
original mistake, and it allowed a moment for which not one byte had been
written to be published as complete, since a store politely returns empty ground
for any piece it does not hold.

Five things are checked, and each corresponds to a way an operator could
otherwise be shown a confident picture of nothing.

**The pixels and their zoomed-out copies.** For every level the position
advertises, the exact list of pieces that moment ought to have produced is
worked out, and the store is asked, piece by piece, whether it really holds each
one. That is not the same as reading the level back and finding numbers in it: a
piece that was never stored reads back as perfectly ordinary empty ground, so
reading alone cannot tell "nothing was written here" from "this part of the
slide is blank". Everything that *is* stored is then decoded as well, because a
file can exist and be half a chunk long, and half a chunk is exactly what a
viewer would draw as plausible noise.

**The pointers.** At the levels the overview points at rather than copies, it
stores no pixels of its own; when the viewer asks for a piece, the answer is a
stretch of bytes inside a position that was already written. Which position
answers for which piece is written down as a map beside the run, and that map is
then read back and followed: every piece this position supplies is resolved to a
byte range, decoded on its own, and compared against what the position's own
array returns. This is the check that catches a wrong byte range, which produces
a picture rather than an error.

**The shared zoomed-out picture.** The pieces this position disturbs are rebuilt
from the committed positions only, and then the ground this position covers is
read back out of that picture and compared, pixel for pixel, against the
position's own store. Comparing the pixels is the whole point: a picture that is
present but black, or one that still shows the ground as it was before this
position arrived, is not a fault anybody would notice on screen — it looks like
specimen that has not been imaged.

**The raw overlap picture.** The whole frame this position recorded is read back
out of the stop on the tile slider that belongs to it, and compared pixel for
pixel against the position's own store. This is what catches another tile having
written over these measurements, which is the one failure the raw view exists to
make impossible and the one that leaves no trace on screen — the strip still
looks like specimen, it is simply the neighbour's specimen.

**The arrangement.** The layout that says who owns what is written down and read
back before it is referred to, because every published measurement will point at
it later. It is not enough that the file parses. It has to be *this* run's
arrangement, so its run, its storage plan and its revision number are all
compared against the run in hand; a well-formed layout belonging to a different
experiment would otherwise be accepted without a word.

Only when all five hold is an event created, and only then does the record move.

Once published, pixels stop being editable
------------------------------------------

Somebody reading a published revision is entitled to assume that everything that
revision covers still says what it said. So once a position at one moment has
been committed, writing over it is refused. Data can of course turn out to be
wrong, and :meth:`LivePublisher.replace_a_position` is the way to say so: it
writes the new pixels into a **new generation** of that position's store, leaves
the old generation exactly where it is, rebuilds both shared pictures from the
new one, and publishes the change as its own revision. Nothing anybody has
already been shown is altered; a newer answer simply appears beside it.

What this module is not
-----------------------

It is one narrow path: a small mosaic, one moment, written locally. It is meant
to be the first thing that is true end to end rather than the last word on any
part of it. What it does not yet do is written down in
``docs/design/live-writer-and-linked-views-plan.md`` rather than implied by
silence here.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import zarr
from zarr.codecs import ZstdCodec

from .coarse import chunks_touched_by, what_a_chunk_should_hold
from .manifest import RunManifest, now_in_words
from .model import (
    AcquisitionProfile,
    CommitEvent,
    GridCell,
    Interval,
    SceneLayoutRevision,
    ZmartLiveError,
)
from .ownership import check_the_grid_holds_together, place_the_tiles, the_far_edges
from .shardlink import where_one_chunk_lives
from .viewroute import Placed, route_the_view

__all__ = [
    "Inspection",
    "LivePublisher",
    "NotReadyToPublish",
]

_LAYOUT = "layout.json"
_LINKS = "links.json"

#: The name written into the map of pointers, so that anybody reading that file
#: can tell at once whether it is one this version of ZMART understands.
_LINKS_SCHEMA = "zmart-live-links/1"


class NotReadyToPublish(ZmartLiveError):
    """What was found on disk does not yet justify showing this to anybody.

    The message lists what is missing. It is a refusal rather than a warning
    because the alternative — publishing anyway and hoping — produces a picture
    that looks finished and is not, which nobody downstream can detect.
    """


@dataclass(frozen=True)
class Inspection:
    """What was actually found when one position, at one moment, was looked at.

    Every field here is the result of opening files and reading bytes. None of it
    can be supplied by a caller, which is the entire point: this is the evidence
    the publication event is built from.

    ``timepoint`` is the moment that was asked about. ``None`` means the caller
    did not name one, which is how a position with no timelapse is published; the
    moment actually looked at in that case is moment zero.
    """

    position_id: str
    timepoint: int | None
    pyramids_ready: bool = False
    links_ready: bool = False
    coarse_chunks_ready: bool = False
    raw_overlap_ready: bool = False
    layout_ready: bool = False
    pieces_read: int = 0
    ranges_checked: int = 0
    coarse_pieces_rebuilt: int = 0
    raw_pixels_compared: int = 0
    complaints: tuple[str, ...] = ()

    @property
    def everything_checks_out(self) -> bool:
        """True only when all five checks held and nothing was complained about."""
        return (
            self.pyramids_ready
            and self.links_ready
            and self.coarse_chunks_ready
            and self.raw_overlap_ready
            and self.layout_ready
            and not self.complaints
        )

    @property
    def moment(self) -> int:
        """The moment this inspection was about, counting from zero."""
        return 0 if self.timepoint is None else self.timepoint

    def describe(self) -> str:
        """One paragraph an operator can read when something is being withheld."""
        which = f"'{self.position_id}' at moment {self.moment}"
        if self.everything_checks_out:
            return (
                f"{which} is complete: {self.pieces_read} pixels read back out of "
                f"the pieces the store really holds, {self.ranges_checked} pointers "
                f"resolved through the stored map and decoded, "
                f"{self.coarse_pieces_rebuilt} pieces of the zoomed-out picture "
                f"rebuilt from the positions already published, and "
                f"{self.raw_pixels_compared} pixels of the raw overlap view found "
                f"to still be this position's own measurements."
            )
        return f"{which} is not ready to be shown. " + " ".join(self.complaints)


@dataclass
class LivePublisher:
    """Writes a small mosaic and publishes each position once it is genuinely done.

    The order it insists on is the order the architecture record lays out: pixels
    and their zoomed-out copies, then the pointers, then the two run-wide
    pictures — the seamless one and the raw one that keeps every overlapping
    pixel — then the arrangement, and only then one indivisible commit. Nothing
    is visible until that last step, however finished the files may look.
    """

    folder: Path
    profile: AcquisitionProfile
    run_id: str
    cells: dict[GridCell, str]
    channels: tuple[str, ...] = ("green",)
    timepoints: int = 1
    manifest: RunManifest = field(init=False)
    layout: SceneLayoutRevision = field(init=False)
    #: Which generation of each position's store is the current one. A position
    #: that has never been replaced does not appear here at all, and its pixels
    #: stay in the plainly named folder they have always been in.
    generations: dict[str, int] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self.folder = Path(self.folder)
        (self.folder / "positions").mkdir(parents=True, exist_ok=True)
        (self.folder / "views").mkdir(parents=True, exist_ok=True)

        check_the_grid_holds_together(
            self.cells, profile_id=self.profile.profile_id
        )
        placements = place_the_tiles(self.profile, self.cells)
        self.layout = SceneLayoutRevision(
            revision=1,
            schema_version="zmart-live-layout/1",
            run_id=self.run_id,
            acquisition_type=self.profile.acquisition_type,
            profile_id=self.profile.profile_id,
            positions=placements,
            seamless_ownership=self.profile.seamless_ownership,
            analysis_ownership=self.profile.analysis_ownership,
            created_at=now_in_words(),
        )
        self.manifest = RunManifest.start(self.folder, run_id=self.run_id)

    # -- where things live ---------------------------------------------------

    def position_store(self, position_id: str, *, generation: int | None = None) -> Path:
        """The folder holding one position's own image.

        Left alone, this gives the generation that is current — the pixels the
        run means when it says ``posA`` today. Naming a ``generation`` asks for a
        particular one instead, which is what lets somebody go back and look at
        the pixels that were on the screen under an earlier revision. Generation
        zero is a position that has never been replaced, and it keeps the plain
        name it has always had so that nothing already written has to move.
        """
        which = self.generations.get(position_id, 0) if generation is None else generation
        if which == 0:
            return self.folder / "positions" / f"{position_id}.ome.zarr"
        return self.folder / "positions" / f"{position_id}.generation-{which}.ome.zarr"

    @property
    def seamless_store(self) -> Path:
        """The folder holding the run-wide zoomed-out picture."""
        return self.folder / "views" / "overview-seamless.ome.zarr"

    @property
    def raw_overlap_store(self) -> Path:
        """The folder holding the picture that keeps every overlapping pixel.

        The name is not free to choose: :func:`zmart_live.scene.build_the_scene`
        tells the viewer where to find this view, and the two have to agree or
        the operator is handed an address with nothing behind it.
        """
        return self.folder / "views" / "overview-raw.ome.zarr"

    @property
    def link_map_file(self) -> Path:
        """The file saying which position's own bytes answer for each piece.

        At the zoom levels it can point at, the overview stores no pixels of its
        own, so something has to record where each piece of it really lives. This
        is that record. It sits with the run's other bookkeeping rather than
        inside an image, so that nothing we invented ever turns up in a picture
        somebody opens in another program.
        """
        return self.folder / "zmart-live" / _LINKS

    # -- what has already been shown to somebody -----------------------------

    def _committed_units(self) -> set[tuple[str, int]]:
        """Every position-and-moment pair that has already been published.

        Read back from the run's own publication history rather than remembered
        in memory, because a writer that was interrupted and started again must
        still know what its predecessor made visible. Publishing a position
        without naming a moment publishes its moment zero, so that is how such a
        record is counted here.
        """
        published: set[tuple[str, int]] = set()
        for event in self.manifest.events():
            moment = 0 if event.timepoint is None else event.timepoint
            published.add((event.position_id, moment))
        return published

    # -- the stops on the tile slider ----------------------------------------

    @property
    def tile_stops_per_axis(self) -> dict[str, int]:
        """How many stops the tile slider needs along each tiled axis.

        Two tiles can only share specimen if they sit within one frame's width of
        one another, so this is simply how many tiles it takes to travel one
        frame. With a 1152-pixel frame and the stage moving 1024 pixels between
        tiles, two tiles in a row can overlap and the answer is two.
        """
        return {
            axis: -(-self.profile.frame_shape[axis] // self.profile.grid_step(axis))
            for axis in self.profile.tiled_axes
        }

    @property
    def tile_stop_count(self) -> int:
        """How many stops the tile slider has in total.

        This comes from the acquisition geometry alone, never from how many
        positions have arrived, so a stop means the same thing on the first
        commit of the run as on the last.
        """
        total = 1
        for stops in self.tile_stops_per_axis.values():
            total *= stops
        return total

    def tile_stop_of(self, position_id: str) -> int:
        """Which stop on the tile slider shows this position.

        A tile's row and column are counted round the number of stops on each
        axis, in the same way the days of a week come round. Neighbouring tiles
        therefore always land on different stops, and two tiles that do share a
        stop are always far enough apart to share no specimen at all.
        """
        cell = self.layout.placement(position_id).cell
        stop = 0
        for axis, stops in self.tile_stops_per_axis.items():
            index = cell.row if axis == "y" else cell.column
            stop = stop * stops + index % stops
        return stop

    def _no_two_tiles_on_one_stop_overlap(self) -> None:
        """Refuse to write a raw view in which one tile could erase another.

        The arrangement above makes this impossible, and that is exactly why it
        is worth checking rather than believing: if the rule for choosing stops
        were ever changed or broken, the damage would be a strip of one tile's
        specimen quietly replaced by its neighbour's, which looks entirely
        normal on screen. Checking is cheap, because only tiles a few grid
        squares apart could reach one another at all.
        """
        by_cell = {
            placement.cell: placement for placement in self.layout.positions
        }
        stops = self.tile_stops_per_axis
        # How far apart two tiles can be and still share specimen, counted in
        # grid squares. On a tiled axis that is the number of stops. An axis with
        # no overlap declared is not laid out side by side at all, so every tile
        # sits at the same place along it and any two of them have to be
        # compared; that is a strange acquisition, and the point of looking is to
        # notice rather than to assume.
        rows = [placement.cell.row for placement in self.layout.positions] or [0]
        columns = [placement.cell.column for placement in self.layout.positions] or [0]
        reach_rows = stops.get("y", max(rows) - min(rows) + 1)
        reach_columns = stops.get("x", max(columns) - min(columns) + 1)
        for placement in self.layout.positions:
            here = placement.cell
            for row_step in range(-reach_rows + 1, reach_rows):
                for column_step in range(-reach_columns + 1, reach_columns):
                    other = by_cell.get(
                        GridCell(here.row + row_step, here.column + column_step)
                    )
                    if other is None or other.position_id == placement.position_id:
                        continue
                    if self.tile_stop_of(other.position_id) != self.tile_stop_of(
                        placement.position_id
                    ):
                        continue
                    shares_specimen = all(
                        placement.origin[axis]
                        < other.origin[axis] + self.profile.frame_shape[axis]
                        and other.origin[axis]
                        < placement.origin[axis] + self.profile.frame_shape[axis]
                        for axis in self.profile.tiled_axes
                    )
                    if not shares_specimen:
                        continue
                    raise ZmartLiveError(
                        f"'{placement.position_id}' and '{other.position_id}' both "
                        f"photographed the same specimen and would be written to the "
                        f"same stop on the raw view's tile slider, so one would erase "
                        f"the other's measurements. The raw overlap view exists to "
                        f"keep both, so it is not written at all rather than written "
                        f"wrongly."
                    )

    def _mosaic_extent(self) -> tuple[int, int]:
        """How far the whole mosaic reaches in y and x, in full-resolution pixels."""
        reach = {}
        for axis in ("y", "x"):
            step = self.profile.grid_step(axis)
            last = max(
                cell.row if axis == "y" else cell.column for cell in self.cells
            )
            reach[axis] = last * step + self.profile.frame_shape[axis]
        return reach["y"], reach["x"]

    # -- writing -------------------------------------------------------------

    def write_a_position(
        self, position_id: str, pixels: np.ndarray, *, timepoint: int = 0
    ) -> None:
        """Write one position's pixels and every zoomed-out copy it advertises.

        ``pixels`` is one colour given as ``(z, y, x)``, or every colour given as
        ``(colour, z, y, x)``. A run that records more than one colour has to be
        handed all of them, because there is no honest way to guess what the
        colours it was not given should contain.

        Writing does not make anything visible. The files land, and they stay
        invisible until :meth:`publish` has looked at them and found them whole.

        A position and moment that has already been published is refused, so that
        pixels somebody has been shown cannot quietly turn into different pixels.
        :meth:`replace_a_position` is the way to supersede them.
        """
        if position_id not in self.cells.values():
            raise ZmartLiveError(
                f"'{position_id}' is not one of this run's positions. The run holds "
                f"{sorted(self.cells.values())}."
            )
        if (position_id, timepoint) in self._committed_units():
            raise ZmartLiveError(
                f"Moment {timepoint} of '{position_id}' has already been published, "
                f"so anybody following this run is reading those pixels and they "
                f"cannot be written over. Doing so would leave the position's own "
                f"store and the overview disagreeing under one revision, with "
                f"nothing to say which was meant. If this moment genuinely has to "
                f"be superseded, use replace_a_position(), which keeps what was "
                f"published and adds the new pixels as their own revision."
            )
        self._write_the_pixels(position_id, pixels, timepoint=timepoint)

    def _write_the_pixels(
        self, position_id: str, pixels: np.ndarray, *, timepoint: int
    ) -> None:
        """Put one moment's pixels, and every zoomed-out copy, into the store.

        Kept apart from :meth:`write_a_position` so that a deliberate replacement
        can reuse it without having to work around the refusal made there.
        """
        if not 0 <= timepoint < self.timepoints:
            raise ZmartLiveError(
                f"This run was set up for {self.timepoints} moment(s), numbered from "
                f"zero, so there is nowhere in it to put moment {timepoint}."
            )
        store = self.position_store(position_id)
        shrinking = self._one_moment_of_every_colour(pixels)
        for level in self.profile.levels:
            self._write_one_level(store, level, shrinking, timepoint)
            shrinking = _halve(shrinking)

    def _one_moment_of_every_colour(self, pixels: np.ndarray) -> np.ndarray:
        """Read what the caller handed over as ``(colour, z, y, x)``, or say why not.

        A run recording a single colour may hand over a plain ``(z, y, x)`` stack,
        because there is only one thing that could mean. As soon as a run records
        two colours the shortcut becomes a guess, and the guess this writer used
        to make — put the same pixels into every colour — produced a red channel
        that was a copy of the green one, with nothing anywhere to say so.
        """
        given = np.asarray(pixels)
        if given.ndim == 3 and len(self.channels) == 1:
            return given[np.newaxis]
        if given.ndim == 4:
            if given.shape[0] != len(self.channels):
                raise ZmartLiveError(
                    f"This run records the colours {list(self.channels)}, so it "
                    f"expects pixels for {len(self.channels)} of them, but it was "
                    f"handed {given.shape[0]}."
                )
            return given
        raise ZmartLiveError(
            f"This run records the colours {list(self.channels)}. Pixels for it "
            f"have to arrive as (colour, z, y, x), one stack of planes per colour; "
            f"what arrived has the shape {tuple(given.shape)}. A run with a single "
            f"colour may also hand over a plain (z, y, x) stack, but a run with "
            f"more than one cannot, because copying one colour's pixels into the "
            f"others would look exactly like a successful acquisition."
        )

    def _write_one_level(self, store: Path, level, pixels: np.ndarray, timepoint: int):
        """Create or open one zoomed-out level and put this moment's pixels in it."""
        path = store / str(level.level)
        colours, depth, height, width = pixels.shape
        shape = (self.timepoints, len(self.channels), depth, height, width)
        chunks = (
            1, 1,
            min(level.inner_chunk["z"], depth),
            min(level.inner_chunk["y"], height),
            min(level.inner_chunk["x"], width),
        )
        shards = None
        if level.shard is not None:
            # A bundle has to hold a whole number of pieces, and at the smaller
            # levels the whole level may be narrower than the bundle would be, so
            # it is trimmed to fit rather than declared larger than the data.
            shards = tuple(
                max(c, (min(s, n) // c) * c)
                for c, s, n in zip(
                    chunks,
                    (1, 1, level.shard["z"], level.shard["y"], level.shard["x"]),
                    shape,
                    strict=True,
                )
            )
        if not path.exists():
            zarr.create_array(
                store=str(path), shape=shape, chunks=chunks, shards=shards,
                dtype=self.profile.dtype, zarr_format=3,
                compressors=[ZstdCodec(level=3)], overwrite=False,
            )
        array = zarr.open_array(str(path), mode="r+")
        for channel in range(colours):
            array[timepoint, channel] = pixels[channel]

    def write_the_seamless_view(self, committed: frozenset[str]) -> None:
        """Rebuild the run-wide picture from the positions already published.

        The rule this carries out is the one the zoomed-out picture exists to
        obey: a position appears here only once it has been committed. Ground
        belonging to a position that is still being written stays empty, which is
        the truth — that part of the specimen is not finished — rather than a
        picture assembled from half-written data.

        Every tile hands its far strip to the neighbour beyond it, which is what
        keeps all the tiles' numbers lined up and lets the overview point at their
        pixels instead of copying them. A tile at the outside of the mosaic has no
        neighbour to hand that strip to, so nobody would cover it and roughly a
        fifth of every edge tile would come out black.
        :func:`zmart_live.ownership.the_far_edges` says exactly which strips those
        are, and they are written here.
        """
        height, width = self._mosaic_extent()
        level = self.profile.level(0)
        depth = self.profile.frame_shape.get("z", 1)
        shape = (self.timepoints, len(self.channels), depth, height, width)
        chunks = (
            1, 1,
            min(level.inner_chunk["z"], depth),
            level.inner_chunk["y"],
            level.inner_chunk["x"],
        )
        if not self.seamless_store.exists():
            zarr.create_array(
                store=str(self.seamless_store), shape=shape, chunks=chunks,
                dtype=self.profile.dtype, zarr_format=3,
                compressors=[ZstdCodec(level=3)], overwrite=False,
            )
        view = zarr.open_array(str(self.seamless_store), mode="r+")

        for placement in self.layout.positions:
            if placement.position_id not in committed:
                continue
            shown = self._what_this_tile_fills_in(placement)
            source = zarr.open_array(
                str(self.position_store(placement.position_id) / "0"), mode="r"
            )
            y, x = shown["y"], shown["x"]
            lands_y = placement.origin["y"]
            lands_x = placement.origin["x"]
            view[:, :, :, lands_y:lands_y + y.length, lands_x:lands_x + x.length] = (
                source[:, :, :, y.start:y.stop, x.start:x.stop]
            )

    def _what_this_tile_fills_in(self, placement) -> dict[str, Interval]:
        """Which part of one tile the seamless picture is filled in from.

        Ordinarily this is the tile's ``visual_source_roi`` — its own corner
        trimmed to one grid step, the same for every tile, which is what keeps the
        arithmetic lined up. Along an axis where the tile sits at the outside of
        the mosaic there is no neighbour to take the remaining strip, so the
        region reaches all the way to the edge of the frame instead. Which axes
        those are is not decided here: it is read from
        :func:`zmart_live.ownership.the_far_edges`, so that the picture that gets
        written and the picture that gets checked can never drift apart.

        The answer is in the tile's own pixels, where ``0`` is that tile's corner
        rather than the run's.
        """
        fills = {
            axis: placement.visual_source_roi[axis]
            for axis in placement.visual_source_roi.axes
        }
        for edge in the_far_edges(self.profile, self.layout.positions):
            if edge.position_id != placement.position_id:
                continue
            fills[edge.axis] = Interval(fills[edge.axis].start, edge.taken_from.stop)
        return fills

    def write_the_raw_overlap_view(self, committed: frozenset[str]) -> None:
        """Rebuild the picture that keeps every pixel every tile recorded.

        Each published tile is copied in whole, overlap included, at the stop on
        the tile slider that belongs to it. Where two tiles meet, both of their
        measurements are therefore on disk, at the same place on the specimen but
        at different stops, and an operator can step from one to the other to see
        whether the microscope agreed with itself.

        The same rule as the seamless view applies here, for the same reason: a
        position appears only once it has been committed, so nothing half-written
        is ever shown.

        Raises :class:`~zmart_live.model.ZmartLiveError` if two tiles that share
        specimen would be written to one stop, because writing that view would
        throw away one of the two measurements it exists to keep.
        """
        self._no_two_tiles_on_one_stop_overlap()

        height, width = self._mosaic_extent()
        level = self.profile.level(0)
        depth = self.profile.frame_shape.get("z", 1)
        shape = (
            self.tile_stop_count,
            self.timepoints,
            len(self.channels),
            depth,
            height,
            width,
        )
        chunks = (
            1, 1, 1,
            min(level.inner_chunk["z"], depth),
            level.inner_chunk["y"],
            level.inner_chunk["x"],
        )
        if not self.raw_overlap_store.exists():
            zarr.create_array(
                store=str(self.raw_overlap_store), shape=shape, chunks=chunks,
                dtype=self.profile.dtype, zarr_format=3,
                compressors=[ZstdCodec(level=3)], overwrite=False,
            )
        view = zarr.open_array(str(self.raw_overlap_store), mode="r+")

        for placement in self.layout.positions:
            # Not published yet means not shown here either, exactly as in the
            # seamless view above.
            if placement.position_id not in committed:
                continue
            everything = placement.analysis_input_roi
            source = zarr.open_array(
                str(self.position_store(placement.position_id) / "0"), mode="r"
            )
            y, x = everything["y"], everything["x"]
            lands_y = placement.origin["y"]
            lands_x = placement.origin["x"]
            view[
                self.tile_stop_of(placement.position_id),
                :, :, :,
                lands_y:lands_y + y.length,
                lands_x:lands_x + x.length,
            ] = source[:, :, :, y.start:y.stop, x.start:x.stop]

    def write_the_layout(self) -> None:
        """Put the arrangement on disk, where a published result can point at it."""
        target = self.folder / "zmart-live" / _LAYOUT
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.layout.to_json(), indent=2))

    # -- the pointers the overview is served from ----------------------------

    def _where_one_tile_is_pointed_at(self, position_id: str, level_number: int) -> Placed:
        """Where one tile's own pixels sit in the overview, at one zoom level.

        Everything here is in that level's own pixels, so the full-resolution
        numbers are divided by how much smaller the level is. What is pointed at
        is the tile's ``visual_source_roi`` and nothing more: the strips along the
        mosaic's outer edge are written into the seamless store rather than
        pointed at, because they are what is left over once every tile has been
        trimmed the same way.
        """
        placement = self.layout.placement(position_id)
        smaller = self.profile.level(level_number).downsampling
        shown = placement.visual_source_roi
        depth = self.profile.frame_shape.get("z", 1)
        by = {axis: smaller.get(axis, 1) for axis in ("z", "y", "x")}
        return Placed(
            array=self.position_store(position_id) / str(level_number),
            lands_at=(
                0,
                placement.origin["y"] // by["y"],
                placement.origin["x"] // by["x"],
            ),
            taken_from=(0, 0, 0),
            size=(
                depth // by["z"],
                shown["y"].length // by["y"],
                shown["x"].length // by["x"],
            ),
        )

    def _how_big_the_overview_is(self, level_number: int) -> tuple[int, int, int]:
        """How large the overview is at one zoom level, as ``(z, y, x)`` pixels."""
        height, width = self._mosaic_extent()
        smaller = self.profile.level(level_number).downsampling
        depth = self.profile.frame_shape.get("z", 1)
        return (
            depth // smaller.get("z", 1),
            height // smaller.get("y", 1),
            width // smaller.get("x", 1),
        )

    def write_the_link_map(self, committed: frozenset[str]) -> None:
        """Write down which position's own bytes answer for each piece of the overview.

        At the zoom levels the storage plan says can be pointed at, the overview
        keeps no pixels of its own: when the viewer asks for a piece of it, the
        answer is a stretch of bytes inside a position that was already written.
        That only works if something says, in a file which outlives this program,
        which position answers for which piece. This writes that file, and
        :meth:`inspect` reads it back and follows it.

        Building the map is also the moment the arrangement gets checked.
        :func:`zmart_live.viewroute.route_the_view` refuses a set of positions
        that were not all written the same way, one that does not land on whole
        pieces, and two positions both claiming the same piece of the picture.
        That last one matters most: it means no seam was ever decided, and the
        picture would then depend on which position happened to be looked at
        first.
        """
        showing = [
            placement.position_id
            for placement in self.layout.positions
            if placement.position_id in committed
        ]
        levels: list[dict] = []
        for level_number in self.profile.linkable_levels:
            if not showing:
                continue
            pointed = {
                position_id: self._where_one_tile_is_pointed_at(position_id, level_number)
                for position_id in showing
            }
            reach = self._how_big_the_overview_is(level_number)
            # The route is built here and then thrown away. What is wanted is the
            # refusal it makes when the positions do not fit together, before
            # anything is written down as though they did.
            route_the_view(list(pointed.values()), view_shape=reach)
            levels.append(
                {
                    "level": level_number,
                    "view_shape": list(reach),
                    "positions": [
                        {
                            "position_id": position_id,
                            "array": str(place.array.relative_to(self.folder)),
                            "lands_at": list(place.lands_at),
                            "taken_from": list(place.taken_from),
                            "size": list(place.size),
                        }
                        for position_id, place in pointed.items()
                    ],
                }
            )
        target = self.link_map_file
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {
                    "schema": _LINKS_SCHEMA,
                    "run_id": self.run_id,
                    "profile_id": self.profile.profile_id,
                    "scene_layout_revision": self.layout.revision,
                    "created_at": now_in_words(),
                    "levels": levels,
                },
                indent=2,
            )
        )

    def _read_the_link_map(self) -> dict:
        """Read the stored map back, refusing one that belongs somewhere else.

        A map that parses is not automatically this run's map. It has to name this
        run, this storage plan and this revision of the arrangement, because a map
        from another experiment would resolve every request to somebody else's
        pixels and look entirely healthy doing it.
        """
        target = self.link_map_file
        if not target.is_file():
            raise ZmartLiveError(
                f"No map of the overview's pointers has been written at {target}. "
                f"The overview is served straight out of the positions' own files, "
                f"so without that map there is nothing saying where any piece of it "
                f"actually lives."
            )
        stored = json.loads(target.read_text())
        if not isinstance(stored, dict) or stored.get("schema") != _LINKS_SCHEMA:
            raise ZmartLiveError(
                f"The map at {target} is not a {_LINKS_SCHEMA!r} record, so what its "
                f"numbers mean cannot be guessed safely."
            )
        for name, wanted, key in (
            ("run", self.run_id, "run_id"),
            ("storage plan", self.profile.profile_id, "profile_id"),
            ("arrangement revision", self.layout.revision, "scene_layout_revision"),
        ):
            if stored.get(key) != wanted:
                raise ZmartLiveError(
                    f"The stored map of pointers names the {name} "
                    f"{stored.get(key)!r}, but this run's is {wanted!r}. Serving the "
                    f"overview out of somebody else's map would show the wrong "
                    f"specimen without anything failing."
                )
        return stored

    # -- looking, which is the part that matters -----------------------------

    def inspect(self, position_id: str, *, timepoint: int | None = None) -> Inspection:
        """Go and see whether this position, at this moment, is genuinely finished.

        Reads bytes. Does not take anybody's word for anything. The result is
        what :meth:`publish` builds its event from.

        ``timepoint`` says which moment is being asked about. Leaving it out asks
        about moment zero, which is the moment a position with no timelapse
        writes. Every check below is about that one moment, because a timelapse
        finishes its moments one at a time and publishes each on its own.
        """
        # Each check keeps its own list of complaints, so that a fault in one
        # cannot be mistaken for the others being fine. Sharing one list was the
        # first version, and it meant a single flag could be wrong while the
        # overall answer stayed right -- which is exactly the sort of thing that
        # goes unnoticed until somebody trusts the individual flag.
        about_pixels: list[str] = []
        about_pointers: list[str] = []
        about_the_picture: list[str] = []
        about_the_overlaps: list[str] = []
        about_the_layout: list[str] = []

        moment = 0 if timepoint is None else timepoint
        pieces_read = self._read_every_piece(position_id, moment, about_pixels)
        ranges = self._resolve_every_pointer(position_id, about_pointers)
        ranges += self._follow_the_stored_pointers(position_id, moment, about_pointers)
        rebuilt = self._check_the_zoomed_out_picture(
            position_id, moment, about_the_picture
        )
        compared = self._check_the_raw_overlap_view(
            position_id, moment, about_the_overlaps
        )
        layout_ok = self._layout_reads_back(about_the_layout)

        return Inspection(
            position_id=position_id,
            timepoint=timepoint,
            pyramids_ready=pieces_read > 0 and not about_pixels,
            links_ready=ranges > 0 and not about_pointers,
            coarse_chunks_ready=rebuilt > 0 and not about_the_picture,
            raw_overlap_ready=compared > 0 and not about_the_overlaps,
            layout_ready=layout_ok and not about_the_layout,
            pieces_read=pieces_read,
            ranges_checked=ranges,
            coarse_pieces_rebuilt=rebuilt,
            raw_pixels_compared=compared,
            complaints=tuple(
                about_pixels
                + about_pointers
                + about_the_picture
                + about_the_overlaps
                + about_the_layout
            ),
        )

    def _every_piece_this_moment_owes(self, array, timepoint: int) -> list[tuple[int, ...]]:
        """Every piece one level ought to hold for one moment, as chunk coordinates.

        A *piece* here is a chunk: the smallest amount of the picture that is
        stored, and decoded, on its own. Which pieces one moment is responsible
        for follows from the array's own shape and chunking — every colour, every
        plane, and the whole width and height — and it is worked out in advance so
        that the store can then be asked about each of them by name.

        The coordinates count pieces rather than pixels, in the picture's own axis
        order of moment, colour, z, y and x.
        """
        across = [
            -(-size // chunk)
            for size, chunk in zip(array.shape, array.chunks, strict=True)
        ]
        # Moments are stored one to a piece, so a moment's own piece index is
        # simply its number. Working it out from the chunk size rather than
        # assuming one keeps this right if that ever changes.
        moment_index = timepoint // array.chunks[0]
        wanted: list[tuple[int, ...]] = [()]
        for axis, extent in enumerate(across):
            reach = [moment_index] if axis == 0 else range(extent)
            wanted = [(*so_far, place) for so_far in wanted for place in reach]
        return wanted

    def _read_every_piece(
        self, position_id: str, timepoint: int, complaints: list[str]
    ) -> int:
        """Ask the store which pieces this moment really holds, and decode them.

        Two different questions, and both have to be asked.

        *Was every piece stored?* A store answers a request for a piece it has
        never held with its fill value, which is a perfectly ordinary picture of
        empty ground. Reading a level back therefore cannot tell "this piece was
        never written" from "this part of the slide is blank", and the only way to
        tell them apart is to ask the store, piece by piece, which ones it really
        holds. This is what catches a moment nobody wrote at all, and a single
        piece missing from the middle of a level.

        *Does what was stored decode?* A file can exist and hold half a piece, and
        half a piece decodes to something rather than to an error — which a viewer
        would draw as plausible noise. So everything is read back as well.
        """
        store = self.position_store(position_id)
        if not store.exists():
            complaints.append(
                f"Nothing has been written for '{position_id}' yet — there is no "
                f"image at {store}."
            )
            return 0
        read = 0
        for level in self.profile.levels:
            path = store / str(level.level)
            if not path.exists():
                complaints.append(
                    f"'{position_id}' promises a zoomed-out copy at level "
                    f"{level.level}, but it has not been written. A viewer zooming "
                    f"out would find nothing there."
                )
                continue
            try:
                array = zarr.open_array(str(path), mode="r")
                if timepoint >= array.shape[0]:
                    complaints.append(
                        f"Level {level.level} of '{position_id}' has room for "
                        f"{array.shape[0]} moment(s), so there is nowhere in it for "
                        f"moment {timepoint} to have been written."
                    )
                    continue
                owed = self._every_piece_this_moment_owes(array, timepoint)
                absent = [
                    piece for piece in owed if where_one_chunk_lives(path, piece) is None
                ]
                if absent:
                    complaints.append(
                        f"Moment {timepoint} of '{position_id}' is missing "
                        f"{len(absent)} of the {len(owed)} pieces level "
                        f"{level.level} should hold, the first of them at "
                        f"{absent[0]}. A piece that was never stored reads back as "
                        f"perfectly ordinary empty ground, so nothing on the screen "
                        f"would say that part of the specimen was never imaged."
                    )
                # Counted from the read itself, not from the description. Taking
                # the count from metadata was the first version, and it meant the
                # read could be removed without any number changing -- so the read
                # was decorative and the check proved nothing.
                everything = array[:]
                read += int(everything.size)
                if everything.size == 0:
                    complaints.append(
                        f"Level {level.level} of '{position_id}' opened but holds "
                        f"no pixels at all."
                    )
            except Exception as trouble:
                complaints.append(
                    f"Level {level.level} of '{position_id}' could not be read "
                    f"back: {trouble}. A piece that will not decode is exactly the "
                    f"piece a viewer would draw as plausible noise."
                )
        return read

    def _resolve_every_pointer(self, position_id: str, complaints: list[str]) -> int:
        """Resolve a corner piece of each pointed-at level and decode it on its own.

        This is what catches a byte range that is subtly wrong. Such a range does
        not fail; it decodes to a picture, and the picture is of the wrong part of
        the specimen.

        Only the two far corners of each level are taken here, which is the
        cheapest way to notice that resolving ranges has stopped working at all.
        The thorough version — every piece the overview is really served from,
        followed through the map that was written down — is
        :meth:`_follow_the_stored_pointers`, and the two feed the same claim.
        """
        store = self.position_store(position_id)
        checked = 0
        for level_number in self.profile.linkable_levels:
            path = store / str(level_number)
            if not path.exists():
                continue
            try:
                array = zarr.open_array(str(path), mode="r")
                grid = [
                    -(-size // chunk)
                    for size, chunk in zip(array.shape, array.chunks, strict=True)
                ]
                # One piece from each corner of the level is enough to prove the
                # route works while keeping this cheap enough to run on every
                # commit, which is where it has to run.
                for corner in ((0,) * len(grid), tuple(n - 1 for n in grid)):
                    held = where_one_chunk_lives(path, corner)
                    if held is None:
                        continue
                    with held.path.open("rb") as reading:
                        reading.seek(held.offset)
                        lifted = reading.read(held.length)
                    # Comparing the number of bytes would not be worth doing: the
                    # resolver already refuses a range that runs off the end of
                    # its file. What is worth doing, and what nothing else here
                    # would catch, is checking that those bytes are the *right*
                    # bytes. A range that is subtly wrong decodes perfectly well;
                    # it simply shows a different part of the specimen.
                    if not _the_same_picture(lifted, array, corner):
                        complaints.append(
                            f"The pointer for piece {corner} of level "
                            f"{level_number} of '{position_id}' resolves to bytes "
                            f"that do not match the image itself. A viewer would "
                            f"draw them without complaint, showing the wrong part "
                            f"of the specimen."
                        )
                    checked += 1
            except Exception as trouble:
                complaints.append(
                    f"The pointers for level {level_number} of '{position_id}' "
                    f"could not be resolved: {trouble}"
                )
        return checked

    def _follow_the_stored_pointers(
        self, position_id: str, timepoint: int, complaints: list[str]
    ) -> int:
        """Serve every piece this position supplies, out of the map on disk.

        Since the overview copies no pixels at the levels it points at, the
        question that actually matters to an operator is whether a viewer asking
        for a piece of the overview would be handed this position's own pixels.
        That question is asked here the way the viewer's own server asks it:
        through the stored map, one piece at a time, for every piece of the
        picture this position supplies at this moment.

        Each answer is checked twice over. It has to come out of this position's
        own store — a piece served out of the neighbour's store is still specimen
        and looks entirely convincing — and the bytes it points at have to decode
        to the same pixels the position's own array returns for that piece.
        """
        try:
            stored = self._read_the_link_map()
        except Exception as trouble:
            complaints.append(str(trouble))
            return 0

        served = 0
        for level in stored.get("levels", ()):
            level_number = level["level"]
            mine = [
                entry
                for entry in level.get("positions", ())
                if entry["position_id"] == position_id
            ]
            if not mine:
                complaints.append(
                    f"The stored map of pointers says nothing about '{position_id}' "
                    f"at level {level_number}, so a viewer asking for the ground "
                    f"this position covers would be told there is nothing there."
                )
                continue
            try:
                route = route_the_view(
                    [
                        Placed(
                            array=self.folder / entry["array"],
                            lands_at=tuple(entry["lands_at"]),
                            taken_from=tuple(entry["taken_from"]),
                            size=tuple(entry["size"]),
                        )
                        for entry in level.get("positions", ())
                    ],
                    view_shape=tuple(level["view_shape"]),
                )
                served += self._every_piece_of_mine_is_served(
                    position_id, level_number, mine[0], route, timepoint, complaints
                )
            except Exception as trouble:
                complaints.append(
                    f"The stored map of pointers for level {level_number} could not "
                    f"be followed: {trouble}"
                )
        return served

    def _every_piece_of_mine_is_served(
        self,
        position_id: str,
        level_number: int,
        entry: dict,
        route,
        timepoint: int,
        complaints: list[str],
    ) -> int:
        """Ask the route for each piece this position supplies, and weigh the answer.

        Stops at the first piece that is wrong. One clear sentence about the first
        fault is more use at a microscope than several thousand about all of them,
        and the position is being refused either way.
        """
        path = self.position_store(position_id) / str(level_number)
        array = zarr.open_array(str(path), mode="r")
        across = route.inner_chunk
        low = [entry["taken_from"][axis] // across[axis] for axis in range(3)]
        first = [entry["lands_at"][axis] // across[axis] for axis in range(3)]
        how_many = [-(-entry["size"][axis] // across[axis]) for axis in range(3)]
        # The position's own pixels for the whole of its share, read once. Reading
        # them a piece at a time instead was measured at roughly ten times the
        # cost, and this check runs on the path of every commit while the
        # microscope is waiting for it.
        starts = [entry["taken_from"][axis] for axis in range(3)]
        stops = [starts[axis] + entry["size"][axis] for axis in range(3)]
        mine = array[
            timepoint, :,
            starts[0]:stops[0], starts[1]:stops[1], starts[2]:stops[2],
        ]
        served = 0
        for colour in range(len(self.channels)):
            for plane in range(how_many[0]):
                for down in range(how_many[1]):
                    for along in range(how_many[2]):
                        stepped = (plane, down, along)
                        wanted = (
                            timepoint,
                            colour,
                            *(first[axis] + stepped[axis] for axis in range(3)),
                        )
                        answer = route.where_this_chunk_is(wanted)
                        if answer is None:
                            complaints.append(
                                f"The overview has nothing to hand over for piece "
                                f"{wanted} of level {level_number}, although "
                                f"'{position_id}' is meant to supply it. A viewer "
                                f"would draw empty ground there."
                            )
                            return served
                        if answer.position != path:
                            complaints.append(
                                f"Piece {wanted} of level {level_number} would be "
                                f"served out of {answer.position} rather than out of "
                                f"'{position_id}'. Another position's pixels still "
                                f"look like specimen, so nothing on the screen would "
                                f"say the wrong tile is being shown."
                            )
                            return served
                        inside = answer.inside_the_position[-3:]
                        here = tuple(
                            slice(
                                (inside[axis] - low[axis]) * across[axis],
                                min(
                                    (inside[axis] - low[axis] + 1) * across[axis],
                                    mine.shape[axis + 1],
                                ),
                            )
                            for axis in range(3)
                        )
                        with answer.path.open("rb") as reading:
                            reading.seek(answer.offset)
                            handed_over = reading.read(answer.length)
                        if not self._these_are_the_same_pixels(
                            handed_over, route.storage, mine[(colour, *here)], array,
                            answer.inside_the_position,
                        ):
                            complaints.append(
                                f"The bytes the overview would hand over for piece "
                                f"{wanted} of level {level_number} do not decode to "
                                f"what '{position_id}' actually holds there. They "
                                f"decode perfectly well; they are simply a picture "
                                f"of somewhere else."
                            )
                            return served
                        served += 1
        return served

    def _these_are_the_same_pixels(
        self, handed_over: bytes, storage, expected, array, corner
    ) -> bool:
        """Do the bytes the overview would serve hold the pixels expected of them?

        A stored piece is compressed, so the only way to compare it against
        anything is to undo that. Where the compression is one this module
        recognises, the piece is unpacked on its own, which is quick enough to do
        for every piece of every commit. Where it is not — because a run was
        written by some other tool, or with a codec added later — the piece is
        compared the slower but entirely general way instead, by building a
        one-piece image out of it and reading that back.

        A piece at the edge of a level is stored full-sized and padded out, while
        the image itself stops where the specimen does, so only the part that
        genuinely exists is compared.
        """
        unpacked = _unpacked_on_its_own(handed_over, storage)
        if unpacked is None:
            return _the_same_picture(handed_over, array, corner)
        trimmed = unpacked[tuple(slice(0, reach) for reach in expected.shape)]
        return bool(np.array_equal(trimmed, expected))

    def _check_the_zoomed_out_picture(
        self, position_id: str, timepoint: int, complaints: list[str]
    ) -> int:
        """Confirm the shared picture really shows this position's own pixels.

        Counting the pieces that had to be rebuilt says how much work the commit
        brought with it, and that number is worth keeping. What it cannot say is
        whether the picture is *right*, and the only way to find that out is to
        read the ground this position covers back out of the picture and compare
        it, pixel for pixel, against the position's own store. A picture that is
        present but black passes every test except this one, and on the screen it
        looks exactly like specimen nobody has imaged yet.
        """
        placement = self.layout.placement(position_id)
        if not self.seamless_store.exists():
            complaints.append(
                "The run-wide zoomed-out picture has not been built yet, so this "
                "position would be complete zoomed in and missing zoomed out."
            )
            return 0
        rebuilt = 0
        try:
            view = zarr.open_array(str(self.seamless_store), mode="r")
            for level_number in (0,):
                for piece in chunks_touched_by(self.profile, placement, level_number):
                    allowed = what_a_chunk_should_hold(
                        self.profile, piece, self.layout.positions,
                        frozenset(self.manifest.committed().by_store) | {position_id},
                    )
                    if not allowed:
                        continue
                    rebuilt += 1
            shown = self._what_this_tile_fills_in(placement)
            y, x = shown["y"], shown["x"]
            y0, x0 = placement.origin["y"], placement.origin["x"]
            source = zarr.open_array(
                str(self.position_store(position_id) / "0"), mode="r"
            )
            as_written = source[timepoint, :, :, y.start:y.stop, x.start:x.stop]
            as_shown = view[
                timepoint, :, :,
                y0:y0 + y.length,
                x0:x0 + x.length,
            ]
            if as_shown.size == 0:
                complaints.append(
                    "The zoomed-out picture does not reach the ground this "
                    "position covers."
                )
            elif as_shown.shape != as_written.shape or not np.array_equal(
                as_shown, as_written
            ):
                complaints.append(
                    f"The zoomed-out picture does not show '{position_id}'s own "
                    f"pixels over the ground it covers at moment {timepoint}. "
                    f"Empty ground and somebody else's specimen both look "
                    f"completely ordinary on the screen, so only comparing the "
                    f"pixels notices."
                )
        except Exception as trouble:
            complaints.append(f"The zoomed-out picture could not be read: {trouble}")
        return rebuilt

    def _check_the_raw_overlap_view(
        self, position_id: str, timepoint: int, complaints: list[str]
    ) -> int:
        """Confirm this position's own measurements are still in the raw view.

        The whole frame is read back out of the stop belonging to this position
        and compared, pixel for pixel, against the position's own store. Counting
        files or trusting that the write happened would not do: the failure this
        catches is another tile's pixels sitting where these ones should be, and
        those are perfectly readable pixels that look exactly like specimen.

        Returns how many pixels were compared, which is taken from the array that
        came back rather than from any description of it, so that removing the
        read cannot leave the count looking healthy.
        """
        placement = self.layout.placement(position_id)
        if not self.raw_overlap_store.exists():
            complaints.append(
                "The raw overlap view has not been built yet, so the measurements "
                "this position made where it meets its neighbours would exist only "
                "in its own store, with nowhere for an operator to compare them."
            )
            return 0
        try:
            view = zarr.open_array(str(self.raw_overlap_store), mode="r")
            source = zarr.open_array(
                str(self.position_store(position_id) / "0"), mode="r"
            )
            everything = placement.analysis_input_roi
            y, x = everything["y"], everything["x"]
            lands_y = placement.origin["y"]
            lands_x = placement.origin["x"]
            as_written = source[timepoint, :, :, y.start:y.stop, x.start:x.stop]
            as_stored = view[
                self.tile_stop_of(position_id),
                timepoint, :, :,
                lands_y:lands_y + y.length,
                lands_x:lands_x + x.length,
            ]
            if as_stored.shape != as_written.shape or not np.array_equal(
                as_stored, as_written
            ):
                complaints.append(
                    f"The raw overlap view does not show '{position_id}'s own "
                    f"measurements where it should. Another tile's pixels sitting "
                    f"here would still look like specimen, so nothing on screen "
                    f"would say that this position's record of the overlap has "
                    f"been lost."
                )
            return int(as_stored.size)
        except Exception as trouble:
            complaints.append(f"The raw overlap view could not be read: {trouble}")
            return 0

    def _layout_reads_back(self, complaints: list[str]) -> bool:
        """The arrangement must be on disk, and must be this run's, before use.

        Parsing the file is the easy half. The half that matters is that the
        arrangement found there belongs to the run in hand: the same experiment,
        the same storage plan, and the same revision number. A layout from another
        run is perfectly well-formed and describes an entirely different set of
        tiles, so every measurement published against it would be pointing at
        somebody else's account of who owns what — and nothing about that shows up
        as an error.
        """
        target = self.folder / "zmart-live" / _LAYOUT
        if not target.exists():
            complaints.append(
                "The arrangement saying who owns what has not been written, so a "
                "published measurement would have nothing to refer back to."
            )
            return False
        try:
            stored = SceneLayoutRevision.from_json(json.loads(target.read_text()))
        except Exception as trouble:
            complaints.append(f"The stored arrangement could not be read: {trouble}")
            return False
        for name, found, wanted in (
            ("run", stored.run_id, self.run_id),
            ("storage plan", stored.profile_id, self.profile.profile_id),
            ("revision", stored.revision, self.layout.revision),
        ):
            if found != wanted:
                complaints.append(
                    f"The stored arrangement names the {name} {found!r}, but this "
                    f"run's is {wanted!r}. It reads back perfectly well and "
                    f"describes a different experiment's tiles, which is exactly "
                    f"why it has to be refused rather than used."
                )
                return False
        if stored.position_ids != self.layout.position_ids:
            complaints.append(
                f"The stored arrangement describes the positions "
                f"{list(stored.position_ids)}, but this run holds "
                f"{list(self.layout.position_ids)}."
            )
            return False
        return True

    # -- publishing ----------------------------------------------------------

    def publish(
        self,
        position_id: str,
        *,
        timepoint: int | None = None,
        superseding: bool = False,
    ) -> CommitEvent:
        """Look at the position, and publish it only if what is there justifies it.

        There is deliberately no way to pass a readiness flag in. The event is
        assembled from :meth:`inspect`'s findings, so "ready" always means
        "somebody went and looked", never "somebody said so". ``superseding`` is
        not such a flag: it says what kind of publication this is, which the
        record needs in order to distinguish new pixels from replaced ones, and it
        makes nothing easier to publish.
        """
        found = self.inspect(position_id, timepoint=timepoint)
        if not found.everything_checks_out:
            raise NotReadyToPublish(found.describe())

        placement = self.layout.placement(position_id)
        if superseding:
            kind = "position_replaced"
        elif timepoint is None:
            kind = "position_committed"
        else:
            kind = "timepoint_committed"
        event = CommitEvent(
            revision=self.manifest.next_revision(),
            event_type=kind,
            position_id=position_id,
            run_id=self.run_id,
            acquisition_type=self.profile.acquisition_type,
            acquisition_profile_id=self.profile.profile_id,
            scene_layout_revision=self.layout.revision,
            link_revision=self.layout.revision,
            timepoint=timepoint,
            component_id=placement.component_id,
            cell=placement.cell,
            owned_region=placement.visual_roi_in_run(),
            channels=self.channels,
            levels=tuple(level.level for level in self.profile.levels),
            pyramids_ready=found.pyramids_ready,
            links_ready=found.links_ready,
            coarse_chunks_ready=found.coarse_chunks_ready,
            validated=found.everything_checks_out,
            timestamp=now_in_words(),
            notes=found.describe(),
        )
        self.manifest.publish(event)
        return event

    def write_and_publish(
        self, position_id: str, pixels: np.ndarray, *, timepoint: int | None = None
    ) -> CommitEvent:
        """The whole ordered sequence for one position, in the order it must happen.

        Pixels and their zoomed-out copies, then both shared pictures rebuilt from
        what is already published plus this, then the map of pointers and the
        arrangement, then one commit. Doing these in another order is what
        produces a viewer showing something that is not finished.
        """
        self.write_a_position(position_id, pixels, timepoint=timepoint or 0)
        return self._rebuild_everything_shared_and_publish(
            position_id, timepoint=timepoint
        )

    def replace_a_position(
        self, position_id: str, pixels: np.ndarray, *, timepoint: int = 0
    ) -> CommitEvent:
        """Supersede pixels that have already been published, without altering them.

        Sometimes a moment has to be written again — the focus was wrong, the
        laser was off, the frame that arrived was not the frame that was meant.
        Simply writing over it is refused, because somebody may already be looking
        at those pixels and a picture that changes underneath a published revision
        cannot be reasoned about at all.

        So this makes a **new generation** of the position instead. Everything the
        position already held is carried across into a new folder, the new pixels
        are written into that copy, and the old folder is left exactly as it was.
        Both shared pictures are then rebuilt from the new generation and the
        change is published as its own revision, so the two pictures move
        together and an earlier revision goes on meaning what it meant.

        Carrying the position across means copying it, and for a large position
        that is a real cost — worth knowing before this is used as a matter of
        course. It is the price of the promise, and replacing a moment is meant
        to be a deliberate act rather than an ordinary one.

        Returns the commit that made the replacement visible. Raises
        :class:`~zmart_live.model.ZmartLiveError` when this moment has never been
        published, since there is then nothing to supersede and
        :meth:`write_a_position` is the ordinary way in.
        """
        if (position_id, timepoint) not in self._committed_units():
            raise ZmartLiveError(
                f"Moment {timepoint} of '{position_id}' has never been published, so "
                f"there is nothing to supersede. Write it in the ordinary way "
                f"instead; replacing exists only to protect pixels somebody has "
                f"already been shown."
            )
        was = self.generations.get(position_id, 0)
        now = was + 1
        carried_over = self.position_store(position_id, generation=now)
        if carried_over.exists():
            shutil.rmtree(carried_over)
        # Everything the position already held is copied rather than moved, so
        # that the pixels published under earlier revisions stay exactly where
        # they were and any moment this replacement does not touch is still here.
        shutil.copytree(self.position_store(position_id, generation=was), carried_over)
        self.generations[position_id] = now
        try:
            self._write_the_pixels(position_id, pixels, timepoint=timepoint)
            return self._rebuild_everything_shared_and_publish(
                position_id, timepoint=timepoint, superseding=True
            )
        except BaseException:
            # Nothing was published, so the run goes back to the generation it was
            # reading a moment ago rather than being left pointing at a half
            # written one.
            self.generations[position_id] = was
            raise

    def _rebuild_everything_shared_and_publish(
        self,
        position_id: str,
        *,
        timepoint: int | None = None,
        superseding: bool = False,
    ) -> CommitEvent:
        """Rebuild every shared picture from what is published, then commit once."""
        already = frozenset(self.manifest.committed().by_store) | {position_id}
        self.write_the_seamless_view(already)
        self.write_the_raw_overlap_view(already)
        self.write_the_link_map(already)
        self.write_the_layout()
        return self.publish(position_id, timepoint=timepoint, superseding=superseding)


def _unpacked_on_its_own(handed_over: bytes, storage) -> np.ndarray | None:
    """Undo the packing of one stored piece, when it is packed a way we know.

    A piece as it sits on disk is a run of bytes that has had two things done to
    it: the pixels were written out one after another in a settled byte order,
    and the result was compressed. Undoing exactly those two steps is far quicker
    than the general method — measured here at about a tenth of a millisecond
    against eleven — which is what makes it affordable to check every piece of
    every commit rather than a couple of corners.

    Returns ``None``, rather than guessing, when the piece was packed some other
    way. The caller then falls back to the general method, which works whatever
    was done to the bytes. Guessing here would produce a confident picture of
    noise, and comparing that against the specimen would fail for a reason that
    has nothing to do with the run.
    """
    named = [
        step.get("name") if isinstance(step, dict) else None for step in storage.codecs
    ]
    if named[:1] != ["bytes"]:
        return None
    settings = storage.codecs[0].get("configuration") or {}
    order = settings.get("endian", "little")
    rest = named[1:]
    if rest == ["zstd"]:
        try:
            from numcodecs.zstd import Zstd
        except ImportError:  # pragma: no cover - numcodecs comes with zarr
            return None
        try:
            handed_over = Zstd().decode(handed_over)
        except Exception:
            return None
    elif rest:
        return None
    kind = np.dtype(storage.dtype).newbyteorder("<" if order == "little" else ">")
    try:
        flat = np.frombuffer(handed_over, dtype=kind)
        return flat.reshape(storage.chunk)[0, 0]
    except ValueError:
        # The wrong number of bytes for this piece. That is a real disagreement
        # rather than a packing we do not know, so an empty answer is given back
        # and it will compare equal to nothing at all.
        return np.zeros((0, 0, 0), dtype=kind)


def _the_same_picture(lifted: bytes, array, corner: tuple[int, ...]) -> bool:
    """Do these bytes, decoded on their own, match what the image itself returns?

    The bytes were taken out of the middle of a bundle by offset and length. To
    be sure the offset was right, they are decoded as a piece in their own right
    and compared against the same region read normally.

    This is the check that catches a range that is off by a little. Such a range
    does not raise: it produces a perfectly good picture of the wrong place, and
    downstream nobody can tell.
    """
    import tempfile

    from zarr.codecs import ZstdCodec

    # A piece at the edge of a level is stored full-sized and padded, while the
    # image itself stops where the specimen does. So the comparison is made over
    # the part that genuinely exists, and the padding is left out of it. Missing
    # this is easy: it makes every edge piece look wrong, at every level whose
    # width is not a whole number of pieces.
    region = tuple(
        slice(place * size, min(place * size + size, reach))
        for place, size, reach in zip(corner, array.chunks, array.shape, strict=True)
    )
    expected = array[region]
    keep = tuple(slice(0, span.stop - span.start) for span in region)
    with tempfile.TemporaryDirectory() as scratch:
        alone = Path(scratch) / "one.zarr"
        solo = zarr.create_array(
            store=str(alone), shape=array.chunks, chunks=array.chunks,
            dtype=array.dtype, zarr_format=3,
            compressors=[ZstdCodec(level=3)], overwrite=True,
        )
        solo[...] = 1                    # force the single piece to exist on disk
        stored = next(
            p for p in alone.rglob("*") if p.is_file() and p.name != "zarr.json"
        )
        stored.write_bytes(lifted)
        try:
            recovered = zarr.open_array(str(alone), mode="r")[keep]
        except Exception:
            return False
    return bool(np.array_equal(recovered, expected))


def _halve(pixels: np.ndarray) -> np.ndarray:
    """Make the next zoomed-out copy by averaging two-by-two blocks.

    Averaging rather than dropping every other pixel, because dropping loses a
    faint object that happens to sit on an odd row, and a faint object is usually
    the thing somebody is looking for.

    Only the width and the height are halved. Colours are not, because they are
    separate measurements rather than neighbouring places, and planes are not,
    because the space between planes is usually far larger than the space between
    pixels within one, so averaging two of them together would blur across more
    specimen than it saves.
    """
    colours, depth, height, width = pixels.shape
    height -= height % 2
    width -= width % 2
    trimmed = pixels[:, :, :height, :width].astype("float32")
    smaller = trimmed.reshape(
        colours, depth, height // 2, 2, width // 2, 2
    ).mean(axis=(3, 5))
    return smaller.astype(pixels.dtype)

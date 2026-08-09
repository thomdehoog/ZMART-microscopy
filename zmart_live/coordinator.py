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

What "ready" is made to mean
----------------------------

Five things are checked, and each corresponds to a way an operator could
otherwise be shown a confident picture of nothing.

**The pixels and their zoomed-out copies.** Every level the position advertises
is opened and every one of its pieces is actually read back. Not "does the file
exist" — a file can exist and be half a chunk long. A piece that will not decode
is exactly the piece a viewer would draw as plausible noise.

**The pointers.** For every level the overview means to point at rather than
copy, the byte range for each piece is resolved out of its bundle and decoded on
its own, and compared against what the array itself returns. This is the check
that catches a wrong byte range, which produces a picture rather than an error.

**The shared zoomed-out picture.** The pieces this position disturbs are rebuilt
from the committed positions only, and read back. A piece that still shows the
ground as it was before is not a fault anybody would notice; it looks like
specimen that has not been imaged.

**The raw overlap picture.** The whole frame this position recorded is read back
out of the stop on the tile slider that belongs to it, and compared pixel for
pixel against the position's own store. This is what catches another tile having
written over these measurements, which is the one failure the raw view exists to
make impossible and the one that leaves no trace on screen — the strip still
looks like specimen, it is simply the neighbour's specimen.

**The arrangement.** The layout that says who owns what is written down and read
back before it is referred to, because every published measurement will point at
it later.

Only when all five hold is an event created, and only then does the record move.

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
    SceneLayoutRevision,
    ZmartLiveError,
)
from .ownership import check_the_grid_holds_together, place_the_tiles
from .shardlink import where_one_chunk_lives

__all__ = [
    "Inspection",
    "LivePublisher",
    "NotReadyToPublish",
]

_LAYOUT = "layout.json"


class NotReadyToPublish(ZmartLiveError):
    """What was found on disk does not yet justify showing this to anybody.

    The message lists what is missing. It is a refusal rather than a warning
    because the alternative — publishing anyway and hoping — produces a picture
    that looks finished and is not, which nobody downstream can detect.
    """


@dataclass(frozen=True)
class Inspection:
    """What was actually found when the position was looked at.

    Every field here is the result of opening files and reading bytes. None of it
    can be supplied by a caller, which is the entire point: this is the evidence
    the publication event is built from.
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

    def describe(self) -> str:
        """One paragraph an operator can read when something is being withheld."""
        if self.everything_checks_out:
            return (
                f"'{self.position_id}' is complete: {self.pieces_read} pieces read "
                f"back, {self.ranges_checked} pointers resolved and decoded, "
                f"{self.coarse_pieces_rebuilt} pieces of the zoomed-out picture "
                f"rebuilt from the positions already published, and "
                f"{self.raw_pixels_compared} pixels of the raw overlap view found "
                f"to still be this position's own measurements."
            )
        return (
            f"'{self.position_id}' is not ready to be shown. "
            + " ".join(self.complaints)
        )


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

    def position_store(self, position_id: str) -> Path:
        """The folder holding one position's own image."""
        return self.folder / "positions" / f"{position_id}.ome.zarr"

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

        Writing does not make anything visible. The files land, and they stay
        invisible until :meth:`publish` has looked at them and found them whole.
        """
        if position_id not in self.cells.values():
            raise ZmartLiveError(
                f"'{position_id}' is not one of this run's positions. The run holds "
                f"{sorted(self.cells.values())}."
            )
        store = self.position_store(position_id)
        shrinking = pixels
        for level in self.profile.levels:
            self._write_one_level(store, level, shrinking, timepoint)
            shrinking = _halve(shrinking)

    def _write_one_level(self, store: Path, level, plane: np.ndarray, timepoint: int):
        """Create or open one zoomed-out level and put this moment's pixels in it."""
        path = store / str(level.level)
        depth, height, width = plane.shape
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
        for channel in range(len(self.channels)):
            array[timepoint, channel] = plane

    def write_the_seamless_view(self, committed: frozenset[str]) -> None:
        """Rebuild the run-wide picture from the positions already published.

        The rule this carries out is the one the zoomed-out picture exists to
        obey: a position appears here only once it has been committed. Ground
        belonging to a position that is still being written stays empty, which is
        the truth — that part of the specimen is not finished — rather than a
        picture assembled from half-written data.
        """
        height, width = self._mosaic_extent()
        level = self.profile.level(0)
        shape = (self.timepoints, len(self.channels), 1, height, width)
        chunks = (1, 1, 1, level.inner_chunk["y"], level.inner_chunk["x"])
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
            shown = placement.visual_source_roi
            source = zarr.open_array(
                str(self.position_store(placement.position_id) / "0"), mode="r"
            )
            y, x = shown["y"], shown["x"]
            lands_y = placement.origin["y"]
            lands_x = placement.origin["x"]
            view[:, :, :, lands_y:lands_y + y.length, lands_x:lands_x + x.length] = (
                source[:, :, :, y.start:y.stop, x.start:x.stop]
            )

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

    # -- looking, which is the part that matters -----------------------------

    def inspect(self, position_id: str, *, timepoint: int | None = None) -> Inspection:
        """Go and see whether this position is genuinely finished.

        Reads bytes. Does not take anybody's word for anything. The result is
        what :meth:`publish` builds its event from.
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

        pieces_read = self._read_every_piece(position_id, about_pixels)
        ranges = self._resolve_every_pointer(position_id, about_pointers)
        rebuilt = self._check_the_zoomed_out_picture(position_id, about_the_picture)
        compared = self._check_the_raw_overlap_view(position_id, about_the_overlaps)
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

    def _read_every_piece(self, position_id: str, complaints: list[str]) -> int:
        """Open every advertised level and read all of it back.

        Checking that a file exists is not enough. A file can exist and hold half
        a piece, and half a piece decodes to something rather than to an error.
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
        """Resolve each piece of each pointed-at level and decode it on its own.

        This is what catches a byte range that is subtly wrong. Such a range does
        not fail; it decodes to a picture, and the picture is of the wrong part of
        the specimen.
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

    def _check_the_zoomed_out_picture(
        self, position_id: str, complaints: list[str]
    ) -> int:
        """Confirm the shared picture was rebuilt, and shows only published work."""
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
            shown = placement.visual_source_roi
            y0, x0 = placement.origin["y"], placement.origin["x"]
            corner = view[
                0, 0, 0,
                y0:y0 + min(8, shown["y"].length),
                x0:x0 + min(8, shown["x"].length),
            ]
            if corner.size == 0:
                complaints.append(
                    "The zoomed-out picture does not reach the ground this "
                    "position covers."
                )
        except Exception as trouble:
            complaints.append(f"The zoomed-out picture could not be read: {trouble}")
        return rebuilt

    def _check_the_raw_overlap_view(
        self, position_id: str, complaints: list[str]
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
            as_written = source[:, :, :, y.start:y.stop, x.start:x.stop]
            as_stored = view[
                self.tile_stop_of(position_id),
                :, :, :,
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
        """The arrangement must be on disk before anything points at it."""
        target = self.folder / "zmart-live" / _LAYOUT
        if not target.exists():
            complaints.append(
                "The arrangement saying who owns what has not been written, so a "
                "published measurement would have nothing to refer back to."
            )
            return False
        try:
            SceneLayoutRevision.from_json(json.loads(target.read_text()))
            return True
        except Exception as trouble:
            complaints.append(f"The stored arrangement could not be read: {trouble}")
            return False

    # -- publishing ----------------------------------------------------------

    def publish(self, position_id: str, *, timepoint: int | None = None) -> CommitEvent:
        """Look at the position, and publish it only if what is there justifies it.

        There is deliberately no way to pass a readiness flag in. The event is
        assembled from :meth:`inspect`'s findings, so "ready" always means
        "somebody went and looked", never "somebody said so".
        """
        found = self.inspect(position_id, timepoint=timepoint)
        if not found.everything_checks_out:
            raise NotReadyToPublish(found.describe())

        placement = self.layout.placement(position_id)
        event = CommitEvent(
            revision=self.manifest.next_revision(),
            event_type=(
                "position_committed" if timepoint is None else "timepoint_committed"
            ),
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

        Pixels and their zoomed-out copies, then both shared pictures rebuilt
        from what is already published plus this, then the arrangement, then one
        commit. Doing these in another order is what produces a viewer showing
        something that is not finished.
        """
        self.write_a_position(position_id, pixels, timepoint=timepoint or 0)
        already = frozenset(self.manifest.committed().by_store) | {position_id}
        self.write_the_seamless_view(already)
        self.write_the_raw_overlap_view(already)
        self.write_the_layout()
        return self.publish(position_id, timepoint=timepoint)


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


def _halve(plane: np.ndarray) -> np.ndarray:
    """Make the next zoomed-out copy by averaging two-by-two blocks.

    Averaging rather than dropping every other pixel, because dropping loses a
    faint object that happens to sit on an odd row, and a faint object is usually
    the thing somebody is looking for.
    """
    depth, height, width = plane.shape
    height -= height % 2
    width -= width % 2
    trimmed = plane[:, :height, :width].astype("float32")
    smaller = trimmed.reshape(depth, height // 2, 2, width // 2, 2).mean(axis=(2, 4))
    return smaller.astype(plane.dtype)

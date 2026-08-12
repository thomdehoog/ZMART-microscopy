"""Write canonical positions and publish the one strictly virtual linked view.

The manifest refuses an event whose readiness is not proved from the bytes on
disk. A caller cannot supply readiness flags: this coordinator writes a complete
position or timepoint, reads every promised canonical pyramid level back, follows
the stored routes, validates the view description and the realized layout, and
only then advances the atomic publication record.

All pixels live below ``positions/``. Every canonical pyramid level is sharded
and independently portable as part of its position OME-Zarr image, and each
position's own description places it on the specimen — the store opens in the
right place in any OME-Zarr reader on its own, exactly like a mesoSPIM
transfer. The single run-wide presentation below ``views/`` is a description
and routes only. Positions enter it **whole, overlap intact**, in the order
they were committed, and where two of them cover the same ground the later
commit is drawn on top — the settled model of
``docs/design/positions-in-a-container.md``. Nothing hides the overlap: both
recordings of shared ground stay whole in the position stores, which are the
system of record.

The view may not contain a ``c/`` payload tree. Each advertised view chunk is an
already-encoded canonical inner chunk located by byte range inside a source
shard. Publication fails closed if the acquisition profile, route geometry,
encoding, draw order, or manifest generation disagrees.

Published canonical bytes are immutable. Replacing a moment creates a new
position generation, refreshes the generation-specific routes and metadata, and
publishes that answer as a new revision. A failed replacement restores the old
route map; there are no shared view pixels to roll back.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import zarr
from zarr.codecs import ZstdCodec

from .identity import (
    latest_layout_revision,
    record_the_layout,
    spatial_fingerprint_of_a_layout,
    store_the_profile,
)
from .manifest import RunManifest, _write_and_replace, now_in_words
from .model import (
    AcquisitionProfile,
    CommitEvent,
    GridCell,
    SceneLayoutRevision,
    ZmartLiveError,
)
from .omezarr import describe_the_position
from .ownership import check_the_grid_holds_together, place_the_tiles
from .shardlink import where_one_chunk_lives
from .viewroute import Placed, refuse_a_view_stored_differently, route_the_view

__all__ = [
    "Inspection",
    "LivePublisher",
    "NotReadyToPublish",
]

_LAYOUT = "layout.json"
_LINKS = "links.json"

#: The name written into the map of pointers, so that anybody reading that file
#: can tell at once whether it is one this version of ZMART understands.
#: Version 3 routes every position whole and makes the **order** of the stored
#: positions load-bearing: it is the commit order, and a later entry is drawn
#: over an earlier one wherever the two cover the same ground.
_LINKS_SCHEMA = "zmart-live-links/3"


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
    view_ready: bool = False
    layout_ready: bool = False
    pieces_read: int = 0
    ranges_checked: int = 0
    view_levels_validated: int = 0
    complaints: tuple[str, ...] = ()

    @property
    def everything_checks_out(self) -> bool:
        """True only when all four checks held and nothing was complained about."""
        return (
            self.pyramids_ready
            and self.links_ready
            and self.view_ready
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
                f"resolved through the stored map and decoded, and "
                f"{self.view_levels_validated} virtual view levels validated "
                f"without copied payload."
            )
        return f"{which} is not ready to be shown. " + " ".join(self.complaints)


@dataclass
class LivePublisher:
    """Publish complete positions through one metadata-only run-wide view.

    Canonical pixels and pyramids are finalized first, then the ordered route
    map and view description, then the realized layout, and finally one
    indivisible manifest commit. Nothing is visible until that last step.
    """

    folder: Path
    profile: AcquisitionProfile
    run_id: str
    cells: dict[GridCell, str]
    channels: tuple[str, ...] | None = None
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

        profile_channels = tuple(self.profile.channels)
        if not profile_channels:
            raise ZmartLiveError(
                "A live image profile has to declare at least one channel. The "
                "writer cannot give an unnamed empty colour axis a scientific "
                "meaning after pixels have been published."
            )
        expected_axes = ("t", "c", "z", "y", "x")
        if self.profile.axes != expected_axes:
            raise ZmartLiveError(
                f"This live writer indexes arrays as {expected_axes}, but profile "
                f"{self.profile.profile_id!r} declares {self.profile.axes}. "
                "Reordering those axes without reordering every write and route "
                "would mislabel pixels, so this profile is refused."
            )
        if self.channels is None:
            self.channels = profile_channels
        else:
            self.channels = tuple(self.channels)
            if self.channels != profile_channels:
                raise ZmartLiveError(
                    f"This writer was given the channels {list(self.channels)}, but "
                    f"its sealed acquisition profile declares "
                    f"{list(profile_channels)}. Channel identity is part of the "
                    "profile and cannot be changed independently; plan a profile "
                    "with those channels instead."
                )
        if (
            not isinstance(self.timepoints, int)
            or isinstance(self.timepoints, bool)
            or self.timepoints < 1
        ):
            raise ZmartLiveError(
                f"A live position store needs room for at least one timepoint; got "
                f"{self.timepoints!r}."
            )

        component = check_the_grid_holds_together(
            self.cells, profile_id=self.profile.profile_id
        )
        if not component.complete:
            raise ZmartLiveError(
                "The planned mosaic footprint is incomplete. Missing cells inside "
                "the footprint cannot be treated as outer boundaries, because the "
                "neighbouring tiles would then own and display the same specimen "
                "twice. Supply the complete planned footprint before starting this "
                "publisher."
            )
        placements = place_the_tiles(self.profile, self.cells)
        candidate_layout = SceneLayoutRevision(
            revision=1,
            schema_version="zmart-live-layout/2",
            run_id=self.run_id,
            acquisition_type=self.profile.acquisition_type,
            profile_id=self.profile.profile_id,
            positions=placements,
            components=(component,),
            analysis_ownership=self.profile.analysis_ownership,
            created_at=now_in_words(),
        )
        self.manifest = RunManifest.start(self.folder, run_id=self.run_id)

        newest = latest_layout_revision(self.folder)
        if (
            newest is not None
            and spatial_fingerprint_of_a_layout(newest)
            != spatial_fingerprint_of_a_layout(candidate_layout)
        ):
            raise ZmartLiveError(
                f"Run {self.run_id!r} already has immutable layout revision "
                f"{newest.revision}, and reopening it with this acquisition "
                "profile, grid, or ownership policy would give its existing "
                "pixels a different meaning. Resume it with exactly the same "
                "plan, or start the changed acquisition in a new run folder."
            )

        store_the_profile(self.folder, self.profile)
        self.layout = record_the_layout(self.folder, candidate_layout)
        self._restore_generations_from_the_manifest()
        self._check_existing_position_shapes_match_the_plan()

    def _restore_generations_from_the_manifest(self) -> None:
        """Recover which immutable position generation every commit refers to.

        New records state the generation directly.  Records made before that
        field existed can still be recovered because each replacement advanced
        the generation exactly once.  This keeps old runs readable while making
        every new commit self-describing.
        """
        restored: dict[str, int] = {}
        replacements_seen: dict[str, int] = {}
        for event in self.manifest.events():
            inferred = replacements_seen.get(event.position_id, 0)
            if event.event_type == "position_replaced":
                inferred += 1
                replacements_seen[event.position_id] = inferred
            generation = max(event.position_generation, inferred)
            if generation:
                restored[event.position_id] = max(
                    restored.get(event.position_id, 0), generation
                )
        self.generations = restored

    def _check_existing_position_shapes_match_the_plan(self) -> None:
        """Refuse to reinterpret arrays left by an earlier writer process.

        Timepoint room is declared when the arrays are first made. It is not a
        spatial layout property, so the layout fingerprint cannot protect it.
        The arrays themselves are the durable declaration: once any current
        position exists, reopening the run must agree with its complete level-0
        shape, including time and channel room.
        """
        expected = (
            self.timepoints,
            len(self.channels),
            self.profile.frame_shape["z"],
            self.profile.frame_shape["y"],
            self.profile.frame_shape["x"],
        )
        for placement in self.layout.positions:
            level_zero = self.position_store(placement.position_id) / "0"
            if not level_zero.exists():
                continue
            try:
                found = zarr.open_array(str(level_zero), mode="r")
            except Exception as trouble:
                raise ZmartLiveError(
                    f"The existing level-zero array for {placement.position_id!r} "
                    f"cannot be checked while reopening this run: {trouble}"
                ) from trouble
            if tuple(found.shape) != expected:
                raise ZmartLiveError(
                    f"The existing level-zero array for {placement.position_id!r} "
                    f"has shape {tuple(found.shape)}, but this reopened writer "
                    f"would use {expected}. In particular, declared timepoint "
                    "room and channels cannot change after pixels exist; resume "
                    "with the original plan or start a new run folder."
                )

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
    def view_store(self) -> Path:
        """The OME-Zarr group holding the one linked multiscale picture.

        The name is not free to choose: :func:`zmart_live.scene.build_the_scene`
        tells the viewer where to find this view, and the two have to agree or
        the operator is handed an address with nothing behind it.
        """
        return self.folder / "views" / "overview.ome.zarr"

    def view_level(self, level: int = 0) -> Path:
        """One resolution level inside the linked OME-Zarr image."""
        return self.view_store / str(level)

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

    def _positions_in_commit_order(self) -> list[str]:
        """Every published position, in the order each one first arrived.

        This order is the draw order of the linked view, so it is read back
        from the durable publication history rather than remembered in memory.
        A position keeps its place when a later moment or a replacement is
        committed: the tile itself did not move, only its pixels grew or were
        superseded, and reshuffling the draw order underneath an unchanged
        picture would make published ground change hands with nothing recording
        why.
        """
        ordered: list[str] = []
        for event in self.manifest.events():
            if event.position_id not in ordered:
                ordered.append(event.position_id)
        return ordered

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

        placement = self.layout.placement(position_id)
        describe_the_position(
            store,
            self.profile,
            name=position_id,
            channels=self.channels,
            origin_pixels=placement.origin,
        )

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
            settled = given[np.newaxis]
        elif given.ndim == 4:
            if given.shape[0] != len(self.channels):
                raise ZmartLiveError(
                    f"This run records the colours {list(self.channels)}, so it "
                    f"expects pixels for {len(self.channels)} of them, but it was "
                    f"handed {given.shape[0]}."
                )
            settled = given
        else:
            raise ZmartLiveError(
                f"This run records the colours {list(self.channels)}. Pixels for it "
                f"have to arrive as (colour, z, y, x), one stack of planes per "
                f"colour; what arrived has the shape {tuple(given.shape)}. A run "
                f"with a single colour may also hand over a plain (z, y, x) stack, "
                f"but a run with more than one cannot, because copying one colour's "
                "pixels into the others would look exactly like a successful "
                "acquisition."
            )

        expected_shape = tuple(
            self.profile.frame_shape[axis] for axis in ("z", "y", "x")
        )
        if tuple(settled.shape[1:]) != expected_shape:
            raise ZmartLiveError(
                f"Profile {self.profile.profile_id!r} declares each position as "
                f"(z, y, x)={expected_shape}, but the pixels supplied have spatial "
                f"shape {tuple(settled.shape[1:])}. Writing them would make the "
                "OME-Zarr description disagree with its arrays, so nothing was "
                "written. Use the profile for this camera/acquisition format."
            )
        return settled

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

    def _as_position_moments(
        self, committed: frozenset[str | tuple[str, int]]
    ) -> frozenset[tuple[str, int]]:
        """Normalize the old position shorthand without ever meaning all moments.

        A plain position name predates timepoint publication and safely means
        moment zero only.  Treating it as every moment is the bug this boundary
        exists to prevent.
        """
        units: set[tuple[str, int]] = set()
        for item in committed:
            if isinstance(item, str):
                units.add((item, 0))
                continue
            position_id, moment = item
            if not isinstance(position_id, str) or not isinstance(moment, int):
                raise ZmartLiveError(
                    "A published view unit has to be a (position name, moment) pair."
                )
            units.add((position_id, moment))
        return frozenset(units)

    def write_the_view(self) -> None:
        """Describe the one linked image without storing any of its pixels.

        Visibility lives in the link map and manifest; nothing here depends on
        what has been committed, because there are no view pixels to fill or
        clear — only the description of a picture whose every byte is served
        out of the positions.

        Existing ``c/`` payload trees are removed deliberately. They came from
        the earlier copying implementation and would otherwise leave a stale
        second source of truth beside the canonical position chunks.
        """
        levels = self._strict_zero_copy_levels()
        zarr.open_group(str(self.view_store), mode="a", zarr_format=3)
        self._remove_unadvertised_view_levels(
            self.view_store,
            {level.level for level in levels},
        )
        for level in levels:
            depth, height, width = self._how_big_the_overview_is(level.level)
            shape = (self.timepoints, len(self.channels), depth, height, width)
            chunks = (
                1,
                1,
                min(level.inner_chunk["z"], depth),
                min(level.inner_chunk["y"], height),
                min(level.inner_chunk["x"], width),
            )
            path = self.view_level(level.level)
            if not path.exists():
                zarr.create_array(
                    store=str(path),
                    shape=shape,
                    chunks=chunks,
                    dtype=self.profile.dtype,
                    zarr_format=3,
                    compressors=[ZstdCodec(level=3)],
                    dimension_names=self.profile.axes,
                    overwrite=False,
                )
            self._remove_view_payload(path)

        describe_the_position(
            self.view_store,
            self.profile,
            name="overview",
            levels=levels,
            channels=self.channels,
            origin_pixels={"z": 0, "y": 0, "x": 0},
        )

    def _strict_zero_copy_levels(self):
        """Return all levels, or refuse a profile requiring view-owned pixels."""
        missing = [level.level for level in self.profile.levels if not level.linkable]
        if not self.profile.levels or missing:
            raise ZmartLiveError(
                f"Profile {self.profile.profile_id!r} cannot publish strict "
                f"zero-copy views: levels {missing or 'none'} are not linkable. "
                "Plan the frame, overlap and per-level chunks together; this "
                "publisher will not hide the mismatch by copying view pixels."
            )
        return self.profile.levels

    @staticmethod
    def _remove_view_payload(path: Path) -> None:
        """Remove legacy view chunks while preserving the array description."""
        payload = path / "c"
        if payload.is_dir():
            shutil.rmtree(payload)
        elif payload.exists():
            payload.unlink()

    @staticmethod
    def _remove_unadvertised_view_levels(store: Path, advertised: set[int]) -> None:
        """Remove obsolete numeric arrays that the virtual view no longer lists."""
        if not store.exists():
            return
        for child in store.iterdir():
            if child.is_dir() and child.name.isdigit() and int(child.name) not in advertised:
                shutil.rmtree(child)

    def write_the_layout(self) -> None:
        """Persist the immutable arrangement a published result points at.

        The convenience ``layout.json`` pointer is updated atomically, while the
        numbered snapshot it names is write-once.  Repeating an unchanged layout
        reuses its revision; a genuine spatial change receives a new one.
        """
        self.layout = record_the_layout(self.folder, self.layout)

    # -- the pointers the overview is served from ----------------------------

    def _where_one_tile_is_pointed_at(self, position_id: str, level_number: int) -> Placed:
        """Where one tile's own pixels sit in the overview, at one zoom level.

        Everything here is in that level's own pixels, so the full-resolution
        numbers are divided by how much smaller the level is. Every tile is
        placed **whole** — its complete camera frame, overlap intact — and where
        two frames cover the same ground, the draw order of the route decides
        which is shown.
        """
        placement = self.layout.placement(position_id)
        smaller = self.profile.level(level_number).downsampling
        by = {axis: smaller.get(axis, 1) for axis in ("z", "y", "x")}
        return Placed(
            array=self.position_store(position_id) / str(level_number),
            lands_at=(
                0,
                placement.origin["y"] // by["y"],
                placement.origin["x"] // by["x"],
            ),
            taken_from=(0, 0, 0),
            size=tuple(
                self.profile.frame_shape.get(axis, 1) // by[axis]
                for axis in ("z", "y", "x")
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

    def write_the_link_map(
        self, committed: frozenset[str | tuple[str, int]]
    ) -> None:
        """Write down which position's own bytes answer for each piece of the overview.

        At the zoom levels the storage plan says can be pointed at, the overview
        keeps no pixels of its own: when the viewer asks for a piece of it, the
        answer is a stretch of bytes inside a position that was already written.
        That only works if something says, in a file which outlives this program,
        which position answers for which piece. This writes that file, and
        :meth:`inspect` reads it back and follows it.

        **The order of the stored positions is the draw order.** Positions are
        listed as they were first committed, so a later arrival is drawn over
        an earlier one wherever their whole frames cover the same ground.
        Positions that are being routed ahead of their own commit — the
        candidate a publication is about to make visible — go at the tail, in
        the layout's own settled order, which is where a brand-new arrival
        belongs.

        Building the map is also the moment the arrangement gets checked.
        :func:`zmart_live.viewroute.route_the_view` refuses a set of positions
        that were not all written the same way, one that does not land on whole
        pieces, or one asked for ground it does not hold.
        """
        showing_set = {
            position_id for position_id, _ in self._as_position_moments(committed)
        }
        showing = [
            position_id
            for position_id in self._positions_in_commit_order()
            if position_id in showing_set
        ]
        showing += [
            placement.position_id
            for placement in self.layout.positions
            if placement.position_id in showing_set
            and placement.position_id not in showing
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
        _write_and_replace(
            target,
            json.dumps(
                {
                    "schema": _LINKS_SCHEMA,
                    "run_id": self.run_id,
                    "profile_id": self.profile.profile_id,
                    "scene_layout_revision": self.layout.revision,
                    "position_generations": {
                        position_id: self.generations.get(position_id, 0)
                        for position_id in showing
                    },
                    "created_at": now_in_words(),
                    "levels": levels,
                },
                indent=2,
            ),
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
        about_the_layout: list[str] = []

        moment = 0 if timepoint is None else timepoint
        pieces_read = self._read_every_piece(position_id, moment, about_pixels)
        ranges = self._resolve_every_pointer(position_id, about_pointers)
        ranges += self._follow_the_stored_pointers(position_id, moment, about_pointers)
        validated = self._check_the_view_description(about_the_picture)
        layout_ok = self._layout_reads_back(about_the_layout)

        return Inspection(
            position_id=position_id,
            timepoint=timepoint,
            pyramids_ready=pieces_read > 0 and not about_pixels,
            links_ready=ranges > 0 and not about_pointers,
            view_ready=validated > 0 and not about_the_picture,
            layout_ready=layout_ok and not about_the_layout,
            pieces_read=pieces_read,
            ranges_checked=ranges,
            view_levels_validated=validated,
            complaints=tuple(
                about_pixels
                + about_pointers
                + about_the_picture
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
        """Ask the route for each piece this position is drawn at, and weigh the answer.

        A position's whole frame is routed, but not every piece of it is
        necessarily *drawn*: a position committed later may cover part of this
        one's ground, and there the picture rightly shows the later arrival.
        What is checked is therefore exactly what a viewer would be served —
        every piece where this position is the newest claim resolves to this
        position's own bytes, byte for byte. Pieces a newer arrival has taken
        over are its business, and were checked when it was published.

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
                        claims = route.claims_on(wanted)
                        if not claims:
                            complaints.append(
                                f"The overview has nothing to hand over for piece "
                                f"{wanted} of level {level_number}, although "
                                f"'{position_id}' is meant to supply it. A viewer "
                                f"would draw empty ground there."
                            )
                            return served
                        if claims[0].position != path:
                            # A position committed later covers this ground, so
                            # the picture rightly draws it instead of us.
                            continue
                        answer = claims[0].serving()
                        if answer is None:
                            complaints.append(
                                f"The overview has nothing to hand over for piece "
                                f"{wanted} of level {level_number}, although "
                                f"'{position_id}' is meant to supply it. A viewer "
                                f"would draw empty ground there."
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

    def _check_the_view_description(self, complaints: list[str]) -> int:
        """Confirm the linked view is metadata-only and byte-compatible.

        The pointer check already follows and decodes every canonical chunk this
        position supplies. This separate check proves that the virtual arrays
        advertise exactly that encoding and contain no copied payload tree which
        could become a stale second source of truth.
        """
        if not self.view_store.exists():
            complaints.append(
                "The linked virtual view has not been described yet, so the "
                "position would be complete in its own store and unreachable "
                "through the run-wide picture."
            )
            return 0
        checked = 0
        try:
            stored = self._read_the_link_map()
            described = {
                int(item["level"]): item for item in stored.get("levels", ())
            }
            for level in self._strict_zero_copy_levels():
                entry = described.get(level.level)
                if entry is None:
                    complaints.append(
                        f"The linked virtual view has no route for level "
                        f"{level.level}."
                    )
                    continue
                path = self.view_level(level.level)
                if (path / "c").exists():
                    complaints.append(
                        f"Level {level.level} of the linked view contains copied "
                        "chunks. A zero-copy view may contain metadata and routes "
                        "only."
                    )
                    continue
                route = route_the_view(
                    [
                        Placed(
                            array=self.folder / item["array"],
                            lands_at=tuple(item["lands_at"]),
                            taken_from=tuple(item["taken_from"]),
                            size=tuple(item["size"]),
                        )
                        for item in entry.get("positions", ())
                    ],
                    view_shape=tuple(entry["view_shape"]),
                )
                refuse_a_view_stored_differently(path, route)
                checked += 1
        except Exception as trouble:
            complaints.append(f"The linked virtual view could not be checked: {trouble}")
        return checked

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
        # The kind belongs to the position's history, not to how the call was
        # spelled: a position's first commit is its arrival whichever moment it
        # names, and only a position the record already knows can gain a moment.
        # Chosen from the durable record rather than remembered, for the same
        # reason as _committed_units itself.
        already_published = any(
            position == position_id for position, _ in self._committed_units()
        )
        if superseding:
            kind = "position_replaced"
        elif already_published and timepoint is not None:
            kind = "timepoint_committed"
        else:
            kind = "position_committed"
        event = CommitEvent(
            revision=self.manifest.next_revision(),
            event_type=kind,
            position_id=position_id,
            run_id=self.run_id,
            acquisition_type=self.profile.acquisition_type,
            acquisition_profile_id=self.profile.profile_id,
            scene_layout_revision=self.layout.revision,
            link_revision=self.layout.revision,
            position_generation=self.generations.get(position_id, 0),
            timepoint=timepoint,
            component_id=placement.component_id,
            cell=placement.cell,
            channels=self.channels,
            levels=tuple(level.level for level in self.profile.levels),
            pyramids_ready=found.pyramids_ready,
            links_ready=found.links_ready,
            view_ready=found.view_ready,
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

        Pixels and their zoomed-out copies come first, followed by the complete
        virtual routes and metadata for both views, the arrangement, and one
        commit. Doing these in another order can expose an unfinished answer.
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
        Both virtual route sets are then refreshed for the new generation and
        the change is published as its own revision, so the views move together
        and an earlier revision goes on meaning what it meant.

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
        except BaseException as failure:
            # Nothing was published, so the run goes back to the generation it was
            # reading a moment ago rather than being left pointing at a half
            # written one.
            if was:
                self.generations[position_id] = was
            else:
                self.generations.pop(position_id, None)
            try:
                self._restore_shared_state_after_failed_replacement(
                    position_id, timepoint
                )
            except BaseException as recovery_failure:
                raise ZmartLiveError(
                    f"Replacing moment {timepoint} of {position_id!r} failed "
                    f"({failure!r}), and restoring its previously published "
                    f"shared views also failed ({recovery_failure!r}). The gateway "
                    "continues to fail closed, but this run needs operator "
                    "attention before acquisition resumes."
                ) from recovery_failure
            raise

    def _restore_shared_state_after_failed_replacement(
        self, position_id: str, timepoint: int
    ) -> None:
        """Put the last committed generation back after a candidate aborts.

        The candidate link map deliberately withholds the position while the
        metadata-only view description is refreshed. Recovery regenerates that
        description from the last committed units and restores the old map. A
        reader therefore sees the old committed bytes or a temporary refusal,
        never the failed candidate.
        """
        del position_id, timepoint
        self.write_the_view()
        self.write_the_link_map(frozenset(self._committed_units()))

    def _rebuild_everything_shared_and_publish(
        self,
        position_id: str,
        *,
        timepoint: int | None = None,
        superseding: bool = False,
    ) -> CommitEvent:
        """Refresh the virtual view from committed units, then commit once."""
        moment = 0 if timepoint is None else timepoint
        units = frozenset(self._committed_units()) | {(position_id, moment)}
        # Write the candidate route map first. For a replacement, this makes
        # the gateway withhold that position while metadata points at the new
        # generation. The manifest commit later makes it visible in one step.
        self.write_the_link_map(units)
        self.write_the_view()
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

    from zmart_storage.canvas import rmtree_despite_brief_holds

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
    # The scratch folder is removed with the same brief-hold patience as every
    # other delete on a machine whose endpoint protection glances at fresh
    # files: this check runs on the path of every commit, and one glance at the
    # scratch image must not refuse a perfectly sound position.
    scratch = tempfile.mkdtemp()
    try:
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
    finally:
        rmtree_despite_brief_holds(scratch)
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

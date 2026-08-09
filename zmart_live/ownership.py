"""Deciding which tile owns which piece of specimen.

When a mosaic is imaged, neighbouring tiles deliberately share a strip of
specimen. That overlap is not waste: a stitcher needs it later as evidence of
where the stage really went, and a model looking at an object near a tile's edge
needs it as context. But it does create a question that has to be answered
exactly once, and answered the same way by everybody.

**If two tiles both photographed the same piece of specimen, which one counts?**

Get it wrong in one direction and a nucleus sitting in the overlap is counted
twice. Get it wrong in the other and a stripe of specimen belongs to nobody and
quietly disappears from the results. Neither shows up as an error; both show up
as a number that is simply wrong.

This module answers that question, in advance, from the grid alone.

Two different answers, on purpose
---------------------------------

The question is asked twice, for two different reasons, and the right answers are
not the same.

**Which tile's pixels are shown** in the seamless overview. This wants to fall on
a boundary the file can be cut along, so that the overview can point at the
tile's own bytes instead of copying them.

**Which tile's measurements count.** This wants to fall where both neighbours
have specimen on either side of it, so that a model judging an object near the
line has context in both directions. That is usually the middle of the overlap,
which is a terrible place to cut a file and a fine place to divide
responsibility.

Keeping them apart costs nothing — they are two recorded numbers rather than one
— and forcing them together would compromise both.

Why the lower and right neighbour wins
--------------------------------------

The obvious rule is that the first tile keeps its whole image and each later one
gives up the strip on its left and top. It reads naturally, and it was the first
thing written down.

Measuring it against the real writer showed it to be the expensive choice. Under
that rule every interior tile is taken from an offset of one overlap into its own
store, and that offset is the smallest number in the whole arrangement, so it is
what limits how far the overview can point rather than copy.

Describing exactly the same seams from the other side — **every tile gives up its
lower and right strip, so every tile contributes its first ``step`` pixels** —
makes that offset zero for every tile alike. On a 3×3 mosaic of 2304 pixel frames
that took the number of zoom levels the overview could point at from one to four.
A level it cannot point at has to be built by reading every tile back and writing
new pixels *during the acquisition*, so this is the difference between an
overview that costs almost nothing and one that writes a third of the run again.

It is also the simpler rule. Every tile is treated identically: taken from its
own corner, trimmed to one step, landing at its place in the grid. There is no
first-tile special case, no neighbour lookup, and no dependence on the order the
tiles happen to arrive in.

The two rules cover the mosaic identically. Every output pixel still has exactly
one owner; the seams simply sit one overlap-width over.

What it costs, said plainly
---------------------------

Trimming every tile alike leaves the mosaic's far edge uncovered — the last
column's right strip and the last row's bottom strip. Those are written rather
than pointed at. On a ten-by-ten mosaic that is a few tens of megabytes against a
run of hundreds of gigabytes, and :func:`the_far_edges` says exactly which
strips they are so nobody has to work it out again.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import (
    AcquisitionProfile,
    Box,
    GridCell,
    Interval,
    MosaicComponent,
    PositionPlacement,
    ZmartLiveError,
    check_the_name_is_safe,
)

__all__ = [
    "TopologyRefused",
    "the_far_edges",
    "place_the_tiles",
    "plan_one_tile",
    "check_the_grid_holds_together",
]


class TopologyRefused(ZmartLiveError):
    """The tiles do not form the connected mosaic they claim to.

    Refusing is the point. A tile inserted into a grid it does not really belong
    to would be cropped against neighbours it never touched, which produces a
    picture with a stripe of the wrong specimen in it and no error anywhere. The
    position itself is never lost — it remains perfectly good data, and can stand
    as its own component or be handed to a stitcher — it simply does not enter
    the seamless overview.
    """


# ---------------------------------------------------------------------------
# Where one tile sits, and which parts of it are its own
# ---------------------------------------------------------------------------


def _step_on(profile: AcquisitionProfile, axis: str) -> int:
    """How far the stage moves between neighbouring tiles: the frame less the overlap."""
    return profile.grid_step(axis)


def _cell_index(cell: GridCell, axis: str) -> int:
    """Which row or column a cell sits in, for the axis being considered."""
    return cell.row if axis == "y" else cell.column


def _check_the_cell_is_a_forward_grid_index(cell: GridCell) -> None:
    """Keep external grid coordinates out of Python's negative-slice semantics."""
    coordinates = (cell.row, cell.column)
    if any(
        not isinstance(index, int) or isinstance(index, bool) or index < 0
        for index in coordinates
    ):
        raise TopologyRefused(
            f"Grid cells are non-negative whole-number row/column indexes from "
            f"the mosaic's top-left corner; got row {cell.row!r}, column "
            f"{cell.column!r}. A negative origin would be interpreted as a slice "
            "from the far edge of a Zarr array and put the tile in the wrong place."
        )


def plan_one_tile(
    profile: AcquisitionProfile,
    cell: GridCell,
    *,
    component_id: str = "component-0",
    position_id: str | None = None,
    occupied: frozenset[GridCell] | None = None,
    keep_the_far_edge: bool = False,
) -> PositionPlacement:
    """Work out where one tile sits and which parts of it are its responsibility.

    Everything is in the tile's own pixels at full resolution, so ``(0, 0)`` is
    that tile's own corner rather than the run's. ``origin`` says where the tile
    sits in the run's shared coordinates, which is what turns one into the other.

    ``keep_the_far_edge`` applies to a tile with no neighbour beyond it. Left
    alone, every tile is trimmed identically, which is what keeps the overview
    cheap; the uncovered strip at the mosaic's far edge is written instead. Set
    it and the edge tiles keep their whole frame, which covers the mosaic
    completely from pointers alone but makes those tiles line up less well, so
    the overview cannot point as deeply. :func:`the_far_edges` reports the strips
    the default leaves behind.
    """
    _check_the_cell_is_a_forward_grid_index(cell)
    tiled = profile.tiled_axes
    if not tiled:
        raise ZmartLiveError(
            f"The '{profile.acquisition_type}' plan declares no overlapping axes, "
            f"so its positions do not form a mosaic and there is no seam to place. "
            f"Independent positions do not use this."
        )

    occupied = occupied or frozenset({cell})
    origin: dict[str, int] = {}
    shown: dict[str, Interval] = {}
    looked_at: dict[str, Interval] = {}
    counted: dict[str, Interval] = {}
    neighbours: dict[str, str] = {}
    outermost: dict[str, bool] = {}

    for axis in tiled:
        frame = profile.frame_shape[axis]
        overlap = profile.overlap_pixels.get(axis, 0)
        step = _step_on(profile, axis)
        index = _cell_index(cell, axis)

        origin[axis] = index * step

        # Is there a tile beyond this one on this axis? If not, this tile is on
        # the mosaic's outer edge and there is nobody to hand the strip to.
        beyond = (
            GridCell(cell.row + 1, cell.column)
            if axis == "y"
            else GridCell(cell.row, cell.column + 1)
        )
        before = (
            GridCell(cell.row - 1, cell.column)
            if axis == "y"
            else GridCell(cell.row, cell.column - 1)
        )
        has_one_beyond = beyond in occupied
        has_one_before = before in occupied
        outermost[f"{axis}_high"] = not has_one_beyond
        outermost[f"{axis}_low"] = not has_one_before
        if has_one_beyond:
            neighbours[f"{axis}_high"] = f"{component_id}:{beyond.row},{beyond.column}"
        if has_one_before:
            neighbours[f"{axis}_low"] = f"{component_id}:{before.row},{before.column}"

        # What the overview shows. Every tile gives up its far strip, uniformly,
        # which is what keeps the numbers lined up. A tile with nothing beyond it
        # may keep its whole frame if the caller asked for that.
        if has_one_beyond or not keep_the_far_edge:
            shown[axis] = Interval(0, step)
        else:
            shown[axis] = Interval(0, frame)

        # What a model is given: the whole tile, overlap included. The overlap is
        # the context that lets it judge an object sitting near the edge.
        looked_at[axis] = Interval(0, frame)

        # Whose measurements count. Placed in the middle of the overlap wherever
        # there is a neighbour, so that both sides have specimen either way. An
        # odd overlap cannot be halved exactly, and the extra pixel always goes to
        # the lower-numbered tile so that the two neighbours never disagree.
        half_before = overlap // 2 if has_one_before else 0
        half_beyond = (overlap - overlap // 2) if has_one_beyond else 0
        counted[axis] = Interval(half_before, frame - half_beyond)

    # Axes that are not tiled -- colour, depth, time -- are not divided at all.
    # A tile owns everything it recorded on those, and saying so explicitly stops
    # anybody inferring an ownership rule where none exists.
    for axis in profile.axes:
        if axis in tiled or axis not in profile.frame_shape:
            continue
        whole = Interval(0, profile.frame_shape[axis])
        shown[axis] = whole
        looked_at[axis] = whole
        counted[axis] = whole
        origin[axis] = 0

    return PositionPlacement(
        position_id=position_id or f"{component_id}:{cell.row},{cell.column}",
        component_id=component_id,
        cell=cell,
        origin=origin,
        visual_source_roi=Box.of(**shown),
        analysis_input_roi=Box.of(**looked_at),
        analysis_core_roi=Box.of(**counted),
        neighbours=neighbours,
        on_outer_boundary=outermost,
    )


def place_the_tiles(
    profile: AcquisitionProfile,
    cells: dict[GridCell, str],
    *,
    component_id: str = "component-0",
    keep_the_far_edge: bool = False,
) -> tuple[PositionPlacement, ...]:
    """Work out the placement of every tile in one mosaic component.

    ``cells`` maps each occupied grid square to the name of the position sitting
    there. The result is in a settled order, so that two runs given the same
    mosaic produce the same list and can be compared.

    The arrangement is worked out from the grid alone. The order the tiles
    happened to be acquired in never enters into it, which is what makes the
    answer the same whether a run finished tidily or was interrupted and resumed.
    """
    component = check_the_grid_holds_together(
        cells,
        component_id=component_id,
        profile_id=profile.profile_id,
    )
    if not component.complete:
        raise TopologyRefused(
            f"Mosaic component '{component_id}' is incomplete: one or more cells "
            "inside its planned rectangular footprint are missing. Treating those "
            "missing cells as outer boundaries would make diagonal neighbours own "
            "the same specimen twice. Keep the complete planned footprint until "
            "those positions arrive, or describe an intentional irregular boundary "
            "with a future explicit boundary model; this box-shaped ownership "
            "format cannot represent it safely."
        )

    occupied = frozenset(cells)
    return tuple(
        plan_one_tile(
            profile,
            cell,
            component_id=component_id,
            position_id=cells[cell],
            occupied=occupied,
            keep_the_far_edge=keep_the_far_edge,
        )
        for cell in sorted(cells)
    )


# ---------------------------------------------------------------------------
# What the uniform trim leaves behind
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FarEdge:
    """A strip at the mosaic's outer edge that no tile hands over.

    Trimming every tile alike is what keeps the overview cheap, and the price is
    that the last row and last column each leave a strip uncovered. These are
    written rather than pointed at. They are small — one overlap wide, along one
    side of the mosaic — and naming them here means nobody has to rediscover
    which pixels are missing when the overview turns out to stop slightly short.
    """

    axis: str
    position_id: str
    cell: GridCell
    taken_from: Interval
    lands_at: Interval

    @property
    def width(self) -> int:
        """How many pixels wide the strip is."""
        return self.taken_from.length


def the_far_edges(
    profile: AcquisitionProfile,
    placements: tuple[PositionPlacement, ...],
) -> tuple[FarEdge, ...]:
    """The strips left uncovered by trimming every tile the same way.

    Returns nothing when the placements were made with ``keep_the_far_edge``,
    because in that case the edge tiles already cover them.
    """
    edges: list[FarEdge] = []
    for placement in placements:
        for axis in profile.tiled_axes:
            if not placement.on_outer_boundary.get(f"{axis}_high"):
                continue
            frame = profile.frame_shape[axis]
            shown = placement.visual_source_roi[axis]
            if shown.stop >= frame:
                continue  # this tile already keeps its edge
            start = placement.origin[axis] + shown.stop
            edges.append(
                FarEdge(
                    axis=axis,
                    position_id=placement.position_id,
                    cell=placement.cell,
                    taken_from=Interval(shown.stop, frame),
                    lands_at=Interval(start, start + (frame - shown.stop)),
                )
            )
    return tuple(edges)


# ---------------------------------------------------------------------------
# Does this really form one connected mosaic?
# ---------------------------------------------------------------------------


def check_the_grid_holds_together(
    cells: dict[GridCell, str],
    *,
    component_id: str = "component-0",
    profile_id: str = "",
) -> MosaicComponent:
    """Refuse anything that is not genuinely one connected mosaic.

    The seam rule takes its answers from the grid, so the grid has to mean what
    it says. Four things are refused here, and each corresponds to a way a
    plausible-looking picture can come out wrong:

    **Two positions in one square.** They would both claim the same specimen, and
    which one you saw would depend on which was written last.

    **A tile touching only at a corner.** Two tiles meeting diagonally share no
    edge, so neither can be trimmed against the other, and a mosaic held together
    only by corners is not one mosaic.

    **A tile with no neighbour at all.** It is perfectly good data, but it is its
    own separate patch, and pretending otherwise would place it against tiles it
    never touched.

    **A hole in the middle.** A square nobody imaged, surrounded by squares
    somebody did, is reported rather than quietly treated as an outer edge — the
    difference matters, because an outer edge keeps its full frame while a hole
    means the run is not finished.

    Returns the component when everything holds. Raises :class:`TopologyRefused`
    otherwise, saying which square is at fault.
    """
    if not cells:
        raise TopologyRefused(
            f"Mosaic component '{component_id}' has no tiles in it, so there is "
            f"nothing to check and nothing to show."
        )

    seen_on_disk: dict[str, tuple[str, GridCell]] = {}
    for cell, position_id in sorted(cells.items()):
        _check_the_cell_is_a_forward_grid_index(cell)
        check_the_name_is_safe(position_id, what="position")
        disk_name = position_id.casefold()
        if disk_name in seen_on_disk:
            first_name, first_cell = seen_on_disk[disk_name]
            if first_name == position_id:
                raise TopologyRefused(
                    f"Position {position_id!r} is placed at both row "
                    f"{first_cell.row}, column {first_cell.column} and row "
                    f"{cell.row}, column {cell.column}. A position sits in one "
                    "square; putting it in two would claim the same specimen twice."
                )
            raise TopologyRefused(
                f"Positions {first_name!r} at row {first_cell.row}, column "
                f"{first_cell.column} and {position_id!r} at row {cell.row}, "
                f"column {cell.column} differ only by letter case. They are one "
                "folder on the case-insensitive Windows filesystems used by "
                "microscope computers, so one position would overwrite the other."
            )
        seen_on_disk[disk_name] = (position_id, cell)

    # Walk outwards from one square, stepping only between edge neighbours.
    # Anything the walk cannot reach is not joined on, whatever its coordinates
    # suggest.
    occupied = set(cells)
    start = min(occupied)
    reached = {start}
    still_to_visit = [start]
    while still_to_visit:
        here = still_to_visit.pop()
        for neighbour in here.neighbours():
            if neighbour in occupied and neighbour not in reached:
                reached.add(neighbour)
                still_to_visit.append(neighbour)

    if reached != occupied:
        stranded = sorted(occupied - reached)[0]
        touching_a_corner = any(
            GridCell(stranded.row + dr, stranded.column + dc) in reached
            for dr, dc in ((-1, -1), (-1, 1), (1, -1), (1, 1))
        )
        why = (
            "It touches the rest of the mosaic only at a corner, and two tiles "
            "meeting at a corner share no edge, so neither can be trimmed against "
            "the other."
            if touching_a_corner
            else "Nothing beside it has been imaged, so it is a separate patch "
            "rather than part of this mosaic."
        )
        raise TopologyRefused(
            f"The tile at row {stranded.row}, column {stranded.column} is not "
            f"joined to mosaic component '{component_id}'. {why} It remains "
            f"perfectly good data and can be its own component; it simply cannot "
            f"be cropped against tiles it never met."
        )

    rows = [cell.row for cell in occupied]
    columns = [cell.column for cell in occupied]
    holes = [
        GridCell(row, column)
        for row in range(min(rows), max(rows) + 1)
        for column in range(min(columns), max(columns) + 1)
        if GridCell(row, column) not in occupied
    ]

    return MosaicComponent(
        component_id=component_id,
        profile_id=profile_id,
        cells=dict(cells),
        complete=not holes,
    )

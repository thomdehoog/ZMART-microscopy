"""Deciding which tile's measurements count, and whether the grid holds together.

When a mosaic is imaged, neighbouring tiles deliberately share a strip of
specimen. That overlap is not waste: a stitcher needs it later as evidence of
where the stage really went, and a model looking at an object near a tile's edge
needs it as context.

The **picture** needs no ownership rule any more. Positions are routed whole
into the one linked view, overlap intact, and where two of them cover the same
ground the one committed later is simply drawn on top — the settled model of
``docs/design/positions-in-a-container.md``. What still has to be answered
exactly once, and answered the same way by everybody, is the **analysis**
question:

**If two tiles both photographed the same piece of specimen, which one counts?**

Get it wrong in one direction and a nucleus sitting in the overlap is counted
twice. Get it wrong in the other and a stripe of specimen belongs to nobody and
quietly disappears from the results. Neither shows up as an error; both show up
as a number that is simply wrong.

This module answers that question, in advance, from the grid alone. The
boundary is placed in the middle of the overlap wherever a neighbour exists, so
that a model judging an object near the line has specimen on both sides of it —
and the model is still *given* the whole tile, overlap included, because the
overlap is the context that lets it judge an object sitting near the edge.
"""

from __future__ import annotations

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


def _shared_along(profile: AcquisitionProfile, axis: str,
                  mine: dict[str, int], theirs: dict[str, int]) -> int:
    """How much ground two positions share along one axis, in pixels.

    Nought where they do not reach each other. Both origins are in the run's
    own pixels, so this is plain arithmetic on two intervals.
    """
    frame = profile.frame_shape[axis]
    low = max(mine[axis], theirs[axis])
    high = min(mine[axis] + frame, theirs[axis] + frame)
    return max(0, high - low)


def _touching(profile: AcquisitionProfile, tiled: tuple[str, ...],
              mine: dict[str, int], theirs: dict[str, int]) -> bool:
    """Do these two positions actually share ground?

    Every tiled axis has to overlap. Two tiles that meet along one axis while
    sitting clear of one another along the next are not neighbours at all --
    they share no specimen, and neither has anything to hand over.
    """
    return all(_shared_along(profile, axis, mine, theirs) > 0 for axis in tiled)


def plan_one_position(
    profile: AcquisitionProfile,
    *,
    position_id: str,
    origin: dict[str, int],
    others: dict[str, dict[str, int]],
    component_id: str = "component-0",
    cell: GridCell | None = None,
) -> PositionPlacement:
    """Work out where one position sits and which parts of it are its own.

    This is the general act, and :func:`plan_one_tile` is the special case of
    it where the place comes from a grid square. A position has a **place** --
    ``origin``, in the run's own pixels -- and everything else follows from
    the places the positions actually occupy rather than from any pattern they
    may or may not form.

    That distinction is the whole point. A stage doing a survey steps a fixed
    distance and its positions do form a grid, which is why the grid road
    exists and stays. But a dataset from anywhere else sits where it sits, and
    a live path that could only place tiles it had itself arranged could never
    rehearse one -- which is what a replay is for.

    ``others`` is where every other position of the component sits, so that
    neighbours are found by asking which of them actually reach this one.
    Nothing depends on the order positions arrived in, so a run interrupted
    and resumed plans exactly as one that finished tidily.
    """
    # Where this position sits is said by its origin; which axes have a SEAM to
    # divide is a separate question, and the two were previously the same one.
    # A run whose positions do not touch at all declares no overlap, and used to
    # be refused here -- but it still has places, and a picture is still made of
    # it. So placement works along whatever axes the position has a place on,
    # and only the axes with a declared seam are ever divided.
    laid_out = tuple(axis for axis in origin)
    tiled = tuple(axis for axis in profile.tiled_axes if axis in laid_out)

    looked_at: dict[str, Interval] = {}
    counted: dict[str, Interval] = {}
    neighbours: dict[str, str] = {}
    outermost: dict[str, bool] = {}

    beside = {name: where for name, where in others.items()
              if name != position_id and _touching(profile, laid_out, origin, where)}

    for axis in laid_out:
        frame = profile.frame_shape[axis]

        # Who reaches this position from each side along this axis, and how far
        # in. Taken from where the positions are rather than from a pattern, so
        # an arrangement nobody laid out reads the same as one somebody did.
        before = {name: _shared_along(profile, axis, origin, where)
                  for name, where in beside.items() if where[axis] < origin[axis]}
        beyond = {name: _shared_along(profile, axis, origin, where)
                  for name, where in beside.items() if where[axis] > origin[axis]}

        outermost[f"{axis}_low"] = not before
        outermost[f"{axis}_high"] = not beyond

        # Which of them to name as THE neighbour on this side, when more than
        # one reaches in. Settled rather than left to chance: the one sharing
        # most ground, then the one squarely along this axis rather than a
        # corner-on one, then by name. On a grid that is always the tile next
        # door -- the diagonal one shares the same amount and would otherwise
        # win on a coin toss, and two runs given the same mosaic have to
        # produce the same answer.
        def _pick(candidates: dict[str, int], _axis: str = axis) -> str:
            def order(one: str) -> tuple:
                askew = sum(1 for other in laid_out
                            if beside[one][other] != origin[other])
                return (-candidates[one], askew, one)
            return min(candidates, key=order)

        if before:
            neighbours[f"{axis}_low"] = _pick(before)
        if beyond:
            neighbours[f"{axis}_high"] = _pick(beyond)

        # What a model is given: the whole position, overlap included. The
        # overlap is not waste here; it is the context that lets it judge an
        # object sitting near the edge.
        looked_at[axis] = Interval(0, frame)

        if axis not in tiled:
            # No seam declared along this axis, so nothing to divide: this
            # position counts everything it recorded on it.
            counted[axis] = Interval(0, frame)
            continue

        # Whose measurements count. The boundary sits in the middle of the
        # ground actually shared, so that both sides have specimen either way.
        # A shared strip of an odd width cannot be halved exactly, and the
        # extra pixel always goes to the position nearer the run's origin, so
        # that two neighbours never disagree about it.
        share_low = max(before.values(), default=0)
        share_high = max(beyond.values(), default=0)
        counted[axis] = Interval(share_low // 2,
                                 frame - (share_high - share_high // 2))

    # Axes that are not tiled -- colour, depth, time -- are not divided at all.
    # A position owns everything it recorded on those, and saying so explicitly
    # stops anybody inferring an ownership rule where none exists.
    whole_origin = dict(origin)
    for axis in profile.axes:
        if axis in laid_out or axis not in profile.frame_shape:
            continue
        whole = Interval(0, profile.frame_shape[axis])
        looked_at[axis] = whole
        counted[axis] = whole
        whole_origin[axis] = 0

    return PositionPlacement(
        position_id=position_id,
        component_id=component_id,
        cell=cell,
        origin=whole_origin,
        analysis_input_roi=Box.of(**looked_at),
        analysis_core_roi=Box.of(**counted),
        neighbours=neighbours,
        on_outer_boundary=outermost,
    )


def plan_one_tile(
    profile: AcquisitionProfile,
    cell: GridCell,
    *,
    component_id: str = "component-0",
    position_id: str | None = None,
    occupied: frozenset[GridCell] | None = None,
) -> PositionPlacement:
    """Work out where one tile sits and which parts of it are its responsibility.

    Everything is in the tile's own pixels at full resolution, so ``(0, 0)`` is
    that tile's own corner rather than the run's. ``origin`` says where the tile
    sits in the run's shared coordinates, which is what turns one into the other.
    The picture shows the tile whole — there is no visual trimming to record —
    so what is worked out here is where the tile lands and where the boundary
    for *counting* its measurements sits.
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

    def named(one: GridCell) -> str:
        return f"{component_id}:{one.row},{one.column}"

    def placed(one: GridCell) -> dict[str, int]:
        return {axis: _cell_index(one, axis) * _step_on(profile, axis)
                for axis in tiled}

    return plan_one_position(
        profile,
        position_id=position_id or named(cell),
        origin=placed(cell),
        others={named(one): placed(one) for one in occupied if one != cell},
        component_id=component_id,
        cell=cell,
    )


def place_the_positions(
    profile: AcquisitionProfile,
    origins: dict[str, dict[str, int]],
    *,
    cells: dict[str, GridCell] | None = None,
    component_id: str = "component-0",
) -> tuple[PositionPlacement, ...]:
    """Work out the placement of every position of one mosaic component.

    ``origins`` says where each position sits, in the run's own pixels. That
    is all this needs: an arrangement somebody laid out on a grid and one that
    nobody arranged at all are the same problem here, and are answered the
    same way.

    ``cells`` optionally says which grid square each position occupies, which
    a survey knows and a transfer does not. It is carried through as a label
    and decides nothing.

    The result is in a settled order -- by where each position sits, then by
    name -- so that two runs given the same mosaic produce the same list and
    can be compared. The order the positions happened to be acquired in never
    enters into it, which is what makes the answer the same whether a run
    finished tidily or was interrupted and resumed.
    """
    cells = cells or {}
    ordered = sorted(
        origins,
        key=lambda name: (tuple(sorted(origins[name].items())), name),
    )
    return tuple(
        plan_one_position(
            profile,
            position_id=name,
            origin=origins[name],
            others={other: where for other, where in origins.items()
                    if other != name},
            component_id=component_id,
            cell=cells.get(name),
        )
        for name in ordered
    )


def places_on_a_grid(
    profile: AcquisitionProfile, cells: dict[GridCell, str],
) -> dict[str, dict[str, int]]:
    """Where each of these grid squares puts its position, in run pixels.

    This is the whole of what a grid is: a way of choosing places. A survey
    steps a fixed distance and its squares turn into places here; everything
    after this point works from the places and never asks how they were
    chosen.
    """
    tiled = profile.tiled_axes
    return {
        name: {axis: _cell_index(cell, axis) * _step_on(profile, axis)
               for axis in tiled}
        for cell, name in cells.items()
    }


def place_the_tiles(
    profile: AcquisitionProfile,
    cells: dict[GridCell, str],
    *,
    component_id: str = "component-0",
) -> tuple[PositionPlacement, ...]:
    """Work out the placement of every tile in one mosaic component.

    ``cells`` maps each occupied grid square to the name of the position
    sitting there. The squares are turned into places and the work is done by
    :func:`place_the_positions`, so a survey and a dataset from anywhere else
    travel exactly the same road from here on.

    The completeness check stays with the grid, where it belongs: it is a
    statement about a planned rectangular footprint, and a run that was never
    laid out in a rectangle has no footprint to be missing anything from.
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
    return place_the_positions(
        profile,
        places_on_a_grid(profile, cells),
        cells={name: cell for cell, name in cells.items()},
        component_id=component_id,
    )


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

"""Relive a finished dataset as a live run, one position at a time.

Opening a dataset shows all of it at once. A *replay* hands the same positions
to the very doorway the microscope uses -- the live writer, with its sealed
profile, its manifest, and one commit per position -- so the picture assembles
on screen tile by tile, exactly as it would during an acquisition. Nothing
about the live path is faked, and that is the whole point: a replay is a dress
rehearsal for smart microscopy that runs on data already on disk, with no
microscope in the room.

The live writer places tiles on a regular grid: every position sits a fixed
step from its neighbours, and the step is the camera frame minus the overlap.
A replay therefore has to *reproduce the dataset's own spacing*. The plan
below reads the dataset's geometry (through the same mosaic reader the scene
builder uses), works out the spacing the tiles actually sit at, and asks the
live planner for a profile with exactly that spacing. A dataset whose tiles
sit at uneven offsets cannot be placed on any grid and is refused in plain
words; so is one holding several moments in time. Both are their own later
chapters -- the refusals name them.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import zarr
from mosaic import read_the_transfer

from zmart_live.coordinator import LivePublisher
from zmart_live.model import GridCell
from zmart_live.profiles import DEFAULTS, plan_the_writing

# How much a tile's offset may miss its grid place, in micrometres, before the
# dataset is refused. Stages report positions to fractions of a micrometre;
# anything past a tenth of one is a genuinely different layout, not noise.
GRID_TOLERANCE_UM = 0.1


@dataclass(frozen=True)
class ReplayPlan:
    """Everything a replay needs, worked out once before the first beat."""

    profile: object
    geometry: object
    #: Which grid square each position occupies, by position name.
    cells: dict
    #: The positions in the order they will land: (name, level-0 array path,
    #: whether the tile's own axes carry a channel axis).
    beats: list
    z_planes: int
    channel_count: int

    @property
    def total(self) -> int:
        return len(self.beats)


def _spacing(offsets: list[float]) -> float | None:
    """The one step the offsets sit at, or None when there is no second tile."""
    distinct = sorted(set(offsets))
    if len(distinct) < 2:
        return None
    steps = [b - a for a, b in zip(distinct, distinct[1:], strict=False)]
    first = steps[0]
    for step in steps:
        if abs(step - first) > GRID_TOLERANCE_UM:
            raise ValueError(
                f"these positions do not sit on a regular grid: neighbouring "
                f"offsets differ by {first:.1f} and {step:.1f} micrometres. A "
                f"replay places tiles the way the microscope will -- a fixed "
                f"step apart -- so an unevenly spaced dataset cannot be "
                f"replayed. Open it instead, or rebuild it on a grid."
            )
    return first


def plan_a_replay(transfer: str | Path) -> ReplayPlan:
    """Map a dataset onto the live writer's grid, or say plainly why not.

    Reads the dataset with the same mosaic reader the scene builder uses, so
    whatever opens as a scene is understood here identically. Returns the
    sealed profile, the chosen geometry, and the beats in the order they will
    be published: top row first, left to right, the way a stage scans.
    """
    mosaic = read_the_transfer(Path(transfer))
    moments, _ = mosaic.frame_room
    if moments > 1:
        raise ValueError(
            f"this dataset keeps room for {moments} moments in time, and the "
            "replay of a timelapse is its own ordered chapter. Replay a "
            "single-moment dataset, or open this one instead."
        )

    has_channels = "c" in mosaic.axes
    first = mosaic.tiles[0].copies[0]
    # The spatial extent of one tile, by axis name rather than position, so a
    # tile with or without a channel axis reads the same way.
    spatial = dict(zip(("z", "y", "x"), first.shape[-3:], strict=True))
    voxel = dict(zip(("z", "y", "x"), first.voxel_um[-3:], strict=True))
    z_planes = spatial["z"]
    frame = (spatial["y"], spatial["x"])
    channel_count = first.shape[0] if has_channels else 1
    if frame[0] != frame[1]:
        raise ValueError(
            f"this dataset's frames are {frame[0]} by {frame[1]} pixels, and "
            "the replay of rectangular frames is its own chapter. Replay a "
            "square-framed dataset, or open this one instead."
        )

    corners = {tile.name: tile.copies[0].corner_um[-2:] for tile in mosaic.tiles}
    step_y = _spacing([corner[0] for corner in corners.values()])
    step_x = _spacing([corner[1] for corner in corners.values()])
    steps = {step for step in (step_y, step_x) if step is not None}
    if len(steps) > 1:
        raise ValueError(
            f"these positions step {step_y:.1f} micrometres down but "
            f"{step_x:.1f} across, and the live grid uses one step for both. "
            "A replay cannot reproduce that layout; open the dataset instead."
        )

    if steps:
        step_um = steps.pop()
        step_px = step_um / voxel["y"]
        overlap = (frame[0] - step_px) / frame[0]
        if overlap < 0:
            raise ValueError(
                f"these positions sit {step_um:.1f} micrometres apart but one "
                f"frame only spans {frame[0] * voxel['y']:.1f}, leaving gaps "
                "between tiles. The live grid lays tiles edge to edge or "
                "overlapping, so this dataset cannot be replayed."
            )
        defaults = DEFAULTS["overview"].with_overlap(overlap, overlap, overlap)
    else:
        # A single position has no neighbours, so any overlap will do and the
        # stock plan is the simplest true one.
        defaults = DEFAULTS["overview"]
        step_px = None

    channels = tuple(f"channel {index}" for index in range(channel_count))
    profile, geometry = plan_the_writing(
        "overview", frame=frame, dtype=mosaic.dtype, z_planes=z_planes,
        channels=channels, voxel_size=(voxel["z"], voxel["y"], voxel["x"]),
        readable_prefix="replay", defaults=defaults,
    )
    if step_px is not None and geometry.step_shape != (round(step_px),) * 2:
        raise ValueError(
            f"these positions sit {step_px:.0f} pixels apart, but the live "
            f"planner can only place this frame {geometry.step_shape[0]} "
            "pixels apart. The replay would draw the tiles somewhere the "
            "dataset does not put them, so it is refused; open the dataset "
            "instead."
        )

    step_for_cells = step_px if step_px is not None else float(frame[0])
    beats, cells = [], {}
    for tile in sorted(mosaic.tiles, key=lambda t: corners[t.name]):
        name = tile.name.removesuffix(".ome.zarr")
        corner = corners[tile.name]
        cell = GridCell(round(corner[0] / voxel["y"] / step_for_cells),
                        round(corner[1] / voxel["x"] / step_for_cells))
        misses = max(abs(corner[0] - cell.row * step_for_cells * voxel["y"]),
                     abs(corner[1] - cell.column * step_for_cells * voxel["x"]))
        if misses > GRID_TOLERANCE_UM:
            raise ValueError(
                f"position {tile.name} sits {misses:.1f} micrometres off the "
                "grid the other positions define, so the replay would draw it "
                "in the wrong place. Open the dataset instead."
            )
        cells[cell] = name
        beats.append((name, tile.copies[0].held_in, has_channels))

    return ReplayPlan(profile=profile, geometry=geometry, cells=cells,
                      beats=beats, z_planes=z_planes,
                      channel_count=channel_count)


def replay_the_dataset(transfer: str | Path, folder: str | Path, *,
                       every_s: float = 0.7, told=None, announce=None) -> Path:
    """Publish every position of the dataset through the live writer, paced.

    Args:
        transfer: the dataset -- one OME-Zarr per position.
        folder: where the replay's run is written. A run can only be lived
            once (its record only moves forward), so each replay wants a
            fresh folder.
        every_s: the pause between positions, so a watcher can see them land.
            The first position goes immediately.
        told: called as ``told(done, total)`` after each position, for a
            progress display.
        announce: called after each position, to tell open pages to look.

    Returns:
        The run's live view -- the one folder a viewer opens to watch.
    """
    plan = plan_a_replay(transfer)
    publisher = LivePublisher(Path(folder), plan.profile,
                              run_id=Path(transfer).name, cells=plan.cells)
    for number, (name, held_in, has_channels) in enumerate(plan.beats):
        if number and every_s:
            time.sleep(every_s)
        pixels = zarr.open_array(str(held_in), mode="r")[:]
        if not has_channels:
            pixels = pixels[None]
        publisher.write_and_publish(name, pixels, timepoint=0)
        if told:
            told(number + 1, plan.total)
        if announce:
            announce()
    return publisher.folder / "views" / "live" / "live.ome.zarr"

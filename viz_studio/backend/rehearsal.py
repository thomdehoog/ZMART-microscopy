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
words -- that is its own later chapter, and the refusal names it.

A timelapse replays the way it was acquired: every position of the first
moment, then every position of the next, sweep after sweep, so the time
slider grows on screen exactly as it would during the experiment.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import zarr
from mosaic import read_the_transfer, the_front_axes

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
    #: Where each position sits, by name, in the run's own pixels.
    positions: dict
    #: The publications in the order they will land: (name, level-0 array
    #: path, the store's own front axes, the moment to publish). A timelapse
    #: sweeps the whole grid once per moment.
    beats: list
    z_planes: int
    channel_count: int

    @property
    def total(self) -> int:
        return len(self.beats)


def _evenly_spaced(offsets: list[float]) -> bool:
    """Do these offsets sit a single fixed step apart?

    True where there is nothing to disagree about -- one distinct offset, or
    none -- because a run that never moves along an axis is evenly spaced
    along it in the only sense that matters.
    """
    distinct = sorted(set(offsets))
    if len(distinct) < 2:
        return True
    steps = [b - a for a, b in zip(distinct, distinct[1:], strict=False)]
    return all(abs(step - steps[0]) <= GRID_TOLERANCE_UM for step in steps)


def _the_one_step(offsets: list[float]) -> float | None:
    """The single step these offsets sit at, or None when there is not one.

    None covers both "there is no second tile to measure against" and "these
    are not evenly spaced". Neither is a fault: a run without a single step is
    replayed where its positions sit, and the step is only ever wanted to
    reproduce a survey's own spacing.
    """
    distinct = sorted(set(offsets))
    if len(distinct) < 2 or not _evenly_spaced(offsets):
        return None
    return distinct[1] - distinct[0]


def plan_a_replay(transfer: str | Path) -> ReplayPlan:
    """Map a dataset onto the live writer's grid, or say plainly why not.

    Reads the dataset with the same mosaic reader the scene builder uses, so
    whatever opens as a scene is understood here identically. Returns the
    sealed profile, the chosen geometry, and the beats in the order they will
    be published: top row first, left to right, the way a stage scans.
    """
    mosaic = read_the_transfer(Path(transfer))
    # How many moments and channels the dataset keeps, from the same rule
    # every reader of a store's front axes uses. The tile's own front axes
    # say how its array must be sliced per beat.
    moments, channel_count = mosaic.frame_room
    first = mosaic.tiles[0].copies[0]
    front = the_front_axes(first.outer_shape)
    # The spatial extent of one tile, by axis name rather than position, so a
    # tile with or without front axes reads the same way.
    spatial = dict(zip(("z", "y", "x"), first.shape[-3:], strict=True))
    voxel = dict(zip(("z", "y", "x"), first.voxel_um[-3:], strict=True))
    z_planes = spatial["z"]
    frame = (spatial["y"], spatial["x"])

    corners = {tile.name: tile.copies[0].corner_um[-2:] for tile in mosaic.tiles}
    down = [corner[0] for corner in corners.values()]
    across = [corner[1] for corner in corners.values()]
    # A survey's own spacing is reproduced, so that a replay of one is the
    # same run it was. A dataset that is NOT evenly spaced has no spacing to
    # reproduce, and asking for one anyway is how a lone tile 9 micrometres
    # down the specimen turned into a demand for a 97.5% overlap. So the step
    # is taken only when both directions agree there is one.
    on_a_grid = _evenly_spaced(down) and _evenly_spaced(across)
    steps_um = (_the_one_step(down) if on_a_grid else None,
                _the_one_step(across) if on_a_grid else None)
    # In pixels, each against its own axis. A frame is two numbers -- plenty of
    # cameras are longer one way than the other, a light sheet's routinely so
    # -- and the live geometry has always kept it that way, with its own
    # overlap along each. Only this planner used to ask for ONE number, and
    # refused a rectangle rather than guess which of the two it meant.
    steps_px = tuple(
        None if step is None else step / voxel[axis]
        for step, axis in zip(steps_um, ("y", "x"), strict=True)
    )

    shares = []
    for step, side, axis in zip(steps_px, frame, ("down", "across"), strict=True):
        if step is None:
            continue
        if step > side:
            raise ValueError(
                f"these positions sit {step * voxel['y']:.1f} micrometres apart "
                f"{axis} but one frame only spans {side * voxel['y']:.1f} that "
                "way, leaving gaps between tiles. The live grid lays tiles edge "
                "to edge or overlapping, so this dataset cannot be replayed."
            )
        shares.append((side - step) / side)

    if shares and max(shares) - min(shares) > 0.01:
        # The profile asks for ONE overlap band and applies it to both axes,
        # so a run overlapping a tenth one way and a third the other has no
        # single band to plan with. Said plainly rather than planned wrongly.
        raise ValueError(
            f"these positions overlap by {min(shares):.0%} one way and "
            f"{max(shares):.0%} the other, and a live profile declares one "
            "overlap for both. A replay cannot reproduce that layout; open "
            "the dataset instead."
        )

    if shares:
        overlap = shares[0]
        defaults = DEFAULTS["overview"].with_overlap(overlap, overlap, overlap)
    else:
        # A single position has no neighbours, so any overlap will do and the
        # stock plan is the simplest true one.
        defaults = DEFAULTS["overview"]

    channels = tuple(f"channel {index}" for index in range(channel_count))
    profile, geometry = plan_the_writing(
        "overview", frame=frame, dtype=mosaic.dtype, z_planes=z_planes,
        timepoints=moments, channels=channels,
        voxel_size=(voxel["z"], voxel["y"], voxel["x"]),
        readable_prefix="replay", defaults=defaults,
    )
    wanted = tuple(None if step is None else round(step) for step in steps_px)
    if any(step is not None and step != planned
           for step, planned in zip(wanted, geometry.step_shape, strict=True)):
        raise ValueError(
            f"these positions sit {wanted} pixels apart, but the live planner "
            f"can only place this frame {geometry.step_shape} pixels apart. The "
            "replay would draw the tiles somewhere the dataset does not put "
            "them, so it is refused; open the dataset instead."
        )

    # Where each position sits, in the run's own pixels, taken from the
    # position's own description. Nothing is snapped to anything: a run laid
    # out on a grid comes out on that grid because that is where its tiles
    # are, and a run laid out by nobody comes out where it was imaged.
    least = (min(corner[0] for corner in corners.values()),
             min(corner[1] for corner in corners.values()))
    ordered, positions = [], {}
    for tile in sorted(mosaic.tiles, key=lambda t: corners[t.name]):
        name = tile.name.removesuffix(".ome.zarr")
        corner = corners[tile.name]
        positions[name] = {
            "y": round((corner[0] - least[0]) / voxel["y"]),
            "x": round((corner[1] - least[1]) / voxel["x"]),
        }
        ordered.append((name, tile.copies[0].held_in))

    # A timelapse sweeps the whole grid once per moment, walking the same
    # path each sweep -- the way a stage revisits its positions -- so the
    # time slider grows on screen exactly as it did during the experiment.
    beats = [(name, held_in, front, moment)
             for moment in range(moments)
             for name, held_in in ordered]
    return ReplayPlan(profile=profile, geometry=geometry, positions=positions,
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
                              run_id=Path(transfer).name, positions=plan.positions)
    for number, (name, held_in, front, moment) in enumerate(plan.beats):
        if number and every_s:
            time.sleep(every_s)
        # One beat is one (position, moment): the moment's own pixels are
        # read from the store -- sliced off the time axis when the store
        # keeps one -- and given a channel axis when it does not, which is
        # the shape the live writer takes.
        held = zarr.open_array(str(held_in), mode="r")
        pixels = held[moment] if "t" in front else held[:]
        if "c" not in front:
            pixels = pixels[None]
        publisher.write_and_publish(name, pixels, timepoint=moment)
        if told:
            told(number + 1, plan.total)
        if announce:
            announce()
    # No finish_the_run here, deliberately: the publisher runs in its
    # per-publish mode, which keeps the linked view current after every
    # commit, so there is nothing left to finish -- calling it would only
    # restate what is already on disk.
    return publisher.folder / "views" / "live" / "live.ome.zarr"

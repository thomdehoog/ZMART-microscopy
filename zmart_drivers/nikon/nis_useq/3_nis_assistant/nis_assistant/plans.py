"""What the assistant can plan, and how a plan becomes a useq sequence.

``AcquisitionPlan`` is the flat form the model fills in (positions, channels,
a Z-stack, tiles, time points). ``plan_to_sequence`` turns it into a classic
``useq.MDASequence``, and ``describe`` puts a sequence into plain sentences for
the operator.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB), University of Zurich
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
Date: 2026-09-27
License: MIT
"""

from __future__ import annotations

from typing import Any

import useq
from pydantic import BaseModel, Field

from .settings import (
    CONFIRM_XY_UM,
    CONFIRM_Z_UM,
    GUESSED_EXPOSURE_MS,
    MAX_EXPOSURE_MS,
    SECONDS_PER_IMAGE,
)


class PositionSpec(BaseModel):
    x: float = Field(description="stage x in um")
    y: float = Field(description="stage y in um")
    z: float = Field(description="focus z in um")
    name: str | None = Field(None, description="optional label, e.g. 'well_A1'")


class ChannelSpec(BaseModel):
    config: str = Field(description="name of a NIS optical configuration")
    exposure_ms: float | None = Field(
        None, gt=0, le=MAX_EXPOSURE_MS, description="camera exposure; omit to keep"
    )
    do_stack: bool = Field(
        True,
        description="false: one plane at the position's z in this channel, even when the "
        "plan has a Z-stack (for example brightfield)",
    )
    acquire_every: int = Field(1, ge=1, description="image this channel every nth time point")
    z_offset_um: float = Field(
        0.0, description="focus offset of this channel from the planned z, in um"
    )


class ZStack(BaseModel):
    range_um: float = Field(gt=0, description="total height, centred on each position's z")
    step_um: float = Field(gt=0, description="distance between planes")


class Grid(BaseModel):
    """Tiles around each position, rows x columns, centred on it."""

    rows: int = Field(ge=1, le=20)
    columns: int = Field(ge=1, le=20)
    overlap_percent: float = Field(10.0, ge=0, lt=100, description="overlap of neighbouring tiles")
    fov_um: tuple[float, float] | None = Field(
        None,
        description="camera field (width, height) in um; leave out to measure it with one image",
    )


class AcquisitionPlan(BaseModel):
    """One acquisition: positions (optionally tiled) x channels x Z planes, optionally
    repeated in time."""

    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$", description="short name for the file")
    positions: list[PositionSpec] = Field(
        default_factory=list, description="leave empty to image at the current position"
    )
    channels: list[ChannelSpec] = Field(min_length=1)
    z_stack: ZStack | None = None
    grid: Grid | None = Field(None, description="tile an area around each position")
    time_points: int = Field(1, ge=1, le=1000)
    interval_s: float = Field(0.0, ge=0, description="time between time points")
    focus_with_pfs: bool = Field(False, description="lock focus with the PFS at each position")


def plan_to_sequence(
    plan: AcquisitionPlan, fov_um: tuple[float, float] | None = None
) -> useq.MDASequence:
    """The useq sequence for a plan whose positions are filled in.

    ``fov_um`` is the camera field (width, height), which a grid needs to space
    its tiles. The result is a classic ``useq.MDASequence``, not a v2 one: the
    pymmcore-plus file writers (0.18) read the channels and Z planes from a
    classic sequence, but save a v2 sequence as one flat stack of images.
    """
    channels = [
        {
            "config": c.config,
            "exposure": c.exposure_ms,
            "do_stack": c.do_stack,
            "acquire_every": c.acquire_every,
            "z_offset": c.z_offset_um,
        }
        for c in plan.channels
    ]
    kwargs: dict[str, Any] = {
        "stage_positions": [p.model_dump(exclude_none=True) for p in plan.positions],
        "channels": channels,
        "axis_order": "tpgcz",
    }
    if plan.z_stack:
        kwargs["z_plan"] = {"range": plan.z_stack.range_um, "step": plan.z_stack.step_um}
    if plan.grid:
        if fov_um is None:
            raise ValueError("a grid needs the camera field of view to space its tiles")
        overlap = plan.grid.overlap_percent
        kwargs["grid_plan"] = {
            "rows": plan.grid.rows,
            "columns": plan.grid.columns,
            "overlap": (overlap, overlap),
            "fov_width": fov_um[0],
            "fov_height": fov_um[1],
        }
    if plan.time_points > 1:
        kwargs["time_plan"] = {"interval": plan.interval_s, "loops": plan.time_points}
    if plan.focus_with_pfs:
        kwargs["autofocus_plan"] = useq.AxesBasedAF(axes=("t", "p"))
    return useq.MDASequence(**kwargs)


def count_images(events: list[useq.MDAEvent]) -> int:
    return sum(isinstance(e.action, useq.AcquireImage) for e in events)


def describe(
    sequence: useq.MDASequence, events: list[useq.MDAEvent], here: dict[str, float]
) -> str:
    """A useq sequence in plain sentences, including how far the stage will travel
    from ``here`` (the stage position now, per axis in um)."""
    images = count_images(events)
    sizes = sequence.sizes
    z_plan = sequence.z_plan
    channels = []
    for c in sequence.channels:
        extras = [
            "one plane" if z_plan and not c.do_stack else "",
            f"every {c.acquire_every} time points" if c.acquire_every > 1 else "",
            f"{c.z_offset:+g} um in z" if c.z_offset else "",
        ]
        extras = [e for e in extras if e]
        channels.append(f"{c.config} ({', '.join(extras)})" if extras else c.config)
    if z_plan is None:
        planes = "one plane"
    elif isinstance(z_plan, useq.ZRangeAround):
        planes = f"a Z-stack of {z_plan.range:g} um in {z_plan.step:g} um steps"
    else:
        planes = f"{sizes.get('z', 1)} Z planes"
    last_start = max((e.min_start_time or 0.0) for e in events) if events else 0.0
    times = ""
    if sizes.get("t", 0) > 1:
        times = f", {sizes['t']} time points {last_start / (sizes['t'] - 1):g} s apart"
    positions = []
    for i, p in enumerate(sequence.stage_positions):
        axes = ", ".join(f"{a} {getattr(p, a):.0f}" for a in "xyz" if getattr(p, a) is not None)
        where = f"at {axes} um" if axes else "where the stage is"
        positions.append(f"{p.name or f'#{i + 1}'} {where}")
    if len(positions) > 6:
        positions = [*positions[:6], f"and {len(positions) - 6} more"]
    tiles = ""
    grid = sequence.grid_plan
    if isinstance(grid, useq.GridRowsColumns):
        tiles = f", each as {grid.rows} x {grid.columns} tiles"
    elif grid is not None:
        tiles = f", each as {sizes.get('g', 1)} tiles"
    exposures = [c.exposure or GUESSED_EXPOSURE_MS for c in sequence.channels]
    exposure_ms = max(exposures, default=GUESSED_EXPOSURE_MS)
    seconds = max(images * (SECONDS_PER_IMAGE + exposure_ms / 1000), last_start)

    xy = max((_distance(e, here, "x", "y") for e in events), default=0.0)
    z = max((_distance(e, here, "z") for e in events), default=0.0)
    travel = f"The stage travels up to {xy:.0f} um in XY and {z:.0f} um in Z from where it is now."
    if xy > CONFIRM_XY_UM or z > CONFIRM_Z_UM:
        travel += " This includes a long move."
    return (
        f"{images} images: channels {', '.join(channels) or 'as set now'}, {planes}{times}, "
        f"at {len(sequence.stage_positions)} position(s) ({'; '.join(positions)}){tiles}. "
        f"About {max(seconds / 60, 0.1):.1f} minutes. {travel}"
    )


def _distance(event: useq.MDAEvent, here: dict[str, float], *axes: str) -> float:
    """The largest distance, over ``axes``, from ``here`` to where the event goes."""
    targets = {"x": event.x_pos, "y": event.y_pos, "z": event.z_pos}
    return max((abs(targets[a] - here[a]) for a in axes if targets[a] is not None), default=0.0)

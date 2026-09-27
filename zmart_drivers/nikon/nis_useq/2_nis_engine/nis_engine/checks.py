"""May this sequence run? The checks the engine makes before anything moves.

Every check takes a useq event or sequence and what the microscope offers
(``Offered``: the stage limits, the optical configurations, the fitted
objectives, whether there is a Perfect Focus System), and raises ``ValueError``
naming the first problem. Nothing here talks to the microscope.

What an event may hold, on the Nikon:

- ``x_pos``, ``y_pos``, ``z_pos``: an absolute NIS stage position in um, inside
  the limits; a missing axis means "stay".
- ``channel.config``: the name of a NIS optical configuration.
- ``exposure``: the camera exposure in ms.
- ``properties``: the pairs in ``PROPERTIES``, with the values they accept.
- ``action``: ``AcquireImage``, ``HardwareAutofocus`` (the PFS), or the custom
  action ``autofocus`` (the NIS image-based focus sweep).

Anything else (a camera ROI, an SLM image, another custom action) is refused.
This is the place to look up or extend what the engine accepts.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB), University of Zurich
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
Date: 2026-09-27
License: MIT
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nis_bridge.settings import AUTOFOCUS_MAX_SPEED, AUTOFOCUS_RANGE_UM, AUTOFOCUS_SPEED
from useq import AcquireImage, CustomAction, HardwareAutofocus, MDAEvent

# The (device, property) pairs an event may set, with the values each accepts.
PROPERTIES = {
    ("Nosepiece", "Position"): "a nosepiece slot number (1, 2, ...)",
    ("PFS", "State"): '"On" or "Off"',
}


@dataclass(frozen=True)
class Offered:
    """What the microscope offers right now, read once before a check."""

    limits: dict[str, dict[str, float]]  # per axis, min and max in um
    configurations: list[str]
    objectives: list[int]  # the fitted nosepiece slots
    has_pfs: bool


def check_event(event: MDAEvent, offered: Offered) -> None:
    """Raise ValueError if the engine cannot run this event as written."""
    where = where_in_sequence(event)
    if event.roi is not None or event.slm_image is not None:
        raise ValueError(f"{where}: camera ROI and SLM images are not supported")

    position = {"x": event.x_pos, "y": event.y_pos, "z": event.z_pos}
    check_limits(where, {k: v for k, v in position.items() if v is not None}, offered.limits)

    if event.channel is not None and event.channel.config not in offered.configurations:
        raise ValueError(
            f"{where}: {event.channel.config!r} is not an optical configuration in "
            f"NIS-Elements; known: {', '.join(offered.configurations)}"
        )

    for device, prop, value in event.properties or ():
        if (device, prop) not in PROPERTIES:
            known = "; ".join(f"{d}.{p}: {v}" for (d, p), v in PROPERTIES.items())
            raise ValueError(f"{where}: unsupported property {device}.{prop}; known: {known}")
        if device == "Nosepiece" and slot(value) not in offered.objectives:
            raise ValueError(f"{where}: no objective in nosepiece slot {value}")
        if device == "PFS":
            on_off(value)

    action = event.action
    uses_pfs = isinstance(action, HardwareAutofocus) or any(
        device == "PFS" for device, _, _ in event.properties or ()
    )
    if uses_pfs and not offered.has_pfs:
        raise ValueError(f"{where}: needs a Perfect Focus System, and NIS reports none")
    if isinstance(action, HardwareAutofocus) and action.autofocus_motor_offset is not None:
        raise ValueError(f"{where}: setting a PFS offset is not supported")
    if isinstance(action, CustomAction):
        check_autofocus_action(where, action)
    elif not isinstance(action, (AcquireImage, HardwareAutofocus)):
        raise ValueError(f"{where}: unsupported action {action!r}")


def check_limits(where: str, target: dict[str, float], limits: dict) -> None:
    """Raise ValueError when a target (um, per axis) lies outside ``limits``."""
    for axis, value in target.items():
        lo, hi = limits[axis]["min"], limits[axis]["max"]
        if not lo <= value <= hi:
            raise ValueError(
                f"{where}: {axis} = {value} um is outside the stage limits [{lo}, {hi}] um"
            )


def check_limits_are_ranges(limits: dict[str, dict[str, float]]) -> None:
    """Raise ValueError when an axis's minimum is not below its maximum."""
    for axis, limit in limits.items():
        if not limit["min"] < limit["max"]:
            raise ValueError(
                f"{axis}: the minimum must be below the maximum, inside NIS's own limits"
            )


def check_image(image: Any) -> None:
    """Raise ValueError when the camera gives images this engine cannot save."""
    if image.ndim != 2:
        raise ValueError(
            f"the camera gives colour or multi-plane images (shape {image.shape}), which this "
            "engine does not save correctly. Set the camera to monochrome in NIS-Elements."
        )


def check_plans(sequence: Any, field_note: str = "") -> None:
    """Refuse Z and grid plans that useq would turn into wrong absolute positions.

    A relative Z plan or grid is laid out around a stage position; without
    one, useq produces bare offsets around 0 um, and an engine would send the
    stage there. A tiling grid also needs the field of view, or useq places
    the tiles 1 um apart. Nested per-position sequences are checked as well.
    ``field_note`` is added to that message: one sentence on the camera field.
    """
    top_z = getattr(sequence, "z_plan", None)
    top_grid = getattr(sequence, "grid_plan", None)
    positions = list(getattr(sequence, "stage_positions", None) or ()) or [None]
    for p in positions:
        # classic: Position(sequence=...); v2: a nested sequence with its Position in .value
        sub = p if hasattr(p, "axes") else getattr(p, "sequence", None)
        pos = getattr(p, "value", p)
        z_plan = getattr(sub, "z_plan", None) or top_z
        grid = getattr(sub, "grid_plan", None) or top_grid

        if z_plan is not None and z_plan.is_relative and getattr(pos, "z", None) is None:
            raise ValueError(
                "the Z plan is relative (a range around each position), but a stage "
                "position has no z. Give each position a z, or use an absolute Z plan "
                "such as ZTopBottom."
            )
        if grid is None:
            continue
        if grid.is_relative and None in (getattr(pos, "x", None), getattr(pos, "y", None)):
            raise ValueError(
                "the grid is relative (tiles around each position), but a stage position "
                "has no x and y. Give each position x and y, or use GridFromEdges."
            )
        if hasattr(grid, "overlap") and None in (grid.fov_width, grid.fov_height):
            raise ValueError(
                "the grid needs the field of view to space its tiles: set fov_width and "
                f"fov_height (um) on the grid plan. {field_note}"
            )


def where_in_sequence(event: MDAEvent) -> str:
    """The event's place in the sequence, for messages: 'event p=0, z=2'."""
    index = ", ".join(f"{getattr(k, 'value', k)}={v}" for k, v in event.index.items())
    return f"event {index}" if index else "event"


def slot(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"Nosepiece Position must be a slot number (1, 2, ...), not {value!r}"
        ) from None


def on_off(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if str(value).lower() in ("on", "1", "true"):
        return True
    if str(value).lower() in ("off", "0", "false"):
        return False
    raise ValueError(f'PFS State must be "On" or "Off", not {value!r}')


def check_autofocus_action(where: str, action: CustomAction) -> None:
    usage = (
        f'CustomAction(name="autofocus", data={{"range_um": {AUTOFOCUS_RANGE_UM:g}, '
        f'"speed": {AUTOFOCUS_SPEED}}})'
    )
    if action.name != "autofocus" or not set(action.data) <= {"range_um", "speed"}:
        raise ValueError(f"{where}: the only custom action is {usage}")
    try:
        range_um = float(action.data.get("range_um", AUTOFOCUS_RANGE_UM))
        speed = float(action.data.get("speed", AUTOFOCUS_SPEED))
    except (TypeError, ValueError):
        raise ValueError(f"{where}: range_um and speed must be numbers: {usage}") from None
    if range_um <= 0 or not 0 <= speed <= AUTOFOCUS_MAX_SPEED:
        raise ValueError(
            f"{where}: range_um must be positive and speed between 0 and {AUTOFOCUS_MAX_SPEED}"
        )

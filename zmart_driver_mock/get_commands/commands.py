"""The get commands: what the driver can ask the microscope.

Most are one line: which primitive to call, through the get dispatcher. A
few combine readings and give them a meaning, such as the position in user
coordinates. That is the rule from the driver anatomy: *how* to talk to the
vendor belongs in the vendor interface, *what a value means* belongs here.

Every function takes ``ctx``, the connected driver, and returns a
:class:`Reading`.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

from typing import Any

from ..configuration import user_from_raw
from .dispatch import Reading

# The settings an experiment can change, by their ZMART name, with the name
# MockScope uses for each. Translating names is part of giving values a
# meaning, so it lives here and not in the vendor interface.
SETTING_NAMES: dict[str, str] = {
    "laser_power": "laser_power_percent",
    "gain": "detector_gain",
    "exposure_ms": "exposure_ms",
}

# The motors that can move each axis. "motoric" is the coarse focus drive
# for z; "piezo" is the fine one, quick but with only ±100 µm of travel.
ACTUATORS: dict[str, list[str]] = {"x": ["motoric"], "y": ["motoric"], "z": ["motoric", "piezo"]}


def version(ctx) -> Reading:
    return ctx.get.read("software version", ctx.vendor.version)


def hardware(ctx) -> Reading:
    return ctx.get.read("hardware description", ctx.vendor.hardware)


def stage(ctx) -> Reading:
    """The stage position ``{"x", "y"}`` in raw micrometers."""
    return ctx.get.read("stage position", ctx.vendor.stage_position)


def focus(ctx) -> Reading:
    """The focus drives ``{"focus", "piezo"}`` in raw micrometers."""
    return ctx.get.read("focus position", ctx.vendor.focus_position)


def settings(ctx) -> Reading:
    """The vendor settings by the vendor's own names, plus ``objective_slot``."""
    return ctx.get.read("settings", ctx.vendor.settings)


def status(ctx) -> Reading:
    """What the microscope is doing now, and the last acquisition."""
    return ctx.get.read("status", ctx.vendor.status)


def _combine(*readings: Reading) -> Reading | None:
    """The first unknown reading among ``readings``, or None if all are known."""
    for reading in readings:
        if not reading.known:
            return reading
    return None


def raw_position(ctx) -> Reading:
    """Where every drive is, in raw micrometers, with the objective in use.

    The value is ``{"x", "y", "z", "focus", "piezo", "objective"}``, where
    ``z`` is the focus height that matters for the sample: the coarse drive
    plus the piezo.
    """
    xy, z, current = stage(ctx), focus(ctx), settings(ctx)
    unknown = _combine(xy, z, current)
    if unknown is not None:
        return unknown
    value = {
        "x": xy.value["x"],
        "y": xy.value["y"],
        "z": z.value["focus"] + z.value["piezo"],
        "focus": z.value["focus"],
        "piezo": z.value["piezo"],
        "objective": int(current.value["objective_slot"]),
    }
    return Reading(value, max(xy.observed_at, z.observed_at), xy.source)


def user_position(ctx) -> Reading:
    """The position ``{"x", "y", "z"}`` in user coordinates, from the recorded origin."""
    raw = raw_position(ctx)
    if not raw.known:
        return raw
    value = user_from_raw(raw.value, raw.value["objective"], ctx.config)
    return Reading(value, raw.observed_at, raw.source)


def state(ctx) -> Reading:
    """The changeable settings by their ZMART names, plus the objective slot."""
    current = settings(ctx)
    if not current.known:
        return current
    value: dict[str, Any] = {name: current.value[vendor] for name, vendor in SETTING_NAMES.items()}
    value["objective"] = int(current.value["objective_slot"])
    return Reading(value, current.observed_at, current.source)

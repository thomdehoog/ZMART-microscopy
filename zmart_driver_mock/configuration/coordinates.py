"""The coordinate system: from stage coordinates to the user's, and back.

The vendor software reports **raw stage coordinates**: micrometers exactly as
the stage counts them, with its own zero somewhere at the edge of the slide.
Experiments work in **user coordinates**: micrometers from the recorded
origin, so (0, 0, 0) is the place the operator chose.

Two corrections connect them:

- **The origin.** User coordinates are measured from it.
- **The objective offsets** from the optical calibration. Each objective
  looks at a slightly different spot and focuses at a slightly different
  height. Adding the offset of the objective in use means a user position
  always names the same spot on the sample, whichever objective is in place.

The origin is stored as a point on the sample (raw position plus the offset
of the objective in use when it was recorded), so it stays valid after an
objective change.

These functions are the only place this arithmetic happens. The get and set
commands for position use them, so everything above those commands speaks
user coordinates, and the limits are checked in raw stage coordinates, where
recording a new origin cannot move them.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

from .store import Configuration

AXES = ("x", "y", "z")


def _offset(config: Configuration, slot: int) -> dict[str, float]:
    offsets = config.optical_calibration["objective_offsets_um"]
    try:
        return offsets[str(slot)]
    except KeyError:
        raise RuntimeError(
            f"the optical calibration has no entry for objective {slot}; "
            f"calibrate it before using this objective"
        ) from None


def sample_point(raw: dict[str, float], slot: int, config: Configuration) -> dict[str, float]:
    """The spot on the sample in view, from a raw stage position and the objective in use."""
    offset = _offset(config, slot)
    return {axis: raw[axis] + offset[axis] for axis in AXES}


def user_from_raw(raw: dict[str, float], slot: int, config: Configuration) -> dict[str, float]:
    """Turn a raw stage position ``{"x", "y", "z"}`` into user coordinates."""
    point = sample_point(raw, slot, config)
    return {axis: point[axis] - config.origin[axis] for axis in AXES}


def raw_from_user(user: dict[str, float], slot: int, config: Configuration) -> dict[str, float]:
    """Turn a user position ``{"x", "y", "z"}`` into the raw stage position that shows it."""
    offset = _offset(config, slot)
    return {axis: user[axis] + config.origin[axis] - offset[axis] for axis in AXES}


def user_range(config: Configuration, slot: int) -> dict[str, list[float]]:
    """How far each axis may travel, as ``[lowest, highest]`` in user coordinates."""
    stage = config.limits["stage_um"]
    low = user_from_raw({axis: stage[axis][0] for axis in AXES}, slot, config)
    high = user_from_raw({axis: stage[axis][1] for axis in AXES}, slot, config)
    return {axis: [low[axis], high[axis]] for axis in AXES}

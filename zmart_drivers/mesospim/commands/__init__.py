"""Command wrappers + the dispatch backbone.

Everything that tells the instrument to do something lives here: stage
movement (:mod:`.movement`), instrument-state settings (:mod:`.commands`),
the shared result envelope (:mod:`.envelope`), and the fire/confirm backbone
(:mod:`.dispatch`). The stage-limit rules live in :mod:`mesospim.limits`;
this package is the only place they are enforced.
"""

from .commands import (
    set_etl,
    set_filter,
    set_intensity,
    set_laser,
    set_shutter,
    set_state,
    set_zoom,
)
from .dispatch import confirm_and_fire
from .movement import (
    move_absolute,
    move_focus,
    move_relative,
    move_rotation,
    move_xy,
    move_z,
    stop,
    zero_axes,
)

__all__ = [
    "confirm_and_fire",
    "move_absolute",
    "move_relative",
    "move_xy",
    "move_z",
    "move_focus",
    "move_rotation",
    "stop",
    "zero_axes",
    "set_state",
    "set_filter",
    "set_zoom",
    "set_laser",
    "set_intensity",
    "set_shutter",
    "set_etl",
]

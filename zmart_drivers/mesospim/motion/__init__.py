"""Stage motion: movement wrappers + fail-closed stage limits.

Mirrors the Leica ``navigator_expert`` layout: ``movement`` holds the move
commands, ``limits`` holds the hard stage-envelope checks every move passes
through before firing. The bundled envelope lives in ``../limits/defaults/``.
"""

from .limits import (
    LimitError,
    apply_stage_limits_from_config,
    check_axis,
    check_move,
    clear_stage_limits,
    get_stage_limits,
    load_stage_config,
    set_stage_limits,
)
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
    "LimitError",
    "apply_stage_limits_from_config",
    "check_axis",
    "check_move",
    "clear_stage_limits",
    "get_stage_limits",
    "load_stage_config",
    "set_stage_limits",
    "move_absolute",
    "move_relative",
    "move_xy",
    "move_z",
    "move_focus",
    "move_rotation",
    "stop",
    "zero_axes",
]

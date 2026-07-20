"""Stage safety limits: the rulebook for where the ZEN stage may go.

Everything about limits lives here -- the configured XY/Z envelope, the check
functions, and the stage-config loader. The checks fire in exactly one place:
the command wrappers in :mod:`zenapi.commands.commands`, before any RPC leaves
the driver. Mirrors the Leica and mesoSPIM layout, where ``limits/`` owns the
rules and ``commands/`` is the only place they are enforced.
"""

from .checks import (
    _check_xy_limits,
    _check_z_limits,
    apply_stage_limits_from_config,
    get_stage_limits,
    set_stage_limits,
)
from .stage_config import load

__all__ = [
    "apply_stage_limits_from_config",
    "get_stage_limits",
    "set_stage_limits",
    "load",
]

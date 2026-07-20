"""Stage safety limits: the rulebook for where the mesoSPIM stage may go.

Everything about limits lives here -- the configured per-axis envelope, the
check functions, and the bundled default envelope in ``defaults/``. The checks
fire in exactly one place: the movement wrappers in
:mod:`mesospim.commands.movement`, before any request reaches the instrument.
Mirrors the Leica ``navigator_expert`` layout, where ``limits/`` owns the rules
and ``commands/`` is the only place they are enforced.
"""

from .checks import (
    LimitError,
    apply_stage_limits_from_config,
    check_axis,
    check_move,
    clear_stage_limits,
    get_stage_limits,
    load_stage_config,
    set_stage_limits,
)
from .function_limits import (
    SCHEMA_VERSION,
    Constraint,
    FunctionLimits,
    LimitsError,
    LimitViolation,
    load,
    parse,
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
    "SCHEMA_VERSION",
    "Constraint",
    "FunctionLimits",
    "LimitsError",
    "LimitViolation",
    "load",
    "parse",
]

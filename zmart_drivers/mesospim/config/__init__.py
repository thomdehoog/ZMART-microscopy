"""Configuration: profiles, hardware model, and stage limits."""

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
from .profiles import (
    ACQUISITION,
    CONNECTION,
    HARDWARE,
    AcquisitionProfile,
    CommandProfile,
    ConnectionProfile,
    HardwareProfile,
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
    "ACQUISITION",
    "CONNECTION",
    "HARDWARE",
    "AcquisitionProfile",
    "CommandProfile",
    "ConnectionProfile",
    "HardwareProfile",
]

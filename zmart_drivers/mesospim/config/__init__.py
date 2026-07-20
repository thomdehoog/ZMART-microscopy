"""Configuration: the axis vocabulary and the static profiles.

Stage limits live in :mod:`mesospim.limits` and the machine-local coordinate
config in :mod:`mesospim.calibration.machine`; this package holds the axis
constants (:mod:`.axes`) and the static profiles (:mod:`.profiles`).
"""

from .axes import AXES, LINEAR_AXES, ROTARY_AXES
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
    "AXES",
    "LINEAR_AXES",
    "ROTARY_AXES",
    "ACQUISITION",
    "CONNECTION",
    "HARDWARE",
    "AcquisitionProfile",
    "CommandProfile",
    "ConnectionProfile",
    "HardwareProfile",
]

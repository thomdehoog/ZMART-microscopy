"""Configuration: connection, hardware model, and acquisition profiles.

Stage limits moved to :mod:`mesospim.motion.limits` and the machine-local
coordinate config to :mod:`mesospim.calibration.machine`; this package is now
just the static profiles (:mod:`.profiles`).
"""

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
    "ACQUISITION",
    "CONNECTION",
    "HARDWARE",
    "AcquisitionProfile",
    "CommandProfile",
    "ConnectionProfile",
    "HardwareProfile",
]

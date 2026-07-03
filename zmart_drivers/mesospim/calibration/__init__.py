"""Machine-local coordinate configuration for a mesoSPIM.

Mirrors the Leica ``navigator_expert`` layout: this package owns the
machine-local coordinate config -- the ProgramData resolution of the stage
envelope, the function-keyed limits, and the persisted frame origin
(:mod:`.machine`).

A light-sheet has no per-objective translation or backlash calibration (the
Leica's ``calibration/core``), so there is no optical-calibration model here.
The optical hardware description -- lasers, camera, and the zoom->pixel-size
table -- is part of the hardware profile and stays in
:mod:`mesospim.config.profiles`.
"""

from .machine import (
    FUNCTION_LIMITS_FILENAME,
    ORIGIN_FILENAME,
    STAGE_LIMITS_FILENAME,
    MachineProfile,
)

__all__ = [
    "MachineProfile",
    "STAGE_LIMITS_FILENAME",
    "FUNCTION_LIMITS_FILENAME",
    "ORIGIN_FILENAME",
]

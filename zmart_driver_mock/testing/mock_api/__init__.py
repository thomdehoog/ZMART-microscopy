"""The mock API: pretend vendor software for trying a driver without hardware.

Start here::

    from zmart_driver_mock.testing.mock_api import MockScope

    scope = MockScope(output_folder="images")
    scope.send("Login", token="mock-token")
    scope.send("MoveStage", x=51_000.0, y=37_000.0)

See ``README.md`` in this folder for the full list of commands, the error
codes, and how to make the pretend microscope fail on purpose.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from .faults import FAULTS, Faults
from .mraw import read_mraw
from .sample import Tilt
from .scope import (
    COMMANDS,
    DEFAULT_ORIENTATION,
    DEFAULT_TIMING,
    ERRORS,
    FOCUS_TRAVEL,
    OBJECTIVES,
    SETTINGS,
    STAGE_TRAVEL,
    FakeClock,
    MockScope,
)

__all__ = [
    "COMMANDS",
    "DEFAULT_ORIENTATION",
    "DEFAULT_TIMING",
    "ERRORS",
    "FAULTS",
    "FOCUS_TRAVEL",
    "OBJECTIVES",
    "SETTINGS",
    "STAGE_TRAVEL",
    "FakeClock",
    "Faults",
    "MockScope",
    "Tilt",
    "read_mraw",
]

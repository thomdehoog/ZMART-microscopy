"""Part 4 of the driver anatomy: set commands and the set dispatcher.

A set command changes the microscope: a move, a setting, an objective, an
acquisition. Every one of them runs through the set dispatcher, which checks
the limits first, sends the command, tries again after a temporary problem,
and then confirms through the get dispatcher that the change really
happened. When it cannot confirm it, it says so instead of pretending.
"""

from .commands import acquire, move, move_to_user, set_objective, set_setting, stop
from .dispatch import NeverConfirmed, Outcome, SetCommand, SetDispatcher
from .gate import Gate
from .tuning import ACQUIRE_TUNING, DEFAULT_SET_TUNING, OBJECTIVE_TUNING, SetTuning

__all__ = [
    "ACQUIRE_TUNING",
    "DEFAULT_SET_TUNING",
    "OBJECTIVE_TUNING",
    "Gate",
    "NeverConfirmed",
    "Outcome",
    "SetCommand",
    "SetDispatcher",
    "SetTuning",
    "acquire",
    "move",
    "move_to_user",
    "set_objective",
    "set_setting",
    "stop",
]

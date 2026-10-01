"""Part 2 of the driver anatomy: error handling.

Two pieces. :mod:`.classifier` is written for this microscope: it sorts
whatever went wrong into one of the shared kinds. :mod:`.rules` is the same
for every microscope: for each kind, what the get dispatcher and the set
dispatcher do next. The dispatchers never read error messages themselves.
"""

from .classifier import classify
from .rules import RULES, Action, Kind, Rule

__all__ = ["RULES", "Action", "Kind", "Rule", "classify"]

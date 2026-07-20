"""
Backlash correction.
====================
Mechanical slack in the stage gears means the same target can land in slightly
different places depending on the direction you arrive from. This routine
re-pins the slack state at the current position by jogging away and returning
from a fixed direction (-X/-Y), so the position that follows is repeatable.

It composes over the plain ``move_xy`` command (imported lazily to keep the
import graph acyclic). Like the Leica driver, the deliberate composition
``move to target, then correct`` is left to the workflow layer -- the driver
offers building blocks, not choreography.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import time


def correct_backlash(client, *, overshoot_um=50.0, settle_ms=100, tolerance_um=20.0):
    """Re-pin the slack state at the current position (read, jog -X/-Y, return)."""
    from ..readers import get_xy
    from .commands import move_xy

    pos = get_xy(client)
    x_um, y_um = pos["x_um"], pos["y_um"]
    move_xy(client, x_um - overshoot_um, y_um - overshoot_um, unit="um")
    if settle_ms:
        time.sleep(settle_ms / 1000.0)
    return move_xy(client, x_um, y_um, unit="um", tolerance=tolerance_um)

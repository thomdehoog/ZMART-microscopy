"""
Backlash-compensated motion primitives.
========================================
Optional helpers that approach a target from a fixed direction so mechanical
slack is taken up consistently, giving repeatable XY positioning. They compose
over the plain ``move_xy`` command (imported lazily to keep the import graph
acyclic).

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import time


def move_xy_with_backlash(client, x_um, y_um, *, overshoot_um=50.0, settle_ms=100, tolerance=None):
    """Move to ``(x_um, y_um)`` approaching from -X/-Y to pin the slack state.

    Goes to ``(x-overshoot, y-overshoot)`` first, settles, then to the target.
    Returns the final ``move_xy`` result dict.
    """
    from ..commands.commands import move_xy

    move_xy(client, x_um - overshoot_um, y_um - overshoot_um, unit="um")
    if settle_ms:
        time.sleep(settle_ms / 1000.0)
    return move_xy(client, x_um, y_um, unit="um", tolerance=tolerance)


def correct_backlash(client, *, overshoot_um=50.0, settle_ms=100, tolerance_um=20.0):
    """Re-pin the slack state at the current position (read, jog -X/-Y, return)."""
    from ..commands.commands import move_xy
    from ..readers import get_xy

    pos = get_xy(client)
    x_um, y_um = pos["x_um"], pos["y_um"]
    move_xy(client, x_um - overshoot_um, y_um - overshoot_um, unit="um")
    if settle_ms:
        time.sleep(settle_ms / 1000.0)
    return move_xy(client, x_um, y_um, unit="um", tolerance=tolerance_um)

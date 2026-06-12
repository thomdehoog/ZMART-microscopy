"""Stage motion helpers.

Backlash discipline: when the stage reverses direction, leadscrew slack
introduces a position offset that depends on which side the nut last
came from. By always finishing every move with the same +X+Y leg, the
slack-state is pinned and the offset becomes invisible.

Two primitives for the two physical patterns:

  ``move_xy_with_backlash(client, x, y, ...)``
      Transit-with-takeup. Move to a known target *through* an
      overshoot waypoint, settle, then make the final +X +Y leg.
      Two moves, no current-position read. Use when you need to
      arrive somewhere with backlash compensation built in
      (e.g. before each acquisition).

  ``correct_backlash(client, ...)``
      Post-move takeup. Reads current XY, jogs (-X, -Y), settles,
      moves back. Three operations, with one ``get_xy`` read. Use
      when you're already at the target and just need to pin the
      slack-state without net displacement.

Parameters for both come from ``stage.config.load``. Production callers
should pass ``stage_cfg["backlash"]`` from that loader; the function
defaults below are last-resort fallbacks, not the source of truth.

See ``docs/session_notes_20260428_backlash_correction.md`` for the
mechanical analysis behind the recipe.
"""

import logging
import time

from ..commands import commands as _commands
from .. import state_readers as _readers

log = logging.getLogger(__name__)


def move_xy_with_backlash(client, x_um, y_um, *,
                          overshoot_um=50.0, settle_ms=100):
    """Move to ``(x_um, y_um)`` with backlash takeup on the final approach.

    Approaches the target through the overshoot waypoint
    ``(x_um - overshoot_um, y_um - overshoot_um)``, settles, then makes
    the final +X +Y leg to ``(x_um, y_um)``. The consistent +X +Y
    direction pins the leadscrew slack the same way across acquisitions,
    so positions are repeatable regardless of where the stage came from.

    Use this for "move to target with backlash compensation built in" -
    one fewer move than ``correct_backlash`` at a known target. For
    post-move takeup at the *current* stage position (no displacement),
    use ``correct_backlash`` instead.

    Parameters
    ----------
    client
        LAS X API client.
    x_um, y_um
        Target stage XY in micrometres.
    overshoot_um
        Distance to retreat in -X -Y before the final approach. Must
        exceed the stage's backlash; 50 um is 10x margin on the ZMB
        STELLARIS.
    settle_ms
        Pause between the overshoot waypoint and the final approach.

    Returns
    -------
    dict
        The result of the final ``move_xy`` call (always
        ``{"success": True, ...}`` - failures of either leg raise).
        Self-contained contract: either the stage is at ``(x_um, y_um)``
        with the slack-state pinned in +X +Y, or this function raises.
        Silently continuing after a partial move would image at an
        uncompensated position - the bug backlash compensation exists
        to prevent.
    """
    r = _commands.move_xy(
        client, x_um - overshoot_um, y_um - overshoot_um, unit="um",
    )
    if not r or not r.get("success"):
        raise RuntimeError(
            f"backlash overshoot to ({x_um - overshoot_um:.2f}, "
            f"{y_um - overshoot_um:.2f}) failed: {r}"
        )
    time.sleep(settle_ms / 1000.0)
    r = _commands.move_xy(client, x_um, y_um, unit="um")
    if not r or not r.get("success"):
        raise RuntimeError(
            f"backlash final approach to ({x_um:.2f}, {y_um:.2f}) "
            f"failed: {r}"
        )
    return r


def correct_backlash(client, *, overshoot_um=50.0, settle_ms=100,
                     tolerance_um=20.0):
    """Pin the stage to the +X+Y slack-state with no net displacement.

    Reads current XY, drives to ``(x - overshoot, y - overshoot)``,
    pauses ``settle_ms`` (so controllers that blend consecutive moves
    treat the next command as distinct), then drives back to ``(x, y)``.
    The final +X +Y leg engages both leadscrews against the same flank.

    Parameters
    ----------
    client
        LAS X API client.
    overshoot_um
        Distance to retreat in -X -Y. Must exceed the stage's backlash;
        50 um is 10x margin on the ZMB STELLARIS (3-5 um backlash).
    settle_ms
        Pause between overshoot and return. 100 ms keeps the moves
        distinct without polling.
    tolerance_um
        Pass-through to ``move_xy``. Loose by default; the takeup
        does not need precision.

    The parameter defaults are fallback values only. Production paths
    should pass calibrated values from ``stage_cfg["backlash"]`` loaded
    via ``stage.config.load``.
    """
    # This read parameterizes the two corrective moves below, so bypass the
    # passive reader profile and use the authoritative API path.
    pos = _readers.get_xy(client, mode="api")
    if pos is None:
        raise RuntimeError("backlash takeup: could not read XY")
    x, y = float(pos["x_um"]), float(pos["y_um"])
    log.debug("backlash takeup at (%.2f, %.2f) um, overshoot %.1f um",
              x, y, overshoot_um)
    r = _commands.move_xy(client, x - overshoot_um, y - overshoot_um,
                                unit="um", tolerance=tolerance_um)
    if not r or not r.get("success"):
        raise RuntimeError(f"backlash overshoot move failed: {r}")
    time.sleep(settle_ms / 1000.0)
    r = _commands.move_xy(client, x, y,
                                unit="um", tolerance=tolerance_um)
    if not r or not r.get("success"):
        raise RuntimeError(f"backlash return move failed: {r}")

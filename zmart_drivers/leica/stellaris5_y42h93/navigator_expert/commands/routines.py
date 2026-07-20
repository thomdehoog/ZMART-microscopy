"""Composed stage routines.

Routines here move the stage by composing the checked command primitives
in ``commands.py`` -- every leg passes through ``move_xy``'s limit
checks, so nothing in this module can escape the configured envelope.

Backlash discipline: when the stage reverses direction, leadscrew slack
introduces a position offset that depends on which side the nut last
came from. By always finishing every move with the same +X +Y leg, the
slack-state is pinned and the offset becomes invisible -- the stage then
enters every acquisition in the same mechanical state and positions are
repeatable regardless of where it came from.

When the takeup runs is the caller's decision: the acquisition routine
in the ZMART adapter and the calibration notebook order it at the moment
they need a pinned stage. The driver never fires it on its own.

The constants below are physics of this stage, not configuration
(decision §2b): backlash lives in neither ``limits.json`` nor
``calibration.json``. Callers that want non-default takeup pass the
params explicitly.
"""

import logging
import time

from .. import readers as _readers
from ..limits import checks as _checks
from . import commands as _commands

log = logging.getLogger(__name__)

# The ZMB STELLARIS 5 stage has 3-5 um of leadscrew backlash; 50 um of
# overshoot is 10x margin. 100 ms between moves keeps consecutive
# commands distinct, so controllers that blend back-to-back moves treat
# each one as its own motion.
BACKLASH_OVERSHOOT_UM = 50.0
BACKLASH_SETTLE_MS = 100


def arrive_xy(client, x_um, y_um):
    """Arrive at ``(x_um, y_um)`` with the backlash taken up.

    Approach through an overshoot waypoint in -X -Y, settle, then make
    the final +X +Y leg. Two moves, no position read. Near the
    envelope's lower edge the waypoint is clamped inside the envelope,
    so a legal target close to the boundary stays reachable -- the
    takeup is merely shortened there.

    Both legs go through the checked ``move_xy`` door. Either the stage
    is at ``(x_um, y_um)`` with the slack-state pinned, or this raises.
    """
    # Refuse an illegal destination before any leg fires. Without this,
    # the clamp below could turn an out-of-envelope target into a real
    # move to the envelope's corner — motion caused by a target that
    # should have been refused outright.
    _checks.check_xy(x_um, y_um)
    waypoint_x = x_um - BACKLASH_OVERSHOOT_UM
    waypoint_y = y_um - BACKLASH_OVERSHOOT_UM
    env = _checks.get_stage_limits()
    if env["x_min"] is not None:
        clamped_x = max(waypoint_x, env["x_min"])
        clamped_y = max(waypoint_y, env["y_min"])
        if (clamped_x, clamped_y) != (waypoint_x, waypoint_y):
            log.warning(
                "backlash overshoot clamped to the stage envelope near its "
                "edge; takeup is shortened for this move"
            )
        waypoint_x, waypoint_y = clamped_x, clamped_y
    r = _commands.move_xy(client, waypoint_x, waypoint_y, unit="um")
    if not r or not r.get("success") or not r.get("confirmed"):
        raise RuntimeError(
            f"backlash overshoot to ({waypoint_x:.2f}, {waypoint_y:.2f}) "
            f"failed or was unconfirmed: {r}"
        )
    time.sleep(BACKLASH_SETTLE_MS / 1000.0)
    r = _commands.move_xy(client, x_um, y_um, unit="um")
    if not r or not r.get("success") or not r.get("confirmed"):
        raise RuntimeError(
            f"backlash final approach to ({x_um:.2f}, {y_um:.2f}) failed or was unconfirmed: {r}"
        )


def correct_backlash(
    client,
    *,
    at=None,
    overshoot_um=BACKLASH_OVERSHOOT_UM,
    settle_ms=BACKLASH_SETTLE_MS,
    tolerance_um=20.0,
    passes=3,
):
    """Pin the stage to the +X +Y slack-state with no net displacement.

    Repeats ``passes`` times: drive to ``(x - overshoot, y - overshoot)``,
    pause ``settle_ms``, then drive back to ``(x, y)``. Every return leg
    approaches from -X -Y, so each pass engages both leadscrews against
    the same flank; repeating the back-and-forth settles mechanical slack
    that a single pass can leave partially taken up.

    Parameters
    ----------
    client
        LAS X API client.
    at
        ``(x_um, y_um)`` when the caller already knows where the stage is
        -- for example right after a confirmed move. Skips the position
        read. Omit it and the current position is read from the API.
    overshoot_um
        Distance to retreat in -X -Y. Must exceed the stage's backlash;
        the default is this stage's measured physics (see above).
    settle_ms
        Pause between each overshoot and return, so controllers that
        blend consecutive moves treat the next command as distinct.
    tolerance_um
        Pass-through to ``move_xy``. Loose by default; the takeup
        does not need precision.
    passes
        How many back-and-forth passes to run. Three is the historical
        default; whether one pass suffices after a fresh arrival has not
        been measured on the rig -- keep three until bench data says
        otherwise.

    Either every leg confirms via readback or this raises -- an
    unconfirmed leg could hand the stage to the following capture while
    it is still travelling back from the overshoot point.
    """
    if passes != int(passes) or int(passes) < 1:
        raise ValueError(
            f"backlash takeup needs a whole number of passes (at least one), got {passes}"
        )
    if at is None:
        # This read parameterizes the corrective moves below, so bypass the
        # passive reader profile and use the authoritative API path.
        pos = _readers.get_xy(client, mode="api")
        if pos is None:
            raise RuntimeError("backlash takeup: could not read XY")
        x, y = float(pos["x_um"]), float(pos["y_um"])
    else:
        x, y = float(at[0]), float(at[1])
    log.debug(
        "backlash takeup at (%.2f, %.2f) um, overshoot %.1f um, %d passes",
        x,
        y,
        overshoot_um,
        passes,
    )
    for index in range(int(passes)):
        if index > 0:
            # Same reason as the mid-pass pause below: without a gap the
            # previous return and this overshoot could blend into one
            # motion, and the extra passes would settle nothing.
            time.sleep(settle_ms / 1000.0)
        # success=True alone means "command accepted" (profiles set
        # success_on_unconfirmed=True). This routine's contract needs
        # readback evidence: an unconfirmed leg could hand the stage to
        # the following capture while it is still travelling.
        r = _commands.move_xy(
            client, x - overshoot_um, y - overshoot_um, unit="um", tolerance=tolerance_um
        )
        if not r or not r.get("success") or not r.get("confirmed"):
            raise RuntimeError(f"backlash overshoot move failed or was unconfirmed: {r}")
        time.sleep(settle_ms / 1000.0)
        r = _commands.move_xy(client, x, y, unit="um", tolerance=tolerance_um)
        if not r or not r.get("success") or not r.get("confirmed"):
            raise RuntimeError(f"backlash return move failed or was unconfirmed: {r}")

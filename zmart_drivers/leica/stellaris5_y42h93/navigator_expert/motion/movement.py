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
      Post-move takeup. Reads current XY once, then repeats ``passes``
      (default 3) jog-and-return round trips: jog (-X, -Y), settle,
      move back. One ``get_xy`` read plus two moves per pass — six
      moves by default. Use when you're already at the target and just
      need to pin the slack-state without net displacement.

These are plain utility functions with baked-in default params (decision §2b):
``overshoot_um=50``, ``settle_ms=100``, ``tolerance_um`` per the move profile.
Backlash is not config — it lives in neither ``limits.json`` nor
``calibration.json``. Callers that want non-default takeup pass the params
explicitly; the ZMART adapter calls both helpers bare, so the signature
defaults below are the operative values.

The mechanical rule is simple: every compensated move finishes from the same
direction, so the stage enters the same backlash state before acquisition.
"""

import logging
import time

from .. import readers as _readers
from ..commands import commands as _commands

log = logging.getLogger(__name__)


def move_xy_with_backlash(
    client, x_um, y_um, *, overshoot_um=50.0, settle_ms=100, tolerance_um=None
):
    """Move to ``(x_um, y_um)`` with backlash takeup on the final approach.

    Approaches the target through the overshoot waypoint
    ``(x_um - overshoot_um, y_um - overshoot_um)``, settles, then makes
    the final +X +Y leg to ``(x_um, y_um)``. The consistent +X +Y
    direction pins the leadscrew slack the same way across acquisitions,
    so positions are repeatable regardless of where the stage came from.

    Use this for "move to target with backlash compensation built in" -
    two moves total, against ``correct_backlash``'s read plus two moves
    per pass. For post-move takeup at the *current* stage position (no
    displacement), use ``correct_backlash`` instead.

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
    tolerance_um
        Position confirmation tolerance for both legs; None uses the
        move profile's default. Callers may pass an explicit tolerance;
        the ZMART adapter does not, so the profile default is operative
        there.

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
    # success=True alone means "command accepted" (profiles set
    # success_on_unconfirmed=True); the raise-on-failure contract of this
    # helper needs readback evidence, so both legs must be *confirmed* —
    # an unconfirmed overshoot leaves the slack-state unpinned, an
    # unconfirmed approach images at an uncompensated position.
    r = _commands.move_xy(
        client,
        x_um - overshoot_um,
        y_um - overshoot_um,
        unit="um",
        tolerance=tolerance_um,
    )
    if not r or not r.get("success") or not r.get("confirmed"):
        raise RuntimeError(
            f"backlash overshoot to ({x_um - overshoot_um:.2f}, "
            f"{y_um - overshoot_um:.2f}) failed or was unconfirmed: {r}"
        )
    time.sleep(settle_ms / 1000.0)
    r = _commands.move_xy(client, x_um, y_um, unit="um", tolerance=tolerance_um)
    if not r or not r.get("success") or not r.get("confirmed"):
        raise RuntimeError(
            f"backlash final approach to ({x_um:.2f}, {y_um:.2f}) failed or was unconfirmed: {r}"
        )
    return r


def correct_backlash(client, *, overshoot_um=50.0, settle_ms=100, tolerance_um=20.0, passes=3):
    """Pin the stage to the +X+Y slack-state with no net displacement.

    Reads current XY, then repeats ``passes`` times: drive to
    ``(x - overshoot, y - overshoot)``, pause ``settle_ms`` (so controllers
    that blend consecutive moves treat the next command as distinct), then
    drive back to ``(x, y)``. Every return leg approaches from -X -Y, so
    each pass engages both leadscrews against the same flank; repeating the
    back-and-forth settles mechanical slack that a single pass can leave
    partially taken up.

    Parameters
    ----------
    client
        LAS X API client.
    overshoot_um
        Distance to retreat in -X -Y. Must exceed the stage's backlash;
        50 um is 10x margin on the ZMB STELLARIS (3-5 um backlash).
    settle_ms
        Pause between each overshoot and return. 100 ms keeps the moves
        distinct without polling.
    tolerance_um
        Pass-through to ``move_xy``. Loose by default; the takeup
        does not need precision.
    passes
        How many back-and-forth passes to run (default 3).

    Callers may pass explicit params for non-default takeup; the ZMART
    adapter calls this with no arguments, so the signature defaults above
    are the operative values on that path.
    """
    if passes != int(passes) or int(passes) < 1:
        raise ValueError(
            f"backlash takeup needs a whole number of passes (at least one), got {passes}"
        )
    # This read parameterizes the corrective moves below, so bypass the
    # passive reader profile and use the authoritative API path.
    pos = _readers.get_xy(client, mode="api")
    if pos is None:
        raise RuntimeError("backlash takeup: could not read XY")
    x, y = float(pos["x_um"]), float(pos["y_um"])
    log.debug(
        "backlash takeup at (%.2f, %.2f) um, overshoot %.1f um, %d passes",
        x, y, overshoot_um, passes,
    )
    for index in range(int(passes)):
        if index > 0:
            # Same reason as the mid-pass pause below: without a gap the
            # previous return and this overshoot could blend into one
            # motion, and the extra passes would settle nothing.
            time.sleep(settle_ms / 1000.0)
        # success=True alone means "command accepted" (profiles set
        # success_on_unconfirmed=True). Like move_xy_with_backlash, this
        # helper's contract needs readback evidence: an unconfirmed leg
        # could hand the stage to the following capture while it is still
        # travelling back from the overshoot point.
        r = _commands.move_xy(
            client, x - overshoot_um, y - overshoot_um, unit="um", tolerance=tolerance_um
        )
        if not r or not r.get("success") or not r.get("confirmed"):
            raise RuntimeError(f"backlash overshoot move failed or was unconfirmed: {r}")
        time.sleep(settle_ms / 1000.0)
        r = _commands.move_xy(client, x, y, unit="um", tolerance=tolerance_um)
        if not r or not r.get("success") or not r.get("confirmed"):
            raise RuntimeError(f"backlash return move failed or was unconfirmed: {r}")

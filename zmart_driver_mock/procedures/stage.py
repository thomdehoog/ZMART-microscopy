"""Procedures that only move the stage, and recording the origin.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

from typing import Any

from .. import get_commands as get
from .. import set_commands as setter
from ..configuration import sample_point, save

# How far back the backlash takeup steps before approaching again, in µm.
BACKLASH_STEP_UM = 50.0


def _require(outcome, what: str) -> None:
    if not outcome.confirmed:
        raise RuntimeError(f"{what} could not be confirmed: {outcome.reason}")


def backlash_takeup(ctx) -> dict[str, Any]:
    """Step back by -x and -y, then approach the same position again.

    A stage's screws have a little play. Arriving from the same side every
    time takes that play up in the same direction, so a position visited
    twice is visited exactly.

    Close to the lower edge of the travel range, the step back is shortened
    so that it stays inside the limits; right at the edge, that axis is not
    stepped back at all. The report says how far each axis stepped back.
    """
    here = get.raw_position(ctx).value_or_raise("the current position")
    stage = ctx.config.limits["stage_um"]
    step = {
        axis: max(0.0, min(BACKLASH_STEP_UM, here[axis] - stage[axis][0])) for axis in ("x", "y")
    }
    if step["x"] > 0 or step["y"] > 0:
        back = setter.move(
            ctx,
            x=here["x"] - step["x"],
            y=here["y"] - step["y"],
            focus=here["focus"],
            piezo=here["piezo"],
        )
        _require(back, "stepping back")
        forward = setter.move(
            ctx, x=here["x"], y=here["y"], focus=here["focus"], piezo=here["piezo"]
        )
        _require(forward, "the approach")
    return {"approach": "+x +y", "step_um": step}


def zero_piezo(ctx) -> dict[str, Any]:
    """Hand the piezo's share of the height over to the coarse drive."""
    here = get.raw_position(ctx).value_or_raise("the current position")
    outcome = setter.move(ctx, x=here["x"], y=here["y"], focus=here["z"], piezo=0.0)
    _require(outcome, "parking the piezo")
    return {"focus_um": here["z"], "piezo_um": 0.0}


def record_origin(ctx) -> dict[str, float]:
    """Save the current position as the origin, (0, 0, 0), for every later session.

    This is a setup step for the operator, not part of an experiment, which
    is why it is not offered through ``run_procedure``. It takes effect at
    the next connect. Returns the saved origin.
    """
    here = get.raw_position(ctx).value_or_raise("the current position")
    origin = sample_point(here, here["objective"], ctx.config)
    save("origin", origin, ctx.identity)
    return origin

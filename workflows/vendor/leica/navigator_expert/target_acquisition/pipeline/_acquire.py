"""_acquire.py -- stage-positioning helper for Steps 4 and 5.

After the driver-first migration, this module is motion only.
The driver's ``acquire_and_save`` triggers the frame and persists
it under the canonical layout; the pipeline positions the stage
before each call.

``acquire`` does verified job state, move z-wide, then move XY (with
backlash takeup via the driver primitive if configured). It does not
trigger a frame and returns None.
"""
from __future__ import annotations

import navigator_expert.driver as drv

from .context import Context
from ._job_state import ensure_job_state


def acquire(
    ctx: Context,
    job: str,
    x_um: float,
    y_um: float,
    zwide_um: float,
) -> None:
    """Position the stage for the next acquisition. Does not trigger a frame.

    Job transition goes through ensure_job_state (verified + settled).
    Z-wide first (job-scoped), then XY: with backlash takeup via
    ``drv.move_xy_with_backlash`` if stage_config["backlash"] is set,
    plain ``drv.move_xy`` otherwise. The caller then invokes
    ``drv.acquire_and_save`` to acquire and persist.
    """
    ensure_job_state(ctx, job)

    r = drv.move_z(ctx.client, job, zwide_um, z_mode="zwide")
    if not r or not r.get("success"):
        raise RuntimeError(f"move_z({zwide_um}, zwide) failed: {r!r}")

    backlash = ctx.stage_config.get("backlash")
    if backlash is not None:
        r = drv.move_xy_with_backlash(
            ctx.client, x_um, y_um,
            overshoot_um=backlash.get("overshoot_um", 50.0),
            settle_ms=backlash.get("settle_ms", 100),
        )
    else:
        r = drv.move_xy(ctx.client, x_um, y_um)
    if not r or not r.get("success"):
        raise RuntimeError(f"move_xy({x_um}, {y_um}) failed: {r!r}")

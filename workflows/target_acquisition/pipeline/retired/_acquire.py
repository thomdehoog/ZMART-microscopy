"""Stage-positioning helper for Steps 4 and 5.

This module owns motion only -- the driver's ``acquire`` + ``save``
pair triggers the frame and persists it under the canonical layout. The
pipeline positions the stage before each driver call.

``acquire`` verifies job state, moves z-wide, then moves XY (with
backlash takeup via the driver primitive if configured). It does not
trigger a frame and returns None.
"""

from __future__ import annotations

import navigator_expert as drv

from ._job_state import ensure_job_state
from .context import Context


def acquire(
    ctx: Context,
    job: str,
    x_um: float,
    y_um: float,
    zwide_um: float,
) -> None:
    """Position the stage for the next acquisition. Does not trigger a frame.

    Job transition goes through ensure_job_state (verified + settled).
    Z-wide first (job-scoped), then XY with backlash takeup. The caller then
    invokes ``drv.acquire`` and ``drv.save`` to acquire and persist.
    """
    ensure_job_state(ctx, job)

    r = drv.move_z(ctx.client, job, zwide_um, z_mode="zwide")
    if not r or not r.get("success"):
        raise RuntimeError(f"move_z({zwide_um}, zwide) failed: {r!r}")

    # Backlash is a motion utility with baked-in default params (decision §2b),
    # not config; call it bare.
    r = drv.move_xy_with_backlash(ctx.client, x_um, y_um)
    if not r or not r.get("success"):
        raise RuntimeError(f"move_xy({x_um}, {y_um}) failed: {r!r}")

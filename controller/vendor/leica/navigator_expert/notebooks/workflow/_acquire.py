"""_acquire.py -- shared acquire + save helpers for Steps 4 and 5.

acquire(): verified job state, move z-wide, backlash with known
  target coordinates, move XY, acquire_frame.
save_acquired(): persist a frame to disk (LAS X copy preferred,
  numpy fallback).
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path
import numpy as np
import tifffile

import navigator_expert.driver as drv

from .context import Context
from ._job_state import ensure_job_state


def acquire(
    ctx: Context,
    job: str,
    x_um: float,
    y_um: float,
    zwide_um: float,
) -> tuple[np.ndarray, Path]:
    """Move, acquire, return (image, lasx_path).

    Job transition goes through ensure_job_state (verified + settled).
    Z-wide first (job-scoped), then backlash overshoot + final XY
    (target-based, no get_xy needed), then acquire.
    """
    ensure_job_state(ctx, job)

    r = drv.move_z(ctx.client, job, zwide_um, z_mode="zwide")
    if not r or not r.get("success"):
        raise RuntimeError(f"move_z({zwide_um}, zwide) failed: {r!r}")

    backlash = ctx.stage_config.get("backlash")
    if backlash is not None:
        overshoot = backlash.get("overshoot_um", 50.0)
        settle_s = backlash.get("settle_ms", 100) / 1000.0
        r = drv.move_xy(ctx.client, x_um - overshoot, y_um - overshoot)
        if not r or not r.get("success"):
            print(f"[acquire] WARNING: backlash overshoot failed, "
                  f"continuing to final XY: {r!r}")
        time.sleep(settle_s)

    r = drv.move_xy(ctx.client, x_um, y_um)
    if not r or not r.get("success"):
        raise RuntimeError(f"move_xy({x_um}, {y_um}) failed: {r!r}")

    image, lasx_path = drv.acquire_frame(ctx.client, job)
    return image, lasx_path


def save_acquired(
    image: np.ndarray,
    lasx_path: Path | None,
    destination: Path,
) -> Path:
    """Persist an acquired frame to destination.

    Prefers copying the LAS X OME-TIFF (preserves metadata).
    Falls back to tifffile.imwrite from the numpy array.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)

    if lasx_path is not None and Path(lasx_path).exists():
        try:
            shutil.copy2(str(lasx_path), str(destination))
        except OSError:
            tifffile.imwrite(str(destination), image)
    else:
        tifffile.imwrite(str(destination), image)

    return destination

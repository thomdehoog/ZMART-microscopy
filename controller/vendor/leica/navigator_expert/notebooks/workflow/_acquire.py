"""_acquire.py -- shared acquire + save helpers for Steps 4 and 5.

acquire(): lazy job switch, move XY, move z-wide, acquire_frame.
save_acquired(): persist a frame to disk (LAS X copy preferred,
  numpy fallback).
"""
from __future__ import annotations

import shutil
from pathlib import Path
import numpy as np
import tifffile

import navigator_expert.driver as drv
from navigator_expert.driver.commands import select_job as drv_select_job

from .context import Context


def acquire(
    ctx: Context,
    job: str,
    x_um: float,
    y_um: float,
    zwide_um: float,
) -> tuple[np.ndarray, Path]:
    """Move, acquire, return (image, lasx_path).

    Lazy-switches job if ctx.current_job differs. Z is always
    commanded as z-wide (D2/D3).
    """
    client = ctx.client

    if ctx.current_job != job:
        result = drv_select_job(client, job)
        if not result or not result.get("success"):
            raise RuntimeError(f"select_job({job!r}) failed: {result!r}")
        ctx.current_job = job

    r = drv.move_xy(client, x_um, y_um)
    if not r or not r.get("success"):
        raise RuntimeError(f"move_xy({x_um}, {y_um}) failed: {r!r}")

    r = drv.move_z(client, job, zwide_um, z_mode="zwide")
    if not r or not r.get("success"):
        raise RuntimeError(f"move_z({zwide_um}, zwide) failed: {r!r}")

    image, lasx_path = drv.acquire_frame(client, job)
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

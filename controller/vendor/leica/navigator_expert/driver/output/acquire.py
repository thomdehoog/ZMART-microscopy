"""High-level acquire-and-load helpers.

One step up from the bare ``acquire`` command: orchestrate the full
acquire path (optional backlash takeup → fire acquire → poll for new
files → wait for size-stability → load TIFF) so cookbook scripts can
treat "take a picture" as a single call.

Two entry points:

    acquire_frame(client, job) -> (image, path)
        Single-frame acquire. Returns the loaded numpy array and the
        OME-TIFF path. Collapses 3-D OME-TIFFs to 2-D via the first
        plane (or the requested channel).

    acquire_stack(client, job) -> stack
        Z-stack acquire. Returns a 3-D numpy array (slices, h, w),
        whether LAS X exported the stack as one multi-page TIFF or
        as N single-frame TIFFs.

Backlash takeup is optional: pass ``backlash_params=stage_cfg["backlash"]``
to apply a +X +Y takeup (via ``stage_motion.correct_backlash``) before
the acquire. The default ``backlash_params=None`` skips it. Callers
that want compensation positioning at a known target should use
``stage_motion.move_xy_with_backlash`` *before* calling these helpers
(that's what the v3 workflow does); the ``backlash_params`` route
here applies post-move takeup at the current stage position.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np
import tifffile

from ..api import commands as _commands
from ..api import readers as _readers
from . import lasx_files as _file_confirmation
from ..motion.stage import correct_backlash


#: How long to wait for OME-TIFF files to be unlocked + size-stable on
#: the export drive after an acquire. Override per call if needed.
DEFAULT_FILE_STABILITY_TIMEOUT_S: int = 30


def _apply_backlash_if_requested(
    client: Any, backlash_params: dict | None,
) -> None:
    if backlash_params is None:
        return
    correct_backlash(
        client,
        overshoot_um=backlash_params.get("overshoot_um", 50.0),
        settle_ms=backlash_params.get("settle_ms", 100),
        tolerance_um=backlash_params.get("tolerance_um", 20.0),
    )


def _acquire_files(
    client: Any, job: str, *,
    backlash_params: dict | None,
    file_stability_timeout_s: int,
) -> list[Path]:
    """Fire one acquire and return the new OME-TIFF path(s).

    Internal helper shared by ``acquire_frame`` and ``acquire_stack``.
    Raises ``RuntimeError`` on any failure along the chain so callers
    can rely on the returned list being non-empty and the files being
    size-stable on disk.
    """
    _apply_backlash_if_requested(client, backlash_params)

    baseline = _file_confirmation.read_relative_path(client)
    t_start = time.time()
    result = _commands.acquire(client, job)
    if not result or not result.get("success"):
        raise RuntimeError(f"acquire failed: {result}")

    media_path = _readers.get_lasx_settings()["export"]["media_path"]
    detection = _file_confirmation.detect_new_files(
        client, baseline, media_path, acquire_start=t_start,
    )
    if not detection["success"]:
        raise RuntimeError(f"file detection failed: {detection.get('error')}")

    files = sorted(detection["image_files"])
    if not files:
        raise RuntimeError("acquire produced no image files")

    _file_confirmation.wait_all_stable(files, timeout=file_stability_timeout_s)
    return [Path(f) for f in files]


def acquire_frame(
    client: Any, job: str, *,
    backlash_params: dict | None = None,
    channel: int = 0,
    file_stability_timeout_s: int = DEFAULT_FILE_STABILITY_TIMEOUT_S,
) -> tuple[np.ndarray, Path]:
    """Acquire one frame and return ``(image, path)``.

    Args:
        client: LAS X API client.
        job: Job name to acquire (must be the selected job).
        backlash_params: ``stage_cfg["backlash"]`` to apply +X+Y takeup
            first; ``None`` skips the takeup. Default ``None``.
        channel: Channel index to load when LAS X exports one TIFF
            per channel; ignored for single-channel acquires.
        file_stability_timeout_s: Maximum wait for the OME-TIFF to
            settle on disk after the acquire returns.

    Returns:
        ``(image_array, path)``. The array is 2-D (H × W); 3-D OME-TIFF
        plane stacks collapse to the first plane.
    """
    files = _acquire_files(
        client, job,
        backlash_params=backlash_params,
        file_stability_timeout_s=file_stability_timeout_s,
    )
    idx = min(channel, len(files) - 1)
    path = files[idx]
    img = tifffile.imread(str(path))
    if img.ndim == 3:
        img = img[0]
    return img, path


def acquire_stack(
    client: Any, job: str, *,
    backlash_params: dict | None = None,
    file_stability_timeout_s: int = DEFAULT_FILE_STABILITY_TIMEOUT_S,
) -> np.ndarray:
    """Acquire a Z-stack and return it as a 3-D numpy array.

    LAS X may export a Z-stack either as one multi-page TIFF or as N
    single-frame TIFFs; this helper handles both transparently and
    always returns shape ``(slices, H, W)``.
    """
    files = _acquire_files(
        client, job,
        backlash_params=backlash_params,
        file_stability_timeout_s=file_stability_timeout_s,
    )
    if len(files) == 1:
        stack = tifffile.imread(str(files[0]))
        if stack.ndim == 2:
            stack = stack[np.newaxis, ...]
        return stack
    slices = [tifffile.imread(str(f)) for f in files]
    slices = [s[0] if s.ndim == 3 else s for s in slices]
    return np.array(slices)

"""LAS X source-side file primitives.

This module stays deliberately small. Exporter-specific collection lives
in ``lasx_native_autosave``; persistence and OME checks live in
``save`` / ``ome``.

Source naming (LAS X auto-export)::

    image--L0000--J08--E00--X00--Y00--T0000--Z00--C00.ome.tif
    metadata/image--L0000--J08--E00--T0000.ome.xml
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from .._file_utils import _wait_file_stable

if TYPE_CHECKING:
    from pathlib import Path

    from .capture import AcquisitionResult

log = logging.getLogger(__name__)


DEFAULT_FILE_STABILITY_TIMEOUT_S = 120
# Completeness (all timepoints/planes present) gets a budget in the same
# regime as file stability: a long time-series still flushing to disk
# after the job finished is healthy, not a failure.
DEFAULT_EXPORT_COMPLETION_TIMEOUT_S = 60.0
DEFAULT_EXPORT_COMPLETION_POLL_INTERVAL_S = 0.5


def read_relative_path(client):
    """Read ``RelativePathName`` from the LAS X data model.

    Returns an empty string on failure or when LAS X has not published a
    path in the current session.
    """
    try:
        return str(client.PyApiImagePathItem.Model.RelativePathName)
    except Exception as e:
        log.warning("Could not read RelativePathName: %s", e)
        return ""


# Exports often land on SMB shares whose mtime resolution is coarse (1-2 s)
# and whose clock can drift from the driver host. Without an allowance, a
# genuinely fresh export can be rejected as stale ("No ... files found").
# The residual risk — accepting a stale file written within the allowance
# before the acquire — is bounded by this constant and by
# _detect_from_mtime's refusal of ambiguous multi-candidate matches.
MTIME_SKEW_ALLOWANCE_S = 2.0


def _is_from_acquisition(path: Path, acq: AcquisitionResult) -> bool:
    """Return True when *path* was written at or after *acq* started.

    The comparison allows MTIME_SKEW_ALLOWANCE_S of skew: host wall-clock
    (acq.started_at) and file-server mtime are different clocks.
    """
    try:
        return path.stat().st_mtime >= acq.started_at - MTIME_SKEW_ALLOWANCE_S
    except OSError:
        return False


def _relative_posix(path: Path, base: Path, *, fallback_to_str: bool) -> str | None:
    """Return *path* relative to *base* as a POSIX string.

    When *path* is not under *base*, fall back to the POSIX form of the
    absolute path (``fallback_to_str=True``) or to ``None``
    (``fallback_to_str=False``).
    """
    try:
        return str(path.relative_to(base)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/") if fallback_to_str else None


def wait_all_stable(files, *, timeout=60, poll_interval=0.5, stable_readings=3):
    """Block until every file in *files* is unlocked and size-stable."""
    t0 = time.perf_counter()
    unstable = []

    for f in files:
        remaining = timeout - (time.perf_counter() - t0)
        if remaining <= 0:
            unstable.append(f)
            continue
        if not _wait_file_stable(f, remaining, poll_interval, stable_readings):
            unstable.append(f)

    if unstable:
        elapsed = time.perf_counter() - t0
        log.warning(
            "%d/%d files not stable after %.1fs",
            len(unstable),
            len(files),
            elapsed,
        )
        return {
            "success": False,
            "error": f"{len(unstable)} file(s) not stable after {timeout}s",
            "unstable": [str(f) for f in unstable],
        }

    elapsed = time.perf_counter() - t0
    log.debug("All %d files stable in %.1fs", len(files), elapsed)
    return {"success": True, "stable_count": len(files), "elapsed_s": elapsed}

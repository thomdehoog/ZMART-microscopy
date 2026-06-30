"""Pure derivations shared by state-reader backends."""

from __future__ import annotations

from ..utils import parse_tile_geometry


def job_by_name(jobs, job_name):
    """Return a job dict from a job list by LAS X job name."""
    if not jobs:
        return None
    for job in jobs:
        if job.get("Name") == job_name:
            return job
    return None


def selected_job(jobs):
    """Return the single selected job dict, or None if absent/ambiguous."""
    if not jobs:
        return None
    selected = [job for job in jobs if job.get("IsSelected") is True]
    return selected[0] if len(selected) == 1 else None


def fov_from_settings(settings):
    """Return current field of view in metres from LAS X job settings."""
    if not settings:
        return None
    try:
        geo = parse_tile_geometry(settings)
        return (geo["tile_w_um"] * 1e-6, geo["tile_h_um"] * 1e-6)
    except (KeyError, TypeError, ValueError):
        return None


def base_fov_from_settings(settings):
    """Return zoom-1 field of view in metres from LAS X job settings."""
    if not settings:
        return None
    try:
        geo = parse_tile_geometry(settings)
        zoom_info = settings.get("zoom") or {}
        current_zoom = float(zoom_info.get("current", 1) or 1)
        if current_zoom < 1:
            current_zoom = 1
        return (
            geo["tile_w_um"] * 1e-6 * current_zoom,
            geo["tile_h_um"] * 1e-6 * current_zoom,
        )
    except (KeyError, TypeError, ValueError):
        return None


def settings_geometry_ready(settings):
    """Return True when job settings carry a populated ``imageSize``.

    LAS X transiently dumps settings with a blank ``imageSize`` while the
    engine repopulates geometry after a zoom or format change. Both reader
    backends use this to skip those not-yet-fresh dumps.
    """
    return bool(settings.get("imageSize"))


def zwide_um_from_settings(settings):
    """Return the live z-wide position (µm) parsed from raw job settings.

    Flattens the API JSON via :func:`make_changeable_copy`, reads
    ``zPosition['z-wide']``, and applies the dict-shape guard: LAS X
    sometimes nests the value as ``{'position': ...}`` rather than a bare
    float. Raises ``RuntimeError`` when ``zPosition`` or the z-wide value
    is unavailable (almost always means the job is not selected or the
    LAS X version does not expose Z readback in this shape).
    """
    from ..commands.settings import make_changeable_copy

    ch = make_changeable_copy(settings)
    if not ch or "zPosition" not in ch:
        raise RuntimeError("zPosition not in job settings - LAS X version mismatch?")
    val = ch["zPosition"].get("z-wide")
    if isinstance(val, dict):
        val = val.get("position")
    if val is None:
        raise RuntimeError(f"z-wide readback missing; got {ch['zPosition']!r}")
    return float(val)

"""Pure derivations shared by state-reader backends."""

from __future__ import annotations

from ..runtime.utils import parse_tile_geometry


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
        # FOV scales as 1/zoom, so the zoom-1 (base) FOV is the current tile FOV
        # times the current zoom. Zoom < 1 is valid on hardware whose range
        # starts below 1 (e.g. 0.75); do not clamp it or the base FOV inflates.
        return (
            geo["tile_w_um"] * 1e-6 * current_zoom,
            geo["tile_h_um"] * 1e-6 * current_zoom,
        )
    except (KeyError, TypeError, ValueError):
        return None

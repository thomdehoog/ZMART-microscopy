"""Pure derivations shared by state-reader backends."""

from __future__ import annotations

from .parsing import parse_tile_geometry


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
        # Sub-unity zoom is legal hardware state (range starts at 0.75x);
        # only None/0 fall back to 1. Clamping <1 to 1 corrupted the base
        # FOV by up to ~33% at 0.75x.
        current_zoom = float(zoom_info.get("current", 1) or 1)
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


def stack_z_wide_um(settings, expected: int) -> list[float] | None:
    """Where each slice of the job's z-stack sits, in absolute z-wide um.

    ``None`` when the job takes no stack, which is every ordinary imaging job:
    a single plane is wherever the drive already is, and this has nothing to
    add. ``None`` too when the stack is there but says less than it must --
    a guessed position is worse than none, because it would place a picture
    somewhere nobody imaged.

    ``begin``, ``end`` and ``sections`` are authoritative and evenly spaced,
    which preserves a reversed stack (``begin > end``). ``stepSize`` is
    informational: LAS X rounds it for display, so deriving from it disagrees
    with the rig in the last decimal.

    *expected* is how many planes actually came back. A stack whose settings
    describe a different number is not describing this acquisition, and saying
    nothing is the only honest answer left.
    """
    from .parsing import make_changeable_copy

    try:
        stack = (make_changeable_copy(settings) or {}).get("stack")
    except Exception:  # noqa: BLE001 — a settings shape we cannot read says nothing
        stack = None
    raw = settings.get("stack") if isinstance(settings, dict) else None
    if not isinstance(stack, dict) or any(stack.get(k) is None for k in _STACK_NEEDS):
        stack = raw if isinstance(raw, dict) else None
    if not isinstance(stack, dict) or any(stack.get(k) is None for k in _STACK_NEEDS):
        return None

    try:
        begin, end = float(stack["begin"]), float(stack["end"])
        sections = int(stack["sections"])
    except (TypeError, ValueError):
        return None
    if sections != expected or sections < 1:
        return None
    if sections == 1:
        return [begin]
    step = (end - begin) / (sections - 1)
    return [begin + step * index for index in range(sections)]


#: What a stack block must carry before it can say where a slice was taken.
_STACK_NEEDS = ("begin", "end", "sections")


def z_um_from_settings(settings, key, *, client=None, job_name=None):
    """Return one z drive's position (µm) for the job whose settings these are.

    The settings' ``zPosition`` is the job's stored z reference. LAS X keeps
    it current for a drive that carries no z-stack and stops refreshing it
    for the drive the job's stack is on (measured on the simulator
    2026-08-25/26; the CAM API offers no other Z readout). So for that one
    drive the value here is stale by construction, and this function falls
    back to the saved experiment instead: ``PyApiSaveExperiment`` makes
    LAS X write the ``.lrp`` from its live block, and the job's Master
    setting carries ``ZPosition`` for the drive its ``ZUseModeName`` names.
    That costs one save (~0.4 s) and needs *client* and *job_name*; the
    free drive costs nothing extra — the decision is a lookup on the
    ``stack`` block already in *settings*. A stacked drive asked for
    without a client refuses rather than returning the stale number.

    Canonical home of the z-readback shape quirk: LAS X sometimes nests the
    value as ``{'position': ...}`` rather than a bare float, so after
    flattening the API JSON via :func:`make_changeable_copy` and reading
    ``zPosition[key]``, the dict-shape guard unwraps ``'position'``. Raises
    ``RuntimeError`` when ``zPosition`` or the per-drive value is
    unavailable (almost always means the job is not selected or the
    LAS X version does not expose Z readback in this shape).
    """
    from .parsing import make_changeable_copy

    ch = make_changeable_copy(settings)
    if ch and (ch.get("stack") or {}).get("zDrive") == key:
        return _z_um_from_saved_experiment(client, job_name, key)
    if not ch or "zPosition" not in ch:
        raise RuntimeError("zPosition not in job settings - LAS X version mismatch?")
    val = ch["zPosition"].get(key)
    if isinstance(val, dict):
        val = val.get("position")
    if val is None:
        raise RuntimeError(f"{key} readback missing; got {ch['zPosition']!r}")
    return float(val)


def _z_um_from_saved_experiment(client, job_name, key):
    """*job_name*'s ``ZPosition`` for *key* (µm), read from a fresh ``.lrp``.

    The file holds one ``ZPosition`` per setting definition, for the drive
    its ``ZUseModeName`` names (LAS X's own spelling, ``"z-galvo"`` or
    ``"z-wide"``). Asking for the other drive is refused rather than
    answered with the wrong axis under the right label.
    """
    if client is None or job_name is None:
        raise RuntimeError(
            f"{key} carries the job's z-stack, so its settings value is stale; reading it "
            f"needs the client and the job name to save the experiment"
        )
    lrp_data = save_and_read_lrp(client)
    if lrp_data is None:
        raise RuntimeError(
            f"{key} carries {job_name!r}'s z-stack, so its settings value is stale, and the "
            f"experiment save failed - no current Z available"
        )
    job = lrp_data["jobs"].get(job_name)
    if job is None:
        raise RuntimeError(
            f"No such job {job_name!r} in the saved experiment; it has {list(lrp_data['jobs'])}"
        )
    attrs = job.get("Master", {}).get("attrs", {})
    if attrs.get("ZUseModeName") != key:
        raise RuntimeError(
            f"The saved experiment holds {job_name!r}'s ZPosition for "
            f"{attrs.get('ZUseModeName')!r}, not for {key!r}"
        )
    raw = attrs.get("ZPosition")
    if raw is None:
        raise RuntimeError(f"{job_name!r}'s Master setting carries no ZPosition")
    return float(raw) * 1e6


def save_and_read_lrp(client, **kwargs):
    """The driver's own save-and-parse, imported late: ``scanfields.files``
    reaches ``commands.gate``, which reaches the readers this module belongs to."""
    from ..scanfields.files import save_and_read_lrp as _save_and_read_lrp

    return _save_and_read_lrp(client, **kwargs)


def zwide_um_from_settings(settings, *, client=None, job_name=None):
    """Return the z-wide position (µm); see :func:`z_um_from_settings`."""
    return z_um_from_settings(settings, "z-wide", client=client, job_name=job_name)

"""
Settings parsing.
=================
Transforms the raw job settings JSON returned by ``readers.get_job_settings``
into a flat, navigable dict with normalized field names.

``make_changeable_copy`` is the only public function. It:

    1. Validates that required top-level keys exist (schema guard).
    2. Copies and normalises each ``activeSettings`` entry, adding
       private keys like ``_beamRoute``, ``_lineIndex``, and ``_index``
       so that confirm functions can locate detectors, lasers, and
       filter wheels by route/index without re-parsing the raw JSON.
    3. Conditionally includes ``stack``, ``zPosition``, and ``time``
       sections when present.

The output dict is what every ``_confirm_*`` function in ``confirmations.py``
reads via ``_readback()``.

Dependency direction:
    - Imports: ``readers.parsing`` (``_safe_float``, via a lazy shim).
    - Imported by: ``confirmations`` (``_readback`` calls ``make_changeable_copy``),
      ``__init__`` (re-export).
"""


# =============================================================================
# make_changeable_copy
# =============================================================================

_REQUIRED_SETTINGS_KEYS = ["zoom", "scanSpeed", "activeSettings"]


def _safe_float(val, default=None):
    """Lazy shim over :func:`readers.parsing._safe_float`.

    The import happens at call time on purpose: a module-level
    ``from ..readers`` here would close an import cycle, because
    ``readers.derived`` imports this module while the readers package is
    still initializing.
    """
    from ..readers.parsing import _safe_float as _impl

    return _impl(val, default)


def make_changeable_copy(settings):
    """Transform raw job settings JSON into a flat, navigable dict.

    Validates that required keys exist. Raises ValueError on schema mismatch.
    """
    if settings is None:
        return None

    # Schema validation — fail loud on missing required keys
    missing = [k for k in _REQUIRED_SETTINGS_KEYS if k not in settings]
    if missing:
        raise ValueError(
            f"Job settings missing required keys: {missing}. "
            f"LAS X version mismatch or corrupt settings JSON. "
            f"Available keys: {list(settings.keys())}"
        )

    ch = {}

    # Direct fields
    ch["zoom"] = settings.get("zoom", {"current": None})
    ch["scanSpeed"] = settings.get("scanSpeed", {"value": None, "isResonant": False})
    ch["scanMode"] = settings.get("scanMode", "")
    ch["sequentialMode"] = settings.get("sequentialMode", "")
    ch["scanFieldRotation"] = settings.get("scanFieldRotation", {"value": 0.0})
    ch["format"] = settings.get("format", "")
    ch["objective"] = settings.get("objective", {"name": "", "magnification": 0})

    # Active settings
    active = []
    for s in settings.get("activeSettings", []):
        entry = {
            "_index": s.get("index", s.get("_index", 0)),
            "_name": s.get("name", s.get("_name", "")),
            "frameAccumulation": s.get("frameAccumulation", 1),
            "frameAverage": s.get("frameAverage", 1),
            "lineAccumulation": s.get("lineAccumulation", 1),
            "lineAverage": s.get("lineAverage", 1),
            "pinholeAiry": s.get("pinholeAiry", {"value": 1.0}),
        }
        # Detectors with _beamRoute
        detectors = []
        for d in s.get("activeDetectors", []):
            det = dict(d)
            det["_beamRoute"] = d.get("beamRoute", d.get("_beamRoute", ""))
            detectors.append(det)
        entry["activeDetectors"] = detectors

        # Laser lines with _beamRoute and _lineIndex
        lasers = []
        for laser_raw in s.get("activeLaserLines", []):
            laser = dict(laser_raw)
            laser["_beamRoute"] = laser_raw.get("beamRoute", laser_raw.get("_beamRoute", ""))
            laser["_lineIndex"] = laser_raw.get("lineIndex", laser_raw.get("_lineIndex", 0))
            lasers.append(laser)
        entry["activeLaserLines"] = lasers

        # Filter wheels
        if "filterWheels" in s:
            fws = []
            for fw_raw in s["filterWheels"]:
                fw = dict(fw_raw)
                fw["_beamRoute"] = fw_raw.get("beamRoute", fw_raw.get("_beamRoute", ""))
                fws.append(fw)
            entry["filterWheels"] = fws

        active.append(entry)
    ch["activeSettings"] = active

    # Z-stack — only include if scan mode involves Z
    scan_mode = ch.get("scanMode", "")
    has_z = "z" in scan_mode.lower() if scan_mode else False
    stack_raw = settings.get("stack")

    if has_z or (stack_raw and isinstance(stack_raw, dict)):
        if stack_raw and isinstance(stack_raw, dict):
            begin = _safe_float(stack_raw.get("begin"))
            end = _safe_float(stack_raw.get("end"))
            step_size = _safe_float(stack_raw.get("stepSize"))
            size = _safe_float(stack_raw.get("size"))
            sections = stack_raw.get("sections")  # number of z-planes
            z_drive = stack_raw.get("mode")  # e.g. "z-galvo", "z-wide"
            # Compute size from begin/end if not provided
            if size is None and begin is not None and end is not None:
                size = abs(end - begin)
            ch["stack"] = {
                "begin": begin,
                "end": end,
                "stepSize": step_size,
                "size": size,
                "sections": sections,
                "zDrive": z_drive,
            }
        else:
            ch["stack"] = {
                "begin": None,
                "end": None,
                "stepSize": None,
                "size": None,
                "sections": None,
                "zDrive": None,
            }

    # Z position (z-galvo / z-wide readback)
    zp_raw = settings.get("zPosition")
    if zp_raw and isinstance(zp_raw, dict):
        ch["zPosition"] = {}
        for key, entry in zp_raw.items():
            ch["zPosition"][key] = (
                _safe_float(entry.get("position")) if isinstance(entry, dict) else None
            )

    # Time series
    time_raw = settings.get("time")
    if time_raw and isinstance(time_raw, dict):
        ch["time"] = dict(time_raw)

    return ch

"""Parsers for the strings and dicts LAS X hands back.

Pure functions with no API-object knowledge: safe type conversion, format
strings ("512 x 512"), the micron-unit mojibake repair, and the tile
geometry derived from raw job settings. Shared by the readers, the command
wrappers, scanfields, and acquisition — all the places LAS X text arrives.

``make_changeable_copy`` is the largest parser here: it transforms the raw
job-settings JSON from ``get_job_settings`` into a flat, navigable dict
(validated required keys; ``_beamRoute``/``_lineIndex``/``_index`` markers so
detectors, lasers, and filter wheels can be located without re-parsing; the
``stack``/``zPosition``/``time`` sections when present). The confirm
functions in ``commands/confirmations.py`` read their readback through it.
"""

import re


def _safe_float(val, default=None):
    """Convert val to float. Returns default on failure or None input."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _hw_get(d, key, default=None):
    """Safe dict/object getter for hardware info navigation."""
    try:
        if isinstance(d, dict):
            return d.get(key, default)
        return getattr(d, key, default)
    except Exception:
        return default


def parse_format(format_str):
    """Parse '512 x 512' into ``(512, 512)``."""
    parts = format_str.split("x")
    if len(parts) != 2:
        raise ValueError(f"Cannot parse format: '{format_str}'")
    return int(parts[0].strip()), int(parts[1].strip())


# =============================================================================
# Image / tile geometry
# =============================================================================


def normalize_unit_mojibake(text):
    """Map LAS X micron-unit spellings — including mojibake — to ASCII ``um``.

    LAS X emits size strings like ``'290.63 µm x 290.63 µm'``; on some
    delivery paths the UTF-8 ``µ`` (0xC2 0xB5) is re-decoded as Latin-1 and
    arrives as ``'Âµm'``. Normalize ``'Âµm'``, ``'µm'``, and Greek-mu
    ``'μm'`` to plain ``'um'`` so unit parsers see one shape. Canonical home
    of this vendor quirk — parsers must not re-handle ``'Â'`` themselves.
    """
    return (
        text.replace("Âµm", "um")  # 'Âµm': UTF-8 'µm' re-decoded as Latin-1
        .replace("µm", "um")  # 'µm': micro sign
        .replace("μm", "um")  # 'μm': Greek small letter mu
    )


def parse_tile_geometry(settings):
    """Extract complete tile geometry from raw job settings.

    Parses ``imageSize``, ``pixelSize``, and ``format`` and returns
    tile dimensions, pixel size, pixel count, and the bounding box
    of the current tile centered on the stage position.

    Args:
        settings: Raw job settings dict from ``get_job_settings()``.

    Returns:
        dict with keys::

            tile_w_um, tile_h_um    — tile dimensions in µm
            pixel_w_nm, pixel_h_nm  — pixel size in nm
            pixel_w_um, pixel_h_um  — pixel size in µm
            pixels_x, pixels_y      — pixel count per axis
            bbox                    — {x_min, x_max, y_min, y_max} in µm

    Raises:
        ValueError: If ``imageSize`` is missing or unparseable.
    """

    def _parse_dim_um(raw):
        """Parse 'W unit x H unit' → (w_um, h_um). Supports mm, µm, nm."""
        raw = normalize_unit_mojibake(raw)
        if "mm" in raw:
            scale = 1000.0
        elif "nm" in raw:
            scale = 0.001
        else:  # µm (default)
            scale = 1.0
        cleaned = re.sub(r"[nmu]*m", "", raw)
        parts = cleaned.split("x")
        if len(parts) != 2:
            return None, None
        try:
            return float(parts[0].strip()) * scale, float(parts[1].strip()) * scale
        except ValueError:
            return None, None

    # ── tile size (µm) ──
    raw_size = settings.get("imageSize", "")
    tile_w, tile_h = _parse_dim_um(raw_size)
    if tile_w is None:
        raise ValueError(f"Cannot parse imageSize: '{raw_size}'")

    # ── pixel size (µm, converted to nm for output) ──
    raw_px = settings.get("pixelSize", "")
    pixel_w_um, pixel_h_um = _parse_dim_um(raw_px)
    pixel_w_nm = pixel_w_um * 1000 if pixel_w_um is not None else None
    pixel_h_nm = pixel_h_um * 1000 if pixel_h_um is not None else None

    # ── format (pixel count) ──
    raw_fmt = settings.get("format", "")
    fmt_parts = raw_fmt.split("x")
    if len(fmt_parts) == 2:
        pixels_x = int(fmt_parts[0].strip())
        pixels_y = int(fmt_parts[1].strip())
    else:
        pixels_x = None
        pixels_y = None

    # ── bounding box (µm) ──
    stage = settings.get("xyStage", {})
    cx = float(stage.get("posX", 0))
    cy = float(stage.get("posY", 0))
    bbox = {
        "x_min": cx - tile_w / 2,
        "x_max": cx + tile_w / 2,
        "y_min": cy - tile_h / 2,
        "y_max": cy + tile_h / 2,
    }

    return {
        "tile_w_um": tile_w,
        "tile_h_um": tile_h,
        "pixel_w_nm": pixel_w_nm,
        "pixel_h_nm": pixel_h_nm,
        "pixel_w_um": pixel_w_um,
        "pixel_h_um": pixel_h_um,
        "pixels_x": pixels_x,
        "pixels_y": pixels_y,
        "bbox": bbox,
    }


# =============================================================================
# Raw job settings -> flat navigable dict
# =============================================================================

_REQUIRED_SETTINGS_KEYS = ["zoom", "scanSpeed", "activeSettings"]


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

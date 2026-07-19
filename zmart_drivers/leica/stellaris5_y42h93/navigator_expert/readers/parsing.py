"""Parsers for the strings and dicts LAS X hands back.

Pure functions with no API-object knowledge: safe type conversion, format
strings ("512 x 512"), the micron-unit mojibake repair, and the tile
geometry derived from raw job settings. Shared by the readers, the command
wrappers, scanfields, and acquisition — all the places LAS X text arrives.
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

"""
Utility functions.
==================
Shared low-level helpers with no domain knowledge. Used across the driver
for format parsing, safe type conversion, timing envelope construction,
and structured log entry creation.

Every function here is a pure utility — no imports from other driver
modules, no knowledge of LAS X, microscopes, or API objects.
"""

import time
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
    """Parse '512 x 512' → (512, 512)."""
    parts = format_str.split("x")
    if len(parts) != 2:
        raise ValueError(f"Cannot parse format: '{format_str}'")
    return int(parts[0].strip()), int(parts[1].strip())


def format_to_str(width, height):
    """Convert (512, 512) → '512 x 512'."""
    return f"{width} x {height}"


# =============================================================================
# Image / tile geometry
# =============================================================================

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
    # ── tile size (µm) ──
    raw_size = settings.get("imageSize", "")
    cleaned = re.sub(r"[\u00b5\u03bc]?m", "", raw_size)
    parts = cleaned.split("x")
    if len(parts) != 2:
        raise ValueError(f"Cannot parse imageSize: '{raw_size}'")
    tile_w = float(parts[0].strip())
    tile_h = float(parts[1].strip())

    # ── pixel size (nm) ──
    raw_px = settings.get("pixelSize", "")
    cleaned_px = re.sub(r"n[\u00b5\u03bc]?m", "", raw_px).replace("nm", "")
    px_parts = cleaned_px.split("x")
    if len(px_parts) == 2:
        pixel_w_nm = float(px_parts[0].strip())
        pixel_h_nm = float(px_parts[1].strip())
    else:
        pixel_w_nm = None
        pixel_h_nm = None

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
        "pixel_w_um": pixel_w_nm / 1000 if pixel_w_nm else None,
        "pixel_h_um": pixel_h_nm / 1000 if pixel_h_nm else None,
        "pixels_x": pixels_x,
        "pixels_y": pixels_y,
        "bbox": bbox,
    }


# =============================================================================
# Structured log entries
# =============================================================================

def _make_log_entry(level, msg):
    """Build a timestamped log entry dict.

    Every pluggable function in the pipeline accumulates these entries in
    its ``logs`` list. The backbone collects them into a single ordered
    trace so the caller has full visibility into what happened.

    Args:
        level: One of "debug", "info", "warning", "error".
        msg: Human-readable log message.

    Returns:
        {"ts": float, "level": str, "msg": str}
    """
    return {"ts": time.time(), "level": level, "msg": msg}


# =============================================================================
# Timing envelope
# =============================================================================

def _make_timing(pre_check_s=0.0, setup_s=0.0, fire_s=0.0, check_s=0.0,
                 confirm_s=0.0, total_s=0.0, attempts=1,
                 confirm_attempts=0, method="sync"):
    """Build a timing dict for command result envelopes.

    Args:
        pre_check_s: Time spent in pre-fire check (e.g. idle wait).
        setup_s: Time writing parameters to the model.
        fire_s: Time for UpdateAwaitReceipt transport.
        check_s: Time for API error check.
        confirm_s: Time spent in confirm_fn.
        total_s: Wall-clock time for the entire operation.
        attempts: Number of fire-block attempts (1 + retries).
        confirm_attempts: Number of confirm-wrapper attempts.
        method: 'sync' or 'async'.

    Returns:
        Timing dict with all keys above.
    """
    return {
        "pre_check_s": pre_check_s,
        "setup_s": setup_s,
        "fire_s": fire_s,
        "check_s": check_s,
        "confirm_s": confirm_s,
        "total_s": total_s,
        "attempts": attempts,
        "confirm_attempts": confirm_attempts,
        "method": method,
    }

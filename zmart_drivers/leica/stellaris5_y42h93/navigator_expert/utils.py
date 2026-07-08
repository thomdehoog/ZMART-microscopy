"""
Utility functions.
==================
Shared low-level helpers with no domain knowledge. Used across the driver
for format parsing, safe type conversion, timing envelope construction,
and structured log entry creation.

Every function here is a pure utility — no imports from other driver
modules, no knowledge of LAS X, microscopes, or API objects.
"""

import re
import time

# ---------------------------------------------------------------------------
# Timeouts (seconds).
# NOTE: runtime consumers (commands.dispatch, commands.confirmations,
# commands.confirm_select_job) read these at call time (``utils.CONFIRM_POLL_S``),
# so reassigning ``utils.RECEIPT_TIMEOUT``/``utils.CONFIRM_POLL_S`` at runtime
# (e.g. a test monkeypatch) takes effect. Exception: ``config.profiles``
# captures them into dataclass field defaults at import, so profile fields
# keep the values from process start. To tune for your hardware, edit these
# constants.
# ---------------------------------------------------------------------------
RECEIPT_TIMEOUT = 2  # UpdateAwaitReceipt transport ACK deadline (a true timeout:
# expiry after transport retries is a hard delivery failure)
CONFIRM_POLL_S = 3  # Per-attempt readback poll window (NOT a timeout): poll the
# readback for this long, then re-fire and poll again up to max_confirm_attempts;
# exhaustion returns unconfirmed, never a hard fail.

# ---------------------------------------------------------------------------
# Galvo pan calibration.
# ---------------------------------------------------------------------------
# The physics
# ------------
# A pan value is a dimensionless angular fraction of the galvo's range.
# Sample displacement per unit of pan = (galvo angle) x (objective focal
# length). Base FOV is also proportional to focal length. So the
# displacement-per-unit-pan (PAN_SCALE) scales linearly with base FOV.
# Writing it in physical form:
#
#     pan_scale_um = base_fov_um * GALVO_FIELD_FRACTION / PAN_LIMIT
#
# where each factor has a concrete meaning:
#
#  PAN_LIMIT (0.00775) — max software-enforced pan value per axis
#                        (hard limit in LAS X; known exactly).
#
#  GALVO_FIELD_FRACTION (0.667) — fraction of base FOV that a maximum
#                                 pan shifts the sample by. This is a
#                                 scope-level constant (galvo mirror
#                                 mechanical range x scan-lens focal
#                                 length), independent of objective.
#                                 Measured on ZMB STELLARIS 8
#                                 (2026-04-23) at 0.667 +- 0.001 across
#                                 10x/20x/40x objectives; matches 2/3
#                                 to 3 decimal places.
#
# Equivalent empirical shortcut:
#     pan_scale_um = base_fov_um * 86.06  (= GALVO_FIELD_FRACTION / PAN_LIMIT)
#
# Callers should use the helper below rather than re-deriving:
#
#     base_fov_um = get_base_fov(client, job)[0] * 1e6
#     pan_scale_um = base_fov_um * GALVO_FIELD_FRACTION / PAN_LIMIT
#
# Re-measure GALVO_FIELD_FRACTION on each new
# instrument — GALVO_FIELD_FRACTION is scope-specific but fixed per
# scope.
#
# WARNING: the committed value was measured on the ZMB STELLARIS 8 while
# this driver targets the STELLARIS 5 (y42h93). Unlike the orientation, which
# is measured per microscope and saved to a config, this constant is not
# stored per machine, so a per-scope error can only be corrected by editing it
# here — verify it before trusting galvo-pan targeting on a new instrument.
PAN_LIMIT = 0.00775  # max pan value per axis (software limit)
GALVO_FIELD_FRACTION = 0.667  # sample shift at max pan, as fraction of base FOV


def pan_scale_um_from_base_fov(base_fov_um):
    """um of sample displacement per unit of pan, for an objective
    with the given base FOV (FOV at zoom 1, in um).

    See module header for the physics: at max pan (``PAN_LIMIT``) the
    galvo shifts the sample by ``GALVO_FIELD_FRACTION`` of base FOV;
    for any smaller pan value the displacement scales linearly.

    Args:
        base_fov_um: Objective's base FOV in um (from ``get_base_fov``).

    Returns:
        um displacement per unit of pan.
    """
    return base_fov_um * GALVO_FIELD_FRACTION / PAN_LIMIT


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


def _make_timing(
    pre_check_s=0.0,
    setup_s=0.0,
    fire_s=0.0,
    check_s=0.0,
    confirm_s=0.0,
    total_s=0.0,
    attempts=1,
    confirm_attempts=0,
    method="async",
):
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

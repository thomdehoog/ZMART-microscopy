"""
Scan-field scanning template editors.
=======================================
Editors for scan direction, zoom, image format, phase correction,
resonant scanner, bit depth, and scan field rotation.

Dependency direction:
    - Imports: ``scanning_template_editors`` (helpers), stdlib.
    - Imported by: ``__init__`` (re-export).
"""

import logging

from ._primitives import (
    _set_job_attr,
    _verify_job_attr,
    _verify_job_attr_float,
)

log = logging.getLogger(__name__)


# =============================================================================
# Zoom
# =============================================================================

def lrp_set_zoom(lrp_path, value, job_name):
    """Set Zoom on all settings in a job.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        value: Target zoom factor (numeric, e.g. ``1``, ``2``, ``1.5``).
        job_name: Name of the job to modify.

    Returns:
        Number of attributes changed.
    """
    return _set_job_attr(lrp_path, "Zoom", str(value), job_name, "lrp_set_zoom")


def lrp_verify_zoom(lrp_path, value, job_name, tolerance=0.01):
    """Verify Zoom for a job (with tolerance)."""
    return _verify_job_attr_float(lrp_path, "Zoom", float(value), job_name,
                                  tolerance)


# =============================================================================
# Scan speed
# =============================================================================

def lrp_set_scan_speed(lrp_path, value, job_name):
    """Set ScanSpeed on all settings in a job.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        value: Target scan speed (int, e.g. ``100``, ``200``, ``400``).
        job_name: Name of the job to modify.

    Returns:
        Number of attributes changed.
    """
    return _set_job_attr(lrp_path, "ScanSpeed", str(int(value)), job_name,
                         "lrp_set_scan_speed")


def lrp_verify_scan_speed(lrp_path, value, job_name):
    """Verify ScanSpeed for a job (exact match)."""
    return _verify_job_attr(lrp_path, "ScanSpeed", str(int(value)), job_name)


# =============================================================================
# Image format (InDimension + OutDimension)
# =============================================================================

def lrp_set_image_format(lrp_path, value, job_name):
    """Set image format (InDimension and OutDimension) on all settings.

    Accepts either an int (e.g. ``1024``) or a string like
    ``"1024x1024"``.  Both dimensions are set to the same value.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        value: Target resolution (int or ``"NxN"`` string).
        job_name: Name of the job to modify.

    Returns:
        Number of attributes changed.
    """
    if isinstance(value, str) and "x" in value:
        dim = str(int(value.split("x")[0]))
    else:
        dim = str(int(value))

    count = 0
    count += _set_job_attr(lrp_path, "InDimension", dim, job_name,
                           "lrp_set_image_format")
    count += _set_job_attr(lrp_path, "OutDimension", dim, job_name,
                           "lrp_set_image_format")
    return count


def lrp_verify_image_format(lrp_path, value, job_name):
    """Verify InDimension and OutDimension for a job (exact match)."""
    if isinstance(value, str) and "x" in value:
        dim = str(int(value.split("x")[0]))
    else:
        dim = str(int(value))

    return (_verify_job_attr(lrp_path, "InDimension", dim, job_name) and
            _verify_job_attr(lrp_path, "OutDimension", dim, job_name))


# =============================================================================
# Scan direction (bidirectional / unidirectional)
# =============================================================================

SCAN_DIRECTIONS = {
    0: "UnknownDirection",   # LAS X uses this name for bidirectional
    1: "Unidirectional",
}


def lrp_set_scan_direction(lrp_path, bidirectional, job_name):
    """Set scan direction (bidirectional or unidirectional).

    Args:
        lrp_path: Path to the ``.lrp`` file.
        bidirectional: ``True`` for bidirectional, ``False`` for
            unidirectional.
        job_name: Name of the job to modify.

    Returns:
        Number of attributes changed.
    """
    mode = 0 if bidirectional else 1
    name = SCAN_DIRECTIONS[mode]
    count = 0
    count += _set_job_attr(lrp_path, "ScanDirectionX", str(mode), job_name,
                           "lrp_set_scan_direction")
    count += _set_job_attr(lrp_path, "ScanDirectionXName", name, job_name,
                           "lrp_set_scan_direction")
    return count


def lrp_verify_scan_direction(lrp_path, bidirectional, job_name):
    """Verify ScanDirectionX for a job (exact match)."""
    mode = 0 if bidirectional else 1
    return _verify_job_attr(lrp_path, "ScanDirectionX", str(mode), job_name)


# =============================================================================
# PhaseX (bidirectional phase correction)
# =============================================================================

def lrp_set_phase_x(lrp_path, value, job_name):
    """Set PhaseX on all settings in a job.

    PhaseX controls the phase correction for bidirectional scanning.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        value: Target PhaseX value (float).
        job_name: Name of the job to modify.

    Returns:
        Number of attributes changed.
    """
    return _set_job_attr(lrp_path, "PhaseX", str(value), job_name,
                         "lrp_set_phase_x")


def lrp_verify_phase_x(lrp_path, value, job_name, tolerance=0.1):
    """Verify PhaseX for a job (with tolerance)."""
    return _verify_job_attr_float(lrp_path, "PhaseX", float(value), job_name,
                                  tolerance)


# =============================================================================
# Resonant scanner
# =============================================================================

def lrp_set_resonant_scanner(lrp_path, enable, job_name):
    """Enable or disable the resonant scanner for a job.

    Sets ``IsResonantScanner`` and ``IsResonantConfocalScanner``.
    LAS X recalculates ``ScanSpeed``, timing attributes, and other
    dependent settings when it reloads the template.

    Note: LAS X does not restore previous ``ScanSpeed`` / ``Zoom``
    values when toggling — set those explicitly afterwards if needed.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        enable: ``True`` to enable, ``False`` to disable.
        job_name: Name of the job to modify.

    Returns:
        Number of attributes changed.
    """
    val = "1" if enable else "0"
    count = 0
    count += _set_job_attr(lrp_path, "IsResonantScanner", val, job_name,
                           "lrp_set_resonant_scanner")
    count += _set_job_attr(lrp_path, "IsResonantConfocalScanner", val,
                           job_name, "lrp_set_resonant_scanner")
    return count


def lrp_verify_resonant_scanner(lrp_path, enable, job_name):
    """Verify IsResonantScanner for a job (exact match)."""
    val = "1" if enable else "0"
    return _verify_job_attr(lrp_path, "IsResonantScanner", val, job_name)


# =============================================================================
# Bit depth
# =============================================================================

def lrp_set_bit_depth(lrp_path, value, job_name):
    """Set BitSize on all settings in a job.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        value: Target bit depth (``8``, ``12``, or ``16``).
        job_name: Name of the job to modify.

    Returns:
        Number of attributes changed.
    """
    value = int(value)
    if value not in (8, 12, 16):
        log.error("lrp_set_bit_depth: invalid value %r (expected 8, 12, or 16)",
                  value)
        return 0
    return _set_job_attr(lrp_path, "BitSize", str(value), job_name,
                         "lrp_set_bit_depth")


def lrp_verify_bit_depth(lrp_path, value, job_name):
    """Verify BitSize for a job (exact match)."""
    return _verify_job_attr(lrp_path, "BitSize", str(int(value)), job_name)


# =============================================================================
# Scan field rotation
# =============================================================================

def lrp_set_scan_field_rotation(lrp_path, value, job_name):
    """Set RotatorAngle on all settings in a job.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        value: Target rotation angle in degrees (float).
        job_name: Name of the job to modify.

    Returns:
        Number of attributes changed.
    """
    return _set_job_attr(lrp_path, "RotatorAngle", str(value), job_name,
                         "lrp_set_scan_field_rotation")


def lrp_verify_scan_field_rotation(lrp_path, value, job_name, tolerance=0.01):
    """Verify RotatorAngle for a job (with tolerance)."""
    return _verify_job_attr_float(lrp_path, "RotatorAngle", float(value),
                                  job_name, tolerance)


# =============================================================================
# Galvo pan (PanFirstDim + PanSecondDim)
# =============================================================================

def lrp_set_pan(lrp_path, x, y, job_name):
    """Set galvo pan on all settings in a job.

    Sets ``PanFirstDim`` (X) and ``PanSecondDim`` (Y) on every
    ``ATLConfocalSettingDefinition`` in the job.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        x: Pan X value (float).
        y: Pan Y value (float).
        job_name: Name of the job to modify.

    Returns:
        Number of attributes changed.
    """
    count = 0
    count += _set_job_attr(lrp_path, "PanFirstDim", str(x), job_name,
                           "lrp_set_pan")
    count += _set_job_attr(lrp_path, "PanSecondDim", str(y), job_name,
                           "lrp_set_pan")
    return count


def lrp_verify_pan(lrp_path, x, y, job_name, tolerance=0.001):
    """Verify PanFirstDim and PanSecondDim for a job (with tolerance)."""
    return (_verify_job_attr_float(lrp_path, "PanFirstDim", float(x),
                                   job_name, tolerance) and
            _verify_job_attr_float(lrp_path, "PanSecondDim", float(y),
                                   job_name, tolerance))


def reset_pan(client, job_name):
    """Atomic LRP edit: set galvo pan to ``(0, 0)`` for *job_name*.

    Used to return the scan field to its un-panned position — typically as
    the final step of a cookbook so a subsequent run starts from a known
    state. Verifies the change before returning.
    """
    from ...templates.files import TEMPLATE_XML
    from ...templates.transaction import apply_lrp_change
    apply_lrp_change(
        client, TEMPLATE_XML,
        lambda p: lrp_set_pan(p, 0.0, 0.0, job_name),
        verify_fn=lambda p: lrp_verify_pan(p, 0.0, 0.0, job_name),
    )


def lrp_get_pan(lrp_path, job_name):
    """Read ``(PanFirstDim, PanSecondDim)`` for a job from the LRP.

    Used by relative-pan callers that need the current pan to compose a
    delta. Returns ``(0.0, 0.0)`` if the job or attributes are absent --
    that matches LAS X's "no pan written yet" state.

    Delegates to ``driver.templates.edits.read.lrp_get_pan``.
    """
    from ...templates.edits.read import lrp_get_pan as _lrp_get_pan
    return _lrp_get_pan(lrp_path, job_name)

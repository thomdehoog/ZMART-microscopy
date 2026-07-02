"""
Z-stack scanning template editors.
====================================
Functions that modify Z-stack–related attributes in LAS X scanning
template LRP files.

Editors here follow the same pattern as the main editors module:
string replacement on raw LRP text, designed for use with
``templates.transaction.apply_lrp_change``.

Dependency direction:
    - Imports: ``_primitives``, stdlib.
    - Imported by: driver facade re-exports.
"""

import logging
import xml.etree.ElementTree as ET
from pathlib import Path

from ._primitives import (
    _set_job_attr,
    _verify_job_attr,
    _verify_job_attr_float,
)

log = logging.getLogger(__name__)


# =============================================================================
# Z-stack direction
# =============================================================================

Z_STACK_DIRECTIONS = {
    0: "Bidirectional",
    1: "Unidirectional",
}


def lrp_set_z_stack_direction(lrp_path, mode, job_name):
    """Set Z-stack direction mode for a job.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        mode: ``0`` for Bidirectional, ``1`` for Unidirectional.
        job_name: Name of the job to modify.

    Returns:
        Number of attributes changed.
    """
    mode = int(mode)
    if mode not in Z_STACK_DIRECTIONS:
        log.error("lrp_set_z_stack_direction: invalid mode %r (expected 0 or 1)", mode)
        return 0
    name = Z_STACK_DIRECTIONS[mode]
    count = 0
    count += _set_job_attr(
        lrp_path, "ZStackDirectionMode", str(mode), job_name, "lrp_set_z_stack_direction"
    )
    count += _set_job_attr(
        lrp_path, "ZStackDirectionModeName", name, job_name, "lrp_set_z_stack_direction"
    )
    return count


def lrp_verify_z_stack_direction(lrp_path, mode, job_name):
    """Verify ZStackDirectionMode for a job (exact match)."""
    return _verify_job_attr(lrp_path, "ZStackDirectionMode", str(int(mode)), job_name)


# =============================================================================
# Z-stack sections
# =============================================================================


def lrp_set_sections(lrp_path, value, job_name):
    """Set the number of Z-stack sections for a job.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        value: Target number of sections (int, >= 1).
        job_name: Name of the job to modify.

    Returns:
        Number of attributes changed.
    """
    value = int(value)
    if value < 1:
        log.error("lrp_set_sections: invalid value %r (must be >= 1)", value)
        return 0
    return _set_job_attr(lrp_path, "Sections", str(value), job_name, "lrp_set_sections")


def lrp_verify_sections(lrp_path, value, job_name):
    """Verify Sections for a job (exact match)."""
    return _verify_job_attr(lrp_path, "Sections", str(int(value)), job_name)


# =============================================================================
# Z-stack active (enable / disable)
# =============================================================================


def lrp_set_z_stack_active(lrp_path, enable, job_name):
    """Enable or disable the Z-stack for a job.

    Sets ``ValidBeginStack`` and ``ValidEndStack``.  When disabling,
    also resets ``Sections`` to 1.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        enable: ``True`` to enable, ``False`` to disable.
        job_name: Name of the job to modify.

    Returns:
        Number of attributes changed.
    """
    val = "1" if enable else "0"
    count = 0
    count += _set_job_attr(lrp_path, "ValidBeginStack", val, job_name, "lrp_set_z_stack_active")
    count += _set_job_attr(lrp_path, "ValidEndStack", val, job_name, "lrp_set_z_stack_active")
    if not enable:
        count += _set_job_attr(lrp_path, "Sections", "1", job_name, "lrp_set_z_stack_active")
    return count


def lrp_verify_z_stack_active(lrp_path, enable, job_name):
    """Verify ValidBeginStack and ValidEndStack for a job."""
    val = "1" if enable else "0"
    return _verify_job_attr(lrp_path, "ValidBeginStack", val, job_name) and _verify_job_attr(
        lrp_path, "ValidEndStack", val, job_name
    )


# =============================================================================
# Z use mode (z-galvo / z-wide)
# =============================================================================

Z_USE_MODES = {
    0: "z-wide",
    1: "z-galvo",
}


def lrp_set_z_use_mode(lrp_path, mode, job_name):
    """Set the Z use mode (z-galvo or z-wide) for a job.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        mode: ``0`` for z-wide, ``1`` for z-galvo.
            Also accepts string names: ``"z-wide"``, ``"z-galvo"``.
        job_name: Name of the job to modify.

    Returns:
        Number of attributes changed.
    """
    if isinstance(mode, str):
        reverse = {v: k for k, v in Z_USE_MODES.items()}
        mode = reverse.get(mode)
        if mode is None:
            log.error("lrp_set_z_use_mode: invalid mode string (expected 'z-wide' or 'z-galvo')")
            return 0
    mode = int(mode)
    if mode not in Z_USE_MODES:
        log.error("lrp_set_z_use_mode: invalid mode %r (expected 0 or 1)", mode)
        return 0
    name = Z_USE_MODES[mode]
    count = 0
    count += _set_job_attr(lrp_path, "ZUseMode", str(mode), job_name, "lrp_set_z_use_mode")
    count += _set_job_attr(lrp_path, "ZUseModeName", name, job_name, "lrp_set_z_use_mode")
    return count


def lrp_verify_z_use_mode(lrp_path, mode, job_name):
    """Verify ZUseMode for a job (exact match)."""
    if isinstance(mode, str):
        reverse = {v: k for k, v in Z_USE_MODES.items()}
        mode = reverse.get(mode, mode)
    return _verify_job_attr(lrp_path, "ZUseMode", str(int(mode)), job_name)


# =============================================================================
# Z-position
# =============================================================================


def lrp_set_z_position(lrp_path, z_um, job_name):
    """Set the Z-position for a job.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        z_um: Target Z-position in **micrometers**.
        job_name: Name of the job to modify.

    Returns:
        Number of attributes changed.
    """
    z_m = float(z_um) * 1e-6
    return _set_job_attr(lrp_path, "ZPosition", str(z_m), job_name, "lrp_set_z_position")


def lrp_verify_z_position(lrp_path, z_um, job_name, tolerance_um=0.5):
    """Verify ZPosition for a job (with tolerance, in um)."""
    return _verify_job_attr_float(
        lrp_path, "ZPosition", float(z_um) * 1e-6, job_name, tolerance_um * 1e-6
    )


# =============================================================================
# Z-stack range (begin / end) and size
# =============================================================================


def lrp_set_z_stack_range(lrp_path, begin_um, end_um, job_name):
    """Set the Z-stack begin and end positions for a job.

    Also enables the z-stack by setting ``ValidBeginStack`` and
    ``ValidEndStack`` to 1.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        begin_um: Stack begin position in **micrometers**.
        end_um: Stack end position in **micrometers**.
        job_name: Name of the job to modify.

    Returns:
        Number of attributes changed.
    """
    begin_m = float(begin_um) * 1e-6
    end_m = float(end_um) * 1e-6
    count = 0
    count += _set_job_attr(lrp_path, "Begin", str(begin_m), job_name, "lrp_set_z_stack_range")
    count += _set_job_attr(lrp_path, "End", str(end_m), job_name, "lrp_set_z_stack_range")
    count += _set_job_attr(lrp_path, "ValidBeginStack", "1", job_name, "lrp_set_z_stack_range")
    count += _set_job_attr(lrp_path, "ValidEndStack", "1", job_name, "lrp_set_z_stack_range")
    return count


def lrp_verify_z_stack_range(lrp_path, begin_um, end_um, job_name, tolerance_um=1.0):
    """Verify Begin and End for a job (with tolerance, in um)."""
    return _verify_job_attr_float(
        lrp_path, "Begin", float(begin_um) * 1e-6, job_name, tolerance_um * 1e-6
    ) and _verify_job_attr_float(
        lrp_path, "End", float(end_um) * 1e-6, job_name, tolerance_um * 1e-6
    )


def lrp_set_z_stack_size(lrp_path, size_um, job_name):
    """Set the Z-stack total size, centered on the current Z-position.

    Reads the current ``ZPosition`` from the Master element, then
    sets ``Begin`` and ``End`` symmetrically around it.  Also enables
    the z-stack.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        size_um: Total stack size in **micrometers**.
        job_name: Name of the job to modify.

    Returns:
        Number of attributes changed.
    """
    lrp_path = Path(lrp_path)
    root = ET.parse(lrp_path).getroot()

    # Find current ZPosition for this job's Master element.
    z_m = None
    job_found = False
    for b in root.findall(".//LDM_Block_Sequence_Block"):
        seq = b.find(".//LDM_Block_Sequential")
        if seq is not None and seq.get("BlockName") == job_name:
            job_found = True
            el = b.find(".//LDM_Block_Sequential_Master/ATLConfocalSettingDefinition")
            if el is None:
                log.error(
                    "lrp_set_z_stack_size: job '%s' has no Sequential_Master setting", job_name
                )
                return 0
            raw_z = el.get("ZPosition")
            if raw_z is None:
                # Silently centering at Z=0 m would move the stack far from
                # the sample; fail loudly instead.
                log.error(
                    "lrp_set_z_stack_size: job '%s' Master has no ZPosition; refusing to "
                    "centre the stack at 0",
                    job_name,
                )
                return 0
            try:
                z_m = float(raw_z)
            except (ValueError, TypeError):
                log.error(
                    "lrp_set_z_stack_size: job '%s' ZPosition %r unparseable", job_name, raw_z
                )
                return 0
            break

    if not job_found:
        log.error("lrp_set_z_stack_size: job '%s' not found", job_name)
        return 0
    if z_m is None:
        return 0

    half_m = (float(size_um) * 1e-6) / 2.0
    begin_um = (z_m - half_m) * 1e6
    end_um = (z_m + half_m) * 1e6

    log.info(
        "lrp_set_z_stack_size: job='%s', z=%.1f um, size=%.1f um, begin=%.1f um, end=%.1f um",
        job_name,
        z_m * 1e6,
        size_um,
        begin_um,
        end_um,
    )

    return lrp_set_z_stack_range(lrp_path, begin_um, end_um, job_name)


def lrp_verify_z_stack_size(lrp_path, size_um, job_name, tolerance_um=1.0):
    """Verify the Z-stack total size (End - Begin) in um."""
    lrp_path = Path(lrp_path)
    root = ET.parse(lrp_path).getroot()
    for b in root.findall(".//LDM_Block_Sequence_Block"):
        seq = b.find(".//LDM_Block_Sequential")
        if seq is not None and seq.get("BlockName") == job_name:
            el = b.find(".//LDM_Block_Sequential_Master/ATLConfocalSettingDefinition")
            if el is None:
                return False
            try:
                begin = float(el.get("Begin", "0"))
                end = float(el.get("End", "0"))
            except (ValueError, TypeError):
                return False
            actual_um = (end - begin) * 1e6
            return abs(actual_um - size_um) < tolerance_um
    return False

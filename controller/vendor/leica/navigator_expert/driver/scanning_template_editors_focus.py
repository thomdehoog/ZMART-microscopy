"""
Focus-related scanning template editors.
==========================================
Editors for autofocus, pinhole, and Z-stack calculation mode.

Dependency direction:
    - Imports: ``scanning_template_editors`` (helpers), stdlib.
    - Imported by: ``__init__`` (re-export).
"""

import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .scanning_template_editors import (
    _set_job_attr,
    _verify_job_attr,
    _verify_job_attr_float,
)

log = logging.getLogger(__name__)


# =============================================================================
# Z-stack calculation mode
# =============================================================================

STACK_MODES = {
    0: "Constant steps",
    1: "Constant step size",
    2: "System optimized step size",
}


def lrp_set_stack_calculation_mode(lrp_path, mode, job_name):
    """Set the Z-stack calculation mode for a specific job.

    Uses string replacement on the ``ATLConfocalSettingDefinition``
    inside ``LDM_Block_Sequential_Master`` (the authoritative element).

    Args:
        lrp_path: Path to the ``.lrp`` file.
        mode: Target mode — ``0`` (Constant steps),
            ``1`` (Constant step size), or
            ``2`` (System optimized step size).
        job_name: Name of the job to modify (e.g. ``"AF Job"``).

    Returns:
        Number of attributes changed (0, 1, or 2).
    """
    if mode not in STACK_MODES:
        log.error("lrp_set_stack_calculation_mode: invalid mode %r "
                  "(expected 0, 1, or 2)", mode)
        return 0

    lrp_path = Path(lrp_path)
    text = lrp_path.read_text(encoding="utf-8")

    marker = f'BlockName="{job_name}"'
    job_pos = text.find(marker)
    if job_pos == -1:
        log.error("lrp_set_stack_calculation_mode: job '%s' not found", job_name)
        return 0

    master_tag = "LDM_Block_Sequential_Master"
    master_pos = text.find(master_tag, job_pos)
    if master_pos == -1:
        log.error("lrp_set_stack_calculation_mode: no Sequential_Master "
                  "found for job '%s'", job_name)
        return 0

    setting_tag = "ATLConfocalSettingDefinition"
    setting_pos = text.find(setting_tag, master_pos)
    if setting_pos == -1:
        log.error("lrp_set_stack_calculation_mode: no setting found in "
                  "Sequential_Master for job '%s'", job_name)
        return 0

    end_pos = text.find(">", setting_pos)
    if end_pos == -1:
        return 0

    element_text = text[setting_pos:end_pos + 1]
    new_element = element_text
    count = 0

    m = re.search(r'StackCalculationMode="(\d+)"', new_element)
    if m and m.group(1) != str(mode):
        new_element = new_element.replace(
            m.group(0), f'StackCalculationMode="{mode}"')
        count += 1

    target_name = STACK_MODES[mode]
    m = re.search(r'StackCalculationModeName="([^"]*)"', new_element)
    if m and m.group(1) != target_name:
        new_element = new_element.replace(
            m.group(0), f'StackCalculationModeName="{target_name}"')
        count += 1

    if count > 0:
        text = text[:setting_pos] + new_element + text[end_pos + 1:]
        lrp_path.write_text(text, encoding="utf-8")

    log.info("lrp_set_stack_calculation_mode: job='%s', mode=%d (%s), "
             "%d attributes changed", job_name, mode, STACK_MODES[mode],
             count)
    return count


def lrp_verify_stack_calculation_mode(lrp_path, mode, job_name):
    """Verify the Z-stack calculation mode on the Master element.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        mode: Expected mode (0, 1, or 2).
        job_name: Name of the job to verify.

    Returns:
        True if ``StackCalculationMode`` matches the expected value.
    """
    lrp_path = Path(lrp_path)
    root = ET.parse(lrp_path).getroot()
    for b in root.findall(".//LDM_Block_Sequence_Block"):
        seq = b.find(".//LDM_Block_Sequential")
        if seq is not None and seq.get("BlockName") == job_name:
            el = b.find(".//LDM_Block_Sequential_Master/"
                        "ATLConfocalSettingDefinition")
            if el is None:
                return False
            return el.get("StackCalculationMode") == str(mode)
    return False


# =============================================================================
# Pinhole (Airy units)
# =============================================================================

def lrp_set_pinhole_airy(lrp_path, value, job_name):
    """Set PinholeAiry on all settings in a job.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        value: Target pinhole size in Airy units (float).
        job_name: Name of the job to modify (e.g. ``"AF Job"``).

    Returns:
        Number of attributes changed.
    """
    return _set_job_attr(lrp_path, "PinholeAiry", str(value), job_name,
                         "lrp_set_pinhole_airy")


def lrp_verify_pinhole_airy(lrp_path, value, job_name, tolerance=0.1):
    """Verify PinholeAiry for a job (with tolerance).

    LAS X adjusts PinholeAiry when saving (e.g. ``1.0`` becomes
    ``0.99996859...``), so float tolerance is used instead of exact
    string comparison.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        value: Expected pinhole size in Airy units.
        job_name: Name of the job to verify.
        tolerance: Acceptable deviation (default 0.1 AU).

    Returns:
        True if all PinholeAiry values are within tolerance.
    """
    return _verify_job_attr_float(lrp_path, "PinholeAiry", value, job_name,
                                  tolerance)


# =============================================================================
# Autofocus active
# =============================================================================

def lrp_set_autofocus_active(lrp_path, enable, job_name):
    """Enable or disable autofocus for a job.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        enable: ``True`` to enable, ``False`` to disable.
        job_name: Name of the job to modify.

    Returns:
        Number of attributes changed.
    """
    val = "1" if enable else "0"
    return _set_job_attr(lrp_path, "IsAutofocusActive", val, job_name,
                         "lrp_set_autofocus_active")


def lrp_verify_autofocus_active(lrp_path, enable, job_name):
    """Verify IsAutofocusActive for a job (exact match)."""
    val = "1" if enable else "0"
    return _verify_job_attr(lrp_path, "IsAutofocusActive", val, job_name)

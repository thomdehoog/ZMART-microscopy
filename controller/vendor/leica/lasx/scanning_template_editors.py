"""
Scanning template editors.
===========================
Functions that modify specific attributes in LAS X scanning template
LRP files.  Each editor operates on raw file text (string replacement)
to preserve the original single-line XML format exactly.

Editors are designed to plug into ``scanning_templates.apply_lrp_change``
as the ``lrp_edit_fn`` argument.  Each editor has a corresponding
``verify_*`` function for the ``verify_fn`` argument.

Pattern::

    from lasx.scanning_templates import apply_lrp_change, TEMPLATE_XML
    from lasx.scanning_template_editors import (
        set_stack_calculation_mode, verify_stack_calculation_mode,
    )

    apply_lrp_change(
        client, TEMPLATE_XML,
        set_stack_calculation_mode, mode, job_name,
        verify_fn=lambda p: verify_stack_calculation_mode(p, mode, job_name),
    )

Dependency direction:
    - Imports: stdlib only.
    - Imported by: ``__init__`` (re-export).
"""

import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path

log = logging.getLogger(__name__)


# =============================================================================
# Z-stack calculation mode
# =============================================================================

STACK_MODES = {
    0: "Constant steps",
    1: "Constant step size",
    2: "System optimized step size",
}


def set_stack_calculation_mode(lrp_path, mode, job_name):
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
        log.error("set_stack_calculation_mode: invalid mode %r "
                  "(expected 0, 1, or 2)", mode)
        return 0

    lrp_path = Path(lrp_path)
    text = lrp_path.read_text(encoding="utf-8")

    marker = f'BlockName="{job_name}"'
    job_pos = text.find(marker)
    if job_pos == -1:
        log.error("set_stack_calculation_mode: job '%s' not found", job_name)
        return 0

    master_tag = "LDM_Block_Sequential_Master"
    master_pos = text.find(master_tag, job_pos)
    if master_pos == -1:
        log.error("set_stack_calculation_mode: no Sequential_Master "
                  "found for job '%s'", job_name)
        return 0

    setting_tag = "ATLConfocalSettingDefinition"
    setting_pos = text.find(setting_tag, master_pos)
    if setting_pos == -1:
        log.error("set_stack_calculation_mode: no setting found in "
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

    log.info("set_stack_calculation_mode: job='%s', mode=%d (%s), "
             "%d attributes changed", job_name, mode, STACK_MODES[mode],
             count)
    return count


def verify_stack_calculation_mode(lrp_path, mode, job_name):
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

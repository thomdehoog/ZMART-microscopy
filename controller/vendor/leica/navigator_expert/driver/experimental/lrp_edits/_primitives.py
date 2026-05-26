"""
Base LRP-editing primitives.
==============================
Low-level helpers that modify individual XML attributes inside LAS X
scanning template ``.lrp`` files.  Every higher-level editor (general,
scan, z, roi, focus) is built on top of these four functions.


Dependency direction:
    - Imports: stdlib only.
    - Imported by: ``general``, ``scan``, ``z``, ``roi``, ``focus``.
"""

import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path

log = logging.getLogger(__name__)


# =============================================================================
# Generic job-block attribute helpers
# =============================================================================

def _set_job_attr(lrp_path, attr_name, value_str, job_name, caller):
    """Replace *attr_name* on every ATLConfocalSettingDefinition in a job.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        attr_name: XML attribute name (e.g. ``"LineAverage"``).
        value_str: Target value as string.
        job_name: Name of the job to modify.
        caller: Caller name for log messages.

    Returns:
        Number of attributes changed.
    """
    lrp_path = Path(lrp_path)
    text = lrp_path.read_text(encoding="utf-8")

    marker = f'BlockName="{job_name}"'
    job_pos = text.find(marker)
    if job_pos == -1:
        log.error("%s: job '%s' not found", caller, job_name)
        return 0

    next_block = text.find("<LDM_Block_Sequence_Block", job_pos + 1)
    block_end = next_block if next_block != -1 else len(text)

    count = 0
    setting_tag = "ATLConfocalSettingDefinition"
    pattern = re.compile(rf'{attr_name}="([^"]*)"')
    search_pos = job_pos

    while search_pos < block_end:
        setting_pos = text.find(setting_tag, search_pos)
        if setting_pos == -1 or setting_pos >= block_end:
            break

        end_pos = text.find(">", setting_pos)
        if end_pos == -1:
            break

        element_text = text[setting_pos:end_pos + 1]
        m = pattern.search(element_text)
        if m and m.group(1) != value_str:
            new_element = element_text.replace(
                m.group(0), f'{attr_name}="{value_str}"')
            text = text[:setting_pos] + new_element + text[end_pos + 1:]
            block_end += len(new_element) - len(element_text)
            end_pos += len(new_element) - len(element_text)
            count += 1

        search_pos = end_pos + 1

    if count > 0:
        lrp_path.write_text(text, encoding="utf-8")

    log.info("%s: job='%s', value=%s, %d attributes changed",
             caller, job_name, value_str, count)
    return count


def _verify_job_attr(lrp_path, attr_name, value_str, job_name):
    """Verify *attr_name* on all settings in a job (exact match).

    Returns True if every ``ATLConfocalSettingDefinition`` that has
    the attribute matches *value_str*.
    """
    lrp_path = Path(lrp_path)
    root = ET.parse(lrp_path).getroot()
    for b in root.findall(".//LDM_Block_Sequence_Block"):
        seq = b.find(".//LDM_Block_Sequential")
        if seq is not None and seq.get("BlockName") == job_name:
            for el in b.findall(".//ATLConfocalSettingDefinition"):
                raw = el.get(attr_name)
                if raw is None:
                    continue
                if raw != value_str:
                    return False
            return True
    return False


def _verify_job_attr_float(lrp_path, attr_name, value, job_name, tolerance):
    """Like ``_verify_job_attr`` but with float tolerance."""
    lrp_path = Path(lrp_path)
    root = ET.parse(lrp_path).getroot()
    for b in root.findall(".//LDM_Block_Sequence_Block"):
        seq = b.find(".//LDM_Block_Sequential")
        if seq is not None and seq.get("BlockName") == job_name:
            for el in b.findall(".//ATLConfocalSettingDefinition"):
                raw = el.get(attr_name)
                if raw is None:
                    continue
                try:
                    if abs(float(raw) - value) > tolerance:
                        return False
                except (ValueError, TypeError):
                    return False
            return True
    return False


def _set_sequential_attr(lrp_path, attr_name, value_str, job_name, caller):
    """Replace *attr_name* on the ``LDM_Block_Sequential`` element for a job.

    Unlike ``_set_job_attr`` (which targets ``ATLConfocalSettingDefinition``),
    this targets the ``LDM_Block_Sequential`` element itself.
    """
    lrp_path = Path(lrp_path)
    text = lrp_path.read_text(encoding="utf-8")

    marker = f'BlockName="{job_name}"'
    job_pos = text.find(marker)
    if job_pos == -1:
        log.error("%s: job '%s' not found", caller, job_name)
        return 0

    # Find the LDM_Block_Sequential element that contains this BlockName.
    # Walk backwards from job_pos to find the opening tag.
    seq_tag = "LDM_Block_Sequential"
    # Search backwards for the tag start
    search_start = text.rfind(seq_tag, 0, job_pos)
    if search_start == -1:
        log.error("%s: no LDM_Block_Sequential found for job '%s'",
                  caller, job_name)
        return 0

    end_pos = text.find(">", search_start)
    if end_pos == -1:
        return 0

    element_text = text[search_start:end_pos + 1]
    pattern = re.compile(rf'{attr_name}="([^"]*)"')
    m = pattern.search(element_text)
    if not m or m.group(1) == value_str:
        log.info("%s: job='%s', no change needed", caller, job_name)
        return 0

    new_element = element_text.replace(
        m.group(0), f'{attr_name}="{value_str}"')
    text = text[:search_start] + new_element + text[end_pos + 1:]
    lrp_path.write_text(text, encoding="utf-8")

    log.info("%s: job='%s', %s -> %s", caller, job_name, attr_name, value_str)
    return 1

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
    # Whitespace lookbehind so e.g. attr_name="Zoom" can never match inside
    # a suffix-colliding sibling like BaseZoom="..." on the same tag.
    pattern = re.compile(rf'(?<=\s){re.escape(attr_name)}="([^"]*)"')
    search_pos = job_pos

    while search_pos < block_end:
        setting_pos = text.find(setting_tag, search_pos)
        if setting_pos == -1 or setting_pos >= block_end:
            break

        end_pos = text.find(">", setting_pos)
        if end_pos == -1:
            break

        element_text = text[setting_pos : end_pos + 1]
        m = pattern.search(element_text)
        if m and m.group(1) != value_str:
            # Splice at the match position: replacing by value would also
            # rewrite any other attribute that happens to carry the same text.
            new_element = (
                element_text[: m.start()] + f'{attr_name}="{value_str}"' + element_text[m.end() :]
            )
            text = text[:setting_pos] + new_element + text[end_pos + 1 :]
            block_end += len(new_element) - len(element_text)
            end_pos += len(new_element) - len(element_text)
            count += 1

        search_pos = end_pos + 1

    if count > 0:
        lrp_path.write_text(text, encoding="utf-8")

    log.info("%s: job='%s', value=%s, %d attributes changed", caller, job_name, value_str, count)
    return count


def _job_setting_attr_values(lrp_path, attr_name, job_name):
    """All values of *attr_name* on the job's settings, or None if the job is missing."""
    root = ET.parse(Path(lrp_path)).getroot()
    for b in root.findall(".//LDM_Block_Sequence_Block"):
        seq = b.find(".//LDM_Block_Sequential")
        if seq is not None and seq.get("BlockName") == job_name:
            return [
                el.get(attr_name)
                for el in b.findall(".//ATLConfocalSettingDefinition")
                if el.get(attr_name) is not None
            ]
    return None


def _verify_job_attr(lrp_path, attr_name, value_str, job_name):
    """Verify *attr_name* on all settings in a job (exact match).

    Returns True only if the job exists, at least one of its
    ``ATLConfocalSettingDefinition`` elements carries the attribute, and
    every carried value matches *value_str*. An absent attribute is a
    failed verification, not a vacuous pass — ``_set_job_attr`` never
    adds attributes, so "absent" means the edit silently did nothing.
    """
    values = _job_setting_attr_values(lrp_path, attr_name, job_name)
    if not values:
        return False
    return all(raw == value_str for raw in values)


def _verify_job_attr_float(lrp_path, attr_name, value, job_name, tolerance):
    """Like ``_verify_job_attr`` but with float tolerance."""
    values = _job_setting_attr_values(lrp_path, attr_name, job_name)
    if not values:
        return False
    try:
        return all(abs(float(raw) - value) <= tolerance for raw in values)
    except (ValueError, TypeError):
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
        log.error("%s: no LDM_Block_Sequential found for job '%s'", caller, job_name)
        return 0

    end_pos = text.find(">", search_start)
    if end_pos == -1:
        return 0

    element_text = text[search_start : end_pos + 1]
    pattern = re.compile(rf'(?<=\s){re.escape(attr_name)}="([^"]*)"')
    m = pattern.search(element_text)
    if not m:
        log.warning("%s: job='%s' has no %s attribute; nothing edited", caller, job_name, attr_name)
        return 0
    if m.group(1) == value_str:
        log.info("%s: job='%s', no change needed", caller, job_name)
        return 0

    new_element = element_text[: m.start()] + f'{attr_name}="{value_str}"' + element_text[m.end() :]
    text = text[:search_start] + new_element + text[end_pos + 1 :]
    lrp_path.write_text(text, encoding="utf-8")

    log.info("%s: job='%s', %s -> %s", caller, job_name, attr_name, value_str)
    return 1

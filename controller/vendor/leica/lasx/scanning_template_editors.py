"""
Scanning template editors — core helpers and basic settings.
==============================================================
Shared helpers (``_set_job_attr``, ``_verify_job_attr``, etc.) used by
all editor modules, plus editors for line/frame averaging, scan mode,
and sequential mode.

Sub-modules:
    - ``scanning_template_editors_focus`` — autofocus, pinhole,
      stack calculation mode.
    - ``scanning_template_editors_scan`` — zoom, scan speed, image
      format, scan direction, phase, resonant, bit depth, rotation.
    - ``scanning_template_editors_z`` — z-stack direction, sections,
      z-stack active, z-use mode, z-position, z-stack range/size.

Dependency direction:
    - Imports: stdlib only.
    - Imported by: sub-modules above, ``__init__`` (re-export).
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


# =============================================================================
# Line average / Line accumulation / Frame average / Frame accumulation
# =============================================================================

def lrp_set_line_average(lrp_path, value, job_name):
    """Set LineAverage on all settings in a job.

    Timing attributes are left unchanged — LAS X recalculates on load.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        value: Target line average count (int, >= 1).
        job_name: Name of the job to modify.

    Returns:
        Number of attributes changed.
    """
    return _set_job_attr(lrp_path, "LineAverage", str(int(value)), job_name,
                         "lrp_set_line_average")


def lrp_verify_line_average(lrp_path, value, job_name):
    """Verify LineAverage for a job (exact match)."""
    return _verify_job_attr(lrp_path, "LineAverage", str(int(value)),
                            job_name)


def lrp_set_line_accumulation(lrp_path, value, job_name):
    """Set Line_Accumulation on all settings in a job.

    Note: LAS X uses ``Line_Accumulation`` (with underscore) in the
    LRP, unlike the other averaging attributes.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        value: Target line accumulation count (int, >= 1).
        job_name: Name of the job to modify.

    Returns:
        Number of attributes changed.
    """
    return _set_job_attr(lrp_path, "Line_Accumulation", str(int(value)),
                         job_name, "lrp_set_line_accumulation")


def lrp_verify_line_accumulation(lrp_path, value, job_name):
    """Verify Line_Accumulation for a job (exact match)."""
    return _verify_job_attr(lrp_path, "Line_Accumulation", str(int(value)),
                            job_name)


def lrp_set_frame_average(lrp_path, value, job_name):
    """Set FrameAverage on all settings in a job.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        value: Target frame average count (int, >= 1).
        job_name: Name of the job to modify.

    Returns:
        Number of attributes changed.
    """
    return _set_job_attr(lrp_path, "FrameAverage", str(int(value)), job_name,
                         "lrp_set_frame_average")


def lrp_verify_frame_average(lrp_path, value, job_name):
    """Verify FrameAverage for a job (exact match)."""
    return _verify_job_attr(lrp_path, "FrameAverage", str(int(value)),
                            job_name)


def lrp_set_frame_accumulation(lrp_path, value, job_name):
    """Set FrameAccumulation on all settings in a job.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        value: Target frame accumulation count (int, >= 1).
        job_name: Name of the job to modify.

    Returns:
        Number of attributes changed.
    """
    return _set_job_attr(lrp_path, "FrameAccumulation", str(int(value)),
                         job_name, "lrp_set_frame_accumulation")


def lrp_verify_frame_accumulation(lrp_path, value, job_name):
    """Verify FrameAccumulation for a job (exact match)."""
    return _verify_job_attr(lrp_path, "FrameAccumulation", str(int(value)),
                            job_name)


# =============================================================================
# Scan mode (xyz, xzy, xyzt, ...)
# =============================================================================

def lrp_set_scan_mode(lrp_path, mode, job_name):
    """Set ScanMode on all settings in a job.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        mode: Target scan mode string (e.g. ``"xyz"``, ``"xzy"``,
            ``"xyzt"``).
        job_name: Name of the job to modify.

    Returns:
        Number of attributes changed.
    """
    return _set_job_attr(lrp_path, "ScanMode", str(mode), job_name,
                         "lrp_set_scan_mode")


def lrp_verify_scan_mode(lrp_path, mode, job_name):
    """Verify ScanMode for a job (exact match)."""
    return _verify_job_attr(lrp_path, "ScanMode", str(mode), job_name)


# =============================================================================
# Sequential mode (on LDM_Block_Sequential, not ATLConfocalSettingDefinition)
# =============================================================================

SEQUENTIAL_MODES = {
    0: "Line",
    1: "Frame",
    2: "Stack",
}


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


def lrp_set_sequential_mode(lrp_path, mode, job_name):
    """Set SequentialMode on the LDM_Block_Sequential element for a job.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        mode: Target mode — ``0`` (Line), ``1`` (Frame), or ``2`` (Stack).
            Also accepts string names: ``"Line"``, ``"Frame"``, ``"Stack"``.
        job_name: Name of the job to modify.

    Returns:
        Number of attributes changed (0 or 1).
    """
    if isinstance(mode, str):
        reverse = {v: k for k, v in SEQUENTIAL_MODES.items()}
        mode = reverse.get(mode)
        if mode is None:
            log.error("lrp_set_sequential_mode: invalid mode string "
                      "(expected 'Line', 'Frame', or 'Stack')")
            return 0
    mode = int(mode)
    if mode not in SEQUENTIAL_MODES:
        log.error("lrp_set_sequential_mode: invalid mode %r "
                  "(expected 0, 1, or 2)", mode)
        return 0
    return _set_sequential_attr(lrp_path, "SequentialMode", str(mode),
                                job_name, "lrp_set_sequential_mode")


def lrp_verify_sequential_mode(lrp_path, mode, job_name):
    """Verify SequentialMode for a job (exact match).

    Reads the ``LDM_Block_Sequential`` element's ``SequentialMode``
    attribute.
    """
    if isinstance(mode, str):
        reverse = {v: k for k, v in SEQUENTIAL_MODES.items()}
        mode = reverse.get(mode, mode)
    lrp_path = Path(lrp_path)
    root = ET.parse(lrp_path).getroot()
    for b in root.findall(".//LDM_Block_Sequence_Block"):
        seq = b.find(".//LDM_Block_Sequential")
        if seq is not None and seq.get("BlockName") == job_name:
            return seq.get("SequentialMode") == str(int(mode))
    return False

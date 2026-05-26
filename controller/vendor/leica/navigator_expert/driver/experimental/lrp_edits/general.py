"""
General LRP editors -- line/frame averaging, scan mode, sequential mode.
=========================================================================
Editors for line/frame averaging, scan mode, and sequential mode.

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
    _set_sequential_attr,
)

log = logging.getLogger(__name__)


# =============================================================================
# Line average / Line accumulation / Frame average / Frame accumulation
# =============================================================================

def lrp_set_line_average(lrp_path, value, job_name):
    """Set LineAverage on all settings in a job.

    Timing attributes are left unchanged -- LAS X recalculates on load.

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


def lrp_set_sequential_mode(lrp_path, mode, job_name):
    """Set SequentialMode on the LDM_Block_Sequential element for a job.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        mode: Target mode -- ``0`` (Line), ``1`` (Frame), or ``2`` (Stack).
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

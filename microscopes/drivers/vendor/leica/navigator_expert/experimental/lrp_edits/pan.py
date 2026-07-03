"""Galvo-pan LRP edits — the one experimental helper production depends on.

``move_galvo_to_pixel`` (commands.py) reads and writes galvo pan directly in the
scan-field ``.lrp`` file, then confirms via ``apply_lrp_change``. Only pan is
used in anger; the rest of the historical LRP editor surface was removed.

Geometry (two LAS X-documented invariants):

    translation_um = ((px - centre) * pixel_size_um, (py - centre) * pixel_size_um)
    (pan_x, pan_y)  = (-tx_um, +ty_um) / pan_scale_um

``pan_scale_um`` is objective-dependent; resolve it with
``pan_scale_um_from_base_fov`` from ``runtime.utils``.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path

log = logging.getLogger(__name__)


def _set_job_attr(lrp_path, attr_name, value_str, job_name, caller):
    """Replace *attr_name* on every ATLConfocalSettingDefinition in a job.

    Returns the number of attributes changed. The attribute name is matched on
    a word boundary and spliced by position, so editing ``Zoom`` never touches
    ``BaseZoom`` (or any other suffixed attribute) sharing its value.
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
    pattern = re.compile(rf'(?<![\w]){re.escape(attr_name)}="([^"]*)"')
    search_pos = job_pos

    while search_pos < block_end:
        setting_pos = text.find(setting_tag, search_pos)
        if setting_pos == -1 or setting_pos >= block_end:
            break

        end_pos = text.find(">", setting_pos)
        if end_pos == -1:
            break

        element = text[setting_pos : end_pos + 1]
        m = pattern.search(element)
        if m and m.group(1) != value_str:
            new_element = (
                element[: m.start()] + f'{attr_name}="{value_str}"' + element[m.end() :]
            )
            text = text[:setting_pos] + new_element + text[end_pos + 1 :]
            delta = len(new_element) - len(element)
            block_end += delta
            end_pos += delta
            count += 1

        search_pos = end_pos + 1

    if count > 0:
        lrp_path.write_text(text, encoding="utf-8")

    log.info("%s: job='%s', value=%s, %d attributes changed", caller, job_name, value_str, count)
    return count


def _verify_job_attr_float(lrp_path, attr_name, value, job_name, tolerance):
    """Return True if every setting in *job_name* has *attr_name* within tolerance."""
    root = ET.parse(Path(lrp_path)).getroot()
    found = False
    for block in root.findall(".//LDM_Block_Sequence_Block"):
        seq = block.find(".//LDM_Block_Sequential")
        if seq is None or seq.get("BlockName") != job_name:
            continue
        for setting in block.findall(".//ATLConfocalSettingDefinition"):
            raw = setting.get(attr_name)
            if raw is None or abs(float(raw) - float(value)) > tolerance:
                return False
            found = True
    return found


def roi_translation_to_pan(translation_x_m, translation_y_m, *, pan_scale_um):
    """Convert an image-frame translation (metres) to galvo ``(pan_x, pan_y)``.

    ROI translation is the offset from field centre with X negated. ``pan_scale_um``
    (um per pan unit) is objective-dependent; resolve via ``pan_scale_um_from_base_fov``.
    """
    tx_um = float(translation_x_m) * 1e6
    ty_um = float(translation_y_m) * 1e6
    return (-tx_um / pan_scale_um, ty_um / pan_scale_um)


def galvo_pan_for_pixel(px, py, *, pixel_size_um, image_size, pan_scale_um):
    """Pan *delta* that brings pixel (px, py) to the FOV centre.

    Returned values are deltas relative to the current pan; the caller adds them
    to whatever pan is set. Stage XY does not enter the derivation — the galvo
    deflects the scan field, which lives in the image frame, not the stage frame.
    """
    centre = image_size / 2.0
    tx_m = (px - centre) * pixel_size_um * 1e-6
    ty_m = (py - centre) * pixel_size_um * 1e-6
    return roi_translation_to_pan(tx_m, ty_m, pan_scale_um=pan_scale_um)


def lrp_set_pan(lrp_path, x, y, job_name):
    """Set ``PanFirstDim`` (X) and ``PanSecondDim`` (Y) on every setting in a job."""
    count = _set_job_attr(lrp_path, "PanFirstDim", str(x), job_name, "lrp_set_pan")
    count += _set_job_attr(lrp_path, "PanSecondDim", str(y), job_name, "lrp_set_pan")
    return count


def lrp_verify_pan(lrp_path, x, y, job_name, tolerance=0.001):
    """Verify PanFirstDim and PanSecondDim for a job (within tolerance)."""
    return _verify_job_attr_float(
        lrp_path, "PanFirstDim", float(x), job_name, tolerance
    ) and _verify_job_attr_float(lrp_path, "PanSecondDim", float(y), job_name, tolerance)


def lrp_get_pan(lrp_path, job_name):
    """Read ``(PanFirstDim, PanSecondDim)`` for a job, or ``(0.0, 0.0)`` if unset."""
    root = ET.parse(Path(lrp_path)).getroot()
    for block in root.findall(".//LDM_Block_Sequence_Block"):
        seq = block.find(".//LDM_Block_Sequential")
        if seq is None or seq.get("BlockName") != job_name:
            continue
        for setting in block.findall(".//ATLConfocalSettingDefinition"):
            pan_x = setting.get("PanFirstDim")
            pan_y = setting.get("PanSecondDim")
            if pan_x is not None and pan_y is not None:
                return float(pan_x), float(pan_y)
    return 0.0, 0.0

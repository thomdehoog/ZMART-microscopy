"""Strip and restore LAS X scanning templates.

Stripping removes scan-field objects and regions so LAS X stays
responsive during LRP editing.  Restoring reloads the original
template (with all objects) and copies the modified LRP back.

Dependency direction:
    - Imports: ``.files``, ``_file_utils``, stdlib.
    - Imported by: ``__init__`` (re-export).
"""

import logging
import shutil
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from .files import (
    find_scanning_templates_dir,
    save_experiment, load_experiment,
    TEMPLATE_XML, TEMPLATE_RGN, TEMPLATE_LRP, TEMPLATE_BASE,
    STRIPPED_XML, STRIPPED_RGN, STRIPPED_LRP,
)
from .._file_utils import _wait_file_stable

log = logging.getLogger(__name__)


# =============================================================================
# XML / RGN strip helpers
# =============================================================================

def _strip_xml(src, dst):
    """Remove all ``<ScanFields>`` content from *src*, write to *dst*."""
    text = src.read_text(encoding="utf-8")
    start = text.find("<ScanFields")
    end = text.find("</ScanFields>")
    if start != -1 and end != -1:
        text = text[:start] + "<ScanFields />" + text[end + len("</ScanFields>"):]
    dst.write_text(text, encoding="utf-8")


def _strip_rgn(src, dst):
    """Create a minimal RGN from *src* with empty Items and FocusMap."""
    tree = ET.parse(src)
    root = tree.getroot()

    fill_mask = "None"
    vertex_unit = "Pixels"
    z_mode = "1"

    el = root.find(".//ShapeList/FillMaskMode")
    if el is not None and el.text:
        fill_mask = el.text
    el = root.find(".//ShapeList/VertexUnitMode")
    if el is not None and el.text:
        vertex_unit = el.text
    el = root.find("FocusMap")
    if el is not None:
        z_mode = el.get("ZMode", "1")

    lines = [
        "<StageOverviewRegions>",
        "  <Regions>",
        "    <ShapeList>",
        "      <Items />",
        f"      <FillMaskMode>{fill_mask}</FillMaskMode>",
        f"      <VertexUnitMode>{vertex_unit}</VertexUnitMode>",
        "    </ShapeList>",
        "  </Regions>",
        f'  <FocusMap ZMode="{z_mode}" />',
        "</StageOverviewRegions>",
    ]
    dst.write_text("\r\n".join(lines), encoding="utf-8", newline="")


def _count_objects(xml_path, rgn_path):
    """Count scan fields, RGN items, and focus points."""
    try:
        xml_text = xml_path.read_text(encoding="utf-8")
        rgn_tree = ET.parse(rgn_path)
        fields = xml_text.count("<ScanFieldData")
        items = len(rgn_tree.findall(".//ShapeList/Items/*"))
        focus = len(rgn_tree.findall(".//FocusMap/*"))
        return fields, items, focus
    except (OSError, ET.ParseError) as e:
        log.warning("Cannot count objects: %s", e)
        return 0, 0, 0


# =============================================================================
# Strip template
# =============================================================================

def strip_template(client, *, save_timeout=120):
    """Save the active experiment, create a stripped copy, and load it.

    Returns:
        Result dict with ``templates_dir`` and original object counts,
        or None on failure.
    """
    templates_dir = find_scanning_templates_dir()
    if templates_dir is None:
        log.error("Cannot find ScanningTemplates directory")
        return None

    xml_path = templates_dir / TEMPLATE_XML
    rgn_path = templates_dir / TEMPLATE_RGN
    lrp_path = templates_dir / TEMPLATE_LRP
    stripped_xml = templates_dir / STRIPPED_XML
    stripped_rgn = templates_dir / STRIPPED_RGN
    stripped_lrp = templates_dir / STRIPPED_LRP

    t0 = time.perf_counter()

    log.info("Saving current experiment...")
    r = save_experiment(client, TEMPLATE_XML, templates_dir,
                        timeout=save_timeout, confirm_path=rgn_path)
    if r is None:
        log.error("Initial save failed — aborting strip")
        return None

    fields, items, focus = _count_objects(xml_path, rgn_path)
    log.info("Saved: %d fields, %d items, %d focus points",
             fields, items, focus)

    log.info("Creating stripped template files...")
    _strip_xml(xml_path, stripped_xml)
    _strip_rgn(rgn_path, stripped_rgn)
    if lrp_path.is_file():
        shutil.copy2(lrp_path, stripped_lrp)

    if "<ScanFieldData" in stripped_xml.read_text(encoding="utf-8"):
        log.warning("Strip incomplete — stripped XML still contains "
                    "ScanFieldData elements")

    log.info("Loading stripped template...")
    r = load_experiment(client, STRIPPED_XML)
    if r is None:
        log.error("Failed to load stripped template")
        return None

    log.info("Confirming strip via save...")
    r = save_experiment(client, STRIPPED_XML, templates_dir,
                        confirm_path=stripped_rgn)
    if r is None:
        log.error("Confirm-save of stripped template failed")
        return None

    sf, si, fp = _count_objects(stripped_xml, stripped_rgn)
    if sf > 0 or si > 0 or fp > 0:
        log.warning("Stripped template still has objects after confirm-save: "
                    "%d fields, %d items, %d focus", sf, si, fp)

    total_t = time.perf_counter() - t0
    log.info("Strip complete in %.1fs — template is now editable", total_t)

    return {
        "success": True,
        "templates_dir": str(templates_dir),
        "original_fields": fields,
        "original_items": items,
        "original_focus": focus,
        "total_s": total_t,
    }


def strip_template_in_place(client, *, save_timeout=120):
    """Strip the canonical PythonInspect template and keep it loaded.

    Unlike ``strip_template``, this does not create or load a
    ``_stripped`` sidecar and has no matching restore step. It is the
    correct operation when the workflow has already consumed the
    marker objects and wants the operator to continue editing the same
    canonical template name.

    Returns:
        Result dict with ``templates_dir`` and original object counts,
        or None on failure.
    """
    templates_dir = find_scanning_templates_dir()
    if templates_dir is None:
        log.error("Cannot find ScanningTemplates directory")
        return None

    xml_path = templates_dir / TEMPLATE_XML
    rgn_path = templates_dir / TEMPLATE_RGN
    lrp_path = templates_dir / TEMPLATE_LRP

    t0 = time.perf_counter()

    log.info("Saving current experiment before in-place strip...")
    r = save_experiment(client, TEMPLATE_XML, templates_dir,
                        timeout=save_timeout, confirm_path=rgn_path)
    if r is None:
        log.error("Initial save failed; aborting in-place strip")
        return None

    fields, items, focus = _count_objects(xml_path, rgn_path)
    log.info("Saved: %d fields, %d items, %d focus points",
             fields, items, focus)

    log.info("Stripping canonical template files in place...")
    tmp_xml = xml_path.with_suffix(xml_path.suffix + ".tmp")
    tmp_rgn = rgn_path.with_suffix(rgn_path.suffix + ".tmp")
    _strip_xml(xml_path, tmp_xml)
    _strip_rgn(rgn_path, tmp_rgn)
    tmp_xml.replace(xml_path)
    tmp_rgn.replace(rgn_path)

    # This routine owns the canonical no-sidecar workflow. Remove stale
    # sidecar files so get_template_state reflects the canonical files.
    for path in (
        templates_dir / STRIPPED_XML,
        templates_dir / STRIPPED_RGN,
        templates_dir / STRIPPED_LRP,
    ):
        path.unlink(missing_ok=True)

    if not lrp_path.is_file():
        log.error("Missing LRP after in-place strip: %s", lrp_path)
        return None

    log.info("Loading stripped canonical template...")
    r = load_experiment(client, TEMPLATE_XML)
    if r is None:
        log.error("Failed to load stripped canonical template")
        return None

    log.info("Confirming in-place strip via save...")
    r = save_experiment(client, TEMPLATE_XML, templates_dir,
                        timeout=save_timeout, confirm_path=rgn_path)
    if r is None:
        log.error("Confirm-save of stripped canonical template failed")
        return None

    sf, si, fp = _count_objects(xml_path, rgn_path)
    if sf > 0 or si > 0 or fp > 0:
        log.error("Canonical template still has objects after strip: "
                  "%d fields, %d items, %d focus", sf, si, fp)
        return None

    total_t = time.perf_counter() - t0
    log.info("In-place strip complete in %.1fs", total_t)

    return {
        "success": True,
        "templates_dir": str(templates_dir),
        "original_fields": fields,
        "original_items": items,
        "original_focus": focus,
        "fields": sf,
        "items": si,
        "focus": fp,
        "total_s": total_t,
    }


# =============================================================================
# Restore template
# =============================================================================

_RESTORE_SAVE_TIMEOUTS = (120, 120, 180, 240)


def restore_template(client):
    """Reload the original template (with all objects) and clean up.

    Returns:
        Result dict with restored object counts and attempt count,
        or None on failure.
    """
    templates_dir = find_scanning_templates_dir()
    if templates_dir is None:
        log.error("Cannot find ScanningTemplates directory")
        return None

    xml_path = templates_dir / TEMPLATE_XML
    rgn_path = templates_dir / TEMPLATE_RGN
    lrp_path = templates_dir / TEMPLATE_LRP
    stripped_xml = templates_dir / STRIPPED_XML
    stripped_rgn = templates_dir / STRIPPED_RGN
    stripped_lrp = templates_dir / STRIPPED_LRP

    t0 = time.perf_counter()

    bak_lrp = templates_dir / (TEMPLATE_BASE + ".lrp.bak")
    if stripped_lrp.is_file():
        shutil.copy2(stripped_lrp, bak_lrp)
        log.debug("Backed up modified LRP")

    orig_fields, orig_items, orig_focus = _count_objects(xml_path, rgn_path)
    log.info("Restoring template (expecting %d fields, %d items, %d focus)...",
             orig_fields, orig_items, orig_focus)

    bak_xml = templates_dir / (TEMPLATE_BASE + ".xml.bak")
    bak_rgn = templates_dir / (TEMPLATE_BASE + ".rgn.bak")
    shutil.copy2(xml_path, bak_xml)
    shutil.copy2(rgn_path, bak_rgn)

    for attempt, save_timeout in enumerate(_RESTORE_SAVE_TIMEOUTS, 1):
        log.info("Restore attempt %d/%d: loading original template...",
                 attempt, len(_RESTORE_SAVE_TIMEOUTS))

        r = load_experiment(client, TEMPLATE_XML)
        if r is None:
            log.error("Load failed on attempt %d", attempt)
            continue

        log.info("Confirm-saving (timeout=%ds, watching RGN)...", save_timeout)
        r = save_experiment(client, TEMPLATE_XML, templates_dir,
                            timeout=save_timeout, confirm_path=rgn_path)
        if r is None:
            log.warning("Confirm-save timed out on attempt %d — "
                        "waiting for file locks before restoring backup",
                        attempt)
            _wait_file_stable(rgn_path, 15)
            shutil.copy2(bak_xml, xml_path)
            shutil.copy2(bak_rgn, rgn_path)
            continue

        fields, items, focus = _count_objects(xml_path, rgn_path)
        log.info("Attempt %d result: %d fields, %d items, %d focus",
                 attempt, fields, items, focus)

        if items >= orig_items and fields >= orig_fields:
            break

        log.warning("Object count mismatch (expected >=%d/%d, got %d/%d) — "
                    "restoring backup", orig_fields, orig_items, fields, items)
        _wait_file_stable(rgn_path, 15)
        shutil.copy2(bak_xml, xml_path)
        shutil.copy2(bak_rgn, rgn_path)
    else:
        total_t = time.perf_counter() - t0
        bak_xml.unlink(missing_ok=True)
        bak_rgn.unlink(missing_ok=True)
        bak_lrp.unlink(missing_ok=True)
        log.error("Restore failed after %d attempts (%.1fs)",
                  len(_RESTORE_SAVE_TIMEOUTS), total_t)
        return None

    if bak_lrp.is_file():
        shutil.copy2(bak_lrp, lrp_path)
        log.debug("Restored modified LRP after confirm-save")

    total_t = time.perf_counter() - t0

    for f in (stripped_xml, stripped_rgn, stripped_lrp,
              bak_xml, bak_rgn, bak_lrp):
        if f.is_file():
            f.unlink()

    log.info("Restore complete in %.1fs (%d attempt%s): "
             "%d fields, %d items, %d focus",
             total_t, attempt, "s" if attempt > 1 else "",
             fields, items, focus)

    return {
        "success": True,
        "fields": fields,
        "items": items,
        "focus": focus,
        "attempts": attempt,
        "total_s": total_t,
    }

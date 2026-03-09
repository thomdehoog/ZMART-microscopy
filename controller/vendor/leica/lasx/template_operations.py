"""
Template operations.
====================
Save, load, strip, and restore LAS X scanning templates.

These functions operate on **direct API objects**
(``PyApiSaveExperiment``, ``PyApiLoadExperiment``), not the
``PyApiCommand`` dispatch channel used by most readers and commands.

The receipt from ``UpdateAwaitReceipt`` confirms command *acceptance*,
not action *completion*:

    - **Save** confirmation is file-based: poll the XML file's mtime
      on disk until it is updated.
    - **Load** has no reliable confirmation — use a follow-up save to
      verify.

High-level workflow for template modification::

    drv.strip_template(client)    # save → create _stripped → load _stripped
    # ... modify LRP files ...
    drv.restore_template(client)  # copy LRP back → load original → cleanup

Stripping removes scan field objects and regions so LAS X stays
responsive during LRP editing. ``restore_template`` copies the
modified LRP back to the original before reloading, so LRP edits
persist.

Dependency direction:
    - Imports: ``utils`` (``RECEIPT_TIMEOUT``, ``_make_timing``,
      ``_make_log_entry``).
    - Imported by: ``__init__`` (re-export).
"""

import logging
import os
import re
import shutil
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from .utils import RECEIPT_TIMEOUT, _make_timing, _make_log_entry

log = logging.getLogger(__name__)


# =============================================================================
# ScanningTemplates directory discovery
# =============================================================================

def find_scanning_templates_dir():
    """Locate the LAS X ScanningTemplates folder via %APPDATA%.

    Returns:
        Path to the ScanningTemplates directory, or None if not found.
    """
    appdata = os.environ.get("APPDATA")
    if not appdata:
        log.warning("find_scanning_templates_dir: APPDATA not set")
        return None
    base = Path(appdata) / "Leica Microsystems" / "LAS X" / "MatrixScreener6"
    if not base.is_dir():
        log.warning("find_scanning_templates_dir: not found: %s", base)
        return None
    user_dirs = sorted(base.glob("User_*"))
    if not user_dirs:
        log.warning("find_scanning_templates_dir: no User_* dirs in %s", base)
        return None
    templates = user_dirs[0] / "ScanningTemplates"
    return templates if templates.is_dir() else None


# =============================================================================
# Save experiment
# =============================================================================

def save_experiment(client, name, templates_dir, *, timeout=10,
                    poll_interval=0.1, max_retries=3):
    """Save the current experiment to disk with file-based confirmation.

    Sets ``PyApiSaveExperiment.Model.ExperimentName`` and fires
    ``UpdateAwaitReceipt``, then polls the XML file's mtime until
    it is updated. Retries up to max_retries times.

    Args:
        client: Live LAS X CAM client.
        name: Experiment file name including ``.xml`` extension.
        templates_dir: Path to the ScanningTemplates folder.
        timeout: Max seconds to wait for file update per attempt.
        poll_interval: Seconds between file stat checks.
        max_retries: Number of attempts.

    Returns:
        dict with success/confirmed/message/timing/logs, or None on failure.
    """
    templates_dir = Path(templates_dir)
    xml_path = templates_dir / name

    for attempt in range(max_retries):
        logs = []
        t0 = time.perf_counter()
        try:
            # Record pre-save mtime
            old_mtime = xml_path.stat().st_mtime if xml_path.is_file() else 0

            # Dispatch
            client.PyApiSaveExperiment.Model.ExperimentName = name
            if not client.PyApiSaveExperiment.UpdateAwaitReceipt(
                    RECEIPT_TIMEOUT):
                log.warning("save_experiment: receipt failed (attempt %d)",
                            attempt + 1)
                logs.append(_make_log_entry("warning", "receipt failed"))
                continue

            fire_t = time.perf_counter() - t0

            # Poll for file update
            poll_t0 = time.perf_counter()
            confirmed = False
            while (time.perf_counter() - poll_t0) < timeout:
                try:
                    if (xml_path.is_file()
                            and xml_path.stat().st_size > 0
                            and xml_path.stat().st_mtime > old_mtime):
                        # Settle for RGN companion file
                        time.sleep(0.3)
                        confirmed = True
                        break
                except OSError:
                    pass
                time.sleep(poll_interval)

            confirm_t = time.perf_counter() - poll_t0
            total_t = time.perf_counter() - t0

            if confirmed:
                return {
                    "success": True,
                    "confirmed": True,
                    "message": f"SaveExperiment '{name}'",
                    "timing": _make_timing(
                        fire_s=fire_t, confirm_s=confirm_t,
                        total_s=total_t, attempts=attempt + 1,
                        method="async"),
                    "logs": logs,
                }

            log.warning("save_experiment timeout (attempt %d) for '%s'",
                        attempt + 1, name)
            logs.append(_make_log_entry("warning", "timeout"))
        except Exception as e:
            log.error("save_experiment failed (attempt %d): %s",
                      attempt + 1, e)
            if attempt < max_retries - 1:
                time.sleep(poll_interval)
    return None


# =============================================================================
# Load experiment
# =============================================================================

def load_experiment(client, name, *, max_retries=3):
    """Load an experiment into LAS X (receipt only, no confirmation).

    Sets ``PyApiLoadExperiment.Model.ExperimentName`` and fires
    ``UpdateAwaitReceipt``. There is no reliable way to confirm the
    load took effect via the API alone — use a follow-up
    ``save_experiment`` to verify modifications persisted.

    Args:
        client: Live LAS X CAM client.
        name: Experiment file name including ``.xml`` extension.
        max_retries: Number of attempts on receipt failure.

    Returns:
        dict with success/message/timing/logs, or None on failure.
    """
    for attempt in range(max_retries):
        logs = []
        t0 = time.perf_counter()
        try:
            client.PyApiLoadExperiment.Model.ExperimentName = name
            if not client.PyApiLoadExperiment.UpdateAwaitReceipt(
                    RECEIPT_TIMEOUT):
                log.warning("load_experiment: receipt failed (attempt %d)",
                            attempt + 1)
                logs.append(_make_log_entry("warning", "receipt failed"))
                continue

            total_t = time.perf_counter() - t0
            return {
                "success": True,
                "confirmed": False,
                "message": f"LoadExperiment '{name}'",
                "timing": _make_timing(
                    fire_s=total_t,
                    total_s=total_t, attempts=attempt + 1,
                    method="async"),
                "logs": logs,
            }
        except Exception as e:
            log.error("load_experiment failed (attempt %d): %s",
                      attempt + 1, e)
    return None


# =============================================================================
# Template names
# =============================================================================

TEMPLATE_BASE = "{ScanningTemplate}_PythonInspect"
TEMPLATE_XML = TEMPLATE_BASE + ".xml"
TEMPLATE_RGN = TEMPLATE_BASE + ".rgn"
TEMPLATE_LRP = TEMPLATE_BASE + ".lrp"

STRIPPED_BASE = TEMPLATE_BASE + "_stripped"
STRIPPED_XML = STRIPPED_BASE + ".xml"
STRIPPED_RGN = STRIPPED_BASE + ".rgn"
STRIPPED_LRP = STRIPPED_BASE + ".lrp"

_SCAN_FIELDS_RE = re.compile(
    r"<ScanFields\b[^/]*?>.*?</ScanFields>",
    re.DOTALL,
)


# =============================================================================
# Strip / restore
# =============================================================================

def _strip_xml(src, dst):
    """Replace <ScanFields>...</ScanFields> with <ScanFields /> in dst."""
    text = src.read_text(encoding="utf-8")
    text = _SCAN_FIELDS_RE.sub("<ScanFields />", text)
    dst.write_text(text, encoding="utf-8")


def _strip_rgn(src, dst):
    """Create a minimal RGN with empty Items and FocusMap."""
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
    """Count ScanFieldData, RGN items, and focus points."""
    xml_text = xml_path.read_text(encoding="utf-8")
    rgn_tree = ET.parse(rgn_path)
    fields = len(re.findall(r"<ScanFieldData", xml_text))
    items = len(rgn_tree.findall(".//ShapeList/Items/*"))
    focus = len(rgn_tree.findall(".//FocusMap/*"))
    return fields, items, focus


def strip_template(client, *, max_restore_attempts=10):
    """Save current state, create stripped copy, and load it.

    1. Finds the ScanningTemplates directory.
    2. Saves the current experiment as ``_PythonInspect``.
    3. Creates ``_PythonInspect_stripped`` (XML + RGN stripped,
       LRP copied as-is).
    4. Loads the stripped version for responsive editing.

    Args:
        client: Live LAS X CAM client.
        max_restore_attempts: Not used here (reserved for restore_template).

    Returns:
        dict with success, templates_dir, original object counts,
        or None on failure.
    """
    templates_dir = find_scanning_templates_dir()
    if templates_dir is None:
        log.error("strip_template: cannot find ScanningTemplates dir")
        return None

    xml_path = templates_dir / TEMPLATE_XML
    rgn_path = templates_dir / TEMPLATE_RGN
    lrp_path = templates_dir / TEMPLATE_LRP

    stripped_xml = templates_dir / STRIPPED_XML
    stripped_rgn = templates_dir / STRIPPED_RGN
    stripped_lrp = templates_dir / STRIPPED_LRP

    t0 = time.perf_counter()

    # Step 1: Save current state
    r = save_experiment(client, TEMPLATE_XML, templates_dir)
    if r is None:
        log.error("strip_template: save failed")
        return None

    fields, items, focus = _count_objects(xml_path, rgn_path)
    log.info("strip_template: saved [%d fields, %d items, %d focus]",
             fields, items, focus)

    # Step 2: Create stripped copies
    _strip_xml(xml_path, stripped_xml)
    _strip_rgn(rgn_path, stripped_rgn)
    if lrp_path.is_file():
        shutil.copy2(lrp_path, stripped_lrp)

    # Step 3: Load stripped
    r = load_experiment(client, STRIPPED_XML)
    if r is None:
        log.error("strip_template: load stripped failed")
        return None

    # Step 4: Confirm strip via save
    r = save_experiment(client, STRIPPED_XML, templates_dir)
    if r is None:
        log.error("strip_template: confirm save failed")
        return None

    sf, it, fp = _count_objects(stripped_xml, stripped_rgn)
    if sf > 0 or it > 0 or fp > 0:
        log.warning("strip_template: stripped file still has objects "
                    "[%d fields, %d items, %d focus]", sf, it, fp)

    total_t = time.perf_counter() - t0
    log.info("strip_template: done in %.1fs", total_t)

    return {
        "success": True,
        "templates_dir": str(templates_dir),
        "original_fields": fields,
        "original_items": items,
        "original_focus": focus,
        "total_s": total_t,
    }


def restore_template(client, *, max_attempts=10):
    """Copy modified LRP back to original, reload, and clean up.

    1. Copies ``_stripped.lrp`` → ``_PythonInspect.lrp``
       (preserving LRP edits made while stripped).
    2. Loads ``_PythonInspect`` (with objects).
    3. Confirms via save + object count check, retrying the load
       if objects don't appear.
    4. Deletes ``_stripped`` files.

    Args:
        client: Live LAS X CAM client.
        max_attempts: Max load retries for object restoration.

    Returns:
        dict with success, restored object counts, attempts,
        or None on failure.
    """
    templates_dir = find_scanning_templates_dir()
    if templates_dir is None:
        log.error("restore_template: cannot find ScanningTemplates dir")
        return None

    xml_path = templates_dir / TEMPLATE_XML
    rgn_path = templates_dir / TEMPLATE_RGN
    lrp_path = templates_dir / TEMPLATE_LRP

    stripped_xml = templates_dir / STRIPPED_XML
    stripped_rgn = templates_dir / STRIPPED_RGN
    stripped_lrp = templates_dir / STRIPPED_LRP

    t0 = time.perf_counter()

    # Step 1: Back up modified LRP (edits made while stripped)
    bak_lrp = templates_dir / (TEMPLATE_BASE + ".lrp.bak")
    if stripped_lrp.is_file():
        shutil.copy2(stripped_lrp, bak_lrp)
        log.info("restore_template: backed up modified LRP")

    # Get expected object counts from original
    orig_fields, orig_items, orig_focus = _count_objects(xml_path, rgn_path)

    # Back up original XML/RGN — the confirm save may overwrite them
    # with stripped data if LAS X hasn't fully loaded the objects yet.
    bak_xml = templates_dir / (TEMPLATE_BASE + ".xml.bak")
    bak_rgn = templates_dir / (TEMPLATE_BASE + ".rgn.bak")
    shutil.copy2(xml_path, bak_xml)
    shutil.copy2(rgn_path, bak_rgn)

    # Step 2: Load original with retry until objects appear
    for attempt in range(1, max_attempts + 1):
        r = load_experiment(client, TEMPLATE_XML)
        if r is None:
            log.error("restore_template: load failed (attempt %d)", attempt)
            continue

        r = save_experiment(client, TEMPLATE_XML, templates_dir)
        if r is None:
            log.error("restore_template: confirm save failed (attempt %d)",
                      attempt)
            continue

        fields, items, focus = _count_objects(xml_path, rgn_path)
        log.info("restore_template attempt %d: [%d fields, %d items, "
                 "%d focus]", attempt, fields, items, focus)

        if items >= orig_items and fields >= orig_fields:
            break

        # Save overwrote original with stripped data — restore from backup
        shutil.copy2(bak_xml, xml_path)
        shutil.copy2(bak_rgn, rgn_path)
    else:
        total_t = time.perf_counter() - t0
        # Clean up backups even on failure
        bak_xml.unlink(missing_ok=True)
        bak_rgn.unlink(missing_ok=True)
        bak_lrp.unlink(missing_ok=True)
        log.error("restore_template: objects not restored after %d attempts "
                  "(%.1fs)", max_attempts, total_t)
        return None

    # Step 3: Copy modified LRP back (save_experiment overwrote it)
    if bak_lrp.is_file():
        shutil.copy2(bak_lrp, lrp_path)
        log.info("restore_template: restored modified LRP")

    total_t = time.perf_counter() - t0

    # Step 4: Clean up stripped files and backups
    for f in (stripped_xml, stripped_rgn, stripped_lrp,
              bak_xml, bak_rgn, bak_lrp):
        if f.is_file():
            f.unlink()

    log.info("restore_template: done in %.1fs (%d attempts) "
             "[%d fields, %d items, %d focus]",
             total_t, attempt, fields, items, focus)

    return {
        "success": True,
        "fields": fields,
        "items": items,
        "focus": focus,
        "attempts": attempt,
        "total_s": total_t,
    }

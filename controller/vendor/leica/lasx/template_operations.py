"""
Template operations — save, load, strip, and restore LAS X scanning templates.

These functions operate on **direct API objects**
(``PyApiSaveExperiment``, ``PyApiLoadExperiment``), not the
``PyApiCommand`` dispatch channel used by most readers and commands.

The receipt from ``UpdateAwaitReceipt`` confirms command *acceptance*,
not action *completion*.  Save confirmation is file-based: poll a
target file (XML, RGN, or LRP) for mtime change + size stability.
Load has no reliable on-disk confirmation — use a follow-up save.

High-level workflow::

    drv.strip_template(client)    # save → strip XML/RGN → load stripped
    # ... modify LRP files ...
    drv.restore_template(client)  # load original → confirm → cleanup

Stripping removes scan-field objects and regions so LAS X stays
responsive during LRP editing.  ``restore_template`` reloads the
original template (with all objects) and copies the modified LRP back.
"""

import logging
import os
import shutil
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from .utils import RECEIPT_TIMEOUT, _make_timing, _make_log_entry

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
#  File stability helpers
# ---------------------------------------------------------------------------

def _is_file_locked(path):
    """Return True if *path* is locked by another process (Windows).

    Opens the file in read+write mode; a ``PermissionError`` means
    another process (typically LAS X) holds an exclusive lock.
    """
    try:
        with open(path, "r+b"):
            return False
    except PermissionError:
        return True
    except OSError:
        return False


def _wait_file_stable(path, timeout, poll_interval=0.5, stable_readings=3):
    """Block until *path* has stable size and is unlocked.

    Requires *stable_readings* consecutive checks where the file
    exists, has non-zero size, the size hasn't changed, and the file
    is not locked.  Used before any ``shutil.copy`` to prevent
    ``PermissionError`` on files LAS X is still writing.

    Returns True if stable, False on timeout.
    """
    path = Path(path)
    t0 = time.perf_counter()
    consecutive = 0
    last_size = -1

    while (time.perf_counter() - t0) < timeout:
        try:
            if not path.is_file():
                consecutive = 0
                time.sleep(poll_interval)
                continue

            size = path.stat().st_size
            locked = _is_file_locked(path)

            if size == last_size and size > 0 and not locked:
                consecutive += 1
                if consecutive >= stable_readings:
                    return True
            else:
                consecutive = 0

            last_size = size
        except OSError:
            consecutive = 0

        time.sleep(poll_interval)

    return False


# ---------------------------------------------------------------------------
#  ScanningTemplates directory discovery
# ---------------------------------------------------------------------------

def find_scanning_templates_dir():
    """Locate the LAS X ScanningTemplates folder via ``%APPDATA%``.

    Returns the first ``User_*/ScanningTemplates`` directory found
    under ``Leica Microsystems/LAS X/MatrixScreener6``, or None.
    """
    appdata = os.environ.get("APPDATA")
    if not appdata:
        log.warning("APPDATA not set — cannot locate ScanningTemplates")
        return None
    base = Path(appdata) / "Leica Microsystems" / "LAS X" / "MatrixScreener6"
    if not base.is_dir():
        log.warning("MatrixScreener6 directory not found: %s", base)
        return None
    user_dirs = sorted(base.glob("User_*"))
    if not user_dirs:
        log.warning("No User_* directories in %s", base)
        return None
    templates = user_dirs[0] / "ScanningTemplates"
    return templates if templates.is_dir() else None


# ---------------------------------------------------------------------------
#  Save / load experiment
# ---------------------------------------------------------------------------

def save_experiment(client, name, templates_dir, *, timeout=30,
                    poll_interval=0.1, confirm_path=None):
    """Save the active experiment and wait for file-based confirmation.

    Fires ``PyApiSaveExperiment.UpdateAwaitReceipt``, then polls
    *confirm_path* (default: the XML) for an mtime change followed by
    3 consecutive stable size readings at *poll_interval*.

    Args:
        client: Live LAS X CAM client.
        name: Experiment filename (e.g. ``"template.xml"``).
        templates_dir: Path to the ScanningTemplates folder.
        timeout: Max seconds to wait for the file to stabilise.
        poll_interval: Seconds between ``stat()`` checks.
        confirm_path: File to poll.  Defaults to ``templates_dir/name``.
            Pass an RGN path for strip/restore, or an LRP path for
            settings changes.

    Returns:
        Result dict on success, None on timeout or receipt failure.
    """
    templates_dir = Path(templates_dir)
    watch_path = Path(confirm_path) if confirm_path else templates_dir / name
    t0 = time.perf_counter()

    try:
        old_mtime = watch_path.stat().st_mtime if watch_path.is_file() else 0

        # Fire save (retry receipt once on transient failure)
        client.PyApiSaveExperiment.Model.ExperimentName = name
        if not client.PyApiSaveExperiment.UpdateAwaitReceipt(RECEIPT_TIMEOUT):
            log.warning("Save receipt failed for '%s', retrying once", name)
            if not client.PyApiSaveExperiment.UpdateAwaitReceipt(
                    RECEIPT_TIMEOUT):
                log.error("Save receipt failed twice for '%s'", name)
                return None

        fire_t = time.perf_counter() - t0

        # Poll until mtime changes, then wait for 3 stable size readings
        poll_t0 = time.perf_counter()
        confirmed = False
        while (time.perf_counter() - poll_t0) < timeout:
            try:
                if (watch_path.is_file()
                        and watch_path.stat().st_size > 0
                        and watch_path.stat().st_mtime > old_mtime):
                    last_size = watch_path.stat().st_size
                    stable_count = 0
                    while (time.perf_counter() - poll_t0) < timeout:
                        time.sleep(poll_interval)
                        cur_size = watch_path.stat().st_size
                        if cur_size == last_size:
                            stable_count += 1
                            if stable_count >= 3:
                                confirmed = True
                                break
                        else:
                            stable_count = 0
                        last_size = cur_size
                    break
            except OSError:
                pass
            time.sleep(poll_interval)

        confirm_t = time.perf_counter() - poll_t0
        total_t = time.perf_counter() - t0

        if confirmed:
            log.debug("Saved '%s' in %.1fs (fire=%.2fs, confirm=%.2fs, "
                      "watching %s)", name, total_t, fire_t, confirm_t,
                      watch_path.name)
            return {
                "success": True,
                "confirmed": True,
                "message": f"SaveExperiment '{name}'",
                "timing": _make_timing(
                    fire_s=fire_t, confirm_s=confirm_t,
                    total_s=total_t, attempts=1, method="async"),
                "logs": [],
            }

        log.warning("Save timeout after %.1fs for '%s' (watching %s)",
                    timeout, name, watch_path.name)
        return None
    except Exception as e:
        log.error("Save failed for '%s': %s", name, e)
        return None


def load_experiment(client, name):
    """Load an experiment into LAS X (receipt only, no on-disk confirmation).

    Use a follow-up ``save_experiment`` to verify the load took effect.

    Returns:
        Result dict on success, None on receipt failure.
    """
    t0 = time.perf_counter()
    try:
        client.PyApiLoadExperiment.Model.ExperimentName = name
        if not client.PyApiLoadExperiment.UpdateAwaitReceipt(RECEIPT_TIMEOUT):
            log.warning("Load receipt failed for '%s', retrying once", name)
            if not client.PyApiLoadExperiment.UpdateAwaitReceipt(
                    RECEIPT_TIMEOUT):
                log.error("Load receipt failed twice for '%s'", name)
                return None

        total_t = time.perf_counter() - t0
        log.debug("Loaded '%s' in %.2fs", name, total_t)
        return {
            "success": True,
            "confirmed": False,
            "message": f"LoadExperiment '{name}'",
            "timing": _make_timing(
                fire_s=total_t, total_s=total_t,
                attempts=1, method="async"),
            "logs": [],
        }
    except Exception as e:
        log.error("Load failed for '%s': %s", name, e)
        return None


# ---------------------------------------------------------------------------
#  Template file names
# ---------------------------------------------------------------------------

TEMPLATE_BASE = "{ScanningTemplate}_PythonInspect"
TEMPLATE_XML = TEMPLATE_BASE + ".xml"
TEMPLATE_RGN = TEMPLATE_BASE + ".rgn"
TEMPLATE_LRP = TEMPLATE_BASE + ".lrp"

STRIPPED_BASE = TEMPLATE_BASE + "_stripped"
STRIPPED_XML = STRIPPED_BASE + ".xml"
STRIPPED_RGN = STRIPPED_BASE + ".rgn"
STRIPPED_LRP = STRIPPED_BASE + ".lrp"


# ---------------------------------------------------------------------------
#  Template state detection
# ---------------------------------------------------------------------------

def get_template_state(templates_dir=None):
    """Determine the current template state from files on disk.

    Returns:
        ``"fresh"`` — no ``_PythonInspect`` files exist yet.
        ``"unstripped"`` — original files exist and are current.
        ``"stripped"`` — stripped files exist and are newer than the original.
    """
    if templates_dir is None:
        templates_dir = find_scanning_templates_dir()
    if templates_dir is None:
        return "fresh"

    templates_dir = Path(templates_dir)
    xml_path = templates_dir / TEMPLATE_XML
    stripped_xml = templates_dir / STRIPPED_XML

    if not xml_path.is_file():
        return "fresh"
    if not stripped_xml.is_file():
        return "unstripped"
    if stripped_xml.stat().st_mtime > xml_path.stat().st_mtime:
        return "stripped"
    return "unstripped"


# ---------------------------------------------------------------------------
#  File-level strip helpers
# ---------------------------------------------------------------------------

def _strip_xml(src, dst):
    """Remove all ``<ScanFields>`` content from *src*, write to *dst*.

    Replaces the ``<ScanFields ...>...</ScanFields>`` block with a
    self-closing ``<ScanFields />``.  Uses string slicing (not regex)
    for speed on large files.
    """
    text = src.read_text(encoding="utf-8")
    start = text.find("<ScanFields")
    end = text.find("</ScanFields>")
    if start != -1 and end != -1:
        text = text[:start] + "<ScanFields />" + text[end + len("</ScanFields>"):]
    dst.write_text(text, encoding="utf-8")


def _strip_rgn(src, dst):
    """Create a minimal RGN from *src* with empty Items and FocusMap.

    Preserves ``FillMaskMode``, ``VertexUnitMode``, and ``ZMode``
    from the original so LAS X accepts the file without errors.
    """
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
    """Count scan fields, RGN items, and focus points.

    Returns ``(fields, items, focus)`` or ``(0, 0, 0)`` if either
    file is missing or corrupt.
    """
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


# ---------------------------------------------------------------------------
#  Strip template
# ---------------------------------------------------------------------------

def strip_template(client, *, save_timeout=120):
    """Save the active experiment, create a stripped copy, and load it.

    Workflow:
        1. Save current experiment (confirm on RGN).
        2. Create ``_stripped`` files — XML with ScanFields removed,
           RGN with empty Items/FocusMap, LRP copied as-is.
        3. Load the stripped template into LAS X.
        4. Confirm-save the stripped template (confirm on stripped RGN).

    Args:
        client: Live LAS X CAM client.
        save_timeout: Max seconds for the initial save.

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

    # 1. Save current state, confirm on RGN (last file LAS X writes)
    log.info("Saving current experiment...")
    r = save_experiment(client, TEMPLATE_XML, templates_dir,
                        timeout=save_timeout, confirm_path=rgn_path)
    if r is None:
        log.error("Initial save failed — aborting strip")
        return None

    fields, items, focus = _count_objects(xml_path, rgn_path)
    log.info("Saved: %d fields, %d items, %d focus points", fields, items, focus)

    # 2. Create stripped copies on disk
    log.info("Creating stripped template files...")
    _strip_xml(xml_path, stripped_xml)
    _strip_rgn(rgn_path, stripped_rgn)
    if lrp_path.is_file():
        shutil.copy2(lrp_path, stripped_lrp)

    if "<ScanFieldData" in stripped_xml.read_text(encoding="utf-8"):
        log.warning("Strip incomplete — stripped XML still contains "
                    "ScanFieldData elements")

    # 3. Load stripped template
    log.info("Loading stripped template...")
    r = load_experiment(client, STRIPPED_XML)
    if r is None:
        log.error("Failed to load stripped template")
        return None

    # 4. Confirm-save the stripped template (confirm on stripped RGN)
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


# ---------------------------------------------------------------------------
#  Restore template
# ---------------------------------------------------------------------------

_RESTORE_SAVE_TIMEOUTS = (120, 120, 180, 240)


def restore_template(client):
    """Reload the original template (with all objects) and clean up.

    Workflow:
        1. Back up the modified LRP and original XML/RGN.
        2. Load the original template and confirm-save on RGN.
        3. Verify object counts match the original.  If incomplete,
           restore backups and retry (up to 4 attempts with escalating
           save timeouts: 120 / 120 / 180 / 240 s).
        4. Copy the modified LRP back (save overwrites it).
        5. Delete stripped files and backups.

    Before any file copy, ``_wait_file_stable`` ensures LAS X has
    released its file locks — preventing the ``PermissionError`` that
    occurs with large templates.

    Args:
        client: Live LAS X CAM client.

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

    # 1. Back up files before we start modifying anything
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

    # 2. Load → save (confirm on RGN) → verify object counts
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

    # 3. Copy modified LRP back (save_experiment overwrote it)
    if bak_lrp.is_file():
        shutil.copy2(bak_lrp, lrp_path)
        log.debug("Restored modified LRP after confirm-save")

    total_t = time.perf_counter() - t0

    # 4. Clean up stripped files and backups
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

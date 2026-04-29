"""
Scanning template backbone.
============================
Save, load, strip, restore, and edit LAS X scanning templates.

This module provides the infrastructure for all template file
operations.  ``save_experiment`` and ``load_experiment`` handle
the API-level save/load commands.  ``strip_template`` and
``restore_template`` manage the strip/restore cycle that makes LRP
editing safe while LAS X is running.  ``apply_lrp_change`` is the
generic backbone for any LRP modification: save → edit → load →
save → verify.

High-level workflow::

    drv.strip_template(client)    # save → strip XML/RGN → load stripped
    # ... modify LRP files ...
    drv.restore_template(client)  # load original → confirm → cleanup

Stripping removes scan-field objects and regions so LAS X stays
responsive during LRP editing.  ``restore_template`` reloads the
original template (with all objects) and copies the modified LRP back.

Dependency direction:
    - Imports: ``utils``, ``readers`` (``get_selected_job``), and stdlib.
    - Imported by: ``__init__`` (re-export).
"""

import logging
import os
import shutil
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from .readers import get_selected_job
from .scanning_template_parsers import parse_lrp
from .utils import RECEIPT_TIMEOUT, _make_timing, _make_log_entry

log = logging.getLogger(__name__)


# =============================================================================
# File stability helpers
# =============================================================================

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
    is not locked.

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


# =============================================================================
# ScanningTemplates directory discovery
# =============================================================================

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


# =============================================================================
# Template file name constants
# =============================================================================

TEMPLATE_BASE = "{ScanningTemplate}_PythonInspect"
TEMPLATE_XML = TEMPLATE_BASE + ".xml"
TEMPLATE_RGN = TEMPLATE_BASE + ".rgn"
TEMPLATE_LRP = TEMPLATE_BASE + ".lrp"

STRIPPED_BASE = TEMPLATE_BASE + "_stripped"
STRIPPED_XML = STRIPPED_BASE + ".xml"
STRIPPED_RGN = STRIPPED_BASE + ".rgn"
STRIPPED_LRP = STRIPPED_BASE + ".lrp"


# =============================================================================
# Save + parse convenience
# =============================================================================

def save_and_read_lrp(client, *, timeout=5.0):
    """Save the current experiment and return parsed LRP data.

    Combines :func:`save_experiment` and :func:`parse_lrp` into a
    single call, handling template directory and file path resolution
    internally.

    Args:
        client: Live LAS X CAM client.
        timeout: Save confirmation timeout in seconds.

    Returns:
        Parsed LRP dict (same structure as :func:`parse_lrp`),
        or ``None`` if the save or parse fails.
    """
    tdir = find_scanning_templates_dir()
    if tdir is None:
        log.error("save_and_read_lrp: cannot locate ScanningTemplates dir")
        return None
    lrp_path = os.path.join(tdir, TEMPLATE_LRP)
    result = save_experiment(client, TEMPLATE_XML, tdir, timeout=timeout)
    if not result:
        log.warning("save_and_read_lrp: save_experiment returned no result")
    try:
        return parse_lrp(lrp_path)
    except Exception as e:
        log.error("save_and_read_lrp: parse failed: %s", e)
        return None


# =============================================================================
# Template state detection
# =============================================================================

def get_template_state(templates_dir=None):
    """Determine the current template state from files on disk.

    Returns:
        ``"fresh"`` — no ``_PythonInspect`` files exist yet.
        ``"unstripped"`` — original files exist and are current.
        ``"stripped"`` — stripped files exist and are newer than original.
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


# =============================================================================
# Save / load experiment
# =============================================================================

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

    Returns:
        Result dict on success, None on timeout or receipt failure.
    """
    templates_dir = Path(templates_dir)
    watch_path = Path(confirm_path) if confirm_path else templates_dir / name
    t0 = time.perf_counter()

    try:
        old_mtime = watch_path.stat().st_mtime if watch_path.is_file() else 0

        client.PyApiSaveExperiment.Model.ExperimentName = name
        if not client.PyApiSaveExperiment.UpdateAwaitReceipt(RECEIPT_TIMEOUT):
            log.warning("Save receipt failed for '%s', retrying once", name)
            if not client.PyApiSaveExperiment.UpdateAwaitReceipt(
                    RECEIPT_TIMEOUT):
                log.error("Save receipt failed twice for '%s'", name)
                return None

        fire_t = time.perf_counter() - t0

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


# =============================================================================
# XML / RGN strip helpers
# =============================================================================

def _strip_xml(src, dst):
    """Remove all ``<ScanFields>`` content from *src*, write to *dst*.

    Replaces the ``<ScanFields ...>...</ScanFields>`` block with a
    self-closing ``<ScanFields />``.
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


# =============================================================================
# Strip template
# =============================================================================

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


# =============================================================================
# Restore template
# =============================================================================

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
    released its file locks.

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


# =============================================================================
# Job reordering
# =============================================================================

def reorder_jobs(lrp_path, first_job):
    """Move a job to first position in the LRP.

    LAS X selects the first job after loading a template, so this
    controls which job is active in the GUI after a reload.

    Reorders both the ``LDM_Block_Sequence_Element_List`` and the
    ``LDM_Block_Sequence_Block_List``.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        first_job: Name of the job to move to first position.

    Returns:
        True if the job was moved (or was already first), False on error.
    """
    lrp_path = Path(lrp_path)
    root = ET.parse(lrp_path).getroot()

    el_list = root.find(".//LDM_Block_Sequence_Element_List")
    block_list = root.find(".//LDM_Block_Sequence_Block_List")
    if el_list is None or block_list is None:
        log.error("reorder_jobs: missing element/block list")
        return False

    block_to_job = {}
    for b in block_list:
        seq = b.find(".//LDM_Block_Sequential")
        if seq is not None:
            block_to_job[b.get("BlockID")] = seq.get("BlockName")

    el_by_job = {}
    for e in el_list:
        job = block_to_job.get(e.get("BlockID"))
        if job:
            el_by_job[job] = e

    block_by_job = {}
    for b in block_list:
        seq = b.find(".//LDM_Block_Sequential")
        if seq is not None:
            block_by_job[seq.get("BlockName")] = b

    if first_job not in block_by_job:
        log.error("reorder_jobs: job '%s' not found", first_job)
        return False

    current_order = [block_to_job[e.get("BlockID")] for e in el_list
                     if e.get("BlockID") in block_to_job]

    if current_order and current_order[0] == first_job:
        log.debug("reorder_jobs: '%s' already first", first_job)
        return True

    new_order = [first_job] + [j for j in current_order if j != first_job]

    for e in list(el_list):
        el_list.remove(e)
    for b in list(block_list):
        block_list.remove(b)

    for job_name in new_order:
        el_list.append(el_by_job[job_name])
        block_list.append(block_by_job[job_name])

    ET.ElementTree(root).write(str(lrp_path), encoding="unicode",
                               xml_declaration=False)
    log.info("reorder_jobs: moved '%s' to first position", first_job)
    return True


# =============================================================================
# LRP edit backbone
# =============================================================================

def apply_lrp_change(client, xml_name, lrp_edit_fn, *args,
                     verify_fn=None,
                     confirm_delays=(0.5, 1, 2, 4, 8, 16), **kwargs):
    """Apply an LRP edit with save → edit → reorder → load → save → verify.

    This is the generic backbone through which all LRP modifications
    are dispatched.  Individual edit functions (in
    ``scanning_template_editors``) provide the *lrp_edit_fn* and
    *verify_fn* callables; this function owns the surrounding
    save/load/verify cycle.

    Workflow:
        1. Save to flush LAS X state to disk.
        2. Query the currently selected job in LAS X.
        3. Edit the LRP file on disk via *lrp_edit_fn*.
        4. Reorder jobs so the previously active job stays first
           (LAS X selects the first job after reload).
        5. Load the template so LAS X picks up the change.
        6. Save again so LAS X writes its state back to disk.
        7. Verify the target attribute(s) in the saved file.

    The ``verify_fn`` should only check the specific attributes that
    were edited — LAS X regenerates many internal IDs on every save.

    Args:
        client: Live LAS X CAM client.
        xml_name: Template XML filename (e.g. ``TEMPLATE_XML`` or
            ``STRIPPED_XML``).
        lrp_edit_fn: Callable that modifies the LRP file.
            Called as ``lrp_edit_fn(lrp_path, *args, **kwargs)``.
        *args: Forwarded to *lrp_edit_fn*.
        verify_fn: Optional callable ``verify_fn(lrp_path) -> bool``
            that checks the saved file.  If None, success is assumed
            after save.
        confirm_delays: Sequence of delays (seconds) for confirm save
            attempts.  Length determines number of attempts.
        **kwargs: Forwarded to *lrp_edit_fn*.

    Returns:
        dict with success, edit_result, attempts, or None on failure.
    """
    templates_dir = find_scanning_templates_dir()
    if templates_dir is None:
        log.error("apply_lrp_change: cannot find ScanningTemplates dir")
        return None

    lrp_path = Path(templates_dir) / xml_name.replace(".xml", ".lrp")

    r = save_experiment(client, xml_name, templates_dir)
    if r is None:
        log.error("apply_lrp_change: initial save failed")
        return None

    current_job = get_selected_job(client)
    current_job_name = current_job.get("Name") if current_job else None
    if current_job_name:
        log.debug("apply_lrp_change: preserving active job '%s'",
                  current_job_name)
    else:
        log.warning("apply_lrp_change: could not determine active job")

    edit_result = lrp_edit_fn(lrp_path, *args, **kwargs)

    if current_job_name:
        reorder_jobs(lrp_path, current_job_name)

    r = load_experiment(client, xml_name)
    if r is None:
        log.error("apply_lrp_change: load failed")
        return None

    for attempt, save_timeout in enumerate(confirm_delays, 1):
        r = save_experiment(client, xml_name, templates_dir,
                            timeout=save_timeout)
        if r is None:
            log.warning("apply_lrp_change: confirm save timed out "
                        "(attempt %d, timeout=%.1fs)", attempt, save_timeout)
            continue

        if verify_fn is None or verify_fn(lrp_path):
            log.info("apply_lrp_change: verified after %d attempt(s)",
                     attempt)
            return {
                "success": True,
                "edit_result": edit_result,
                "attempts": attempt,
            }

        log.warning("apply_lrp_change: verification failed (attempt %d)",
                    attempt)

    log.error("apply_lrp_change: failed after %d attempts",
              len(confirm_delays))
    return None

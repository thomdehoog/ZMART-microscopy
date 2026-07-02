"""LRP edit transaction backbone.

``apply_lrp_change`` is the generic backbone through which all LRP
modifications are dispatched: save -> edit -> reorder -> load -> save
-> verify.

``reorder_jobs`` moves a job to first position in the LRP so LAS X
selects the right job after a template reload.

Dependency direction:
    - Imports: ``.files``, ``..readers``, stdlib.
    - Imported by: ``__init__`` (re-export), editor modules.
"""

import logging
import xml.etree.ElementTree as ET
from pathlib import Path

from ..readers import get_selected_job
from .files import find_scanning_templates_dir, load_experiment, save_experiment

log = logging.getLogger(__name__)


# =============================================================================
# Job reordering
# =============================================================================


def reorder_jobs(lrp_path, first_job):
    """Move a job to first position in the LRP.

    LAS X selects the first job after loading a template, so this
    controls which job is active in the GUI after a reload.

    Args:
        lrp_path: Path to the ``.lrp`` file.
        first_job: Name of the job to move to first position.

    Returns:
        True if the job was moved (or was already first), False on error.
    """
    lrp_path = Path(lrp_path)
    raw = lrp_path.read_text(encoding="utf-8")
    root = ET.fromstring(raw, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))

    el_list = root.find(".//LDM_Block_Sequence_Element_List")
    block_list = root.find(".//LDM_Block_Sequence_Block_List")
    if el_list is None or block_list is None:
        log.error("reorder_jobs: missing element/block list")
        return False

    target_block = None
    for b in block_list:
        seq = b.find(".//LDM_Block_Sequential")
        if seq is not None and seq.get("BlockName") == first_job:
            target_block = b
            break
    if target_block is None:
        log.error("reorder_jobs: job '%s' not found", first_job)
        return False

    block_id = target_block.get("BlockID")
    target_el = next((e for e in el_list if e.get("BlockID") == block_id), None)
    if target_el is None:
        log.error(
            "reorder_jobs: no sequence element for job '%s' (BlockID=%s)", first_job, block_id
        )
        return False

    if list(el_list)[0] is target_el and list(block_list)[0] is target_block:
        log.debug("reorder_jobs: '%s' already first", first_job)
        return True

    # Move the target's entries to the front; every other entry keeps its
    # place. Blocks/elements the job maps miss (non-job block types,
    # unmapped BlockIDs, duplicates) must survive the reorder untouched.
    el_list.remove(target_el)
    el_list.insert(0, target_el)
    block_list.remove(target_block)
    block_list.insert(0, target_block)

    # LAS X writes the XML declaration and its header comments *before* the
    # root element, where ElementTree cannot represent them — preserve that
    # prolog verbatim and re-serialize only the root. Always write UTF-8:
    # a locale-encoded write would corrupt non-ASCII job names.
    root_start = raw.find(f"<{root.tag}")
    prolog = raw[:root_start] if root_start > 0 else '<?xml version="1.0"?>'
    lrp_path.write_text(prolog + ET.tostring(root, encoding="unicode"), encoding="utf-8")
    log.info("reorder_jobs: moved '%s' to first position", first_job)
    return True


# =============================================================================
# LRP edit backbone
# =============================================================================


def apply_lrp_change(
    client,
    xml_name,
    lrp_edit_fn,
    *args,
    verify_fn=None,
    confirm_delays=(2, 4, 8, 16),
    **kwargs,
):
    """Apply an LRP edit with save -> edit -> reorder -> load -> save -> verify.

    Args:
        client: Live LAS X CAM client.
        xml_name: Template XML filename.
        lrp_edit_fn: Callable that modifies the LRP file.
            Called as ``lrp_edit_fn(lrp_path, *args, **kwargs)``.
        *args: Forwarded to *lrp_edit_fn*.
        verify_fn: Optional callable ``verify_fn(lrp_path) -> bool``
            that checks the saved file.
        confirm_delays: Per-attempt save *timeouts* (seconds) for the
            confirm save attempts, escalating across retries.
        **kwargs: Forwarded to *lrp_edit_fn*.

    Returns:
        dict with success, edit_result, attempts, or None on failure.

    There is no rollback: a failure after the edit leaves the on-disk LRP
    modified while LAS X's in-memory template may be stale. Pass a
    *verify_fn* whenever the edit's effect can be checked — an edit that
    changed nothing (e.g. job not found) still reaches the confirm stage.
    """
    templates_dir = find_scanning_templates_dir()
    if templates_dir is None:
        log.error("apply_lrp_change: cannot find ScanningTemplates dir")
        return None

    lrp_path = Path(templates_dir) / xml_name.replace(".xml", ".lrp")

    r = save_experiment(client, xml_name, templates_dir, confirm_path=lrp_path)
    if r is None:
        log.error("apply_lrp_change: initial save failed")
        return None

    current_job = get_selected_job(client)
    current_job_name = current_job.get("Name") if current_job else None
    if current_job_name:
        log.debug("apply_lrp_change: preserving active job '%s'", current_job_name)
    else:
        log.warning("apply_lrp_change: could not determine active job")

    edit_result = lrp_edit_fn(lrp_path, *args, **kwargs)
    if not edit_result:
        # 0/None covers both "already at target" and "job/attribute not
        # found" — the edit fns log which. Surface it here because without
        # a verify_fn the caller would otherwise see success=True.
        log.warning("apply_lrp_change: edit reported no changes (edit_result=%r)", edit_result)

    if current_job_name:
        reorder_jobs(lrp_path, current_job_name)

    r = load_experiment(client, xml_name)
    if r is None:
        log.error("apply_lrp_change: load failed")
        return None

    for attempt, save_timeout in enumerate(confirm_delays, 1):
        r = save_experiment(
            client, xml_name, templates_dir, timeout=save_timeout, confirm_path=lrp_path
        )
        if r is None:
            log.warning(
                "apply_lrp_change: confirm save timed out (attempt %d, timeout=%.1fs)",
                attempt,
                save_timeout,
            )
            continue

        if verify_fn is None or verify_fn(lrp_path):
            log.info("apply_lrp_change: verified after %d attempt(s)", attempt)
            return {
                "success": True,
                "edit_result": edit_result,
                "attempts": attempt,
            }

        log.warning("apply_lrp_change: verification failed (attempt %d)", attempt)

    log.error("apply_lrp_change: failed after %d attempts", len(confirm_delays))
    return None

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

from .files import find_scanning_templates_dir, save_experiment, load_experiment
from ..readers import get_selected_job

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
    """Apply an LRP edit with save -> edit -> reorder -> load -> save -> verify.

    Args:
        client: Live LAS X CAM client.
        xml_name: Template XML filename.
        lrp_edit_fn: Callable that modifies the LRP file.
            Called as ``lrp_edit_fn(lrp_path, *args, **kwargs)``.
        *args: Forwarded to *lrp_edit_fn*.
        verify_fn: Optional callable ``verify_fn(lrp_path) -> bool``
            that checks the saved file.
        confirm_delays: Sequence of delays (seconds) for confirm save
            attempts.
        **kwargs: Forwarded to *lrp_edit_fn*.

    Returns:
        dict with success, edit_result, attempts, or None on failure.
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
                            timeout=save_timeout, confirm_path=lrp_path)
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

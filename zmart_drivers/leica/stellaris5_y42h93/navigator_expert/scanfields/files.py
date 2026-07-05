"""Scan-field file I/O and constants.

Save/load experiments, locate the ScanningTemplates directory,
detect template state, and define the canonical filename constants.

``save_experiment`` / ``load_experiment`` fire ``PyApi{Save,Load}Experiment``
directly on the client — mutations outside the ``commands.commands`` wrappers
— so they carry their own function-keyed limits gate (``commands.gate``,
keys ``save_experiment`` / ``load_experiment``): with no valid machine-local
limits the receipt is never fired and the call returns ``None`` (the
functions' existing failure contract) after logging the refusal.

Dependency direction:
    - Imports: ``..utils``, ``..commands.gate``, ``.lrp``, ``_file_utils``,
      stdlib.
    - Imported by: ``strip_restore``, ``transaction``, ``__init__`` (re-export).
"""

import logging
import os
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from .._file_utils import _wait_file_stable
from ..commands import gate as _gate
from ..utils import RECEIPT_TIMEOUT, _make_timing
from .lrp import parse_lrp

log = logging.getLogger(__name__)


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
    if len(user_dirs) > 1:
        # Guessing alphabetically could edit another user's templates.
        log.error(
            "Multiple LAS X user profiles found (%s); cannot pick one safely — "
            "pass the ScanningTemplates dir explicitly",
            ", ".join(d.name for d in user_dirs),
        )
        return None
    templates = user_dirs[0] / "ScanningTemplates"
    return templates if templates.is_dir() else None


# =============================================================================
# Template state detection
# =============================================================================


def get_template_state(templates_dir=None):
    """Determine the current template state from files on disk.

    Returns:
        ``"fresh"`` when no canonical ``_PythonInspect`` files exist.
        ``"unstripped"`` when the canonical files contain scan fields,
        region objects, or focus points.
        ``"stripped"`` when the active sidecar is newer than the
        canonical XML, or when the canonical files contain no objects.
        ``"unreadable"`` when the canonical files exist but cannot be
        parsed — a corrupt template must not masquerade as "stripped"
        and invite a workflow to proceed as if stripping succeeded.
    """
    if templates_dir is None:
        templates_dir = find_scanning_templates_dir()
    if templates_dir is None:
        return "fresh"

    templates_dir = Path(templates_dir)
    xml_path = templates_dir / TEMPLATE_XML
    rgn_path = templates_dir / TEMPLATE_RGN
    stripped_xml = templates_dir / STRIPPED_XML

    if not xml_path.is_file():
        return "fresh"
    try:
        xml_path.read_text(encoding="utf-8")
        ET.parse(rgn_path)
    except (OSError, ET.ParseError) as e:
        log.warning("get_template_state: canonical template unreadable: %s", e)
        return "unreadable"
    if not stripped_xml.is_file():
        return "unstripped" if _template_has_objects(xml_path, rgn_path) else "stripped"
    if stripped_xml.stat().st_mtime > xml_path.stat().st_mtime:
        return "stripped"
    return "unstripped" if _template_has_objects(xml_path, rgn_path) else "stripped"


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


def _template_has_objects(xml_path, rgn_path):
    """Return True when a canonical template contains operator objects."""
    return any(_count_objects(xml_path, rgn_path))


# =============================================================================
# Save / load experiment
# =============================================================================


def save_experiment(
    client, name, templates_dir, *, timeout=30, poll_interval=0.1, confirm_path=None
):
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
        Result dict on success, None on timeout, receipt failure, or a
        function-limits refusal (logged at ERROR).
    """
    refused = _gate.check_refusal(client, "save_experiment", {"name": name})
    if refused is not None:
        log.error(refused)
        return None

    templates_dir = Path(templates_dir)
    watch_path = Path(confirm_path) if confirm_path else templates_dir / name
    t0 = time.perf_counter()

    try:
        old_mtime = watch_path.stat().st_mtime if watch_path.is_file() else 0

        client.PyApiSaveExperiment.Model.ExperimentName = name
        if not client.PyApiSaveExperiment.UpdateAwaitReceipt(RECEIPT_TIMEOUT):
            log.warning("Save receipt failed for '%s', retrying once", name)
            if not client.PyApiSaveExperiment.UpdateAwaitReceipt(RECEIPT_TIMEOUT):
                log.error("Save receipt failed twice for '%s'", name)
                return None

        fire_t = time.perf_counter() - t0

        poll_t0 = time.perf_counter()
        confirmed = False
        while (time.perf_counter() - poll_t0) < timeout:
            try:
                if (
                    watch_path.is_file()
                    and watch_path.stat().st_size > 0
                    and watch_path.stat().st_mtime > old_mtime
                ):
                    remaining = timeout - (time.perf_counter() - poll_t0)
                    confirmed = _wait_file_stable(
                        watch_path, remaining, poll_interval, stable_readings=3
                    )
                    break
            except OSError:
                pass
            time.sleep(poll_interval)

        confirm_t = time.perf_counter() - poll_t0
        total_t = time.perf_counter() - t0

        if confirmed:
            log.debug(
                "Saved '%s' in %.1fs (fire=%.2fs, confirm=%.2fs, watching %s)",
                name,
                total_t,
                fire_t,
                confirm_t,
                watch_path.name,
            )
            return {
                "success": True,
                "confirmed": True,
                "message": f"SaveExperiment '{name}'",
                "timing": _make_timing(
                    fire_s=fire_t, confirm_s=confirm_t, total_s=total_t, attempts=1, method="async"
                ),
                "logs": [],
            }

        log.warning(
            "Save timeout after %.1fs for '%s' (watching %s)", timeout, name, watch_path.name
        )
        return None
    except Exception as e:
        log.error("Save failed for '%s': %s", name, e)
        return None


def load_experiment(client, name):
    """Load an experiment into LAS X (receipt only, no on-disk confirmation).

    Use a follow-up ``save_experiment`` to verify the load took effect.

    Returns:
        Result dict on success, None on receipt failure or a function-limits
        refusal (logged at ERROR).
    """
    refused = _gate.check_refusal(client, "load_experiment", {"name": name})
    if refused is not None:
        log.error(refused)
        return None

    t0 = time.perf_counter()
    try:
        client.PyApiLoadExperiment.Model.ExperimentName = name
        if not client.PyApiLoadExperiment.UpdateAwaitReceipt(RECEIPT_TIMEOUT):
            log.warning("Load receipt failed for '%s', retrying once", name)
            if not client.PyApiLoadExperiment.UpdateAwaitReceipt(RECEIPT_TIMEOUT):
                log.error("Load receipt failed twice for '%s'", name)
                return None

        total_t = time.perf_counter() - t0
        log.debug("Loaded '%s' in %.2fs", name, total_t)
        return {
            "success": True,
            "confirmed": False,
            "message": f"LoadExperiment '{name}'",
            "timing": _make_timing(fire_s=total_t, total_s=total_t, attempts=1, method="async"),
            "logs": [],
        }
    except Exception as e:
        log.error("Load failed for '%s': %s", name, e)
        return None


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
        # Returning the parse anyway would hand the caller *stale* pre-save
        # hardware settings while claiming they are current.
        log.error("save_and_read_lrp: save failed; not parsing the stale on-disk LRP")
        return None
    try:
        return parse_lrp(lrp_path)
    except Exception as e:
        log.error("save_and_read_lrp: parse failed: %s", e)
        return None

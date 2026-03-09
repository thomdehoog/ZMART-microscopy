"""
Template operations.
====================
Save and load LAS X scanning templates with confirmation.

These functions operate on **direct API objects**
(``PyApiSaveExperiment``, ``PyApiLoadExperiment``), not the
``PyApiCommand`` dispatch channel used by most readers and commands.

The receipt from ``UpdateAwaitReceipt`` confirms command *acceptance*,
not action *completion*:

    - **Save** confirmation is file-based: poll the XML file's mtime
      on disk until it is updated.
    - **Load** confirmation is name-based: validate the experiment name
      via readback on ``PyApiLoadExperiment.Model.ExperimentName``.

Functions follow the same retry/return conventions as the rest of the
driver (dict on success, ``None`` on failure).

Dependency direction:
    - Imports: ``utils`` (``RECEIPT_TIMEOUT``, ``_make_timing``,
      ``_make_log_entry``).
    - Imported by: ``__init__`` (re-export).
"""

import logging
import os
import time
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

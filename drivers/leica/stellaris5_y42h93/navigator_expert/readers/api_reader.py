"""
Read functions.
===============
Read-only queries against the LAS X Python API: scan status, connection
health, job settings, hardware info, XY stage position, job list, and
LAS X application settings (parsed from the on-disk XML file).

Most queries follow a **flush-fire-poll** pattern:

    1. Flush the data model to a sentinel (None or NaN) so fresh data
       can be detected.
    2. Write the command name to ``PyApiCommand.Model.Command``.
    3. Fire via ``PyApiCommand.UpdateAwaitReceipt()`` to ensure the
       command is accepted before polling.
    4. Poll the dedicated data-object model until it transitions from
       the sentinel to a real value, or timeout.

Using ``UpdateAwaitReceipt`` on ``PyApiCommand`` is cheap (1-4 ms) and
prevents commands from being silently dropped when dispatched in rapid
succession (e.g. during ``confirm_move_xy``).

``get_lasx_settings`` is the exception: it reads the Navigator Expert
XML configuration file directly from disk (no API round-trip).

These functions do NOT modify microscope state.

Dependency direction:
    - Imports: derived readers, stdlib (json, logging, os, time, xml).
    - Imported by: ``prechecks`` (scan status polling), ``confirmations``
      (readback via ``get_job_settings`` and ``get_xy``),
      ``commands`` (early-exit checks, post-processing readbacks),
      ``__init__`` (re-export).
"""

import json
import logging
import math
import os
import time
import xml.etree.ElementTree as ET

from ..utils import RECEIPT_TIMEOUT
from . import derived

log = logging.getLogger(__name__)


# =============================================================================
# Scan status
# =============================================================================


def get_scan_status(client):
    """Read current scanner state string from PyApiStatus."""
    try:
        return str(client.PyApiStatus.Model.ScanStatus)
    except Exception:
        return "Unknown"


# =============================================================================
# Connection health
# =============================================================================


def ping(client):
    """Lightweight connection check. Returns True if LAS X responds."""
    try:
        receipt = client.PyApiPing.UpdateAwaitReceipt(RECEIPT_TIMEOUT)
        if receipt:
            return True
        # Transport failure: try fallback
    except Exception:
        pass
    # Fallback: try reading scan status
    try:
        _ = client.PyApiStatus.Model.ScanStatus
        return True
    except Exception:
        return False


# =============================================================================
# Read functions
# =============================================================================


def get_job_settings(client, job_name, timeout=1.0, poll_interval=0.01, max_retries=3):
    """Read full job settings JSON from LAS X.

    Uses the dual-dispatch pattern: commits the JobName parameter on
    the dedicated API object, then fires GetJobSettingsByName via the
    command channel and polls until data arrives.  Retries the full
    commit->flush->fire->poll cycle up to *max_retries* times.
    """
    for attempt in range(1, max_retries + 1):
        try:
            client.PyApiGetJobSettingsByName.Model.JobName = job_name
            try:
                client.PyApiGetJobSettingsByName.UpdateAwaitReceipt(RECEIPT_TIMEOUT)
            except Exception:
                pass  # best-effort; command channel is the real transport

            client.PyApiGetJobSettingsByName.Model.Settings = None

            client.PyApiCommand.Model.Command = ""
            client.PyApiCommand.Model.Command = "GetJobSettingsByName"
            if not client.PyApiCommand.UpdateAwaitReceipt(RECEIPT_TIMEOUT):
                log.warning(
                    "get_job_settings: attempt %d/%d receipt failed for '%s'",
                    attempt,
                    max_retries,
                    job_name,
                )
                continue

            deadline = time.perf_counter() + timeout
            while time.perf_counter() < deadline:
                raw = client.PyApiGetJobSettingsByName.Model.Settings
                if raw is not None:
                    parsed = json.loads(raw) if isinstance(raw, str) else raw
                    # LAS X occasionally returns a populated dict whose
                    # geometry fields are blank - happens right after a
                    # zoom or format change while the engine is still
                    # repopulating. Treat that the same as None and let
                    # the retry loop wait for the real values.
                    if isinstance(parsed, dict) and not parsed.get("imageSize"):
                        log.debug(
                            "get_job_settings: empty imageSize on attempt %d/%d; retrying",
                            attempt,
                            max_retries,
                        )
                        break
                    return parsed
                time.sleep(poll_interval)

            log.warning(
                "get_job_settings: attempt %d/%d timed out for '%s'", attempt, max_retries, job_name
            )
        except Exception as e:
            log.error("get_job_settings attempt %d/%d failed: %s", attempt, max_retries, e)

    log.error("get_job_settings: all %d attempts failed for '%s'", max_retries, job_name)
    return None


def get_hardware_info(client, timeout=1.0, poll_interval=0.01, max_retries=3):
    """Read confocal hardware info from LAS X.

    Flushes HWInfo to None, fires GetConfocalHardwareInfo via
    UpdateAwaitReceipt, then polls until data arrives. Retries up to
    *max_retries* times.
    """
    for attempt in range(1, max_retries + 1):
        try:
            try:
                client.PyApiGetConfocalHardwareInfo.Model.HWInfo = None
            except Exception:
                pass

            client.PyApiCommand.Model.Command = ""
            client.PyApiCommand.Model.Command = "GetConfocalHardwareInfo"
            if not client.PyApiCommand.UpdateAwaitReceipt(RECEIPT_TIMEOUT):
                log.warning("get_hardware_info: attempt %d/%d receipt failed", attempt, max_retries)
                continue

            deadline = time.perf_counter() + timeout
            while time.perf_counter() < deadline:
                raw = client.PyApiGetConfocalHardwareInfo.Model.HWInfo
                if raw is not None:
                    return json.loads(raw) if isinstance(raw, str) else raw
                time.sleep(poll_interval)

            log.warning("get_hardware_info: attempt %d/%d timed out", attempt, max_retries)
        except Exception as e:
            log.error("get_hardware_info attempt %d/%d failed: %s", attempt, max_retries, e)

    log.error("get_hardware_info: all %d attempts failed", max_retries)
    return None


def get_xy(client, timeout=1.0, poll_interval=0.01, max_retries=3):
    """Read current XY stage position.

    Flushes the model to NaN, fires GetXY via UpdateAwaitReceipt, then
    polls until fresh (non-NaN) data arrives. Retries up to
    *max_retries* times.

    Returns:
        dict with x/y in meters and microns, or None on failure.
    """
    for attempt in range(1, max_retries + 1):
        try:
            client.PyApiGetXY.Model.XPosition = float("nan")
            client.PyApiGetXY.Model.YPosition = float("nan")

            client.PyApiCommand.Model.Command = ""
            client.PyApiCommand.Model.Command = "GetXY"
            if not client.PyApiCommand.UpdateAwaitReceipt(RECEIPT_TIMEOUT):
                log.warning("get_xy: attempt %d/%d receipt failed", attempt, max_retries)
                continue

            deadline = time.perf_counter() + timeout
            while time.perf_counter() < deadline:
                x = client.PyApiGetXY.Model.XPosition
                y = client.PyApiGetXY.Model.YPosition

                if not (math.isnan(x) or math.isnan(y)):
                    return {
                        "x": x,
                        "y": y,
                        "x_um": x * 1e6,
                        "y_um": y * 1e6,
                    }
                time.sleep(poll_interval)

            log.warning("get_xy: attempt %d/%d timed out", attempt, max_retries)
        except Exception as e:
            log.error("get_xy attempt %d/%d failed: %s", attempt, max_retries, e)

    log.error("get_xy: all %d attempts failed", max_retries)
    return None


def read_zwide_um(client, job_name):
    """Return the live z-wide position (in um) for the given job.

    Parses the ``zPosition.z-wide`` field from
    :func:`get_job_settings` (after :func:`make_changeable_copy` has
    flattened the API JSON). Raises ``RuntimeError`` if the readback
    is unavailable: almost always means the job is not selected or
    the LAS X version doesn't expose Z readback in this shape.
    """
    from ..commands.settings import make_changeable_copy

    settings = get_job_settings(client, job_name)
    if not settings:
        raise RuntimeError(f"could not read job settings for '{job_name}'")
    ch = make_changeable_copy(settings)
    if not ch or "zPosition" not in ch:
        raise RuntimeError("zPosition not in job settings - LAS X version mismatch?")
    val = ch["zPosition"].get("z-wide")
    if val is None:
        raise RuntimeError(f"z-wide readback missing; got {ch['zPosition']!r}")
    return float(val)


def get_jobs(client, timeout=1.0, poll_interval=0.01, max_retries=3):
    """List all available jobs and their selection status.

    Flushes Jobs to None, fires GetJobsInformation via
    UpdateAwaitReceipt, then polls until data arrives. Retries up to
    *max_retries* times.
    """
    for attempt in range(1, max_retries + 1):
        try:
            try:
                client.PyApiGetJobsInformation.Model.Jobs = None
            except Exception:
                pass

            client.PyApiCommand.Model.Command = ""
            client.PyApiCommand.Model.Command = "GetJobsInformation"
            if not client.PyApiCommand.UpdateAwaitReceipt(RECEIPT_TIMEOUT):
                log.warning("get_jobs: attempt %d/%d receipt failed", attempt, max_retries)
                continue

            deadline = time.perf_counter() + timeout
            while time.perf_counter() < deadline:
                raw = client.PyApiGetJobsInformation.Model.Jobs
                if raw is not None:
                    return json.loads(raw) if isinstance(raw, str) else raw
                time.sleep(poll_interval)

            log.warning("get_jobs: attempt %d/%d timed out", attempt, max_retries)
        except Exception as e:
            log.error("get_jobs attempt %d/%d failed: %s", attempt, max_retries, e)

    log.error("get_jobs: all %d attempts failed", max_retries)
    return None


def get_job_by_name(client, job_name, **kwargs):
    """Return the metadata dict for a single job, or None if not found.

    Convenience wrapper around get_jobs(). All keyword arguments are
    forwarded to get_jobs().
    """
    return derived.job_by_name(get_jobs(client, **kwargs), job_name)


def get_selected_job(client, **kwargs):
    """Return the metadata dict for the currently selected job, or None.

    Convenience wrapper around get_jobs(). All keyword arguments are
    forwarded to get_jobs().
    """
    return derived.selected_job(get_jobs(client, **kwargs))


def get_fov(client, job_name, **kwargs):
    """Return the scan field size for a job in metres.

    Queries ``get_job_settings`` and parses ``imageSize``.

    Args:
        client: Live LAS X CAM client.
        job_name: Job name to query.
        **kwargs: Forwarded to ``get_job_settings``.

    Returns:
        ``(width_m, height_m)`` tuple, or ``None`` on failure.
    """
    settings = get_job_settings(client, job_name, **kwargs)
    if not settings:
        log.error("get_fov: no settings for job '%s'", job_name)
        return None
    value = derived.fov_from_settings(settings)
    if value is None:
        log.error("get_fov: cannot parse FOV for '%s'", job_name)
    return value


def get_base_fov(client, job_name, **kwargs):
    """Return the objective's full field of view (at zoom 1) in metres.

    Reads the current FOV and zoom from the API, then scales back to
    zoom 1.  This is a fundamental property of the objective and scan
    configuration; it does not change with zoom.

    Args:
        client: Live LAS X CAM client.
        job_name: Job name to query.
        **kwargs: Forwarded to ``get_job_settings``.

    Returns:
        ``(width_m, height_m)`` tuple at zoom 1, or ``None`` on failure.
    """
    settings = get_job_settings(client, job_name, **kwargs)
    if not settings:
        log.error("get_base_fov: no settings for job '%s'", job_name)
        return None
    value = derived.base_fov_from_settings(settings)
    if value is None:
        log.error("get_base_fov: cannot parse FOV for '%s'", job_name)
    return value


# =============================================================================
# LAS X application settings (from XML on disk)
# =============================================================================

_SETTINGS_PATH = os.path.join(
    os.getenv("APPDATA", ""),
    "Leica Microsystems",
    "LAS X",
    "MatrixScreener6",
    "User_0",
    "Settings",
    "{Settings}MatrixScreenerM6.xml",
)


def _xml_text(parent, tag, default=None):
    """Get text content of a child element, or default."""
    el = parent.find(tag)
    if el is not None and el.text and el.text.strip():
        return el.text.strip()
    return default


def _xml_bool(parent, tag, default=False):
    """Get boolean from child element text ('true'/'false')."""
    val = _xml_text(parent, tag)
    if val is None:
        return default
    return val.lower() == "true"


def _xml_int(parent, tag, default=0):
    """Get int from child element text."""
    val = _xml_text(parent, tag)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def get_lasx_settings(settings_path=None):
    """Read LAS X MatrixScreener / Navigator Expert settings from disk.

    Only parses the sections consumed by the driver: data export,
    export formats, and image orientation.

    Args:
        settings_path: Override path to the XML file. None uses the
            default APPDATA location.

    Returns:
        dict with sections, or None if the file doesn't exist.
    """
    path = settings_path or _SETTINGS_PATH
    if not os.path.exists(path):
        log.warning("LAS X settings file not found: %s", path)
        return None

    tree = ET.parse(path)
    root = tree.getroot()

    nav = root.find("SettingsNavigatorExpert")
    result = {}

    if nav is not None:
        exporter = nav.find("SettingsDataExporter")
        if exporter is not None:
            result["export"] = {
                "media_path": _xml_text(exporter, "MediaPath"),
                "auto_export": _xml_bool(exporter, "ExportDataAutomatically"),
                "delete_after_export": _xml_bool(exporter, "DeleteExportedExperiments"),
                "auto_save": _xml_bool(exporter, "UseAutoSave"),
                "save_lif_in_folder": _xml_bool(exporter, "SaveLIFInExperimentFolder"),
            }

        fmt = nav.find("ExportFileFormats")
        if fmt is not None:
            result["export_formats"] = {
                "ome_tif": _xml_bool(fmt, "AsOmeTifFile"),
                "multipage_ome_tif": _xml_bool(fmt, "AsMultiPageOmeTifFile"),
                "multipage_tif": _xml_bool(fmt, "AsMultiPageTifFile"),
                "tif": _xml_bool(fmt, "AsTifFile"),
                "imagej_tif": _xml_bool(fmt, "AsImageJTifFile"),
                "bmp": _xml_bool(fmt, "AsBitmapFile"),
                "jpg": _xml_bool(fmt, "AsJpgFile"),
                "png": _xml_bool(fmt, "AsPngFile"),
                "lif": _xml_bool(fmt, "AsLifFile"),
                "xlef": _xml_bool(fmt, "AsXLefFile"),
                "screenshot": _xml_bool(fmt, "AsScreenShot"),
                "combine_mosaics": _xml_bool(fmt, "CombineMosaics"),
                "enable_edof": _xml_bool(fmt, "EnableEDOF"),
                "compression": _xml_bool(fmt, "EnableImageCompression"),
                "compression_value": _xml_int(fmt, "ImageCompressionValue"),
            }

        img_exp = nav.find("SettingsExportedImage")
        if img_exp is not None:
            result["image_orientation"] = {
                "enable_transform": _xml_bool(img_exp, "EnableImageTransformation"),
                "transformation": _xml_text(img_exp, "ImageTransformation", "RIGHTTOP"),
            }

    return result

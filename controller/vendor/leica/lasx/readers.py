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
    3. Fire via ``PyApiCommand.UpdateAsync()`` (no receipt wait).
    4. Poll the dedicated data-object model until it transitions from
       the sentinel to a real value, or timeout.

This avoids the slow ``UpdateAwaitReceipt`` round-trip. The polling
loop is the authoritative signal for data arrival.

``get_lasx_settings`` is the exception — it reads the Navigator Expert
XML configuration file directly from disk (no API round-trip).

These functions do NOT modify microscope state.

Dependency direction:
    - Imports: stdlib only (json, logging, os, time, xml).
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

from .utils import RECEIPT_TIMEOUT

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
        # Transport failure — try fallback
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

def get_job_settings(client, job_name, timeout=1.0, poll_interval=0.01,
                     max_retries=3):
    """Read full job settings JSON from LAS X.

    Flushes Settings to None, fires GetJobSettingsByName via UpdateAsync,
    then polls until data arrives. Retries the full flush→fire→poll cycle
    up to *max_retries* times.
    """
    for attempt in range(1, max_retries + 1):
        try:
            client.PyApiGetJobSettingsByName.Model.JobName = job_name
            client.PyApiGetJobSettingsByName.Model.Settings = None

            client.PyApiCommand.Model.Command = ""
            client.PyApiCommand.Model.Command = "GetJobSettingsByName"
            client.PyApiCommand.UpdateAsync()

            deadline = time.perf_counter() + timeout
            while time.perf_counter() < deadline:
                raw = client.PyApiGetJobSettingsByName.Model.Settings
                if raw is not None:
                    return json.loads(raw) if isinstance(raw, str) else raw
                time.sleep(poll_interval)

            log.warning("get_job_settings: attempt %d/%d timed out for '%s'",
                        attempt, max_retries, job_name)
        except Exception as e:
            log.error("get_job_settings attempt %d/%d failed: %s",
                      attempt, max_retries, e)

    log.error("get_job_settings: all %d attempts failed for '%s'",
              max_retries, job_name)
    return None


def get_hardware_info(client, timeout=1.0, poll_interval=0.01,
                      max_retries=3):
    """Read confocal hardware info from LAS X.

    Flushes HWInfo to None, fires GetConfocalHardwareInfo via UpdateAsync,
    then polls until data arrives. Retries up to *max_retries* times.
    """
    for attempt in range(1, max_retries + 1):
        try:
            try:
                client.PyApiGetConfocalHardwareInfo.Model.HWInfo = None
            except Exception:
                pass

            client.PyApiCommand.Model.Command = ""
            client.PyApiCommand.Model.Command = "GetConfocalHardwareInfo"
            client.PyApiCommand.UpdateAsync()

            deadline = time.perf_counter() + timeout
            while time.perf_counter() < deadline:
                raw = client.PyApiGetConfocalHardwareInfo.Model.HWInfo
                if raw is not None:
                    return json.loads(raw) if isinstance(raw, str) else raw
                time.sleep(poll_interval)

            log.warning("get_hardware_info: attempt %d/%d timed out",
                        attempt, max_retries)
        except Exception as e:
            log.error("get_hardware_info attempt %d/%d failed: %s",
                      attempt, max_retries, e)

    log.error("get_hardware_info: all %d attempts failed", max_retries)
    return None


def get_xy(client, timeout=1.0, poll_interval=0.1, max_retries=3):
    """Read current XY stage position.

    Flushes the model to NaN, fires GetXY via UpdateAsync, then polls
    until fresh (non-NaN) data arrives. Retries up to *max_retries* times.

    Returns:
        dict with x/y in meters and microns, or None on failure.
    """
    for attempt in range(1, max_retries + 1):
        try:
            client.PyApiGetXY.Model.XPosition = float('nan')
            client.PyApiGetXY.Model.YPosition = float('nan')

            client.PyApiCommand.Model.Command = ""
            client.PyApiCommand.Model.Command = "GetXY"
            client.PyApiCommand.UpdateAsync()

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

            log.warning("get_xy: attempt %d/%d timed out",
                        attempt, max_retries)
        except Exception as e:
            log.error("get_xy attempt %d/%d failed: %s",
                      attempt, max_retries, e)

    log.error("get_xy: all %d attempts failed", max_retries)
    return None


def get_jobs(client, timeout=1.0, poll_interval=0.01, max_retries=3):
    """List all available jobs and their selection status.

    Flushes Jobs to None, fires GetJobsInformation via UpdateAsync,
    then polls until data arrives. Retries up to *max_retries* times.
    """
    for attempt in range(1, max_retries + 1):
        try:
            try:
                client.PyApiGetJobsInformation.Model.Jobs = None
            except Exception:
                pass

            client.PyApiCommand.Model.Command = ""
            client.PyApiCommand.Model.Command = "GetJobsInformation"
            client.PyApiCommand.UpdateAsync()

            deadline = time.perf_counter() + timeout
            while time.perf_counter() < deadline:
                raw = client.PyApiGetJobsInformation.Model.Jobs
                if raw is not None:
                    return json.loads(raw) if isinstance(raw, str) else raw
                time.sleep(poll_interval)

            log.warning("get_jobs: attempt %d/%d timed out",
                        attempt, max_retries)
        except Exception as e:
            log.error("get_jobs attempt %d/%d failed: %s",
                      attempt, max_retries, e)

    log.error("get_jobs: all %d attempts failed", max_retries)
    return None


def get_job_by_name(client, job_name, **kwargs):
    """Return the metadata dict for a single job, or None if not found.

    Convenience wrapper around get_jobs(). All keyword arguments are
    forwarded to get_jobs().
    """
    jobs = get_jobs(client, **kwargs)
    if jobs:
        for j in jobs:
            if j.get("Name") == job_name:
                return j
    return None


def get_selected_job(client, **kwargs):
    """Return the metadata dict for the currently selected job, or None.

    Convenience wrapper around get_jobs(). All keyword arguments are
    forwarded to get_jobs().
    """
    jobs = get_jobs(client, **kwargs)
    if jobs:
        for j in jobs:
            if j.get("IsSelected"):
                return j
    return None


# =============================================================================
# LAS X application settings (from XML on disk)
# =============================================================================

_SETTINGS_PATH = os.path.join(
    os.getenv("APPDATA", ""),
    "Leica Microsystems", "LAS X",
    "MatrixScreener6", "User_0", "Settings",
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


def _xml_float(parent, tag, default=0.0):
    """Get float from child element text."""
    val = _xml_text(parent, tag)
    if val is None:
        return default
    try:
        return float(val)
    except ValueError:
        return default


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

    Parses the XML settings file that backs the Navigator Expert GUI
    (General Settings, Carrier Settings, Rare Event Settings, Advanced
    Settings tabs).

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
    stage_ov = root.find("SettingsStageOverview")
    general = root.find("SettingsGeneral")

    result = {}

    # ── General Settings ────────────────────────────────────────────
    if general is not None:
        result["general"] = {
            "delete_logs_older_than_days": _xml_int(general, "DeleteLogFilesOlderThanTheLastDays", 5),
            "enable_last_used_z": _xml_bool(general, "EnableLastUsedZPositionInMeter"),
            "last_used_z_m": _xml_float(general, "LastUsedZPositionInMeter"),
            "sync_focus_on_job_switch": _xml_bool(general, "EnableSynchronizeFocusDuringJobSwitchInDefinition"),
        }

    # ── Recent Files ────────────────────────────────────────────────
    recent = root.find("SettingsRecentFiles/Files")
    if recent is not None:
        result["recent_files"] = [
            el.text.strip() for el in recent.findall("string")
            if el.text and el.text.strip()
        ]

    # ── Standard Viewer ──────────────────────────────────────────────
    std_viewer = root.find("SettingsStandardViewer")
    if std_viewer is not None:
        result["standard_viewer"] = {
            "override_enabled": _xml_bool(std_viewer, "OverrideIsEnabled"),
            "swap_xy": _xml_bool(std_viewer, "SwapXY"),
            "invert_x": _xml_bool(std_viewer, "InvertX"),
            "invert_y": _xml_bool(std_viewer, "InvertY"),
        }

    # ── Carrier / Stage Overview ────────────────────────────────────
    if stage_ov is not None:
        result["carrier"] = {
            "show_in_gui": _xml_bool(stage_ov, "ShowInGUI"),
            "carrier_offset_x_um": _xml_float(stage_ov, "CarrierShiftX"),
            "carrier_offset_y_um": _xml_float(stage_ov, "CarrierShiftY"),
            "stage_offset_x_um": _xml_float(stage_ov, "StageOverViewOffSetX"),
            "stage_offset_y_um": _xml_float(stage_ov, "StageOverViewOffSetY"),
            "carrier_opacity": _xml_float(stage_ov, "CarrierOpacity"),
            "image_opacity": _xml_float(stage_ov, "ImageOpacity"),
            "overlap_x_pct": _xml_float(stage_ov, "OverlapX"),
            "overlap_y_pct": _xml_float(stage_ov, "OverlapY"),
            "scan_rotation_angle": _xml_float(stage_ov, "ScanRotationAngle"),
            "show_label": _xml_bool(stage_ov, "ShowLabel"),
        }

    # ── Data Export ─────────────────────────────────────────────────
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

        # ── Export Formats ──────────────────────────────────────────
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

        # ── CAM ─────────────────────────────────────────────────────
        cam = nav.find("SettingsCAM")
        if cam is not None:
            result["cam"] = {
                "enabled": _xml_bool(cam, "EnableCAM"),
                "client_name": _xml_text(cam, "ClientName"),
                "level2": _xml_bool(cam, "CanDoCamLevel2"),
            }

        # ── Stage Configuration ─────────────────────────────────────
        stage_cfg = nav.find("SettingsStageConfiguration")
        if stage_cfg is not None:
            result["stage_config"] = {
                "enabled": stage_cfg.get("IsEnabled", "false").lower() == "true",
                "invert_x": _xml_bool(stage_cfg, "InvertXMovement"),
                "invert_y": _xml_bool(stage_cfg, "InvertYMovement"),
                "flip_x": _xml_bool(stage_cfg, "FlipX"),
                "flip_y": _xml_bool(stage_cfg, "FlipY"),
                "swap_xy": _xml_bool(stage_cfg, "SwapXY"),
                "custom_tile_scan": _xml_bool(stage_cfg, "CustomTileScanSettings"),
            }

        # ── Rare Event Settings ─────────────────────────────────────
        rare = nav.find("SettingsRareEvent")
        if rare is not None:
            result["rare_event"] = {
                "invert_x": _xml_bool(rare, "RareEventInvertX"),
                "invert_y": _xml_bool(rare, "RareEventInvertY"),
                "swap_xy": _xml_bool(rare, "RareEventSwapXY"),
                "enable_dx_dy_offset": _xml_bool(rare, "EnableDxDyOffset"),
                "dx_offset": _xml_float(rare, "DxOffset"),
                "dy_offset": _xml_float(rare, "DyOffset"),
                "max_per_image": _xml_int(rare, "MaximalRareEventsPerImage"),
                "detection_limit_per_image": _xml_int(rare, "DetectionLimitPerImage"),
                "shuffle": _xml_bool(rare, "IsRareEventListRandomlyShuffled"),
                "enable_test_images": _xml_bool(rare, "EnableTestImage"),
                "enable_single_test_image": _xml_bool(rare, "EnableSingleTestImages"),
                "test_image_path": _xml_text(rare, "TestImagePath"),
                "enable_random_test_images": _xml_bool(rare, "EnableRandomTestImages"),
                "random_image_folder": _xml_text(rare, "TestRandomImageFolderPath"),
                "aivia_workflows_path": _xml_text(rare, "AiviaWorkflowsPath"),
            }

        # ── Image Export Orientation ────────────────────────────────
        img_exp = nav.find("SettingsExportedImage")
        if img_exp is not None:
            result["image_orientation"] = {
                "enable_transform": _xml_bool(img_exp, "EnableImageTransformation"),
                "transformation": _xml_text(img_exp, "ImageTransformation", "RIGHTTOP"),
            }

        # ── Skip Box ────────────────────────────────────────────────
        skip = nav.find("SettingsSkipBox")
        if skip is not None:
            result["skip_box"] = {
                "show_at_end_of_loop": _xml_bool(skip, "UseSkipBoxInTheEndOfLoopScan"),
                "auto_close": _xml_bool(skip, "EnableAutoCloseSkipBox"),
                "auto_close_ms": _xml_int(skip, "TimeUntilSkipboxWillAutoClosedInmilliseconds", 4000),
            }

        # ── Fast Scan ───────────────────────────────────────────────
        fast = nav.find("SettingsFastScan")
        if fast is not None:
            result["fast_scan"] = {
                "enabled": _xml_bool(fast, "EnableFastScanMode"),
            }

    return result

"""
Read functions.
===============
Read-only queries to LAS X: scan status, connection health, job settings,
hardware info, XY position, and job list.

These use the command dispatch pattern through PyApiCommand and poll for
data arrival. They do NOT modify microscope state.
"""

import json
import logging
import os
import time
import xml.etree.ElementTree as ET

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

def ping(client, timeout=5):
    """Lightweight connection check. Returns True if LAS X responds."""
    try:
        receipt = client.PyApiPing.UpdateAwaitReceipt(2)
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

def get_job_settings(client, job_name, timeout=10, poll_interval=0.1,
                     max_retries=3):
    """Read full job settings JSON from LAS X.

    Uses the dual-dispatch pattern: fires both the dedicated API object
    and the PyApiCommand channel, then polls Model.Settings until data
    arrives. Retries up to max_retries times on empty result.
    """
    # Early exit: if the requested job is already active and Settings
    # is populated, return it directly. Avoids the clear-then-poll cycle
    # which times out when LAS X doesn't re-send settings for the
    # already-active job.
    try:
        selected = get_selected_job(client)
        if selected and selected.get("Name") == job_name:
            raw = client.PyApiGetJobSettingsByName.Model.Settings
            if raw is not None:
                log.debug("get_job_settings: '%s' already active, returning "
                          "existing settings", job_name)
                return json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        pass  # Fall through to normal dispatch

    for attempt in range(max_retries):
        try:
            # Set job name on the data object model, then dispatch via command
            # channel. Receipt on data objects is unreliable (spec: "Calling
            # UpdateAwaitReceipt directly on the data object does NOT work").
            # We still call it to push the model update, but don't retry on
            # False — proceed to command dispatch regardless.
            client.PyApiGetJobSettingsByName.Model.JobName = job_name
            try:
                client.PyApiGetJobSettingsByName.UpdateAwaitReceipt(2)
            except Exception:
                pass  # Best-effort; command channel is the real transport

            # Clear cached settings before dispatch to prevent race condition
            client.PyApiGetJobSettingsByName.Model.Settings = None

            # Reset Command to "" first to force property-change event
            client.PyApiCommand.Model.Command = ""
            client.PyApiCommand.Model.Command = "GetJobSettingsByName"
            if not client.PyApiCommand.UpdateAwaitReceipt(2):
                log.warning("get_job_settings: command dispatch receipt failed "
                            "(attempt %d)", attempt + 1)
                continue

            t0 = time.perf_counter()
            while (time.perf_counter() - t0) < timeout:
                raw = client.PyApiGetJobSettingsByName.Model.Settings
                if raw is not None:
                    return json.loads(raw) if isinstance(raw, str) else raw
                time.sleep(poll_interval)

            # Timeout — check for API error
            if client.PyApiCommandEcho.Model.HasError:
                log.error("get_job_settings failed (attempt %d): %s",
                          attempt + 1, client.PyApiCommandEcho.Model.Error)
            else:
                log.warning("get_job_settings timeout (attempt %d) for '%s'",
                            attempt + 1, job_name)
        except Exception as e:
            log.error("get_job_settings failed (attempt %d): %s", attempt + 1, e)
            if attempt < max_retries - 1:
                time.sleep(poll_interval)
    return None


def get_hardware_info(client, timeout=10, poll_interval=0.1, max_retries=3):
    """Read confocal hardware info from LAS X.

    Uses command dispatch through PyApiCommand, then polls
    PyApiGetConfocalHardwareInfo.Model.HWInfo. Retries up to max_retries times.
    """
    for attempt in range(max_retries):
        try:
            # Clear cached HWInfo before dispatch to prevent race condition
            try:
                client.PyApiGetConfocalHardwareInfo.Model.HWInfo = None
            except Exception:
                pass

            client.PyApiCommand.Model.Command = ""
            client.PyApiCommand.Model.Command = "GetConfocalHardwareInfo"
            if not client.PyApiCommand.UpdateAwaitReceipt(2):
                log.warning("get_hardware_info: receipt failed (attempt %d)",
                            attempt + 1)
                continue

            t0 = time.perf_counter()
            while (time.perf_counter() - t0) < timeout:
                raw = client.PyApiGetConfocalHardwareInfo.Model.HWInfo
                if raw is not None:
                    return json.loads(raw) if isinstance(raw, str) else raw
                time.sleep(poll_interval)

            if client.PyApiCommandEcho.Model.HasError:
                log.error("get_hardware_info failed (attempt %d): %s",
                          attempt + 1, client.PyApiCommandEcho.Model.Error)
            else:
                log.warning("get_hardware_info timeout (attempt %d)",
                            attempt + 1)
        except Exception as e:
            log.error("get_hardware_info failed (attempt %d): %s", attempt + 1, e)
            if attempt < max_retries - 1:
                time.sleep(poll_interval)
    return None


def get_xy(client, timeout=10, poll_interval=0.1, max_retries=3):
    """Read current XY stage position.

    Uses command dispatch: fires "GetXY" via PyApiCommand, then reads
    the result from PyApiGetXY.Model.XPosition / YPosition.

    The returned values are in meters (LAS X internal unit).

    Note: On the first call after connect, the model properties may
    still be at their default (0.0) because the receipt confirms
    command acceptance, not data delivery. We wait briefly and re-read
    if the first result looks stale.

    Returns:
        dict with x/y in meters and microns, or None on failure.
    """
    for attempt in range(max_retries):
        try:
            # Command dispatch — same pattern as get_jobs, get_hardware_info
            client.PyApiCommand.Model.Command = ""
            client.PyApiCommand.Model.Command = "GetXY"
            if not client.PyApiCommand.UpdateAwaitReceipt(2):
                log.warning("get_xy: receipt failed (attempt %d)",
                            attempt + 1)
                if attempt < max_retries - 1:
                    time.sleep(poll_interval)
                continue

            # Check for errors
            if client.PyApiCommandEcho.Model.HasError:
                err = client.PyApiCommandEcho.Model.Error
                log.error("get_xy failed (attempt %d): %s", attempt + 1, err)
                if attempt < max_retries - 1:
                    time.sleep(poll_interval)
                continue

            # Brief wait for data propagation — receipt confirms command
            # acceptance, not data delivery. Without this, first call
            # after connect returns stale (0, 0).
            time.sleep(0.05)

            x = client.PyApiGetXY.Model.XPosition
            y = client.PyApiGetXY.Model.YPosition

            # Stale-data guard: if both are exactly 0.0 on first attempt,
            # retry after a longer wait — real stage is rarely at (0, 0).
            if attempt == 0 and x == 0.0 and y == 0.0:
                log.info("get_xy: got (0, 0), may be stale — retrying")
                time.sleep(0.2)
                # Re-fire command
                client.PyApiCommand.Model.Command = ""
                client.PyApiCommand.Model.Command = "GetXY"
                client.PyApiCommand.UpdateAwaitReceipt(2)
                time.sleep(0.05)
                x = client.PyApiGetXY.Model.XPosition
                y = client.PyApiGetXY.Model.YPosition

            return {
                "x": x,
                "y": y,
                "x_um": x * 1e6,
                "y_um": y * 1e6,
            }
        except Exception as e:
            log.error("get_xy failed (attempt %d): %s", attempt + 1, e)
            if attempt < max_retries - 1:
                time.sleep(poll_interval)
    return None


def get_jobs(client, timeout=10, poll_interval=0.1, max_retries=3):
    """List all available jobs and their selection status.

    Uses command dispatch through PyApiCommand, then polls
    PyApiGetJobsInformation.Model.Jobs. Retries up to 3 times.
    """
    for attempt in range(max_retries):
        try:
            # Clear cached jobs before dispatch to prevent race condition
            try:
                client.PyApiGetJobsInformation.Model.Jobs = None
            except Exception:
                pass

            client.PyApiCommand.Model.Command = ""
            client.PyApiCommand.Model.Command = "GetJobsInformation"
            if not client.PyApiCommand.UpdateAwaitReceipt(2):
                log.warning("get_jobs: receipt failed (attempt %d)",
                            attempt + 1)
                continue

            t0 = time.perf_counter()
            while (time.perf_counter() - t0) < timeout:
                raw = client.PyApiGetJobsInformation.Model.Jobs
                if raw is not None:
                    return json.loads(raw) if isinstance(raw, str) else raw
                time.sleep(poll_interval)

            if client.PyApiCommandEcho.Model.HasError:
                log.error("get_jobs failed (attempt %d): %s",
                          attempt + 1, client.PyApiCommandEcho.Model.Error)
            else:
                log.warning("get_jobs timeout (attempt %d)", attempt + 1)
        except Exception as e:
            log.error("get_jobs failed (attempt %d): %s", attempt + 1, e)
            if attempt < max_retries - 1:
                time.sleep(poll_interval)
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

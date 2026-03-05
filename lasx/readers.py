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
import time

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

def get_job_settings(client, job_name, timeout=15, poll_interval=0.05,
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


def get_hardware_info(client, timeout=15, poll_interval=0.05, max_retries=3):
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


def get_xy(client, timeout=15, poll_interval=0.05, max_retries=3):
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


def get_jobs(client, timeout=15, poll_interval=0.05, max_retries=3):
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

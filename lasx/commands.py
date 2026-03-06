"""
Command wrappers.
=================
Public ``set_*``, ``move_*``, ``acquire``, and ``select_job`` functions.
Each wrapper follows a three-phase pattern:

    **Phase A** — Pre-checks: input validation, limit checks, enum
        resolution, early-exit optimizations. Stays in the wrapper.
    **Phase B** — Backbone: calls ``confirm_and_fire`` with the command's
        profile. Replaces all bespoke dispatch code.
    **Phase C** — Post-processing: attach extra data to the result dict
        (e.g. ``move_xy`` attaches position readback).

Every command unpacks its profile and binds ``client`` via lambda.
The binding pattern is identical across all commands — no exceptions::

    pre_check_fn  = lambda: profile.pre_check_fn(client)
    error_check_fn = lambda: profile.error_check_fn(client)
    confirm_fn    = lambda: profile.confirm_fn(client, ...)

Import restrictions: only ``core``, ``profiles``, ``errors``, ``limits``,
``readers``, ``confirm``, ``checks``, and ``util``. The ``checks`` import
is used in ``_dispatch`` for the ``pre_check_timeout`` override.
"""

import logging
import time
from functools import partial

from .checks import check_idle
from .core import confirm_and_fire
from .profiles import (
    ZOOM, SCAN_SPEED, SCAN_RESONANT, SCAN_MODE, SEQUENTIAL_MODE,
    SCAN_FIELD_ROTATION, IMAGE_FORMAT, OBJECTIVE,
    Z_STACK_DEFINITION, Z_STACK_STEP_SIZE, Z_STACK_SIZE,
    FRAME_ACCUMULATION, FRAME_AVERAGE, LINE_ACCUMULATION, LINE_AVERAGE,
    PINHOLE_AIRY, DETECTOR_GAIN,
    LASER_INTENSITY, LASER_SHUTTER,
    FILTER_WHEEL_SLOT, FILTER_WHEEL_SPECTRUM,
    MOVE_XY, MOVE_Z, ACQUIRE, SELECT_JOB,
)
from .confirm import (
    _confirm_zoom, _confirm_scan_speed, _confirm_scan_resonant,
    _confirm_scan_mode, _confirm_sequential_mode,
    _confirm_scan_field_rotation, _confirm_image_format,
    confirm_objective, _confirm_z_stack_definition,
    _confirm_z_stack_step_size, _confirm_z_stack_size,
    _confirm_frame_accumulation, _confirm_frame_average,
    _confirm_line_accumulation, _confirm_line_average,
    _confirm_pinhole_airy, _confirm_detector_gain,
    _confirm_laser_intensity, _confirm_laser_shutter,
    _confirm_filter_wheel_slot, _confirm_filter_wheel_spectrum,
    confirm_move_xy, confirm_move_z,
    confirm_acquire, confirm_select_job,
)
from .limits import _check_xy_limits, _check_z_limits
from . import readers as _readers
from .util import _hw_get, parse_format, _make_timing

log = logging.getLogger(__name__)


# =============================================================================
# Internal helper — uniform backbone call
# =============================================================================

def _dispatch(client, api_obj, description, profile, *,
              setup_fn, confirm_fn=None,
              max_retries=None, retry_backoff=None, retry_escalate=None,
              max_confirm_attempts=None, pre_check_timeout=None):
    """Call confirm_and_fire with a profile's settings.

    This is the single internal helper that all command wrappers call.
    It binds ``client`` into each profile callable via lambda, producing
    the zero-arg callables that the backbone expects. The binding
    pattern is identical for every command.

    Args:
        client: LAS X API client.
        api_obj: Resolved API object.
        description: Human-readable label for logging.
        profile: CommandProfile instance with all settings.
        setup_fn: Callable(model) that writes parameters to api_obj.Model.
        confirm_fn: Override for the profile's confirm_fn. Use when
            the confirm callable needs command-specific parameters
            (e.g. target value, tolerance) that are not in the profile.
            When None, uses profile.confirm_fn (which may also be None,
            meaning no confirmation).
        max_retries: Override for the profile's max_retries. None uses
            the profile default.
        retry_backoff: Override for the profile's retry_backoff. None
            uses the profile default.
        retry_escalate: Override for the profile's retry_escalate. None
            uses the profile default.
        max_confirm_attempts: Override for the profile's max_confirm_attempts.
            None uses the profile default.
        pre_check_timeout: Override idle-wait timeout (seconds). None
            uses the profile's pre_check_fn as-is. When provided,
            replaces the profile's pre_check_fn with a fresh
            ``check_idle`` using this timeout.

    Returns:
        Result dict from confirm_and_fire.
    """
    # Resolve confirm_fn: explicit override > profile default > None
    effective_confirm = confirm_fn if confirm_fn is not None else profile.confirm_fn

    # Resolve pre_check_fn: timeout override > profile default > None
    if pre_check_timeout is not None and profile.pre_check_fn is not None:
        heartbeat = getattr(profile.pre_check_fn, 'keywords', {}).get('heartbeat', 30.0)
        pre_check_fn = lambda: check_idle(client, timeout=pre_check_timeout, heartbeat=heartbeat)
    elif profile.pre_check_fn is not None:
        pre_check_fn = lambda: profile.pre_check_fn(client)
    else:
        pre_check_fn = None

    return confirm_and_fire(
        client, api_obj, description,
        setup_fn=setup_fn,
        pre_check_fn=pre_check_fn,
        error_check_fn=lambda: profile.error_check_fn(client),
        confirm_fn=(lambda: effective_confirm(client))
                    if effective_confirm else None,
        correct_fn=(lambda: profile.correct_fn(client))
                    if profile.correct_fn else None,
        max_retries=max_retries if max_retries is not None else profile.max_retries,
        max_confirm_attempts=max_confirm_attempts if max_confirm_attempts is not None else profile.max_confirm_attempts,
        retry_backoff=retry_backoff if retry_backoff is not None else profile.retry_backoff,
        retry_escalate=retry_escalate if retry_escalate is not None else profile.retry_escalate,
    )


# =============================================================================
# Set functions — Job-level
# =============================================================================

def set_zoom(client, job_name, value, *,
             max_retries=None, pre_check_timeout=None, tolerance=0.1):
    """Set zoom level for the specified job.

    Args:
        client: LAS X API client.
        job_name: Target job name.
        value: Desired zoom level.
        max_retries: Transient error retry ceiling.
        pre_check_timeout: Idle-wait timeout (seconds). None = profile default.
        tolerance: Readback confirmation tolerance.
    """
    api_obj = client.PyApiSetZoomByJobName

    def setup(m):
        m.JobName = job_name
        m.ZoomValue = value

    return _dispatch(
        client, api_obj, f"Zoom -> {value}", ZOOM,
        setup_fn=setup,
        confirm_fn=partial(_confirm_zoom, job_name=job_name, target=value,
                           tolerance=tolerance),
        max_retries=max_retries, pre_check_timeout=pre_check_timeout,
    )


def set_scan_speed(client, job_name, value, *,
                   max_retries=None, pre_check_timeout=None):
    """Set scan speed for the specified job."""
    api_obj = client.PyApiSetScanSpeedByJobName

    def setup(m):
        m.JobName = job_name
        m.ScanSpeed = value

    return _dispatch(
        client, api_obj, f"ScanSpeed -> {value}", SCAN_SPEED,
        setup_fn=setup,
        confirm_fn=partial(_confirm_scan_speed, job_name=job_name,
                           target=value),
        max_retries=max_retries, pre_check_timeout=pre_check_timeout,
    )


def set_scan_resonant(client, job_name, enable, *,
                      max_retries=None, pre_check_timeout=None):
    """Enable or disable resonant scanning for the specified job."""
    api_obj = client.PyApiSetScannerToResonantByJobName

    def setup(m):
        m.JobName = job_name
        m.EnableResonant = enable

    return _dispatch(
        client, api_obj, f"Resonant -> {enable}", SCAN_RESONANT,
        setup_fn=setup,
        confirm_fn=partial(_confirm_scan_resonant, job_name=job_name,
                           target=enable),
        max_retries=max_retries, pre_check_timeout=pre_check_timeout,
    )


def set_scan_mode(client, job_name, mode, *,
                  max_retries=None, pre_check_timeout=None):
    """Set scan mode (e.g. 'xyz', 'xyzt') for the specified job."""
    api_obj = client.PyApiSetScanModeByJobName

    def setup(m):
        m.JobName = job_name
        m.ScanModeValue = mode

    return _dispatch(
        client, api_obj, f"ScanMode -> {mode}", SCAN_MODE,
        setup_fn=setup,
        confirm_fn=partial(_confirm_scan_mode, job_name=job_name,
                           target=mode),
        max_retries=max_retries, pre_check_timeout=pre_check_timeout,
    )


def set_sequential_mode(client, job_name, mode, *,
                        max_retries=None, pre_check_timeout=None):
    """Set sequential mode ('Line', 'Frame', or 'Stack') for the specified job."""
    # Phase A: input validation and enum resolution
    if not isinstance(mode, str) or not mode.strip():
        return {
            "success": False, "confirmed": None,
            "message": f"SequentialMode -> {repr(mode)} | Invalid: mode must be a "
                       f"non-empty string. Valid: ['Line', 'Frame', 'Stack']",
            "timing": _make_timing(total_s=0.0, attempts=0),
            "logs": [],
        }

    _enum_map = {"Line": "eSequentialLine", "Frame": "eSequentialFrame",
                 "Stack": "eSequentialStack"}
    enum_val = _enum_map.get(mode)
    if enum_val is None:
        return {
            "success": False, "confirmed": None,
            "message": f"Could not map {repr(mode)} to SequentialMode enum. "
                       f"Valid: {list(_enum_map.keys())}",
            "timing": _make_timing(total_s=0.0, attempts=0),
            "logs": [],
        }

    api_obj = client.PyApiSetSequentialModeByJobName

    def setup(m):
        m.JobName = job_name
        try:
            current = m.SequentialMode
            m.SequentialMode = getattr(type(current), enum_val, enum_val)
        except (AttributeError, TypeError):
            m.SequentialMode = enum_val

    return _dispatch(
        client, api_obj, f"SequentialMode -> {mode}", SEQUENTIAL_MODE,
        setup_fn=setup,
        confirm_fn=partial(_confirm_sequential_mode, job_name=job_name,
                           target=mode),
        max_retries=max_retries, pre_check_timeout=pre_check_timeout,
    )


def set_scan_field_rotation(client, job_name, angle, *,
                            max_retries=None, pre_check_timeout=None,
                            tolerance=0.5):
    """Set scan field rotation angle (degrees) for the specified job."""
    api_obj = client.PyApiSetScanFieldRotationByJobName

    def setup(m):
        m.JobName = job_name
        m.Rotation = angle

    return _dispatch(
        client, api_obj, f"Rotation -> {angle}", SCAN_FIELD_ROTATION,
        setup_fn=setup,
        confirm_fn=partial(_confirm_scan_field_rotation, job_name=job_name,
                           target=angle, tolerance=tolerance),
        max_retries=max_retries, pre_check_timeout=pre_check_timeout,
    )


def set_image_format(client, job_name, format_str, *,
                     max_retries=None, pre_check_timeout=None):
    """Set image dimensions for the specified job.

    Args:
        format_str: Either a string like '512 x 512' or a tuple (w, h).
    """
    if isinstance(format_str, tuple):
        w, h = format_str
    else:
        w, h = parse_format(format_str)

    api_obj = client.PyApiSetImageSizeByJobName

    def setup(m):
        m.JobName = job_name
        m.ImageWidth = w
        m.ImageHeight = h
        m.IsAutoFocusDefinition = False

    return _dispatch(
        client, api_obj, f"Format -> {w} x {h}", IMAGE_FORMAT,
        setup_fn=setup,
        confirm_fn=partial(_confirm_image_format, job_name=job_name,
                           w=w, h=h),
        max_retries=max_retries, pre_check_timeout=pre_check_timeout,
    )


def set_objective(client, job_name, hw_info, name=None, magnification=None, *,
                  max_retries=None, pre_check_timeout=None):
    """Set objective by name or magnification.

    Looks up the objective in hw_info to find the correct slot index,
    then fires the command. Exactly one of name or magnification must
    be provided.
    """
    # Phase A: resolve objective from hardware info
    objectives = _hw_get(
        _hw_get(hw_info, "Microscope", {}), "objectives", [])

    slot = None
    target_name = None

    if name is not None:
        for obj in objectives:
            obj_name = _hw_get(obj, "name", "").strip()
            if obj_name == name.strip():
                slot = _hw_get(obj, "slotIndex")
                target_name = obj_name
                break
    elif magnification is not None:
        for obj in objectives:
            if _hw_get(obj, "magnification") == magnification:
                slot = _hw_get(obj, "slotIndex")
                target_name = _hw_get(obj, "name", "").strip()
                break

    if slot is None:
        return {
            "success": False, "confirmed": None,
            "message": f"Could not find objective: name={name}, mag={magnification}. "
                       f"Available: {[_hw_get(o, 'name', '').strip() for o in objectives]}",
            "timing": _make_timing(total_s=0.0, attempts=0),
            "logs": [],
        }

    api_obj = client.PyApiSetObjectiveSlotByJobName

    def setup(m):
        m.JobName = job_name
        m.ObjectiveSlotIndex = slot

    return _dispatch(
        client, api_obj, f"Objective -> {target_name} (slot {slot})", OBJECTIVE,
        setup_fn=setup,
        confirm_fn=partial(confirm_objective, job_name=job_name,
                           target_name=target_name),
        max_retries=max_retries, pre_check_timeout=pre_check_timeout,
    )


# =============================================================================
# Set functions — Z-Stack
# =============================================================================

def set_z_stack_definition(client, job_name, begin_um=None, end_um=None,
                           old_begin_um=None, old_end_um=None, *,
                           max_retries=None, pre_check_timeout=None,
                           tolerance=1.0):
    """Set z-stack begin/end positions (micrometers).

    Note: confirm_fn is provided but LAS X may recalculate z-stack
    geometry (size, end) after setting begin/end. Confirmation may
    report unconfirmed even though the command was accepted.
    """
    # Determine set flags: 0=reset, 1=set, 2=ignore
    if begin_um is not None:
        set_begin = 1
    elif old_begin_um is not None:
        set_begin = 0
    else:
        set_begin = 2

    if end_um is not None:
        set_end = 1
    elif old_end_um is not None:
        set_end = 0
    else:
        set_end = 2

    def setup(m):
        m.JobName = job_name
        m.SetBegin = set_begin
        # Explicit None check: begin_um=0.0 is a valid z-position.
        # Using (begin_um or 0) would treat 0.0 as falsy.
        m.BeginValue = (begin_um if begin_um is not None else 0) * 1e-6
        m.SetEnd = set_end
        m.EndValue = (end_um if end_um is not None else 0) * 1e-6

    api_obj = client.PyApiSetZStackDefinitionByJobName

    return _dispatch(
        client, api_obj,
        f"Z-stack def: begin={begin_um}, end={end_um}",
        Z_STACK_DEFINITION,
        setup_fn=setup,
        confirm_fn=partial(_confirm_z_stack_definition, job_name=job_name,
                           begin_um=begin_um, end_um=end_um,
                           tolerance=tolerance),
        max_retries=max_retries, pre_check_timeout=pre_check_timeout,
    )


def set_z_stack_step_size(client, job_name, step_size_um, *,
                          max_retries=None, pre_check_timeout=None,
                          tolerance=0.5):
    """Set z-stack step size (micrometers)."""
    api_obj = client.PyApiCommandSetZStackStepSizeByJobName

    def setup(m):
        m.JobName = job_name
        m.StackStepSize = step_size_um * 1e-6

    return _dispatch(
        client, api_obj, f"Z-stack step -> {step_size_um} um",
        Z_STACK_STEP_SIZE,
        setup_fn=setup,
        confirm_fn=partial(_confirm_z_stack_step_size, job_name=job_name,
                           target_um=step_size_um, tolerance=tolerance),
        max_retries=max_retries, pre_check_timeout=pre_check_timeout,
    )


def set_z_stack_size(client, job_name, size_um, *,
                     max_retries=None, pre_check_timeout=None,
                     tolerance=1.5):
    """Set z-stack total size (micrometers).

    Note: LAS X may recalculate z-stack geometry when size is changed.
    Confirmation may report unconfirmed if "System Optimized" is active.
    """
    api_obj = client.PyApiSetZStackSizeByJobName

    def setup(m):
        m.JobName = job_name
        m.StackSize = size_um * 1e-6

    return _dispatch(
        client, api_obj, f"Z-stack size -> {size_um} um", Z_STACK_SIZE,
        setup_fn=setup,
        confirm_fn=partial(_confirm_z_stack_size, job_name=job_name,
                           target_um=size_um, tolerance=tolerance),
        max_retries=max_retries, pre_check_timeout=pre_check_timeout,
    )


# =============================================================================
# Set functions — Per-setting
# =============================================================================

def set_frame_accumulation(client, job_name, setting_index, value, *,
                           max_retries=None, pre_check_timeout=None):
    """Set frame accumulation count for a specific setting index."""
    api_obj = client.PyApiSetFrameAccumulationByJobName

    def setup(m):
        m.JobName = job_name
        m.SettingIndex = setting_index
        m.FrameAccumulation = value

    return _dispatch(
        client, api_obj,
        f"Setting[{setting_index}].FrameAccumulation -> {value}",
        FRAME_ACCUMULATION,
        setup_fn=setup,
        confirm_fn=partial(_confirm_frame_accumulation, job_name=job_name,
                           si=setting_index, target=value),
        max_retries=max_retries, pre_check_timeout=pre_check_timeout,
    )


def set_frame_average(client, job_name, setting_index, value, *,
                      max_retries=None, pre_check_timeout=None):
    """Set frame average count for a specific setting index."""
    api_obj = client.PyApiSetFrameAverageByJobName

    def setup(m):
        m.JobName = job_name
        m.SettingIndex = setting_index
        m.FrameAverage = value

    return _dispatch(
        client, api_obj,
        f"Setting[{setting_index}].FrameAverage -> {value}",
        FRAME_AVERAGE,
        setup_fn=setup,
        confirm_fn=partial(_confirm_frame_average, job_name=job_name,
                           si=setting_index, target=value),
        max_retries=max_retries, pre_check_timeout=pre_check_timeout,
    )


def set_line_accumulation(client, job_name, setting_index, value, *,
                          max_retries=None, pre_check_timeout=None):
    """Set line accumulation count for a specific setting index."""
    api_obj = client.PyApiSetLineAccumulationByJobName

    def setup(m):
        m.JobName = job_name
        m.SettingIndex = setting_index
        m.LineAccumulation = value

    return _dispatch(
        client, api_obj,
        f"Setting[{setting_index}].LineAccumulation -> {value}",
        LINE_ACCUMULATION,
        setup_fn=setup,
        confirm_fn=partial(_confirm_line_accumulation, job_name=job_name,
                           si=setting_index, target=value),
        max_retries=max_retries, pre_check_timeout=pre_check_timeout,
    )


def set_line_average(client, job_name, setting_index, value, *,
                     max_retries=None, pre_check_timeout=None):
    """Set line average count for a specific setting index."""
    api_obj = client.PyApiSetLineAverageByJobName

    def setup(m):
        m.JobName = job_name
        m.SettingIndex = setting_index
        m.LineAverage = value

    return _dispatch(
        client, api_obj,
        f"Setting[{setting_index}].LineAverage -> {value}",
        LINE_AVERAGE,
        setup_fn=setup,
        confirm_fn=partial(_confirm_line_average, job_name=job_name,
                           si=setting_index, target=value),
        max_retries=max_retries, pre_check_timeout=pre_check_timeout,
    )


def set_pinhole_airy(client, job_name, setting_index, value, *,
                     max_retries=None, pre_check_timeout=None,
                     tolerance=0.05):
    """Set pinhole size in Airy units for a specific setting index."""
    api_obj = client.PyApiSetPinholeAUByJobName

    def setup(m):
        m.JobName = job_name
        m.SettingIndex = setting_index
        m.PinholeAiry = value

    return _dispatch(
        client, api_obj,
        f"Setting[{setting_index}].PinholeAiry -> {value}",
        PINHOLE_AIRY,
        setup_fn=setup,
        confirm_fn=partial(_confirm_pinhole_airy, job_name=job_name,
                           si=setting_index, target=value,
                           tolerance=tolerance),
        max_retries=max_retries, pre_check_timeout=pre_check_timeout,
    )


# =============================================================================
# Set functions — Detector
# =============================================================================

def set_detector_gain(client, job_name, setting_index, beam_route, value, *,
                      max_retries=None, pre_check_timeout=None,
                      tolerance=1.0):
    """Set detector gain for a specific detector identified by beam route."""
    api_obj = client.PyApiSetDetectorGainByJobName

    def setup(m):
        m.JobName = job_name
        m.SettingIndex = setting_index
        m.BeamRoute = beam_route
        m.GainValue = value

    return _dispatch(
        client, api_obj,
        f"Setting[{setting_index}].Detector[{beam_route}].Gain -> {value}",
        DETECTOR_GAIN,
        setup_fn=setup,
        confirm_fn=partial(_confirm_detector_gain, job_name=job_name,
                           si=setting_index, beam_route=beam_route,
                           target=value, tolerance=tolerance),
        max_retries=max_retries, pre_check_timeout=pre_check_timeout,
    )


# =============================================================================
# Set functions — Laser
# =============================================================================

def set_laser_intensity(client, job_name, setting_index, beam_route,
                        line_index, value, *,
                        max_retries=None, pre_check_timeout=None,
                        tolerance=0.005):
    """Set laser intensity (0.0-1.0) for a specific laser line."""
    api_obj = client.PyApiSetLaserIntensityByJobName

    def setup(m):
        m.JobName = job_name
        m.SettingIndex = setting_index
        m.BeamRoute = beam_route
        m.LaserLineIndex = line_index
        m.IntensityValue = value
        m.IsRoiBackground = False

    return _dispatch(
        client, api_obj,
        f"Setting[{setting_index}].Laser[{beam_route}][{line_index}] -> {value}",
        LASER_INTENSITY,
        setup_fn=setup,
        confirm_fn=partial(_confirm_laser_intensity, job_name=job_name,
                           si=setting_index, beam_route=beam_route,
                           line_index=line_index, target=value,
                           tolerance=tolerance),
        max_retries=max_retries, pre_check_timeout=pre_check_timeout,
    )


def set_laser_shutter(client, job_name, setting_index, beam_route, activate,
                      *, max_retries=None, pre_check_timeout=None):
    """Open or close laser shutter for a specific beam route."""
    api_obj = client.PyApiSetLaserShutterByJobName

    def setup(m):
        m.JobName = job_name
        m.SettingIndex = setting_index
        m.BeamRoute = beam_route
        m.Activate = activate

    label = "Open" if activate else "Closed"
    return _dispatch(
        client, api_obj,
        f"Setting[{setting_index}].Shutter[{beam_route}] -> {label}",
        LASER_SHUTTER,
        setup_fn=setup,
        confirm_fn=partial(_confirm_laser_shutter, job_name=job_name,
                           si=setting_index, beam_route=beam_route,
                           target=activate),
        max_retries=max_retries, pre_check_timeout=pre_check_timeout,
    )


# =============================================================================
# Set functions — Filter Wheel
# =============================================================================

def set_filter_wheel_slot(client, job_name, setting_index, beam_route,
                          filter_wheel_type, slot_index, *,
                          max_retries=None, pre_check_timeout=None):
    """Set filter wheel to a specific slot."""
    api_obj = client.PyApiSetFilterWheelSlotByJobName

    def setup(m):
        m.JobName = job_name
        m.SettingIndex = setting_index
        m.BeamRoute = beam_route
        # Cast int to .NET enum type
        try:
            fw_type = type(m.FilterWheelType)(filter_wheel_type)
        except Exception:
            fw_type = filter_wheel_type
        m.FilterWheelType = fw_type
        m.SlotIndex = slot_index

    return _dispatch(
        client, api_obj,
        f"FilterWheel[{beam_route}] slot -> {slot_index}",
        FILTER_WHEEL_SLOT,
        setup_fn=setup,
        confirm_fn=partial(_confirm_filter_wheel_slot, job_name=job_name,
                           si=setting_index, beam_route=beam_route,
                           fw_type=filter_wheel_type, target=slot_index),
        max_retries=max_retries, pre_check_timeout=pre_check_timeout,
    )


def set_filter_wheel_spectrum(client, job_name, setting_index, beam_route,
                              filter_wheel_type, position, *,
                              max_retries=None, pre_check_timeout=None,
                              tolerance=1):
    """Set filter wheel spectrum position (nm)."""
    api_obj = client.PyApiSetFilterWheelSpectrumPositionByJobName

    def setup(m):
        m.JobName = job_name
        m.SettingIndex = setting_index
        m.BeamRoute = beam_route
        # Cast int to .NET enum type
        try:
            fw_type = type(m.FilterWheelType)(filter_wheel_type)
        except Exception:
            fw_type = filter_wheel_type
        m.FilterWheelType = fw_type
        m.FilterSpectrumPosition = position

    return _dispatch(
        client, api_obj,
        f"FilterWheel[{beam_route}] spectrum -> {position}",
        FILTER_WHEEL_SPECTRUM,
        setup_fn=setup,
        confirm_fn=partial(_confirm_filter_wheel_spectrum,
                           job_name=job_name, si=setting_index,
                           beam_route=beam_route, fw_type=filter_wheel_type,
                           target=position, tolerance=tolerance),
        max_retries=max_retries, pre_check_timeout=pre_check_timeout,
    )


# =============================================================================
# Stage movement
# =============================================================================

def move_xy(client, x, y, unit="um", *,
            max_retries=None, pre_check_timeout=None,
            tolerance=20.0):
    """Move XY stage to absolute position.

    Args:
        client: LAS X API client.
        x, y: Target coordinates in the specified unit.
        unit: 'um' (micrometers), 'mm' (millimeters), or 'm' (meters).
        tolerance: Position confirmation tolerance in micrometers.

    Returns:
        Result dict with 'position' key containing final XY readback.
    """
    # Phase A: convert to um for limit check
    try:
        if unit == "mm":
            x_um, y_um = x * 1000, y * 1000
        elif unit == "m":
            x_um, y_um = x * 1e6, y * 1e6
        else:
            x_um, y_um = x, y
        _check_xy_limits(x_um, y_um)
    except RuntimeError as e:
        return {"success": False, "confirmed": None, "message": str(e),
                "position": None,
                "timing": _make_timing(total_s=0.0, attempts=0),
                "logs": []}

    api_obj = client.PyApiMoveHardwareXY

    # Resolve .NET enums with integer fallback
    UNIT_ENUM_MAP = {"um": "eMicrons", "mm": "eMillimeter", "m": "eMeter"}
    UNIT_INT_MAP = {"um": 4, "mm": 3, "m": 1}
    try:
        unit_val = getattr(type(api_obj.Model.Units), UNIT_ENUM_MAP[unit])
    except Exception:
        unit_val = UNIT_INT_MAP[unit]
        log.warning("Units enum resolution failed, using int fallback: %d",
                    unit_val)

    try:
        mode_val = type(api_obj.Model.MoveXyMode).eMoveXY
    except Exception:
        mode_val = 2  # eMoveXY=2 (NOT 0 which is eDontMove!)
        log.warning("MoveXyMode enum resolution failed, using int fallback: "
                    "%d", mode_val)

    def setup(m):
        m.RelativePosition = False
        m.XPosition = x
        m.YPosition = y
        m.MoveXyMode = mode_val
        m.Units = unit_val

    # Phase B: backbone
    r = _dispatch(
        client, api_obj, f"MoveXY -> ({x}, {y}) {unit}", MOVE_XY,
        setup_fn=setup,
        confirm_fn=partial(confirm_move_xy, target_x_um=x_um,
                           target_y_um=y_um, tolerance=tolerance),
        max_retries=max_retries, pre_check_timeout=pre_check_timeout,
    )

    # Phase C: attach position readback
    pos = _readers.get_xy(client)
    r["position"] = pos if pos else {"x": x_um * 1e-6, "y": y_um * 1e-6,
                                      "x_um": x_um, "y_um": y_um}
    return r


def move_z(client, job_name, z, unit="um", z_mode="galvo", *,
           max_retries=None, pre_check_timeout=None,
           tolerance=1.0):
    """Move Z drive to an absolute position (galvo or zwide).

    Args:
        client: LAS X API client.
        job_name: Target job.
        z: Target position (can be negative).
        unit: 'um', 'mm', or 'm'.
        z_mode: Drive type — 'galvo' or 'zwide'.
        tolerance: Position confirmation tolerance in micrometers.
    """
    ZMODE_MAP = {"galvo": "eUseGalvo", "zwide": "eUseZWide"}
    UNIT_MAP = {"um": "eMicrons", "mm": "eMillimeter", "m": "eMeter"}
    UNIT_INT_MAP = {"um": 4, "mm": 3, "m": 1}

    z_member = ZMODE_MAP.get(z_mode)
    if z_member is None:
        return {"success": False, "confirmed": None,
                "message": f"Unknown z_mode '{z_mode}'. "
                           f"Use: {list(ZMODE_MAP.keys())}",
                "timing": _make_timing(total_s=0.0, attempts=0),
                "logs": []}

    # Convert to um for limit check and confirmation
    if unit == "mm":
        z_um = z * 1000
    elif unit == "m":
        z_um = z * 1e6
    else:
        z_um = z

    # Limit check
    try:
        _check_z_limits(z_um, z_mode)
    except (RuntimeError, ValueError) as e:
        return {"success": False, "confirmed": None, "message": str(e),
                "timing": _make_timing(total_s=0.0, attempts=0),
                "logs": []}

    # Resolve .NET enums from the live model
    api_obj = client.PyApiMoveZByJobName
    try:
        z_use_val = getattr(type(api_obj.Model.ZUseMode), z_member)
    except Exception:
        z_use_val = z_member
        log.warning("ZUseMode enum resolution failed for '%s'", z_member)

    try:
        unit_val = getattr(type(api_obj.Model.Units), UNIT_MAP[unit])
    except Exception:
        unit_val = UNIT_INT_MAP[unit]
        log.warning("Units enum resolution failed, using int fallback: %d",
                    unit_val)

    def setup(m):
        m.JobName = job_name
        m.RelativePosition = False
        m.ZPosition = z
        m.ZUseMode = z_use_val
        m.Units = unit_val

    return _dispatch(
        client, api_obj, f"Z -> {z} {unit} ({z_mode})", MOVE_Z,
        setup_fn=setup,
        confirm_fn=partial(confirm_move_z, job_name=job_name,
                           z_mode=z_mode, target_um=z_um,
                           tolerance=tolerance),
        max_retries=max_retries, pre_check_timeout=pre_check_timeout,
    )


# =============================================================================
# Acquisition
# =============================================================================

def acquire(client, job_name, poll_interval=0.1, poll_timeout=None,
            heartbeat_interval=30.0, settle_time=0.5, start_timeout=15.0,
            pre_check_timeout=None):
    """Trigger acquisition and block until scan completes.

    Routes through the backbone for consistent idle-wait, retry, and
    timing instrumentation. The completion logic (settle_time,
    saw_scanning, start_timeout) lives in ``confirm_acquire``.

    Args:
        client: LAS X API client.
        job_name: Job to acquire.
        poll_interval: Seconds between scan status polls during completion.
        poll_timeout: Hard ceiling for scan completion (seconds). None
            for no timeout (wait indefinitely).
        heartbeat_interval: Log interval during long scans (seconds).
        settle_time: Minimum seconds after fire before accepting idle
            as completion.
        start_timeout: Seconds to wait for scan to start before logging
            a warning.

    Returns:
        Result dict with timing in timing['total_s'].
    """
    api_obj = client.PyApiAcquireJob

    def setup(m):
        m.JobName = job_name

    return _dispatch(
        client, api_obj, f"Acquire '{job_name}'", ACQUIRE,
        setup_fn=setup,
        confirm_fn=partial(confirm_acquire,
                           settle_time=settle_time,
                           start_timeout=start_timeout,
                           heartbeat_interval=heartbeat_interval,
                           timeout=poll_timeout,
                           poll_interval=poll_interval),
        pre_check_timeout=pre_check_timeout,
    )


# =============================================================================
# Job selection
# =============================================================================

def select_job(client, job_name, poll_timeout=10.0, poll_interval=0.01):
    """Select a job by name.

    Routes through the backbone. No pre_check_fn (job switching doesn't
    need scanner idle). The "already selected" optimization stays in
    Phase A.

    Args:
        client: LAS X API client.
        job_name: Name of job to select.
        poll_timeout: Max seconds to wait for job switch confirmation.
        poll_interval: Seconds between get_jobs polls.
    """
    t0 = time.perf_counter()

    # Phase A: check if already selected (early exit)
    try:
        jobs = _readers.get_jobs(client)
        if jobs:
            for j in jobs:
                if j.get("Name") == job_name and j.get("IsSelected"):
                    elapsed = time.perf_counter() - t0
                    return {
                        "success": True, "confirmed": True,
                        "message": f"'{job_name}' already selected",
                        "timing": _make_timing(total_s=elapsed, attempts=0),
                        "logs": [],
                    }
    except Exception:
        log.debug("Could not check current job selection before select_job")

    # Phase B: backbone
    api_obj = client.PyApiSelectJobByName

    def setup(m):
        m.JobName = job_name

    return _dispatch(
        client, api_obj, f"SelectJob '{job_name}'", SELECT_JOB,
        setup_fn=setup,
        confirm_fn=partial(confirm_select_job, job_name=job_name,
                           timeout=poll_timeout,
                           poll_interval=poll_interval),
    )

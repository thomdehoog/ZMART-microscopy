"""
Command wrappers.
=================
Public ``set_*``, ``move_*``, ``acquire``, and ``select_job`` functions.
Each wrapper follows a three-phase pattern:

    **Phase A** - Pre-checks: input validation, limit checks, enum
        resolution, early-exit optimizations. Stays in the wrapper.
    **Phase B** - Backbone: calls ``confirm_and_fire`` with the command's
        profile. Replaces all bespoke dispatch code.
    **Phase C** - Post-processing: attach extra data to the result dict
        (e.g. ``move_xy`` attaches position readback).

Every command unpacks its profile and binds ``client`` via lambda.
The binding pattern is identical across all commands - no exceptions::

    pre_check_fn  = lambda: profile.pre_check_fn(client)
    error_check_fn = lambda: profile.error_check_fn(client)
    confirm_fn    = lambda: profile.confirm_fn(client, ...)

Numeric command tuning comes from ``profiles.py``. Wrapper keyword
arguments are explicit overrides for tests and unusual hardware runs;
``None`` means "use the profile".

Result contract: with the profiles' ``success_on_unconfirmed=True``
(deliberate — see ``CommandProfile``), ``result["success"]`` means the
command was *accepted*, not that it took effect. A caller that needs
proof the setting/move landed must check ``result["confirmed"]``.

Function-keyed limits gate: every mutating wrapper here declares its
``function_limits`` key in ``gate.MUTATING_COMMANDS`` and calls
``_limits_refusal`` in Phase A — fail-closed BEFORE the native call can
fire (no limits handshake / invalid machine-local limits / constraint
violation all refuse with a result dict). See ``commands/gate.py``.

Import restrictions: only command helpers, runtime profiles/utilities, limits,
the gate, readers, and confirmations. The ``prechecks`` import is used in
``_dispatch`` for the ``pre_check_timeout`` override.
"""

import logging
import math
import time
from functools import partial

from ..commands.errors import _check_api_error, _is_transient_error
from ..config.profiles import (
    ACQUIRE,
    DETECTOR_GAIN,
    FILTER_WHEEL_SLOT,
    FILTER_WHEEL_SPECTRUM,
    FRAME_ACCUMULATION,
    FRAME_AVERAGE,
    IMAGE_FORMAT,
    LASER_INTENSITY,
    LASER_SHUTTER,
    LINE_ACCUMULATION,
    LINE_AVERAGE,
    MOVE_XY,
    MOVE_Z,
    OBJECTIVE,
    PINHOLE_AIRY,
    SCAN_FIELD_ROTATION,
    SCAN_MODE,
    SCAN_RESONANT,
    SCAN_SPEED,
    SELECT_JOB,
    SEQUENTIAL_MODE,
    Z_STACK_DEFINITION,
    Z_STACK_SIZE,
    Z_STACK_STEP_SIZE,
    ZOOM,
)
from ..motion.limits import _check_xy_limits, _check_z_limits
from ..utils import PAN_LIMIT, _hw_get, _make_log_entry, _make_timing, parse_format
from . import gate as _gate
from .confirm_select_job import prepare_select_job, select_job_confirm_legs
from .confirmations import (
    _confirm_detector_gain,
    _confirm_filter_wheel_slot,
    _confirm_filter_wheel_spectrum,
    _confirm_frame_accumulation,
    _confirm_frame_average,
    _confirm_image_format,
    _confirm_laser_intensity,
    _confirm_laser_shutter,
    _confirm_line_accumulation,
    _confirm_line_average,
    _confirm_pinhole_airy,
    _confirm_scan_field_rotation,
    _confirm_scan_mode,
    _confirm_scan_resonant,
    _confirm_scan_speed,
    _confirm_sequential_mode,
    _confirm_z_stack_definition,
    _confirm_z_stack_size,
    _confirm_z_stack_step_size,
    _confirm_zoom,
    confirm_acquire,
    confirm_move_xy,
    confirm_move_z,
    confirm_objective,
    race_confirmations,
)
from .dispatch import confirm_and_fire
from .objectives import objective_by_slot
from .prechecks import check_idle

log = logging.getLogger(__name__)


def _profile_value(profile, name, override=None):
    """Return an explicit override or the command profile value."""
    return override if override is not None else getattr(profile, name)


def _limits_refusal(client, command, values, **extra):
    """Fail-closed function-limits gate for one wrapper (Phase A, before fire).

    Returns None when the command may fire, else the wrapper's fail-closed
    result dict (``success=False``, the native call must NOT fire). ``extra``
    lets a wrapper add its contract-specific keys (e.g. ``position=None``).
    """
    message = _gate.check_refusal(client, command, values)
    if message is None:
        return None
    log.error(message)
    return {
        "success": False,
        "confirmed": None,
        "message": message,
        "timing": _make_timing(total_s=0.0, attempts=0),
        "logs": [_make_log_entry("error", message)],
        **extra,
    }


def _has_bound_keyword(fn, name):
    """Return True when a partial already owns a keyword value."""
    return isinstance(fn, partial) and name in (fn.keywords or {})


# =============================================================================
# Internal helper - uniform backbone call
# =============================================================================


def _dispatch(
    client,
    api_obj,
    description,
    profile,
    *,
    setup_fn,
    confirm_fn=None,
    log_confirm_fn=None,
    confirm_race_budget_s=None,
    max_retries=None,
    retry_backoff=None,
    retry_escalate=None,
    max_confirm_attempts=None,
    pre_check_timeout=None,
    error_check_fn=None,
):
    """Call confirm_and_fire with a profile's settings.

    This is the single internal helper that all command wrappers call.
    It binds ``client`` into each profile callable via lambda, producing
    the zero-arg callables that the backbone expects. The binding
    pattern is identical for every command. Every confirmation routes
    through ``confirmations.race_confirmations``: with only the api leg
    (the normal case) that is an identity pass-through; commands that
    also have log evidence pass ``log_confirm_fn`` and the confirmation
    becomes a target-gated race with ``confirm_race_budget_s`` as its
    wall-clock bound (required, must fit inside one confirm attempt).

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
        log_confirm_fn: Optional log-evidence confirm leg. When provided,
            the confirmation becomes a target-gated race between the api and
            log legs instead of an identity pass-through.
        confirm_race_budget_s: Wall-clock bound for that race (seconds).
            Required when ``log_confirm_fn`` is given; must fit inside one
            confirm attempt.
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
        error_check_fn: Override for the profile's API echo error check.
            Use only for command-specific LAS X echo semantics.

    Returns:
        Result dict from confirm_and_fire.
    """
    # Resolve confirm_fn: explicit override > profile default > None
    effective_confirm = confirm_fn if confirm_fn is not None else profile.confirm_fn

    # Inject the confirm poll window (confirm_poll_s) from the profile into simple
    # readback confirmations. Long-poll confirms (acquire, select_job) bind their
    # own `timeout` and are left untouched by the guard below.
    if (
        effective_confirm is not None
        and profile.confirm_poll_s is not None
        and not _has_bound_keyword(effective_confirm, "timeout")
        and not _has_bound_keyword(effective_confirm, "poll_window")
    ):
        _inner = effective_confirm
        _poll_window = profile.confirm_poll_s

        def effective_confirm(c, _f=_inner, _t=_poll_window):
            return _f(c, poll_window=_t)

    # Resolve pre_check_fn: timeout override > profile default > None
    if pre_check_timeout is not None and profile.pre_check_fn is not None:
        heartbeat = getattr(profile.pre_check_fn, "keywords", {}).get("heartbeat", 30.0)

        def pre_check_fn():
            return check_idle(client, timeout=pre_check_timeout, heartbeat=heartbeat)
    elif profile.pre_check_fn is not None:

        def pre_check_fn():
            return profile.pre_check_fn(client)
    else:
        pre_check_fn = None

    effective_error_check = error_check_fn if error_check_fn is not None else profile.error_check_fn
    api_confirm_leg = (lambda: effective_confirm(client)) if effective_confirm else None
    final_confirm_fn = race_confirmations(
        api_leg=api_confirm_leg,
        log_leg=log_confirm_fn,
        label=description,
        budget_s=confirm_race_budget_s,
    )

    return confirm_and_fire(
        client,
        api_obj,
        description,
        setup_fn=setup_fn,
        pre_check_fn=pre_check_fn,
        error_check_fn=(lambda: effective_error_check(client)) if effective_error_check else None,
        confirm_fn=final_confirm_fn,
        max_retries=max_retries if max_retries is not None else profile.max_retries,
        max_confirm_attempts=max_confirm_attempts
        if max_confirm_attempts is not None
        else profile.max_confirm_attempts,
        refire_on_unconfirmed=profile.refire_on_unconfirmed,
        retry_backoff=retry_backoff if retry_backoff is not None else profile.retry_backoff,
        retry_escalate=retry_escalate if retry_escalate is not None else profile.retry_escalate,
        skip_echo=profile.skip_echo,
        receipt_timeout=profile.receipt_timeout,
        fire_async=profile.fire_async,
        success_on_unconfirmed=profile.success_on_unconfirmed,
    )


def _dispatch_setting(
    client,
    api_attr,
    field_map,
    description,
    profile,
    confirm_fn,
    *,
    max_retries=None,
    pre_check_timeout=None,
):
    """Fire a pure field-write setting command through the backbone.

    The boilerplate is identical for every pure-delegation setter: resolve
    the PyApi object, write a fixed map of model fields *in order*, and
    dispatch with the command's profile and a target-bound confirm. ``field_map``
    is an ordered ``{model_attr: value}`` mapping (insertion order is the write
    order, matching the original hand-written ``setup`` bodies).

    Setters that compute fields, resolve/cast enums, convert units, or validate
    inputs keep their own bodies and call ``_dispatch`` directly — they do not
    route through here.
    """
    api_obj = getattr(client, api_attr)

    def setup(m):
        for attr, value in field_map.items():
            setattr(m, attr, value)

    return _dispatch(
        client,
        api_obj,
        description,
        profile,
        setup_fn=setup,
        confirm_fn=confirm_fn,
        max_retries=max_retries,
        pre_check_timeout=pre_check_timeout,
    )


_SCAN_RESONANT_NO_CHANGE = "desired state does not differ from the current state"


def _scan_resonant_error_check(client, *, job_name, target, timeout=None):
    """Accept LAS X's resonant no-change echo only when readback agrees."""
    logs = []
    err = _check_api_error(client)

    if err is None:
        return {"success": True, "error": None, "transient": None, "logs": logs}

    error_msg = err.get("error", "")
    details = err.get("details", {})
    if _SCAN_RESONANT_NO_CHANGE in error_msg.lower():
        confirmed = _confirm_scan_resonant(client, job_name, target, poll_window=timeout)
        logs.extend(confirmed.get("logs", []))
        if confirmed.get("success"):
            msg = f"Resonant -> {target} already matched; accepting LAS X no-change response"
            logs.append(_make_log_entry("info", msg))
            return {"success": True, "error": None, "transient": None, "logs": logs}

    transient = _is_transient_error(error_msg)
    log_msg = f"API error: {error_msg}"
    if details:
        log_msg += f" | details: {details}"
    logs.append(_make_log_entry("warning" if transient else "error", log_msg))
    return {
        "success": False,
        "error": error_msg,
        "transient": transient,
        "logs": logs,
    }


# =============================================================================
# Set functions - Job-level
# =============================================================================


def set_zoom(client, job_name, value, *, max_retries=None, pre_check_timeout=None, tolerance=None):
    """Set zoom level for the specified job.

    Args:
        client: LAS X API client.
        job_name: Target job name.
        value: Desired zoom level.
        max_retries: Transient error retry ceiling.
        pre_check_timeout: Idle-wait timeout (seconds). None = profile default.
        tolerance: Readback confirmation tolerance.
    """
    refused = _limits_refusal(client, "set_zoom", {"job_name": job_name})
    if refused:
        return refused
    return _dispatch_setting(
        client,
        "PyApiSetZoomByJobName",
        {"JobName": job_name, "ZoomValue": value},
        f"Zoom -> {value}",
        ZOOM,
        partial(
            _confirm_zoom,
            job_name=job_name,
            target=value,
            tolerance=_profile_value(ZOOM, "confirm_tolerance", tolerance),
        ),
        max_retries=max_retries,
        pre_check_timeout=pre_check_timeout,
    )


def set_scan_speed(client, job_name, value, *, max_retries=None, pre_check_timeout=None):
    """Set scan speed for the specified job."""
    refused = _limits_refusal(client, "set_scan_speed", {"job_name": job_name})
    if refused:
        return refused
    return _dispatch_setting(
        client,
        "PyApiSetScanSpeedByJobName",
        {"JobName": job_name, "ScanSpeed": value},
        f"ScanSpeed -> {value}",
        SCAN_SPEED,
        partial(_confirm_scan_speed, job_name=job_name, target=value),
        max_retries=max_retries,
        pre_check_timeout=pre_check_timeout,
    )


def set_scan_resonant(client, job_name, enable, *, max_retries=None, pre_check_timeout=None):
    """Enable or disable resonant scanning for the specified job."""
    refused = _limits_refusal(client, "set_scan_resonant", {"job_name": job_name})
    if refused:
        return refused
    api_obj = client.PyApiSetScannerToResonantByJobName

    def setup(m):
        m.JobName = job_name
        m.EnableResonant = enable

    return _dispatch(
        client,
        api_obj,
        f"Resonant -> {enable}",
        SCAN_RESONANT,
        setup_fn=setup,
        confirm_fn=partial(_confirm_scan_resonant, job_name=job_name, target=enable),
        error_check_fn=partial(
            _scan_resonant_error_check,
            job_name=job_name,
            target=enable,
            timeout=SCAN_RESONANT.confirm_poll_s,
        ),
        max_retries=max_retries,
        pre_check_timeout=pre_check_timeout,
    )


def set_scan_mode(client, job_name, mode, *, max_retries=None, pre_check_timeout=None):
    """Set scan mode (e.g. 'xyz', 'xyzt') for the specified job."""
    refused = _limits_refusal(client, "set_scan_mode", {"job_name": job_name})
    if refused:
        return refused
    return _dispatch_setting(
        client,
        "PyApiSetScanModeByJobName",
        {"JobName": job_name, "ScanModeValue": mode},
        f"ScanMode -> {mode}",
        SCAN_MODE,
        partial(_confirm_scan_mode, job_name=job_name, target=mode),
        max_retries=max_retries,
        pre_check_timeout=pre_check_timeout,
    )


def set_sequential_mode(client, job_name, mode, *, max_retries=None, pre_check_timeout=None):
    """Set sequential mode ('Line', 'Frame', or 'Stack') for the specified job."""
    refused = _limits_refusal(client, "set_sequential_mode", {"job_name": job_name})
    if refused:
        return refused
    # Phase A: input validation and enum resolution
    if not isinstance(mode, str) or not mode.strip():
        return {
            "success": False,
            "confirmed": None,
            "message": f"SequentialMode -> {repr(mode)} | Invalid: mode must be a "
            f"non-empty string. Valid: ['Line', 'Frame', 'Stack']",
            "timing": _make_timing(total_s=0.0, attempts=0),
            "logs": [],
        }

    _enum_map = {
        "Line": "eSequentialLine",
        "Frame": "eSequentialFrame",
        "Stack": "eSequentialStack",
    }
    enum_val = _enum_map.get(mode)
    if enum_val is None:
        return {
            "success": False,
            "confirmed": None,
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
        client,
        api_obj,
        f"SequentialMode -> {mode}",
        SEQUENTIAL_MODE,
        setup_fn=setup,
        confirm_fn=partial(_confirm_sequential_mode, job_name=job_name, target=mode),
        max_retries=max_retries,
        pre_check_timeout=pre_check_timeout,
    )


def set_scan_field_rotation(
    client, job_name, angle, *, max_retries=None, pre_check_timeout=None, tolerance=None
):
    """Set scan field rotation angle (degrees) for the specified job."""
    refused = _limits_refusal(client, "set_scan_field_rotation", {"job_name": job_name})
    if refused:
        return refused
    return _dispatch_setting(
        client,
        "PyApiSetScanFieldRotationByJobName",
        {"JobName": job_name, "Rotation": angle},
        f"Rotation -> {angle}",
        SCAN_FIELD_ROTATION,
        partial(
            _confirm_scan_field_rotation,
            job_name=job_name,
            target=angle,
            tolerance=_profile_value(SCAN_FIELD_ROTATION, "confirm_tolerance", tolerance),
        ),
        max_retries=max_retries,
        pre_check_timeout=pre_check_timeout,
    )


def set_image_format(client, job_name, format_str, *, max_retries=None, pre_check_timeout=None):
    """Set image dimensions for the specified job.

    Args:
        format_str: Either a string like '512 x 512' or a tuple (w, h).
    """
    refused = _limits_refusal(client, "set_image_format", {"job_name": job_name})
    if refused:
        return refused
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
        client,
        api_obj,
        f"Format -> {w} x {h}",
        IMAGE_FORMAT,
        setup_fn=setup,
        confirm_fn=partial(_confirm_image_format, job_name=job_name, w=w, h=h),
        max_retries=max_retries,
        pre_check_timeout=pre_check_timeout,
    )


def _resolve_objective(hw_info, slot_index=None, name=None, magnification=None):
    """Resolve an objective to (slot, display_name) from hardware info.

    Any one of *slot_index*, *name*, or *magnification* identifies the
    objective.  Returns ``(None, None)`` if not found.
    """
    # Empty turret slots (objectiveNumber 0) are excluded by objective_by_slot;
    # sending those to LAS X can trigger modal error dialogs that block the app.
    for obj in objective_by_slot(hw_info).values():
        s = _hw_get(obj, "slotIndex")
        n = _hw_get(obj, "name", "").strip()
        m = _hw_get(obj, "magnification")

        if slot_index is not None and s == slot_index:
            return s, n
        if name is not None and n == name.strip():
            return s, n
        if magnification is not None and m == magnification:
            return s, n

    return None, None


def set_objective(
    client,
    job_name,
    hw_info,
    slot_index=None,
    name=None,
    magnification=None,
    *,
    max_retries=None,
    pre_check_timeout=None,
):
    """Set objective by slot index, name, or magnification.

    Resolves the input to a slot index, then fires the command.
    Exactly one of slot_index, name, or magnification must be provided.
    """
    refused = _limits_refusal(client, "set_objective", {"job_name": job_name})
    if refused:
        return refused
    selectors = [v for v in (slot_index, name, magnification) if v is not None]
    if len(selectors) != 1:
        return {
            "success": False,
            "confirmed": None,
            "message": (
                "exactly one of slot_index, name, or magnification must be "
                f"provided (got {len(selectors)})"
            ),
            "timing": _make_timing(total_s=0.0, attempts=0),
            "logs": [],
        }
    slot, target_name = _resolve_objective(
        hw_info, slot_index=slot_index, name=name, magnification=magnification
    )

    if slot is None:
        available = [
            (_hw_get(o, "slotIndex"), _hw_get(o, "name", "").strip())
            for o in objective_by_slot(hw_info).values()
        ]
        return {
            "success": False,
            "confirmed": None,
            "message": f"Could not find objective: slot_index={slot_index}, "
            f"name={name}, mag={magnification}. "
            f"Available: {available}",
            "timing": _make_timing(total_s=0.0, attempts=0),
            "logs": [],
        }

    api_obj = client.PyApiSetObjectiveSlotByJobName

    def setup(m):
        m.JobName = job_name
        m.ObjectiveSlotIndex = slot

    return _dispatch(
        client,
        api_obj,
        f"Objective -> {target_name} (slot {slot})",
        OBJECTIVE,
        setup_fn=setup,
        confirm_fn=partial(
            confirm_objective, job_name=job_name, target_slot=slot, target_name=target_name
        ),
        max_retries=max_retries,
        pre_check_timeout=pre_check_timeout,
    )


# =============================================================================
# Set functions - Z-Stack
# =============================================================================


def set_z_stack_definition(
    client,
    job_name,
    begin_um=None,
    end_um=None,
    old_begin_um=None,
    old_end_um=None,
    *,
    max_retries=None,
    pre_check_timeout=None,
    tolerance=None,
):
    """Set z-stack begin/end positions (micrometers).

    Args:
        begin_um, end_um: New positions; None leaves the field untouched
            (unless the matching old_* flag requests a reset).
        old_begin_um, old_end_um: Reset *flags*, not values — passing any
            non-None value asks LAS X to reset that field to its default
            (SetBegin/SetEnd = 0). The numeric value itself is never sent.

    Note: confirm_fn is provided but LAS X may recalculate z-stack
    geometry (size, end) after setting begin/end. Confirmation may
    report unconfirmed even though the command was accepted; reset
    outcomes are not confirmed at all (only non-None targets are).
    """
    refused = _limits_refusal(client, "set_z_stack_definition", {"job_name": job_name})
    if refused:
        return refused
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
        client,
        api_obj,
        f"Z-stack def: begin={begin_um}, end={end_um}",
        Z_STACK_DEFINITION,
        setup_fn=setup,
        confirm_fn=partial(
            _confirm_z_stack_definition,
            job_name=job_name,
            begin_um=begin_um,
            end_um=end_um,
            tolerance=_profile_value(Z_STACK_DEFINITION, "confirm_tolerance", tolerance),
        ),
        max_retries=max_retries,
        pre_check_timeout=pre_check_timeout,
    )


def set_z_stack_step_size(
    client, job_name, step_size_um, *, max_retries=None, pre_check_timeout=None, tolerance=None
):
    """Set z-stack step size (micrometers)."""
    refused = _limits_refusal(client, "set_z_stack_step_size", {"job_name": job_name})
    if refused:
        return refused
    api_obj = client.PyApiCommandSetZStackStepSizeByJobName

    def setup(m):
        m.JobName = job_name
        m.StackStepSize = step_size_um * 1e-6

    return _dispatch(
        client,
        api_obj,
        f"Z-stack step -> {step_size_um} um",
        Z_STACK_STEP_SIZE,
        setup_fn=setup,
        confirm_fn=partial(
            _confirm_z_stack_step_size,
            job_name=job_name,
            target=step_size_um,
            tolerance=_profile_value(Z_STACK_STEP_SIZE, "confirm_tolerance", tolerance),
        ),
        max_retries=max_retries,
        pre_check_timeout=pre_check_timeout,
    )


def set_z_stack_size(
    client, job_name, size_um, *, max_retries=None, pre_check_timeout=None, tolerance=None
):
    """Set z-stack total size (micrometers).

    Note: LAS X may recalculate z-stack geometry when size is changed.
    Confirmation may report unconfirmed if "System Optimized" is active.
    """
    refused = _limits_refusal(client, "set_z_stack_size", {"job_name": job_name})
    if refused:
        return refused
    api_obj = client.PyApiSetZStackSizeByJobName

    def setup(m):
        m.JobName = job_name
        m.StackSize = size_um * 1e-6

    return _dispatch(
        client,
        api_obj,
        f"Z-stack size -> {size_um} um",
        Z_STACK_SIZE,
        setup_fn=setup,
        confirm_fn=partial(
            _confirm_z_stack_size,
            job_name=job_name,
            target_um=size_um,
            tolerance=_profile_value(Z_STACK_SIZE, "confirm_tolerance", tolerance),
        ),
        max_retries=max_retries,
        pre_check_timeout=pre_check_timeout,
    )


# =============================================================================
# Set functions - Per-setting
# =============================================================================


def set_frame_accumulation(
    client, job_name, setting_index, value, *, max_retries=None, pre_check_timeout=None
):
    """Set frame accumulation count for a specific setting index."""
    refused = _limits_refusal(client, "set_frame_accumulation", {"job_name": job_name})
    if refused:
        return refused
    return _dispatch_setting(
        client,
        "PyApiSetFrameAccumulationByJobName",
        {"JobName": job_name, "SettingIndex": setting_index, "FrameAccumulation": value},
        f"Setting[{setting_index}].FrameAccumulation -> {value}",
        FRAME_ACCUMULATION,
        partial(_confirm_frame_accumulation, job_name=job_name, si=setting_index, target=value),
        max_retries=max_retries,
        pre_check_timeout=pre_check_timeout,
    )


def set_frame_average(
    client, job_name, setting_index, value, *, max_retries=None, pre_check_timeout=None
):
    """Set frame average count for a specific setting index."""
    refused = _limits_refusal(client, "set_frame_average", {"job_name": job_name})
    if refused:
        return refused
    return _dispatch_setting(
        client,
        "PyApiSetFrameAverageByJobName",
        {"JobName": job_name, "SettingIndex": setting_index, "FrameAverage": value},
        f"Setting[{setting_index}].FrameAverage -> {value}",
        FRAME_AVERAGE,
        partial(_confirm_frame_average, job_name=job_name, si=setting_index, target=value),
        max_retries=max_retries,
        pre_check_timeout=pre_check_timeout,
    )


def set_line_accumulation(
    client, job_name, setting_index, value, *, max_retries=None, pre_check_timeout=None
):
    """Set line accumulation count for a specific setting index."""
    refused = _limits_refusal(client, "set_line_accumulation", {"job_name": job_name})
    if refused:
        return refused
    return _dispatch_setting(
        client,
        "PyApiSetLineAccumulationByJobName",
        {"JobName": job_name, "SettingIndex": setting_index, "LineAccumulation": value},
        f"Setting[{setting_index}].LineAccumulation -> {value}",
        LINE_ACCUMULATION,
        partial(_confirm_line_accumulation, job_name=job_name, si=setting_index, target=value),
        max_retries=max_retries,
        pre_check_timeout=pre_check_timeout,
    )


def set_line_average(
    client, job_name, setting_index, value, *, max_retries=None, pre_check_timeout=None
):
    """Set line average count for a specific setting index."""
    refused = _limits_refusal(client, "set_line_average", {"job_name": job_name})
    if refused:
        return refused
    return _dispatch_setting(
        client,
        "PyApiSetLineAverageByJobName",
        {"JobName": job_name, "SettingIndex": setting_index, "LineAverage": value},
        f"Setting[{setting_index}].LineAverage -> {value}",
        LINE_AVERAGE,
        partial(_confirm_line_average, job_name=job_name, si=setting_index, target=value),
        max_retries=max_retries,
        pre_check_timeout=pre_check_timeout,
    )


def set_pinhole_airy(
    client,
    job_name,
    setting_index,
    value,
    *,
    max_retries=None,
    pre_check_timeout=None,
    tolerance=None,
):
    """Set pinhole size in Airy units for a specific setting index."""
    refused = _limits_refusal(client, "set_pinhole_airy", {"job_name": job_name})
    if refused:
        return refused
    return _dispatch_setting(
        client,
        "PyApiSetPinholeAUByJobName",
        {"JobName": job_name, "SettingIndex": setting_index, "PinholeAiry": value},
        f"Setting[{setting_index}].PinholeAiry -> {value}",
        PINHOLE_AIRY,
        partial(
            _confirm_pinhole_airy,
            job_name=job_name,
            si=setting_index,
            target=value,
            tolerance=_profile_value(PINHOLE_AIRY, "confirm_tolerance", tolerance),
        ),
        max_retries=max_retries,
        pre_check_timeout=pre_check_timeout,
    )


# =============================================================================
# Set functions - Detector
# =============================================================================


def set_detector_gain(
    client,
    job_name,
    setting_index,
    beam_route,
    value,
    *,
    max_retries=None,
    pre_check_timeout=None,
    tolerance=None,
):
    """Set detector gain for a specific detector identified by beam route."""
    refused = _limits_refusal(client, "set_detector_gain", {"job_name": job_name})
    if refused:
        return refused
    return _dispatch_setting(
        client,
        "PyApiSetDetectorGainByJobName",
        {
            "JobName": job_name,
            "SettingIndex": setting_index,
            "BeamRoute": beam_route,
            "GainValue": value,
        },
        f"Setting[{setting_index}].Detector[{beam_route}].Gain -> {value}",
        DETECTOR_GAIN,
        partial(
            _confirm_detector_gain,
            job_name=job_name,
            si=setting_index,
            beam_route=beam_route,
            target=value,
            tolerance=_profile_value(DETECTOR_GAIN, "confirm_tolerance", tolerance),
        ),
        max_retries=max_retries,
        pre_check_timeout=pre_check_timeout,
    )


# =============================================================================
# Set functions - Laser
# =============================================================================


def set_laser_intensity(
    client,
    job_name,
    setting_index,
    beam_route,
    line_index,
    value,
    *,
    max_retries=None,
    pre_check_timeout=None,
    tolerance=None,
):
    """Set laser intensity (0.0-1.0) for a specific laser line."""
    refused = _limits_refusal(client, "set_laser_intensity", {"job_name": job_name})
    if refused:
        return refused
    return _dispatch_setting(
        client,
        "PyApiSetLaserIntensityByJobName",
        {
            "JobName": job_name,
            "SettingIndex": setting_index,
            "BeamRoute": beam_route,
            "LaserLineIndex": line_index,
            "IntensityValue": value,
            "IsRoiBackground": False,
        },
        f"Setting[{setting_index}].Laser[{beam_route}][{line_index}] -> {value}",
        LASER_INTENSITY,
        partial(
            _confirm_laser_intensity,
            job_name=job_name,
            si=setting_index,
            beam_route=beam_route,
            line_index=line_index,
            target=value,
            tolerance=_profile_value(LASER_INTENSITY, "confirm_tolerance", tolerance),
        ),
        max_retries=max_retries,
        pre_check_timeout=pre_check_timeout,
    )


def set_laser_shutter(
    client,
    job_name,
    setting_index,
    beam_route,
    activate,
    *,
    max_retries=None,
    pre_check_timeout=None,
):
    """Open or close laser shutter for a specific beam route."""
    refused = _limits_refusal(client, "set_laser_shutter", {"job_name": job_name})
    if refused:
        return refused
    label = "Open" if activate else "Closed"
    return _dispatch_setting(
        client,
        "PyApiSetLaserShutterByJobName",
        {
            "JobName": job_name,
            "SettingIndex": setting_index,
            "BeamRoute": beam_route,
            "Activate": activate,
        },
        f"Setting[{setting_index}].Shutter[{beam_route}] -> {label}",
        LASER_SHUTTER,
        partial(
            _confirm_laser_shutter,
            job_name=job_name,
            si=setting_index,
            beam_route=beam_route,
            target=activate,
        ),
        max_retries=max_retries,
        pre_check_timeout=pre_check_timeout,
    )


# =============================================================================
# Set functions - Filter Wheel
# =============================================================================


def set_filter_wheel_slot(
    client,
    job_name,
    setting_index,
    beam_route,
    filter_wheel_type,
    slot_index,
    *,
    max_retries=None,
    pre_check_timeout=None,
):
    """Set filter wheel to a specific slot."""
    refused = _limits_refusal(client, "set_filter_wheel_slot", {"job_name": job_name})
    if refused:
        return refused
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
        client,
        api_obj,
        f"FilterWheel[{beam_route}] slot -> {slot_index}",
        FILTER_WHEEL_SLOT,
        setup_fn=setup,
        confirm_fn=partial(
            _confirm_filter_wheel_slot,
            job_name=job_name,
            si=setting_index,
            beam_route=beam_route,
            fw_type=filter_wheel_type,
            target=slot_index,
        ),
        max_retries=max_retries,
        pre_check_timeout=pre_check_timeout,
    )


def set_filter_wheel_spectrum(
    client,
    job_name,
    setting_index,
    beam_route,
    filter_wheel_type,
    position,
    *,
    max_retries=None,
    pre_check_timeout=None,
    tolerance=None,
):
    """Set filter wheel spectrum position (nm)."""
    refused = _limits_refusal(client, "set_filter_wheel_spectrum", {"job_name": job_name})
    if refused:
        return refused
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
        client,
        api_obj,
        f"FilterWheel[{beam_route}] spectrum -> {position}",
        FILTER_WHEEL_SPECTRUM,
        setup_fn=setup,
        confirm_fn=partial(
            _confirm_filter_wheel_spectrum,
            job_name=job_name,
            si=setting_index,
            beam_route=beam_route,
            fw_type=filter_wheel_type,
            target=position,
            tolerance=_profile_value(FILTER_WHEEL_SPECTRUM, "confirm_tolerance", tolerance),
        ),
        max_retries=max_retries,
        pre_check_timeout=pre_check_timeout,
    )


# =============================================================================
# Stage movement
# =============================================================================


def move_xy(client, x, y, unit="um", *, max_retries=None, pre_check_timeout=None, tolerance=None):
    """Move XY stage to absolute position.

    Args:
        client: LAS X API client.
        x, y: Target coordinates in the specified unit.
        unit: 'um' (micrometers), 'mm' (millimeters), or 'm' (meters).
        tolerance: Position confirmation tolerance in micrometers.

    Returns:
        Result dict; 'position' is the requested *target* (meters), not a
        readback — check 'confirmed' for evidence the stage arrived.
    """
    if unit not in ("um", "mm", "m"):
        return {
            "success": False,
            "confirmed": None,
            "message": f"unknown unit {unit!r} (expected 'um', 'mm', or 'm')",
            "position": None,
            "timing": _make_timing(total_s=0.0, attempts=0),
            "logs": [],
        }
    # Phase A: convert to um, gate on the function-keyed limits, then the
    # stage envelope + backstop — all before the native call can fire.
    try:
        if unit == "mm":
            x_um, y_um = x * 1000, y * 1000
        elif unit == "m":
            x_um, y_um = x * 1e6, y * 1e6
        else:
            x_um, y_um = x, y
        refused = _limits_refusal(client, "move_xy", {"x_um": x_um, "y_um": y_um}, position=None)
        if refused:
            return refused
        _check_xy_limits(x_um, y_um)
    except (RuntimeError, TypeError) as e:
        return {
            "success": False,
            "confirmed": None,
            "message": str(e),
            "position": None,
            "timing": _make_timing(total_s=0.0, attempts=0),
            "logs": [],
        }

    api_obj = client.PyApiMoveHardwareXY

    # Resolve .NET enums with integer fallback
    UNIT_ENUM_MAP = {"um": "eMicrons", "mm": "eMillimeter", "m": "eMeter"}
    UNIT_INT_MAP = {"um": 4, "mm": 3, "m": 1}
    try:
        unit_val = getattr(type(api_obj.Model.Units), UNIT_ENUM_MAP[unit])
    except Exception:
        unit_val = UNIT_INT_MAP[unit]
        log.warning("Units enum resolution failed, using int fallback: %d", unit_val)

    try:
        mode_val = type(api_obj.Model.MoveXyMode).eMoveXY
    except Exception:
        mode_val = 2  # eMoveXY=2 (NOT 0 which is eDontMove!)
        log.warning("MoveXyMode enum resolution failed, using int fallback: %d", mode_val)

    def setup(m):
        m.RelativePosition = False
        m.XPosition = x
        m.YPosition = y
        m.MoveXyMode = mode_val
        m.Units = unit_val

    # Phase B: backbone
    r = _dispatch(
        client,
        api_obj,
        f"MoveXY -> ({x}, {y}) {unit}",
        MOVE_XY,
        setup_fn=setup,
        confirm_fn=partial(
            confirm_move_xy,
            target_x_um=x_um,
            target_y_um=y_um,
            tolerance=_profile_value(MOVE_XY, "confirm_tolerance", tolerance),
        ),
        max_retries=max_retries,
        pre_check_timeout=pre_check_timeout,
    )

    # Target position (not a readback - check r["confirmed"] for verification status)
    r["position"] = {"x": x_um * 1e-6, "y": y_um * 1e-6, "x_um": x_um, "y_um": y_um}
    return r


# ── Galvo pan limits ────────────────────────────────────────────────
# Single source: utils.PAN_LIMIT (max pan value in either axis, objective-
# independent; see the galvo pan calibration header in utils.py).
_PAN_LIMIT = PAN_LIMIT


def move_galvo_to_pixel(client, px, py, *, job_name=None, pixel_size_um=None, image_size=None):
    """Pan the galvo so the pixel ``(px, py)`` of the current frame appears at FOV centre.

    The primary galvo navigation primitive: take a pixel coordinate from
    whatever image is currently loaded and pan there. No stage XY round-trip,
    no calibration matrix - pan is image-frame, derived from documented LAS X
    invariants (see ``galvo_pan_for_pixel``). The stage does not move.

    The pan is composed *atomically* with whatever pan was previously written
    (read-modify-write inside one ``apply_lrp_change`` transaction): if the
    frame was already acquired at non-zero pan, this still recentres on
    ``(px, py)`` of that frame.

    ``pixel_size_um`` and ``image_size`` default to the active acquisition's
    geometry (``parse_tile_geometry`` from ``get_job_settings``); pass them
    explicitly only if the caller has cached values.

    Returns a dict with ``success``, ``pan`` (the absolute pan written),
    ``delta_pan`` (what was added), ``pan_scale_um``, ``message``. Returns
    ``success=False`` with ``message`` if the resulting absolute pan would
    exceed the angular limit (``_PAN_LIMIT``); the caller should stage-move
    closer first.
    """
    from ..experimental.lrp_edits.roi import galvo_pan_for_pixel
    from ..experimental.lrp_edits.scan import lrp_get_pan, lrp_set_pan
    from ..readers import get_base_fov, get_job_settings, get_selected_job
    from ..scanfields.files import TEMPLATE_XML
    from ..scanfields.transaction import apply_lrp_change
    from ..utils import pan_scale_um_from_base_fov, parse_tile_geometry

    # Function-keyed gate (fail-closed state check up front; the composed
    # absolute pan is checked again against the file inside the transaction,
    # once it is known).
    refused = _gate.check_refusal(client, "move_galvo_to_pixel", {})
    if refused is not None:
        log.error(refused)
        return {
            "success": False,
            "pan": None,
            "delta_pan": None,
            "pan_scale_um": None,
            "message": refused,
        }

    if job_name is None:
        # These reads parameterize the command that follows, so they use the
        # authoritative API path rather than the passive reader profile.
        sel = get_selected_job(client, mode="api")
        job_name = sel.get("Name") if sel else None
    if not job_name:
        return {
            "success": False,
            "pan": None,
            "delta_pan": None,
            "pan_scale_um": None,
            "message": "No job name provided and no job selected",
        }

    if pixel_size_um is None or image_size is None:
        geo = parse_tile_geometry(get_job_settings(client, job_name, mode="api") or {})
        pixel_size_um = pixel_size_um if pixel_size_um is not None else float(geo["pixel_w_um"])
        image_size = image_size if image_size is not None else int(geo["pixels_x"])

    base_fov_m = get_base_fov(client, job_name, mode="api")
    if not base_fov_m:
        return {
            "success": False,
            "pan": None,
            "delta_pan": None,
            "pan_scale_um": None,
            "message": "Could not read base FOV to resolve pan scale",
        }
    pan_scale_um = pan_scale_um_from_base_fov(base_fov_m[0] * 1e6)

    d_pan_x, d_pan_y = galvo_pan_for_pixel(
        px,
        py,
        pixel_size_um=pixel_size_um,
        image_size=image_size,
        pan_scale_um=pan_scale_um,
    )

    new_pan = [None, None]

    def _edit(p):
        cur_x, cur_y = lrp_get_pan(p, job_name)
        new_pan[0] = cur_x + d_pan_x
        new_pan[1] = cur_y + d_pan_y
        # NaN compares False against the angular limit below, so a poisoned
        # pixel target (or a corrupt current pan) would otherwise be written
        # into the LRP verbatim — refuse non-finite pans outright.
        if not (math.isfinite(new_pan[0]) and math.isfinite(new_pan[1])):
            raise RuntimeError(
                f"resulting pan ({new_pan[0]!r}, {new_pan[1]!r}) is not finite; "
                f"refusing the galvo pan (poisoned pixel target or corrupt current pan)"
            )
        if abs(new_pan[0]) > _PAN_LIMIT or abs(new_pan[1]) > _PAN_LIMIT:
            raise RuntimeError(
                f"resulting pan ({new_pan[0]:+.5f}, {new_pan[1]:+.5f}) "
                f"exceeds angular limit ±{_PAN_LIMIT}; stage-move closer first."
            )
        # The machine file may constrain the absolute pan further; check the
        # composed value before it is written into the LRP.
        gate_message = _gate.check_refusal(
            client, "move_galvo_to_pixel", {"pan_x": new_pan[0], "pan_y": new_pan[1]}
        )
        if gate_message is not None:
            raise RuntimeError(gate_message)
        lrp_set_pan(p, new_pan[0], new_pan[1], job_name)

    try:
        # Use the default confirm_delays from apply_lrp_change rather
        # than a shortened tuple. A shorter retry budget runs out when
        # LAS X is slow late in a long session - the ROI cookbook with
        # the default budget keeps working in those same conditions.
        r = apply_lrp_change(client, TEMPLATE_XML, _edit)
    except RuntimeError as e:
        return {
            "success": False,
            "pan": tuple(new_pan),
            "delta_pan": (d_pan_x, d_pan_y),
            "pan_scale_um": pan_scale_um,
            "message": str(e),
        }

    success = r is not None and r.get("success", False)
    return {
        "success": success,
        "pan": tuple(new_pan),
        "delta_pan": (d_pan_x, d_pan_y),
        "pan_scale_um": pan_scale_um,
        "message": "OK" if success else "apply_lrp_change failed",
    }


def move_z(
    client,
    job_name,
    z,
    unit="um",
    z_mode="galvo",
    *,
    max_retries=None,
    pre_check_timeout=None,
    tolerance=None,
):
    """Move Z drive to an absolute position (galvo or zwide).

    Args:
        client: LAS X API client.
        job_name: Target job.
        z: Target position (can be negative).
        unit: 'um', 'mm', or 'm'.
        z_mode: Drive type - 'galvo' or 'zwide'.
        tolerance: Position confirmation tolerance in micrometers.
    """
    ZMODE_MAP = {"galvo": "eUseGalvo", "zwide": "eUseZWide"}
    UNIT_MAP = {"um": "eMicrons", "mm": "eMillimeter", "m": "eMeter"}
    UNIT_INT_MAP = {"um": 4, "mm": 3, "m": 1}

    z_member = ZMODE_MAP.get(z_mode)
    if z_member is None:
        return {
            "success": False,
            "confirmed": None,
            "message": f"Unknown z_mode '{z_mode}'. Use: {list(ZMODE_MAP.keys())}",
            "timing": _make_timing(total_s=0.0, attempts=0),
            "logs": [],
        }
    if unit not in UNIT_MAP:
        return {
            "success": False,
            "confirmed": None,
            "message": f"unknown unit {unit!r}. Use: {list(UNIT_MAP.keys())}",
            "timing": _make_timing(total_s=0.0, attempts=0),
            "logs": [],
        }

    # Convert to um for limit check and confirmation
    try:
        if unit == "mm":
            z_um = z * 1000
        elif unit == "m":
            z_um = z * 1e6
        else:
            z_um = z

        # Function-keyed gate, then the stage envelope + backstop — all
        # before the native call can fire.
        refused = _limits_refusal(
            client, "move_z", {f"z_{'galvo' if z_mode == 'galvo' else 'wide'}_um": z_um}
        )
        if refused:
            return refused
        _check_z_limits(z_um, z_mode)
    except (RuntimeError, ValueError, TypeError) as e:
        return {
            "success": False,
            "confirmed": None,
            "message": str(e),
            "timing": _make_timing(total_s=0.0, attempts=0),
            "logs": [],
        }

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
        log.warning("Units enum resolution failed, using int fallback: %d", unit_val)

    def setup(m):
        m.JobName = job_name
        m.RelativePosition = False
        m.ZPosition = z
        m.ZUseMode = z_use_val
        m.Units = unit_val

    return _dispatch(
        client,
        api_obj,
        f"Z -> {z} {unit} ({z_mode})",
        MOVE_Z,
        setup_fn=setup,
        confirm_fn=partial(
            confirm_move_z,
            job_name=job_name,
            z_mode=z_mode,
            target_um=z_um,
            tolerance=_profile_value(MOVE_Z, "confirm_tolerance", tolerance),
        ),
        max_retries=max_retries,
        pre_check_timeout=pre_check_timeout,
    )


# =============================================================================
# Acquisition
# =============================================================================


def acquire(
    client,
    job_name,
    poll_interval=None,
    poll_timeout=None,
    heartbeat_interval=None,
    start_timeout=None,
    pre_check_timeout=None,
):
    """Trigger acquisition and block until scan completes.

    Routes through the backbone for consistent idle-wait and timing
    instrumentation. Acquisition commands are deliberately fired once.
    If LAS X never reports scanning before ``start_timeout``, the result
    is a failure; the driver does not send a second acquire command.

    Args:
        client: LAS X API client.
        job_name: Job to acquire.
        poll_interval: Seconds between scan status polls during completion.
        poll_timeout: Hard ceiling for scan completion (seconds). None
            for no timeout (wait indefinitely).
        heartbeat_interval: Log interval during long scans (seconds).
        start_timeout: Seconds to wait for scan to start before
            reporting failure.

    Returns:
        Result dict with timing in timing['total_s'].
    """
    refused = _limits_refusal(client, "acquire", {"job_name": job_name})
    if refused:
        return refused

    api_obj = client.PyApiAcquireJob

    def setup(m):
        m.JobName = job_name

    return _dispatch(
        client,
        api_obj,
        f"Acquire '{job_name}'",
        ACQUIRE,
        setup_fn=setup,
        confirm_fn=partial(
            confirm_acquire,
            start_timeout=_profile_value(ACQUIRE, "start_timeout", start_timeout),
            heartbeat_interval=_profile_value(ACQUIRE, "heartbeat_interval", heartbeat_interval),
            timeout=_profile_value(ACQUIRE, "poll_timeout", poll_timeout),
            poll_interval=_profile_value(ACQUIRE, "poll_interval", poll_interval),
        ),
        pre_check_timeout=pre_check_timeout,
    )


# =============================================================================
# Job selection
# =============================================================================


def select_job(client, job_name, poll_timeout=None, poll_interval=None):
    """Select a job by name.

    Routes through the backbone. The SELECT_JOB profile pre-checks scanner
    idle before firing (``check_idle`` with no timeout). Source policy
    (api / log / hybrid) lives entirely
    in the confirmation layer: ``prepare_select_job`` owns the
    "already selected" decision and the api baseline, and
    ``select_job_confirm_legs`` builds the confirmation legs the dispatch
    race runs.

    Args:
        client: LAS X API client.
        job_name: Name of job to select.
        poll_timeout: Max seconds to wait for job switch confirmation.
        poll_interval: Seconds between get_jobs polls.
    """
    refused = _limits_refusal(client, "select_job", {"job_name": job_name})
    if refused:
        return refused

    t0 = time.perf_counter()
    noop, context = prepare_select_job(client, job_name)
    if noop is not None:
        noop["timing"] = _make_timing(total_s=time.perf_counter() - t0, attempts=0)
        return noop

    api_obj = client.PyApiSelectJobByName

    def setup(m):
        m.JobName = job_name

    command_started_at = time.time()
    api_confirm, log_leg, budget_s = select_job_confirm_legs(
        job_name,
        command_started_at=command_started_at,
        api_baseline_name=context["api_baseline_name"],
        timeout=_profile_value(SELECT_JOB, "poll_timeout", poll_timeout),
        poll_interval=_profile_value(SELECT_JOB, "poll_interval", poll_interval),
    )
    result = _dispatch(
        client,
        api_obj,
        f"SelectJob '{job_name}'",
        SELECT_JOB,
        setup_fn=setup,
        confirm_fn=api_confirm,
        log_confirm_fn=log_leg,
        confirm_race_budget_s=budget_s,
    )
    if context["api_said_selected"]:
        result.setdefault("logs", []).append(
            _make_log_entry(
                "info",
                "API reported target already selected before SelectJob, "
                "but the log-participating confirmation still fired the "
                "command",
            )
        )
    return result

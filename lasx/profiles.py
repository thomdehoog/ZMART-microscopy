"""
Per-command profiles.
=====================
Every command has a ``CommandProfile`` that is its complete recipe — all
pluggable callables and all retry/confirm settings in one place. Adding
a new command means adding a profile and a command function. Tuning a
command means editing its profile. Nothing else needs to change.

All four callable fields follow the same rule: ``callable(client) → result``.
Extra parameters are pre-bound with ``partial`` at profile definition
time. The command function always binds ``client`` via lambda — the same
pattern for every field, no exceptions.

**Two patterns cover all cases:**

    Pattern A — callable needs extra parameters: use partial to pre-bind.
    Pattern B — callable takes only client: assign directly.

Import restrictions: only ``checks``, ``confirm``, ``errors``, and
stdlib. Nothing from ``core``, ``commands``, or ``util``.
"""

from dataclasses import dataclass
from functools import partial

from .checks import check_idle
from .confirm import (
    _confirm_zoom,
    _confirm_scan_speed,
    _confirm_scan_resonant,
    _confirm_scan_mode,
    _confirm_sequential_mode,
    _confirm_scan_field_rotation,
    _confirm_image_format,
    confirm_objective,
    _confirm_z_stack_definition,
    _confirm_z_stack_step_size,
    _confirm_z_stack_size,
    _confirm_frame_accumulation,
    _confirm_frame_average,
    _confirm_line_accumulation,
    _confirm_line_average,
    _confirm_pinhole_airy,
    _confirm_detector_gain,
    _confirm_laser_intensity,
    _confirm_laser_shutter,
    _confirm_filter_wheel_slot,
    _confirm_filter_wheel_spectrum,
    confirm_move_xy,
    confirm_move_z,
    confirm_acquire,
    confirm_select_job,
)
from .errors import _default_error_check


@dataclass
class CommandProfile:
    """Complete recipe for a single command's backbone behaviour.

    Each field is either a callable or a tuning parameter. Callables
    follow the contract ``callable(client) → result dict``. Extra
    parameters are pre-bound with ``partial``. The command function
    binds ``client`` via lambda at call time.

    Attributes:
        pre_check_fn: Pre-flight check. ``callable(client) → result``.
            None to skip. Most commands use ``check_idle``.
        error_check_fn: Post-fire error check. ``callable(client) → result``.
            Defaults to ``_default_error_check``.
        confirm_fn: Readback confirmation. ``callable(client) → result``.
            None to skip confirmation.
        correct_fn: Custom correction strategy. ``callable(client) → result``.
            None uses built-in idle correction. Stubbed for future use.
        max_retries: Transient error retries inside the fire block.
        max_confirm_attempts: Confirm wrapper re-attempt ceiling.
        retry_backoff: Base delay in seconds between transient error retries.
            None for immediate retry (no delay).
        retry_escalate: If True, double the delay after each retry
            (exponential backoff: 0s, base, 2×base, 4×base, ...).
            If False, use a fixed delay. Ignored when retry_backoff is None.
    """
    pre_check_fn: callable = None
    error_check_fn: callable = _default_error_check
    confirm_fn: callable = None
    correct_fn: callable = None
    max_retries: int = 3
    max_confirm_attempts: int = 3
    retry_backoff: float = None
    retry_escalate: bool = False


# =============================================================================
# Standard pre-check: wait for scanner idle
# =============================================================================
#
# Most commands need the scanner idle before firing. The timeout and
# heartbeat vary by command type. These partials pre-bind those values;
# the command function binds `client` via lambda at call time.

# timeout == heartbeat → no heartbeat logs emitted before timeout
_idle_standard = partial(check_idle, timeout=30.0, heartbeat=30.0)
_idle_post_action = partial(check_idle, timeout=10.0, heartbeat=10.0)
_idle_long = partial(check_idle, timeout=60.0, heartbeat=30.0)
_idle_no_timeout = partial(check_idle, timeout=None, heartbeat=30.0)


# =============================================================================
# Job-level set commands
# =============================================================================

ZOOM = CommandProfile(
    pre_check_fn=_idle_standard,
    confirm_fn=_confirm_zoom,
)

SCAN_SPEED = CommandProfile(
    pre_check_fn=_idle_standard,
    confirm_fn=_confirm_scan_speed,
)

SCAN_RESONANT = CommandProfile(
    pre_check_fn=_idle_standard,
    confirm_fn=_confirm_scan_resonant,
)

SCAN_MODE = CommandProfile(
    pre_check_fn=_idle_standard,
    confirm_fn=_confirm_scan_mode,
)

SEQUENTIAL_MODE = CommandProfile(
    pre_check_fn=_idle_standard,
    confirm_fn=_confirm_sequential_mode,
)

SCAN_FIELD_ROTATION = CommandProfile(
    pre_check_fn=_idle_standard,
    confirm_fn=_confirm_scan_field_rotation,
)

IMAGE_FORMAT = CommandProfile(
    pre_check_fn=_idle_standard,
    confirm_fn=_confirm_image_format,
)

OBJECTIVE = CommandProfile(
    pre_check_fn=_idle_post_action,
    confirm_fn=confirm_objective,
    max_confirm_attempts=1,
)


# =============================================================================
# Z-stack commands
# =============================================================================

Z_STACK_DEFINITION = CommandProfile(
    pre_check_fn=_idle_standard,
    confirm_fn=_confirm_z_stack_definition,
)

Z_STACK_STEP_SIZE = CommandProfile(
    pre_check_fn=_idle_standard,
    confirm_fn=_confirm_z_stack_step_size,
)

Z_STACK_SIZE = CommandProfile(
    pre_check_fn=_idle_standard,
    confirm_fn=_confirm_z_stack_size,
)



# =============================================================================
# Per-setting commands
# =============================================================================

FRAME_ACCUMULATION = CommandProfile(
    pre_check_fn=_idle_standard,
    confirm_fn=_confirm_frame_accumulation,
)

FRAME_AVERAGE = CommandProfile(
    pre_check_fn=_idle_standard,
    confirm_fn=_confirm_frame_average,
)

LINE_ACCUMULATION = CommandProfile(
    pre_check_fn=_idle_standard,
    confirm_fn=_confirm_line_accumulation,
)

LINE_AVERAGE = CommandProfile(
    pre_check_fn=_idle_standard,
    confirm_fn=_confirm_line_average,
)


# =============================================================================
# Detector commands
# =============================================================================

DETECTOR_GAIN = CommandProfile(
    pre_check_fn=_idle_standard,
    confirm_fn=_confirm_detector_gain,
)


PINHOLE_AIRY = CommandProfile(
    pre_check_fn=_idle_standard,
    confirm_fn=_confirm_pinhole_airy,
)


# =============================================================================
# Laser commands
# =============================================================================

LASER_INTENSITY = CommandProfile(
    pre_check_fn=_idle_standard,
    confirm_fn=_confirm_laser_intensity,
)

LASER_SHUTTER = CommandProfile(
    pre_check_fn=_idle_standard,
    confirm_fn=_confirm_laser_shutter,
)



# =============================================================================
# Filter wheel commands
# =============================================================================

FILTER_WHEEL_SLOT = CommandProfile(
    pre_check_fn=_idle_standard,
    confirm_fn=_confirm_filter_wheel_slot,
)

FILTER_WHEEL_SPECTRUM = CommandProfile(
    pre_check_fn=_idle_standard,
    confirm_fn=_confirm_filter_wheel_spectrum,
)


# =============================================================================
# Stage movement
# =============================================================================

MOVE_XY = CommandProfile(
    pre_check_fn=_idle_post_action,
    confirm_fn=confirm_move_xy,
    max_confirm_attempts=1,
)

MOVE_Z = CommandProfile(
    pre_check_fn=_idle_post_action,
    confirm_fn=confirm_move_z,
    max_confirm_attempts=1,
)


# =============================================================================
# Acquisition and job selection
# =============================================================================

ACQUIRE = CommandProfile(
    pre_check_fn=_idle_no_timeout,
    confirm_fn=confirm_acquire,
    max_confirm_attempts=1,  # Acquisition confirms once (owns its polling)
)

SELECT_JOB = CommandProfile(
    pre_check_fn=None,  # Job switching doesn't need scanner idle
    confirm_fn=confirm_select_job,
    max_confirm_attempts=1,  # Job selection confirms once (owns its polling)
)

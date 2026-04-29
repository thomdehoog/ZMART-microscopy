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

Import restrictions: only ``prechecks``, ``confirmations``, ``errors``, and
stdlib. Nothing from ``core``, ``commands``, or ``utils``.
"""

from dataclasses import dataclass

from .utils import RECEIPT_TIMEOUT, CONFIRM_TIMEOUT  # noqa: F401 — re-exported
from .confirmations import (
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


@dataclass(frozen=True)
class CommandProfile:
    """Complete recipe for a single command's backbone behaviour.

    Each field is either a callable or a tuning parameter. Callables
    follow the contract ``callable(client) → result dict``. Extra
    parameters are pre-bound with ``partial``. The command function
    binds ``client`` via lambda at call time.

    Attributes:
        pre_check_fn: Pre-flight check. ``callable(client) → result``.
            None to skip.
        error_check_fn: Post-fire error check. ``callable(client) → result``.
            Defaults to ``_default_error_check``.
        confirm_fn: Readback confirmation. ``callable(client) → result``.
            None to skip confirmation. Declarative only — commands always
            override this with a target-bound partial at call time.
        correct_fn: Custom correction strategy. ``callable(client) → result``.
            None uses built-in idle correction. Stubbed for future use.
        max_retries: Transient error retries inside the fire block.
        max_confirm_attempts: Confirm wrapper re-attempt ceiling.
        retry_backoff: Base delay in seconds between transient error retries.
            None for immediate retry (no delay).
        retry_escalate: If True, double the delay after each retry
            (exponential backoff: 0s, base, 2×base, 4×base, ...).
            If False, use a fixed delay. Ignored when retry_backoff is None.
        skip_echo: If True, skip echo settlement polling after fire.
            Use for commands where a dedicated confirm_fn (e.g. scan
            status polling) is the authoritative completion signal and
            echo waiting is redundant overhead.
        receipt_timeout: Seconds for UpdateAwaitReceipt transport ACK.
            None uses the module-level RECEIPT_TIMEOUT default.
            Ignored when fire_async is True.
        fire_async: If True, use UpdateAsync instead of UpdateAwaitReceipt.
            Use for hardware commands (e.g. stage moves, acquisitions)
            where confirm_fn is the authoritative completion signal.
    """
    pre_check_fn: callable = None
    error_check_fn: callable = _default_error_check
    confirm_fn: callable = None
    correct_fn: callable = None
    max_retries: int = 3
    max_confirm_attempts: int = 3
    confirm_timeout: float = None  # Per-attempt confirm timeout (seconds). None uses CONFIRM_TIMEOUT.
    retry_backoff: float = None
    retry_escalate: bool = False
    skip_echo: bool = False
    receipt_timeout: float = None  # Per-profile UpdateAwaitReceipt deadline. None uses RECEIPT_TIMEOUT.
    fire_async: bool = False


# =============================================================================
# Job-level set commands
# =============================================================================

ZOOM = CommandProfile(
    confirm_fn=_confirm_zoom,
)

SCAN_SPEED = CommandProfile(
    confirm_fn=_confirm_scan_speed,
)

SCAN_RESONANT = CommandProfile(
    confirm_fn=_confirm_scan_resonant,
)

SCAN_MODE = CommandProfile(
    confirm_fn=_confirm_scan_mode,
)

SEQUENTIAL_MODE = CommandProfile(
    confirm_fn=_confirm_sequential_mode,
)

SCAN_FIELD_ROTATION = CommandProfile(
    confirm_fn=_confirm_scan_field_rotation,
)

IMAGE_FORMAT = CommandProfile(
    confirm_fn=_confirm_image_format,
)

OBJECTIVE = CommandProfile(
    confirm_fn=confirm_objective,
    max_confirm_attempts=1,
)


# =============================================================================
# Z-stack commands
# =============================================================================

Z_STACK_DEFINITION = CommandProfile(
    confirm_fn=_confirm_z_stack_definition,
)

Z_STACK_STEP_SIZE = CommandProfile(
    confirm_fn=_confirm_z_stack_step_size,
)

Z_STACK_SIZE = CommandProfile(
    confirm_fn=_confirm_z_stack_size,
)


# =============================================================================
# Per-setting commands
# =============================================================================

FRAME_ACCUMULATION = CommandProfile(
    confirm_fn=_confirm_frame_accumulation,
)

FRAME_AVERAGE = CommandProfile(
    confirm_fn=_confirm_frame_average,
)

LINE_ACCUMULATION = CommandProfile(
    confirm_fn=_confirm_line_accumulation,
)

LINE_AVERAGE = CommandProfile(
    confirm_fn=_confirm_line_average,
)


# =============================================================================
# Detector commands
# =============================================================================

DETECTOR_GAIN = CommandProfile(
    confirm_fn=_confirm_detector_gain,
)

PINHOLE_AIRY = CommandProfile(
    confirm_fn=_confirm_pinhole_airy,
)


# =============================================================================
# Laser commands
# =============================================================================

LASER_INTENSITY = CommandProfile(
    confirm_fn=_confirm_laser_intensity,
)

LASER_SHUTTER = CommandProfile(
    confirm_fn=_confirm_laser_shutter,
)


# =============================================================================
# Filter wheel commands
# =============================================================================

FILTER_WHEEL_SLOT = CommandProfile(
    confirm_fn=_confirm_filter_wheel_slot,
)

FILTER_WHEEL_SPECTRUM = CommandProfile(
    confirm_fn=_confirm_filter_wheel_spectrum,
)


# =============================================================================
# Stage movement
# =============================================================================

MOVE_XY = CommandProfile(
    confirm_fn=confirm_move_xy,
    error_check_fn=None,
    max_confirm_attempts=1,
    confirm_timeout=15.0,
    fire_async=True,
)

MOVE_Z = CommandProfile(
    confirm_fn=confirm_move_z,
    max_confirm_attempts=1,
)


# =============================================================================
# Acquisition and job selection
# =============================================================================

ACQUIRE = CommandProfile(
    confirm_fn=confirm_acquire,
    error_check_fn=None,
    max_confirm_attempts=3,
    skip_echo=True,
    fire_async=True,
)

ACQUIRE_SINGLE_IMAGE = CommandProfile(
    confirm_fn=confirm_acquire,
    error_check_fn=None,
    max_confirm_attempts=3,
    skip_echo=True,
    fire_async=True,
)

SELECT_JOB = CommandProfile(
    confirm_fn=confirm_select_job,
    max_confirm_attempts=1,
)

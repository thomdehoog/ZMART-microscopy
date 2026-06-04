"""
Per-command profiles.
=====================
Every command has a ``CommandProfile`` that is its complete recipe - all
pluggable callables and all retry/confirm settings in one place. Adding
a new command means adding a profile and a command function. Tuning a
command means editing its profile. Nothing else needs to change.

Command wrappers may accept explicit overrides for tests and unusual
hardware sessions, but their default tolerances, polling intervals, and
retry ceilings live here. This keeps machine-sensitive tuning out of
the wrapper logic.

All four callable fields follow the same rule: ``callable(client) -> result``.
Extra parameters are pre-bound with ``partial`` at profile definition
time. The command function always binds ``client`` via lambda - the same
pattern for every field, no exceptions.

**Two patterns cover all cases:**

    Pattern A - callable needs extra parameters: use partial to pre-bind.
    Pattern B - callable takes only client: assign directly.

Import restrictions: only ``prechecks``, ``confirmations``, ``errors``,
``utils``, and stdlib. Nothing from ``dispatch`` or ``commands``.
"""

from dataclasses import dataclass
from typing import Optional

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
class LogReaderProfile:
    """Low-level LAS X log-reader paths and freshness defaults."""

    lcs_log_path: str = r"C:\ProgramData\Leica Microsystems\LAS X\lcsCommand.log"
    msgbox_log_path: str = r"C:\ProgramData\Leica Microsystems\LAS X\MatrixScreener.log"
    current_window_s: float = 180.0
    max_age_s: Optional[float] = None


@dataclass(frozen=True)
class StateReaderProfile:
    """Profile-controlled backend selection for passive state reads.

    These modes are defaults for cold/status reads. Reads that decide command
    control flow - prechecks, early exits, command-parameterizing reads,
    confirmations, and post-write readbacks - must use the gated confirmation
    path, or explicitly pin API. Reads that produce persisted or foundational
    correctness artifacts, such as calibration geometry or canonical OME
    physical metadata, must also pin API. A fresh-by-age log value must never
    decide whether a command fires, how it is parameterized, whether it
    confirms, or what metadata/calibration is persisted.
    """

    both_log_grace_s: float = 0.25

    xy_mode: str = "api"
    xy_log_max_age_s: float = 1.0
    xy_timeout_s: float = 2.0

    job_settings_mode: str = "api"
    job_settings_log_max_age_s: float = 2.0
    job_settings_timeout_s: float = 2.0

    jobs_mode: str = "api"
    jobs_log_max_age_s: float = 2.0
    jobs_timeout_s: float = 2.0
    selected_job_confirm_source: str = "api"
    selected_job_log_prime_cluster: bool = False
    selected_job_log_confirm_timeout_s: float = 2.0
    selected_job_log_poll_timeout_s: float = 5.0
    selected_job_log_poll_interval_s: float = 0.1
    selected_job_log_cluster_max_age_s: Optional[float] = None

    hardware_info_mode: str = "api"
    hardware_info_log_max_age_s: float = 2.0
    hardware_info_timeout_s: float = 2.0

    scan_status_mode: str = "api"
    scan_status_log_max_age_s: float = 0.5
    scan_status_timeout_s: float = 2.0


LOG_READER = LogReaderProfile()
STATE_READERS = StateReaderProfile()


@dataclass(frozen=True)
class CommandProfile:
    """Complete recipe for a single command's backbone behaviour.

    Each field is either a callable or a tuning parameter. Callables
    follow the contract ``callable(client) -> result dict``. Extra
    parameters are pre-bound with ``partial``. The command function
    binds ``client`` via lambda at call time.

    Attributes:
        pre_check_fn: Pre-flight check. ``callable(client) -> result``.
            None to skip.
        error_check_fn: Post-fire error check. ``callable(client) -> result``.
            Defaults to ``_default_error_check``.
        confirm_fn: Readback confirmation. ``callable(client) -> result``.
            None to skip confirmation. Declarative only - commands always
            override this with a target-bound partial at call time.
        correct_fn: Custom correction strategy. ``callable(client) -> result``.
            None uses built-in idle correction. Stubbed for future use.
        max_retries: Transient error retries inside the fire block.
        max_confirm_attempts: Confirm wrapper re-attempt ceiling.
        refire_on_unconfirmed: If True, an unconfirmed readback causes
            the command to be sent again before the next confirmation
            attempt. If False, the dispatcher retries readback only.
            Leica setting commands normally re-fire because the API may
            accept a command while LAS X later settles to a different
            state, or an operator may change the setting manually.
        confirm_timeout: Per-attempt readback confirmation timeout.
            None lets the confirmation function use its own low-level
            default.
        confirm_tolerance: Numeric tolerance passed to target readback
            confirmations. None means exact-match or function default.
        poll_interval: Poll interval for command-specific long-running
            confirmations such as acquire and select-job.
        poll_timeout: Poll deadline for long-running confirmations.
            None means the confirmation waits until LAS X completes.
        start_timeout: Acquisition-start deadline before the acquire
            confirmation treats the command as failed.
        heartbeat_interval: Status-log cadence during long acquisitions.
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
        success_on_unconfirmed: If True, return success=True when all
            confirmation attempts are exhausted (confirmed=False).
            Use for commands where the fire is reliable but the reader
            may be slow (e.g. XY stage moves). Default False: exhausted
            confirmation returns success=False.
    """
    pre_check_fn: callable = None
    error_check_fn: callable = _default_error_check
    confirm_fn: callable = None
    correct_fn: callable = None
    max_retries: int = 3
    max_confirm_attempts: int = 3
    refire_on_unconfirmed: bool = True
    confirm_timeout: float = None  # Per-attempt confirm timeout (seconds). None uses CONFIRM_TIMEOUT.
    confirm_tolerance: float = None
    poll_interval: float = None
    poll_timeout: float = None
    start_timeout: float = None
    heartbeat_interval: float = None
    retry_backoff: float = None
    retry_escalate: bool = False
    skip_echo: bool = False
    receipt_timeout: float = None  # Per-profile UpdateAwaitReceipt deadline. None uses RECEIPT_TIMEOUT.
    fire_async: bool = False
    success_on_unconfirmed: bool = False


def _leica_setting_profile(confirm_fn, **overrides):
    """Profile for Leica setting updates with occasionally stale readback.

    Setting commands get three 5-second readback windows. If a readback
    window does not confirm the requested state, the command is sent
    again before the next readback. If LAS X still reports another
    state, the result is ``success=True, confirmed=False`` so the larger
    acquisition workflow can continue while the logs show the mismatch.
    """
    return CommandProfile(
        confirm_fn=confirm_fn,
        max_confirm_attempts=3,
        confirm_timeout=5.0,
        success_on_unconfirmed=True,
        **overrides,
    )


# =============================================================================
# Job-level set commands
# =============================================================================

ZOOM = _leica_setting_profile(
    _confirm_zoom,
    confirm_tolerance=0.1,
)

SCAN_SPEED = _leica_setting_profile(
    _confirm_scan_speed,
)

SCAN_RESONANT = _leica_setting_profile(
    _confirm_scan_resonant,
)

SCAN_MODE = _leica_setting_profile(
    _confirm_scan_mode,
)

SEQUENTIAL_MODE = _leica_setting_profile(
    _confirm_sequential_mode,
)

SCAN_FIELD_ROTATION = _leica_setting_profile(
    _confirm_scan_field_rotation,
    confirm_tolerance=0.5,
)

IMAGE_FORMAT = _leica_setting_profile(
    _confirm_image_format,
)

OBJECTIVE = CommandProfile(
    confirm_fn=confirm_objective,
    max_confirm_attempts=1,
    confirm_timeout=10.0,
    success_on_unconfirmed=True,
)


# =============================================================================
# Z-stack commands
# =============================================================================

Z_STACK_DEFINITION = _leica_setting_profile(
    _confirm_z_stack_definition,
    confirm_tolerance=1.0,
)

Z_STACK_STEP_SIZE = _leica_setting_profile(
    _confirm_z_stack_step_size,
    confirm_tolerance=0.5,
)

Z_STACK_SIZE = _leica_setting_profile(
    _confirm_z_stack_size,
    confirm_tolerance=1.5,
)


# =============================================================================
# Per-setting commands
# =============================================================================

FRAME_ACCUMULATION = _leica_setting_profile(
    _confirm_frame_accumulation,
)

FRAME_AVERAGE = _leica_setting_profile(
    _confirm_frame_average,
)

LINE_ACCUMULATION = _leica_setting_profile(
    _confirm_line_accumulation,
)

LINE_AVERAGE = _leica_setting_profile(
    _confirm_line_average,
)


# =============================================================================
# Detector commands
# =============================================================================

DETECTOR_GAIN = _leica_setting_profile(
    _confirm_detector_gain,
    confirm_tolerance=1.0,
)

PINHOLE_AIRY = _leica_setting_profile(
    _confirm_pinhole_airy,
    confirm_tolerance=0.05,
)


# =============================================================================
# Laser commands
# =============================================================================

LASER_INTENSITY = _leica_setting_profile(
    _confirm_laser_intensity,
    confirm_tolerance=0.005,
)

LASER_SHUTTER = _leica_setting_profile(
    _confirm_laser_shutter,
)


# =============================================================================
# Filter wheel commands
# =============================================================================

FILTER_WHEEL_SLOT = _leica_setting_profile(
    _confirm_filter_wheel_slot,
)

FILTER_WHEEL_SPECTRUM = _leica_setting_profile(
    _confirm_filter_wheel_spectrum,
    confirm_tolerance=1.0,
)


# =============================================================================
# Stage movement
# =============================================================================

MOVE_XY = CommandProfile(
    confirm_fn=confirm_move_xy,
    error_check_fn=None,
    max_confirm_attempts=3,
    refire_on_unconfirmed=False,
    confirm_timeout=15.0,
    confirm_tolerance=20.0,
    fire_async=True,
    success_on_unconfirmed=True,
)

MOVE_Z = CommandProfile(
    confirm_fn=confirm_move_z,
    max_confirm_attempts=1,
    confirm_tolerance=1.0,
)


# =============================================================================
# Acquisition and job selection
# =============================================================================

ACQUIRE = CommandProfile(
    confirm_fn=confirm_acquire,
    error_check_fn=None,
    max_confirm_attempts=1,
    refire_on_unconfirmed=False,
    poll_interval=0.1,
    poll_timeout=None,
    start_timeout=15.0,
    heartbeat_interval=30.0,
    skip_echo=True,
    fire_async=True,
)

ACQUIRE_SINGLE_IMAGE = CommandProfile(
    confirm_fn=confirm_acquire,
    error_check_fn=None,
    max_confirm_attempts=1,
    refire_on_unconfirmed=False,
    poll_interval=0.1,
    poll_timeout=None,
    start_timeout=15.0,
    heartbeat_interval=30.0,
    skip_echo=True,
    fire_async=True,
)

SELECT_JOB = CommandProfile(
    confirm_fn=confirm_select_job,
    max_confirm_attempts=3,
    poll_interval=0.01,
    poll_timeout=5.0,
)

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

Both callable fields follow the same rule: ``callable(client) -> result``.
Extra parameters are pre-bound with ``partial`` at profile definition
time. The command function always binds ``client`` via lambda - the same
pattern for every field, no exceptions.

**Two patterns cover all cases:**

    Pattern A - callable needs extra parameters: use partial to pre-bind.
    Pattern B - callable takes only client: assign directly.

Import restrictions: command prechecks, runtime errors/utilities, and stdlib.
Nothing from dispatch, confirmations, or command wrappers. (Confirm functions
are bound by the command wrappers themselves, with the target value baked in —
a profile cannot know the target, so it never carries a confirm callable.)
"""

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from ..commands.errors import _default_error_check
from ..commands.prechecks import check_idle
from ..utils import CONFIRM_POLL_S, RECEIPT_TIMEOUT


@dataclass(frozen=True)
class LogReaderProfile:
    """Low-level LAS X log-reader paths and freshness defaults."""

    lcs_log_path: str = r"C:\ProgramData\Leica Microsystems\LAS X\lcsCommand.log"
    msgbox_log_path: str = r"C:\ProgramData\Leica Microsystems\LAS X\MatrixScreener.log"
    current_window_s: float = 180.0
    max_age_s: float | None = None


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

    hybrid_log_grace_s: float = 0.25

    xy_mode: str = "hybrid"
    xy_log_max_age_s: float = 1.0
    xy_timeout_s: float = 2.0

    job_settings_mode: str = "hybrid"
    job_settings_log_max_age_s: float = 2.0
    job_settings_timeout_s: float = 2.0

    # jobs is API-pinned, NOT hybrid: the log stream only reports the ACTIVE
    # job, so its list is incomplete (a job not re-dumped this session is
    # absent) — only the API enumerates the full job list. Confirmed on the
    # bench (2026-07-06). selected_job (which job is active) stays hybrid: that
    # is exactly what the log can see.
    jobs_mode: str = "api"
    jobs_log_max_age_s: float = 2.0
    jobs_timeout_s: float = 2.0

    selected_job_mode: str = "hybrid"
    selected_job_log_max_age_s: float = 2.0
    selected_job_timeout_s: float = 2.0
    # Selected-job confirmation source: "api" | "log" | "hybrid".
    # hybrid races the api leg (transition-admissible: a stale API readback
    # cannot witness a transition to a target it already read pre-command)
    # against the log leg (post-command CurrentBlock event). The race runs for
    # one confirm window (the shared CONFIRM_POLL_S), so the whole confirmation
    # is the uniform 3x3: CONFIRM_POLL_S per attempt, max_confirm_attempts
    # attempts, re-fire between — same as every other command.
    # Default hybrid: the api confirm is measured-wrong on the real scope
    # (stale 15 s+, wrong job) and log-only is insufficient on the
    # simulator; hybrid fits both without environment detection.
    selected_job_confirm_source: str = "hybrid"
    selected_job_log_prime_cluster: bool = False
    selected_job_log_confirm_timeout_s: float = 2.0
    selected_job_log_poll_timeout_s: float = 5.0
    selected_job_log_poll_interval_s: float = 0.1
    selected_job_log_cluster_max_age_s: float | None = None

    hardware_info_mode: str = "hybrid"
    hardware_info_log_max_age_s: float = 2.0
    hardware_info_timeout_s: float = 2.0

    scan_status_mode: str = "hybrid"
    scan_status_log_max_age_s: float = 0.5
    scan_status_timeout_s: float = 2.0


LOG_READER = LogReaderProfile()
STATE_READERS = StateReaderProfile()


@dataclass(frozen=True)
class LasxApiProfile:
    """Connection-level LAS X API settings.

    ``DelayInMilliseconds`` is Leica's client-side pacing knob. Keeping it in
    the profile makes the default explicit and keeps hardware-specific API
    timing out of scripts and workflows. ``runtime_root`` is the LAS X-installed
    NavigatorExpert add-in directory that contains the CAM API assemblies.
    """

    delay_ms: int | None = 250
    runtime_root: str = r"C:\Program Files\Leica Microsystems CMS GmbH\LAS X\AddIns\NavigatorExpert"


LASX_API = LasxApiProfile()


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
        max_retries: Transient error retries inside the fire block.
        max_confirm_attempts: Confirm wrapper re-attempt ceiling.
        refire_on_unconfirmed: If True, an unconfirmed readback causes
            the command to be sent again before the next confirmation
            attempt. If False, the dispatcher retries readback only.
            Leica setting commands normally re-fire because the API may
            accept a command while LAS X later settles to a different
            state, or an operator may change the setting manually.
        confirm_poll_s: Per-attempt readback poll window (seconds). NOT a
            timeout - the readback is polled for this long, then the command
            re-fires and polls again up to ``max_confirm_attempts``; exhaustion
            returns unconfirmed, never a hard fail. Every confirm function
            defaults to the shared ``CONFIRM_POLL_S`` on its own; this field
            exists for the commands that read the window explicitly
            (``select_job``'s confirmation legs, the resonant-scan error
            check). It matches ``CONFIRM_POLL_S`` on every shipped profile.
        confirm_tolerance: Numeric tolerance passed to target readback
            confirmations. None means exact-match or function default.
        poll_interval: Poll interval for command-specific long-running
            confirmations such as acquire and select-job.
        poll_timeout: Poll deadline for long-running confirmations.
            None means the confirmation waits until LAS X completes.
        start_timeout: Acquisition-start deadline before the acquire
            confirmation treats the command as failed.
        heartbeat_interval: Status-log cadence during long acquisitions.
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
        success_on_unconfirmed: If True (the default), return success=True with
            confirmed=False when all confirmation attempts are exhausted. The
            command never hard-fails on an unconfirmed readback; only transport
            failure and an echo error-check rejection return success=False. Set
            False only for a command that must hard-fail on unconfirmed - none do.
    """

    pre_check_fn: Callable[..., dict] | None = None
    error_check_fn: Callable[..., dict] | None = _default_error_check
    max_retries: int = 3
    max_confirm_attempts: int = 3
    refire_on_unconfirmed: bool = True
    confirm_poll_s: float = CONFIRM_POLL_S  # Per-attempt readback poll window (s).
    confirm_tolerance: float | None = None
    poll_interval: float | None = None
    poll_timeout: float | None = None
    start_timeout: float | None = None
    heartbeat_interval: float | None = None
    skip_echo: bool = False
    receipt_timeout: float = RECEIPT_TIMEOUT  # UpdateAwaitReceipt ACK deadline (s).
    fire_async: bool = False
    success_on_unconfirmed: bool = True

    def __post_init__(self):
        # Async fire blanks the echo, so an echo-based error check would read a
        # cleared echo and report a meaningless success. Couple the two fields.
        if self.fire_async and self.error_check_fn is not None:
            raise ValueError("fire_async=True requires error_check_fn=None")
        # A single confirm window has no 'next attempt' to re-fire before, so a
        # requested re-fire could never run. Forbid the incoherent combination.
        if self.max_confirm_attempts == 1 and self.refire_on_unconfirmed:
            raise ValueError("max_confirm_attempts==1 requires refire_on_unconfirmed=False")


# =============================================================================
# Setting commands (zoom, scan, z-stack, detector, laser, filter wheel)
# =============================================================================
# Every setting command shares the ``CommandProfile`` default posture: three
# 3-second readback poll windows, a re-fire before each retry window, and a
# ``success=True, confirmed=False`` result if LAS X still reports another
# state after all windows — the larger acquisition workflow continues while
# the logs show the mismatch. The only per-command tuning is the readback
# tolerance for continuous values; the matching confirm function is bound by
# the command wrapper itself, with the target value baked in.

ZOOM = CommandProfile(confirm_tolerance=0.1)

SCAN_SPEED = CommandProfile()

SCAN_RESONANT = CommandProfile()

SCAN_MODE = CommandProfile()

SEQUENTIAL_MODE = CommandProfile()

SCAN_FIELD_ROTATION = CommandProfile(confirm_tolerance=0.5)

IMAGE_FORMAT = CommandProfile()

OBJECTIVE = CommandProfile(
    pre_check_fn=partial(check_idle, timeout=None),
    # Uniform posture: 3 confirm windows, re-fire between them, unconfirmed-not-
    # fail. A slow turret change is absorbed by the idle-wait before each re-fire.
)

Z_STACK_DEFINITION = CommandProfile(confirm_tolerance=1.0)

Z_STACK_STEP_SIZE = CommandProfile(confirm_tolerance=0.5)

Z_STACK_SIZE = CommandProfile(confirm_tolerance=1.5)

FRAME_ACCUMULATION = CommandProfile()

FRAME_AVERAGE = CommandProfile()

LINE_ACCUMULATION = CommandProfile()

LINE_AVERAGE = CommandProfile()

DETECTOR_GAIN = CommandProfile(confirm_tolerance=1.0)

PINHOLE_AIRY = CommandProfile(confirm_tolerance=0.05)

LASER_INTENSITY = CommandProfile(confirm_tolerance=0.005)

LASER_SHUTTER = CommandProfile()

FILTER_WHEEL_SLOT = CommandProfile()

FILTER_WHEEL_SPECTRUM = CommandProfile(confirm_tolerance=1.0)


# =============================================================================
# Stage movement
# =============================================================================

MOVE_XY = CommandProfile(
    pre_check_fn=partial(check_idle, timeout=None),
    error_check_fn=None,  # async fire blanks the echo; nothing to error-check
    confirm_tolerance=20.0,
    fire_async=True,
    # Uniform posture: re-fires an unconfirmed absolute move (idempotent) after
    # waiting for idle; unconfirmed-not-fail like every other command.
)

MOVE_Z = CommandProfile(
    pre_check_fn=partial(check_idle, timeout=None),
    confirm_tolerance=1.0,
    # Uniform posture (was single-attempt hard-fail): 3 windows, re-fire,
    # unconfirmed-not-fail - same as MOVE_XY.
)


# =============================================================================
# Acquisition and job selection
# =============================================================================

ACQUIRE = CommandProfile(
    pre_check_fn=partial(check_idle, timeout=None),
    error_check_fn=None,
    # ACQUIRE is the one command that must never re-send: re-firing starts a
    # second acquisition (duplicate data). It declines retry on BOTH axes -
    # max_retries=0 (fire loop) and refire_on_unconfirmed=False (confirm loop).
    # It still returns unconfirmed rather than failing; save()'s freshness/grid
    # check is the real gate against acting on missing data.
    max_retries=0,
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
    pre_check_fn=partial(check_idle, timeout=None),
    # select_job's confirmation legs are built per call by
    # confirm_select_job.select_job_confirm_legs (api / log / hybrid policy from
    # StateReaderProfile.selected_job_confirm_source), not by this profile.
    # Same 3x3 posture as every other command: max_confirm_attempts confirm
    # windows of confirm_poll_s seconds each (the shared CONFIRM_POLL_S), re-fire
    # between, unconfirmed-not-fail. No bespoke poll_timeout — the window comes
    # from the profile like every setting command.
    max_confirm_attempts=3,
    poll_interval=0.01,
)

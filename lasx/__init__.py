"""
LASX Driver v6.0.0
===================
Python driver for the Leica STELLARIS confocal microscope via the LAS X
Python API.

Package layout::

    lasx/
    ├── __init__.py    ← you are here (public API)
    ├── util.py        ← helpers: _make_log_entry, _make_timing,
    │                     parse_format, etc.
    ├── errors.py      ← error classification + _check_api_error +
    │                     _default_error_check adapter
    ├── limits.py      ← stage safety limits
    ├── readers.py     ← get_scan_status, ping, get_jobs,
    │                     get_job_settings, get_hardware_info, get_xy
    ├── settings.py    ← make_changeable_copy
    ├── checks.py      ← pre-flight check functions (check_idle)
    ├── confirm.py     ← readback confirmation functions,
    │                     confirm_acquire, confirm_select_job
    ├── core.py        ← _fire_with_receipt, _fire_block,
    │                     confirm_and_fire
    ├── profiles.py    ← CommandProfile dataclass + per-command profiles
    └── commands.py    ← set_*, move_*, acquire, select_job

Dependency flow (strict DAG — no cycles)::

    util                          ← stdlib only
    errors                        ← util
    limits                        ← stdlib only
    readers                       ← stdlib only
    settings                      ← util
    checks                        ← readers, util
    confirm                       ← readers, settings, util
    core                          ← errors, util
    profiles                      ← checks, confirm, errors
    commands                      ← core, profiles, confirm, errors,
                                     limits, readers, util
"""

__version__ = "6.0.0"

__all__ = [
    # version
    "__version__", "log",
    # util
    "_safe_float", "_hw_get", "parse_format", "format_to_str",
    "_make_timing", "_make_log_entry",
    # errors
    "_is_transient_error", "_check_api_error", "_default_error_check",
    "_PERMANENT_PATTERNS", "_TRANSIENT_PATTERNS",
    # limits
    "_stage_limits", "set_stage_limits", "get_stage_limits",
    "_check_xy_limits", "_check_z_limits",
    # readers
    "get_scan_status", "ping", "get_job_settings", "get_hardware_info",
    "get_xy", "get_jobs", "get_job_by_name", "get_selected_job",
    # settings
    "make_changeable_copy",
    # checks
    "check_idle",
    # confirm (public readback helper only; _confirm_* are private)
    "_readback",
    # core
    "confirm_and_fire", "_fire_with_receipt",
    # commands
    "set_zoom", "set_scan_speed", "set_scan_resonant", "set_scan_mode",
    "set_sequential_mode", "set_scan_field_rotation", "set_image_format",
    "set_objective", "set_z_stack_definition", "set_z_stack_step_size",
    "set_z_stack_size", "set_time_definition",
    "set_frame_accumulation", "set_frame_average",
    "set_line_accumulation", "set_line_average",
    "set_pinhole_airy", "set_detector_gain", "set_detector_active",
    "set_laser_intensity", "set_laser_shutter", "add_or_remove_laser_line",
    "set_filter_wheel_slot", "set_filter_wheel_spectrum",
    "move_xy", "move_z", "acquire", "select_job",
]

# ── Utilities ────────────────────────────────────────────────────────
from .util import (
    _safe_float,
    _hw_get,
    parse_format,
    format_to_str,
    _make_timing,
    _make_log_entry,
)

# ── Error classification ─────────────────────────────────────────────
from .errors import (
    _is_transient_error,
    _check_api_error,
    _default_error_check,
    _PERMANENT_PATTERNS,
    _TRANSIENT_PATTERNS,
)

# ── Stage limits ─────────────────────────────────────────────────────
from .limits import (
    _stage_limits,
    set_stage_limits,
    get_stage_limits,
    _check_xy_limits,
    _check_z_limits,
)

# ── Read functions ───────────────────────────────────────────────────
from .readers import (
    get_scan_status,
    ping,
    get_job_settings,
    get_hardware_info,
    get_xy,
    get_jobs,
    get_job_by_name,
    get_selected_job,
)

# ── Settings parsing ────────────────────────────────────────────────
from .settings import make_changeable_copy

# ── Pre-flight checks ───────────────────────────────────────────────
from .checks import check_idle

# ── Confirm (public readback helper only) ────────────────────────────
from .confirm import _readback

# ── Core dispatch ───────────────────────────────────────────────────
from .core import (
    _fire_with_receipt,
    confirm_and_fire,
)

# ── Command wrappers ────────────────────────────────────────────────
from .commands import (
    set_zoom,
    set_scan_speed,
    set_scan_resonant,
    set_scan_mode,
    set_sequential_mode,
    set_scan_field_rotation,
    set_image_format,
    set_objective,
    set_z_stack_definition,
    set_z_stack_step_size,
    set_z_stack_size,
    set_time_definition,
    set_frame_accumulation,
    set_frame_average,
    set_line_accumulation,
    set_line_average,
    set_pinhole_airy,
    set_detector_gain,
    set_detector_active,
    set_laser_intensity,
    set_laser_shutter,
    add_or_remove_laser_line,
    set_filter_wheel_slot,
    set_filter_wheel_spectrum,
    move_xy,
    move_z,
    acquire,
    select_job,
)

# ── Logging ─────────────────────────────────────────────────────────
import logging
log = logging.getLogger(__name__)

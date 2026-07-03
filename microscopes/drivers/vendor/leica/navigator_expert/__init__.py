# ruff: noqa: E402,I001,F401
"""Navigator Expert driver for Leica LAS X.

Package layout::

    navigator_expert/
    - commands/     command wrappers, dispatch, confirmation logic
    - runtime/      profiles, session helpers, errors, shared utilities
    - state_readers/ API/log/hybrid state readers
    - scanfields/   LAS X scan-field files, parsing, planning, strip/restore
    - acquisition/  acquire-only capture, LAS X file export, OME fixes, save
    - stage/        stage limits, backlash-aware movement, stage config
    - experimental/ galvo-pan LRP edits (used by move_galvo_to_pixel)
"""

__version__ = "6.0.0"

__all__ = [
    # version
    "__version__",
    "log",
    # config
    "RECEIPT_TIMEOUT",
    "CONFIRM_TIMEOUT",
    "PAN_LIMIT",
    "GALVO_FIELD_FRACTION",
    "pan_scale_um_from_base_fov",
    # utils
    "_safe_float",
    "_hw_get",
    "parse_format",
    "format_to_str",
    "_make_timing",
    "_make_log_entry",
    "parse_tile_geometry",
    # errors
    "_is_transient_error",
    "_check_api_error",
    "_default_error_check",
    "_PERMANENT_PATTERNS",
    "_TRANSIENT_PATTERNS",
    # limits
    "_stage_limits",
    "set_stage_limits",
    "get_stage_limits",
    "apply_stage_limits_from_config",
    "_check_xy_limits",
    "_check_z_limits",
    # readers
    "Reading",
    "get_scan_status",
    "ping",
    "get_job_settings",
    "get_hardware_info",
    "get_xy",
    "read_zwide_um",
    "get_jobs",
    "get_job_by_name",
    "get_selected_job",
    "get_fov",
    "get_base_fov",
    "get_lasx_settings",
    "get_pending_dialog",
    # OME metadata checks/fixes
    "extract_wavelength_from_id",
    "check_ome_xml_bytes",
    "check_ome_tiff",
    "check_ome_xml_file",
    "fix_ome_xml_bytes",
    "fix_ome_tiff",
    "fix_ome_xml_file",
    # settings
    "make_changeable_copy",
    # prechecks
    "check_idle",
    # confirmations (public readback helper only; _confirm_* are private)
    "_readback",
    # runtime/dispatch
    "confirm_and_fire",
    "_fire_with_receipt",
    # commands
    "set_zoom",
    "set_scan_speed",
    "set_scan_resonant",
    "set_scan_mode",
    "set_sequential_mode",
    "set_scan_field_rotation",
    "set_image_format",
    "set_objective",
    "set_z_stack_definition",
    "set_z_stack_step_size",
    "set_z_stack_size",
    "set_frame_accumulation",
    "set_frame_average",
    "set_line_accumulation",
    "set_line_average",
    "set_pinhole_airy",
    "set_detector_gain",
    "set_laser_intensity",
    "set_laser_shutter",
    "set_filter_wheel_slot",
    "set_filter_wheel_spectrum",
    "move_xy",
    "move_galvo_to_pixel",
    "move_z",
    "acquire",
    "select_job",
    # scan fields
    "find_scanning_templates_dir",
    "save_experiment",
    "load_experiment",
    "strip_template",
    "restore_template",
    "get_template_state",
    "strip_template_in_place",
    "apply_lrp_change",
    "reorder_jobs",
    "save_and_read_lrp",
    # position parsers/planning
    "parse_lrp",
    "diff_lrp",
    "parse_scan_positions",
    "get_master_attrs",
    "get_rois",
    "parse_acquisition_positions",
    "parse_base_grid",
    "parse_focus_points",
    "parse_rgn_geometries",
    "parse_rgn_tile_colors",
    "parse_matrix_settings",
    "plan_tiles_from_geometries",
    # experimental galvo-pan LRP edits (used by move_galvo_to_pixel)
    "galvo_pan_for_pixel",
    "roi_translation_to_pan",
    "lrp_set_pan",
    "lrp_verify_pan",
    "lrp_get_pan",
    # acquisition file handling
    "read_relative_path",
    "parse_lasx_filename",
    "wait_all_stable",
    # session helpers
    "connect_python_client",
    "configure_lasx_api_delay",
    "require_canonical_scan_orientation",
    "LIMITS_SCHEMA_VERSION",
    "CALIBRATION_SCHEMA_VERSION",
    "LIMITS_SOURCE_DEFAULTS",
    "LIMITS_SOURCE_BOUNDARY_MARKERS",
    "LIMITS_SOURCE_CFG_FALLBACK",
    "LIMITS_SOURCE_SCAN_FIELD",
    "LIMITS_SOURCE_MIGRATION",
    "LIMITS_SOURCES",
    "current_stage_limits_path",
    "default_stage_limits_path",
    "load_stage_config",
    "write_stage_limits_config",
    # acquisition workflow
    "AcquisitionResult",
    "PlaneIndex",
    "PositionIndex",
    "PlaneSource",
    "ChannelMetadata",
    "AcquisitionMetadata",
    "VendorMetadataSource",
    "SavedAcquisition",
    "native_autosave_base_folder",
    "native_autosave_enabled",
    "active_save_exporter",
    "save_source_root",
    "save",
]

# -- package self-bootstrap
# navigator_expert depends on shared.output_layout under microscopes/.
# Callers usually put microscopes/drivers/vendor/leica/ on sys.path; adding
# both roots here keeps subprocesses and scripts resilient when they import the
# driver first.
import sys as _sys
from pathlib import Path as _Path

_here = _Path(__file__).resolve()
_leica_root = str(_here.parents[1])
_microscopes_root = str(_here.parents[4])
for _path in (_microscopes_root, _leica_root):
    if _path not in _sys.path:
        _sys.path.insert(0, _path)
del _sys, _Path, _here, _leica_root, _microscopes_root, _path

# -- runtime/ + commands/ - shared runtime helpers and command mechanics
from .runtime.utils import (
    _safe_float,
    _hw_get,
    parse_format,
    format_to_str,
    _make_timing,
    _make_log_entry,
    parse_tile_geometry,
    RECEIPT_TIMEOUT,
    CONFIRM_TIMEOUT,
    PAN_LIMIT,
    GALVO_FIELD_FRACTION,
    pan_scale_um_from_base_fov,
)
from .runtime.errors import (
    _is_transient_error,
    _check_api_error,
    _default_error_check,
    _PERMANENT_PATTERNS,
    _TRANSIENT_PATTERNS,
)
from .state_readers import (
    Reading,
    get_scan_status,
    ping,
    get_job_settings,
    get_hardware_info,
    get_xy,
    read_zwide_um,
    get_jobs,
    get_job_by_name,
    get_selected_job,
    get_fov,
    get_base_fov,
    get_lasx_settings,
    get_pending_dialog,
)
from .commands.settings import make_changeable_copy
from .commands.prechecks import check_idle
from .commands.confirmations import _readback
from .commands.dispatch import _fire_with_receipt, confirm_and_fire
from .commands.commands import (
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
    set_frame_accumulation,
    set_frame_average,
    set_line_accumulation,
    set_line_average,
    set_pinhole_airy,
    set_detector_gain,
    set_laser_intensity,
    set_laser_shutter,
    set_filter_wheel_slot,
    set_filter_wheel_spectrum,
    move_xy,
    move_galvo_to_pixel,
    move_z,
    select_job,
)
from .runtime.session import (
    connect_python_client,
    configure_lasx_api_delay,
    require_canonical_scan_orientation,
)

# -- stage/ - stage safety + movement
from .stage.limits import (
    _stage_limits,
    set_stage_limits,
    get_stage_limits,
    apply_stage_limits_from_config,
    _check_xy_limits,
    _check_z_limits,
)
from .stage.movement import correct_backlash, move_xy_with_backlash
from .stage.config import (
    LIMITS_SCHEMA_VERSION,
    CALIBRATION_SCHEMA_VERSION,
    LIMITS_SOURCE_DEFAULTS,
    LIMITS_SOURCE_BOUNDARY_MARKERS,
    LIMITS_SOURCE_CFG_FALLBACK,
    LIMITS_SOURCE_SCAN_FIELD,
    LIMITS_SOURCE_MIGRATION,
    LIMITS_SOURCES,
    current_path as current_stage_limits_path,
    defaults_path as default_stage_limits_path,
    load as load_stage_config,
    write_limits as write_stage_limits_config,
)

# -- scanfields/ - LAS X scan-field file operations and parsing
from .scanfields.files import (
    find_scanning_templates_dir,
    save_experiment,
    load_experiment,
    get_template_state,
    save_and_read_lrp,
)
from .scanfields.strip_restore import strip_template, restore_template
from .scanfields.strip_restore import strip_template_in_place
from .scanfields.transaction import apply_lrp_change, reorder_jobs
from .scanfields.parsers import (
    parse_lrp,
    diff_lrp,
    parse_scan_positions,
    parse_acquisition_positions,
    parse_base_grid,
    parse_focus_points,
    parse_rgn_geometries,
    parse_rgn_tile_colors,
    parse_matrix_settings,
    get_master_attrs,
    get_rois,
)
from .scanfields.planning import plan_tiles_from_geometries

# -- acquisition/ - capture, file arrival, and save handling
from .acquisition.ome_vendor_fix import (
    extract_wavelength_from_id,
    check_ome_xml_bytes,
    check_ome_tiff,
    check_ome_xml_file,
    fix_ome_xml_bytes,
    fix_ome_tiff,
    fix_ome_xml_file,
)
from .acquisition.files import (
    read_relative_path,
    parse_lasx_filename,
    wait_all_stable,
)
from .acquisition.capture import AcquisitionResult, acquire
from .acquisition.product import (
    AcquisitionMetadata,
    ChannelMetadata,
    PlaneIndex,
    PlaneSource,
    PositionIndex,
    SavedAcquisition,
    VendorMetadataSource,
)
from .acquisition.lasx_native_autosave import (
    native_autosave_base_folder,
    native_autosave_enabled,
)
from .acquisition.save import active_save_exporter, save_source_root, save

# -- experimental/lrp_edits/ - galvo-pan LRP edits (used by move_galvo_to_pixel)
from .experimental.lrp_edits.pan import (
    galvo_pan_for_pixel,
    lrp_get_pan,
    lrp_set_pan,
    lrp_verify_pan,
    roi_translation_to_pan,
)

# -- logging
import logging

log = logging.getLogger(__name__)

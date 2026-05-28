"""
Navigator Expert Driver
=======================
Python driver for the Leica STELLARIS confocal microscope via the LAS X
Python API.

Package layout::

    navigator_expert/driver/
    - core/         raw LAS X commands, readers, confirmations, profiles
    - templates/    LRP/XML/RGN parsing, strip/restore, transactions
    - acquisition/  capture, LAS X file arrival, OME fixes, acquire-and-save
    - stage/        stage limits, backlash-aware movement, stage config
    - experimental/ LRP mutation helpers without live-state readback
"""

__version__ = "6.0.0"

__all__ = [
    # version
    "__version__", "log",
    # config
    "RECEIPT_TIMEOUT", "CONFIRM_TIMEOUT",
    "PAN_LIMIT", "GALVO_FIELD_FRACTION", "pan_scale_um_from_base_fov",
    # utils
    "_safe_float", "_hw_get", "parse_format", "format_to_str",
    "_make_timing", "_make_log_entry", "parse_tile_geometry",
    # errors
    "_is_transient_error", "_check_api_error", "_default_error_check",
    "_PERMANENT_PATTERNS", "_TRANSIENT_PATTERNS",
    # limits
    "_stage_limits", "set_stage_limits", "get_stage_limits",
    "apply_stage_limits_from_config",
    "_check_xy_limits", "_check_z_limits",
    # readers
    "get_scan_status", "ping", "get_job_settings", "get_hardware_info",
    "get_xy", "read_zwide_um",
    "get_jobs", "get_job_by_name", "get_selected_job",
    "get_fov", "get_base_fov", "get_lasx_settings",
    # OME metadata checks/fixes
    "extract_wavelength_from_id",
    "check_ome_xml_bytes", "check_ome_tiff", "check_ome_xml_file",
    "fix_ome_xml_bytes", "fix_ome_tiff", "fix_ome_xml_file",
    "update_ome_tiff_filename", "update_ome_xml_filename",
    # settings
    "make_changeable_copy",
    # prechecks
    "check_idle",
    # confirmations (public readback helper only; _confirm_* are private)
    "_readback",
    # core
    "confirm_and_fire", "_fire_with_receipt",
    # commands
    "set_zoom", "set_scan_speed", "set_scan_resonant", "set_scan_mode",
    "set_sequential_mode", "set_scan_field_rotation", "set_image_format",
    "set_objective", "set_z_stack_definition", "set_z_stack_step_size",
    "set_z_stack_size",
    "set_frame_accumulation", "set_frame_average",
    "set_line_accumulation", "set_line_average",
    "set_pinhole_airy", "set_detector_gain",
    "set_laser_intensity", "set_laser_shutter",
    "set_filter_wheel_slot", "set_filter_wheel_spectrum",
    "move_xy", "move_galvo_to_pixel",
    "move_z", "acquire", "acquire_single_image", "select_job",
    # templates
    "find_scanning_templates_dir", "save_experiment", "load_experiment",
    "strip_template", "restore_template", "get_template_state",
    "apply_lrp_change", "reorder_jobs", "save_and_read_lrp",
    # template parsers
    "parse_lrp", "diff_lrp", "parse_template_positions",
    "get_master_attrs", "get_rois",
    "parse_acquisition_positions", "parse_base_grid", "parse_focus_points",
    "parse_rgn_geometries", "parse_rgn_tile_colors", "parse_matrix_settings",
    # experimental LRP edits (general)
    "lrp_set_line_average", "lrp_verify_line_average",
    "lrp_set_line_accumulation", "lrp_verify_line_accumulation",
    "lrp_set_frame_average", "lrp_verify_frame_average",
    "lrp_set_frame_accumulation", "lrp_verify_frame_accumulation",
    "lrp_set_scan_mode", "lrp_verify_scan_mode",
    "SEQUENTIAL_MODES", "lrp_set_sequential_mode", "lrp_verify_sequential_mode",
    # experimental LRP edits (focus)
    "STACK_MODES", "lrp_set_stack_calculation_mode", "lrp_verify_stack_calculation_mode",
    "lrp_set_pinhole_airy", "lrp_verify_pinhole_airy",
    "lrp_set_autofocus_active", "lrp_verify_autofocus_active",
    # experimental LRP edits (scan)
    "lrp_set_zoom", "lrp_verify_zoom",
    "lrp_set_scan_speed", "lrp_verify_scan_speed",
    "lrp_set_image_format", "lrp_verify_image_format",
    "SCAN_DIRECTIONS", "lrp_set_scan_direction", "lrp_verify_scan_direction",
    "lrp_set_phase_x", "lrp_verify_phase_x",
    "lrp_set_resonant_scanner", "lrp_verify_resonant_scanner",
    "lrp_set_bit_depth", "lrp_verify_bit_depth",
    "lrp_set_scan_field_rotation", "lrp_verify_scan_field_rotation",
    "lrp_set_pan", "lrp_verify_pan", "lrp_get_pan", "reset_pan",
    # experimental LRP edits (ROI)
    "um",
    "ROI_POLYGON", "ROI_RECTANGLE", "ROI_ELLIPSE", "ROI_LINE",
    "argb_color", "COLOR_RED", "COLOR_GREEN", "COLOR_BLUE", "COLOR_YELLOW",
    "lrp_enable_roi_scan", "lrp_verify_roi_scan",
    "lrp_clear_rois", "lrp_add_roi",
    "lrp_verify_roi_count", "lrp_verify_roi",
    "make_rectangle", "make_ellipse", "make_polygon", "make_star", "make_line",
    "lrp_find_aotf_template",
    "roi_translation_to_pan", "roi_to_absolute_um",
    "absolute_um_to_roi_translation",
    "galvo_pan_for_pixel",
    "bbox_to_zoom", "roi_geometry", "roi_to_pan_zoom",
    "mask_contour_to_roi",
    # experimental LRP edits (Z)
    "Z_STACK_DIRECTIONS", "lrp_set_z_stack_direction", "lrp_verify_z_stack_direction",
    "lrp_set_sections", "lrp_verify_sections",
    "lrp_set_z_stack_active", "lrp_verify_z_stack_active",
    "Z_USE_MODES", "lrp_set_z_use_mode", "lrp_verify_z_use_mode",
    "lrp_set_z_position", "lrp_verify_z_position",
    "lrp_set_z_stack_range", "lrp_verify_z_stack_range",
    "lrp_set_z_stack_size", "lrp_verify_z_stack_size",
    # acquisition file handling
    "read_relative_path", "parse_lasx_filename",
    "detect_new_files", "wait_all_stable", "validate_files",
    "confirm_arrival",
    # high-level acquire-and-load
    "acquire_frame", "acquire_stack",
    # session helpers
    "connect_python_client", "require_canonical_scan_orientation",
    "disable_roi_scan",
    "LIMITS_SCHEMA_VERSION", "CALIBRATION_SCHEMA_VERSION",
    "current_stage_limits_path", "default_stage_limits_path",
    "load_stage_config", "write_stage_limits_config",
    # acquisition (driver-first API)
    "start_run", "acquire_and_save", "RunHandle", "SavedAcquisition",
]

# ── _shared self-bootstrap ──────────────────────────────────────────
# Package infrastructure: navigator_expert.driver depends on
# shared.output_layout, which lives at the repository root. Callers
# that put only controller/vendor/leica/ on sys.path would otherwise get
# ModuleNotFoundError when driver imports shared. Adding the repository
# root once here keeps the dependency invisible to callers. Idempotent.
import sys as _sys
from pathlib import Path as _Path
_repo_root = str(_Path(__file__).resolve().parents[5])
if _repo_root not in _sys.path:
    _sys.path.insert(0, _repo_root)
del _sys, _Path, _repo_root

# -- core/ - raw LAS X command/readback mechanics
from .core.utils import (
    _safe_float, _hw_get, parse_format, format_to_str,
    _make_timing, _make_log_entry, parse_tile_geometry,
    RECEIPT_TIMEOUT, CONFIRM_TIMEOUT,
    PAN_LIMIT, GALVO_FIELD_FRACTION, pan_scale_um_from_base_fov,
)
from .core.errors import (
    _is_transient_error, _check_api_error, _default_error_check,
    _PERMANENT_PATTERNS, _TRANSIENT_PATTERNS,
)
from .core.readers import (
    get_scan_status, ping, get_job_settings, get_hardware_info,
    get_xy, read_zwide_um, get_jobs, get_job_by_name, get_selected_job,
    get_fov, get_base_fov, get_lasx_settings,
)
from .core.settings import make_changeable_copy
from .core.prechecks import check_idle
from .core.confirmations import _readback
from .core.dispatch import _fire_with_receipt, confirm_and_fire
from .core.commands import (
    set_zoom, set_scan_speed, set_scan_resonant, set_scan_mode,
    set_sequential_mode, set_scan_field_rotation, set_image_format,
    set_objective, set_z_stack_definition, set_z_stack_step_size,
    set_z_stack_size, set_frame_accumulation, set_frame_average,
    set_line_accumulation, set_line_average, set_pinhole_airy,
    set_detector_gain, set_laser_intensity, set_laser_shutter,
    set_filter_wheel_slot, set_filter_wheel_spectrum,
    move_xy, move_galvo_to_pixel, move_z,
    acquire, acquire_single_image, select_job,
)
from .core.session import connect_python_client, require_canonical_scan_orientation

# -- stage/ - stage safety + movement
from .stage.limits import (
    _stage_limits, set_stage_limits, get_stage_limits,
    apply_stage_limits_from_config, _check_xy_limits, _check_z_limits,
)
from .stage.movement import correct_backlash, move_xy_with_backlash
from .stage.config import (
    LIMITS_SCHEMA_VERSION, CALIBRATION_SCHEMA_VERSION,
    current_path as current_stage_limits_path,
    defaults_path as default_stage_limits_path,
    load as load_stage_config,
    write_limits as write_stage_limits_config,
)

# ── templates/ — LRP/XML/RGN file operations ──────────────────────
from .templates.files import (
    find_scanning_templates_dir, save_experiment, load_experiment,
    get_template_state, save_and_read_lrp,
)
from .templates.strip_restore import strip_template, restore_template
from .templates.transaction import apply_lrp_change, reorder_jobs
from .templates.parsers import (
    parse_lrp, diff_lrp, parse_template_positions,
    parse_acquisition_positions, parse_base_grid, parse_focus_points,
    parse_rgn_geometries, parse_rgn_tile_colors, parse_matrix_settings,
    get_master_attrs, get_rois,
)
from .templates.edits.read import lrp_get_pan

# -- acquisition/ - capture, file arrival, and save handling
from .acquisition.ome import (
    extract_wavelength_from_id,
    check_ome_xml_bytes, check_ome_tiff, check_ome_xml_file,
    fix_ome_xml_bytes, fix_ome_tiff, fix_ome_xml_file,
    update_ome_tiff_filename, update_ome_xml_filename,
)
from .acquisition.files import (
    read_relative_path, parse_lasx_filename,
    detect_new_files, wait_all_stable, validate_files, confirm_arrival,
)
from .acquisition.capture import acquire_frame, acquire_stack
from .acquisition.save import (
    RunHandle, SavedAcquisition, acquire_and_save, start_run,
)

# ── experimental/lrp_edits/ — LRP mutation helpers ─────────────────
from .experimental.lrp_edits.general import (
    lrp_set_line_average, lrp_verify_line_average,
    lrp_set_line_accumulation, lrp_verify_line_accumulation,
    lrp_set_frame_average, lrp_verify_frame_average,
    lrp_set_frame_accumulation, lrp_verify_frame_accumulation,
    lrp_set_scan_mode, lrp_verify_scan_mode,
    SEQUENTIAL_MODES, lrp_set_sequential_mode, lrp_verify_sequential_mode,
)
from .experimental.lrp_edits.focus import (
    STACK_MODES, lrp_set_stack_calculation_mode, lrp_verify_stack_calculation_mode,
    lrp_set_pinhole_airy, lrp_verify_pinhole_airy,
    lrp_set_autofocus_active, lrp_verify_autofocus_active,
)
from .experimental.lrp_edits.scan import (
    lrp_set_zoom, lrp_verify_zoom, lrp_set_scan_speed, lrp_verify_scan_speed,
    lrp_set_image_format, lrp_verify_image_format,
    SCAN_DIRECTIONS, lrp_set_scan_direction, lrp_verify_scan_direction,
    lrp_set_phase_x, lrp_verify_phase_x,
    lrp_set_resonant_scanner, lrp_verify_resonant_scanner,
    lrp_set_bit_depth, lrp_verify_bit_depth,
    lrp_set_scan_field_rotation, lrp_verify_scan_field_rotation,
    lrp_set_pan, lrp_verify_pan, reset_pan,
)
from .experimental.lrp_edits.roi import (
    um, ROI_POLYGON, ROI_RECTANGLE, ROI_ELLIPSE, ROI_LINE,
    argb_color, COLOR_RED, COLOR_GREEN, COLOR_BLUE, COLOR_YELLOW,
    lrp_enable_roi_scan, lrp_verify_roi_scan,
    lrp_clear_rois, lrp_add_roi, lrp_verify_roi_count, lrp_verify_roi,
    make_rectangle, make_ellipse, make_polygon, make_star, make_line,
    lrp_find_aotf_template,
    roi_translation_to_pan, roi_to_absolute_um, absolute_um_to_roi_translation,
    galvo_pan_for_pixel, bbox_to_zoom, roi_geometry, roi_to_pan_zoom,
    mask_contour_to_roi, disable_roi_scan,
)
from .experimental.lrp_edits.z import (
    Z_STACK_DIRECTIONS, lrp_set_z_stack_direction, lrp_verify_z_stack_direction,
    lrp_set_sections, lrp_verify_sections,
    lrp_set_z_stack_active, lrp_verify_z_stack_active,
    Z_USE_MODES, lrp_set_z_use_mode, lrp_verify_z_use_mode,
    lrp_set_z_position, lrp_verify_z_position,
    lrp_set_z_stack_range, lrp_verify_z_stack_range,
    lrp_set_z_stack_size, lrp_verify_z_stack_size,
)

# ── Logging ─────────────────────────────────────────────────────────
import logging
log = logging.getLogger(__name__)

"""
Navigator Expert Driver v6.0.0
==============================
Python driver for the Leica STELLARIS confocal microscope via the LAS X
Python API. Lives at ``navigator_expert/driver/`` — sibling to
``calibration/``, ``examples/``, ``docs/``, ``test/``.

Package layout::

    navigator_expert/driver/
    ├── __init__.py               ← you are here (public API)
    ├── utils.py                  ← helpers: _make_log_entry, _make_timing,
    │                                parse_format, parse_tile_geometry, etc.
    ├── errors.py                 ← error classification + _check_api_error +
    │                                _default_error_check adapter
    ├── limits.py                 ← stage safety limits
    ├── readers.py                ← get_scan_status, ping, get_jobs,
    │                                get_job_settings, get_hardware_info, get_xy
    ├── settings.py               ← make_changeable_copy
    ├── prechecks.py              ← pre-flight check functions (check_idle)
    ├── confirmations.py          ← readback confirmation functions,
    │                                confirm_acquire, confirm_select_job
    ├── core.py                   ← _fire_with_receipt, _fire_block,
    │                                confirm_and_fire
    ├── profiles.py               ← CommandProfile dataclass + per-command profiles
    ├── commands.py               ← set_*, move_*, acquire, select_job
    ├── scanning_templates.py     ← save_experiment, load_experiment,
    │                                strip_template, restore_template,
    │                                apply_lrp_change, reorder_jobs
    ├── scanning_template_parsers.py ← parse_lrp, diff_lrp,
    │                                parse_template_positions,
    │                                parse_acquisition_positions
    ├── scanning_template_editors.py ← lrp_set_stack_calculation_mode,
    │                                lrp_verify_stack_calculation_mode
    └── ome_tiff.py               ← OME-XML validation and patching

Dependency flow (strict DAG — no cycles)::

    utils                         ← stdlib only
    errors                        ← utils
    limits                        ← stdlib only
    readers                       ← stdlib only
    ome_tiff                      ← stdlib only
    settings                      ← utils
    prechecks                     ← readers, utils
    confirmations                 ← readers, settings, utils
    core                          ← errors, utils
    profiles                      ← prechecks, confirmations, errors
    commands                      ← core, profiles, confirmations, errors,
                                     limits, readers, utils
    scanning_templates            ← utils
    scanning_template_parsers     ← stdlib (+ optional readers)
    scanning_template_editors     ← stdlib only
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
    # ome_tiff
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
    "move_xy", "move_xy_stage", "move_xy_galvo",
    "move_z", "acquire", "acquire_single_image", "select_job",
    # scanning_templates
    "find_scanning_templates_dir", "save_experiment", "load_experiment",
    "strip_template", "restore_template", "get_template_state",
    "apply_lrp_change", "reorder_jobs", "save_and_read_lrp",
    # scanning_template_parsers
    "parse_lrp", "diff_lrp", "parse_template_positions",
    "get_master_attrs", "get_rois",
    "parse_acquisition_positions", "parse_base_grid", "parse_focus_points",
    "parse_rgn_geometries", "parse_rgn_tile_colors", "parse_matrix_settings",
    # scanning_template_synthesis
    "synthesize_tiles", "assign_focus_points_to_regions",
    # scanning_template_editors (core)
    "lrp_set_line_average", "lrp_verify_line_average",
    "lrp_set_line_accumulation", "lrp_verify_line_accumulation",
    "lrp_set_frame_average", "lrp_verify_frame_average",
    "lrp_set_frame_accumulation", "lrp_verify_frame_accumulation",
    "lrp_set_scan_mode", "lrp_verify_scan_mode",
    "SEQUENTIAL_MODES", "lrp_set_sequential_mode", "lrp_verify_sequential_mode",
    # scanning_template_editors_focus
    "STACK_MODES", "lrp_set_stack_calculation_mode", "lrp_verify_stack_calculation_mode",
    "lrp_set_pinhole_airy", "lrp_verify_pinhole_airy",
    "lrp_set_autofocus_active", "lrp_verify_autofocus_active",
    # scanning_template_editors_scan
    "lrp_set_zoom", "lrp_verify_zoom",
    "lrp_set_scan_speed", "lrp_verify_scan_speed",
    "lrp_set_image_format", "lrp_verify_image_format",
    "SCAN_DIRECTIONS", "lrp_set_scan_direction", "lrp_verify_scan_direction",
    "lrp_set_phase_x", "lrp_verify_phase_x",
    "lrp_set_resonant_scanner", "lrp_verify_resonant_scanner",
    "lrp_set_bit_depth", "lrp_verify_bit_depth",
    "lrp_set_scan_field_rotation", "lrp_verify_scan_field_rotation",
    "lrp_set_pan", "lrp_verify_pan",
    # scanning_template_editors_roi
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
    "pixel_to_absolute_um", "bbox_to_zoom", "roi_geometry", "roi_to_pan_zoom",
    "mask_contour_to_roi",
    # scanning_template_editors_z
    "Z_STACK_DIRECTIONS", "lrp_set_z_stack_direction", "lrp_verify_z_stack_direction",
    "lrp_set_sections", "lrp_verify_sections",
    "lrp_set_z_stack_active", "lrp_verify_z_stack_active",
    "Z_USE_MODES", "lrp_set_z_use_mode", "lrp_verify_z_use_mode",
    "lrp_set_z_position", "lrp_verify_z_position",
    "lrp_set_z_stack_range", "lrp_verify_z_stack_range",
    "lrp_set_z_stack_size", "lrp_verify_z_stack_size",
    # file_confirmation
    "read_relative_path", "parse_lasx_filename", "predict_manifest",
    "next_position_index",
    "detect_new_files", "wait_all_stable", "validate_files",
    "rename_and_move", "confirm_arrival", "confirm_acquisition",
    # alignment
    "load_alignment", "translate_xy", "translate_pan", "translate_z", "translate_xyz",
    # objectives (hw_info helpers)
    "objective_by_slot", "objective_summary", "validate_slots",
    # calibration (config + accessors + mutators)
    "CALIBRATION_SCHEMA_VERSION", "STAGE_SCHEMA_VERSION",
    "default_calibration_path",
    "load_calibration", "save_calibration", "save_calibration_report",
    "make_run_dir", "now_timestamp",
    "get_reference_slot", "get_image_to_stage",
    "get_shift_xy_um", "get_offset_z_um", "get_shift_z_um",
    "translate_xy_between_objectives", "translate_z_between_objectives",
    "translate_xyz_between_objectives", "reference_to_objective_command_xy",
    "pixel_to_stage_xy_um",
    "set_image_to_stage", "update_objective",
    "load_stage_config",
]

# ── Utilities ────────────────────────────────────────────────────────
from .utils import (
    _safe_float,
    _hw_get,
    parse_format,
    format_to_str,
    _make_timing,
    _make_log_entry,
    parse_tile_geometry,
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
    apply_stage_limits_from_config,
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
    read_zwide_um,
    get_jobs,
    get_job_by_name,
    get_selected_job,
    get_fov,
    get_base_fov,
    get_lasx_settings,
)

# ── OME-TIFF / OME-XML validation and patching ────────────────────
from .ome_tiff import (
    extract_wavelength_from_id,
    check_ome_xml_bytes,
    check_ome_tiff,
    check_ome_xml_file,
    fix_ome_xml_bytes,
    fix_ome_tiff,
    fix_ome_xml_file,
    update_ome_tiff_filename,
    update_ome_xml_filename,
)

# ── Settings parsing ────────────────────────────────────────────────
from .settings import make_changeable_copy

# ── Pre-flight checks ───────────────────────────────────────────────
from .prechecks import check_idle

# ── Confirm (public readback helper only) ────────────────────────────
from .confirmations import _readback

# ── Core dispatch ───────────────────────────────────────────────────
from .utils import (  # noqa: F401
    RECEIPT_TIMEOUT, CONFIRM_TIMEOUT,
    PAN_LIMIT, GALVO_FIELD_FRACTION, pan_scale_um_from_base_fov,
)

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
    move_xy_stage,
    move_xy_galvo,
    move_z,
    acquire,
    acquire_single_image,
    select_job,
)

# ── Scanning templates ─────────────────────────────────────────────
from .scanning_templates import (
    find_scanning_templates_dir,
    save_experiment,
    load_experiment,
    strip_template,
    restore_template,
    get_template_state,
    apply_lrp_change,
    reorder_jobs,
    save_and_read_lrp,
)

# ── Scanning template parsers ─────────────────────────────────────
from .scanning_template_parsers import (
    parse_lrp,
    diff_lrp,
    parse_template_positions,
    parse_acquisition_positions,
    parse_base_grid,
    parse_focus_points,
    parse_rgn_geometries,
    parse_rgn_tile_colors,
    parse_matrix_settings,
    get_master_attrs,
    get_rois,
)

# ── Scanning template synthesis ──────────────────────────────────
from .scanning_template_synthesis import (
    synthesize_tiles,
    assign_focus_points_to_regions,
)

# ── Scanning template editors (core + averaging + mode) ──────────
from .scanning_template_editors import (
    lrp_set_line_average,
    lrp_verify_line_average,
    lrp_set_line_accumulation,
    lrp_verify_line_accumulation,
    lrp_set_frame_average,
    lrp_verify_frame_average,
    lrp_set_frame_accumulation,
    lrp_verify_frame_accumulation,
    lrp_set_scan_mode,
    lrp_verify_scan_mode,
    SEQUENTIAL_MODES,
    lrp_set_sequential_mode,
    lrp_verify_sequential_mode,
)

# ── Focus editors (autofocus, pinhole, stack calc mode) ──────────
from .scanning_template_editors_focus import (
    STACK_MODES,
    lrp_set_stack_calculation_mode,
    lrp_verify_stack_calculation_mode,
    lrp_set_pinhole_airy,
    lrp_verify_pinhole_airy,
    lrp_set_autofocus_active,
    lrp_verify_autofocus_active,
)

# ── Scan-field editors (zoom, speed, format, direction, etc.) ────
from .scanning_template_editors_scan import (
    lrp_set_zoom,
    lrp_verify_zoom,
    lrp_set_scan_speed,
    lrp_verify_scan_speed,
    lrp_set_image_format,
    lrp_verify_image_format,
    SCAN_DIRECTIONS,
    lrp_set_scan_direction,
    lrp_verify_scan_direction,
    lrp_set_phase_x,
    lrp_verify_phase_x,
    lrp_set_resonant_scanner,
    lrp_verify_resonant_scanner,
    lrp_set_bit_depth,
    lrp_verify_bit_depth,
    lrp_set_scan_field_rotation,
    lrp_verify_scan_field_rotation,
    lrp_set_pan,
    lrp_verify_pan,
)

# ── ROI scanning template editors ────────────────────────────────
from .scanning_template_editors_roi import (
    um,
    ROI_POLYGON, ROI_RECTANGLE, ROI_ELLIPSE, ROI_LINE,
    argb_color, COLOR_RED, COLOR_GREEN, COLOR_BLUE, COLOR_YELLOW,
    lrp_enable_roi_scan,
    lrp_verify_roi_scan,
    lrp_clear_rois,
    lrp_add_roi,
    lrp_verify_roi_count,
    lrp_verify_roi,
    make_rectangle,
    make_ellipse,
    make_polygon,
    make_star,
    make_line,
    lrp_find_aotf_template,
    roi_translation_to_pan,
    roi_to_absolute_um,
    absolute_um_to_roi_translation,
    pixel_to_absolute_um,
    bbox_to_zoom,
    roi_geometry,
    roi_to_pan_zoom,
    mask_contour_to_roi,
)

# ── Z-stack scanning template editors ────────────────────────────
from .scanning_template_editors_z import (
    Z_STACK_DIRECTIONS,
    lrp_set_z_stack_direction,
    lrp_verify_z_stack_direction,
    lrp_set_sections,
    lrp_verify_sections,
    lrp_set_z_stack_active,
    lrp_verify_z_stack_active,
    Z_USE_MODES,
    lrp_set_z_use_mode,
    lrp_verify_z_use_mode,
    lrp_set_z_position,
    lrp_verify_z_position,
    lrp_set_z_stack_range,
    lrp_verify_z_stack_range,
    lrp_set_z_stack_size,
    lrp_verify_z_stack_size,
)

# ── File confirmation ─────────────────────────────────────────────
from .file_confirmation import (
    read_relative_path,
    parse_lasx_filename,
    predict_manifest,
    next_position_index,
    detect_new_files,
    wait_all_stable,
    validate_files,
    rename_and_move,
    confirm_arrival,
    confirm_acquisition,
)

# ── Alignment / coordinate translation ────────────────────────────
from .alignment import (
    load_alignment,
    translate_xy,
    translate_pan,
    translate_z,
    translate_xyz,
)

# ── Objective-slot helpers (pure functions over hw_info) ───────
from .objectives import (
    objective_by_slot,
    objective_summary,
    validate_slots,
)

from .calibration import (
    SCHEMA_VERSION as CALIBRATION_SCHEMA_VERSION,
    default_path as default_calibration_path,
    load_calibration,
    save_calibration,
    save_calibration_report,
    make_run_dir,
    now_timestamp,
    get_reference_slot,
    get_image_to_stage,
    get_shift_xy_um,
    get_offset_z_um,
    get_shift_z_um,
    translate_xy_between_objectives,
    translate_z_between_objectives,
    translate_xyz_between_objectives,
    reference_to_objective_command_xy,
    pixel_to_stage_xy_um,
    set_image_to_stage,
    update_objective,
)

# ── Stage motion (backlash takeup) ──────────────────────────────
from .stage_motion import correct_backlash

# ── Stage config (limits + backlash; physical, not optical) ─────
from .stage_config import (
    SCHEMA_VERSION as STAGE_SCHEMA_VERSION,
    load as load_stage_config,
)

# ── Logging ─────────────────────────────────────────────────────────
import logging
log = logging.getLogger(__name__)

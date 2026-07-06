# ruff: noqa: E402,I001,F401
"""Navigator Expert driver for Leica LAS X.

Package layout::

    navigator_expert/
    - commands/     command wrappers, dispatch, confirmation logic
    - config/       command and reader profiles, tuning defaults
    - connection/   session helpers and LAS X API connection
    - readers/      API/log/hybrid state readers
    - scanfields/   LAS X scan-field files, parsing, planning, strip/restore
    - acquisition/  acquire-only capture, LAS X file export, OME fixes, save
    - motion/       stage limits, backlash motion utilities, stage config
    - calibration/  image-stage + objective-pair calibration (model + defaults consumed at connect)
    - limits/       stage/function limits TEMPLATES + the operator notebook that
                    creates the machine-local (enforceable) files
    - zmart_adapter/ ops table plugging this driver into zmart_controller
    - experimental/ LRP mutation helpers without live-state readback
    - tests/        offline unit suite + hardware validators
"""

__version__ = "6.0.0"

__all__ = [
    # logging
    "log",
    # utils
    "parse_tile_geometry",
    # limits
    "set_stage_limits",
    "get_stage_limits",
    "apply_stage_limits_from_config",
    # function-keyed limits gate (commands layer)
    "connect_limits_handshake",
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
    # settings
    "make_changeable_copy",
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
    # acquisition, not a command: acquire RAISES on failure and returns an
    # AcquisitionResult, never a result dict (see acquisition.capture)
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
    "move_xy_with_backlash",
    "reorder_jobs",
    "save_and_read_lrp",
    # position parsers/planning
    "parse_lrp",
    "parse_scan_positions",
    "parse_acquisition_positions",
    "parse_base_grid",
    "parse_focus_points",
    "parse_rgn_geometries",
    "parse_rgn_tile_colors",
    "parse_matrix_settings",
    "plan_tiles_from_geometries",
    # experimental LRP edits (scan)
    "lrp_set_zoom",
    "reset_pan",
    # experimental LRP edits (ROI)
    "lrp_clear_rois",
    "lrp_add_roi",
    "make_rectangle",
    "make_ellipse",
    "make_polygon",
    "roi_translation_to_pan",
    "galvo_pan_for_pixel",
    "mask_contour_to_roi",
    # session helpers
    "connect_python_client",
    "require_canonical_scan_orientation",
    "disable_roi_scan",
    "LIMITS_SOURCE_DEFAULTS",
    "LIMITS_SOURCE_BOUNDARY_MARKERS",
    "LIMITS_SOURCE_CFG_FALLBACK",
    "LIMITS_SOURCE_SCAN_FIELD",
    "current_stage_limits_path",
    "load_stage_config",
    "write_stage_limits_config",
    # acquisition workflow
    "AcquisitionResult",
    "PlaneIndex",
    "PositionIndex",
    "SavedAcquisition",
    "save_source_root",
    "save",
]

# -- package self-bootstrap
# navigator_expert depends on shared.output_layout at the repo root.
# Callers usually put zmart_drivers/leica/stellaris5_y42h93/ on sys.path; adding
# both roots here keeps subprocesses and scripts resilient when they import the
# driver first.
import sys as _sys
from pathlib import Path as _Path

_here = _Path(__file__).resolve()
_machine_root = str(_here.parents[1])  # .../leica/stellaris5_y42h93
_repo_root = str(_here.parents[4])
for _path in (_repo_root, _machine_root):
    if _path not in _sys.path:
        _sys.path.insert(0, _path)
del _sys, _Path, _here, _machine_root, _repo_root, _path

# -- shared utilities + commands/ - helpers and command mechanics
from .utils import (
    _safe_float,
    parse_format,
    _make_log_entry,
    parse_tile_geometry,
)
from .commands.errors import (
    _is_transient_error,
    _check_api_error,
    _default_error_check,
)
from .readers import (
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
from .commands.confirmations import _readback
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
from .connection.session import (
    connect_python_client,
    require_canonical_scan_orientation,
)

# -- commands/gate - function-keyed limits gate + connect handshake
from .commands.gate import (
    connect_handshake as connect_limits_handshake,
)

# -- motion/ - stage safety + movement
from .motion.limits import (
    _stage_limits,
    set_stage_limits,
    get_stage_limits,
    apply_stage_limits_from_config,
    _check_xy_limits,
    _check_z_limits,
)
from .motion.movement import move_xy_with_backlash
from .motion.stage_config import (
    LIMITS_SOURCE_DEFAULTS,
    LIMITS_SOURCE_BOUNDARY_MARKERS,
    LIMITS_SOURCE_CFG_FALLBACK,
    LIMITS_SOURCE_SCAN_FIELD,
    current_path as current_stage_limits_path,
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
from .scanfields.lrp import parse_lrp
from .scanfields.parsers import (
    parse_scan_positions,
    parse_acquisition_positions,
    parse_base_grid,
    parse_focus_points,
    parse_rgn_geometries,
    parse_rgn_tile_colors,
    parse_matrix_settings,
)
from .scanfields.planning import plan_tiles_from_geometries

# -- acquisition/ - capture, file arrival, and save handling
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
from .acquisition.save import active_save_exporter, save_source_root, save

# -- experimental/lrp_edits/ - LRP mutation helpers
from .experimental.lrp_edits.scan import (
    lrp_set_zoom,
    reset_pan,
)
from .experimental.lrp_edits.roi import (
    lrp_clear_rois,
    lrp_add_roi,
    make_rectangle,
    make_ellipse,
    make_polygon,
    roi_translation_to_pan,
    galvo_pan_for_pixel,
    mask_contour_to_roi,
    disable_roi_scan,
)

# -- logging
import logging

log = logging.getLogger(__name__)

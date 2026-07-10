"""Public surface for the target-acquisition workflow (controller-only).

The workflow drives the microscope through the ``zmart_controller`` Session
surface only -- no ``import navigator_expert`` in the operator path. The
notebook imports the numbered step functions from this package and runs
them in order:

  connect -> pick_focus_points (click points, Measure focus) ->
  run_overview -> view_overview (channel overlay mosaic) ->
  discover_targets -> explore_targets (gate + inspect) ->
  acquire_gallery (pick N at random, review same-scale pairs)

Re-exports:

- the step functions (``workflow.steps``): ``connect``, ``load_positions``,
  ``load_analysis_engine``, ``preflight_analysis_engine``, ``with_focus_z``,
  ``run_overview``, ``overview_inputs_from_records``, ``acquire_targets``,
  ``hijack_if_simulating``, ``write_run_report``;
- focus (``workflow._focus_run`` / ``workflow._focus_surface`` /
  ``workflow._focus_widget``): ``measure_focus``, ``fit_focus_surface``,
  ``FocusSurface``, ``pick_focus_points``, ``FocusPicker`` (the interactive
  point-picking figure with the in-place focus-map heatmap);
- target discovery (``workflow.discovery``): ``discover_targets``;
- the XY-calibration validation run (``workflow._calibration_check``):
  ``start_calibration_check`` / ``finish_calibration_check`` — image the
  same ring of sites with both objectives and measure how far the
  objective-pair calibration is off, averaged over many stage moves;
- the interactive review widgets (each a matplotlib figure; see the module
  docstrings): ``view_overview`` / ``OverviewViewer`` (zoomable tile mosaic
  with per-channel colour, brightness and contrast), ``explore_targets`` /
  ``TargetExplorer`` (feature scatter with threshold + lasso gating and
  hover cell crops), ``acquire_gallery`` / ``AcquisitionGallery`` (random
  pick from the gate, then same-scale overview/target image pairs);
- the shared acquire primitive (``workflow._capture_run``):
  ``capture_positions``;
- the pixel->frame geometry (``workflow._geom``): ``overview_pixel_to_frame``;
- run summary + plots (``workflow.viz``): ``summarize_run``, ``write_summary``,
  ``plot_focus_surface``, ``plot_frame_layout`` (plots lazy-import matplotlib);
- simulation-mode hijack (``workflow._hijack`` / ``workflow._mock_provider``):
  ``hijack_records``, ``get_provider``, ``NonSimulatorFrameError``.

Importing this package pulls in no driver code. The sim hijack overwrites the
pixels of the ``.ome.tiff`` files ``acquire`` saved (gated per-frame on a
positive ``SystemTypeName == "SIMULATOR"`` allowlist); the driver's OME check
it uses is lazy-imported, so ``import workflow`` stays driver-free and the
operator step functions never learn about simulation.

The pre-controller driver-coupled flow is preserved under
``workflow.retired`` (see that package's docstring).

Modules whose names start with ``_`` are internal.
"""

from ._acquisition_widget import AcquisitionGallery, acquire_gallery
from ._calibration_check import (
    CalibrationCheck,
    finish_calibration_check,
    start_calibration_check,
)
from ._capture_run import capture_positions
from ._discovery_widget import TargetExplorer, explore_targets
from ._focus_run import measure_focus
from ._focus_surface import FocusSurface, fit_focus_surface
from ._focus_widget import FocusPicker, pick_focus_points
from ._geom import overview_pixel_to_frame
from ._hijack import NonSimulatorFrameError, hijack_records
from ._mock_provider import get_provider
from ._overview_widget import OverviewViewer, view_overview
from .discovery import build_overview_inputs, discover_targets, read_overview_geometry
from .steps import (
    acquire_targets,
    connect,
    hijack_if_simulating,
    load_analysis_engine,
    load_positions,
    overview_inputs_from_records,
    preflight_analysis_engine,
    run_overview,
    with_focus_z,
    write_run_report,
)
from .viz import (
    plot_focus_surface,
    plot_frame_layout,
    summarize_run,
    write_summary,
)

__all__ = [
    "connect",
    "load_positions",
    "load_analysis_engine",
    "preflight_analysis_engine",
    "with_focus_z",
    "measure_focus",
    "fit_focus_surface",
    "FocusSurface",
    "pick_focus_points",
    "FocusPicker",
    "start_calibration_check",
    "finish_calibration_check",
    "CalibrationCheck",
    "view_overview",
    "OverviewViewer",
    "explore_targets",
    "TargetExplorer",
    "acquire_gallery",
    "AcquisitionGallery",
    "run_overview",
    "overview_inputs_from_records",
    "build_overview_inputs",
    "read_overview_geometry",
    "discover_targets",
    "acquire_targets",
    "hijack_if_simulating",
    "capture_positions",
    "overview_pixel_to_frame",
    "summarize_run",
    "write_summary",
    "write_run_report",
    "plot_focus_surface",
    "plot_frame_layout",
    "get_provider",
    "hijack_records",
    "NonSimulatorFrameError",
]

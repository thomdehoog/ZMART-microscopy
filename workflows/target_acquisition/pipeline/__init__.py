"""Public surface for the target-acquisition pipeline (controller-only).

The workflow drives the microscope through the ``zmart_controller`` Session
surface only -- no ``import navigator_expert`` in the operator path. The
notebook imports the numbered step functions from this package and runs
them in order:

  connect -> load_positions -> measure_focus / fit_focus_surface ->
  run_overview -> discover_targets -> acquire_targets

Re-exports:

- the step functions (``pipeline.steps``): ``connect``, ``load_positions``,
  ``with_focus_z``, ``run_overview``, ``acquire_targets``;
- focus (``pipeline._focus_run`` / ``pipeline._focus_surface``):
  ``measure_focus``, ``fit_focus_surface``, ``FocusSurface``;
- target discovery (``pipeline.discovery``): ``discover_targets``;
- the shared acquire primitive (``pipeline._capture_run``):
  ``capture_positions``;
- the pixel->frame geometry (``pipeline._geom``): ``overview_pixel_to_frame``;
- run summary + plots (``pipeline.viz``): ``summarize_run``, ``write_summary``,
  ``plot_focus_surface``, ``plot_frame_layout`` (plots lazy-import matplotlib);
- simulation-mode hijack (``pipeline._hijack`` / ``pipeline._mock_provider``):
  ``hijack_records``, ``get_provider``, ``NonSimulatorFrameError``.

Importing this package pulls in no driver code. The sim hijack overwrites the
pixels of the ``.ome.tiff`` files ``acquire`` saved (gated per-frame on a
positive ``SystemTypeName == "SIMULATOR"`` allowlist); the driver's OME check
it uses is lazy-imported, so ``import pipeline`` stays driver-free and the
operator step functions never learn about simulation.

The pre-controller driver-coupled flow is preserved under
``pipeline.retired`` (see that package's docstring).

Modules whose names start with ``_`` are internal.
"""

from ._capture_run import capture_positions
from ._focus_run import measure_focus
from ._focus_surface import FocusSurface, fit_focus_surface
from ._geom import overview_pixel_to_frame
from ._hijack import NonSimulatorFrameError, hijack_records
from ._mock_provider import get_provider
from ._orientation import Orientation, apply_orientation, load_orientation
from .discovery import build_overview_inputs, discover_targets, read_overview_geometry
from .steps import (
    acquire_targets,
    connect,
    load_positions,
    run_overview,
    with_focus_z,
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
    "with_focus_z",
    "measure_focus",
    "fit_focus_surface",
    "FocusSurface",
    "run_overview",
    "build_overview_inputs",
    "read_overview_geometry",
    "discover_targets",
    "acquire_targets",
    "capture_positions",
    "overview_pixel_to_frame",
    "summarize_run",
    "write_summary",
    "plot_focus_surface",
    "plot_frame_layout",
    "get_provider",
    "hijack_records",
    "NonSimulatorFrameError",
    "Orientation",
    "load_orientation",
    "apply_orientation",
]

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
- the pixel->frame geometry (``pipeline._geom``): ``overview_pixel_to_frame``.

Importing this package pulls in no driver code. Simulation-mode helpers
(``hijack_frame`` / ``get_provider``) live in ``pipeline._hijack`` /
``pipeline._mock_provider`` and are imported on demand by the sim caller,
so the default operator path stays driver-free.

The pre-controller driver-coupled flow is preserved under
``pipeline.retired`` (see that package's docstring).

Modules whose names start with ``_`` are internal.
"""

from ._capture_run import capture_positions
from ._focus_run import measure_focus
from ._focus_surface import FocusSurface, fit_focus_surface
from ._geom import overview_pixel_to_frame
from .discovery import discover_targets
from .steps import (
    acquire_targets,
    connect,
    load_positions,
    run_overview,
    with_focus_z,
)

__all__ = [
    "connect",
    "load_positions",
    "with_focus_z",
    "measure_focus",
    "fit_focus_surface",
    "FocusSurface",
    "run_overview",
    "discover_targets",
    "acquire_targets",
    "capture_positions",
    "overview_pixel_to_frame",
]

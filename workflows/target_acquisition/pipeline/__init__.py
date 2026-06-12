"""Public surface for the target-acquisition pipeline.

The notebook imports only from this package. Re-exports:

- the six numbered step functions executed in order from the notebook:
  preflight -> prepare_template -> build_focus_map -> run_overview ->
  select_targets -> acquire_targets -> finish;
- the run-scoped types (`Config`, `Context`, `LimitsContext`, `TargetState`),
  the dataclasses each step produces (`Picks`, `OverviewResult`,
  `SelectionResult`, `TargetRecord`, `FocusMap`), and the selection-mode
  constants;
- the visualization and diagnostic helpers used both live in the notebook
  and offline.

Modules whose names start with `_` are internal.
"""
from .connect import connect_lasx
from .context import Config, Context, LimitsContext, TargetState
from .focus import FocusMap, build_focus_map
from .overview import OverviewResult, Pick, TileEvent, run_overview
from .preflight import preflight
from .selection import (
    MODE_EMPTY, MODE_NO_QUALIFYING, MODE_SPARSE, MODE_THRESHOLD,
    Picks, SelectionResult, load_overview_result, select_targets,
)
from .summary import write_summary, plot_results, finish
from .target import TargetRecord, acquire_targets
from .template import (
    archive_and_strip, plot_scan_field, plot_stage_envelope,
    prepare_template, read_scan_field, show_template_state,
)
from .visualize import (
    display_selection, display_tile, display_target,
    plot_overview_tiles, plot_target_pairs,
)

__all__ = ["Config", "Context", "LimitsContext", "TargetState",
           "connect_lasx",
           "FocusMap", "build_focus_map",
           "OverviewResult", "Pick", "Picks", "TileEvent", "run_overview",
           "SelectionResult", "select_targets", "load_overview_result",
           "MODE_THRESHOLD", "MODE_SPARSE", "MODE_NO_QUALIFYING", "MODE_EMPTY",
           "TargetRecord", "acquire_targets",
           "write_summary", "plot_results", "finish",
           "preflight", "prepare_template", "archive_and_strip",
           "read_scan_field", "show_template_state",
           "plot_scan_field", "plot_stage_envelope",
           "display_tile", "display_target", "display_selection",
           "plot_overview_tiles", "plot_target_pairs"]

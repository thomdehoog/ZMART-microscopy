"""Notebook-side pipeline helpers for target acquisition.

The notebook imports only from this package; implementation logic lives
here while operator-facing notes live in the parent README.
"""
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[6]
_CONTROLLER_LEICA = _REPO_ROOT / "controller" / "vendor" / "leica"
for _path in (str(_CONTROLLER_LEICA), str(_REPO_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

del _path

from .connect import connect_lasx
from .context import Config, Context, LimitsContext, TargetState
from .focus import FocusMap, build_focus_map
from .overview import OverviewResult, Pick, Picks, TileEvent, run_overview
from .preflight import preflight
from .selection import (
    MODE_EMPTY, MODE_NO_QUALIFYING, MODE_SPARSE, MODE_THRESHOLD,
    SelectionResult, load_overview_result, select_targets,
)
from .summary import write_summary, plot_results, finish
from .target import TargetRecord, acquire_targets
from .template import (
    archive_and_strip, plot_scan_field, plot_stage_envelope,
    prepare_template, read_scan_field,
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
           "read_scan_field", "plot_scan_field", "plot_stage_envelope",
           "display_tile", "display_target", "display_selection",
           "plot_overview_tiles", "plot_target_pairs"]

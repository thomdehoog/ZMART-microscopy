"""Notebook-side workflow helpers for target acquisition.

The notebook (smart_microscopy_v3.ipynb) imports only from this
package; all real logic lives here. See TARGET_ACQUISITION_DESIGN.md
in the parent directory for the full contract.
"""
import sys
from pathlib import Path

# navigator_expert lives three directories above workflow/:
#   .../leica/navigator_expert/notebooks/workflow/__init__.py
#   parents[3] = .../leica/
_LEICA_ROOT = str(Path(__file__).resolve().parents[3])
if _LEICA_ROOT not in sys.path:
    sys.path.insert(0, _LEICA_ROOT)

# parents[4] = .../vendor/ — needed for `from _shared.output_layout import ...`
_VENDOR_ROOT = str(Path(__file__).resolve().parents[4])
if _VENDOR_ROOT not in sys.path:
    sys.path.insert(0, _VENDOR_ROOT)

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
from .template import prepare_template, read_scan_field, plot_scan_field
from .visualize import (
    display_selection, display_tile, display_target,
    plot_overview_tiles, plot_target_pairs,
)

__all__ = ["Config", "Context", "LimitsContext", "TargetState",
           "FocusMap", "build_focus_map",
           "OverviewResult", "Pick", "Picks", "TileEvent", "run_overview",
           "SelectionResult", "select_targets", "load_overview_result",
           "MODE_THRESHOLD", "MODE_SPARSE", "MODE_NO_QUALIFYING", "MODE_EMPTY",
           "TargetRecord", "acquire_targets",
           "write_summary", "plot_results", "finish",
           "preflight", "prepare_template",
           "read_scan_field", "plot_scan_field",
           "display_tile", "display_target", "display_selection",
           "plot_overview_tiles", "plot_target_pairs"]

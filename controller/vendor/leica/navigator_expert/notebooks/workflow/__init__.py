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

from .context import Config, Context, TargetState
from .focus import FocusMap, build_focus_map
from .overview import Pick, Picks, TileEvent, run_overview_with_picks
from .preflight import preflight
from .summary import write_summary, plot_results, finish
from .target import TargetRecord, acquire_targets
from .template import prepare_template, read_scan_field, plot_scan_field
from .visualize import (
    display_tile, display_target,
    plot_overview_tiles, plot_target_pairs,
)

__all__ = ["Config", "Context", "TargetState", "FocusMap", "build_focus_map",
           "Pick", "Picks", "TileEvent", "run_overview_with_picks",
           "TargetRecord", "acquire_targets",
           "write_summary", "plot_results", "finish",
           "preflight", "prepare_template",
           "read_scan_field", "plot_scan_field",
           "display_tile", "display_target",
           "plot_overview_tiles", "plot_target_pairs"]

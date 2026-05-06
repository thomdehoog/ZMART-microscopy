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

from .context import Config, Context
from .focus import FocusMap, build_focus_map
from .preflight import preflight
from .template import prepare_template, read_scan_field, plot_scan_field

__all__ = ["Config", "Context", "FocusMap", "build_focus_map",
           "preflight", "prepare_template",
           "read_scan_field", "plot_scan_field"]

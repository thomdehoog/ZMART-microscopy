"""Notebook bootstrap: paths, Leica registration, and public notebook imports."""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).parent.resolve()
_REPO_ROOT = _HERE.parents[1]
TARGET_ACQ = _HERE

# navigator_expert (and navigator_expert.calibration) needs its parent dir on sys.path
_DRIVER_PARENT = _REPO_ROOT / "zmart_drivers" / "leica" / "stellaris5_y42h93"
if str(_DRIVER_PARENT) not in sys.path:
    sys.path.insert(0, str(_DRIVER_PARENT))

# shared/ and workflows/ live at the repo root
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Importing the adapter registers the Leica microscope with zmart_controller.
import navigator_expert.zmart_adapter  # noqa: E402,F401

# pipeline/ is a sibling package to this bootstrap
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import pipeline  # noqa: E402

# v3 notebook entry: ``Config`` belongs to the retired driver-coupled flow
# (the active controller-only pipeline no longer defines it). See
# pipeline/retired/.
from pipeline.retired.context import Config  # noqa: E402

__all__ = ["Config", "Path", "TARGET_ACQ", "pipeline"]

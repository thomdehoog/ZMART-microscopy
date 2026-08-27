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

# workflows/ lives at the repo root
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Importing the adapter registers the Leica microscope with zmart_controller.
import navigator_expert.zmart_adapter  # noqa: E402,F401

# The workflow's Python front door now stands beside its JavaScript one, in
# the application: `application/workflows/target_acquisition/`. The notebooks
# ask for `workflow`, and that is what they get -- the name is the notebook's
# word for "the thing I am driving", and it is worth keeping while its code
# finds the place it belongs.
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import application.workflows.target_acquisition as workflow  # noqa: E402

__all__ = ["Path", "TARGET_ACQ", "workflow"]

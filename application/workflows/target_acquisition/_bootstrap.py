"""Notebook bootstrap: paths, Leica registration, and public notebook imports."""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).parent.resolve()
_REPO_ROOT = _HERE.parents[2]          # .../application/workflows/<this>/
TARGET_ACQ = _HERE

# navigator_expert (and navigator_expert.calibration) needs its parent dir on sys.path
_DRIVER_PARENT = _REPO_ROOT / "zmart_drivers" / "leica" / "stellaris5_y42h93"
if str(_DRIVER_PARENT) not in sys.path:
    sys.path.insert(0, str(_DRIVER_PARENT))

# `application/` lives at the repo root, and everything below it is named from
# there: `application.parts.microscope`, `application.workflows.<name>`.
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Importing the adapter registers the Leica microscope with zmart_controller.
import navigator_expert.zmart_adapter  # noqa: E402,F401

# The notebooks ask for `workflow`, and that is what they get: the name is the
# notebook's word for "the thing I am driving", and the package it names is
# this folder -- the workflow's Python front door, standing beside its
# JavaScript one.
import application.workflows.target_acquisition as workflow  # noqa: E402

__all__ = ["Path", "TARGET_ACQ", "workflow"]

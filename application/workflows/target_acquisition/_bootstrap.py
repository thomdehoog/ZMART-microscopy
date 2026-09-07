"""Notebook bootstrap: paths, Leica registration, and public notebook imports."""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).parent.resolve()
_REPO_ROOT = _HERE.parents[2]          # .../application/workflows/<this>/
TARGET_ACQ = _HERE

# `application/` lives at the repo root, and everything below it is named from
# there: `application.parts.microscope`, `application.workflows.<name>`.
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Every driver folder under zmart_drivers/<vendor>/ registers its microscope
# with zmart_controller when imported (the Leica's navigator_expert.zmart_adapter
# among them); this finds and imports them all, so the notebook sees the
# same Microscope list the operator page does.
from zmart_drivers.discovery import register_every_driver  # noqa: E402

register_every_driver()

# The notebooks ask for `workflow`, and that is what they get: the name is the
# notebook's word for "the thing I am driving", and the package it names is
# this folder -- the workflow's Python front door, standing beside its
# JavaScript one.
import application.workflows.target_acquisition as workflow  # noqa: E402

__all__ = ["Path", "TARGET_ACQ", "workflow"]

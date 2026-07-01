"""
Stage configuration loader.
===========================
A slim JSON loader for the per-instrument stage envelope. The Leica driver's
calibration schema is intentionally dropped here (calibration is an extension
seam); the MVP only needs the safety-limit envelope in micrometers.

Expected JSON shape::

    {
      "stage_um": {
        "x": [x_min, x_max],
        "y": [y_min, y_max],
        "z": [z_min, z_max]
      }
    }

Feed the result to :func:`zenapi.motion.limits.apply_stage_limits_from_config`.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import json
from pathlib import Path

_REQUIRED_AXES = ("x", "y", "z")


def load(path: str | Path) -> dict:
    """Load and validate a stage-config JSON file. Returns the parsed dict."""
    path = Path(path)
    with path.open(encoding="utf-8") as fh:
        cfg = json.load(fh)
    stage = cfg.get("stage_um")
    if not isinstance(stage, dict):
        raise ValueError(f"{path}: missing 'stage_um' object")
    for axis in _REQUIRED_AXES:
        bounds = stage.get(axis)
        if not (isinstance(bounds, (list, tuple)) and len(bounds) == 2):
            raise ValueError(f"{path}: stage_um.{axis} must be a [min, max] pair")
        if bounds[0] > bounds[1]:
            raise ValueError(f"{path}: stage_um.{axis} min > max")
    return cfg


def example() -> dict:
    """A template stage-config dict (edit for the real instrument envelope)."""
    return {
        "stage_um": {
            "x": [-60000.0, 60000.0],
            "y": [-40000.0, 40000.0],
            "z": [0.0, 10000.0],
        }
    }

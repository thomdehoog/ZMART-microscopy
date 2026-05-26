"""Stage calibration: physical limits + backlash takeup parameters.

Loaded from the root-level calibration live state:
``calibration/vendor/leica/navigator_expert/live/stage.json``.

Schema (v1)::

    {
      "schema_version": 1,
      "limits_um":  { "x": [...], "y": [...], "z_galvo": [...], "z_wide": [...] },
      "backlash":   { "overshoot_um": <float>, "settle_ms": <int> }
    }
"""

import json
from pathlib import Path

SCHEMA_VERSION = 1

_REQUIRED_AXES = ("x", "y", "z_galvo", "z_wide")


def default_path():
    """Path to the live stage configuration."""
    repo_root = Path(__file__).resolve().parents[6]
    return (
        repo_root
        / "calibration"
        / "vendor"
        / "leica"
        / "navigator_expert"
        / "live"
        / "stage.json"
    )


def load(path=None):
    """Load and validate stage.json. Raises if missing or malformed."""
    path = Path(path) if path is not None else default_path()
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if cfg.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported stage.json schema_version: "
            f"{cfg.get('schema_version')!r} in {path}"
        )
    for key in ("limits_um", "backlash"):
        if key not in cfg:
            raise ValueError(f"stage.json missing required section: {key!r}")
    for axis in _REQUIRED_AXES:
        if axis not in cfg["limits_um"]:
            raise ValueError(f"stage.json limits_um missing axis: {axis!r}")
    return cfg

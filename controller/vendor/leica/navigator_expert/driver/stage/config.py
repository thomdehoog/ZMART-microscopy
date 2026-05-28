"""Load and write Leica stage limit state.

Stage limits are configured safety/working limits, not calibration
measurements. They live beside calibration files because both describe
the current Leica machine state.

``limits/vendor/leica/navigator_expert/defaults.json`` contains the configured
physical envelope for the microscope.

``limits/vendor/leica/navigator_expert/current.json`` contains the active
working envelope. The target-acquisition notebook updates this file from
boundary markers or scan-field geometry before applying limits.

``current/calibration.json`` contains measured calibration state, including
the backlash block consumed by motion helpers.

The loader reads ``limits/.../current.json`` by default and never falls back to
``limits/.../defaults.json``. Resetting current from defaults is an explicit
operator action.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

LIMITS_SCHEMA_VERSION = 1
CALIBRATION_SCHEMA_VERSION = 11

_REQUIRED_AXES = ("x", "y", "z_galvo", "z_wide")
_REQUIRED_BACKLASH = (
    "approach",
    "overshoot_um",
    "settle_ms",
    "tolerance_um",
    "session_id",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[6]


def limits_root() -> Path:
    return (
        _repo_root()
        / "limits"
        / "vendor"
        / "leica"
        / "navigator_expert"
    )


def calibration_current_root() -> Path:
    return (
        _repo_root()
        / "calibration"
        / "vendor"
        / "leica"
        / "navigator_expert"
        / "current"
    )


def current_path() -> Path:
    """Path to the current limits config."""
    return limits_root() / "current.json"


def defaults_path() -> Path:
    """Path to the configured physical-envelope baseline."""
    return limits_root() / "defaults.json"


def default_calibration_path() -> Path:
    """Path to the current calibration config."""
    return calibration_current_root() / "calibration.json"


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(str(tmp), str(path))


def _validate_limits(limits: dict[str, Any], *, path: Path) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for axis in _REQUIRED_AXES:
        if axis not in limits:
            raise ValueError(f"{path} stage limits missing axis: {axis!r}")
        values = limits[axis]
        if not isinstance(values, list) or len(values) != 2:
            raise ValueError(
                f"{path} stage limit {axis!r} must be [min, max], got {values!r}"
            )
        low, high = float(values[0]), float(values[1])
        if low > high:
            raise ValueError(
                f"{path} stage limit {axis!r} has min > max: {values!r}"
            )
        out[axis] = [low, high]
    return out


def _validate_backlash(
    backlash: dict[str, Any],
    *,
    path: Path,
) -> dict[str, Any]:
    for key in _REQUIRED_BACKLASH:
        if key not in backlash:
            raise ValueError(f"{path} backlash missing field: {key!r}")
    return {
        "approach": backlash["approach"],
        "overshoot_um": float(backlash["overshoot_um"]),
        "settle_ms": int(backlash["settle_ms"]),
        "tolerance_um": float(backlash["tolerance_um"]),
        "session_id": backlash["session_id"],
    }


def _read_limits(path: Path) -> dict[str, list[float]]:
    payload = _read_json(path)
    if payload.get("schema_version") != LIMITS_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported limits.json schema_version "
            f"{payload.get('schema_version')!r} in {path}"
        )
    if "stage_um" not in payload:
        raise ValueError(f"{path} missing stage_um section")
    return _validate_limits(payload["stage_um"], path=path)


def _read_backlash(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    if payload.get("schema_version") != CALIBRATION_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported calibration.json schema_version "
            f"{payload.get('schema_version')!r} in {path}; expected "
            f"{CALIBRATION_SCHEMA_VERSION}"
        )
    if "backlash" not in payload:
        raise ValueError(f"{path} missing backlash section")
    return _validate_backlash(payload["backlash"], path=path)


def load(
    limits_path: str | Path | None = None,
    calibration_path: str | Path | None = None,
) -> dict[str, Any]:
    """Load active stage limits and calibrated backlash."""
    selected_limits = (
        Path(limits_path) if limits_path is not None else current_path()
    )
    selected_calibration = (
        Path(calibration_path) if calibration_path is not None
        else default_calibration_path()
    )

    limits = _read_limits(selected_limits)
    backlash = _read_backlash(selected_calibration)

    return {
        "stage_um": limits,
        "backlash": backlash,
    }


def write_limits(
    stage_um: dict[str, Any],
    path: str | Path | None = None,
) -> Path:
    """Write a stage limits file after validating the canonical schema."""
    selected = Path(path) if path is not None else current_path()
    limits = _validate_limits(stage_um, path=selected)
    _atomic_write_json(
        selected,
        {
            "schema_version": LIMITS_SCHEMA_VERSION,
            "stage_um": limits,
        },
    )
    return selected

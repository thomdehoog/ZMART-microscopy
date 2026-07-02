"""Load stage limits and calibrated backlash.

The physical stage envelope and the calibration backlash are machine state:
they resolve through the machine profile - the newest snapshot under
``C:\\ProgramData\\smart_microscopy\\...`` or the driver-bundled default (see
:mod:`navigator_expert.config.machine`). ``adopt_limits`` publishes a new
physical-envelope snapshot from the ``set_stage_limits`` notebook.

The per-run *working* envelope (boundary-marker / scan-field limits) is not
machine state - it belongs to the acquisition workflow, above the vendor
driver - so it is not resolved here. The legacy ``current_path`` /
``write_limits`` helpers remain only until that lift into the workflow lands.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..calibration.core.model import SCHEMA_VERSION as CALIBRATION_SCHEMA_VERSION

LIMITS_SCHEMA_VERSION = 1
LIMITS_SOURCE_DEFAULTS = "defaults"
LIMITS_SOURCE_BOUNDARY_MARKERS = "boundary_markers"
LIMITS_SOURCE_CFG_FALLBACK = "cfg_fallback"
LIMITS_SOURCE_SCAN_FIELD = "scan_field"
LIMITS_SOURCE_MIGRATION = "migration"
LIMITS_SOURCES = frozenset(
    {
        LIMITS_SOURCE_DEFAULTS,
        LIMITS_SOURCE_BOUNDARY_MARKERS,
        LIMITS_SOURCE_CFG_FALLBACK,
        LIMITS_SOURCE_SCAN_FIELD,
        LIMITS_SOURCE_MIGRATION,
    }
)

_REQUIRED_AXES = ("x", "y", "z_galvo", "z_wide")
_REQUIRED_BACKLASH = (
    "approach",
    "overshoot_um",
    "settle_ms",
    "tolerance_um",
    "session_id",
)


def _driver_root() -> Path:
    return Path(__file__).resolve().parents[1]


def limits_root() -> Path:
    return _driver_root() / "limits"


def current_path() -> Path:
    """Path to the per-run working-envelope limits config.

    This is per-run data (target acquisition writes it from boundary markers),
    not machine state. It stays under the driver tree for now; a later increment
    relocates it to the acquisition run output.
    """
    return limits_root() / "current.json"


def defaults_path() -> Path:
    """Path to the active physical stage envelope.

    Resolves through the machine profile: the newest ProgramData snapshot's
    ``limits.json``, or the driver-bundled default when no snapshot exists.
    """
    from ..config.machine import MACHINE

    return MACHINE.limits_path()


def default_calibration_path() -> Path:
    """Path to the active calibration config (machine snapshot / bundled default)."""
    from ..config.machine import MACHINE

    return MACHINE.calibration_path()


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
            raise ValueError(f"{path} stage limit {axis!r} must be [min, max], got {values!r}")
        low, high = float(values[0]), float(values[1])
        if low > high:
            raise ValueError(f"{path} stage limit {axis!r} has min > max: {values!r}")
        out[axis] = [low, high]
    return out


def _validate_source(source: Any, *, path: Path | None = None) -> str:
    if not isinstance(source, str) or not source:
        where = f"{path} " if path is not None else ""
        raise ValueError(f"{where}source must be a non-empty string")
    if source not in LIMITS_SOURCES:
        where = f"{path} " if path is not None else ""
        allowed = ", ".join(sorted(LIMITS_SOURCES))
        raise ValueError(f"{where}source {source!r} is not one of: {allowed}")
    return source


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
            f"unsupported limits.json schema_version {payload.get('schema_version')!r} in {path}"
        )
    if "stage_um" not in payload:
        raise ValueError(f"{path} missing stage_um section")
    _validate_source(payload.get("source"), path=path)
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
    """Load stage limits and calibrated backlash.

    Without an explicit ``limits_path``, this reads the configured physical
    envelope via ``defaults_path()`` (the machine limits snapshot, falling
    back to the bundled ``defaults/limits.json``). Use ``current_path()``
    explicitly for the active target-acquisition working envelope.
    """
    selected_limits = Path(limits_path) if limits_path is not None else defaults_path()
    selected_calibration = (
        Path(calibration_path) if calibration_path is not None else default_calibration_path()
    )

    limits = _read_limits(selected_limits)
    backlash = _read_backlash(selected_calibration)

    return {
        "stage_um": limits,
        "backlash": backlash,
    }


def write_limits(
    stage_um: dict[str, Any],
    *,
    source: str,
    path: str | Path | None = None,
) -> Path:
    """Write a stage limits file after validating the canonical schema."""
    source = _validate_source(source)
    selected = Path(path) if path is not None else current_path()
    limits = _validate_limits(stage_um, path=selected)
    _atomic_write_json(
        selected,
        {
            "schema_version": LIMITS_SCHEMA_VERSION,
            "source": source,
            "stage_um": limits,
        },
    )
    return selected


def adopt_limits(
    stage_um: dict[str, Any],
    *,
    source: str = LIMITS_SOURCE_DEFAULTS,
    machine: Any = None,
    moment: datetime | None = None,
    notebook_paths: Any = (),
) -> dict:
    """Publish a new machine snapshot holding an updated physical stage envelope.

    Validates *stage_um* against the limits schema, carries the latest snapshot's
    calibration forward untouched, and publishes a copy-forward snapshot whose
    ``limits.json`` is the new physical envelope. This is the writer for the
    ``set_stage_limits`` notebook - the hardware envelope only, never the per-run
    working envelope (which is the workflow's concern).

    Args:
        stage_um: ``{"x": [min, max], "y": ..., "z_galvo": ..., "z_wide": ...}``.
        source: Provenance tag (defaults to ``"defaults"``, the configured
            physical baseline).
        machine: ``MachineProfile`` to publish into; ``None`` uses the global one.
        moment: Snapshot timestamp; ``None`` uses ``datetime.now(timezone.utc)``.
        notebook_paths: Executed notebook(s) to archive in the snapshot.

    Returns:
        ``{"snapshot": str, "limits_path": str}``.
    """
    validated = _validate_limits(stage_um, path=Path("limits.json"))
    payload = {
        "schema_version": LIMITS_SCHEMA_VERSION,
        "source": _validate_source(source),
        "stage_um": validated,
    }
    if machine is None:
        from ..config.machine import MACHINE

        machine = MACHINE
    if moment is None:
        moment = datetime.now(timezone.utc)
    snapshot = machine.publish_snapshot(
        moment,
        limits=payload,
        notebook_paths=notebook_paths,
    )
    return {"snapshot": str(snapshot), "limits_path": str(snapshot / "limits.json")}

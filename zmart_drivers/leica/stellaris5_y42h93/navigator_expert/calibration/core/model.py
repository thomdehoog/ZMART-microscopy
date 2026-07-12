"""Load and apply the current objective calibration.

The calibration is resolved through the machine profile - the newest ProgramData
snapshot under ``C:\\ProgramData\\zmart-microscopy\\...``. Repo defaults seed
ProgramData on first use; runtime reads and writes stay machine-local. The schema keeps only
consumer-facing state: one objective translation triple per slot. The rig's
image->stage orientation is a separate concern owned by
:mod:`navigator_expert.orientation` (measured by the ``set_orientation``
notebook, applied at save time), not part of this calibration. Diagnostic
sub-deltas from calibration sessions stay in the session reports instead of the
canonical JSON.

Backlash is a plain motion utility with baked-in default params (decision §2b,
:mod:`navigator_expert.motion.movement`), not calibration state. It is no
longer part of the schema. A ``backlash`` block left over in an older
machine-local ``calibration.json`` is tolerated (ignored), not rejected, so an
existing file keeps loading without a re-adopt.
"""

from __future__ import annotations

import json
import math
import os
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 12


class OldSchemaError(ValueError):
    """Raised when a calibration file is an older, unsupported schema."""


def default_path(calibration_name: str | None = None) -> Path:
    """Path to the active calibration config.

    Resolves through the machine profile: the newest ProgramData snapshot for
    this microscope, seeding it from repo defaults when needed.
    ``calibration_name`` selects ``calibrations/<name>/calibration.json`` in the
    snapshot; omitting it uses ``ZMART_CALIBRATION_NAME`` when set, otherwise
    the legacy/default flat ``calibration.json``.
    """
    from ...config.machine import MACHINE

    return MACHINE.calibration_path(calibration_name)


def now_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _atomic_write_json(path: str | Path, obj: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(str(tmp), str(path))


def _old_schema_message(version: Any) -> str:
    return (
        f"calibration.json is at schema v{version}; this driver expects "
        f"v{SCHEMA_VERSION}. Re-run the calibration notebooks to publish a "
        f"v{SCHEMA_VERSION} snapshot."
    )


def _require_block(cfg: dict[str, Any], key: str) -> dict[str, Any]:
    value = cfg.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"calibration config is missing {key!r} block")
    return value


def _validate_schema_version(cfg: dict[str, Any], path: Path) -> None:
    version = cfg.get("schema_version")
    if version == SCHEMA_VERSION:
        return
    if isinstance(version, int) and version < SCHEMA_VERSION:
        raise OldSchemaError(_old_schema_message(version))
    raise ValueError(
        f"unsupported calibration.json schema_version {version!r} in {path}; "
        f"expected {SCHEMA_VERSION}"
    )


def validate_calibration(config: dict[str, Any]) -> None:
    """Validate the canonical calibration schema."""
    get_reference_slot(config)

    objectives = _require_block(config, "objectives")
    for slot, entry in objectives.items():
        if not isinstance(entry, dict):
            raise ValueError(f"calibration objective {slot!r} must be an object")
        translation = get_translation_um(config, int(slot))
        # NaN or infinity here would silently poison every frame coordinate
        # computed from this slot (NaN spreads through arithmetic without
        # raising), so a non-finite offset is rejected at validation time.
        if not all(math.isfinite(v) for v in translation):
            raise ValueError(
                f"calibration objective {slot!r} has a non-finite translation_um "
                f"{list(translation)!r}; every offset must be a real, finite "
                "number — re-run the calibration notebooks for this slot"
            )
        for key in ("name", "session_id"):
            if key not in entry:
                raise ValueError(f"calibration objective {slot!r} missing field: {key!r}")

    # No backlash block: backlash is a motion utility with baked-in defaults
    # (decision §2b), not calibration state. A stray ``backlash`` key in an
    # older machine-local file is ignored, not validated.


def load_calibration(
    path: str | Path | None = None,
    *,
    calibration_name: str | None = None,
) -> dict[str, Any]:
    """Load calibration.json without mutating it.

    Old schemas raise :class:`OldSchemaError`; the operator re-runs the
    calibration notebooks to publish a current-schema snapshot.
    """
    if path is not None and calibration_name is not None:
        raise ValueError("pass either path or calibration_name, not both")
    current = Path(path) if path is not None else default_path(calibration_name)
    if not current.exists():
        raise FileNotFoundError(f"calibration config not found: {current}")
    with current.open(encoding="utf-8") as fh:
        cfg = json.load(fh)
    _validate_schema_version(cfg, current)
    validate_calibration(cfg)
    return cfg


def prepared_calibration(
    config: dict[str, Any],
    *,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Return a validated, write-ready copy of *config* (bumps ``last_updated``).

    Shared by :func:`save_calibration` and the snapshot writer so a calibration
    is validated identically no matter where it is persisted. *path* is only
    used to label validation errors.
    """
    cfg = deepcopy(config)
    cfg["last_updated"] = now_timestamp()
    label = Path(path) if path is not None else Path("calibration.json")
    _validate_schema_version(cfg, label)
    validate_calibration(cfg)
    return cfg


def save_calibration(
    config: dict[str, Any],
    *,
    path: str | Path | None = None,
    calibration_name: str | None = None,
) -> Path:
    """Write the current calibration config atomically and bump timestamp."""
    if path is not None and calibration_name is not None:
        raise ValueError("pass either path or calibration_name, not both")
    current = Path(path) if path is not None else default_path(calibration_name)
    cfg = prepared_calibration(config, path=current)
    _atomic_write_json(current, cfg)
    return current


def update_objective(
    config: dict[str, Any],
    slot: int,
    *,
    name: str | None = None,
    translation_um: tuple[float, float, float] | list[float] | None = None,
    session_id: str | None = None,
) -> None:
    """Incrementally update an objective entry."""
    objectives = config.setdefault("objectives", {})
    key = str(int(slot))
    entry = objectives.get(key)
    if entry is None:
        if name is None:
            raise ValueError(f"cannot create objective slot {slot} without a name")
        entry = {}
        objectives[key] = entry
    if name is not None:
        entry["name"] = name
    if translation_um is not None:
        if len(translation_um) != 3:
            raise ValueError(f"translation_um must have 3 values, got {translation_um!r}")
        entry["translation_um"] = [
            float(translation_um[0]),
            float(translation_um[1]),
            float(translation_um[2]),
        ]
    if session_id is not None:
        entry["session_id"] = session_id


def _entry(config: dict[str, Any], slot: int) -> dict[str, Any]:
    entry = (config.get("objectives") or {}).get(str(int(slot)))
    if entry is None:
        available = sorted(int(s) for s in config.get("objectives", {}))
        raise ValueError(f"No calibration entry for slot {slot}. Available: {available}")
    return entry


def get_translation_um(config: dict[str, Any], slot: int) -> tuple[float, float, float]:
    """Return the objective translation triple for ``slot`` in micrometres."""
    value = _entry(config, slot).get("translation_um")
    if value is None:
        raise ValueError(
            f"Slot {slot} has no translation_um. Run the calibration "
            "notebooks and adopt the config."
        )
    if len(value) != 3:
        raise ValueError(f"Slot {slot} translation_um must have 3 values, got {value!r}")
    return float(value[0]), float(value[1]), float(value[2])


def get_reference_slot(config: dict[str, Any]) -> int:
    """The reference (origin) objective slot -- the one at translation [0, 0, 0].

    There is no privileged, operator-specified reference: translations are
    relative, so the origin is simply whichever objective reads [0, 0, 0] (the
    first objective calibrated on a fresh config). Derived from the data, not
    stored.
    """
    refs = []
    for slot, entry in (config.get("objectives") or {}).items():
        value = entry.get("translation_um")
        if value is None:
            continue
        if len(value) == 3 and all(float(v) == 0.0 for v in value):
            refs.append(int(slot))
    if not refs:
        raise ValueError(
            "calibration config has no reference objective: no entry has "
            "translation_um == [0, 0, 0]"
        )
    if len(refs) > 1:
        raise ValueError(f"calibration config has multiple zero-translation references: {refs}")
    return refs[0]

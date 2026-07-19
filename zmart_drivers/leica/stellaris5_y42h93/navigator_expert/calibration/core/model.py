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
:mod:`navigator_expert.commands.routines`), not calibration state. It is no
longer part of the schema. A ``backlash`` block left over in an older
machine-local ``calibration.json`` is tolerated (ignored), not rejected, so an
existing file keeps loading without a re-adopt.
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 13
_LEGACY_SCHEMA_VERSION = 12


class OldSchemaError(ValueError):
    """Raised when a calibration file is an older, unsupported schema."""


def default_path(calibration_name: str | None = None) -> Path:
    """Path to the active calibration config.

    Resolves through the machine profile: the newest calibration timestamp for
    this microscope, seeding the calibration tree from repo defaults when needed.
    ``calibration_name`` selects ``calibrations/<name>/calibration.json`` in the
    snapshot; omitting it uses ``ZMART_CALIBRATION_NAME`` when set, otherwise
    the legacy/default flat ``calibration.json``.
    """
    from ...config.machine import MACHINE

    return MACHINE.calibration_path(calibration_name)


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


def _upgrade_schema(cfg: dict[str, Any], path: Path) -> dict[str, Any]:
    """Return the current minimal schema, upgrading metadata-only v12 files."""
    cfg = deepcopy(cfg)
    version = cfg.get("schema_version")
    if version == SCHEMA_VERSION:
        return cfg
    if version == _LEGACY_SCHEMA_VERSION:
        objectives = cfg.get("objectives") or {}
        measured = any(entry.get("session_id") for entry in objectives.values())
        for entry in objectives.values():
            entry.pop("session_id", None)
            if not measured:
                entry.pop("translation_um", None)
        cfg.pop("last_updated", None)
        cfg.pop("backlash", None)
        cfg["schema_version"] = SCHEMA_VERSION
        return cfg
    if isinstance(version, int) and version < SCHEMA_VERSION:
        raise OldSchemaError(_old_schema_message(version))
    raise ValueError(
        f"unsupported calibration.json schema_version {version!r} in {path}; "
        f"expected {SCHEMA_VERSION}"
    )


def validate_calibration(config: dict[str, Any]) -> None:
    """Validate the canonical calibration schema.

    A config with no objectives, and entries that carry only a name (no
    ``translation_um``), are both legal. The zero-reference rule applies as
    soon as any entry has a translation.
    """
    extra_top_level = set(config) - {"schema_version", "objectives"}
    if extra_top_level:
        raise ValueError(f"calibration config has unsupported fields: {sorted(extra_top_level)}")
    objectives = _require_block(config, "objectives")
    if any(entry.get("translation_um") is not None for entry in objectives.values()):
        get_reference_slot(config)

    for slot, entry in objectives.items():
        if not isinstance(entry, dict):
            raise ValueError(f"calibration objective {slot!r} must be an object")
        if entry.get("translation_um") is not None:
            get_translation_um(config, int(slot))
        if "name" not in entry:
            raise ValueError(f"calibration objective {slot!r} missing field: 'name'")
        extra = set(entry) - {"name", "translation_um"}
        if extra:
            raise ValueError(
                f"calibration objective {slot!r} has unsupported fields: {sorted(extra)}"
            )

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
        raw = json.load(fh)
    cfg = _upgrade_schema(raw, current)
    validate_calibration(cfg)
    return cfg


def prepared_calibration(
    config: dict[str, Any],
    *,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Return a validated, write-ready copy of *config*.

    Shared by :func:`save_calibration` and the snapshot writer so a calibration
    is validated identically no matter where it is persisted. *path* is only
    used to label validation errors.
    """
    label = Path(path) if path is not None else Path("calibration.json")
    cfg = _upgrade_schema(config, label)
    validate_calibration(cfg)
    return cfg


def save_calibration(
    config: dict[str, Any],
    *,
    path: str | Path | None = None,
    calibration_name: str | None = None,
) -> Path:
    """Write the current calibration config atomically."""
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


def load_translations(calibration_name: str | None = None) -> dict[int, tuple[float, float, float]]:
    """Per-slot objective translations (micrometres) from the active calibration.

    Resolves the machine-local ``calibration.json`` (or the named set selected
    by ``calibration_name`` / the ``ZMART_CALIBRATION_NAME`` environment
    variable), and returns ``{slot: (x, y, z)}`` for every objective it lists.
    Raises on any IO/schema problem; callers that must not fail the connection
    wrap this and degrade to ``None`` instead.
    """
    config = load_calibration(calibration_name=calibration_name)
    return {
        int(slot): get_translation_um(config, int(slot))
        for slot, entry in (config.get("objectives") or {}).items()
        if entry.get("translation_um") is not None
    }


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


def set_reference(config: dict[str, Any], new_ref_slot: int) -> None:
    """Re-origin all objective translations around ``new_ref_slot``.

    Subtracts ``new_ref_slot``'s translation from every objective, so it becomes
    the [0, 0, 0] origin. The reference is derived from the data (the zero
    entry), never stored.
    """
    ref = get_translation_um(config, new_ref_slot)
    for entry in (config.get("objectives") or {}).values():
        value = entry.get("translation_um")
        if value is None:
            continue
        entry["translation_um"] = [
            float(value[0]) - ref[0],
            float(value[1]) - ref[1],
            float(value[2]) - ref[2],
        ]
    get_reference_slot(config)  # sanity: exactly one zero entry now


def translate_xy_between_objectives(
    x_um: float,
    y_um: float,
    config: dict[str, Any],
    *,
    from_slot: int,
    to_slot: int,
) -> tuple[float, float]:
    """Translate stage XY from one objective frame to another."""
    dx_from, dy_from, _ = get_translation_um(config, from_slot)
    dx_to, dy_to, _ = get_translation_um(config, to_slot)
    return (
        float(x_um) + (dx_to - dx_from),
        float(y_um) + (dy_to - dy_from),
    )


def translate_z_between_objectives(
    z_um: float,
    config: dict[str, Any],
    *,
    from_slot: int,
    to_slot: int,
) -> float:
    """Translate z-wide from one objective frame to another."""
    *_, dz_from = get_translation_um(config, from_slot)
    *_, dz_to = get_translation_um(config, to_slot)
    return float(z_um) + (dz_to - dz_from)


def translate_xyz_between_objectives(
    x_um: float,
    y_um: float,
    z_um: float,
    config: dict[str, Any],
    *,
    from_slot: int,
    to_slot: int,
) -> tuple[float, float, float]:
    """Translate full stage coordinates between objective frames."""
    x_t, y_t = translate_xy_between_objectives(
        x_um,
        y_um,
        config,
        from_slot=from_slot,
        to_slot=to_slot,
    )
    z_t = translate_z_between_objectives(
        z_um,
        config,
        from_slot=from_slot,
        to_slot=to_slot,
    )
    return x_t, y_t, z_t

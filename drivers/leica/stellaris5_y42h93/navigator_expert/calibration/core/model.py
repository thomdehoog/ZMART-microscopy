"""Load and apply the current objective calibration.

The canonical calibration file is
``drivers/leica/stellaris5_y42h93/navigator_expert/calibration/current/calibration.json``.
Schema v11 keeps only consumer-facing state: the image-to-stage matrix,
one objective translation triple per slot, and calibrated backlash
parameters. Diagnostic sub-deltas from calibration sessions stay in the
session reports instead of the canonical JSON.
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 11
MIGRATION_COMMAND = (
    "python -m navigator_expert.calibration.migrate_current_calibration"
)


class OldSchemaError(ValueError):
    """Raised when a calibration file needs the explicit migration step."""


def default_path() -> Path:
    """Path to the active calibration config.

    Resolves through the machine profile: the newest ProgramData snapshot for
    this microscope, or the driver-bundled default when no snapshot exists
    (see :mod:`navigator_expert.config.machine`). Deferred import keeps this
    module import-light.
    """
    from ...config.machine import MACHINE

    return MACHINE.calibration_path()


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
        f"calibration.json is at schema v{version}; this code expects "
        f"v{SCHEMA_VERSION}. Run `{MIGRATION_COMMAND}` to migrate. "
        "The migration is reversible via `git revert` on the migration "
        "commit."
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
    """Validate the v11 canonical calibration schema."""
    get_image_to_stage(config)
    get_reference_slot(config)

    objectives = _require_block(config, "objectives")
    for slot, entry in objectives.items():
        if not isinstance(entry, dict):
            raise ValueError(f"calibration objective {slot!r} must be an object")
        get_translation_um(config, int(slot))
        for key in ("name", "session_id"):
            if key not in entry:
                raise ValueError(f"calibration objective {slot!r} missing field: {key!r}")

    backlash = _require_block(config, "backlash")
    for key in (
        "approach",
        "overshoot_um",
        "settle_ms",
        "tolerance_um",
        "session_id",
    ):
        if key not in backlash:
            raise ValueError(f"calibration backlash missing field: {key!r}")
    float(backlash["overshoot_um"])
    int(backlash["settle_ms"])
    float(backlash["tolerance_um"])


def load_calibration(path: str | Path | None = None) -> dict[str, Any]:
    """Load calibration.json without mutating it.

    Old schemas raise :class:`OldSchemaError`; migration is an explicit
    operator action handled by ``migrate_current_calibration.py``.
    """
    current = Path(path) if path is not None else default_path()
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
) -> Path:
    """Write the current calibration config atomically and bump timestamp."""
    current = Path(path) if path is not None else default_path()
    cfg = prepared_calibration(config, path=current)
    _atomic_write_json(current, cfg)
    return current


def set_image_to_stage(
    config: dict[str, Any],
    matrix: list[list[float]],
    *,
    session_id: str | None = None,
) -> None:
    """Set the 2x2 image-to-stage Jacobian."""
    config["image_to_stage"] = {
        "matrix": [
            [float(matrix[0][0]), float(matrix[0][1])],
            [float(matrix[1][0]), float(matrix[1][1])],
        ],
        "session_id": session_id,
    }


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


def get_image_to_stage(config: dict[str, Any]) -> list[list[float]]:
    """Return the 2x2 image-to-stage matrix as floats."""
    block = config.get("image_to_stage")
    if not isinstance(block, dict):
        raise ValueError(
            "calibration config is missing v11 image_to_stage block with matrix/session_id"
        )
    matrix = block.get("matrix")
    if matrix is None:
        raise ValueError("calibration config is missing image_to_stage.matrix")
    if len(matrix) != 2 or any(len(row) != 2 for row in matrix):
        raise ValueError(f"image_to_stage.matrix must be 2x2, got {matrix!r}")
    return [
        [float(matrix[0][0]), float(matrix[0][1])],
        [float(matrix[1][0]), float(matrix[1][1])],
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


def get_reference_slot_from_data(config: dict[str, Any]) -> int:
    """Derive the reference slot from the zero translation entry."""
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


def get_reference_slot(config: dict[str, Any]) -> int:
    """Return and validate the cached reference objective slot."""
    if "reference_objective_slot" not in config:
        raise ValueError("calibration config is missing 'reference_objective_slot'")
    cached = int(config["reference_objective_slot"])
    derived = get_reference_slot_from_data(config)
    if cached != derived:
        raise ValueError(
            f"reference_objective_slot={cached} disagrees with zero-translation slot {derived}"
        )
    return cached


def set_reference(config: dict[str, Any], new_ref_slot: int) -> None:
    """Re-origin all objective translations around ``new_ref_slot``."""
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
    config["reference_objective_slot"] = int(new_ref_slot)
    get_reference_slot(config)


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


def reference_to_objective_command_xy(
    x_ref_um: float,
    y_ref_um: float,
    config: dict[str, Any],
    target_slot: int,
) -> tuple[float, float]:
    """Translate a reference-frame XY to a command under ``target_slot``."""
    return translate_xy_between_objectives(
        x_ref_um,
        y_ref_um,
        config,
        from_slot=get_reference_slot(config),
        to_slot=target_slot,
    )


def pixel_to_stage_xy_um(
    px: float,
    py: float,
    stage_xy_um: tuple[float, float],
    pixel_size_um: float,
    image_size: int,
    config: dict[str, Any],
) -> tuple[float, float]:
    """Convert image pixel coordinates to absolute stage XY in micrometres."""
    matrix = get_image_to_stage(config)
    centre = image_size / 2.0
    dx_image_um = (px - centre) * pixel_size_um
    dy_image_um = (py - centre) * pixel_size_um

    stage_dx = matrix[0][0] * dx_image_um + matrix[0][1] * dy_image_um
    stage_dy = matrix[1][0] * dx_image_um + matrix[1][1] * dy_image_um

    return float(stage_xy_um[0]) + stage_dx, float(stage_xy_um[1]) + stage_dy

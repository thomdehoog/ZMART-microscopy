"""Explicit migration for Leica Navigator Expert current calibration files.

This script converts the current v9 ``calibration.json`` plus v1
``stage.json`` pair into v11 ``current/calibration.json`` plus v1
``microscopes/limits/vendor/leica/navigator_expert/current.json``. Loading calibration
data never performs this migration implicitly; run this script as an
intentional source-tree change.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

TARGET_CALIBRATION_SCHEMA = 11
TARGET_LIMITS_SCHEMA = 1
SOURCE_CALIBRATION_SCHEMA = 9
SOURCE_STAGE_SCHEMA = 1
LIMITS_SOURCE_MIGRATION = "migration"


def current_root() -> Path:
    return Path(__file__).resolve().parent / "current"


def limits_root() -> Path:
    repo_root = Path(__file__).resolve().parents[4]
    return repo_root / "limits" / "vendor" / "leica" / "navigator_expert"


def current_limits_path() -> Path:
    return limits_root() / "current.json"


def now_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


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


def _is_current_limits(limits_path: Path) -> bool:
    if not limits_path.exists():
        return False
    limits = _read_json(limits_path)
    return (
        limits.get("schema_version") == TARGET_LIMITS_SCHEMA
        and isinstance(limits.get("stage_um"), dict)
        and isinstance(limits.get("source"), str)
        and bool(limits.get("source"))
    )


def _is_target_state(calibration: dict[str, Any], limits_path: Path) -> bool:
    return calibration.get("schema_version") == TARGET_CALIBRATION_SCHEMA and _is_current_limits(
        limits_path
    )


def _translation_from_v9(entry: dict[str, Any]) -> list[float]:
    shift_xy = entry["shift_xy_um"]
    return [
        float(shift_xy[0]),
        float(shift_xy[1]),
        float(entry["offset_z_um"]) + float(entry["shift_z_um"]),
    ]


def _reference_slot_from_data(calibration: dict[str, Any]) -> int:
    refs = []
    for slot, entry in calibration["objectives"].items():
        value = entry["translation_um"]
        if all(float(v) == 0.0 for v in value):
            refs.append(int(slot))
    if len(refs) != 1:
        raise ValueError(f"expected exactly one zero-translation reference slot, found {refs}")
    return refs[0]


def build_v11_calibration(
    calibration_v9: dict[str, Any],
    stage_v1: dict[str, Any],
    *,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Build the v11 calibration payload without writing files."""
    if calibration_v9.get("schema_version") != SOURCE_CALIBRATION_SCHEMA:
        raise ValueError(
            f"expected calibration schema v{SOURCE_CALIBRATION_SCHEMA}, got "
            f"{calibration_v9.get('schema_version')!r}"
        )
    if stage_v1.get("schema_version") != SOURCE_STAGE_SCHEMA:
        raise ValueError(
            f"expected stage schema v{SOURCE_STAGE_SCHEMA}, got {stage_v1.get('schema_version')!r}"
        )
    if "limits_um" not in stage_v1 or "backlash" not in stage_v1:
        raise ValueError("stage.json must contain limits_um and backlash")

    objectives = {}
    for slot, entry in calibration_v9.get("objectives", {}).items():
        objectives[str(int(slot))] = {
            "name": entry.get("name", ""),
            "translation_um": _translation_from_v9(entry),
            "session_id": None,
        }

    payload = {
        "schema_version": TARGET_CALIBRATION_SCHEMA,
        "last_updated": timestamp or now_timestamp(),
        "reference_objective_slot": int(calibration_v9["reference_objective_slot"]),
        "image_to_stage": {
            "matrix": calibration_v9["image_to_stage"],
            "session_id": None,
        },
        "objectives": objectives,
        "backlash": {
            **stage_v1["backlash"],
            "session_id": None,
        },
    }

    derived_ref = _reference_slot_from_data(payload)
    if int(payload["reference_objective_slot"]) != derived_ref:
        raise ValueError(
            "reference_objective_slot does not match zero translation: "
            f"{payload['reference_objective_slot']} != {derived_ref}"
        )
    return payload


def build_limits_v1(stage_v1: dict[str, Any]) -> dict[str, Any]:
    """Build the limits payload from legacy stage.json."""
    if stage_v1.get("schema_version") != SOURCE_STAGE_SCHEMA:
        raise ValueError(
            f"expected stage schema v{SOURCE_STAGE_SCHEMA}, got {stage_v1.get('schema_version')!r}"
        )
    return {
        "schema_version": TARGET_LIMITS_SCHEMA,
        "source": LIMITS_SOURCE_MIGRATION,
        "stage_um": stage_v1["limits_um"],
    }


def migrate(
    root: Path | None = None,
    limits_path: Path | None = None,
) -> dict[str, Path | str]:
    """Migrate ``root`` and return paths plus a status string."""
    root = Path(root) if root is not None else current_root()
    calibration_path = root / "calibration.json"
    stage_path = root / "stage.json"
    selected_limits_path = Path(limits_path) if limits_path is not None else current_limits_path()

    calibration = _read_json(calibration_path)
    if _is_target_state(calibration, selected_limits_path):
        if stage_path.exists():
            stage_path.unlink()
        return {
            "status": "already current",
            "calibration_path": calibration_path,
            "limits_path": selected_limits_path,
        }

    version = calibration.get("schema_version")
    if version == TARGET_CALIBRATION_SCHEMA:
        if not stage_path.exists():
            raise FileNotFoundError(
                "calibration.json is already v"
                f"{TARGET_CALIBRATION_SCHEMA}, but current limits are missing "
                f"or invalid and {stage_path} is not available to rebuild it."
            )
        stage = _read_json(stage_path)
        limits = build_limits_v1(stage)
        _atomic_write_json(selected_limits_path, limits)
        stage_path.unlink()
        return {
            "status": (
                f"Recovered v{TARGET_CALIBRATION_SCHEMA} calibration by "
                "writing current limits and removing stage.json."
            ),
            "calibration_path": calibration_path,
            "limits_path": selected_limits_path,
        }

    if version != SOURCE_CALIBRATION_SCHEMA:
        raise ValueError(
            f"unsupported calibration schema "
            f"{version!r}; expected "
            f"{SOURCE_CALIBRATION_SCHEMA} or {TARGET_CALIBRATION_SCHEMA}"
        )
    if not stage_path.exists():
        raise FileNotFoundError(
            f"cannot migrate calibration schema v{SOURCE_CALIBRATION_SCHEMA}: missing {stage_path}"
        )

    stage = _read_json(stage_path)
    migrated = build_v11_calibration(calibration, stage)
    limits = build_limits_v1(stage)

    _atomic_write_json(selected_limits_path, limits)
    _atomic_write_json(calibration_path, migrated)
    stage_path.unlink()

    ref_slot = int(migrated["reference_objective_slot"])
    ref_name = migrated["objectives"][str(ref_slot)].get("name", "")
    return {
        "status": (
            f"Migrated to v{TARGET_CALIBRATION_SCHEMA}. "
            f"{len(migrated['objectives'])} objectives. "
            f"Reference: slot {ref_slot} ({ref_name})."
        ),
        "calibration_path": calibration_path,
        "limits_path": selected_limits_path,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--current-root",
        type=Path,
        default=current_root(),
        help="directory containing current calibration.json and stage.json",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = migrate(args.current_root)
    print(result["status"])
    print(f"calibration: {result['calibration_path']}")
    print(f"limits     : {result['limits_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

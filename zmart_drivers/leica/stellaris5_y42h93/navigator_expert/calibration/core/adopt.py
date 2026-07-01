"""Adopt a session-staging calibration into a machine snapshot.

Adoption is the explicit operator step that folds a trustworthy session staging
config into the microscope's calibration. It reads the current calibration - the
newest machine snapshot, or the driver-bundled default when there is none -
merges the one staged delta, and publishes a new cumulative snapshot via
:meth:`navigator_expert.config.machine.MachineProfile.publish_snapshot`
(copy-forward: the latest snapshot's ``calibration.json`` + ``limits.json`` are
carried forward, this adopt's ``calibration.json`` is overwritten, and the
executed notebook is archived alongside; the write is atomic). Save workflows
never adopt; this is the only path that writes a calibration snapshot.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import model as calibration_model
from .common import STAGING_SCHEMA_VERSION

_VALID_KINDS = {"image_to_stage", "objective_translation"}


def _expected_kind_for(staging_name: str) -> str | None:
    """Map a staging filename's prefix to the JSON ``kind`` it must carry.

    Returns ``None`` if the filename does not match a known prefix; the
    caller still gets the regular ``_VALID_KINDS`` check.
    """
    stem = staging_name[:-5] if staging_name.endswith(".json") else staging_name
    if stem == "image_to_stage":
        return "image_to_stage"
    if stem.startswith("objective_") and "_to_" in stem:
        return "objective_translation"
    return None


def _validate_staging_name(staging_name: str) -> None:
    if not staging_name:
        raise ValueError("staging_name must be a non-empty filename")
    if (
        "/" in staging_name
        or "\\" in staging_name
        or os.sep in staging_name
        or ".." in Path(staging_name).parts
    ):
        raise ValueError(f"staging_name must be a bare filename, got {staging_name!r}")


def _norm_label(value: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", value.lower()).strip("_")


def _contains_ordered_tokens(haystack: list[str], needle: list[str]) -> bool:
    if not needle:
        return False
    pos = 0
    for token in haystack:
        if token == needle[pos]:
            pos += 1
            if pos == len(needle):
                return True
    return False


def _objective_slot_for_label(config: dict[str, Any], label: str) -> int:
    target = _norm_label(label)
    target_tokens = target.split("_")
    matches: list[int] = []
    for slot, entry in (config.get("objectives") or {}).items():
        name = str(entry.get("name", ""))
        norm = _norm_label(name)
        tokens = norm.split("_")
        if target == norm or _contains_ordered_tokens(tokens, target_tokens):
            matches.append(int(slot))
    if len(matches) != 1:
        raise ValueError(f"objective label {label!r} matched slots {matches}; expected one")
    return matches[0]


def _apply_staging_payload(
    config: dict[str, Any], data: dict[str, Any], *, session_id: str
) -> None:
    kind = data["kind"]
    if kind == "image_to_stage":
        calibration_model.set_image_to_stage(
            config,
            data["image_to_stage"],
            session_id=session_id,
        )
        return

    from_slot = _objective_slot_for_label(config, data["from_objective"])
    to_slot = _objective_slot_for_label(config, data["to_objective"])
    base = calibration_model.get_translation_um(config, from_slot)
    translation_xy = data["translation_xy_um"]
    translation = [
        base[0] + float(translation_xy[0]),
        base[1] + float(translation_xy[1]),
        base[2] + float(data["translation_z_um"]),
    ]
    calibration_model.update_objective(
        config,
        to_slot,
        translation_um=translation,
        session_id=session_id,
    )


def _load_staging(session: Any, staging_name: str) -> tuple[Path, dict[str, Any]]:
    """Validate *staging_name* and load+validate its staging payload."""
    _validate_staging_name(staging_name)
    source = session.paths.configs_dir / staging_name
    if not source.exists():
        raise FileNotFoundError(
            "No staging config to adopt. Review the report. The "
            "measurement may have failed validation or weak voting."
        )
    data = json.loads(source.read_text(encoding="utf-8"))
    if data.get("schema_version") != STAGING_SCHEMA_VERSION:
        raise ValueError(
            f"staging config has unexpected schema_version "
            f"{data.get('schema_version')!r}; expected {STAGING_SCHEMA_VERSION}"
        )
    kind = data.get("kind")
    if kind not in _VALID_KINDS:
        raise ValueError(
            f"staging config has unsupported kind {kind!r}; expected one of {sorted(_VALID_KINDS)}"
        )
    expected = _expected_kind_for(staging_name)
    if expected is not None and kind != expected:
        raise ValueError(
            f"staging_name {staging_name!r} expects kind {expected!r}, "
            f"but the file declares kind {kind!r}; refusing to adopt a "
            "mismatched pair."
        )
    return source, data


def adopt_calibration(
    session: Any,
    staging_name: str,
    *,
    machine: Any = None,
    moment: datetime | None = None,
    notebook_paths: Any = (),
) -> dict:
    """Merge ``session.paths.configs_dir / staging_name`` and publish a snapshot.

    Args:
        session: A workflow session with ``.paths.configs_dir`` and ``.session_id``.
        staging_name: Bare filename inside the session's ``configs/`` folder.
        machine: ``MachineProfile`` to read the current calibration from and
            publish the snapshot into. ``None`` uses the global ``MACHINE``.
        moment: Snapshot timestamp; ``None`` uses ``datetime.now(timezone.utc)``.
            Must sort strictly after the latest snapshot (monotonic guard).
        notebook_paths: Executed notebook(s) to archive in the snapshot.

    Returns:
        ``{"source": str, "snapshot": str, "calibration_path": str}`` - the new
        snapshot folder and its ``calibration.json``.

    Raises:
        FileNotFoundError: if the staging file does not exist.
        ValueError: if the staging schema/kind is invalid, the staging_name is
            not a bare filename, or *moment* does not sort after the latest snapshot.
    """
    source, data = _load_staging(session, staging_name)

    if machine is None:
        from ...config.machine import MACHINE

        machine = MACHINE
    if moment is None:
        moment = datetime.now(timezone.utc)

    config = calibration_model.load_calibration(machine.calibration_path())
    _apply_staging_payload(
        config,
        data,
        session_id=getattr(session, "session_id", "unknown"),
    )
    prepared = calibration_model.prepared_calibration(config)
    snapshot = machine.publish_snapshot(
        moment,
        calibration=prepared,
        notebook_paths=notebook_paths,
    )

    return {
        "source": str(source),
        "snapshot": str(snapshot),
        "calibration_path": str(snapshot / "calibration.json"),
    }

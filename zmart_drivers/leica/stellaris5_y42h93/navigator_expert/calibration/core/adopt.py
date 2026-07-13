"""Adopt a session-staging calibration into its machine-owned timestamp tree.

Adoption is the explicit operator step that folds a trustworthy session staging
config into the microscope's calibration. It reads the current ProgramData
calibration, or the bundled default as seed material when ProgramData is empty,
merges the one staged delta, and publishes a new calibration snapshot via
:meth:`navigator_expert.config.machine.MachineProfile.publish_snapshot`.
Save workflows never adopt; this is the path that writes calibration snapshots.
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

_VALID_KINDS = {"objective_translation"}


def _expected_kind_for(staging_name: str) -> str | None:
    """Map a staging filename's prefix to the JSON ``kind`` it must carry.

    Returns ``None`` if the filename does not match a known prefix; the
    caller still gets the regular ``_VALID_KINDS`` check.
    """
    stem = staging_name[:-5] if staging_name.endswith(".json") else staging_name
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
    config: dict[str, Any],
    data: dict[str, Any],
    *,
    session_id: str,
    hardware_objectives: dict[int, str] | None = None,
) -> None:
    # An empty live name means "the hardware reported nothing usable" — treat
    # it like an absent slot so it can never erase the config's human-set name
    # (update_objective skips the name only when it is None).
    live_names = {
        slot: name for slot, name in (hardware_objectives or {}).items() if name and name.strip()
    }
    if data.get("from_slot") is not None or data.get("to_slot") is not None:
        if data.get("from_slot") is None or data.get("to_slot") is None:
            raise ValueError("staging config must provide both from_slot and to_slot")
        from_slot = int(data["from_slot"])
        to_slot = int(data["to_slot"])
        if from_slot == to_slot:
            raise ValueError("reference and target objective slots must differ")
        # Measurement-time API reads are authoritative. Carry their names into
        # the canonical config even when the prior file used stale labels.
        for slot, key in ((from_slot, "from_objective"), (to_slot, "to_objective")):
            name = str(data.get(key) or "").strip()
            if not name:
                raise ValueError(f"staging config missing measured objective name: {key}")
            live_names[slot] = name
    else:
        # Backward compatibility for staging files created before objective
        # slots were recorded directly from hardware.
        from_slot = _objective_slot_for_label(config, data["from_objective"])
        to_slot = _objective_slot_for_label(config, data["to_objective"])
        if from_slot == to_slot:
            raise ValueError("reference and target objective slots must differ")
    from_entry = (config.get("objectives") or {}).get(str(from_slot), {})
    # Refuse the two merges that would corrupt this calibration's origin, and
    # say so now with a way out — rather than failing later at publish time
    # with a schema message the operator cannot act on.
    try:
        stored_reference = calibration_model.get_reference_slot(config)
    except ValueError:
        stored_reference = None  # nothing calibrated yet: no origin to protect
    if stored_reference is not None:
        if to_slot == stored_reference:
            raise ValueError(
                f"the target objective (slot {to_slot}) is this calibration's "
                f"established zero-reference objective; adopting would overwrite "
                f"the origin every other objective is measured against. Measure "
                f"the pair the other way around (reference objective first), or "
                f"start a session under a new calibration_name to establish a "
                f"different reference objective."
            )
        if "translation_um" not in from_entry:
            raise ValueError(
                f"this measurement's reference objective (slot {from_slot}) is "
                f"not in the calibration being updated, so the new target cannot "
                f"be placed relative to the existing origin (slot "
                f"{stored_reference}). Measure from an objective this calibration "
                f"already covers, or start a session under a new calibration_name."
            )
    if "translation_um" in from_entry:
        # The FROM objective already has a position, so place the new one
        # relative to it -- this keeps every objective consistent with the same
        # origin.
        base = calibration_model.get_translation_um(config, from_slot)
        # Refresh its name from the live microscope and record this measuring
        # session as its provenance. The measurement re-establishes the FROM
        # objective on this microscope, so its entry must stop looking like an
        # untouched placeholder (placeholder entries carry no session_id and do
        # not count as calibrated in the driver's preflight verdict).
        calibration_model.update_objective(
            config,
            from_slot,
            name=live_names.get(from_slot),
            session_id=session_id,
        )
    else:
        # Nothing has been calibrated yet, so the first objective used becomes
        # the [0, 0, 0] origin. There is no privileged reference to pick;
        # objective positions are always relative to one another.
        calibration_model.update_objective(
            config,
            from_slot,
            translation_um=(0.0, 0.0, 0.0),
            name=live_names.get(from_slot),
            session_id=session_id,
        )
        base = (0.0, 0.0, 0.0)
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
        name=live_names.get(to_slot),
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


def _base_calibration_path(machine: Any, calibration_name: str | None) -> Path:
    latest = machine.latest_snapshot("calibration")
    if latest is None:
        return machine.bundled_default_path("calibration.json")
    snapshot = machine.ensure_snapshot("calibration")
    if calibration_name is not None:
        named = snapshot / machine.calibration_relpath(calibration_name)
        if named.exists():
            return named
    return snapshot / "calibration.json"


def adopt_calibration(
    session: Any,
    staging_name: str,
    *,
    calibration_name: str | None = None,
    machine: Any = None,
    moment: datetime | None = None,
    notebook_paths: Any = (),
) -> dict:
    """Merge ``session.paths.configs_dir / staging_name`` and publish a snapshot.

    Args:
        session: A workflow session with ``.paths.configs_dir`` and ``.session_id``.
        staging_name: Bare filename inside the session's ``configs/`` folder.
        calibration_name: Optional named calibration set to update under
            ``calibrations/<name>/calibration.json`` in the new machine snapshot.
            When omitted, ``session.calibration_name`` is used. If neither is
            set, the legacy/default flat ``calibration.json`` is updated.
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

    selected_name = calibration_name
    if selected_name is None:
        selected_name = getattr(session, "calibration_name", None)

    config = calibration_model.load_calibration(_base_calibration_path(machine, selected_name))
    _apply_staging_payload(
        config,
        data,
        session_id=getattr(session, "session_id", "unknown"),
        hardware_objectives=getattr(session, "hardware_objectives", None),
    )
    prepared = calibration_model.prepared_calibration(config)
    snapshot = machine.publish_snapshot(
        moment,
        calibration=prepared,
        calibration_name=selected_name,
        notebook_paths=notebook_paths,
    )
    calibration_rel = (
        machine.calibration_relpath(selected_name)
        if selected_name is not None
        else Path("calibration.json")
    )

    return {
        "source": str(source),
        "snapshot": str(snapshot),
        "calibration_name": selected_name,
        "calibration_path": str(snapshot / calibration_rel),
    }

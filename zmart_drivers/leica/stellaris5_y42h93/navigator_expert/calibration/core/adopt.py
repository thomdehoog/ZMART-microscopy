"""Compile objective-pair acquisitions and publish the result.

Each acquisition owns one report. The session-level ``calibration.json`` is a
derived file rebuilt from the trusted reports, so there is no second staging
payload that can disagree with the report. When several acquisitions in one
session measured the same target objective, only the newest report (by its
``created_at`` timestamp) is applied — re-measuring a pair supersedes the
earlier measurement no matter what the acquisition folders are named.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import model as calibration_model
from .common import STAGING_SCHEMA_VERSION

log = logging.getLogger(__name__)

_REPORT_NAME = "objective_pair_report.json"


def _apply_objective_pair(
    config: dict[str, Any],
    report: dict[str, Any],
    *,
    hardware_objectives: dict[int, str] | None = None,
) -> None:
    """Apply one trusted objective-pair report to *config*."""
    try:
        from_slot = int(report["from_slot"])
        to_slot = int(report["to_slot"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("objective-pair report requires integer from_slot and to_slot") from exc
    if from_slot == to_slot:
        raise ValueError("reference and target objective slots must differ")

    from_name = str(report.get("from_objective") or "").strip()
    to_name = str(report.get("to_objective") or "").strip()
    live_names = {
        int(slot): str(name).strip()
        for slot, name in (hardware_objectives or {}).items()
        if str(name).strip()
    }
    from_name = live_names.get(from_slot, from_name)
    to_name = live_names.get(to_slot, to_name)
    if not from_name or not to_name:
        raise ValueError("objective-pair report requires both measured objective names")

    translation_xy = report.get("translation_xy_um")
    if not isinstance(translation_xy, list) or len(translation_xy) != 2:
        raise ValueError("objective-pair report requires two translation_xy_um values")
    try:
        delta = (
            float(translation_xy[0]),
            float(translation_xy[1]),
            float(report["translation_z_um"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("objective-pair report contains invalid translation values") from exc

    objectives = config.get("objectives") or {}
    from_entry = objectives.get(str(from_slot), {})
    try:
        stored_reference = calibration_model.get_reference_slot(config)
    except ValueError:
        stored_reference = None

    if stored_reference is not None:
        if to_slot == stored_reference:
            raise ValueError(
                f"target slot {to_slot} is the established reference objective; "
                "measure this pair in the other direction"
            )
        if "translation_um" not in from_entry:
            raise ValueError(
                f"reference slot {from_slot} is not calibrated relative to the "
                f"established origin in slot {stored_reference}"
            )

    if "translation_um" in from_entry:
        base = calibration_model.get_translation_um(config, from_slot)
        calibration_model.update_objective(
            config,
            from_slot,
            name=from_name,
        )
    else:
        base = (0.0, 0.0, 0.0)
        calibration_model.update_objective(
            config,
            from_slot,
            name=from_name,
            translation_um=base,
        )

    calibration_model.update_objective(
        config,
        to_slot,
        name=to_name,
        translation_um=[base[i] + delta[i] for i in range(3)],
    )


def _trusted_reports(session: Any) -> list[tuple[Path, dict[str, Any]]]:
    """Load and validate this session's trusted acquisition reports."""
    session_root = Path(session.paths.session_root)
    loaded: list[tuple[Path, dict[str, Any]]] = []
    reference_slots: set[int] = set()

    for path in sorted(session_root.glob(f"*/reports/{_REPORT_NAME}")):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read acquisition report: {path}") from exc
        if report.get("schema_version") != STAGING_SCHEMA_VERSION:
            raise ValueError(f"unsupported acquisition report schema: {path}")
        if report.get("kind") != "objective_translation_report":
            raise ValueError(f"unexpected acquisition report kind: {path}")
        if report.get("session_id") != session.session_id:
            raise ValueError(f"acquisition report belongs to another session: {path}")
        if report.get("acquisition_name") != path.parent.parent.name:
            raise ValueError(f"acquisition report name does not match its folder: {path}")
        if not report.get("config_written"):
            continue
        try:
            reference_slots.add(int(report["from_slot"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"acquisition report has no valid reference slot: {path}") from exc
        loaded.append((path, report))

    if len(reference_slots) > 1:
        raise ValueError(
            "all acquisitions in one calibration session must use the same "
            f"reference slot; found {sorted(reference_slots)}"
        )

    # One measurement per target objective: the NEWEST trusted report wins,
    # judged by its created_at timestamp — never by what the acquisition
    # folder happened to be named. Without this, re-measuring a pair under
    # a new acquisition name left both reports in play and the
    # alphabetically-last folder silently won.
    newest: dict[int, tuple[Path, dict[str, Any]]] = {}
    for path, report in loaded:
        try:
            to_slot = int(report["to_slot"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"acquisition report has no valid target slot: {path}") from exc
        kept = newest.get(to_slot)
        if kept is None:
            newest[to_slot] = (path, report)
            continue
        if str(report.get("created_at") or "") > str(kept[1].get("created_at") or ""):
            log.info(
                "calibration for slot %d: %s supersedes older measurement %s",
                to_slot, path.parent.parent.name, kept[0].parent.parent.name,
            )
            newest[to_slot] = (path, report)
        else:
            log.info(
                "calibration for slot %d: keeping %s; %s is older and ignored",
                to_slot, kept[0].parent.parent.name, path.parent.parent.name,
            )
    return [newest[slot] for slot in sorted(newest)]


def compile_session_calibration(
    session: Any,
    *,
    allow_empty: bool = False,
    base_path: str | Path | None = None,
) -> Path | None:
    """Rebuild the objective pair's ``calibration.json`` from trusted reports."""
    destination = Path(session.paths.session_dir) / "calibration.json"
    reports = _trusted_reports(session)
    if not reports:
        destination.unlink(missing_ok=True)
        if allow_empty:
            return None
        raise FileNotFoundError(
            "No trusted objective-pair acquisition is available in this session."
        )

    source = Path(base_path) if base_path is not None else Path(session.calibration_path)
    config = calibration_model.load_calibration(source)
    for _path, report in reports:
        _apply_objective_pair(
            config,
            report,
            hardware_objectives=getattr(session, "hardware_objectives", None),
        )
    return calibration_model.save_calibration(config, path=destination)


def adopt_calibration(
    session: Any,
    *,
    calibration_name: str | None = None,
    machine: Any = None,
    moment: datetime | None = None,
    notebook_paths: Any = (),
) -> dict:
    """Compile all session acquisitions and publish the calibration snapshot."""
    if machine is None:
        from ...config.machine import MACHINE

        machine = MACHINE
    if moment is None:
        moment = datetime.now(timezone.utc)

    selected_name = calibration_name
    if selected_name is None:
        selected_name = getattr(session, "calibration_name", None)
    base_path = getattr(session, "calibration_path", None)
    if base_path is None:
        latest = machine.latest_snapshot("calibration")
        if latest is None:
            base_path = machine.bundled_default_path("calibration.json")
        else:
            named = (
                latest / machine.calibration_relpath(selected_name)
                if selected_name is not None
                else latest / "calibration.json"
            )
            base_path = named if named.exists() else latest / "calibration.json"
    source = compile_session_calibration(session, base_path=base_path)
    config = calibration_model.load_calibration(source)
    notebook_paths = tuple(notebook_paths)
    snapshot = machine.publish_snapshot(
        moment,
        calibration=config,
        calibration_name=selected_name,
        notebook_paths=notebook_paths,
    )
    for notebook_path in notebook_paths:
        notebook_path = Path(notebook_path)
        destination = Path(session.paths.session_dir) / "calibrate_objective_pair.ipynb"
        shutil.copy2(notebook_path, destination)
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

"""Adopt a session-staging calibration into the current folder.

Adoption is the explicit operator step that folds a trustworthy session
staging config into the operator-supplied current calibration file. Save
workflows never adopt; this module is the only writer of
``<current_root>/calibration.json``.

The operator passes ``current_root`` on every call. The workflow refuses
to guess a default: current config writes are too easy to overlook, and a
silent default would let a stale package-tree file become the truth.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

from .common import STAGING_SCHEMA_VERSION, now_iso
from . import model as calibration_model

_VALID_KINDS = {"image_to_stage", "objective_translation"}
_STAMP_SAFE = re.compile(r"[^0-9A-Za-z._-]+")


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


def _sanitize_stamp(value: str) -> str:
    cleaned = _STAMP_SAFE.sub("_", value.strip())
    return cleaned or "unknown"


def _validate_staging_name(staging_name: str) -> None:
    if not staging_name:
        raise ValueError("staging_name must be a non-empty filename")
    if (
        "/" in staging_name
        or "\\" in staging_name
        or os.sep in staging_name
        or ".." in Path(staging_name).parts
    ):
        raise ValueError(
            f"staging_name must be a bare filename, got {staging_name!r}"
        )


def _calibration_path(current_root: Path) -> Path:
    return current_root / "calibration.json"


def _archive_current(current_path: Path, archive_dir: Path) -> Path | None:
    if not current_path.exists():
        return None
    try:
        existing = json.loads(current_path.read_text(encoding="utf-8"))
        stamp_raw = existing.get("last_updated", "unknown")
    except Exception:
        stamp_raw = "unknown"
    stamp = _sanitize_stamp(stamp_raw)
    suffix = 0
    while True:
        name = (
            f"{stamp}_{current_path.name}"
            if suffix == 0
            else f"{stamp}_{suffix}_{current_path.name}"
        )
        candidate = archive_dir / name
        try:
            with current_path.open("rb") as src, candidate.open("xb") as dst:
                shutil.copyfileobj(src, dst)
            shutil.copystat(current_path, candidate)
            return candidate
        except FileExistsError:
            suffix += 1


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
        raise ValueError(
            f"objective label {label!r} matched slots {matches}; expected one"
        )
    return matches[0]


def _apply_staging_payload(config: dict[str, Any], data: dict[str, Any],
                           *, session_id: str) -> None:
    kind = data["kind"]
    if kind == "image_to_stage":
        calibration_model.set_image_to_stage(
            config, data["image_to_stage"], session_id=session_id,
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


def adopt_calibration(
    session: Any,
    staging_name: str,
    *,
    current_root: str | Path,
) -> dict:
    """Copy ``session.paths.configs_dir / staging_name`` into ``current_root``.

    Args:
        session: A workflow session with ``.paths.configs_dir`` and
            ``.session_id``.
        staging_name: Bare filename inside the session's ``configs/`` folder.
        current_root: Operator-supplied directory that holds the current
            calibration configs. Required.

    Returns:
        ``{"source": str, "current_path": str, "archived_previous": str | None}``.
        ``current_path`` is always the canonical ``calibration.json``.

    Raises:
        FileNotFoundError: if the staging file does not exist.
        ValueError: if the staging payload schema/kind is invalid or the
            staging_name is not a bare filename.
        RuntimeError: if the current_root or archive directory cannot be
            created.
    """
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
            f"{data.get('schema_version')!r}; expected "
            f"{STAGING_SCHEMA_VERSION}"
        )
    kind = data.get("kind")
    if kind not in _VALID_KINDS:
        raise ValueError(
            f"staging config has unsupported kind {kind!r}; "
            f"expected one of {sorted(_VALID_KINDS)}"
        )
    expected = _expected_kind_for(staging_name)
    if expected is not None and kind != expected:
        raise ValueError(
            f"staging_name {staging_name!r} expects kind {expected!r}, "
            f"but the file declares kind {kind!r}; refusing to adopt a "
            "mismatched pair."
        )

    resolved_root = Path(current_root).absolute()
    resolved_current = _calibration_path(resolved_root)
    try:
        resolved_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(
            f"cannot create current config directory {resolved_root}: {exc}"
        ) from exc

    archive_dir = resolved_root / "archive"
    try:
        archive_dir.mkdir(exist_ok=True)
    except OSError as exc:
        raise RuntimeError(
            f"cannot create archive directory {archive_dir}: {exc}"
        ) from exc

    config = calibration_model.load_calibration(resolved_current)
    _apply_staging_payload(
        config,
        data,
        session_id=getattr(session, "session_id", "unknown"),
    )
    archived = _archive_current(resolved_current, archive_dir)
    calibration_model.save_calibration(config, path=resolved_current)

    session_id = getattr(session, "session_id", "unknown")
    log_path = resolved_root / ".adopt.log"
    line = f"{now_iso()} {kind} {session_id} -> {resolved_current}\n"
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(line)

    return {
        "source": str(source),
        "current_path": str(resolved_current),
        "archived_previous": str(archived) if archived else None,
    }

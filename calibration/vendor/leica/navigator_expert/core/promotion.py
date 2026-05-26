"""Promote a session-staging calibration to the current folder.

Promotion is the explicit operator step that turns a session's
trustworthy staging config into a file inside the operator-supplied
``current_root``. Save workflows never promote; this module is the only
writer of ``<current_root>/<staging_name>``.

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

from .common import SCHEMA_VERSION, now_iso, write_json_atomic

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


def promote_calibration(
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
        ``{"source": str, "current_path": str, "archived_previous": str | None}``
        with absolute path strings.

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
            "No staging config to promote. Review the report. The "
            "measurement may have failed validation or weak voting."
        )

    data = json.loads(source.read_text(encoding="utf-8"))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"staging config has unexpected schema_version "
            f"{data.get('schema_version')!r}; expected {SCHEMA_VERSION}"
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
            f"but the file declares kind {kind!r}; refusing to promote a "
            "mismatched pair."
        )

    # absolute(), not resolve(): keep the operator's drive letter intact.
    resolved_root = Path(current_root).absolute()
    resolved_current = resolved_root / staging_name
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

    archived: Path | None = None
    if resolved_current.exists():
        try:
            existing = json.loads(resolved_current.read_text(encoding="utf-8"))
            stamp_raw = existing.get("created_at", "unknown")
        except Exception:
            stamp_raw = "unknown"
        stamp = _sanitize_stamp(stamp_raw)
        # Counter-based collision avoidance. now_iso() is second-precision
        # and fast reruns / tests would otherwise overwrite an archive.
        candidate = archive_dir / f"{stamp}_{staging_name}"
        i = 1
        while candidate.exists():
            candidate = archive_dir / f"{stamp}_{i}_{staging_name}"
            i += 1
        archived = candidate
        shutil.copy2(resolved_current, archived)

    write_json_atomic(resolved_current, data)

    session_id = getattr(session, "session_id", "unknown")
    log_path = resolved_root / ".promotion.log"
    line = f"{now_iso()} {kind} {session_id} -> {resolved_current}\n"
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(line)

    return {
        "source": str(source),
        "current_path": str(resolved_current),
        "archived_previous": str(archived) if archived else None,
    }

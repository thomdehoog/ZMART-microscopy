"""Setup sessions: one operator's pass through the workflow, kept so it can be reopened.

A session is a folder holding the four documents -- limits, orientation,
calibration, origin -- as they stood when the operator last adopted them,
with a name and two timestamps. Opening a session later brings every step
back to what it held, so a setup can be reviewed and edited rather than
redone. Sessions are kept beside the driver's own published snapshots, under
a folder the driver names (see the optional ``home`` op), so the record of
how a machine was set up lives with the machine.

Nothing here knows which microscope a session is for. The documents are
whatever the driver published, stored as they were.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

#: The file a session keeps inside its folder.
SESSION_FILENAME = "session.json"

_ID_FORMAT = "%Y-%m-%dT%H-%M-%S-%fZ"
_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{6}Z$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _write(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")


def _summary(record: dict) -> dict:
    """The part of a session a list shows: its id, name, when, and which
    documents it holds."""
    return {
        "id": record["id"],
        "name": record.get("name") or record["id"],
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "subsystems": sorted((record.get("documents") or {}).keys()),
    }


def list_sessions(root: Path) -> list[dict]:
    """Every session under ``root``, newest first."""
    root = Path(root)
    if not root.is_dir():
        return []
    found = []
    for folder in root.iterdir():
        if not (folder.is_dir() and _ID_RE.match(folder.name)):
            continue
        try:
            record = json.loads((folder / SESSION_FILENAME).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        record.setdefault("id", folder.name)
        found.append(_summary(record))
    found.sort(key=lambda s: s["id"], reverse=True)
    return found


def create_session(root: Path, name: str | None, documents: dict) -> dict:
    """A new session holding ``documents`` (subsystem name to document). A
    session is known by the moment it was started; ``name`` is kept for a
    caller that has one, and is otherwise that moment."""
    moment = _now()
    session_id = moment.strftime(_ID_FORMAT)
    stamp = moment.isoformat()
    record = {
        "id": session_id,
        "name": (name or "").strip() or moment.strftime("Session %Y-%m-%d %H:%M"),
        "created_at": stamp,
        "updated_at": stamp,
        "documents": {key: value for key, value in (documents or {}).items() if isinstance(value, dict)},
    }
    _write(Path(root) / session_id / SESSION_FILENAME, record)
    return record


def open_session(root: Path, session_id: str) -> dict:
    """The full record of one session, documents included."""
    if not _ID_RE.match(session_id or ""):
        raise ValueError(f"not a session id: {session_id!r}")
    path = Path(root) / session_id / SESSION_FILENAME
    if not path.is_file():
        raise ValueError(f"no session {session_id}")
    record = json.loads(path.read_text(encoding="utf-8"))
    record.setdefault("id", session_id)
    record.setdefault("documents", {})
    return record


def record_document(root: Path, session_id: str, subsystem: str, document: dict) -> dict:
    """Keep ``document`` as the session's ``subsystem``, and note when."""
    record = open_session(root, session_id)
    record["documents"][subsystem] = dict(document)
    record["updated_at"] = _now().isoformat()
    _write(Path(root) / session_id / SESSION_FILENAME, record)
    return record

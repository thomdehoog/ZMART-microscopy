"""The protocols: the settings a run ran with, written beside it, and the ones saved by name.

A finished run leaves ``protocol.json`` beside its pictures; the next
session lists every one under the machine's output root and can open on
it. Protocols saved on purpose live in the computer's ZMART folder, so they
outlive any one run's folder.

Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from zmart_controller.registry import config_root

from . import state

#: What a run of this workflow is called on disk: ``target-acquisition_<hash>``.
#: The page names it when it connects (the bridge makes the run folder), and
#: the protocols of earlier runs are found by it, so it never changes: runs
#: and protocols saved before still have to be found.
EXPERIMENT = "target-acquisition"


#: What a finished run leaves beside its pictures: the settings it ran with,
#: as the page wrote them. The next session lists these and opens on one.
PROTOCOL_FILE = "protocol.json"


#: And the protocols saved on purpose, by name, for this machine. They live
#: in the computer's ZMART folder, beside what the controller and the drivers
#: keep there (``C:\ProgramData\zmart-microscopy`` on Windows, or wherever
#: ``ZMART_MICROSCOPY_ROOT`` points), under ``zmart-interface\protocols``, so a
#: saved protocol outlives any one run's folder. ``ZMART_PROTOCOL_LIBRARY``
#: names another folder outright.
PROTOCOL_LIBRARY = Path(
    os.environ.get("ZMART_PROTOCOL_LIBRARY")
    or config_root() / "zmart-interface" / "protocols"
)


def library_protocols() -> list:
    if not PROTOCOL_LIBRARY.is_dir():
        return []
    found = []
    for path in PROTOCOL_LIBRARY.glob("*.json"):
        try:
            protocol = json.loads(path.read_text(encoding="utf-8"))
            written = path.stat().st_mtime
        except (OSError, ValueError):
            continue
        found.append({"id": path.stem, "written": written, "protocol": protocol, "saved": True})
    return found


def save_protocol_to_library(asked: dict) -> dict:
    """Write the settings into the library under the name given, or the time."""
    protocol = asked.get("protocol")
    if not isinstance(protocol, dict):
        raise ValueError("the protocol must be the run's settings, as an object")
    name = str(asked.get("name") or "").strip()
    safe = "".join(ch if ch.isalnum() or ch in "-_ ." else "_" for ch in name).strip() or time.strftime("%Y-%m-%d_%H-%M-%S")
    PROTOCOL_LIBRARY.mkdir(parents=True, exist_ok=True)
    path = PROTOCOL_LIBRARY / f"{safe}.json"
    path.write_text(json.dumps(protocol, indent=2), encoding="utf-8")
    return {"written": str(path), "id": path.stem}


def protocols(connection: dict | None = None) -> dict:
    """Every protocol under the machine's output root, newest first, settings inline.

    With a session open the root is the run folder's parent. Before one,
    the folder the interface was started with (``--output-root``), where it
    puts its runs; a driver's own entry is never read for it. Without that
    folder the library alone is listed. A file that does not parse is left
    out rather than failing the list -- one damaged run must not hide the
    others. ``connection`` is the chosen instrument's entry, accepted so the
    page can ask the same way before and after connecting.
    """
    if state.run is not None:
        root = state.run.parent
    elif state.output_root is not None:
        root = Path(state.output_root)
    else:
        root = None
    found = library_protocols()
    if root is None or not root.is_dir():
        found.sort(key=lambda one: one["written"], reverse=True)
        return {"protocols": found}
    for path in root.glob(f"{EXPERIMENT}_*/{PROTOCOL_FILE}"):
        try:
            protocol = json.loads(path.read_text(encoding="utf-8"))
            written = path.stat().st_mtime
        except (OSError, ValueError):
            continue
        found.append({"id": path.parent.name, "written": written, "protocol": protocol})
    found.sort(key=lambda one: one["written"], reverse=True)
    return {"protocols": found}


def save_protocol(asked: dict) -> dict:
    """Write the run's settings into the run folder, replacing an earlier write."""
    if state.run is None:
        raise RuntimeError("no session is open, so there is no run folder to write the protocol into")
    protocol = asked.get("protocol")
    if not isinstance(protocol, dict):
        raise ValueError("the protocol must be the run's settings, as an object")
    path = state.run / PROTOCOL_FILE
    path.write_text(json.dumps(protocol, indent=2), encoding="utf-8")
    return {"written": str(path)}

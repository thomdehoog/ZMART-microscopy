"""
Machine-local files for one Nikon microscope.
=============================================
The frame origin an operator sets with ``set_origin`` should survive closing
and reopening ZMART, so it is written to a small JSON file in a machine-wide
folder::

    C:\\ProgramData\\zmart-microscopy\\nikon\\<microscope_id>\\origin.json

The root can be moved with the ``ZMART_MICROSCOPY_ROOT`` environment variable
or a ``machine_root`` key in the connection dict (tests use a temp folder).
No admin rights are needed: ordinary users can write under ProgramData
subfolders they create.

Author: Thom de Hoog (ZMB, University of Zurich)
        thom.dehoog@zmb.uzh.ch . thomdehoog@gmail.com
License: MIT
"""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_PROGRAMDATA_ROOT = Path(r"C:\ProgramData\zmart-microscopy")
VENDOR_DIR = "nikon"
ORIGIN_FILENAME = "origin.json"


def _atomic_write_json(path: Path, payload: dict) -> None:
    """Write the file completely or not at all, so a crash never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)


class MachineProfile:
    """Where this microscope's machine-local files live."""

    def __init__(
        self, microscope_id: str, programdata_root: str | os.PathLike | None = None
    ) -> None:
        self.microscope_id = microscope_id
        self._root = Path(programdata_root) if programdata_root else None

    def root(self) -> Path:
        if self._root is not None:
            return self._root
        env = os.environ.get("ZMART_MICROSCOPY_ROOT")
        return Path(env) if env else DEFAULT_PROGRAMDATA_ROOT

    def machine_dir(self) -> Path:
        return self.root() / VENDOR_DIR / self.microscope_id

    def read_origin(self) -> dict | None:
        """The persisted origin payload, or None when none was saved yet."""
        path = self.machine_dir() / ORIGIN_FILENAME
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def write_origin(self, payload: dict) -> Path:
        path = self.machine_dir() / ORIGIN_FILENAME
        _atomic_write_json(path, payload)
        return path
